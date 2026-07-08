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

- **Config-driven jobs** — declare schedules and callables in a config file instead of
  hardcoding timers in application code.
- **Package-agnostic** — point a job at any importable function in any installed package.
- **Decorator support** — mark a function as schedulable directly in its source.
- **Startup arguments** — pass arguments to jobs at schedule time.

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

*(To be filled in once the core API is implemented.)*

## Documentation

Full documentation is published at <https://linnetcodes.github.io/gpscheduler/>
(English / 简体中文).

## License

[MIT](LICENSE) © LinnetCodes
