"""Per-job worker_init decorator + gp_context injection (per-job worker_init design).

Two pieces live here:

1. The ``@worker_init`` decorator: marks a module-level synchronous function as a
   lazy, reusable initializer. It runs once per execution context (main process
   for thread jobs, each worker process for process jobs) on first execution,
   returns a single object, and gpscheduler injects that object into the job
   function as ``gp_context``.

2. The ``_dispatch_contextual_job`` function: a module-level dispatcher that
   APScheduler invokes for worker_init jobs. It lazy-builds the init object on
   first call (cached per job_name, thread-safe via a lock) and injects it as
   ``gp_context`` into the job function at call time. The loader registers this
   function as ``job.func`` and passes the per-job dotpaths + job_name +
   ``gp_globals`` as leading positional args (all picklable); the func and init
   are re-resolved by dotted path at call time via the registry. A module-level
   function (not a callable instance) is required so APScheduler's
   ``obj_to_ref``/``ref_to_obj`` round-trip survives the process-pool pickle
   path.
"""

from __future__ import annotations

import inspect
import threading
from collections.abc import Callable
from typing import Any, TypeVar

from gpscheduler._contract import _WORKER_INIT, _validate_common_contract
from gpscheduler.exceptions import ReservedKeyError, SignatureContractError
from gpscheduler.registry import registry

F = TypeVar("F", bound=Callable[..., Any])


def worker_init(func: F) -> F:
    """Mark a module-level synchronous function as a per-job worker_init initializer.

    Validates the signature contract (ADR-0003, extended for worker_init) and
    registers ``func`` in the worker_init registry under its dotted path.

    A function decorated with @worker_init may NOT also be @scheduled, and vice
    versa. Raises SignatureContractError on contract violation or double decoration.

    Raises:
        SignatureContractError: if ``func`` is async, a lambda, a nested function,
            a bound method, declares a ``gp_context`` parameter, or is already
            registered as a @scheduled function.
    """
    _validate_worker_init_contract(func)
    registry.register_init(func)
    return func


def _validate_worker_init_contract(func: Callable[..., Any]) -> None:
    """Enforce the worker_init signature contract + double-decoration prohibition.

    The five shared base checks (async, non-function, nested/lambda,
    class-body/method via qualname, module-resolution) live in
    :func:`gpscheduler._contract._validate_common_contract`; this function
    keeps only the kind-specific tail — the no-gp_context rule and the
    double-decoration ban against @scheduled.
    """
    _validate_common_contract(func, _WORKER_INIT)

    # worker_init must not declare gp_context (it produces the context, not consumes it).
    params = inspect.signature(func).parameters
    if "gp_context" in params:
        raise SignatureContractError(
            f"{func.__name__!r}: @worker_init functions must not declare 'gp_context' "
            "(that parameter is for job functions that consume the init result)."
        )

    # Double-decoration ban: a function already @scheduled cannot be @worker_init.
    dotted = f"{func.__module__}.{func.__qualname__}"
    if registry.contains(dotted):
        raise SignatureContractError(
            f"{func.__name__!r}: already registered as a @scheduled function; "
            "a function cannot be both @scheduled and @worker_init."
        )


#: Reserved kwarg name; job kwargs must not set it (injected at call time).
GP_CONTEXT_KEY = "gp_context"

#: Sentinel distinguishing "not yet cached" from a cached None return value.
_CACHE_MISS = object()

#: Module-level cache: job_name -> init object. On the thread side this lives in
#: the main process; after spawn each worker process has its own fresh module
#: state, so the cache is naturally per-worker.
_context_cache: dict[str, object] = {}
_context_lock = threading.Lock()


def _get_or_create_context(
    job_name: str,
    worker_init_dotpath: str,
    gp_globals: dict[str, Any] | None = None,
) -> object:
    """Return the cached init object for ``job_name``, building it on first miss.

    Thread-safe via _context_lock. If the init function raises, the result is NOT
    cached — the next call retries.
    """
    # Fast path: already cached.
    cached = _context_cache.get(job_name, _CACHE_MISS)
    if cached is not _CACHE_MISS:
        return cached
    with _context_lock:
        # Re-check inside the lock (another thread may have built it).
        cached = _context_cache.get(job_name, _CACHE_MISS)
        if cached is not _CACHE_MISS:
            return cached
        init_func = registry.get_init(worker_init_dotpath)
        # Inject gp_globals if the init function declares it.
        init_kwargs: dict[str, Any] = {}
        if "gp_globals" in inspect.signature(init_func).parameters and gp_globals is not None:
            init_kwargs["gp_globals"] = gp_globals
        obj = init_func(**init_kwargs)  # raises propagate; not cached on failure
        _context_cache[job_name] = obj
        return obj


def _dispatch_contextual_job(
    func_dotpath: str,
    worker_init_dotpath: str,
    job_name: str,
    gp_globals: dict[str, Any] | None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Module-level dispatcher APScheduler invokes for worker_init jobs.

    Replaces per-job ``_ContextualFunc`` instances: APScheduler stores job funcs
    by dotted-path reference (``func_ref``) and re-resolves them inside spawned
    workers via ``ref_to_obj``. A callable *instance* cannot survive that path —
    ``obj_to_ref(instance)`` returns the *class*, losing instance state. A
    module-level *function* resolves correctly, so the loader registers THIS
    function as ``job.func`` and passes the per-job dotpaths + job_name +
    ``gp_globals`` as leading positional args (all picklable: strings + dict).

    On each call: lazy-builds the init object (cached per job_name, thread-safe),
    injects it as ``gp_context``, re-resolves the job func by dotpath, and calls
    it. The func/init are re-resolved from the registry at call time — in a
    spawned worker, the process-pool initializer has re-imported ``packages`` so
    the registry is populated.
    """
    if GP_CONTEXT_KEY in kwargs:
        # Load-time guard should prevent this, but defend at runtime too.
        raise ReservedKeyError(f"{GP_CONTEXT_KEY!r} is reserved and must not be passed directly")
    ctx = _get_or_create_context(job_name, worker_init_dotpath, gp_globals)
    kwargs[GP_CONTEXT_KEY] = ctx
    func = registry.get(func_dotpath)
    return func(*args, **kwargs)


def _reset_cache_for_test() -> None:
    """Test helper: clear the module-level context cache."""
    _context_cache.clear()
