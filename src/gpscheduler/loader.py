"""Config loader / validator (ADR-0004/0005/0006/0013).

Walks the ``jobs/`` config folder via a GPConfigManager, resolves each
``GPJobConfig`` against the Registry, validates cron + signature + reserved
keys, and produces LoadedJob records the scheduler registers with APScheduler.
Designed for dependency injection: callers pass the manager, registry, an
import-packages callable, and the cron parser, so tests stay hermetic.
"""

from __future__ import annotations

import importlib
import inspect
import pickle
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from apscheduler.triggers.cron import CronTrigger

from gpscheduler.config import GPSchedulerConfig
from gpscheduler.context import GP_CONTEXT_KEY, _dispatch_contextual_job
from gpscheduler.cron import parse_cron
from gpscheduler.exceptions import (
    CronExpressionError,
    JobSignatureError,
    MaxRunsError,
    NotScheduledError,
    NotWorkerInitError,
    PackageImportError,
    ReservedKeyError,
)
from gpscheduler.registry import Registry

if TYPE_CHECKING:
    from gpconfig import GPConfigManager

#: Reserved kwarg name; job kwargs must not set it (ADR-0006).
GP_GLOBALS_KEY = "gp_globals"

ImportPackagesFn = Callable[[list[str]], None]
CronParserFn = Callable[[str, str | None], CronTrigger]


@dataclass
class LoadedJob:
    """A fully-validated, ready-to-register job."""

    name: str
    func: Callable[..., Any]
    trigger: CronTrigger
    args: list[Any]
    kwargs: dict[str, Any]
    executor: str
    enable: bool = True
    max_runs: int | None = None  # None = unlimited (ADR-0016)


def _default_import_packages(packages: list[str]) -> None:
    """Import each top-level package name so @scheduled side-effects fire."""
    for pkg in packages:
        try:
            importlib.import_module(pkg)
        except ModuleNotFoundError as e:
            raise PackageImportError(
                f"failed to import configured package {pkg!r} "
                f"(in scheduler.yaml:packages): {e}"
            ) from e


def _resolve_executor(job_executor: str | None, sched_executor: str) -> str:
    """ADR-0013 priority: job.executor -> sched.executor -> 'thread'."""
    return job_executor or sched_executor or "thread"


def _src(job_cfg: Any) -> str:
    """Format a config-file source prefix for error messages.

    gpconfig populates ``cfg_file_path`` on every loaded config (the absolute
    Path to the YAML file). Including it in error messages lets users locate
    which file is wrong — e.g. ``"jobs/compute_stats.yaml: invalid cron ..."``.
    Falls back to the job name if the path is absent (defensive; the loader
    always loads via the manager, which sets it).

    ``GPConfig`` defaults ``cfg_file_path`` to ``Path()`` (i.e. ``"."``) for
    in-memory / test-constructed configs, which is truthy but meaningless —
    treat it as absent so the fallback fires.
    """
    path = getattr(job_cfg, "cfg_file_path", None)
    if path is not None and Path(path) != Path():
        return f"{path}"
    name = getattr(job_cfg, "name", "<unknown>")
    return f"job {name!r}"


def _preflight_pickle(
    func: Callable[..., Any],
    args: list[Any],
    kwargs: dict[str, Any],
    src: str,
) -> None:
    """Ensure process-executor arguments are picklable (ADR-0013, Fail-Early)."""
    try:
        pickle.dumps((func, args, kwargs))
    except (pickle.PicklingError, TypeError, AttributeError) as e:
        raise JobSignatureError(
            f"{src}: process-executor job {getattr(func, '__qualname__', func)!r} has "
            f"non-picklable args/kwargs: {e}"
        ) from e


