"""Armazenamento: onde as fotos ficam, como os discos as protegem e se estão saudáveis."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.backend.base import HelperResult, StorageReport
from nuvem_ruscher.core import raid
from nuvem_ruscher.core.disks import Disk
from nuvem_ruscher.core.migration import MigrationState
from nuvem_ruscher.core.raid import RaidArray, RaidState
from nuvem_ruscher.core.smart import SmartInfo, parse_health_results
from nuvem_ruscher.core.storage import human_size
from nuvem_ruscher.i18n import N_, _, ngettext
from nuvem_ruscher.ui.common import (
    confirm,
    icon_button,
    label,
    open_folder,
    show_error,
    status_icon,
    toast,
)
from nuvem_ruscher.ui.flow import BUSY
from nuvem_ruscher.ui.format import duration
from nuvem_ruscher.ui.page import Page, advanced_expander, group, icon_tile
from nuvem_ruscher.ui.storage_flows import DISK_REASONS, MigrationDialog, RaidDialog, disk_reason, property_row

if TYPE_CHECKING:
    from nuvem_ruscher.ui.shell import AppContext


class LocationCard(Gtk.Box):
    """O local atual das fotos, com espaço usado e livre."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("card")
        self.add_css_class("location-card")
        top = Gtk.Box(spacing=14)
        self.icon = Gtk.Image.new_from_icon_name("folder-pictures-symbolic")
        self.icon.set_pixel_size(32)
        self.icon.add_css_class("accent")
        self.icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        top.append(self.icon)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        self.disk = label("—", css=("title-4",))
        self.path = label("", css=("monospace", "caption"))
        self.path.set_width_chars(1)
        texts.append(self.disk)
        texts.append(self.path)
        top.append(texts)
        self.actions = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        top.append(self.actions)
        self.append(top)
        self.bar = Gtk.LevelBar(min_value=0, max_value=1)
        for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            self.bar.remove_offset_value(offset)
        self.bar.update_property([Gtk.AccessibleProperty.LABEL], [_("Space used")])
        self.append(self.bar)
        numbers = Gtk.Box(spacing=18)
        self.total = label("", css=("caption", "dim-label", "numeric"), wrap=False)
        self.used = label("", css=("caption", "dim-label", "numeric"), wrap=False)
        self.free = label("", css=("caption-heading", "numeric"), wrap=False, xalign=1)
        self.free.set_hexpand(True)
        for widget in (self.total, self.used, self.free):
            numbers.append(widget)
        self.append(numbers)

    def show(self, path: str, disk_name: str, details: str, usage: tuple[int, int, int]) -> None:
        self.disk.set_text(disk_name)
        self.path.set_text(path or "—")
        total, used, free = usage
        self.bar.set_visible(bool(total))
        if total:
            self.bar.set_value(used / total)
            self.total.set_text(_("{size} total").format(size=human_size(total)))
            self.used.set_text(_("{size} used").format(size=human_size(used)))
            self.free.set_text(_("{size} available").format(size=human_size(free)))
        else:
            self.total.set_text(details)
            self.used.set_text("")
            self.free.set_text("")


RAID_STATE = {
    RaidState.HEALTHY: ("ok", N_("Healthy")),
    RaidState.SYNCING: ("pending", N_("Preparing")),
    RaidState.CHECKING: ("pending", N_("Checking")),
    RaidState.REBUILDING: ("warning", N_("Rebuilding")),
    RaidState.DEGRADED: ("warning", N_("Degraded")),
    RaidState.FAILED: ("error", N_("Failed — attention required")),
}
RAID_EXPLAIN = {
    RaidState.HEALTHY: N_("Every drive is working. If one fails, your photos stay available."),
    RaidState.SYNCING: N_("The drives are being prepared. The array can already be used."),
    RaidState.CHECKING: N_("A routine check is reading every drive. Everything keeps working."),
    RaidState.REBUILDING: N_("Copying the data to a replacement drive. Protection returns when it finishes."),
    RaidState.DEGRADED: N_(
        "A drive is missing or failed. Your photos are still available, but there is no protection "
        "until the drive is replaced."
    ),
    RaidState.FAILED: N_(
        "The array is stopped and the photos on it are not available. Do not format any drive: "
        "see the technical details or ask for help."
    ),
}
LEVEL_NAMES = {
    "raid1": N_("RAID 1 — mirror"),
    "raid5": N_("RAID 5"),
    "raid6": N_("RAID 6"),
    "raid10": N_("RAID 10"),
    "raid0": N_("RAID 0 — no redundancy"),
}
HEALTH = {
    "ok": ("ok", N_("Healthy")),
    "warning": ("warning", N_("Needs attention")),
    "error": ("error", N_("Failing")),
    "unknown": ("info", N_("No health data")),
}
KIND_ICONS = {"usb": "drive-harddisk-usb-symbolic", "nvme": "drive-harddisk-solidstate-symbolic"}


