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
from nuvem_ruscher.core.releases import Release, br_date
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
        super().__init__(wizard, _("Bem-vindo"), "welcome")
        self.header.set_show_title(False)
        self.actions.set_visible(False)
        self.body.set_valign(Gtk.Align.CENTER)
        self.body.set_spacing(18)
        self.body.append(illustration("nuvem-ruscher-welcome", 300))
        title = label(_("Suas fotos, na sua casa."), css=("hero-title",), xalign=0.5)
        title.set_accessible_role(Gtk.AccessibleRole.HEADING)
        self.body.append(title)
        self.body.append(
            label(
                _(
                    "Vamos transformar este computador num “Google Fotos” só seu, com o Immich. "
                    "Leva poucos minutos, e nada do que já está nos seus discos será apagado."
                ),
                css=("lead", "dim-label"),
                xalign=0.5,
            )
        )
        start = pill_button(_("Começar"), lambda *_: self.wizard.go("checks"), suggested=True)
        start.set_margin_top(12)
        self._default_button = start
        self.body.append(start)
        more = Gtk.Button(label=_("O que vai ser instalado?"), halign=Gtk.Align.CENTER)
        more.add_css_class("flat")
        more.connect("clicked", self._explain)
        self.body.append(more)

    def _explain(self, button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(
            heading=_("O que o Nuvem Ruscher faz"),
            body=_(
                "• Instala o Docker, se faltar, e roda o Immich oficial dentro dele.\n"
                "• Guarda as fotos na pasta que você escolher (nada é apagado ou movido).\n"
                "• Guarda o banco de dados no disco interno, como recomenda o Immich.\n"
                "• Registra um serviço que liga o servidor só quando o disco das fotos está presente.\n"
                "• Pede sua senha de administrador apenas para as etapas que mexem no sistema."
            ),
        )
        dialog.add_response("ok", _("Entendi"))
        dialog.present(self.get_root())


# --- 2. Verificação ------------------------------------------------------------------------

CHECK_PLACEHOLDERS = {
    "docker_installed": N_("Docker instalado"),
    "docker_running": N_("Docker ligado"),
    "docker_group": N_("Permissão para usar o Docker"),
    "memory": N_("Memória"),
    "cpu": N_("Processador"),
    "disk_system": N_("Espaço no disco do sistema"),
    "port": N_("Porta 2283 livre"),
    "internet": N_("Conexão com a internet"),
    "firewall": N_("Firewall"),
}


class ChecksPage(WizardPage):
    step = 0

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Verificação"), "checks")
        self.set_header_title(_("Verificação"))
        self.body.append(
            page_heading(
                _("Preparando o terreno"),
                _("Conferimos se este computador tem tudo o que o servidor de fotos precisa."),
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

        self.again = Gtk.Button(label=_("Verificar de novo"))
        self.again.connect("clicked", lambda *_: self.run_checks())
        self.add_action(self.again, start=True)
        self.next = Gtk.Button(label=_("Continuar"), sensitive=False)
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
        self.summary.set_text(_("Verificando…"))
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
            self.summary.set_text(
                _("Resolva os itens marcados para continuar. Cada um tem um botão que faz isso por você.")
            )
        else:
            self.summary.set_text(_("Tudo certo! Pode continuar."))

    def _apply_fix(self, fix: Fix) -> None:
        if self._busy:
            return
        self._busy = True
        for row in self.rows.values():
            row.fix_button.set_sensitive(False)
        self.again.set_sensitive(False)
        self.summary.set_text(_("Aplicando a correção… (pode ser pedida a senha de administrador)"))

        def done(result: HelperResult) -> None:
            self._busy = False
            for row in self.rows.values():
                row.fix_button.set_sensitive(True)
            if result.ok:
                if fix.action == "firewall-allow":
                    self.backend.state_set("firewall_allowed", True)
                self.toast(_("Pronto!"))
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
        super().__init__(wizard, _("Armazenamento"), "storage")
        self.set_header_title(_("Armazenamento"))
        self.body.append(
            page_heading(
                _("Onde suas fotos vão morar"),
                _("Escolhemos o disco com mais espaço. Você pode trocar se quiser."),
            )
        )
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=36)
        spinner = Adw.Spinner()
        spinner.set_size_request(32, 32)
        loading.append(spinner)
        loading.append(label(_("Procurando o disco…"), css=("dim-label",), xalign=0.5))
        self.stack.add_named(loading, "loading")
        self.missing = StatusBlock("drive-harddisk-usb-symbolic")
        retry = pill_button(_("Procurar de novo"), lambda *_: self.inspect(self.ctx.photo_path), suggested=True)
        self.missing.set_child(retry)
        self.stack.add_named(self.missing, "missing")
        self.ready = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.stack.add_named(self.ready, "ready")
        self.body.append(self.stack)

        choose = Gtk.Button(label=_("Escolher outra pasta…"))
        choose.connect("clicked", self._choose)
        self.add_action(choose, start=True)
        self.next = Gtk.Button(label=_("Continuar"), sensitive=False)
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
            self.missing.set_title(_("Essa pasta não serve"))
            self.missing.set_description(report.error)
            self.stack.set_visible_child_name("missing")
            return
        if report.disk_missing or report.volume is None:
            self.missing.set_icon_name("drive-harddisk-usb-symbolic")
            self.missing.set_title(_("O disco não está conectado"))
            self.missing.set_description(
                _("Não encontramos {path}. Conecte o disco (ou escolha outra pasta) e procure de novo.").format(
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
            _("Disco externo USB")
            if volume.transport == "usb"
            else (_("Disco do sistema") if volume.is_system_disk else _("Disco interno"))
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
        bar.update_property([Gtk.AccessibleProperty.LABEL], [_("Espaço usado no disco")])
        info.append(bar)
        info.append(
            label(
                _("{free} livres de {total}").format(free=human_size(volume.available), total=human_size(volume.size)),
                css=("caption", "numeric"),
            )
        )
        card.append(info)
        self.ready.append(card)

        folder = Adw.PreferencesGroup()
        path_row = Adw.ActionRow(title=_("Pasta das fotos"), subtitle=GLib.markup_escape_text(report.path))
        path_row.set_subtitle_selectable(True)
        path_row.add_prefix(Gtk.Image.new_from_icon_name("folder-pictures-symbolic"))
        if os.path.isdir(report.path):
            open_button = Gtk.Button.new_from_icon_name("folder-open-symbolic")
            open_button.set_tooltip_text(_("Abrir a pasta"))
            open_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Abrir a pasta")])
            open_button.add_css_class("flat")
            open_button.set_valign(Gtk.Align.CENTER)
            open_button.connect("clicked", lambda b: open_folder(b, report.path))
            path_row.add_suffix(open_button)
        folder.add(path_row)
        if report.library and report.library.exists:
            lib_row = Adw.ActionRow(
                title=_("Encontramos fotos de uma instalação anterior"),
                subtitle=_("Elas serão reaproveitadas — nada será apagado."),
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
                title=_("Depois de reiniciar"),
                description=_(
                    "Este disco hoje só aparece quando você entra na sessão. Sem a opção abaixo, "
                    "o servidor liga sozinho assim que você entrar e o disco aparecer."
                ),
            )
            if report.fstab_state == "none":
                self.boot_switch = Adw.SwitchRow(
                    title=_("Ligar o disco junto com o computador (recomendado)"),
                    subtitle=_(
                        "O servidor funciona logo depois de reiniciar, mesmo antes de você entrar. "
                        "O disco continua aparecendo no mesmo lugar. Se ele não estiver conectado, "
                        "o computador liga normalmente."
                    ),
                )
                self.boot_switch.set_subtitle_lines(5)
                boot.add(self.boot_switch)
                tech = Adw.ExpanderRow(title=_("Detalhes técnicos"))
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                for margin in ("top", "bottom", "start", "end"):
                    getattr(box, f"set_margin_{margin}")(12)
                box.append(
                    label(
                        _(
                            "Esta linha será adicionada ao /etc/fstab, montando o disco pelo UUID no mesmo "
                            "caminho de hoje. Antes, uma cópia do arquivo é guardada; o resultado é "
                            "validado com “findmnt --verify” e, se algo falhar, o original volta sozinho."
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
                    title=_("O disco já liga junto com o computador"),
                    subtitle=_("Montagem automática configurada pelo Nuvem Ruscher."),
                )
                row.add_prefix(status_icon("ok"))
                boot.add(row)
            elif report.fstab_state == "foreign":
                row = Adw.ActionRow(
                    title=_("Este disco já é montado pelo sistema"),
                    subtitle=_("Há uma regra para ele no /etc/fstab. Nada será alterado."),
                )
                row.add_prefix(status_icon("ok"))
                boot.add(row)
            else:
                row = Adw.ActionRow(
                    title=_("Este tipo de disco não pode ligar automaticamente"),
                    subtitle=_("O servidor vai ligar quando você entrar na sessão e o disco aparecer."),
                )
                row.add_prefix(status_icon("info"))
                boot.add(row)
            self.ready.append(boot)

        note = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        note.append(Gtk.Image.new_from_icon_name("security-high-symbolic"))
        note.append(
            label(
                _("O banco de dados (álbuns, pessoas, informações) fica no disco interno do computador."),
                css=("dim-label", "caption"),
            )
        )
        self.ready.append(note)

    def _choose(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title=_("Escolha a pasta das fotos"), modal=True)
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
                _("Usar mesmo assim?"),
                _("Vídeos maiores que 4 GB não poderão ser guardados neste disco."),
                _("Usar este disco"),
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
        self.next.set_label(_("Configurando…"))

        def done(result: HelperResult) -> None:
            self.next.set_sensitive(True)
            self.next.set_label(_("Continuar"))
            if result.ok:
                self.toast(_("Pronto! O disco vai ligar junto com o computador."))
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
                alternative=(_("Continuar sem isso"), lambda: self.wizard.go("configure")),
            )

        self.backend.helper("fstab-add", [volume.uuid, volume.mountpoint], None, done)


# --- 4. Ajustes -------------------------------------------------------------------------------

ML_LABELS = {
    "cpu": N_("Processador"),
    "openvino": N_("Placa Intel (OpenVINO)"),
    "rocm": N_("Placa AMD (ROCm) — download grande"),
    "cuda": N_("Placa NVIDIA (CUDA)"),
}
VENDOR_LABELS = {"amd": "AMD", "intel": "Intel", "nvidia": "NVIDIA"}


class ConfigurePage(WizardPage):
    step = 2

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Ajustes"), "configure")
        self.set_header_title(_("Ajustes finais"))
        self.body.append(page_heading(_("Ajustes finais"), _("Já deixamos tudo no ponto. Mude só se quiser.")))
        group = Adw.PreferencesGroup()
        self.timezone = Adw.ComboRow(title=_("Fuso horário"), subtitle=_("Detectado do sistema"))
        self.timezone.set_enable_search(True)
        self.timezone.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        group.add(self.timezone)
        self.version = Adw.ComboRow(title=_("Versão do Immich"), subtitle=_("Buscando versões…"))
        self.version.set_sensitive(False)
        group.add(self.version)
        self.body.append(group)

        advanced = Adw.PreferencesGroup()
        self.expander = Adw.ExpanderRow(
            title=_("Opções avançadas"), subtitle=_("Placa de vídeo e inteligência artificial")
        )
        self.transcode = Adw.SwitchRow(title=_("Vídeos mais rápidos com a placa de vídeo"))
        self.transcode.set_subtitle_lines(3)
        self.ml = Adw.SwitchRow(
            title=_("Reconhecimento de rostos e busca inteligente"),
            subtitle=_("Encontre fotos escrevendo “praia” ou “cachorro”. Usa cerca de 1 a 2 GB de memória."),
            active=True,
        )
        self.ml.set_subtitle_lines(3)
        self.ml_accel = Adw.ComboRow(
            title=_("Acelerar a inteligência artificial com"),
            subtitle=_("O processador é o mais compatível e o recomendado"),
        )
        self.ml_accel.set_subtitle_lines(2)
        self.ml.connect("notify::active", lambda *_: self.ml_accel.set_sensitive(self.ml.get_active()))
        for row in (self.transcode, self.ml, self.ml_accel):
            self.expander.add_row(row)
        advanced.add(self.expander)
        self.body.append(advanced)

        self.install = Gtk.Button(label=_("Instalar"), sensitive=False)
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
                _("Placa detectada: {vendor}. Converte vídeos para o celular bem mais rápido.").format(vendor=vendors)
            )
            self.transcode.set_active(True)
            self.ctx.extras["transcode_mode"] = gpu.transcode
        else:
            self.transcode.set_subtitle(_("Nenhuma placa compatível encontrada; o processador fará o trabalho."))
            self.transcode.set_sensitive(False)
        if not defaults.ml_recommended:
            self.ml.set_active(False)
            self.ml.set_subtitle(_("Desligado para caber na memória deste computador. Você pode ligar depois."))
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
                labels.append(_("{tag} — mais recente").format(tag=release.tag))
            else:
                labels.append(f"{release.tag} ({br_date(release.published)})")
        self.version.set_model(Gtk.StringList.new(labels))
        self.version.set_selected(0)
        self.version.set_subtitle(_("Recomendamos a mais recente"))
        self.version.set_sensitive(True)
        self._loaded |= 2
        self._update()

    def _no_releases(self, _exc: BaseException) -> None:
        self._releases = [KNOWN_GOOD_VERSION]
        self.version.set_model(Gtk.StringList.new([KNOWN_GOOD_VERSION]))
        self.version.set_subtitle(_("Sem acesso ao GitHub agora: usaremos a versão testada"))
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
    "prepare": N_("Preparando a configuração"),
    "download": N_("Baixando os componentes"),
    "start": N_("Ligando o servidor"),
    "health": N_("Aguardando o servidor ficar pronto"),
}
HELPER_STEP_TEXT = {
    "storage": N_("Conferindo o disco das fotos"),
    "download": N_("Baixando a configuração oficial do Immich"),
    "env": N_("Criando a senha do banco de dados"),
    "service": N_("Registrando o serviço no sistema"),
    "start": N_("Ligando…"),
    "restart": N_("Religando com a nova configuração…"),
}
ORDER = ("prepare", "download", "start", "health")


class InstallPage(WizardPage):
    step = 3

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Instalação"), "install")
        self.set_header_title(_("Instalação"))
        self.body.append(
            page_heading(
                _("Instalando sua nuvem"),
                _("Leva alguns minutos, conforme a internet. Pode usar o computador normalmente."),
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
        expander = Gtk.Expander(label=_("Detalhes técnicos"), child=self.log_scroller)
        self.body.append(expander)

        self.cancel = Gtk.Button(label=_("Cancelar"))
        self.cancel.connect("clicked", self._cancel)
        self.add_action(self.cancel, start=True)
        self.retry = Gtk.Button(label=_("Tentar novamente"), visible=False)
        self.retry.add_css_class("suggested-action")
        self.retry.connect("clicked", lambda *_: self.run(self._failed_step or "prepare"))
        self.add_action(self.retry)
        self.next = Gtk.Button(label=_("Continuar"), visible=False)
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
        self.retry.set_label(_("Tentar novamente"))
        self.retry.set_visible(True)
        self.cancel.set_visible(False)
        self.set_can_pop(True)

    def _pause(self, step: str) -> None:
        self._failed_step = step
        self.steps[step].set_state("warning", _("Pausado. Você pode continuar de onde parou."))
        self.retry.set_label(_("Continuar"))
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
        step.set_state("running", _("Pedindo autorização… digite sua senha de administrador, se pedida"))
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
            step.set_state("ok", _("Configuração pronta"))
            self.backend.state_set("install_step", "download")
            self._step_download()

        self._op = self.backend.helper("setup", args, event, done)

    def _step_download(self) -> None:
        step = self.steps["download"]
        step.set_state("running", _("Preparando o download…"))
        step.set_fraction(0)
        self.backend.state_set("install_step", "download")
        last_log = {"t": 0.0}

        def progress(p: PullProgress, line: str) -> None:
            step.set_fraction(p.fraction)
            if p.total:
                speed = p.speed()
                text = _("{percent}% · {done} baixados").format(
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
                _("Componentes baixados ({size})").format(size=human_size(p.total))
                if p.total
                else _("Componentes prontos"),
            )
            self._step_start()

        try:
            self._op = self.backend.pull(progress, done)
        except OSError as exc:
            self._fail("download", "not-installed", str(exc))

    def _step_start(self) -> None:
        step = self.steps["start"]
        step.set_state("running", _("Ligando…"))
        self.backend.state_set("install_step", "start")
        action = "restart" if self._restart_needed else "start"

        def done(result: HelperResult) -> None:
            self._op = None
            if not result.ok:
                self._fail("start", result.error_code, result.error_detail, result.log)
                return
            step.set_state("ok", _("Servidor ligado"))
            self._step_health()

        self._op = self.backend.helper(action, [], None, done)

    def _step_health(self) -> None:
        step = self.steps["health"]
        step.set_state("running", _("O servidor está acordando…"))
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
                step.set_state("ok", _("Tudo pronto!"))
                self._finished()
                return
            if elapsed > HEALTH_TIMEOUT_S:
                self._fail("health", "service-failed", f"sem resposta em {HEALTH_TIMEOUT_S}s")
                return
            text = _("{ready} de {total} componentes prontos").format(ready=ready, total=total) if total else ""
            if elapsed > 60:
                text = (text + " · " if text else "") + _("Na primeira vez demora mais: o banco está sendo preparado.")
            step.set_detail(text or _("O servidor está acordando…"))
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
        self.toast(_("Servidor no ar!"))
        GLib.timeout_add(900, lambda: self._advance() or False)

    def _advance(self) -> None:
        if self.wizard.nav.get_visible_page() is self:
            self.wizard.go_replace("account")


# --- 6. Conta ------------------------------------------------------------------------------------


class AccountPage(WizardPage):
    step = 4

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Conta"), "account", can_pop=False)
        self.set_header_title(_("Conta"))
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        loading = Adw.Spinner()
        loading.set_size_request(32, 32)
        loading.set_margin_top(48)
        self.stack.add_named(loading, "loading")

        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        form.append(
            page_heading(
                _("Crie sua conta de administrador"),
                _("É com ela que você entra no app do celular e no site. Guarde bem a senha."),
            )
        )
        group = Adw.PreferencesGroup()
        self.name = Adw.EntryRow(title=_("Seu nome"))
        self.email = Adw.EntryRow(title=_("E-mail"), input_purpose=Gtk.InputPurpose.EMAIL)
        self.password = Adw.PasswordEntryRow(title=_("Senha (mínimo de 8 caracteres)"))
        self.confirm = Adw.PasswordEntryRow(title=_("Confirmar a senha"))
        for row in (self.name, self.email, self.password, self.confirm):
            row.connect("changed", lambda *_: self._validate())
            row.connect("entry-activated", lambda *_: self._create())
            group.add(row)
        form.append(group)
        strength_box = Gtk.Box(spacing=12)
        self.strength_bar = Gtk.LevelBar(min_value=0, max_value=4, hexpand=True, valign=Gtk.Align.CENTER)
        self.strength_bar.update_property([Gtk.AccessibleProperty.LABEL], [_("Força da senha")])
        self.strength_label = label("", css=("caption", "dim-label"), wrap=False)
        strength_box.append(self.strength_bar)
        strength_box.append(self.strength_label)
        form.append(strength_box)
        self.hint = label("", css=("caption", "error"))
        self.hint.set_visible(False)
        form.append(self.hint)
        stats_group = Adw.PreferencesGroup()
        self.stats = Adw.SwitchRow(
            title=_("Mostrar quantas fotos e vídeos você tem no painel"),
            subtitle=_("Cria uma chave que só lê estatísticas. Sua senha não é guardada."),
            active=True,
        )
        self.stats.set_subtitle_lines(3)
        stats_group.add(self.stats)
        form.append(stats_group)
        browser = Gtk.Button(label=_("Prefiro criar a conta no navegador"), halign=Gtk.Align.CENTER)
        browser.add_css_class("flat")
        browser.connect("clicked", self._browser)
        form.append(browser)
        self.stack.add_named(form, "form")

        exists = StatusBlock(
            "avatar-default-symbolic",
            _("Sua conta já existe"),
            _("Encontramos a conta da instalação anterior. Use o mesmo e-mail e senha no app do celular e no site."),
        )
        exists_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        self.connect_button = pill_button(_("Mostrar contagem de fotos no painel"), self._connect_stats)
        exists_box.append(self.connect_button)
        exists.set_child(exists_box)
        self.stack.add_named(exists, "exists")
        self.body.append(self.stack)

        self.create = Gtk.Button(label=_("Criar conta"), sensitive=False)
        self.create.add_css_class("suggested-action")
        self.create.connect("clicked", lambda *_: self._create())
        self.add_action(self.create, default=True)
        self.skip = Gtk.Button(label=_("Continuar"), visible=False)
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
            problems.append(_("Confira o e-mail."))
        else:
            self.email.remove_css_class("error")
        if password and len(password) < 8:
            problems.append(_("A senha precisa de pelo menos 8 caracteres."))
        if again and again != password:
            self.confirm.add_css_class("error")
            problems.append(_("As senhas não são iguais."))
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
        self.create.set_label(_("Criando…"))
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
            self.toast(_("Conta criada!"))
            self.wizard.go("phone")

        def failed(exc: BaseException) -> None:
            self._busy = False
            self.create.set_label(_("Criar conta"))
            self._validate()
            message = exc.message if isinstance(exc, ApiError) else str(exc)
            dialog = Adw.AlertDialog(
                heading=_("Não foi possível criar a conta"),
                body=_("O servidor respondeu: {msg}").format(msg=message)
                if isinstance(exc, ApiError) and exc.status
                else _("O servidor não respondeu. Espere alguns segundos e tente de novo."),
            )
            dialog.add_response("ok", _("Fechar"))
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
        super().__init__(wizard, _("Celular"), "phone")
        self.set_header_title(_("Celular"))
        self.body.append(PhoneView(self.backend))
        done = Gtk.Button(label=_("Concluir"))
        done.add_css_class("suggested-action")
        done.connect("clicked", lambda *_: self.wizard.go_replace("done"))
        self.add_action(done, default=True)


# --- 8. Celebração ------------------------------------------------------------------------------------


class DonePage(WizardPage):
    step = None

    def __init__(self, wizard: Wizard) -> None:
        super().__init__(wizard, _("Pronto"), "done", can_pop=False)
        self.header.set_show_title(False)
        self.actions.set_visible(False)
        self.body.set_valign(Gtk.Align.CENTER)
        self.body.set_spacing(16)
        self.body.append(illustration("nuvem-ruscher-done", 280))
        title = label(_("Sua nuvem está no ar!"), css=("hero-title",), xalign=0.5)
        title.set_accessible_role(Gtk.AccessibleRole.HEADING)
        self.body.append(title)
        self.body.append(
            label(
                _("Abra o app Immich no celular e as fotos começam a chegar. Este computador cuida do resto."),
                css=("lead", "dim-label"),
                xalign=0.5,
            )
        )
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=12)
        open_button = pill_button(_("Abrir o Immich"), lambda b: open_uri(b, self.backend.local_url), suggested=True)
        panel = pill_button(_("Ir para o painel"), lambda *_: self.wizard.finish())
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
