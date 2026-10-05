"""Armazenamento: onde as fotos ficam, como os discos as protegem e se estão saudáveis."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from gi.repository import Adw, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.backend.base import HelperResult, StorageReport
from nuvem_ruscher.core.storage import human_size
from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.common import confirm, icon_button, label, open_folder, show_error, toast
from nuvem_ruscher.ui.page import Page, group

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
        self.path = label("", css=("monospace", "caption"), selectable=True)
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
        self.location_group.add(self.location)
        self.add(self.location_group)

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

        self.monitor.connect("changed", lambda *_: self._show_location())

    def on_shown(self) -> None:
        self._show_location()
        conf = self.monitor.conf
        if conf.upload_location:
            run_async(self.backend.inspect_storage, conf.upload_location, on_done=self._show_storage)

    def _show_location(self) -> None:
        conf = self.monitor.conf
        report = self._report
        volume = report.volume if report else None
        if volume is not None:
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