def kernel_minutes(text: str) -> float | None:
    """ "84.2min" (estimativa do próprio kernel) → segundos."""
    if text.endswith("min"):
        try:
            return float(text[:-3]) * 60
        except ValueError:
            return None
    return None


def smart_problems(info: SmartInfo) -> list[str]:
    texts = []
    if "failing" in info.problems:
        texts.append(_("The drive’s own self-test reports a failure. Copy your data to another drive."))
    if info.uncorrectable:
        texts.append(
            ngettext("{n} sector could not be read", "{n} sectors could not be read", info.uncorrectable).format(
                n=info.uncorrectable
            )
        )
    if info.media_errors:
        texts.append(ngettext("{n} media error", "{n} media errors", info.media_errors).format(n=info.media_errors))
    if info.reallocated:
        texts.append(
            ngettext("{n} damaged sector was replaced", "{n} damaged sectors were replaced", info.reallocated).format(
                n=info.reallocated
            )
        )
    if info.pending:
        texts.append(
            ngettext(
                "{n} sector is waiting to be checked", "{n} sectors are waiting to be checked", info.pending
            ).format(n=info.pending)
        )
    if "hot" in info.problems and info.temperature is not None:
        texts.append(_("Running hot ({t} °C)").format(t=info.temperature))
    if "worn" in info.problems and info.percentage_used is not None:
        texts.append(_("Worn out ({n}% of its rated life used)").format(n=info.percentage_used))
    return texts


def pill(text: str, status: str) -> Gtk.Box:
    """Pílula de estado com ícone + texto (nunca só cor)."""
    box = Gtk.Box(spacing=5, valign=Gtk.Align.CENTER)
    box.add_css_class("state-pill")
    box.add_css_class(status if status in ("ok", "warning", "error", "pending") else "pending")
    box.append(status_icon(status, 14))
    box.append(label(text, css=("caption-heading",), wrap=False))
    return box


