"""Visão geral: status ao vivo, ações principais, números e componentes."""

from __future__ import annotations

import os
from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.backend.base import Backend, HelperResult
from nuvem_ruscher.constants import CONTAINERS
from nuvem_ruscher.core.docker import Health, container_description, container_label
from nuvem_ruscher.core.storage import human_size
from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.common import icon_button, label, open_folder, open_uri, show_error
from nuvem_ruscher.ui.dashboard.monitor import ServerMonitor
from nuvem_ruscher.ui.dialogs import ConnectStatsDialog

DOT_CLASSES = ("ok", "busy", "warning", "stopped")
PILL_CLASSES = ("ok", "busy", "warning", "error", "stopped")


def _set_class(widget: Gtk.Widget, value: str, options: tuple[str, ...]) -> None:
    for option in options:
        widget.remove_css_class(option)
    widget.add_css_class(value)


def thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


class StatCard(Gtk.Box):
    def __init__(self, title: str, icon: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, width_request=180)
        self.add_css_class("card")
        self.add_css_class("stat-card")
        top = Gtk.Box(spacing=8)
        image = Gtk.Image.new_from_icon_name(icon)
        image.add_css_class("dim-label")
        image.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        top.append(image)
        top.append(label(title, css=("dim-label", "caption-heading"), wrap=False))
        self.append(top)
        self.value = label("—", css=("stat-value", "numeric"), wrap=False)
        self.append(self.value)
        self.note = label("", css=("caption", "dim-label", "numeric"))
        self.append(self.note)

    def set(self, value: str, note: str = "") -> None:
        self.value.set_text(value)
        self.note.set_text(note)
        self.note.set_visible(bool(note))


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
                text, cls = _("saudável"), "ok"
            elif health is Health.STARTING:
                text, cls = _("iniciando"), "busy"
            else:
                text, cls = _("com problema"), "error"
        elif state == "restarting":
            text, cls = _("reiniciando"), "warning"
        elif state == "missing":
            text, cls = _("não criado"), "stopped"
        else:
            text, cls = _("parado"), "stopped"
        self.pill.set_text(text)
        _set_class(self.pill, cls, PILL_CLASSES)
        if cpu is not None and mem is not None and state == "running":
            self.metrics.set_text(
                _("CPU {cpu}% · RAM {mem}").format(cpu=f"{cpu:.1f}".replace(".", ","), mem=human_size(mem, binary=True))
            )
        else:
            self.metrics.set_text("")


