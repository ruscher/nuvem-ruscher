import shutil
import subprocess

import pytest
from conftest import MOUNTPOINT, PHOTO_PATH, fixture_text

from nuvem_ruscher.core import fstab, storage
from nuvem_ruscher.core.storage import FsFamily


def ntfs_volume():
    mount = storage.parse_findmnt(fixture_text("findmnt-ntfs.json"))
    part = storage.parse_lsblk(fixture_text("lsblk-ntfs.json"))
    parent = storage.parse_lsblk(fixture_text("lsblk-ntfs-parent.json"))
    return storage.build_volume(PHOTO_PATH, mount, part, parent)


def test_findmnt_and_lsblk_real_output():
    vol = ntfs_volume()
    assert vol.mountpoint == MOUNTPOINT
    assert vol.device == "/dev/sdd1"
    assert vol.fstype == "ntfs"  # fuseblk traduzido
    assert vol.family is FsFamily.NTFS
    assert vol.uuid == "F22A6D342A6CF74F"
    assert vol.label == "Novo volume"
    assert vol.display_name == "Novo volume"
    assert vol.size == 2000397795328
    assert vol.available == 1986854027264
    assert vol.transport == "usb"
    assert vol.is_external
    assert vol.model == "SanDisk Portable SSD"
    assert vol.needs_boot_mount
    assert not vol.is_system_disk


def test_btrfs_subvolume_source():
    text = (
        '{"filesystems":[{"target":"/home","source":"/dev/nvme0n1p2[/@home]","fstype":"btrfs","options":"rw,noatime"}]}'
    )
    mount = storage.parse_findmnt(text)
    assert mount.source == "/dev/nvme0n1p2"
    assert mount.options == ("rw", "noatime")


@pytest.mark.parametrize(
    ("fstype", "family", "level"),
    [
        ("ntfs", FsFamily.NTFS, "warning"),
        ("exfat", FsFamily.EXFAT, "warning"),
        ("vfat", FsFamily.FAT, "error"),
        ("ext4", FsFamily.LINUX, None),
        ("btrfs", FsFamily.LINUX, None),
        ("zzfs", FsFamily.OTHER, "warning"),
    ],
)
def test_fs_warnings(fstype, family, level):
    vol = storage.Volume(PHOTO_PATH, MOUNTPOINT, "/dev/x", fstype)
    assert vol.family is family
    warnings = storage.fs_warnings(vol)
    if level is None:
        assert warnings == []
    else:
        assert warnings[0].level == level
        # O aviso sempre lembra que o banco não vai para esse disco.
        assert any("banco de dados" in d for d in warnings[0].details)


def test_fat32_mentions_4gb():
    vol = storage.Volume(PHOTO_PATH, MOUNTPOINT, "/dev/x", "vfat")
    assert "4 GB" in storage.fs_warnings(vol)[0].title


def test_detect_library(tmp_path):
    lib = tmp_path / "Novo volume" / "immich-ruscher"
    assert not storage.detect_library(str(lib)).exists
    lib.mkdir(parents=True)
    assert not storage.detect_library(str(lib)).exists
    for name in ("library", "upload", "backups"):
        (lib / name).mkdir()
        (lib / name / ".immich").write_text("")
    (lib / "backups" / "immich-db-backup-20261001T020000-v3.2.4-pg14.19.sql.gz").write_bytes(b"x")
    info = storage.detect_library(str(lib))
    assert info.exists
    assert info.folders == ["library", "upload", "backups"]
    assert len(info.backups) == 1


def test_human_size():
    assert storage.human_size(0) == "0 B"
    assert storage.human_size(1986854027264) == "2,0 TB"
    assert storage.human_size(410_500_000) == "410 MB"
    assert storage.human_size(1_500_000_000) == "1,5 GB"


def test_suggest_photo_folder(tmp_path):
    big = tmp_path / "Novo volume"
    small = tmp_path / "Pendrive"
    big.mkdir()
    small.mkdir()
    mounts = [(str(small), 10), (str(big), 1000)]
    assert storage.suggest_photo_folder("ruscher", mounts) == str(big / "immich-ruscher")
    (small / "immich-ruscher").mkdir()
    assert storage.suggest_photo_folder("ruscher", mounts) == str(small / "immich-ruscher")
    assert storage.suggest_photo_folder("ruscher", []) is None


class TestFstab:
    def test_ntfs_line(self):
        line = fstab.fstab_line("F22A6D342A6CF74F", MOUNTPOINT, "ntfs", 1000, 1007)
        assert line == (
            "UUID=F22A6D342A6CF74F /run/media/ruscher/Novo\\040volume ntfs-3g "
            "defaults,nofail,nosuid,nodev,x-systemd.device-timeout=15s,"
            "uid=1000,gid=1007,dmask=022,fmask=133,windows_names 0 0"
        )

    @pytest.mark.parametrize(
        ("fstype", "kind", "passno"),
        [
            ("exfat", "exfat", 0),
            ("vfat", "vfat", 0),
            ("ext4", "ext4", 2),
            ("btrfs", "btrfs", 0),
            ("xfs", "xfs", 2),
        ],
    )
    def test_other_filesystems(self, fstype, kind, passno):
        kind_out, options, passno_out = fstab.mount_spec(fstype, 1000, 1000)
        assert kind_out == kind
        assert passno_out == passno
        assert "nofail" in options

    def test_unsupported(self):
        with pytest.raises(ValueError):
            fstab.mount_spec("iso9660", 1000, 1000)

    def test_parse_and_find(self):
        text = fixture_text("fstab-biglinux.txt")
        text += "\n" + fstab.MARKER + "\n" + fstab.fstab_line("F22A6D342A6CF74F", MOUNTPOINT, "ntfs", 1000, 1007)
        entries = fstab.parse_fstab(text)
        found = fstab.find_entry(entries, "F22A6D342A6CF74F", MOUNTPOINT)
        assert found is not None
        assert found.target == MOUNTPOINT
        assert fstab.is_ours(text, "F22A6D342A6CF74F")
        assert fstab.find_entry(entries, "DEADBEEF", "/mnt/x") is None

    @pytest.mark.skipif(not shutil.which("findmnt"), reason="findmnt ausente")
    def test_findmnt_reads_escaped_target(self, tmp_path):
        tab = tmp_path / "fstab"
        tab.write_text(fstab.fstab_line("F22A6D342A6CF74F", MOUNTPOINT, "ntfs", 1000, 1007) + "\n")
        out = subprocess.run(
            ["findmnt", "--tab-file", str(tab), "-n", "-o", "TARGET", "-S", "UUID=F22A6D342A6CF74F"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert out == MOUNTPOINT
