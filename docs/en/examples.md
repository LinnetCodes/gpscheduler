# Examples

This page walks through the runnable demo bundled in the repo's `examples/` directory.
It exercises every major feature — arguments, `job_globals` injection, `worker_init` in
both thread and process pools, executor override, `max_runs` (capped executions), and a
disabled job — end to end.

If you have the repo cloned, you can follow along directly; the demo uses only `print()`
for output, so it needs no external services.

## Layout

```
examples/
├── README.md
├── configs/
│   ├── global_env.yaml          # gpconfig requires this at the folder root
│   ├── scheduler.yaml           # GPSchedulerConfig
│   └── jobs/
│       ├── hello.yaml           # args/kwargs
│       ├── cleanup.yaml         # job_globals injection
│       ├── ping_db.yaml         # worker_init (thread executor)
│       ├── compute_stats.yaml   # worker_init (process executor)
│       └── maintenance.yaml     # enable: false
└── demo_jobs/                   # the package imported by `packages: [demo_jobs]`
    ├── __init__.py
    ├── hello.py
    ├── cleanup.py
    ├── db.py
    ├── compute.py
    └── maintenance.py
```

Each job demonstrates one feature:

| Job / file | Feature | Notes |
| --- | --- | --- |
| `hello` | positional + keyword args, `max_runs` | `greet("gpscheduler", greeting="Hi")`, capped at 10 runs |
| `cleanup` | `job_globals` → `gp_globals` injection | reads `work_dir` from injected globals |
| `ping_db` | `worker_init` + `gp_context`, **thread** | one DB handler reused across runs |
| `compute_stats` | `worker_init` + `gp_context`, **process** | heavy object built inside the worker, never pickled |
| `maintenance` | `enable: false` | validated but not registered |

## Prerequisites

Activate the project venv and install the package in editable mode (first time only):

```bash
source .venv/Scripts/activate    # Git Bash on Windows
pip install -e ".[dev]"
```

This makes the `gpscheduler` console command available.

## Run it

You must run from the `examples/` directory so the `demo_jobs` package is importable.
The CLI does not add the current directory to `sys.path`, so set `PYTHONPATH=.` as well.

**Git Bash (Windows) / Linux / macOS:**

```bash
cd examples
PYTHONPATH=. gpscheduler list-jobs --config configs
PYTHONPATH=. gpscheduler run --config configs
```

**PowerShell (Windows):**

```powershell
cd examples
$env:PYTHONPATH = "."
gpscheduler list-jobs --config configs
gpscheduler run --config configs
```

`list-jobs` is a **dry run** — it validates config and prints the enabled jobs without
starting anything. `run` starts the scheduler and blocks until you press `Ctrl+C`.

Expected `list-jobs` output (four enabled jobs):

```
4 enabled job(s):
  - cleanup: next run 2026-07-14 03:30:00+08:00 (max_runs: unlimited)
  - compute_stats: next run 2026-07-14 00:06:10+08:00 (max_runs: unlimited)
  - hello: next run 2026-07-14 00:06:02+08:00 (max_runs: 10)
  - ping_db: next run 2026-07-14 00:06:05+08:00 (max_runs: unlimited)
1 disabled job(s) validated but not registered: maintenance
```

