"""Assistentes em diálogo (migração, RAID, contas): páginas com rodapé de ações.

Enquanto uma operação roda, o diálogo não fecha (``set_busy``) e diz por quê.
"""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.common import label
from nuvem_ruscher.ui.widgets.rows import InstallStep

# Diálogos com uma operação privilegiada em andamento.
BUSY: set[Adw.Dialog] = set()


class FlowPage(Adw.NavigationPage):
    def __init__(self, title: str, tag: str | None = None, can_pop: bool = True, width: int = 600) -> None:
        super().__init__(title=title, can_pop=can_pop)
        if tag:
            self.set_tag(tag)
        toolbar = Adw.ToolbarView()
        self.header = Adw.HeaderBar()
        toolbar.add_top_bar(self.header)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.body.add_css_class("flow-body")
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
        scroller.set_vexpand(True)
        scroller.set_child(Adw.Clamp(maximum_size=width, tightening_threshold=int(width * 0.8), child=self.body))
        toolbar.set_content(scroller)
        self.bar = Gtk.Box(spacing=12)
        self.bar.add_css_class("wizard-actions")
        self.bar_start = Gtk.Box(spacing=8, hexpand=True)
        self.bar_end = Gtk.Box(spacing=8)
        self.bar.append(self.bar_start)
        self.bar.append(self.bar_end)
        self.bar.set_visible(False)
        toolbar.add_bottom_bar(self.bar)
        self.set_child(toolbar)

    def add(self, widget: Gtk.Widget) -> Gtk.Widget:
        self.body.append(widget)
        return widget

    def intro(self, title: str, text: str, icon_name: str = "") -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        if icon_name:
            image = Gtk.Image.new_from_icon_name(icon_name)
            image.set_pixel_size(48)
            # Ícones de resultado usam a cor do estado; os demais, a cor de destaque.
            if "ok" in icon_name:
                image.add_css_class("success")
            elif "warning" in icon_name or "error" in icon_name:
                image.add_css_class("warning")
            else:
                image.add_css_class("accent")
            image.set_halign(Gtk.Align.START)
            image.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            box.append(image)
        heading = label(title, css=("title-2",))
        heading.set_accessible_role(Gtk.AccessibleRole.HEADING)
        box.append(heading)
        if text:
            box.append(label(text, css=("dim-label",)))
        self.add(box)

    def button(self, text: str, callback: Callable[[], None], style: str = "", start: bool = False) -> Gtk.Button:
        widget = Gtk.Button(label=text)
        widget.add_css_class("pill")
        if style:
            widget.add_css_class(style)
        widget.connect("clicked", lambda *_: callback())
        (self.bar_start if start else self.bar_end).append(widget)
        self.bar.set_visible(True)
        return widget


class FlowDialog(Adw.Dialog):
    def __init__(self, title: str, width: int = 640, height: int = 640) -> None:
        super().__init__(title=title, content_width=width, content_height=height)
        self.nav = Adw.NavigationView()
        self.set_child(self.nav)
        self._busy = False
        self._busy_reason = ""
        self.connect("close-attempt", self._close_attempt)

    def push(self, page: Adw.NavigationPage) -> None:
        self.nav.push(page)

    def replace(self, page: Adw.NavigationPage) -> None:
        self.nav.replace([page])

    def set_busy(self, busy: bool, reason: str = "") -> None:
        self._busy = busy
        self._busy_reason = reason
        self.set_can_close(not busy)
        # A janela principal também pergunta antes de fechar (ver MainWindow).
        BUSY.discard(self)
        if busy:
            BUSY.add(self)

    def _close_attempt(self, _dialog: Adw.Dialog) -> None:
        if self._busy:
            message = self._busy_reason or _("Please wait: an operation is running.")
            alert = Adw.AlertDialog(heading=_("Not yet"), body=message)
            alert.add_response("ok", _("Got it"))
            alert.present(self)


class StepList(Gtk.ListBox):
    """Etapas de uma operação longa, cada uma com estado (e progresso, se tiver)."""

    def __init__(self, steps: list[tuple[str, str, bool]]) -> None:
        super().__init__(selection_mode=Gtk.SelectionMode.NONE)
        self.add_css_class("boxed-list")
        self.steps: dict[str, InstallStep] = {}
        for key, title, with_progress in steps:
            step = InstallStep(title, with_progress)
            row = Gtk.ListBoxRow(activatable=False, child=step)
            self.append(row)
            self.steps[key] = step
        self._current = ""

    def start(self, key: str, detail: str = "") -> None:
        if key not in self.steps or key == self._current:
            return
        keys = list(self.steps)
        for previous in keys[: keys.index(key)]:
            if self.steps[previous].state in ("pending", "running"):
                self.steps[previous].set_state("ok")
        self.steps[key].set_state("running", detail)
        self._current = key

    def finish(self, ok: bool = True) -> None:
        for step in self.steps.values():
            if step.state == "running":
                step.set_state("ok" if ok else "error")
            elif ok and step.state == "pending":
                step.set_state("ok")

    def fail(self, key: str | None = None, detail: str = "") -> None:
        target = self.steps.get(key or self._current)
        if target is not None:
            target.set_state("error", detail or None)


class LogExpander(Gtk.Expander):
    """Detalhes técnicos recolhidos, atualizados linha a linha."""

    def __init__(self, title: str | None = None, keep: int = 80) -> None:
        super().__init__(label=title or _("Technical details"))
        self._lines: list[str] = []
        self._keep = keep
        self.text = label("", css=("monospace", "caption"), selectable=True)
        self.text.set_margin_top(6)
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True, max_content_height=200
        )
        scroller.set_child(self.text)
        self.set_child(scroller)

    def append(self, line: str) -> None:
        self._lines.append(line)
        self.text.set_text("\n".join(self._lines[-self._keep :]))

    @property
    def lines(self) -> list[str]:
        return list(self._lines)


def idle(callback: Callable[[], None]) -> None:
    GLib.idle_add(lambda: callback() or False)
