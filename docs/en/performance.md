# Performance: thread vs process executors

Every GPScheduler scheduler registers **both** a `thread` executor (an APScheduler
`ThreadPoolExecutor`) and a `process` executor (a `ProcessPoolExecutor`), each sized to
`max_workers`. Every job picks its pool through the [`executor`](api.md#gpjobconfig)
field. Threads are the default; processes are opt-in. This page explains when to use
each, the picklability constraint, how `worker_init` behaves in each, the graceful-
shutdown semantics, and the cross-platform differences.

## Choosing an executor

| Use **thread** (the default) when… | Use **process** when… |
| --- | --- |
| The job is **I/O-bound** (HTTP, DB, disk, network) | The job is **CPU-bound** (data processing, model inference, hashing) |
| You want **fast startup** and shared in-memory state | You want **true parallelism** (threads can't bypass the CPython GIL) |
| You need to pass **unpicklable** objects around freely | You want **process-level isolation** between jobs |
| You want free global injection (shared memory) | You want shutdown to be able to **actually force-kill** a stuck job |

### Executor selection priority

A job's executor is resolved in this order (the first value wins):

```
job.executor  →  scheduler.executor  →  "thread"
```

So `scheduler.yaml`'s `executor` is the **default**; any job can override it by setting
its own `executor` field. A single scheduler can run some jobs in threads and others in
processes simultaneously.

### `max_workers`

A single `max_workers` value applies to **both** pools independently — the thread pool
can hold up to `max_workers` concurrent thread jobs, and the process pool can hold up to
`max_workers` concurrent process jobs. They are separate pools.

### Per-job execution counters

The scheduler retains an in-memory execution counter for each registered job (covering
**all** jobs, not just those with a `max_runs` cap) for the lifetime of the
`GPScheduler` instance. These counters exist for observability — they do not grow
per-execution beyond a Python int rebind — and are bounded by the fixed set of
registered job ids. Removing a job does **not** clear its counter.

## The picklability constraint (process jobs)

Process jobs run in **spawned worker processes**, which means their arguments must
cross a process boundary. Therefore, for any `executor: process` job:

- its `args` and `kwargs`,
- the injected `gp_globals` (i.e. `scheduler.yaml`'s `job_globals` values),

…must all be **picklable**. gpscheduler enforces this at load time: it test-pickles the
job's function, args, and kwargs during validation, and a failure raises
`JobSignatureError` **at startup** (Fail-Early) — not on the job's first run.

Thread jobs have **no** picklability constraint; they can take any arguments.

### `worker_init` sidesteps the constraint for heavy objects

This is the key reason `worker_init` exists. A live connection handler, a socket, a
lock, or an ML model is **not picklable**, so it cannot live in `args`/`kwargs`. But
`worker_init` builds the object **inside** the worker process on first execution and
caches it there — the object never crosses the process boundary. So even a process job
can use a completely unpicklable object, as long as that object is constructed by a
`@worker_init` function rather than passed as an argument.

See [API → worker_init](api.md#worker_init) for the full pattern.

## `worker_init` cache scope per executor

The cached object built by `worker_init` lives in a different scope depending on the
executor:

| Executor | When `worker_init` runs | Cache scope |
| --- | --- | --- |
| `thread` | First execution of this job (lazy) | Main process — one object shared across all threads |
| `process` | First execution of this job **inside each worker process** (lazy) | Per worker process — each worker builds its own object |

In the thread pool, `worker_init` runs once and every subsequent run reuses the same
object (e.g. one shared DB connection). In the process pool, each worker process builds
its own independent object on first use (e.g. each worker has its own connection). This
is by design: there is no shared memory across processes, so each worker needs its own.

gpscheduler guarantees the initializer runs only **once per execution context** (via an
internal lock). Whether the returned object is safe to share across **concurrent
threads** is your responsibility.

## Process jobs and `stdout`

A process job runs in a **separate spawned worker process**, which has its own
`stdout` buffer independent of the main process. When the main process writes to a
terminal, `stdout` is line-buffered (each `\n` flushes). But when `stdout` is
**redirected to a file or a pipe** — e.g. `gpscheduler run > log.txt`, a systemd unit,
a daemon, or any non-TTY sink — Python switches to **block buffering** (it flushes only
when the buffer fills, ~4–8 KB). Because a worker process is long-lived (pooled and
reused) and typically produces little output, that buffer may not fill for a long time,
so a process job's `print()` output can **appear delayed or absent** in the redirected
file — even though the job executed normally.

This is standard `concurrent.futures.ProcessPoolExecutor` behavior, not a gpscheduler
bug. It affects **only the visibility of `print()`/`stdout`** from process jobs — the
job's actual execution, return value, side effects, and `gpclog` output are unaffected
(`gpclog` writes to its own file with `flush=True`, and does not go through `stdout`).
Thread jobs share the main process's buffer and are normally flushed by other activity,
so they are rarely affected.

How to observe process jobs reliably:

- **Don't rely on `print()`** for diagnostics inside process jobs. Write logs via
  `gpclog` or to a file of your own — both are visible immediately regardless of how the
  process was launched. (This is the recommended practice for *any* job, thread or
  process; see [API → embedded usage](api.md#embedded-usage).)
- **If you must see `stdout` live**, run the scheduler attached to a terminal, or set
  `PYTHONUNBUFFERED=1` (`python -u` also works) so output is flushed on every write.

## Graceful shutdown timeout

The `timeout` field in `scheduler.yaml` (or the `timeout` argument to
`shutdown(timeout=...)`) bounds how long the scheduler waits for running jobs to finish
before forcing exit:

```
shutdown(timeout=...)  →  config.timeout  →  wait forever
```

- **Before the timeout:** both executor models wait for all running jobs to complete
  (graceful).
- **After the timeout:** the behavior differs by model — and this is the honest
  trade-off to understand:

| Executor | After timeout |
| --- | --- |
| `thread` | Surviving worker threads are **daemonized**. The main process exits, and the lingering threads die with it. `finally` blocks are **not** guaranteed to run, so a job interrupted mid-flight may leave state inconsistent. |
| `process` | Worker subprocesses are **terminated** (`terminate()`). They receive a termination signal, so the job function's `try/finally` / `atexit` has a chance to run. |

Both models **guarantee the main process exits after the timeout** — that is the user's
real requirement. The only difference is how much self-rescue opportunity an
interrupted job gets. If you cannot tolerate mid-task interruption, use the process
model, set a generous `timeout`, or set no timeout (wait forever).

> **Note:** there is **no single-job execution timeout**. `timeout` is a scheduler-level
> graceful-shutdown bound only. If a job needs a runtime cap, enforce it inside the
> function (e.g. `signal.alarm` on POSIX, a thread timeout).

## Cross-platform notes

GPScheduler runs on both Windows and Linux. The differences below matter in practice.

### Process startup cost

`ProcessPoolExecutor` spawns fresh worker processes. On **Linux**, the default start
method is `fork`, which is relatively cheap. On **Windows** (and macOS), the start
method is `spawn`: each new worker re-imports the entire module tree from scratch,
including your `packages`. So:

- The target package must **import cleanly** (no top-level side effects that break under
  re-import, no unresolved imports).
- First-run latency for process jobs is **higher on Windows** than on Linux.

Workers are pooled and reused, so this cost is paid per worker, not per job run.

### `Ctrl+C` and worker processes

On Windows, `Ctrl+C` is broadcast to the **entire process group**, not just the main
process. A process-pool worker blocked on its work queue would otherwise receive that
interrupt and dump a `KeyboardInterrupt` traceback to stderr.

GPScheduler prevents this: every spawned worker installs `signal.SIG_IGN` for `SIGINT`
during its initialization, so workers **never** respond to `Ctrl+C`. Graceful shutdown
on `Ctrl+C` is owned exclusively by the main process, on **both** OSes (a single code
path — there is no per-OS branch). You press `Ctrl+C`, the main process runs graceful
shutdown, and worker processes exit without printing spurious tracebacks.

### Signals for shutdown

| Platform | Graceful-shutdown signal(s) |
| --- | --- |
| Linux / macOS | `SIGINT` (`Ctrl+C`) **and** `SIGTERM` (`kill <pid>`) |
| Windows | `SIGINT` (`Ctrl+C`) **only** |

On Windows, `SIGTERM` is not reliably delivered by `taskkill`, and closing the console
window or using Task Manager is **not** guaranteed to run graceful shutdown (the process
gets only a few seconds, and the winapi path isn't handled). Use `Ctrl+C` for graceful
shutdown on Windows. There is no direct `SIGKILL` equivalent on Windows — `taskkill /F`
is a hard kill with no graceful path. See [CLI → stopping](cli.md#stopping-the-scheduler).

### Signal-handler thread constraint

The shutdown signal handler is installed from the **main thread** (a `signal.signal()`
requirement). The blocking `run()` loop polls a `threading.Event` with a short timeout
rather than waiting indefinitely — a Windows-specific workaround because an indefinite
`Event.wait()` blocks in `WaitForSingleObject` and is not reliably woken by `Ctrl+C`.
On POSIX this polling is harmless. This is all handled internally; you don't need to do
anything.

## `gpclog` initialization

gpscheduler's own logs (startup, shutdown, job-execution exceptions captured by the
APScheduler executor) go through `gpclog`. Two things to know:

- **Loggers are initialized from the main thread.** `GPScheduler.__init__` acquires the
  `gpclog` logger before the background scheduler thread starts. Construct the scheduler
  from the main thread; never call `gpclog.get_logger(...)` for the first time from
  inside a job thread. (See [API → embedded usage](api.md#embedded-usage).)
- **Process workers re-initialize their own logger.** Each spawned worker acquires a
  per-process logger with a process-id suffix, so the scheduler's logs are correctly
  emitted per worker. `loguru` handlers don't cross process boundaries.

Job-internal logging (logs produced *inside* a job function) is the **job's**
responsibility — gpscheduler does not configure or forward it.
