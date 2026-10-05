"""Modo simulado da v2: contas, compartilhamento, RAID e troca de local — sem tocar no sistema."""

import os
import subprocess

import pytest

gi = pytest.importorskip("gi")
from gi.repository import GLib  # noqa: E402

from nuvem_ruscher.backend.simulated import SCENARIOS, SimulatedBackend  # noqa: E402
from nuvem_ruscher.backend.simulated_cloud import BACKUP_DISK, PATRICIA  # noqa: E402
from nuvem_ruscher.core.immich_api import ApiError  # noqa: E402
from nuvem_ruscher.core.migration import Mode  # noqa: E402
from nuvem_ruscher.core.raid import RaidState  # noqa: E402

V2 = [s for s in SCENARIOS if s.startswith(("family", "quota", "user-", "api-", "raid-", "migration"))]


@pytest.fixture
def no_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(f"o modo simulado tentou executar: {args!r}")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)


def sim(scenario: str) -> SimulatedBackend:
    backend = SimulatedBackend(scenario)
    backend.time_scale = 0.001
    return backend


def run_helper(backend, action, args, cancel_at_step=None, cancel_at_progress=None):
    """Roda a linha do tempo do helper simulado no loop do GLib até o fim."""
    loop = GLib.MainLoop()
    box = {}
    events = []

    def on_event(event):
        events.append(event)
        if cancel_at_step and event.kind == "step" and event.value == cancel_at_step:
            box["op"].cancel()
        if (
            cancel_at_progress is not None
            and event.kind == "progress"
            and int(event.value.split()[-1]) >= cancel_at_progress
        ):
            box["op"].cancel()

    def on_done(result):
        box["result"] = result
        loop.quit()

    box["op"] = backend.helper(action, args, on_event, on_done, interactive=True)
    GLib.timeout_add_seconds(20, loop.quit)
    loop.run()
    return box.get("result"), events


@pytest.mark.parametrize("scenario", V2)
def test_v2_scenarios_never_run_commands(no_processes, scenario):
    backend = sim(scenario)
    assert backend.disks()
    backend.raid_arrays()
    backend.migration_state()
    plan = backend.plan_migration(f"{BACKUP_DISK}/Nuvem")
    assert plan.source == backend.photo_path


def test_family_accounts(no_processes):
    backend = sim("family")
    with pytest.raises(PermissionError):
        backend.accounts()
    session = backend.sign_in("ruscher@example.com", "segredo")
    assert session.is_admin
    accounts = backend.accounts()
    assert len(accounts) == 5
    assert sum(a.disabled for a in accounts) == 1
    with pytest.raises(ApiError) as exc:
        backend.create_account("Ana", "patricia@example.com", "x" * 12, None, None, False)
    assert exc.value.status == 400
    with pytest.raises(ApiError):
        backend.create_account("Ana", "não-é-email", "x" * 12, None, None, False)
    created = backend.create_account("Ana", "ana@example.com", "x" * 12, 25 * 1024**3, "ana", False)
    assert created.should_change_password and created.quota == 25 * 1024**3
    with pytest.raises(ApiError):
        backend.disable_account(session.user_id)  # a própria conta não
    assert backend.disable_account(created.id).disabled
    assert not backend.restore_account(created.id).disabled
    assert len(backend.reset_account_password(created.id)) == 16
    backend.sign_out()
    assert backend.session is None


def test_quota_exceeded_and_failures(no_processes):
    backend = sim("quota-exceeded")
    backend.sign_in("ruscher@example.com", "x")
    assert any(a.over_quota for a in backend.accounts())
    failing = sim("user-create-fails")
    failing.sign_in("ruscher@example.com", "x")
    with pytest.raises(ApiError) as exc:
        failing.create_account("Ana", "ana@example.com", "x" * 12, None, None, False)
    assert exc.value.status == 500
    down = sim("api-unavailable")
    with pytest.raises(ApiError) as exc:
        down.sign_in("ruscher@example.com", "x")
    assert exc.value.status == 0
    wrong = sim("family")
    with pytest.raises(ApiError):
        wrong.sign_in("ruscher@example.com", "errada")


