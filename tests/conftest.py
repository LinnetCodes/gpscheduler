"""Shared pytest fixtures for the gpscheduler test suite.

This conftest applies to ALL tests in tests/ (pytest auto-discovers it).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from gpscheduler.registry import registry


@pytest.fixture(autouse=True, scope="session")
def _gpclog_to_tmp(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Point gpclog at a per-session temp dir via GPCLOG_PATH.

    gpscheduler acquires its gpclog logger inside GPScheduler construction;
    with gpclog's default log_dir mode "auto" and GPCLOG_PATH unset, that warns
    ("gpclog: Using home directory for logs") on first use and writes logs under
    the user's home. Setting GPCLOG_PATH for the whole session keeps test output
    pristine and stops tests writing to ~/gpclog_output.
    """
    old = os.environ.get("GPCLOG_PATH")
    os.environ["GPCLOG_PATH"] = str(tmp_path_factory.mktemp("gpclog"))
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("GPCLOG_PATH", None)
        else:
            os.environ["GPCLOG_PATH"] = old


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
