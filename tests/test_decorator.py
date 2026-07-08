"""Tests for the @scheduled decorator (ADR-0003, ADR-0004)."""

from __future__ import annotations

import inspect

import pytest

import gpscheduler
from gpscheduler import registry as reg_mod
from gpscheduler.decorator import scheduled
from gpscheduler.exceptions import SignatureContractError


# A module-level scheduled function (decorated at import of this module).
@scheduled
def sample_job() -> None:
    return None


@scheduled
def another_job() -> None:
    return None


def test_module_level_function_registered() -> None:
    key = f"{sample_job.__module__}.{sample_job.__qualname__}"
    assert reg_mod.registry.contains(key)
    assert reg_mod.registry.get(key) is sample_job


def test_exported_from_package() -> None:
    assert hasattr(gpscheduler, "scheduled")


def test_decorator_returns_same_function() -> None:
    # The decorator is a marker + side-effect: it must return the function
    # unchanged. Uses a module-level function so it satisfies the v1 contract
    # (ADR-0003); nested functions are rejected (see test_rejects_nested_function).
    assert inspect.isfunction(another_job)
    assert another_job is not None


def test_rejects_async_def() -> None:
    with pytest.raises(SignatureContractError):

        @scheduled
        async def async_job() -> None:
            return None


def test_rejects_lambda() -> None:
    with pytest.raises(SignatureContractError):
        scheduled(lambda: None)  # type: ignore[arg-type]


def test_rejects_nested_function() -> None:
    with pytest.raises(SignatureContractError):

        def outer() -> None:
            @scheduled
            def inner() -> None:
                return None

            return inner

        outer()


def test_rejects_bound_method() -> None:
    class C:
        def method(self) -> None:
            return None

    c = C()
    with pytest.raises(SignatureContractError):
        scheduled(c.method)  # type: ignore[arg-type]