def _validate_max_runs(value: Any, src: str) -> int | None:
    """Validate a job's max_runs config value (ADR-0016).

    Returns the validated positive int, or None (unlimited). Raises
    MaxRunsError on: bool (checked first because bool is an int subclass),
    non-int (rejects float even if losslessly convertible), or <= 0.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise MaxRunsError(
            f"{src}: max_runs must be a positive integer, got bool {value!r}"
        )
    if not isinstance(value, int):
        raise MaxRunsError(
            f"{src}: max_runs must be a positive integer, got {type(value).__name__} {value!r}"
        )
    if value <= 0:
        raise MaxRunsError(
            f"{src}: max_runs must be a positive integer, got {value}"
        )
    return value


def load_jobs(
    *,
    manager: GPConfigManager,
    registry: Registry,
    sched_config: GPSchedulerConfig,
    import_packages: ImportPackagesFn = _default_import_packages,
    cron_parser: CronParserFn = parse_cron,
    context_cache_token: str | None = None,
) -> list[LoadedJob]:
    """Import packages, then load + validate every job under ``jobs/``.

    Validation runs for ALL jobs (enabled and disabled). Disabled jobs are
    validated but excluded from the returned list (ADR-0005).

    ``context_cache_token`` is the owning scheduler's UUID hex string; it is
    threaded into each worker_init job's dispatcher args so the per-scheduler
    cache key ``(token, job_name)`` isolates worker_init objects across
    co-resident schedulers (logic.03, Option A). ``None`` is the legacy/no-
    scheduler-context default (cache key ``(None, job_name)``).

    Raises:
        NotScheduledError, CronExpressionError, JobSignatureError,
        ReservedKeyError: on the first failing job (Fail-Early).
    """
    import_packages(sched_config.packages)

    from gpconfig.exceptions import ConfigNotFoundError

    # No jobs/ folder is legal -> empty schedule (ADR-0005); ConfigNotFoundError
    # means the folder simply isn't there. Any other gpconfig error propagates.
    try:
        job_names = manager.list_configs("jobs")
    except ConfigNotFoundError:
        job_names = []

    loaded: list[LoadedJob] = []
    # get_config auto-detects GPJobConfig via cfg_class_name (returns a
    # GPJobConfig instance for jobs/<name>.yaml).
    for name in job_names:
        job_cfg = manager.get_config(f"jobs.{name}")
        loaded_job = _validate_one(
            name=name,
            job_cfg=job_cfg,
            registry=registry,
            sched_config=sched_config,
            cron_parser=cron_parser,
            context_cache_token=context_cache_token,
        )
        if loaded_job.enable:
            loaded.append(loaded_job)
    return loaded


def _validate_one(
    *,
    name: str,
    job_cfg: Any,
    registry: Registry,
    sched_config: GPSchedulerConfig,
    cron_parser: CronParserFn,
    context_cache_token: str | None = None,
) -> LoadedJob:
    # Source identifier for error messages: the config file path (set by
    # gpconfig on every loaded config), so users can see WHICH file is wrong.
    src = _src(job_cfg)

    # (a) Registry lookup (ADR-0004 strict).
    func = _lookup(registry, job_cfg.func, src)

    # (a2) max_runs validation (ADR-0016).
    max_runs = _validate_max_runs(job_cfg.max_runs, src)

    # (b) Cron parse (ADR-0007). cron_parser is generic (no file context), so
    # catch and re-raise with the source path attached.
    try:
        trigger = cron_parser(job_cfg.cron, _tz(sched_config))
    except CronExpressionError as e:
        raise CronExpressionError(f"{src}: {e}") from e

    # (c) Reserved-key check (ADR-0006 + gp_context).
    if GP_GLOBALS_KEY in job_cfg.kwargs:
        raise ReservedKeyError(
            f"{src}: kwargs must not contain reserved key {GP_GLOBALS_KEY!r} (ADR-0006)"
        )
    if GP_CONTEXT_KEY in job_cfg.kwargs:
        raise ReservedKeyError(f"{src}: kwargs must not contain reserved key {GP_CONTEXT_KEY!r}")

    # (d) Conditional gp_globals injection (ADR-0006) — does the func declare it?
    effective_kwargs = dict(job_cfg.kwargs)
    if _signature_declares_gp_globals(func):
        effective_kwargs[GP_GLOBALS_KEY] = sched_config.job_globals

    # (e) worker_init resolution + gp_context contract (per-job worker_init design).
    func_params = inspect.signature(func).parameters
    # Fail-Early: gp_context and gp_globals are injected as KEYWORD args at call
    # time. A positional-only declaration (PEP 570: `def f(gp_context, /)`)
    # cannot receive them as keywords, so the first execution would raise
    # TypeError. Reject such signatures at load time instead (logic.02).
    # NOTE: gp_context is filtered out of the bind check below (injected by the
    # dispatcher), so the bind check alone cannot catch a positional-only
    # gp_context — this loop is the only guard for it.
    for _reserved in (GP_CONTEXT_KEY, GP_GLOBALS_KEY):
        if _reserved in func_params:
            _check_not_positional_only(func_params[_reserved], func, src, _reserved)
    declares_gp_context = GP_CONTEXT_KEY in func_params
    init_func: Callable[..., Any] | None = None
    if job_cfg.worker_init is not None:
        init_func = _lookup_init(registry, job_cfg.worker_init, src)
        # Resolved only to validate registration (raises NotWorkerInitError if
        # unregistered); the dispatcher re-resolves by dot-path at call time.
        if not declares_gp_context:
            raise JobSignatureError(
                f"{src}: worker_init is configured but the function "
                f"{func.__qualname__!r} does not declare a 'gp_context' parameter"
            )
        # Bind-validate the init function's signature (Fail-Early): gpscheduler
        # calls it as init_func() or init_func(gp_globals=...). Reject inits with
        # other required params now rather than at first execution.
        init_params = dict(inspect.signature(init_func).parameters)
        init_kwargs: dict[str, Any] = {}
        if GP_GLOBALS_KEY in init_params:
            init_kwargs[GP_GLOBALS_KEY] = sched_config.job_globals
        _bind_check_with_params(init_func, init_params, [], init_kwargs, src)
    elif declares_gp_context:
        raise JobSignatureError(
            f"{src}: function {func.__qualname__!r} declares 'gp_context' "
            "but no worker_init is configured"
        )

    # (f) signature.bind (ADR-0003). gp_context is injected at call time by the
    # dispatcher, so exclude it from the bind check (user never supplies it).
    bind_params = {k: v for k, v in func_params.items() if k != GP_CONTEXT_KEY}
    _bind_check_with_params(func, bind_params, job_cfg.args, effective_kwargs, src)

    # (g) Dispatch via the module-level _dispatch_contextual_job if worker_init
    # is set. APScheduler stores job.func as a dotted-path reference (func_ref)
    # and re-resolves it in spawned workers; a callable INSTANCE cannot survive
    # that (obj_to_ref returns the class, losing instance state), so we register
    # a module-level FUNCTION as job.func and pass the per-job dotpaths +
    # job_name + gp_globals as leading positional args (all picklable). The
    # scheduler's context_cache_token leads the args so the dispatcher's cache
    # key is (token, job_name) — isolating worker_init objects per scheduler
    # (logic.03, Option A).
    effective_func: Callable[..., Any] = func
    effective_args: list[Any] = list(job_cfg.args)
    if init_func is not None:
        effective_func = _dispatch_contextual_job
        effective_args = [
            context_cache_token,
            job_cfg.func,
            job_cfg.worker_init,
            name,
            sched_config.job_globals,
            *effective_args,
        ]

    # (h) executor resolution + pickle preflight for process jobs (ADR-0013).
    executor = _resolve_executor(job_cfg.executor, sched_config.executor)
    if executor == "process":
        _preflight_pickle(effective_func, effective_args, effective_kwargs, src)

    return LoadedJob(
        name=name,
        func=effective_func,
        trigger=trigger,
        args=effective_args,
        kwargs=effective_kwargs,
        executor=executor,
        enable=job_cfg.enable,
        max_runs=max_runs,
    )


def _tz(sched_config: GPSchedulerConfig) -> str | None:
    return sched_config.timezone or None


def _lookup(registry: Registry, dotted: str, src: str) -> Callable[..., Any]:
    try:
        return registry.get(dotted)
    except KeyError:
        raise NotScheduledError(
            f"{src}: func {dotted!r} is not registered. "
            "Is the function decorated with @scheduled and its package imported?"
        ) from None


def _lookup_init(registry: Registry, dotted: str, src: str) -> Callable[..., Any]:
    try:
        return registry.get_init(dotted)
    except KeyError:
        raise NotWorkerInitError(
            f"{src}: worker_init {dotted!r} is not a registered "
            "@worker_init function. Is the function decorated with @worker_init "
            "and its package imported?"
        ) from None


def _signature_declares_gp_globals(func: Callable[..., Any]) -> bool:
    sig = inspect.signature(func)
    params = sig.parameters
    return GP_GLOBALS_KEY in params


def _check_not_positional_only(
    param: inspect.Parameter,
    func: Callable[..., Any],
    src: str,
    name: str,
) -> None:
    """Reject positional-only declarations of reserved keyword parameters.

    ``gp_context`` and ``gp_globals`` are injected as keyword arguments at call
    time, so a positional-only declaration (PEP 570) cannot receive them — the
    first execution would raise ``TypeError``. Fail at load time instead
    (logic.02).
    """
    if param.kind is inspect.Parameter.POSITIONAL_ONLY:
        raise JobSignatureError(
            f"{src}: function {func.__qualname__!r} declares {name!r} as "
            f"positional-only, but gpscheduler injects it as a keyword. "
            "Declare it as a regular or keyword-only parameter."
        )


def _bind_check_with_params(
    func: Callable[..., Any],
    params: dict[str, inspect.Parameter],
    args: list[Any],
    kwargs: dict[str, Any],
    src: str,
) -> None:
    """Bind-check args/kwargs against ``params`` (a filtered signature.parameters).

    Used to exclude gp_context, which is injected at call time, not supplied by config.
    """
    try:
        inspect.Signature(parameters=list(params.values())).bind(*args, **kwargs)
    except TypeError as e:
        raise JobSignatureError(
            f"{src}: arguments do not bind to {func.__qualname__!r}: {e}"
        ) from e
