# Overview

GPScheduler (General-Purpose Scheduler) is a cron-style Python **library** that turns
functions from any package into scheduled jobs through YAML config files. You mark a
function as schedulable with the `@scheduled` decorator, point a config file at it by
dotted path, declare when it should run with a cron expression, and gpscheduler takes
care of the rest.

## Design purpose

Application code is littered with timers, `while True: sleep(...)` loops, and
hand-rolled schedulers that are hard to audit and harder to change. GPScheduler exists
to move all of that out of application code and into **declarative config**:

- **Schedules live in config, not in code.** A cron expression in a YAML file says
  *when*; the function says *what*. Operators can change timing without touching
  application code, and the full schedule is auditable at a glance.
- **Any importable function can be a job.** Jobs are not subclassed or registered by
  hand — they are pointed at by dotted path (`mypkg.jobs.cleanup`). The `@scheduled`
  decorator is the opt-in signal: *"gpscheduler may call me."*
- **Call arguments come from config too.** Positional and keyword arguments for each
  job are declared in its config file and validated against the function's signature
  at load time.

GPScheduler is a **thin wrapper** around [APScheduler 3.x](https://apscheduler.readthedocs.io/)
— a stable, widely used scheduler engine. It is **not** a distributed scheduler. It
schedules jobs in a **single process**, and focuses on doing that well: config-driven
job definitions, two execution models (thread and process), cross-platform graceful
shutdown, and loud, early validation.

## Architecture

GPScheduler has a single-direction dependency flow. Nothing depends on the engine
except the scheduler module itself, so a future migration would be contained in one
place.

```
                       ┌──────────────┐
   config files ─────▶ │   config     │   GPSchedulerConfig, GPJobConfig
   (gpconfig folder)   └──────┬───────┘   (Pydantic-validated, extra="forbid")
                              │
                              ▼
   @scheduled funcs  ┌──────────────┐
   (imported by ───▶ │   loader     │   validates every job (cron, signature,
    packages)         └──────┬───────┘   registry lookup, pickle preflight) …
         ▲                   │           … returns a list of LoadedJob records
         │                   ▼
   ┌──────────────┐   ┌──────────────┐
   │  registry    │◀──│   cron       │   dotted-path → function map
   │  (process-   │   │  (5/6-field) │   strict lookup, never falls back to
   │   local)     │   └──────────────┘   importlib for undecorated functions
   └──────────────┘
                              │
                              ▼
                       ┌──────────────┐
                       │  scheduler   │   composes APScheduler BackgroundScheduler,
                       │  (engine)    │   registers both "thread" + "process"
                       │              │   executors, handles start/shutdown/signals
                       └──────┬───────┘
                              │
                              ▼
                       ┌──────────────┐
                       │     CLI      │   gpscheduler run / list-jobs
                       └──────────────┘
```

How a job gets from config to execution:

1. **Config load** — gpconfig hydrates `scheduler.yaml` into a `GPSchedulerConfig` and
   each `jobs/<name>.yaml` into a `GPJobConfig`. Unknown keys are rejected.
2. **Package import** — every package in `scheduler.yaml:packages` is imported, which
   fires the `@scheduled` / `@worker_init` registration side-effects and populates the
   process-global Registry.
3. **Per-job validation** — for each job the loader looks up `func` in the Registry,
   parses the cron expression, checks for reserved keys, binds `args`/`kwargs` against
   the function signature, and (for `process` jobs) pickles the arguments as a preflight
   check. Any failure stops startup with a precise exception.
4. **Registration** — enabled jobs are registered with APScheduler under both a `thread`
   and a `process` named executor; each job picks its pool via its `executor` field.
5. **Execution** — APScheduler's background thread fires jobs on schedule, in the chosen
   pool. The scheduler's own logs (startup, shutdown, job-execution exceptions) go
   through `gpclog`.

## Use cases

GPScheduler is a good fit when you want **cron-style scheduling inside a Python
process**, declaratively:

- **Batch housekeeping** — nightly cleanup, daily report generation, weekly index
  rebuilds, declared as config rather than `crontab` lines pointing at separate scripts.
- **Periodic I/O work** — polling an API, pinging a database, flushing a queue on an
  interval. The default **thread** executor and `@worker_init` (reuse one connection)
  are designed for this.
- **CPU-bound periodic work** — data processing, model inference, heavy computation on
  a schedule. The opt-in **process** executor gives real parallelism and process-level
  isolation.
- **Embedding in a host application** — a web app or service that needs a background
  scheduler alongside its own event loop. Use the [embedded API](api.md#embedded-usage)
  (`create_scheduler(...)` then `start()`/`shutdown()`), not the CLI.

GPScheduler is **not** the right tool for: distributed scheduling across multiple
machines, sub-second or event-driven workloads (it is cron-style, not a stream
processor), or jobs that must be `async` (the executors are synchronous).

## Key design principles

### Fail-Early

GPScheduler surfaces problems at **load time**, never at the first trigger. If a cron
expression is malformed, a dotted path isn't registered, configured arguments don't
bind to the signature, or process-job arguments aren't picklable, startup fails with a
precise exception immediately. You will not discover a broken schedule three days into
a production run.

This applies to **disabled jobs too** — a job with `enable: false` is still fully
validated. Disabling a job is not a way to ship broken config; it only skips trigger
registration.

> **Note:** Fail-Early targets *system-design and configuration errors*. It does **not**
> mean a job that raises at runtime crashes the scheduler — runtime job failures are
> caught, logged, and do not affect the next trigger. The scheduler keeps running.

### Single source of truth

The `@scheduled` decorator carries **no** scheduling information — no cron expression,
no arguments, nothing. All of that lives in config. There is one place that says when
and how a job runs, and it is the config file. The decorator only declares *"gpscheduler
may call me."*

### Strict registry lookup

A `func` dotted path in config **must** resolve to a `@scheduled`-decorated function.
gpscheduler never falls back to `importlib` for an undecorated function — the decorator
is your explicit consent to be scheduled, and an unknown path fails loudly at load time
rather than silently calling arbitrary code.

## Limitations

Be aware of the current boundaries:

- **Single-process, not distributed.** No APScheduler 4.x data store or event broker;
  no cross-machine coordination.
- **No `async` jobs.** APScheduler 3.x's synchronous executors are used; `async def`
  functions are rejected by the decorators.
- **No runtime add/remove of jobs.** All jobs are loaded and validated at startup from
  config. Changing the schedule means restarting the scheduler (no hot-reload).
- **No single-job execution timeout.** If a job needs a runtime cap, enforce it inside
  the function (e.g. `signal.alarm`, a thread timeout). The scheduler-level
  `timeout` is for *graceful shutdown* only.
- **Return values are not consumed.** A job that needs to hand off data must do so
  through an external channel (database, queue, file).
- **Windows graceful shutdown is `Ctrl+C`-only.** `SIGTERM` is not reliably delivered
  on Windows; see [Performance → cross-platform](performance.md#cross-platform-notes).
- **Cron supports only POSIX special characters** (`* , - /`); Quartz extensions
  (`L`, `W`, `#`) and a year field are not supported. See
  [Configuration → cron format](configuration.md#cron-format).
