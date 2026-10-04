#!/usr/bin/env python3
"""Passeio automático pelas telas, em modo simulado, salvando capturas em PNG.

Ferramenta de desenvolvimento/QA (não é instalada). Uso:

    python3 tools/tour.py screenshots/            # tema do sistema, janela larga
    python3 tools/tour.py /tmp/x --escuro         # força o tema escuro
    python3 tools/tour.py /tmp/x --estreito       # 390 px (breakpoints)
    python3 tools/tour.py /tmp/x --cenario ntfs   # outro cenário da simulação

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
    parser.add_argument("--escuro", action="store_true")
    parser.add_argument("--estreito", action="store_true")
    parser.add_argument("--cenario", default="feliz")
    parser.add_argument("--somente", default="", help="prefixos separados por vírgula")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    i18n.setup(locale_dir())
    backend = SimulatedBackend(args.cenario)
    app = NuvemApplication(backend)
    app.set_flags(app.get_flags() | gi.repository.Gio.ApplicationFlags.NON_UNIQUE)
    suffix = ("-escuro" if args.escuro else "") + ("-estreito" if args.estreito else "")

    steps: list[tuple[int, Callable[[], None]]] = []

    def shot(name: str) -> Callable[[], None]:
        def go() -> None:
            if args.somente and not any(name.startswith(p) for p in args.somente.split(",")):
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
        p.email.set_text("maria@exemplo.com.br")
        p.password.set_text("Fotos-da-Familia-2026")
        p.confirm.set_text("Fotos-da-Familia-2026")

    def configure_advanced() -> None:
        page("configure").expander.set_expanded(True)

    def storage_switch() -> None:
        switch = page("storage").boot_switch
        if switch is not None:
            switch.set_active(True)

    def dashboard(tab: str) -> Callable[[], None]:
        return lambda: app.window.dashboard.show(tab)

    steps += [
        (1800, shot("01-boas-vindas")),
        (100, lambda: wizard().go("checks")),
        (5200, shot("02-verificacao")),
        (100, lambda: wizard().go("storage")),
        (2600, storage_switch),
        (400, shot("03-armazenamento")),
        (100, lambda: wizard().go("configure")),
        (2200, configure_advanced),
        (600, shot("04-ajustes")),
        (100, lambda: page("configure")._install(None)),
        (5200, shot("05-instalacao")),
        (16000, fill_account),
        (600, shot("06-conta")),
        (100, lambda: page("account")._create()),
        (2600, shot("07-celular")),
        (100, lambda: wizard().go_replace("done")),
        (900, shot("08-celebracao")),
        (2600, lambda: wizard().finish()),
        (7000, shot("09-painel")),
        (100, dashboard("logs")),
        (2200, shot("10-registros")),
        (100, dashboard("backups")),
        (1200, shot("11-backups")),
        (100, dashboard("updates")),
        (2200, shot("12-atualizacoes")),
        (100, dashboard("more")),
        (1500, shot("13-mais")),
        (100, dashboard("phone")),
        (1200, shot("14-painel-celular")),
        (300, app.quit),
    ]

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
        if args.escuro:
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        app.window.remove_css_class("devel")  # capturas limpas para o README
        if args.estreito:
            app.window.set_default_size(390, 820)
        run()

    app.connect_after("activate", on_activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
