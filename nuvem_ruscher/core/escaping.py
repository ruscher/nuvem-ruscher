"""Escapes para fstab e systemd — o lugar onde “Novo volume” costuma quebrar tudo."""

from __future__ import annotations

from nuvem_ruscher.core.validation import FORBIDDEN_PATH_CHARS

_FSTAB_ESCAPES = {" ": r"\040", "\t": r"\011", "\n": r"\012", "\\": r"\134"}


def fstab_escape(path: str) -> str:
    """Escapa um caminho para uso no fstab (espaço vira ``\\040``)."""
    return "".join(_FSTAB_ESCAPES.get(c, c) for c in path)


def fstab_unescape(field: str) -> str:
    """Desfaz os escapes octais ``\\NNN`` usados pelo fstab/mtab."""
    out = bytearray()
    raw = field.encode()
    i = 0
    while i < len(raw):
        chunk = raw[i : i + 4]
        if len(chunk) == 4 and chunk[0] == 0x5C and all(0x30 <= b <= 0x37 for b in chunk[1:]):
            out.append(int(chunk[1:].decode(), 8))
            i += 4
        else:
            out.append(raw[i])
            i += 1
    return out.decode(errors="replace")


def systemd_quote(path: str) -> str:
    """Coloca um caminho entre aspas para diretivas do systemd que aceitam listas.

    Só aceita caminhos já validados (sem aspas, barra invertida ou ``%``).
    """
    if FORBIDDEN_PATH_CHARS.intersection(path) or "\n" in path:
        raise ValueError(f"caminho impróprio para o systemd: {path!r}")
    return f'"{path}"'


def systemd_escape_path(path: str) -> str:
    """Implementa ``systemd-escape --path``."""
    trimmed = "/".join(p for p in path.split("/") if p)
    if not trimmed:
        return "-"
    out: list[str] = []
    for index, byte in enumerate(trimmed.encode()):
        char = chr(byte)
        if char == "/":
            out.append("-")
        elif byte < 0x80 and (char.isalnum() or char in ":_.") and not (index == 0 and char == "."):
            out.append(char)
        else:
            out.append(f"\\x{byte:02x}")
    return "".join(out)


def mount_unit_name(mountpoint: str) -> str:
    """Nome da unidade de montagem do systemd para um ponto de montagem."""
    return systemd_escape_path(mountpoint) + ".mount"
