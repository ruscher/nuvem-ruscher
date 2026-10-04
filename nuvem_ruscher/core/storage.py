"""Detecção do disco de fotos (findmnt + lsblk) e avisos por sistema de arquivos."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from nuvem_ruscher.i18n import _

IMMICH_FOLDERS = ("library", "upload", "thumbs", "encoded-video", "profile", "backups")


class FsFamily(Enum):
    LINUX = "linux"
    NTFS = "ntfs"
    EXFAT = "exfat"
    FAT = "fat"
    OTHER = "other"


LINUX_FS = frozenset({"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "zfs", "bcachefs", "jfs"})
FS_DISPLAY = {
    "ntfs": "NTFS",
    "ntfs3": "NTFS",
    "exfat": "exFAT",
    "vfat": "FAT32",
    "msdos": "FAT",
    "ext4": "ext4",
    "ext3": "ext3",
    "btrfs": "Btrfs",
    "xfs": "XFS",
    "f2fs": "F2FS",
}


def fs_family(fstype: str) -> FsFamily:
    fstype = fstype.lower()
    if fstype in LINUX_FS:
        return FsFamily.LINUX
    if fstype in ("ntfs", "ntfs3", "ntfs-3g"):
        return FsFamily.NTFS
    if fstype == "exfat":
        return FsFamily.EXFAT
    if fstype in ("vfat", "fat", "fat32", "msdos"):
        return FsFamily.FAT
    return FsFamily.OTHER


@dataclass(frozen=True)
class MountInfo:
    target: str
    source: str
    fstype: str
    options: tuple[str, ...]


@dataclass
class Volume:
    """O disco (sistema de arquivos) onde a pasta das fotos está."""

    path: str  # pasta das fotos
    mountpoint: str
    device: str
    fstype: str  # tipo real (ntfs, ext4…), já traduzido de fuseblk
    uuid: str = ""
    label: str = ""
    size: int = 0
    available: int = 0
    used: int = 0
    removable: bool = False
    hotplug: bool = False
    rotational: bool = False
    transport: str = ""
    model: str = ""
    is_system_disk: bool = False

    @property
    def family(self) -> FsFamily:
        return fs_family(self.fstype)

    @property
    def display_name(self) -> str:
        if self.label:
            return self.label
        if self.model:
            return self.model
        return os.path.basename(self.device) or self.device

    @property
    def fs_display(self) -> str:
        return FS_DISPLAY.get(self.fstype.lower(), self.fstype or "?")

    @property
    def is_external(self) -> bool:
        return self.hotplug or self.removable or self.transport in ("usb", "ieee1394")

    @property
    def needs_boot_mount(self) -> bool:
        """Montado só pela sessão (udisks2) e fora do disco do sistema."""
        return not self.is_system_disk and self.mountpoint.startswith("/run/media/")


@dataclass(frozen=True)
class FsWarning:
    level: str  # "info" | "warning" | "error"
    title: str
    summary: str
    details: tuple[str, ...] = ()


@dataclass
class LibraryInfo:
    exists: bool
    folders: list[str] = field(default_factory=list)
    backups: list[str] = field(default_factory=list)
    other_entries: int = 0


def _first(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key) or []
    return value if isinstance(value, list) else []


def parse_findmnt(text: str) -> MountInfo:
    """Interpreta ``findmnt -J -T <caminho> -o TARGET,SOURCE,FSTYPE,OPTIONS``."""
    entries = _first(json.loads(text), "filesystems")
    if not entries:
        raise ValueError("findmnt não retornou sistemas de arquivos")
    fs = entries[0]
    source = str(fs.get("source") or "")
    # btrfs: "/dev/nvme0n1p2[/@home]" → "/dev/nvme0n1p2"
    if "[" in source and source.endswith("]"):
        source = source[: source.index("[")]
    options = tuple(o for o in str(fs.get("options") or "").split(",") if o)
    return MountInfo(str(fs.get("target") or ""), source, str(fs.get("fstype") or ""), options)


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip() in ("1", "true")
    return bool(value)


def parse_lsblk(text: str) -> dict[str, Any]:
    """Primeiro dispositivo de ``lsblk -J -b ...``; dicionário vazio se nada."""
    devices = _first(json.loads(text), "blockdevices")
    return devices[0] if devices else {}


def build_volume(
    path: str,
    mount: MountInfo,
    part: dict[str, Any],
    parent: dict[str, Any] | None = None,
    system_sources: frozenset[str] = frozenset(),
) -> Volume:
    """Junta findmnt + lsblk (partição e disco-pai) num ``Volume``."""
    parent = parent or {}
    fstype = str(part.get("fstype") or mount.fstype)
    if fstype == "fuseblk":
        fstype = "ntfs"
    return Volume(
        path=path,
        mountpoint=mount.target,
        device=mount.source,
        fstype=fstype,
        uuid=str(part.get("uuid") or ""),
        label=str(part.get("label") or "").strip(),
        size=_to_int(part.get("size")),
        available=_to_int(part.get("fsavail")),
        used=_to_int(part.get("fsused")),
        removable=_to_bool(parent.get("rm", part.get("rm"))),
        hotplug=_to_bool(parent.get("hotplug", part.get("hotplug"))),
        rotational=_to_bool(parent.get("rota", part.get("rota"))),
        transport=str(parent.get("tran") or part.get("tran") or ""),
        model=" ".join(
            str(x).strip() for x in (parent.get("vendor"), parent.get("model")) if x and str(x).strip()
        ),
        is_system_disk=mount.target == "/" or mount.source in system_sources,
    )


def fs_warnings(volume: Volume) -> list[FsWarning]:
    """Avisos honestos e amigáveis sobre o sistema de arquivos das fotos."""
    family = volume.family
    db_note = _(
        "O banco de dados do Immich não fica nesse disco: ele vai para o disco interno, "
        "como a documentação oficial exige."
    )
    safe_remove = _(
        "Use “Remover com segurança” antes de desconectar o disco (ou desligue o computador). "
        "Desligamentos bruscos podem corromper arquivos."
    )
    if family is FsFamily.NTFS:
        return [
            FsWarning(
                "warning",
                _("Disco formatado no Windows (NTFS)"),
                _("Funciona bem para guardar fotos. Só pedimos três cuidados."),
                (
                    safe_remove,
                    _(
                        "Se você usa esse disco no Windows, desative lá a “Inicialização rápida”; "
                        "senão o Linux pode abri-lo apenas para leitura."
                    ),
                    _(
                        "Ele é um pouco mais lento que um disco formatado para Linux: "
                        "as miniaturas podem demorar mais na primeira vez."
                    ),
                    db_note,
                ),
            )
        ]
    if family is FsFamily.EXFAT:
        return [
            FsWarning(
                "warning",
                _("Disco no formato exFAT"),
                _("Funciona para guardar fotos, com dois cuidados."),
                (
                    safe_remove,
                    _("O exFAT não tem diário (journal): falhas de energia são mais arriscadas."),
                    db_note,
                ),
            )
        ]
    if family is FsFamily.FAT:
        return [
            FsWarning(
                "error",
                _("Este disco não aceita arquivos maiores que 4 GB"),
                _(
                    "Ele está no formato FAT32. Fotos funcionam, mas vídeos longos não serão salvos. "
                    "Se puder, escolha outro disco."
                ),
                (safe_remove, db_note),
            )
        ]
    if family is FsFamily.OTHER:
        return [
            FsWarning(
                "warning",
                _("Sistema de arquivos pouco comum ({fs})").format(fs=volume.fstype or "?"),
                _("Não testamos esse formato. Pode funcionar, mas prefira ext4, Btrfs ou NTFS."),
                (db_note,),
            )
        ]
    return []


def detect_library(path: str) -> LibraryInfo:
    """Procura uma biblioteca do Immich existente (arquivos ``.immich``). Só lê."""
    base = Path(path)
    if not base.is_dir():
        return LibraryInfo(False)
    folders = [name for name in IMMICH_FOLDERS if (base / name / ".immich").is_file()]
    backups: list[str] = []
    backup_dir = base / "backups"
    if backup_dir.is_dir():
        try:
            backups = sorted(p.name for p in backup_dir.iterdir() if p.name.endswith(".sql.gz"))
        except OSError:
            backups = []
    try:
        other = sum(1 for p in base.iterdir() if p.name not in IMMICH_FOLDERS)
    except OSError:
        other = 0
    return LibraryInfo(bool(folders), folders, backups, other)


def human_size(num_bytes: float) -> str:
    """Tamanho legível em pt-BR (base 1000, como os gerenciadores de arquivos)."""
    units = ("B", "kB", "MB", "GB", "TB", "PB")
    value = float(num_bytes)
    for unit in units:
        if abs(value) < 1000 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            text = f"{value:.1f}" if value < 100 else f"{value:.0f}"
            return f"{text.replace('.', ',')} {unit}"
        value /= 1000
    return f"{value} PB"  # pragma: no cover


def suggest_photo_folder(user: str, mounts: list[tuple[str, int]]) -> str | None:
    """Sugere a pasta das fotos.

    ``mounts``: lista de (ponto de montagem em /run/media/<user>, bytes livres).
    Preferência: uma pasta ``immich-<user>`` já existente; senão, o disco com mais
    espaço livre.
    """
    if not mounts:
        return None
    folder = f"immich-{user}"
    for mountpoint, _free in mounts:
        if os.path.isdir(os.path.join(mountpoint, folder)):
            return os.path.join(mountpoint, folder)
    best = max(mounts, key=lambda m: m[1])[0]
    return os.path.join(best, folder)
