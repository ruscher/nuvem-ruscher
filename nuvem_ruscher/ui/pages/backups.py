"""Backups do banco (automáticos do Immich e manuais) e o que eles não cobrem."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.backend.base import BackupFile, HelperResult
from nuvem_ruscher.core.storage import human_size
from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.common import StatusBlock, icon_button, show_error, show_in_folder, toast
from nuvem_ruscher.ui.format import relative_time
from nuvem_ruscher.ui.page import Page, group

if TYPE_CHECKING:
    from nuvem_ruscher.ui.shell import AppContext


class BackupsPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            _("Backups"),
            _("Copies of the database: albums, people, favorites and photo details. Immich makes one every night."),
            "document-save-symbolic",
            "yellow",
        )
        self.ctx = ctx
        self.backend = ctx.backend
        self.monitor = ctx.monitor
        self.now = Gtk.Button(label=_("Back up now"), valign=Gtk.Align.CENTER)
        self.now.add_css_class("pill")
        self.now.add_css_class("suggested-action")
        self.now.connect("clicked", self._backup_now)
        self.add_hero_action(self.now)

        self.list = group(_("Database backups"))
        self.where = Adw.ActionRow(title=_("Stored in"), subtitle="—")
        self.where.add_css_class("property")
        self.where.set_subtitle_selectable(True)
        self.list.add(self.where)
        self.add(self.list)
        self.empty = StatusBlock(
            "document-save-symbolic",
            _("No backups yet"),
            _("The first automatic backup happens tonight. If you want, make one now."),
        )
        self.add(self.empty)

        photos = group(
            _("What about the photos?"),
            _("These backups protect the database, not the photos and videos themselves."),
        )
        for icon, title, text in (
            (
                "drive-harddisk-symbolic",
                _("Keep a copy of the photo folder on another disk"),
                _(
                    "From time to time, copy the photo folder to an external disk you keep somewhere else. "
                    "That is the copy that saves your photos if this computer is lost or damaged."
                ),
            ),
            (
                "drive-multidisk-symbolic",
                _("RAID is not a backup"),
                _(
                    "RAID protects against some drive failures. A deleted photo, a virus or a fire affects "
                    "every drive in the array at the same time."
                ),
            ),
            (
                "dialog-information-symbolic",
                _("Where the database backups are"),
                _("They are saved on the photo disk, apart from the database, so one failure does not take both."),
            ),
        ):
            row = Adw.ActionRow(title=title, subtitle=text)
            row.set_subtitle_lines(5)
            image = Gtk.Image.new_from_icon_name(icon)
            image.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            row.add_prefix(image)
            photos.add(row)
        self.add(photos)
        self._rows: list[Gtk.Widget] = []

    def on_shown(self) -> None:
        upload = self.monitor.conf.upload_location
        self.where.set_subtitle(GLib.markup_escape_text(os.path.join(upload, "backups") if upload else "—"))
        run_async(self.backend.backups, on_done=self._show, on_error=lambda _e: self._show([]))

    def _show(self, backups: list[BackupFile]) -> None:
        for row in self._rows:
            self.list.remove(row)
        self._rows = []
        self.empty.set_visible(not backups)
        for backup in backups[:40]:
            kind = _("Automatic") if backup.automatic else _("Manual")
            parts = [kind, human_size(backup.size)]
            if backup.version:
                parts.append(_("Immich {v}").format(v=backup.version))
            row = Adw.ActionRow(title=relative_time(backup.mtime), subtitle=" · ".join(parts))
            icon = Gtk.Image.new_from_icon_name(
                "document-save-symbolic" if backup.automatic else "document-edit-symbolic"
            )
            icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            row.add_prefix(icon)
            row.add_suffix(
                icon_button("folder-open-symbolic", _("Show in folder"), lambda b, p=backup.path: show_in_folder(b, p))
            )
            row.set_tooltip_text(backup.path)
            self.list.add(row)
            self._rows.append(row)

    def _backup_now(self, button: Gtk.Button) -> None:
        if self.monitor.overall != "ok":
            show_error(self, "not-running", _("the server must be on for the backup"))
            return
        self.now.set_sensitive(False)
        self.now.set_label(_("Backing up…"))

        def done(result: HelperResult) -> None:
            self.now.set_sensitive(True)
            self.now.set_label(_("Back up now"))
            if result.ok:
                size = result.results.get("size")
                toast(self, _("Backup done ({size})").format(size=human_size(int(size))) if size else _("Backup done"))
                GLib.timeout_add(300, lambda: self.on_shown() or False)
            else:
                show_error(
                    self, result.error_code, result.error_detail, result.log, retry=lambda: self._backup_now(button)
                )

        self.backend.helper("backup-db", [], None, done)
