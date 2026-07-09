"""The @scheduled decorator (ADR-0003, ADR-0004).

A bare, parameterless decorator. At decoration time it performs syntax-level
hard checks (module-level plain synchronous function) and registers the
function in the global Registry. Scheduling information (cron, args, etc.)
comes entirely from config, never from the decorator.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from gpscheduler.exceptions import SignatureContractError
from gpscheduler.registry import registry

F = TypeVar("F", bound=Callable[..., Any])


def scheduled(func: F) -> F:
    """Mark a module-level synchronous function as schedulable.

    Performs syntax-level validation (ADR-0003) and registers ``func`` in the
    global Registry under ``f"{func.__module__}.{func.__qualname__}"``.

    Raises:
        SignatureContractError: if ``func`` is an async function, a lambda,
            a nested function, or a bound method.
    """
    _validate_signature_contract(func)
    registry.register(func)
    return func


def _validate_signature_contract(func: Callable[..., Any]) -> None:
    """Enforce the v1 signature contract: module-level plain sync function."""
    if inspect.iscoroutinefunction(func):
        raise SignatureContractError(
            f"{func.__name__!r}: async functions are not supported (ADR-0003)."
        )

    if not inspect.isfunction(func):
        # Catches bound methods (MethodType), builtins, callable instances, etc.
        raise SignatureContractError(
            f"{func!r}: @scheduled requires a plain function, "
            "not a method or callable instance (ADR-0003)."
        )

    qualname = getattr(func, "__qualname__", "")
    if "<locals>" in qualname or "<lambda>" in qualname:
        raise SignatureContractError(
            f"{func.__name__!r}: @scheduled requires a module-level function, "
            "not a nested function or lambda (ADR-0003)."
        )

    # Belt-and-suspenders: the defining module must own this function.
    module = inspect.getmodule(func)
    if module is None:
        raise SignatureContractError(f"{func!r}: could not resolve a defining module (ADR-0003).")
