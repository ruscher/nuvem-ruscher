"""Onde ficam os dados do app, rodando do código-fonte ou instalado.

Layout instalado: ``<prefixo>/share/nuvem-ruscher/{nuvem_ruscher,data}``, com o helper em
``<prefixo>/lib/nuvem-ruscher/`` e as traduções em ``<prefixo>/share/locale``. O prefixo é
``/usr`` no pacote do pacman e ``/nix/store/<hash>-nuvem-ruscher-<versão>`` no Nix: por
isso tudo é calculado a partir da posição deste arquivo, nunca escrito por extenso.
Do código-fonte, o pacote fica ao lado de ``data/`` — então o mesmo cálculo serve para
os dois casos.
"""

from __future__ import annotations

from pathlib import Path

from nuvem_ruscher.constants import HELPER_PATH

PACKAGE_DIR = Path(__file__).resolve().parent
APP_DIR = PACKAGE_DIR.parent
DATA_DIR = APP_DIR / "data"
ILLUSTRATIONS_DIR = DATA_DIR / "illustrations"
ICONS_DIR = DATA_DIR / "icons"
STYLE_CSS = PACKAGE_DIR / "ui" / "style.css"


def running_from_source(app_dir: Path = APP_DIR) -> bool:
    return (app_dir / ".git").exists() or (app_dir / "pyproject.toml").exists()


def install_prefix(app_dir: Path = APP_DIR) -> Path | None:
    """``/usr`` (pacman), o caminho no Nix Store, ou ``None`` no código-fonte."""
    if running_from_source(app_dir) or app_dir.parent.name != "share":
        return None
    return app_dir.parent.parent


def helper_path(app_dir: Path = APP_DIR) -> Path:
    """O helper que acompanha esta cópia do app.

    Do código-fonte, só o helper instalado em /usr/lib serve: é o caminho que a regra do
    polkit conhece, e o do repositório pode ser alterado pelo próprio usuário.
    """
    prefix = install_prefix(app_dir)
    if prefix is None:
        return Path(HELPER_PATH)
    return prefix / "lib" / "nuvem-ruscher" / "nuvem-ruscher-helper"


def locale_dir(app_dir: Path = APP_DIR) -> Path | None:
    """Pasta dos catálogos ``.mo``; ``None`` = padrão do Python (sem traduções compiladas)."""
    prefix = install_prefix(app_dir)
    if prefix is not None:
        return prefix / "share" / "locale"
    source = app_dir / "build" / "locale"
    return source if source.is_dir() else None