`maintenance` is `enable: false`, so it is validated but not registered — it appears in the
trailing summary line, not in the enabled list above. (Timestamps are illustrative; `list-jobs`
computes them from each job's trigger against the current time.)

## Walkthrough

### 1. `hello` — args and kwargs

```python
# demo_jobs/hello.py
from gpscheduler import scheduled

@scheduled
def greet(name: str, *, greeting: str = "Hello") -> None:
    print(f"[hello] {greeting}, {name}!")
```

```yaml
# configs/jobs/hello.yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.hello.greet"
cron: "*/2 * * * * *"        # 6-segment: every 2 seconds
args: ["gpscheduler"]        # positional -> name
kwargs:
  greeting: "Hi"             # keyword -> greeting
max_runs: 10                 # caps at 10 executions, then auto-removes the job
```

The 6-segment cron (`second minute hour day month dow`) fires every 2 seconds. `args`
maps to the positional `name`; `kwargs` maps to the keyword-only `greeting`.

`max_runs: 10` limits this job to 10 executions. Each invocation counts (whether the
function returns normally or raises). After the 10th run the scheduler removes the job
and logs `job 'hello' reached max_runs=10, removing`. At a 2-second interval that takes
about 20 seconds, after which `hello` stops appearing in the output while the other jobs
keep running. Omit `max_runs` (or set it to `null`) for unlimited executions — the
default, identical to classic cron. See [Configuration](configuration.md) for the full
`max_runs` reference.

### 2. `cleanup` — injecting `job_globals`

```python
# demo_jobs/cleanup.py
from typing import Any
from gpscheduler import scheduled

@scheduled
def cleanup(retention_days: int, *, gp_globals: dict[str, Any]) -> None:
    target_dir = gp_globals.get("work_dir", "/tmp")
    print(f"[cleanup] would remove files older than {retention_days} day(s) from {target_dir}")
```

```yaml
# configs/jobs/cleanup.yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.cleanup.cleanup"
cron: "30 3 * * *"           # 5-segment: daily at 03:30
args: [7]
kwargs: {}                   # gp_globals is injected, never written here
```

The function **declares** `gp_globals`, so gpscheduler injects `scheduler.yaml`'s
`job_globals` dict into it. Note `gp_globals` does **not** appear in `kwargs` — putting
it there would raise `ReservedKeyError`.

### 3. `ping_db` — reusable object via `worker_init` (thread)

```python
# demo_jobs/db.py
import os
from typing import Any
from gpscheduler import scheduled, worker_init

@worker_init
def init_db_handler(*, gp_globals: dict[str, Any]) -> dict[str, Any]:
    db_url = gp_globals["db_url"]
    print(f"[init_db_handler] opening connection to {db_url} (pid={os.getpid()})")
    return {"db_url": db_url, "pid": os.getpid(), "connect_count": 0}

@scheduled
def ping_db(*, gp_context: dict[str, Any]) -> None:
    gp_context["connect_count"] += 1
    print(f"[ping_db] connected to {gp_context['db_url']} "
          f"(pid={gp_context['pid']}, connect_count={gp_context['connect_count']})")
```

```yaml
# configs/jobs/ping_db.yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.db.ping_db"
worker_init: "demo_jobs.db.init_db_handler"
cron: "*/5 * * * * *"        # every 5 seconds
args: []
kwargs: {}
# no executor field -> uses scheduler default ("thread")
```

Because this runs in the **thread** pool, `init_db_handler` runs **once in the main
process** and the same object is shared across every run. Watch the output:
`[init_db_handler]` prints only once, while `[ping_db]`'s `connect_count` increments
every 5 seconds.

### 4. `compute_stats` — `worker_init` across the process boundary

```python
# demo_jobs/compute.py
import os, random
from typing import Any
from gpscheduler import scheduled, worker_init

@worker_init
def init_stats_client(*, gp_globals: dict[str, Any]) -> dict[str, Any]:
    client_id = f"client-{random.randint(1000, 9999)}"
    print(f"[init_stats_client] built client {client_id} "
          f"(api_key={gp_globals['api_key']}, pid={os.getpid()})")
    return {"client_id": client_id, "pid": os.getpid(), "calls": 0}

@scheduled
def compute_stats(dataset: str, *, iterations: int = 1000,
                  gp_context: dict[str, Any]) -> None:
    gp_context["calls"] += 1
    total = sum(i * i for i in range(iterations))
    print(f"[compute_stats] dataset={dataset!r} sum={total} "
          f"(client_id={gp_context['client_id']}, pid={gp_context['pid']}, "
          f"calls={gp_context['calls']})")
```

```yaml
# configs/jobs/compute_stats.yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.compute.compute_stats"
worker_init: "demo_jobs.compute.init_stats_client"
cron: "*/10 * * * * *"        # every 10 seconds
args: ["metrics"]
kwargs:
  iterations: 5000
executor: process             # override the scheduler default
```

This is the most interesting path. `executor: process` sends the job into a spawned
worker process. The worker re-imports `demo_jobs` (re-registering the decorators), then
builds `init_stats_client` **inside the worker** on first execution. The heavy object
never crosses the process boundary — so even though it is just a dict in this demo, it
could equally be a live socket, a lock, or an ML model.

### 5. `maintenance` — disabled but still validated

```yaml
# configs/jobs/maintenance.yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.maintenance.rebuild_index"
cron: "0 2 * * 1"             # every Monday at 02:00
args: []
kwargs: {}
enable: false                 # validated, not registered
```

`enable: false` excludes the job from `run` and from the enabled list in `list-jobs`,
but its config is still fully validated at load — and `list-jobs` prints a trailing
summary line naming it, so you know it was checked. Flip `enable: true` (or remove the
line) and it appears in the enabled list.

## Things to try

The demo is a good playground for gpscheduler's Fail-Early behavior. Each of these
breaks config and should fail loudly at load (`list-jobs` exits with an error before
anything runs):

- **Unknown function** — change `hello.yaml`'s `func` to `demo_jobs.hello.nope` →
  `NotScheduledError`.
- **Reserved key** — add `gp_globals: foo` to some job's `kwargs` → `ReservedKeyError`.
- **Bad cron** — set `cron: "99 * * * *"` → `CronExpressionError`.
- **Signature mismatch** — set `hello.yaml`'s `args: []` (missing required `name`) →
  `JobSignatureError`.
- **Quartz extension** — set `cron: "* * * * * 5L"` → `CronExpressionError`.
- **Enable the disabled job** — set `maintenance.yaml`'s `enable: true` → it appears in
  `list-jobs`.
- **Switch the default executor** — set `scheduler.yaml`'s `executor: process` → every
  job without a per-job override moves to the process pool (note the higher startup cost
  on Windows as workers spawn).
- **Faster smoke test** — temporarily change `hello.yaml`'s cron to `* * * * * *`
  (every second) to see frequent output.

## How gpscheduler finds things

1. The config folder is passed via `--config` (it must contain `global_env.yaml`).
2. `scheduler.yaml` hydrates into a `GPSchedulerConfig`.
3. Every package in `packages:` is imported; importing `demo_jobs` runs its `__init__.py`,
   which imports the job submodules and fires the `@scheduled` / `@worker_init`
   registration side-effects in the global Registry.
4. Each file under `jobs/` hydrates into a `GPJobConfig`; the filename stem becomes the
   job id.
5. Each job's `func` (and `worker_init`, if set) is resolved against the Registry — it
   must exactly equal `"{module}.{qualname}"` of the decorated function, or startup
   raises `NotScheduledError` / `NotWorkerInitError`.

For more, see the [Configuration](configuration.md) and [API reference](api.md) pages.
