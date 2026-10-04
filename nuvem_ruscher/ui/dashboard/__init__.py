"""Painel das execuções seguintes."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gio, GObject, Gtk

from nuvem_ruscher.backend.base import Backend
from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.dashboard.backups import BackupsPage
from nuvem_ruscher.ui.dashboard.logs import LogsPage
from nuvem_ruscher.ui.dashboard.monitor import ServerMonitor
from nuvem_ruscher.ui.dashboard.more import MorePage
from nuvem_ruscher.ui.dashboard.overview import OverviewPage
from nuvem_ruscher.ui.dashboard.updates import UpdatesPage
from nuvem_ruscher.ui.widgets.phone import PhoneView


class Dashboard(Adw.BreakpointBin):
    def __init__(self, backend: Backend, menu: Gio.MenuModel, on_uninstalled: Callable[[], None]) -> None:
        super().__init__()
        self.set_size_request(360, 480)
        self.backend = backend
        self.monitor = ServerMonitor(backend)

        self.stack = Adw.ViewStack()
        self.overview = OverviewPage(backend, self.monitor, go_phone=lambda: self.show("phone"))
        self.phone = PhoneView(backend, show_title=False)
        phone_scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        phone_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for margin in ("top", "bottom"):
            getattr(phone_box, f"set_margin_{margin}")(24)
        phone_box.set_margin_start(16)
        phone_box.set_margin_end(16)
        phone_box.append(self.phone)
        phone_scroller.set_child(Adw.Clamp(maximum_size=760, child=phone_box))
        self.logs = LogsPage(backend)
        self.backups = BackupsPage(backend, self.monitor)
        self.updates = UpdatesPage(backend, self.monitor)
        self.more = MorePage(backend, self.monitor, self._phone_away, on_uninstalled)

        for name, title, icon, widget in (
            ("overview", _("Início"), "computer-symbolic", self.overview),
            ("phone", _("Celular"), "phone-symbolic", phone_scroller),
            ("logs", _("Registros"), "utilities-terminal-symbolic", self.logs),
            ("backups", _("Backups"), "document-save-symbolic", self.backups),
            ("updates", _("Atualizar"), "software-update-available-symbolic", self.updates),
            ("more", _("Mais"), "view-more-horizontal-symbolic", self.more),
        ):
            self.stack.add_titled_with_icon(widget, name, title, icon)
        self.stack.connect("notify::visible-child-name", self._page_changed)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(self.switcher)
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True)
        menu_button.set_tooltip_text(_("Menu"))
        header.pack_end(menu_button)
        toolbar.add_top_bar(header)
        toolbar.set_content(self.stack)
        self.bar = Adw.ViewSwitcherBar(stack=self.stack)
        toolbar.add_bottom_bar(self.bar)
        self.set_child(toolbar)

        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 680sp"))
        breakpoint_.add_setter(self.bar, "reveal", GObject.Value(bool, True))
        title = Adw.WindowTitle(title="Nuvem Ruscher")
        breakpoint_.add_setter(header, "title-widget", GObject.Value(Gtk.Widget, title))
        self.add_breakpoint(breakpoint_)

        # Atalhos: Ctrl+1…6, F5, Ctrl+F
        controller = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        for index, name in enumerate(("overview", "phone", "logs", "backups", "updates", "more"), start=1):
            controller.add_shortcut(
                Gtk.Shortcut(
                    trigger=Gtk.ShortcutTrigger.parse_string(f"<primary>{index}"),
                    action=Gtk.CallbackAction.new(lambda *_a, n=name: self.show(n) or True),
                )
            )
        controller.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("F5"),
                action=Gtk.CallbackAction.new(lambda *_a: self.refresh() or True),
            )
        )
        controller.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("<primary>f"),
                action=Gtk.CallbackAction.new(lambda *_a: self._find() or True),
            )
        )
        self.add_controller(controller)
        self._root_handler = 0

    def show(self, name: str) -> None:
        self.stack.set_visible_child_name(name)

    def _find(self) -> None:
        self.show("logs")
        self.logs.focus_search()

    def _phone_away(self) -> None:
        self.show("phone")
        if self.phone.where.get_visible():
            self.phone.where.set_active_name("away")

    def refresh(self) -> None:
        self.monitor.refresh()
        self.monitor.refresh_statistics()
        self._page_changed()

    def activate_monitor(self) -> None:
        self.monitor.start()
        root = self.get_root()
        if isinstance(root, Gtk.Window) and not self._root_handler:
            self._root_handler = root.connect("notify::is-active", lambda *_: self._page_changed())
        self._page_changed()

    def deactivate_monitor(self) -> None:
        self.monitor.stop()
        self.logs.set_active(False)

    def _page_changed(self, *_args: object) -> None:
        name = self.stack.get_visible_child_name()
        root = self.get_root()
        window_active = isinstance(root, Gtk.Window) and root.is_active()
        self.monitor.want_stats = name == "overview" and window_active
        if self.monitor.want_stats:
            self.monitor.refresh_stats()
        self.logs.set_active(name == "logs")
        if name == "backups":
            self.backups.refresh()
        elif name == "updates" and self.updates.info is None:
            self.updates.refresh()
        elif name == "more":
            self.more.refresh()
        elif name == "phone":
            self.phone.refresh()
