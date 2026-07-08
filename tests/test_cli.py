"""Tests for the CLI (ADR-0008)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from gpscheduler.cli import main


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
