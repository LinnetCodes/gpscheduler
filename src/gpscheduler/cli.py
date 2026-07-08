"""Click CLI entry: gpscheduler run / list-jobs (ADR-0008)."""

from __future__ import annotations

import sys

import click

from gpscheduler.exceptions import GPSchedulerError
from gpscheduler.scheduler import create_scheduler, run_scheduler


@click.group()
def main() -> None:
    """GPScheduler command line interface."""


@main.command("run")
@click.option("--config", "config", default=None, help="Path to the gpconfig cfg_folder.")
@click.option("--project", "project", default="gpscheduler", help="gpconfig project name.")
@click.option(
    "--log-level",
    "log_level",
    default=None,
    help="Reserved for future use (gpclog controls level via its own config).",
)
def run_cmd(config: str | None, project: str, log_level: str | None) -> None:
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
    for j in jobs:
        click.echo(f"  - {j.id}: next run {j.next_run_time}")


if __name__ == "__main__":
    main()
