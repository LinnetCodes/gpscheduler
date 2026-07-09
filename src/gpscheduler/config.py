"""Configuration classes for gpscheduler (ADR-0005, ADR-0013).

Two GPConfig subclasses with ``extra="forbid"`` (inherited from GPConfig).
They self-register with GPConfigManager at import via their ``cfg_class_name``
ClassVar, so ``manager.get_config("scheduler")`` / ``get_config("jobs.x")``
auto-deserialize them.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from gpconfig import GPConfig, GPConfigManager


class GPSchedulerConfig(GPConfig):
    """Scheduler-level configuration (one file: ``scheduler.yaml``)."""

    cfg_class_name: ClassVar[str] = "GPSchedulerConfig"

    configured_class_name: str = "GPScheduler"
    executor: Literal["thread", "process"] = "thread"
    timezone: str = ""  # empty -> local timezone at parse time
    max_workers: int = 10
    timeout: float | None = None  # None = wait forever on graceful shutdown
    packages: list[str] = []
    job_globals: dict[str, Any] = {}


class GPJobConfig(GPConfig):
    """Per-job configuration (one file under ``jobs/<name>.yaml``)."""

    cfg_class_name: ClassVar[str] = "GPJobConfig"

    func: str  # dotted path, validated against the Registry at load time
    cron: str  # 5/6-segment cron expression, parsed at load time
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    executor: Literal["thread", "process"] | None = None
    enable: bool = True
    worker_init: str | None = None  # optional dot-path to a @worker_init function


# Self-register so GPConfigManager.get_config auto-detects by cfg_class_name.
GPConfigManager.register_config_class(GPSchedulerConfig)
GPConfigManager.register_config_class(GPJobConfig)
