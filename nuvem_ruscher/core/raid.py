"""RAID por software (mdadm): leitura do estado sem root, por /proc/mdstat.

Só leitura. Criar arrays é tarefa do helper (``raid-create``), com confirmação.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Níveis que o app sabe explicar e criar; raid0 só aparece em "Avançado".
LEVELS = ("raid1", "raid5", "raid6", "raid10", "raid0")
MIN_DISKS = {"raid1": 2, "raid5": 3, "raid6": 4, "raid10": 4, "raid0": 2}
# Quantos discos podem falhar sem perder o array (raid10: um por par, no mínimo 1).
TOLERATES = {"raid1": None, "raid5": 1, "raid6": 2, "raid10": 1, "raid0": 0}


class RaidState(Enum):
    HEALTHY = "healthy"
    SYNCING = "syncing"  # sincronização inicial (resync), redundância já existe
    CHECKING = "checking"  # verificação periódica (check/repair)
    REBUILDING = "rebuilding"  # recuperando um disco (recovery/reshape)
    DEGRADED = "degraded"  # falta disco e nada está reconstruindo
    FAILED = "failed"  # parado ou com menos discos que o mínimo


@dataclass(frozen=True)
class RaidMember:
    name: str  # sdb1, nvme0n1p1…
    slot: int
    faulty: bool = False
    spare: bool = False


@dataclass
class RaidArray:
    device: str  # md127
    level: str  # raid1…
    active: bool
    members: list[RaidMember] = field(default_factory=list)
    raid_disks: int = 0  # discos previstos
    working_disks: int = 0  # discos em uso agora
    status_map: str = ""  # "UU", "U_"
    size_bytes: int = 0
    operation: str = ""  # resync | recovery | reshape | check | repair
    progress: float | None = None  # 0–1
    finish: str = ""  # "84.2min", como o kernel informa
    speed: str = ""
    label: str = ""  # nome em /dev/md/<label>

    @property
    def name(self) -> str:
        return self.label or self.device

    @property
    def missing(self) -> int:
        return max(0, self.raid_disks - self.working_disks)

    @property
    def failed_members(self) -> list[RaidMember]:
        return [m for m in self.members if m.faulty]

    @property
    def state(self) -> RaidState:
        if not self.active:
            return RaidState.FAILED
        if self._lost():
            return RaidState.FAILED
        if self.operation in ("recovery", "reshape"):
            return RaidState.REBUILDING
        if self.operation == "resync":
            return RaidState.REBUILDING if self.missing else RaidState.SYNCING
        if self.operation in ("check", "repair"):
            return RaidState.CHECKING
        if self.missing or self.failed_members:
            return RaidState.DEGRADED
        return RaidState.HEALTHY

    def _lost(self) -> bool:
        """Faltam mais discos do que o nível aguenta?"""
        if self.level == "raid0":
            return self.missing > 0 or bool(self.failed_members)
        if self.level == "raid1":
            return self.working_disks < 1
        tolerated = TOLERATES.get(self.level)
        if tolerated is None:
            return False
        if self.level == "raid10":
            # Sem saber os pares, só dá para afirmar perda quando falta mais da metade.
            return self.missing > self.raid_disks // 2
        return self.missing > tolerated


_HEAD = re.compile(r"^(md\w+)\s*:\s*(active|inactive)(?:\s*\((?:auto-)?read-only\))?\s*(\S+)?\s*(.*)$")
_MEMBER = re.compile(r"^(\S+?)\[(\d+)\]((?:\([A-Z]\))*)$")
_COUNTS = re.compile(r"(\d+)\s+blocks.*\[(\d+)/(\d+)\]\s*\[([U_]+)\]")
_BLOCKS = re.compile(r"(\d+)\s+blocks")
_PROGRESS = re.compile(
    r"\b(resync|recovery|reshape|check|repair)\s*=\s*([\d.]+)%(?:.*?finish=(\S+))?(?:.*?speed=(\S+))?"
)
_DELAYED = re.compile(r"\b(resync|recovery|reshape|check|repair)\s*=\s*(DELAYED|PENDING)")


def parse_mdstat(text: str) -> list[RaidArray]:
    arrays: list[RaidArray] = []
    current: RaidArray | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("Personalities", "unused devices")):
            continue
        head = _HEAD.match(line)
        if head:
            device, state, level, rest = head.groups()
            active = state == "active"
            tokens = rest.split()
            if level and not level.startswith("raid") and level != "linear":
                # "md125 : inactive sdf[0](S)": não há nível na linha, o primeiro item já é disco.
                tokens.insert(0, level)
                level = ""
            members = []
            for token in tokens:
                m = _MEMBER.match(token)
                if m:
                    flags = m.group(3)
                    members.append(RaidMember(m.group(1), int(m.group(2)), "(F)" in flags, "(S)" in flags))
            current = RaidArray(device=device, level=level or "", active=active, members=members)
            arrays.append(current)
            continue
        if current is None:
            continue
        counts = _COUNTS.search(line)
        if counts:
            current.size_bytes = int(counts.group(1)) * 1024
            current.raid_disks = int(counts.group(2))
            current.working_disks = int(counts.group(3))
            current.status_map = counts.group(4)
            continue
        blocks = _BLOCKS.search(line)
        if blocks and not current.size_bytes:
            current.size_bytes = int(blocks.group(1)) * 1024
        progress = _PROGRESS.search(line)
        if progress:
            current.operation = progress.group(1)
            current.progress = float(progress.group(2)) / 100
            current.finish = progress.group(3) or ""
            current.speed = progress.group(4) or ""
            continue
        delayed = _DELAYED.search(line)
        if delayed:
            current.operation = delayed.group(1)
            current.progress = 0.0
    for array in arrays:
        if not array.raid_disks:
            # raid0/linear e arrays inativos não mostram [n/m]: todos os membros contam.
            working = [m for m in array.members if not m.faulty and not m.spare]
            array.raid_disks = len(working) if array.active else len(array.members)
            array.working_disks = len(working) if array.active else 0
    return arrays


def read_arrays(mdstat: str = "/proc/mdstat", dev_md: str = "/dev/md") -> list[RaidArray]:
    """Arrays do sistema; lista vazia se o kernel não tem md (sem /proc/mdstat)."""
    try:
        text = Path(mdstat).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    arrays = parse_mdstat(text)
    labels = _labels(dev_md)
    for array in arrays:
        array.label = labels.get(array.device, "")
    return arrays


def _labels(dev_md: str) -> dict[str, str]:
    """/dev/md/<nome> → mdNNN."""
    result: dict[str, str] = {}
    try:
        entries = os.listdir(dev_md)
    except OSError:
        return result
    for name in entries:
        target = os.path.realpath(os.path.join(dev_md, name))
        result[os.path.basename(target)] = name.split(":", 1)[-1]
    return result


def usable_size(level: str, sizes: list[int]) -> int:
    """Capacidade útil aproximada (o array usa o tamanho do menor disco)."""
    if not sizes:
        return 0
    n = len(sizes)
    smallest = min(sizes)
    if level == "raid1":
        return smallest
    if level == "raid5":
        return smallest * (n - 1) if n >= 3 else 0
    if level == "raid6":
        return smallest * (n - 2) if n >= 4 else 0
    if level == "raid10":
        return smallest * (n // 2) if n >= 4 else 0
    if level == "raid0":
        return smallest * n
    return 0
