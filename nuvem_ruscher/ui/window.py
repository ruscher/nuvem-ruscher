"""Janela principal: alterna entre o assistente e o painel (barra lateral)."""

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
        self.set_default_size(1120, 780)
        self.set_size_request(360, 520)
        if backend.simulated:
            self.add_css_class("devel")

        self.connect("close-request", self._close_request)
        self._closing = False
        self.toasts = Adw.ToastOverlay()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=300)
        self.toasts.set_child(self.stack)
        self.set_content(self.toasts)
        self.wizard = None
        self.shell = None

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

    def _close_request(self, _window: Adw.ApplicationWindow) -> bool:
        from nuvem_ruscher.ui.flow import BUSY

        if not BUSY or self._closing:
            return False
        alert = Adw.AlertDialog(
            heading=_("An operation is still running"),
            body=_(
                "Closing is safe: it continues in the background and does not stop halfway. Open Nuvem "
                "Ruscher again later to see the result."
            ),
        )
        alert.add_response("stay", _("Keep open"))
        alert.add_response("close", _("Close anyway"))
        alert.set_default_response("stay")
        alert.set_close_response("stay")

        def answered(_a: Adw.AlertDialog, response: str) -> None:
            if response == "close":
                self._closing = True
                self.close()

        alert.connect("response", answered)
        alert.present(self)
        return True

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
        from nuvem_ruscher.ui.shell import Shell

        if self.shell is None:
            self.shell = Shell(self.backend, self.menu, on_uninstalled=self._uninstalled)
            self.stack.add_named(self.shell, "shell")
        self.stack.set_visible_child_name("shell")
        self.shell.activate_monitor()
        self.set_title(APP_NAME)
        if self.wizard is not None:
            wizard = self.wizard
            self.wizard = None
            self.stack.remove(wizard)

    def _uninstalled(self) -> None:
        if self.shell is not None:
            self.shell.deactivate_monitor()
            shell = self.shell
            self.shell = None
            self.show_wizard("welcome")
            self.stack.remove(shell)
