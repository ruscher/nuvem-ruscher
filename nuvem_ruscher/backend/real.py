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
from nuvem_ruscher.core import disks as dsk
from nuvem_ruscher.core import docker as dk
from nuvem_ruscher.core import fstab, migration, raid, storage, system
from nuvem_ruscher.core.compose import PullProgress, pull_args, write_pull_plan
from nuvem_ruscher.core.config import ApiKeyStore, AppConfig, UserState, cache_dir, load_conf
from nuvem_ruscher.core.helper_protocol import parse_line, pkexec_error_code
from nuvem_ruscher.core.immich_api import Album, ApiError, ImmichClient, ImmichUser, Person, ServerStats, Session
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
        interactive: bool = False,
    ) -> None:
        self.result = HelperResult(ok=False)
        self._on_event = on_event
        self._on_done = on_done
        self._interactive = interactive
        self._proc = StreamingProcess(argv, self._line, self._exit, interactive=interactive)

    @property
    def running(self) -> bool:
        return self._proc.running

    def cancel(self) -> None:
        # O helper roda como root: não dá para sinalizá-lo. Ele lê o pedido no stdin e só
        # cancela quando ainda é seguro (ex.: durante a cópia, com o servidor no ar).
        if self._interactive:
            self._proc.send("cancel")
        else:
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
        self._session: Session | None = None

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
        interactive: bool = False,
    ) -> Operation:
        helper = str(helper_path())
        if not os.access(helper, os.X_OK):
            on_done(HelperResult(False, "helper-missing", f"{helper} not found"))
            return _Finished()
        return HelperCall(["pkexec", helper, action, *args], on_event, on_done, interactive=interactive)

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

    def probe_server(self, url: str) -> bool:
        return ImmichClient(url, timeout=4).ping()

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

    # --- contas e compartilhamento ------------------------------------------------------------
    @property
    def session(self) -> Session | None:
        return self._session

    def _token(self, admin: bool = False) -> str:
        if self._session is None:
            raise PermissionError("not signed in")
        if admin and not self._session.is_admin:
            raise PermissionError("not an administrator")
        return self._session.token

    def sign_in(self, email: str, password: str) -> Session:
        self.sign_out()
        self._session = self._api.session(email, password)
        return self._session

    def sign_out(self) -> None:
        if self._session is not None:
            self._api.logout(self._session.token)
            self._session = None

    def accounts(self) -> list[ImmichUser]:
        token = self._token(admin=True)
        users = self._api.admin_users(token)
        try:
            usage = self._api.usage_by_user(token)
        except ApiError:
            usage = {}
        for user in users:
            photos, videos, _bytes = usage.get(user.id, (0, 0, 0))
            user.photos, user.videos = photos, videos
        return users

    def create_account(
        self, name: str, email: str, password: str, quota: int | None, storage_label: str | None, is_admin: bool
    ) -> ImmichUser:
        return self._api.create_user(self._token(admin=True), name, email, password, quota, storage_label, is_admin)

    def update_account(self, user_id: str, **changes: object) -> ImmichUser:
        return self._api.update_user(self._token(admin=True), user_id, **changes)

    def reset_account_password(self, user_id: str) -> str:
        return self._api.reset_password(self._token(admin=True), user_id)

    def disable_account(self, user_id: str) -> ImmichUser:
        return self._api.disable_user(self._token(admin=True), user_id)

    def restore_account(self, user_id: str) -> ImmichUser:
        return self._api.restore_user(self._token(admin=True), user_id)

    def people(self) -> list[Person]:
        return self._api.people(self._token())

    def shared_albums(self) -> tuple[list[Album], list[Album]]:
        token = self._token()
        return self._api.albums(token, owned=True, shared=True), self._api.albums(token, owned=False)

    def create_shared_album(self, name: str, members: list[tuple[str, str]]) -> Album:
        return self._api.create_album(self._token(), name, members)

    def add_album_members(self, album_id: str, members: list[tuple[str, str]]) -> Album:
        return self._api.add_album_members(self._token(), album_id, members)

    def set_album_role(self, album_id: str, user_id: str, role: str) -> None:
        self._api.set_album_role(self._token(), album_id, user_id, role)

    def remove_album_member(self, album_id: str, user_id: str) -> None:
        self._api.remove_album_member(self._token(), album_id, user_id)

    def partners(self) -> tuple[list[Person], list[Person]]:
        token = self._token()
        return self._api.partners(token, "shared-by"), self._api.partners(token, "shared-with")

    def add_partner(self, user_id: str) -> None:
        self._api.add_partner(self._token(), user_id)

    def remove_partner(self, user_id: str) -> None:
        self._api.remove_partner(self._token(), user_id)

    # --- discos, RAID e troca de local -----------------------------------------------------------
    def disks(self) -> list[dsk.Disk]:
        code, out = system.run_text(list(dsk.LSBLK_ARGV), timeout=20)
        if code != 0:
            return []
        try:
            swaps = dsk.parse_swaps(Path("/proc/swaps").read_text())
        except OSError:
            swaps = set()
        conf = self.load_config()
        lsblk = dsk.parse_lsblk(out)
        names = [d.get("name", "") for d in lsblk.get("blockdevices") or [] if d.get("type") == "disk"]
        return dsk.inventory(
            lsblk,
            swaps=swaps,
            by_id=dsk.stable_ids(dsk.read_by_id()),
            protected={
                "cloud": conf.upload_location,
                "old-copy": conf.raw.get("OLD_UPLOAD_LOCATION", ""),
                "database": conf.db_data_location or "/var/lib/nuvem-ruscher",
                "docker": "/var/lib/docker",
            },
            holders_of={name: dsk.holders(name) for name in names},
            photos=dsk.photo_tags(conf.raw),
            fstab=dsk.fstab_tags(self._fstab_sources()),
        )

    @staticmethod
    def _fstab_sources() -> list[str]:
        try:
            return [entry.source for entry in fstab.parse_fstab(Path("/etc/fstab").read_text(encoding="utf-8"))]
        except OSError:
            return []

    def raid_arrays(self) -> list[raid.RaidArray]:
        return raid.read_arrays()

    def tool_available(self, name: str) -> bool:
        if name not in ("rsync", "mdadm", "smartctl"):
            raise ValueError(name)
        return bool(shutil.which(name) or shutil.which(name, path="/usr/bin:/usr/sbin:/bin:/sbin"))

    def plan_migration(self, dest: str, mode: migration.Mode | None = None) -> migration.MigrationPlan:
        conf = self.load_config()
        source = conf.upload_location
        stats = migration.scan_tree(source) if source and os.path.isdir(source) else migration.TreeStats()
        return migration.assess(source, dest, stats, self._destination(source, dest), mode)

    def _destination(self, source: str, dest: str) -> migration.Destination:
        info = migration.Destination(path=dest)
        dest = os.path.normpath(dest) if dest.startswith("/") else dest
        parent = os.path.dirname(dest)
        info.parent_exists = os.path.isdir(parent)
        if not info.parent_exists:
            return info
        info.symlink_in_path = os.path.realpath(parent) != parent or os.path.islink(dest)
        info.exists = os.path.lexists(dest)
        info.is_dir = os.path.isdir(dest)
        probe = dest if info.is_dir else parent
        if info.is_dir:
            try:
                entries = [e for e in os.listdir(dest) if e != migration.MIGRATION_MARKER]
            except OSError:
                entries = ["?"]
            info.empty = not entries
            info.markers = {f for f in migration.IMMICH_FOLDERS if os.path.isfile(os.path.join(dest, f, ".immich"))}
            if info.markers:
                info.files = migration.scan_tree(dest).files
            try:
                marker = Path(dest, migration.MIGRATION_MARKER).read_text(encoding="utf-8").splitlines()
                if marker and marker[0].startswith("SOURCE="):
                    info.resumable_from = marker[0].split("=", 1)[1]
            except OSError:
                pass
        code, out = system.run_text(["findmnt", "-J", "-T", probe, "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"])
        if code == 0:
            mount = storage.parse_findmnt(out)
            info.mountpoint = mount.target
            info.fstype = mount.fstype
            info.read_only = "ro" in mount.options
        report = self.inspect_storage(dest)
        if report.volume is not None:
            info.fstype = report.volume.fstype or info.fstype
            info.removable = report.volume.is_external
            info.system_disk = report.volume.is_system_disk
        total, _used, free = system.disk_usage(probe)
        info.total, info.free = total, free
        if source and os.path.isdir(source):
            try:
                same_dev = os.stat(source).st_dev == os.stat(probe).st_dev
            except OSError:
                same_dev = False
            code, out = system.run_text(["findmnt", "-n", "-o", "TARGET", "-T", source])
            info.same_fs = same_dev and code == 0 and out.strip() == info.mountpoint
        return info

    def migration_state(self) -> migration.MigrationState | None:
        return migration.read_state()

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
