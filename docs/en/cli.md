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
  - hello: next run 2026-07-12 10:00:02+08:00
  - cleanup: next run 2026-07-13 03:30:00+08:00
  - ping_db: next run 2026-07-12 10:00:05+08:00
  - compute_stats: next run 2026-07-12 10:00:10+08:00
```

If there are no enabled jobs, it prints `No enabled jobs.` Because `list-jobs` loads an
**unstarted** scheduler, next-fire times are computed directly from each job's trigger;
they show when each job *would* next fire if the scheduler were started now.

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

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The scheduler started and shut down cleanly. |
| `1` | A `GPSchedulerError` occurred during load/validation (bad config, unknown function, invalid cron, …). |
