"""Assistente de primeira execução."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gio, Gtk

from nuvem_ruscher.backend.base import Backend
from nuvem_ruscher.ui.wizard.base import WizardContext, WizardPage

PAGE_ORDER = ("welcome", "checks", "storage", "configure", "install", "account", "phone", "done")


class Wizard(Adw.Bin):
    def __init__(self, backend: Backend, menu_model: Gio.MenuModel, on_finish: Callable[[], None]) -> None:
        super().__init__()
        self.ctx = WizardContext(backend=backend)
        self._menu_model = menu_model
        self.on_finish = on_finish
        self.nav = Adw.NavigationView()
        self.set_child(self.nav)
        self._pages: dict[str, WizardPage] = {}

    def menu_button(self) -> Gtk.MenuButton:
        button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=self._menu_model, primary=True)
        button.set_tooltip_text("Menu")
        return button

    def _page(self, tag: str) -> WizardPage:
        if tag not in self._pages:
            from nuvem_ruscher.ui.wizard import pages

            factory: dict[str, type[WizardPage]] = {
                "welcome": pages.WelcomePage,
                "checks": pages.ChecksPage,
                "storage": pages.StoragePage,
                "configure": pages.ConfigurePage,
                "install": pages.InstallPage,
                "account": pages.AccountPage,
                "phone": pages.PhonePage,
                "done": pages.DonePage,
            }
            self._pages[tag] = factory[tag](self)
        return self._pages[tag]

    def start(self, tag: str = "welcome") -> None:
        """Começa (ou retoma) numa tela. Retomar mantém as anteriores na pilha."""
        index = PAGE_ORDER.index(tag)
        stack = [self._page(t) for t in PAGE_ORDER[: index + 1]] if tag != "welcome" else [self._page("welcome")]
        if tag in ("install", "account", "phone", "done"):
            # Depois de instalado, voltar para a verificação não faz sentido.
            stack = [self._page(tag)]
        self.nav.replace(stack)

    def go(self, tag: str) -> None:
        self.nav.push(self._page(tag))

    def go_replace(self, tag: str) -> None:
        """Avança sem permitir voltar (ex.: depois da instalação)."""
        self.nav.replace([self._page(tag)])

    def finish(self) -> None:
        self.ctx.backend.state_set("wizard_done", True)
        self.on_finish()
