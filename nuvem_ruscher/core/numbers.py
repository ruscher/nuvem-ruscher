"""Números no formato do idioma do usuário (vírgula ou ponto, separador de milhar)."""

from __future__ import annotations

import locale


def integer(value: int) -> str:
    """12483 → "12,483" (inglês) ou "12.483" (pt-BR)."""
    return locale.format_string("%d", int(value), grouping=True)


def decimal(value: float, digits: int = 1) -> str:
    """1.5 → "1.5" (inglês) ou "1,5" (pt-BR)."""
    return locale.format_string(f"%.{digits}f", float(value), grouping=True)


def percent(fraction: float, digits: int = 0) -> str:
    """0.153 → "15%"; o símbolo segue colado ao número, como no GNOME."""
    return f"{decimal(fraction * 100, digits)}%"
