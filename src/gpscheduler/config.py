"""Configuration classes for gpscheduler (ADR-0005, ADR-0013).

Two GPConfig subclasses with ``extra="forbid"`` (inherited from GPConfig).
They self-register with GPConfigManager at import via their ``cfg_class_name``
ClassVar, so ``manager.get_config("scheduler")`` / ``get_config("jobs.x")``
auto-deserialize them.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from gpconfig import GPConfig, GPConfigManager
from pydantic import field_validator


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
    # Optional cap on executions; None = unlimited. bool/float are rejected at
    # the pydantic boundary (ADR-0016): ``True``->1 / ``1.0``->1 would otherwise
    # be silently coerced before the loader ever sees them, so the boundary
    # validator catches them here. The <=0 range check is deferred to the loader,
    # which can attach the config-file source prefix to the error message.
    max_runs: int | None = None

    @field_validator("max_runs", mode="before")
    @classmethod
    def _reject_non_int_max_runs(cls, value: Any) -> Any:
        if value is None:
            return None
        # Imported lazily to avoid a circular import (gpscheduler.exceptions
        # does not import config, but keep the boundary clean).
        from gpscheduler.exceptions import MaxRunsError

        # bool FIRST: isinstance(True, int) is True, so it would otherwise pass
        # through the int check below.
        if isinstance(value, bool):
            raise MaxRunsError(f"max_runs must be a positive integer, got bool {value!r}")
        if not isinstance(value, int):
            raise MaxRunsError(
                f"max_runs must be a positive integer, got {type(value).__name__} {value!r}"
            )
        return value


# Self-register so GPConfigManager.get_config auto-detects by cfg_class_name.
GPConfigManager.register_config_class(GPSchedulerConfig)
GPConfigManager.register_config_class(GPJobConfig)
