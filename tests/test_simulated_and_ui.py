"""O modo --simular nunca executa nada no sistema; a interface importa sem erros."""

import importlib
import os
import subprocess

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from nuvem_ruscher.backend.base import CHECK_IDS, CheckStatus  # noqa: E402
from nuvem_ruscher.backend.simulated import SCENARIOS, SimulatedBackend  # noqa: E402


@pytest.fixture
def no_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(f"o modo simulado tentou executar: {args!r}")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr("time.sleep", lambda _s: None)


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_simulated_backend_never_runs_commands(no_processes, scenario):
    backend = SimulatedBackend(scenario)
    for check_id in CHECK_IDS:
        result = backend.check(check_id)
        assert result.title
    report = backend.inspect_storage(backend.suggest_photo_path())
    assert report.volume is not None or report.disk_missing
    backend.defaults()
    try:
        backend.releases()
    except OSError:
        assert scenario == "offline"
    backend.containers()
    backend.stats()
    backend.backups()
    backend.ping()
    backend.lan_ip()
    backend.tailscale()
    backend.load_config()


def test_scenarios_produce_expected_problems(no_processes):
    assert SimulatedBackend("no-docker").check("docker_installed").status is CheckStatus.ERROR
    assert SimulatedBackend("port-busy").check("port").status is CheckStatus.ERROR
    assert SimulatedBackend("low-memory").check("memory").status is CheckStatus.WARNING
    assert SimulatedBackend("no-docker-group").check("docker_group").fix.action == "add-docker-group"
    assert SimulatedBackend("firewall").check("firewall").status is CheckStatus.INFO
    assert SimulatedBackend("disk-missing").inspect_storage("/run/media/ruscher/X/immich").disk_missing
    fat = SimulatedBackend("fat32").inspect_storage("/run/media/ruscher/Novo volume/immich-ruscher")
    assert fat.warnings[0].level == "error"


UI_MODULES = [
    "nuvem_ruscher.ui.application",
    "nuvem_ruscher.ui.window",
    "nuvem_ruscher.ui.common",
    "nuvem_ruscher.ui.dialogs",
    "nuvem_ruscher.ui.widgets.qr_code",
    "nuvem_ruscher.ui.widgets.confetti",
    "nuvem_ruscher.ui.widgets.rows",
    "nuvem_ruscher.ui.widgets.phone",
    "nuvem_ruscher.ui.wizard",
    "nuvem_ruscher.ui.wizard.pages",
    "nuvem_ruscher.ui.shell",
    "nuvem_ruscher.ui.monitor",
    "nuvem_ruscher.ui.page",
    "nuvem_ruscher.ui.format",
    "nuvem_ruscher.ui.pages",
    "nuvem_ruscher.ui.pages.home",
    "nuvem_ruscher.ui.pages.phones",
    "nuvem_ruscher.ui.pages.storage",
    "nuvem_ruscher.ui.pages.backups",
    "nuvem_ruscher.ui.pages.network",
    "nuvem_ruscher.ui.pages.updates",
    "nuvem_ruscher.ui.pages.logs",
    "nuvem_ruscher.ui.pages.system",
    "nuvem_ruscher.ui.pages.users",
    "nuvem_ruscher.ui.pages.sharing",
    "nuvem_ruscher.ui.flow",
    "nuvem_ruscher.ui.storage_flows",
    "nuvem_ruscher.ui.accounts_ui",
]


@pytest.mark.parametrize("module", UI_MODULES)
def test_ui_modules_import(module):
    importlib.import_module(module)


def test_phone_tips_shape():
    from nuvem_ruscher.ui.widgets.phone import TIPS

    assert all(len(tip) == 3 and tip[0].endswith("-symbolic") for tip in TIPS)


def test_qr_matrix():
    from nuvem_ruscher.ui.widgets.qr_code import qr_matrix

    matrix = qr_matrix("http://192.168.0.10:2283")
    assert len(matrix) >= 21 and all(len(row) == len(matrix) for row in matrix)
