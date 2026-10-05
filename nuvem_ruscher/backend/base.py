"""Fachada única entre a interface e o sistema.

``RealBackend`` executa de verdade; ``SimulatedBackend`` finge tudo (``--simular``).
Métodos bloqueantes devem ser chamados via ``run_async``; métodos que devolvem
``Operation`` já são assíncronos e entregam callbacks na thread da interface.
"""

from __future__ import annotations

import abc
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from nuvem_ruscher.async_utils import Operation
from nuvem_ruscher.constants import (
    IMMICH_PORT,
    MIN_DOCKER_FREE_GIB,
    MIN_RAM_GIB,
    ML_OFF_RAM_GIB,
)
from nuvem_ruscher.core.compose import PullProgress
from nuvem_ruscher.core.config import AppConfig
from nuvem_ruscher.core.disks import Disk
from nuvem_ruscher.core.docker import ContainerState, ContainerStats, GroupAccess
from nuvem_ruscher.core.helper_protocol import HelperEvent
from nuvem_ruscher.core.immich_api import Album, ImmichUser, Person, ServerStats, Session
from nuvem_ruscher.core.migration import MigrationPlan, MigrationState, Mode
from nuvem_ruscher.core.raid import RaidArray
from nuvem_ruscher.core.releases import Release
from nuvem_ruscher.core.storage import FsWarning, LibraryInfo, Volume, human_size
from nuvem_ruscher.core.system import GIB, GpuInfo, PortStatus, TailscaleInfo
from nuvem_ruscher.i18n import _

# Versão testada com este app; usada quando não há internet para listar releases.
KNOWN_GOOD_VERSION = "v3.2.4"


