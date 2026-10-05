"""Conectar o celular (Android ou iPhone): instalar o app, digitar o endereço, entrar, ligar o backup.

O que muda entre os sistemas vem de ``core.mobile``; aqui só se monta a tela. O teste de
conexão roda neste computador e diz isso: quem prova que o celular alcança o servidor é
o próprio celular, abrindo o código do endereço no navegador.
"""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.backend.base import Backend
from nuvem_ruscher.constants import IMMICH_PORT
from nuvem_ruscher.core import mobile, network
from nuvem_ruscher.core.mobile import MobilePlatform, Note
from nuvem_ruscher.core.system import TailscaleInfo
from nuvem_ruscher.i18n import N_, _
from nuvem_ruscher.ui.common import copy_text, icon_button, label, open_uri, status_icon, toast
from nuvem_ruscher.ui.widgets.qr_code import QrCode, qr_frame

PLATFORM_STATE = "phone_platform"

# Problemas do diagnóstico (core.network): título, o que fazer e a página que resolve.
PROBLEMS = {
    "server-off": (
        N_("The server is not running"),
        N_("Turn it on in Home, then test again."),
        "home",
    ),
    "no-network": (
        N_("This computer is not on a network"),
        N_("Connect it to the same Wi-Fi (or router) as the phone."),
        "network",
    ),
    "link-local": (
        N_("The network did not give this computer an address"),
        N_("Reconnect the Wi-Fi on this computer or restart the router."),
        "network",
    ),
    "tailscale-missing": (
        N_("Tailscale is not installed on this computer"),
        N_("Set it up in Network, or use the home address."),
        "network",
    ),
    "tailscale-off": (
        N_("Tailscale is off on this computer"),
        N_("Turn it on and sign in, then test again."),
        "network",
    ),
    "not-answering": (
        N_("The server answers only on this computer"),
        N_("It does not answer at the address above. Restart it in System and test again."),
        "system",
    ),
    "firewall": (
        N_("A firewall may block the phone"),
        N_("This test cannot see it. If the phone cannot connect, allow the server in Network."),
        "network",
    ),
    "public-address": (
        N_("This does not look like a home network"),
        N_("Phones on your Wi-Fi may not reach this address. Is this computer on the home Wi-Fi?"),
        "network",
    ),
}
PAGE_BUTTONS = {"home": N_("Open Home"), "network": N_("Open Network"), "system": N_("Open System")}


def plain_row(kind: type[Adw.ActionRow] | type[Adw.ExpanderRow], title: str, subtitle: str = "") -> Adw.PreferencesRow:
    """Linha com texto puro ("Privacy & Security"): sem markup, e o texto só depois.

    Passado no construtor, o texto é lido como markup antes de ``use_markup`` valer.
    """
    row = kind(use_markup=False)
    row.set_title(title)
    if subtitle:
        row.set_subtitle(subtitle)
    return row


def note_row(note: Note, title: str | None = None) -> Adw.PreferencesRow:
    """Linha com ícone; detalhes, quando há, ficam recolhidos (``Adw.ExpanderRow``)."""
    if note.details:
        row: Adw.PreferencesRow = plain_row(Adw.ExpanderRow, title or _(note.title), _(note.body))
        row.set_subtitle_lines(0)
        details = label(_(note.details), css=("dim-label",))
        details.set_margin_top(12)
        details.set_margin_bottom(12)
        details.set_margin_start(12)
        details.set_margin_end(12)
        row.add_row(details)
        row.add_prefix(_icon(note.icon))
        return row
    row = plain_row(Adw.ActionRow, title or _(note.title), _(note.body))
    row.set_subtitle_lines(0)
    row.add_prefix(_icon(note.icon))
    return row


def _icon(name: str) -> Gtk.Image:
    image = Gtk.Image.new_from_icon_name(name)
    image.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    return image


