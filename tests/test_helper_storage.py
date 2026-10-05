"""Helper: trocar o local das fotos e criar RAID, sempre na sandbox (nada real é tocado).

Os discos são arquivos em $ROOT/dev; mdadm, wipefs, mkfs.ext4, mount e smartctl são
falsos (tests/sim-bin). A cópia usa o rsync de verdade, só entre pastas da sandbox.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from conftest import ROOT
from test_helper import Sim, env_values

from nuvem_ruscher.core.escaping import mount_unit_name

pytestmark = pytest.mark.skipif(not shutil.which("rsync"), reason="rsync ausente")

LIBRARY = {
    "library/admin/2024/Praia com espaço.jpg": b"j" * 3000,
    "library/admin/2024/ação ü 日本.heic": b"h" * 5000,
    "upload/admin/aa/bb/aabb.mp4": b"v" * 20000,
    "thumbs/admin/aa/bb/aabb-preview.webp": b"t" * 700,
    "encoded-video/admin/aa/bb/aabb.mp4": b"e" * 9000,
    "profile/admin/avatar.png": b"p" * 300,
}


@pytest.fixture
def sim():
    base = ROOT / "build" / "testes"
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="storage-", dir=base))
    yield Sim(path)
    shutil.rmtree(path, ignore_errors=True)


def installed(sim: Sim) -> Sim:
    """Instalação pronta, servidor ligado e uma biblioteca com nomes difíceis."""
    sim.setup()
    photos = Path(sim.photos)
    for folder in ("library", "upload", "thumbs", "encoded-video", "profile", "backups"):
        (photos / folder).mkdir(parents=True, exist_ok=True)
        (photos / folder / ".immich").write_text("")
    for rel, data in LIBRARY.items():
        target = photos / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    assert sim.run("start").returncode == 0
    return sim


def new_disk(sim: Sim, name: str = "HD2", fstype: str = "ext4") -> str:
    mount = Path(sim.root, "run", "media", "ruscher", name)
    mount.mkdir(parents=True)
    sim.env["SIM_MOUNTS"] = f"{sim.mountpoint}|fuseblk|rw;{mount}|{fstype}|rw,nosuid,nodev"
    return str(mount)


def tree(path: str) -> dict[str, bytes]:
    root = Path(path)
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and "backups" not in p.parts and p.name != ".nuvem-ruscher-migration"
    }


def state(sim: Sim) -> dict[str, str]:
    file = sim.root / "var" / "lib" / "nuvem-ruscher" / "migration.state"
    return env_values(file) if file.exists() else {}


class TestCopy:
    def test_copy_verify_switch(self, sim):
        installed(sim)
        dest = new_disk(sim) + "/Nuvem"
        before = tree(sim.photos)
        proc = sim.run("migrate-storage", "copy", dest)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        res = sim.results(proc)
        assert res["migration"] == "ok"
        assert int(res["sampled"]) >= len(LIBRARY)
        # cópia idêntica, origem intacta
        assert tree(dest) == before
        assert tree(sim.photos) == before
        assert not Path(dest, ".nuvem-ruscher-migration").exists()
        # configuração apontando para o novo local
        assert env_values(sim.stack / ".env")["UPLOAD_LOCATION"] == f'"{dest}"'
        conf = env_values(sim.conf)
        assert conf["UPLOAD_LOCATION"] == dest
        assert conf["OLD_UPLOAD_LOCATION"] == sim.photos
        assert conf["MOUNT_POINT"] == str(Path(dest).parent)
        unit = sim.unit.read_text()
        assert f'RequiresMountsFor="{dest}"' in unit
        assert f'ExecStartPre=/usr/bin/mountpoint -q "{Path(dest).parent}"' in unit
        wants = [p.parent.name for p in (sim.root / "etc/systemd/system").glob("*.wants/nuvem-ruscher-immich.service")]
        assert wants == [f"{mount_unit_name(str(Path(dest).parent))}.wants"]
        assert state(sim)["STATE"] == "migrated"
        assert (sim.root / "state" / "service").read_text() == "active"
        # Nenhuma cópia do .env (com a senha do banco) fica para trás.
        assert list((sim.root / "var/lib/nuvem-ruscher/tmp").glob("*before-migration")) == []
        steps = [e.value for e in sim.events(proc) if e.kind == "step"]
        assert steps.index("backup") < steps.index("copy") < steps.index("stop") < steps.index("verify")
        assert steps.index("verify") < steps.index("switch") < steps.index("start") < steps.index("confirm")

    def test_not_enough_space(self, sim):
        installed(sim)
        dest = new_disk(sim) + "/Nuvem"
        proc = sim.run("migrate-storage", "copy", dest, SIM_DF_AVAIL="1000")
        assert sim.error(proc) == "no-space"
        assert not Path(dest).exists()
        assert env_values(sim.conf)["UPLOAD_LOCATION"] == sim.photos

    def test_destination_not_empty(self, sim):
        installed(sim)
        dest = Path(new_disk(sim), "Nuvem")
        dest.mkdir()
        (dest / "documento.txt").write_text("não é meu")
        proc = sim.run("migrate-storage", "copy", str(dest))
        assert sim.error(proc) == "dest-not-empty"
        assert (dest / "documento.txt").read_text() == "não é meu"

    def test_server_must_be_running(self, sim):
        installed(sim)
        sim.run("stop")
        proc = sim.run("migrate-storage", "copy", new_disk(sim) + "/Nuvem")
        assert sim.error(proc) == "not-running"

    @pytest.mark.parametrize("where", ["inside", "parent"])
    def test_nested_paths(self, sim, where):
        installed(sim)
        dest = sim.photos + "/sub" if where == "inside" else str(Path(sim.photos).parent)
        proc = sim.run("migrate-storage", "copy", dest)
        assert sim.error(proc) == "storage-unsafe"

    def test_disk_not_connected(self, sim):
        installed(sim)
        proc = sim.run("migrate-storage", "copy", str(sim.root / "run/media/ruscher/Sumiu/Nuvem"))
        assert sim.error(proc) == "storage-missing"

    def test_cancel_during_copy_keeps_everything(self, sim):
        installed(sim)
        dest = new_disk(sim) + "/Nuvem"
        proc = sim.run("migrate-storage", "copy", dest, stdin="cancel\n", SIM_RSYNC_DELAY="3")
        assert sim.error(proc) == "migration-cancelled"
        assert state(sim)["STATE"] == "cancelled"
        assert env_values(sim.conf)["UPLOAD_LOCATION"] == sim.photos
        assert (sim.root / "state" / "service").read_text() == "active"
        assert not any(c.startswith("systemctl stop") for c in sim.calls())

    def test_closing_the_window_does_not_cancel(self, sim):
        installed(sim)
        dest = new_disk(sim) + "/Nuvem"
        proc = sim.run("migrate-storage", "copy", dest, stdin="", SIM_RSYNC_DELAY="1")
        assert sim.results(proc)["migration"] == "ok"

    def test_resume_after_interruption(self, sim):
        installed(sim)
        dest = new_disk(sim) + "/Nuvem"
        sim.run("migrate-storage", "copy", dest, stdin="cancel\n", SIM_RSYNC_DELAY="3")
        Path(dest, "library").mkdir(parents=True, exist_ok=True)  # cópia parcial deixada para trás
        proc = sim.run("migrate-storage", "copy", dest)
        assert sim.results(proc)["migration"] == "ok"
        assert "resuming an interrupted copy" in proc.stdout

    def test_rollback_when_container_does_not_see_the_folder(self, sim):
        installed(sim)
        dest = new_disk(sim) + "/Nuvem"
        proc = sim.run("migrate-storage", "copy", dest, SIM_CONFIRM_FAIL="1")
        assert sim.error(proc) == "migration-rolled-back"
        conf = env_values(sim.conf)
        assert conf["UPLOAD_LOCATION"] == sim.photos
        assert env_values(sim.stack / ".env")["UPLOAD_LOCATION"] == f'"{sim.photos}"'
        assert f'RequiresMountsFor="{sim.photos}"' in sim.unit.read_text()
        assert state(sim)["STATE"] == "rolled-back"
        assert (sim.root / "state" / "service").read_text() == "active"
        assert tree(sim.photos) == tree(dest)  # a cópia nova fica, para análise

    def test_ntfs_destination_uses_portable_options(self, sim):
        installed(sim)
        dest = new_disk(sim, fstype="fuseblk") + "/Nuvem"
        proc = sim.run("migrate-storage", "copy", dest)
        assert sim.results(proc)["migration"] == "ok"
        assert tree(dest) == tree(sim.photos)

    def test_fat32_refuses_large_files(self, sim):
        installed(sim)
        big = Path(sim.photos, "upload", "grande.mp4")
        with big.open("wb") as handle:
            handle.truncate(4 * 1024**3 + 10)  # arquivo esparso: não ocupa espaço de verdade
        proc = sim.run("migrate-storage", "copy", new_disk(sim, fstype="vfat") + "/Nuvem")
        assert sim.error(proc) == "storage-unsafe"
        assert "4 GB" in proc.stdout


class TestRenameAndAdopt:
    def test_rename_on_same_disk(self, sim):
        installed(sim)
        before = tree(sim.photos)
        dest = sim.mountpoint + "/Fotos da família"
        proc = sim.run("migrate-storage", "rename", dest)
        assert proc.returncode == 0, proc.stdout
        assert tree(dest) == before
        assert not Path(sim.photos).exists()
        assert env_values(sim.conf)["UPLOAD_LOCATION"] == dest

    def test_rename_refused_across_disks(self, sim):
        installed(sim)
        proc = sim.run("migrate-storage", "rename", new_disk(sim) + "/Nuvem")
        assert sim.error(proc) == "invalid-argument"

    def test_rename_rolls_back(self, sim):
        installed(sim)
        dest = sim.mountpoint + "/Outra"
        proc = sim.run("migrate-storage", "rename", dest, SIM_CONFIRM_FAIL="1")
        assert sim.error(proc) == "migration-rolled-back"
        assert Path(sim.photos).is_dir() and not Path(dest).exists()
        assert env_values(sim.conf)["UPLOAD_LOCATION"] == sim.photos

    def test_adopt_existing_copy(self, sim):
        installed(sim)
        dest = Path(new_disk(sim), "Nuvem")
        shutil.copytree(sim.photos, dest)
        proc = sim.run("migrate-storage", "adopt", str(dest))
        assert proc.returncode == 0, proc.stdout
        assert env_values(sim.conf)["UPLOAD_LOCATION"] == str(dest)

    def test_adopt_refuses_empty_folder(self, sim):
        installed(sim)
        dest = Path(new_disk(sim), "Vazia")
        dest.mkdir()
        proc = sim.run("migrate-storage", "adopt", str(dest))
        assert sim.error(proc) == "adopt-incomplete"
        assert env_values(sim.conf)["UPLOAD_LOCATION"] == sim.photos


class TestRemoveOldCopy:
    def migrated(self, sim) -> str:
        installed(sim)
        dest = new_disk(sim) + "/Nuvem"
        assert sim.results(sim.run("migrate-storage", "copy", dest))["migration"] == "ok"
        return dest

    def test_removes_only_immich_folders(self, sim):
        dest = self.migrated(sim)
        Path(sim.photos, "minhas notas.txt").write_text("não é do Immich")
        proc = sim.run("remove-old-copy", sim.photos)
        assert proc.returncode == 0, proc.stdout
        left = sorted(p.name for p in Path(sim.photos).iterdir())
        assert left == ["minhas notas.txt"]
        assert tree(dest)  # o novo local continua intacto
        assert env_values(sim.conf)["OLD_UPLOAD_LOCATION"] == ""
        assert state(sim)["STATE"] == "removed-old"

    def test_refuses_when_old_copy_has_extra_files(self, sim):
        self.migrated(sim)
        Path(sim.photos, "library", "admin", "só na cópia antiga.jpg").write_bytes(b"x")
        proc = sim.run("remove-old-copy", sim.photos)
        assert sim.error(proc) == "old-copy-differs"
        assert Path(sim.photos, "library").is_dir()

    def test_refuses_any_other_folder(self, sim):
        dest = self.migrated(sim)
        for target in (dest, str(sim.root / "run/media/ruscher/Outra")):
            proc = sim.run("remove-old-copy", target)
            assert sim.error(proc) in ("invalid-argument", "storage-unsafe")
        assert Path(sim.photos, "library").is_dir()

    def test_refuses_without_completed_migration(self, sim):
        installed(sim)
        proc = sim.run("remove-old-copy", sim.photos)
        assert sim.error(proc) == "invalid-argument"
        assert Path(sim.photos, "library").is_dir()


class TestRaid:
    def disks(self, sim, *names: str) -> list[str]:
        dev = sim.root / "dev"
        by_id = dev / "disk" / "by-id"
        by_id.mkdir(parents=True, exist_ok=True)
        paths = []
        for name in names:
            (dev / name).write_text("")
            link = by_id / f"ata-Exemplo_HDD_{name.upper()}"
            link.symlink_to(f"../../{name}")
            sim.env[f"SIM_SERIAL_{name}"] = f"S-{name.upper()}"
            paths.append(str(link))
        return paths

    def destructive_calls(self, sim) -> list[str]:
        return [c for c in sim.calls() if c.split()[0] in ("wipefs", "mdadm", "mkfs.ext4") and "--detail" not in c]

    def test_create_raid1(self, sim):
        sim.setup()
        uuid = "3f1c7a52-9d0e-4b8a-9a1e-6c3b2d1e0f99"
        disks = self.disks(sim, "sdb", "sdc")
        proc = sim.run(
            "raid-create",
            "raid1",
            "S-SDB,S-SDC",
            *disks,
            NUVEM_RUSCHER_SIM_UUID=uuid,
            SIM_UUID=uuid,
            SIM_REAL_FSTYPE="ext4",
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        res = sim.results(proc)
        assert res["mountpoint"] == str(sim.root / "mnt/nuvem-ruscher-raid")
        calls = sim.calls()
        create = next(c for c in calls if c.startswith("mdadm --create"))
        assert "--level=1" in create and "--raid-devices=2" in create and "--metadata=1.2" in create
        wiped = [c for c in calls if c.startswith("wipefs")]
        assert len(wiped) == 2
        assert wiped[0].endswith(f"-- {sim.root}/dev/sdb") and wiped[1].endswith(f"-- {sim.root}/dev/sdc")
        assert any(c.startswith("mkfs.ext4") and uuid in c for c in calls)
        assert "ARRAY /dev/md/nuvem-ruscher" in (sim.root / "etc/mdadm.conf").read_text()
        fstab = sim.fstab.read_text()
        assert f"UUID={uuid} " in fstab and "nuvem-ruscher-raid ext4" in fstab
        assert any(c.startswith("mount ") for c in calls)

    @pytest.mark.parametrize(
        ("case", "env", "args"),
        [
            ("wrong serial", {}, ("raid1", "S-SDB,S-XXX")),
            ("missing serial", {}, ("raid1", "S-SDB")),
            ("mounted", {"SIM_TREE_sdc": 'PATH="/dev/sdc1" TYPE="part" FSTYPE="ext4" MOUNTPOINT="/mnt/x"'}, None),
            (
                "raid member",
                {"SIM_TREE_sdc": 'PATH="/dev/sdc1" TYPE="part" FSTYPE="linux_raid_member" MOUNTPOINT=""'},
                None,
            ),
            ("luks", {"SIM_TREE_sdc": 'PATH="/dev/sdc1" TYPE="part" FSTYPE="crypto_LUKS" MOUNTPOINT=""'}, None),
            ("lvm in use", {"SIM_TREE_sdc": 'PATH="/dev/mapper/vg" TYPE="lvm" FSTYPE="ext4" MOUNTPOINT=""'}, None),
            ("partition", {}, "partition"),
            ("twice", {}, "twice"),
            ("raid5 with two", {}, ("raid5", "S-SDB,S-SDC")),
        ],
    )
    def test_refuses_and_touches_nothing(self, sim, case, env, args):
        sim.setup()
        disks = self.disks(sim, "sdb", "sdc")
        level, serials = ("raid1", "S-SDB,S-SDC")
        if isinstance(args, tuple):
            level, serials = args
        if args == "partition":
            part = Path(disks[1] + "-part1")
            part.symlink_to("../../sdc")
            disks[1] = str(part)
        if args == "twice":
            disks[1] = disks[0]
        proc = sim.run("raid-create", level, serials, *disks, **env)
        assert proc.returncode == 1, case
        assert sim.error(proc) in ("not-confirmed", "disk-in-use", "invalid-argument", "disk-protected"), case
        assert self.destructive_calls(sim) == [], case
        assert not (sim.root / "etc/mdadm.conf").exists()

    def test_system_disk_is_protected(self, sim):
        sim.setup()
        disks = self.disks(sim, "sdb", "sdc")
        proc = sim.run("raid-create", "raid1", "S-SDB,S-SDC", *disks, SIM_ROOT_DISK=str(sim.root / "dev/sdb"))
        assert sim.error(proc) == "disk-protected"
        assert self.destructive_calls(sim) == []

    def test_unknown_system_disk_fails_closed(self, sim):
        sim.setup()
        disks = self.disks(sim, "sdb", "sdc")
        # O lsblk não acha disco nenhum por trás do "/": sem saber, nada é apagado.
        proc = sim.run("raid-create", "raid1", "S-SDB,S-SDC", *disks, SIM_ROOT_DISK="")
        assert sim.error(proc) == "disk-protected"
        assert self.destructive_calls(sim) == []

    def test_raid10_needs_even_disks(self, sim):
        sim.setup()
        disks = self.disks(sim, "sdb", "sdc", "sdd", "sde", "sdf")
        proc = sim.run("raid-create", "raid10", "S-SDB,S-SDC,S-SDD,S-SDE,S-SDF", *disks)
        assert sim.error(proc) == "invalid-argument"
        assert self.destructive_calls(sim) == []

    def test_only_one_app_array(self, sim):
        sim.setup()
        (sim.root / "dev/md").mkdir(parents=True)
        (sim.root / "dev/md/nuvem-ruscher").write_text("")
        disks = self.disks(sim, "sdb", "sdc")
        proc = sim.run("raid-create", "raid1", "S-SDB,S-SDC", *disks)
        assert sim.error(proc) == "raid-exists"
        assert self.destructive_calls(sim) == []

    def test_disk_health_is_read_only(self, sim):
        disks = self.disks(sim, "sdb")
        data = {"smart_status": {"passed": True}, "temperature": {"current": 41}}
        proc = sim.run("disk-health", disks[0], SIM_SMART_JSON=json.dumps(data))
        assert proc.returncode == 0, proc.stdout
        assert json.loads(sim.results(proc)[f"smart:{disks[0]}"])["temperature"]["current"] == 41
        assert sim.error(sim.run("disk-health", "/etc/passwd")) == "invalid-argument"
        assert sim.error(sim.run("disk-health", "$(reboot)")) == "invalid-argument"


def test_new_actions_need_root_outside_simulation():
    env = {k: v for k, v in os.environ.items() if k != "NUVEM_RUSCHER_SIM_ROOT"}
    for action in ("migrate-storage", "remove-old-copy", "raid-create", "disk-health", "install-tools"):
        proc = __import__("subprocess").run(
            ["bash", str(ROOT / "helper/nuvem-ruscher-helper"), action],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert "not-authorized" in proc.stdout
