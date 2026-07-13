"""Tests for the GPSchedulerError hierarchy (ADR-0011)."""

from __future__ import annotations

import gpscheduler
from gpscheduler import exceptions as exc


def test_base_exception_is_exception() -> None:
    assert issubclass(exc.GPSchedulerError, Exception)


def test_decorator_layer() -> None:
    assert issubclass(exc.SignatureContractError, exc.DecoratorError)
    assert issubclass(exc.DecoratorError, exc.GPSchedulerError)


def test_registry_layer() -> None:
    assert issubclass(exc.NotScheduledError, exc.RegistryError)
    assert issubclass(exc.RegistryError, exc.GPSchedulerError)


def test_config_layer() -> None:
    for leaf in (
        exc.CronExpressionError,
        exc.JobSignatureError,
        exc.ReservedKeyError,
        exc.MaxRunsError,
        exc.PackageImportError,
        exc.InvalidTimezoneError,
    ):
        assert issubclass(leaf, exc.ConfigError)
    assert issubclass(exc.ConfigError, exc.GPSchedulerError)


def test_worker_init_layer() -> None:
    assert issubclass(exc.NotWorkerInitError, exc.WorkerInitError)
    assert issubclass(exc.WorkerInitError, exc.GPSchedulerError)


def test_all_exported_from_package() -> None:
    for name in [
        "GPSchedulerError",
        "DecoratorError",
        "SignatureContractError",
        "RegistryError",
        "NotScheduledError",
        "ConfigError",
        "CronExpressionError",
        "JobSignatureError",
        "ReservedKeyError",
        "MaxRunsError",
        "PackageImportError",
        "InvalidTimezoneError",
        "WorkerInitError",
        "NotWorkerInitError",
    ]:
        assert hasattr(gpscheduler, name), f"{name} not exported from gpscheduler"


def test_package_import_error_inherits_config_and_base() -> None:
    """Sanity: the new leaf is catchable at both category and base level."""
    assert issubclass(exc.PackageImportError, exc.ConfigError)
    assert issubclass(exc.PackageImportError, exc.GPSchedulerError)


def test_invalid_timezone_error_inherits_config_and_base() -> None:
    """Sanity: the new leaf is catchable at both category and base level."""
    assert issubclass(exc.InvalidTimezoneError, exc.ConfigError)
    assert issubclass(exc.InvalidTimezoneError, exc.GPSchedulerError)
