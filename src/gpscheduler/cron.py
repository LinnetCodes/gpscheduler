"""Cron expression parsing (ADR-0007).

Supports variable 5/6-segment expressions. 5 segments are standard crontab
(``minute hour day month day_of_week``, second implicit 0); 6 segments add an
explicit leading second field. Only the POSIX special characters ``* , - /``
are accepted — APScheduler's own field validation rejects Quartz extensions
(``L``/``W``/``#``), surfaced here as CronExpressionError.

Day-of-week uses POSIX numbering (0=Sunday .. 6=Saturday; 7 also = Sunday).
APScheduler 3.x historically treats 0 as Monday instead, so the ``day_of_week``
field is translated before the trigger is constructed — see
https://github.com/agronholm/apscheduler/issues/286.
"""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger

from gpscheduler.exceptions import CronExpressionError

# POSIX day-of-week names -> POSIX int (0=Sunday .. 6=Saturday).
_POSIX_DOW_NAMES = {
    "sun": 0, "sunday": 0,
    "mon": 1, "monday": 1,
    "tue": 2, "tues": 2, "tuesday": 2,
    "wed": 3, "weds": 3, "wednesday": 3,
    "thu": 4, "thur": 4, "thurs": 4, "thursday": 4,
    "fri": 5, "friday": 5,
    "sat": 6, "saturday": 6,
}


def _normalize_posix_dow_value(value: int) -> int:
    """Normalize a single POSIX dow int, mapping 7 -> 0 (both = Sunday)."""
    if value == 7:
        return 0
    if not 0 <= value <= 7:
        raise ValueError(f"day-of-week value out of range: {value}")
    return value


def _parse_dow_field_to_posix_ints(field: str) -> set[int]:
    """Parse a single dow field string into a set of POSIX ints (0-6).

    7 is normalized to 0. Supports ``*``, ``*/n``, ``a-b`` (including
    wrap-around like ``6-0``), ``a-b/n``, single values, case-insensitive
    3-letter / full names, and comma-separated lists of any of the above.
    """
    field = field.lower()
    out: set[int] = set()
    for item in field.split(","):
        out |= _parse_dow_item(item)
    return out


def _parse_dow_item(item: str) -> set[int]:
    """Parse one comma-separated piece of a dow field into POSIX ints."""
    if item == "*":
        return {0, 1, 2, 3, 4, 5, 6}

    # Range with optional step: a-b, a-b/n.
    if "-" in item and not item.startswith("-"):
        base, sep, step_part = item.partition("/")
        step = int(step_part) if step_part else 1
        if step <= 0:
            raise ValueError(f"day-of-week step must be positive: {item!r}")
        start_s, end_s = base.split("-", 1)
        start = _parse_dow_atom(start_s)
        end = _parse_dow_atom(end_s)
        return _expand_posix_range(start, end, step)

    # Step on its own (e.g. ``*/2`` is handled above; ``/n`` is invalid).
    if item.startswith("*/"):
        n = int(item[2:])
        if n <= 0:
            raise ValueError(f"day-of-week step must be positive: {item!r}")
        return {i for i in range(7) if i % n == 0}

    # Plain value (int or name). Note: a bare ``5/2`` form is rejected by
    # APScheduler anyway, so we don't synthesize it here.
    return {_normalize_posix_dow_value(_parse_dow_atom(item))}


def _parse_dow_atom(atom: str) -> int:
    """Parse a single dow atom (no list/range/step) to a POSIX int 0-7."""
    atom = atom.strip()
    if not atom:
        raise ValueError("empty day-of-week value")
    if atom.lower() in _POSIX_DOW_NAMES:
        return _POSIX_DOW_NAMES[atom.lower()]
    # Must be a base-10 integer; 0-7 (7 = Sunday, normalized later).
    value = int(atom)  # raises ValueError on garbage like "xyz"
    if not 0 <= value <= 7:
        raise ValueError(f"day-of-week value out of range: {value}")
    return value


def _expand_posix_range(start: int, end: int, step: int) -> set[int]:
    """Expand a POSIX dow range, handling wrap-around (e.g. 6-0 -> {6,0})."""
    start = _normalize_posix_dow_value(start)
    end = _normalize_posix_dow_value(end)
    # When start > end (e.g. 6-0), wrap through 7 (Sunday-as-7), then normalize 7 -> 0.
    raw = range(start, end + 1, step) if start <= end else range(start, end + 8, step)
    return {_normalize_posix_dow_value(v) for v in raw}


def _translate_posix_dow(field: str) -> str:
    """Translate a POSIX dow field to APScheduler dow numbering.

    APScheduler 3.x treats 0 as Monday; POSIX (Linux crontab) treats 0 as
    Sunday. Formula: ``aps = (posix + 6) % 7``. Returns a canonical
    comma-joined list of APScheduler ints, or ``"*"`` unchanged. On any parse
    failure the original field is returned so APScheduler surfaces its own
    validation error.
    """
    field = field.strip().lower()
    if field == "*":
        return "*"
    try:
        posix_values = _parse_dow_field_to_posix_ints(field)
        aps_values = {(p + 6) % 7 for p in posix_values}
        return ",".join(str(v) for v in sorted(aps_values))
    except (ValueError, KeyError, AttributeError):
        # If parsing fails, return the original field unchanged and let
        # APScheduler's own validation surface a meaningful error.
        return field


def parse_cron(expr: str, timezone: str | None = None) -> CronTrigger:
    """Parse a 5/6-segment cron expression into a CronTrigger.

    Args:
        expr: The cron expression. 5 segments = ``min hour day month dow``;
            6 segments = ``sec min hour day month dow``. The dow field uses
            POSIX numbering (0=Sunday .. 6=Saturday; 7 also = Sunday), matching
            Linux crontab semantics.
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
            segments[4] = _translate_posix_dow(segments[4])
            return CronTrigger.from_crontab(" ".join(segments), timezone=tz)
        if count == 6:
            second, minute, hour, day, month, day_of_week = segments
            day_of_week = _translate_posix_dow(day_of_week)
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
