"""GPScheduler — a cron-style scheduler that turns package functions into scheduled jobs.

The public API surface is re-exported here as modules are implemented.
"""

from __future__ import annotations

from gpscheduler.config import GPJobConfig, GPSchedulerConfig
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
from gpscheduler.scheduler import GPScheduler, create_scheduler, run_scheduler

__all__ = [
    "__version__",
    "scheduled",
    # Config classes (ADR-0005, ADR-0013)
    "GPSchedulerConfig",
    "GPJobConfig",
    # Scheduler engine + convenience functions (ADR-0009/0012/0013)
    "GPScheduler",
    "create_scheduler",
    "run_scheduler",
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
