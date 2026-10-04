"""Tradução via gettext. Os textos-fonte são em pt-BR (ADR-009)."""

from __future__ import annotations

import gettext
import locale
from pathlib import Path

DOMAIN = "nuvem-ruscher"

_translation: gettext.NullTranslations = gettext.NullTranslations()


def setup(localedir: Path | None = None) -> None:
    """Configura o domínio de tradução (também para Gtk.Builder, se usado)."""
    global _translation
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    directory = str(localedir) if localedir else None
    try:
        locale.bindtextdomain(DOMAIN, directory)  # type: ignore[attr-defined]
        locale.textdomain(DOMAIN)  # type: ignore[attr-defined]
    except AttributeError:
        pass
    _translation = gettext.translation(DOMAIN, directory, fallback=True)


def _(message: str) -> str:
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _translation.ngettext(singular, plural, n)


def N_(message: str) -> str:  # noqa: N802 — convenção do gettext
    """Marca o texto para extração sem traduzir agora (traduz-se no uso)."""
    return message