def test_sharing_flow(no_processes):
    backend = sim("family")
    backend.sign_in("ruscher@example.com", "x")
    mine, with_me = backend.shared_albums()
    assert {a.name for a in mine} == {"Família", "Viagem a Gramado"}
    assert [a.name for a in with_me] == ["Aniversário da Lúcia"]
    album = backend.create_shared_album("Natal", [(PATRICIA, "viewer")])
    assert album.owner.name == "Ruscher" and album.members[0].role == "viewer"
    backend.set_album_role(album.id, PATRICIA, "editor")
    mine, _ = backend.shared_albums()
    natal = next(a for a in mine if a.name == "Natal")
    assert natal.members[0].role == "editor"
    backend.remove_album_member(album.id, PATRICIA)
    assert all(a.name != "Natal" for a in backend.shared_albums()[0])  # sem membros, não é mais compartilhado
    by, with_ = backend.partners()
    assert [p.name for p in by] == ["Patrícia"] == [p.name for p in with_]


@pytest.mark.parametrize(
    ("scenario", "state"),
    [
        ("raid-healthy", RaidState.HEALTHY),
        ("raid-degraded", RaidState.DEGRADED),
        ("raid-rebuilding", RaidState.REBUILDING),
        ("raid-failed", RaidState.FAILED),
    ],
)
def test_raid_states(no_processes, scenario, state):
    backend = sim(scenario)
    assert backend.raid_arrays()[0].state is state
    assert backend.photo_path.startswith("/mnt/nuvem-ruscher-raid/")


def test_raid_members_are_protected(no_processes):
    disks = {d.name: d for d in sim("raid-healthy").disks()}
    assert "raid-member" in disks["sda"].reasons
    assert "system" in disks["nvme0n1"].reasons
    free = {d.name: d for d in sim("migration").disks()}
    assert free["sda"].available and free["sdb"].has_data


def test_migration_plans(no_processes):
    assert sim("migration").plan_migration(f"{BACKUP_DISK}/Nuvem").can_start
    assert "no-space" in sim("migration-no-space").plan_migration(f"{BACKUP_DISK}/Nuvem").problems
    resumed = sim("migration-interrupted").plan_migration(f"{BACKUP_DISK}/Nuvem", Mode.COPY)
    assert resumed.can_start and "resume" in resumed.warnings
    same = sim("migration").plan_migration("/run/media/ruscher/Novo volume/Fotos")
    assert same.mode is Mode.RENAME


def test_simulated_migration_success():
    backend = sim("migration")
    old = backend.photo_path
    result, events = run_helper(backend, "migrate-storage", ["copy", f"{BACKUP_DISK}/Nuvem"])
    assert result.ok, result.error_code
    assert backend.photo_path == f"{BACKUP_DISK}/Nuvem"
    assert backend.migration_state().state == "migrated" and backend.migration_state().old == old
    assert any(e.kind == "progress" for e in events)


def test_cancel_only_during_copy():
    backend = sim("migration")
    old = backend.photo_path
    result, _ = run_helper(backend, "migrate-storage", ["copy", f"{BACKUP_DISK}/Nuvem"], cancel_at_progress=20)
    assert result.error_code == "migration-cancelled"
    assert backend.photo_path == old
    assert backend.migration_state().state == "cancelled"
    # Depois da cópia, o pedido de cancelar é ignorado (como no helper de verdade).
    late = sim("migration")
    result, _ = run_helper(late, "migrate-storage", ["copy", f"{BACKUP_DISK}/Nuvem"], cancel_at_step="verify")
    assert result.ok


def test_simulated_verify_failure_keeps_old_location():
    backend = sim("migration-verify-fails")
    old = backend.photo_path
    result, _ = run_helper(backend, "migrate-storage", ["copy", f"{BACKUP_DISK}/Nuvem"])
    assert result.error_code == "verify-failed"
    assert backend.photo_path == old
    assert backend.migration_state().state == "failed"


def test_simulated_raid_create_and_health():
    backend = sim("migration")
    disks = [d.by_id for d in backend.disks() if d.name in ("sda", "sdb")]
    result, _ = run_helper(backend, "raid-create", ["raid1", "ZTN0A1B2,WD-WX12A3456789", *disks])
    assert result.ok
    array = backend.raid_arrays()[0]
    assert array.level == "raid1" and array.state is RaidState.SYNCING
    health, _ = run_helper(backend, "disk-health", [])
    assert any(k.startswith("smart:") for k in health.results)
