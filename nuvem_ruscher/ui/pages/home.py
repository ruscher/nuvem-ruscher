"""Início: a nuvem está no ar? Números, saúde de cada parte e atalhos."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import Adw, Gtk

from nuvem_ruscher import APP_ID
from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.backend.base import BackupFile, HelperResult
from nuvem_ruscher.core import numbers
from nuvem_ruscher.core.storage import human_size
from nuvem_ruscher.core.system import TailscaleInfo
from nuvem_ruscher.i18n import N_, _
from nuvem_ruscher.ui.common import label, open_uri, set_status_icon, show_error, status_icon, toast
from nuvem_ruscher.ui.dialogs import ConnectStatsDialog
from nuvem_ruscher.ui.format import relative_time
from nuvem_ruscher.ui.page import Page, group, icon_tile

if TYPE_CHECKING:
    from nuvem_ruscher.ui.shell import AppContext

# Backup do banco mais velho que isso merece um aviso (o Immich faz um por dia).
BACKUP_STALE_S = 3 * 24 * 3600

HERO = {
    "loading": ("pending", N_("Checking…"), N_("Checking your cloud…"), ""),
    "ok": ("ok", N_("Online"), N_("Your cloud is online"), "{url}"),
    "starting": ("pending", N_("Starting…"), N_("Starting the server…"), N_("This takes about a minute.")),
    "stopping": ("pending", N_("Turning off…"), N_("Turning off…"), ""),
    "stopped": (
        "warning",
        N_("Turned off"),
        N_("Your cloud is turned off"),
        N_("Turn it on so phones can upload photos again."),
    ),
    "problem": (
        "error",
        N_("Needs attention"),
        N_("Your cloud needs attention"),
        N_("Some parts are not healthy. See System for details."),
    ),
    "failed": ("error", N_("Needs attention"), N_("The server could not start"), N_("See the logs or try again.")),
    "disk-missing": (
        "error",
        N_("Photo disk missing"),
        N_("The photo disk is not connected"),
        N_("Connect the disk and the server starts by itself."),
    ),
}


class StatCard(Gtk.Box):
    def __init__(self, title: str, icon_name: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("card")
        self.add_css_class("stat-card")
        top = Gtk.Box(spacing=8)
        image = Gtk.Image.new_from_icon_name(icon_name)
        image.add_css_class("dim-label")
        image.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        top.append(image)
        top.append(label(title, css=("dim-label", "caption-heading"), wrap=False))
        self.append(top)
        self.value = label("—", css=("stat-value", "numeric"), wrap=False)
        self.append(self.value)
        self.note = label("", css=("caption", "dim-label", "numeric"))
        self.append(self.note)

    def set(self, value: str, note: str = "") -> None:
        self.value.set_text(value)
        self.note.set_text(note)
        self.note.set_visible(bool(note))


class HealthTile(Gtk.Button):
    """Cartão clicável: uma parte da nuvem, seu estado (ícone + texto) e um detalhe."""

    def __init__(self, title: str, icon_name: str, tint: str, on_click: Callable[[], None]) -> None:
        super().__init__()
        self.add_css_class("card")
        self.add_css_class("health-tile")
        self._title = title
        box = Gtk.Box(spacing=12)
        box.append(icon_tile(icon_name, tint, size=18, tile="medium"))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        texts.append(label(title, css=("caption-heading", "dim-label"), wrap=False))
        state = Gtk.Box(spacing=6)
        self.icon = status_icon("pending", 14)
        state.append(self.icon)
        self.value = label(_("Checking…"), css=("heading",))
        self.value.set_width_chars(1)
        state.append(self.value)
        texts.append(state)
        self.detail = label("", css=("caption", "dim-label"))
        self.detail.set_width_chars(1)
        self.detail.set_visible(False)
        texts.append(self.detail)
        box.append(texts)
        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        arrow.add_css_class("dim-label")
        arrow.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        box.append(arrow)
        self.set_child(box)
        self.connect("clicked", lambda *_: on_click())

    def set_state(self, status: str, value: str, detail: str = "") -> None:
        set_status_icon(self.icon, status)
        self.value.set_text(value)
        self.detail.set_text(detail)
        self.detail.set_visible(bool(detail))
        self.update_property([Gtk.AccessibleProperty.LABEL], [f"{self._title}: {value}. {detail}".strip()])


class HomePage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(_("Your cloud"), "", f"{APP_ID}-symbolic", "blue")
        self.ctx = ctx
        self.backend = ctx.backend
        self.monitor = ctx.monitor
        self.hero.add_css_class("home-hero")

        # Pílula de estado acima do título: ícone + texto (nunca só cor).
        self.state_pill = Gtk.Box(spacing=6, halign=Gtk.Align.START)
        self.state_pill.add_css_class("state-pill")
        self.hero_state = status_icon("pending", 14)
        self.state_text = label("", css=("caption-heading",), wrap=False)
        self.state_pill.append(self.hero_state)
        self.state_pill.append(self.state_text)
        self.hero_title.get_parent().insert_child_after(self.state_pill, None)

        self.open_button = Gtk.Button(label=_("Open Immich"), valign=Gtk.Align.CENTER)
        self.open_button.add_css_class("pill")
        self.open_button.add_css_class("suggested-action")
        self.open_button.connect("clicked", lambda b: open_uri(b, self.backend.local_url))
        self.add_hero_action(self.open_button)
        self.power = Gtk.Button(valign=Gtk.Align.CENTER)
        self.power.add_css_class("pill")
        self.power.connect("clicked", self._power)
        self.add_hero_action(self.power)

        self.banner = Adw.Banner(revealed=False)
        self.banner.connect("button-clicked", lambda *_: self._service("start"))
        self.prepend_banner(self.banner)

        # Números
        glance = group(_("At a glance"))
        cards = Adw.WrapBox(child_spacing=12, line_spacing=12, justify=Adw.JustifyMode.FILL, justify_last_line=True)
        self.photos = StatCard(_("Photos"), "camera-photo-symbolic")
        self.videos = StatCard(_("Videos"), "camera-video-symbolic")
        self.space = StatCard(_("Space used"), "drive-harddisk-symbolic")
        self.space_bar = Gtk.LevelBar(min_value=0, max_value=1)
        for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            self.space_bar.remove_offset_value(offset)
        self.space_bar.set_margin_top(6)
        self.space_bar.update_property([Gtk.AccessibleProperty.LABEL], [_("Space used on the photo disk")])
        self.space.append(self.space_bar)
        for card in (self.photos, self.videos, self.space):
            card.set_size_request(200, -1)
            cards.append(card)
        glance_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        glance_box.append(cards)
        self.connect_stats = Gtk.Button(label=_("Show how many photos you have"), halign=Gtk.Align.START)
        self.connect_stats.add_css_class("flat")
        self.connect_stats.set_visible(False)
        self.connect_stats.connect("clicked", self._connect_stats)
        glance_box.append(self.connect_stats)
        glance.add(glance_box)
        self.add(glance)

        # Saúde
        health = group(_("Health"), _("Each part of your cloud. Select one for details."))
        self.tiles_box = Adw.WrapBox(
            child_spacing=12, line_spacing=12, justify=Adw.JustifyMode.FILL, justify_last_line=True
        )
        show = ctx.show_page
        self.tiles: dict[str, HealthTile] = {
            "server": HealthTile(_("Server"), "network-server-symbolic", "blue", lambda: show("system")),
            "storage": HealthTile(_("Storage"), "drive-harddisk-symbolic", "teal", lambda: show("storage")),
            "backups": HealthTile(_("Backups"), "document-save-symbolic", "yellow", lambda: show("backups")),
            "network": HealthTile(_("Network"), "network-wireless-symbolic", "blue", lambda: show("network")),
        }
        for tile in self.tiles.values():
            tile.set_size_request(270, -1)
            self.tiles_box.append(tile)
        health.add(self.tiles_box)
        self.add(health)

        # Atalhos
        actions = group(_("Quick actions"))
        self.actions_box = Adw.WrapBox(child_spacing=8, line_spacing=8)
        self.add_action(_("Connect a phone"), "phone-symbolic", lambda: show("phones"))
        self.add_action(_("Storage"), "drive-harddisk-symbolic", lambda: show("storage"))
        self.add_action(_("Back up now"), "document-save-symbolic", lambda: show("backups"))
        self.add_action(_("View logs"), "utilities-terminal-symbolic", lambda: show("logs"))
        actions.add(self.actions_box)
        self.add(actions)

        self.monitor.connect("changed", lambda *_: self.update())
        self._last_slow = 0.0
        self.update()

    def prepend_banner(self, banner: Adw.Banner) -> None:
        self.insert_child_after(banner, None)

    def add_action(self, text: str, icon_name: str, callback: Callable[[], None], first: bool = False) -> Gtk.Button:
        content = Adw.ButtonContent(label=text, icon_name=icon_name)
        button = Gtk.Button(child=content)
        button.add_css_class("pill")
        button.add_css_class("quick-action")
        button.connect("clicked", lambda *_: callback())
        if first:
            self.actions_box.insert_child_after(button, None)
        else:
            self.actions_box.append(button)
        return button

    def add_tile(self, key: str, tile: HealthTile, after: str | None = None) -> None:
        tile.set_size_request(270, -1)
        self.tiles[key] = tile
        sibling = self.tiles.get(after) if after else None
        if sibling is not None:
            self.tiles_box.insert_child_after(tile, sibling)
        else:
            self.tiles_box.append(tile)

    # --- atualização ---------------------------------------------------------------------
    def on_shown(self) -> None:
        self.update()
        self._refresh_slow(force=True)

    def update(self) -> None:
        m = self.monitor
        overall = m.overall
        status, pill, title, desc = HERO[overall]
        url = self.backend.server_url() if overall == "ok" else ""
        self.hero_title.set_text(_(title))
        self.set_description(_(desc).format(url=url) if desc else "")
        set_status_icon(self.hero_state, status)
        self.state_text.set_text(_(pill))
        for cls in ("ok", "pending", "warning", "error"):
            self.state_pill.remove_css_class(cls)
        self.state_pill.add_css_class(status)
        busy = bool(m.busy_action)
        running = overall in ("ok", "starting", "problem")
        self.power.set_label(_("Turn off") if running else _("Turn on"))
        self.power.set_sensitive(not busy and overall not in ("loading", "disk-missing"))
        if running:
            self.power.remove_css_class("suggested-action")
        else:
            self.power.add_css_class("suggested-action")
        self.open_button.set_visible(overall == "ok")

        if overall == "disk-missing":
            disk = os.path.basename(m.conf.mount_point) or _("photos")
            self.banner.set_title(_("The “{disk}” disk is not connected.").format(disk=disk))
            self.banner.set_button_label(None)
            self.banner.set_revealed(True)
        elif overall in ("stopped", "failed"):
            self.banner.set_title(_("The server is turned off. Your photos are not being backed up."))
            self.banner.set_button_label(_("Turn on"))
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

        if m.statistics is not None:
            self.photos.set(numbers.integer(m.statistics.photos))
            self.videos.set(
                numbers.integer(m.statistics.videos),
                _("{size} in total").format(size=human_size(m.statistics.usage)),
            )
            self.connect_stats.set_visible(False)
        else:
            has_key = self.backend.has_stats_key()
            if overall != "ok":
                note = _("Available with the server on")
            elif not has_key:
                note = _("Connect your account to see")
            else:
                note = _("Loading…")
            self.photos.set("—", note)
            self.videos.set("—")
            self.connect_stats.set_visible(not has_key and overall == "ok")
        total, used, free = m.disk
        if total:
            self.space.set(
                human_size(used),
                _("{free} free of {total}").format(free=human_size(free), total=human_size(total)),
            )
            self.space_bar.set_value(used / total)
        else:
            self.space.set("—", _("Disk not found"))
            self.space_bar.set_value(0)

        server = {
            "ok": ("ok", _("Running")),
            "starting": ("pending", _("Starting…")),
            "stopping": ("pending", _("Turning off…")),
            "stopped": ("warning", _("Turned off")),
            "problem": ("error", _("Needs attention")),
            "failed": ("error", _("Could not start")),
            "disk-missing": ("error", _("Waiting for the photo disk")),
            "loading": ("pending", _("Checking…")),
        }[overall]
        self.tiles["server"].set_state(
            server[0], server[1], m.conf.immich_version and f"Immich {m.conf.immich_version}"
        )
        if overall == "disk-missing":
            self.tiles["storage"].set_state("error", _("Disk disconnected"), m.conf.upload_location)
        elif total:
            level = "warning" if free < 0.05 * total else "ok"
            value = _("Almost full") if level == "warning" else _("Healthy")
            self.tiles["storage"].set_state(level, value, _("{free} free").format(free=human_size(free)))
        self._refresh_slow()

    def _refresh_slow(self, force: bool = False) -> None:
        """Backups e rede: bastam a cada 60 s (ou ao abrir a página)."""
        now = time.monotonic()
        if not force and now - self._last_slow < 60:
            return
        self._last_slow = now
        run_async(self.backend.backups, on_done=self._show_backups, on_error=lambda _e: None)

        def network() -> tuple[str, TailscaleInfo]:
            return self.backend.lan_ip(), self.backend.tailscale()

        run_async(network, on_done=self._show_network, on_error=lambda _e: None)

    def _show_backups(self, backups: list[BackupFile]) -> None:
        tile = self.tiles["backups"]
        if not backups:
            tile.set_state("warning", _("No backup yet"), _("Immich makes one every night"))
            return
        newest = max(b.mtime for b in backups)
        level = "warning" if time.time() - newest > BACKUP_STALE_S else "ok"
        tile.set_state(level, _("Last backup: {when}").format(when=relative_time(newest)), _("Database only"))

    def _show_network(self, result: tuple[str, TailscaleInfo]) -> None:
        lan, tailscale = result
        tile = self.tiles["network"]
        away = _("Away from home: on") if tailscale.running and tailscale.ip else _("Away from home: off")
        if lan:
            tile.set_state("ok", _("Home network"), away)
        else:
            tile.set_state("warning", _("Not connected"), _("Connect this computer to Wi-Fi or cable"))

    # --- ações -------------------------------------------------------------------------------
    def _power(self, _button: Gtk.Button) -> None:
        running = self.monitor.overall in ("ok", "starting", "problem")
        self._service("stop" if running else "start")

    def _service(self, action: str) -> None:
        self.monitor.busy_action = action
        self.update()

        def done(result: HelperResult) -> None:
            self.monitor.busy_action = ""
            self.monitor.refresh()
            if result.ok:
                messages = {
                    "start": _("Starting the server…"),
                    "stop": _("Server turned off"),
                    "restart": _("Restarting…"),
                }
                toast(self, messages[action])
            else:
                self.update()
                show_error(
                    self, result.error_code, result.error_detail, result.log, retry=lambda: self._service(action)
                )

        self.backend.helper(action, [], None, done)

    def _connect_stats(self, _button: Gtk.Button) -> None:
        ConnectStatsDialog(self.backend, on_done=self.monitor.refresh_statistics).present(self.get_root())
