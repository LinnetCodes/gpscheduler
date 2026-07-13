"""Tests for the GPScheduler engine and convenience functions (ADR-0009/0012/0013)."""

from __future__ import annotations

import signal
import threading
import time
from pathlib import Path

import pytest
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED  # noqa: F401

import gpscheduler  # noqa: F401  (registers config classes)
from gpscheduler import GPScheduler, GPSchedulerConfig, create_scheduler, run_scheduler
from gpscheduler.decorator import scheduled
from gpscheduler.exceptions import ConfigError, InvalidTimezoneError
from gpscheduler.scheduler import _process_init, bridge_apscheduler_logging


@scheduled
def _quick_task() -> int:
    return 42


@scheduled
def _counter_task() -> int:
    """Job whose execution count we verify in max_runs tests."""
    return 1


@scheduled
def _failing_task() -> None:
    """Job that raises; used to verify errors still count toward max_runs."""
    raise ValueError("boom")


def test_exported_from_package() -> None:
    for name in ("GPScheduler", "GPSchedulerConfig", "create_scheduler", "run_scheduler"):
        assert hasattr(gpscheduler, name)


def test_gpscheduler_is_gpconfigurable() -> None:
    from gpconfig import GPConfigurable

    assert issubclass(GPScheduler, GPConfigurable)


def test_construct_from_config() -> None:
    cfg = GPSchedulerConfig()
    s = GPScheduler(cfg)
    assert s.config is cfg


def test_start_and_shutdown_roundtrip() -> None:
    cfg = GPSchedulerConfig(timezone="UTC", max_workers=1, timeout=5)
    s = GPScheduler(cfg)
    s.start()
    try:
        assert s.running
    finally:
        s.shutdown()
    assert not s.running


def test_shutdown_timeout_argument_overrides_config() -> None:
    cfg = GPSchedulerConfig(timeout=5)
    s = GPScheduler(cfg)
    s.start()
    # shutdown(timeout=5) should exit quickly because there are no running jobs.
    s.shutdown(timeout=5)
    assert not s.running


def test_shutdown_force_exits_on_timeout() -> None:
    """If shutdown(wait=True) outlasts the timeout, force-exit via wait=False."""
    cfg = GPSchedulerConfig(timezone="UTC", max_workers=1, timeout=5)
    s = GPScheduler(cfg)
    s.start()

    # Patch _scheduler.shutdown so wait=True blocks (simulating a busy job),
    # while wait=False actually shuts the scheduler down. The timeout path must
    # call shutdown(wait=False) and then return within the timeout window.
    original_shutdown = s._scheduler.shutdown
    state = {"forced": False}

    def _fake_shutdown(wait: bool = True) -> None:
        if wait:
            # Simulate a job still running: never return until forced.
            # The timeout path will call us again with wait=False.
            time.sleep(20)
        else:
            state["forced"] = True
            original_shutdown(wait=False)

    s._scheduler.shutdown = _fake_shutdown  # type: ignore[method-assign]

    try:
        start = time.monotonic()
        s.shutdown(timeout=1)  # 1s timeout; wait=True would block ~20s
        elapsed = time.monotonic() - start
        assert elapsed < 5, f"shutdown took too long: {elapsed}s"
        assert state["forced"], "expected force-exit (shutdown(wait=False)) to be called"
        assert not s.running
    finally:
        # Restore in case of failure so the background thread can clean up.
        s._scheduler.shutdown = original_shutdown  # type: ignore[method-assign]
        # Ensure the daemon shutdown thread (stuck in time.sleep(20)) is gone.


def test_process_init_is_callable() -> None:
    # Should not raise; it's meant to run in worker processes.
    assert callable(_process_init)


def test_process_init_ignores_sigint() -> None:
    """ADR-0014: _process_init makes the worker ignore SIGINT.

    Runs _process_init in the test's main thread (a worker's initializer also
    runs in the worker's main thread, so this is faithful). It must leave SIGINT
    disposed as SIG_IGN so Ctrl+C never raises KeyboardInterrupt inside a worker
    (which dumps an ugly traceback on Windows). The previous disposition is
    restored so this does not leak into other tests.
    """
    previous = signal.getsignal(signal.SIGINT)
    try:
        _process_init()
        assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
    finally:
        signal.signal(signal.SIGINT, previous)


def test_bridge_logging_is_idempotent() -> None:
    # Calling twice must not error.
    bridge_apscheduler_logging()
    bridge_apscheduler_logging()


