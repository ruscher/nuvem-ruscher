"""Navegação principal: barra lateral com as páginas e área de conteúdo."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from gi.repository import Adw, Gio, GObject, Gtk

from nuvem_ruscher import APP_NAME
from nuvem_ruscher.backend.base import Backend
from nuvem_ruscher.i18n import N_, _
from nuvem_ruscher.ui.common import label
from nuvem_ruscher.ui.monitor import ServerMonitor
from nuvem_ruscher.ui.page import Page, icon_tile

# (seção, ((id, título, ícone, cor), …)) — a ordem também define os atalhos Ctrl+1…9.
NAVIGATION = (
    (
        N_("Your cloud"),
        (
            ("home", N_("Home"), "go-home-symbolic", "blue"),
            ("phones", N_("Phones"), "phone-symbolic", "green"),
            ("users", N_("Accounts"), "system-users-symbolic", "violet"),
            ("sharing", N_("Sharing"), "folder-publicshare-symbolic", "orange"),
        ),
    ),
    (
        N_("Your data"),
        (
            ("storage", N_("Storage"), "drive-harddisk-symbolic", "teal"),
            ("backups", N_("Backups"), "document-save-symbolic", "yellow"),
        ),
    ),
    (
        N_("System"),
        (
            ("network", N_("Network"), "network-wireless-symbolic", "blue"),
            ("updates", N_("Updates"), "software-update-available-symbolic", "green"),
            ("logs", N_("Logs"), "utilities-terminal-symbolic", "slate"),
            ("system", N_("System"), "preferences-system-symbolic", "slate"),
        ),
    ),
)
PAGE_IDS = tuple(page for _section, pages in NAVIGATION for page, *_rest in pages)

STATUS_TEXT = {
    "loading": N_("Checking…"),
    "ok": N_("Online"),
    "starting": N_("Starting…"),
    "stopping": N_("Turning off…"),
    "stopped": N_("Turned off"),
    "problem": N_("Needs attention"),
    "failed": N_("Needs attention"),
    "disk-missing": N_("Photo disk missing"),
}


@dataclass
class AppContext:
    """O que toda página recebe: o sistema, o estado ao vivo e a navegação."""

    backend: Backend
    monitor: ServerMonitor
    show_page: Callable[[str], None]
    on_uninstalled: Callable[[], None]
    extras: dict[str, object] = field(default_factory=dict)


class NavRow(Gtk.ListBoxRow):
    def __init__(self, page_id: str, title: str, icon_name: str, tint: str, section: str) -> None:
        super().__init__()
        self.page_id = page_id
        self.section = section
        box = Gtk.Box(spacing=12)
        box.append(icon_tile(icon_name, tint))
        self.title = label(title, wrap=False, xalign=0)
        self.title.set_hexpand(True)
        box.append(self.title)
        self.badge = label("", css=("nav-badge",), wrap=False)
        self.badge.set_valign(Gtk.Align.CENTER)
        self.badge.set_visible(False)
        box.append(self.badge)
        self.set_child(box)
        self._title_text = title
        self.update_property([Gtk.AccessibleProperty.LABEL], [title])

    def set_badge(self, text: str | None, level: str = "warning") -> None:
        for cls in ("warning", "error", "accent"):
            self.badge.remove_css_class(cls)
        self.badge.set_visible(bool(text))
        if text:
            self.badge.set_text(text)
            self.badge.add_css_class(level)
            # O selo não pode depender só da cor: o leitor de tela também o anuncia.
            self.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [_("{page} — needs attention").format(page=self._title_text)],
            )
        else:
            self.update_property([Gtk.AccessibleProperty.LABEL], [self._title_text])


class Shell(Adw.BreakpointBin):
    def __init__(self, backend: Backend, menu: Gio.MenuModel, on_uninstalled: Callable[[], None]) -> None:
        super().__init__()
        self.set_size_request(360, 480)
        self.backend = backend
        self.monitor = ServerMonitor(backend)
        self.ctx = AppContext(backend, self.monitor, self.show, on_uninstalled)
        self.ctx.extras["shell"] = self
        self.pages: dict[str, Page] = {}
        self.rows: dict[str, NavRow] = {}
        self._current = ""

        # Barra lateral
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("navigation-sidebar")
        self.nav.set_header_func(self._section_header)
        self.nav.connect("row-selected", self._row_selected)
        self.nav.update_property([Gtk.AccessibleProperty.LABEL], [_("Pages")])
        for section, entries in NAVIGATION:
            for page_id, title, icon_name, tint in entries:
                row = NavRow(page_id, _(title), icon_name, tint, _(section))
                self.rows[page_id] = row
                self.nav.append(row)
        sidebar_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=self.nav)
        sidebar = Adw.ToolbarView()
        sidebar.add_css_class("nr-sidebar")
        sidebar_header = Adw.HeaderBar(show_end_title_buttons=False)
        self.sidebar_title = Adw.WindowTitle(title=APP_NAME, subtitle=_(STATUS_TEXT["loading"]))
        sidebar_header.set_title_widget(self.sidebar_title)
        sidebar.add_top_bar(sidebar_header)
        sidebar.set_content(sidebar_scroll)

        # Conteúdo
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=150)
        self.stack.set_vhomogeneous(False)
        content = Adw.ToolbarView()
        content.add_css_class("nr-content")
        self.content_header = Adw.HeaderBar(show_title=False)
        self.toggle = Gtk.ToggleButton(icon_name="sidebar-show-symbolic", visible=False)
        self.toggle.set_tooltip_text(_("Show pages"))
        self.toggle.update_property([Gtk.AccessibleProperty.LABEL], [_("Show pages")])
        self.content_header.pack_start(self.toggle)
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True)
        menu_button.set_tooltip_text(_("Main menu"))
        self.content_header.pack_end(menu_button)
        content.add_top_bar(self.content_header)
        content.set_content(self.stack)

        self.split = Adw.OverlaySplitView(
            sidebar=sidebar,
            content=content,
            min_sidebar_width=232,
            max_sidebar_width=290,
            sidebar_width_fraction=0.25,
        )
        self.split.bind_property(
            "show-sidebar", self.toggle, "active", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE
        )
        self.set_child(self.split)

        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 760sp"))
        narrow.add_setter(self.split, "collapsed", GObject.Value(bool, True))
        narrow.add_setter(self.toggle, "visible", GObject.Value(bool, True))
        narrow.add_setter(self.content_header, "show-title", GObject.Value(bool, True))
        self.add_breakpoint(narrow)
        self.page_title = Adw.WindowTitle()
        self.content_header.set_title_widget(self.page_title)

        self._build_pages()
        for page in self.pages.values():
            narrow.add_setter(page.hero_tile, "visible", GObject.Value(bool, False))
            narrow.add_setter(page.hero_actions, "halign", GObject.Value(Gtk.Align, Gtk.Align.START))
        self._install_shortcuts()
        self.monitor.connect("changed", lambda *_: self._status_changed())
        self._root_handler = 0
        self.show("home")

    # --- páginas ---------------------------------------------------------------------------
    def _build_pages(self) -> None:
        from nuvem_ruscher.ui.pages import build_pages

        for page_id, page in build_pages(self.ctx).items():
            page.page_id = page_id
            self.pages[page_id] = page
            self.stack.add_named(page, page_id)
        for page_id, row in self.rows.items():
            row.set_visible(page_id in self.pages)
        self.ctx.extras.update(self.pages)

    def show(self, page_id: str) -> None:
        if page_id not in self.pages:
            return
        row = self.rows[page_id]
        if self.nav.get_selected_row() is not row:
            self.nav.select_row(row)  # chama _row_selected
        else:
            self._switch(page_id)

    def page(self, page_id: str) -> Page | None:
        return self.pages.get(page_id)

    def _row_selected(self, _listbox: Gtk.ListBox, row: NavRow | None) -> None:
        if row is not None:
            self._switch(row.page_id)
            if self.split.get_collapsed():
                self.split.set_show_sidebar(False)

    def _switch(self, page_id: str) -> None:
        previous = self.pages.get(self._current)
        if previous is not None and self._current != page_id:
            previous.on_hidden()
        self._current = page_id
        page = self.pages[page_id]
        self.stack.set_visible_child(page)
        self.page_title.set_title(page.page_title)
        page.scroll_to_top()
        page.on_shown()
        self._update_stats_wish()

    def set_badge(self, page_id: str, text: str | None, level: str = "warning") -> None:
        row = self.rows.get(page_id)
        if row is not None:
            row.set_badge(text, level)

    def _section_header(self, row: NavRow, before: NavRow | None) -> None:
        if before is not None and before.section == row.section:
            row.set_header(None)
            return
        header = label(row.section, css=("nav-section", "caption-heading"), wrap=False)
        row.set_header(header)

    # --- estado ---------------------------------------------------------------------------
    def _status_changed(self) -> None:
        overall = self.monitor.overall
        self.sidebar_title.set_subtitle(_(STATUS_TEXT.get(overall, STATUS_TEXT["loading"])))
        self.set_badge("home", "!" if overall in ("problem", "failed", "disk-missing") else None)

    def _update_stats_wish(self) -> None:
        root = self.get_root()
        window_active = isinstance(root, Gtk.Window) and root.is_active()
        self.monitor.want_stats = self._current == "system" and window_active
        if self.monitor.want_stats:
            self.monitor.refresh_stats()

    def refresh(self) -> None:
        self.monitor.refresh()
        self.monitor.refresh_statistics()
        page = self.pages.get(self._current)
        if page is not None:
            page.on_shown()

    def activate_monitor(self) -> None:
        self.monitor.start()
        root = self.get_root()
        if isinstance(root, Gtk.Window) and not self._root_handler:
            self._root_handler = root.connect("notify::is-active", lambda *_: self._update_stats_wish())
        page = self.pages.get(self._current)
        if page is not None:
            page.on_shown()

    def deactivate_monitor(self) -> None:
        self.monitor.stop()
        for page in self.pages.values():
            page.on_hidden()

    # --- atalhos ---------------------------------------------------------------------------
    def _install_shortcuts(self) -> None:
        controller = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)

        def add(trigger: str, callback: Callable[[], None]) -> None:
            controller.add_shortcut(
                Gtk.Shortcut(
                    trigger=Gtk.ShortcutTrigger.parse_string(trigger),
                    action=Gtk.CallbackAction.new(lambda *_a: callback() or True),
                )
            )

        for accel, page_id in self._shortcut_pages():
            add(accel, lambda p=page_id: self.show(p))
        add("F5", self.refresh)
        add("<primary>r", self.refresh)
        add("<primary>f", self._find)
        self.add_controller(controller)

    def _shortcut_pages(self) -> list[tuple[str, str]]:
        visible = [page_id for page_id in PAGE_IDS if page_id in self.pages]
        return [(f"<primary>{index}", page_id) for index, page_id in enumerate(visible[:9], start=1)]

    def shortcut_titles(self) -> list[tuple[str, str]]:
        return [(accel, self.pages[page_id].page_title) for accel, page_id in self._shortcut_pages()]

    def _find(self) -> None:
        self.show("logs")
        logs = self.pages.get("logs")
        if logs is not None and hasattr(logs, "focus_search"):
            logs.focus_search()
