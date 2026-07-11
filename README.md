# gpscheduler

[![PyPI version](https://img.shields.io/pypi/v/gpscheduler.svg)](https://pypi.org/project/gpscheduler/)
[![Python](https://img.shields.io/pypi/pyversions/gpscheduler.svg)](https://pypi.org/project/gpscheduler/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue.svg)](https://linnetcodes.github.io/gpscheduler/)
[![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://github.com/LinnetCodes/gpscheduler/actions)

**GPScheduler** (General-Purpose Scheduler) is a cron-style Python scheduler that turns
functions from any package into scheduled jobs via config files, configures startup
arguments, and exposes a decorator to mark schedulable functions.

> **中文文档**：[README.zh.md](README.zh.md)

---

## Features

- **Config-driven cron jobs** — declare schedules, callables, and call arguments in YAML
  config files; no timers hardcoded in application code.
- **Package-agnostic** — point a job at any importable function in any installed package,
  located by dotted path.
- **Two decorators** — `@scheduled` marks a function as schedulable; `@worker_init` builds
  an expensive object (DB connection, network client, …) once and reuses it across runs.
- **Thread and process executors** — each job picks its own pool. Threads for I/O-bound
  work, processes for CPU-bound or isolated work.
- **Scheduler-wide globals** — shared config values (`db_url`, `api_key`, …) injected into
  every job that asks for them.
- **Graceful, cross-platform shutdown** — `Ctrl+C` on Windows, `SIGINT`/`SIGTERM` on
  Linux, with a configurable shutdown timeout.
- **Fail-Early validation** — invalid config fails loudly at load time, never silently at
  the first trigger.
- **Embeddable** — run standalone via the CLI, or embed it inside a host application.

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

1. Install gpscheduler (see [Installation](#installation)).

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

   The config folder also needs a `global_env.yaml` (required by the underlying
   [gpconfig](https://github.com/LinnetCodes/gpconfig) loader) — an empty `{}` is fine.

4. Run it:

   ```bash
   gpscheduler run --config configs
   ```

   Use `gpscheduler list-jobs --config configs` for a dry run that validates config and
   lists enabled jobs without starting anything.

See the [Examples](https://linnetcodes.github.io/gpscheduler/examples/) page in the docs
for a complete, annotated demo covering arguments, `job_globals` injection, `worker_init`
in both thread and process pools, and more.

## Documentation

Full documentation is published at <https://linnetcodes.github.io/gpscheduler/>
(English / 简体中文).

## License

[MIT](LICENSE) © LinnetCodes
