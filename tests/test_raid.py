"""Estado do RAID por /proc/mdstat (sem root, sem criar arrays de verdade)."""

import pytest

from nuvem_ruscher.core import raid
from nuvem_ruscher.core.raid import RaidState

HEALTHY = """Personalities : [raid1] [raid6] [raid5] [raid4]
md127 : active raid1 sdc1[1] sdb1[0]
      1953382464 blocks super 1.2 [2/2] [UU]
      bitmap: 0/15 pages [0KB], 65536KB chunk

unused devices: <none>
"""

REBUILDING = """Personalities : [raid1]
md126 : active raid1 sdd[2] sde[0] sdf[1](F)
      976630464 blocks super 1.2 [2/1] [U_]
      [===>.................]  recovery = 15.3% (149568000/976630464) finish=84.2min speed=163636K/sec
      bitmap: 2/8 pages [8KB], 65536KB chunk

unused devices: <none>
"""

INITIAL_SYNC = """md0 : active raid1 sdb[1] sda[0]
      3906886464 blocks super 1.2 [2/2] [UU]
      [>....................]  resync =  0.4% (16521984/3906886464) finish=392.6min speed=165152K/sec
      bitmap: 30/30 pages [120KB], 65536KB chunk
"""

CHECKING = """md0 : active raid5 sdd[3] sdc[1] sdb[0]
      7813772288 blocks super 1.2 level 5, 512k chunk, algorithm 2 [3/3] [UUU]
      [=========>...........]  check = 47.0% (1836125184/3906886144) finish=211.6min speed=163000K/sec
"""

DEGRADED = """md127 : active raid1 sdb1[0]
      1953382464 blocks super 1.2 [2/1] [U_]
"""

RAID5_TWO_MISSING = """md1 : active raid5 sdb[0]
      7813772288 blocks super 1.2 level 5, 512k chunk, algorithm 2 [3/1] [U__]
"""

INACTIVE = """Personalities : [raid1]
md125 : inactive sdf[0](S)
      976630464 blocks super 1.2

unused devices: <none>
"""

RAID0 = """md2 : active raid0 sdc[1] sdb[0]
      3906764800 blocks super 1.2 512k chunks
"""

RAID10 = """md3 : active raid10 sde[3] sdd[2] sdc[1] sdb[0]
      3906764800 blocks super 1.2 512K chunks 2 near-copies [4/3] [UU_U]
"""

DELAYED = """md4 : active raid1 sdc[2] sdb[0]
      976630464 blocks super 1.2 [2/1] [U_]
        resync=DELAYED
"""


def only(text):
    arrays = raid.parse_mdstat(text)
    assert len(arrays) == 1
    return arrays[0]


def test_healthy_mirror():
    a = only(HEALTHY)
    assert (a.device, a.level, a.active) == ("md127", "raid1", True)
    assert [m.name for m in a.members] == ["sdc1", "sdb1"]
    assert (a.raid_disks, a.working_disks, a.status_map) == (2, 2, "UU")
    assert a.size_bytes == 1953382464 * 1024
    assert a.state is RaidState.HEALTHY
    assert a.progress is None


def test_rebuilding_after_failure():
    a = only(REBUILDING)
    assert a.state is RaidState.REBUILDING
    assert a.operation == "recovery"
    assert a.progress == pytest.approx(0.153)
    assert (a.finish, a.speed) == ("84.2min", "163636K/sec")
    assert [m.name for m in a.failed_members] == ["sdf"]
    assert a.missing == 1


def test_initial_sync_is_not_degraded():
    a = only(INITIAL_SYNC)
    assert a.state is RaidState.SYNCING
    assert a.progress == pytest.approx(0.004)


def test_check_in_progress():
    a = only(CHECKING)
    assert a.level == "raid5"
    assert a.state is RaidState.CHECKING
    assert a.progress == pytest.approx(0.47)


def test_degraded_without_rebuild():
    assert only(DEGRADED).state is RaidState.DEGRADED


def test_raid5_losing_two_disks_failed():
    assert only(RAID5_TWO_MISSING).state is RaidState.FAILED


def test_inactive_array_is_failed():
    a = only(INACTIVE)
    assert a.active is False
    assert a.state is RaidState.FAILED
    assert a.members[0].spare is True


def test_raid0_has_no_counts_but_is_healthy():
    a = only(RAID0)
    assert a.level == "raid0"
    assert (a.raid_disks, a.working_disks) == (2, 2)
    assert a.state is RaidState.HEALTHY


def test_raid10_one_missing_is_degraded():
    assert only(RAID10).state is RaidState.DEGRADED


def test_delayed_resync_counts_as_rebuilding():
    a = only(DELAYED)
    assert a.state is RaidState.REBUILDING
    assert a.progress == 0.0


def test_several_arrays_and_garbage():
    arrays = raid.parse_mdstat(HEALTHY + REBUILDING + "lixo qualquer\n")
    assert [a.device for a in arrays] == ["md127", "md126"]


def test_no_md_support(tmp_path):
    assert raid.read_arrays(str(tmp_path / "nao-existe")) == []


def test_labels_from_dev_md(tmp_path):
    mdstat = tmp_path / "mdstat"
    mdstat.write_text(HEALTHY)
    devmd = tmp_path / "md"
    devmd.mkdir()
    (tmp_path / "md127").touch()
    (devmd / "biglinux:nuvem-ruscher").symlink_to(tmp_path / "md127")
    arrays = raid.read_arrays(str(mdstat), str(devmd))
    assert arrays[0].label == "nuvem-ruscher"
    assert arrays[0].name == "nuvem-ruscher"


@pytest.mark.parametrize(
    ("level", "sizes", "usable"),
    [
        ("raid1", [2000, 2000], 2000),
        ("raid1", [2000, 1000], 1000),
        ("raid5", [1000, 1000, 1000], 2000),
        ("raid5", [1000, 1000], 0),
        ("raid6", [1000] * 4, 2000),
        ("raid10", [1000] * 4, 2000),
        ("raid0", [1000, 2000], 2000),
    ],
)
def test_usable_size(level, sizes, usable):
    assert raid.usable_size(level, sizes) == usable


def test_raid10_losing_a_whole_mirror_pair_is_failed():
    lost = only(RAID10.replace("[4/3] [UU_U]", "[4/2] [UU__]"))
    assert lost.near_copies == 2
    assert lost.state is raid.RaidState.FAILED
    # Um disco de cada par: degradado, mas sem perda.
    assert only(RAID10.replace("[4/3] [UU_U]", "[4/2] [U_U_]")).state is raid.RaidState.DEGRADED
