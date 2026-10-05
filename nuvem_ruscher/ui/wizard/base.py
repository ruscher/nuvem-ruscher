"""Estrutura comum das telas do assistente."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from gi.repository import Adw, Gtk

from nuvem_ruscher.backend.base import Backend, StorageReport
from nuvem_ruscher.ui.widgets.rows import StepDots

if TYPE_CHECKING:
    from nuvem_ruscher.ui.wizard import Wizard

TOTAL_STEPS = 6  # verificação, armazenamento, ajustes, instalação, conta, celular


@dataclass
class WizardContext:
    backend: Backend
    photo_path: str = ""
    storage: StorageReport | None = None
    version: str = ""
    timezone: str = ""
    transcode: str = "cpu"
    ml: str = "cpu"
    installed_now: bool = False
    extras: dict[str, object] = field(default_factory=dict)


class WizardPage(Adw.NavigationPage):
    """Cabeçalho, conteúdo rolável centralizado e barra de ações embaixo."""

    step: int | None = None

    def __init__(self, wizard: Wizard, title: str, tag: str, can_pop: bool = True) -> None:
        super().__init__(title=title, tag=tag, can_pop=can_pop)
        self.wizard = wizard
        self.ctx = wizard.ctx
        self.backend = wizard.ctx.backend
        self._first_show = True

        self.toolbar = Adw.ToolbarView()
        self.header = Adw.HeaderBar()
        self.header.pack_end(wizard.menu_button())
        self.toolbar.add_top_bar(self.header)

        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.body.set_margin_top(18)
        self.body.set_margin_bottom(30)
        self.body.set_margin_start(16)
        self.body.set_margin_end(16)
        if self.step is not None:
            dots = StepDots(TOTAL_STEPS, self.step)
            dots.set_margin_bottom(4)
            self.body.append(dots)
        clamp = Adw.Clamp(maximum_size=620, tightening_threshold=440, child=self.body)
        self.scroller.set_child(clamp)
        self.toolbar.set_content(self.scroller)

        self.actions = Gtk.Box(spacing=12)
        self.actions.add_css_class("wizard-actions")
        self.actions_start = Gtk.Box(spacing=12, hexpand=True)
        self.actions_end = Gtk.Box(spacing=12, halign=Gtk.Align.END)
        self.actions.append(self.actions_start)
        self.actions.append(self.actions_end)
        self.toolbar.add_bottom_bar(self.actions)
        self.set_child(self.toolbar)
        self.connect("shown", self._on_shown)

    def step_subtitle(self) -> str:
        from nuvem_ruscher.i18n import _

        if self.step is None:
            return ""
        return _("Step {n} of {total}").format(n=self.step + 1, total=TOTAL_STEPS)

    def set_header_title(self, title: str) -> None:
        self.header.set_title_widget(Adw.WindowTitle(title=title, subtitle=self.step_subtitle()))

    def add_action(self, button: Gtk.Button, start: bool = False, default: bool = False) -> Gtk.Button:
        (self.actions_start if start else self.actions_end).append(button)
        if default:
            self._default_button = button
        return button

    def _on_shown(self, _page: Adw.NavigationPage) -> None:
        default = getattr(self, "_default_button", None)
        root = self.get_root()
        if default is not None and isinstance(root, Gtk.Window):
            root.set_default_widget(default)
        first = self._first_show
        self._first_show = False
        self.on_shown(first)

    def on_shown(self, first: bool) -> None:
        """Sobrescrito pelas telas."""

    def toast(self, text: str) -> None:
        root = self.get_root()
        if root is not None and hasattr(root, "toast"):
            root.toast(text)
