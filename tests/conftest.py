"""Shared pytest fixtures for the gpscheduler test suite.

This conftest applies to ALL tests in tests/ (pytest auto-discovers it).
"""
from __future__ import annotations

import pytest

from gpscheduler.registry import registry


@pytest.fixture(autouse=True)
def _isolate_global_registry() -> object:
    """Snapshot/restore the process-global registry around every test.

    Several test modules register fixture functions at module scope to satisfy
    the loader/dispatcher (which re-resolves by dotted path at runtime). Without
    isolation these registrations leak across modules for the rest of the
    process — currently harmless (distinct dotted paths prevent collisions) but
    a latent footgun for order-dependent test surprises.

    This fixture snapshots ``registry._functions`` and ``registry._init_functions``
    before each test and restores them after, so every test sees a clean slate
    matching whatever state existed at module-import time.

    Uses snapshot-and-restore (NOT clear()) so product-code registrations made
    during gpscheduler's own import are preserved.
    """
    functions_before = dict(registry._functions)  # type: ignore[attr-defined]
    init_before = dict(registry._init_functions)  # type: ignore[attr-defined]
    yield
    registry._functions.clear()  # type: ignore[attr-defined]
    registry._functions.update(functions_before)  # type: ignore[attr-defined]
    registry._init_functions.clear()  # type: ignore[attr-defined]
    registry._init_functions.update(init_before)  # type: ignore[attr-defined]