class CheckStatus(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"
    SKIP = "skip"


@dataclass(frozen=True)
class Fix:
    label: str
    action: str  # ação do helper (ex.: "install-docker")


@dataclass(frozen=True)
class CheckResult:
    id: str
    status: CheckStatus
    title: str
    subtitle: str = ""
    fix: Fix | None = None

    @property
    def blocking(self) -> bool:
        return self.status is CheckStatus.ERROR


CHECK_IDS = (
    "docker_installed",
    "docker_running",
    "docker_group",
    "memory",
    "cpu",
    "disk_system",
    "port",
    "internet",
    "firewall",
)


@dataclass
class StorageReport:
    path: str
    volume: Volume | None = None
    warnings: list[FsWarning] = field(default_factory=list)
    library: LibraryInfo | None = None
    fstab_state: str = "none"  # none | ours | foreign | unsupported
    fstab_preview: str = ""
    error: str = ""  # texto humano quando a pasta é inválida
    disk_missing: bool = False


@dataclass
class HelperResult:
    ok: bool
    error_code: str = ""
    error_detail: str = ""
    results: dict[str, str] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BackupFile:
    path: str
    name: str
    size: int
    mtime: float
    automatic: bool
    version: str = ""


@dataclass
class Defaults:
    timezone: str
    timezones: list[str]
    gpu: GpuInfo
    ram: int
    cpu_v2: bool

    @property
    def ml_recommended(self) -> bool:
        return self.cpu_v2 and self.ram >= MIN_RAM_GIB * GIB * 0.95


VERSION_IN_NAME = re.compile(r"-v(\d+\.\d+\.\d+)")


def version_from_backup_name(name: str) -> str:
    match = VERSION_IN_NAME.search(name)
    return f"v{match.group(1)}" if match else ""


HelperEventCallback = Callable[[HelperEvent], None]
HelperDoneCallback = Callable[[HelperResult], None]


class Backend(abc.ABC):
    simulated: bool = False

    # --- informações básicas ----------------------------------------------------
    @abc.abstractmethod
    def user_name(self) -> str: ...

    @abc.abstractmethod
    def load_config(self) -> AppConfig: ...

    @abc.abstractmethod
    def docker_access(self) -> GroupAccess: ...

    # --- fatos para a verificação (bloqueantes) ---------------------------------
    @abc.abstractmethod
    def fact_docker(self) -> tuple[bool, str, bool]:
        """(instalado, versão, ligado)."""

    @abc.abstractmethod
    def fact_memory(self) -> int: ...

    @abc.abstractmethod
    def fact_cpu(self) -> tuple[int, bool]: ...

    @abc.abstractmethod
    def fact_docker_free(self) -> int: ...

    @abc.abstractmethod
    def fact_port(self) -> tuple[PortStatus, bool]:
        """(estado da porta, é o nosso Immich?)."""

    @abc.abstractmethod
    def fact_internet(self) -> bool: ...

    @abc.abstractmethod
    def fact_firewall(self) -> str: ...

    # --- armazenamento e configuração -------------------------------------------
    @abc.abstractmethod
    def suggest_photo_path(self) -> str: ...

    @abc.abstractmethod
    def inspect_storage(self, path: str) -> StorageReport: ...

    @abc.abstractmethod
    def defaults(self) -> Defaults: ...

    @abc.abstractmethod
    def releases(self, force: bool = False) -> list[Release]: ...

    # --- helper privilegiado -----------------------------------------------------
    @abc.abstractmethod
    def helper(
        self,
        action: str,
        args: list[str],
        on_event: HelperEventCallback | None,
        on_done: HelperDoneCallback,
        interactive: bool = False,
    ) -> Operation:
        """``interactive``: ``cancel()`` pede o cancelamento ao helper (ele decide se ainda dá)."""

    # --- Docker como usuário -----------------------------------------------------
    @abc.abstractmethod
    def pull(
        self,
        on_progress: Callable[[PullProgress, str], None],
        on_done: Callable[[bool, PullProgress], None],
        version: str | None = None,
        compose_text: str | None = None,
    ) -> Operation: ...

    @abc.abstractmethod
    def download_compose(self, version: str) -> str: ...

    @abc.abstractmethod
    def service_state(self) -> str: ...

    @abc.abstractmethod
    def containers(self) -> list[ContainerState]: ...

    @abc.abstractmethod
    def stats(self) -> dict[str, ContainerStats]: ...

    @abc.abstractmethod
    def watch_events(self, on_event: Callable[[str], None], on_exit: Callable[[int], None]) -> Operation: ...

    @abc.abstractmethod
    def follow_logs(
        self, container: str, on_line: Callable[[str], None], on_exit: Callable[[int], None]
    ) -> Operation: ...

    # --- API do Immich -------------------------------------------------------------
    @abc.abstractmethod
    def ping(self) -> bool: ...

    @abc.abstractmethod
    def probe_server(self, url: str) -> bool:
        """O servidor responde em ``url`` (ex.: o endereço do QR)? Testado deste computador."""

    @abc.abstractmethod
    def server_version(self) -> str: ...

    @abc.abstractmethod
    def is_initialized(self) -> bool: ...

    @abc.abstractmethod
    def create_admin(
        self, name: str, email: str, password: str, want_key: bool, transcode: str, ml_enabled: bool
    ) -> None: ...

    @abc.abstractmethod
    def connect_stats(self, email: str, password: str) -> None: ...

    @abc.abstractmethod
    def has_stats_key(self) -> bool: ...

    @abc.abstractmethod
    def statistics(self) -> ServerStats | None: ...

    # --- contas e compartilhamento (API do Immich; sessão só na memória) ----------
    @property
    @abc.abstractmethod
    def session(self) -> Session | None: ...

    @abc.abstractmethod
    def sign_in(self, email: str, password: str) -> Session: ...

    @abc.abstractmethod
    def sign_out(self) -> None: ...

    @abc.abstractmethod
    def accounts(self) -> list[ImmichUser]:
        """Todas as contas (inclusive desativadas), com fotos, vídeos e uso. Só administrador."""

    @abc.abstractmethod
    def create_account(
        self, name: str, email: str, password: str, quota: int | None, storage_label: str | None, is_admin: bool
    ) -> ImmichUser: ...

    @abc.abstractmethod
    def update_account(self, user_id: str, **changes: object) -> ImmichUser: ...

    @abc.abstractmethod
    def reset_account_password(self, user_id: str) -> str: ...

    @abc.abstractmethod
    def disable_account(self, user_id: str) -> ImmichUser: ...

    @abc.abstractmethod
    def restore_account(self, user_id: str) -> ImmichUser: ...

    @abc.abstractmethod
    def people(self) -> list[Person]: ...

    @abc.abstractmethod
    def shared_albums(self) -> tuple[list[Album], list[Album]]:
        """(compartilhados pela conta conectada, compartilhados com ela)."""

    @abc.abstractmethod
    def create_shared_album(self, name: str, members: list[tuple[str, str]]) -> Album: ...

    @abc.abstractmethod
    def add_album_members(self, album_id: str, members: list[tuple[str, str]]) -> Album: ...

    @abc.abstractmethod
    def set_album_role(self, album_id: str, user_id: str, role: str) -> None: ...

    @abc.abstractmethod
    def remove_album_member(self, album_id: str, user_id: str) -> None: ...

    @abc.abstractmethod
    def partners(self) -> tuple[list[Person], list[Person]]:
        """(com quem a conta conectada compartilha a biblioteca, quem compartilha com ela)."""

    @abc.abstractmethod
    def add_partner(self, user_id: str) -> None: ...

    @abc.abstractmethod
    def remove_partner(self, user_id: str) -> None: ...

    # --- discos, RAID e troca de local -----------------------------------------------
    @abc.abstractmethod
    def disks(self) -> list[Disk]: ...

    @abc.abstractmethod
    def raid_arrays(self) -> list[RaidArray]: ...

    @abc.abstractmethod
    def tool_available(self, name: str) -> bool:
        """rsync | mdadm | smartctl"""

    @abc.abstractmethod
    def plan_migration(self, dest: str, mode: Mode | None = None) -> MigrationPlan:
        """Bloqueante: conta os arquivos da biblioteca (pode levar alguns segundos)."""

    @abc.abstractmethod
    def migration_state(self) -> MigrationState | None: ...

    # --- diversos -----------------------------------------------------------------
    @abc.abstractmethod
    def backups(self) -> list[BackupFile]: ...

    @abc.abstractmethod
    def lan_ip(self) -> str: ...

    @abc.abstractmethod
    def tailscale(self) -> TailscaleInfo: ...

    @abc.abstractmethod
    def disk_usage(self, path: str) -> tuple[int, int, int]: ...

    @abc.abstractmethod
    def is_mounted(self, path: str) -> bool: ...

    @abc.abstractmethod
    def state_get(self, key: str, default: object = None) -> object: ...

    @abc.abstractmethod
    def state_set(self, key: str, value: object) -> None: ...

    # --- endereços -------------------------------------------------------------------
    def server_url(self, host: str | None = None) -> str:
        return f"http://{host or self.lan_ip()}:{IMMICH_PORT}"

    @property
    def local_url(self) -> str:
        return f"http://localhost:{IMMICH_PORT}"

    # --- verificação do sistema (textos humanos) -------------------------------------
    def check(self, check_id: str) -> CheckResult:
        if check_id == "docker_installed":
            installed, version, _running = self.fact_docker()
            if installed:
                return CheckResult(check_id, CheckStatus.OK, _("Docker installed"), _("Version {v}").format(v=version))
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                _("Docker is not installed"),
                _("It is the program that runs the photo server. Installation is automatic."),
                Fix(_("Install"), "install-docker"),
            )
        if check_id == "docker_running":
            installed, _version, running = self.fact_docker()
            if not installed:
                return CheckResult(check_id, CheckStatus.SKIP, _("Docker running"), _("Waiting for the installation"))
            if running:
                return CheckResult(check_id, CheckStatus.OK, _("Docker running"))
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                _("Docker is turned off"),
                _("We will turn it on now and have it start with the computer."),
                Fix(_("Turn on"), "enable-docker"),
            )
        if check_id == "docker_group":
            access = self.docker_access()
            if access is GroupAccess.ACTIVE:
                return CheckResult(check_id, CheckStatus.OK, _("Your user can use Docker"))
            if access is GroupAccess.PENDING:
                return CheckResult(
                    check_id,
                    CheckStatus.OK,
                    _("Permission granted"),
                    _("It already works. When you can, log out and back in to complete the change."),
                )
            if access is GroupAccess.NO_GROUP:
                return CheckResult(
                    check_id,
                    CheckStatus.SKIP,
                    _("Permission to use Docker"),
                    _("Waiting for the installation"),
                )
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                _("Your user cannot use Docker yet"),
                _("We need to add “{user}” to the docker group.").format(user=self.user_name()),
                Fix(_("Allow"), "add-docker-group"),
            )
        if check_id == "memory":
            ram = self.fact_memory()
            text = _("Memory: {size}").format(size=human_size(ram, binary=True))
            # /proc/meminfo mostra um pouco menos que o pente instalado; 5 % de folga.
            if ram >= MIN_RAM_GIB * GIB * 0.95:
                return CheckResult(check_id, CheckStatus.OK, text, _("The minimum is {n} GB").format(n=MIN_RAM_GIB))
            if ram >= ML_OFF_RAM_GIB * GIB * 0.95:
                return CheckResult(
                    check_id,
                    CheckStatus.WARNING,
                    text,
                    _("Below the recommended amount. We will turn off face recognition so it fits."),
                )
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                text,
                _("Immich needs at least {n} GB of memory.").format(n=ML_OFF_RAM_GIB),
            )
        if check_id == "cpu":
            cores, v2 = self.fact_cpu()
            title = _("Processor: {n} cores").format(n=cores)
            if not v2:
                return CheckResult(
                    check_id,
                    CheckStatus.WARNING,
                    title,
                    _("Old processor: artificial intelligence will be turned off."),
                )
            if cores < 2:
                return CheckResult(check_id, CheckStatus.WARNING, title, _("It will work, but slowly."))
            return CheckResult(check_id, CheckStatus.OK, title)
        if check_id == "disk_system":
            free = self.fact_docker_free()
            need = MIN_DOCKER_FREE_GIB * GIB
            title = _("Space on the system disk: {size} free").format(size=human_size(free))
            if free >= need:
                return CheckResult(check_id, CheckStatus.OK, title, _("The components take up about 5 GB"))
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                _("Not enough space on the system disk"),
                _("Free up {size} more to download the components.").format(size=human_size(need - free)),
            )
        if check_id == "port":
            port, ours = self.fact_port()
            if port.free:
                return CheckResult(check_id, CheckStatus.OK, _("Port {p} is free").format(p=IMMICH_PORT))
            if ours:
                return CheckResult(
                    check_id, CheckStatus.OK, _("Port {p} already belongs to your Immich").format(p=IMMICH_PORT)
                )
            if port.owner:
                hint = _("It is used by “{name}”. Close that program or stop the other Immich, then check again.")
                hint = hint.format(name=port.owner)
            else:
                hint = _("Close that program or stop the other Immich, then check again.")
            return CheckResult(
                check_id, CheckStatus.ERROR, _("Another program is using port {p}").format(p=IMMICH_PORT), hint
            )
        if check_id == "internet":
            if self.fact_internet():
                return CheckResult(check_id, CheckStatus.OK, _("Connected to the internet"))
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                _("No internet connection"),
                _("It is only needed now, to download the components."),
            )
        if check_id == "firewall":
            name = self.fact_firewall()
            if not name:
                return CheckResult(check_id, CheckStatus.OK, _("No firewall blocking"))
            if self.state_get("firewall_allowed"):
                return CheckResult(
                    check_id,
                    CheckStatus.OK,
                    _("Firewall open to the home network"),
                    _("Port {p} open only to local networks and Tailscale").format(p=IMMICH_PORT),
                )
            return CheckResult(
                check_id,
                CheckStatus.INFO,
                _("Firewall active ({name})").format(name=name),
                _("Open port {p} so the phone can find the server on the home network.").format(p=IMMICH_PORT),
                Fix(_("Open port"), "firewall-allow"),
            )
        raise ValueError(check_id)
