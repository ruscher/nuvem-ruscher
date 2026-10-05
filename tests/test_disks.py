"""Inventário de discos: o que pode ou não entrar num RAID novo (só leitura)."""

import json

from conftest import FIXTURES

from nuvem_ruscher.core import disks

LSBLK = json.loads((FIXTURES / "lsblk-disks.json").read_text())
PROTECTED = {
    "cloud": "/run/media/maria/Fotos/immich",
    "database": "/var/lib/nuvem-ruscher/immich/postgres",
    "docker": "/var/lib/docker",
}
BY_ID = {
    "ata-Exemplo_SSD_1TB_LIVRE-0003": "/dev/sdb",
    "wwn-0x5000000000000003": "/dev/sdb",
    "ata-Exemplo_HDD_4TB_VELHO-0004": "/dev/sdc",
    "ata-Exemplo_HDD_4TB_VELHO-0004-part1": "/dev/sdc1",
    "nvme-eui.0000000000000001": "/dev/nvme0n1",
    "nvme-Exemplo_NVMe_1TB_SYS-0001": "/dev/nvme0n1",
}


def inv(**kw):
    found = disks.inventory(LSBLK, swaps={"/dev/zram0"}, by_id=disks.stable_ids(BY_ID), protected=PROTECTED, **kw)
    return {d.name: d for d in found}


def test_only_whole_disks_are_listed():
    names = set(inv())
    assert "loop0" not in names
    assert {"nvme0n1", "sda", "sdb", "sdc", "sdd", "sde", "sdf", "sdg", "sdh"} <= names


def test_system_disk_is_protected_even_behind_luks():
    d = inv()["nvme0n1"]
    assert "system" in d.reasons
    assert "luks" in d.reasons
    assert not d.available


def test_available_blank_and_old_data():
    found = inv()
    assert found["sdb"].available and not found["sdb"].has_data
    assert found["sdc"].available and found["sdc"].has_data
    assert found["sdc"].partitions[0].fstype == "ntfs"


def test_cloud_database_docker_and_mounted():
    found = inv()
    assert {"cloud", "mounted"} <= set(found["sdd"].reasons)
    # banco e Docker ficam no "/" (disco do sistema)
    assert {"system", "database", "docker"} <= set(found["nvme0n1"].reasons)
    assert found["sda"].reasons == ["mounted"]


def test_raid_lvm_swap_small():
    found = inv()
    assert "raid-member" in found["sde"].reasons
    assert "lvm" in found["sdh"].reasons
    assert "swap" in found["sdf"].reasons
    assert "too-small" in found["sdg"].reasons
    assert "swap" in found["zram0"].reasons


def test_holders_mark_disk_in_use():
    found = inv(holders_of={"sdb": ["dm-3"]})
    assert found["sdb"].reasons == ["in-use"]


def test_stable_ids_prefer_ata_over_wwn_and_skip_partitions():
    ids = disks.stable_ids(BY_ID)
    assert ids["/dev/sdb"] == "/dev/disk/by-id/ata-Exemplo_SSD_1TB_LIVRE-0003"
    assert ids["/dev/nvme0n1"] == "/dev/disk/by-id/nvme-Exemplo_NVMe_1TB_SYS-0001"
    assert "/dev/sdc1" not in ids
    assert inv()["sdb"].by_id.endswith("LIVRE-0003")


def test_owner_mount():
    mounts = ["/", "/home", "/run/media/maria/Fotos", "[SWAP]"]
    assert disks.owner_mount("/run/media/maria/Fotos/immich", mounts) == "/run/media/maria/Fotos"
    assert disks.owner_mount("/home/maria/x", mounts) == "/home"
    assert disks.owner_mount("/var/lib/docker", mounts) == "/"
    assert disks.owner_mount("/run/media/maria/FotosX", mounts) == "/"


def test_parse_swaps():
    text = "Filename\tType\tSize\tUsed\tPriority\n/dev/sdf1  partition 100 0 -1\n/swapfile file 1 0 -2\n"
    assert disks.parse_swaps(text) == {"/dev/sdf1", "/swapfile"}


def test_kind():
    found = inv()
    assert (found["nvme0n1"].kind, found["sdd"].kind, found["sda"].kind, found["sdb"].kind) == (
        "nvme",
        "usb",
        "hdd",
        "ssd",
    )
