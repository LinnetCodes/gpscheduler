"""Tests for @worker_init and the gp_context injection (per-job worker_init design)."""

from __future__ import annotations

from typing import Any

import pytest

import gpscheduler  # noqa: F401  (ensures config classes register)
from gpscheduler.context import worker_init
from gpscheduler.decorator import scheduled
from gpscheduler.exceptions import SignatureContractError
from gpscheduler.registry import registry

# --- @worker_init decorator contract ---------------------------------------


@worker_init
def _good_init() -> object:
    return object()


def test_worker_init_registers_into_init_map() -> None:
    key = f"{_good_init.__module__}.{_good_init.__qualname__}"
    assert registry.contains_init(key)
    assert not registry.contains(key)  # not in the scheduled map


def test_worker_init_rejects_async_function() -> None:
    with pytest.raises(SignatureContractError):

        @worker_init
        async def _bad() -> object:  # type: ignore[unused-variable]
            return object()


def test_worker_init_rejects_lambda() -> None:
    with pytest.raises(SignatureContractError):
        worker_init(lambda: object())  # type: ignore[arg-type]


def test_worker_init_rejects_nested_function() -> None:
    def _outer() -> None:
        @worker_init
        def _nested() -> object:
            return object()

    with pytest.raises(SignatureContractError):
        _outer()


def test_worker_init_rejects_gp_context_parameter() -> None:
    with pytest.raises(SignatureContractError):

        @worker_init
        def _bad(gp_context: Any) -> object:  # type: ignore[unused-variable]
            return gp_context


@worker_init
def _ok_gp_globals(gp_globals: dict[str, Any]) -> object:  # type: ignore[unused-variable]
    return object()


def test_worker_init_allows_gp_globals_parameter() -> None:
    assert registry.contains_init(f"{_ok_gp_globals.__module__}.{_ok_gp_globals.__qualname__}")


# --- double-decoration ban --------------------------------------------------


@scheduled
def _scheduled_func() -> None:
    pass


def test_cannot_decorate_scheduled_function_as_worker_init() -> None:
    """A function already @scheduled cannot also be @worker_init."""
    with pytest.raises(SignatureContractError):
        worker_init(_scheduled_func)


def test_cannot_decorate_worker_init_function_as_scheduled() -> None:
    """A function already @worker_init cannot also be @scheduled."""
    with pytest.raises(SignatureContractError):
        scheduled(_good_init)
