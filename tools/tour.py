#!/usr/bin/env python3
"""Passeio automático pelas telas, em modo simulado, salvando capturas em PNG.

Ferramenta de desenvolvimento/QA (não é instalada). Uso:

    python3 tools/tour.py screenshots/                    # assistente + todas as páginas
    python3 tools/tour.py /tmp/x --dark                   # tema escuro
    python3 tools/tour.py /tmp/x --narrow                 # 390 px (barra lateral recolhida)
    python3 tools/tour.py /tmp/x --scenario installed     # só as páginas, noutro cenário
    python3 tools/tour.py /tmp/x --only p-home,p-storage  # só algumas capturas

As capturas são renderizadas pelo próprio GTK (Gtk.WidgetPaintable), então não
dependem do foco da janela nem do compositor.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Graphene, Gtk  # noqa: E402

from nuvem_ruscher import i18n  # noqa: E402
from nuvem_ruscher.backend.simulated import SimulatedBackend  # noqa: E402
from nuvem_ruscher.paths import locale_dir  # noqa: E402
from nuvem_ruscher.ui.application import NuvemApplication  # noqa: E402


def capture(window: Gtk.Window, path: Path) -> None:
    width, height = window.get_width(), window.get_height()
    paintable = Gtk.WidgetPaintable(widget=window)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        print("nada para capturar", path)
        return
    renderer = window.get_renderer()
    rect = Graphene.Rect().init(0, 0, width, height)
    texture = renderer.render_texture(node, rect)
    texture.save_to_png(str(path))
    print("capturado", path.name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--dark", "--escuro", dest="dark", action="store_true")
    parser.add_argument("--narrow", "--estreito", dest="narrow", action="store_true")
    parser.add_argument("--scenario", "--cenario", dest="scenario", default="fresh")
    parser.add_argument("--only", "--somente", dest="only", default="", help="prefixos separados por vírgula")
    parser.add_argument("--extra", default="", help="ações extras depois das páginas (ex.: users-add)")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    i18n.setup(locale_dir())
    backend = SimulatedBackend(args.scenario)
    app = NuvemApplication(backend)
    app.set_flags(app.get_flags() | gi.repository.Gio.ApplicationFlags.NON_UNIQUE)
    suffix = ("-dark" if args.dark else "") + ("-narrow" if args.narrow else "")
    if args.scenario != "fresh":
        suffix += f"-{args.scenario}"

    steps: list[tuple[int, Callable[[], None]]] = []

    def shot(name: str) -> Callable[[], None]:
        def go() -> None:
            if args.only and not any(name.startswith(p) for p in args.only.split(",")):
                return
            capture(app.window, out / f"{name}{suffix}.png")

        return go

    def wizard():  # noqa: ANN202
        return app.window.wizard

    def page(tag: str):  # noqa: ANN202
        return wizard()._page(tag)

    def fill_account() -> None:
        p = page("account")
        p.name.set_text("Maria")
        p.email.set_text("maria@example.com")
        p.password.set_text("Family-Photos-2026")
        p.confirm.set_text("Family-Photos-2026")

    def configure_advanced() -> None:
        page("configure").expander.set_expanded(True)

    def storage_switch() -> None:
        switch = page("storage").boot_switch
        if switch is not None:
            switch.set_active(True)

    def show(page_id: str) -> Callable[[], None]:
        return lambda: app.window.shell.show(page_id)

    if args.scenario == "fresh":
        steps += [
            (1800, shot("w1-welcome")),
            (100, lambda: wizard().go("checks")),
            (5200, shot("w2-checks")),
            (100, lambda: wizard().go("storage")),
            (2600, storage_switch),
            (400, shot("w3-storage")),
            (100, lambda: wizard().go("configure")),
            (2200, configure_advanced),
            (600, shot("w4-settings")),
            (100, lambda: page("configure")._install(None)),
            (5200, shot("w5-install")),
            (16000, fill_account),
            (600, shot("w6-account")),
            (100, lambda: page("account")._create()),
            (2600, shot("w7-phone")),
            (100, lambda: wizard().go_replace("done")),
            (900, shot("w8-done")),
            (2600, lambda: wizard().finish()),
            (5000, lambda: None),
        ]
    else:
        steps.append((2500, lambda: None))

    from nuvem_ruscher.ui.shell import PAGE_IDS

    def page_shot(page_id: str) -> Callable[[], None]:
        def go() -> None:
            if page_id in app.window.shell.pages:  # páginas ainda não registradas ficam de fora
                shot(f"p-{page_id}")()

        return go

    for page_id in PAGE_IDS:
        waits = {"home": 2500, "logs": 2200, "updates": 2200}
        steps += [
            (100, show(page_id)),
            (waits.get(page_id, 1300), page_shot(page_id)),
        ]
    for name in filter(None, args.extra.split(",")):
        steps += EXTRAS[name](app, shot)
    steps.append((300, app.quit))

    def run(index: int = 0) -> bool:
        if index >= len(steps):
            return False
        delay, action = steps[index]

        def fire() -> bool:
            try:
                action()
            except Exception as exc:
                print("falhou no passo", index, exc)
            run(index + 1)
            return False

        GLib.timeout_add(delay, fire)
        return False

    def on_activate(_app: Adw.Application) -> None:
        scheme = Adw.ColorScheme.FORCE_DARK if args.dark else Adw.ColorScheme.FORCE_LIGHT
        Adw.StyleManager.get_default().set_color_scheme(scheme)
        app.window.remove_css_class("devel")  # capturas limpas para o README
        if args.narrow:
            app.window.set_default_size(390, 820)
        run()

    app.connect_after("activate", on_activate)
    return app.run([sys.argv[0]])


def _migration_tour(app: NuvemApplication, shot: Callable[[str], Callable[[], None]]) -> list:
    box: dict = {}

    def open_dialog() -> None:
        storage = app.window.shell.page("storage")
        app.window.shell.show("storage")
        box["d"] = storage.open_migration("/run/media/ruscher/Backup HD/Nuvem")

    return [
        (300, open_dialog),
        (1500, shot("d-move-1-choose")),
        (100, lambda: box["d"]._check()),
        (3000, shot("d-move-2-summary")),
        (100, lambda: box["d"]._start()),
        (4500, shot("d-move-3-copy")),
        (16000, shot("d-move-4-done")),
        (100, lambda: box["d"].close()),
    ]


def _raid_tour(app: NuvemApplication, shot: Callable[[str], Callable[[], None]]) -> list:
    box: dict = {}

    def open_dialog() -> None:
        storage = app.window.shell.page("storage")
        app.window.shell.show("storage")
        box["d"] = storage.open_raid()

    def pick() -> None:
        for name in ("sda", "sdb"):
            check = box["d"].checks.get(name)
            if check is not None:
                check.set_active(True)

    def confirm_all() -> None:
        for check in box["d"].erase_checks:
            check.set_active(True)
        box["d"].word_entry.set_text(box["d"].word)

    return [
        (300, open_dialog),
        (1200, shot("d-raid-1-level")),
        (100, lambda: box["d"]._choose_disks()),
        (1500, pick),
        (500, shot("d-raid-2-disks")),
        (100, lambda: box["d"]._confirm_page()),
        (600, confirm_all),
        (500, shot("d-raid-3-confirm")),
        (100, lambda: box["d"]._create()),
        (8000, shot("d-raid-4-done")),
        (100, lambda: box["d"].close()),
    ]


def _accounts_tour(app: NuvemApplication, shot: Callable[[str], Callable[[], None]]) -> list:
    box: dict = {}

    def sign_in() -> None:
        users = app.window.shell.page("users")
        app.window.shell.show("users")
        users.sign_in.email.set_text("ruscher@example.com")
        users.sign_in.password.set_text("example-password")
        users.sign_in._go()

    def add() -> None:
        from nuvem_ruscher.ui.accounts_ui import AddAccountDialog

        box["d"] = AddAccountDialog(app.window.shell.ctx, lambda _u: None)
        box["d"].present(app.window)

    def fill() -> None:
        d = box["d"]
        d.name.set_text("Ana")
        d.email.set_text("ana@example.com")
        d.quota.set_selected(4)

    def sharing() -> None:
        app.window.shell.show("sharing")

    def manage() -> None:
        page = app.window.shell.page("sharing")
        from nuvem_ruscher.ui.pages.sharing import SharedFolderDialog

        mine, _w = app.window.shell.ctx.backend.shared_albums()
        box["m"] = SharedFolderDialog(app.window.shell.ctx, mine[0], page.people, lambda: None)
        box["m"].present(app.window)

    return [
        (300, lambda: app.window.shell.show("users")),
        (900, shot("p-users-signin")),
        (100, sign_in),
        (3000, shot("p-users")),
        (100, add),
        (600, fill),
        (500, shot("d-account-1-form")),
        (100, lambda: box["d"]._create()),
        (2500, shot("d-account-2-created")),
        (100, lambda: box["d"].close()),
        (300, sharing),
        (2500, shot("p-sharing")),
        (100, manage),
        (900, shot("d-shared-folder")),
        (100, lambda: box["m"].close()),
        (300, lambda: app.window.shell.show("home")),
        (2500, shot("p-home-signed")),
    ]


def _phones_tour(app: NuvemApplication, shot: Callable[[str], Callable[[], None]]) -> list:
    """Celulares: Android, iPhone, fora de casa, teste da conexão e a parte de baixo da página."""

    def page():  # noqa: ANN202
        return app.window.shell.page("phones")

    def scroll(fraction: float) -> Callable[[], None]:
        def go() -> None:
            adj = page().scroller.get_vadjustment()
            adj.set_value((adj.get_upper() - adj.get_page_size()) * fraction)

        return go

    def expand_all() -> None:
        for row in _walk(page().view):
            if isinstance(row, Adw.ExpanderRow):
                row.set_expanded(True)

    return [
        (100, lambda: app.window.shell.show("phones")),
        (100, lambda: page().view.set_platform("android")),
        (1200, shot("ph-android")),
        (100, lambda: page().view.set_platform("ios")),
        (900, shot("ph-iphone")),
        (100, lambda: page().view.run_test()),
        (1500, lambda: page().scroller.get_child().scroll_to(page().view.check, None)),
        (500, shot("ph-iphone-test")),
        (100, expand_all),
        (100, scroll(1.0)),
        (900, shot("ph-iphone-more")),
        (100, lambda: page().view.where.set_active_name("away")),
        (400, scroll(0.0)),
        (600, shot("ph-iphone-away")),
        (100, lambda: page().view.where.set_active_name("home")),
    ]


def _walk(widget: Gtk.Widget):  # noqa: ANN202
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


# Ações extras (diálogos): nome → passos.
EXTRAS: dict[str, Callable[..., list[tuple[int, Callable[[], None]]]]] = {
    "migration": _migration_tour,
    "raid": _raid_tour,
    "accounts": _accounts_tour,
    "phones": _phones_tour,
}


if __name__ == "__main__":
    sys.exit(main())
