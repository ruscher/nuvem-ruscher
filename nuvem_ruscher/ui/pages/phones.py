"""Celulares: conectar o app do Immich em casa ou fora de casa."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.page import Page
from nuvem_ruscher.ui.widgets.phone import PhoneView

if TYPE_CHECKING:
    from nuvem_ruscher.ui.shell import AppContext


class PhonesPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            _("Phones"),
            _("Android or iPhone: install Immich, type the address and turn on the backup."),
            "phone-symbolic",
            "green",
        )
        self.view = PhoneView(ctx.backend, show_title=False, open_page=ctx.show_page)
        self.add(self.view)

    def on_shown(self) -> None:
        self.view.refresh()

    def show_away(self) -> None:
        if self.view.where.get_visible():
            self.view.where.set_active_name("away")
