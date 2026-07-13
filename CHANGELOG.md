# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No version has been released yet. The initial alpha implements the full public
API surface of gpscheduler:

- **Config-driven scheduling** — declare jobs (cron, callable, args) in YAML via
  [gpconfig](https://github.com/LinnetCodes/gpconfig); nothing is hardcoded in
  application code.
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

[Unreleased]: https://github.com/LinnetCodes/gpscheduler/compare/initial...HEAD
