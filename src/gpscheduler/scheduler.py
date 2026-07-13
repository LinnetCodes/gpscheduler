"""The GPScheduler engine and convenience functions (ADR-0009/0012/0013/0014).

GPScheduler composes (does not inherit) an APScheduler BackgroundScheduler,
always registering both a ``thread`` and a ``process`` named executor so each
job can pick its pool. gpclog is acquired from the main thread before the
scheduler thread starts (ADR-0012 threading constraint).
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import threading
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from zoneinfo import ZoneInfoNotFoundError

import gpclog
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.executors.pool import ProcessPoolExecutor, ThreadPoolExecutor
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.background import BackgroundScheduler
from gpconfig import GPConfigFolder, GPConfigManager, GPConfigurable
from gpconfig.exceptions import GPConfigError
from loguru import logger as loguru_logger

from gpscheduler import context
from gpscheduler.config import GPSchedulerConfig
from gpscheduler.exceptions import ConfigError, InvalidTimezoneError
from gpscheduler.loader import _default_import_packages, load_jobs
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
    """Per-worker gpclog (re)initialization + SIGINT disposition (ADR-0012/0014)."""
    gpclog.get_logger(LOGGER_NAME, sn=os.getpid())
    # Workers must NOT respond to Ctrl+C. On Windows, Ctrl+C is broadcast to the
    # whole process group; an uninterruptible worker would raise KeyboardInterrupt
    # and dump an ugly traceback from its call_queue.get() block. On POSIX spawn,
    # workers can inherit the main process's custom SIGINT handler (which would
    # reference a stop_event the worker doesn't own). Ignoring SIGINT in every
    # worker (both OSes) keeps the shutdown flow in the main process exclusively,
    # consistent with ADR-0008's "main process owns signals" architecture. See
    # ADR-0014 for the full rationale.
    signal.signal(signal.SIGINT, signal.SIG_IGN)


class _ProcessWorkerInitializer:
    """Picklable process-pool initializer: gpclog + SIG_IGN + import packages.

    Runs in every spawned worker on start. Does the work of ``_process_init``
    (gpclog + SIG_IGN, ADR-0012/0014) AND imports the configured ``packages`` so
    the worker's process-global Registry is populated — required for
    ``worker_init`` jobs, whose ``_ContextualFunc`` wrapper re-resolves the
    init/func by dotted path via the Registry at call time. Without this, a
    spawned worker's Registry is empty and ``registry.get``/``get_init`` raise
    ``KeyError``.

    Must be a module-level class (not a closure) so it pickles by reference
    into spawned workers — the same picklability constraint as
    ``_ContextualFunc``. ``packages`` is a list of strings (picklable).
    """

    def __init__(self, packages: list[str]) -> None:
        self._packages = list(packages)

    def __call__(self) -> None:
        _process_init()
        _default_import_packages(self._packages)

    def __getstate__(self) -> dict[str, object]:
        return {"_packages": self._packages}

    def __setstate__(self, state: dict[str, object]) -> None:
        self._packages = state["_packages"]  # type: ignore[assignment]


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
        # Per-scheduler UUID token used as the leading half of the worker_init
        # cache key (logic.03, Option A). A fresh hex string per instance means
        # two GPScheduler instances with a same-named job get isolated cache
        # entries, and rebuild-after-shutdown cannot pick up a stale cached
        # object. A str (not id(self)) so it pickles cleanly into spawned worker
        # processes where the scheduler object does not exist.
        self._context_cache_token: str = uuid4().hex
        # max_runs counting (ADR-0016).
        self._run_counts: dict[str, int] = {}
        self._job_max_runs: dict[str, int | None] = {}
        self._run_counts_lock = threading.Lock()
        self._scheduler.add_listener(
            self._on_job_run, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )

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
            # Record max_runs for the listener (ADR-0016). Defaults to None
            # (unlimited) if the LoadedJob predates the field.
            self._job_max_runs[job.name] = getattr(job, "max_runs", None)

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
                # APScheduler marks itself stopped before waiting in
                # shutdown(wait=True), so by now the background thread may have
                # already transitioned the scheduler to STOPPED — in which case
                # this second shutdown(wait=False) raises SchedulerNotRunningError.
                # Swallow it: the goal is best-effort forced exit; if APScheduler
                # is already stopped, the goal is met. (logic.01)
                try:
                    self._scheduler.shutdown(wait=False)
                except SchedulerNotRunningError:
                    self._logger.debug("scheduler already stopped when forcing exit")
        # Drop this scheduler's worker_init cache entries (logic.03, Option C).
        # In the main process this keeps a rebuild-from-new-config from reusing
        # a stale cached object; in spawned workers each worker owns its own
        # module state so this clear is process-local and harmless there.
        context._clear_owned_keys(self._context_cache_token)
        self._started = False

    def run(self) -> None:
        """Start, block until a shutdown signal, then shut down (ADR-0008)."""
        self._stop_event.clear()
        install_shutdown_handler(self._stop_event)
        self.start()
        try:
            self._logger.info("gpscheduler running; waiting for shutdown signal")
            # Poll with a short timeout instead of an indefinite wait. On Windows,
            # CPython only dispatches SIGINT between bytecode instructions on the
            # main thread; an indefinite Event.wait() blocks in
            # WaitForSingleObject and is not reliably woken, so Ctrl+C fails to
            # interrupt `gpscheduler run`. A periodic timeout lets the main
            # thread wake and observe the event set by the signal handler. On
            # POSIX the event also wakes promptly (its wait is signal-interrupt
            # regardless), so the poll is harmless there. KeyboardInterrupt is
            # caught as a backstop: if the handler is bypassed and the default
            # SIGINT path fires instead, the exception still breaks us out.
            while not self._stop_event.wait(timeout=0.2):
                pass
        except KeyboardInterrupt:
            self._logger.info("gpscheduler interrupted (Ctrl+C); shutting down")
            self._stop_event.set()
        finally:
            self.shutdown()
        self._logger.info("gpscheduler stopped")

    # --- internals ----------------------------------------------------------

    def _on_job_run(self, event: Any) -> None:
        """max_runs listener: increment count, remove job when limit reached (ADR-0016).

        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR both count (Q1: trigger-then-count).
        MISSED is not subscribed, so skipped runs don't count. All jobs are
        counted (including unlimited ones, ``max_runs=None``) for observability;
        only the removal check is skipped when there is no limit.
        """
        job_id = event.job_id
        limit = self._job_max_runs.get(job_id)
        with self._run_counts_lock:
            self._run_counts[job_id] = self._run_counts.get(job_id, 0) + 1
            count = self._run_counts[job_id]
        if limit is None:
            return  # unlimited: count recorded, but never removed
        if count >= limit:
            self._logger.info(f"job {job_id!r} reached max_runs={limit}, removing")
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                # Job may already be gone (shutdown in progress, or a concurrent
                # event already removed it). APScheduler's _dispatch_event swallows
                # listener exceptions (base.py:1041) and logs them at ERROR level;
                # we catch here to log at DEBUG instead, avoiding noise for this
                # expected boundary. Not a silent swallow: it is logged.
                self._logger.debug(f"job {job_id!r} already removed or scheduler stopping")

    def _build_scheduler(self) -> BackgroundScheduler:
        tz = self.config.timezone or None
        try:
            return BackgroundScheduler(
                executors={
                    "thread": ThreadPoolExecutor(max_workers=self.config.max_workers),
                    "process": ProcessPoolExecutor(
                        max_workers=self.config.max_workers,
                        pool_kwargs={"initializer": self._make_process_initializer()},
                    ),
                },
                timezone=tz,
            )
        except ZoneInfoNotFoundError as e:
            raise InvalidTimezoneError(
                f"configured timezone {self.config.timezone!r} "
                f"(in scheduler.yaml:timezone) is not a valid IANA timezone name: {e}"
            ) from e

    def _make_process_initializer(self) -> _ProcessWorkerInitializer:
        """Build a picklable process-pool initializer for this scheduler.

        Returns a ``_ProcessWorkerInitializer`` instance carrying the configured
        ``packages``. The initializer runs in every spawned worker on start:
        gpclog + SIG_IGN (ADR-0012/0014) plus importing ``packages`` so the
        worker's Registry is populated for ``worker_init`` jobs.
        """
        return _ProcessWorkerInitializer(self.config.packages)


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
            context_cache_token=scheduler._context_cache_token,
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
