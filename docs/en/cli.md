# Command-line interface

GPScheduler ships a `gpscheduler` console command (installed as a `[project.scripts]`
entry point). It has two subcommands: [`run`](#gpscheduler-run) (start the scheduler)
and [`list-jobs`](#gpscheduler-list-jobs) (validate config and list enabled jobs
without starting anything).

```
gpscheduler [--help] {run,list-jobs}
```

## Commands

### `gpscheduler run`

Starts the scheduler from a config folder and **blocks** until a shutdown signal is
received (`Ctrl+C` on Windows, `SIGINT`/`SIGTERM` on POSIX), then shuts down gracefully.

```bash
gpscheduler run [--config PATH] [--project NAME]
```

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `--config` | path | `None` | Path to the gpconfig config folder (`cfg_folder`). If omitted, gpconfig's search is used. |
| `--project` | str | `gpscheduler` | gpconfig project name. |

Internally this is `run_scheduler(create_scheduler(cfg_folder=config, project_name=project))`.
Any `GPSchedulerError` during load/validation is printed as `error: <message>` to stderr
and the process exits with code `1`. Once running, the process exits `0` after a clean
shutdown.

**Example:**

```bash
gpscheduler run --config /etc/myapp/scheduler-config
```

### `gpscheduler list-jobs`

A **dry run**: loads and validates the full config (every job, enabled or disabled) and
prints the enabled jobs with their next fire times. The scheduler is **not** started, so
nothing executes. Use this to verify config before a deploy, or to inspect what a
running scheduler would pick up.

```bash
gpscheduler list-jobs [--config PATH] [--project NAME]
```

Same `--config` and `--project` options and defaults as `run`.

**Example output:**

```
4 enabled job(s):
  - cleanup: next run 2026-07-14 03:30:00+08:00 (max_runs: unlimited)
  - compute_stats: next run 2026-07-14 00:06:10+08:00 (max_runs: unlimited)
  - hello: next run 2026-07-14 00:06:02+08:00 (max_runs: 10)
  - ping_db: next run 2026-07-14 00:06:05+08:00 (max_runs: unlimited)
1 disabled job(s) validated but not registered: maintenance
```

Jobs are listed in alphabetical order by job id. Each line shows the job's `max_runs`
setting — a positive integer, or `unlimited` when the job has no cap (the default). See
[Configuration → max_runs](configuration.md).

If there are no enabled jobs, it prints `No enabled jobs.` Because `list-jobs` loads an
**unstarted** scheduler, next-fire times are computed directly from each job's trigger;
they show when each job *would* next fire if the scheduler were started now.

Disabled jobs (`enable: false`) are **fully validated** at load time (Fail-Early) but not
registered with the scheduler — they do not appear in the enabled list above. When one or
more disabled jobs were validated, `list-jobs` prints a trailing summary line naming them:

```
1 disabled job(s) validated but not registered: maintenance
```

This tells you the disabled jobs were checked, so a clean-looking `list-jobs` output is
never a surprise failure when `gpscheduler run` re-validates the same config. The names are
sorted alphabetically (same convention as the enabled list), and the line is omitted
entirely when there are no disabled jobs (no noise for the common case).

## How config is located

`--config` maps to gpconfig's `cfg_folder`. When it is omitted, gpconfig searches in
order:

1. The `--config` argument (highest priority).
2. The `{PROJECT}_CFG_PATH` environment variable (e.g. `GPSCHEDULER_CFG_PATH`).
3. The user's `~/.{project}/` directory (e.g. `~/.gpscheduler/`).

A config folder must contain at least:

```
<cfg_folder>/
├── global_env.yaml      # gpconfig requires this at the folder root
├── scheduler.yaml       # GPSchedulerConfig
└── jobs/                # one GPJobConfig per file
    ├── ...
```

See [Configuration → folder layout](configuration.md#folder-layout) for the full
reference.

## Stopping the scheduler

| Platform | Signal | Notes |
| --- | --- | --- |
| **Linux / macOS** | `Ctrl+C` (`SIGINT`) or `kill <pid>` (`SIGTERM`) | Both are handled; graceful shutdown runs. |
| **Windows** | `Ctrl+C` (`SIGINT`) | The supported graceful-shutdown path. |

On Windows, `SIGTERM` is not reliably delivered by `taskkill`, and there is no direct
`SIGKILL` equivalent — closing the console window or using Task Manager is **not**
guaranteed to run graceful shutdown. Use `Ctrl+C`. See
[Performance → cross-platform notes](performance.md#cross-platform-notes) for the full
picture, including how worker processes behave under `Ctrl+C`.

After the shutdown signal, the scheduler waits up to `scheduler.yaml`'s `timeout` for
running jobs to finish (or forever if `timeout` is unset), then exits. How that timeout
is enforced differs by executor model — see
[Performance → shutdown timeout](performance.md#graceful-shutdown-timeout).

> **Redirecting output?** When you run `gpscheduler run` with `stdout` redirected to a
> file or pipe (a daemon, systemd, `> log.txt`, …), a **process** job's `print()` output
> may appear delayed or missing — the job still runs normally. See
> [Performance → Process jobs and `stdout`](performance.md#process-jobs-and-stdout).

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The scheduler started and shut down cleanly. |
| `1` | A `GPSchedulerError` occurred during load/validation (bad config, unknown function, invalid cron, …). |
