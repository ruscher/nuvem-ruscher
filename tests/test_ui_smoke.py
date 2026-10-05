"""Fumaça da interface: monta janela, páginas e diálogos com o backend simulado.

Exceções dentro de callbacks do GTK não derrubam nada — só são impressas. Aqui elas são
capturadas (sys.excepthook) e fazem o teste falhar. Precisa de uma tela (Wayland/X11).
"""

import os
import sys
import time

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")) or not Gtk.init_check(),
    reason="sem tela para o GTK",
)


@pytest.fixture
def errors(monkeypatch):
    found = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: found.append(exc))
    return found


def pump(seconds: float = 0.6) -> None:
    """Deixa as threads de run_async e os timeouts do GLib terminarem."""
    context = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def build(scenario: str):
    from nuvem_ruscher.backend.simulated import SimulatedBackend
    from nuvem_ruscher.ui.shell import Shell

    Adw.init()
    backend = SimulatedBackend(scenario)
    backend.time_scale = 0.01
    window = Adw.ApplicationWindow()
    window.toast = lambda *a, **k: None
    shell = Shell(backend, Gio.Menu(), on_uninstalled=lambda: None)
    window.set_content(shell)
    window.present()
    shell.activate_monitor()
    pump(0.5)
    return backend, window, shell


SCENARIOS = [
    "installed",
    "family",
    "raid-degraded",
    "raid-failed",
    "migration",
    "migration-interrupted",
    "api-unavailable",
]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_page_renders(errors, scenario):
    backend, window, shell = build(scenario)
    try:
        if scenario != "api-unavailable":
            backend.sign_in("ruscher@example.com", "x")
            for page_id in ("users", "sharing", "home"):
                shell.page(page_id).session_changed()
        for page_id in shell.pages:
            shell.show(page_id)
            pump(0.4)
    finally:
        shell.deactivate_monitor()
        window.destroy()
    assert errors == [], [str(e[1]) for e in errors]


def test_dialogs_open_and_walk(errors):
    from nuvem_ruscher.ui.accounts_ui import AccountDialog, AddAccountDialog
    from nuvem_ruscher.ui.pages.sharing import NewSharedFolderDialog, SharedFolderDialog
    from nuvem_ruscher.ui.storage_flows import MigrationDialog, RaidDialog

    backend, window, shell = build("family")
    try:
        backend.sign_in("ruscher@example.com", "x")
        ctx = shell.ctx
        accounts = backend.accounts()
        dialogs = [
            AddAccountDialog(ctx, lambda _u: None),
            AccountDialog(ctx, accounts[1], lambda: None),
            AccountDialog(ctx, next(a for a in accounts if a.disabled), lambda: None),
            AccountDialog(ctx, accounts[0], lambda: None),  # a própria conta
        ]
        mine, _with = backend.shared_albums()
        people = backend.people()
        dialogs += [
            NewSharedFolderDialog(ctx, people, lambda _a: None),
            SharedFolderDialog(ctx, mine[0], people, lambda: None),
        ]
        migration = MigrationDialog(ctx, "/run/media/ruscher/Novo volume/Fotos")
        raid = RaidDialog(ctx)
        dialogs += [migration, raid]
        for dialog in dialogs:
            dialog.present(window)
            pump(0.3)
        migration._check()
        pump(0.8)
        raid._choose_disks()
        pump(0.6)
        for dialog in dialogs:
            dialog.force_close()
        pump(0.2)
    finally:
        shell.deactivate_monitor()
        window.destroy()
    assert errors == [], [str(e[1]) for e in errors]


def test_failure_paths_show_human_errors(errors):
    from nuvem_ruscher.ui.storage_flows import MigrationDialog

    _backend, window, shell = build("migration-verify-fails")
    try:
        dialog = MigrationDialog(shell.ctx, "/run/media/ruscher/Backup HD/Nuvem")
        dialog.present(window)
        dialog._check()
        pump(0.8)
        dialog._start()
        pump(2.5)
        assert dialog.nav.get_visible_page().get_tag() == "failed"
        dialog.force_close()
    finally:
        shell.deactivate_monitor()
        window.destroy()
    assert errors == [], [str(e[1]) for e in errors]
