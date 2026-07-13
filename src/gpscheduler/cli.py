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
        # CronTrigger always has a tzinfo ``timezone``; the old
        # ``getattr(job, "_scheduler", job).timezone`` reached into APScheduler's
        # private ``_scheduler`` attr, and the ``job.timezone`` fallback was dead
        # code (APScheduler Job has no ``timezone`` attr). ``now`` must be
        # timezone-aware for ``get_next_fire_time`` to compute correctly.
        now = datetime.now(tz=job.trigger.timezone)
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

    # Sort by job id so list-jobs output is alphabetical as a gpscheduler
    # contract, independent of APScheduler's iteration order. Today the order
    # happens to be alphabetical only as a gpconfig side-effect
    # (GPConfigManager.list_configs returns sorted items); sorting here isolates
    # us from any future change to that internal behavior.
    jobs = sorted(scheduler.get_jobs(), key=lambda j: j.id)
    if jobs:
        click.echo(f"{len(jobs)} enabled job(s):")
        for j in jobs:
            mr = scheduler.get_job_max_runs(j.id)
            mr_str = str(mr) if mr is not None else "unlimited"
            click.echo(f"  - {j.id}: next run {_next_run_time(j)} (max_runs: {mr_str})")
    else:
        click.echo("No enabled jobs.")

    # Always check for disabled jobs (even when there are no enabled ones). A
    # disabled job is fully validated at load time (Fail-Early) but not
    # registered (ADR-0005), so it does not appear in get_jobs(). Surfacing its
    # name here tells the user it WAS checked, so a green-looking `list-jobs`
    # output is never a surprise failure when `run` re-validates the same
    # config (behavior.02). The line is omitted entirely when N=0 to avoid
    # noise in the common all-enabled case.
    disabled = scheduler.get_disabled_job_names()
    if disabled:
        # Sort for deterministic output, matching the enabled-jobs alphabetical
        # convention (inconsistency.04).
        names = ", ".join(sorted(disabled))
        click.echo(f"{len(disabled)} disabled job(s) validated but not registered: {names}")


if __name__ == "__main__":
    main()
