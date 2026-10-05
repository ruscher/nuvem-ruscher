"""Contas do Immich na interface: entrar como administrador, criar e editar contas (doc 10)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.core import numbers
from nuvem_ruscher.core.immich_api import ApiError, ImmichUser, generate_password
from nuvem_ruscher.core.storage import human_size
from nuvem_ruscher.core.validation import EMAIL_RE
from nuvem_ruscher.i18n import N_, _
from nuvem_ruscher.ui.common import confirm, copy_text, label, status_icon, toast
from nuvem_ruscher.ui.flow import FlowDialog, FlowPage
from nuvem_ruscher.ui.widgets.qr_code import QrCode, qr_frame

if TYPE_CHECKING:
    from nuvem_ruscher.ui.shell import AppContext

GIB = 1024**3
# Atalhos de quota (a quota em si é a do Immich, em bytes).
QUOTAS: tuple[tuple[str, int | None], ...] = (
    (N_("Unlimited"), None),
    ("10 GB", 10 * GIB),
    ("25 GB", 25 * GIB),
    ("50 GB", 50 * GIB),
    ("100 GB", 100 * GIB),
    ("250 GB", 250 * GIB),
    ("500 GB", 500 * GIB),
    ("1 TB", 1024 * GIB),
    (N_("Custom"), -1),
)
STORAGE_LABEL_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
DELETE_DELAY_DAYS = 7  # padrão do Immich (user.deleteDelay)


def api_message(exc: BaseException) -> str:
    """Erro da API em linguagem humana (o detalhe técnico vem entre parênteses)."""
    if isinstance(exc, PermissionError):
        return _("Sign in again as an administrator.")
    if isinstance(exc, ApiError):
        text = exc.message.lower()
        if exc.status == 0:
            return _("Immich did not answer. Make sure the server is on and try again.")
        if exc.status in (401, 403) and "own" in text:
            return _("You cannot do this to your own account.")
        if exc.status == 401:
            return _("Incorrect email or password.")
        if "exists" in text and "label" in text:
            return _("Another account already uses this storage label.")
        if "exists" in text:
            return _("There is already an account with this email.")
        if "email" in text:
            return _("Check the email address.")
        if "admin status" in text:
            return _("Your own administrator status can only be changed by another administrator.")
        return _("Immich refused the change ({detail}).").format(detail=exc.message)
    return _("Something unexpected happened ({detail}).").format(detail=exc)


def quota_text(user: ImmichUser) -> str:
    used = human_size(user.usage or 0)
    if user.quota is None:
        return _("{used} used · no limit").format(used=used)
    return _("{used} of {quota}").format(used=used, quota=human_size(user.quota, binary=True))


def quota_index(quota: int | None) -> int:
    for index, (_title, value) in enumerate(QUOTAS):
        if value == quota:
            return index
    return len(QUOTAS) - 1


class QuotaRow(Adw.ComboRow):
    """Quota com atalhos; "Personalizado" mostra um campo em GB."""

    def __init__(self, quota: int | None = None) -> None:
        super().__init__(title=_("Storage quota"))
        names = Gtk.StringList()
        for title, _value in QUOTAS:
            names.append(_(title) if title in ("Unlimited", "Custom") else title)
        self.set_model(names)
        self.custom = Adw.SpinRow.new_with_range(1, 100_000, 1)
        self.custom.set_title(_("Custom quota (GB)"))
        self.custom.set_visible(False)
        index = quota_index(quota)
        self.set_selected(index)
        if QUOTAS[index][1] == -1 and quota:
            self.custom.set_value(round(quota / GIB))
            self.custom.set_visible(True)
        self.connect("notify::selected", lambda *_: self.custom.set_visible(QUOTAS[self.get_selected()][1] == -1))

    @property
    def quota(self) -> int | None:
        value = QUOTAS[self.get_selected()][1]
        if value == -1:
            return int(self.custom.get_value()) * GIB
        return value


class SignInPanel(Gtk.Box):
    """Entrar no Immich. A senha não é guardada; a sessão dura até fechar o app."""

    def __init__(self, ctx: AppContext, on_signed_in: Callable[[], None], admin_hint: bool = True) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.ctx = ctx
        self.on_signed_in = on_signed_in
        group = Adw.PreferencesGroup(
            title=_("Sign in to Immich"),
            description=_("Use an administrator account to manage accounts.")
            if admin_hint
            else _("Shared folders belong to the account you sign in with."),
        )
        self.email = Adw.EntryRow(title=_("Email"), input_purpose=Gtk.InputPurpose.EMAIL)
        self.password = Adw.PasswordEntryRow(title=_("Password"))
        self.password.connect("entry-activated", lambda *_: self._go())
        group.add(self.email)
        group.add(self.password)
        self.append(group)
        self.error = label("", css=("error",))
        self.error.set_visible(False)
        self.append(self.error)
        self.button = Gtk.Button(label=_("Sign in"), halign=Gtk.Align.START)
        self.button.add_css_class("pill")
        self.button.add_css_class("suggested-action")
        self.button.connect("clicked", lambda *_: self._go())
        self.append(self.button)
        self.append(
            label(
                _("Your password is not stored. You stay signed in until you close Nuvem Ruscher."),
                css=("dim-label", "caption"),
            )
        )

    def _go(self) -> None:
        email, password = self.email.get_text().strip(), self.password.get_text()
        if not email or not password:
            return
        self.button.set_sensitive(False)
        self.error.set_visible(False)

        def done(_session: object) -> None:
            self.button.set_sensitive(True)
            self.password.set_text("")
            self.on_signed_in()
            for page in ("users", "sharing", "home"):
                target = self.ctx.extras.get(page)
                if target is not None and target is not self and hasattr(target, "session_changed"):
                    target.session_changed()

        def failed(exc: BaseException) -> None:
            self.button.set_sensitive(True)
            self.error.set_text(api_message(exc))
            self.error.set_visible(True)

        run_async(self.ctx.backend.sign_in, email, password, on_done=done, on_error=failed)


# === Nova conta ===============================================================================


class AddAccountDialog(FlowDialog):
    def __init__(self, ctx: AppContext, on_created: Callable[[ImmichUser], None]) -> None:
        super().__init__(_("Add account"), 560, 680)
        self.ctx = ctx
        self.on_created = on_created
        self.push(self._form())

    def _form(self) -> FlowPage:
        page = FlowPage(_("Add account"), "form")
        page.intro(
            _("A new person in your cloud"),
            _("They get their own login, library, phone backup and albums. Nobody sees anyone else’s photos."),
            "avatar-default-symbolic",
        )
        person = Adw.PreferencesGroup()
        self.name = Adw.EntryRow(title=_("Name"))
        self.email = Adw.EntryRow(title=_("Email"), input_purpose=Gtk.InputPurpose.EMAIL)
        self.password = Adw.PasswordEntryRow(title=_("Initial password"))
        self.password.set_text(generate_password())
        regenerate = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER)
        regenerate.add_css_class("flat")
        regenerate.set_tooltip_text(_("Generate another password"))
        regenerate.update_property([Gtk.AccessibleProperty.LABEL], [_("Generate another password")])
        regenerate.connect("clicked", lambda *_: self.password.set_text(generate_password()))
        self.password.add_suffix(regenerate)
        for row in (self.name, self.email, self.password):
            row.connect("changed", lambda *_: self._validate())
            person.add(row)
        page.add(person)
        page.add(
            label(
                _("They will be asked to choose a new password the first time they sign in."),
                css=("dim-label", "caption"),
            )
        )

        storage = Adw.PreferencesGroup(title=_("Storage"))
        self.quota = QuotaRow()
        storage.add(self.quota)
        storage.add(self.quota.custom)
        page.add(storage)

        advanced = Adw.PreferencesGroup()
        expander = Adw.ExpanderRow(title=_("Advanced"), subtitle=_("Storage label and administrator access"))
        self.label_row = Adw.EntryRow(title=_("Storage label (folder name, optional)"))
        self.label_row.connect("changed", lambda *_: self._validate())
        self.admin = Adw.SwitchRow(
            title=_("Administrator"),
            subtitle=_("Can manage accounts, the server and every setting. Give it only to people you trust."),
        )
        self.admin.set_subtitle_lines(3)
        expander.add_row(self.label_row)
        expander.add_row(self.admin)
        advanced.add(expander)
        page.add(advanced)

        self.error = label("", css=("error",))
        self.error.set_visible(False)
        page.add(self.error)
        page.button(_("Cancel"), self.close, start=True)
        self.create = page.button(_("Create account"), self._create, "suggested-action")
        self._validate()
        return page

    def _validate(self) -> None:
        email = self.email.get_text().strip()
        label_text = self.label_row.get_text().strip()
        problems = []
        if email and not EMAIL_RE.match(email):
            problems.append(_("Check the email address."))
        if len(self.password.get_text()) < 8:
            problems.append(_("The password needs at least 8 characters."))
        if label_text and not set(label_text) <= STORAGE_LABEL_CHARS:
            problems.append(_("The storage label can only have lowercase letters, numbers, - and _."))
        self.error.set_text(" ".join(problems))
        self.error.set_visible(bool(problems))
        self.create.set_sensitive(bool(self.name.get_text().strip()) and bool(email) and not problems)

    def _create(self) -> None:
        self.create.set_sensitive(False)
        self.set_busy(True, _("Creating the account…"))
        password = self.password.get_text()

        def done(user: ImmichUser) -> None:
            self.set_busy(False)
            self.on_created(user)
            self.replace(self._created(user, password))

        def failed(exc: BaseException) -> None:
            self.set_busy(False)
            self.create.set_sensitive(True)
            self.error.set_text(api_message(exc))
            self.error.set_visible(True)

        run_async(
            self.ctx.backend.create_account,
            self.name.get_text().strip(),
            self.email.get_text().strip(),
            password,
            self.quota.quota,
            self.label_row.get_text().strip() or None,
            self.admin.get_active(),
            on_done=done,
            on_error=failed,
        )

    def _created(self, user: ImmichUser, password: str) -> FlowPage:
        page = FlowPage(_("Account created"), "created", can_pop=False)
        page.intro(
            _("User created successfully"),
            _("Give these details to {name}. The app on the phone asks for the server address first.").format(
                name=user.name
            ),
            "nr-status-ok-symbolic",
        )
        server = self.ctx.backend.server_url()
        group = Adw.PreferencesGroup()
        for title, value in (
            (_("Server address"), server),
            (_("Email"), user.email),
            (_("Initial password"), password),
        ):
            row = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(value))
            row.add_css_class("property")
            row.set_subtitle_selectable(True)
            copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER)
            copy.add_css_class("flat")
            copy.set_tooltip_text(_("Copy"))
            copy.update_property([Gtk.AccessibleProperty.LABEL], [_("Copy {what}").format(what=title)])
            copy.connect("clicked", lambda b, v=value: (copy_text(b, v), toast(b, _("Copied"))))
            row.add_suffix(copy)
            group.add(row)
        page.add(group)
        qr = QrCode(server, 156)
        frame = qr_frame(qr)
        frame.set_halign(Gtk.Align.CENTER)
        page.add(frame)
        page.add(label(_("Scan with the phone camera to open the server address."), css=("dim-label",), xalign=0.5))
        page.button(_("Done"), self.close, "suggested-action")
        return page


# === Detalhes de uma conta ======================================================================


class AccountDialog(Adw.Dialog):
    def __init__(self, ctx: AppContext, user: ImmichUser, on_changed: Callable[[], None]) -> None:
        super().__init__(title=user.name, content_width=560, content_height=640)
        self.ctx = ctx
        self.user = user
        self.on_changed = on_changed
        session = ctx.backend.session
        self.is_me = session is not None and session.user_id == user.id
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        toolbar.set_content(page)
        self.set_child(toolbar)

        head = Adw.PreferencesGroup()
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER)
        avatar = Adw.Avatar(size=72, text=user.name, show_initials=True)
        top.append(avatar)
        top.append(label(user.name, css=("title-2",), xalign=0.5))
        top.append(label(user.email, css=("dim-label",), xalign=0.5, selectable=True))
        role = _("Administrator") if user.is_admin else _("User")
        if user.disabled:
            role = _("Disabled")
        top.append(label(role, css=("caption-heading",), xalign=0.5))
        head.add(top)
        page.add(head)

        usage = Adw.PreferencesGroup(title=_("Library"))
        usage.add(
            self._property(
                _("Photos and videos"),
                _("{photos} photos · {videos} videos").format(
                    photos=numbers.integer(user.photos), videos=numbers.integer(user.videos)
                ),
            )
        )
        usage.add(self._property(_("Space used"), quota_text(user)))
        if user.quota:
            bar = usage_bar((user.usage or 0) / user.quota, quota_text(user), width=-1)
            bar.set_margin_top(6)
            usage.add(bar)
        page.add(usage)

        settings = Adw.PreferencesGroup(title=_("Settings"))
        self.name = Adw.EntryRow(title=_("Name"), text=user.name, show_apply_button=True)
        self.name.connect("apply", lambda *_: self._save(name=self.name.get_text().strip()))
        settings.add(self.name)
        self.quota = QuotaRow(user.quota)
        self.quota.connect("notify::selected", lambda *_: self._quota_changed())
        self.quota.custom.connect("notify::value", lambda *_: self._quota_changed())
        settings.add(self.quota)
        settings.add(self.quota.custom)
        advanced = Adw.ExpanderRow(title=_("Advanced"), subtitle=_("Storage label and administrator access"))
        self.label_row = Adw.EntryRow(title=_("Storage label"), text=user.storage_label or "", show_apply_button=True)
        self.label_row.connect("apply", lambda *_: self._save(storage_label=self.label_row.get_text().strip() or None))
        advanced.add_row(self.label_row)
        self.admin = Adw.SwitchRow(title=_("Administrator"), active=user.is_admin)
        if self.is_me:
            self.admin.set_sensitive(False)
            self.admin.set_subtitle(_("Your own access can only be changed by another administrator."))
        self.admin.connect("notify::active", lambda *_: self._save(is_admin=self.admin.get_active()))
        advanced.add_row(self.admin)
        settings.add(advanced)
        settings.set_sensitive(not user.disabled)
        page.add(settings)

        actions = Adw.PreferencesGroup(title=_("Access"))
        reset = Adw.ActionRow(
            title=_("Create a temporary password"),
            subtitle=_("For a forgotten password. They must choose a new one the next time they sign in."),
        )
        reset.set_subtitle_lines(3)
        button = Gtk.Button(label=_("Create"), valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda *_: self._reset())
        reset.add_suffix(button)
        reset.set_sensitive(not user.disabled)
        actions.add(reset)
        if user.disabled:
            restore = Adw.ActionRow(
                title=_("Reactivate account"),
                subtitle=_("Immich keeps a disabled account for {days} days before deleting it.").format(
                    days=DELETE_DELAY_DAYS
                ),
            )
            restore.set_subtitle_lines(3)
            again = Gtk.Button(label=_("Reactivate"), valign=Gtk.Align.CENTER)
            again.add_css_class("suggested-action")
            again.connect("clicked", lambda *_: self._call(self.ctx.backend.restore_account, _("Account reactivated")))
            restore.add_suffix(again)
            actions.add(restore)
        elif not self.is_me:
            disable = Adw.ActionRow(
                title=_("Disable account"),
                subtitle=_(
                    "They can no longer sign in. After {days} days Immich deletes the account and its photos "
                    "for good; until then you can reactivate it."
                ).format(days=DELETE_DELAY_DAYS),
            )
            disable.set_subtitle_lines(4)
            off = Gtk.Button(label=_("Disable…"), valign=Gtk.Align.CENTER)
            off.add_css_class("destructive-action")
            off.connect("clicked", lambda *_: self._ask_disable())
            disable.add_suffix(off)
            actions.add(disable)
        page.add(actions)

    @staticmethod
    def _property(title: str, value: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(value))
        row.add_css_class("property")
        return row

    def _quota_changed(self) -> None:
        quota = self.quota.quota
        if quota != self.user.quota:
            self._save(quota=quota)

    def _save(self, **changes: object) -> None:
        def done(user: ImmichUser) -> None:
            self.user = user
            toast(self, _("Saved"))
            self.on_changed()

        def failed(exc: BaseException) -> None:
            toast(self, api_message(exc), 6)

        run_async(self.ctx.backend.update_account, self.user.id, **changes, on_done=done, on_error=failed)

    def _reset(self) -> None:
        def done(password: str) -> None:
            alert = Adw.AlertDialog(
                heading=_("Temporary password"),
                body=_("Give it to {name}. They will choose a new one when they sign in.").format(name=self.user.name),
            )
            entry = Gtk.Entry(text=password, editable=False)
            entry.add_css_class("monospace")
            box = Gtk.Box(spacing=6)
            entry.set_hexpand(True)
            box.append(entry)
            copy = Gtk.Button(icon_name="edit-copy-symbolic")
            copy.set_tooltip_text(_("Copy"))
            copy.connect("clicked", lambda b: (copy_text(b, password), toast(b, _("Copied"))))
            box.append(copy)
            alert.set_extra_child(box)
            alert.add_response("ok", _("Done"))
            alert.present(self)

        run_async(
            self.ctx.backend.reset_account_password,
            self.user.id,
            on_done=done,
            on_error=lambda e: toast(self, api_message(e), 6),
        )

    def _ask_disable(self) -> None:
        confirm(
            self,
            _("Disable {name}’s account?").format(name=self.user.name),
            _(
                "{name} can no longer sign in, and the phone stops backing up. After {days} days Immich deletes "
                "the account and its {photos} photos for good. You can reactivate it before that."
            ).format(name=self.user.name, days=DELETE_DELAY_DAYS, photos=numbers.integer(self.user.photos)),
            _("Disable account"),
            lambda: self._call(self.ctx.backend.disable_account, _("Account disabled")),
            destructive=True,
        )

    def _call(self, method: Callable[[str], ImmichUser], message: str) -> None:
        def done(_user: ImmichUser) -> None:
            toast(self, message)
            self.on_changed()
            self.close()

        run_async(method, self.user.id, on_done=done, on_error=lambda e: toast(self, api_message(e), 6))


def account_status(user: ImmichUser) -> tuple[str, str]:
    """(estado, texto) para a pílula de uma conta."""
    if user.disabled:
        return "error", _("Disabled")
    if user.over_quota:
        return "warning", _("Quota full")
    if user.quota and user.usage is not None and user.usage >= 0.9 * user.quota:
        return "warning", _("Almost full")
    return "ok", _("Active")


def usage_bar(fraction: float, description: str, width: int = 90) -> Gtk.LevelBar:
    """Barra de uso neutra; a partir de 90 % vira aviso (a cor nunca é a única pista: há texto ao lado)."""
    bar = Gtk.LevelBar(min_value=0, max_value=1, valign=Gtk.Align.CENTER, width_request=width)
    for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
        bar.remove_offset_value(offset)
    bar.set_value(max(0.0, min(1.0, fraction)))
    if fraction >= 0.9:
        bar.add_css_class("near-full")
    bar.update_property([Gtk.AccessibleProperty.LABEL], [description])
    return bar


def status_widget(status: str, text: str) -> Gtk.Box:
    box = Gtk.Box(spacing=5, valign=Gtk.Align.CENTER)
    box.add_css_class("state-pill")
    box.add_css_class(status)
    box.append(status_icon(status, 14))
    box.append(label(text, css=("caption-heading",), wrap=False))
    return box
