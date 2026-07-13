# GPScheduler

GPScheduler (General-Purpose Scheduler) is a cron-style Python scheduler that turns
functions from any package into scheduled jobs via config files, configures startup
arguments, and exposes a decorator to mark schedulable functions.

> This documentation is bilingual. Use the language selector in the top bar to switch
> to 简体中文.

## Features

- **Config-driven cron jobs** — declare schedules, callables, and call arguments in
  YAML config files; no timers hardcoded in application code. See
  [Configuration](configuration.md).
- **Package-agnostic** — point a job at any importable function in any installed
  package, located by dotted path. The `@scheduled` decorator marks functions as
  schedulable directly in their source. See [API reference](api.md#scheduled).
- **Two decorators** — `@scheduled` marks a function as schedulable; `@worker_init`
  builds an expensive object (DB connection, network client, …) once and reuses it
  across a job's runs. See [API reference → scheduled](api.md#scheduled) and
  [API reference → worker_init](api.md#worker_init).
- **Thread and process executors** — each job picks its own pool. Threads for
  I/O-bound work, processes for CPU-bound or isolated work. See
  [Performance](performance.md).
- **Reusable per-job initialization** — the `@worker_init` decorator builds an
  expensive object (DB connection, network client, …) once and reuses it across a
  job's runs. See [API reference → worker_init](api.md#worker_init).
- **Scheduler-wide globals** — shared config values (`db_url`, `api_key`, …) injected
  into every job that asks for them. See
  [Configuration → job_globals](configuration.md#job_globals-and-gp_globals).
- **Graceful, cross-platform shutdown** — `Ctrl+C` on Windows, `SIGINT`/`SIGTERM` on
  Linux, with a configurable shutdown timeout. See [CLI](cli.md).
- **Fail-Early validation** — invalid config (bad cron, unknown function, argument
  mismatch, unpicklable process args) fails loudly at load time, never silently at the
  first trigger. See [Overview → Fail-Early](overview.md#fail-early).
- **Embeddable** — run it standalone via the CLI, or embed it inside a host
  application. See [API reference → Embedded usage](api.md#embedded-usage).

## Installation

```bash
pip install gpscheduler
```

For local development from a clone:

```bash
source .venv/Scripts/activate   # Git Bash on Windows
pip install -e ".[dev]"
```

## Quick start

1. Install gpscheduler (above).
2. Write a package containing a `@scheduled` function:

   ```python
   # myjobs/hello.py
   from gpscheduler import scheduled

   @scheduled
   def greet(name: str, *, greeting: str = "Hello") -> None:
       print(f"{greeting}, {name}!")
   ```

3. Point a config folder at it:

   ```yaml
   # configs/scheduler.yaml
   cfg_class_name: GPSchedulerConfig
   configured_class_name: GPScheduler
   executor: thread
   packages: [myjobs]
   ```

   ```yaml
   # configs/jobs/hello.yaml
   cfg_class_name: GPJobConfig
   func: "myjobs.hello.greet"
   cron: "*/2 * * * * *"   # every 2 seconds (6-segment, leading seconds field)
   args: ["world"]
   kwargs:
     greeting: "Hi"
   ```

   The config folder also needs a `global_env.yaml` at its root — required by the
   underlying [gpconfig](https://github.com/LinnetCodes/gpconfig) loader. An empty
   `{}` is fine:

   ```yaml
   # configs/global_env.yaml
   {}
   ```

4. Run it:

   ```bash
   gpscheduler run --config configs
   ```

See [Examples](examples.md) for a complete, annotated demo, or read
[Configuration](configuration.md) for the full config reference.

## Documentation

| Page | What it covers |
| --- | --- |
| [Overview](overview.md) | Design purpose, architecture, use cases, limitations |
| [API reference](api.md) | Public API: decorators, classes, config data classes, exceptions, embedded usage |
| [CLI](cli.md) | The `gpscheduler` command (`run`, `list-jobs`) |
| [Configuration](configuration.md) | gpconfig folder layout, config fields, cron format |
| [Examples](examples.md) | End-to-end demo walkthrough |
| [Performance](performance.md) | Thread vs process executors, cross-platform notes |
