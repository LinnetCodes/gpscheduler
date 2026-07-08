"""Tests for cross-platform signal handling (ADR-0008)."""

from __future__ import annotations

import os
import signal
import threading

from gpscheduler.signals import install_shutdown_handler


def test_returns_a_request_shutdown_callable() -> None:
    ev = threading.Event()
    request = install_shutdown_handler(ev)
    assert callable(request)


def test_request_shutdown_sets_event() -> None:
    ev = threading.Event()
    request = install_shutdown_handler(ev)
    assert not ev.is_set()
    request()
    assert ev.is_set()


def test_installed_handlers_registered_correctly(monkeypatch) -> None:
    ev = threading.Event()
    installed: dict[int, object] = {}
    real_signal = signal.signal

    def fake_signal(sig, handler):
        installed[sig] = handler
        return real_signal(sig, signal.SIG_DFL)  # don't actually keep our handler

    monkeypatch.setattr(signal, "signal", fake_signal)
    install_shutdown_handler(ev)

    expected = {signal.SIGINT}
    if os.name != "nt":
        expected.add(signal.SIGTERM)
    assert expected.issubset(installed.keys())
