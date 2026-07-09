"""Tests for the config loader / validator (ADR-0004/0005/0006/0013)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import gpscheduler  # noqa: F401  (ensures config classes register)
from gpscheduler.config import GPJobConfig, GPSchedulerConfig
from gpscheduler.exceptions import (
    CronExpressionError,
    JobSignatureError,
    NotScheduledError,
    ReservedKeyError,
)
from gpscheduler.loader import LoadedJob, load_jobs
from gpscheduler.registry import Registry

# --- helpers ---------------------------------------------------------------


def _sched_config(**overrides: Any) -> GPSchedulerConfig:
    return GPSchedulerConfig(**overrides)


def _func_no_globals(a: int, b: int = 0) -> int:
    return a + b


def _func_with_globals(a: int, gp_globals: dict[str, Any]) -> int:
    return a + len(gp_globals)


def _func_pickle_ok(x: int) -> int:
    return x


def _make_registry(*funcs: Any) -> Registry:
    reg = Registry()
    for f in funcs:
        reg.register(f)
    return reg


class FakeManager:
    """Stand-in for GPConfigManager: serves job configs from a dict."""

    def __init__(self, jobs: dict[str, GPJobConfig]) -> None:
        self._jobs = jobs
        self._cfg_folder = Path("/fake")

    @property
    def cfg_folder(self) -> Path:
        return self._cfg_folder

    def list_configs(self, path: str = "") -> list[str]:
        if path == "jobs":
            return list(self._jobs.keys())
        return []

    def get_config(self, path: str, config_cls: Any = None) -> Any:
        # path like "jobs.cleanup"
        parts = path.split(".")
        if len(parts) == 2 and parts[0] == "jobs":
            return self._jobs[parts[1]]
        raise KeyError(path)


def _load(
    manager: FakeManager,
    registry: Registry,
    sched: GPSchedulerConfig,
) -> list[LoadedJob]:
    return load_jobs(
        manager=manager,
        registry=registry,
        sched_config=sched,
        import_packages=lambda _pkgs: None,
    )


def dotted(fn: Any) -> str:
    return f"{fn.__module__}.{fn.__qualname__}"


# --- tests -----------------------------------------------------------------


def test_loaded_job_has_trigger_func_args_kwargs_executor() -> None:
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager(
        {"cleanup": GPJobConfig(func=dotted(_func_no_globals), cron="0 3 * * *", args=[1, 2])}
    )
    jobs = _load(mgr, reg, _sched_config())
    assert len(jobs) == 1
    j = jobs[0]
    assert j.func is _func_no_globals
    assert j.args == [1, 2]
    assert j.kwargs == {}
    assert j.executor == "thread"
    assert j.enable is True
    from apscheduler.triggers.cron import CronTrigger

    assert isinstance(j.trigger, CronTrigger)


def test_disabled_job_validated_but_not_returned() -> None:
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager(
        {
            "cleanup": GPJobConfig(
                func=dotted(_func_no_globals), cron="0 3 * * *", args=[1], enable=False
            )
        }
    )
    jobs = _load(mgr, reg, _sched_config())
    assert jobs == []


def test_missing_func_raises_not_scheduled() -> None:
    reg = Registry()  # empty
    mgr = FakeManager({"cleanup": GPJobConfig(func="nope.f", cron="0 3 * * *")})
    with pytest.raises(NotScheduledError):
        _load(mgr, reg, _sched_config())


def test_bad_cron_raises() -> None:
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager({"cleanup": GPJobConfig(func=dotted(_func_no_globals), cron="99 * * *")})
    with pytest.raises(CronExpressionError):
        _load(mgr, reg, _sched_config())


def test_signature_mismatch_raises() -> None:
    reg = _make_registry(_func_no_globals)
    # _func_no_globals(a, b=0): passing 3 positional args fails bind
    mgr = FakeManager(
        {"cleanup": GPJobConfig(func=dotted(_func_no_globals), cron="0 3 * * *", args=[1, 2, 3])}
    )
    with pytest.raises(JobSignatureError):
        _load(mgr, reg, _sched_config())


def test_reserved_key_in_kwargs_raises() -> None:
    reg = _make_registry(_func_with_globals)
    mgr = FakeManager(
        {
            "x": GPJobConfig(
                func=dotted(_func_with_globals),
                cron="0 3 * * *",
                args=[1],
                kwargs={"gp_globals": {"db_url": "x"}},  # reserved!
            )
        }
    )
    with pytest.raises(ReservedKeyError):
        _load(mgr, reg, _sched_config())


def test_gp_globals_injected_when_signature_declares_it() -> None:
    reg = _make_registry(_func_with_globals)
    mgr = FakeManager(
        {"x": GPJobConfig(func=dotted(_func_with_globals), cron="0 3 * * *", args=[1])}
    )
    sched = _sched_config(job_globals={"db_url": "x"})
    jobs = _load(mgr, reg, sched)
    assert jobs[0].kwargs == {"gp_globals": {"db_url": "x"}}


def test_gp_globals_not_injected_when_signature_omits_it() -> None:
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager({"x": GPJobConfig(func=dotted(_func_no_globals), cron="0 3 * * *", args=[1])})
    sched = _sched_config(job_globals={"db_url": "x"})
    jobs = _load(mgr, reg, sched)
    assert jobs[0].kwargs == {}


def test_executor_priority_job_overrides_scheduler() -> None:
    reg = _make_registry(_func_pickle_ok)
    mgr = FakeManager(
        {
            "x": GPJobConfig(
                func=dotted(_func_pickle_ok), cron="0 3 * * *", args=[1], executor="process"
            )
        }
    )
    jobs = _load(mgr, reg, _sched_config(executor="thread"))
    assert jobs[0].executor == "process"


def test_executor_falls_back_to_scheduler_default() -> None:
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager({"x": GPJobConfig(func=dotted(_func_no_globals), cron="0 3 * * *", args=[1])})
    jobs = _load(mgr, reg, _sched_config(executor="process"))
    assert jobs[0].executor == "process"


def test_process_executor_pickle_preflight_passes() -> None:
    reg = _make_registry(_func_pickle_ok)
    mgr = FakeManager(
        {
            "x": GPJobConfig(
                func=dotted(_func_pickle_ok), cron="0 3 * * *", args=[1], executor="process"
            )
        }
    )
    # pickle-able args -> OK
    jobs = _load(mgr, reg, _sched_config())
    assert jobs[0].executor == "process"


def test_process_executor_pickle_preflight_fails_on_unpickleable() -> None:
    reg = Registry()
    reg.register(_func_pickle_ok)

    class Unpickleable:
        def __reduce__(self) -> Any:
            raise TypeError("nope")

    bad_args: list[Any] = [Unpickleable()]
    mgr = FakeManager(
        {
            "x": GPJobConfig(
                func=dotted(_func_pickle_ok),
                cron="0 3 * * *",
                args=bad_args,
                executor="process",
            )
        }
    )
    # The loader tries pickle.dumps on the args and must raise JobSignatureError.
    with pytest.raises(JobSignatureError):
        _load(mgr, reg, _sched_config())


def test_disabled_job_still_validated_for_signature() -> None:
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager(
        {
            "x": GPJobConfig(
                func=dotted(_func_no_globals),
                cron="0 3 * * *",
                args=[1, 2, 3],  # bad bind
                enable=False,
            )
        }
    )
    with pytest.raises(JobSignatureError):
        _load(mgr, reg, _sched_config())
