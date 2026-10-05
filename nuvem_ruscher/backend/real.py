"""Backend real: executa comandos, chama o helper via pkexec e fala com a API."""

from __future__ import annotations

import getpass
import glob
import os
import pwd
import shutil
import urllib.request
from collections.abc import Callable
from pathlib import Path

from nuvem_ruscher.async_utils import Operation, StreamingProcess
from nuvem_ruscher.backend.base import (
    Backend,
    BackupFile,
    Defaults,
    HelperDoneCallback,
    HelperEventCallback,
    HelperResult,
    StorageReport,
    version_from_backup_name,
)
from nuvem_ruscher.constants import (
    CONNECTIVITY_URL,
    CONTAINER_SERVER,
    CONTAINERS,
    GITHUB_RELEASES_API,
    IMMICH_PORT,
    RELEASE_DOWNLOAD,
    SERVICE_NAME,
    STACK_DIR,
)
from nuvem_ruscher.core import docker as dk
from nuvem_ruscher.core import fstab, storage, system
from nuvem_ruscher.core.compose import PullProgress, pull_args, write_pull_plan
from nuvem_ruscher.core.config import ApiKeyStore, AppConfig, UserState, cache_dir, load_conf
from nuvem_ruscher.core.helper_protocol import parse_line, pkexec_error_code
from nuvem_ruscher.core.immich_api import ImmichClient, ServerStats
from nuvem_ruscher.core.releases import Release, ReleaseCache, parse_releases
from nuvem_ruscher.core.validation import ValidationError, validate_photo_path
from nuvem_ruscher.paths import helper_path


class HelperCall(Operation):
    """Executa uma ação do helper via pkexec e junta o resultado."""

    def __init__(
        self,
        argv: list[str],
        on_event: HelperEventCallback | None,
        on_done: HelperDoneCallback,
    ) -> None:
        self.result = HelperResult(ok=False)
        self._on_event = on_event
        self._on_done = on_done
        self._proc = StreamingProcess(argv, self._line, self._exit)

    @property
    def running(self) -> bool:
        return self._proc.running

    def cancel(self) -> None:
        self._proc.cancel()

    def _line(self, line: str) -> None:
        event = parse_line(line)
        self.result.log.append(line)
        if event.kind == "result":
            self.result.results[event.key] = event.value
        elif event.kind == "error":
            self.result.error_code = event.key
            self.result.error_detail = event.value
        if self._on_event:
            self._on_event(event)

    def _exit(self, code: int) -> None:
        pk = pkexec_error_code(code)
        if pk and not self.result.error_code:
            self.result.error_code = pk
        self.result.ok = code == 0 and not self.result.error_code
        if not self.result.ok and not self.result.error_code:
            self.result.error_code = "internal"
            self.result.error_detail = f"exit code {code}"
        self._on_done(self.result)


class _Finished(Operation):
    running = False

    def cancel(self) -> None:
        pass


