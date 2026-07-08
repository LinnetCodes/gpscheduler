"""Tests for the Registry (ADR-0004)."""

from __future__ import annotations

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
