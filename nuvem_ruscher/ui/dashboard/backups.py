"""Backups do banco: automáticos do Immich e manuais do Nuvem Ruscher."""

from __future__ import annotations

import time

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.backend.base import Backend, BackupFile, HelperResult
from nuvem_ruscher.core.storage import human_size
from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.common import StatusBlock, icon_button, label, show_error, show_in_folder, toast
from nuvem_ruscher.ui.dashboard.monitor import ServerMonitor

MONTHS = ("jan.", "fev.", "mar.", "abr.", "maio", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez.")


def friendly_date(timestamp: float) -> str:
    t = time.localtime(timestamp)
    today = time.localtime()
    hour = f"{t.tm_hour:02d}:{t.tm_min:02d}"
    if (t.tm_year, t.tm_yday) == (today.tm_year, today.tm_yday):
        return _("Today, {hour}").format(hour=hour)
    if t.tm_year == today.tm_year and t.tm_yday == today.tm_yday - 1:
        return _("Yesterday, {hour}").format(hour=hour)
    return f"{t.tm_mday} {MONTHS[t.tm_mon - 1]} {t.tm_year}, {hour}"


class BackupsPage(Gtk.Box):
    def __init__(self, backend: Backend, monitor: ServerMonitor) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.backend = backend
        self.monitor = monitor
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        body.set_margin_top(24)
        body.set_margin_bottom(24)
        body.set_margin_start(16)
        body.set_margin_end(16)
        scroller.set_child(Adw.Clamp(maximum_size=760, child=body))
        self.append(scroller)

        head = Gtk.Box(spacing=12)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        texts.append(label(_("Database backups"), css=("title-2",)))
        texts.append(
            label(
                _("They keep albums, people, favorites and photo information. Immich makes one every day at 2 AM."),
                css=("dim-label",),
            )
        )
        head.append(texts)
        self.now = Gtk.Button(label=_("Back up now"), valign=Gtk.Align.CENTER)
        self.now.add_css_class("pill")
        self.now.add_css_class("suggested-action")
        self.now.connect("clicked", self._backup_now)
        head.append(self.now)
        body.append(head)

        self.list = Adw.PreferencesGroup()
        self.empty = StatusBlock(
            "document-save-symbolic",
            _("No backups yet"),
            _("The first automatic backup happens tonight. If you want, make one now."),
        )
        body.append(self.empty)
        body.append(self.list)

        note = Adw.PreferencesGroup()
        row = Adw.ActionRow(
            title=_("What about the photos?"),
            subtitle=_(
                "The database backup does not include the photos. To really protect them, copy the "
                "photo folder to another disk from time to time. Backups are stored on the photo disk, "
                "apart from the database."
            ),
        )
        row.set_subtitle_lines(5)
        row.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        note.add(row)
        body.append(note)
        self._rows: list[Gtk.Widget] = []

    def refresh(self) -> None:
        run_async(self.backend.backups, on_done=self._show, on_error=lambda _e: self._show([]))

    def _show(self, backups: list[BackupFile]) -> None:
        for row in self._rows:
            self.list.remove(row)
        self._rows = []
        self.empty.set_visible(not backups)
        self.list.set_visible(bool(backups))
        for backup in backups[:40]:
            kind = _("Automatic") if backup.automatic else _("Manual")
            parts = [kind, human_size(backup.size)]
            if backup.version:
                parts.append(_("Immich {v}").format(v=backup.version))
            row = Adw.ActionRow(title=friendly_date(backup.mtime), subtitle=" · ".join(parts))
            icon = Gtk.Image.new_from_icon_name(
                "document-save-symbolic" if backup.automatic else "document-edit-symbolic"
            )
            icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            row.add_prefix(icon)
            row.add_suffix(
                icon_button(
                    "folder-open-symbolic",
                    _("Show in folder"),
                    lambda b, p=backup.path: show_in_folder(b, p),
                )
            )
            row.set_tooltip_text(backup.path)
            self.list.add(row)
            self._rows.append(row)

    def _backup_now(self, _button: Gtk.Button) -> None:
        if self.monitor.overall != "ok":
            show_error(self, "not-running", _("the server must be on for the backup"))
            return
        self.now.set_sensitive(False)
        self.now.set_label(_("Backing up…"))

        def done(result: HelperResult) -> None:
            self.now.set_sensitive(True)
            self.now.set_label(_("Back up now"))
            if result.ok:
                toast(
                    self,
                    _("Backup done ({size})").format(size=human_size(int(result.results.get("size", "0") or 0)))
                    if result.results.get("size")
                    else _("Backup done"),
                )
                GLib.timeout_add(300, lambda: self.refresh() or False)
            else:
                show_error(
                    self,
                    result.error_code,
                    result.error_detail,
                    result.log,
                    retry=lambda: self._backup_now(_button),
                )

        self.backend.helper("backup-db", [], None, done)