class RealBackend(Backend):
    simulated = False

    def __init__(self) -> None:
        self._user = getpass.getuser()
        self._state = UserState()
        self._keys = ApiKeyStore()
        self._api = ImmichClient(f"http://127.0.0.1:{IMMICH_PORT}")
        self._release_cache = ReleaseCache(cache_dir() / "releases.json")

    # --- básico -------------------------------------------------------------------
    def user_name(self) -> str:
        return self._user

    def load_config(self) -> AppConfig:
        return load_conf()

    def docker_access(self) -> dk.GroupAccess:
        return dk.docker_group_access(self._user)

    def _docker(self, args: list[str]) -> list[str]:
        return dk.docker_argv(args, self.docker_access())

    def _run_docker(self, args: list[str], timeout: float = 15) -> tuple[int, str]:
        return system.run_text(self._docker(args), timeout=timeout)

    def state_get(self, key: str, default: object = None) -> object:
        return self._state.get(key, default)

    def state_set(self, key: str, value: object) -> None:
        self._state.set(key, value)

    # --- fatos ----------------------------------------------------------------------
    def fact_docker(self) -> tuple[bool, str, bool]:
        if not shutil.which("docker"):
            return False, "", False
        code, out = system.run_text(["docker", "--version"])
        version = out.split("version", 1)[1].split(",", 1)[0].strip() if code == 0 and "version" in out else "?"
        compose = any(
            os.path.exists(p)
            for p in (
                "/usr/lib/docker/cli-plugins/docker-compose",
                "/usr/libexec/docker/cli-plugins/docker-compose",
            )
        ) or bool(glob.glob(os.path.expanduser("~/.docker/cli-plugins/docker-compose")))
        running = system.unit_active_state("docker.service") == "active" or (
            system.unit_active_state("docker.socket") == "active"
        )
        return compose, version, running

    def fact_memory(self) -> int:
        return system.mem_total()

    def fact_cpu(self) -> tuple[int, bool]:
        return system.cpu_info()

    def fact_docker_free(self) -> int:
        return system.free_bytes("/var/lib/docker")

    def fact_port(self) -> tuple[system.PortStatus, bool]:
        status = system.port_status(IMMICH_PORT)
        if status.free:
            return status, False
        ours = any(c.name == CONTAINER_SERVER and c.running for c in self.containers())
        return status, ours

    def fact_internet(self) -> bool:
        return system.check_internet(CONNECTIVITY_URL)

    def fact_firewall(self) -> str:
        return system.firewall_info().name

    # --- armazenamento ------------------------------------------------------------------
    def suggest_photo_path(self) -> str:
        conf = self.load_config()
        if conf.upload_location:
            return conf.upload_location
        base = f"/run/media/{self._user}"
        mounts: list[tuple[str, int]] = []
        try:
            for entry in sorted(os.listdir(base)):
                path = os.path.join(base, entry)
                if os.path.ismount(path):
                    mounts.append((path, system.free_bytes(path)))
        except OSError:
            pass
        suggestion = storage.suggest_photo_folder(self._user, mounts)
        return suggestion or os.path.join(os.path.expanduser("~"), "Imagens", "Immich")

    def inspect_storage(self, path: str) -> StorageReport:
        report = StorageReport(path=path)
        try:
            path = validate_photo_path(path)
        except ValidationError as exc:
            report.error = str(exc)
            return report
        report.path = path
        probe = path if os.path.isdir(path) else os.path.dirname(path)
        if not os.path.isdir(probe):
            report.disk_missing = True
            return report
        code, out = system.run_text(["findmnt", "-J", "-T", probe, "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"])
        if code != 0:
            report.disk_missing = True
            return report
        mount = storage.parse_findmnt(out)
        cols = "NAME,PATH,UUID,LABEL,FSTYPE,SIZE,FSAVAIL,FSUSED,MOUNTPOINTS,RM,HOTPLUG,ROTA,TRAN,MODEL,PKNAME"
        part: dict[str, object] = {}
        parent: dict[str, object] = {}
        if mount.source.startswith("/dev/"):
            code, out = system.run_text(["lsblk", "-J", "-b", "-o", cols, mount.source])
            part = storage.parse_lsblk(out) if code == 0 else {}
            pkname = str(part.get("pkname") or "")
            if pkname:
                code, out = system.run_text(
                    [
                        "lsblk",
                        "-J",
                        "-b",
                        "-d",
                        "-o",
                        "NAME,PATH,RM,HOTPLUG,ROTA,TRAN,MODEL,VENDOR,SIZE",
                        f"/dev/{pkname}",
                    ]
                )
                parent = storage.parse_lsblk(out) if code == 0 else {}
        code, out = system.run_text(["findmnt", "-n", "--nofsroot", "-o", "SOURCE", "/"])
        system_sources = frozenset({out.strip()}) if code == 0 else frozenset()
        volume = storage.build_volume(path, mount, part, parent, system_sources)
        if not volume.size:
            total, used, free = system.disk_usage(volume.mountpoint)
            volume.size, volume.used, volume.available = total, used, free
        report.volume = volume
        report.warnings = storage.fs_warnings(volume)
        report.library = storage.detect_library(path)
        if volume.needs_boot_mount and volume.uuid:
            try:
                entries = fstab.parse_fstab(Path("/etc/fstab").read_text())
            except OSError:
                entries = []
            found = fstab.find_entry(entries, volume.uuid, volume.mountpoint)
            if found is not None:
                try:
                    ours = fstab.is_ours(Path("/etc/fstab").read_text(), volume.uuid)
                except OSError:
                    ours = False
                report.fstab_state = "ours" if ours else "foreign"
            pw = pwd.getpwnam(self._user)
            try:
                report.fstab_preview = fstab.fstab_line(
                    volume.uuid, volume.mountpoint, volume.fstype, pw.pw_uid, pw.pw_gid
                )
            except ValueError:
                report.fstab_state = "unsupported" if found is None else report.fstab_state
        return report

    def defaults(self) -> Defaults:
        cores, v2 = system.cpu_info()
        del cores
        return Defaults(
            timezone=system.system_timezone(),
            timezones=system.list_timezones(),
            gpu=system.detect_gpu(),
            ram=system.mem_total(),
            cpu_v2=v2,
        )

    def releases(self, force: bool = False) -> list[Release]:
        text = None if force else self._release_cache.get()
        if text is None:
            request = urllib.request.Request(
                GITHUB_RELEASES_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "nuvem-ruscher"},
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    text = response.read().decode()
                self._release_cache.put(text)
            except OSError:
                text = self._release_cache.get_stale()
                if text is None:
                    raise
        return parse_releases(text)

    def download_compose(self, version: str) -> str:
        url = RELEASE_DOWNLOAD.format(tag=version, name="docker-compose.yml")
        request = urllib.request.Request(url, headers={"User-Agent": "nuvem-ruscher"})
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode()
        if "name: immich" not in text or "${UPLOAD_LOCATION}:/data" not in text:
            raise ValueError("docker-compose.yml has an unexpected format")
        return text

    # --- helper ----------------------------------------------------------------------
    def helper(
        self,
        action: str,
        args: list[str],
        on_event: HelperEventCallback | None,
        on_done: HelperDoneCallback,
    ) -> Operation:
        helper = str(helper_path())
        if not os.access(helper, os.X_OK):
            on_done(HelperResult(False, "helper-missing", f"{helper} not found"))
            return _Finished()
        return HelperCall(["pkexec", helper, action, *args], on_event, on_done)

    # --- Docker ------------------------------------------------------------------------
    def pull(
        self,
        on_progress: Callable[[PullProgress, str], None],
        on_done: Callable[[bool, PullProgress], None],
        version: str | None = None,
        compose_text: str | None = None,
    ) -> Operation:
        conf = self.load_config()
        stack = Path(STACK_DIR)
        compose = compose_text or (stack / "docker-compose.yml").read_text()
        override = (stack / "docker-compose.override.yml").read_text()
        env = {
            "UPLOAD_LOCATION": conf.upload_location,
            "DB_DATA_LOCATION": conf.db_data_location or f"{STACK_DIR}/postgres",
            "TZ": conf.timezone or "Etc/UTC",
            "IMMICH_VERSION": version or conf.immich_version,
            "DB_USERNAME": "postgres",
            "DB_DATABASE_NAME": "immich",
        }
        plan = write_pull_plan(cache_dir() / "plano", compose, override, env)
        progress = PullProgress()

        def line(text: str) -> None:
            progress.feed(text)
            on_progress(progress, text)

        def done(code: int) -> None:
            ok = code == 0 and not progress.errors
            if ok:
                progress.finish()
            on_done(ok, progress)

        return StreamingProcess(self._docker(pull_args(plan)), line, done)

    def service_state(self) -> str:
        return system.unit_active_state(SERVICE_NAME)

    def containers(self) -> list[dk.ContainerState]:
        code, out = self._run_docker(dk.ps_args())
        return dk.parse_ps(out.splitlines()) if code == 0 else []

    def stats(self) -> dict[str, dk.ContainerStats]:
        running = [c.name for c in self.containers() if c.running]
        if not running:
            return {}
        code, out = self._run_docker(dk.stats_args(running), timeout=20)
        return dk.parse_stats(out.splitlines()) if code == 0 else {}

    def watch_events(self, on_event: Callable[[str], None], on_exit: Callable[[int], None]) -> Operation:
        return StreamingProcess(self._docker(dk.events_args()), on_event, on_exit)

    def follow_logs(self, container: str, on_line: Callable[[str], None], on_exit: Callable[[int], None]) -> Operation:
        if container not in CONTAINERS:
            raise ValueError(container)
        return StreamingProcess(self._docker(dk.logs_args(container)), on_line, on_exit)

    # --- API --------------------------------------------------------------------------------
    def ping(self) -> bool:
        return self._api.ping()

    def server_version(self) -> str:
        return self._api.version()

    def is_initialized(self) -> bool:
        return self._api.is_initialized()

    def create_admin(
        self, name: str, email: str, password: str, want_key: bool, transcode: str, ml_enabled: bool
    ) -> None:
        self._api.admin_sign_up(name, email, password)
        token = self._api.login(email, password)
        try:
            if want_key:
                self._keys.save(self._api.create_stats_key(token))
            try:
                self._api.apply_initial_settings(token, transcode, ml_enabled)
            except Exception:
                self.state_set("initial_settings_pending", True)
        finally:
            self._api.logout(token)

    def connect_stats(self, email: str, password: str) -> None:
        token = self._api.login(email, password)
        try:
            self._keys.save(self._api.create_stats_key(token))
        finally:
            self._api.logout(token)

    def has_stats_key(self) -> bool:
        return self._keys.load() is not None

    def statistics(self) -> ServerStats | None:
        key = self._keys.load()
        if not key:
            return None
        return self._api.statistics(key)

    # --- diversos --------------------------------------------------------------------------
    def backups(self) -> list[BackupFile]:
        conf = self.load_config()
        if not conf.upload_location:
            return []
        base = Path(conf.upload_location) / "backups"
        found: list[BackupFile] = []
        for folder, automatic in ((base, True), (base / "nuvem-ruscher", False)):
            try:
                entries = list(folder.iterdir())
            except OSError:
                continue
            for entry in entries:
                if not entry.name.endswith(".sql.gz") or not entry.is_file():
                    continue
                st = entry.stat()
                found.append(
                    BackupFile(
                        str(entry),
                        entry.name,
                        st.st_size,
                        st.st_mtime,
                        automatic,
                        version_from_backup_name(entry.name),
                    )
                )
        return sorted(found, key=lambda b: b.mtime, reverse=True)

    def lan_ip(self) -> str:
        return system.lan_ip()

    def tailscale(self) -> system.TailscaleInfo:
        return system.tailscale_info()

    def disk_usage(self, path: str) -> tuple[int, int, int]:
        return system.disk_usage(path)

    def is_mounted(self, path: str) -> bool:
        return system.is_mountpoint(path)
