"""Ponto de entrada: argumentos, tradução e a aplicação GTK."""

from __future__ import annotations

import argparse
import os
import sys

from nuvem_ruscher import APP_NAME, VERSION, i18n
from nuvem_ruscher.paths import locale_dir


def parse_args(argv: list[str]) -> argparse.Namespace:
    from nuvem_ruscher.i18n import _

    parser = argparse.ArgumentParser(
        prog="nuvem-ruscher",
        description=_("Installs and looks after Immich on BigLinux."),
        allow_abbrev=False,
    )
    # --simular/--cenario/ajuda: nomes da primeira versão, mantidos como apelidos.
    parser.add_argument(
        "--simulate",
        "--simular",
        dest="simulate",
        action="store_true",
        help=_("fakes every system operation (nothing is changed)"),
    )
    parser.add_argument(
        "--scenario",
        "--cenario",
        dest="scenario",
        default="fresh",
        metavar=_("NAME"),
        help=_("simulation scenario; use “--scenario help” to list them"),
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    i18n.setup(locale_dir())
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.scenario in ("help", "ajuda"):
        from nuvem_ruscher.backend.simulated import SCENARIO_HELP

        width = max(len(k) for k in SCENARIO_HELP)
        for name, text in SCENARIO_HELP.items():
            print(f"  {name.ljust(width)}  {i18n._(text)}")
        return 0

    if os.geteuid() == 0:
        print(i18n._("Do not run Nuvem Ruscher as root: it asks for the password only when needed."), file=sys.stderr)
        return 1

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")

    from nuvem_ruscher.backend import create_backend
    from nuvem_ruscher.backend.simulated import resolve_scenario

    scenario = resolve_scenario(args.scenario)
    if scenario is None:
        print(
            i18n._("Unknown scenario: {name}. Use --scenario help.").format(name=args.scenario),
            file=sys.stderr,
        )
        return 2
    if scenario != "fresh":
        args.simulate = True

    backend = create_backend(args.simulate, scenario)

    from gi.repository import Gio

    from nuvem_ruscher.ui.application import NuvemApplication

    app = NuvemApplication(backend)
    if args.simulate:
        # Instância separada: a simulação nunca se mistura com o app real aberto.
        app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    return app.run([sys.argv[0]])
