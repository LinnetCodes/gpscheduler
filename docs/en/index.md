# GPScheduler

GPScheduler (General-Purpose Scheduler) is a cron-style Python scheduler that turns
functions from any package into scheduled jobs via config files, configures startup
arguments, and exposes a decorator to mark schedulable functions.

> This documentation is bilingual. Use the language selector in the top bar to switch
> to 简体中文.

## Overview

- **Config-driven jobs** — declare schedules and callables in a config file instead of
  hardcoding timers in application code.
- **Package-agnostic** — point a job at any importable function in any installed package.
- **Decorator support** — mark a function as schedulable directly in its source.
- **Startup arguments** — pass arguments to jobs at schedule time.

> The API reference and tutorials will be filled in as the library takes shape.

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
