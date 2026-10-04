"""Ponto de entrada: argumentos, tradução e a aplicação GTK."""

from __future__ import annotations

import argparse
import os
import sys

from nuvem_ruscher import APP_NAME, VERSION, i18n
from nuvem_ruscher.paths import locale_dir


def parse_args(argv: list[str]) -> argparse.Namespace:
    from nuvem_ruscher.i18n import _

    parser = argparse.ArgumentParser(prog="nuvem-ruscher", description=_("Instala e cuida do Immich no BigLinux."))
    parser.add_argument(
        "--simular",
        action="store_true",
        help=_("finge todas as operações de sistema (nada é alterado)"),
    )
    parser.add_argument(
        "--cenario",
        default="feliz",
        metavar="NOME",
        help=_("cenário da simulação; use “--cenario ajuda” para listar"),
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    i18n.setup(locale_dir())
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.cenario == "ajuda":
        from nuvem_ruscher.backend.simulated import SCENARIO_HELP

        width = max(len(k) for k in SCENARIO_HELP)
        for name, text in SCENARIO_HELP.items():
            print(f"  {name.ljust(width)}  {text}")
        return 0

    if os.geteuid() == 0:
        print(i18n._("Não rode o Nuvem Ruscher como root: ele pede a senha só quando precisa."), file=sys.stderr)
        return 1

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")

    from nuvem_ruscher.backend import create_backend
    from nuvem_ruscher.backend.simulated import SCENARIOS

    if args.simular and args.cenario not in SCENARIOS:
        print(
            i18n._("Cenário desconhecido: {name}. Use --cenario ajuda.").format(name=args.cenario),
            file=sys.stderr,
        )
        return 2
    if args.cenario != "feliz" and not args.simular:
        args.simular = True

    backend = create_backend(args.simular, args.cenario)

    from gi.repository import Gio

    from nuvem_ruscher.ui.application import NuvemApplication

    app = NuvemApplication(backend)
    if args.simular:
        # Instância separada: a simulação nunca se mistura com o app real aberto.
        app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    return app.run([sys.argv[0]])
