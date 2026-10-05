"""Adw.Application: ações globais, atalhos, CSS e ícones."""

from __future__ import annotations

import sys

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from nuvem_ruscher import APP_ID, APP_NAME, VERSION
from nuvem_ruscher.backend.base import Backend
from nuvem_ruscher.constants import IMMICH_DOCS_URL, PROJECT_URL
from nuvem_ruscher.i18n import _
from nuvem_ruscher.paths import ICONS_DIR, ILLUSTRATIONS_DIR, STYLE_CSS

COLOR_SCHEMES = {
    "system": Adw.ColorScheme.DEFAULT,
    "light": Adw.ColorScheme.FORCE_LIGHT,
    "dark": Adw.ColorScheme.FORCE_DARK,
}


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

        # Aparência: Sistema / Claro / Escuro, guardada nas preferências do usuário.
        saved = str(self.backend.state_get("color_scheme", "system") or "system")
        if saved not in COLOR_SCHEMES:
            saved = "system"
        scheme = Gio.SimpleAction.new_stateful("color-scheme", GLib.VariantType.new("s"), GLib.Variant("s", saved))
        scheme.connect("change-state", self._color_scheme)
        self.add_action(scheme)
        Adw.StyleManager.get_default().set_color_scheme(COLOR_SCHEMES[saved])

    def _action(self, name: str, callback, accels: list[str] | None = None) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    def _color_scheme(self, action: Gio.SimpleAction, value: GLib.Variant) -> None:
        name = value.get_string()
        if name not in COLOR_SCHEMES:
            return
        action.set_state(value)
        Adw.StyleManager.get_default().set_color_scheme(COLOR_SCHEMES[name])
        self.backend.state_set("color_scheme", name)

    def menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append(_("Open Immich in the browser"), "app.open-immich")
        menu.append_section(None, section)
        appearance = Gio.Menu()
        for name, title in (("system", _("Follow system style")), ("light", _("Light")), ("dark", _("Dark"))):
            appearance.append(title, f"app.color-scheme::{name}")
        menu.append_submenu(_("Appearance"), appearance)
        section = Gio.Menu()
        section.append(_("Keyboard shortcuts"), "app.shortcuts")
        section.append(_("About {name}").format(name=APP_NAME), "app.about")
        menu.append_section(None, section)
        return menu

    def do_shutdown(self) -> None:
        # A sessão de administrador vive só na memória: ao sair, o token é encerrado no Immich.
        try:
            self.backend.sign_out()
        except Exception as exc:  # sair nunca pode falhar por causa do logout
            print(f"nuvem-ruscher: could not sign out of Immich: {exc}", file=sys.stderr)
        Adw.Application.do_shutdown(self)

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
            version=_("{version} (simulation)").format(version=VERSION) if self.backend.simulated else VERSION,
            website=PROJECT_URL,
            issue_url=PROJECT_URL + "/issues",
            license_type=Gtk.License.GPL_3_0,
            comments=_(
                "Installs, configures and looks after Immich — your free alternative to Google Photos — "
                "on this computer, with the photos stored on the disk you choose."
            ),
        )
        about.add_link(_("Immich documentation"), IMMICH_DOCS_URL)
        about.add_legal_section(
            "Immich",
            "© Immich contributors",
            Gtk.License.AGPL_3_0,
            None,
        )
        about.present(self.window)

    def _shortcuts(self, *_args: object) -> None:
        dialog = Adw.ShortcutsDialog()
        section = Adw.ShortcutsSection(title=_("General"))
        for accel, title in (
            ("<primary>q", _("Quit")),
            ("<primary>w", _("Close the window")),
            ("<primary>question", _("Keyboard shortcuts")),
            ("<alt>Left", _("Go back in the assistant")),
        ):
            section.add(Adw.ShortcutsItem(title=title, accelerator=accel))
        dialog.add(section)
        panel = Adw.ShortcutsSection(title=_("Pages"))
        shell = getattr(self.window, "shell", None)
        if shell is not None:
            for accel, title in shell.shortcut_titles():
                panel.add(Adw.ShortcutsItem(title=title, accelerator=accel))
        for accel, title in (("F5", _("Refresh information")), ("<primary>f", _("Search the logs"))):
            panel.add(Adw.ShortcutsItem(title=title, accelerator=accel))
        dialog.add(panel)
        dialog.present(self.window)
