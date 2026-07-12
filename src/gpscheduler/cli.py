"""Click CLI entry: gpscheduler run / list-jobs (ADR-0008)."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

import click

from gpscheduler.exceptions import GPSchedulerError
from gpscheduler.scheduler import create_scheduler, run_scheduler


def _next_run_time(job: Any) -> str:
    """Render a job's next fire time, computing it when the scheduler is unstarted.

    APScheduler only sets ``Job.next_run_time`` once the scheduler has started
    (the jobstore computes and writes it via ``Job._modify``). ``create_scheduler``
    deliberately does NOT start the scheduler — that is ``run_scheduler``'s job —
    so ``list-jobs`` (a dry run) sees jobs whose ``next_run_time`` slot is unset
    and accessing it raises ``AttributeError``.

    For a meaningful dry-run listing, compute the next fire time from the
    trigger directly via ``trigger.get_next_fire_time(None, now)``. When the
    scheduler IS started, the job's own ``next_run_time`` wins.
    """
    # Started scheduler: the jobstore has populated next_run_time.
    if hasattr(job, "next_run_time") and job.next_run_time is not None:
        return str(job.next_run_time)
    # Unstarted (dry run): ask the trigger when it would next fire.
    trigger = getattr(job, "trigger", None)
    if trigger is not None:
        now = datetime.now(tz=getattr(job, "_scheduler", job).timezone or None)
        nxt = trigger.get_next_fire_time(None, now)
        if nxt is not None:
            return str(nxt)
    return "(unscheduled)"


@click.group()
def main() -> None:
    """GPScheduler command line interface."""


@main.command("run")
@click.option("--config", "config", default=None, help="Path to the gpconfig cfg_folder.")
@click.option("--project", "project", default="gpscheduler", help="gpconfig project name.")
def run_cmd(config: str | None, project: str) -> None:
    """Start the scheduler and block until a shutdown signal."""
    try:
        scheduler = create_scheduler(cfg_folder=config, project_name=project)
    except GPSchedulerError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    run_scheduler(scheduler)


@main.command("list-jobs")
@click.option("--config", "config", default=None, help="Path to the gpconfig cfg_folder.")
@click.option("--project", "project", default="gpscheduler", help="gpconfig project name.")
def list_jobs_cmd(config: str | None, project: str) -> None:
    """Load + validate config, then list enabled jobs."""
    try:
        scheduler = create_scheduler(cfg_folder=config, project_name=project)
    except GPSchedulerError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)

    jobs = scheduler.get_jobs()
    if not jobs:
        click.echo("No enabled jobs.")
        return
    click.echo(f"{len(jobs)} enabled job(s):")
    # _job_max_runs maps job_id -> max_runs (None = unlimited). Populated by
    # register_jobs (ADR-0016). Access the internal dict directly; cli.py is
    # part of gpscheduler.
    max_runs_map = getattr(scheduler, "_job_max_runs", {})
    for j in jobs:
        mr = max_runs_map.get(j.id)
        mr_str = str(mr) if mr is not None else "unlimited"
        click.echo(f"  - {j.id}: next run {_next_run_time(j)} (max_runs: {mr_str})")


if __name__ == "__main__":
    main()
