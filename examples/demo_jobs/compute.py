"""Compute job demo: worker_init + the PROCESS executor (the trickiest path).

This module shows that ``worker_init`` works across the process pool's spawn
boundary — the hardest path, and the one most likely to break silently.

* ``init_stats_client`` is a ``@worker_init`` that builds a fake stats client
  once per worker process. It reads config from ``gp_globals``.
* ``compute_stats`` is a ``@scheduled`` job that runs in the PROCESS pool
  (executor: process) and reuses the client via ``gp_context``.

Watch the output: ``init_stats_client`` prints once per worker process on its
first run, then ``compute_stats`` reuses the same client (client_id stays the
same across runs within a worker). This proves the spawn + func_ref + worker
package-import path all work end-to-end.

Process-executor constraints (enforced at load time by the loader's pickle
preflight): the job's args/kwargs must be picklable. The heavy object built by
the init is NOT pickled — it's constructed inside the worker, so it can be any
type (sockets, locks, etc.).
"""

from __future__ import annotations

import os
import random
from typing import Any

from gpscheduler import scheduled, worker_init


@worker_init
def init_stats_client(*, gp_globals: dict[str, Any]) -> dict[str, Any]:
    """Build a fake stats client once per worker process.

    In real code this could be a network client or a loaded ML model —
    expensive to build, reused across runs. Here it's a dict with a random id
    so reuse is observable (the id stays the same across runs in the same
    worker process).
    """
    api_key = gp_globals.get("api_key", "<none>")
    pid = os.getpid()
    client_id = random.randint(1000, 9999)  # noqa: S311 (demo only)
    print(f"[init_stats_client] built client {client_id} (api_key={api_key}, pid={pid})")
    return {"client_id": client_id, "pid": pid, "calls": 0}


@scheduled
def compute_stats(dataset: str, *, iterations: int = 1000, gp_context: dict[str, Any]) -> None:
    """Pretend to do CPU-heavy work on ``dataset``, reusing the stats client."""
    gp_context["calls"] += 1
    total = sum(i * i for i in range(iterations))
    print(
        f"[compute_stats] dataset={dataset!r} sum={total} "
        f"(client_id={gp_context['client_id']}, pid={gp_context['pid']}, "
        f"calls={gp_context['calls']})"
    )
