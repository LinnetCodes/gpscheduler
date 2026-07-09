# Worker initialization (`@worker_init`)

Some jobs need an expensive-to-construct object — a database connection, a network
client, a heavy client — that should be built **once** and **reused** across the
job's many scheduled runs, not reconstructed on every execution.

The existing [`gp_globals`](index.md) mechanism cannot serve this: it is a literal
YAML dict that is pickled into every process job at load time, and a live
connection handler is neither picklable nor something you want to rebuild per run.

`@worker_init` solves this. It runs an initializer **once per execution context**
(main process for thread jobs, each worker process for process jobs) on the job's
**first execution**, returns a single object, and gpscheduler injects that object
into the job function on every execution thereafter.

## Quick start

```python
from gpscheduler import scheduled, worker_init


@worker_init
def init_db() -> DbHandler:
    """Build the heavy object once. May read config via gp_globals."""
    return DbHandler(connect_str="...")


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

## How it works

| Executor | When `worker_init` runs | Cache scope |
| --- | --- | --- |
| `thread` (default) | First execution of this job (lazy) | Main process, one object shared across all threads |
| `process` | First execution of this job **inside each worker process** (lazy) | Per worker process — each worker builds its own object |

- The initializer runs **at most once per job per context**; subsequent executions
  reuse the cached object.
- A worker process builds its own object independently of other workers (e.g., its
  own connection).
- If the initializer raises on first execution, the job execution fails (logged
  per the normal job-failure handling) and the result is **not** cached — the next
  execution retries the initializer.

## The `gp_context` parameter

`gp_context` is a **reserved keyword parameter** (alongside `gp_globals`). A job
function receives it **if and only if** it declares the `gp_context` parameter
**and** its config declares a `worker_init`. Mismatching the two sides is a
load-time error (Fail-Early):

| Config / signature | Result |
| --- | --- |
| `worker_init` set + func declares `gp_context` | Object injected every run |
| `worker_init` set + func does NOT declare `gp_context` | `JobSignatureError` at load |
| func declares `gp_context` + no `worker_init` set | `JobSignatureError` at load |
| `gp_context` appears in the job's `kwargs` | `ReservedKeyError` at load |

## Config flows through `gp_globals`; objects flow through `gp_context`

These two mechanisms are complementary, not competing:

- **`gp_globals`** carries **configuration data** — strings, numbers, anything
  picklable. It comes from `scheduler.yaml`'s `job_globals` dict and is available
  to both job functions and init functions that declare it.
- **`gp_context`** carries the **runtime object** the init function built. It is
  constructed inside the execution context and **never crosses a process
  boundary** — so it can be a live connection, a lock, or any unpicklable object.

The recommended pattern: read connection parameters from `gp_globals`, build the
heavy object inside `worker_init`, and use it in the job via `gp_context`.

```python
@worker_init
def init_db(*, gp_globals: dict) -> DbHandler:
    # gp_globals carries the picklable config (a string URL)...
    return DbHandler(connect_str=gp_globals["db_url"])


@scheduled
def report(*, gp_context: DbHandler) -> None:
    # ...and gp_context carries the live DbHandler the init built.
    rows = gp_context.query("SELECT ...")
```

## Thread safety

gpscheduler guarantees the initializer runs only **once** per execution context
(thread-safe via an internal lock). Whether the returned object is safe to share
across **concurrent threads** is **your responsibility** — use a connection pool,
add your own locking, or accept serialization, as appropriate to the object.

For **process** jobs, each worker process has its own independent object, so there
is no cross-process sharing concern.

## `@worker_init` function contract

A `@worker_init` function must be:

- a **module-level plain synchronous function** (not async, not a lambda, not a
  nested function, not a bound method) — same rules as `@scheduled`;
- may optionally declare a `gp_globals` parameter (to read config);
- must **not** declare `gp_context` (the init *produces* the context, it does not
  consume one);
- must **not** also be decorated with `@scheduled` (a function cannot be both an
  initializer and a scheduled job — enforced at decoration time).

A `worker_init` dotted path that is not registered as a `@worker_init` function
raises `NotWorkerInitError` at load.
