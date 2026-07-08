"""GPScheduler — a cron-style scheduler that turns package functions into scheduled jobs.

Public API grows here as the library is implemented. For now the package exposes
its version so build backends and tooling can read it.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
