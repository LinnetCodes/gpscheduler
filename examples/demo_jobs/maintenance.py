"""Maintenance job: demonstrates enable: false (ADR-0005).

A job with ``enable: false`` in its YAML still goes through the FULL validation
pipeline — Registry lookup, cron parse, signature bind — but is excluded from
the returned job list, so APScheduler never registers it.

Why validate disabled jobs? Fail-Early: a typo in the func path or a stale cron
should fail loudly at load time, not silently rot until someone flips
``enable`` back to true.
"""

from __future__ import annotations

from gpscheduler import scheduled


@scheduled
def rebuild_index() -> None:
    """Pretend to rebuild a search index. Takes no arguments."""
    print("[rebuild_index] index rebuilt")
