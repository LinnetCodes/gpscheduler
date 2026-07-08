"""Tests for the GPScheduler engine and convenience functions (ADR-0009/0012/0013)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

import gpscheduler  # noqa: F401  (registers config classes)
from gpscheduler import GPScheduler, GPSchedulerConfig, create_scheduler, run_scheduler
from gpscheduler.decorator import scheduled
from gpscheduler.exceptions import ConfigError
from gpscheduler.scheduler import _process_init, bridge_apscheduler_logging


@scheduled
def _quick_task() -> int:
    return 42


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


def test_gpconfig_errors_translated_to_config_error(tmp_path: Path) -> None:
    # Point at a non-existent folder -> gpconfig raises ConfigFolderError (a GPConfigError).
    with pytest.raises(ConfigError):
        create_scheduler(cfg_folder=tmp_path / "does-not-exist", project_name="gpscheduler_test")
