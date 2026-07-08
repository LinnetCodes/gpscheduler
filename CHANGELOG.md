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

[Unreleased]: https://github.com/LinnetCodes/gpscheduler/compare/initial...HEAD
