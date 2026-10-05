"""Janela principal: alterna entre o assistente e o painel."""

from __future__ import annotations

from gi.repository import Adw, Gio, Gtk

from nuvem_ruscher import APP_NAME
from nuvem_ruscher.backend.base import Backend
from nuvem_ruscher.i18n import _


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, backend: Backend, menu: Gio.MenuModel) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.backend = backend
        self.menu = menu
        self.set_default_size(920, 760)
        self.set_size_request(360, 520)
        if backend.simulated:
            self.add_css_class("devel")

        self.toasts = Adw.ToastOverlay()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=300)
        self.toasts.set_child(self.stack)
        self.set_content(self.toasts)
        self.wizard = None
        self.dashboard = None

        # Decisão instantânea (lê um arquivo pequeno): nada de tela de carregamento.
        conf = backend.load_config()
        wizard_done = bool(backend.state_get("wizard_done", False))
        if conf.installed and wizard_done:
            self.show_dashboard()
        elif conf.installed:
            step = str(backend.state_get("install_step", "") or "")
            self.show_wizard("account" if step == "done" else "install")
        else:
            self.show_wizard("welcome")

    def toast(self, text: str, timeout: int = 3) -> None:
        self.toasts.add_toast(Adw.Toast(title=text, timeout=timeout))

    def show_wizard(self, start: str = "welcome") -> None:
        from nuvem_ruscher.ui.wizard import Wizard

        if self.wizard is None:
            self.wizard = Wizard(self.backend, self.menu, on_finish=self.show_dashboard)
            self.stack.add_named(self.wizard, "wizard")
        self.wizard.start(start)
        self.stack.set_visible_child_name("wizard")
        self.set_title(_("Set up {name}").format(name=APP_NAME))

    def show_dashboard(self) -> None:
        from nuvem_ruscher.ui.dashboard import Dashboard

        if self.dashboard is None:
            self.dashboard = Dashboard(self.backend, self.menu, on_uninstalled=self._uninstalled)
            self.stack.add_named(self.dashboard, "dashboard")
        self.stack.set_visible_child_name("dashboard")
        self.dashboard.activate_monitor()
        self.set_title(APP_NAME)
        if self.wizard is not None:
            wizard = self.wizard
            self.wizard = None
            self.stack.remove(wizard)

    def _uninstalled(self) -> None:
        if self.dashboard is not None:
            self.dashboard.deactivate_monitor()
            dashboard = self.dashboard
            self.dashboard = None
            self.show_wizard("welcome")
            self.stack.remove(dashboard)
