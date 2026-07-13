"""Tests for the cron parser (ADR-0007)."""

from __future__ import annotations

from datetime import datetime

import pytest
from apscheduler.triggers.cron import CronTrigger

from gpscheduler.cron import parse_cron
from gpscheduler.exceptions import CronExpressionError


def _next_weekday(expr: str) -> int:
    """Build a trigger from ``expr`` and return the weekday() of its next fire.

    Uses datetime.weekday(): Monday=0 .. Sunday=6.
    """
    t = parse_cron(expr)
    nt = t.get_next_fire_time(None, datetime.now())
    assert nt is not None, f"no next fire time for {expr!r}"
    return nt.weekday()


def test_five_segment_uses_from_crontab() -> None:
    t = parse_cron("0 3 * * *")
    assert isinstance(t, CronTrigger)
    # minute=0, hour=3
    assert str(t.fields)  # non-empty


def test_six_segment_with_seconds() -> None:
    t = parse_cron("*/30 0 * * * *")
    assert isinstance(t, CronTrigger)


def test_every_minute() -> None:
    t = parse_cron("* * * * *")
    assert isinstance(t, CronTrigger)


def test_with_list_and_range_and_step() -> None:
    t = parse_cron("0,30 0-23 * * *")
    assert isinstance(t, CronTrigger)


def test_invalid_segment_count_four() -> None:
    with pytest.raises(CronExpressionError):
        parse_cron("0 3 *")


def test_invalid_segment_count_seven() -> None:
    with pytest.raises(CronExpressionError):
        parse_cron("0 0 0 0 0 0 0")


def test_field_out_of_range() -> None:
    with pytest.raises(CronExpressionError):
        parse_cron("99 * * * *")


def test_quartz_L_rejected() -> None:
    with pytest.raises(CronExpressionError):
        parse_cron("0 3 L * *")


def test_quartz_W_rejected() -> None:
    with pytest.raises(CronExpressionError):
        parse_cron("0 3 15W * *")


def test_empty_expression() -> None:
    with pytest.raises(CronExpressionError):
        parse_cron("")


def test_whitespace_only() -> None:
    with pytest.raises(CronExpressionError):
        parse_cron("   ")


def test_timezone_applied() -> None:
    t = parse_cron("0 3 * * *", timezone="Asia/Shanghai")
    assert "Asia/Shanghai" in str(t.timezone) or str(t.timezone).endswith("Shanghai")


# ---------------------------------------------------------------------------
# POSIX day-of-week translation (ADR-0007).
#
# POSIX cron: 0=Sunday .. 6=Saturday (7 also = Sunday). APScheduler 3.x treats
# 0=Monday (a historical mistake fixed only in v4). parse_cron must translate
# POSIX dow values to APScheduler dow values before constructing the trigger so
# Linux crontab lines paste correctly.
#
# weekday(): Monday=0 .. Sunday=6.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr,expected",
    [
        # POSIX 0=Sun -> APScheduler dow 6 -> next fire weekday()=6 (Sunday)
        ("0 2 * * 0", 6),
        # POSIX 1=Mon -> APScheduler dow 0 -> next fire weekday()=0 (Monday)
        ("0 2 * * 1", 0),
        # POSIX 6=Sat -> APScheduler dow 5 -> next fire weekday()=5 (Saturday)
        ("0 2 * * 6", 5),
        # POSIX 7 is also Sunday -> next fire weekday()=6 (Sunday)
        ("0 2 * * 7", 6),
    ],
)
def test_parse_cron_posix_dow_single_value(expr: str, expected: int) -> None:
    assert _next_weekday(expr) == expected


@pytest.mark.parametrize(
    "expr,allowed",
    [
        # Mon-Fri (POSIX 1-5). Next fire is a weekday.
        ("0 0 * * 1-5", {0, 1, 2, 3, 4}),
        # Wrap-around 6-0: Saturday or Sunday.
        ("0 0 * * 6-0", {5, 6}),
        # List 0,6: Saturday or Sunday.
        ("0 0 * * 0,6", {5, 6}),
    ],
)
def test_parse_cron_posix_dow_range_and_list(expr: str, allowed: set[int]) -> None:
    assert _next_weekday(expr) in allowed


@pytest.mark.parametrize(
    "expr,expected",
    [
        # POSIX names, case-insensitive.
        ("0 0 * * sun", 6),
        ("0 0 * * mon-fri", None),  # any weekday
        ("0 0 * * SAT", 5),
    ],
)
def test_parse_cron_posix_dow_names(expr: str, expected: int | None) -> None:
    if expected is None:
        assert _next_weekday(expr) in {0, 1, 2, 3, 4}
    else:
        assert _next_weekday(expr) == expected


def test_parse_cron_posix_dow_step() -> None:
    # POSIX */2 = {0,2,4,6} = Sun/Tue/Thu/Sat.
    assert _next_weekday("0 0 * * */2") in {6, 1, 3, 5}


def test_six_segment_posix_dow_sunday() -> None:
    # 6-segment: POSIX dow 0 = Sunday -> weekday() 6.
    assert _next_weekday("0 0 0 * * 0") == 6


def test_five_and_six_segment_same_day_of_week() -> None:
    # 5-seg "0 0 * * 0" and 6-seg "0 0 0 * * 0" must fire on the same day.
    assert _next_weekday("0 0 * * 0") == _next_weekday("0 0 0 * * 0")


def test_star_dow_still_works() -> None:
    # dow=* must keep working (every day).
    assert _next_weekday("* * * * *") in {0, 1, 2, 3, 4, 5, 6}


def test_dow_out_of_range_raises() -> None:
    with pytest.raises(CronExpressionError):
        parse_cron("0 0 * * 9")


def test_dow_unknown_name_raises() -> None:
    with pytest.raises(CronExpressionError):
        parse_cron("0 0 * * xyz")