class RaidSection:
    """Redundância: o array do app (ou o convite para criar um)."""

    def __init__(self, page: StoragePage) -> None:
        self.page = page
        self.group = group(
            _("Redundancy"),
            _("How the drives protect the photos. RAID protects against some drive failures. RAID is not a backup."),
        )
        self.rows: list[Gtk.Widget] = []

    def clear(self) -> None:
        for row in self.rows:
            self.group.remove(row)
        self.rows = []

    def add(self, row: Gtk.Widget) -> None:
        self.group.add(row)
        self.rows.append(row)

    def show(self, arrays: list[RaidArray], disks: dict[str, Disk]) -> None:
        self.clear()
        if not arrays:
            row = Adw.ActionRow(
                title=_("Not set up"),
                subtitle=_("Your photos are on a single drive. With a second drive, both can keep a copy."),
            )
            row.set_subtitle_lines(3)
            row.add_prefix(icon_tile("drive-multidisk-symbolic", "slate", 18, "medium"))
            setup = Gtk.Button(label=_("Set up RAID…"), valign=Gtk.Align.CENTER)
            setup.connect("clicked", lambda *_: self.page.open_raid())
            row.add_suffix(setup)
            self.add(row)
            return
        for array in arrays:
            self._show_array(array, disks)

    def _show_array(self, array: RaidArray, disks: dict[str, Disk]) -> None:
        state = array.state
        status, text = RAID_STATE[state]
        level = _(LEVEL_NAMES.get(array.level, array.level.upper() or "RAID"))
        sizes = [disks[m.name].size for m in array.members if m.name in disks]
        usable = raid.usable_size(array.level, sizes) if sizes else array.size_bytes
        head = Adw.ActionRow(
            title=level,
            subtitle=_("{count} drives · usable capacity {size}").format(
                count=array.raid_disks, size=human_size(usable or array.size_bytes)
            ),
        )
        tint = {"ok": "green", "warning": "orange", "error": "red"}.get(status, "teal")
        head.add_prefix(icon_tile("drive-multidisk-symbolic", tint, 18, "medium"))
        head.add_suffix(pill(_(text), status))
        self.add(head)

        explain = Adw.ActionRow(title=_(RAID_EXPLAIN[state]))
        explain.set_title_lines(4)
        explain.add_prefix(status_icon(status))
        if state in (RaidState.SYNCING, RaidState.CHECKING, RaidState.REBUILDING) and array.progress is not None:
            left = kernel_minutes(array.finish)
            note = _("{percent}% done").format(percent=int(array.progress * 100))
            if left:
                note = _("{done} · about {left} left (estimated by the system)").format(done=note, left=duration(left))
            explain.set_subtitle(note)
            bar = Gtk.ProgressBar(fraction=array.progress, valign=Gtk.Align.CENTER, width_request=120)
            bar.update_property([Gtk.AccessibleProperty.LABEL], [note])
            explain.add_suffix(bar)
        self.add(explain)

        for member in sorted(array.members, key=lambda m: m.slot):
            disk = disks.get(member.name)
            name = disk.display_name if disk else member.name
            if member.faulty:
                mstatus, mtext = "error", _("Failed")
            elif member.spare:
                mstatus, mtext = "pending", _("Spare")
            else:
                mstatus, mtext = "ok", _("Working")
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(name),
                subtitle=GLib.markup_escape_text(
                    " · ".join(
                        x
                        for x in (
                            human_size(disk.size) if disk else "",
                            disk.serial if disk else "",
                            f"/dev/{member.name}",
                        )
                        if x
                    )
                ),
            )
            row.add_prefix(
                Gtk.Image.new_from_icon_name(KIND_ICONS.get(disk.kind if disk else "", "drive-harddisk-symbolic"))
            )
            row.add_suffix(pill(mtext, mstatus))
            self.add(row)
        if array.missing and not any(m.faulty for m in array.members):
            missing = Adw.ActionRow(
                title=ngettext("{n} drive is missing", "{n} drives are missing", array.missing).format(n=array.missing)
            )
            missing.add_prefix(status_icon("warning"))
            self.add(missing)

        details = advanced_expander(_("Advanced"), _("Device, status and maintenance"))
        details.add_row(property_row(_("Device"), f"/dev/{array.device}"))
        details.add_row(property_row(_("Name"), array.name))
        details.add_row(property_row(_("Drive status"), f"[{array.status_map}]" if array.status_map else "—"))
        if array.operation:
            details.add_row(property_row(_("Current operation"), f"{array.operation} {array.speed}".strip()))
        check = Adw.ActionRow(
            title=_("Check the drives now"),
            subtitle=_("Reads every drive looking for problems. It takes hours; everything keeps working."),
        )
        check.set_subtitle_lines(3)
        start = Gtk.Button(label=_("Check"), valign=Gtk.Align.CENTER)
        start.set_sensitive(state is RaidState.HEALTHY)
        start.connect("clicked", lambda *_: self.page.raid_check(array.device))
        check.add_suffix(start)
        details.add_row(check)
        if state in (RaidState.DEGRADED, RaidState.FAILED):
            failed = [m.name for m in array.members if m.faulty]
            guide = Adw.ActionRow(
                title=_("Replacing a drive"),
                subtitle=_(
                    "Turn the computer off, replace the failed drive (see its serial number above) with one of "
                    "the same size or bigger, turn it on and add it as administrator with: "
                    "mdadm --manage /dev/{md} --add /dev/<new drive>"
                ).format(md=array.device)
                + (f"\n{', '.join(failed)}" if failed else ""),
            )
            guide.set_subtitle_lines(8)
            guide.set_subtitle_selectable(True)
            details.add_row(guide)
        self.add(details)


