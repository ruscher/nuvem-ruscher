"""Docker via CLI: comandos, acesso ao grupo e parsers das saídas JSON."""

from __future__ import annotations

import grp
import json
import os
import pwd
import re
import shlex
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from nuvem_ruscher.constants import COMPOSE_PROJECT, CONTAINERS
from nuvem_ruscher.i18n import N_, _


class GroupAccess(Enum):
    ACTIVE = "active"  # o processo atual já tem o grupo docker
    PENDING = "pending"  # está no /etc/group, mas a sessão é anterior: usar `sg docker`
    MISSING = "missing"  # não está no grupo
    NO_GROUP = "no-group"  # grupo docker não existe (Docker não instalado)


def docker_group_access(
    user: str | None = None,
    process_groups: Iterable[int] | None = None,
) -> GroupAccess:
    user = user or pwd.getpwuid(os.getuid()).pw_name
    try:
        group = grp.getgrnam("docker")
    except KeyError:
        return GroupAccess.NO_GROUP
    current = set(os.getgroups() if process_groups is None else process_groups)
    if group.gr_gid in current or os.getuid() == 0:
        return GroupAccess.ACTIVE
    try:
        primary = pwd.getpwnam(user).pw_gid
    except KeyError:
        primary = -1
    if user in group.gr_mem or primary == group.gr_gid:
        return GroupAccess.PENDING
    return GroupAccess.MISSING


def docker_argv(args: Sequence[str], access: GroupAccess = GroupAccess.ACTIVE) -> list[str]:
    """Monta a linha de comando do Docker.

    Logo depois de entrar no grupo, a sessão atual ainda não tem o GID. Nesse caso
    usamos ``sg docker -c`` (o usuário é membro em /etc/group, então não há senha).
    """
    argv = ["docker", *args]
    if access is GroupAccess.PENDING:
        return ["sg", "docker", "-c", shlex.join(argv)]
    return argv


class Health(Enum):
    HEALTHY = "healthy"
    STARTING = "starting"
    UNHEALTHY = "unhealthy"
    NONE = "none"  # container sem healthcheck


@dataclass(frozen=True)
class ContainerState:
    name: str
    state: str  # running, exited, created, restarting, paused, dead
    health: Health
    status: str
    image: str

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def ok(self) -> bool:
        return self.running and self.health in (Health.HEALTHY, Health.NONE)


CONTAINER_LABELS = {
    "immich_server": N_("Servidor"),
    "immich_machine_learning": N_("Inteligência artificial"),
    "immich_postgres": N_("Banco de dados"),
    "immich_redis": N_("Cache"),
}

CONTAINER_DESCRIPTIONS = {
    "immich_server": N_("Site, aplicativo e envio de fotos"),
    "immich_machine_learning": N_("Rostos e busca inteligente"),
    "immich_postgres": N_("Álbuns, pessoas e informações das fotos"),
    "immich_redis": N_("Fila de tarefas"),
}


def container_label(name: str) -> str:
    return _(CONTAINER_LABELS[name]) if name in CONTAINER_LABELS else name


def container_description(name: str) -> str:
    return _(CONTAINER_DESCRIPTIONS[name]) if name in CONTAINER_DESCRIPTIONS else ""


_HEALTH_IN_STATUS = re.compile(r"\((healthy|unhealthy|health: starting)\)")


def _health(item: dict[str, object]) -> Health:
    raw = str(item.get("HealthStatus") or "").lower()
    if not raw or raw == "none":
        match = _HEALTH_IN_STATUS.search(str(item.get("Status") or ""))
        raw = match.group(1) if match else "none"
    if raw.startswith("health: "):
        raw = raw.removeprefix("health: ")
    try:
        return Health(raw)
    except ValueError:
        return Health.NONE


def parse_ps(lines: Iterable[str]) -> list[ContainerState]:
    """``docker ps -a --format json`` (um objeto por linha), ordenado como no painel."""
    found: dict[str, ContainerState] = {}
    for raw in lines:
        line = raw.strip()
        if not line.startswith("{"):
            continue
        item = json.loads(line)
        name = str(item.get("Names") or "").split(",")[0]
        found[name] = ContainerState(
            name=name,
            state=str(item.get("State") or "").lower(),
            health=_health(item),
            status=str(item.get("Status") or ""),
            image=str(item.get("Image") or ""),
        )
    order = {name: i for i, name in enumerate(CONTAINERS)}
    return sorted(found.values(), key=lambda c: (order.get(c.name, 99), c.name))


@dataclass(frozen=True)
class ContainerStats:
    name: str
    cpu_percent: float
    memory_bytes: int


_SIZE_UNITS = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}


def parse_size(text: str) -> int:
    """'410.5MiB' → bytes. Valores desconhecidos ('--') viram 0."""
    match = re.match(r"^\s*([\d.]+)\s*([A-Za-z]+)\s*$", text)
    if not match:
        return 0
    number, unit = match.groups()
    return int(float(number) * _SIZE_UNITS.get(unit.lower(), 1))


def parse_stats(lines: Iterable[str]) -> dict[str, ContainerStats]:
    """``docker stats --no-stream --format json``."""
    result: dict[str, ContainerStats] = {}
    for raw in lines:
        line = raw.strip()
        if not line.startswith("{"):
            continue
        item = json.loads(line)
        name = str(item.get("Name") or "")
        cpu_text = str(item.get("CPUPerc") or "").rstrip("%")
        try:
            cpu = float(cpu_text)
        except ValueError:
            cpu = 0.0
        mem = parse_size(str(item.get("MemUsage") or "").split("/")[0])
        result[name] = ContainerStats(name, cpu, mem)
    return result


@dataclass(frozen=True)
class DockerEvent:
    container: str
    action: str


def parse_event(line: str) -> DockerEvent | None:
    """Uma linha de ``docker events --format '{{json .}}'``."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        return None
    actor = item.get("Actor") or {}
    attributes = actor.get("Attributes") or {}
    name = str(attributes.get("name") or "")
    action = str(item.get("Action") or item.get("status") or "")
    return DockerEvent(name, action) if name else None


def ps_args() -> list[str]:
    return ["ps", "-a", "--filter", f"label=com.docker.compose.project={COMPOSE_PROJECT}", "--format", "json"]


def events_args() -> list[str]:
    return [
        "events",
        "--filter",
        "type=container",
        "--filter",
        f"label=com.docker.compose.project={COMPOSE_PROJECT}",
        "--format",
        "{{json .}}",
    ]


def stats_args(names: Sequence[str]) -> list[str]:
    return ["stats", "--no-stream", "--format", "json", *names]


def logs_args(container: str, tail: int = 400) -> list[str]:
    if container not in CONTAINERS:
        raise ValueError(f"container desconhecido: {container}")
    return ["logs", "--follow", "--timestamps", "--tail", str(tail), container]
