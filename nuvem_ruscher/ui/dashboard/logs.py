"""Registros em tempo real, com filtro, pausa da rolagem e copiar."""

from __future__ import annotations

from collections import deque

from gi.repository import Adw, GLib, Gtk, Pango

from nuvem_ruscher.async_utils import Debouncer, Operation
from nuvem_ruscher.backend.base import Backend
from nuvem_ruscher.constants import CONTAINERS
from nuvem_ruscher.core.docker import container_label
from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.common import copy_text, toast

MAX_LINES = 3000


class LogsPage(Gtk.Box):
    def __init__(self, backend: Backend) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.backend = backend
        self._lines: deque[str] = deque(maxlen=MAX_LINES)
        self._op: Operation | None = None
        self._active = False

        bar = Gtk.Box(spacing=8)
        for margin in ("top", "bottom", "start", "end"):
            getattr(bar, f"set_margin_{margin}")(12)
        self.container = Gtk.DropDown.new_from_strings([container_label(n) for n in CONTAINERS])
        self.container.set_tooltip_text(_("Componente"))
        self.container.update_property([Gtk.AccessibleProperty.LABEL], [_("Componente")])
        self.container.connect("notify::selected", lambda *_: self._restart())
        bar.append(self.container)
        self.search = Gtk.SearchEntry(hexpand=True, placeholder_text=_("Filtrar registros (ex.: erro)"))
        self.search.update_property([Gtk.AccessibleProperty.LABEL], [_("Filtrar registros")])
        self._refilter = Debouncer(200, self._render)
        self.search.connect("search-changed", lambda *_: self._refilter())
        bar.append(self.search)
        self.follow = Gtk.ToggleButton(icon_name="go-bottom-symbolic", active=True)
        self.follow.set_tooltip_text(_("Acompanhar os registros novos"))
        self.follow.update_property([Gtk.AccessibleProperty.LABEL], [_("Acompanhar os registros novos")])
        bar.append(self.follow)
        copy = Gtk.Button(icon_name="edit-copy-symbolic")
        copy.set_tooltip_text(_("Copiar os registros mostrados"))
        copy.update_property([Gtk.AccessibleProperty.LABEL], [_("Copiar os registros mostrados")])
        copy.connect("clicked", self._copy)
        bar.append(copy)
        self.append(bar)

        self.buffer = Gtk.TextBuffer()
        table = self.buffer.get_tag_table()
        self.tag_error = Gtk.TextTag(name="erro", foreground="#e01b24", weight=Pango.Weight.BOLD)
        self.tag_warn = Gtk.TextTag(name="aviso", foreground="#c64600")
        table.add(self.tag_error)
        table.add(self.tag_warn)
        view = Gtk.TextView(buffer=self.buffer, editable=False, cursor_visible=False, monospace=True)
        view.add_css_class("log-view")
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        for side in ("top", "bottom", "left", "right"):
            getattr(view, f"set_{side}_margin")(12)
        view.update_property([Gtk.AccessibleProperty.LABEL], [_("Registros do servidor")])
        self.scroller = Gtk.ScrolledWindow(vexpand=True, child=view)
        self.stack = Gtk.Stack()
        empty = Adw.StatusPage(
            icon_name="utilities-terminal-symbolic",
            title=_("Nada por aqui ainda"),
            description=_("Os registros aparecem quando o servidor está ligado."),
        )
        self.stack.add_named(empty, "empty")
        self.stack.add_named(self.scroller, "logs")
        self.append(self.stack)

    # Chamado pelo painel quando a aba aparece/some (economia de recursos).
    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self._restart()
        elif self._op is not None:
            self._op.cancel()
            self._op = None

    def focus_search(self) -> None:
        self.search.grab_focus()

    def _restart(self) -> None:
        if self._op is not None:
            self._op.cancel()
            self._op = None
        self._lines.clear()
        self.buffer.set_text("")
        self.stack.set_visible_child_name("empty")
        if not self._active:
            return
        name = CONTAINERS[self.container.get_selected()]
        try:
            self._op = self.backend.follow_logs(name, self._on_line, lambda _code: None)
        except (OSError, ValueError):
            self._op = None

    def _matches(self, line: str) -> bool:
        query = self.search.get_text().strip().lower()
        return not query or query in line.lower()

    def _insert(self, line: str) -> None:
        end = self.buffer.get_end_iter()
        lowered = line.lower()
        if " error " in lowered or "error:" in lowered or "erro" in lowered or "fatal" in lowered:
            self.buffer.insert_with_tags(end, line + "\n", self.tag_error)
        elif " warn" in lowered:
            self.buffer.insert_with_tags(end, line + "\n", self.tag_warn)
        else:
            self.buffer.insert(end, line + "\n")

    def _on_line(self, line: str) -> None:
        overflow = len(self._lines) == MAX_LINES
        self._lines.append(line)
        self.stack.set_visible_child_name("logs")
        if overflow:
            start = self.buffer.get_start_iter()
            second = self.buffer.get_iter_at_line(1)[1]
            self.buffer.delete(start, second)
        if self._matches(line):
            self._insert(line)
            self._scroll()

    def _render(self) -> None:
        self.buffer.set_text("")
        for line in self._lines:
            if self._matches(line):
                self._insert(line)
        self._scroll()

    def _scroll(self) -> None:
        if not self.follow.get_active():
            return
        adj = self.scroller.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()) or False)

    def _copy(self, button: Gtk.Button) -> None:
        start, end = self.buffer.get_bounds()
        copy_text(button, self.buffer.get_text(start, end, False))
        toast(button, _("Registros copiados"))
