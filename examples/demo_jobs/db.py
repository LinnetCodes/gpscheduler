"""DB handler demo: shows worker_init + gp_context (the new feature).

This module demonstrates the recommended pattern for expensive objects:

* ``init_db_handler`` is decorated with ``@worker_init`` and builds a fake
  "DB handler" once per execution context. It reads its connection string from
  ``gp_globals`` (config data, picklable, flows IN from scheduler.yaml).
* ``ping_db`` is a ``@scheduled`` job that declares ``gp_context`` and reuses
  the handler the init built — it never reconstructs it.

Watch the output: the handler's ``connect_count`` stays at 1 across every run,
proving the init ran once and the object was reused. On a process-executor job,
each worker process builds its own handler (its own pid in the log line).
"""

from __future__ import annotations

import os
from typing import Any

from gpscheduler import scheduled, worker_init


@worker_init
def init_db_handler(*, gp_globals: dict[str, Any]) -> dict[str, Any]:
    """Build a fake DB handler once per execution context.

    Reads the connection string from ``gp_globals`` (injected from
    scheduler.yaml:job_globals). Returns a small dict acting as the "handler"
    so the reuse is observable via its ``connect_count``.

    In real code this would be a real connection/client object — possibly
    unpicklable, which is fine because it is built INSIDE the execution context
    and never crosses a process boundary.
    """
    db_url = gp_globals.get("db_url", "postgresql://localhost/demo")
    pid = os.getpid()
    print(f"[init_db_handler] opening connection to {db_url} (pid={pid})")
    return {"db_url": db_url, "pid": pid, "connect_count": 0}


@scheduled
def ping_db(*, gp_context: dict[str, Any]) -> None:
    """Reuse the handler built by init_db_handler; prove it's the same object."""
    gp_context["connect_count"] += 1
    print(
        f"[ping_db] connected to {gp_context['db_url']} "
        f"(pid={gp_context['pid']}, connect_count={gp_context['connect_count']})"
    )
