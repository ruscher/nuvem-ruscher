"""As telas do assistente, da boas-vindas à celebração."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from gi.repository import Adw, Gio, GLib, Gtk

from nuvem_ruscher.async_utils import Operation, run_async
from nuvem_ruscher.backend.base import (
    CHECK_IDS,
    KNOWN_GOOD_VERSION,
    CheckResult,
    CheckStatus,
    Defaults,
    Fix,
    HelperResult,
    StorageReport,
)
from nuvem_ruscher.constants import HEALTH_TIMEOUT_S
from nuvem_ruscher.core.compose import PullProgress
from nuvem_ruscher.core.helper_protocol import HelperEvent, human_error
from nuvem_ruscher.core.immich_api import ApiError
from nuvem_ruscher.core.releases import Release, local_date
from nuvem_ruscher.core.storage import human_size
from nuvem_ruscher.core.validation import is_valid_email, password_strength
from nuvem_ruscher.i18n import N_, _
from nuvem_ruscher.ui.common import (
    StatusBlock,
    confirm,
    illustration,
    label,
    open_folder,
    open_uri,
    pill_button,
    show_error,
    status_icon,
)
from nuvem_ruscher.ui.dialogs import ConnectStatsDialog
from nuvem_ruscher.ui.widgets.confetti import Confetti
from nuvem_ruscher.ui.widgets.phone import PhoneView
from nuvem_ruscher.ui.widgets.rows import CheckRow, InstallStep
from nuvem_ruscher.ui.wizard.base import WizardPage

if TYPE_CHECKING:
    from nuvem_ruscher.ui.wizard import Wizard


def page_heading(title: str, description: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.append(label(title, css=("title-1",), xalign=0.5))
    box.append(label(description, css=("dim-label", "lead"), xalign=0.5))
    return box


# --- 1. Boas-vindas ---------------------------------------------------------------------


class WelcomePage(WizardPage):
    step = None

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Welcome"), "welcome")
        self.header.set_show_title(False)
        self.actions.set_visible(False)
        self.body.set_valign(Gtk.Align.CENTER)
        self.body.set_spacing(18)
        self.body.append(illustration("nuvem-ruscher-welcome", 300))
        title = label(_("Your photos, at your home."), css=("hero-title",), xalign=0.5)
        title.set_accessible_role(Gtk.AccessibleRole.HEADING)
        self.body.append(title)
        self.body.append(
            label(
                _(
                    "Let’s turn this computer into a “Google Photos” of your own, with Immich. It takes a "
                    "few minutes, and nothing already on your disks will be deleted."
                ),
                css=("lead", "dim-label"),
                xalign=0.5,
            )
        )
        start = pill_button(_("Get started"), lambda *_: self.wizard.go("checks"), suggested=True)
        start.set_margin_top(12)
        self._default_button = start
        self.body.append(start)
        more = Gtk.Button(label=_("What will be installed?"), halign=Gtk.Align.CENTER)
        more.add_css_class("flat")
        more.connect("clicked", self._explain)
        self.body.append(more)

    def _explain(self, button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading=_("What Nuvem Ruscher does"),
            body=_(
                "• Installs Docker, if missing, and runs the official Immich inside it.\n• Stores the "
                "photos in the folder you choose (nothing is deleted or moved).\n• Stores the database "
                "on the internal disk, as Immich recommends.\n• Registers a service that starts the "
                "server only when the photo disk is present.\n• Asks for your administrator password "
                "only for the steps that change the system."
            ),
        )
        dialog.add_response("ok", _("Got it"))
        dialog.present(self.get_root())


# --- 2. Verificação ------------------------------------------------------------------------

CHECK_PLACEHOLDERS = {
    "docker_installed": N_("Docker installed"),
    "docker_running": N_("Docker running"),
    "docker_group": N_("Permission to use Docker"),
    "memory": N_("Memory"),
    "cpu": N_("Processor"),
    "disk_system": N_("Space on the system disk"),
    "port": N_("Port 2283 free"),
    "internet": N_("Internet connection"),
    "firewall": N_("Firewall"),
}


class ChecksPage(WizardPage):
    step = 0

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Check"), "checks")
        self.set_header_title(_("Check"))
        self.body.append(
            page_heading(
                _("Getting ready"),
                _("We check that this computer has everything the photo server needs."),
            )
        )
        group = Adw.PreferencesGroup()
        self.rows: dict[str, CheckRow] = {}
        for check_id in CHECK_IDS:
            row = CheckRow(_(CHECK_PLACEHOLDERS[check_id]))
            self.rows[check_id] = row
            group.add(row)
        self.body.append(group)
        self.summary = label("", css=("dim-label",), xalign=0.5)
        self.body.append(self.summary)

        self.again = Gtk.Button(label=_("Check again"))
        self.again.connect("clicked", lambda *_: self.run_checks())
        self.add_action(self.again, start=True)
        self.next = Gtk.Button(label=_("Continue"), sensitive=False)
        self.next.add_css_class("suggested-action")
        self.next.connect("clicked", lambda *_: self.wizard.go("storage"))
        self.add_action(self.next, default=True)
        self._generation = 0
        self._results: dict[str, CheckResult] = {}
        self._busy = False

    def on_shown(self, first: bool) -> None:
        if first:
            self.run_checks()

    def run_checks(self) -> None:
        self._generation += 1
        generation = self._generation
        self._results.clear()
        self.next.set_sensitive(False)
        self.again.set_sensitive(False)
        self.summary.set_text(_("Checking…"))
        for check_id, row in self.rows.items():
            row.set_result("pending", _(CHECK_PLACEHOLDERS[check_id]), "")
        self._run_one(list(CHECK_IDS), generation)

    def _run_one(self, remaining: list[str], generation: int) -> None:
        if generation != self._generation:
            return
        if not remaining:
            self._finish()
            return
        check_id = remaining.pop(0)
        self.rows[check_id].set_running()
        started = time.monotonic()

        def done(result: CheckResult) -> None:
            if generation != self._generation:
                return
            # Um respiro mínimo entre itens deixa a animação legível.
            delay = max(0, int((0.18 - (time.monotonic() - started)) * 1000))
            GLib.timeout_add(delay + 1, lambda: self._show(result, remaining, generation))

        def failed(exc: BaseException) -> None:
            done(CheckResult(check_id, CheckStatus.WARNING, _(CHECK_PLACEHOLDERS[check_id]), str(exc)))

        run_async(self.backend.check, check_id, on_done=done, on_error=failed)

    def _show(self, result: CheckResult, remaining: list[str], generation: int) -> bool:
        if generation == self._generation:
            self._results[result.id] = result
            fix = result.fix
            self.rows[result.id].set_result(
                result.status.value,
                result.title,
                result.subtitle,
                fix.label if fix else "",
                (lambda f=fix: self._apply_fix(f)) if fix else None,
            )
            self._run_one(remaining, generation)
        return GLib.SOURCE_REMOVE

    def _finish(self) -> None:
        self.again.set_sensitive(True)
        blocking = [r for r in self._results.values() if r.blocking]
        self.next.set_sensitive(not blocking)
        if blocking:
            self.summary.set_text(_("Fix the marked items to continue. Each one has a button that does it for you."))
        else:
            self.summary.set_text(_("All good! You can continue."))

    def _apply_fix(self, fix: Fix) -> None:
        if self._busy:
            return
        self._busy = True
        for row in self.rows.values():
            row.fix_button.set_sensitive(False)
        self.again.set_sensitive(False)
        self.summary.set_text(_("Applying the fix… (the administrator password may be requested)"))

        def done(result: HelperResult) -> None:
            self._busy = False
            for row in self.rows.values():
                row.fix_button.set_sensitive(True)
            if result.ok:
                if fix.action == "firewall-allow":
                    self.backend.state_set("firewall_allowed", True)
                self.toast(_("Done!"))
                self.run_checks()
            else:
                self.again.set_sensitive(True)
                self._finish()
                show_error(
                    self,
                    result.error_code,
                    result.error_detail,
                    result.log,
                    retry=lambda: self._apply_fix(fix),
                )

        self.backend.helper(fix.action, [], None, done)


# --- 3. Armazenamento --------------------------------------------------------------------------


class StoragePage(WizardPage):
    step = 1

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Storage"), "storage")
        self.set_header_title(_("Storage"))
        self.body.append(
            page_heading(
                _("Where your photos will live"),
                _("We chose the disk with the most space. You can change it if you want."),
            )
        )
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=36)
        spinner = Adw.Spinner()
        spinner.set_size_request(32, 32)
        loading.append(spinner)
        loading.append(label(_("Looking for the disk…"), css=("dim-label",), xalign=0.5))
        self.stack.add_named(loading, "loading")
        self.missing = StatusBlock("drive-harddisk-usb-symbolic")
        retry = pill_button(_("Look again"), lambda *_: self.inspect(self.ctx.photo_path), suggested=True)
        self.missing.set_child(retry)
        self.stack.add_named(self.missing, "missing")
        self.ready = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.stack.add_named(self.ready, "ready")
        self.body.append(self.stack)

        choose = Gtk.Button(label=_("Choose another folder…"))
        choose.connect("clicked", self._choose)
        self.add_action(choose, start=True)
        self.next = Gtk.Button(label=_("Continue"), sensitive=False)
        self.next.add_css_class("suggested-action")
        self.next.connect("clicked", self._continue)
        self.add_action(self.next, default=True)
        self.report: StorageReport | None = None
        self.boot_switch: Adw.SwitchRow | None = None

    def on_shown(self, first: bool) -> None:
        if first:
            run_async(self.backend.suggest_photo_path, on_done=self.inspect)

    def inspect(self, path: str) -> None:
        self.ctx.photo_path = path
        self.stack.set_visible_child_name("loading")
        self.next.set_sensitive(False)
        run_async(self.backend.inspect_storage, path, on_done=self._show)

    def _show(self, report: StorageReport) -> None:
        self.report = report
        self.ctx.photo_path = report.path
        if report.error:
            self.missing.set_icon_name("folder-symbolic")
            self.missing.set_title(_("This folder will not work"))
            self.missing.set_description(report.error)
            self.stack.set_visible_child_name("missing")
            return
        if report.disk_missing or report.volume is None:
            self.missing.set_icon_name("drive-harddisk-usb-symbolic")
            self.missing.set_title(_("The disk is not connected"))
            self.missing.set_description(
                _("We could not find {path}. Connect the disk (or choose another folder) and look again.").format(
                    path=report.path
                )
            )
            self.stack.set_visible_child_name("missing")
            return
        self._build_ready(report)
        self.stack.set_visible_child_name("ready")
        self.next.set_sensitive(True)

    def _build_ready(self, report: StorageReport) -> None:
        volume = report.volume
        if volume is None:
            return
        while (child := self.ready.get_first_child()) is not None:
            self.ready.remove(child)

        # Cartão do disco
        card = Gtk.Box(spacing=16)
        card.add_css_class("card")
        card.add_css_class("stat-card")
        icon = Gtk.Image.new_from_icon_name(
            "drive-harddisk-usb-symbolic" if volume.is_external else "drive-harddisk-symbolic"
        )
        icon.set_pixel_size(48)
        icon.set_valign(Gtk.Align.CENTER)
        icon.add_css_class("accent")
        icon.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        card.append(icon)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        info.append(label(volume.display_name, css=("title-3",)))
        parts = [
            _("External USB disk")
            if volume.transport == "usb"
            else (_("System disk") if volume.is_system_disk else _("Internal disk"))
        ]
        if volume.model and volume.model != volume.display_name:
            parts.append(volume.model)
        parts.append(volume.fs_display)
        info.append(label(" · ".join(parts), css=("dim-label",)))
        bar = Gtk.LevelBar(min_value=0, max_value=1, value=(volume.used / volume.size) if volume.size else 0)
        bar.remove_offset_value(Gtk.LEVEL_BAR_OFFSET_LOW)
        bar.remove_offset_value(Gtk.LEVEL_BAR_OFFSET_HIGH)
        bar.remove_offset_value(Gtk.LEVEL_BAR_OFFSET_FULL)
        bar.set_margin_top(4)
        bar.update_property([Gtk.AccessibleProperty.LABEL], [_("Disk space used")])
        info.append(bar)
        info.append(
            label(
                _("{free} free of {total}").format(free=human_size(volume.available), total=human_size(volume.size)),
                css=("caption", "numeric"),
            )
        )
        card.append(info)
        self.ready.append(card)

        folder = Adw.PreferencesGroup()
        path_row = Adw.ActionRow(title=_("Photo folder"), subtitle=GLib.markup_escape_text(report.path))
        path_row.set_subtitle_selectable(True)
        path_row.add_prefix(Gtk.Image.new_from_icon_name("folder-pictures-symbolic"))
        if os.path.isdir(report.path):
            open_button = Gtk.Button.new_from_icon_name("folder-open-symbolic")
            open_button.set_tooltip_text(_("Open the folder"))
            open_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Open the folder")])
            open_button.add_css_class("flat")
            open_button.set_valign(Gtk.Align.CENTER)
            open_button.connect("clicked", lambda b: open_folder(b, report.path))
            path_row.add_suffix(open_button)
        folder.add(path_row)
        if report.library and report.library.exists:
            lib_row = Adw.ActionRow(
                title=_("We found photos from a previous installation"),
                subtitle=_("They will be reused — nothing will be deleted."),
            )
            lib_row.set_subtitle_lines(3)
            lib_row.add_prefix(status_icon("info"))
            folder.add(lib_row)
        self.ready.append(folder)

        for warning in report.warnings:
            group = Adw.PreferencesGroup()
            expander = Adw.ExpanderRow(
                title=GLib.markup_escape_text(warning.title),
                subtitle=GLib.markup_escape_text(warning.summary),
            )
            expander.set_subtitle_lines(3)
            expander.add_prefix(status_icon(warning.level))
            expander.set_expanded(warning.level == "error")
            for detail in warning.details:
                text = label(detail)
                text.set_margin_top(10)
                text.set_margin_bottom(10)
                text.set_margin_start(14)
                text.set_margin_end(14)
                expander.add_row(text)
            group.add(expander)
            self.ready.append(group)

        self.boot_switch = None
        if volume.needs_boot_mount:
            boot = Adw.PreferencesGroup(
                title=_("After a restart"),
                description=_(
                    "Today this disk only appears when you log in. Without the option below, the server "
                    "starts by itself as soon as you log in and the disk appears."
                ),
            )
            if report.fstab_state == "none":
                self.boot_switch = Adw.SwitchRow(
                    title=_("Mount the disk when the computer starts (recommended)"),
                    subtitle=_(
                        "The server works right after a restart, even before you log in. The disk keeps "
                        "appearing in the same place. If it is not connected, the computer starts normally."
                    ),
                )
                self.boot_switch.set_subtitle_lines(5)
                boot.add(self.boot_switch)
                tech = Adw.ExpanderRow(title=_("Technical details"))
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                for margin in ("top", "bottom", "start", "end"):
                    getattr(box, f"set_margin_{margin}")(12)
                box.append(
                    label(
                        _(
                            "This line will be added to /etc/fstab, mounting the disk by UUID at the same path as "
                            "today. First a copy of the file is saved; the result is validated with “findmnt "
                            "--verify” and, if anything fails, the original comes back by itself."
                        ),
                        css=("caption",),
                    )
                )
                line = label(report.fstab_preview, css=("fstab-line",), selectable=True)
                box.append(line)
                tech.add_row(box)
                boot.add(tech)
            elif report.fstab_state == "ours":
                row = Adw.ActionRow(
                    title=_("The disk already mounts when the computer starts"),
                    subtitle=_("Automatic mounting configured by Nuvem Ruscher."),
                )
                row.add_prefix(status_icon("ok"))
                boot.add(row)
            elif report.fstab_state == "foreign":
                row = Adw.ActionRow(
                    title=_("This disk is already mounted by the system"),
                    subtitle=_("There is a rule for it in /etc/fstab. Nothing will be changed."),
                )
                row.add_prefix(status_icon("ok"))
                boot.add(row)
            else:
                row = Adw.ActionRow(
                    title=_("This type of disk cannot be mounted automatically at startup"),
                    subtitle=_("The server will start when you log in and the disk appears."),
                )
                row.add_prefix(status_icon("info"))
                boot.add(row)
            self.ready.append(boot)

        note = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        note.append(Gtk.Image.new_from_icon_name("security-high-symbolic"))
        note.append(
            label(
                _("The database (albums, people, information) stays on the computer’s internal disk."),
                css=("dim-label", "caption"),
            )
        )
        self.ready.append(note)

    def _choose(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title=_("Choose the photo folder"), modal=True)
        current = self.ctx.photo_path
        start = current if os.path.isdir(current) else os.path.dirname(current)
        if os.path.isdir(start):
            dialog.set_initial_folder(Gio.File.new_for_path(start))

        def picked(dlg: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                folder = dlg.select_folder_finish(result)
            except GLib.Error:
                return
            if folder is None or folder.get_path() is None:
                return
            path = folder.get_path()
            # Escolheu a raiz de um disco? Usamos uma subpasta própria (ADR-004).
            if os.path.ismount(path) or os.path.dirname(path) == f"/run/media/{self.backend.user_name()}":
                path = os.path.join(path, f"immich-{self.backend.user_name()}")
            self.inspect(path)

        dialog.select_folder(self.get_root(), None, picked)

    def _continue(self, _button: Gtk.Button) -> None:
        report = self.report
        if report is None or report.volume is None:
            return
        if any(w.level == "error" for w in report.warnings) and not self.ctx.extras.get("fat_ok"):

            def accept() -> None:
                self.ctx.extras["fat_ok"] = True
                self._continue(_button)

            confirm(
                self,
                _("Use it anyway?"),
                _("Videos larger than 4 GB cannot be stored on this disk."),
                _("Use this disk"),
                accept,
            )
            return
        self.ctx.storage = report
        if self.boot_switch is not None and self.boot_switch.get_active():
            self._enable_boot_mount(report)
        else:
            self.wizard.go("configure")

    def _enable_boot_mount(self, report: StorageReport) -> None:
        volume = report.volume
        if volume is None:
            return
        self.next.set_sensitive(False)
        self.next.set_label(_("Configuring…"))

        def done(result: HelperResult) -> None:
            self.next.set_sensitive(True)
            self.next.set_label(_("Continue"))
            if result.ok:
                self.toast(_("Done! The disk will mount when the computer starts."))
                report.fstab_state = "ours"
                self._build_ready(report)
                self.wizard.go("configure")
                return
            show_error(
                self,
                result.error_code,
                result.error_detail,
                result.log,
                retry=lambda: self._enable_boot_mount(report),
                alternative=(_("Continue without it"), lambda: self.wizard.go("configure")),
            )

        self.backend.helper("fstab-add", [volume.uuid, volume.mountpoint], None, done)


# --- 4. Ajustes -------------------------------------------------------------------------------

ML_LABELS = {
    "cpu": N_("Processor"),
    "openvino": N_("Intel graphics (OpenVINO)"),
    "rocm": N_("AMD graphics (ROCm) — large download"),
    "cuda": N_("NVIDIA graphics (CUDA)"),
}
VENDOR_LABELS = {"amd": "AMD", "intel": "Intel", "nvidia": "NVIDIA"}


class ConfigurePage(WizardPage):
    step = 2

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Settings"), "configure")
        self.set_header_title(_("Final settings"))
        self.body.append(
            page_heading(_("Final settings"), _("We have set everything up already. Change only if you want."))
        )
        group = Adw.PreferencesGroup()
        self.timezone = Adw.ComboRow(title=_("Time zone"), subtitle=_("Detected from the system"))
        self.timezone.set_enable_search(True)
        self.timezone.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        group.add(self.timezone)
        self.version = Adw.ComboRow(title=_("Immich version"), subtitle=_("Looking for versions…"))
        self.version.set_sensitive(False)
        group.add(self.version)
        self.body.append(group)

        advanced = Adw.PreferencesGroup()
        self.expander = Adw.ExpanderRow(
            title=_("Advanced options"), subtitle=_("Graphics card and artificial intelligence")
        )
        self.transcode = Adw.SwitchRow(title=_("Faster videos with the graphics card"))
        self.transcode.set_subtitle_lines(3)
        self.ml = Adw.SwitchRow(
            title=_("Face recognition and smart search"),
            subtitle=_("Find photos by typing “beach” or “dog”. Uses about 1 to 2 GB of memory."),
            active=True,
        )
        self.ml.set_subtitle_lines(3)
        self.ml_accel = Adw.ComboRow(
            title=_("Speed up artificial intelligence with"),
            subtitle=_("The processor is the most compatible and recommended choice"),
        )
        self.ml_accel.set_subtitle_lines(2)
        self.ml.connect("notify::active", lambda *_: self.ml_accel.set_sensitive(self.ml.get_active()))
        for row in (self.transcode, self.ml, self.ml_accel):
            self.expander.add_row(row)
        advanced.add(self.expander)
        self.body.append(advanced)

        self.install = Gtk.Button(label=_("Install"), sensitive=False)
        self.install.add_css_class("suggested-action")
        self.install.connect("clicked", self._install)
        self.add_action(self.install, default=True)
        self._releases: list[str] = []
        self._ml_options: list[str] = ["cpu"]
        self._timezones: list[str] = []
        self._loaded = 0

    def on_shown(self, first: bool) -> None:
        if first:
            run_async(self.backend.defaults, on_done=self._defaults)
            run_async(self.backend.releases, on_done=self._got_releases, on_error=self._no_releases)

    def _defaults(self, defaults: Defaults) -> None:
        zones = defaults.timezones or [defaults.timezone]
        if defaults.timezone not in zones:
            zones = [defaults.timezone, *zones]
        self._timezones = zones
        self.timezone.set_model(Gtk.StringList.new(zones))
        self.timezone.set_selected(zones.index(defaults.timezone))
        gpu = defaults.gpu
        if gpu.transcode != "cpu":
            vendors = ", ".join(VENDOR_LABELS.get(v, v) for v in gpu.vendors)
            self.transcode.set_subtitle(
                _("Card detected: {vendor}. Converts videos for the phone much faster.").format(vendor=vendors)
            )
            self.transcode.set_active(True)
            self.ctx.extras["transcode_mode"] = gpu.transcode
        else:
            self.transcode.set_subtitle(_("No compatible card found; the processor will do the work."))
            self.transcode.set_sensitive(False)
        if not defaults.ml_recommended:
            self.ml.set_active(False)
            self.ml.set_subtitle(_("Turned off to fit in this computer’s memory. You can turn it on later."))
        self._ml_options = list(gpu.ml_options)
        self.ml_accel.set_model(Gtk.StringList.new([_(ML_LABELS[o]) for o in self._ml_options]))
        self.ml_accel.set_selected(0)
        self.ml_accel.set_sensitive(self.ml.get_active() and len(self._ml_options) > 1)
        self._loaded |= 1
        self._update()

    def _got_releases(self, releases: list[Release]) -> None:
        stable = releases[:6]
        self._releases = [r.tag for r in stable]
        labels = []
        for index, release in enumerate(stable):
            if index == 0:
                labels.append(_("{tag} — latest").format(tag=release.tag))
            else:
                labels.append(f"{release.tag} ({local_date(release.published)})")
        self.version.set_model(Gtk.StringList.new(labels))
        self.version.set_selected(0)
        self.version.set_subtitle(_("We recommend the latest one"))
        self.version.set_sensitive(True)
        self._loaded |= 2
        self._update()

    def _no_releases(self, _exc: BaseException) -> None:
        self._releases = [KNOWN_GOOD_VERSION]
        self.version.set_model(Gtk.StringList.new([KNOWN_GOOD_VERSION]))
        self.version.set_subtitle(_("No access to GitHub right now: we will use the tested version"))
        self._loaded |= 2
        self._update()

    def _update(self) -> None:
        self.install.set_sensitive(self._loaded == 3)

    def _install(self, _button: Gtk.Button) -> None:
        self.ctx.timezone = self._timezones[self.timezone.get_selected()] if self._timezones else "Etc/UTC"
        self.ctx.version = self._releases[self.version.get_selected()] if self._releases else KNOWN_GOOD_VERSION
        mode = str(self.ctx.extras.get("transcode_mode", "cpu"))
        self.ctx.transcode = mode if self.transcode.get_active() else "cpu"
        if not self.ml.get_active():
            self.ctx.ml = "off"
        else:
            index = self.ml_accel.get_selected()
            self.ctx.ml = self._ml_options[index] if 0 <= index < len(self._ml_options) else "cpu"
        self.wizard.go("install")


# --- 5. Instalação ------------------------------------------------------------------------------

STEP_TITLES = {
    "prepare": N_("Preparing the configuration"),
    "download": N_("Downloading the components"),
    "start": N_("Starting the server"),
    "health": N_("Waiting for the server to be ready"),
}
HELPER_STEP_TEXT = {
    "storage": N_("Checking the photo disk"),
    "download": N_("Downloading the official Immich configuration"),
    "env": N_("Creating the database password"),
    "service": N_("Registering the service in the system"),
    "start": N_("Starting…"),
    "restart": N_("Restarting with the new configuration…"),
}
ORDER = ("prepare", "download", "start", "health")


class InstallPage(WizardPage):
    step = 3

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Installation"), "install")
        self.set_header_title(_("Installation"))
        self.body.append(
            page_heading(
                _("Installing your cloud"),
                _("It takes a few minutes, depending on the internet. You can keep using the computer."),
            )
        )
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("card")
        self.steps: dict[str, InstallStep] = {}
        for index, key in enumerate(ORDER):
            if index:
                card.append(Gtk.Separator())
            step = InstallStep(_(STEP_TITLES[key]), with_progress=key == "download")
            self.steps[key] = step
            card.append(step)
        self.body.append(card)

        self.error_group = Adw.PreferencesGroup(visible=False)
        self.error_row = Adw.ActionRow()
        self.error_row.set_subtitle_lines(4)
        self.error_row.add_prefix(status_icon("error", 20))
        self.error_group.add(self.error_row)
        self.body.append(self.error_group)

        self.log_buffer = Gtk.TextBuffer()
        log_view = Gtk.TextView(buffer=self.log_buffer, editable=False, cursor_visible=False, monospace=True)
        log_view.add_css_class("log-view")
        log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        for side in ("top", "bottom", "left", "right"):
            getattr(log_view, f"set_{side}_margin")(10)
        self.log_scroller = Gtk.ScrolledWindow(min_content_height=200, max_content_height=260, child=log_view)
        self.log_scroller.add_css_class("card")
        self.log_scroller.add_css_class("log-frame")
        expander = Gtk.Expander(label=_("Technical details"), child=self.log_scroller)
        self.body.append(expander)

        self.cancel = Gtk.Button(label=_("Cancel"))
        self.cancel.connect("clicked", self._cancel)
        self.add_action(self.cancel, start=True)
        self.retry = Gtk.Button(label=_("Try again"), visible=False)
        self.retry.add_css_class("suggested-action")
        self.retry.connect("clicked", lambda *_: self.run(self._failed_step or "prepare"))
        self.add_action(self.retry)
        self.next = Gtk.Button(label=_("Continue"), visible=False)
        self.next.add_css_class("suggested-action")
        self.next.connect("clicked", lambda *_: self._advance())
        self.add_action(self.next, default=True)

        self._op: Operation | None = None
        self._cancelled = False
        self._failed_step: str | None = None
        self._health_source = 0
        self._health_started = 0.0
        self._restart_needed = False
        self._log_lines = 0

    # -- infraestrutura
    def log(self, text: str) -> None:
        if not text:
            return
        end = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end, text + "\n")
        self._log_lines += 1
        if self._log_lines > 2000:
            start = self.log_buffer.get_start_iter()
            cut = self.log_buffer.get_iter_at_line(500)[1]
            self.log_buffer.delete(start, cut)
            self._log_lines -= 500
        adj = self.log_scroller.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()) or False)

    def on_shown(self, first: bool) -> None:
        if first:
            resume = str(self.backend.state_get("install_step", "") or "")
            conf = self.backend.load_config()
            if not self.ctx.version and conf.installed and resume in ORDER and resume != "prepare":
                # App reaberto no meio da instalação: a configuração já existe.
                self.run(resume)
            elif not self.ctx.version and conf.installed:
                self.run("download")
            else:
                self.run("prepare")

    def run(self, step: str) -> None:
        self._cancelled = False
        self._failed_step = None
        self.error_group.set_visible(False)
        self.retry.set_visible(False)
        self.next.set_visible(False)
        self.cancel.set_visible(True)
        self.cancel.set_sensitive(True)
        self.set_can_pop(False)
        reached = False
        for key in ORDER:
            if key == step:
                reached = True
            if reached:
                self.steps[key].set_state("pending", "")
            elif self.steps[key].state != "ok":
                # Retomando: o que veio antes já foi feito numa execução anterior.
                self.steps[key].set_state("ok", _("Already done"))
        self.backend.state_set("install_step", step)
        getattr(self, f"_step_{step}")()

    def _fail(self, step: str, code: str, detail: str = "", log: list[str] | None = None) -> None:
        self._failed_step = step
        title, hint = human_error(code)
        self.steps[step].set_state("error", title)
        self.error_row.set_title(GLib.markup_escape_text(title))
        self.error_row.set_subtitle(GLib.markup_escape_text(hint))
        self.error_group.set_visible(True)
        if detail:
            self.log(f"[erro] {code}: {detail}")
        for line in log or []:
            if line.startswith("@@ERROR"):
                self.log(line)
        self.retry.set_label(_("Try again"))
        self.retry.set_visible(True)
        self.cancel.set_visible(False)
        self.set_can_pop(True)

    def _pause(self, step: str) -> None:
        self._failed_step = step
        self.steps[step].set_state("warning", _("Paused. You can continue where you left off."))
        self.retry.set_label(_("Continue"))
        self.retry.set_visible(True)
        self.cancel.set_visible(False)
        self.set_can_pop(True)

    def _cancel(self, _button: Gtk.Button) -> None:
        self._cancelled = True
        self.cancel.set_sensitive(False)
        if self._op is not None and self._op.running:
            self._op.cancel()
        if self._health_source:
            GLib.source_remove(self._health_source)
            self._health_source = 0
            self._pause("health")

    # -- etapas
    def _step_prepare(self) -> None:
        step = self.steps["prepare"]
        step.set_state("running", _("Requesting authorization… type your administrator password, if asked"))
        args = [
            self.ctx.version or KNOWN_GOOD_VERSION,
            self.ctx.photo_path,
            self.ctx.timezone or "Etc/UTC",
            self.ctx.transcode,
            self.ctx.ml,
        ]

        def event(ev: HelperEvent) -> None:
            if ev.kind == "step" and ev.value in HELPER_STEP_TEXT:
                step.set_detail(_(HELPER_STEP_TEXT[ev.value]))
            if ev.kind != "result":
                self.log(ev.value if ev.kind == "log" else f"• {ev.kind}: {ev.key or ''} {ev.value}".strip())

        def done(result: HelperResult) -> None:
            self._op = None
            if not result.ok:
                self._fail("prepare", result.error_code, result.error_detail, result.log)
                return
            self._restart_needed = result.results.get("restart-needed") == "1"
            step.set_state("ok", _("Configuration ready"))
            self.backend.state_set("install_step", "download")
            self._step_download()

        self._op = self.backend.helper("setup", args, event, done)

    def _step_download(self) -> None:
        step = self.steps["download"]
        step.set_state("running", _("Preparing the download…"))
        step.set_fraction(0)
        self.backend.state_set("install_step", "download")
        last_log = {"t": 0.0}

        def progress(p: PullProgress, line: str) -> None:
            step.set_fraction(p.fraction)
            if p.unpacking:
                step.set_detail(_("Unpacking the components…"))
            elif p.total:
                speed = p.speed()
                text = _("{percent}% · {done} downloaded").format(
                    percent=int(p.fraction * 100), done=human_size(p.downloaded)
                )
                if speed > 0:
                    text += " · " + _("{speed}/s").format(speed=human_size(speed))
                step.set_detail(text)
            now = time.monotonic()
            if not line.startswith("{") or now - last_log["t"] > 1.5:
                last_log["t"] = now
                self.log(line[:200])

        def done(ok: bool, p: PullProgress) -> None:
            self._op = None
            if self._cancelled:
                self._pause("download")
                return
            if not ok:
                self._fail("download", "download-failed", "; ".join(p.errors[-3:]))
                return
            step.set_fraction(1)
            step.set_state(
                "ok",
                _("Components downloaded ({size})").format(size=human_size(p.total))
                if p.total
                else _("Components ready"),
            )
            self._step_start()

        try:
            self._op = self.backend.pull(progress, done)
        except OSError as exc:
            self._fail("download", "not-installed", str(exc))

    def _step_start(self) -> None:
        step = self.steps["start"]
        step.set_state("running", _("Starting…"))
        self.backend.state_set("install_step", "start")
        action = "restart" if self._restart_needed else "start"

        def done(result: HelperResult) -> None:
            self._op = None
            if not result.ok:
                self._fail("start", result.error_code, result.error_detail, result.log)
                return
            step.set_state("ok", _("Server on"))
            self._step_health()

        self._op = self.backend.helper(action, [], None, done)

    def _step_health(self) -> None:
        step = self.steps["health"]
        step.set_state("running", _("The server is waking up…"))
        self.backend.state_set("install_step", "health")
        self._health_started = time.monotonic()
        self._health_tick()

    def _health_tick(self) -> bool:
        self._health_source = 0
        if self._cancelled:
            return GLib.SOURCE_REMOVE
        elapsed = time.monotonic() - self._health_started
        step = self.steps["health"]

        def got(result: tuple[bool, int, int]) -> None:
            if self._cancelled:
                return
            healthy, ready, total = result
            if healthy:
                step.set_state("ok", _("All set!"))
                self._finished()
                return
            if elapsed > HEALTH_TIMEOUT_S:
                self._fail("health", "service-failed", f"no response after {HEALTH_TIMEOUT_S}s")
                return
            text = _("{ready} of {total} components ready").format(ready=ready, total=total) if total else ""
            if elapsed > 60:
                text = (text + " · " if text else "") + _(
                    "The first time takes longer: the database is being prepared."
                )
            step.set_detail(text or _("The server is waking up…"))
            self._health_source = GLib.timeout_add(2000, self._health_tick)

        def probe() -> tuple[bool, int, int]:
            containers = self.backend.containers()
            ready = sum(1 for c in containers if c.ok)
            return self.backend.ping(), ready, len(containers)

        run_async(probe, on_done=got, on_error=lambda _e: got((False, 0, 0)))
        return GLib.SOURCE_REMOVE

    def _finished(self) -> None:
        self.ctx.installed_now = True
        self.backend.state_set("install_step", "done")
        self.cancel.set_visible(False)
        self.next.set_visible(True)
        self.toast(_("Server is up!"))
        GLib.timeout_add(900, lambda: self._advance() or False)

    def _advance(self) -> None:
        if self.wizard.nav.get_visible_page() is self:
            self.wizard.go_replace("account")


# --- 6. Conta ------------------------------------------------------------------------------------


class AccountPage(WizardPage):
    step = 4

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Account"), "account", can_pop=False)
        self.set_header_title(_("Account"))
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        loading = Adw.Spinner()
        loading.set_size_request(32, 32)
        loading.set_margin_top(48)
        self.stack.add_named(loading, "loading")

        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        form.append(
            page_heading(
                _("Create your administrator account"),
                _("You use it to sign in to the phone app and the website. Keep the password safe."),
            )
        )
        group = Adw.PreferencesGroup()
        self.name = Adw.EntryRow(title=_("Your name"))
        self.email = Adw.EntryRow(title=_("Email"), input_purpose=Gtk.InputPurpose.EMAIL)
        self.password = Adw.PasswordEntryRow(title=_("Password (at least 8 characters)"))
        self.confirm = Adw.PasswordEntryRow(title=_("Confirm the password"))
        for row in (self.name, self.email, self.password, self.confirm):
            row.connect("changed", lambda *_: self._validate())
            row.connect("entry-activated", lambda *_: self._create())
            group.add(row)
        form.append(group)
        strength_box = Gtk.Box(spacing=12)
        self.strength_bar = Gtk.LevelBar(min_value=0, max_value=4, hexpand=True, valign=Gtk.Align.CENTER)
        self.strength_bar.update_property([Gtk.AccessibleProperty.LABEL], [_("Password strength")])
        self.strength_label = label("", css=("caption", "dim-label"), wrap=False)
        strength_box.append(self.strength_bar)
        strength_box.append(self.strength_label)
        form.append(strength_box)
        self.hint = label("", css=("caption", "error"))
        self.hint.set_visible(False)
        form.append(self.hint)
        stats_group = Adw.PreferencesGroup()
        self.stats = Adw.SwitchRow(
            title=_("Show how many photos and videos you have on the dashboard"),
            subtitle=_("Creates a key that only reads statistics. Your password is not stored."),
            active=True,
        )
        self.stats.set_subtitle_lines(3)
        stats_group.add(self.stats)
        form.append(stats_group)
        browser = Gtk.Button(label=_("I prefer to create the account in the browser"), halign=Gtk.Align.CENTER)
        browser.add_css_class("flat")
        browser.connect("clicked", self._browser)
        form.append(browser)
        self.stack.add_named(form, "form")

        exists = StatusBlock(
            "avatar-default-symbolic",
            _("Your account already exists"),
            _(
                "We found the account from the previous installation. Use the same email and password "
                "in the phone app and on the website."
            ),
        )
        exists_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        self.connect_button = pill_button(_("Show photo count on the dashboard"), self._connect_stats)
        exists_box.append(self.connect_button)
        exists.set_child(exists_box)
        self.stack.add_named(exists, "exists")
        self.body.append(self.stack)

        self.create = Gtk.Button(label=_("Create account"), sensitive=False)
        self.create.add_css_class("suggested-action")
        self.create.connect("clicked", lambda *_: self._create())
        self.add_action(self.create, default=True)
        self.skip = Gtk.Button(label=_("Continue"), visible=False)
        self.skip.add_css_class("suggested-action")
        self.skip.connect("clicked", lambda *_: self.wizard.go("phone"))
        self.add_action(self.skip)
        self._busy = False

    def on_shown(self, first: bool) -> None:
        if first:
            self.stack.set_visible_child_name("loading")
            run_async(
                self.backend.is_initialized,
                on_done=self._initialized,
                on_error=lambda _e: self._initialized(False),
            )

    def _initialized(self, initialized: bool) -> None:
        if initialized:
            self.stack.set_visible_child_name("exists")
            self.create.set_visible(False)
            self.skip.set_visible(True)
            self.connect_button.set_visible(not self.backend.has_stats_key())
            self._default_button = self.skip
        else:
            self.stack.set_visible_child_name("form")
            self.name.grab_focus()

    def _validate(self) -> bool:
        name = self.name.get_text().strip()
        email = self.email.get_text().strip()
        password = self.password.get_text()
        again = self.confirm.get_text()
        strength = password_strength(password)
        self.strength_bar.set_value(strength.score)
        self.strength_label.set_text(strength.label)
        problems = []
        if email and not is_valid_email(email):
            self.email.add_css_class("error")
            problems.append(_("Check the email."))
        else:
            self.email.remove_css_class("error")
        if password and len(password) < 8:
            problems.append(_("The password needs at least 8 characters."))
        if again and again != password:
            self.confirm.add_css_class("error")
            problems.append(_("The passwords do not match."))
        else:
            self.confirm.remove_css_class("error")
        self.hint.set_text(" ".join(problems))
        self.hint.set_visible(bool(problems))
        ok = bool(name) and is_valid_email(email) and len(password) >= 8 and password == again
        self.create.set_sensitive(ok and not self._busy)
        return ok

    def _create(self) -> None:
        if self._busy or not self._validate():
            return
        self._busy = True
        self.create.set_sensitive(False)
        self.create.set_label(_("Creating…"))
        args = (
            self.name.get_text().strip(),
            self.email.get_text().strip(),
            self.password.get_text(),
            self.stats.get_active(),
            self.ctx.transcode,
            self.ctx.ml != "off",
        )

        def done(_result: object) -> None:
            self._busy = False
            self.password.set_text("")
            self.confirm.set_text("")
            self.toast(_("Account created!"))
            self.wizard.go("phone")

        def failed(exc: BaseException) -> None:
            self._busy = False
            self.create.set_label(_("Create account"))
            self._validate()
            message = exc.message if isinstance(exc, ApiError) else str(exc)
            dialog = Adw.AlertDialog(
                heading=_("Could not create the account"),
                body=_("The server responded: {msg}").format(msg=message)
                if isinstance(exc, ApiError) and exc.status
                else _("The server did not respond. Wait a few seconds and try again."),
            )
            dialog.add_response("ok", _("Close"))
            dialog.present(self.get_root())

        run_async(self.backend.create_admin, *args, on_done=done, on_error=failed)

    def _browser(self, button: Gtk.Button) -> None:
        open_uri(button, self.backend.local_url + "/auth/register")
        self.create.set_visible(False)
        self.skip.set_visible(True)

    def _connect_stats(self, _button: Gtk.Button) -> None:
        dialog = ConnectStatsDialog(self.backend, on_done=lambda: self.connect_button.set_visible(False))
        dialog.present(self.get_root())


# --- 7. Celular -------------------------------------------------------------------------------------


class PhonePage(WizardPage):
    step = 5

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Phone"), "phone")
        self.set_header_title(_("Phone"))
        self.body.append(PhoneView(self.backend))
        done = Gtk.Button(label=_("Finish"))
        done.add_css_class("suggested-action")
        done.connect("clicked", lambda *_: self.wizard.go_replace("done"))
        self.add_action(done, default=True)


# --- 8. Celebração ------------------------------------------------------------------------------------


class DonePage(WizardPage):
    step = None

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Ready"), "done", can_pop=False)
        self.header.set_show_title(False)
        self.actions.set_visible(False)
        self.body.set_valign(Gtk.Align.CENTER)
        self.body.set_spacing(16)
        self.body.append(illustration("nuvem-ruscher-done", 280))
        title = label(_("Your cloud is up!"), css=("hero-title",), xalign=0.5)
        title.set_accessible_role(Gtk.AccessibleRole.HEADING)
        self.body.append(title)
        self.body.append(
            label(
                _(
                    "Open the Immich app on the phone and the photos start arriving. This computer takes "
                    "care of the rest."
                ),
                css=("lead", "dim-label"),
                xalign=0.5,
            )
        )
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=12)
        open_button = pill_button(_("Open Immich"), lambda b: open_uri(b, self.backend.local_url), suggested=True)
        panel = pill_button(_("Go to the dashboard"), lambda *_: self.wizard.finish())
        buttons.append(open_button)
        buttons.append(panel)
        self.body.append(buttons)
        self._default_button = open_button
        self.confetti = Confetti()
        self.toolbar.set_content(None)
        overlay = Gtk.Overlay(child=self.scroller)
        overlay.add_overlay(self.confetti)
        self.toolbar.set_content(overlay)

    def on_shown(self, first: bool) -> None:
        self.backend.state_set("wizard_done", True)
        if first:
            GLib.timeout_add(250, lambda: self.confetti.burst() or False)