class DrivesSection:
    """Discos do computador: o papel de cada um e a saúde (SMART), quando verificada."""

    def __init__(self, page: StoragePage) -> None:
        self.page = page
        self.group = group(_("Drives"), _("Every drive in this computer and what it is used for."))
        self.check_button = Gtk.Button(label=_("Check health"), valign=Gtk.Align.CENTER)
        self.check_button.add_css_class("flat")
        self.check_button.set_tooltip_text(_("Reads the health report of each drive (SMART)"))
        self.check_button.connect("clicked", lambda *_: page.check_health())
        self.group.set_header_suffix(self.check_button)
        self.rows: list[Gtk.Widget] = []
        self.health: dict[str, SmartInfo] = {}

    def show(self, disks: list[Disk]) -> None:
        for row in self.rows:
            self.group.remove(row)
        self.rows = []
        for disk in disks:
            kind = {"hdd": "HDD", "ssd": "SSD", "nvme": "NVMe", "usb": "USB"}.get(disk.kind, "")
            # O transporte só aparece quando diz algo além do tipo (ex.: SATA num HDD).
            transport = disk.transport.upper() if disk.transport.upper() not in (kind.upper(), "") else ""
            parts = [human_size(disk.size), transport, kind]
            role = self._role(disk)
            row = Adw.ExpanderRow(
                title=GLib.markup_escape_text(disk.display_name),
                subtitle=GLib.markup_escape_text(" · ".join(dict.fromkeys(p for p in [*parts, role] if p))),
            )
            row.add_prefix(Gtk.Image.new_from_icon_name(KIND_ICONS.get(disk.kind, "drive-harddisk-symbolic")))
            info = self.health.get(disk.by_id) or self.health.get(disk.path)
            if info is not None:
                status, text = HEALTH[info.level]
                row.add_suffix(pill(_(text), status))
                for problem in smart_problems(info):
                    note = Adw.ActionRow(title=GLib.markup_escape_text(problem))
                    note.set_title_lines(3)
                    note.add_prefix(status_icon("warning" if info.level == "warning" else "error"))
                    row.add_row(note)
                if info.temperature is not None:
                    row.add_row(property_row(_("Temperature"), f"{info.temperature} °C"))
                if info.power_on_hours is not None:
                    row.add_row(property_row(_("Time powered on"), _("{n} hours").format(n=info.power_on_hours)))
            row.add_row(property_row(_("Device"), disk.path))
            row.add_row(property_row(_("Stable name"), disk.by_id or "—"))
            row.add_row(property_row(_("Serial"), disk.serial or "—"))
            for part in disk.partitions:
                where = ", ".join(part.mountpoints) or _("not mounted")
                row.add_row(
                    property_row(
                        part.path, " · ".join(x for x in (part.label, part.fstype, human_size(part.size), where) if x)
                    )
                )
            self.group.add(row)
            self.rows.append(row)

    @staticmethod
    def _role(disk: Disk) -> str:
        if not disk.reasons:
            return _("Free")
        if "cloud" in disk.reasons:
            return _(DISK_REASONS["cloud"])
        return disk_reason(disk)


