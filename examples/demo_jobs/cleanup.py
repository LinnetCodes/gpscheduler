"""Cleanup job: demonstrates job_globals injection (ADR-0006).

The ``gp_globals`` parameter tells gpscheduler "this job wants the scheduler's
``job_globals`` dict." At load time the loader detects this parameter and
injects ``scheduler.yaml:job_globals`` into the job's kwargs automatically.

Important: ``gp_globals`` must NEVER appear in a job's YAML ``kwargs`` — it is a
reserved key. The loader raises ``ReservedKeyError`` if you try to set it
manually. Only declaring the parameter triggers injection.
"""

from __future__ import annotations

from typing import Any

from gpscheduler import scheduled


@scheduled
def cleanup(retention_days: int, *, gp_globals: dict[str, Any]) -> None:
    """Pretend to delete files older than ``retention_days``.

    Args:
        retention_days: Age threshold in days (positional, from ``args``).
        gp_globals: Injected by the scheduler. NEVER set this in YAML kwargs;
            the function signature is what triggers injection.
    """
    target_dir = gp_globals.get("work_dir", "/tmp")
    print(f"[cleanup] would remove files older than {retention_days} day(s) from {target_dir}")
