# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-10-24

First published release. The initial alpha implements the full public
API surface of gpscheduler:

- **Config-driven scheduling** — declare jobs (cron, callable, args) in YAML via
  [gpconfig](https://github.com/LinnetCodes/gpconfig); nothing is hardcoded in
  application code.
- **`create_scheduler_from_cfg_mgr`** — assemble a scheduler from a
  caller-owned `GPConfigManager` at configurable gpconfig dot-addresses
  (`scheduler_path`, `jobs_path`), enabling custom config layouts and manager
  reuse; `create_scheduler` now delegates to it, and `load_jobs` accepts
  `jobs_path`.
- **`@scheduled` decorator** — marks a module-level function as schedulable;
  located by dotted path and validated against a strict process-local Registry.
- **`@worker_init` decorator** — builds an expensive object once per execution
  context and injects it as `gp_context`; never crosses a process boundary.
- **`job_globals` / `gp_globals`** — opt-in scheduler-wide config values injected
  into functions that declare the `gp_globals` parameter.
- **Variable 5/6-segment cron** — paste-compatible with standard crontab, with
  an optional leading-seconds field for sub-minute precision.
- **Thread and process executors** — each job picks its pool; process jobs get
  pickle preflight at load time.
- **`max_runs`** — optional cap on job executions before automatic removal.
- **Fail-Early validation** — bad config, unknown functions, signature
  mismatches, and unpicklable args fail loudly at load time.
- **Cross-platform graceful shutdown** — `Ctrl+C` on Windows, `SIGINT`/`SIGTERM`
  on POSIX, with a configurable timeout.
- **`GPScheduler` engine + CLI** — `create_scheduler`/`run_scheduler` for
  embedded use; `gpscheduler run` / `list-jobs` console commands.
- **Bilingual docs** — English / 简体中文 MkDocs site.

[Unreleased]: https://github.com/LinnetCodes/gpscheduler/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/LinnetCodes/gpscheduler/releases/tag/v0.2.0
