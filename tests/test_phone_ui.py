"""Tela de celulares com GTK de verdade e o backend simulado (Android e iPhone).

Precisa de uma tela (Wayland/X11); exceções em callbacks do GTK fazem o teste falhar.
"""

import os
import sys
import time

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from nuvem_ruscher import constants  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")) or not Gtk.init_check(),
    reason="sem tela para o GTK",
)

LAN_URL = "http://192.168.0.10:2283"
TS_URL = "http://ruscher-big.tail9c419a.ts.net:2283"


@pytest.fixture
def errors(monkeypatch):
    found = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: found.append(exc))
    yield found
    assert found == [], [str(e[1]) for e in found]


def pump(seconds: float = 0.5) -> None:
    context = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def walk(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from walk(child)
        child = child.get_next_sibling()


@pytest.fixture
def phone():
    from nuvem_ruscher.backend.simulated import SimulatedBackend
    from nuvem_ruscher.ui.widgets.phone import PhoneView

    Adw.init()
    windows = []
    opened = []

    def make(scenario="installed", width=1000, open_page=True):
        backend = SimulatedBackend(scenario)
        view = PhoneView(backend, show_title=True, open_page=opened.append if open_page else None)
        window = Adw.ApplicationWindow(default_width=width, default_height=900)
        window.toast = lambda *a, **k: None
        window.set_content(Gtk.ScrolledWindow(child=view))
        window.present()
        windows.append(window)
        pump(0.6)
        return backend, view

    make.opened = opened
    yield make
    for window in windows:
        window.destroy()


def qr_texts(view):
    from nuvem_ruscher.ui.widgets.qr_code import QrCode

    return [w.text for w in walk(view.cards) if isinstance(w, QrCode)]


def store_buttons(view):
    return [w.get_label() for w in walk(view.cards) if isinstance(w, Gtk.Button) and w.has_css_class("pill")]


def texts(widget):
    found = []
    for w in walk(widget):
        if isinstance(w, Adw.PreferencesRow):
            found.append(w.get_title())
        if isinstance(w, Adw.ActionRow | Adw.ExpanderRow):
            found.append(w.get_subtitle() or "")
        if isinstance(w, Gtk.Label):
            found.append(w.get_text())
    return " ".join(found)


def test_android_is_the_default(errors, phone):
    _backend, view = phone()
    assert view.platform.id == "android"
    assert qr_texts(view) == [constants.PLAY_STORE_URL, LAN_URL]
    assert store_buttons(view) == ["Play Store", "F-Droid"]
    shown = texts(view)
    assert "Unrestricted" in shown and "Background App Refresh" not in shown


def test_iphone_switches_store_tips_and_remembers(errors, phone):
    backend, view = phone()
    view.set_platform("ios")
    pump(0.2)
    assert qr_texts(view) == [constants.APP_STORE_URL, LAN_URL]  # o QR do servidor não muda
    assert store_buttons(view) == ["App Store"]
    shown = texts(view)
    assert "Background App Refresh" in shown and "Local Network" in shown and "iCloud" in shown
    assert "Unrestricted" not in shown and "F-Droid" not in shown
    assert backend.state_get("phone_platform") == "ios"
    # De volta ao Android: tudo do iPhone some.
    view.set_platform("android")
    pump(0.2)
    assert store_buttons(view) == ["Play Store", "F-Droid"]
    assert "Background App Refresh" not in texts(view)


def test_saved_platform_is_restored(errors, phone):
    from nuvem_ruscher.ui.widgets.phone import PhoneView

    backend, _view = phone()
    backend.state_set("phone_platform", "ios")
    assert PhoneView(backend).platform.id == "ios"


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_away_from_home_adds_tailscale(errors, phone, platform):
    _backend, view = phone()
    view.set_platform(platform)
    assert view.where.get_visible()
    view.where.set_active_name("away")
    pump(0.2)
    tailscale = constants.TAILSCALE_APP_STORE_URL if platform == "ios" else constants.TAILSCALE_PLAY_STORE_URL
    assert qr_texts(view)[1:] == [tailscale, TS_URL]
    assert view.address.get_text() == TS_URL
    assert "Tailscale on the phone" in texts(view)


def test_without_tailscale_only_home(errors, phone):
    _backend, view = phone("no-tailscale")
    assert not view.where.get_visible()
    assert qr_texts(view)[-1] == LAN_URL


def test_server_qr_never_carries_credentials(errors, phone):
    _backend, view = phone("family")
    for platform in ("android", "ios"):
        view.set_platform(platform)
        pump(0.1)
        server = qr_texts(view)[-1]
        assert server == LAN_URL and "@" not in server and "key" not in server.lower()


def test_connection_ok(errors, phone):
    _backend, view = phone()
    view.run_test()
    pump(1.2)
    titles = [r.get_title() for r in view._result_rows]
    assert titles == ["Your cloud answers at this address"]
    assert view.test_button.get_sensitive()


def test_no_network(errors, phone):
    _backend, view = phone("no-network")
    assert view.address.get_text() == "http://127.0.0.1:2283"
    assert "could not find this computer" in view.address_note.get_text()
    view.run_test()
    pump(1.2)
    assert [r.get_title() for r in view._result_rows] == ["This computer is not on a network"]


def test_lan_unreachable_points_to_the_fix(errors, phone):
    _backend, view = phone("lan-unreachable")
    view.run_test()
    pump(1.2)
    titles = [r.get_title() for r in view._result_rows]
    assert titles == ["The server answers only on this computer", "A firewall may block the phone"]
    button = next(w for w in walk(view._result_rows[1]) if isinstance(w, Gtk.Button))
    button.emit("clicked")
    assert phone.opened == ["network"]


def test_in_the_wizard_there_are_no_page_buttons(errors, phone):
    _backend, view = phone("lan-unreachable", open_page=False)
    view.run_test()
    pump(1.2)
    assert not any(isinstance(w, Gtk.Button) for row in view._result_rows for w in walk(row))


def test_qr_codes_have_text_alternatives(errors, phone):
    _backend, view = phone()
    view.set_platform("ios")
    pump(0.1)
    # O endereço também aparece como texto selecionável e tem botão de copiar.
    assert view.address.get_selectable() and view.address.get_text() == LAN_URL
    copy = [w for w in walk(view.cards) if isinstance(w, Gtk.Button) and w.get_icon_name() == "edit-copy-symbolic"]
    assert len(copy) == 1
    stores = [w for w in walk(view.cards) if isinstance(w, Gtk.Button) and w.has_css_class("pill")]
    assert all(b.get_tooltip_text() for b in stores)


@pytest.mark.parametrize("dark", [False, True])
def test_narrow_and_dark(errors, phone, dark):
    manager = Adw.StyleManager.get_default()
    manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT)
    try:
        _backend, view = phone(width=360)
        view.set_platform("ios")
        view.where.set_active_name("away")
        pump(0.4)
        assert view.get_width() <= 360
    finally:
        manager.set_color_scheme(Adw.ColorScheme.DEFAULT)


def test_plain_text_is_never_parsed_as_markup(errors, phone):
    # "Privacy & Security": lido como markup, o GTK recusa o texto e a linha fica vazia.
    _backend, view = phone()
    view.set_platform("ios")
    pump(0.2)
    shown = [w.get_text() for w in walk(view) if isinstance(w, Gtk.Label)]
    assert any("Privacy & Security" in text for text in shown)


def test_rebuilding_keeps_a_single_server_card(errors, phone):
    # Cada troca remonta os cartões: o QR do endereço precisa estar no cartão visível.
    _backend, view = phone()
    for platform in ("ios", "android", "ios"):
        view.set_platform(platform)
        view.where.set_active_name("away" if platform == "android" else "home")
        pump(0.1)
    assert view.server_qr.get_root() is not None and view.address.get_root() is not None
    assert qr_texts(view)[-1] == view.address.get_text() == LAN_URL
