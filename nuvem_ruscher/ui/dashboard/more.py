"""Mais: acesso fora de casa, disco, firewall, detalhes e desinstalação."""

from __future__ import annotations

import os
from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.async_utils import run_async
from nuvem_ruscher.backend.base import Backend, HelperResult, StorageReport
from nuvem_ruscher.constants import CONF_FILE, IMMICH_PORT, SERVICE_NAME, TAILSCALE_DOWNLOAD_URL
from nuvem_ruscher.core.system import TailscaleInfo
from nuvem_ruscher.i18n import _
from nuvem_ruscher.ui.common import (
    confirm,
    copy_text,
    icon_button,
    open_folder,
    open_uri,
    show_error,
    status_icon,
    toast,
)
from nuvem_ruscher.ui.dashboard.monitor import ServerMonitor


class MorePage(Gtk.Box):
    def __init__(
        self,
        backend: Backend,
        monitor: ServerMonitor,
        show_phone_away: Callable[[], None],
        on_uninstalled: Callable[[], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.backend = backend
        self.monitor = monitor
        self.show_phone_away = show_phone_away
        self.on_uninstalled = on_uninstalled
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        body.set_margin_top(24)
        body.set_margin_bottom(24)
        body.set_margin_start(16)
        body.set_margin_end(16)
        scroller.set_child(Adw.Clamp(maximum_size=760, child=body))
        self.append(scroller)

        # Acesso fora de casa
        self.away = Adw.PreferencesGroup(
            title=_("Acesso fora de casa"),
            description=_("Com o Tailscale (gratuito), o celular envia fotos de qualquer lugar, com segurança."),
        )
        self.away_row = Adw.ActionRow(title=_("Verificando o Tailscale…"))
        self.away_row.set_subtitle_lines(4)
        self.away_icon = status_icon("pending")
        self.away_row.add_prefix(self.away_icon)
        self.away_suffix = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.away_row.add_suffix(self.away_suffix)
        self.away.add(self.away_row)
        body.append(self.away)

        # Disco
        self.disk = Adw.PreferencesGroup(title=_("Disco das fotos"))
        self.boot = Adw.SwitchRow(
            title=_("Ligar o disco junto com o computador"),
            subtitle=_("O servidor funciona logo depois de reiniciar, mesmo antes de você entrar."),
            sensitive=False,
        )
        self.boot.set_subtitle_lines(3)
        self._boot_handler = self.boot.connect("notify::active", self._toggle_boot)
        self.disk.add(self.boot)
        self.folder = Adw.ActionRow(title=_("Pasta das fotos"))
        self.folder.set_subtitle_selectable(True)
        self.folder.add_suffix(icon_button("folder-open-symbolic", _("Abrir a pasta das fotos"), self._open_folder))
        self.disk.add(self.folder)
        body.append(self.disk)

        # Firewall
        self.firewall = Adw.PreferencesGroup(title=_("Rede"), visible=False)
        fw = Adw.ActionRow(
            title=_("Liberar a porta {p} no firewall").format(p=IMMICH_PORT),
            subtitle=_("Só para redes de casa e Tailscale. Use se o celular não encontrar o servidor."),
        )
        fw.set_subtitle_lines(3)
        fw_button = Gtk.Button(label=_("Liberar"), valign=Gtk.Align.CENTER)
        fw_button.connect("clicked", self._firewall)
        fw.add_suffix(fw_button)
        self.firewall.add(fw)
        body.append(self.firewall)

        # Detalhes técnicos
        tech = Adw.PreferencesGroup(title=_("Detalhes técnicos"))
        for title, value in (
            (_("Serviço do sistema"), SERVICE_NAME),
            (_("Configuração"), CONF_FILE),
            (_("Registros do serviço"), f"journalctl -u {SERVICE_NAME}"),
        ):
            row = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(value))
            row.set_subtitle_selectable(True)
            row.add_css_class("property")
            tech.add(row)
        body.append(tech)

        # Desinstalar
        danger = Adw.PreferencesGroup(title=_("Remover"))
        row = Adw.ActionRow(
            title=_("Desinstalar o servidor"),
            subtitle=_("Remove o Immich deste computador. Suas fotos e vídeos não são apagados."),
        )
        row.set_subtitle_lines(3)
        button = Gtk.Button(label=_("Desinstalar…"), valign=Gtk.Align.CENTER)
        button.add_css_class("destructive-action")
        button.connect("clicked", self._ask_uninstall)
        row.add_suffix(button)
        danger.add(row)
        body.append(danger)
        self._report: StorageReport | None = None

    def refresh(self) -> None:
        conf = self.monitor.conf
        self.folder.set_subtitle(GLib.markup_escape_text(conf.upload_location or "—"))
        run_async(self.backend.tailscale, on_done=self._show_tailscale)
        run_async(self.backend.fact_firewall, on_done=lambda name: self.firewall.set_visible(bool(name)))
        if conf.upload_location:
            run_async(self.backend.inspect_storage, conf.upload_location, on_done=self._show_storage)

    # --- Tailscale ---------------------------------------------------------------------------
    def _show_tailscale(self, info: TailscaleInfo) -> None:
        while (child := self.away_suffix.get_first_child()) is not None:
            self.away_suffix.remove(child)
        if not info.installed:
            self._away(
                "info",
                _("O Tailscale não está instalado"),
                _(
                    "Instale pela loja de programas (pacote “tailscale”), entre na sua conta e "
                    "instale também o app Tailscale no celular."
                ),
            )
            more = Gtk.Button(label=_("Saiba mais"))
            more.connect("clicked", lambda b: open_uri(b, TAILSCALE_DOWNLOAD_URL))
            self.away_suffix.append(more)
        elif not info.running or not info.ip:
            self._away(
                "warning",
                _("O Tailscale está desligado"),
                _("Ligue o Tailscale neste computador (“sudo tailscale up”) e entre na sua conta."),
            )
        else:
            host = info.dns_name or info.ip
            url = f"http://{host}:{IMMICH_PORT}"
            self._away("ok", _("Pronto para usar fora de casa"), url)
            self.away_suffix.append(
                icon_button(
                    "edit-copy-symbolic",
                    _("Copiar endereço"),
                    lambda b: (copy_text(b, url), toast(b, _("Endereço copiado"))),
                )
            )
            qr = Gtk.Button(label=_("Mostrar QR"))
            qr.connect("clicked", lambda *_: self.show_phone_away())
            self.away_suffix.append(qr)

    def _away(self, status: str, title: str, subtitle: str) -> None:
        from nuvem_ruscher.ui.common import set_status_icon

        set_status_icon(self.away_icon, status)
        self.away_row.set_title(GLib.markup_escape_text(title))
        self.away_row.set_subtitle(GLib.markup_escape_text(subtitle))

    # --- Disco ---------------------------------------------------------------------------------
    def _show_storage(self, report: StorageReport) -> None:
        self._report = report
        volume = report.volume
        self.boot.handler_block(self._boot_handler)
        if volume is None or not volume.needs_boot_mount:
            self.boot.set_visible(volume is None)
            self.boot.set_sensitive(False)
            if volume is None:
                self.boot.set_subtitle(_("Conecte o disco das fotos para ver esta opção."))
        elif report.fstab_state == "foreign":
            self.boot.set_active(True)
            self.boot.set_sensitive(False)
            self.boot.set_subtitle(_("Já configurado no sistema (/etc/fstab), fora do Nuvem Ruscher."))
        elif report.fstab_state == "unsupported":
            self.boot.set_active(False)
            self.boot.set_sensitive(False)
            self.boot.set_subtitle(_("Este tipo de disco não pode ligar automaticamente."))
        else:
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
                    toast(self, _("Pronto!") if enable else _("Montagem automática desligada"))
                    self.refresh()
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
                _("Desligar a montagem automática?"),
                _(
                    "Depois de reiniciar, o servidor só vai ligar quando você entrar na sessão e o disco aparecer. "
                    "Apenas a linha criada pelo Nuvem Ruscher sai do /etc/fstab (com cópia de segurança)."
                ),
                _("Desligar"),
                run,
            )
            dialog.connect("response", lambda _d, r: revert() if r != "confirm" else None)

    def _open_folder(self, button: Gtk.Button) -> None:
        path = self.monitor.conf.upload_location
        if path and os.path.isdir(path):
            open_folder(button, path)

    def _firewall(self, _button: Gtk.Button) -> None:
        def done(result: HelperResult) -> None:
            if result.ok:
                self.backend.state_set("firewall_allowed", True)
                toast(self, _("Porta liberada para a rede de casa"))
            else:
                show_error(self, result.error_code, result.error_detail, result.log)

        self.backend.helper("firewall-allow", [], None, done)

    # --- Desinstalar -----------------------------------------------------------------------------
    def _ask_uninstall(self, _button: Gtk.Button) -> None:
        conf = self.monitor.conf
        images = Gtk.CheckButton(label=_("Apagar também os componentes baixados (libera cerca de 5 GB)"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(images)
        body = _(
            "Suas fotos e vídeos continuam em <b>{photos}</b>, intactos.\n\n"
            "O banco de dados (álbuns, pessoas, favoritos) fica guardado em <b>{db}</b> para uma futura "
            "reinstalação reaproveitar tudo."
        ).format(
            photos=GLib.markup_escape_text(conf.upload_location or "—"),
            db=GLib.markup_escape_text(conf.db_data_location or "/var/lib/nuvem-ruscher"),
        )
        confirm(
            self,
            _("Remover o servidor do Immich?"),
            body,
            _("Remover servidor"),
            lambda: self._uninstall(images.get_active()),
            destructive=True,
            extra=box,
            body_markup=True,
        )

    def _uninstall(self, remove_images: bool) -> None:
        def done(result: HelperResult) -> None:
            if result.ok:
                self.backend.state_set("wizard_done", False)
                self.backend.state_set("install_step", "")
                toast(
                    self,
                    _("Servidor removido. Suas fotos continuam no disco."),
                )
                self.on_uninstalled()
            else:
                show_error(self, result.error_code, result.error_detail, result.log)

        toast(self, _("Removendo o servidor…"))
        self.monitor.stop()
        self.backend.helper("uninstall", ["--remove-images"] if remove_images else [], None, done)
