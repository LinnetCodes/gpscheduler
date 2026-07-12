"""Tests for the config loader / validator (ADR-0004/0005/0006/0013)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import gpscheduler  # noqa: F401  (ensures config classes register)
from gpscheduler.config import GPJobConfig, GPSchedulerConfig
from gpscheduler.context import _reset_cache_for_test, worker_init
from gpscheduler.exceptions import (
    CronExpressionError,
    JobSignatureError,
    MaxRunsError,
    NotScheduledError,
    NotWorkerInitError,
    ReservedKeyError,
)
from gpscheduler.loader import LoadedJob, load_jobs
from gpscheduler.registry import Registry
from gpscheduler.registry import registry as _global_registry

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
            cfg = self._jobs[parts[1]]
            # Mirror GPConfigManager, which stamps name (file stem) and
            # cfg_file_path onto every loaded config. In-memory test configs
            # keep the default cfg_file_path (Path() == "."), so loader._src
            # treats it as absent and falls back to "job '<name>'".
            cfg.name = parts[1]
            return cfg
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


# --- worker_init integration -------------------------------------------------


@worker_init
def _make_handle() -> dict[str, int]:
    return {"n": 0}


def _job_with_context(a: int, *, gp_context: dict[str, int]) -> int:
    return a + gp_context["n"]


def _job_without_context(a: int) -> int:
    return a


def _bad_init(unexpected_required: str) -> object:  # noqa: ANN201
    """Module-level init with an unsatisfiable signature (used by bind-check test).

    Defined at module scope because @worker_init rejects nested functions; the
    loader's bind check must reject this signature regardless of decoration.
    """
    return object()


# Register the worker_init job func into the process-global registry so the
# _dispatch_contextual_job dispatcher can resolve it by dotted path at call time
# (mirrors how real @scheduled functions enter the registry; the per-test local
# `reg` passed to the loader is not what the dispatcher re-resolves against).
_global_registry.register(_job_with_context)


def test_load_resolves_worker_init_and_dispatches() -> None:
    """A job with worker_init set dispatches via _dispatch_contextual_job."""
    _reset_cache_for_test()
    reg = _make_registry(_job_with_context)
    reg.register_init(_make_handle)
    init_dot = f"{_make_handle.__module__}.{_make_handle.__qualname__}"
    func_dot = f"{_job_with_context.__module__}.{_job_with_context.__qualname__}"
    mgr = FakeManager(
        {"j": GPJobConfig(func=func_dot, cron="* * * * *", worker_init=init_dot, args=[5])}
    )
    jobs = _load(mgr, reg, _sched_config())
    assert len(jobs) == 1
    # The registered func is the dispatcher, not the bare function.
    assert jobs[0].func is not _job_with_context
    # Calling it with the loader-packed args injects gp_context
    # (init ran: returns dict with n=0; a + 0 = 5).
    assert jobs[0].func(*jobs[0].args) == 5


def test_load_worker_init_not_registered_raises_not_worker_init_error() -> None:
    reg = _make_registry(_job_with_context)
    func_dot = f"{_job_with_context.__module__}.{_job_with_context.__qualname__}"
    mgr = FakeManager(
        {"j": GPJobConfig(func=func_dot, cron="* * * * *", worker_init="pkg.does_not_exist")}
    )
    with pytest.raises(NotWorkerInitError):
        _load(mgr, reg, _sched_config())


def test_load_worker_init_set_but_func_lacks_gp_context_raises() -> None:
    reg = _make_registry(_job_without_context)
    reg.register_init(_make_handle)
    init_dot = f"{_make_handle.__module__}.{_make_handle.__qualname__}"
    func_dot = f"{_job_without_context.__module__}.{_job_without_context.__qualname__}"
    mgr = FakeManager({"j": GPJobConfig(func=func_dot, cron="* * * * *", worker_init=init_dot)})
    with pytest.raises(JobSignatureError):
        _load(mgr, reg, _sched_config())


def test_load_func_has_gp_context_but_no_worker_init_raises() -> None:
    reg = _make_registry(_job_with_context)
    func_dot = f"{_job_with_context.__module__}.{_job_with_context.__qualname__}"
    mgr = FakeManager({"j": GPJobConfig(func=func_dot, cron="* * * * *")})
    with pytest.raises(JobSignatureError):
        _load(mgr, reg, _sched_config())


def test_load_gp_context_in_kwargs_is_reserved() -> None:
    reg = _make_registry(_job_without_context)
    func_dot = f"{_job_without_context.__module__}.{_job_without_context.__qualname__}"
    mgr = FakeManager({"j": GPJobConfig(func=func_dot, cron="* * * * *", kwargs={"gp_context": 1})})
    with pytest.raises(ReservedKeyError):
        _load(mgr, reg, _sched_config())


def test_load_process_job_with_worker_init_preflights_wrapper() -> None:
    """The wrapper is picklable; process preflight must accept it."""
    _reset_cache_for_test()
    reg = _make_registry(_job_with_context)
    reg.register_init(_make_handle)
    init_dot = f"{_make_handle.__module__}.{_make_handle.__qualname__}"
    func_dot = f"{_job_with_context.__module__}.{_job_with_context.__qualname__}"
    mgr = FakeManager(
        {
            "j": GPJobConfig(
                func=func_dot,
                cron="* * * * *",
                worker_init=init_dot,
                executor="process",
                args=[5],
            )
        }
    )
    jobs = _load(mgr, reg, _sched_config(executor="process"))
    import pickle

    pickle.dumps(jobs[0].func)  # must not raise


def test_load_worker_init_bad_signature_raises_at_load() -> None:
    """Regression: an init func with an unsatisfiable signature fails at load, not runtime."""
    reg = _make_registry(_job_with_context)
    reg.register_init(_bad_init)
    init_dot = f"{_bad_init.__module__}.{_bad_init.__qualname__}"
    func_dot = f"{_job_with_context.__module__}.{_job_with_context.__qualname__}"
    mgr = FakeManager({"j": GPJobConfig(func=func_dot, cron="* * * * *", worker_init=init_dot)})
    with pytest.raises(JobSignatureError):
        _load(mgr, reg, _sched_config())


# --- max_runs validation (ADR-0016) -----------------------------------------


def test_loaded_job_carries_max_runs_none_by_default() -> None:
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager(
        {"x": GPJobConfig(func=dotted(_func_no_globals), cron="0 3 * * *", args=[1])}
    )
    jobs = _load(mgr, reg, _sched_config())
    assert jobs[0].max_runs is None


def test_loaded_job_carries_max_runs_when_set() -> None:
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager(
        {"x": GPJobConfig(func=dotted(_func_no_globals), cron="0 3 * * *", args=[1], max_runs=5)}
    )
    jobs = _load(mgr, reg, _sched_config())
    assert jobs[0].max_runs == 5


def test_max_runs_rejects_bool() -> None:
    """bool is a subclass of int; max_runs=True must be rejected to avoid confusion.

    Rejection happens at the pydantic config boundary (bool/float would otherwise
    be silently coerced to int before the loader ever sees them), so the GPJobConfig
    construction itself must raise.
    """
    with pytest.raises(MaxRunsError):
        GPJobConfig(  # type: ignore[arg-type]
            func=dotted(_func_no_globals), cron="0 3 * * *", args=[1], max_runs=True
        )


def test_max_runs_rejects_float() -> None:
    """Even losslessly-convertible floats like 1.0 are rejected (avoid semantic confusion).

    Rejection happens at the pydantic config boundary; the loader never sees floats.
    """
    with pytest.raises(MaxRunsError):
        GPJobConfig(  # type: ignore[arg-type]
            func=dotted(_func_no_globals), cron="0 3 * * *", args=[1], max_runs=1.0
        )


def test_max_runs_rejects_zero() -> None:
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager(
        {"x": GPJobConfig(func=dotted(_func_no_globals), cron="0 3 * * *", args=[1], max_runs=0)}
    )
    with pytest.raises(MaxRunsError):
        _load(mgr, reg, _sched_config())


def test_max_runs_rejects_negative() -> None:
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager(
        {"x": GPJobConfig(func=dotted(_func_no_globals), cron="0 3 * * *", args=[1], max_runs=-3)}
    )
    with pytest.raises(MaxRunsError):
        _load(mgr, reg, _sched_config())


def test_max_runs_disabled_job_still_validated() -> None:
    """Fail-Early: disabled jobs are still validated (consistency with other checks)."""
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager(
        {
            "x": GPJobConfig(
                func=dotted(_func_no_globals), cron="0 3 * * *", args=[1], max_runs=0, enable=False
            )
        }
    )
    with pytest.raises(MaxRunsError):
        _load(mgr, reg, _sched_config())


def test_max_runs_error_message_includes_config_file_path() -> None:
    """Error message must carry the _src() file-path prefix (loader consistency)."""
    reg = _make_registry(_func_no_globals)
    mgr = FakeManager(
        {"x": GPJobConfig(func=dotted(_func_no_globals), cron="0 3 * * *", args=[1], max_runs=0)}
    )
    # FakeManager configs don't have cfg_file_path set, so src falls back to "job 'x'".
    with pytest.raises(MaxRunsError, match="job 'x'"):
        _load(mgr, reg, _sched_config())
