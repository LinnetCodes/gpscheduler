"""Cross-process integration tests for worker_init (Task 9).

These exercise the real ``ProcessPoolExecutor`` spawn path end-to-end through
``create_scheduler``: the ``_ContextualFunc`` wrapper is pickled into a spawned
worker, the worker's process-pool initializer imports the configured ``packages``
(re-firing ``@worker_init``/``@scheduled`` registration), and the init function
runs once per worker with the object reused across subsequent runs.

Marked ``slow`` because spawning a process pool and waiting for cron triggers is
heavyweight relative to the unit tests.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from gpscheduler import create_scheduler

#: The on-disk test package name. Must be importable in the spawned worker,
#: which re-imports it by name (a ``__main__``-local function cannot be
#: re-imported under spawn — the proven limitation from the design phase).
_PKG = "_gpsched_xproc_fixture"


def _write_fixture_pkg(pkg_root: Path, results_file: Path) -> str:
    """Write a small importable package under ``pkg_root`` and return its name.

    The package defines a ``@worker_init`` function that counts how many times
    it has run (via a module-level counter) and a ``@scheduled`` job that
    appends a JSON snapshot to ``results_file`` (shared with the test process
    via the filesystem — the only cross-process channel that doesn't need
    pickling of live objects). Both register into the process-global registry
    at import.
    """
    pkg_dir = pkg_root / _PKG
    pkg_dir.mkdir(parents=True)
    # __init__ must import the submodules so @scheduled/@worker_init registration
    # fires when the top-level package is imported (mirrors examples/demo_jobs).
    (pkg_dir / "__init__.py").write_text(
        f"from {_PKG} import jobs  # noqa: F401  (register decorators)\n",
        encoding="utf-8",
    )
    # Pass the results path via an env var the fixture reads at import, so the
    # job module doesn't need the path baked into its source.
    (pkg_dir / "jobs.py").write_text(_JOBS_SRC, encoding="utf-8")
    return _PKG


#: Source of the fixture jobs module. Defined as a module-level constant at
#: column 0 so ruff format doesn't touch its indentation (textwrap.dedent would
#: break if ruff stripped trailing whitespace from the blank lines). The job
#: appends a JSON snapshot per run so the test can observe cross-process state.
_JOBS_SRC = """\
import json
import os
import threading
from gpscheduler import scheduled, worker_init

# Path the job appends JSON results to (set by the test via env var).
_RESULTS_FILE = os.environ.get("_GPSCHED_XPROC_RESULTS", "")

# Module-level, thread-safe records of what happened in THIS process.
_lock = threading.Lock()
init_runs = 0


@worker_init
def make_handle() -> dict:
    global init_runs
    with _lock:
        init_runs += 1
        return {"init_runs": init_runs}


@scheduled
def use_handle(*, gp_context: dict) -> None:
    snapshot = {"init_runs": gp_context["init_runs"], "pid": os.getpid()}
    if _RESULTS_FILE:
        with open(_RESULTS_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot) + "\\n")
"""


@pytest.mark.slow
def test_process_job_worker_init_runs_once_per_worker(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end via create_scheduler: process worker_init runs once, reused.

    Builds a real scheduler with a process-executor job whose ``worker_init``
    counts its invocations. Lets the job fire at least twice (6-segment cron,
    every second), then asserts:
    - both runs succeed (the spawn/pickle/re-resolve + worker-package-import
      path works);
    - ``init_runs`` is 1 on BOTH runs (init ran once, object reused).
    """
    pkg_root = tmp_path_factory.mktemp("xproc_pkgs")
    results_file = tmp_path_factory.mktemp("xproc_out") / "results.jsonl"
    # The spawned worker inherits env, so it sees this path and writes there.
    monkeypatch.setenv("_GPSCHED_XPROC_RESULTS", str(results_file))

    pkg_name = _write_fixture_pkg(pkg_root, results_file)
    pkg_root_str = str(pkg_root)

    added = pkg_root_str not in sys.path
    if added:
        sys.path.insert(0, pkg_root_str)
    try:
        cfg_folder = tmp_path_factory.mktemp("xproc_cfg")
        (cfg_folder / "jobs").mkdir(parents=True)
        (cfg_folder / "global_env.yaml").write_text("project: test\n", encoding="utf-8")
        (cfg_folder / "scheduler.yaml").write_text(
            "cfg_class_name: GPSchedulerConfig\n"
            "configured_class_name: GPScheduler\n"
            "timezone: UTC\n"
            "max_workers: 1\n"
            f"packages:\n  - {pkg_name}\n",
            encoding="utf-8",
        )
        (cfg_folder / "jobs" / "xproc.yaml").write_text(
            "cfg_class_name: GPJobConfig\n"
            f"func: {pkg_name}.jobs.use_handle\n"
            f"worker_init: {pkg_name}.jobs.make_handle\n"
            "cron: '* * * * * *'\n"  # 6-segment: every second
            "executor: process\n",
            encoding="utf-8",
        )

        scheduler = create_scheduler(cfg_folder=str(cfg_folder), project_name="gpscheduler_test")
        scheduler.start()
        try:
            # Wait for at least 2 firings (cron fires every second).
            deadline = time.monotonic() + 20
            while _count_lines(results_file) < 2 and time.monotonic() < deadline:
                time.sleep(0.2)
        finally:
            scheduler.shutdown(timeout=5)

        snapshots = _read_snapshots(results_file)
        assert len(snapshots) >= 2, f"job did not fire twice: {len(snapshots)} runs"
        # init ran exactly once in the worker (not once per call).
        assert snapshots[0]["init_runs"] == 1, f"first run init_runs={snapshots[0]['init_runs']!r}"
        assert snapshots[1]["init_runs"] == 1, f"second run init_runs={snapshots[1]['init_runs']!r}"
        # Same worker reused the object: same pid across runs (single-worker pool).
        assert snapshots[0]["pid"] == snapshots[1]["pid"], "expected same worker pid"
    finally:
        if added:
            sys.path.remove(pkg_root_str)
        sys.modules.pop(f"{pkg_name}.jobs", None)
        sys.modules.pop(pkg_name, None)


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def _read_snapshots(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    snapshots: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                snapshots.append(json.loads(line))
    return snapshots
