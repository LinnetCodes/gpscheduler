"""Shared signature-contract validation for @scheduled and @worker_init.

Both decorators enforce the same five base checks (async rejection,
non-function rejection, nested/lambda rejection, class-body/method rejection
via qualname, and module-resolution). Their kind-specific tails
(double-decoration ban; worker_init's no-gp_context rule) live in their
own modules.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from gpscheduler.exceptions import SignatureContractError

# Decorator kind label for error messages.
_SCHEDULED = "@scheduled"
_WORKER_INIT = "@worker_init"


def _validate_common_contract(func: Callable[..., Any], decorator: str) -> None:
    """Validate the shared signature contract for @scheduled / @worker_init.

    Args:
        func: the function being decorated.
        decorator: ``"@scheduled"`` or ``"@worker_init"`` — used in error
            messages so the user knows which decorator rejected their function.

    Raises:
        SignatureContractError: if func is async, not a plain function, nested,
            a lambda, defined inside a class body, or has no resolvable module.
    """
    if inspect.iscoroutinefunction(func):
        raise SignatureContractError(
            f"{func.__name__!r}: async functions are not supported ({decorator})."
        )

    if not inspect.isfunction(func):
        raise SignatureContractError(
            f"{func!r}: {decorator} requires a plain function, "
            "not a method or callable instance."
        )

    qualname = getattr(func, "__qualname__", "")
    if "<locals>" in qualname or "<lambda>" in qualname:
        raise SignatureContractError(
            f"{func.__name__!r}: {decorator} requires a module-level function, "
            "not a nested function or lambda."
        )

    if "." in qualname:
        raise SignatureContractError(
            f"{func.__name__!r}: {decorator} requires a module-level function, "
            "not a class-body function or method."
        )

    module = inspect.getmodule(func)
    if module is None:
        raise SignatureContractError(
            f"{func!r}: could not resolve a defining module ({decorator})."
        )
