"""Per-job worker_init decorator + gp_context injection (per-job worker_init design).

A @worker_init function is a lazy, reusable initializer: it runs once per
execution context (main process for thread jobs, each worker process for process
jobs) on first execution, returns a single object, and gpscheduler injects that
object into the job function as ``gp_context``.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from gpscheduler.exceptions import SignatureContractError
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
