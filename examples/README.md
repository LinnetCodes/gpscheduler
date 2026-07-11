# GPScheduler examples

An end-to-end, runnable demo of gpscheduler. It exercises these feature areas:

| Feature | Where to look |
| --- | --- |
| **args/kwargs** (positional + keyword startup args) | `configs/jobs/hello.yaml` → `demo_jobs/hello.py` |
| **job_globals injection** (ADR-0006) | `configs/scheduler.yaml` (`job_globals`) → `demo_jobs/cleanup.py` (declares `gp_globals`) |
| **worker_init + gp_context** (thread) | `configs/jobs/ping_db.yaml` → `demo_jobs/db.py` (`@worker_init` + `gp_context`) |
| **worker_init + gp_context** (process) | `configs/jobs/compute_stats.yaml` → `demo_jobs/compute.py` (`@worker_init` + `executor: process`) |
| **thread/process executor override** (ADR-0013) | `configs/scheduler.yaml` (`executor: thread`) vs `configs/jobs/compute_stats.yaml` (`executor: process`) |
| **enable: false** (validated but not registered, ADR-0005) | `configs/jobs/maintenance.yaml` |

## Layout

```
examples/
├── README.md              # this file
├── demo_jobs/             # the package imported by scheduler.yaml:packages
│   ├── __init__.py        # imports submodules so @scheduled/@worker_init fire
│   ├── hello.py           # greet()            — args/kwargs demo
│   ├── cleanup.py         # cleanup()          — job_globals injection demo
│   ├── db.py              # init_db_handler() + ping_db() — worker_init (thread)
│   ├── compute.py         # init_stats_client() + compute_stats() — worker_init (process)
│   └── maintenance.py     # rebuild_index()    — enable:false demo
└── configs/               # a gpconfig cfg_folder
    ├── global_env.yaml    # required by gpconfig; flat key/value, no cfg_class_name
    ├── scheduler.yaml     # GPSchedulerConfig (exactly one)
    └── jobs/
        ├── hello.yaml
        ├── cleanup.yaml
        ├── ping_db.yaml          # worker_init (thread)
        ├── compute_stats.yaml    # worker_init (process)
        └── maintenance.yaml
```

## How gpscheduler finds things

1. **Config folder** — passed via `--config`. gpconfig requires the folder root
   to contain `global_env.yaml`.
2. **Scheduler config** — `scheduler.yaml` hydrates into `GPSchedulerConfig`
   (gpconfig auto-detects the class via `cfg_class_name`).
3. **Package import** — the loader runs `importlib.import_module(pkg)` for every
   name in `scheduler.yaml:packages`. Importing `demo_jobs` runs its
   `__init__.py`, which imports the job submodules, which triggers `@scheduled`
   registration in the global Registry.
4. **Job discovery** — the loader enumerates `jobs/`; each filename stem becomes
   a job id. Each file hydrates into `GPJobConfig`.
5. **func resolution** — each job's `func` string must EXACTLY equal the
   decorated function's registry key, `f"{__module__}.{__qualname__}"`. A
   mismatch raises `NotScheduledError` at load time (Fail-Early).

## Prerequisites

gpscheduler and its sibling deps must be importable. From the repo root, with
the project venv active:

### Activate the venv

**Git Bash on Windows:**
```bash
source .venv/Scripts/activate
```

**Linux / macOS:**
```bash
source .venv/bin/activate
```

### Install gpscheduler in editable mode (first time only)

```bash
pip install -e ".[dev]"
```

This also makes the `gpscheduler` console command available.

## Run the demo

**You must run from the `examples/` directory** so that the `demo_jobs` package
is on `sys.path` (the loader imports it by name). The installed `gpscheduler`
entry point does **not** add the current directory to `sys.path` the way
`python script.py` does, so set `PYTHONPATH=.` as well:

**Git Bash on Windows:**
```bash
cd examples
PYTHONPATH=. gpscheduler list-jobs --config configs
```

**Linux / macOS (bash/sh):**
```bash
cd examples
PYTHONPATH=. gpscheduler list-jobs --config configs
```

**PowerShell on Windows:**
```powershell
cd examples
$env:PYTHONPATH = "."; gpscheduler list-jobs --config configs
```

### Dry run: list enabled jobs (does not execute them)

```bash
gpscheduler list-jobs --config configs
```

You should see the three enabled jobs (`hello`, `cleanup`, `compute_stats`)
with their next-run times. `maintenance` is `enable: false` and is validated but
deliberately omitted — exactly the ADR-0005 behavior.

### Live run: start the scheduler

```bash
gpscheduler run --config configs
```

The scheduler blocks until you stop it.

**Stop it:**

| Platform | Signal |
| --- | --- |
| Linux / macOS | `Ctrl+C` (SIGINT) |
| Windows | `Ctrl+C` (the CLI handles graceful shutdown; `SIGTERM` has no direct Windows equivalent) |

The `hello` job fires every 2 minutes, so for a quick smoke test you can lower
its cron to `* * * * *` (every minute) in `configs/jobs/hello.yaml` temporarily.

## Things to try

- **Break `func`**: change `func` in `hello.yaml` to `demo_jobs.hello.nope` and
  re-run `list-jobs` → `NotScheduledError` (Fail-Early at load time).
- **Reserve `gp_globals`**: add `gp_globals: foo` to some job's `kwargs` and
  re-run → `ReservedKeyError`.
- **Break the cron**: set `cron: "99 * * * *"` → `CronExpressionError`.
- **Break the signature**: set `hello.yaml` `args: []` (now `greet()` is missing
  its required `name`) → `JobSignatureError`.
- **Enable the disabled job**: set `maintenance.yaml` `enable: true` → it now
  appears in `list-jobs`.
- **Switch the default executor**: set `scheduler.yaml` `executor: process` →
  all jobs without a per-job override now use the process pool.

## Notes

- `examples/` is **gitignored** in this repo (treated like `dev_docs/` — local
  working material). Do not rely on it being present in a fresh clone.
- All job functions in this demo use plain `print()`. In real code, job-internal
  logging is the job's responsibility — gpscheduler does not forward it. The
  scheduler's OWN logs (startup/shutdown/exceptions) go through `gpclog`.
