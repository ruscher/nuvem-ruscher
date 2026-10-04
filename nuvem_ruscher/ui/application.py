"""Adw.Application: ações globais, atalhos, CSS e ícones."""

from __future__ import annotations

from gi.repository import Adw, Gdk, Gio, Gtk

from nuvem_ruscher import APP_ID, APP_NAME, VERSION
from nuvem_ruscher.backend.base import Backend
from nuvem_ruscher.constants import IMMICH_DOCS_URL, PROJECT_URL
from nuvem_ruscher.i18n import _
from nuvem_ruscher.paths import ICONS_DIR, ILLUSTRATIONS_DIR, STYLE_CSS


class NuvemApplication(Adw.Application):
    def __init__(self, backend: Backend) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.backend = backend
        self.window = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        display = Gdk.Display.get_default()
        if display is not None:
            theme = Gtk.IconTheme.get_for_display(display)
            theme.add_search_path(str(ICONS_DIR))
            theme.add_search_path(str(ILLUSTRATIONS_DIR))
            provider = Gtk.CssProvider()
            provider.load_from_path(str(STYLE_CSS))
            Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._action("quit", lambda *_: self.quit(), ["<primary>q"])
        self._action("about", self._about)
        self._action("shortcuts", self._shortcuts, ["<primary>question"])
        self._action("open-immich", self._open_immich)
        self.set_accels_for_action("window.close", ["<primary>w"])

    def _action(self, name: str, callback, accels: list[str] | None = None) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    def menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append(_("Abrir o Immich no navegador"), "app.open-immich")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append(_("Atalhos de teclado"), "app.shortcuts")
        section.append(_("Sobre o {name}").format(name=APP_NAME), "app.about")
        menu.append_section(None, section)
        return menu

    def do_activate(self) -> None:
        if self.window is None:
            from nuvem_ruscher.ui.window import MainWindow

            self.window = MainWindow(self, self.backend, self.menu())
        self.window.present()

    def _open_immich(self, *_args: object) -> None:
        Gtk.UriLauncher.new(self.backend.local_url).launch(self.window, None, None)

    def _about(self, *_args: object) -> None:
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            developer_name="ruscher",
            version=VERSION + (" (" + _("simulação") + ")" if self.backend.simulated else ""),
            website=PROJECT_URL,
            issue_url=PROJECT_URL + "/issues",
            license_type=Gtk.License.GPL_3_0,
            comments=_(
                "Instala, configura e cuida do Immich — sua alternativa livre ao Google Fotos — "
                "neste computador, com as fotos guardadas no disco que você escolher."
            ),
        )
        about.add_link(_("Documentação do Immich"), IMMICH_DOCS_URL)
        about.add_legal_section(
            "Immich",
            "© Immich contributors",
            Gtk.License.AGPL_3_0,
            None,
        )
        about.present(self.window)

    def _shortcuts(self, *_args: object) -> None:
        dialog = Adw.ShortcutsDialog()
        section = Adw.ShortcutsSection(title=_("Geral"))
        for accel, title in (
            ("<primary>q", _("Sair")),
            ("<primary>w", _("Fechar a janela")),
            ("<primary>question", _("Atalhos de teclado")),
            ("<alt>Left", _("Voltar no assistente")),
        ):
            section.add(Adw.ShortcutsItem(title=title, accelerator=accel))
        dialog.add(section)
        panel = Adw.ShortcutsSection(title=_("Painel"))
        for accel, title in (
            ("<primary>1", _("Início")),
            ("<primary>2", _("Celular")),
            ("<primary>3", _("Registros")),
            ("<primary>4", _("Backups")),
            ("<primary>5", _("Atualizar")),
            ("<primary>6", _("Mais")),
            ("F5", _("Atualizar informações")),
            ("<primary>f", _("Buscar nos registros")),
        ):
            panel.add(Adw.ShortcutsItem(title=title, accelerator=accel))
        dialog.add(panel)
        dialog.present(self.window)
