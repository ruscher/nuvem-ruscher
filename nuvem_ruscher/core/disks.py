"""Inventário dos discos e o que impede cada um de ser usado num RAID novo.

Só leitura (``lsblk``, ``/proc/swaps``, ``/dev/disk/by-id``, ``/sys/block``). O helper
refaz as mesmas checagens como root antes de qualquer operação destrutiva.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

LSBLK_COLUMNS = (
    "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,TRAN,RM,RO,HOTPLUG,ROTA,FSTYPE,UUID,LABEL,PARTTYPENAME,MOUNTPOINTS,PKNAME"
)
LSBLK_ARGV = ("lsblk", "-J", "-b", "-o", LSBLK_COLUMNS)

# Pontos de montagem que denunciam o disco do sistema.
SYSTEM_MOUNTS = ("/", "/boot", "/boot/efi", "/efi", "/usr", "/var", "/home", "/opt", "/srv")
# Ordem de preferência dos nomes estáveis em /dev/disk/by-id.
ID_PREFIXES = ("ata-", "nvme-", "usb-", "scsi-", "mmc-", "virtio-", "wwn-")
# Menor disco que faz sentido oferecer para guardar fotos.
MIN_SIZE = 8 * 1024**3

# Motivos que impedem o uso (códigos; o texto humano fica na interface).
REASONS = (
    "system",
    "swap",
    "mounted",
    "raid-member",
    "lvm",
    "luks",
    "in-use",
    "cloud",
    "database",
    "docker",
    "read-only",
    "too-small",
)


@dataclass(frozen=True)
class Partition:
    path: str
    size: int
    fstype: str = ""
    label: str = ""
    mountpoints: tuple[str, ...] = ()


@dataclass
class Disk:
    name: str  # sdb, nvme1n1
    path: str  # /dev/sdb (pode mudar no próximo boot!)
    size: int
    model: str = ""
    serial: str = ""
    transport: str = ""  # sata, nvme, usb…
    removable: bool = False
    rotational: bool = False
    read_only: bool = False
    by_id: str = ""  # /dev/disk/by-id/… (estável)
    fstype: str = ""  # assinatura no disco inteiro, sem partições
    partitions: list[Partition] = field(default_factory=list)
    mountpoints: list[str] = field(default_factory=list)  # de toda a árvore (partições, LUKS, LVM, md)
    reasons: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return not self.reasons

    @property
    def has_data(self) -> bool:
        return bool(self.fstype or self.partitions)

    @property
    def display_name(self) -> str:
        return self.model.strip() or self.name

    @property
    def kind(self) -> str:
        """usb | nvme | ssd | hdd"""
        if self.transport == "usb":
            return "usb"
        if self.transport == "nvme" or self.name.startswith("nvme"):
            return "nvme"
        return "hdd" if self.rotational else "ssd"


def _walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [node]
    for child in node.get("children") or []:
        nodes += _walk(child)
    return nodes


def _mounts(node: dict[str, Any]) -> list[str]:
    return [m for m in (node.get("mountpoints") or []) if m]


def owner_mount(path: str, mounts: list[str]) -> str:
    """O ponto de montagem mais específico que contém ``path``."""
    best = ""
    norm = os.path.normpath(path) if path else ""
    for mount in mounts:
        if mount.startswith("["):
            continue
        contains = norm == mount or norm.startswith(mount.rstrip("/") + "/") or mount == "/"
        if contains and len(mount) > len(best):
            best = mount
    return best


def parse_swaps(text: str) -> set[str]:
    return {line.split()[0] for line in text.splitlines()[1:] if line.strip()}


def stable_ids(entries: dict[str, str]) -> dict[str, str]:
    """{nome em by-id: alvo real} → {alvo real: melhor caminho by-id}."""
    best: dict[str, tuple[int, str]] = {}
    for name, target in entries.items():
        if "-part" in name or name.startswith("nvme-eui.") or name.startswith("nvme-nvme."):
            continue
        rank = next((i for i, p in enumerate(ID_PREFIXES) if name.startswith(p)), None)
        if rank is None:
            continue
        current = best.get(target)
        if current is None or rank < current[0]:
            best[target] = (rank, f"/dev/disk/by-id/{name}")
    return {target: path for target, (_rank, path) in best.items()}


def read_by_id(directory: str = "/dev/disk/by-id") -> dict[str, str]:
    try:
        names = os.listdir(directory)
    except OSError:
        return {}
    return {name: os.path.realpath(os.path.join(directory, name)) for name in names}


def holders(name: str, sys_block: str = "/sys/block") -> list[str]:
    """Quem usa o disco ou suas partições (dm, md…), segundo o kernel."""
    found: list[str] = []
    base = os.path.join(sys_block, name)
    candidates = [base]
    try:
        candidates += [os.path.join(base, entry) for entry in os.listdir(base) if entry.startswith(name)]
    except OSError:
        return found
    for path in candidates:
        try:
            found += os.listdir(os.path.join(path, "holders"))
        except OSError:
            continue
    return found


def inventory(
    lsblk: dict[str, Any],
    swaps: set[str] | None = None,
    by_id: dict[str, str] | None = None,
    protected: dict[str, str] | None = None,
    holders_of: dict[str, list[str]] | None = None,
) -> list[Disk]:
    """Discos inteiros e os motivos que impedem cada um de entrar num RAID.

    ``protected``: {"cloud": pasta das fotos, "database": pasta do banco, "docker": /var/lib/docker}.
    """
    swaps = swaps or set()
    by_id = by_id or {}
    protected = protected or {}
    holders_of = holders_of or {}
    devices = list(lsblk.get("blockdevices") or [])
    all_mounts = [m for dev in devices for node in _walk(dev) for m in _mounts(node)]
    protected_mounts = {key: owner_mount(path, all_mounts) for key, path in protected.items() if path}

    disks: list[Disk] = []
    for dev in devices:
        if dev.get("type") != "disk":
            continue
        tree = _walk(dev)
        mounts = sorted({m for node in tree for m in _mounts(node)})
        fstypes = {str(node.get("fstype") or "") for node in tree}
        types = {str(node.get("type") or "") for node in tree}
        disk = Disk(
            name=str(dev.get("name") or ""),
            path=str(dev.get("path") or ""),
            size=int(dev.get("size") or 0),
            model=str(dev.get("model") or ""),
            serial=str(dev.get("serial") or ""),
            transport=str(dev.get("tran") or ""),
            removable=bool(dev.get("rm")),
            rotational=bool(dev.get("rota")),
            read_only=bool(dev.get("ro")),
            by_id=by_id.get(str(dev.get("path") or ""), ""),
            fstype=str(dev.get("fstype") or ""),
            partitions=[
                Partition(
                    str(part.get("path") or ""),
                    int(part.get("size") or 0),
                    str(part.get("fstype") or ""),
                    str(part.get("label") or ""),
                    tuple(_mounts(part)),
                )
                for part in dev.get("children") or []
                if part.get("type") == "part"
            ],
            mountpoints=[m for m in mounts if not m.startswith("[")],
        )
        reasons: list[str] = []
        if any(m in SYSTEM_MOUNTS for m in mounts):
            reasons.append("system")
        paths = {str(node.get("path") or "") for node in tree}
        if "[SWAP]" in mounts or paths & swaps:
            reasons.append("swap")
        for key in ("cloud", "database", "docker"):
            mount = protected_mounts.get(key)
            if mount and mount in mounts:
                reasons.append(key)
        if disk.mountpoints and "system" not in reasons:
            reasons.append("mounted")
        if "linux_raid_member" in fstypes or any(t.startswith("raid") for t in types):
            reasons.append("raid-member")
        if "LVM2_member" in fstypes or "lvm" in types:
            reasons.append("lvm")
        if "crypto_LUKS" in fstypes or "crypt" in types:
            reasons.append("luks")
        if holders_of.get(disk.name) and not {"raid-member", "lvm", "luks"} & set(reasons):
            reasons.append("in-use")
        if disk.read_only:
            reasons.append("read-only")
        if disk.size < MIN_SIZE:
            reasons.append("too-small")
        disk.reasons = reasons
        disks.append(disk)
    return disks


def parse_lsblk(text: str) -> dict[str, Any]:
    data = json.loads(text or "{}")
    return data if isinstance(data, dict) else {}
