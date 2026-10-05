"""Sistema: componentes do servidor, detalhes técnicos e desinstalação."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher import APP_NAME, VERSION
from nuvem_ruscher.backend.base import HelperResult
from nuvem_ruscher.constants import CONF_FILE, CONTAINERS, SERVICE_NAME, STACK_DIR
from nuvem_ruscher.core import numbers
from nuvem_ruscher.core.docker import Health, container_description, container_label
from nuvem_ruscher.core.storage import human_size
from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.common import confirm, label, show_error, toast
from nuvem_ruscher.ui.flow import BUSY
from nuvem_ruscher.ui.page import Page, advanced_expander, group

if TYPE_CHECKING:
    from nuvem_ruscher.ui.shell import AppContext

PILL_CLASSES = ("ok", "busy", "warning", "error", "stopped")


class ContainerRow(Adw.ActionRow):
    def __init__(self, name: str) -> None:
        super().__init__(title=container_label(name), subtitle=container_description(name))
        self.name = name
        self.metrics = label("", css=("caption", "dim-label", "numeric"), wrap=False)
        self.metrics.set_valign(Gtk.Align.CENTER)
        self.pill = label("…", css=("pill", "stopped"), wrap=False)
        self.pill.set_valign(Gtk.Align.CENTER)
        self.add_suffix(self.metrics)
        self.add_suffix(self.pill)

    def update(self, state: str, health: Health | None, cpu: float | None, mem: int | None) -> None:
        if state == "running":
            if health in (Health.HEALTHY, Health.NONE):
                text, cls = _("healthy"), "ok"
            elif health is Health.STARTING:
                text, cls = _("starting"), "busy"
            else:
                text, cls = _("unhealthy"), "error"
        elif state == "restarting":
            text, cls = _("restarting"), "warning"
        elif state == "missing":
            text, cls = _("not created"), "stopped"
        else:
            text, cls = _("stopped"), "stopped"
        self.pill.set_text(text)
        for option in PILL_CLASSES:
            self.pill.remove_css_class(option)
        self.pill.add_css_class(cls)
        if cpu is not None and mem is not None and state == "running":
            self.metrics.set_text(
                _("CPU {cpu}% · RAM {mem}").format(cpu=numbers.decimal(cpu), mem=human_size(mem, binary=True))
            )
        else:
            self.metrics.set_text("")


class SystemPage(Page):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            _("System"),
            _("The parts that make up the server and the technical details, for when you need them."),
            "preferences-system-symbolic",
            "slate",
        )
        self.ctx = ctx
        self.backend = ctx.backend
        self.monitor = ctx.monitor

        components = group(_("Components"), _("The four parts of Immich, each in its own container."))
        restart = Gtk.Button(label=_("Restart server"), valign=Gtk.Align.CENTER)
        restart.add_css_class("flat")
        restart.connect("clicked", self._restart)
        components.set_header_suffix(restart)
        self.restart_button = restart
        self.rows = {name: ContainerRow(name) for name in CONTAINERS}
        for row in self.rows.values():
            components.add(row)
        self.add(components)

        about = group(_("Versions"))
        self.immich_row = Adw.ActionRow(title="Immich", subtitle="—")
        self.immich_row.add_css_class("property")
        app_row = Adw.ActionRow(title=APP_NAME, subtitle=VERSION)
        app_row.add_css_class("property")
        about.add(self.immich_row)
        about.add(app_row)
        self.add(about)

        tech = group()
        details = advanced_expander(_("Technical details"), _("Service, configuration and data folders"))
        self.detail_rows: dict[str, Adw.ActionRow] = {}
        for key, title, value in (
            ("service", _("System service"), SERVICE_NAME),
            ("config", _("Configuration"), CONF_FILE),
            ("stack", _("Server files (Docker Compose)"), STACK_DIR),
            ("database", _("Database"), ""),
            ("photos", _("Photos and videos"), ""),
            ("journal", _("Service logs"), f"journalctl -u {SERVICE_NAME}"),
        ):
            row = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(value or "—"))
            row.set_subtitle_selectable(True)
            row.add_css_class("property")
            details.add_row(row)
            self.detail_rows[key] = row
        tech.add(details)
        self.add(tech)

        danger = group(_("Remove"))
        row = Adw.ActionRow(
            title=_("Uninstall the server"),
            subtitle=_("Removes Immich from this computer. Your photos and videos are not deleted."),
        )
        row.set_subtitle_lines(3)
        button = Gtk.Button(label=_("Uninstall…"), valign=Gtk.Align.CENTER)
        button.add_css_class("destructive-action")
        button.connect("clicked", self._ask_uninstall)
        row.add_suffix(button)
        danger.add(row)
        self.add(danger)

        self.monitor.connect("changed", lambda *_: self.update())
        self.monitor.connect("stats-changed", lambda *_: self.update_rows())

    def on_shown(self) -> None:
        self.update()

    def update(self) -> None:
        conf = self.monitor.conf
        self.immich_row.set_subtitle(conf.immich_version or "—")
        self.detail_rows["database"].set_subtitle(GLib.markup_escape_text(conf.db_data_location or "—"))
        self.detail_rows["photos"].set_subtitle(GLib.markup_escape_text(conf.upload_location or "—"))
        running = self.monitor.overall in ("ok", "starting", "problem")
        self.restart_button.set_sensitive(running and not self.monitor.busy_action)
        self.update_rows()

    def update_rows(self) -> None:
        states = {c.name: c for c in self.monitor.containers}
        for name, row in self.rows.items():
            c = states.get(name)
            stat = self.monitor.stats.get(name)
            row.update(
                c.state if c else "missing",
                c.health if c else None,
                stat.cpu_percent if stat else None,
                stat.memory_bytes if stat else None,
            )

    def _restart(self, _button: Gtk.Button) -> None:
        self.monitor.busy_action = "restart"
        self.update()

        def done(result: HelperResult) -> None:
            self.monitor.busy_action = ""
            self.monitor.refresh()
            if result.ok:
                toast(self, _("Restarting…"))
            else:
                show_error(self, result.error_code, result.error_detail, result.log)

        self.backend.helper("restart", [], None, done)

    def _ask_uninstall(self, button: Gtk.Button) -> None:
        conf = self.monitor.conf
        images = Gtk.CheckButton(label=_("Also delete the downloaded components (frees about 5 GB)"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(images)
        body = _(
            "Your photos and videos stay in <b>{photos}</b>, untouched.\n\nThe database (albums, "
            "people, favorites) is kept in <b>{db}</b> so a future reinstallation can reuse "
            "everything."
        ).format(
            photos=GLib.markup_escape_text(conf.upload_location or "—"),
            db=GLib.markup_escape_text(conf.db_data_location or "/var/lib/nuvem-ruscher"),
        )
        confirm(
            self,
            _("Remove the Immich server?"),
            body,
            _("Remove server"),
            lambda: self._uninstall(button, images.get_active()),
            destructive=True,
            extra=box,
            body_markup=True,
        )

    def _uninstall(self, button: Gtk.Button, remove_images: bool) -> None:
        def done(result: HelperResult) -> None:
            BUSY.discard(self)
            button.set_sensitive(True)
            if result.ok:
                self.backend.state_set("wizard_done", False)
                self.backend.state_set("install_step", "")
                toast(self, _("Server removed. Your photos are still on the disk."))
                self.ctx.on_uninstalled()
            else:
                # Nada foi removido (ou a senha foi cancelada): o painel volta a acompanhar.
                self.monitor.start()
                show_error(self, result.error_code, result.error_detail, result.log)

        if self in BUSY:
            return
        button.set_sensitive(False)
        BUSY.add(self)
        toast(self, _("Removing the server…"))
        self.monitor.stop()
        self.backend.helper("uninstall", ["--remove-images"] if remove_images else [], None, done)