class PhoneView(Gtk.Box):
    def __init__(
        self,
        backend: Backend,
        show_title: bool = True,
        open_page: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.backend = backend
        self.open_page = open_page
        self._lan = ""
        self._tailscale = TailscaleInfo(False)
        self._testing = False

        if show_title:
            self.append(label(_("Connect a phone"), css=("title-1",), xalign=0.5))
            self.append(
                label(
                    _("Install Immich, type one address and turn on the backup. It takes a few minutes."),
                    css=("dim-label", "lead"),
                    xalign=0.5,
                )
            )

        # Qual celular? Android e iPhone lado a lado, com o mesmo peso.
        chooser = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER)
        chooser.append(label(_("Which phone?"), css=("heading",), xalign=0.5))
        self.platform_toggle = Adw.ToggleGroup(halign=Gtk.Align.CENTER, homogeneous=True)
        self.platform_toggle.add_css_class("round")
        for p in mobile.PLATFORMS:
            self.platform_toggle.add(Adw.Toggle(name=p.id, label=_(p.label)))
        self.platform_toggle.update_property([Gtk.AccessibleProperty.LABEL], [_("Which phone?")])
        saved = str(backend.state_get(PLATFORM_STATE, "") or "")
        self.platform_toggle.set_active_name(mobile.platform(saved).id)
        self.platform_toggle.connect("notify::active-name", lambda *_: self._platform_changed())
        chooser.append(self.platform_toggle)
        self.append(chooser)

        self.where = Adw.ToggleGroup(halign=Gtk.Align.CENTER, visible=False)
        self.where.add_css_class("round")
        self.where.add(Adw.Toggle(name="home", label=_("At home (Wi-Fi)")))
        self.where.add(Adw.Toggle(name="away", label=_("Away from home (Tailscale)")))
        self.where.update_property([Gtk.AccessibleProperty.LABEL], [_("Where the phone connects from")])
        self.where.set_active_name("home")
        self.where.connect("notify::active-name", lambda *_: self._rebuild())
        self.append(self.where)

        # align=0.5: em janela estreita, cada linha (um cartão) fica centralizada.
        self.cards = Adw.WrapBox(
            child_spacing=18, line_spacing=18, halign=Gtk.Align.CENTER, justify=Adw.JustifyMode.NONE, align=0.5
        )
        self.append(self.cards)

        self.steps_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.append(self.steps_holder)

        # Teste da conexão: daqui (servidor responde?) e do celular (o próprio celular abre o endereço).
        self.check = Adw.PreferencesGroup(
            title=_("Check the connection"),
            description=_("Use it before signing in, or when the phone cannot find your cloud."),
        )
        self.test_row = plain_row(
            Adw.ActionRow, _("Test from this computer"), _("Checks that your cloud answers at the address above.")
        )
        self.test_row.set_subtitle_lines(0)
        self.test_row.add_prefix(_icon("computer-symbolic"))
        self.test_button = Gtk.Button(label=_("Test"), valign=Gtk.Align.CENTER)
        self.test_button.connect("clicked", lambda *_: self.run_test())
        self.test_row.add_suffix(self.test_button)
        self.test_row.set_activatable_widget(self.test_button)
        self.phone_test = plain_row(
            Adw.ActionRow,
            _("Test from the phone"),
            _(
                "Scan the address code with the phone’s camera. If the Immich page opens, the phone can "
                "reach your cloud."
            ),
        )
        self.phone_test.set_subtitle_lines(0)
        self.phone_test.add_prefix(_icon("phone-symbolic"))
        self._result_rows: list[Gtk.Widget] = []
        self._check_rows: list[Gtk.Widget] = []
        self._trouble = Adw.ExpanderRow()
        self.append(self.check)

        self.extras_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.append(self.extras_holder)
        self._rebuild()
        self.refresh()

    # --- estado ---------------------------------------------------------------------------
    @property
    def platform(self) -> MobilePlatform:
        return mobile.platform(self.platform_toggle.get_active_name() or "")

    @property
    def away(self) -> bool:
        return self.where.get_visible() and self.where.get_active_name() == "away"

    def set_platform(self, platform_id: str) -> None:
        self.platform_toggle.set_active_name(mobile.platform(platform_id).id)

    def _platform_changed(self) -> None:
        self.backend.state_set(PLATFORM_STATE, self.platform.id)
        self._rebuild()

    def refresh(self) -> None:
        def fetch() -> tuple[str, TailscaleInfo]:
            return self.backend.lan_ip(), self.backend.tailscale()

        def done(result: tuple[str, TailscaleInfo]) -> None:
            self._lan, self._tailscale = result
            self.where.set_visible(self._tailscale.running and bool(self._tailscale.ip))
            self._rebuild()

        run_async(fetch, on_done=done)

    def current_url(self) -> str:
        if self.away and self._tailscale.ip:
            host = self._tailscale.dns_name or self._tailscale.ip
            return f"http://{host}:{IMMICH_PORT}"
        return self.backend.server_url(self._lan or None)

    # --- montagem ---------------------------------------------------------------------------
    def _rebuild(self) -> None:
        p = self.platform
        while (child := self.cards.get_first_child()) is not None:
            self.cards.remove(child)
        number = 1
        self.cards.append(self._install_card(number, p))
        if self.away:
            number += 1
            self.cards.append(self._tailscale_card(number, p))
        self.cards.append(self._server_card(number + 1))
        self._refresh_address()

        self._replace(self.steps_holder, self._steps_group(p))
        self._replace(self.extras_holder, self._extras_group(p))
        self._trouble = self._trouble_row(p)
        self._layout_check([])

    @staticmethod
    def _replace(holder: Gtk.Box, widget: Gtk.Widget) -> None:
        while (child := holder.get_first_child()) is not None:
            holder.remove(child)
        holder.append(widget)

    def _card(self, title: str, subtitle: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, width_request=236)
        card.add_css_class("card")
        card.add_css_class("qr-card")
        heading = label(title, css=("title-4",), xalign=0.5)
        heading.set_accessible_role(Gtk.AccessibleRole.HEADING)
        card.append(heading)
        note = label(subtitle, css=("dim-label",), xalign=0.5)
        note.set_max_width_chars(26)
        card.append(note)
        return card

    def _store_buttons(self, stores: tuple[mobile.Store, ...], what: str) -> Gtk.Widget:
        box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        for store in stores:
            button = Gtk.Button(label=store.name)
            button.add_css_class("pill")
            text = _("Open {app} in {store}").format(app=what, store=store.name)
            button.set_tooltip_text(text)
            button.update_property([Gtk.AccessibleProperty.LABEL], [text])
            button.connect("clicked", lambda b, url=store.url: open_uri(b, url))
            box.append(button)
        return box

    def _install_card(self, number: int, p: MobilePlatform) -> Gtk.Widget:
        card = self._card(
            _("{n}. Install Immich").format(n=number),
            _("Point the phone’s camera at the code, or tap the store."),
        )
        store = p.stores[0]
        qr = QrCode(store.url, 156, _("Install Immich from {store}").format(store=store.name))
        card.append(qr_frame(qr))
        card.append(self._store_buttons(p.stores, "Immich"))
        return card

    def _tailscale_card(self, number: int, p: MobilePlatform) -> Gtk.Widget:
        card = self._card(
            _("{n}. Install Tailscale").format(n=number),
            _("Then sign in with the same account you use on this computer."),
        )
        qr = QrCode(p.tailscale.url, 156, _("Install Tailscale from {store}").format(store=p.tailscale.name))
        card.append(qr_frame(qr))
        card.append(self._store_buttons((p.tailscale,), "Tailscale"))
        return card

    def _server_card(self, number: int) -> Gtk.Widget:
        card = self._card(
            _("{n}. Type this address in Immich").format(n=number),
            _("On the first screen, in “Server Endpoint URL”."),
        )
        # Widgets novos a cada montagem: um widget só pode ter um pai, e o cartão antigo some.
        self.server_qr = QrCode("", 156)
        self.address = label("…", css=("address", "monospace"), wrap=True, xalign=0.5, selectable=True)
        self.address_note = label("", css=("dim-label", "caption"), xalign=0.5)
        card.append(qr_frame(self.server_qr))
        row = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        row.append(self.address)
        row.append(icon_button("edit-copy-symbolic", _("Copy address"), self._copy))
        card.append(row)
        card.append(self.address_note)
        return card

    def _steps_group(self, p: MobilePlatform) -> Gtk.Widget:
        group = Adw.PreferencesGroup(
            title=_("Then, in the Immich app"),
            description=_("These steps happen on the phone, so this computer cannot see them."),
        )
        for index, note in enumerate(mobile.phone_steps(p), start=1):
            row = note_row(note, _("{n}. {step}").format(n=index, step=_(note.title)))
            group.add(row)
        return group

    def _extras_group(self, p: MobilePlatform) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title=_("Good to know"))
        for note in mobile.good_to_know(p, self.away):
            group.add(note_row(note))
        return group

    def _trouble_row(self, p: MobilePlatform) -> Adw.ExpanderRow:
        row = plain_row(Adw.ExpanderRow, _("The phone cannot connect?"), _("The most common causes, in order."))
        row.add_prefix(_icon("dialog-question-symbolic"))
        for note in mobile.troubleshooting(p, self.away):
            row.add_row(note_row(note))
        return row

    # --- endereço ---------------------------------------------------------------------------
    def _refresh_address(self) -> None:
        url = self.current_url()
        self.address.set_text(url)
        self.server_qr.set_text(url, _("Opens your cloud in the phone’s browser"))
        if self.away:
            self.address_note.set_text(_("Works from anywhere with Tailscale on in the phone (same account)."))
        elif network.address_kind(self._lan) in (network.AddressKind.LOOPBACK, network.AddressKind.INVALID):
            self.address_note.set_text(_("We could not find this computer on the network. Is it connected to Wi-Fi?"))
        else:
            self.address_note.set_text(_("Works when the phone is on the same Wi-Fi."))

    def _copy(self, button: Gtk.Button) -> None:
        copy_text(button, self.current_url())
        toast(button, _("Address copied"))

    # --- teste ------------------------------------------------------------------------------
    def _layout_check(self, results: list[Gtk.Widget]) -> None:
        """Teste daqui, resultados logo abaixo, teste pelo celular e as causas comuns."""
        for row in self._check_rows:
            self.check.remove(row)
        self._check_rows = [self.test_row, *results, self.phone_test, self._trouble]
        for row in self._check_rows:
            self.check.add(row)
        self._result_rows = results

    def run_test(self) -> None:
        if self._testing:
            return
        self._testing = True
        self.test_button.set_sensitive(False)
        self.test_button.set_label(_("Testing…"))
        url = self.current_url()
        host = url.split("://", 1)[-1].rsplit(":", 1)[0]
        mode = "away" if self.away else "home"
        tailscale = self._tailscale
        reachable_host = network.address_kind(host) not in (network.AddressKind.LOOPBACK, network.AddressKind.INVALID)

        def collect() -> network.Facts:
            local = self.backend.ping()
            at_address = self.backend.probe_server(url) if local and reachable_host else False
            return network.Facts(
                mode=mode,
                host=host,
                server_local=local,
                server_at_address=at_address,
                firewall=self.backend.fact_firewall(),
                firewall_opened=bool(self.backend.state_get("firewall_allowed")),
                tailscale_installed=tailscale.installed,
                tailscale_running=tailscale.running and bool(tailscale.ip),
            )

        def finish() -> None:
            self._testing = False
            self.test_button.set_sensitive(True)
            self.test_button.set_label(_("Test again"))

        def done(facts: network.Facts) -> None:
            finish()
            if facts.host != host or url != self.current_url():
                return  # o endereço mudou enquanto testava
            self._show_result(network.diagnose(facts))

        def failed(_exc: BaseException) -> None:
            finish()
            self._show_result(network.Diagnosis(["server-off"]))

        run_async(collect, on_done=done, on_error=failed)

    def _show_result(self, result: network.Diagnosis) -> None:
        rows: list[Gtk.Widget] = []
        if result.ok:
            row = plain_row(
                Adw.ActionRow,
                _("Your cloud answers at this address"),
                _("Seen from this computer. Now test from the phone."),
            )
            row.add_prefix(status_icon("ok"))
            rows.append(row)
        for code in result.problems:
            title, hint, page = PROBLEMS[code]
            row = plain_row(Adw.ActionRow, _(title), _(hint))
            row.set_subtitle_lines(0)
            row.add_prefix(status_icon("warning" if code in network.WARNINGS else "error"))
            if self.open_page is not None:
                button = Gtk.Button(label=_(PAGE_BUTTONS[page]), valign=Gtk.Align.CENTER)
                button.connect("clicked", lambda *_b, target=page: self.open_page(target))
                row.add_suffix(button)
            rows.append(row)
        self._layout_check(rows)
        failures = [code for code in result.problems if code not in network.WARNINGS]
        summary = _(PROBLEMS[failures[0]][0]) if failures else _("Your cloud answers at this address")
        if hasattr(self, "announce"):  # GTK ≥ 4.14: avisa o leitor de tela
            self.announce(summary, Gtk.AccessibleAnnouncementPriority.MEDIUM)
        if rows:
            # grab_focus devolve True: sem o "and False" o idle se repetiria para sempre.
            GLib.idle_add(lambda: rows[0].grab_focus() and False)
