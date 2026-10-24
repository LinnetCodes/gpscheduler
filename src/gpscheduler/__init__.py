"""GPScheduler — a cron-style scheduler that turns package functions into scheduled jobs.

The public API surface is re-exported here as modules are implemented.
"""

from __future__ import annotations

from gpscheduler.config import GPJobConfig, GPSchedulerConfig
from gpscheduler.context import worker_init
from gpscheduler.decorator import scheduled
from gpscheduler.exceptions import (
    ConfigError,
    CronExpressionError,
    DecoratorError,
    GPSchedulerError,
    InvalidTimezoneError,
    JobSignatureError,
    MaxRunsError,
    NotScheduledError,
    NotWorkerInitError,
    PackageImportError,
    RegistryError,
    ReservedKeyError,
    SignatureContractError,
    WorkerInitError,
)
from gpscheduler.scheduler import (
    GPScheduler,
    create_scheduler,
    create_scheduler_from_cfg_mgr,
    run_scheduler,
)

__all__ = [
    "__version__",
    "scheduled",
    "worker_init",
    # Config classes (ADR-0005, ADR-0013)
    "GPSchedulerConfig",
    "GPJobConfig",
    # Scheduler engine + convenience functions (ADR-0009/0012/0013)
    "GPScheduler",
    "create_scheduler",
    "create_scheduler_from_cfg_mgr",
    "run_scheduler",
    # Exceptions (ADR-0011)
    "GPSchedulerError",
    "DecoratorError",
    "SignatureContractError",
    "RegistryError",
    "NotScheduledError",
    "ConfigError",
    "CronExpressionError",
    "InvalidTimezoneError",
    "JobSignatureError",
    "ReservedKeyError",
    "MaxRunsError",
    "PackageImportError",
    "WorkerInitError",
    "NotWorkerInitError",
]

__version__ = "0.2.0"
