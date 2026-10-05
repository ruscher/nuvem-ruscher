"""Conectar o celular: QR para instalar o app e QR/endereço do servidor."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.backend.base import Backend
from nuvem_ruscher.constants import FDROID_URL, IMMICH_PORT, PLAY_STORE_URL
from nuvem_ruscher.core.system import TailscaleInfo
from nuvem_ruscher.i18n import N_, _
from nuvem_ruscher.ui.common import copy_text, icon_button, label, open_uri, toast
from nuvem_ruscher.ui.widgets.qr_code import QrCode, qr_frame

TIPS = (
    (
        "battery-symbolic",
        N_("Take Immich out of battery saving"),
        N_(
            "On Android: Settings → Apps → Immich → Battery → “Unrestricted”. This way the backup "
            "continues even with the screen off."
        ),
    ),
    (
        "camera-photo-symbolic",
        N_("Choose the camera folder"),
        N_(
            "In the app, tap the cloud icon and select “Camera” (and any other folders you want, "
            "such as WhatsApp Images)."
        ),
    ),
    (
        "network-wireless-symbolic",
        N_("Use the same Wi-Fi"),
        N_("At home, the phone must be on the same network as this computer."),
    ),
    (
        "nr-status-ok-symbolic",
        N_("Turn on background backup"),
        N_("In Backup, turn on “Background backup”. New photos upload by themselves."),
    ),
)


class PhoneView(Gtk.Box):
    def __init__(self, backend: Backend, show_title: bool = True) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.backend = backend
        self._lan = ""
        self._tailscale = TailscaleInfo(False)

        if show_title:
            self.append(label(_("Connect your phone"), css=("title-1",), xalign=0.5))
            self.append(
                label(
                    _("Two steps with the phone camera. It takes a minute."),
                    css=("dim-label", "lead"),
                    xalign=0.5,
                )
            )

        self.where = Adw.ToggleGroup(halign=Gtk.Align.CENTER, visible=False)
        self.where.add(Adw.Toggle(name="home", label=_("At home (Wi-Fi)")))
        self.where.add(Adw.Toggle(name="away", label=_("Away from home (Tailscale)")))
        self.where.set_active_name("home")
        self.where.connect("notify::active-name", lambda *_: self._refresh_address())
        self.append(self.where)

        cards = Adw.WrapBox(child_spacing=18, line_spacing=18, halign=Gtk.Align.CENTER, justify=Adw.JustifyMode.NONE)
        self.append(cards)

        # 1. app
        app_card = self._card(_("1. Install the Immich app"), _("Point the camera at the code or tap a store."))
        app_qr = QrCode(PLAY_STORE_URL, 156)
        app_card.append(qr_frame(app_qr))
        stores = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        play = Gtk.Button(label="Play Store")
        play.add_css_class("pill")
        play.connect("clicked", lambda b: open_uri(b, PLAY_STORE_URL))
        fdroid = Gtk.Button(label="F-Droid")
        fdroid.add_css_class("pill")
        fdroid.connect("clicked", lambda b: open_uri(b, FDROID_URL))
        stores.append(play)
        stores.append(fdroid)
        app_card.append(stores)
        cards.append(app_card)

        # 2. servidor
        server_card = self._card(
            _("2. Sign in to the app with this address"),
            _("In the app, tap “Server endpoint URL” and type (or paste) the address below."),
        )
        self.server_qr = QrCode("", 156)
        server_card.append(qr_frame(self.server_qr))
        address_row = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        self.address = label("…", css=("address", "monospace"), wrap=False, xalign=0.5, selectable=True)
        address_row.append(self.address)
        address_row.append(icon_button("edit-copy-symbolic", _("Copy address"), self._copy))
        server_card.append(address_row)
        self.address_note = label("", css=("dim-label", "caption"), xalign=0.5)
        server_card.append(self.address_note)
        cards.append(server_card)

        tips = Adw.PreferencesGroup(title=_("Tips to never lose a photo"))
        for icon, title, body in TIPS:
            row = Adw.ActionRow(title=_(title), subtitle=_(body))
            row.set_subtitle_lines(4)
            image = Gtk.Image.new_from_icon_name(icon)
            image.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            row.add_prefix(image)
            tips.add(row)
        self.append(tips)
        self.refresh()

    def _card(self, title: str, subtitle: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, width_request=236)
        card.add_css_class("card")
        card.add_css_class("qr-card")
        card.append(label(title, css=("title-4",), xalign=0.5))
        note = label(subtitle, css=("dim-label",), xalign=0.5)
        note.set_max_width_chars(26)
        card.append(note)
        return card

    def refresh(self) -> None:
        def fetch() -> tuple[str, TailscaleInfo]:
            return self.backend.lan_ip(), self.backend.tailscale()

        def done(result: tuple[str, TailscaleInfo]) -> None:
            self._lan, self._tailscale = result
            self.where.set_visible(self._tailscale.running and bool(self._tailscale.ip))
            self._refresh_address()

        run_async(fetch, on_done=done)

    def current_url(self) -> str:
        if self.where.get_active_name() == "away" and self._tailscale.ip:
            host = self._tailscale.dns_name or self._tailscale.ip
            return f"http://{host}:{IMMICH_PORT}"
        return self.backend.server_url(self._lan or None)

    def _refresh_address(self) -> None:
        url = self.current_url()
        self.address.set_text(url)
        self.server_qr.set_text(url)
        if self.where.get_active_name() == "away":
            self.address_note.set_text(_("Works from anywhere with Tailscale on in the phone (same account)."))
        elif self._lan.startswith("127."):
            self.address_note.set_text(_("We could not find this computer on the network. Is it connected to Wi-Fi?"))
        else:
            self.address_note.set_text(_("Works when the phone is on the same Wi-Fi."))

    def _copy(self, button: Gtk.Button) -> None:
        copy_text(button, self.current_url())
        toast(button, _("Address copied"))