def test_create_scheduler_builds_instance(tmp_path: Path) -> None:
    # Build a minimal cfg_folder.
    cfg_folder = tmp_path / "cfg"
    (cfg_folder / "jobs").mkdir(parents=True)
    (cfg_folder / "global_env.yaml").write_text("project: test\n", encoding="utf-8")
    (cfg_folder / "scheduler.yaml").write_text(
        "cfg_class_name: GPSchedulerConfig\n"
        "configured_class_name: GPScheduler\n"
        "timezone: UTC\n"
        "max_workers: 1\n",
        encoding="utf-8",
    )
    quick_dotted = f"{_quick_task.__module__}.{_quick_task.__qualname__}"
    (cfg_folder / "jobs" / "quick.yaml").write_text(
        f"cfg_class_name: GPJobConfig\nfunc: {quick_dotted}\ncron: '* * * * *'\n",
        encoding="utf-8",
    )

    # create_scheduler must import packages (none here) and load jobs.
    s = create_scheduler(cfg_folder=cfg_folder, project_name="gpscheduler_test")
    assert isinstance(s, GPScheduler)
    s.start()
    try:
        # One job registered.
        jobs = s.get_jobs()
        assert len(jobs) == 1
    finally:
        s.shutdown(timeout=5)


def test_create_scheduler_with_no_jobs_folder_is_empty_schedule(tmp_path: Path) -> None:
    """ADR-0005: an absent jobs/ folder is legal and yields an empty schedule.

    Exercises the loader's ``except ConfigNotFoundError`` branch (no test in
    test_loader.py does, since those use a FakeManager). Here create_scheduler
    drives a real GPConfigManager, so this covers the real empty-folder path.
    """
    cfg_folder = tmp_path / "cfg"
    cfg_folder.mkdir(parents=True)
    (cfg_folder / "global_env.yaml").write_text("project: test\n", encoding="utf-8")
    (cfg_folder / "scheduler.yaml").write_text(
        "cfg_class_name: GPSchedulerConfig\n"
        "configured_class_name: GPScheduler\n"
        "timezone: UTC\n"
        "max_workers: 1\n",
        encoding="utf-8",
    )
    # Note: NO jobs/ folder created.

    s = create_scheduler(cfg_folder=cfg_folder, project_name="gpscheduler_test")
    assert isinstance(s, GPScheduler)
    assert s.get_jobs() == []


def test_run_scheduler_blocks_until_shutdown(monkeypatch, tmp_path: Path) -> None:
    cfg = GPSchedulerConfig(timezone="UTC", max_workers=1, timeout=5)
    s = GPScheduler(cfg)
    s.start()

    # Simulate a signal arriving almost immediately by pre-setting the event
    # the run loop waits on.
    def _fake_install(ev: threading.Event):
        ev.set()
        return lambda: ev.set()

    monkeypatch.setattr("gpscheduler.scheduler.install_shutdown_handler", _fake_install)

    # Should return promptly because the event is already set.
    start = time.monotonic()
    run_scheduler(s)
    elapsed = time.monotonic() - start
    assert elapsed < 10
    assert not s.running


def test_run_scheduler_keyboard_interrupt_exits_cleanly(monkeypatch) -> None:
    """Regression: run() must shut down gracefully when the wait loop is interrupted.

    On Windows the SIGINT handler is not reliably dispatched while the main
    thread blocks in Event.wait(), so the default KeyboardInterrupt path is
    the backstop. This simulates that path: the first wait() call raises
    KeyboardInterrupt, and run() must catch it, set the event, and shut down
    without re-raising. Covers the previously-untested interrupt branch.
    """
    cfg = GPSchedulerConfig(timezone="UTC", max_workers=1, timeout=5)
    s = GPScheduler(cfg)
    s.start()

    def _wait_then_interrupt(timeout=None):  # type: ignore[no-untyped-def]
        # First call (inside run()'s poll loop) raises as if Ctrl+C hit mid-wait.
        raise KeyboardInterrupt

    monkeypatch.setattr(s._stop_event, "wait", _wait_then_interrupt)

    start = time.monotonic()
    # Must NOT raise; the KeyboardInterrupt is caught inside run().
    run_scheduler(s)
    elapsed = time.monotonic() - start
    assert elapsed < 10
    assert not s.running
    # run() sets the stop event on interrupt; shutdown() in the finally block
    # does not depend on wait(), so it completes normally.
    assert s._stop_event.is_set()


def test_gpconfig_errors_translated_to_config_error(tmp_path: Path) -> None:
    # Point at a non-existent folder -> gpconfig raises ConfigFolderError (a GPConfigError).
    with pytest.raises(ConfigError):
        create_scheduler(cfg_folder=tmp_path / "does-not-exist", project_name="gpscheduler_test")


