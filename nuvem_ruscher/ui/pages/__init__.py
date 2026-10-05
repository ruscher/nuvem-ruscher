"""Páginas do painel. A ordem e os ícones ficam em ``ui/shell.py`` (NAVIGATION)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nuvem_ruscher.ui.page import Page
    from nuvem_ruscher.ui.shell import AppContext


def build_pages(ctx: AppContext) -> dict[str, Page]:
    from nuvem_ruscher.ui.pages.backups import BackupsPage
    from nuvem_ruscher.ui.pages.home import HomePage
    from nuvem_ruscher.ui.pages.logs import LogsPage
    from nuvem_ruscher.ui.pages.network import NetworkPage
    from nuvem_ruscher.ui.pages.phones import PhonesPage
    from nuvem_ruscher.ui.pages.sharing import SharingPage
    from nuvem_ruscher.ui.pages.storage import StoragePage
    from nuvem_ruscher.ui.pages.system import SystemPage
    from nuvem_ruscher.ui.pages.updates import UpdatesPage
    from nuvem_ruscher.ui.pages.users import UsersPage

    return {
        "home": HomePage(ctx),
        "phones": PhonesPage(ctx),
        "users": UsersPage(ctx),
        "sharing": SharingPage(ctx),
        "storage": StoragePage(ctx),
        "backups": BackupsPage(ctx),
        "network": NetworkPage(ctx),
        "updates": UpdatesPage(ctx),
        "logs": LogsPage(ctx),
        "system": SystemPage(ctx),
    }
