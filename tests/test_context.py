"""Tests for @worker_init and the gp_context injection (per-job worker_init design)."""

from __future__ import annotations

from typing import Any

import pytest

import gpscheduler  # noqa: F401  (ensures config classes register)
from gpscheduler.context import _dispatch_contextual_job, _reset_cache_for_test, worker_init
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


# --- class-body functions and methods (qualname contains ".") -----------------
# ADR-0003 promises module-level plain functions only. A function defined in a
# class body has __qualname__ like "C.m" — the "." distinguishes it from a true
# module-level function and must be rejected (gap.02).


class _ClassBodyHolder:
    def method(self) -> object:
        return object()

    @staticmethod
    def static_method() -> object:
        return object()


@pytest.mark.parametrize(
    ("label", "func"),
    [
        # 1. A function defined directly in a class body (accessed via the class,
        #    a plain function whose __qualname__ is "_ClassBodyHolder.method").
        ("class-body-function", _ClassBodyHolder.method),
        # 2. A staticmethod (accessed via the class, a plain function whose
        #    __qualname__ is "_ClassBodyHolder.static_method").
        ("staticmethod", _ClassBodyHolder.static_method),
        # 3. A bound instance method (already caught by the non-function check;
        #    included as a regression guard for the refactor in structure.01).
        ("bound-instance-method", _ClassBodyHolder().method),
    ],
    ids=["class-body-function", "staticmethod", "bound-instance-method"],
)
def test_worker_init_rejects_class_body_function_and_method(label: str, func: Any) -> None:
    """@worker_init must reject class-body functions and methods (gap.02)."""
    with pytest.raises(SignatureContractError):
        worker_init(func)  # type: ignore[arg-type]


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


# --- _dispatch_contextual_job + lazy cache ----------------------------------


@worker_init
def _make_handle() -> list[int]:
    # Return a fresh mutable so identity is observable across calls.
    return [42]


def _job_uses_context(x: int, *, gp_context: list[int]) -> list[int]:
    gp_context.append(x)
    return gp_context


# Module-level holders for the gp_globals-injection and None-init regression
# tests. Defined at module scope because @worker_init rejects nested functions;
# the tests reset + read these instead of closing over locals.
_gp_globals_received: dict[str, Any] = {}


@worker_init
def _capturing_init(gp_globals: dict[str, Any]) -> dict[str, Any]:
    _gp_globals_received.update(gp_globals)
    return gp_globals


_none_init_call_count = [0]


@worker_init
def _none_init() -> None:
    _none_init_call_count[0] += 1
    return None


# Register the job func so the dispatcher can resolve it by dotted path at call
# time (mirrors how real @scheduled functions enter the registry).
registry.register(_job_uses_context)

# Dotpaths reused across tests (module-level so the registry lookup resolves).
_JOB_DOT = f"{_job_uses_context.__module__}.{_job_uses_context.__qualname__}"
_INIT_DOT = f"{_make_handle.__module__}.{_make_handle.__qualname__}"


def test_dispatch_survives_obj_to_ref_roundtrip() -> None:
    """APScheduler stores job.func as a func_ref; a module-level function resolves."""
    from apscheduler.util import obj_to_ref, ref_to_obj

    ref = obj_to_ref(_dispatch_contextual_job)
    resolved = ref_to_obj(ref)
    assert resolved is _dispatch_contextual_job


def test_dispatch_injects_gp_context_once() -> None:
    """First call runs init; second call reuses the cached object."""
    _reset_cache_for_test()
    r1 = _dispatch_contextual_job("test-token", _JOB_DOT, _INIT_DOT, "job_b", None, 1)
    r2 = _dispatch_contextual_job("test-token", _JOB_DOT, _INIT_DOT, "job_b", None, 2)
    # Same cached list object, both appends visible — proves reuse, not rebuild.
    assert r1 is r2
    assert r2 == [42, 1, 2]


def test_dispatch_per_job_isolation() -> None:
    """Two jobs with the same init get independent cached objects."""
    _reset_cache_for_test()

    def _other_job(*, gp_context: list[int]) -> list[int]:
        return gp_context

    from gpscheduler.registry import registry as _reg

    _reg.register(_other_job)
    try:
        other_dot = f"{_other_job.__module__}.{_other_job.__qualname__}"
        ra = _dispatch_contextual_job("test-token", _JOB_DOT, _INIT_DOT, "iso_a", None, 1)
        rb = _dispatch_contextual_job("test-token", other_dot, _INIT_DOT, "iso_b", None)
        assert ra is not rb
    finally:
        _reg._functions.pop(  # type: ignore[attr-defined]
            f"{_other_job.__module__}.{_other_job.__qualname__}", None
        )


def test_dispatch_injects_gp_globals_into_init() -> None:
    """An init func declaring gp_globals receives the scheduler's job_globals."""
    _reset_cache_for_test()
    _gp_globals_received.clear()

    def _job_needing_ctx(*, gp_context: dict[str, Any]) -> dict[str, Any]:
        return gp_context

    from gpscheduler.registry import registry as _reg

    _reg.register(_job_needing_ctx)
    try:
        job_dot = f"{_job_needing_ctx.__module__}.{_job_needing_ctx.__qualname__}"
        init_dot = f"{_capturing_init.__module__}.{_capturing_init.__qualname__}"
        result = _dispatch_contextual_job(
            "test-token",
            job_dot,
            init_dot,
            "gp_globals_test",
            {"db_url": "sqlite:///x", "limit": 100},
        )
        assert _gp_globals_received == {"db_url": "sqlite:///x", "limit": 100}
        assert result == {"db_url": "sqlite:///x", "limit": 100}
    finally:
        _reg._functions.pop(  # type: ignore[attr-defined]
            f"{_job_needing_ctx.__module__}.{_job_needing_ctx.__qualname__}", None
        )


