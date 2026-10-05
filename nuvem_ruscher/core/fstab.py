"""fstab: prévia da linha que o helper vai escrever e leitura de entradas existentes.

O helper é a fonte da verdade (ele relê o tipo do disco com ``blkid``); esta
implementação existe para mostrar a linha exata em “Detalhes técnicos” e é
comparada com a do helper nos testes.
"""

from __future__ import annotations

from dataclasses import dataclass

from nuvem_ruscher.core.escaping import fstab_escape, fstab_unescape, systemd_escape_path
from nuvem_ruscher.core.storage import FsFamily, fs_family

MARKER = "# Nuvem Ruscher: disco de fotos do Immich"
COMMON_OPTIONS = ("defaults", "nofail", "nosuid", "nodev", "x-systemd.device-timeout=15s")


@dataclass(frozen=True)
class FstabEntry:
    source: str
    target: str
    fstype: str
    options: str
    dump: str = "0"
    passno: str = "0"


def device_unit(uuid: str) -> str:
    return systemd_escape_path(f"/dev/disk/by-uuid/{uuid}") + ".device"


def mount_spec(fstype: str, uid: int, gid: int, uuid: str = "") -> tuple[str, list[str], int]:
    """Tipo, opções e passo de fsck para o sistema de arquivos detectado.

    Com ``uuid``, acrescenta ``x-systemd.wanted-by=<dispositivo>``: o systemd monta o disco
    quando ele aparece (no boot ou conectado depois).
    """
    family = fs_family(fstype)
    options = list(COMMON_OPTIONS)
    if uuid:
        options.append(f"x-systemd.wanted-by={device_unit(uuid)}")
    owner = [f"uid={uid}", f"gid={gid}", "dmask=022", "fmask=133"]
    if family is FsFamily.NTFS:
        return "ntfs-3g", [*options, *owner, "windows_names"], 0
    if family is FsFamily.EXFAT:
        return "exfat", [*options, *owner], 0
    if family is FsFamily.FAT:
        return "vfat", [*options, *owner, "utf8", "shortname=mixed"], 0
    if fstype == "btrfs":
        return "btrfs", [*options, "noatime"], 0
    if family is FsFamily.LINUX:
        return fstype, [*options, "noatime"], 2
    raise ValueError(f"file system not supported for automatic mounting: {fstype}")


def fstab_line(uuid: str, mountpoint: str, fstype: str, uid: int, gid: int) -> str:
    kind, options, passno = mount_spec(fstype, uid, gid, uuid)
    return f"UUID={uuid} {fstab_escape(mountpoint)} {kind} {','.join(options)} 0 {passno}"


def parse_fstab(text: str) -> list[FstabEntry]:
    entries: list[FstabEntry] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 4:
            continue
        dump = fields[4] if len(fields) > 4 else "0"
        passno = fields[5] if len(fields) > 5 else "0"
        entries.append(FstabEntry(fields[0], fstab_unescape(fields[1]), fields[2], fields[3], dump, passno))
    return entries


def find_entry(entries: list[FstabEntry], uuid: str, mountpoint: str) -> FstabEntry | None:
    """Entrada que já cuida desse disco ou desse ponto de montagem."""
    for entry in entries:
        if entry.source in (f"UUID={uuid}", f"/dev/disk/by-uuid/{uuid}") or entry.target == mountpoint:
            return entry
    return None


def is_ours(text: str, uuid: str) -> bool:
    """Se a entrada desse UUID foi escrita pelo Nuvem Ruscher (comentário marcador)."""
    previous = ""
    for line in text.splitlines():
        if line.startswith(f"UUID={uuid} ") and previous.startswith(MARKER):
            return True
        previous = line
    return False
