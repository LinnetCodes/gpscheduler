"""Tests for the Registry (ADR-0004)."""

from __future__ import annotations

import pytest

from gpscheduler.registry import Registry


def _sample() -> None:
    pass


def test_register_and_get() -> None:
    reg = Registry()
    reg.register(_sample)
    assert reg.get(f"{_sample.__module__}.{_sample.__qualname__}") is _sample


def test_key_is_module_dot_qualname() -> None:
    reg = Registry()
    key = reg.register(_sample)
    assert key == f"{_sample.__module__}.{_sample.__qualname__}"


def test_get_missing_raises_keyerror() -> None:
    reg = Registry()
    try:
        reg.get("nope")
    except KeyError as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("expected KeyError for missing key")


def test_contains() -> None:
    reg = Registry()
    assert not reg.contains("x")
    reg.register(_sample)
    assert reg.contains(f"{_sample.__module__}.{_sample.__qualname__}")


def test_clear() -> None:
    reg = Registry()
    reg.register(_sample)
    reg.clear()
    assert len(reg) == 0


def test_len() -> None:
    reg = Registry()
    assert len(reg) == 0
    reg.register(_sample)
    assert len(reg) == 1


def _some_init() -> object:
    return object()


def test_register_init_stores_in_init_map() -> None:
    reg = Registry()
    key = reg.register_init(_some_init)
    assert reg.contains_init(key)
    assert reg.get_init(key) is _some_init


def test_init_map_is_separate_from_scheduled_map() -> None:
    """A function in the init map is NOT retrievable via the scheduled get()."""
    reg = Registry()
    key = reg.register_init(_some_init)
    assert reg.contains_init(key)
    assert not reg.contains(key)  # scheduled map must not see it
    with pytest.raises(KeyError):
        reg.get(key)


def test_get_init_missing_raises_keyerror() -> None:
    reg = Registry()
    with pytest.raises(KeyError):
        reg.get_init("nope")


def test_clear_init_empties_init_map_only() -> None:
    reg = Registry()
    init_key = reg.register_init(_some_init)
    sched_key = reg.register(_some_init)  # same func, different map
    assert reg.contains_init(init_key)
    assert reg.contains(sched_key)
    reg.clear_init()
    assert not reg.contains_init(init_key)
    # clear_init must NOT touch the scheduled map
    assert reg.contains(sched_key)

