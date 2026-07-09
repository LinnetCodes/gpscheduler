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
