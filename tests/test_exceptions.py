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
    ]:
        assert hasattr(gpscheduler, name), f"{name} not exported from gpscheduler"
