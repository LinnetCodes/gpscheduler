"""Per-job worker_init decorator + gp_context injection (per-job worker_init design).

Two pieces live here:

1. The ``@worker_init`` decorator: marks a module-level synchronous function as a
   lazy, reusable initializer. It runs once per execution context (main process
   for thread jobs, each worker process for process jobs) on first execution,
   returns a single object, and gpscheduler injects that object into the job
   function as ``gp_context``.

2. The ``_dispatch_contextual_job`` function: a module-level dispatcher that
   APScheduler invokes for worker_init jobs. It lazy-builds the init object on
   first call (cached per ``(scheduler_token, job_name)``, thread-safe via a
   lock) and injects it as ``gp_context`` into the job function at call time.
   The loader registers this function as ``job.func`` and passes the scheduler
   token + per-job dotpaths + job_name + ``gp_globals`` as leading positional
   args (all picklable); the func and init are re-resolved by dotted path at
   call time via the registry. A module-level function (not a callable instance)
   is required so APScheduler's ``obj_to_ref``/``ref_to_obj`` round-trip
   survives the process-pool pickle path.
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

#: Module-level cache keyed by (scheduler_token, job_name) -> init object. The
#: token is a per-GPScheduler UUID hex string (see GPScheduler.__init__), so two
#: schedulers in the same process with a job of the same name do NOT alias each
#: other's cached worker_init objects. On the thread side this cache lives in
#: the main process; after spawn each worker process has its own fresh module
#: state, so the cache is naturally per-worker. A None token is the legacy/no-
#: scheduler-context key (used by the loader when no scheduler is present, e.g.
#: in tests) and still participates in the (None, job_name) tuple.
_context_cache: dict[tuple[str | None, str], object] = {}
#: Ownership map: token -> set of job_names whose cache entries belong to that
#: scheduler. Populated lazily as _get_or_create_context stores objects; used by
#: _clear_owned_keys (called from GPScheduler.shutdown) to remove only this
#: scheduler's entries without touching a co-resident scheduler's.
_owned_keys_by_token: dict[str | None, set[str]] = {}
_context_lock = threading.Lock()

#: Per-key locks for worker_init initializers. Keyed by (token, job_name),
#: matching the cache key (logic.03). Different keys proceed in parallel; the
#: same key serializes to prevent double-init of one cache slot (perf.01).
#: Per-key locks are get-or-created under the short global _context_lock below.
_context_locks: dict[tuple[str | None, str], threading.Lock] = {}


def _register_owned_key(token: str | None, job_name: str) -> None:
    """Record that ``(token, job_name)`` is owned by ``token``'s scheduler.

    Acquires _context_lock internally so the ownership map and the cache stay in
    sync. Callers do NOT need to hold _context_lock (the previous contract had
    callers hold it because they were already inside the single critical section
    that ran the init; with per-key locking the init runs under a per-key lock,
    so this function takes _context_lock itself for the brief ownership update).
    """
    with _context_lock:
        _owned_keys_by_token.setdefault(token, set()).add(job_name)


def _clear_owned_keys(token: str | None) -> None:
    """Remove all cache entries owned by ``token`` (called from shutdown).

    Idempotent: a no-op if ``token`` owns no entries. Clears the cache, the
    ownership-map slot, AND the per-key locks for ``token``'s entries (so the
    lock map does not grow unboundedly across scheduler lifecycles). Co-resident
    schedulers' entries (under other tokens) are left untouched.

    Lock cleanup ordering note: popping a per-key lock here is safe even if
    another thread concurrently holds a reference to it from the get-or-create
    section — that thread will finish on the orphaned lock; new calls create a
    fresh lock. No correctness issue, just a momentary extra lock object.
    """
    with _context_lock:
        job_names = _owned_keys_by_token.pop(token, set())
        for name in job_names:
            _context_cache.pop((token, name), None)
            _context_locks.pop((token, name), None)


def _get_or_create_context(
    job_name: str,
    worker_init_dotpath: str,
    gp_globals: dict[str, Any] | None = None,
    *,
    context_cache_token: str | None = None,
) -> object:
    """Return the cached init object for ``(token, job_name)``, building it on miss.

    Thread-safe via per-key lock; different ``(token, job_name)`` keys initialize
    in parallel, same key serializes (prevents double-init of one cache slot).
    The per-key lock is get-or-created under a short global guard (_context_lock)
    whose critical section is just a dict lookup; the user's init function runs
    UNDER THE PER-KEY LOCK, NOT under _context_lock (perf.01). If the init
    function raises, the result is NOT cached — the next call retries. The cache
    key is the ``(token, job_name)`` tuple, so two GPScheduler instances with a
    same-named job but different worker_init functions get distinct cache entries
    AND distinct per-key locks (logic.03, Option A).
    """
    key: tuple[str | None, str] = (context_cache_token, job_name)
    # Fast path: already cached (dict.get is atomic for reads).
    cached = _context_cache.get(key, _CACHE_MISS)
    if cached is not _CACHE_MISS:
        return cached

    # Get-or-create the per-key lock under the SHORT GLOBAL GUARD. The critical
    # section is tiny (dict lookup + maybe Lock() construction). We deliberately
    # do NOT use dict.setdefault(key, Lock()) — that constructs a Lock on every
    # call even when one already exists, and (more importantly) the get-then-set
    # split is clearer about the intent and avoids any ambiguity around Lock
    # identity if two threads raced the setdefault (each would build a Lock,
    # setdefault keeps one, the other is orphaned).
    with _context_lock:
        per_key_lock = _context_locks.get(key)
        if per_key_lock is None:
            per_key_lock = threading.Lock()
            _context_locks[key] = per_key_lock

    # Run the initializer UNDER THE PER-KEY LOCK, not _context_lock. Different
    # keys proceed in parallel; the same key serializes (one waits, then sees
    # the cached result via the re-check below).
    with per_key_lock:
        # Re-check inside the per-key lock (another thread for the SAME key may
        # have just built and cached it).
        cached = _context_cache.get(key, _CACHE_MISS)
        if cached is not _CACHE_MISS:
            return cached
        init_func = registry.get_init(worker_init_dotpath)
        # Inject gp_globals if the init function declares it.
        init_kwargs: dict[str, Any] = {}
        if "gp_globals" in inspect.signature(init_func).parameters and gp_globals is not None:
            init_kwargs["gp_globals"] = gp_globals
        obj = init_func(**init_kwargs)  # raises propagate; not cached on failure
        _context_cache[key] = obj
        # Ownership tracking stays consistent with _clear_owned_keys (which also
        # takes _context_lock). _register_owned_key acquires _context_lock itself.
        _register_owned_key(context_cache_token, job_name)
        return obj


def _dispatch_contextual_job(
    context_cache_token: str | None,
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

    ``context_cache_token`` is the owning scheduler's UUID hex string; it leads
    the args so the cache key ``(token, job_name)`` isolates worker_init objects
    per scheduler (logic.03, Option A). It is a plain string, so it pickles
    cleanly into spawned worker processes where the scheduler object itself does
    not exist.

    On each call: lazy-builds the init object (cached per (token, job_name),
    thread-safe), injects it as ``gp_context``, re-resolves the job func by
    dotpath, and calls it. The func/init are re-resolved from the registry at
    call time — in a spawned worker, the process-pool initializer has re-imported
    ``packages`` so the registry is populated.
    """
    if GP_CONTEXT_KEY in kwargs:
        # Load-time guard should prevent this, but defend at runtime too.
        raise ReservedKeyError(f"{GP_CONTEXT_KEY!r} is reserved and must not be passed directly")
    ctx = _get_or_create_context(
        job_name, worker_init_dotpath, gp_globals, context_cache_token=context_cache_token
    )
    kwargs[GP_CONTEXT_KEY] = ctx
    func = registry.get(func_dotpath)
    return func(*args, **kwargs)


def _reset_cache_for_test() -> None:
    """Test helper: clear the module-level context cache, ownership map, and per-key locks."""
    _context_cache.clear()
    _owned_keys_by_token.clear()
    _context_locks.clear()
