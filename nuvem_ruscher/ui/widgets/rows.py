"""Linhas de estado: verificação do sistema e etapas da instalação."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.ui.common import label, set_status_icon, status_icon


class StatusStack(Gtk.Stack):
    """Ícone de estado que alterna com um spinner, com transição suave."""

    def __init__(self, size: int = 18) -> None:
        super().__init__(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=200)
        self.set_valign(Gtk.Align.CENTER)
        self.icon = status_icon("pending", size)
        self.spinner = Adw.Spinner()
        self.spinner.set_size_request(size, size)
        self.add_named(self.icon, "icon")
        self.add_named(self.spinner, "spinner")
        self.set_visible_child_name("icon")

    def set_status(self, status: str) -> None:
        if status == "running":
            self.set_visible_child_name("spinner")
            return
        set_status_icon(self.icon, status)
        self.set_visible_child_name("icon")


class CheckRow(Adw.ActionRow):
    def __init__(self, title: str) -> None:
        super().__init__(title=title)
        self.set_title_lines(2)
        self.set_subtitle_lines(3)
        self.status = StatusStack()
        self.add_prefix(self.status)
        self.fix_button = Gtk.Button(valign=Gtk.Align.CENTER, visible=False)
        self.fix_button.add_css_class("suggested-action")
        self.add_suffix(self.fix_button)
        self._fix_handler = 0

    def set_running(self) -> None:
        self.status.set_status("running")
        self.fix_button.set_visible(False)

    def set_result(
        self,
        status: str,
        title: str,
        subtitle: str,
        fix_label: str = "",
        on_fix: Callable[[], None] | None = None,
    ) -> None:
        self.status.set_status(status)
        self.set_title(GLib.markup_escape_text(title))
        self.set_subtitle(GLib.markup_escape_text(subtitle))
        if self._fix_handler:
            self.fix_button.disconnect(self._fix_handler)
            self._fix_handler = 0
        if fix_label and on_fix:
            self.fix_button.set_label(fix_label)
            self.fix_button.set_visible(True)
            if status == "info":
                self.fix_button.remove_css_class("suggested-action")
            else:
                self.fix_button.add_css_class("suggested-action")
            self._fix_handler = self.fix_button.connect("clicked", lambda *_: on_fix())
        else:
            self.fix_button.set_visible(False)


class InstallStep(Gtk.Box):
    """Uma etapa da instalação: ícone, título, detalhe e (opcional) barra de progresso."""

    def __init__(self, title: str, with_progress: bool = False) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.add_css_class("install-step")
        self.add_css_class("pending")
        self.set_margin_top(10)
        self.set_margin_bottom(10)
        self.set_margin_start(14)
        self.set_margin_end(14)
        self.status = StatusStack(20)
        self.status.set_valign(Gtk.Align.START)
        self.append(self.status)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self.title = label(title, css=("step-title",))
        self.detail = label("", css=("dim-label", "caption", "numeric"))
        self.detail.set_visible(False)
        column.append(self.title)
        column.append(self.detail)
        self.progress: Gtk.ProgressBar | None = None
        self._animation: Adw.TimedAnimation | None = None
        if with_progress:
            self.progress = Gtk.ProgressBar(visible=False)
            self.progress.set_margin_top(6)
            column.append(self.progress)
            target = Adw.CallbackAnimationTarget.new(self.progress.set_fraction)
            self._animation = Adw.TimedAnimation(
                widget=self.progress, value_from=0, value_to=0, duration=250, target=target
            )
            self._animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        self.append(column)
        self.state = "pending"

    def set_state(self, state: str, detail: str | None = None) -> None:
        """pending | running | ok | error | warning"""
        self.state = state
        self.remove_css_class("pending")
        if state == "pending":
            self.add_css_class("pending")
        self.status.set_status(state)
        if detail is not None:
            self.set_detail(detail)
        if self.progress is not None:
            self.progress.set_visible(state == "running")

    def set_detail(self, text: str) -> None:
        self.detail.set_text(text)
        self.detail.set_visible(bool(text))

    def set_fraction(self, fraction: float) -> None:
        if self.progress is None or self._animation is None:
            return
        self._animation.pause()
        self._animation.set_value_from(self.progress.get_fraction())
        self._animation.set_value_to(max(0.0, min(fraction, 1.0)))
        self._animation.play()


class StepDots(Gtk.Box):
    """Indicador discreto de etapas do assistente."""

    def __init__(self, total: int, current: int) -> None:
        super().__init__(spacing=6, halign=Gtk.Align.CENTER)
        self.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        for index in range(total):
            dot = Gtk.Box()
            dot.add_css_class("step-dot")
            if index < current:
                dot.add_css_class("done")
            elif index == current:
                dot.add_css_class("current")
            self.append(dot)
