# 配置

GPScheduler 完全通过由 [gpconfig](https://github.com/LinnetCodes/gpconfig) 加载的 YAML 文件来
配置。你写一个配置文件夹，用 `--config` 或 [gpconfig 的搜索](cli.md#配置如何定位)指向它，调度
器在启动时加载、校验并注册一切。

本页涵盖[文件夹布局](#文件夹布局)、[配置字段](#调度器配置)、
[`job_globals`](#job_globals-与-gp_globals)、[`enable`](#enable-语义)标志，以及
[cron 格式](#cron-格式)。完整字段表也见于[API 参考](api.md#gpschedulerconfig)。

## 文件夹布局

一个配置文件夹形如：

```
<cfg_folder>/
├── global_env.yaml      # gpconfig 要求 —— 文件夹根的扁平 key/value
├── scheduler.yaml       # GPSchedulerConfig —— 恰好一个，调度器自身的配置
└── jobs/                # 每个 job 一个文件；文件名 stem 即 job id
    ├── hello.yaml
    ├── cleanup.yaml
    └── report.yaml
```

- **`global_env.yaml`** —— gpconfig 要求它位于文件夹根。它是扁平、无类型的 key/value 映射，通过
  配置管理器只读暴露。gpscheduler 自身不读它的任何键；它只需存在。
- **`scheduler.yaml`** —— 恰好一个文件。还原为
  [`GPSchedulerConfig`](#调度器配置)。
- **`jobs/<name>.yaml`** —— 每个 job 一个文件。文件名 stem `<name>` 成为 APScheduler job id。
  还原为 [`GPJobConfig`](#job-配置)。缺少 `jobs/` 文件夹是合法的，产生空调度计划。

同一个函数可被配置为多个 job：`jobs/cleanup_hourly.yaml` 和 `jobs/cleanup_daily.yaml` 都可把
`func` 指向同一个 `@scheduled` 函数，用不同的 cron/args。增删 job 就是增删文件。

两个配置类都禁止未知字段（`extra="forbid"`）：字段名拼写错误会在加载时被拒绝，绝不静默忽略。

## 调度器配置

`scheduler.yaml` —— 一个 [`GPSchedulerConfig`](api.md#gpschedulerconfig)：

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `configured_class_name` | `str` | `"GPScheduler"` | gpconfig 钩子；保持默认。 |
| `executor` | `"thread" \| "process"` | `"thread"` | 默认 executor。单个 job 的 `executor` 可覆盖它。 |
| `timezone` | `str` | `""` | cron 解释所用的时区名。空字符串 = 本地时区。 |
| `max_workers` | `int` | `10` | worker 池大小，同时应用于线程池和进程池。 |
| `timeout` | `float \| None` | `None` | 优雅关停超时（秒）。`None` = 永远等待。 |
| `packages` | `list[str]` | `[]` | 加载时导入的包（触发 `@scheduled`/`@worker_init` 注册）。 |
| `job_globals` | `dict[str, Any]` | `{}` | 共享值，注入到声明了 `gp_globals` 的 job/init 函数。见下。 |

**示例**（来自 demo）：

```yaml
cfg_class_name: GPSchedulerConfig       # gpconfig 自动探测所需
configured_class_name: GPScheduler
executor: thread                         # 默认 executor；单个 job 可覆盖
timezone: "Asia/Shanghai"               # 空字符串 = 本地时区
max_workers: 10
timeout: 600                             # 优雅关停秒数；null = 永远等
packages:
  - demo_jobs
job_globals:
  work_dir: "/tmp/gpscheduler_demo"
  db_url: "postgresql://localhost/demo"
  api_key: "sk-demo-key-EXAMPLE"
```

## job 配置

`jobs/<name>.yaml` —— 一个 [`GPJobConfig`](api.md#gpjobconfig)。文件名 stem 是 job id。

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `func` | `str` | *(必填)* | 指向 `@scheduled` 函数的 dotted path。加载时对 Registry 校验。 |
| `cron` | `str` | *(必填)* | 5 或 6 段 cron 表达式。见 [cron 格式](#cron-格式)。 |
| `args` | `list` | `[]` | 位置参数，按从左到右绑定。 |
| `kwargs` | `dict` | `{}` | 关键字参数。**不得**包含 `gp_globals` 或 `gp_context`。 |
| `executor` | `"thread" \| "process"` | *(调度器默认)* | 单个 job 的 executor 覆盖。 |
| `enable` | `bool` | `True` | `False` = 校验但不注册。见 [enable 语义](#enable-语义)。 |
| `worker_init` | `str` | *(无)* | 指向 `@worker_init` 函数的 dotted path。见 [API → worker_init](api.md#worker_init)。 |
| `max_runs` | `int \| null` | `null`（无限） | 可选。限制任务在被自动移出调度器前最多执行的次数。必须是正整数。见下文。 |

**`func` 就是装饰器的注册表键** —— 恰好是 `"{function.__module__}.{function.__qualname__}"`。对
`myjobs/hello.py`（可导入为 `myjobs.hello`）中的模块级函数 `greet`，就是
`myjobs.hello.greet`。不匹配会在加载时抛 `NotScheduledError`（Fail-Early）。

**`args`/`kwargs` 在加载时对函数签名做绑定校验。** 若无法绑定，会立即得到
`JobSignatureError` —— 而不是在首次触发时。

**示例**（位置 + 关键字参数）：

```yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.hello.greet"
cron: "*/2 * * * * *"     # 每 2 秒 —— 带前导秒的 6 段式
args: ["gpscheduler"]     # greet("gpscheduler", greeting="Hi")
kwargs:
  greeting: "Hi"
```

**示例**（`worker_init` + 进程 executor）：

```yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.compute.compute_stats"
worker_init: "demo_jobs.compute.init_stats_client"
cron: "*/10 * * * * *"
args: ["metrics"]
kwargs:
  iterations: 5000
executor: process         # 覆盖调度器默认（"thread"）
```

## `job_globals` 与 `gp_globals`

`job_globals`（在 `scheduler.yaml` 中）是一组你想让 job 可用的**共享配置值** dict ——
`db_url`、`api_key`、工作目录，任何可 pickle 的东西。它**仅在某个函数声明了 `gp_globals` 参数
时**才注入到该函数：

```python
# scheduler.yaml:  job_globals: { work_dir: "/var/work", db_url: "..." }

@scheduled
def cleanup(retention_days: int, *, gp_globals: dict) -> None:
    # gp_globals == { "work_dir": "/var/work", "db_url": "..." }
    target = gp_globals["work_dir"]
    ...
```

注入是**按函数选择加入**：未声明 `gp_globals` 的函数就不会收到它。`gp_globals` 是保留关键字
名 —— 绝不要把它写进 job 自己的 `kwargs`（加载时 `ReservedKeyError`）。job 函数和
[`@worker_init`](api.md#worker_init) 函数都可声明它。

惯用分工：

- **`gp_globals`** 承载**配置**（来自 `job_globals` 的可 pickle 值）。
- **`gp_context`** 承载 `worker_init` 构建的**运行时对象**（从不跨进程边界）。见
  [API → worker_init](api.md#worker_init)。

## `enable` 语义

`enable: false` 的意思是“校验这个 job 但不注册它”。该 job 仍然走完整的加载时校验 —— Registry
查找、cron 解析、签名绑定 —— 所以一个带拼写错误或过期 cron 的禁用 job **仍然会让启动失败**。
`enable` 控制触发注册，正交于校验。

这就是 Fail-Early 在起作用：你不会等到把 `enable` 翻回 `true` 时才发现配置一直是坏的。

```yaml
enable: false   # 被校验，但从 list-jobs 和 run 中排除
```

## `max_runs` —— 限制执行次数

设置 `max_runs: N` 可让任务最多执行 `N` 次后自动停止。每次实际调用都会计数（无论函数
正常返回还是抛出异常）。第 `N` 次执行后，调度器会移除该任务并记录一条 info 日志。

- **省略该字段（或设为 `null`）**表示无限次执行——这是默认行为，与经典 cron 一致。
- **计数器存在于内存中，仅在当前进程有效。** 进程重启后计数归零，任务会在新进程里
  重新最多执行 `N` 次。
- 因 `max_instances=1`（默认值）导致上一次执行未完成而跳过的触发，**不计入**次数。
- 只接受正整数。布尔值（`true`）和浮点数（`1.0`）即使能无损转换也会在加载时被
  `MaxRunsError` 拒绝，以避免歧义。

```yaml
# jobs/demo.yaml
cfg_class_name: GPJobConfig
func: mypkg.jobs.demo
cron: "* * * * *"
max_runs: 5   # 执行 5 次后被移除
```

## cron 格式

GPScheduler 使用**可变 5/6 段**的 cron 表达式。空白分隔的字段数决定语义 —— 无需标志位。

| 段数 | 布局 | 含义 |
| --- | --- | --- |
| **5** | `minute hour day month day_of_week` | 标准 crontab。秒隐式为 `0`（在分钟边界触发）。与 Linux crontab 行一致。 |
| **6** | `second minute hour day month day_of_week` | 显式的前导秒字段 —— 用于亚分钟精度。 |

### 示例

```text
*/2 * * * * *      6 段：每 2 秒
*/5 * * * * *      6 段：每 5 秒
30 3 * * *         5 段：每天 03:30（标准 crontab —— 可直接粘贴）
0 2 * * 1          5 段：每周一 02:00（1 = 周一；POSIX：0=周日..6=周六，7 亦为周日）
0 0 1 * *          5 段：每月 1 号 00:00
0 */6 * * *        5 段：每 6 小时整点
```

### 星期几编号（POSIX）

`day_of_week` 字段遵循 **POSIX / Linux crontab** 编号：**0 = 周日 .. 6 = 周六（7 亦为周日）**。
支持大小写不敏感的 3 字母缩写（`sun`、`mon`、`tue`、`wed`、`thu`、`fri`、`sat`）及全名
（`sunday`、`monday`...）。允许环绕范围，如 `6-0`（周六与周日）。这与 `man 5 crontab` 一致，
因此可把 Linux crontab 行直接粘贴使用。

### 特殊字符

只接受 POSIX 特殊字符：

| 字符 | 含义 |
| --- | --- |
| `*` | 任意值（整个范围） |
| `,` | 值列表（`1,15,30`） |
| `-` | 范围（`1-5`） |
| `/` | 步长（`*/15`、`10-20/2`） |

**拒绝 Quartz 扩展**：`L`（最后）、`W`（最近工作日）、`#`（第几个）**不支持**，且**没有年份
字段**（没有 7 段式）。使用它们会在加载时抛 `CronExpressionError`。

### `day` 与 `day_of_week` 是“或”关系

这是一个值得点出的经典 cron 陷阱：`day` 与 `day_of_week` 字段以 **OR** 组合，不是 AND。
`0 0 13 * 5` 意思是“13 号午夜**或**任意星期五的午夜”，不是“星期五又恰逢 13 号的午夜”。这与
标准 crontab 和 APScheduler 语义一致。

### 时区

`scheduler.yaml` 的 `timezone` 字段为**所有** cron 解释设定时区（默认：本地时区）。生产环境请
显式设置以避免歧义：

```yaml
timezone: "Asia/Shanghai"
```

### 与传统 cron 对比

| 特性 | 传统 UNIX cron（5 段） | Quartz（6/7 段） | GPScheduler（可变 5/6） |
| --- | --- | --- | --- |
| 默认形式 | `min hour day month dow` | `sec min hour day month dow [year]` | 5 段 = `min hour day month dow`；6 段加前导 `sec` |
| 秒级精度 | 否 | 是 | 是（可选，通过 6 段式） |
| 可粘贴 Linux crontab 行 | — | 否（秒字段需前导 `0`） | **是**（5 段式完全一致） |
| `L` / `W` / `#` | 否 | 是 | **否** |
| 年份字段 | 否 | 是（第 7 段） | **否** |
| 段数歧义 | 固定 5 | 固定 6/7 | 由段数决定（仅 5 或 6） |

GPScheduler 的设计目标：保持与标准 5 段 crontab 的可粘贴兼容（Linux crontab 行原样可用），
同时允许一个可选的第 6 个前导秒字段以支持亚分钟精度 —— 而不继承 Quartz 方言中不可移植的扩展。
