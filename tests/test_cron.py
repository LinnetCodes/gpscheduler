"""Tests for the cron parser (ADR-0007)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from apscheduler.triggers.cron import CronTrigger

from gpscheduler.cron import _parse_dow_field_to_posix_ints, parse_cron
from gpscheduler.exceptions import CronExpressionError


def _next_weekday(expr: str) -> int:
    """Build a trigger from ``expr`` and return the weekday() of its next fire.

    Uses datetime.weekday(): Monday=0 .. Sunday=6.
    """
    t = parse_cron(expr)
    nt = t.get_next_fire_time(None, datetime.now())
    assert nt is not None, f"no next fire time for {expr!r}"
    return nt.weekday()


def _seven_fire_weekdays(*triggers: CronTrigger) -> tuple[set[int], ...]:
    """Sample the next 7 fire times from each trigger; return their weekday sets.

    Each trigger fires daily, so the 7 weekdays should cover the whole week.
    """
    now = datetime.now()
    results: list[set[int]] = []
    for trig in triggers:
        days: list[datetime] = []
        for _ in range(7):
            prev = days[-1] + timedelta(seconds=1) if days else now
            nxt = trig.get_next_fire_time(None, prev)
            assert nxt is not None
            days.append(nxt)
        results.append({d.weekday() for d in days})
    return tuple(results)


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


# ---------------------------------------------------------------------------
# POSIX wrap-around dow ranges and 0-7 full-week handling.
#
# Per Vixie cron / `man 5 crontab`, ranges may wrap past Sunday: `5-1` means
# Fri+Sat+Sun+Mon. `0-7` and `1-7` both span the full week inclusively because
# 7 is also Sunday.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,expected",
    [
        # Multi-day wrap-around (was crashing before the fix).
        ("5-1", {0, 1, 5, 6}),
        ("4-2", {0, 1, 2, 4, 5, 6}),
        # 3-1 = Wed..Mon wrapping = full week minus Tue(2).
        ("3-1", {0, 1, 3, 4, 5, 6}),
        # Single wrap day (was already correct).
        ("6-0", {0, 6}),
        # Full week via inclusive Sunday endpoints.
        ("0-7", {0, 1, 2, 3, 4, 5, 6}),
        ("1-7", {0, 1, 2, 3, 4, 5, 6}),
        ("0-6", {0, 1, 2, 3, 4, 5, 6}),
        # Sunday-only via either endpoint.
        ("7-7", {0}),
        ("0-0", {0}),
    ],
)
def test_parse_dow_field_posix_range_expansion(field: str, expected: set[int]) -> None:
    assert _parse_dow_field_to_posix_ints(field) == expected


@pytest.mark.parametrize(
    "expr,allowed",
    [
        # 5-1: Fri, Sat, Sun, Mon -> weekday() in {4, 5, 6, 0}.
        ("0 0 * * 5-1", {0, 4, 5, 6}),
        # 4-2: Thu, Fri, Sat, Sun, Mon, Tue -> weekday() in {3, 4, 5, 6, 0, 1}.
        ("0 0 * * 4-2", {0, 1, 3, 4, 5, 6}),
    ],
)
def test_parse_cron_posix_wraparound_range_fires_on_expected_days(
    expr: str, allowed: set[int]
) -> None:
    assert _next_weekday(expr) in allowed


def test_parse_cron_posix_full_week_0_7_matches_star() -> None:
    # `0-7` is the full week and must fire every day, like `*`.
    star = parse_cron("0 0 * * *")
    full = parse_cron("0 0 * * 0-7")
    star_weekdays, full_weekdays = _seven_fire_weekdays(star, full)
    assert star_weekdays == full_weekdays == {0, 1, 2, 3, 4, 5, 6}


def test_parse_cron_posix_full_week_1_7_matches_star() -> None:
    # `1-7` is also the full week (parity with `0-7`).
    star = parse_cron("0 0 * * *")
    full = parse_cron("0 0 * * 1-7")
    star_weekdays, full_weekdays = _seven_fire_weekdays(star, full)
    assert star_weekdays == full_weekdays == {0, 1, 2, 3, 4, 5, 6}
