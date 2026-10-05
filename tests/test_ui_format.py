"""Datas relativas: dias de calendário, não períodos de 24 h."""

import datetime
import time

import pytest

gi = pytest.importorskip("gi")

from nuvem_ruscher.ui.format import duration, relative_time  # noqa: E402


def _ts(day: datetime.date, hour: int, minute: int = 0) -> float:
    return time.mktime(datetime.datetime(day.year, day.month, day.day, hour, minute).timetuple())


def test_relative_time_uses_calendar_days():
    today = datetime.date(2026, 10, 5)
    now = _ts(today, 9)
    assert relative_time(_ts(today, 2), now).startswith("Today")
    assert relative_time(_ts(today - datetime.timedelta(days=1), 23), now).startswith("Yesterday")
    # 33 h atrás, mas dois dias de calendário: não pode virar "1 day ago".
    assert relative_time(_ts(today - datetime.timedelta(days=2), 23), now) == "2 days ago"
    assert relative_time(_ts(today - datetime.timedelta(days=6), 12), now) == "6 days ago"
    assert "ago" not in relative_time(_ts(today - datetime.timedelta(days=30), 12), now)


def test_duration_is_short_and_honest():
    assert duration(20) == "less than a minute"
    assert duration(40 * 60) == "40 min"
    assert duration(2 * 3600 + 15 * 60) == "2 h 15 min"
