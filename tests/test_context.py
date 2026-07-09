"""Tests for @worker_init and the gp_context injection (per-job worker_init design)."""

from __future__ import annotations

from typing import Any

import pytest

import gpscheduler  # noqa: F401  (ensures config classes register)
from gpscheduler.context import _ContextualFunc, _reset_cache_for_test, worker_init
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


# --- _ContextualFunc wrapper + lazy cache -----------------------------------


@worker_init
def _make_handle() -> list[int]:
    # Return a fresh mutable so identity is observable across calls.
    return [42]


def _job_uses_context(x: int, *, gp_context: list[int]) -> list[int]:
    gp_context.append(x)
    return gp_context


# Register the job func so the wrapper can resolve it by dotted path at call
# time (mirrors how real @scheduled functions enter the registry).
registry.register(_job_uses_context)


def test_contextual_func_is_picklable() -> None:
    import pickle

    wf = _ContextualFunc(
        func_dotpath=f"{_job_uses_context.__module__}.{_job_uses_context.__qualname__}",
        worker_init_dotpath=f"{_make_handle.__module__}.{_make_handle.__qualname__}",
        job_name="job_a",
    )
    blob = pickle.dumps(wf)
    wf2 = pickle.loads(blob)
    assert wf2._job_name == "job_a"


def test_contextual_func_injects_gp_context_once() -> None:
    """First call runs init; second call reuses the cached object."""
    _reset_cache_for_test()
    wf = _ContextualFunc(
        func_dotpath=f"{_job_uses_context.__module__}.{_job_uses_context.__qualname__}",
        worker_init_dotpath=f"{_make_handle.__module__}.{_make_handle.__qualname__}",
        job_name="job_b",
    )
    r1 = wf(1)
    r2 = wf(2)
    # Same cached list object, both appends visible — proves reuse, not rebuild.
    assert r1 is r2
    assert r2 == [42, 1, 2]


def test_contextual_func_per_job_isolation() -> None:
    """Two jobs with the same init get independent cached objects."""
    _reset_cache_for_test()

    def _other_job(*, gp_context: list[int]) -> list[int]:
        return gp_context

    # Register _other_job so the wrapper can resolve it by dotted path.
    from gpscheduler.registry import registry as _reg

    _reg.register(_other_job)
    try:
        wa = _ContextualFunc(
            func_dotpath=f"{_job_uses_context.__module__}.{_job_uses_context.__qualname__}",
            worker_init_dotpath=f"{_make_handle.__module__}.{_make_handle.__qualname__}",
            job_name="iso_a",
        )
        wb = _ContextualFunc(
            func_dotpath=f"{_other_job.__module__}.{_other_job.__qualname__}",
            worker_init_dotpath=f"{_make_handle.__module__}.{_make_handle.__qualname__}",
            job_name="iso_b",
        )
        ra = wa(1)
        rb = wb()
        assert ra is not rb
    finally:
        # Best-effort cleanup of the temp registration.
        _reg._functions.pop(  # type: ignore[attr-defined]
            f"{_other_job.__module__}.{_other_job.__qualname__}", None
        )
