"""Planejar a troca do local das fotos (doc 08). Só leitura: quem copia é o helper.

``assess`` é puro (recebe fatos, devolve o plano) para ser testado sem disco nenhum.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

from nuvem_ruscher.core.storage import FsFamily, fs_family
from nuvem_ruscher.core.validation import ValidationError, validate_photo_path

# Pastas que o Immich cria e marca com ".immich" (o servidor recusa subir sem elas).
IMMICH_FOLDERS = ("library", "upload", "thumbs", "encoded-video", "profile", "backups")
MARKER = ".immich"
MIGRATION_MARKER = ".nuvem-ruscher-migration"
STATE_FILE = "/var/lib/nuvem-ruscher/migration.state"
FAT_MAX_FILE = 4 * 1024**3 - 1
SPACE_MARGIN = 1024**3  # 1 GiB além de 2 %


class Mode(Enum):
    COPY = "copy"  # copia, verifica, troca; a origem continua lá
    RENAME = "rename"  # mesmo sistema de arquivos: renomeia a pasta (instantâneo)
    ADOPT = "adopt"  # o destino já tem a biblioteca: só troca o local


@dataclass
class TreeStats:
    files: int = 0
    bytes: int = 0
    symlinks: int = 0
    largest: int = 0
    markers: set[str] = field(default_factory=set)  # pastas do Immich com ".immich"
    errors: int = 0  # entradas que não deu para ler


@dataclass
class Destination:
    path: str
    exists: bool = False
    is_dir: bool = False
    empty: bool = True
    parent_exists: bool = True
    mountpoint: str = ""
    fstype: str = ""
    read_only: bool = False
    free: int = 0
    total: int = 0
    same_fs: bool = False  # mesmo sistema de arquivos da origem
    symlink_in_path: bool = False
    removable: bool = False
    system_disk: bool = False
    markers: set[str] = field(default_factory=set)
    files: int = 0  # só quando o destino já tem uma biblioteca (adotar)
    resumable_from: str = ""  # cópia interrompida desta origem


@dataclass
class MigrationPlan:
    source: str
    dest: str
    mode: Mode
    stats: TreeStats
    destination: Destination
    problems: list[str] = field(default_factory=list)  # bloqueiam
    warnings: list[str] = field(default_factory=list)  # avisam
    modes: list[Mode] = field(default_factory=list)  # possíveis para este destino
    invalid_message: str = ""  # texto humano quando o caminho não passa na validação

    @property
    def can_start(self) -> bool:
        return not self.problems

    @property
    def need_bytes(self) -> int:
        return space_needed(self.stats.bytes) if self.mode is Mode.COPY else 0


def space_needed(size: int) -> int:
    return int(size * 1.02) + SPACE_MARGIN


def inside(child: str, parent: str) -> bool:
    child = os.path.normpath(child)
    parent = os.path.normpath(parent)
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def scan_tree(root: str, should_stop: object = None) -> TreeStats:
    """Conta arquivos e bytes sem seguir links (pode levar alguns segundos em bibliotecas grandes)."""
    stats = TreeStats()
    for folder in IMMICH_FOLDERS:
        if os.path.isfile(os.path.join(root, folder, MARKER)):
            stats.markers.add(folder)
    stack = [root]
    while stack:
        if callable(should_stop) and should_stop():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            stats.symlinks += 1
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            size = entry.stat(follow_symlinks=False).st_size
                            stats.files += 1
                            stats.bytes += size
                            stats.largest = max(stats.largest, size)
                    except OSError:
                        stats.errors += 1
        except OSError:
            stats.errors += 1
    return stats


def available_modes(destination: Destination, stats: TreeStats) -> list[Mode]:
    modes = []
    if destination.markers and destination.markers >= stats.markers:
        modes.append(Mode.ADOPT)
    if destination.same_fs and not destination.exists:
        modes.append(Mode.RENAME)
    modes.append(Mode.COPY)
    return modes


def recommended_mode(destination: Destination, stats: TreeStats) -> Mode:
    modes = available_modes(destination, stats)
    if Mode.ADOPT in modes:
        return Mode.ADOPT
    if Mode.RENAME in modes:
        return Mode.RENAME
    return Mode.COPY


def assess(
    source: str, dest: str, stats: TreeStats, destination: Destination, mode: Mode | None = None
) -> MigrationPlan:
    modes = available_modes(destination, stats)
    chosen = mode or recommended_mode(destination, stats)
    plan = MigrationPlan(source, dest, chosen, stats, destination, modes=modes)
    problems, warnings = plan.problems, plan.warnings

    try:
        validate_photo_path(dest)
    except ValidationError as exc:
        problems.append("invalid")
        plan.invalid_message = str(exc)
        return plan
    if os.path.normpath(source) == os.path.normpath(dest):
        problems.append("same-path")
        return plan
    if inside(dest, source):
        problems.append("dest-inside-source")
    if inside(source, dest):
        problems.append("source-inside-dest")
    if not destination.parent_exists:
        problems.append("dest-missing")
    if destination.symlink_in_path:
        problems.append("dest-symlink")
    if destination.exists and not destination.is_dir:
        problems.append("dest-not-folder")
    if destination.read_only:
        problems.append("dest-read-only")
    if chosen not in modes:
        problems.append(f"mode-unavailable:{chosen.value}")

    family = fs_family(destination.fstype)
    if chosen is Mode.COPY:
        if destination.exists and not destination.empty and destination.resumable_from != source:
            problems.append("dest-not-empty")
        # Espaço livre 0 (disco cheio, ou statvfs falhou) também recusa: sem saber, não começa.
        if destination.parent_exists and destination.free < space_needed(stats.bytes):
            problems.append("no-space")
        if family is FsFamily.FAT and stats.largest > FAT_MAX_FILE:
            problems.append("fat-large-file")
        if stats.symlinks and family in (FsFamily.FAT, FsFamily.EXFAT, FsFamily.NTFS):
            problems.append("symlinks-unsupported")
        if destination.same_fs:
            warnings.append("same-fs-copy")
        if destination.resumable_from == source:
            warnings.append("resume")
    # Mesma regra do helper (mig_check_adopt): menos de 98% dos arquivos não é uma cópia completa.
    if chosen is Mode.ADOPT and stats.files and destination.files < stats.files * 0.98:
        problems.append("adopt-incomplete")
    if stats.errors:
        warnings.append("source-unreadable-entries")

    if family is FsFamily.NTFS:
        warnings.append("dest-ntfs")
    elif family is FsFamily.EXFAT:
        warnings.append("dest-exfat")
    elif family is FsFamily.FAT:
        warnings.append("dest-fat")
    if destination.removable:
        warnings.append("dest-removable")
    if destination.system_disk:
        warnings.append("dest-system-disk")
    return plan


@dataclass
class MigrationState:
    """``/var/lib/nuvem-ruscher/migration.state``, escrito pelo helper (KEY=valor)."""

    state: str = ""  # running | migrated | rolled-back | failed | cancelled | removed-old
    step: str = ""
    mode: str = ""
    old: str = ""
    new: str = ""
    files: int = 0
    bytes: int = 0
    started: str = ""
    finished: str = ""
    error: str = ""

    @property
    def finished_ok(self) -> bool:
        return self.state == "migrated"


def parse_state(text: str) -> MigrationState:
    raw: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            raw[key.strip()] = value
    state = MigrationState(
        state=raw.get("STATE", ""),
        step=raw.get("STEP", ""),
        mode=raw.get("MODE", ""),
        old=raw.get("OLD", ""),
        new=raw.get("NEW", ""),
        started=raw.get("STARTED", ""),
        finished=raw.get("FINISHED", ""),
        error=raw.get("ERROR", ""),
    )
    for key in ("files", "bytes"):
        try:
            setattr(state, key, int(raw.get(key.upper(), "0") or 0))
        except ValueError:
            pass
    return state


def read_state(path: str = STATE_FILE) -> MigrationState | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return parse_state(handle.read())
    except OSError:
        return None
