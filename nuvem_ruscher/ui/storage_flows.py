"""Assistentes de armazenamento: trocar o local das fotos (doc 08) e criar RAID (doc 09)."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import Adw, Gio, GLib, Gtk

from nuvem_ruscher.async_utils import Operation, run_async
from nuvem_ruscher.backend.base import HelperResult
from nuvem_ruscher.core import migration, numbers, raid
from nuvem_ruscher.core.disks import Disk
from nuvem_ruscher.core.helper_protocol import HelperEvent, human_error
from nuvem_ruscher.core.migration import MigrationPlan, Mode
from nuvem_ruscher.core.storage import FS_DISPLAY, human_size
from nuvem_ruscher.i18n import N_, _
from nuvem_ruscher.ui.common import confirm, details_expander, label, open_folder, status_icon, toast
from nuvem_ruscher.ui.flow import FlowDialog, FlowPage, LogExpander, StepList

if TYPE_CHECKING:
    from nuvem_ruscher.ui.shell import AppContext

# --- textos dos diagnósticos do planejamento ------------------------------------------------

PROBLEMS = {
    "same-path": N_("The new location is the current one."),
    "dest-inside-source": N_("The new location is inside the current one. Choose a folder elsewhere."),
    "source-inside-dest": N_("The current location is inside the new one. Choose another folder."),
    "dest-missing": N_("This disk is not connected (the folder above the new one does not exist)."),
    "dest-symlink": N_("The path goes through a shortcut (symbolic link). Choose the real folder."),
    "dest-not-folder": N_("There is a file with this name. Choose a folder."),
    "dest-read-only": N_("This disk can only be read. Nothing can be saved on it."),
    "dest-not-empty": N_("The new folder already has other files. Choose an empty folder."),
    "no-space": N_("Not enough free space on the new disk."),
    "fat-large-file": N_("This disk is FAT32 and some videos are larger than 4 GB."),
    "symlinks-unsupported": N_("The library has shortcuts that this kind of disk cannot store."),
    "mode-unavailable:adopt": N_("The new folder does not have a complete copy of this library."),
    "mode-unavailable:rename": N_("Renaming only works inside the same disk."),
    "mode-unavailable:copy": N_("Copying is not possible here."),
}
WARNINGS = {
    "same-fs-copy": N_("Same disk: the copy needs as much free space as the library itself."),
    "resume": N_("A previous copy was interrupted here. It continues from where it stopped."),
    "adopt-fewer-files": N_("The new folder has fewer files than the current one. Check it before continuing."),
    "source-unreadable-entries": N_("Some files could not be read and were not counted."),
    "dest-ntfs": N_("Disk formatted on Windows (NTFS): it works, but is slower and needs “Safely remove”."),
    "dest-exfat": N_("exFAT disk: it works, but power failures are riskier."),
    "dest-fat": N_("FAT32 disk: videos larger than 4 GB cannot be stored."),
    "dest-removable": N_("External disk: keep it connected, or the server stops."),
    "dest-system-disk": N_("This is the system disk: photos and the system will share the space."),
}
MODES = {
    Mode.COPY: (
        N_("Move existing data"),
        N_("Copies everything, checks the copy and switches. The old copy stays until you decide. Recommended."),
    ),
    Mode.RENAME: (
        N_("Rename the folder"),
        N_("Same disk: instant, nothing is copied. There will be no old copy."),
    ),
    Mode.ADOPT: (
        N_("Use new location without moving existing data"),
        N_("Only for a folder that already has a full copy of this library."),
    ),
}
DISK_REASONS = {
    "system": N_("Holds the operating system"),
    "swap": N_("Used as swap"),
    "cloud": N_("Holds your photos"),
    "database": N_("Holds the Immich database"),
    "docker": N_("Holds Docker data"),
    "mounted": N_("In use (mounted)"),
    "raid-member": N_("Already part of a RAID"),
    "lvm": N_("Part of an LVM volume"),
    "luks": N_("Encrypted volume (LUKS)"),
    "in-use": N_("In use by another service"),
    "read-only": N_("Read-only"),
    "too-small": N_("Too small"),
}


def disk_reason(disk: Disk) -> str:
    for code in ("system", "cloud", "database", "raid-member", "swap", "luks", "lvm", "in-use", "mounted"):
        if code in disk.reasons:
            return _(DISK_REASONS[code])
    return _(DISK_REASONS[disk.reasons[0]]) if disk.reasons else ""


def property_row(title: str, value: str) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(value))
    row.add_css_class("property")
    row.set_subtitle_selectable(True)
    return row


def notice_row(status: str, text: str) -> Adw.ActionRow:
    row = Adw.ActionRow(title=GLib.markup_escape_text(text))
    row.set_title_lines(4)
    row.add_prefix(status_icon(status))
    return row


# === Trocar o local das fotos ==================================================================


class MigrationDialog(FlowDialog):
    def __init__(self, ctx: AppContext, dest: str = "", on_finished: Callable[[], None] | None = None) -> None:
        super().__init__(_("Change storage location"), 640, 700)
        self.ctx = ctx
        self.backend = ctx.backend
        self.on_finished = on_finished
        self.source = ctx.monitor.conf.upload_location
        self.plan: MigrationPlan | None = None
        self.op: Operation | None = None
        self.push(self._choose_page(dest))

    # --- 1. escolher --------------------------------------------------------------------------
    def _choose_page(self, dest: str) -> FlowPage:
        page = FlowPage(_("New location"), "choose")
        page.intro(
            _("Where should your photos live?"),
            _("Choose a folder on another disk (or on this one). The database stays on the internal disk."),
            "folder-pictures-symbolic",
        )
        current = Adw.PreferencesGroup(title=_("Current location"))
        current.add(property_row(_("Photos and videos"), self.source or "—"))
        page.add(current)

        self.suggestions = Adw.PreferencesGroup(
            title=_("Suggested places"), description=_("Disks connected to this computer.")
        )
        self.suggestions.set_visible(False)
        page.add(self.suggestions)

        manual = Adw.PreferencesGroup(
            title=_("Or choose a folder"), description=_("A new folder is created if it does not exist.")
        )
        self.entry = Adw.EntryRow(title=_("New folder"), text=dest)
        self.entry.connect("changed", lambda *_: self._entry_changed())
        browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        browse.add_css_class("flat")
        browse.set_tooltip_text(_("Choose a folder"))
        browse.update_property([Gtk.AccessibleProperty.LABEL], [_("Choose a folder")])
        browse.connect("clicked", self._browse)
        self.entry.add_suffix(browse)
        manual.add(self.entry)
        page.add(manual)

        page.button(_("Cancel"), self.close, start=True)
        self.next_button = page.button(_("Check this place"), self._check, "suggested-action")
        self._entry_changed()
        run_async(self._suggest, on_done=self._show_suggestions, on_error=lambda _e: None)
        return page

    def _suggest(self) -> list[tuple[str, str, int, int]]:
        places: list[tuple[str, str, int, int]] = []
        seen: set[str] = set()
        current_mount = self.ctx.monitor.conf.mount_point
        for disk in self.backend.disks():
            for part in disk.partitions or []:
                for mount in part.mountpoints:
                    if mount in seen or mount in ("/", "/boot", "/boot/efi", "/efi") or mount.startswith("["):
                        continue
                    seen.add(mount)
                    total, _used, free = self.backend.disk_usage(mount)
                    name = part.label or disk.display_name
                    places.append((name, mount, free, total))
        for array in self.backend.raid_arrays():
            mount = "/mnt/nuvem-ruscher-raid"
            if array.active and mount not in seen:
                total, _used, free = self.backend.disk_usage(mount)
                places.append((_("RAID array"), mount, free, total))
        places.sort(key=lambda p: (p[1] == current_mount, -p[2]))
        return places

    def _show_suggestions(self, places: list[tuple[str, str, int, int]]) -> None:
        for name, mount, free, total in places[:6]:
            folder = mount + ("/immich" if mount.startswith("/mnt/nuvem-ruscher-raid") else "/Nuvem")
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(name),
                subtitle=GLib.markup_escape_text(
                    _("{mount} · {free} free of {total}").format(
                        mount=mount, free=human_size(free), total=human_size(total)
                    )
                ),
                activatable=True,
            )
            row.add_prefix(Gtk.Image.new_from_icon_name("drive-harddisk-symbolic"))
            if self.source.startswith(mount + "/"):
                row.add_suffix(label(_("current disk"), css=("dim-label", "caption"), wrap=False))
            use = Gtk.Button(label=_("Use"), valign=Gtk.Align.CENTER)
            use.connect("clicked", lambda _b, f=folder: self.entry.set_text(f))
            row.add_suffix(use)
            row.connect("activated", lambda _r, f=folder: self.entry.set_text(f))
            self.suggestions.add(row)
        self.suggestions.set_visible(bool(places))

    def _entry_changed(self) -> None:
        text = self.entry.get_text().strip()
        self.next_button.set_sensitive(text.startswith("/") and text.rstrip("/") != self.source.rstrip("/"))

    def _browse(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title=_("Choose the new folder"), modal=True)
        current = self.entry.get_text().strip()
        if current and os.path.isdir(os.path.dirname(current)):
            dialog.set_initial_folder(Gio.File.new_for_path(os.path.dirname(current)))

        def chosen(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                folder = source.select_folder_finish(result)
            except GLib.Error:
                return
            if folder is not None and folder.get_path():
                self.entry.set_text(folder.get_path())

        dialog.select_folder(self.get_root(), None, chosen)

    # --- 2. verificar -------------------------------------------------------------------------
    def _check(self) -> None:
        dest = self.entry.get_text().strip()
        if len(dest) > 1:
            dest = dest.rstrip("/")
        page = FlowPage(_("Checking"), "checking", can_pop=False)
        spinner = Adw.Spinner()
        spinner.set_size_request(48, 48)
        page.add(spinner)
        page.add(label(_("Counting the files and checking the new disk…"), css=("dim-label",), xalign=0.5))
        self.push(page)

        def done(plan: MigrationPlan) -> None:
            self.plan = plan
            self.nav.pop()
            self.push(self._summary_page())

        def failed(exc: BaseException) -> None:
            self.nav.pop()
            toast(self, _("Could not check this place: {error}").format(error=exc))

        run_async(self.backend.plan_migration, dest, on_done=done, on_error=failed)

    # --- 3. resumo ------------------------------------------------------------------------------
    def _summary_page(self) -> FlowPage:
        plan = self.plan
        if plan is None:
            return FlowPage(_("Summary"))
        page = FlowPage(_("Summary"), "summary")
        page.intro(
            _("Check before moving"),
            _("Nothing is deleted. The server stays online while copying and pauses for a few minutes at the end."),
        )
        facts = Adw.PreferencesGroup()
        dest = plan.destination
        facts.add(property_row(_("Current location"), plan.source))
        facts.add(property_row(_("New location"), plan.dest))
        facts.add(property_row(_("Data to transfer"), human_size(plan.stats.bytes)))
        facts.add(
            property_row(
                _("Available destination space"),
                _("{free} of {total}").format(free=human_size(dest.free), total=human_size(dest.total))
                if dest.total
                else "—",
            )
        )
        facts.add(property_row(_("Estimated files"), numbers.integer(plan.stats.files)))
        if dest.fstype:
            facts.add(property_row(_("New disk format"), FS_DISPLAY.get(dest.fstype.lower(), dest.fstype)))
        page.add(facts)

        self.mode_group = Adw.PreferencesGroup(
            title=_("What to do with the existing photos"), description=_("Choose how to bring the library over.")
        )
        first: Gtk.CheckButton | None = None
        self.mode_checks: dict[Mode, Gtk.CheckButton] = {}
        for mode in (Mode.COPY, Mode.RENAME, Mode.ADOPT):
            title, text = MODES[mode]
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if first is None:
                first = check
            else:
                check.set_group(first)
            row = Adw.ActionRow(title=_(title), subtitle=_(text), activatable_widget=check)
            row.set_subtitle_lines(3)
            row.add_prefix(check)
            available = mode in plan.modes
            row.set_sensitive(available)
            if not available:
                reason = PROBLEMS.get(f"mode-unavailable:{mode.value}")
                if reason:
                    row.set_subtitle(f"{_(text)}\n{_(reason)}")
            check.set_active(mode is plan.mode)
            check.connect("toggled", lambda c, m=mode: c.get_active() and self._mode_changed(m))
            self.mode_checks[mode] = check
            self.mode_group.add(row)
        page.add(self.mode_group)

        self.notes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.add(self.notes_box)
        page.button(_("Back"), self.nav.pop, start=True)
        self.start_button = page.button(_("Start move"), self._start, "suggested-action")
        self._show_notes()
        return page

    def _mode_changed(self, mode: Mode) -> None:
        plan = self.plan
        if plan is None:
            return
        self.plan = migration.assess(plan.source, plan.dest, plan.stats, plan.destination, mode)
        self._show_notes()

    def _show_notes(self) -> None:
        plan = self.plan
        if plan is None:
            return
        if (old := self.notes_box.get_first_child()) is not None:
            self.notes_box.remove(old)
        self.notes = Adw.PreferencesGroup()
        self.notes_box.append(self.notes)
        for code in plan.problems:
            text = plan.invalid_message if code == "invalid" else _(PROBLEMS.get(code, code))
            self.notes.add(notice_row("error", text))
        for code in plan.warnings:
            if code in WARNINGS:
                self.notes.add(notice_row("warning", _(WARNINGS[code])))
        if plan.mode is Mode.COPY and plan.can_start:
            self.notes.add(
                notice_row(
                    "info",
                    _("Needs {need} on the new disk (the library plus a safety margin).").format(
                        need=human_size(plan.need_bytes)
                    ),
                )
            )
        self.start_button.set_sensitive(plan.can_start)

    # --- 4. mover ------------------------------------------------------------------------------
    def _start(self) -> None:
        plan = self.plan
        if plan is None or not plan.can_start:
            return
        steps = {
            Mode.COPY: [
                ("backup", _("Backing up the database"), False),
                ("copy", _("Copying the photos (the server stays online)"), True),
                ("finish", _("Finishing the copy (server paused)"), False),
                ("verify", _("Checking the copy"), False),
                ("switch", _("Switching to the new location"), False),
                ("start", _("Starting the server and confirming"), False),
            ],
            Mode.RENAME: [
                ("backup", _("Backing up the database"), False),
                ("finish", _("Pausing the server and renaming the folder"), False),
                ("switch", _("Switching to the new location"), False),
                ("start", _("Starting the server and confirming"), False),
            ],
            Mode.ADOPT: [
                ("backup", _("Backing up the database"), False),
                ("finish", _("Pausing the server"), False),
                ("switch", _("Switching to the new location"), False),
                ("start", _("Starting the server and confirming"), False),
            ],
        }[plan.mode]
        page = FlowPage(_("Moving"), "run", can_pop=False)
        page.intro(_("Moving your photos"), _("You can keep using the computer. Keep the disks connected."))
        self.steps = StepList(steps)
        page.add(self.steps)
        self.detail = LogExpander()
        page.add(self.detail)
        self.cancel_button = page.button(_("Cancel copy"), self._cancel, start=True)
        self.cancel_button.set_sensitive(False)
        self.replace(page)
        self.set_busy(True, _("Your photos are being moved. During the copy you can use “Cancel copy”."))
        app = Gtk.Application.get_default()
        self._inhibit = (
            app.inhibit(
                self.get_root() if isinstance(self.get_root(), Gtk.Window) else None,
                Gtk.ApplicationInhibitFlags.LOGOUT | Gtk.ApplicationInhibitFlags.SUSPEND,
                _("Moving the photo library"),
            )
            if app
            else 0
        )
        self.op = self.backend.helper(
            "migrate-storage", [plan.mode.value, plan.dest], self._event, self._done, interactive=True
        )

    def _cancel(self) -> None:
        if self.op is not None:
            self.cancel_button.set_sensitive(False)
            self.cancel_button.set_label(_("Canceling…"))
            self.op.cancel()

    def _event(self, event: HelperEvent) -> None:
        if event.kind in ("info", "log") and event.value:
            self.detail.append(event.value)
            return
        if event.kind == "step":
            key = {
                "backup": "backup",
                "dump": "backup",
                "copy": "copy",
                "stop": "finish",
                "sync": "finish",
                "move": "finish",
                "verify": "verify",
                "switch": "switch",
                "start": "start",
                "confirm": "start",
            }.get(event.value)
            if key:
                self.steps.start(key)
            self.cancel_button.set_sensitive(event.value == "copy")
            if event.value != "copy":
                self.cancel_button.set_label(_("Cancel copy"))
        elif event.kind == "progress":
            parts = event.value.split()
            if len(parts) == 3 and parts[0] == "copy" and parts[1].isdigit() and parts[2].isdigit():
                done, pct = int(parts[1]), int(parts[2])
                step = self.steps.steps.get("copy")
                if step is not None:
                    step.set_fraction(pct / 100)
                    total = self.plan.stats.bytes if self.plan else 0
                    step.set_detail(
                        _("{percent}% · {done} of {total}").format(
                            percent=pct, done=human_size(done), total=human_size(total)
                        )
                    )

    def _done(self, result: HelperResult) -> None:
        self.op = None
        self.set_busy(False)
        app = Gtk.Application.get_default()
        if app and self._inhibit:
            app.uninhibit(self._inhibit)
        if result.ok:
            self.steps.finish(True)
            self.replace(self._done_page(result))
        else:
            self.steps.fail()
            self.replace(self._failed_page(result))
        self.ctx.monitor.refresh()
        if self.on_finished:
            self.on_finished()

    # --- 5. resultado --------------------------------------------------------------------------
    def _done_page(self, result: HelperResult) -> FlowPage:
        old = result.results.get("old", self.source)
        new = result.results.get("new", self.plan.dest if self.plan else "")
        page = FlowPage(_("Done"), "done", can_pop=False)
        page.intro(
            _("The migration was completed and verified"),
            _("Your photos are now in {new}. The server is running and sees every file.").format(new=new),
            "nr-status-ok-symbolic",
        )
        if self.plan is not None and self.plan.mode is Mode.COPY:
            old_group = Adw.PreferencesGroup(
                title=_("The old files"),
                description=_("Keep the old files as a backup or remove them? Keeping them is the safe choice."),
            )
            old_group.add(property_row(_("Old location"), old))
            page.add(old_group)
            page.button(_("Remove old copy…"), lambda: self._ask_remove(old), "destructive-action", start=True)
            page.button(_("Open old location"), lambda: open_folder(self, old))
            page.button(_("Keep old copy"), self.close, "suggested-action")
        else:
            page.button(_("Close"), self.close, "suggested-action")
        if new.startswith("/run/media/"):
            page.add(
                notice_row(
                    "info",
                    _(
                        "The new disk is mounted only when someone logs in. To start the server right "
                        "after a restart, turn on “Mount the photo disk when the computer starts” in Storage."
                    ),
                )
            )
        return page

    def _ask_remove(self, old: str) -> None:
        size = human_size(self.plan.stats.bytes) if self.plan else ""
        confirm(
            self,
            _("Remove the old copy?"),
            _(
                "This deletes the Immich folders in {path} ({size}). The new location was checked and has "
                "every file. This cannot be undone."
            ).format(path=old, size=size),
            _("Remove old copy"),
            lambda: self._remove(old),
            destructive=True,
        )

    def _remove(self, old: str) -> None:
        self.set_busy(True, _("Removing the old copy…"))

        def done(result: HelperResult) -> None:
            self.set_busy(False)
            if result.ok:
                toast(self, _("Old copy removed"))
                self.close()
            else:
                title, hint = human_error(result.error_code)
                alert = Adw.AlertDialog(heading=title, body=hint)
                alert.set_extra_child(details_expander("\n".join([result.error_detail, *result.log[-30:]])))
                alert.add_response("ok", _("Close"))
                alert.present(self)

        self.backend.helper("remove-old-copy", [old], None, done)

    def _failed_page(self, result: HelperResult) -> FlowPage:
        title, hint = human_error(result.error_code)
        page = FlowPage(_("Not moved"), "failed", can_pop=False)
        page.intro(title, hint, "nr-status-warning-symbolic")
        page.add(details_expander("\n".join([f"code: {result.error_code}", result.error_detail, *result.log[-40:]])))
        page.button(_("Close"), self.close, "suggested-action")
        return page


# === Criar RAID ================================================================================

LEVEL_TEXT = {
    "raid1": (
        N_("RAID 1 — Recommended for most home users"),
        N_(
            "2 drives. Your files are copied to both drives. If one drive fails, your cloud can continue "
            "running from the other drive. Usable capacity: approximately the size of one drive."
        ),
    ),
    "raid5": (
        N_("RAID 5"),
        N_(
            "3 or more drives. Survives one failed drive. Rebuilding large drives takes many hours, and a "
            "second failure during that time loses the array."
        ),
    ),
    "raid6": (
        N_("RAID 6"),
        N_("4 or more drives. Survives two failed drives. Usable capacity: all drives minus two."),
    ),
    "raid10": (
        N_("RAID 10"),
        N_("4, 6 or 8 drives in pairs. Fast, survives one failed drive in each pair. Usable capacity: half."),
    ),
    "raid0": (
        N_("RAID 0 — no protection"),
        N_("RAID 0 provides no redundancy. A failure of any drive can make the entire array unavailable."),
    ),
}


class RaidDialog(FlowDialog):
    def __init__(self, ctx: AppContext, on_created: Callable[[str], None] | None = None) -> None:
        super().__init__(_("Set up RAID"), 640, 720)
        self.ctx = ctx
        self.backend = ctx.backend
        self.on_created = on_created
        self.level = "raid1"
        self.disks: list[Disk] = []
        self.selected: list[Disk] = []
        self.push(self._level_page())

    # --- 1. nível ----------------------------------------------------------------------------
    def _level_page(self) -> FlowPage:
        page = FlowPage(_("Redundancy"), "level")
        page.intro(
            _("Protect your photos from a drive failure"),
            _(
                "RAID keeps your files on more than one drive. The new array starts empty; afterwards you "
                "can move your photos to it."
            ),
            "drive-multidisk-symbolic",
        )
        page.add(notice_row("info", _("RAID protects against some drive failures. RAID is not a backup.")))
        self.tool_row = Adw.ActionRow(
            title=_("The RAID tool (mdadm) is not installed"),
            subtitle=_("It comes from the official repositories. The administrator password is needed."),
        )
        self.tool_row.add_prefix(status_icon("warning"))
        install = Gtk.Button(label=_("Install"), valign=Gtk.Align.CENTER)
        install.add_css_class("suggested-action")
        install.connect("clicked", self._install_mdadm)
        self.tool_row.add_suffix(install)
        tool_group = Adw.PreferencesGroup()
        tool_group.add(self.tool_row)
        tool_group.set_visible(not self.backend.tool_available("mdadm"))
        self.tool_group = tool_group
        page.add(tool_group)

        group = Adw.PreferencesGroup(title=_("Type of RAID"))
        self.level_checks: dict[str, Gtk.CheckButton] = {}
        first = self._level_row(group, "raid1", None)
        advanced = Adw.ExpanderRow(
            title=_("Advanced options"), subtitle=_("More drives, other trade-offs. Read the risks of each one.")
        )
        for level in ("raid5", "raid6", "raid10", "raid0"):
            self._level_row(advanced, level, first)
        group.add(advanced)
        page.add(group)
        page.button(_("Cancel"), self.close, start=True)
        self.level_next = page.button(_("Choose drives"), self._choose_disks, "suggested-action")
        self.level_next.set_sensitive(self.backend.tool_available("mdadm"))
        return page

    def _level_row(self, parent: Gtk.Widget, level: str, group: Gtk.CheckButton | None) -> Gtk.CheckButton:
        title, text = LEVEL_TEXT[level]
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER, active=level == "raid1")
        if group is not None:
            check.set_group(group)
        row = Adw.ActionRow(title=_(title), subtitle=_(text), activatable_widget=check)
        row.set_subtitle_lines(5)
        row.add_prefix(check)
        if level == "raid0":
            row.add_suffix(status_icon("warning"))
            row.add_css_class("warning")
        check.connect("toggled", lambda c, lv=level: c.get_active() and setattr(self, "level", lv))
        if isinstance(parent, Adw.ExpanderRow):
            parent.add_row(row)
        else:
            parent.add(row)
        self.level_checks[level] = check
        return check

    def _install_mdadm(self, button: Gtk.Button) -> None:
        button.set_sensitive(False)

        def done(result: HelperResult) -> None:
            button.set_sensitive(True)
            if result.ok and self.backend.tool_available("mdadm"):
                self.tool_group.set_visible(False)
                self.level_next.set_sensitive(True)
            elif not result.ok:
                title, hint = human_error(result.error_code)
                toast(self, f"{title}. {hint}")

        self.backend.helper("install-tools", ["mdadm"], None, done)

    # --- 2. discos ---------------------------------------------------------------------------
    def _choose_disks(self) -> None:
        page = FlowPage(_("Drives"), "disks")
        page.intro(
            _("Choose the drives"),
            _("Only whole drives that nothing is using can be chosen. The system drive is always protected."),
        )
        self.disk_group = Adw.PreferencesGroup(title=_("Available drives"))
        page.add(self.disk_group)
        self.unavailable = Adw.PreferencesGroup(
            title=_("Not available"), description=_("These drives are protected and cannot be used.")
        )
        page.add(self.unavailable)
        self.capacity = label("", css=("heading",))
        page.add(self.capacity)
        page.button(_("Back"), self.nav.pop, start=True)
        self.disks_next = page.button(_("Continue"), self._confirm_page, "suggested-action")
        self.disks_next.set_sensitive(False)
        self.push(page)
        run_async(self.backend.disks, on_done=self._show_disks, on_error=lambda _e: self._show_disks([]))

    def _show_disks(self, disks: list[Disk]) -> None:
        self.disks = disks
        self.checks: dict[str, Gtk.CheckButton] = {}
        available = [d for d in disks if d.available and d.by_id]
        for disk in available:
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(f"{disk.display_name} · {human_size(disk.size)}"),
                subtitle=GLib.markup_escape_text(
                    _("Device {device} · Serial {serial}").format(device=disk.path, serial=disk.serial or "—")
                ),
                activatable_widget=check,
            )
            row.add_prefix(check)
            pill = label(
                _("Contains existing data") if disk.has_data else _("Empty"),
                css=("pill", "warning" if disk.has_data else "stopped"),
                wrap=False,
            )
            pill.set_valign(Gtk.Align.CENTER)
            row.add_suffix(pill)
            check.connect("toggled", lambda *_: self._selection_changed())
            self.checks[disk.name] = check
            self.disk_group.add(row)
        if not available:
            self.disk_group.add(
                notice_row(
                    "info", _("No free drive was found. Connect two empty drives of similar size and try again.")
                )
            )
        for disk in disks:
            if disk.available and disk.by_id:
                continue
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(f"{disk.display_name} · {human_size(disk.size)}"),
                subtitle=GLib.markup_escape_text(disk_reason(disk) or _("No stable identifier")),
            )
            row.add_prefix(Gtk.Image.new_from_icon_name("changes-prevent-symbolic"))
            row.set_sensitive(False)
            self.unavailable.add(row)
        self._selection_changed()

    def _selection_changed(self) -> None:
        self.selected = [d for d in self.disks if d.name in self.checks and self.checks[d.name].get_active()]
        need = raid.MIN_DISKS[self.level]
        count = len(self.selected)
        ok = count >= need and not (self.level == "raid10" and count % 2)
        usable = raid.usable_size(self.level, [d.size for d in self.selected])
        if ok:
            self.capacity.set_text(_("Usable capacity: about {size}").format(size=human_size(usable)))
        else:
            self.capacity.set_text(_("Choose at least {n} drives.").format(n=need))
        self.disks_next.set_sensitive(ok)

    # --- 3. confirmar -------------------------------------------------------------------------
    def _confirm_page(self) -> None:
        page = FlowPage(_("Confirm"), "confirm")
        page.intro(
            _("Creating this RAID array will erase all data on the selected drives"),
            _("Check each drive. Everything on them is erased; your photos and the system drive are not touched."),
            "dialog-warning-symbolic",
        )
        self.erase_checks: list[Gtk.CheckButton] = []
        for disk in self.selected:
            group = Adw.PreferencesGroup(title=GLib.markup_escape_text(disk.display_name))
            group.add(property_row(_("Drive"), f"{disk.display_name} · {human_size(disk.size)}"))
            group.add(property_row(_("Device"), disk.path))
            group.add(property_row(_("Serial"), disk.serial or "—"))
            fs = ", ".join(sorted({p.fstype for p in disk.partitions if p.fstype} | ({disk.fstype} - {""})))
            group.add(property_row(_("Current file system"), fs or _("none")))
            group.add(property_row(_("Existing data"), _("Detected") if disk.has_data else _("None detected")))
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.connect("toggled", lambda *_: self._confirm_changed())
            row = Adw.ActionRow(title=_("Erase everything on this drive"), activatable_widget=check)
            row.add_prefix(check)
            group.add(row)
            self.erase_checks.append(check)
            page.add(group)
        self.word = _("erase")
        typed = Adw.PreferencesGroup(
            description=_("To confirm, type “{word}” below.").format(word=self.word),
        )
        self.word_entry = Adw.EntryRow(title=_("Confirmation"))
        self.word_entry.connect("changed", lambda *_: self._confirm_changed())
        typed.add(self.word_entry)
        page.add(typed)
        page.button(_("Back"), self.nav.pop, start=True)
        self.create_button = page.button(_("Erase and create RAID"), self._create, "destructive-action")
        self.create_button.set_sensitive(False)
        self.push(page)

    def _confirm_changed(self) -> None:
        typed = self.word_entry.get_text().strip().casefold() == self.word.casefold()
        self.create_button.set_sensitive(typed and all(c.get_active() for c in self.erase_checks))

    # --- 4. criar ----------------------------------------------------------------------------
    def _create(self) -> None:
        page = FlowPage(_("Creating"), "run", can_pop=False)
        page.intro(_("Creating the RAID array"), _("This takes about a minute. Keep the drives connected."))
        self.steps = StepList(
            [
                ("check", _("Checking the drives again"), False),
                ("wipe", _("Erasing the selected drives"), False),
                ("create", _("Creating the array"), False),
                ("format", _("Preparing the file system"), False),
                ("mount", _("Mounting it for the photos"), False),
            ]
        )
        page.add(self.steps)
        self.replace(page)
        self.set_busy(True, _("The RAID array is being created. Please wait."))
        serials = ",".join(d.serial for d in self.selected)
        devices = [d.by_id for d in self.selected]
        mapping = {
            "check": "check",
            "wipe": "wipe",
            "create": "create",
            "format": "format",
            "config": "mount",
            "mount": "mount",
        }

        def event(ev: HelperEvent) -> None:
            if ev.kind == "step" and ev.value in mapping:
                self.steps.start(mapping[ev.value])

        def done(result: HelperResult) -> None:
            self.set_busy(False)
            if result.ok:
                self.steps.finish(True)
                self.replace(self._created_page(result))
                if self.on_created:
                    self.on_created(result.results.get("suggested", ""))
            else:
                self.steps.fail()
                title, hint = human_error(result.error_code)
                failed = FlowPage(_("Not created"), "failed", can_pop=False)
                failed.intro(title, hint, "nr-status-warning-symbolic")
                failed.add(
                    details_expander("\n".join([f"code: {result.error_code}", result.error_detail, *result.log[-40:]]))
                )
                failed.button(_("Close"), self.close, "suggested-action")
                self.replace(failed)

        self.backend.helper("raid-create", [self.level, serials, *devices], event, done)

    def _created_page(self, result: HelperResult) -> FlowPage:
        suggested = result.results.get("suggested", "/mnt/nuvem-ruscher-raid/immich")
        page = FlowPage(_("Ready"), "done", can_pop=False)
        page.intro(
            _("Your RAID is ready"),
            _(
                "It is synchronizing the drives in the background and can already be used. "
                "It is empty: move your photos to it whenever you want."
            ),
            "nr-status-ok-symbolic",
        )
        page.add(notice_row("info", _("RAID protects against some drive failures. RAID is not a backup.")))
        page.button(_("Later"), self.close, start=True)
        page.button(_("Move photos to the RAID…"), lambda: self._move_now(suggested), "suggested-action")
        return page

    def _move_now(self, dest: str) -> None:
        root = self.get_root()
        self.close()
        MigrationDialog(self.ctx, dest).present(root)