class StoragePage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            _("Storage"),
            _("Where your photos live, how your drives protect them, and whether they are healthy."),
            "drive-harddisk-symbolic",
            "teal",
        )
        self.ctx = ctx
        self.backend = ctx.backend
        self.monitor = ctx.monitor
        self._report: StorageReport | None = None

        self.location_group = group(_("Cloud storage"), _("The folder that holds every photo and video."))
        self.location = LocationCard()
        self.location.actions.append(icon_button("folder-open-symbolic", _("Open the photo folder"), self._open_folder))
        change = Gtk.Button(label=_("Change location…"), valign=Gtk.Align.CENTER)
        change.connect("clicked", lambda *_: self.open_migration())
        self.location.actions.append(change)
        self.location_group.add(self.location)
        self.add(self.location_group)
        self.move_group = group()
        self.move_group.set_visible(False)
        self.add(self.move_group)
        self._move_rows: list[Gtk.Widget] = []

        self.boot_group = group(_("After a restart"))
        self.boot = Adw.SwitchRow(
            title=_("Mount the photo disk when the computer starts"),
            subtitle=_("The server works right after a restart, even before anyone logs in."),
            sensitive=False,
        )
        self.boot.set_subtitle_lines(3)
        self._boot_handler = self.boot.connect("notify::active", self._toggle_boot)
        self.boot_group.add(self.boot)
        self.add(self.boot_group)

        self.raid = RaidSection(self)
        self.add(self.raid.group)
        self.drives = DrivesSection(self)
        self.add(self.drives.group)
        self._disks: list[Disk] = []

        self.monitor.connect("changed", lambda *_: self._show_location())
        self._raid_timer = 0

    def on_shown(self) -> None:
        self._show_location()
        conf = self.monitor.conf
        if conf.upload_location:
            run_async(self.backend.inspect_storage, conf.upload_location, on_done=self._show_storage)
        self.refresh_drives()
        run_async(self.backend.migration_state, on_done=self._show_move_state, on_error=lambda _e: None)
        if not self._raid_timer:
            # Sincronização/reconstrução do RAID: progresso a cada 5 s com a página à mostra.
            self._raid_timer = GLib.timeout_add_seconds(5, self._tick_raid)

    def on_hidden(self) -> None:
        if self._raid_timer:
            GLib.source_remove(self._raid_timer)
            self._raid_timer = 0

    def _tick_raid(self) -> bool:
        run_async(self.backend.raid_arrays, on_done=self._show_arrays, on_error=lambda _e: None)
        return GLib.SOURCE_CONTINUE

    def refresh_drives(self) -> None:
        def collect() -> tuple[list[Disk], list[RaidArray]]:
            return self.backend.disks(), self.backend.raid_arrays()

        def done(result: tuple[list[Disk], list[RaidArray]]) -> None:
            self._disks, arrays = result
            self.drives.show(self._disks)
            self._show_arrays(arrays)

        run_async(collect, on_done=done, on_error=lambda _e: None)

    def _show_arrays(self, arrays: list[RaidArray]) -> None:
        self.raid.show(arrays, {d.name: d for d in self._disks})
        bad = [a for a in arrays if a.state in (RaidState.DEGRADED, RaidState.FAILED)]
        shell = self.ctx.extras.get("shell")
        if shell is not None and hasattr(shell, "set_badge"):
            shell.set_badge(
                "storage", "!" if bad else None, "error" if any(a.state is RaidState.FAILED for a in bad) else "warning"
            )

    def _show_move_state(self, state: MigrationState | None) -> None:
        for row in self._move_rows:
            self.move_group.remove(row)
        self._move_rows = []
        old = self.monitor.conf.raw.get("OLD_UPLOAD_LOCATION", "")
        if state is not None and state.state == "migrated" and (old or state.old):
            old = old or state.old
            row = Adw.ActionRow(
                title=_("The previous location was kept as a copy"),
                subtitle=GLib.markup_escape_text(old),
            )
            row.add_prefix(status_icon("info"))
            open_button = icon_button("folder-open-symbolic", _("Open old location"), lambda b: open_folder(b, old))
            row.add_suffix(open_button)
            remove = Gtk.Button(label=_("Remove…"), valign=Gtk.Align.CENTER)
            remove.add_css_class("destructive-action")
            remove.connect("clicked", lambda b: self._ask_remove_old(b, old))
            row.add_suffix(remove)
            self.move_group.add(row)
            self._move_rows.append(row)
        elif state is not None and state.state in ("cancelled", "failed") and state.new:
            row = Adw.ActionRow(
                title=_("A move was not finished"),
                subtitle=GLib.markup_escape_text(
                    _("Your photos are still in the current location. Partial copy: {path}").format(path=state.new)
                ),
            )
            row.set_subtitle_lines(3)
            row.add_prefix(status_icon("warning"))
            resume = Gtk.Button(label=_("Resume…"), valign=Gtk.Align.CENTER)
            resume.connect("clicked", lambda *_: self.open_migration(state.new))
            row.add_suffix(resume)
            self.move_group.add(row)
            self._move_rows.append(row)
        self.move_group.set_visible(bool(self._move_rows))

    def _ask_remove_old(self, button: Gtk.Button, old: str) -> None:
        def run() -> None:
            if self in BUSY:
                return
            button.set_sensitive(False)
            BUSY.add(self)  # a janela avisa antes de fechar

            def done(result: HelperResult) -> None:
                BUSY.discard(self)
                button.set_sensitive(True)
                if result.ok:
                    toast(self, _("Old copy removed"))
                    self.on_shown()
                else:
                    show_error(self, result.error_code, result.error_detail, result.log)

            self.backend.helper("remove-old-copy", [old], None, done)

        confirm(
            self,
            _("Remove the old copy?"),
            _(
                "This deletes the Immich folders in {path}. Before deleting, the app checks again that the "
                "current location has every file. This cannot be undone."
            ).format(path=old),
            _("Remove old copy"),
            run,
            destructive=True,
        )

    # --- assistentes e ações ------------------------------------------------------------------
    def open_migration(self, dest: str = "") -> MigrationDialog | None:
        if not self.monitor.conf.upload_location:
            return None
        dialog = MigrationDialog(self.ctx, dest, on_finished=self.on_shown)
        dialog.present(self.get_root())
        return dialog

    def open_raid(self) -> RaidDialog:
        dialog = RaidDialog(self.ctx, on_created=lambda _s: self.on_shown())
        dialog.present(self.get_root())
        return dialog

    def raid_check(self, device: str) -> None:
        def done(result: HelperResult) -> None:
            if result.ok:
                toast(self, _("The check started. It runs in the background."))
                self.refresh_drives()
            else:
                show_error(self, result.error_code, result.error_detail, result.log)

        self.backend.helper("raid-check", [device], None, done)

    def _tools_installed(self, result: HelperResult) -> None:
        if result.ok:
            self.check_health()
        else:
            show_error(self, result.error_code, result.error_detail, result.log)

    def check_health(self) -> None:
        if not self.backend.tool_available("smartctl"):
            confirm(
                self,
                _("Install the health tool?"),
                _("Reading the drives’ health needs smartmontools, from the official repositories."),
                _("Install"),
                lambda: self.backend.helper("install-tools", ["smartmontools"], None, self._tools_installed),
            )
            return
        self.drives.check_button.set_sensitive(False)
        self.drives.check_button.set_label(_("Checking…"))
        targets = [d.by_id for d in self._disks if d.by_id]

        def done(result: HelperResult) -> None:
            self.drives.check_button.set_sensitive(True)
            self.drives.check_button.set_label(_("Check health"))
            if result.ok:
                self.drives.health = parse_health_results(result.results)
                self.drives.show(self._disks)
            else:
                show_error(self, result.error_code, result.error_detail, result.log)

        self.backend.helper("disk-health", targets, None, done)

    def _show_location(self) -> None:
        conf = self.monitor.conf
        report = self._report
        volume = report.volume if report else None
        if volume is not None and volume.device.startswith("/dev/md"):
            name = f"{_('RAID array')} · {volume.label or volume.device}"
            details = volume.fs_display
        elif volume is not None:
            name = volume.display_name
            if volume.is_system_disk:
                kind = _("System disk")
            elif volume.is_external:
                kind = _("External USB disk")
            else:
                kind = _("Internal disk")
            details = f"{kind} · {volume.fs_display}"
            name = f"{name} · {kind}"
        else:
            name = os.path.basename(conf.mount_point) or _("Photo disk")
            details = ""
        self.location.show(conf.upload_location, name, details, self.monitor.disk)

    def _show_storage(self, report: StorageReport) -> None:
        self._report = report
        self._show_location()
        volume = report.volume
        self.boot.handler_block(self._boot_handler)
        if volume is None or not volume.needs_boot_mount:
            self.boot_group.set_visible(volume is None)
            self.boot.set_sensitive(False)
            if volume is None:
                self.boot.set_subtitle(_("Connect the photo disk to see this option."))
        elif report.fstab_state == "foreign":
            self.boot_group.set_visible(True)
            self.boot.set_active(True)
            self.boot.set_sensitive(False)
            self.boot.set_subtitle(_("Already configured in the system (/etc/fstab), outside Nuvem Ruscher."))
        elif report.fstab_state == "unsupported":
            self.boot_group.set_visible(True)
            self.boot.set_active(False)
            self.boot.set_sensitive(False)
            self.boot.set_subtitle(_("This type of disk cannot be mounted automatically at startup."))
        else:
            self.boot_group.set_visible(True)
            self.boot.set_active(report.fstab_state == "ours")
            self.boot.set_sensitive(True)
        self.boot.handler_unblock(self._boot_handler)

    def _toggle_boot(self, row: Adw.SwitchRow, _pspec: object) -> None:
        report = self._report
        if report is None or report.volume is None:
            return
        volume = report.volume
        enable = row.get_active()

        def revert() -> None:
            self.boot.handler_block(self._boot_handler)
            self.boot.set_active(not enable)
            self.boot.handler_unblock(self._boot_handler)

        def run() -> None:
            self.boot.set_sensitive(False)

            def done(result: HelperResult) -> None:
                self.boot.set_sensitive(True)
                if result.ok:
                    toast(self, _("Done!") if enable else _("Automatic mounting turned off"))
                    self.on_shown()
                else:
                    revert()
                    show_error(self, result.error_code, result.error_detail, result.log)

            if enable:
                self.backend.helper("fstab-add", [volume.uuid, volume.mountpoint], None, done)
            else:
                self.backend.helper("fstab-remove", [volume.uuid], None, done)

        if enable:
            run()
        else:
            dialog = confirm(
                self,
                _("Turn off automatic mounting?"),
                _(
                    "After a restart, the server will only start when you log in and the disk appears. Only "
                    "the line created by Nuvem Ruscher is removed from /etc/fstab (with a backup copy)."
                ),
                _("Turn off"),
                run,
            )
            dialog.connect("response", lambda _d, r: revert() if r != "confirm" else None)

    def _open_folder(self, button: Gtk.Button) -> None:
        path = self.monitor.conf.upload_location
        if path and os.path.isdir(path):
            open_folder(button, path)
        else:
            toast(button, _("The photo folder is not available right now."))
