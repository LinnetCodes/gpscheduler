"""Sanity test: the package imports and exposes a version string.

This guards against broken src-layout installs early in development.
"""

from __future__ import annotations

import re

import gpscheduler

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(\.dev\d+|a\d+|b\d+|rc\d+)?(.post\d+)?(\.dirty)?$")


def test_package_imports() -> None:
    assert hasattr(gpscheduler, "__version__")


def test_version_is_pep440_like() -> None:
    assert _VERSION_RE.match(gpscheduler.__version__), (
        f"__version__={gpscheduler.__version__!r} is not a valid PEP 440 version"
    )
