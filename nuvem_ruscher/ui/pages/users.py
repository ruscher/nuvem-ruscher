"""Contas: cada pessoa da casa com login, biblioteca, celular e quota próprios (doc 10)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.core import numbers
from nuvem_ruscher.core.immich_api import ImmichUser
from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.accounts_ui import (
    DELETE_DELAY_DAYS,
    AccountDialog,
    AddAccountDialog,
    SignInPanel,
    account_status,
    api_message,
    quota_text,
    status_widget,
    usage_bar,
)
from nuvem_ruscher.ui.common import StatusBlock, toast
from nuvem_ruscher.ui.page import Page, group

if TYPE_CHECKING:
    from nuvem_ruscher.ui.shell import AppContext


class UsersPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            _("Accounts"),
            _("Each person has their own login, library, phone backup and albums."),
            "system-users-symbolic",
            "violet",
        )
        self.ctx = ctx
        self.backend = ctx.backend
        self.users: list[ImmichUser] = []

        self.add_button = Gtk.Button(label=_("Add account"), valign=Gtk.Align.CENTER)
        self.add_button.add_css_class("pill")
        self.add_button.add_css_class("suggested-action")
        self.add_button.connect("clicked", lambda *_: self._add())
        self.add_hero_action(self.add_button)

        self.sign_in = SignInPanel(ctx, self.session_changed)
        self.add(self.sign_in)

        self.not_admin = StatusBlock(
            "changes-prevent-symbolic",
            _("This account is not an administrator"),
            _("Ask an administrator to sign in here to add or change accounts. Sharing still works."),
        )
        self.add(self.not_admin)

        self.session_group = group()
        self.session_row = Adw.ActionRow()
        self.session_row.add_prefix(Gtk.Image.new_from_icon_name("avatar-default-symbolic"))
        sign_out = Gtk.Button(label=_("Sign out"), valign=Gtk.Align.CENTER)
        sign_out.add_css_class("flat")
        sign_out.connect("clicked", lambda *_: self._sign_out())
        self.session_row.add_suffix(sign_out)
        self.session_group.add(self.session_row)
        self.add(self.session_group)

        self.list = group(_("People"))
        self.add(self.list)
        self.disabled = group(
            _("Disabled accounts"),
            _("They cannot sign in. Immich deletes them for good {days} days after they were disabled.").format(
                days=DELETE_DELAY_DAYS
            ),
        )
        self.add(self.disabled)
        self.error = StatusBlock("network-offline-symbolic", _("Could not load the accounts"))
        self.add(self.error)
        self._rows: list[tuple[Adw.PreferencesGroup, Gtk.Widget]] = []
        self.session_changed()

    # --- estado ---------------------------------------------------------------------------
    def session_changed(self) -> None:
        session = self.backend.session
        signed = session is not None
        admin = signed and session.is_admin
        self.sign_in.set_visible(not signed)
        self.not_admin.set_visible(signed and not admin)
        self.session_group.set_visible(signed)
        self.add_button.set_visible(admin)
        self.list.set_visible(admin)
        self.disabled.set_visible(False)
        self.error.set_visible(False)
        if signed:
            self.session_row.set_title(GLib.markup_escape_text(session.name))
            self.session_row.set_subtitle(
                GLib.markup_escape_text(
                    _("Signed in as {email}").format(email=session.email)
                    + (" · " + _("Administrator") if session.is_admin else "")
                )
            )
        if admin:
            self.refresh()

    def on_shown(self) -> None:
        if self.backend.session is not None and self.backend.session.is_admin:
            self.refresh()

    def refresh(self) -> None:
        run_async(self.backend.accounts, on_done=self._show, on_error=self._failed)

    def _failed(self, exc: BaseException) -> None:
        self.list.set_visible(False)
        self.error.set_description(api_message(exc))
        self.error.set_visible(True)

    def _show(self, users: list[ImmichUser]) -> None:
        self.users = users
        for parent, row in self._rows:
            parent.remove(row)
        self._rows = []
        active = [u for u in users if not u.disabled]
        disabled = [u for u in users if u.disabled]
        active.sort(key=lambda u: (not u.is_admin, u.name.casefold()))
        self.list.set_title(_("People ({n})").format(n=len(active)))
        for user in active:
            self._row(self.list, user)
        for user in disabled:
            self._row(self.disabled, user)
        self.list.set_visible(True)
        self.disabled.set_visible(bool(disabled))
        home = self.ctx.extras.get("home")
        if home is not None and hasattr(home, "accounts_changed"):
            home.accounts_changed(len(active))

    def _row(self, parent: Adw.PreferencesGroup, user: ImmichUser) -> None:
        role = _("Administrator") if user.is_admin else _("User")
        media = _("{photos} photos · {videos} videos").format(
            photos=numbers.integer(user.photos), videos=numbers.integer(user.videos)
        )
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(user.name),
            subtitle=GLib.markup_escape_text(f"{role} · {quota_text(user)} · {media}"),
            activatable=True,
        )
        row.set_subtitle_lines(2)
        row.add_prefix(Adw.Avatar(size=36, text=user.name, show_initials=True))
        if user.quota:
            row.add_suffix(usage_bar((user.usage or 0) / user.quota, quota_text(user)))
        status, text = account_status(user)
        row.add_suffix(status_widget(status, text))
        row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        row.connect("activated", lambda *_r, u=user: self._open(u))
        parent.add(row)
        self._rows.append((parent, row))

    # --- ações -------------------------------------------------------------------------------
    def _open(self, user: ImmichUser) -> None:
        AccountDialog(self.ctx, user, on_changed=self.refresh).present(self.get_root())

    def _add(self) -> None:
        def created(user: ImmichUser) -> None:
            toast(self, _("Account created for {name}").format(name=user.name))
            self.refresh()

        AddAccountDialog(self.ctx, created).present(self.get_root())

    def _sign_out(self) -> None:
        def done(_r: object) -> None:
            for page in ("users", "sharing", "home"):
                target = self.ctx.extras.get(page)
                if target is not None and hasattr(target, "session_changed"):
                    target.session_changed()

        run_async(self.backend.sign_out, on_done=done, on_error=lambda _e: done(None))
