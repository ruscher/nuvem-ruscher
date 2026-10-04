"""Diálogos reutilizáveis."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.backend.base import Backend
from nuvem_ruscher.core.immich_api import ApiError
from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.common import label


class ConnectStatsDialog(Adw.Dialog):
    """Entra uma vez para criar a chave só de estatísticas (a senha não é guardada)."""

    def __init__(self, backend: Backend, on_done: Callable[[], None] | None = None) -> None:
        super().__init__(title=_("Mostrar estatísticas"), content_width=420)
        self.backend = backend
        self.on_done = on_done
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for margin in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{margin}")(18)
        box.append(
            label(
                _(
                    "Entre com a conta de administrador do Immich. Vamos criar uma chave que só lê a "
                    "contagem de fotos e o uso do disco. Sua senha não fica guardada."
                ),
                css=("dim-label",),
            )
        )
        group = Adw.PreferencesGroup()
        self.email = Adw.EntryRow(title=_("E-mail"), input_purpose=Gtk.InputPurpose.EMAIL)
        self.password = Adw.PasswordEntryRow(title=_("Senha"))
        self.password.connect("entry-activated", lambda *_: self._go())
        group.add(self.email)
        group.add(self.password)
        box.append(group)
        self.error = label("", css=("error",))
        self.error.set_visible(False)
        box.append(self.error)
        self.button = Gtk.Button(label=_("Conectar"), halign=Gtk.Align.CENTER)
        self.button.add_css_class("pill")
        self.button.add_css_class("suggested-action")
        self.button.connect("clicked", lambda *_: self._go())
        box.append(self.button)
        toolbar.set_content(box)
        self.set_child(toolbar)
        self.set_default_widget(self.button)

    def _go(self) -> None:
        self.button.set_sensitive(False)
        self.error.set_visible(False)

        def done(_r: object) -> None:
            if self.on_done:
                self.on_done()
            self.close()

        def failed(exc: BaseException) -> None:
            self.button.set_sensitive(True)
            if isinstance(exc, ApiError) and exc.status in (400, 401):
                self.error.set_text(_("E-mail ou senha incorretos."))
            else:
                self.error.set_text(_("O servidor não respondeu. Ele está ligado?"))
            self.error.set_visible(True)

        run_async(
            self.backend.connect_stats,
            self.email.get_text().strip(),
            self.password.get_text(),
            on_done=done,
            on_error=failed,
        )
