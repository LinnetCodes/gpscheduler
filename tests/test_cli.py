"""Tests for the CLI (ADR-0008)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from gpscheduler.cli import main
from gpscheduler.decorator import scheduled


def _make_cfg_folder(tmp_path: Path) -> Path:
    cfg_folder = tmp_path / "cfg"
    (cfg_folder / "jobs").mkdir(parents=True)
    (cfg_folder / "global_env.yaml").write_text("project: test\n", encoding="utf-8")
    (cfg_folder / "scheduler.yaml").write_text(
        "cfg_class_name: GPSchedulerConfig\nconfigured_class_name: GPScheduler\n"
        "timezone: UTC\nmax_workers: 1\n",
        encoding="utf-8",
    )
    return cfg_folder


@scheduled
def _cli_demo_task() -> None:
    """Job registered purely so a cfg file can reference it in tests."""


def test_list_jobs_no_jobs(tmp_path: Path) -> None:
    cfg_folder = _make_cfg_folder(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["list-jobs", "--config", str(cfg_folder), "--project", "gpscheduler_test"],
    )
    assert result.exit_code == 0, result.output
    # No jobs folder contents -> reports zero enabled jobs.
    assert "no enabled jobs" in result.output.lower()


def test_run_missing_config_errors_cleanly(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main, ["run", "--config", str(tmp_path / "nope"), "--project", "gpscheduler_test"]
    )
    assert result.exit_code != 0


def test_list_jobs_with_enabled_job_prints_next_run(tmp_path: Path) -> None:
    """Regression: list-jobs must not crash when jobs exist but scheduler is unstarted.

    ``create_scheduler`` deliberately does NOT call ``start()`` (that is
    ``run_scheduler``'s job), so APScheduler leaves ``Job.next_run_time`` unset.
    Accessing it raised ``AttributeError``. This test ensures the helper computes
    the next fire time from the trigger instead, so a dry-run listing works.
    """
    cfg_folder = _make_cfg_folder(tmp_path)
    dotted = f"{_cli_demo_task.__module__}.{_cli_demo_task.__qualname__}"
    (cfg_folder / "jobs" / "demo.yaml").write_text(
        f"cfg_class_name: GPJobConfig\nfunc: {dotted}\ncron: '* * * * *'\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["list-jobs", "--config", str(cfg_folder), "--project", "gpscheduler_test"],
    )
    assert result.exit_code == 0, result.output
    assert "1 enabled job(s)" in result.output
    assert "demo" in result.output
    # The crash site: must render a next-run time, not crash with AttributeError.
    assert "next run" in result.output.lower()
    assert "(unscheduled)" not in result.output


def test_list_jobs_shows_max_runs_value(tmp_path: Path) -> None:
    cfg_folder = _make_cfg_folder(tmp_path)
    dotted = f"{_cli_demo_task.__module__}.{_cli_demo_task.__qualname__}"
    (cfg_folder / "jobs" / "demo.yaml").write_text(
        f"cfg_class_name: GPJobConfig\nfunc: {dotted}\ncron: '* * * * *'\nmax_runs: 5\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["list-jobs", "--config", str(cfg_folder), "--project", "gpscheduler_test"],
    )
    assert result.exit_code == 0, result.output
    assert "max_runs: 5" in result.output


def test_list_jobs_shows_unlimited_when_max_runs_absent(tmp_path: Path) -> None:
    cfg_folder = _make_cfg_folder(tmp_path)
    dotted = f"{_cli_demo_task.__module__}.{_cli_demo_task.__qualname__}"
    (cfg_folder / "jobs" / "demo.yaml").write_text(
        f"cfg_class_name: GPJobConfig\nfunc: {dotted}\ncron: '* * * * *'\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["list-jobs", "--config", str(cfg_folder), "--project", "gpscheduler_test"],
    )
    assert result.exit_code == 0, result.output
    assert "max_runs: unlimited" in result.output


def test_list_jobs_output_is_alphabetical_by_job_id(tmp_path: Path) -> None:
    """list-jobs lists jobs in alphabetical order by job id (inconsistency.04).

    The job id is the jobs/<name>.yaml filename stem. We register jobs whose
    filename-stem ids sort in a different order than they are written to disk
    ("zebra" written first, "apple" second, "mango" third) and assert the printed
    job lines appear alphabetically. This promotes alphabetical ordering from a
    gpconfig side-effect to an explicit gpscheduler contract.
    """
    cfg_folder = _make_cfg_folder(tmp_path)
    dotted = f"{_cli_demo_task.__module__}.{_cli_demo_task.__qualname__}"
    # Write in non-alphabetical order to defeat any incidental FS ordering.
    for stem in ("zebra", "apple", "mango"):
        (cfg_folder / "jobs" / f"{stem}.yaml").write_text(
            f"cfg_class_name: GPJobConfig\nfunc: {dotted}\ncron: '* * * * *'\n",
            encoding="utf-8",
        )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["list-jobs", "--config", str(cfg_folder), "--project", "gpscheduler_test"],
    )
    assert result.exit_code == 0, result.output

    # Pull out the job ids in print order from lines like "  - apple: next run ...".
    printed_ids = [
        line.split(":")[0].strip().removeprefix("- ").strip()
        for line in result.output.splitlines()
        if line.lstrip().startswith("- ")
    ]
    assert printed_ids == ["apple", "mango", "zebra"], result.output


def test_run_with_bad_package_reports_error_and_exits_1(tmp_path: Path) -> None:
    """End-to-end: a bad packages entry surfaces as `error:` + exit 1, not a traceback.

    The CLI catches only ``GPSchedulerError``, so the loader's translation of
    ``ModuleNotFoundError`` -> ``PackageImportError`` must reach it as a hierarchy
    member, producing a clean `error: <message>` line rather than a raw traceback.
    """
    cfg_folder = _make_cfg_folder(tmp_path)
    # Overwrite scheduler.yaml to include a bogus package.
    (cfg_folder / "scheduler.yaml").write_text(
        "cfg_class_name: GPSchedulerConfig\nconfigured_class_name: GPScheduler\n"
        "timezone: UTC\nmax_workers: 1\npackages: [definitely_not_a_real_pkg_xyz]\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["list-jobs", "--config", str(cfg_folder), "--project", "gpscheduler_test"]
    )
    assert result.exit_code == 1, result.output
    assert "error:" in result.output.lower()
    # Must not leak a Python traceback.
    assert "Traceback" not in result.output


def test_run_with_bad_timezone_reports_error_and_exits_1(tmp_path: Path) -> None:
    """End-to-end: a bad timezone surfaces as `error:` + exit 1, not a traceback.

    The bad timezone is consumed inside ``GPScheduler.__init__`` (via
    ``_build_scheduler``), which is reached before the loader runs. The CLI must
    still catch it cleanly via ``except GPSchedulerError``.
    """
    cfg_folder = _make_cfg_folder(tmp_path)
    # Overwrite scheduler.yaml with a bogus timezone.
    (cfg_folder / "scheduler.yaml").write_text(
        "cfg_class_name: GPSchedulerConfig\nconfigured_class_name: GPScheduler\n"
        "timezone: Bogus/Nowhere\nmax_workers: 1\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["list-jobs", "--config", str(cfg_folder), "--project", "gpscheduler_test"]
    )
    assert result.exit_code == 1, result.output
    assert "error:" in result.output.lower()
    assert "Traceback" not in result.output


def test_next_run_time_renders_meaningful_string_for_unstarted_job() -> None:
    """``_next_run_time`` uses ``job.trigger.timezone`` and does not raise on an
    unstarted scheduler (clarity.01).

    The helper previously reached into APScheduler's private ``_scheduler`` attr
    via ``getattr(job, "_scheduler", job).timezone``. That refactor replaced it
    with the public ``job.trigger.timezone``. This test pins the public path:
    given a job with a known trigger whose ``next_run_time`` is None (the
    unstarted dry-run case), the helper must return a meaningful next-fire
    string rather than ``(unscheduled)`` or raising ``AttributeError``.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from apscheduler.triggers.cron import CronTrigger

    from gpscheduler.cli import _next_run_time

    # Build a minimal fake job: unstarted scheduler leaves next_run_time unset.
    trigger = CronTrigger.from_crontab("* * * * *", timezone=ZoneInfo("UTC"))

    class _FakeJob:
        next_run_time = None
        # APScheduler sets ``trigger`` on every real job; mirror that here.
        # The helper accesses it directly as a public attribute.

    fake = _FakeJob()
    fake.trigger = trigger  # type: ignore[attr-defined]

    result = _next_run_time(fake)
    assert result != "(unscheduled)"
    # Must parse as a real datetime (the str() of an aware datetime).
    datetime.fromisoformat(result)
