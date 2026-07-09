"""Per-job worker_init decorator + gp_context injection (per-job worker_init design).

Two pieces live here:

1. The ``@worker_init`` decorator: marks a module-level synchronous function as a
   lazy, reusable initializer. It runs once per execution context (main process
   for thread jobs, each worker process for process jobs) on first execution,
   returns a single object, and gpscheduler injects that object into the job
   function as ``gp_context``.

2. The ``_ContextualFunc`` wrapper: a picklable, callable class that APScheduler
   invokes. It lazy-builds the init object on first call (cached per job_name,
   thread-safe via a lock) and injects it as ``gp_context`` into the job
   function at call time. It stores only dot-path strings + job_name so it
   pickles cleanly into spawned process workers; the func and init function are
   re-resolved by dotted path at call time via the registry.
"""

from __future__ import annotations

import inspect
import threading
from collections.abc import Callable
from typing import Any, TypeVar

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
    """Enforce the worker_init signature contract + double-decoration prohibition."""
    if inspect.iscoroutinefunction(func):
        raise SignatureContractError(
            f"{func.__name__!r}: async functions are not supported (worker_init)."
        )

    if not inspect.isfunction(func):
        raise SignatureContractError(
            f"{func!r}: @worker_init requires a plain function, not a method or callable instance."
        )

    qualname = getattr(func, "__qualname__", "")
    if "<locals>" in qualname or "<lambda>" in qualname:
        raise SignatureContractError(
            f"{func.__name__!r}: @worker_init requires a module-level function, "
            "not a nested function or lambda."
        )

    module = inspect.getmodule(func)
    if module is None:
        raise SignatureContractError(f"{func!r}: could not resolve a defining module.")

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
    cached = _context_cache.get(job_name)
    if cached is not None:
        return cached
    with _context_lock:
        # Re-check inside the lock (another thread may have built it).
        cached = _context_cache.get(job_name)
        if cached is not None:
            return cached
        init_func = registry.get_init(worker_init_dotpath)
        # Inject gp_globals if the init function declares it.
        init_kwargs: dict[str, Any] = {}
        if "gp_globals" in inspect.signature(init_func).parameters and gp_globals is not None:
            init_kwargs["gp_globals"] = gp_globals
        obj = init_func(**init_kwargs)  # raises propagate; not cached on failure
        _context_cache[job_name] = obj
        return obj


class _ContextualFunc:
    """Picklable job wrapper: lazy-builds and injects the gp_context object.

    Stores only dot-path strings + job_name so it pickles cleanly into spawned
    process workers. func and the init function are re-resolved by dotted path
    at call time (registrations are rebuilt in each worker on package re-import).
    """

    def __init__(
        self,
        *,
        func_dotpath: str,
        worker_init_dotpath: str,
        job_name: str,
        gp_globals: dict[str, Any] | None = None,
    ) -> None:
        self._func_dotpath = func_dotpath
        self._worker_init_dotpath = worker_init_dotpath
        self._job_name = job_name
        self._gp_globals = gp_globals

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if GP_CONTEXT_KEY in kwargs:
            # Load-time guard should prevent this, but defend at runtime too.
            raise ReservedKeyError(
                f"{GP_CONTEXT_KEY!r} is reserved and must not be passed directly"
            )
        ctx = _get_or_create_context(self._job_name, self._worker_init_dotpath, self._gp_globals)
        kwargs[GP_CONTEXT_KEY] = ctx
        func = registry.get(self._func_dotpath)
        return func(*args, **kwargs)

    def __getstate__(self) -> dict[str, Any]:
        return {
            "_func_dotpath": self._func_dotpath,
            "_worker_init_dotpath": self._worker_init_dotpath,
            "_job_name": self._job_name,
            "_gp_globals": self._gp_globals,
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        self._func_dotpath = state["_func_dotpath"]
        self._worker_init_dotpath = state["_worker_init_dotpath"]
        self._job_name = state["_job_name"]
        self._gp_globals = state["_gp_globals"]


def _reset_cache_for_test() -> None:
    """Test helper: clear the module-level context cache."""
    _context_cache.clear()
