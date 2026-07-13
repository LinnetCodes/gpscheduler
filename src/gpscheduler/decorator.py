"""The @scheduled decorator (ADR-0003, ADR-0004).

A bare, parameterless decorator. At decoration time it performs syntax-level
hard checks (module-level plain synchronous function) and registers the
function in the global Registry. Scheduling information (cron, args, etc.)
comes entirely from config, never from the decorator.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from gpscheduler._contract import _SCHEDULED, _validate_common_contract
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
    """Enforce the v1 signature contract: module-level plain sync function.

    The five shared base checks (async, non-function, nested/lambda,
    class-body/method via qualname, module-resolution) live in
    :func:`gpscheduler._contract._validate_common_contract`; this function
    keeps only the kind-specific tail — the double-decoration ban against
    @worker_init.
    """
    _validate_common_contract(func, _SCHEDULED)

    # Double-decoration ban: a function already @worker_init cannot be @scheduled.
    dotted = f"{func.__module__}.{func.__qualname__}"
    if registry.contains_init(dotted):
        raise SignatureContractError(
            f"{func.__name__!r}: already registered as a @worker_init function; "
            "a function cannot be both @scheduled and @worker_init."
        )
