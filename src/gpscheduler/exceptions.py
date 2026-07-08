"""GPScheduler exception hierarchy.

Three layers: base -> category -> leaf (ADR-0011). Users can catch a whole
category (e.g. ``except RegistryError``) or the base ``except
GPSchedulerError`` to catch anything gpscheduler raises.
"""

from __future__ import annotations


class GPSchedulerError(Exception):
    """Base class for all gpscheduler exceptions."""


# ---- Decorator layer ----


class DecoratorError(GPSchedulerError):
    """Misuse of the @scheduled decorator."""


class SignatureContractError(DecoratorError):
    """A function does not satisfy the Scheduled Function signature contract."""


# ---- Registry layer ----


class RegistryError(GPSchedulerError):
    """Registry-related error."""


class NotScheduledError(RegistryError):
    """A dotted path in config was not found in the Registry (strict check)."""


# ---- Config layer ----


class ConfigError(GPSchedulerError):
    """Configuration error (includes translated gpconfig failures)."""


class CronExpressionError(ConfigError):
    """A cron expression is invalid (ADR-0007)."""


class JobSignatureError(ConfigError):
    """Configured arguments cannot bind to the function signature (ADR-0003)."""


class ReservedKeyError(ConfigError):
    """A job's kwargs used the reserved key ``gp_globals`` (ADR-0006)."""
