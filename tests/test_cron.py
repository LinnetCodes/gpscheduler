"""Tests for the cron parser (ADR-0007)."""

from __future__ import annotations

import pytest
from apscheduler.triggers.cron import CronTrigger

from gpscheduler.cron import parse_cron
from gpscheduler.exceptions import CronExpressionError


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
