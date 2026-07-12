# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project scaffolding: src layout (`src/gpscheduler/`), test suite, docs
  skeleton, and `pyproject.toml` (PEP 621, hatchling build backend).
- Bilingual documentation (English / 简体中文) via `mkdocs-static-i18n`, organized
  by language subdirectory (`docs/en/`, `docs/zh/`); README keeps the `README.zh.md`
  suffix convention.
- `CHANGELOG.md` (Keep a Changelog format) and `AGENTS.md` (contributor/AI-agent
  guidance). PyPI and GitHub Pages publishing are performed manually by the
  maintainer.
- Core scheduler library implemented:
  - `GPSchedulerError` exception hierarchy (3 layers) in `exceptions.py`.
  - `@scheduled` decorator with signature-contract validation + process-local
    `Registry` of dotted-path keys.
  - `GPSchedulerConfig` and `GPJobConfig` gpconfig-backed config classes
    (`extra="forbid"`).
  - Cron expression parser (5/6 segments) → APScheduler `CronTrigger`.
  - Config loader/validator: Registry lookup, cron parse, `signature.bind`,
    reserved-key (`gp_globals`) guard, conditional `job_globals` injection,
    per-job executor with pickle preflight.
  - `GPScheduler` engine (composes `BackgroundScheduler`, always registers
    `thread` + `process` executors), `create_scheduler`, `run_scheduler`.
  - Cross-platform graceful-shutdown signal handling (SIGINT+SIGTERM on POSIX,
    SIGINT on Windows).
  - `gpscheduler` CLI: `run` and `list-jobs` subcommands.
- `apscheduler>=3.10,<4` added as a runtime dependency.
- Per-job `worker_init` initializer: decorate a function with `@worker_init`,
  reference it from a job's `worker_init:` config field (dot-path), and its
  returned object is injected into the job function as `gp_context` on every
  execution. The init runs once per execution context (main process for thread
  jobs, each worker process for process jobs) and is reused thereafter, so
  expensive objects (DB handlers, network clients) are built once, not per run.
  Config flows through `gp_globals`; heavy objects flow through `gp_context`.
  New exceptions: `WorkerInitError`, `NotWorkerInitError`. See ADR-0015.
- Per-job `max_runs` config field: optionally cap how many times a job executes
  before automatic removal. In-memory, process-local counter; `null` (default)
  means unlimited. Invalid values (bool, float, <= 0) raise `MaxRunsError` at
  load time. `list-jobs` displays the configured value (`max_runs: N` or
  `max_runs: unlimited`). See ADR-0016.

### Fixed
- `gpscheduler list-jobs` no longer crashes with `AttributeError: 'apscheduler.job.Job'
  object has no attribute 'next_run_time'` when jobs exist. APScheduler leaves
  `Job.next_run_time` unset until the scheduler starts, and `create_scheduler`
  deliberately does not start it (that is `run_scheduler`'s job), so the dry-run
  listing now computes the next fire time from the trigger directly.
- `gpscheduler run` (Ctrl+C) now shuts down gracefully on Windows. The main
  thread blocked indefinitely on `Event.wait()`, which CPython cannot reliably
  interrupt with SIGINT on Windows, so Ctrl+C failed to exit the process. The
  wait is now a short-timeout poll loop with a `KeyboardInterrupt` backstop;
  the same path remains interruptible on POSIX.
- Process-pool workers no longer dump a `KeyboardInterrupt` traceback to stderr
  on Ctrl+C. On Windows, Ctrl+C is broadcast to the whole process group and an
  uninterruptible worker raised from its `call_queue.get()` block. Workers now
  ignore SIGINT (`SIG_IGN`) so only the main process responds to Ctrl+C (ADR-0014).
- Config-validation errors now include the offending file's path. Previously a
  bad cron or unregistered `func` reported only the job name (filename stem);
  now the message leads with the absolute path (e.g.
  `jobs/compute_stats.yaml: invalid cron expression ...`), making it easy to
  locate which config file is wrong.

[Unreleased]: https://github.com/LinnetCodes/gpscheduler/compare/initial...HEAD