class OverviewPage(Gtk.Box):
    def __init__(self, backend: Backend, monitor: ServerMonitor, go_phone: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.backend = backend
        self.monitor = monitor

        self.banner = Adw.Banner(revealed=False)
        self.banner.connect("button-clicked", self._banner_clicked)
        self.append(self.banner)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        for margin in ("top", "bottom"):
            getattr(body, f"set_margin_{margin}")(24)
        body.set_margin_start(16)
        body.set_margin_end(16)
        scroller.set_child(Adw.Clamp(maximum_size=880, tightening_threshold=600, child=body))
        self.append(scroller)

        # Cartão principal
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        hero.add_css_class("card")
        hero.add_css_class("hero-card")
        top = Gtk.Box(spacing=16)
        self.dot = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        self.dot.add_css_class("status-dot")
        self.dot.set_margin_start(6)
        self.dot.set_margin_end(4)
        top.append(self.dot)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self.title = label(_("Carregando…"), css=("title-2",))
        self.title.set_accessible_role(Gtk.AccessibleRole.HEADING)
        self.subtitle = label("", css=("dim-label",))
        texts.append(self.title)
        texts.append(self.subtitle)
        top.append(texts)
        hero.append(top)
        buttons = Adw.WrapBox(child_spacing=8, line_spacing=8)
        self.open_button = Gtk.Button(label=_("Abrir o Immich"))
        self.open_button.add_css_class("pill")
        self.open_button.add_css_class("suggested-action")
        self.open_button.connect("clicked", lambda b: open_uri(b, backend.local_url))
        self.power = Gtk.Button()
        self.power.add_css_class("pill")
        self.power.connect("clicked", self._power)
        self.restart = Gtk.Button(label=_("Reiniciar"))
        self.restart.add_css_class("pill")
        self.restart.connect("clicked", lambda *_: self._service("restart"))
        phone = Gtk.Button(label=_("Conectar celular"))
        phone.add_css_class("pill")
        phone.connect("clicked", lambda *_: go_phone())
        for button in (self.open_button, self.power, self.restart, phone):
            buttons.append(button)
        hero.append(buttons)
        body.append(hero)

        # Números
        cards = Adw.WrapBox(child_spacing=12, line_spacing=12)
        self.photos = StatCard(_("Fotos"), "camera-photo-symbolic")
        self.videos = StatCard(_("Vídeos"), "camera-video-symbolic")
        self.disk = StatCard(_("Disco das fotos"), "drive-harddisk-symbolic")
        self.disk_bar = Gtk.LevelBar(min_value=0, max_value=1)
        for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            self.disk_bar.remove_offset_value(offset)
        self.disk_bar.set_margin_top(4)
        self.disk.append(self.disk_bar)
        self.disk.set_size_request(260, -1)
        for card in (self.photos, self.videos, self.disk):
            cards.append(card)
        body.append(cards)
        self.connect_stats = Gtk.Button(label=_("Mostrar contagem de fotos"), halign=Gtk.Align.START, visible=False)
        self.connect_stats.add_css_class("flat")
        self.connect_stats.connect("clicked", self._connect_stats)
        body.append(self.connect_stats)

        # Componentes
        group = Adw.PreferencesGroup(
            title=_("Componentes"), description=_("As quatro partes do Immich, cada uma em seu container.")
        )
        self.rows = {name: ContainerRow(name) for name in CONTAINERS}
        for row in self.rows.values():
            group.add(row)
        body.append(group)

        # Onde estão os dados
        data = Adw.PreferencesGroup(title=_("Onde estão seus dados"))
        self.photos_row = Adw.ActionRow(title=_("Fotos e vídeos"))
        self.photos_row.set_subtitle_selectable(True)
        self.photos_row.add_suffix(icon_button("folder-open-symbolic", _("Abrir a pasta das fotos"), self._open_photos))
        self.db_row = Adw.ActionRow(title=_("Banco de dados (álbuns, pessoas, informações)"))
        self.db_row.set_subtitle_selectable(True)
        self.version_row = Adw.ActionRow(title=_("Versão do Immich"))
        for row in (self.photos_row, self.db_row, self.version_row):
            data.add(row)
        body.append(data)

        monitor.connect("changed", lambda *_: self.update())
        monitor.connect("stats-changed", lambda *_: self.update_rows())
        self.update()

    # --- atualização -----------------------------------------------------------------------
    def update(self) -> None:
        m = self.monitor
        overall = m.overall
        url = self.backend.server_url()
        texts = {
            "loading": (_("Carregando…"), "", "stopped"),
            "ok": (_("Seu servidor está no ar"), url, "ok"),
            "starting": (_("Ligando o servidor…"), _("Isso leva cerca de um minuto."), "busy"),
            "stopping": (_("Desligando…"), "", "busy"),
            "stopped": (
                _("O servidor está desligado"),
                _("Ligue para o celular voltar a enviar fotos."),
                "stopped",
            ),
            "problem": (
                _("O servidor está com problemas"),
                _("Veja os registros ou tente reiniciar."),
                "warning",
            ),
            "failed": (
                _("O servidor não conseguiu ligar"),
                _("Veja os registros ou tente de novo."),
                "warning",
            ),
            "disk-missing": (
                _("O disco das fotos não está conectado"),
                _("Conecte o disco e o servidor liga sozinho."),
                "warning",
            ),
        }
        title, subtitle, dot = texts[overall]
        self.title.set_text(title)
        self.subtitle.set_text(subtitle)
        _set_class(self.dot, dot, DOT_CLASSES)
        busy = bool(m.busy_action)
        running = overall in ("ok", "starting", "problem")
        self.power.set_label(_("Desligar") if running else _("Ligar"))
        self.power.set_sensitive(not busy and overall not in ("loading", "disk-missing"))
        if running:
            self.power.remove_css_class("suggested-action")
        else:
            self.power.add_css_class("suggested-action")
        self.restart.set_sensitive(not busy and running)
        self.open_button.set_visible(overall == "ok")

        # Banner
        if overall == "disk-missing":
            disk = os.path.basename(m.conf.mount_point) or _("das fotos")
            self.banner.set_title(_("O disco “{disk}” não está conectado.").format(disk=disk))
            self.banner.set_button_label(None)
            self.banner.set_revealed(True)
        elif overall in ("stopped", "failed"):
            self.banner.set_title(_("O servidor está desligado. Suas fotos não estão sendo copiadas."))
            self.banner.set_button_label(_("Ligar"))
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

        # Números
        if m.statistics is not None:
            self.photos.set(thousands(m.statistics.photos))
            self.videos.set(
                thousands(m.statistics.videos),
                _("{size} no total").format(size=human_size(m.statistics.usage)),
            )
            self.connect_stats.set_visible(False)
        else:
            self.photos.set("—", _("Disponível com o servidor ligado"))
            self.videos.set("—")
            self.connect_stats.set_visible(not self.backend.has_stats_key() and overall == "ok")
        total, used, free = m.disk
        if total:
            self.disk.set(human_size(free), _("livres de {total}").format(total=human_size(total)))
            self.disk_bar.set_value(used / total)
        else:
            self.disk.set("—", _("Disco não encontrado"))
            self.disk_bar.set_value(0)

        conf = m.conf
        self.photos_row.set_subtitle(GLib.markup_escape_text(conf.upload_location or "—"))
        self.db_row.set_subtitle(GLib.markup_escape_text(conf.db_data_location or "—"))
        self.version_row.set_subtitle(conf.immich_version or "—")
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

    # --- ações -------------------------------------------------------------------------------
    def _power(self, _button: Gtk.Button) -> None:
        running = self.monitor.overall in ("ok", "starting", "problem")
        self._service("stop" if running else "start")

    def _banner_clicked(self, _banner: Adw.Banner) -> None:
        self._service("start")

    def _service(self, action: str) -> None:
        self.monitor.busy_action = action
        self.update()

        def done(result: HelperResult) -> None:
            self.monitor.busy_action = ""
            self.monitor.refresh()
            root = self.get_root()
            if result.ok:
                messages = {
                    "start": _("Ligando o servidor…"),
                    "stop": _("Servidor desligado"),
                    "restart": _("Reiniciando…"),
                }
                if root is not None and hasattr(root, "toast"):
                    root.toast(messages[action])
            else:
                self.update()
                show_error(
                    self,
                    result.error_code,
                    result.error_detail,
                    result.log,
                    retry=lambda: self._service(action),
                )

        self.backend.helper(action, [], None, done)

    def _open_photos(self, button: Gtk.Button) -> None:
        path = self.monitor.conf.upload_location
        if path and os.path.isdir(path):
            open_folder(button, path)

    def _connect_stats(self, _button: Gtk.Button) -> None:
        dialog = ConnectStatsDialog(self.backend, on_done=self.monitor.refresh_statistics)
        dialog.present(self.get_root())
