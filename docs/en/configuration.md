# Configuration

GPScheduler is configured entirely through YAML files loaded by
[gpconfig](https://github.com/LinnetCodes/gpconfig). You write a config folder, point
gpscheduler at it (via `--config` or [gpconfig's search](cli.md#how-config-is-located)),
and the scheduler loads, validates, and registers everything at startup.

This page covers the [folder layout](#folder-layout), the [config fields](#scheduler-configuration),
[`job_globals`](#job_globals-and-gp_globals), the [`enable`](#enable-semantics) flag,
and the [cron format](#cron-format). Full field tables also appear in the
[API reference](api.md#gpschedulerconfig).

## Folder layout

A config folder has this shape:

```
<cfg_folder>/
├── global_env.yaml      # REQUIRED by gpconfig — flat key/values at folder root
├── scheduler.yaml       # GPSchedulerConfig — exactly one, the scheduler's own config
└── jobs/                # one file per job; the filename stem is the job id
    ├── hello.yaml
    ├── cleanup.yaml
    └── report.yaml
```

- **`global_env.yaml`** — required by gpconfig at the folder root. It is a flat,
  untyped key/value map exposed read-only via the config manager. gpscheduler itself
  does not read any of its keys; it just needs to be present.
- **`scheduler.yaml`** — exactly one file. Hydrated into a
  [`GPSchedulerConfig`](#scheduler-configuration).
- **`jobs/<name>.yaml`** — one file per job. The filename stem `<name>` becomes the
  APScheduler job id. Hydrated into a [`GPJobConfig`](#job-configuration). A missing
  `jobs/` folder is legal and yields an empty schedule.

The same function can be configured as multiple jobs: `jobs/cleanup_hourly.yaml` and
`jobs/cleanup_daily.yaml` can both point `func` at the same `@scheduled` function with
different cron/args. Adding or removing a job is just adding or removing a file.

Both config classes forbid unknown keys (`extra="forbid"`): a typo in a field name is
rejected at load time, not silently ignored.

## Scheduler configuration

`scheduler.yaml` — a [`GPSchedulerConfig`](api.md#gpschedulerconfig):

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `configured_class_name` | `str` | `"GPScheduler"` | gpconfig hook; leave as default. |
| `executor` | `"thread" \| "process"` | `"thread"` | Default executor. Per-job `executor` overrides this. |
| `timezone` | `str` | `""` | Timezone name for cron interpretation. Empty = local timezone. |
| `max_workers` | `int` | `10` | Worker pool size, applied to **both** the thread and the process pool. |
| `timeout` | `float \| None` | `None` | Graceful-shutdown timeout (seconds). `None` = wait forever. |
| `packages` | `list[str]` | `[]` | Packages to import at load time (fires `@scheduled`/`@worker_init` registration). |
| `job_globals` | `dict[str, Any]` | `{}` | Shared values injected into jobs/init functions that declare `gp_globals`. See below. |

**Example** (from the demo):

```yaml
cfg_class_name: GPSchedulerConfig       # required by gpconfig auto-detection
configured_class_name: GPScheduler
executor: thread                         # default executor; jobs may override
timezone: "Asia/Shanghai"               # empty string = local timezone
max_workers: 10
timeout: 600                             # graceful-shutdown seconds; null = wait forever
packages:
  - demo_jobs
job_globals:
  work_dir: "/tmp/gpscheduler_demo"
  db_url: "postgresql://localhost/demo"
  api_key: "sk-demo-key-EXAMPLE"
```

## Job configuration

`jobs/<name>.yaml` — a [`GPJobConfig`](api.md#gpjobconfig). The filename stem is the
job id.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `func` | `str` | *(required)* | Dotted path to a `@scheduled` function. Validated against the Registry at load. |
| `cron` | `str` | *(required)* | 5- or 6-segment cron expression. See [cron format](#cron-format). |
| `args` | `list` | `[]` | Positional arguments, bound left-to-right. |
| `kwargs` | `dict` | `{}` | Keyword arguments. Must **not** contain `gp_globals` or `gp_context`. |
| `executor` | `"thread" \| "process" \| None` | `None` | Per-job executor override. `None` falls back to the scheduler default. |
| `enable` | `bool` | `True` | `False` = validate but don't register. See [enable semantics](#enable-semantics). |
| `worker_init` | `str \| None` | `None` | Dotted path to a `@worker_init` function. See [API → worker_init](api.md#worker_init). |
| `max_runs` | `int \| null` | `None` | Optional. Caps the number of times the job executes before being automatically removed from the scheduler (`None` = unlimited). Must be a positive integer. See below. |

**`func` is the decorator's registry key** — exactly `"{function.__module__}.{function.__qualname__}"`.
For a module-level function `greet` in `myjobs/hello.py` (importable as `myjobs.hello`),
that is `myjobs.hello.greet`. A mismatch raises `NotScheduledError` at load (Fail-Early).

**`args`/`kwargs` are bind-checked** against the function signature at load time. If they
can't bind, you get a `JobSignatureError` immediately — not at the first trigger.

**Example** (positional + keyword args):

```yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.hello.greet"
cron: "*/2 * * * * *"     # every 2 seconds — 6-segment form with leading seconds
args: ["gpscheduler"]     # greet("gpscheduler", greeting="Hi")
kwargs:
  greeting: "Hi"
```

**Example** (`worker_init` + process executor):

```yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.compute.compute_stats"
worker_init: "demo_jobs.compute.init_stats_client"
cron: "*/10 * * * * *"
args: ["metrics"]
kwargs:
  iterations: 5000
executor: process         # override the scheduler default ("thread")
```

## `job_globals` and `gp_globals`

`job_globals` (in `scheduler.yaml`) is a dict of **shared configuration values** you want
available to your jobs — a `db_url`, an `api_key`, a working directory, anything picklable.
It is injected into a function **only if that function declares a `gp_globals` parameter**:

```python
# scheduler.yaml:  job_globals: { work_dir: "/var/work", db_url: "..." }

@scheduled
def cleanup(retention_days: int, *, gp_globals: dict) -> None:
    # gp_globals == { "work_dir": "/var/work", "db_url": "..." }
    target = gp_globals["work_dir"]
    ...
```

Injection is **opt-in per function**: a function that does not declare `gp_globals`
simply doesn't receive it. `gp_globals` is a reserved kwarg name — never put it in a
job's own `kwargs` (load-time `ReservedKeyError`). Both job functions and
[`@worker_init`](api.md#worker_init) functions may declare it.

The idiomatic split:

- **`gp_globals`** carries **configuration** (picklable values from `job_globals`).
- **`gp_context`** carries the **runtime object** built by `worker_init` (never crosses a
  process boundary). See [API → worker_init](api.md#worker_init).

## `enable` semantics

`enable: false` means *"validate this job but don't register it."* The job still goes
through the full load-time validation — Registry lookup, cron parse, signature bind — so
a disabled job with a typo or a stale cron **still fails startup**. `enable` controls
trigger registration, orthogonally to validation.

This is Fail-Early in action: you won't discover your disabled job's config was broken
only when you flip `enable` back to `true`.

```yaml
enable: false   # validated, but excluded from list-jobs and run
```

## `max_runs` — limiting executions

Set `max_runs: N` to make a job run at most `N` times and then stop. Each actual
invocation counts (whether the function returns normally or raises). After the
`N`-th execution the scheduler removes the job and logs an info message.

- **Omit the field (or set `null`)** for unlimited executions — the default,
  identical to classic cron behavior.
- **The counter is in-memory and process-local.** If the process restarts,
  counting resets; the job runs up to `N` times again in the new process.
- Runs skipped due to `max_instances=1` (the default) when a previous execution
  is still in progress do **not** count.
- Only positive integers are accepted. Booleans (`true`) and floats (`1.0`)
  are rejected at load time with a `MaxRunsError`, even if they would convert
  losslessly, to avoid ambiguity.

```yaml
# jobs/demo.yaml
cfg_class_name: GPJobConfig
func: mypkg.jobs.demo
cron: "* * * * *"
max_runs: 5   # runs 5 times, then is removed
```

## Cron format

GPScheduler uses a **variable 5/6-segment** cron expression. The number of whitespace-
separated fields decides the semantics — no flag needed.

| Segments | Layout | Meaning |
| --- | --- | --- |
| **5** | `minute hour day month day_of_week` | Standard crontab. Second is implicitly `0` (fires on the minute boundary). Identical to a Linux crontab line. |
| **6** | `second minute hour day month day_of_week` | Explicit leading seconds field — for sub-minute precision. |

### Examples

```text
*/2 * * * * *      6-segment: every 2 seconds
*/5 * * * * *      6-segment: every 5 seconds
30 3 * * *         5-segment: daily at 03:30 (standard crontab — paste directly)
0 2 * * 1          5-segment: every Monday at 02:00 (1 = Monday; POSIX: 0=Sun..6=Sat, 7 also = Sun)
0 0 1 * *          5-segment: at 00:00 on the first day of every month
0 */6 * * *        5-segment: every 6 hours on the hour
```

### Day-of-week numbering (POSIX)

The `day_of_week` field follows **POSIX / Linux crontab** numbering:
**0 = Sunday .. 6 = Saturday (and 7 is also Sunday)**. Case-insensitive 3-letter
names (`sun`, `mon`, `tue`, `wed`, `thu`, `fri`, `sat`) and full names
(`sunday`, `monday`, ...) are supported. Common Vixie-cron abbreviation
variants (`tues`, `weds`, `thurs`) are also accepted. Wrap-around ranges
like `6-0` (Saturday and Sunday), or longer ones like `5-1`
(Fri+Sat+Sun+Mon), are allowed. This matches `man 5 crontab`, so a line
copied from a Linux crontab pastes directly.

### Special characters

Only the POSIX special characters are accepted:

| Char | Meaning |
| --- | --- |
| `*` | any value (the whole range) |
| `,` | list of values (`1,15,30`) |
| `-` | range (`1-5`) |
| `/` | step (`*/15`, `10-20/2`) |

**Quartz extensions are rejected**: `L` (last), `W` (nearest weekday), `#` (nth weekday)
are **not** supported, and there is **no year field** (no 7-segment form). Using one
raises `CronExpressionError` at load.

### `day` and `day_of_week` are OR-ed

This is a classic cron gotcha worth calling out: the `day` and `day_of_week` fields are
combined with **OR**, not AND. `0 0 13 * 5` means *"midnight on the 13th **OR** on any
Friday,"* not *"midnight on Friday the 13th."* This matches standard crontab and
APScheduler semantics.

### Timezone

The `timezone` field in `scheduler.yaml` sets the timezone for **all** cron
interpretation (default: the local timezone). Set it explicitly in production to avoid
ambiguity:

```yaml
timezone: "Asia/Shanghai"
```

### Comparison with traditional cron

| Feature | Traditional UNIX cron (5-field) | Quartz (6/7-field) | GPScheduler (variable 5/6) |
| --- | --- | --- | --- |
| Default form | `min hour day month dow` | `sec min hour day month dow [year]` | 5-field = `min hour day month dow`; 6-field adds leading `sec` |
| Second precision | no | yes | yes (opt-in, via the 6-field form) |
| Paste a Linux crontab line | — | no (needs leading `0` for seconds) | **yes** (the 5-field form is identical) |
| `L` / `W` / `#` | no | yes | **no** |
| Year field | no | yes (7th) | **no** |
| Segment-count ambiguity | fixed 5 | fixed 6/7 | decided by segment count (5 or 6 only) |

GPScheduler's design goal: keep paste-compatibility with standard 5-field crontab (so a
Linux crontab line works unchanged), while allowing an opt-in 6th leading seconds field
for sub-minute precision — without inheriting the Quartz dialect's non-portable
extensions.
