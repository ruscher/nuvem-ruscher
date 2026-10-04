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
from nuvem_ruscher.core.docker import ContainerState, ContainerStats, GroupAccess
from nuvem_ruscher.core.helper_protocol import HelperEvent
from nuvem_ruscher.core.immich_api import ServerStats
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
    ) -> Operation: ...

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
                return CheckResult(check_id, CheckStatus.OK, _("Docker instalado"), _("Versão {v}").format(v=version))
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                _("O Docker não está instalado"),
                _("É o programa que roda o servidor de fotos. A instalação é automática."),
                Fix(_("Instalar"), "install-docker"),
            )
        if check_id == "docker_running":
            installed, _version, running = self.fact_docker()
            if not installed:
                return CheckResult(check_id, CheckStatus.SKIP, _("Docker ligado"), _("Aguardando a instalação"))
            if running:
                return CheckResult(check_id, CheckStatus.OK, _("Docker ligado"))
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                _("O Docker está desligado"),
                _("Vamos ligá-lo agora e deixá-lo ligando junto com o computador."),
                Fix(_("Ligar"), "enable-docker"),
            )
        if check_id == "docker_group":
            access = self.docker_access()
            if access is GroupAccess.ACTIVE:
                return CheckResult(check_id, CheckStatus.OK, _("Seu usuário pode usar o Docker"))
            if access is GroupAccess.PENDING:
                return CheckResult(
                    check_id,
                    CheckStatus.OK,
                    _("Permissão concedida"),
                    _("Já funciona. Quando puder, saia e entre na sessão para completar o ajuste."),
                )
            if access is GroupAccess.NO_GROUP:
                return CheckResult(
                    check_id,
                    CheckStatus.SKIP,
                    _("Permissão para usar o Docker"),
                    _("Aguardando a instalação"),
                )
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                _("Seu usuário ainda não pode usar o Docker"),
                _("Precisamos colocar “{user}” no grupo docker.").format(user=self.user_name()),
                Fix(_("Permitir"), "add-docker-group"),
            )
        if check_id == "memory":
            ram = self.fact_memory()
            text = _("Memória: {size}").format(size=human_size(ram, binary=True))
            # /proc/meminfo mostra um pouco menos que o pente instalado; 5 % de folga.
            if ram >= MIN_RAM_GIB * GIB * 0.95:
                return CheckResult(check_id, CheckStatus.OK, text, _("O mínimo é {n} GB").format(n=MIN_RAM_GIB))
            if ram >= ML_OFF_RAM_GIB * GIB * 0.95:
                return CheckResult(
                    check_id,
                    CheckStatus.WARNING,
                    text,
                    _("Abaixo do recomendado. Vamos desligar o reconhecimento de rostos para caber."),
                )
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                text,
                _("O Immich precisa de pelo menos {n} GB de memória.").format(n=ML_OFF_RAM_GIB),
            )
        if check_id == "cpu":
            cores, v2 = self.fact_cpu()
            title = _("Processador: {n} núcleos").format(n=cores)
            if not v2:
                return CheckResult(
                    check_id,
                    CheckStatus.WARNING,
                    title,
                    _("Processador antigo: a inteligência artificial ficará desligada."),
                )
            if cores < 2:
                return CheckResult(check_id, CheckStatus.WARNING, title, _("Vai funcionar, mas devagar."))
            return CheckResult(check_id, CheckStatus.OK, title)
        if check_id == "disk_system":
            free = self.fact_docker_free()
            need = MIN_DOCKER_FREE_GIB * GIB
            title = _("Espaço no disco do sistema: {size} livres").format(size=human_size(free))
            if free >= need:
                return CheckResult(check_id, CheckStatus.OK, title, _("Os componentes ocupam cerca de 5 GB"))
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                _("Falta espaço no disco do sistema"),
                _("Libere mais {size} para baixar os componentes.").format(size=human_size(need - free)),
            )
        if check_id == "port":
            port, ours = self.fact_port()
            if port.free:
                return CheckResult(check_id, CheckStatus.OK, _("Porta {p} livre").format(p=IMMICH_PORT))
            if ours:
                return CheckResult(check_id, CheckStatus.OK, _("Porta {p} já é do seu Immich").format(p=IMMICH_PORT))
            owner = _(" (usada por {name})").format(name=port.owner) if port.owner else ""
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                _("Outro programa está usando a porta {p}").format(p=IMMICH_PORT),
                _("Feche esse programa ou pare o outro Immich e verifique de novo.") + owner,
            )
        if check_id == "internet":
            if self.fact_internet():
                return CheckResult(check_id, CheckStatus.OK, _("Conectado à internet"))
            return CheckResult(
                check_id,
                CheckStatus.ERROR,
                _("Sem conexão com a internet"),
                _("Ela só é necessária agora, para baixar os componentes."),
            )
        if check_id == "firewall":
            name = self.fact_firewall()
            if not name:
                return CheckResult(check_id, CheckStatus.OK, _("Nenhum firewall bloqueando"))
            if self.state_get("firewall_allowed"):
                return CheckResult(
                    check_id,
                    CheckStatus.OK,
                    _("Firewall liberado para a rede de casa"),
                    _("Porta {p} aberta só para redes locais e Tailscale").format(p=IMMICH_PORT),
                )
            return CheckResult(
                check_id,
                CheckStatus.INFO,
                _("Firewall ativo ({name})").format(name=name),
                _("Libere a porta {p} para que o celular encontre o servidor na rede de casa.").format(p=IMMICH_PORT),
                Fix(_("Liberar"), "firewall-allow"),
            )
        raise ValueError(check_id)
