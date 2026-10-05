"""Datas e durações para a interface, no idioma e no formato do usuário."""

from __future__ import annotations

import datetime
import time

from gi.repository import GLib

from nuvem_ruscher.i18n import _, ngettext


def _clock(timestamp: float) -> str:
    return GLib.DateTime.new_from_unix_local(int(timestamp)).format("%R") or ""


def full_date(timestamp: float) -> str:
    """Data por extenso do locale (ex.: "4 de out. de 2026" / "Oct 4, 2026")."""
    return GLib.DateTime.new_from_unix_local(int(timestamp)).format("%x") or ""


def relative_time(timestamp: float, now: float | None = None) -> str:
    """ "Today, 02:00", "Yesterday, 23:10", "3 days ago" ou a data (dias de calendário)."""
    now = time.time() if now is None else now
    days = (datetime.date.fromtimestamp(now) - datetime.date.fromtimestamp(timestamp)).days
    if days <= 0:
        return _("Today, {hour}").format(hour=_clock(timestamp))
    if days == 1:
        return _("Yesterday, {hour}").format(hour=_clock(timestamp))
    if days < 7:
        return ngettext("{n} day ago", "{n} days ago", days).format(n=days)
    return full_date(timestamp)


def duration(seconds: float) -> str:
    """Duração curta e honesta: "2 h 15 min", "40 min", "less than a minute"."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return _("less than a minute")
    minutes = seconds // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return _("{h} h {m} min").format(h=hours, m=minutes)
    return _("{m} min").format(m=minutes)