def test_dispatch_none_returning_init_runs_once() -> None:
    """Regression: a None-returning init must still only run once (cache sentinel)."""
    _reset_cache_for_test()
    _none_init_call_count[0] = 0

    def _job_none_ctx(*, gp_context: Any) -> None:
        return None

    from gpscheduler.registry import registry as _reg

    _reg.register(_job_none_ctx)
    try:
        job_dot = f"{_job_none_ctx.__module__}.{_job_none_ctx.__qualname__}"
        init_dot = f"{_none_init.__module__}.{_none_init.__qualname__}"
        _dispatch_contextual_job("test-token", job_dot, init_dot, "none_init_test", None)
        _dispatch_contextual_job("test-token", job_dot, init_dot, "none_init_test", None)
        _dispatch_contextual_job("test-token", job_dot, init_dot, "none_init_test", None)
        assert _none_init_call_count[0] == 1  # init ran exactly once despite returning None
    finally:
        _reg._functions.pop(  # type: ignore[attr-defined]
            f"{_job_none_ctx.__module__}.{_job_none_ctx.__qualname__}", None
        )


# --- per-scheduler cache isolation (token-keyed cache) ---------------------
#
# The module-level _context_cache is keyed by (token, job_name) so that two
# GPScheduler instances in the same process (each with its own worker_init
# functions) do NOT alias each other's cached objects, and so that
# shutdown() of one scheduler clears only its own entries.


@worker_init
def _init_alpha() -> dict[str, str]:
    return {"which": "ALPHA"}


@worker_init
def _init_beta() -> dict[str, str]:
    return {"which": "BETA"}


_ALPHA_DOT = f"{_init_alpha.__module__}.{_init_alpha.__qualname__}"
_BETA_DOT = f"{_init_beta.__module__}.{_init_beta.__qualname__}"


def test_cross_scheduler_isolation_via_tokens() -> None:
    """Two tokens + same job_name + different inits must NOT alias (logic.03 Option A)."""
    _reset_cache_for_test()
    from gpscheduler.context import _get_or_create_context

    obj_a = _get_or_create_context("shared", _ALPHA_DOT, context_cache_token="tok-a")
    obj_b = _get_or_create_context("shared", _BETA_DOT, context_cache_token="tok-b")
    assert obj_a is not obj_b  # not aliased
    assert obj_a == {"which": "ALPHA"}
    assert obj_b == {"which": "BETA"}


_same_token_call_count = [0]


@worker_init
def _counting_init() -> dict[str, int]:
    _same_token_call_count[0] += 1
    return {"ran": _same_token_call_count[0]}


_COUNTING_DOT = f"{_counting_init.__module__}.{_counting_init.__qualname__}"


def test_same_token_caches_init_once() -> None:
    """Same token + same job_name + same init: init runs exactly once, object reused."""
    _reset_cache_for_test()
    _same_token_call_count[0] = 0
    from gpscheduler.context import _get_or_create_context

    first = _get_or_create_context("once-job", _COUNTING_DOT, context_cache_token="tok-x")
    second = _get_or_create_context("once-job", _COUNTING_DOT, context_cache_token="tok-x")
    assert first is second
    assert _same_token_call_count[0] == 1


_fail_once_state = {"calls": 0}


@worker_init
def _flaky_init() -> str:
    _fail_once_state["calls"] += 1
    if _fail_once_state["calls"] == 1:
        raise RuntimeError("boom on first call")
    return "ok-after-retry"


_FLAKY_DOT = f"{_flaky_init.__module__}.{_flaky_init.__qualname__}"


def test_init_failure_not_cached_under_token() -> None:
    """A first-call failure must not be cached; the second call succeeds (existing contract)."""
    _reset_cache_for_test()
    _fail_once_state["calls"] = 0
    from gpscheduler.context import _get_or_create_context

    with pytest.raises(RuntimeError, match="boom on first call"):
        _get_or_create_context("flaky-job", _FLAKY_DOT, context_cache_token="tok-f")
    # Second call succeeds and returns the object (failure was not cached).
    result = _get_or_create_context("flaky-job", _FLAKY_DOT, context_cache_token="tok-f")
    assert result == "ok-after-retry"


def test_clear_owned_keys_clears_only_owners_entries() -> None:
    """_clear_owned_keys(token) removes that token's entries, leaving others intact (Option C)."""
    _reset_cache_for_test()
    from gpscheduler.context import (
        _clear_owned_keys,
        _context_cache,  # for direct introspection
        _get_or_create_context,
    )

    # Populate: two entries under T1, one under T2 (shared job_name between them
    # to also prove the tuple key distinguishes them).
    _get_or_create_context("job1", _ALPHA_DOT, context_cache_token="T1")
    _get_or_create_context("job2", _BETA_DOT, context_cache_token="T1")
    _get_or_create_context("job1", _BETA_DOT, context_cache_token="T2")

    _clear_owned_keys("T1")

    # T1's entries gone, T2's remain.
    assert ("T1", "job1") not in _context_cache
    assert ("T1", "job2") not in _context_cache
    assert ("T2", "job1") in _context_cache
