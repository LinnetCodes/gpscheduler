"""Tests for config classes (ADR-0005, ADR-0013)."""

from __future__ import annotations

import pytest
from gpconfig import GPConfigManager
from pydantic import ValidationError

import gpscheduler
from gpscheduler.config import GPJobConfig, GPSchedulerConfig


def test_exported_from_package() -> None:
    assert hasattr(gpscheduler, "GPSchedulerConfig")
    assert hasattr(gpscheduler, "GPJobConfig")


def test_scheduler_config_defaults() -> None:
    c = GPSchedulerConfig()
    assert c.executor == "thread"
    assert c.max_workers == 10
    assert c.timeout is None
    assert c.packages == []
    assert c.job_globals == {}
    assert c.configured_class_name == "GPScheduler"


def test_scheduler_config_accepts_full_fields() -> None:
    c = GPSchedulerConfig(
        executor="process",
        timezone="Asia/Shanghai",
        max_workers=4,
        timeout=600,
        packages=["mypkg"],
        job_globals={"db_url": "x"},
    )
    assert c.executor == "process"
    assert c.timezone == "Asia/Shanghai"
    assert c.timeout == 600


def test_scheduler_config_forbids_unknown_field() -> None:
    with pytest.raises(ValidationError):
        GPSchedulerConfig(bogus=1)  # type: ignore[call-arg]


def test_job_config_required_fields() -> None:
    c = GPJobConfig(func="m.f", cron="0 3 * * *")
    assert c.func == "m.f"
    assert c.cron == "0 3 * * *"
    assert c.args == []
    assert c.kwargs == {}
    assert c.enable is True


def test_job_config_missing_required_raises() -> None:
    with pytest.raises(ValidationError):
        GPJobConfig(func="m.f")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        GPJobConfig(cron="0 3 * * *")  # type: ignore[call-arg]


def test_job_config_executor_optional() -> None:
    c = GPJobConfig(func="m.f", cron="* * * * *", executor="process")
    assert c.executor == "process"


def test_job_config_forbids_unknown_field() -> None:
    with pytest.raises(ValidationError):
        GPJobConfig(func="m.f", cron="* * * * *", bogus=1)  # type: ignore[call-arg]


def test_cfg_class_names_registered() -> None:
    # GPSchedulerConfig/GPJobConfig register themselves at import time.
    assert "GPSchedulerConfig" in GPConfigManager._config_classes
    assert "GPJobConfig" in GPConfigManager._config_classes


def test_job_config_worker_init_defaults_none() -> None:
    cfg = GPJobConfig(func="pkg.f", cron="* * * * *")
    assert cfg.worker_init is None


def test_job_config_worker_init_accepts_dotpath() -> None:
    cfg = GPJobConfig(func="pkg.f", cron="* * * * *", worker_init="pkg.init_db")
    assert cfg.worker_init == "pkg.init_db"


def test_job_config_max_runs_defaults_none() -> None:
    cfg = GPJobConfig(func="pkg.f", cron="* * * * *")
    assert cfg.max_runs is None


def test_job_config_max_runs_accepts_positive_int() -> None:
    cfg = GPJobConfig(func="pkg.f", cron="* * * * *", max_runs=5)
    assert cfg.max_runs == 5
