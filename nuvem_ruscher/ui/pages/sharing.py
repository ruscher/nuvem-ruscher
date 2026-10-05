"""Compartilhamento: pastas compartilhadas (álbuns) e bibliotecas inteiras (partners) — doc 11."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.core import numbers
from nuvem_ruscher.core.immich_api import Album, AlbumMember, Person
from nuvem_ruscher.i18n import N_, _, ngettext
from nuvem_ruscher.ui.accounts_ui import SignInPanel, api_message
from nuvem_ruscher.ui.common import StatusBlock, confirm, label, open_uri, toast
from nuvem_ruscher.ui.flow import FlowDialog, FlowPage
from nuvem_ruscher.ui.page import Page, group, icon_tile

if TYPE_CHECKING:
    from nuvem_ruscher.ui.shell import AppContext

# Papéis do Immich (AlbumUserRole) com o que cada um faz de verdade (código da v3.2.4).
ROLES = (
    ("editor", N_("Can add")),
    ("viewer", N_("Can view")),
)
ROLE_TEXT = {"owner": N_("Owner"), "editor": N_("Can add"), "viewer": N_("Can view")}
ROLE_HELP = N_(
    "Can view: see and download. Can add: also add their own photos, rename the folder and invite other "
    "people. Only the owner can delete the folder or remove other people’s photos."
)


def members_text(album: Album) -> str:
    names = [f"{m.name} ({_(ROLE_TEXT.get(m.role, m.role)).lower()})" for m in album.members]
    return ", ".join(names) if names else _("Only you")


class SharingPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            _("Sharing"),
            _("Folders that several people see and fill together, each with their own account."),
            "folder-publicshare-symbolic",
            "orange",
        )
        self.ctx = ctx
        self.backend = ctx.backend
        self.people: list[Person] = []
        self.new_button = Gtk.Button(label=_("New shared folder"), valign=Gtk.Align.CENTER)
        self.new_button.add_css_class("pill")
        self.new_button.add_css_class("suggested-action")
        self.new_button.connect("clicked", lambda *_: self._new())
        self.add_hero_action(self.new_button)

        self.sign_in = SignInPanel(ctx, self.session_changed, admin_hint=False)
        self.add(self.sign_in)

        self.help = group()
        help_row = Adw.ActionRow(title=_("What each person can do"), subtitle=_(ROLE_HELP))
        help_row.set_subtitle_lines(5)
        help_row.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        self.help.add(help_row)
        self.add(self.help)

        self.by_me = group(_("Shared folders"), _("Folders you created and share with other people."))
        self.with_me = group(_("Shared with you"), _("Folders other people share with you."))
        self.partners = group(
            _("Whole libraries"),
            _(
                "A partner sees all of your photos (except archived and locked ones) in their own timeline, "
                "including locations. It works in one direction."
            ),
        )
        for widget in (self.by_me, self.with_me, self.partners):
            self.add(widget)
        self.empty = StatusBlock(
            "folder-publicshare-symbolic",
            _("Nothing shared yet"),
            _("Create a shared folder for the family, a trip or an event. Everyone adds photos from their phone."),
        )
        self.add(self.empty)
        self.error = StatusBlock("network-offline-symbolic", _("Could not load the shared folders"))
        self.add(self.error)
        self._rows: list[tuple[Adw.PreferencesGroup, Gtk.Widget]] = []
        self.session_changed()

    def session_changed(self) -> None:
        signed = self.backend.session is not None
        self.sign_in.set_visible(not signed)
        for widget in (self.help, self.by_me, self.with_me, self.partners, self.new_button):
            widget.set_visible(signed)
        self.empty.set_visible(False)
        self.error.set_visible(False)
        if signed:
            self.refresh()

    def on_shown(self) -> None:
        if self.backend.session is not None:
            self.refresh()

    def refresh(self) -> None:
        def collect() -> tuple[tuple[list[Album], list[Album]], tuple[list[Person], list[Person]], list[Person]]:
            return self.backend.shared_albums(), self.backend.partners(), self.backend.people()

        run_async(collect, on_done=self._show, on_error=self._failed)

    def _failed(self, exc: BaseException) -> None:
        for widget in (self.by_me, self.with_me, self.partners, self.help):
            widget.set_visible(False)
        self.error.set_description(api_message(exc))
        self.error.set_visible(True)

    def _clear(self) -> None:
        for parent, row in self._rows:
            parent.remove(row)
        self._rows = []

    def _add_row(self, parent: Adw.PreferencesGroup, row: Gtk.Widget) -> None:
        parent.add(row)
        self._rows.append((parent, row))

    def _show(self, data: tuple) -> None:
        (mine, with_me), (shared_by, shared_with), people = data
        self.people = people
        self._clear()
        for album in mine:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(album.name),
                subtitle=GLib.markup_escape_text(
                    ngettext("{n} item", "{n} items", album.asset_count).format(n=numbers.integer(album.asset_count))
                    + " · "
                    + members_text(album)
                ),
                activatable=True,
            )
            row.set_subtitle_lines(3)
            row.add_prefix(icon_tile("folder-publicshare-symbolic", "orange", 16, "small"))
            count = len(album.members)
            badge = label(
                ngettext("{n} person", "{n} people", count).format(n=count), css=("caption", "dim-label"), wrap=False
            )
            row.add_suffix(badge)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", lambda *_r, a=album: self._manage(a))
            self._add_row(self.by_me, row)
        if not mine:
            self._add_row(self.by_me, self._note(_("You have not shared any folder yet.")))
        for album in with_me:
            mine_role = next(
                (m.role for m in album.members if self.backend.session and m.user_id == self.backend.session.user_id),
                "viewer",
            )
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(album.name),
                subtitle=GLib.markup_escape_text(
                    _("From {owner} · you {role}").format(
                        owner=album.owner.name if album.owner else "?",
                        role=_(ROLE_TEXT.get(mine_role, mine_role)).lower(),
                    )
                ),
            )
            row.add_prefix(icon_tile("folder-publicshare-symbolic", "blue", 16, "small"))
            row.add_suffix(self._open_button(album))
            self._add_row(self.with_me, row)
        if not with_me:
            self._add_row(self.with_me, self._note(_("Nobody shares a folder with you yet.")))

        for person in shared_by:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(_("{name} sees your whole library").format(name=person.name)),
                subtitle=GLib.markup_escape_text(person.email),
            )
            row.add_prefix(Adw.Avatar(size=32, text=person.name, show_initials=True))
            stop = Gtk.Button(label=_("Stop sharing"), valign=Gtk.Align.CENTER)
            stop.connect("clicked", lambda *_b, p=person: self._remove_partner(p))
            row.add_suffix(stop)
            self._add_row(self.partners, row)
        for person in shared_with:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(_("You see {name}’s whole library").format(name=person.name)),
                subtitle=GLib.markup_escape_text(person.email),
            )
            row.add_prefix(Adw.Avatar(size=32, text=person.name, show_initials=True))
            self._add_row(self.partners, row)
        add = Adw.ActionRow(title=_("Share your whole library with someone…"), activatable=True)
        add.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        add.connect("activated", lambda *_: self._add_partner())
        self._add_row(self.partners, add)
        self.empty.set_visible(not mine and not with_me and not shared_by and not shared_with)

    @staticmethod
    def _note(text: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(text))
        row.add_css_class("dim-label")
        return row

    def _open_button(self, album: Album) -> Gtk.Button:
        button = Gtk.Button(icon_name="adw-external-link-symbolic", valign=Gtk.Align.CENTER)
        button.add_css_class("flat")
        button.set_tooltip_text(_("Open in Immich"))
        button.update_property([Gtk.AccessibleProperty.LABEL], [_("Open in Immich")])
        button.connect("clicked", lambda b: open_uri(b, f"{self.backend.local_url}/albums/{album.id}"))
        return button

    # --- ações -------------------------------------------------------------------------------
    def _new(self) -> None:
        def created(album: Album) -> None:
            toast(self, _("“{name}” is shared").format(name=album.name))
            self.refresh()

        NewSharedFolderDialog(self.ctx, self.people, created).present(self.get_root())

    def _manage(self, album: Album) -> None:
        SharedFolderDialog(self.ctx, album, self.people, self.refresh).present(self.get_root())

    def _add_partner(self) -> None:
        session = self.backend.session
        candidates = [p for p in self.people if session is None or p.id != session.user_id]
        if not candidates:
            toast(self, _("Create another account first."))
            return

        def chosen(person: Person) -> None:
            run_async(
                self.backend.add_partner,
                person.id,
                on_done=lambda _r: (
                    toast(self, _("{name} now sees your library").format(name=person.name)),
                    self.refresh(),
                ),
                on_error=lambda e: toast(self, api_message(e), 6),
            )

        PersonPicker(
            _("Share your whole library"),
            _("This person will see all of your photos and videos (except archived and locked ones)."),
            candidates,
            chosen,
        ).present(self.get_root())

    def _remove_partner(self, person: Person) -> None:
        def run() -> None:
            run_async(
                self.backend.remove_partner,
                person.id,
                on_done=lambda _r: self.refresh(),
                on_error=lambda e: toast(self, api_message(e), 6),
            )

        confirm(
            self,
            _("Stop sharing your library with {name}?").format(name=person.name),
            _("Your photos stay where they are; {name} just stops seeing them.").format(name=person.name),
            _("Stop sharing"),
            run,
            destructive=True,
        )


class PersonPicker(Adw.AlertDialog):
    def __init__(self, heading: str, body: str, people: list[Person], on_chosen: Callable[[Person], None]) -> None:
        super().__init__(heading=heading, body=body)
        names = Gtk.StringList()
        for person in people:
            names.append(f"{person.name} — {person.email}")
        self.dropdown = Gtk.DropDown(model=names)
        self.dropdown.update_property([Gtk.AccessibleProperty.LABEL], [_("Person")])
        self.set_extra_child(self.dropdown)
        self.add_response("cancel", _("Cancel"))
        self.add_response("ok", _("Share"))
        self.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        self.set_default_response("ok")
        self.set_close_response("cancel")
        self.connect("response", lambda _d, r: r == "ok" and on_chosen(people[self.dropdown.get_selected()]))


class MemberRows:
    """Lista "pessoa + papel" usada ao criar e ao gerenciar uma pasta."""

    def __init__(self, people: list[Person], members: dict[str, str]) -> None:
        self.group = Adw.PreferencesGroup(title=_("People"))
        self.checks: dict[str, Gtk.CheckButton] = {}
        self.roles: dict[str, Adw.ComboRow] = {}
        for person in people:
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER, active=person.id in members)
            combo = Adw.ComboRow(
                title=GLib.markup_escape_text(person.name), subtitle=GLib.markup_escape_text(person.email)
            )
            combo.set_model(Gtk.StringList.new([_(text) for _key, text in ROLES]))
            combo.set_selected(0 if members.get(person.id, "viewer") == "editor" else 1)
            combo.add_prefix(check)
            combo.set_sensitive(True)
            self.checks[person.id] = check
            self.roles[person.id] = combo
            self.group.add(combo)

    def chosen(self) -> list[tuple[str, str]]:
        return [
            (pid, ROLES[self.roles[pid].get_selected()][0]) for pid, check in self.checks.items() if check.get_active()
        ]


class NewSharedFolderDialog(FlowDialog):
    def __init__(self, ctx: AppContext, people: list[Person], on_created: Callable[[Album], None]) -> None:
        super().__init__(_("New shared folder"), 560, 640)
        self.ctx = ctx
        self.on_created = on_created
        session = ctx.backend.session
        others = [p for p in people if session is None or p.id != session.user_id]
        page = FlowPage(_("New shared folder"), "new")
        page.intro(
            _("A folder for several people"),
            _("You are the owner. Choose who can add photos and who can only view. Photos are added in Immich."),
            "folder-publicshare-symbolic",
        )
        name_group = Adw.PreferencesGroup()
        self.name = Adw.EntryRow(title=_("Name (for example: Family, Trip to the beach)"))
        self.name.connect("changed", lambda *_: self._validate())
        name_group.add(self.name)
        page.add(name_group)
        self.members = MemberRows(others, {})
        for check in self.members.checks.values():
            check.connect("toggled", lambda *_: self._validate())
        page.add(self.members.group)
        if not others:
            page.add(label(_("There are no other accounts yet. Add them in Accounts."), css=("dim-label",)))
        page.add(label(_(ROLE_HELP), css=("dim-label", "caption")))
        self.error = label("", css=("error",))
        self.error.set_visible(False)
        page.add(self.error)
        page.button(_("Cancel"), self.close, start=True)
        self.create = page.button(_("Create and share"), self._create, "suggested-action")
        self._validate()
        self.push(page)

    def _validate(self) -> None:
        self.create.set_sensitive(bool(self.name.get_text().strip()) and bool(self.members.chosen()))

    def _create(self) -> None:
        self.create.set_sensitive(False)

        def done(album: Album) -> None:
            self.on_created(album)
            self.close()

        def failed(exc: BaseException) -> None:
            self.create.set_sensitive(True)
            self.error.set_text(api_message(exc))
            self.error.set_visible(True)

        run_async(
            self.ctx.backend.create_shared_album,
            self.name.get_text().strip(),
            self.members.chosen(),
            on_done=done,
            on_error=failed,
        )


class SharedFolderDialog(Adw.Dialog):
    """Gerenciar participantes de uma pasta compartilhada (papéis e remoções, um a um)."""

    def __init__(self, ctx: AppContext, album: Album, people: list[Person], on_changed: Callable[[], None]) -> None:
        super().__init__(title=album.name, content_width=560, content_height=600)
        self.ctx = ctx
        self.album = album
        self.on_changed = on_changed
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        toolbar.set_content(page)
        self.set_child(toolbar)

        about = Adw.PreferencesGroup(
            description=ngettext("{n} item", "{n} items", album.asset_count).format(
                n=numbers.integer(album.asset_count)
            )
        )
        owner = Adw.ActionRow(
            title=GLib.markup_escape_text(album.owner.name if album.owner else "?"), subtitle=_("Owner")
        )
        owner.add_prefix(Adw.Avatar(size=32, text=album.owner.name if album.owner else "?", show_initials=True))
        about.add(owner)
        open_row = Adw.ActionRow(title=_("Open in Immich to add or remove photos"), activatable=True)
        open_row.add_suffix(Gtk.Image.new_from_icon_name("adw-external-link-symbolic"))
        open_row.connect("activated", lambda r: open_uri(r, f"{ctx.backend.local_url}/albums/{album.id}"))
        about.add(open_row)
        page.add(about)

        members = Adw.PreferencesGroup(title=_("Participants"), description=_(ROLE_HELP))
        self.members_group = members
        for member in album.members:
            members.add(self._member_row(member))
        page.add(members)

        present = {m.user_id for m in album.members} | {album.owner.user_id if album.owner else ""}
        self.candidates = [p for p in people if p.id not in present]
        if self.candidates:
            add_group = Adw.PreferencesGroup()
            add = Adw.ActionRow(title=_("Add a person…"), activatable=True)
            add.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
            add.connect("activated", lambda *_: self._add())
            add_group.add(add)
            page.add(add_group)

    def _member_row(self, member: AlbumMember) -> Adw.ComboRow:
        row = Adw.ComboRow(title=GLib.markup_escape_text(member.name), subtitle=GLib.markup_escape_text(member.email))
        row.add_prefix(Adw.Avatar(size=32, text=member.name, show_initials=True))
        row.set_model(Gtk.StringList.new([_(text) for _key, text in ROLES]))
        row.set_selected(0 if member.role == "editor" else 1)
        row.connect("notify::selected", lambda r, _p, m=member: self._set_role(m, ROLES[r.get_selected()][0]))
        remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
        remove.add_css_class("flat")
        remove.set_tooltip_text(_("Remove from this folder"))
        remove.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Remove {name} from this folder").format(name=member.name)]
        )
        remove.connect("clicked", lambda *_b, m=member: self._remove(m))
        row.add_suffix(remove)
        return row

    def _set_role(self, member: AlbumMember, role: str) -> None:
        if role == member.role:
            return
        run_async(
            self.ctx.backend.set_album_role,
            self.album.id,
            member.user_id,
            role,
            on_done=lambda _r: (toast(self, _("Saved")), self.on_changed()),
            on_error=lambda e: toast(self, api_message(e), 6),
        )

    def _remove(self, member: AlbumMember) -> None:
        def run() -> None:
            run_async(
                self.ctx.backend.remove_album_member,
                self.album.id,
                member.user_id,
                on_done=lambda _r: (self.on_changed(), self.close()),
                on_error=lambda e: toast(self, api_message(e), 6),
            )

        confirm(
            self,
            _("Remove {name} from “{folder}”?").format(name=member.name, folder=self.album.name),
            _("{name} stops seeing this folder.").format(name=member.name),
            _("Remove"),
            run,
            destructive=True,
        )

    def _add(self) -> None:
        def chosen(person: Person) -> None:
            run_async(
                self.ctx.backend.add_album_members,
                self.album.id,
                [(person.id, "viewer")],
                on_done=lambda _r: (self.on_changed(), self.close()),
                on_error=lambda e: toast(self, api_message(e), 6),
            )

        PersonPicker(
            _("Add a person"),
            _("They start with “Can view”. You can change it afterwards."),
            self.candidates,
            chosen,
        ).present(self)
