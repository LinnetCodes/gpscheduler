"""GPScheduler — a cron-style scheduler that turns package functions into scheduled jobs.

The public API surface is re-exported here as modules are implemented.
"""

from __future__ import annotations

from gpscheduler.decorator import scheduled
from gpscheduler.exceptions import (
    ConfigError,
    CronExpressionError,
    DecoratorError,
    GPSchedulerError,
    JobSignatureError,
    NotScheduledError,
    RegistryError,
    ReservedKeyError,
    SignatureContractError,
)

__all__ = [
    "__version__",
    "scheduled",
    # Exceptions (ADR-0011)
    "GPSchedulerError",
    "DecoratorError",
    "SignatureContractError",
    "RegistryError",
    "NotScheduledError",
    "ConfigError",
    "CronExpressionError",
    "JobSignatureError",
    "ReservedKeyError",
]

__version__ = "0.1.0"