def test_invalid_timezone_translated_to_invalid_timezone_error() -> None:
    """A bad scheduler.yaml timezone must raise InvalidTimezoneError, not ZoneInfoNotFoundError.

    APScheduler's ``BackgroundScheduler(timezone=tz)`` raises
    ``ZoneInfoNotFoundError`` for a bogus IANA name. That escapes the GPSchedulerError
    hierarchy, so ``_build_scheduler`` must translate it at the source.
    """
    bad_tz = "Bogus/Nowhere"
    cfg = GPSchedulerConfig(timezone=bad_tz, max_workers=1)
    with pytest.raises(InvalidTimezoneError) as exc_info:
        GPScheduler(cfg)
    # The bad timezone name must appear in the message.
    assert bad_tz in str(exc_info.value)
    # The original error is preserved as __cause__.
    from zoneinfo import ZoneInfoNotFoundError

    assert isinstance(exc_info.value.__cause__, ZoneInfoNotFoundError)


def test_register_jobs_records_max_runs() -> None:
    """register_jobs stores max_runs so the listener can look it up by job_id."""
    from apscheduler.triggers.cron import CronTrigger

    from gpscheduler.loader import LoadedJob

    cfg = GPSchedulerConfig(timezone="UTC", max_workers=1)
    s = GPScheduler(cfg)
    trigger = CronTrigger.from_crontab("* * * * *")
    loaded = [
        LoadedJob(
            name="limited",
            func=_counter_task,
            trigger=trigger,
            args=[],
            kwargs={},
            executor="thread",
            max_runs=3,
        ),
        LoadedJob(
            name="unlimited",
            func=_counter_task,
            trigger=trigger,
            args=[],
            kwargs={},
            executor="thread",
            max_runs=None,
        ),
    ]
    s.register_jobs(loaded)
    assert s._job_max_runs == {"limited": 3, "unlimited": None}


def test_max_runs_removes_job_after_limit() -> None:
    """A job with max_runs=N is removed after exactly N executions."""
    from apscheduler.triggers.interval import IntervalTrigger

    from gpscheduler.loader import LoadedJob

    cfg = GPSchedulerConfig(timezone="UTC", max_workers=1)
    s = GPScheduler(cfg)
    # Fire immediately, every 0.1s.
    trigger = IntervalTrigger(seconds=0.1, start_date="2020-01-01")
    loaded = [
        LoadedJob(
            name="capped",
            func=_counter_task,
            trigger=trigger,
            args=[],
            kwargs={},
            executor="thread",
            max_runs=3,
        )
    ]
    s.register_jobs(loaded)
    s.start()
    try:
        # Wait long enough for 3 executions + the remove to process.
        time.sleep(2.0)
        # Job must be gone.
        job_ids = [j.id for j in s.get_jobs()]
        assert "capped" not in job_ids
        # Counter must be exactly 3 (>= would have removed at 3; no 4th run).
        assert s._run_counts.get("capped") == 3
    finally:
        s.shutdown(timeout=2)


def test_max_runs_none_means_unlimited() -> None:
    """A job with max_runs=None runs more than any small limit without removal."""
    from apscheduler.triggers.interval import IntervalTrigger

    from gpscheduler.loader import LoadedJob

    cfg = GPSchedulerConfig(timezone="UTC", max_workers=1)
    s = GPScheduler(cfg)
    trigger = IntervalTrigger(seconds=0.1, start_date="2020-01-01")
    loaded = [
        LoadedJob(
            name="forever",
            func=_counter_task,
            trigger=trigger,
            args=[],
            kwargs={},
            executor="thread",
            max_runs=None,
        )
    ]
    s.register_jobs(loaded)
    s.start()
    try:
        time.sleep(1.0)
        # Should have run several times and NOT been removed.
        job_ids = [j.id for j in s.get_jobs()]
        assert "forever" in job_ids
        assert s._run_counts.get("forever", 0) >= 3
    finally:
        s.shutdown(timeout=2)


def test_max_runs_counts_errors() -> None:
    """Q1 decision: a job that raises still counts toward max_runs."""
    from apscheduler.triggers.interval import IntervalTrigger

    from gpscheduler.loader import LoadedJob

    cfg = GPSchedulerConfig(timezone="UTC", max_workers=1)
    s = GPScheduler(cfg)
    trigger = IntervalTrigger(seconds=0.1, start_date="2020-01-01")
    loaded = [
        LoadedJob(
            name="fails",
            func=_failing_task,
            trigger=trigger,
            args=[],
            kwargs={},
            executor="thread",
            max_runs=2,
        )
    ]
    s.register_jobs(loaded)
    s.start()
    try:
        time.sleep(1.5)
        job_ids = [j.id for j in s.get_jobs()]
        assert "fails" not in job_ids
        assert s._run_counts.get("fails") == 2
    finally:
        s.shutdown(timeout=2)
