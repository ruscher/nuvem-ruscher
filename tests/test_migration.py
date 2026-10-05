"""Planejamento da troca de local das fotos: todos os bloqueios antes de copiar um byte."""

import pytest

from nuvem_ruscher.core import migration
from nuvem_ruscher.core.migration import Destination, Mode, TreeStats

SRC = "/run/media/maria/HD1/Nuvem"
DST = "/run/media/maria/HD2/Nuvem"
GB = 1000**3
ALL = set(migration.IMMICH_FOLDERS)


def stats(**kw):
    base = {"files": 183542, "bytes": 842 * GB, "largest": 2 * GB, "markers": set(ALL)}
    base.update(kw)
    return TreeStats(**base)


def dest(**kw):
    base = {"path": DST, "fstype": "ext4", "free": 1700 * GB, "total": 2000 * GB, "mountpoint": "/run/media/maria/HD2"}
    base.update(kw)
    return Destination(**base)


def plan(dst=DST, st=None, de=None, mode=None, src=SRC):
    return migration.assess(src, dst, st or stats(), de or dest(path=dst), mode)


def test_happy_copy_to_another_disk():
    p = plan()
    assert p.mode is Mode.COPY
    assert p.can_start, p.problems
    assert p.warnings == []
    assert p.need_bytes == int(842 * GB * 1.02) + 1024**3


@pytest.mark.parametrize(
    ("dst", "problem"),
    [
        (SRC, "same-path"),
        (SRC + "/novo", "dest-inside-source"),
        ("/run/media/maria/HD1", "source-inside-dest"),
    ],
)
def test_nested_or_same_paths(dst, problem):
    assert problem in plan(dst).problems


@pytest.mark.parametrize("dst", ["/", "/home", "/usr/x", "/etc/fotos", "/var/lib/docker/x", "relativo", "/tmp/x"])
def test_dangerous_destinations_rejected(dst):
    p = plan(dst)
    assert p.problems == ["invalid"]
    assert p.invalid_message


def test_insufficient_space():
    assert "no-space" in plan(de=dest(free=800 * GB)).problems


def test_disk_not_connected():
    assert "dest-missing" in plan(de=dest(parent_exists=False)).problems


def test_read_only_destination():
    assert "dest-read-only" in plan(de=dest(read_only=True)).problems


def test_non_empty_destination_blocks_copy_but_resume_is_ok():
    assert "dest-not-empty" in plan(de=dest(exists=True, is_dir=True, empty=False)).problems
    resumed = plan(de=dest(exists=True, is_dir=True, empty=False, resumable_from=SRC))
    assert resumed.can_start
    assert "resume" in resumed.warnings
    other = plan(de=dest(exists=True, is_dir=True, empty=False, resumable_from="/outra"))
    assert "dest-not-empty" in other.problems


def test_fat32_large_files_and_symlinks():
    assert "fat-large-file" in plan(st=stats(largest=5 * GB), de=dest(fstype="vfat")).problems
    assert "symlinks-unsupported" in plan(st=stats(symlinks=3), de=dest(fstype="exfat")).problems
    assert "symlinks-unsupported" not in plan(st=stats(symlinks=3), de=dest(fstype="ext4")).problems


def test_same_filesystem_prefers_rename():
    p = plan(de=dest(same_fs=True))
    assert p.mode is Mode.RENAME
    assert p.can_start
    assert p.need_bytes == 0
    # Mesmo disco sem espaço para duplicar: copiar não dá, renomear dá.
    copy = plan(de=dest(same_fs=True, free=100 * GB), mode=Mode.COPY)
    assert "no-space" in copy.problems and "same-fs-copy" in copy.warnings


def test_adopt_requires_a_complete_library():
    complete = plan(de=dest(exists=True, is_dir=True, empty=False, markers=set(ALL), files=183542))
    assert complete.mode is Mode.ADOPT and complete.can_start
    # Sem biblioteca no destino, "usar sem mover" não existe: o banco apontaria para o vazio.
    empty = plan(mode=Mode.ADOPT)
    assert "mode-unavailable:adopt" in empty.problems
    partial = plan(de=dest(exists=True, is_dir=True, empty=False, markers={"upload"}), mode=Mode.ADOPT)
    assert "mode-unavailable:adopt" in partial.problems
    fewer = plan(de=dest(exists=True, is_dir=True, empty=False, markers=set(ALL), files=1000))
    assert "adopt-incomplete" in fewer.problems and not fewer.can_start


def test_filesystem_warnings():
    assert "dest-ntfs" in plan(de=dest(fstype="ntfs")).warnings
    assert "dest-removable" in plan(de=dest(removable=True)).warnings
    assert "dest-system-disk" in plan(de=dest(system_disk=True)).warnings


def test_rename_unavailable_across_filesystems():
    assert "mode-unavailable:rename" in plan(mode=Mode.RENAME).problems


def test_scan_tree_counts_without_following_links(tmp_path):
    root = tmp_path / "Nuvem com espaço"
    for folder in ("upload", "library"):
        (root / folder).mkdir(parents=True)
        (root / folder / ".immich").write_text("")
    (root / "library" / "ação ü.jpg").write_bytes(b"x" * 1000)
    (root / "upload" / "v.mp4").write_bytes(b"y" * 5000)
    outside = tmp_path / "fora"
    outside.mkdir()
    (outside / "grande").write_bytes(b"z" * 100000)
    (root / "library" / "atalho").symlink_to(outside)
    st = migration.scan_tree(str(root))
    assert st.files == 4  # dois .immich + duas mídias
    assert st.bytes == 6000
    assert st.symlinks == 1
    assert st.largest == 5000
    assert st.markers == {"upload", "library"}


def test_state_file():
    text = "STATE=migrated\nOLD=/run/media/maria/HD1/Nuvem\nNEW=/x/y z\nFILES=12\nBYTES=34\nERROR=\n"
    st = migration.parse_state(text)
    assert st.finished_ok and (st.files, st.bytes, st.new) == (12, 34, "/x/y z")
    assert migration.read_state("/nao/existe") is None


def test_unknown_or_zero_free_space_blocks():
    # statvfs falhou ou o disco está cheio: sem espaço conhecido, a cópia não começa.
    assert "no-space" in plan(de=dest(free=0)).problems
