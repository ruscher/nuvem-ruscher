"""Parte "nuvem" do modo simulado: contas, compartilhamento, discos, RAID e troca de local.

Mixin do ``SimulatedBackend``. Tudo fica na memória: nada chama pkexec, mdadm, rsync nem
a API do Immich, e nada no sistema é alterado.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import replace

from nuvem_ruscher.backend.base import HelperDoneCallback, HelperEventCallback, HelperResult
from nuvem_ruscher.backend.timeline import Step, Timeline
from nuvem_ruscher.core import migration
from nuvem_ruscher.core.disks import Disk, Partition
from nuvem_ruscher.core.helper_protocol import HelperEvent
from nuvem_ruscher.core.immich_api import (
    Album,
    AlbumMember,
    ApiError,
    ImmichUser,
    Person,
    Session,
    generate_password,
)
from nuvem_ruscher.core.raid import RaidArray, RaidMember
from nuvem_ruscher.core.validation import EMAIL_RE

GB = 1000**3
GIB = 1024**3
TB = 1000**4

ADMIN = "0a1b2c3d-0000-4000-8000-000000000001"
PATRICIA = "0a1b2c3d-0000-4000-8000-000000000002"
JOAO = "0a1b2c3d-0000-4000-8000-000000000003"
LUCIA = "0a1b2c3d-0000-4000-8000-000000000004"
GUEST = "0a1b2c3d-0000-4000-8000-000000000005"

RAID_MOUNT = "/mnt/nuvem-ruscher-raid"
BACKUP_DISK = "/run/media/ruscher/Backup HD"

CLOUD_ACTIONS = ("migrate-storage", "remove-old-copy", "raid-create", "raid-check", "disk-health", "install-tools")

# Biblioteca simulada: os mesmos números do painel (12.430 fotos, 318 vídeos, 214 GB).
LIBRARY_FILES = 41_233
LIBRARY_BYTES = 214 * GB


class SimulatedCloud:
    """Requer, do SimulatedBackend: ``photo_path``, ``mountpoint``, ``fstype``, ``installed``."""

    photo_path: str
    mountpoint: str
    fstype: str

    time_scale = 1.0  # os testes encurtam os atrasos da simulação

    def _init_cloud(self, opts: dict[str, object]) -> None:
        self.family = bool(opts.get("family"))
        self.api_down = bool(opts.get("api_down"))
        self.create_fails = bool(opts.get("create_fails"))
        self.raid_state = str(opts.get("raid", ""))
        self.migration_kind = str(opts.get("migration", ""))
        self._session: Session | None = None
        self._tools = {"rsync": True, "mdadm": True, "smartctl": True}
        self._migration: migration.MigrationState | None = None
        self._folders: set[str] = set()
        self._users = [
            ImmichUser(
                ADMIN, "Ruscher", "ruscher@example.com", True, quota=None, usage=214 * GB, photos=12_430, videos=318
            )
        ]
        if self.family:
            lucia_quota = 50 * GIB
            lucia_usage = int(lucia_quota * (1.01 if opts.get("quota_exceeded") else 0.83))
            self._users += [
                ImmichUser(
                    PATRICIA,
                    "Patrícia",
                    "patricia@example.com",
                    quota=500 * GIB,
                    usage=182 * GB,
                    photos=8_120,
                    videos=240,
                ),
                ImmichUser(JOAO, "João", "joao@example.com", quota=100 * GIB, usage=54 * GB, photos=3_010, videos=97),
                ImmichUser(
                    LUCIA, "Lúcia", "lucia@example.com", quota=lucia_quota, usage=lucia_usage, photos=2_204, videos=12
                ),
                ImmichUser(
                    GUEST, "Visitante", "visitante@example.com", status="deleted", deleted_at="2026-10-01T10:00:00Z"
                ),
            ]
        me = AlbumMember(ADMIN, "Ruscher", "ruscher@example.com", "owner")
        self._albums: list[Album] = []
        self._partners_by: list[str] = []
        self._partners_with: list[str] = []
        if self.family:
            self._albums = [
                Album(
                    "0a1b2c3d-1111-4000-8000-000000000001",
                    "Família",
                    asset_count=1_240,
                    shared=True,
                    owner=me,
                    members=[
                        self._member(PATRICIA, "editor"),
                        self._member(JOAO, "viewer"),
                        self._member(LUCIA, "viewer"),
                    ],
                ),
                Album(
                    "0a1b2c3d-1111-4000-8000-000000000002",
                    "Viagem a Gramado",
                    asset_count=312,
                    shared=True,
                    owner=me,
                    members=[self._member(PATRICIA, "editor")],
                ),
                Album(
                    "0a1b2c3d-1111-4000-8000-000000000003",
                    "Aniversário da Lúcia",
                    asset_count=88,
                    shared=True,
                    owner=self._member(PATRICIA, "owner"),
                    members=[AlbumMember(ADMIN, "Ruscher", "ruscher@example.com", "viewer")],
                ),
            ]
            self._partners_by = [PATRICIA]
            self._partners_with = [PATRICIA]
        if self.raid_state:
            self.mountpoint = RAID_MOUNT
            self.photo_path = f"{RAID_MOUNT}/immich"
            self.fstype = "ext4"
        self._arrays = self._initial_arrays()
        if self.migration_kind == "interrupted":
            self._folders.add(f"{BACKUP_DISK}/Nuvem")
            self._migration = migration.MigrationState(
                state="cancelled",
                mode="copy",
                old=self.photo_path,
                new=f"{BACKUP_DISK}/Nuvem",
                files=LIBRARY_FILES,
                bytes=LIBRARY_BYTES,
                error="migration-cancelled the copy was cancelled",
            )

    def _member(self, user_id: str, role: str) -> AlbumMember:
        user = next(u for u in self._users if u.id == user_id)
        return AlbumMember(user.id, user.name, user.email, role)

    # --- sessão e contas ---------------------------------------------------------------------
    @property
    def session(self) -> Session | None:
        return self._session

    def _api(self, delay: float = 0.4) -> None:
        time.sleep(delay * self.time_scale)
        if self.api_down:
            raise ApiError(0, "Connection refused")

    def _need(self, admin: bool = False) -> Session:
        if self._session is None:
            raise PermissionError("not signed in")
        if admin and not self._session.is_admin:
            raise PermissionError("not an administrator")
        return self._session

    def sign_in(self, email: str, password: str) -> Session:
        self._api(0.8)
        if password in {"errada", "wrong"}:
            raise ApiError(401, "Incorrect email or password")
        email = email.strip().lower()
        user = next((u for u in self._users if u.email == email and not u.disabled), self._users[0])
        self._session = Session("sim-token", user.id, user.name, user.email, user.is_admin)
        return self._session

    def sign_out(self) -> None:
        self._session = None

    def accounts(self) -> list[ImmichUser]:
        self._need(admin=True)
        self._api()
        return [replace(u) for u in self._users]

    def _account(self, user_id: str) -> ImmichUser:
        for user in self._users:
            if user.id == user_id:
                return user
        raise ApiError(400, "User not found")

    def create_account(
        self, name: str, email: str, password: str, quota: int | None, storage_label: str | None, is_admin: bool
    ) -> ImmichUser:
        self._need(admin=True)
        self._api(0.9)
        if self.create_fails:
            raise ApiError(500, "Internal server error")
        email = email.strip().lower()
        if not EMAIL_RE.match(email):
            raise ApiError(400, "email must be an email")
        if any(u.email == email for u in self._users):
            raise ApiError(400, "User exists")
        if storage_label and any(u.storage_label == storage_label for u in self._users):
            raise ApiError(400, "Storage label already exists")
        user_id = f"0a1b2c3d-0000-4000-8000-{len(self._users) + 1:012d}"
        user = ImmichUser(
            user_id,
            name.strip(),
            email,
            is_admin,
            quota=quota,
            usage=0,
            storage_label=storage_label or None,
            should_change_password=True,
        )
        self._users.append(user)
        return replace(user)

    def update_account(self, user_id: str, **changes: object) -> ImmichUser:
        session = self._need(admin=True)
        self._api()
        user = self._account(user_id)
        if "is_admin" in changes and user_id == session.user_id:
            raise ApiError(400, "Admin status can only be changed by another admin")
        for key, value in changes.items():
            if key in ("name", "quota", "storage_label", "is_admin", "email"):
                setattr(user, key, value)
        return replace(user)

    def reset_account_password(self, user_id: str) -> str:
        self._need(admin=True)
        self._api()
        self._account(user_id).should_change_password = True
        return generate_password()

    def disable_account(self, user_id: str) -> ImmichUser:
        session = self._need(admin=True)
        self._api()
        if user_id == session.user_id:
            raise ApiError(403, "Cannot delete your own account")
        user = self._account(user_id)
        user.status, user.deleted_at = "deleted", "2026-10-05T10:00:00Z"
        return replace(user)

    def restore_account(self, user_id: str) -> ImmichUser:
        self._need(admin=True)
        self._api()
        user = self._account(user_id)
        user.status, user.deleted_at = "active", None
        return replace(user)

    def people(self) -> list[Person]:
        self._need()
        self._api(0.2)
        return [Person(u.id, u.name, u.email) for u in self._users if not u.disabled]

    # --- compartilhamento ---------------------------------------------------------------------
    def shared_albums(self) -> tuple[list[Album], list[Album]]:
        me = self._need().user_id
        self._api()
        mine = [replace(a) for a in self._albums if a.owner and a.owner.user_id == me and a.members]
        with_me = [
            replace(a)
            for a in self._albums
            if a.owner and a.owner.user_id != me and any(m.user_id == me for m in a.members)
        ]
        return mine, with_me

    def _album(self, album_id: str) -> Album:
        for album in self._albums:
            if album.id == album_id:
                return album
        raise ApiError(400, "Album not found")

    def create_shared_album(self, name: str, members: list[tuple[str, str]]) -> Album:
        session = self._need()
        self._api(0.7)
        owner = AlbumMember(session.user_id, session.name, session.email, "owner")
        album = Album(
            f"0a1b2c3d-1111-4000-8000-{len(self._albums) + 1:012d}",
            name.strip(),
            shared=bool(members),
            owner=owner,
            members=[self._member(uid, role) for uid, role in members if uid != session.user_id],
        )
        self._albums.append(album)
        return replace(album)

    def add_album_members(self, album_id: str, members: list[tuple[str, str]]) -> Album:
        self._need()
        self._api()
        album = self._album(album_id)
        present = {m.user_id for m in album.members} | {album.owner.user_id if album.owner else ""}
        album.members += [self._member(uid, role) for uid, role in members if uid not in present]
        album.shared = bool(album.members)
        return replace(album)

    def set_album_role(self, album_id: str, user_id: str, role: str) -> None:
        self._need()
        self._api()
        album = self._album(album_id)
        album.members = [replace(m, role=role) if m.user_id == user_id else m for m in album.members]

    def remove_album_member(self, album_id: str, user_id: str) -> None:
        self._need()
        self._api()
        album = self._album(album_id)
        album.members = [m for m in album.members if m.user_id != user_id]
        album.shared = bool(album.members)

    def partners(self) -> tuple[list[Person], list[Person]]:
        self._need()
        self._api()

        def person(uid: str) -> Person:
            user = self._account(uid)
            return Person(user.id, user.name, user.email)

        return [person(u) for u in self._partners_by], [person(u) for u in self._partners_with]

    def add_partner(self, user_id: str) -> None:
        self._need()
        self._api()
        if user_id not in self._partners_by:
            self._partners_by.append(user_id)

    def remove_partner(self, user_id: str) -> None:
        self._need()
        self._api()
        self._partners_by = [u for u in self._partners_by if u != user_id]

    # --- discos e RAID ---------------------------------------------------------------------
    def tool_available(self, name: str) -> bool:
        return self._tools.get(name, False)

    def disks(self) -> list[Disk]:
        time.sleep(0.3 * self.time_scale)
        nvme = Disk(
            "nvme0n1",
            "/dev/nvme0n1",
            1_000_204_886_016,
            "Samsung SSD 980 1TB",
            "S6B0NL0W123456",
            "nvme",
            by_id="/dev/disk/by-id/nvme-Samsung_SSD_980_1TB_S6B0NL0W123456",
            partitions=[
                Partition("/dev/nvme0n1p1", 1 * GB, "vfat", "", ("/boot/efi",)),
                Partition("/dev/nvme0n1p2", 999 * GB, "btrfs", "", ("/", "/home")),
            ],
            mountpoints=["/", "/boot/efi", "/home"],
            reasons=["system", "database", "docker"],
        )
        usb = Disk(
            "sdd",
            "/dev/sdd",
            2_000_398_934_016,
            "SanDisk Portable SSD",
            "323143334D343031",
            "usb",
            removable=True,
            by_id="/dev/disk/by-id/usb-SanDisk_Portable_SSD_323143334D343031-0:0",
            partitions=[
                Partition("/dev/sdd1", 2_000_397_795_328, "ntfs", "Novo volume", ("/run/media/ruscher/Novo volume",))
            ],
            mountpoints=["/run/media/ruscher/Novo volume"],
            reasons=["mounted"] if self.raid_state else ["cloud", "mounted"],
        )
        found = [nvme, usb]
        members = {m.name for a in self._arrays for m in a.members}
        for name, model, serial, data in (
            ("sda", "Seagate IronWolf 4TB", "ZTN0A1B2", False),
            ("sdb", "WD Red Plus 4TB", "WD-WX12A3456789", True),
        ):
            disk = Disk(
                name,
                f"/dev/{name}",
                4_000_787_030_016,
                model,
                serial,
                "sata",
                rotational=True,
                by_id=f"/dev/disk/by-id/ata-{model.replace(' ', '_')}_{serial}",
            )
            if name in members:
                disk.fstype = "linux_raid_member"
                disk.reasons = ["raid-member"] + (["cloud"] if self.raid_state else [])
            elif data:
                disk.partitions = [Partition(f"/dev/{name}1", disk.size, "ntfs", "Arquivos antigos")]
            found.append(disk)
        if self.migration_kind:
            found.append(
                Disk(
                    "sde",
                    "/dev/sde",
                    4_000_787_030_016,
                    "Seagate Expansion HDD",
                    "NAA1B2C3",
                    "usb",
                    removable=True,
                    rotational=True,
                    by_id="/dev/disk/by-id/usb-Seagate_Expansion_HDD_NAA1B2C3-0:0",
                    partitions=[Partition("/dev/sde1", 4_000_786_000_000, "ext4", "Backup HD", (BACKUP_DISK,))],
                    mountpoints=[BACKUP_DISK],
                    reasons=["mounted"],
                )
            )
        return found

    def _initial_arrays(self) -> list[RaidArray]:
        if not self.raid_state:
            return []
        members = [RaidMember("sda", 0), RaidMember("sdb", 1)]
        array = RaidArray(
            device="md127",
            level="raid1",
            active=True,
            members=members,
            raid_disks=2,
            working_disks=2,
            status_map="UU",
            size_bytes=4_000_651_739_136,
            label="nuvem-ruscher",
        )
        if self.raid_state == "degraded":
            array.members = [members[0], RaidMember("sdb", 1, faulty=True)]
            array.working_disks, array.status_map = 1, "U_"
        elif self.raid_state == "rebuilding":
            array.members = [members[0], RaidMember("sdc", 2)]
            array.working_disks, array.status_map = 1, "U_"
            array.operation, array.progress, array.finish, array.speed = "recovery", 0.37, "84.2min", "163636K/sec"
        elif self.raid_state == "failed":
            array.active = False
            array.working_disks = 0
        return [array]

    def raid_arrays(self) -> list[RaidArray]:
        for array in self._arrays:
            # A reconstrução e a sincronização avançam enquanto o app está aberto.
            if array.operation and array.progress is not None:
                array.progress = min(0.999, array.progress + 0.004)
        return [replace(a, members=list(a.members)) for a in self._arrays]

    def _smart(self, by_id: str) -> str:
        data: dict[str, object] = {
            "smart_status": {"passed": True},
            "temperature": {"current": 36},
            "power_on_time": {"hours": 9120},
        }
        if "WD_Red" in by_id and self.raid_state in ("degraded", "failed"):
            data["smart_status"] = {"passed": self.raid_state != "failed"}
            data["ata_smart_attributes"] = {
                "table": [{"id": 5, "raw": {"value": 184}}, {"id": 197, "raw": {"value": 16}}]
            }
        if "nvme-" in by_id:
            data["nvme_smart_health_information_log"] = {"temperature": 41, "percentage_used": 4, "media_errors": 0}
        if "usb-" in by_id:
            return "{}"  # muitos adaptadores USB não repassam o SMART
        data["rotation_rate"] = 0 if "nvme" in by_id else 5400
        return json.dumps(data)

    # --- troca de local -----------------------------------------------------------------------
    def _sim_mounts(self) -> dict[str, tuple[str, int, int, bool, bool]]:
        """ponto de montagem → (fs, total, livre, removível, disco do sistema)."""
        mounts = {
            "/run/media/ruscher/Novo volume": ("ntfs", 2_000_397_795_328, 1_786_397_795_328, True, False),
            "/home/ruscher": ("btrfs", 999 * GB, 310 * GB, False, True),
        }
        if self.migration_kind:
            free = 120 * GB if self.migration_kind == "no-space" else 3_600 * GB
            mounts[BACKUP_DISK] = ("ext4", 4_000 * GB, free, True, False)
        if self._arrays:
            mounts[RAID_MOUNT] = ("ext4", 4_000_651_739_136, 3_700 * GB, False, False)
        return mounts

    def plan_migration(self, dest: str, mode: migration.Mode | None = None) -> migration.MigrationPlan:
        time.sleep(1.2 * self.time_scale)
        stats = migration.TreeStats(LIBRARY_FILES, LIBRARY_BYTES, 0, 3_900_000_000, set(migration.IMMICH_FOLDERS))
        mounts = self._sim_mounts()
        mount = max((m for m in mounts if dest == m or dest.startswith(m + "/")), key=len, default="")
        source_mount = max((m for m in mounts if self.photo_path.startswith(m + "/")), key=len, default="")
        info = migration.Destination(path=dest, parent_exists=bool(mount))
        if mount:
            fs, total, free, removable, system_disk = mounts[mount]
            info.mountpoint, info.fstype, info.total, info.free = mount, fs, total, free
            info.removable, info.system_disk = removable, system_disk
            info.same_fs = mount == source_mount
            if dest in self._folders:
                info.exists = info.is_dir = True
                info.empty = False
                if self._migration and self._migration.new == dest and self._migration.state == "cancelled":
                    info.resumable_from = self.photo_path
        return migration.assess(self.photo_path, dest, stats, info, mode)

    def migration_state(self) -> migration.MigrationState | None:
        return replace(self._migration) if self._migration else None

    # --- ações do helper (simuladas) ---------------------------------------------------------
    def cloud_helper(
        self, action: str, args: list[str], on_event: HelperEventCallback | None, on_done: HelperDoneCallback
    ) -> Timeline:
        result = HelperResult(ok=True)
        holder: dict[str, Timeline] = {}

        def emit(kind: str, key: str = "", value: str = "") -> Callable[[], None]:
            def go() -> None:
                if kind == "error":
                    result.ok = False
                    result.error_code, result.error_detail = key, value
                    line = f"@@ERROR {key} {value}"
                elif kind == "result":
                    result.results[key] = value
                    line = f"@@RESULT {key}={value}"
                else:
                    line = f"@@{kind.upper()} {value}"
                result.log.append(line)
                if on_event:
                    on_event(HelperEvent(kind, key, value))

            return go

        def info(text: str) -> Callable[[], None]:
            return emit("info", value=text)

        def do(fn: Callable[[], object]) -> Callable[[], None]:
            return lambda: (fn(), None)[1]

        def cancellable(flag: bool) -> Callable[[], None]:
            def go() -> None:
                holder["timeline"].cancellable = flag

            return go

        steps: list[Step] = [(250, info(f"[simulated] pkexec nuvem-ruscher-helper {action}"))]
        on_cancel = None
        if action == "migrate-storage":
            steps, on_cancel = self._migration_script(steps, args, emit, info, do, cancellable, result, on_done)
        elif action == "remove-old-copy":
            steps += [
                (500, emit("step", value="verify")),
                (900, emit("step", value="remove")),
                (300, do(lambda: self._set_migration("removed-old"))),
                (10, emit("result", "removed", args[0] if args else "")),
            ]
        elif action == "raid-create":
            level = args[0] if args else "raid1"
            devices = args[2:]
            steps += [
                (400, emit("step", value="check")),
                (700, emit("step", value="wipe")),
                *[(300, info(f"erasing signatures on {d}")) for d in devices],
                (900, emit("step", value="create")),
                (1200, emit("step", value="format")),
                (500, emit("step", value="config")),
                (600, emit("step", value="mount")),
                (200, do(lambda: self._create_array(level, devices))),
                (10, emit("result", "mountpoint", RAID_MOUNT)),
                (10, emit("result", "suggested", f"{RAID_MOUNT}/immich")),
            ]
        elif action == "raid-check":
            steps += [(400, do(self._start_check)), (10, emit("result", "check", "started"))]
        elif action == "disk-health":
            targets = args or [d.by_id for d in self.disks() if d.by_id]
            steps += [(80, emit("result", f"smart:{t}", self._smart(t))) for t in targets]
        elif action == "install-tools":
            steps += [
                (600, emit("step", value="install")),
                (1200, do(lambda: self._tools.update({a: True for a in args}))),
            ]
        steps.append((150, lambda: on_done(result)))
        timeline = Timeline(steps, on_cancel=on_cancel, cancellable=on_cancel is None, scale=self.time_scale)
        holder["timeline"] = timeline
        return timeline

    def _set_migration(self, state: str, error: str = "") -> None:
        if self._migration is not None:
            self._migration = replace(self._migration, state=state, error=error)

    def _create_array(self, level: str, devices: list[str]) -> None:
        names = []
        for disk in self.disks():
            if disk.by_id in devices:
                names.append(disk.name)
        members = [RaidMember(name, i) for i, name in enumerate(names)]
        self._arrays = [
            RaidArray(
                "md127",
                level,
                True,
                members,
                len(members),
                len(members),
                "U" * len(members),
                4_000_651_739_136,
                "resync",
                0.004,
                "392.6min",
                "165152K/sec",
                "nuvem-ruscher",
            )
        ]

    def _start_check(self) -> None:
        for array in self._arrays:
            if array.active and not array.operation:
                array.operation, array.progress, array.finish = "check", 0.0, "240.0min"

    def _migration_script(self, steps, args, emit, info, do, cancellable, result, on_done):  # noqa: ANN001, ANN202
        mode = args[0] if args else "copy"
        new = args[1] if len(args) > 1 else ""
        old = self.photo_path
        state = migration.MigrationState("running", "", mode, old, new, LIBRARY_FILES, LIBRARY_BYTES)

        def begin() -> None:
            self._migration = state

        def switch() -> None:
            mounts = self._sim_mounts()
            mount = max((m for m in mounts if new.startswith(m + "/")), key=len, default=self.mountpoint)
            self.photo_path, self.mountpoint, self.fstype = new, mount, mounts.get(mount, ("ext4",))[0]
            self._folders.add(old)

        def cancelled() -> None:
            emit("error", "migration-cancelled", f"the copy was cancelled; the server keeps using {old}")()
            self._migration = replace(state, state="cancelled", error="migration-cancelled")
            self._folders.add(new)
            on_done(result)

        steps += [
            (300, emit("step", value="check")),
            (900, emit("result", "files", str(LIBRARY_FILES))),
            (10, emit("result", "bytes", str(LIBRARY_BYTES))),
            (10, do(begin)),
            (600, emit("step", value="backup")),
            (900, emit("step", value="dump")),
        ]
        if mode == "copy":
            steps += [(10, cancellable(True)), (300, emit("step", value="copy"))]
            for pct in range(0, 101, 4):
                steps.append((380, emit("progress", value=f"copy {LIBRARY_BYTES * pct // 100} {pct}")))
            steps += [
                (10, cancellable(False)),
                (500, emit("step", value="stop")),
                (300, emit("step", value="sync")),
                (300, emit("progress", value=f"sync {LIBRARY_BYTES} 100")),
                (700, emit("step", value="verify")),
            ]
            if self.migration_kind == "verify-fails":
                steps += [
                    (900, info("differs: >f.st...... library/admin/2024/IMG_2041.jpg")),
                    (300, info("going back to " + old)),
                    (900, info("the server is back on " + old)),
                    (10, do(lambda: self._fail_migration(state))),
                    (10, emit("error", "verify-failed", "the copy is different from the original")),
                ]
                return steps, cancelled
            steps.append((800, emit("result", "sampled", "220")))
        else:
            steps += [
                (500, emit("step", value="stop")),
                (600, emit("step", value="move" if mode == "rename" else "stop")),
            ]
        steps += [
            (500, emit("step", value="switch")),
            (10, do(switch)),
            (700, emit("step", value="start")),
            (2200, emit("step", value="confirm")),
            (500, do(lambda: setattr(self, "_migration", replace(state, state="migrated")))),
            (10, emit("result", "old", old)),
            (10, emit("result", "new", new)),
            (10, emit("result", "migration", "ok")),
        ]
        return steps, cancelled

    def _fail_migration(self, state: migration.MigrationState) -> None:
        self._migration = replace(state, state="failed", error="verify-failed the copy is different from the original")
        self._folders.add(state.new)
