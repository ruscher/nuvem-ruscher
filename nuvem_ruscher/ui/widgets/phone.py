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
        N_("Tire o Immich da economia de bateria"),
        N_(
            "No Android: Configurações → Apps → Immich → Bateria → “Sem restrições”. "
            "Assim o backup continua mesmo com a tela desligada."
        ),
    ),
    (
        "camera-photo-symbolic",
        N_("Escolha a pasta da câmera"),
        N_("No app, toque no ícone de nuvem e selecione “Camera” (e outras pastas que quiser, como WhatsApp Images)."),
    ),
    (
        "network-wireless-symbolic",
        N_("Use o mesmo Wi-Fi"),
        N_("Em casa, o celular precisa estar na mesma rede que este computador."),
    ),
    (
        "nr-status-ok-symbolic",
        N_("Ative o backup em segundo plano"),
        N_("Em Backup, ligue “Backup em segundo plano”. As fotos novas sobem sozinhas."),
    ),
)


class PhoneView(Gtk.Box):
    def __init__(self, backend: Backend, show_title: bool = True) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.backend = backend
        self._lan = ""
        self._tailscale = TailscaleInfo(False)

        if show_title:
            self.append(label(_("Conecte seu celular"), css=("title-1",), xalign=0.5))
            self.append(
                label(
                    _("Dois passos com a câmera do celular. Leva um minuto."),
                    css=("dim-label", "lead"),
                    xalign=0.5,
                )
            )

        self.where = Adw.ToggleGroup(halign=Gtk.Align.CENTER, visible=False)
        self.where.add(Adw.Toggle(name="home", label=_("Em casa (Wi-Fi)")))
        self.where.add(Adw.Toggle(name="away", label=_("Fora de casa (Tailscale)")))
        self.where.set_active_name("home")
        self.where.connect("notify::active-name", lambda *_: self._refresh_address())
        self.append(self.where)

        cards = Adw.WrapBox(child_spacing=18, line_spacing=18, halign=Gtk.Align.CENTER, justify=Adw.JustifyMode.NONE)
        self.append(cards)

        # 1. app
        app_card = self._card(_("1. Instale o app Immich"), _("Aponte a câmera para o código ou toque em uma loja."))
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
            _("2. Entre no app com este endereço"),
            _("No app, toque em “Endereço do servidor” e digite (ou cole) o endereço abaixo."),
        )
        self.server_qr = QrCode("", 156)
        server_card.append(qr_frame(self.server_qr))
        address_row = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        self.address = label("…", css=("address", "monospace"), wrap=False, xalign=0.5, selectable=True)
        address_row.append(self.address)
        address_row.append(icon_button("edit-copy-symbolic", _("Copiar endereço"), self._copy))
        server_card.append(address_row)
        self.address_note = label("", css=("dim-label", "caption"), xalign=0.5)
        server_card.append(self.address_note)
        cards.append(server_card)

        tips = Adw.PreferencesGroup(title=_("Dicas para não perder nenhuma foto"))
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
            self.address_note.set_text(_("Funciona de qualquer lugar com o Tailscale ligado no celular (mesma conta)."))
        elif self._lan.startswith("127."):
            self.address_note.set_text(_("Não encontramos este computador na rede. Ele está conectado ao Wi-Fi?"))
        else:
            self.address_note.set_text(_("Funciona quando o celular está no mesmo Wi-Fi."))

    def _copy(self, button: Gtk.Button) -> None:
        copy_text(button, self.current_url())
        toast(button, _("Endereço copiado"))
