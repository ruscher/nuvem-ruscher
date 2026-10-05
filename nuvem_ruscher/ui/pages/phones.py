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
            _("Two steps with the phone camera. Each person signs in with their own account."),
            "phone-symbolic",
            "green",
        )
        self.view = PhoneView(ctx.backend, show_title=False)
        self.add(self.view)

    def on_shown(self) -> None:
        self.view.refresh()

    def show_away(self) -> None:
        if self.view.where.get_visible():
            self.view.where.set_active_name("away")
