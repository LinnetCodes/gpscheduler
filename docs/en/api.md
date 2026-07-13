# API reference

This page documents the public API surface of gpscheduler: the decorators, the engine
class, the config data classes, the convenience functions, and the exception hierarchy.
Everything documented here is importable directly from the `gpscheduler` package.

```python
from gpscheduler import scheduled, worker_init, GPScheduler, GPSchedulerConfig, ...
```

| Section | |
| --- | --- |
| [`@scheduled`](#scheduled) | Mark a function as schedulable |
| [`@worker_init`](#worker_init) | Build a reusable object once per execution context |
| [`GPScheduler`](#gpscheduler) | The engine class |
| [`GPSchedulerConfig`](#gpschedulerconfig) | Scheduler-level config data class |
| [`GPJobConfig`](#gpjobconfig) | Per-job config data class |
| [`create_scheduler`](#create_scheduler) / [`run_scheduler`](#run_scheduler) | Convenience functions |
| [Exception hierarchy](#exception-hierarchy) | All exceptions gpscheduler raises |
| [Embedded usage](#embedded-usage) | How to embed gpscheduler in a host application |

---

## `@scheduled`

```python
@scheduled
def greet(name: str, *, greeting: str = "Hello") -> None:
    ...
```

Marks a **module-level plain synchronous function** as schedulable. It is a bare,
parameterless decorator — used without parentheses or arguments. It does **not** carry
scheduling information (no cron, no args); all of that comes from
[config](configuration.md). The decorator only declares *"gpscheduler may call me"* and
registers the function in the process-global Registry under its dotted path
`"{module}.{qualname}"`.

At decoration time it performs syntax-level validation (see the contract below) and
raises immediately if the contract is violated.

### Contract

A `@scheduled` function must be:

- a **module-level plain synchronous function** — `def` at module scope;
- **not `async`** (`async def` is rejected);
- **not a lambda or a nested function** (its `__qualname__` must not contain `<locals>`);
- **not a bound method, builtin, or callable instance** — only plain functions.

On violation it raises `SignatureContractError`. It must also **not** already be
decorated with [`@worker_init`](#worker_init) — a function cannot be both an initializer
and a scheduled job.

The function's **parameter count, names, type hints, and return type are
unconstrained** — whether configured `args`/`kwargs` actually bind to the signature is
checked at config-load time (raises `JobSignatureError`). The scheduler does **not**
consume the return value.

### Why bare?

`@scheduled` deliberately takes no arguments. `@scheduled(cron="...")` would create a
dual source of truth ("one schedule in the decorator, one in config — who wins?").
Keeping scheduling info strictly in config means there is exactly one place that says
when and how a job runs.

---

## `@worker_init`

Some jobs need an expensive-to-construct object — a database connection, a network
client, a heavy client — that should be built **once** and **reused** across the job's
many scheduled runs, not reconstructed on every execution.

The [`gp_globals`](#reserved-keys) mechanism cannot serve this: it is a literal YAML
dict that is pickled into every process job at load time, and a live connection handler
is neither picklable nor something you want to rebuild per run. `@worker_init` solves
this. It runs an initializer **once per execution context** (main process for thread
jobs, each worker process for process jobs) on the job's **first execution**, returns a
single object, and gpscheduler injects that object into the job function on every
execution thereafter.

### Quick start

```python
from gpscheduler import scheduled, worker_init


@worker_init
def init_db(*, gp_globals: dict) -> DbHandler:
    """Build the heavy object once. May read config via gp_globals."""
    return DbHandler(connect_str=gp_globals["db_url"])


@scheduled
def cleanup(retention_days: int, *, gp_context: DbHandler) -> None:
    # gp_context is init_db()'s return value, reused across every run.
    gp_context.execute("DELETE ... WHERE created_at < ?", retention_days)
```

```yaml
# jobs/cleanup.yaml
cfg_class_name: GPJobConfig
func: "mypkg.jobs.cleanup"
cron: "30 3 * * *"
worker_init: "mypkg.jobs.init_db"   # dot-path, same convention as `func`
args: [7]
```

### How it works

| Executor | When `worker_init` runs | Cache scope |
| --- | --- | --- |
| `thread` (default) | First execution of this job (lazy) | Main process, one object shared across all threads |
| `process` | First execution of this job **inside each worker process** (lazy) | Per worker process — each worker builds its own object |

- The initializer runs **at most once per job per context**; subsequent executions
  reuse the cached object.
- A worker process builds its own object independently of other workers (e.g., its own
  connection).
- If the initializer raises on first execution, the job execution fails (logged per the
  normal job-failure handling) and the result is **not** cached — the next execution
  retries the initializer.
- Because the object is constructed *inside* the execution context and never crosses a
  process boundary, it can be **any type** — a live socket, a lock, an ML model. Only
  the configured `args`/`kwargs` need to be picklable for `process` jobs.

### The `gp_context` parameter

`gp_context` is a **reserved keyword parameter** (alongside `gp_globals`). A job
function receives it **if and only if** it declares the `gp_context` parameter **and**
its config declares a `worker_init`. Mismatching the two sides is a load-time error
(Fail-Early):

| Config / signature | Result |
| --- | --- |
| `worker_init` set + func declares `gp_context` | Object injected every run |
| `worker_init` set + func does NOT declare `gp_context` | `JobSignatureError` at load |
| func declares `gp_context` + no `worker_init` set | `JobSignatureError` at load |
| `gp_context` appears in the job's `kwargs` | `ReservedKeyError` at load |

### Config flows through `gp_globals`; objects flow through `gp_context`

These two mechanisms are complementary, not competing:

- **`gp_globals`** carries **configuration data** — strings, numbers, anything
  picklable. It comes from `scheduler.yaml`'s `job_globals` dict and is available to
  both job functions and init functions that declare it.
- **`gp_context`** carries the **runtime object** the init function built. It is
  constructed inside the execution context and **never crosses a process boundary** —
  so it can be a live connection, a lock, or any unpicklable object.

The recommended pattern: read connection parameters from `gp_globals`, build the heavy
object inside `worker_init`, and use it in the job via `gp_context`.

### Thread safety

gpscheduler guarantees the initializer runs only **once** per execution context
(thread-safe via an internal lock). Whether the returned object is safe to share across
**concurrent threads** is **your responsibility** — use a connection pool, add your own
locking, or accept serialization, as appropriate to the object.

For **process** jobs, each worker process has its own independent object, so there is no
cross-process sharing concern.

### `@worker_init` function contract

A `@worker_init` function must be:

- a **module-level plain synchronous function** (not `async`, not a lambda, not a nested
  function, not a bound method) — same rules as `@scheduled`;
- may optionally declare a `gp_globals` parameter (to read config);
- must **not** declare `gp_context` (the init *produces* the context, it does not
  consume one);
- must **not** also be decorated with `@scheduled` (a function cannot be both an
  initializer and a scheduled job — enforced at decoration time).

A `worker_init` dotted path that is not registered as a `@worker_init` function raises
`NotWorkerInitError` at load.

---

## `GPScheduler`

```python
from gpscheduler import GPScheduler, GPSchedulerConfig
```

The engine class. It **composes** (does not inherit) an APScheduler
`BackgroundScheduler` and always registers **both** a `thread` and a `process` named
executor, so each job picks its pool via its [`executor`](#gpjobconfig) field.

### Constructor

```python
GPScheduler(config: GPSchedulerConfig)
```

Constructs the scheduler from a config object. During construction it acquires the
`gpclog` logger **from the main thread** (a threading requirement of gpclog's internal
cache — see [Embedded usage](#embedded-usage) for why this matters), bridges
APScheduler's logging into `gpclog`, and builds the underlying `BackgroundScheduler` with
both executors configured to `max_workers` slots.

You normally do **not** construct this directly — use [`create_scheduler`](#create_scheduler)
which also loads and validates jobs from config.

### Properties

| Property | Type | Description |
| --- | --- | --- |
| `config` | `GPSchedulerConfig` | The config object the scheduler was built from (read-only view). |
| `running` | `bool` | Whether the scheduler is currently running. |

### Methods

#### `start() -> None`

Starts the underlying `BackgroundScheduler` and returns **immediately** — jobs run on a
background thread. Idempotent: a no-op if already started.

#### `shutdown(timeout: float | None = None) -> None`

Gracefully shuts down. Idempotent: a no-op if not started.

The `timeout` argument overrides the config-level timeout. The effective timeout follows
this priority chain:

```
shutdown(timeout=...) → config.timeout → wait forever
```

How the timeout is enforced differs by executor model — see
[Performance → shutdown timeout](performance.md#graceful-shutdown-timeout).

#### `run() -> None`

Starts the scheduler, **blocks the calling thread** until a shutdown signal is received,
then shuts down. This is the blocking-loop kernel used by the CLI's `run` subcommand and
by [`run_scheduler`](#run_scheduler). Cross-platform: `Ctrl+C` on Windows,
`SIGINT`/`SIGTERM` on POSIX. It installs the shutdown signal handler itself.

#### `register_jobs(loaded) -> None`

Registers a pre-loaded list of jobs. Called by `create_scheduler` after loading config;
you normally don't call this yourself unless you loaded jobs manually.

#### `get_jobs() -> list`

Returns the currently-registered APScheduler jobs. Used by `gpscheduler list-jobs`.

---

## `GPSchedulerConfig`

```python
from gpscheduler import GPSchedulerConfig
```

Scheduler-level configuration. Hydrated from **one** file: `scheduler.yaml` at the root
of the [config folder](configuration.md#folder-layout). Subclasses `gpconfig.GPConfig`
with `extra="forbid"` — unknown keys are rejected at load time.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `configured_class_name` | `str` | `"GPScheduler"` | gpconfig hook; identifies the `GPConfigurable`. Leave as default. |
| `executor` | `"thread" \| "process"` | `"thread"` | **Default** executor. Per-job `executor` overrides this. |
| `timezone` | `str` | `""` | Timezone name (e.g. `"Asia/Shanghai"`) for cron interpretation. Empty string = the local timezone. |
| `max_workers` | `int` | `10` | Worker pool size, applied to **both** the thread and the process pool. |
| `timeout` | `float \| None` | `None` | Graceful-shutdown timeout in seconds. `None` = wait forever. |
| `packages` | `list[str]` | `[]` | Packages imported at load time so `@scheduled`/`@worker_init` side-effects fire. |
| `job_globals` | `dict[str, Any]` | `{}` | Shared config values injected into jobs/init functions that declare a `gp_globals` parameter. |

See [Configuration](configuration.md) for examples.

## `GPJobConfig`

```python
from gpscheduler import GPJobConfig
```

Per-job configuration. Hydrated from **one** file: `jobs/<name>.yaml`. The filename stem
`<name>` becomes the job id. Same `extra="forbid"` behavior.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `func` | `str` | *(required)* | Dotted path to a `@scheduled` function, validated against the Registry at load time. |
| `cron` | `str` | *(required)* | A 5- or 6-segment cron expression. See [cron format](configuration.md#cron-format). |
| `args` | `list[Any]` | `[]` | Positional arguments, bound left-to-right (`func(*args)`). |
| `kwargs` | `dict[str, Any]` | `{}` | Keyword arguments, bound by name (`func(**kwargs)`). Must not contain reserved keys. |
| `executor` | `"thread" \| "process" \| None` | `None` | Per-job executor override. `None` falls back to the scheduler default. |
| `enable` | `bool` | `True` | If `False`, the job is validated but not registered. |
| `worker_init` | `str \| None` | `None` | Dotted path to a `@worker_init` function. |
| `max_runs` | `int \| None` | `None` | Optional cap on executions before the job is automatically removed (`None` = unlimited). Must be a positive integer. See [Configuration → max_runs](configuration.md#max_runs--limiting-executions). |

### Reserved keys

Two keyword names are reserved and must **never** appear in a job's `kwargs` (load-time
`ReservedKeyError`):

- **`gp_globals`** — auto-injected into any function/init that declares a `gp_globals`
  parameter; its value comes from `scheduler.yaml`'s `job_globals`.
- **`gp_context`** — injected at call time by the `worker_init` dispatcher; received by
  jobs that declare a `gp_context` parameter and have a `worker_init` configured.

---

## `create_scheduler`

```python
from gpscheduler import create_scheduler

def create_scheduler(
    cfg_folder: Path | str | None = None,
    project_name: str = "gpscheduler",
) -> GPScheduler
```

Builds a `GPScheduler` from a gpconfig config folder. This is the high-level entry
point for both the CLI and [embedded usage](#embedded-usage). It:

1. Initializes `GPConfigManager(project_name, cfg_folder=...)`.
2. Loads `scheduler.yaml` into a `GPSchedulerConfig`.
3. Constructs the `GPScheduler`.
4. Imports `packages`, then loads and validates **all** jobs under `jobs/`.
5. Registers the enabled jobs.

It **does not start** the scheduler — call `.start()` (non-blocking) or
`.run()`/[`run_scheduler`](#run_scheduler) (blocking) afterward.

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `cfg_folder` | `Path \| str \| None` | `None` | Path to the gpconfig config folder. `None` → gpconfig's search (env var `GPSCHEDULER_CFG_PATH`, then `~/.gpscheduler/`). |
| `project_name` | `str` | `"gpscheduler"` | gpconfig project name. |

Raises `ConfigError` (or a subclass) on any config failure.

## `run_scheduler`

```python
from gpscheduler import run_scheduler

def run_scheduler(scheduler: GPScheduler) -> None
```

Runs an already-built scheduler, **blocking the calling thread** until a shutdown
signal. Thin wrapper around `GPScheduler.run()`. This is what the CLI's `run` subcommand
calls after `create_scheduler`.

---

## Exception hierarchy

All exceptions gpscheduler raises inherit from a single base, `GPSchedulerError`, so
`except GPSchedulerError` catches anything gpscheduler raises (including underlying
gpconfig errors, which are translated and wrapped). The hierarchy is three layers —
**base → category → leaf** — so you can catch a whole category or a specific leaf.

```
GPSchedulerError                     # base for everything
├── DecoratorError                   # misuse of a decorator
│   └── SignatureContractError       # function violates the @scheduled/@worker_init contract
├── RegistryError                    # registry lookup problem
│   └── NotScheduledError            # a func dotted path is not a registered @scheduled function
├── WorkerInitError                  # @worker_init lookup problem
│   └── NotWorkerInitError           # a worker_init dotted path is not a registered @worker_init function
└── ConfigError                      # configuration problem (wraps gpconfig failures)
    ├── CronExpressionError          # invalid cron expression
    ├── InvalidTimezoneError         # the configured timezone is not a valid IANA name
    ├── JobSignatureError            # configured args/kwargs can't bind to the signature
    ├── MaxRunsError                 # a job's max_runs is not a positive int (bool/float/<=0)
    ├── PackageImportError           # a configured packages entry could not be imported
    └── ReservedKeyError             # a job's kwargs used a reserved key (gp_globals/gp_context)
```

| Exception | When it's raised |
| --- | --- |
| `SignatureContractError` | A decorated function is async, a lambda, nested, a bound method, or decorated with both `@scheduled` and `@worker_init`. |
| `NotScheduledError` | A job's `func` dotted path is not in the Registry (not `@scheduled`, or its package wasn't imported). |
| `NotWorkerInitError` | A job's `worker_init` dotted path is not a registered `@worker_init` function. |
| `CronExpressionError` | A cron expression has the wrong segment count, an out-of-range field, an illegal character, or a Quartz extension. |
| `InvalidTimezoneError` | The configured `timezone` is not a valid IANA timezone name. |
| `JobSignatureError` | Configured `args`/`kwargs` can't bind to the function signature, a `gp_context`/`worker_init` contract is broken, or a process job's args aren't picklable. |
| `PackageImportError` | A package name in `packages` could not be imported. |
| `ReservedKeyError` | A job's `kwargs` contains `gp_globals` or `gp_context`. |
| `MaxRunsError` | A job's `max_runs` is not a positive integer — a bool, a float (even `1.0`), or `<= 0`. |
| `ConfigError` | Any other config-loading failure, including wrapped gpconfig errors. |

```python
from gpscheduler import GPSchedulerError

try:
    scheduler = create_scheduler(cfg_folder="configs")
except GPSchedulerError as e:
    # covers every load/validation failure above
    print(f"startup failed: {e}")
```

---

## Embedded usage

GPScheduler can run standalone via the [CLI](cli.md), or be **embedded** inside a host
application — a web app, a service, anything that wants a background scheduler alongside
its own runtime. The CLI is just a thin wrapper over the embedded API.

### The correct pattern

```python
from gpscheduler import create_scheduler

# 1. Build (loads + validates config, registers jobs). Does NOT start.
scheduler = create_scheduler(cfg_folder="path/to/configs")

# 2. Start. Returns immediately; jobs run on a background thread.
scheduler.start()

# ... your host application runs here ...

# 3. Shut down when the host is done.
scheduler.shutdown()
```

### Things to know when embedding

- **One scheduler per process is recommended.** gpscheduler supports multiple
  `GPScheduler` instances in the same process (each gets an isolated `worker_init`
  cache, so they won't cross-contaminate runtime objects), but for the simplest
  mental model we recommend one scheduler per process. If you do run multiple
  instances, give their jobs distinct ids to keep logs and events easy to tell
  apart.
- **Don't block the host.** Use `start()` (non-blocking) for embedded use, not `run()`
  or [`run_scheduler`](#run_scheduler) — those block the calling thread and are meant
  for the standalone CLI pattern where the scheduler *is* the whole process.
- **`gpclog` is initialized in the main thread for you.** `GPScheduler.__init__` calls
  `gpclog.get_logger("gpscheduler")` from the constructing (main) thread before the
  background scheduler thread starts. This is required by `gpclog`'s internal cache.
  Construct the scheduler from the main thread; don't defer construction to a worker
  thread.
- **All jobs are loaded at construction.** There is no runtime `add_job`/`remove_job`
  in the current version — to change the schedule, rebuild the scheduler from updated
  config. See [Overview → limitations](overview.md#limitations).
- **Runtime job failures don't crash the host.** A job function that raises is caught
  by the APScheduler executor, logged via `gpclog`, and does not propagate to the host.
  The next trigger fires normally.
- **Job-internal logging is the job's responsibility.** gpscheduler only logs its own
  events (startup, shutdown, job-execution exceptions). Logs produced *inside* a job
  function are the job's to configure — gpscheduler does not forward or set them up.
