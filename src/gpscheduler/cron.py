"""Cron expression parsing (ADR-0007).

Supports variable 5/6-segment expressions. 5 segments are standard crontab
(``minute hour day month day_of_week``, second implicit 0); 6 segments add an
explicit leading second field. Only the POSIX special characters ``* , - /``
are accepted — APScheduler's own field validation rejects Quartz extensions
(``L``/``W``/``#``), surfaced here as CronExpressionError.
"""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger

from gpscheduler.exceptions import CronExpressionError


def parse_cron(expr: str, timezone: str | None = None) -> CronTrigger:
    """Parse a 5/6-segment cron expression into a CronTrigger.

    Args:
        expr: The cron expression. 5 segments = ``min hour day month dow``;
            6 segments = ``sec min hour day month dow``.
        timezone: Optional timezone name (e.g. ``"Asia/Shanghai"``). ``None``
            or empty means APScheduler's local default.

    Raises:
        CronExpressionError: if the segment count is not 5 or 6, or any field
            value is invalid (range, illegal character, Quartz extension).
    """
    if not expr or not expr.strip():
        raise CronExpressionError("cron expression is empty")

    tz = timezone if timezone else None
    segments = expr.split()
    count = len(segments)

    try:
        if count == 5:
            return CronTrigger.from_crontab(expr, timezone=tz)
        if count == 6:
            second, minute, hour, day, month, day_of_week = segments
            return CronTrigger(
                second=second,
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=tz,
            )
    except ValueError as e:
        raise CronExpressionError(f"invalid cron expression {expr!r}: {e}") from e

    raise CronExpressionError(
        f"invalid cron expression {expr!r}: expected 5 or 6 fields, got {count}"
    )
