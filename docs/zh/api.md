# API 参考

本页文档 gpscheduler 的公共 API 表面：装饰器、引擎类、配置数据类、便捷函数与异常层级。这里
文档化的所有内容都可直接从 `gpscheduler` 包导入。

```python
from gpscheduler import scheduled, worker_init, GPScheduler, GPSchedulerConfig, ...
```

| 章节 | |
| --- | --- |
| [`@scheduled`](#scheduled) | 标记函数为可调度 |
| [`@worker_init`](#worker_init) | 每个执行上下文构建一次可复用对象 |
| [`GPScheduler`](#gpscheduler) | 引擎类 |
| [`GPSchedulerConfig`](#gpschedulerconfig) | 调度器级配置数据类 |
| [`GPJobConfig`](#gpjobconfig) | 单个 job 配置数据类 |
| [`create_scheduler`](#create_scheduler) / [`run_scheduler`](#run_scheduler) | 便捷函数 |
| [异常层级](#异常层级) | gpscheduler 抛出的所有异常 |
| [嵌入式用法](#嵌入式用法) | 如何把 gpscheduler 嵌入宿主应用 |

---

## `@scheduled`

```python
@scheduled
def greet(name: str, *, greeting: str = "Hello") -> None:
    ...
```

标记一个**模块级普通同步函数**为可调度。它是一个裸的、无参数装饰器 —— 使用时不带括号或参数。
它**不**携带调度信息（没有 cron、没有参数）；这些全来自[配置](configuration.md)。装饰器只声明
“gpscheduler 可以调用我”，并在进程全局 Registry 中以 dotted path `"{module}.{qualname}"`
注册该函数。

在装饰时它做语法级校验（见下方契约），违反契约会立即抛出。

### 契约

`@scheduled` 函数必须是：

- 一个**模块级普通同步函数** —— 模块作用域的 `def`；
- **不能是 `async`**（拒绝 `async def`）；
- **不能是 lambda 或嵌套函数**（其 `__qualname__` 不得包含 `<locals>`）；
- **不能是绑定方法、内建函数或可调用实例** —— 只能是普通函数。

违反时抛出 `SignatureContractError`。它还**不得**已被
[`@worker_init`](#worker_init) 装饰 —— 一个函数不能既是初始化器又是被调度的 job。

函数的**参数个数、名字、类型注解、返回类型都不受约束** —— 配置的 `args`/`kwargs` 是否真能绑定
到签名，是在配置加载时检查的（抛 `JobSignatureError`）。调度器**不**消费返回值。

### 为什么是裸装饰器？

`@scheduled` 刻意不接收任何参数。`@scheduled(cron="...")` 会造成双重真理来源（“装饰器里一份
调度计划，配置里一份 —— 谁说了算？”）。把调度信息严格放在配置里，意味着说明 job 何时、如何
运行的地方只有一处。

---

## `@worker_init`

某些 job 需要一个构建成本很高的对象 —— 数据库连接、网络客户端、重量级 client —— 这类对象应当
**只构建一次**并在该 job 的多次调度运行中**复用**，而不是每次执行都重建。

现有的 [`gp_globals`](#保留键) 机制无法满足：它是一个纯 YAML dict，加载时会 pickle 进每个
process job，而一个活跃的连接 handler 既不可 pickle，也不是你想每次重建的东西。`@worker_init`
解决这个问题。它会在**首次执行**该 job 时，在**每个执行上下文**里（thread job 是主进程，
process job 是每个 worker 进程）跑一次初始化器，返回单个对象，之后 gpscheduler 在每次执行时把
该对象注入给 job 函数。

### 快速上手

```python
from gpscheduler import scheduled, worker_init


@worker_init
def init_db(*, gp_globals: dict) -> DbHandler:
    """构建一次重对象。可通过 gp_globals 读配置。"""
    return DbHandler(connect_str=gp_globals["db_url"])


@scheduled
def cleanup(retention_days: int, *, gp_context: DbHandler) -> None:
    # gp_context 是 init_db() 的返回值，每次运行都复用。
    gp_context.execute("DELETE ... WHERE created_at < ?", retention_days)
```

```yaml
# jobs/cleanup.yaml
cfg_class_name: GPJobConfig
func: "mypkg.jobs.cleanup"
cron: "30 3 * * *"
worker_init: "mypkg.jobs.init_db"   # dot-path，与 `func` 同样的约定
args: [7]
```

### 工作机制

| Executor | `worker_init` 何时运行 | 缓存作用域 |
| --- | --- | --- |
| `thread`（默认） | 该 job 首次执行时（lazy） | 主进程，一个对象被所有线程共享 |
| `process` | 该 job 在**每个 worker 进程内**首次执行时（lazy） | 每个 worker 进程独立——各 worker 建各自的对象 |

- 初始化器**每个上下文至多运行一次**；后续执行复用缓存的对象。
- 一个 worker 进程独立于其它 worker 建自己的对象（例如各自的连接）。
- 若初始化器在首次执行时抛错，该次 job 执行失败（按正常的 job 失败处理记录日志），且结果
  **不缓存**——下次执行会重试初始化器。
- 由于对象在执行上下文*内部*构建，从不跨进程边界传递，它可以是**任意类型** —— 活跃 socket、
  锁、ML 模型皆可。只有配置的 `args`/`kwargs` 对 `process` job 需要可 pickle。

### `gp_context` 参数

`gp_context` 是一个**保留关键字参数**（与 `gp_globals` 并列）。job 函数**当且仅当**声明了
`gp_context` 参数**且**其配置声明了 `worker_init` 时才会收到它。两边不匹配是加载时错误
（Fail-Early）：

| 配置 / 签名 | 结果 |
| --- | --- |
| 设了 `worker_init` + 函数声明 `gp_context` | 每次运行注入对象 |
| 设了 `worker_init` + 函数未声明 `gp_context` | 加载时 `JobSignatureError` |
| 函数声明 `gp_context` + 未设 `worker_init` | 加载时 `JobSignatureError` |
| job 的 `kwargs` 里出现 `gp_context` | 加载时 `ReservedKeyError` |

### 配置走 `gp_globals`；对象走 `gp_context`

这两个机制是互补的，不是竞争关系：

- **`gp_globals`** 承载**配置数据** —— 字符串、数字，任何可 pickle 的东西。它来自
  `scheduler.yaml` 的 `job_globals` dict，声明了它的 job 函数和 init 函数都能拿到。
- **`gp_context`** 承载 init 函数构建的**运行时对象**。它在执行上下文内部构建，**从不跨进程
  边界传递**——所以可以是活跃连接、锁，或任何不可 pickle 的对象。

推荐模式：从 `gp_globals` 读连接参数，在 `worker_init` 内部构建重对象，job 里通过
`gp_context` 使用它。

### 线程安全

gpscheduler 保证初始化器在每个执行上下文里只运行**一次**（内部用锁保证）。但返回的对象是否
能在**并发线程**间安全共享是**你的责任**——按对象性质使用连接池、自己加锁，或接受串行化。

对 **process** job，每个 worker 进程有自己独立的对象，不存在跨进程共享的问题。

### `@worker_init` 函数契约

`@worker_init` 函数必须是：

- **模块级普通同步函数**（不能是 `async`、lambda、嵌套函数、绑定方法）——与 `@scheduled`
  相同的规则；
- 可选地声明 `gp_globals` 参数（用于读配置）；
- **不得**声明 `gp_context`（init *生产* context，不消费）；
- **不得**同时被 `@scheduled` 装饰（一个函数不能既是初始化器又是被调度的 job——装饰时强制）。

一个未注册为 `@worker_init` 函数的 `worker_init` dotted path，加载时会抛
`NotWorkerInitError`。

---

## `GPScheduler`

```python
from gpscheduler import GPScheduler, GPSchedulerConfig
```

引擎类。它**组合**（不继承）一个 APScheduler `BackgroundScheduler`，并始终注册**同时**一个
`thread` 和一个 `process` 具名 executor，这样每个 job 都能通过自己的
[`executor`](#gpjobconfig) 字段选择池。

### 构造函数

```python
GPScheduler(config: GPSchedulerConfig)
```

由配置对象构造调度器。构造期间它会**从主线程**获取 `gpclog` logger（gpclog 内部缓存的线程
要求——为什么这很重要见[嵌入式用法](#嵌入式用法)），把 APScheduler 的日志桥接到 `gpclog`，
并用两个 executor（都配置为 `max_workers` 槽位）构建底层的 `BackgroundScheduler`。

通常你**不**直接构造它 —— 用 [`create_scheduler`](#create_scheduler)，它还会从配置加载并校验
job。

### 属性

| 属性 | 类型 | 描述 |
| --- | --- | --- |
| `config` | `GPSchedulerConfig` | 构造调度器所用的配置对象（只读视图）。 |
| `running` | `bool` | 调度器当前是否在运行。 |

### 方法

#### `start() -> None`

启动底层 `BackgroundScheduler` 并**立即返回** —— job 在后台线程上运行。幂等：已启动时为空操作。

#### `shutdown(timeout: float | None = None) -> None`

优雅关停。幂等：未启动时为空操作。

`timeout` 参数覆盖配置级超时。有效超时遵循此优先级链：

```
shutdown(timeout=...) → config.timeout → 永远等待
```

超时如何强制执行因 executor 模型而异 —— 见
[性能 → 关停超时](performance.md#优雅关停超时)。

#### `run() -> None`

启动调度器，**阻塞调用线程**直到收到关停信号，然后关停。这是 CLI `run` 子命令和
[`run_scheduler`](#run_scheduler) 所用的阻塞循环内核。跨平台：Windows 下 `Ctrl+C`，
POSIX 下 `SIGINT`/`SIGTERM`。它自己负责安装关停信号处理器。

#### `register_jobs(loaded) -> None`

注册预加载的一组 job。`create_scheduler` 在加载配置后调用；除非你手工加载了 job，否则通常不用
自己调用。

#### `get_jobs() -> list`

返回当前已注册的 APScheduler job。`gpscheduler list-jobs` 使用它。

---

## `GPSchedulerConfig`

```python
from gpscheduler import GPSchedulerConfig
```

调度器级配置。由**一个**文件还原而来：[配置文件夹](configuration.md#文件夹布局)根目录的
`scheduler.yaml`。它是 `gpconfig.GPConfig` 的子类，`extra="forbid"` —— 未知字段会在加载时被
拒绝。

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `configured_class_name` | `str` | `"GPScheduler"` | gpconfig 钩子；标识 `GPConfigurable`。保持默认。 |
| `executor` | `"thread" \| "process"` | `"thread"` | **默认** executor。单个 job 的 `executor` 可覆盖它。 |
| `timezone` | `str` | `""` | cron 解释所用的时区名（如 `"Asia/Shanghai"`）。空字符串 = 本地时区。 |
| `max_workers` | `int` | `10` | worker 池大小，同时应用于线程池和进程池。 |
| `timeout` | `float \| None` | `None` | 优雅关停超时（秒）。`None` = 永远等待。 |
| `packages` | `list[str]` | `[]` | 加载时导入的包，触发 `@scheduled`/`@worker_init` 注册副作用。 |
| `job_globals` | `dict[str, Any]` | `{}` | 共享配置值，注入到声明了 `gp_globals` 参数的 job/init 函数。 |

示例见[配置](configuration.md)。

## `GPJobConfig`

```python
from gpscheduler import GPJobConfig
```

单个 job 的配置。由**一个**文件还原而来：`jobs/<name>.yaml`。文件名 stem `<name>` 成为 job
id。同样 `extra="forbid"`。

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `func` | `str` | *(必填)* | 指向 `@scheduled` 函数的 dotted path，加载时对 Registry 校验。 |
| `cron` | `str` | *(必填)* | 5 或 6 段 cron 表达式。见 [cron 格式](configuration.md#cron-格式)。 |
| `args` | `list[Any]` | `[]` | 位置参数，按从左到右绑定（`func(*args)`）。 |
| `kwargs` | `dict[str, Any]` | `{}` | 关键字参数，按名字绑定（`func(**kwargs)`）。不得包含保留键。 |
| `executor` | `"thread" \| "process" \| None` | `None` | 单个 job 的 executor 覆盖。`None` 回落到调度器默认值。 |
| `enable` | `bool` | `True` | 为 `False` 时，校验但不注册。 |
| `worker_init` | `str \| None` | `None` | 指向 `@worker_init` 函数的 dotted path。 |
| `max_runs` | `int \| None` | `None` | 可选。限制任务在被自动移除前最多执行的次数（`None` = 无限）。必须是正整数。见[配置 → max_runs](configuration.md#max_runs--限制执行次数)。 |

### 保留键

两个关键字名字是保留的，**绝不能**出现在 job 的 `kwargs` 里（加载时 `ReservedKeyError`）：

- **`gp_globals`** —— 自动注入到任何声明了 `gp_globals` 参数的函数/init；其值来自
  `scheduler.yaml` 的 `job_globals`。
- **`gp_context`** —— 由 `worker_init` 分发器在调用时注入；由声明了 `gp_context` 参数且配置了
  `worker_init` 的 job 接收。

---

## `create_scheduler`

```python
from gpscheduler import create_scheduler

def create_scheduler(
    cfg_folder: Path | str | None = None,
    project_name: str = "gpscheduler",
) -> GPScheduler
```

由 gpconfig 配置文件夹构建 `GPScheduler`。这是 CLI 和[嵌入式用法](#嵌入式用法)的高级入口。它：

1. 初始化 `GPConfigManager(project_name, cfg_folder=...)`。
2. 把 `scheduler.yaml` 加载为 `GPSchedulerConfig`。
3. 构造 `GPScheduler`。
4. 导入 `packages`，然后加载并校验 `jobs/` 下的**所有** job。
5. 注册启用的 job。

它**不启动**调度器 —— 之后调用 `.start()`（非阻塞）或
`.run()`/[`run_scheduler`](#run_scheduler)（阻塞）。

| 参数 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `cfg_folder` | `Path \| str \| None` | `None` | gpconfig 配置文件夹路径。`None` → gpconfig 的搜索（环境变量 `GPSCHEDULER_CFG_PATH`，然后 `~/.gpscheduler/`）。 |
| `project_name` | `str` | `"gpscheduler"` | gpconfig 项目名。 |

任何配置失败都抛 `ConfigError`（或其子类）。

## `run_scheduler`

```python
from gpscheduler import run_scheduler

def run_scheduler(scheduler: GPScheduler) -> None
```

运行一个已构建好的调度器，**阻塞调用线程**直到收到关停信号。`GPScheduler.run()` 的薄封装。CLI
的 `run` 子命令在 `create_scheduler` 之后调用的就是它。

---

## 异常层级

gpscheduler 抛出的所有异常都继承自单一基类 `GPSchedulerError`，所以 `except GPSchedulerError`
能捕获 gpscheduler 抛出的任何异常（包括被翻译包装的底层 gpconfig 错误）。层级为三层 ——
**基类 → 类别 → 叶子** —— 你可以捕获整类或某个具体叶子。

```
GPSchedulerError                     # 一切的基类
├── DecoratorError                   # 装饰器误用
│   └── SignatureContractError       # 函数违反 @scheduled/@worker_init 契约
├── RegistryError                    # 注册表查找问题
│   └── NotScheduledError            # func dotted path 不是已注册的 @scheduled 函数
├── WorkerInitError                  # @worker_init 查找问题
│   └── NotWorkerInitError           # worker_init dotted path 不是已注册的 @worker_init 函数
└── ConfigError                      # 配置问题（包装 gpconfig 失败）
    ├── CronExpressionError          # 无效的 cron 表达式
    ├── InvalidTimezoneError         # 配置的时区不是合法的 IANA 名称
    ├── JobSignatureError            # 配置的 args/kwargs 无法绑定到签名
    ├── MaxRunsError                 # job 的 max_runs 不是正整数（bool/float/<=0）
    ├── PackageImportError           # 配置的 packages 条目无法导入
    └── ReservedKeyError             # job 的 kwargs 用了保留键（gp_globals/gp_context）
```

| 异常 | 何时抛出 |
| --- | --- |
| `SignatureContractError` | 被装饰的函数是 async、lambda、嵌套函数、绑定方法，或同时被 `@scheduled` 和 `@worker_init` 装饰。 |
| `NotScheduledError` | job 的 `func` dotted path 不在 Registry 中（未被 `@scheduled`，或其包未被导入）。 |
| `NotWorkerInitError` | job 的 `worker_init` dotted path 不是已注册的 `@worker_init` 函数。 |
| `CronExpressionError` | cron 表达式段数错误、字段越界、非法字符，或用了 Quartz 扩展。 |
| `InvalidTimezoneError` | 配置的 `timezone` 不是合法的 IANA 时区名。 |
| `JobSignatureError` | 配置的 `args`/`kwargs` 无法绑定到函数签名，`gp_context`/`worker_init` 契约破坏，或 process job 的参数不可 pickle。 |
| `PackageImportError` | `packages` 中的某个包名无法导入。 |
| `ReservedKeyError` | job 的 `kwargs` 包含 `gp_globals` 或 `gp_context`。 |
| `MaxRunsError` | job 的 `max_runs` 不是正整数 —— 是 bool、float（即使 `1.0`）或 `<= 0`。 |
| `ConfigError` | 其它任何配置加载失败，包括被包装的 gpconfig 错误。 |

```python
from gpscheduler import GPSchedulerError

try:
    scheduler = create_scheduler(cfg_folder="configs")
except GPSchedulerError as e:
    # 涵盖上面所有加载/校验失败
    print(f"启动失败: {e}")
```

---

## 嵌入式用法

GPScheduler 可通过 [CLI](cli.md) 独立运行，也可**嵌入**宿主应用 —— web 应用、服务，任何想要
在自己运行时之外再带个后台调度器的东西。CLI 只是嵌入式 API 的薄封装。

### 正确模式

```python
from gpscheduler import create_scheduler

# 1. 构建（加载并校验配置，注册 job）。不启动。
scheduler = create_scheduler(cfg_folder="path/to/configs")

# 2. 启动。立即返回；job 在后台线程运行。
scheduler.start()

# ... 你的宿主应用在这里运行 ...

# 3. 宿主结束时关停。
scheduler.shutdown()
```

### 嵌入时需知

- **建议每个进程一个调度器。** gpscheduler 支持同一进程中存在多个 `GPScheduler`
  实例（每个实例拥有独立的 `worker_init` 缓存，因此不会互相污染运行时对象），但为了
  最简单的心智模型，我们建议每个进程只运行一个调度器。如果你确实运行多个实例，请给它们
  的 job 使用不同的 id，以便日志和事件易于区分。
- **不要阻塞宿主。** 嵌入时用 `start()`（非阻塞），而非 `run()` 或
  [`run_scheduler`](#run_scheduler) —— 它们会阻塞调用线程，仅适用于调度器*本身*就是整个进程的
  独立 CLI 模式。
- **`gpclog` 已在主线程为你初始化。** `GPScheduler.__init__` 在后台调度器线程启动之前，从构造
  它的（主）线程调用 `gpclog.get_logger("gpscheduler")`。这是 `gpclog` 内部缓存的要求。请从主
  线程构造调度器；不要把构造推迟到 worker 线程。
- **所有 job 在构造时加载。** 当前版本没有运行时 `add_job`/`remove_job` —— 要改调度计划，就
  从更新的配置重建调度器。见[概览 → 限制](overview.md#限制)。
- **运行时 job 失败不会拖垮宿主。** job 函数抛出的异常会被 APScheduler executor 捕获、经
  `gpclog` 记录，不向宿主传播。下一次触发正常进行。
- **job 内部日志是 job 自己的责任。** gpscheduler 只记录自己的事件（启动、关停、job 执行
  异常）。*在* job 函数内部产生的日志，由 job 自行配置 —— gpscheduler 不转发也不代为设置。
