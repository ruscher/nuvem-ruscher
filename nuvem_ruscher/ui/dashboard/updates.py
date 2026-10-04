"""Atualizações: novidades, alertas e atualização com backup, saúde e rollback."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from nuvem_ruscher.async_utils import Operation, run_async
from nuvem_ruscher.backend.base import Backend, HelperResult
from nuvem_ruscher.core.compose import PullProgress
from nuvem_ruscher.core.helper_protocol import HelperEvent, human_error
from nuvem_ruscher.core.releases import Release, UpdateInfo, simple_markdown_to_pango, update_info
from nuvem_ruscher.core.storage import human_size
from nuvem_ruscher.i18n import N_, _
from nuvem_ruscher.ui.common import confirm, label, open_uri, pill_button, status_icon
from nuvem_ruscher.ui.dashboard.monitor import ServerMonitor
from nuvem_ruscher.ui.widgets.rows import InstallStep

UPDATE_STEPS = (
    ("download", N_("Baixando a nova versão")),
    ("backup", N_("Fazendo backup do banco de dados")),
    ("snapshot", N_("Guardando uma cópia instantânea do banco")),
    ("switch", N_("Trocando a versão")),
    ("health", N_("Conferindo se está tudo certo")),
)
HELPER_TO_STEP = {
    "download": "download",
    "pull": "download",
    "backup": "backup",
    "dump": "backup",
    "copy": "backup",
    "stop": "snapshot",
    "snapshot": "snapshot",
    "switch": "switch",
    "start": "health",
    "rollback": "health",
}


class UpdateDialog(Adw.Dialog):
    def __init__(self, backend: Backend, target: str, on_finished: Callable[[bool], None]) -> None:
        super().__init__(title=_("Atualizando o Immich"), content_width=520, can_close=False)
        self.backend = backend
        self.target = target
        self.on_finished = on_finished
        self._op: Operation | None = None
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        toolbar.add_top_bar(header)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for margin in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{margin}")(18)
        self.headline = label(
            _("Atualizando para a {v}. Seu servidor fica fora do ar por alguns minutos.").format(v=target),
            css=("dim-label",),
        )
        box.append(self.headline)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("card")
        self.steps: dict[str, InstallStep] = {}
        for index, (key, title) in enumerate(UPDATE_STEPS):
            if index:
                card.append(Gtk.Separator())
            step = InstallStep(_(title), with_progress=key == "download")
            self.steps[key] = step
            card.append(step)
        box.append(card)
        self.result = Adw.PreferencesGroup(visible=False)
        self.result_row = Adw.ActionRow()
        self.result_row.set_subtitle_lines(5)
        self.result_icon = status_icon("ok", 20)
        self.result_row.add_prefix(self.result_icon)
        self.result.add(self.result_row)
        box.append(self.result)
        self.log = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self.log, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.add_css_class("log-view")
        scroller = Gtk.ScrolledWindow(min_content_height=140, max_content_height=200, child=view)
        box.append(Gtk.Expander(label=_("Detalhes técnicos"), child=scroller))
        self.close_button = pill_button(_("Fechar"), lambda *_: self._close(), suggested=True)
        self.close_button.set_visible(False)
        box.append(self.close_button)
        toolbar.set_content(box)
        self.set_child(toolbar)
        self._current = ""
        self._ok = False
        GLib.idle_add(lambda: self._start() or False)

    def _append(self, text: str) -> None:
        self.log.insert(self.log.get_end_iter(), text + "\n")

    def _set_current(self, key: str) -> None:
        if key == self._current:
            return
        order = [k for k, _t in UPDATE_STEPS]
        if self._current:
            self.steps[self._current].set_state("ok")
        for previous in order[: order.index(key)]:
            if self.steps[previous].state in ("pending", "running"):
                self.steps[previous].set_state("ok")
        self._current = key
        self.steps[key].set_state("running")

    def _start(self) -> None:
        self._set_current("download")
        step = self.steps["download"]
        step.set_detail(_("Buscando os arquivos da {v}…").format(v=self.target))

        def got_compose(text: str) -> None:
            def progress(p: PullProgress, line: str) -> None:
                step.set_fraction(p.fraction)
                if p.total:
                    step.set_detail(
                        _("{percent}% · {done} baixados").format(
                            percent=int(p.fraction * 100), done=human_size(p.downloaded)
                        )
                    )

            def pulled(ok: bool, p: PullProgress) -> None:
                if not ok:
                    self._finish(False, "download-failed", "; ".join(p.errors[-2:]))
                    return
                step.set_fraction(1)
                step.set_detail(_("Componentes novos baixados"))
                self._run_helper()

            self._op = self.backend.pull(progress, pulled, version=self.target, compose_text=text)

        run_async(
            self.backend.download_compose,
            self.target,
            on_done=got_compose,
            on_error=lambda e: self._finish(False, "download-failed", str(e)),
        )

    def _run_helper(self) -> None:
        def event(ev: HelperEvent) -> None:
            if ev.kind == "step":
                if ev.value == "rollback":
                    self.steps["health"].set_state(
                        "warning", _("A nova versão não respondeu. Voltando para a anterior…")
                    )
                    self._current = "health"
                elif ev.value in HELPER_TO_STEP:
                    self._set_current(HELPER_TO_STEP[ev.value])
            if ev.kind in ("log", "info"):
                self._append(ev.value)
            elif ev.kind == "error":
                self._append(f"[erro] {ev.key}: {ev.value}")

        def done(result: HelperResult) -> None:
            if result.ok:
                self._finish(True)
            else:
                self._finish(False, result.error_code, result.error_detail)

        self._op = self.backend.helper("update", [self.target], event, done)

    def _finish(self, ok: bool, code: str = "", detail: str = "") -> None:
        self._ok = ok
        self.set_can_close(True)
        self.close_button.set_visible(True)
        self.result.set_visible(True)
        if ok:
            for step in self.steps.values():
                if step.state != "ok":
                    step.set_state("ok")
            self.result_row.set_title(_("Atualizado para a {v}!").format(v=self.target))
            self.result_row.set_subtitle(_("Um backup e uma cópia do banco anterior ficaram guardados, por segurança."))
            self.result_icon.set_from_icon_name("nr-status-ok-symbolic")
        else:
            title, hint = human_error(code)
            if self._current:
                self.steps[self._current].set_state("warning" if code == "update-rolled-back" else "error")
            self.result_row.set_title(GLib.markup_escape_text(title))
            self.result_row.set_subtitle(GLib.markup_escape_text(hint))
            self.result_icon.set_from_icon_name(
                "nr-status-warning-symbolic" if code == "update-rolled-back" else "nr-status-error-symbolic"
            )
            if detail:
                self._append(f"[{code}] {detail}")

    def _close(self) -> None:
        self.close()
        self.on_finished(self._ok)


class UpdatesPage(Gtk.Box):
    def __init__(self, backend: Backend, monitor: ServerMonitor) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.backend = backend
        self.monitor = monitor
        self.info: UpdateInfo | None = None
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.body.set_margin_top(24)
        self.body.set_margin_bottom(24)
        self.body.set_margin_start(16)
        self.body.set_margin_end(16)
        scroller.set_child(Adw.Clamp(maximum_size=760, child=self.body))
        self.append(scroller)

        self.status = Adw.StatusPage(icon_name="software-update-available-symbolic")
        self.status.add_css_class("compact")
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        self.check_button = pill_button(_("Verificar agora"), lambda *_: self.refresh(force=True))
        self.update_button = pill_button(_("Atualizar com segurança"), self._ask_update, suggested=True)
        self.update_button.set_visible(False)
        buttons.append(self.check_button)
        buttons.append(self.update_button)
        self.status.set_child(buttons)
        self.body.append(self.status)

        self.breaking = Adw.PreferencesGroup(visible=False)
        self.body.append(self.breaking)
        self.notes = Adw.PreferencesGroup(title=_("Novidades"), visible=False)
        self.body.append(self.notes)
        self._dynamic: list[tuple[Adw.PreferencesGroup, Gtk.Widget]] = []
        explain = Adw.PreferencesGroup()
        row = Adw.ActionRow(
            title=_("Como a atualização protege seus dados"),
            subtitle=_(
                "Antes de trocar a versão, fazemos um backup do banco e uma cópia instantânea dele. "
                "Depois conferimos se o servidor respondeu. "
                "Se não responder, tudo volta sozinho para a versão anterior."
            ),
        )
        row.set_subtitle_lines(6)
        row.add_prefix(Gtk.Image.new_from_icon_name("security-high-symbolic"))
        explain.add(row)
        self.body.append(explain)
        self._loading = False

    def refresh(self, force: bool = False) -> None:
        if self._loading:
            return
        self._loading = True
        self.check_button.set_sensitive(False)
        self.status.set_title(_("Procurando atualizações…"))
        self.status.set_description(None)
        current = self.monitor.conf.immich_version or self.backend.load_config().immich_version

        def done(releases: list[Release]) -> None:
            self._loading = False
            self.check_button.set_sensitive(True)
            self._show(update_info(current, releases))

        def failed(_exc: BaseException) -> None:
            self._loading = False
            self.check_button.set_sensitive(True)
            self.status.set_title(_("Não foi possível verificar agora"))
            self.status.set_description(_("Sem conexão com o GitHub. Tente de novo mais tarde."))

        run_async(self.backend.releases, force, on_done=done, on_error=failed)

    def _clear(self) -> None:
        for group, widget in self._dynamic:
            group.remove(widget)
        self._dynamic = []

    def _show(self, info: UpdateInfo) -> None:
        self.info = info
        self._clear()
        if not info.available or info.latest is None:
            self.status.set_icon_name("nr-status-ok-symbolic")
            self.status.set_title(_("Você está na versão mais recente"))
            self.status.set_description(_("Immich {v}").format(v=info.current))
            self.update_button.set_visible(False)
            self.breaking.set_visible(False)
            self.notes.set_visible(False)
            return
        latest = info.latest
        self.status.set_icon_name("software-update-available-symbolic")
        self.status.set_title(_("A versão {v} está disponível").format(v=latest.tag))
        self.status.set_description(
            _("Você está na {cur}. Publicada em {date}.").format(cur=info.current, date=latest.published)
        )
        self.update_button.set_visible(True)

        warnings = info.breaking
        self.breaking.set_visible(bool(warnings) or info.major_change)
        if warnings or info.major_change:
            expander = Adw.ExpanderRow(
                title=_("Mudanças importantes nesta atualização"),
                subtitle=_("Leia antes de atualizar. Normalmente não exigem nada de você."),
                expanded=True,
            )
            expander.add_prefix(status_icon("warning"))
            if info.major_change:
                expander.add_row(self._text_row(_("É uma versão principal nova: a mudança é maior que o normal.")))
            for tag, section in warnings:
                expander.add_row(self._text_row(f"<b>{tag}</b>\n" + simple_markdown_to_pango(section), markup=True))
            self.breaking.add(expander)
            self._dynamic.append((self.breaking, expander))

        self.notes.set_visible(True)
        for release in info.pending[:8]:
            expander = Adw.ExpanderRow(title=release.tag, subtitle=release.published)
            expander.add_row(self._text_row(simple_markdown_to_pango(release.body), markup=True))
            link = Adw.ActionRow(title=_("Ver no GitHub"), activatable=True)
            link.add_suffix(Gtk.Image.new_from_icon_name("adw-external-link-symbolic"))
            link.connect("activated", lambda r, u=release.url: open_uri(r, u))
            expander.add_row(link)
            self.notes.add(expander)
            self._dynamic.append((self.notes, expander))

    @staticmethod
    def _text_row(text: str, markup: bool = False) -> Gtk.Widget:
        widget = label(text, markup=markup, selectable=True)
        widget.set_margin_top(12)
        widget.set_margin_bottom(12)
        widget.set_margin_start(14)
        widget.set_margin_end(14)
        return widget

    def _ask_update(self, _button: Gtk.Button) -> None:
        info = self.info
        if info is None or info.latest is None:
            return
        target = info.latest.tag
        if self.monitor.overall == "disk-missing":
            confirm(
                self,
                _("Conecte o disco das fotos"),
                _("A atualização precisa do servidor ligado."),
                _("Entendi"),
                lambda: None,
            )
            return
        confirm(
            self,
            _("Atualizar para a {v}?").format(v=target),
            _(
                "O servidor fica fora do ar por alguns minutos. Antes, fazemos backup do banco; "
                "se algo der errado, tudo volta sozinho para a {cur}."
            ).format(cur=info.current),
            _("Atualizar"),
            lambda: self._run_update(target),
        )

    def _run_update(self, target: str) -> None:
        def finished(ok: bool) -> None:
            self.monitor.refresh()
            self.refresh()

        UpdateDialog(self.backend, target, finished).present(self.get_root())
