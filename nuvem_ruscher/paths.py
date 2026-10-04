"""Onde ficam os dados do app, rodando do código-fonte ou instalado.

Layout instalado: /usr/share/nuvem-ruscher/{nuvem_ruscher,data}. Do código-fonte, o
pacote fica ao lado de ``data/`` — então o mesmo cálculo serve para os dois casos.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR.parent / "data"
ILLUSTRATIONS_DIR = DATA_DIR / "illustrations"
ICONS_DIR = DATA_DIR / "icons"
STYLE_CSS = PACKAGE_DIR / "ui" / "style.css"
SOURCE_LOCALE_DIR = PACKAGE_DIR.parent / "build" / "locale"


def running_from_source() -> bool:
    return (PACKAGE_DIR.parent / ".git").exists() or (PACKAGE_DIR.parent / "pyproject.toml").exists()


def locale_dir() -> Path | None:
    """``None`` = diretório padrão do sistema (/usr/share/locale)."""
    if running_from_source() and SOURCE_LOCALE_DIR.is_dir():
        return SOURCE_LOCALE_DIR
    return None
