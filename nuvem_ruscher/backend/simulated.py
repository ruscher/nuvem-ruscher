"""Backend simulado (``--simular``): finge todas as operações de sistema.

Nada aqui toca no sistema: não chama pkexec, docker, systemctl nem grava em /etc.
O estado do usuário fica só em memória. Os cenários reproduzem a matriz de testes
de docs/06-testes-e-qa.md.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from dataclasses import replace

from gi.repository import GLib

from nuvem_ruscher.async_utils import Operation
from nuvem_ruscher.backend.base import (
    KNOWN_GOOD_VERSION,
    Backend,
    BackupFile,
    Defaults,
    HelperDoneCallback,
    HelperEventCallback,
    HelperResult,
    StorageReport,
)
from nuvem_ruscher.constants import CONTAINERS, STACK_DIR
from nuvem_ruscher.core import fstab, storage
from nuvem_ruscher.core.compose import PullProgress
from nuvem_ruscher.core.config import AppConfig
from nuvem_ruscher.core.docker import ContainerState, ContainerStats, GroupAccess, Health
from nuvem_ruscher.core.helper_protocol import HelperEvent
from nuvem_ruscher.core.immich_api import ApiError, ServerStats
from nuvem_ruscher.core.releases import Release
from nuvem_ruscher.core.system import GIB, GpuInfo, PortStatus, TailscaleInfo
from nuvem_ruscher.core.validation import ValidationError, validate_photo_path

SCENARIOS: dict[str, dict[str, object]] = {
    "feliz": {},
    "instalado": {"installed": True, "initialized": True},
    "atualizacao": {"installed": True, "initialized": True, "version": "v3.0.3"},
    "atualizacao-falha": {"installed": True, "initialized": True, "version": "v3.0.3", "update_fail": True},
    "sem-docker": {"docker_installed": False, "docker_running": False, "group": GroupAccess.NO_GROUP},
    "docker-parado": {"docker_running": False},
    "sem-grupo": {"group": GroupAccess.MISSING},
    "grupo-pendente": {"group": GroupAccess.PENDING},
    "disco-ausente": {"disk": False},
    "ntfs": {},
    "fat32": {"fstype": "vfat"},
    "ext4": {"fstype": "ext4"},
    "porta-ocupada": {"port_busy": True},
    "sem-internet": {"internet": False},
    "pouca-ram": {"ram_gib": 5},
    "biblioteca-existente": {"library": True, "initialized": True},
    "falha-download": {"pull_fail": True},
    "lento": {"slow": True},
    "firewall": {"firewall": "ufw"},
    "fstab-configurado": {"fstab": "ours"},
}

SCENARIO_HELP = {
    "feliz": "primeira instalação, tudo certo (padrão)",
    "instalado": "abre direto no painel",
    "atualizacao": "painel com atualização disponível (com mudanças incompatíveis)",
    "atualizacao-falha": "atualização que falha e volta sozinha",
    "sem-docker": "Docker ausente",
    "docker-parado": "Docker instalado, mas desligado",
    "sem-grupo": "usuário fora do grupo docker",
    "grupo-pendente": "acabou de entrar no grupo docker (sessão antiga)",
    "disco-ausente": "disco das fotos desconectado",
    "ntfs": "disco NTFS (como nesta máquina)",
    "fat32": "disco FAT32 (limite de 4 GB)",
    "ext4": "disco ext4 (sem avisos)",
    "porta-ocupada": "porta 2283 ocupada",
    "sem-internet": "sem internet",
    "pouca-ram": "5 GB de memória",
    "biblioteca-existente": "reinstalação com fotos e conta existentes",
    "falha-download": "download das imagens falha no meio",
    "lento": "servidor demora a ficar pronto",
    "firewall": "firewall ufw ativo",
    "fstab-configurado": "montagem automática já configurada",
}

FAKE_RELEASES = [
    (
        "v3.2.4",
        "2026-09-28",
        "## What's Changed\n### 🐛 Bug fixes\n* fix(mobile): sync status page goes blank",
    ),
    (
        "v3.2.2",
        "2026-09-15",
        "## What's Changed\n### 🐛 Bug fixes\n* fix(server): memory leak in thumbnail job",
    ),
    ("v3.2.0", "2026-09-10", "## Highlights\n* Novo editor de álbuns\n* Busca por texto nas fotos (OCR)"),
    (
        "v3.1.0",
        "2026-07-29",
        "## Highlights\n* Pastas compartilhadas\n### 🚨 Breaking Changes\n"
        "* A variável `IMMICH_MEDIA_LOCATION` foi removida; use `UPLOAD_LOCATION`.",
    ),
    ("v3.0.3", "2026-07-15", "## What's Changed\n* fix: várias correções"),
]

LOG_LINES = [
    "[Nest] 7  - {ts}     LOG [Microservices:MetadataService] Processando metadados de IMG_{n}.jpg",
    "[Nest] 7  - {ts}     LOG [Microservices:MediaService] Miniatura gerada para IMG_{n}.jpg",
    "[Nest] 7  - {ts}     LOG [Api:LoggingInterceptor] GET /api/server/ping 200 1.2ms",
    "[Nest] 7  - {ts}    WARN [Microservices:JobService] Fila de miniaturas com {n} itens",
    "[Nest] 7  - {ts}     LOG [Api:AssetService] Upload recebido de Pixel 8 (IMG_{n}.jpg)",
    "[Nest] 7  - {ts}   ERROR [Microservices:MetadataService] Não foi possível ler EXIF de VID_{n}.mp4",
]


class _Timeline(Operation):
    """Sequência de passos com atrasos, cancelável."""

    def __init__(
        self, steps: list[tuple[int, Callable[[], None]]], on_cancel: Callable[[], None] | None = None
    ) -> None:
        self._steps = list(steps)
        self._source = 0
        self._running = True
        self._on_cancel = on_cancel
        self._next()

    @property
    def running(self) -> bool:
        return self._running

    def _next(self) -> None:
        if not self._steps:
            self._running = False
            return
        delay, action = self._steps.pop(0)

        def fire() -> bool:
            self._source = 0
            action()
            self._next()
            return GLib.SOURCE_REMOVE

        self._source = GLib.timeout_add(max(delay, 1), fire)

    def cancel(self) -> None:
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0
        if self._running:
            self._running = False
            if self._on_cancel:
                self._on_cancel()


class SimulatedBackend(Backend):
    simulated = True

    def __init__(self, scenario: str = "feliz") -> None:
        if scenario not in SCENARIOS:
            raise ValueError(scenario)
        self.scenario = scenario
        opts = SCENARIOS[scenario]
        self._user = "ruscher"
        self._state: dict[str, object] = {}
        self.docker_installed = bool(opts.get("docker_installed", True))
        self.docker_running = bool(opts.get("docker_running", True))
        group = opts.get("group", GroupAccess.ACTIVE)
        self.group = group if isinstance(group, GroupAccess) else GroupAccess.ACTIVE
        self.disk = bool(opts.get("disk", True))
        self.fstype = str(opts.get("fstype", "ntfs"))
        self.port_busy = bool(opts.get("port_busy", False))
        self.internet = bool(opts.get("internet", True))
        ram_gib = opts.get("ram_gib", 46)
        self.ram = int(float(ram_gib if isinstance(ram_gib, (int, float)) else 46) * GIB)
        self.library = bool(opts.get("library", False))
        self.initialized = bool(opts.get("initialized", False))
        self.pull_fail = bool(opts.get("pull_fail", False))
        self.slow = bool(opts.get("slow", False))
        self.firewall = str(opts.get("firewall", ""))
        self.fstab_state = str(opts.get("fstab", "none"))
        self.update_fail = bool(opts.get("update_fail", False))
        self.installed = bool(opts.get("installed", False))
        self.version = str(opts.get("version", KNOWN_GOOD_VERSION))
        self.service = "active" if self.installed else "inactive"
        self._service_since = time.monotonic() - (600 if self.installed else 0)
        self._stats_key = self.initialized
        self._pull_attempts = 0
        self._event_listeners: list[Callable[[str], None]] = []
        self.mountpoint = f"/run/media/{self._user}/Novo volume"
        self.photo_path = f"{self.mountpoint}/immich-{self._user}"
        if self.installed:
            self._state["wizard_done"] = True

    # --- básico ---------------------------------------------------------------------
    def user_name(self) -> str:
        return self._user

    def load_config(self) -> AppConfig:
        if not self.installed:
            return AppConfig()
        return AppConfig(
            installed=True,
            immich_version=self.version,
            upload_location=self.photo_path,
            mount_point=self.mountpoint,
            mount_unit="run-media-ruscher-Novo\\x20volume.mount",
            fs_type=self.fstype,
            transcode="vaapi",
            ml="cpu",
            timezone="America/Sao_Paulo",
            db_data_location=f"{STACK_DIR}/postgres",
        )

    def docker_access(self) -> GroupAccess:
        return self.group

    def state_get(self, key: str, default: object = None) -> object:
        return self._state.get(key, default)

    def state_set(self, key: str, value: object) -> None:
        self._state[key] = value

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds * (2.5 if self.slow else 1))

    # --- fatos -------------------------------------------------------------------------
    def fact_docker(self) -> tuple[bool, str, bool]:
        self._sleep(0.35)
        return self.docker_installed, "29.7.2", self.docker_running

    def fact_memory(self) -> int:
        self._sleep(0.15)
        return self.ram

    def fact_cpu(self) -> tuple[int, bool]:
        self._sleep(0.15)
        return 16, True

    def fact_docker_free(self) -> int:
        self._sleep(0.2)
        return 176 * 10**9

    def fact_port(self) -> tuple[PortStatus, bool]:
        self._sleep(0.2)
        if self.installed and self.service == "active":
            return PortStatus(False, "docker-proxy"), True
        if self.port_busy:
            return PortStatus(False, "node"), False
        return PortStatus(True), False

    def fact_internet(self) -> bool:
        self._sleep(0.6)
        return self.internet

    def fact_firewall(self) -> str:
        self._sleep(0.2)
        return self.firewall

    # --- armazenamento --------------------------------------------------------------------
    def suggest_photo_path(self) -> str:
        return self.photo_path

    def _volume(self, path: str) -> storage.Volume:
        return storage.Volume(
            path=path,
            mountpoint=self.mountpoint,
            device="/dev/sdd1",
            fstype=self.fstype,
            uuid="F22A6D342A6CF74F",
            label="Novo volume",
            size=2_000_397_795_328,
            available=1_986_854_027_264,
            used=13_543_763_968,
            hotplug=True,
            transport="usb",
            model="SanDisk Portable SSD",
        )

    def inspect_storage(self, path: str) -> StorageReport:
        self._sleep(0.5)
        report = StorageReport(path=path)
        try:
            report.path = validate_photo_path(path)
        except ValidationError as exc:
            report.error = str(exc)
            return report
        if not self.disk:
            report.disk_missing = True
            return report
        volume = self._volume(report.path)
        if not report.path.startswith(self.mountpoint):
            volume = replace(
                volume,
                mountpoint="/home",
                device="/dev/nvme0n1p2",
                fstype="btrfs",
                label="",
                model="Samsung SSD 990",
                hotplug=False,
                transport="nvme",
                is_system_disk=True,
            )
        report.volume = volume
        report.warnings = storage.fs_warnings(volume)
        report.library = storage.LibraryInfo(
            self.library,
            ["library", "upload", "thumbs", "profile", "backups"] if self.library else [],
            ["immich-db-backup-20261003T020000-v3.2.4-pg14.19.sql.gz"] if self.library else [],
        )
        if volume.needs_boot_mount:
            report.fstab_state = self.fstab_state
            try:
                report.fstab_preview = fstab.fstab_line(volume.uuid, volume.mountpoint, volume.fstype, 1000, 1007)
            except ValueError:
                report.fstab_state = "unsupported"
        return report

    def defaults(self) -> Defaults:
        self._sleep(0.2)
        return Defaults(
            timezone="America/Sao_Paulo",
            timezones=["America/Manaus", "America/Recife", "America/Sao_Paulo", "Europe/Lisbon", "UTC/UTC"],
            gpu=GpuInfo(("amd",), True, False),
            ram=self.ram,
            cpu_v2=True,
        )

    def releases(self, force: bool = False) -> list[Release]:
        self._sleep(0.6)
        if not self.internet:
            raise OSError("sem internet (simulado)")
        out = []
        for tag, date, body in FAKE_RELEASES:
            major, minor, patch = (int(x) for x in tag[1:].split("."))
            out.append(
                Release(
                    tag,
                    (major, minor, patch),
                    tag,
                    body,
                    date,
                    f"https://github.com/immich-app/immich/releases/{tag}",
                )
            )
        return out

    def download_compose(self, version: str) -> str:
        self._sleep(0.4)
        return "name: immich\n"

    # --- helper -----------------------------------------------------------------------------
    def helper(
        self,
        action: str,
        args: list[str],
        on_event: HelperEventCallback | None,
        on_done: HelperDoneCallback,
    ) -> Operation:
        result = HelperResult(ok=True)
        steps: list[tuple[int, Callable[[], None]]] = []
        slow = 2 if self.slow else 1

        def emit(kind: str, key: str = "", value: str = "") -> Callable[[], None]:
            def go() -> None:
                event = HelperEvent(kind, key, value)
                line = f"@@{kind.upper()} " + (f"{key}={value}" if kind == "result" else (key or value))
                if kind == "error":
                    line = f"@@ERROR {key} {value}"
                    result.ok = False
                    result.error_code, result.error_detail = key, value
                if kind == "result":
                    result.results[key] = value
                result.log.append(line)
                if on_event:
                    on_event(event)

            return go

        def log(text: str) -> Callable[[], None]:
            def go() -> None:
                result.log.append(text)
                if on_event:
                    on_event(HelperEvent("log", value=text))

            return go

        script: list[tuple[int, Callable[[], None]]] = [(250, log(f"[simulado] pkexec nuvem-ruscher-helper {action}"))]
        if action == "install-docker":
            script += [
                (400, emit("step", value="install")),
                (900, log("resolvendo dependências... docker docker-compose")),
                (1300, emit("step", value="enable")),
                (500, self._do(lambda: setattr(self, "docker_installed", True))),
                (10, self._do(lambda: setattr(self, "docker_running", True))),
                (10, self._do(lambda: setattr(self, "group", GroupAccess.MISSING))),
            ]
        elif action == "enable-docker":
            script += [
                (600, emit("step", value="enable")),
                (400, self._do(lambda: setattr(self, "docker_running", True))),
            ]
        elif action == "add-docker-group":
            script += [
                (600, emit("step", value="group")),
                (300, self._do(lambda: setattr(self, "group", GroupAccess.PENDING))),
            ]
        elif action == "firewall-allow":
            script += [(700, emit("step", value="firewall")), (300, emit("result", "firewall", "ufw"))]
        elif action == "fstab-add":
            script += [
                (300, emit("step", value="check")),
                (300, emit("step", value="backup")),
                (200, emit("result", "backup", "/etc/fstab.nuvem-ruscher-20261004-101500.bak")),
                (300, emit("step", value="write")),
                (300, emit("step", value="verify")),
                (400, emit("step", value="apply")),
                (200, self._do(lambda: setattr(self, "fstab_state", "ours"))),
                (10, emit("result", "fstab", "ok")),
            ]
        elif action == "fstab-remove":
            script += [
                (500, emit("step", value="write")),
                (300, self._do(lambda: setattr(self, "fstab_state", "none"))),
            ]
        elif action == "setup":
            if not self.disk:
                script += [
                    (400, emit("step", value="storage")),
                    (300, emit("error", "storage-missing", "disco ausente")),
                ]
            else:
                version = args[0] if args else KNOWN_GOOD_VERSION
                script += [
                    (400 * slow, emit("step", value="storage")),
                    (300, emit("result", "mountpoint", self.mountpoint)),
                    (500 * slow, emit("step", value="download")),
                    (600 * slow, log("baixando docker-compose.yml da release " + version)),
                    (400 * slow, emit("step", value="env")),
                    (400 * slow, emit("step", value="service")),
                    (300, self._do(lambda: self._mark_installed(version))),
                    (10, emit("result", "version", version)),
                ]
        elif action in ("start", "restart"):
            if not self.disk:
                script += [(300, emit("error", "storage-missing", "disco não montado"))]
            else:
                script += [(500, emit("step", value=action)), (200, self._do(self._start_service))]
        elif action == "stop":
            script += [(800, emit("step", value="stop")), (200, self._do(self._stop_service))]
        elif action == "backup-db":
            name = time.strftime("nuvem-ruscher-db-%Y%m%d-%H%M%S") + f"-{self.version}.sql.gz"
            script += [
                (500, emit("step", value="dump")),
                (1500, emit("step", value="copy")),
                (300, self._do(lambda: self._add_backup(name))),
                (10, emit("result", "file", f"{self.photo_path}/backups/nuvem-ruscher/{name}")),
            ]
        elif action == "update":
            new = args[0] if args else KNOWN_GOOD_VERSION
            old = self.version
            script += [
                (500, emit("step", value="download")),
                (900, emit("step", value="pull")),
                (900, emit("step", value="backup")),
                (1200, emit("step", value="stop")),
                (600, emit("step", value="snapshot")),
                (600, emit("step", value="switch")),
                (400, emit("step", value="start")),
                (1800, log("aguardando o servidor responder (0s, serviço: active)")),
            ]
            if self.update_fail:
                script += [
                    (1500, emit("step", value="rollback")),
                    (1200, emit("result", "version", old)),
                    (
                        10,
                        emit(
                            "error",
                            "update-rolled-back",
                            f"a nova versão não ficou saudável; tudo voltou para {old}",
                        ),
                    ),
                ]
            else:
                script += [
                    (800, self._do(lambda: setattr(self, "version", new))),
                    (10, emit("result", "version", new)),
                ]
        elif action == "uninstall":
            script += [
                (600, emit("step", value="stop")),
                (800, emit("step", value="containers")),
                (500, emit("step", value="service")),
                (300, emit("step", value="files")),
                (200, self._do(self._uninstall)),
                (10, emit("result", "kept-photos", self.photo_path)),
            ]
        else:
            script += [(100, emit("error", "invalid-argument", f"ação desconhecida: {action}"))]
        steps.extend(script)
        steps.append((150, lambda: on_done(result)))
        return _Timeline(steps)

    @staticmethod
    def _do(fn: Callable[[], object]) -> Callable[[], None]:
        def go() -> None:
            fn()

        return go

    def _mark_installed(self, version: str) -> None:
        self.installed = True
        self.version = version

    def _start_service(self) -> None:
        self.service = "active"
        self._service_since = time.monotonic()
        self._notify("start")

    def _stop_service(self) -> None:
        self.service = "inactive"
        self._notify("die")

    def _uninstall(self) -> None:
        self.installed = False
        self.service = "inactive"
        self._state["wizard_done"] = False
        self._notify("destroy")

    def _notify(self, action: str) -> None:
        for listener in list(self._event_listeners):
            listener(json.dumps({"Action": action, "Actor": {"Attributes": {"name": "immich_server"}}}))

    _backups: list[BackupFile] | None = None

    def _add_backup(self, name: str) -> None:
        backups = self.backups()
        self._backups = backups
        backups.insert(
            0,
            BackupFile(
                f"{self.photo_path}/backups/nuvem-ruscher/{name}",
                name,
                18_400_000,
                time.time(),
                False,
                self.version,
            ),
        )

    # --- Docker -------------------------------------------------------------------------------
    def pull(
        self,
        on_progress: Callable[[PullProgress, str], None],
        on_done: Callable[[bool, PullProgress], None],
        version: str | None = None,
        compose_text: str | None = None,
    ) -> Operation:
        self._pull_attempts += 1
        progress = PullProgress()
        images = {
            "immich-server": [380, 220, 160, 90, 40],
            "immich-machine-learning": [520, 310, 120, 60],
            "database": [140, 60, 20],
            "redis": [12, 4],
        }
        events: list[str] = []
        for service in images:
            events.append(json.dumps({"id": service, "status": "Working", "text": "Pulling"}))
        for service, layers in images.items():
            for index in range(len(layers)):
                layer = f"{service[:4]}{index}"
                events.append(
                    json.dumps({"id": layer, "parent_id": service, "status": "Working", "text": "Pulling fs layer"})
                )
        for service, layers in images.items():
            for index, size_mb in enumerate(layers):
                total = size_mb * 1_000_000
                layer = f"{service[:4]}{index}"
                chunks = max(3, size_mb // 40)
                for chunk in range(1, chunks + 1):
                    events.append(
                        json.dumps(
                            {
                                "id": layer,
                                "parent_id": service,
                                "status": "Working",
                                "text": "Downloading",
                                "current": total * chunk // chunks,
                                "total": total,
                            }
                        )
                    )
                events.append(
                    json.dumps({"id": layer, "parent_id": service, "status": "Done", "text": "Pull complete"})
                )
            events.append(json.dumps({"id": service, "status": "Done", "text": "Pulled"}))
        fail_at = len(events) // 2 if (self.pull_fail and self._pull_attempts == 1) else None
        state = {"i": 0, "clock": 0.0}
        cancelled = {"v": False}

        def tick() -> bool:
            if cancelled["v"]:
                return GLib.SOURCE_REMOVE
            for _ in range(2):
                i = state["i"]
                if fail_at is not None and i >= fail_at:
                    line = json.dumps(
                        {
                            "id": "imm0",
                            "parent_id": "immich-server",
                            "status": "Error",
                            "text": "Error",
                            "details": "net/http: TLS handshake timeout",
                        }
                    )
                    progress.feed(line)
                    on_progress(progress, line)
                    on_done(False, progress)
                    return GLib.SOURCE_REMOVE
                if i >= len(events):
                    progress.finish()
                    on_done(True, progress)
                    return GLib.SOURCE_REMOVE
                state["clock"] += 1.6  # cada pedaço de ~40 MB "leva" 1,6 s
                progress.feed(events[i], now=state["clock"])
                on_progress(progress, events[i])
                state["i"] = i + 1
            return GLib.SOURCE_CONTINUE

        GLib.timeout_add(70, tick)

        class _Pull(Operation):
            @property
            def running(self) -> bool:
                return not cancelled["v"] and state["i"] < len(events)

            def cancel(self) -> None:
                cancelled["v"] = True
                on_done(False, progress)

        return _Pull()

    def service_state(self) -> str:
        return self.service

    def _age(self) -> float:
        return time.monotonic() - self._service_since

    def containers(self) -> list[ContainerState]:
        if not self.installed:
            return []
        if self.service != "active":
            return [ContainerState(n, "exited", Health.NONE, "Exited (0) 2 minutes ago", "") for n in CONTAINERS]
        age = self._age() / (3 if self.slow else 1)
        out = []
        for index, name in enumerate(CONTAINERS):
            health = Health.HEALTHY if age > 4 + index else Health.STARTING
            if name == "immich_redis":
                health = Health.HEALTHY if age > 2 else Health.STARTING
            out.append(ContainerState(name, "running", health, "Up", ""))
        return out

    def stats(self) -> dict[str, ContainerStats]:
        if self.service != "active":
            return {}
        base = {
            "immich_server": (2.0, 410),
            "immich_machine_learning": (0.4, 1130),
            "immich_postgres": (0.8, 190),
            "immich_redis": (0.2, 9),
        }
        return {
            name: ContainerStats(
                name, round(cpu + random.uniform(0, 1.5), 1), int((mem + random.uniform(-5, 5)) * 1024**2)
            )
            for name, (cpu, mem) in base.items()
        }

    def watch_events(self, on_event: Callable[[str], None], on_exit: Callable[[int], None]) -> Operation:
        self._event_listeners.append(on_event)
        listeners = self._event_listeners

        class _Watch(Operation):
            active = True

            @property
            def running(self) -> bool:
                return self.active

            def cancel(self) -> None:
                if self.active:
                    self.active = False
                    if on_event in listeners:
                        listeners.remove(on_event)

        return _Watch()

    def follow_logs(self, container: str, on_line: Callable[[str], None], on_exit: Callable[[int], None]) -> Operation:
        counter = {"n": 4200}

        def line() -> str:
            counter["n"] += 1
            ts = time.strftime("%d/%m/%Y, %H:%M:%S")
            template = random.choice(LOG_LINES) if container == "immich_server" else "{ts} [" + container + "] ok ({n})"
            return template.format(ts=ts, n=counter["n"])

        for _ in range(40):
            on_line(line())
        state = {"active": True}

        def tick() -> bool:
            if not state["active"]:
                return GLib.SOURCE_REMOVE
            if self.service == "active":
                on_line(line())
            return GLib.SOURCE_CONTINUE

        GLib.timeout_add(700, tick)

        class _Logs(Operation):
            @property
            def running(self) -> bool:
                return state["active"]

            def cancel(self) -> None:
                state["active"] = False

        return _Logs()

    # --- API -------------------------------------------------------------------------------------
    def ping(self) -> bool:
        time.sleep(0.15)
        return self.service == "active" and self._age() > (14 if self.slow else 5)

    def server_version(self) -> str:
        return self.version

    def is_initialized(self) -> bool:
        time.sleep(0.4)
        return self.initialized

    def create_admin(
        self, name: str, email: str, password: str, want_key: bool, transcode: str, ml_enabled: bool
    ) -> None:
        time.sleep(1.2)
        if email.lower().startswith("erro@"):
            raise ApiError(400, "email must be an email")
        self.initialized = True
        self._stats_key = want_key

    def connect_stats(self, email: str, password: str) -> None:
        time.sleep(0.8)
        if password == "errada":
            raise ApiError(401, "Incorrect email or password")
        self._stats_key = True

    def has_stats_key(self) -> bool:
        return self._stats_key

    def statistics(self) -> ServerStats | None:
        time.sleep(0.2)
        if not self._stats_key:
            return None
        return ServerStats(12_430, 318, 214_000_000_000)

    # --- diversos ------------------------------------------------------------------------------
    def backups(self) -> list[BackupFile]:
        if self._backups is None:
            now = time.time()
            folder = f"{self.photo_path}/backups"
            stamp = "%Y%m%dT020000"
            self._backups = [
                BackupFile(
                    f"{folder}/immich-db-backup-{time.strftime(stamp, time.localtime(now - d * 86400))}"
                    "-v3.2.4-pg14.19.sql.gz",
                    f"immich-db-backup-{d}.sql.gz",
                    17_800_000 + d * 120_000,
                    now - d * 86400 - 3600 * 8,
                    True,
                    "v3.2.4",
                )
                for d in range(0, 6 if self.installed else 0)
            ]
        return list(self._backups)

    def lan_ip(self) -> str:
        return "192.168.0.10"

    def tailscale(self) -> TailscaleInfo:
        return TailscaleInfo(True, True, "100.100.184.97", "ruscher-big.tail9c419a.ts.net")

    def disk_usage(self, path: str) -> tuple[int, int, int]:
        return 2_000_397_795_328, 214_000_000_000, 1_786_397_795_328

    def is_mounted(self, path: str) -> bool:
        return self.disk
