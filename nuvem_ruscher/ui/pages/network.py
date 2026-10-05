"""Rede: endereço em casa, acesso fora de casa (Tailscale) e firewall."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.backend.base import HelperResult
from nuvem_ruscher.constants import IMMICH_PORT, TAILSCALE_DOWNLOAD_URL
from nuvem_ruscher.core.system import TailscaleInfo
from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.common import copy_text, icon_button, open_uri, set_status_icon, show_error, status_icon, toast
from nuvem_ruscher.ui.page import Page, advanced_expander, group

if TYPE_CHECKING:
    from nuvem_ruscher.ui.shell import AppContext


class NetworkPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            _("Network"),
            _("How phones and computers reach your cloud, at home and away."),
            "network-wireless-symbolic",
            "blue",
        )
        self.ctx = ctx
        self.backend = ctx.backend

        home = group(_("At home"), _("Phones on the same Wi-Fi use this address."))
        self.lan_row = Adw.ActionRow(title=_("Home address"), subtitle="…")
        self.lan_icon = status_icon("pending")
        self.lan_row.add_prefix(self.lan_icon)
        self.lan_row.set_subtitle_selectable(True)
        self.lan_copy = icon_button("edit-copy-symbolic", _("Copy address"), self._copy_lan)
        self.lan_row.add_suffix(self.lan_copy)
        home.add(self.lan_row)
        self.add(home)

        self.away = group(
            _("Away from home"),
            _("With Tailscale (free), phones upload photos from anywhere, securely, without opening ports."),
        )
        self.away_row = Adw.ActionRow(title=_("Checking Tailscale…"))
        self.away_row.set_subtitle_lines(4)
        self.away_icon = status_icon("pending")
        self.away_row.add_prefix(self.away_icon)
        self.away_suffix = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.away_row.add_suffix(self.away_suffix)
        self.away.add(self.away_row)
        self.add(self.away)

        self.firewall = group(_("Firewall"))
        self.firewall.set_visible(False)
        fw = Adw.ActionRow(
            title=_("Open port {p} for the home network").format(p=IMMICH_PORT),
            subtitle=_("Only for home networks and Tailscale. Use it if a phone cannot find the server."),
        )
        fw.set_subtitle_lines(3)
        self.fw_icon = status_icon("info")
        fw.add_prefix(self.fw_icon)
        self.fw_button = Gtk.Button(label=_("Open port"), valign=Gtk.Align.CENTER)
        self.fw_button.connect("clicked", self._firewall)
        fw.add_suffix(self.fw_button)
        self.firewall.add(fw)
        self.add(self.firewall)

        advanced = group()
        details = advanced_expander(_("Advanced"), _("Port and addresses used by the server"))
        self.port_row = Adw.ActionRow(title=_("Server port"), subtitle=str(IMMICH_PORT))
        self.port_row.add_css_class("property")
        self.local_row = Adw.ActionRow(
            title=_("On this computer"), subtitle=GLib.markup_escape_text(self.backend.local_url)
        )
        self.local_row.add_css_class("property")
        self.local_row.set_subtitle_selectable(True)
        details.add_row(self.port_row)
        details.add_row(self.local_row)
        advanced.add(details)
        self.add(advanced)
        self._lan_url = ""

    def on_shown(self) -> None:
        def fetch() -> tuple[str, TailscaleInfo, str]:
            return self.backend.lan_ip(), self.backend.tailscale(), self.backend.fact_firewall()

        run_async(fetch, on_done=self._show, on_error=lambda _e: None)

    def _show(self, result: tuple[str, TailscaleInfo, str]) -> None:
        lan, info, firewall = result
        if lan:
            self._lan_url = self.backend.server_url(lan)
            self.lan_row.set_subtitle(GLib.markup_escape_text(self._lan_url))
            set_status_icon(self.lan_icon, "ok")
        else:
            self._lan_url = ""
            self.lan_row.set_subtitle(_("This computer is not connected to a network."))
            set_status_icon(self.lan_icon, "warning")
        self.lan_copy.set_sensitive(bool(lan))
        self._show_tailscale(info)
        self.firewall.set_visible(bool(firewall))
        allowed = bool(self.backend.state_get("firewall_allowed"))
        set_status_icon(self.fw_icon, "ok" if allowed else "info")
        self.fw_button.set_label(_("Open again") if allowed else _("Open port"))

    def _show_tailscale(self, info: TailscaleInfo) -> None:
        while (child := self.away_suffix.get_first_child()) is not None:
            self.away_suffix.remove(child)
        if not info.installed:
            self._away(
                "info",
                _("Tailscale is not installed"),
                _(
                    "Install it from the software store (package “tailscale”), sign in to your account and "
                    "also install the Tailscale app on the phone."
                ),
            )
            more = Gtk.Button(label=_("Learn more"))
            more.connect("clicked", lambda b: open_uri(b, TAILSCALE_DOWNLOAD_URL))
            self.away_suffix.append(more)
        elif not info.running or not info.ip:
            self._away(
                "warning",
                _("Tailscale is turned off"),
                _("Turn on Tailscale on this computer (“sudo tailscale up”) and sign in to your account."),
            )
        else:
            url = f"http://{info.dns_name or info.ip}:{IMMICH_PORT}"
            self._away("ok", _("Ready to use away from home"), url)
            self.away_suffix.append(
                icon_button(
                    "edit-copy-symbolic",
                    _("Copy address"),
                    lambda b: (copy_text(b, url), toast(b, _("Address copied"))),
                )
            )
            qr = Gtk.Button(label=_("Show QR"))
            qr.connect("clicked", lambda *_: self._show_away_qr())
            self.away_suffix.append(qr)

    def _show_away_qr(self) -> None:
        self.ctx.show_page("phones")
        phones = self.ctx.extras.get("phones")
        if phones is not None and hasattr(phones, "show_away"):
            phones.show_away()

    def _away(self, status: str, title: str, subtitle: str) -> None:
        set_status_icon(self.away_icon, status)
        self.away_row.set_title(GLib.markup_escape_text(title))
        self.away_row.set_subtitle(GLib.markup_escape_text(subtitle))

    def _copy_lan(self, button: Gtk.Button) -> None:
        if self._lan_url:
            copy_text(button, self._lan_url)
            toast(button, _("Address copied"))

    def _firewall(self, _button: Gtk.Button) -> None:
        def done(result: HelperResult) -> None:
            if result.ok:
                self.backend.state_set("firewall_allowed", True)
                toast(self, _("Port opened to the home network"))
                self.on_shown()
            else:
                show_error(self, result.error_code, result.error_detail, result.log)

        self.backend.helper("firewall-allow", [], None, done)
