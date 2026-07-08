"""The GPScheduler engine and convenience functions (ADR-0009/0012/0013).

GPScheduler composes (does not inherit) an APScheduler BackgroundScheduler,
always registering both a ``thread`` and a ``process`` named executor so each
job can pick its pool. gpclog is acquired from the main thread before the
scheduler thread starts (ADR-0012 threading constraint).
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from typing import TYPE_CHECKING, Any

import gpclog
from apscheduler.executors.pool import ProcessPoolExecutor, ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from gpconfig import GPConfigFolder, GPConfigManager, GPConfigurable
from gpconfig.exceptions import GPConfigError
from loguru import logger as loguru_logger

from gpscheduler.config import GPSchedulerConfig
from gpscheduler.exceptions import ConfigError
from gpscheduler.loader import load_jobs
from gpscheduler.signals import install_shutdown_handler

if TYPE_CHECKING:
    from pathlib import Path

#: Fixed gpclog logger name for scheduler-owned logs (ADR-0012).
LOGGER_NAME = "gpscheduler"


class InterceptHandler(logging.Handler):
    """Bridge stdlib ``logging`` records into loguru (ADR-0012)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame: Any = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        loguru_logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def bridge_apscheduler_logging() -> None:
    """Route APScheduler's stdlib logging into loguru (idempotent)."""
    aps_logger = logging.getLogger("apscheduler")
    aps_logger.handlers = [InterceptHandler()]
    aps_logger.propagate = False


def _process_init() -> None:
    """Per-worker gpclog (re)initialization for the process pool (ADR-0012)."""
    gpclog.get_logger(LOGGER_NAME, sn=os.getpid())


class GPScheduler(GPConfigurable):
    """A cron-style scheduler wrapping APScheduler's BackgroundScheduler."""

    def __init__(self, config: GPSchedulerConfig) -> None:
        super().__init__(config)
        # Acquire the logger in the main thread NOW (ADR-0012 cache constraint).
        self._logger = gpclog.get_logger(LOGGER_NAME)
        bridge_apscheduler_logging()
        self._scheduler: BackgroundScheduler = self._build_scheduler()
        self._stop_event: threading.Event = threading.Event()
        self._started = False

    @property
    def config(self) -> GPSchedulerConfig:
        # gpconfig is untyped; _config is Any. We store a GPSchedulerConfig, so
        # the cast is sound but mypy cannot verify it.
        return self._config  # type: ignore[no-any-return]

    @property
    def running(self) -> bool:
        return bool(self._scheduler.running)

    def register_jobs(self, loaded: list[Any]) -> None:
        """Register pre-loaded jobs (used by create_scheduler)."""
        for job in loaded:
            self._scheduler.add_job(
                func=job.func,
                trigger=job.trigger,
                args=list(job.args),
                kwargs=dict(job.kwargs),
                id=job.name,
                name=job.name,
                executor=job.executor,
                replace_existing=True,
            )

    def get_jobs(self) -> list[Any]:
        """Return currently-registered APScheduler jobs."""
        return list(self._scheduler.get_jobs())

    def start(self) -> None:
        """Start the BackgroundScheduler (returns immediately; background thread)."""
        if self._started:
            return
        self._logger.info("gpscheduler starting")
        self._scheduler.start()
        self._started = True

    def shutdown(self, timeout: float | None = None) -> None:
        """Gracefully shut down.

        Priority: ``timeout`` arg -> ``config.timeout`` -> wait forever (ADR-0008).
        """
        if not self._started:
            return
        resolved = timeout if timeout is not None else self.config.timeout
        self._logger.info(f"gpscheduler shutting down (timeout={resolved})")
        # APScheduler's shutdown(wait=True) has no timeout; we honor our own
        # timeout by waiting in a background thread and forcing exit on overrun.
        if resolved is None:
            self._scheduler.shutdown(wait=True)
        else:
            done = threading.Event()

            def _do_shutdown() -> None:
                try:
                    self._scheduler.shutdown(wait=True)
                finally:
                    done.set()

            t = threading.Thread(target=_do_shutdown, daemon=True)
            t.start()
            if not done.wait(timeout=float(resolved)):
                self._logger.warning(
                    f"shutdown timed out after {resolved}s; forcing exit "
                    "(running jobs may be interrupted)"
                )
                self._scheduler.shutdown(wait=False)
        self._started = False

    def run(self) -> None:
        """Start, block until a shutdown signal, then shut down (ADR-0008)."""
        self._stop_event.clear()
        install_shutdown_handler(self._stop_event)
        self.start()
        try:
            self._logger.info("gpscheduler running; waiting for shutdown signal")
            self._stop_event.wait()
        finally:
            self.shutdown()
        self._logger.info("gpscheduler stopped")

    # --- internals ----------------------------------------------------------

    def _build_scheduler(self) -> BackgroundScheduler:
        tz = self.config.timezone or None
        return BackgroundScheduler(
            executors={
                "thread": ThreadPoolExecutor(max_workers=self.config.max_workers),
                "process": ProcessPoolExecutor(
                    max_workers=self.config.max_workers,
                    pool_kwargs={"initializer": _process_init},
                ),
            },
            timezone=tz,
        )


def create_scheduler(
    cfg_folder: Path | str | None = None,
    project_name: str = "gpscheduler",
) -> GPScheduler:
    """Build a GPScheduler from a gpconfig folder.

    Initializes GPConfigManager, loads ``scheduler.yaml`` (GPSchedulerConfig),
    imports packages, loads + validates all jobs, and registers them.
    """
    try:
        manager = GPConfigManager(project_name, cfg_folder=cfg_folder)
    except GPConfigError as e:
        raise ConfigError(f"failed to initialize config manager: {e}") from e

    try:
        sched_config = manager.get_config("scheduler")
    except GPConfigError as e:
        raise ConfigError(f"failed to load scheduler config: {e}") from e

    if not isinstance(sched_config, GPSchedulerConfig):
        raise ConfigError(
            f"expected GPSchedulerConfig at 'scheduler', got {type(sched_config).__name__}"
        )

    scheduler = GPScheduler(sched_config)

    # Point gpclog at this manager's folder so users can configure logger YAMLs.
    with contextlib.suppress(Exception):
        # Non-fatal: gpclog falls back to default config.
        gpclog.set_config_folder(GPConfigFolder(manager, ""))

    try:
        loaded = load_jobs(
            manager=manager,
            registry=_get_registry(),
            sched_config=sched_config,
        )
    except GPConfigError as e:
        raise ConfigError(f"failed to load jobs: {e}") from e

    scheduler.register_jobs(loaded)
    return scheduler


def run_scheduler(scheduler: GPScheduler) -> None:
    """Run a built scheduler, blocking until a shutdown signal (ADR-0008)."""
    scheduler.run()


def _get_registry() -> Any:
    """Return the process-global registry (imported lazily to avoid cycles)."""
    from gpscheduler.registry import registry

    return registry
