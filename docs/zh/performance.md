# 性能：线程 vs 进程 executor

每个 GPScheduler 调度器都**同时**注册一个 `thread` executor（APScheduler 的
`ThreadPoolExecutor`）和一个 `process` executor（`ProcessPoolExecutor`），各自大小为
`max_workers`。每个 job 通过 [`executor`](api.md#gpjobconfig) 字段选择池。线程是默认，进程是可
选。本页说明各自的使用时机、可 pickle 约束、`worker_init` 在两者中的行为、优雅关停语义，以及
跨平台差异。

## 选择 executor

| **用线程**（默认）当…… | **用进程**当…… |
| --- | --- |
| job 是 **I/O 密集型**（HTTP、DB、磁盘、网络） | job 是 **CPU 密集型**（数据处理、模型推理、哈希） |
| 你想要**快启动**和共享的内存状态 | 你想要**真正并行**（线程绕不过 CPython 的 GIL） |
| 你需要自由传递**不可 pickle**的对象 | 你想要 job 之间的**进程级隔离** |
| 你想要免费的全局注入（共享内存） | 你希望关停时能**真正强杀**卡住的 job |

### executor 选择优先级

一个 job 的 executor 按以下顺序解析（第一个值胜出）：

```
job.executor  →  scheduler.executor  →  "thread"
```

所以 `scheduler.yaml` 的 `executor` 是**默认**；任何 job 都可通过设置自己的 `executor` 字段
覆盖它。单个调度器可以同时让一些 job 走线程、另一些走进程。

### `max_workers`

单个 `max_workers` 值独立应用于**两个**池 —— 线程池最多可容纳 `max_workers` 个并发线程 job，
进程池最多可容纳 `max_workers` 个并发进程 job。它们是独立的池。

## 可 pickle 约束（进程 job）

进程 job 运行在**派生的 worker 进程**中，这意味着它们的参数要跨进程边界。因此，对任何
`executor: process` 的 job：

- 它的 `args` 和 `kwargs`，
- 注入的 `gp_globals`（即 `scheduler.yaml` 的 `job_globals` 值），

……都必须**可 pickle**。gpscheduler 在加载时强制这一点：它在校验期间对 job 的函数、args、
kwargs 试 pickle，失败就在**启动时**抛 `JobSignatureError`（Fail-Early）—— 而不是在 job 首次
运行时。

线程 job **没有**可 pickle 约束；它可以接受任何参数。

### `worker_init` 为重对象绕开约束

这是 `worker_init` 存在的关键原因。活跃的连接 handler、socket、锁或 ML 模型**不可 pickle**，
所以不能放进 `args`/`kwargs`。但 `worker_init` 在首次执行时**在 worker 进程内部**构建对象并缓
存 —— 对象从不跨进程边界。所以即便是进程 job 也能用一个完全不可 pickle 的对象，只要该对象由
`@worker_init` 函数构建而非作为参数传入。

完整模式见 [API → worker_init](api.md#worker_init)。

## `worker_init` 缓存作用域（按 executor）

`worker_init` 构建的缓存对象，其作用域因 executor 而异：

| Executor | `worker_init` 何时运行 | 缓存作用域 |
| --- | --- | --- |
| `thread` | 该 job 首次执行时（lazy） | 主进程 —— 一个对象被所有线程共享 |
| `process` | 该 job 在**每个 worker 进程内**首次执行时（lazy） | 每个 worker 进程 —— 各 worker 建各自的对象 |

在线程池中，`worker_init` 只跑一次，之后每次运行复用同一个对象（如一个共享的 DB 连接）。在进
程池中，每个 worker 进程在首次使用时独立构建自己的对象（如每个 worker 有自己的连接）。这是设
计使然：进程间无共享内存，所以每个 worker 都需要自己的。

gpscheduler 保证初始化器在每个执行上下文里只运行**一次**（内部用锁）。但返回的对象是否能在
**并发线程**间安全共享是你的责任。

## 优雅关停超时

`scheduler.yaml` 的 `timeout` 字段（或 `shutdown(timeout=...)` 的 `timeout` 参数）限定调度器
等待运行中 job 结束多久后才强制退出：

```
shutdown(timeout=...)  →  config.timeout  →  永远等待
```

- **超时之前：** 两种 executor 模型都等待所有运行中的 job 完成（优雅）。
- **超时之后：** 行为因模型而异 —— 这是需要理解的诚实权衡：

| Executor | 超时之后 |
| --- | --- |
| `thread` | 存活的工作线程被**守护化**。主进程退出，残留线程随之死亡。`finally` 块**不保证**运行，所以中途被打断的 job 可能留下不一致的状态。 |
| `process` | worker 子进程被**终止**（`terminate()`）。它们收到一个终止信号，所以 job 函数的 `try/finally` / `atexit` 有机会运行。 |

两种模型都**保证主进程在超时后退出** —— 这才是用户的真实要求。唯一差异是一个被打断的 job 能
得到多少自救机会。如果你无法容忍任务中途被打断，请用进程模型、设一个宽裕的 `timeout`、或不设
超时（永远等待）。

> **注意：** **没有单次 job 执行超时**。`timeout` 仅是调度器级的优雅关停上限。如果 job 需要运
> 行时长上限，请在函数内部强制（如 POSIX 上的 `signal.alarm`、线程超时）。

## 跨平台注意事项

GPScheduler 同时跑在 Windows 和 Linux 上。下面的差异在实践中很重要。

### 进程启动开销

`ProcessPoolExecutor` 派生全新的 worker 进程。**Linux** 上默认启动方式是 `fork`，相对廉价。
**Windows**（和 macOS）上启动方式是 `spawn`：每个新 worker 从零重新导入整个模块树，包括你的
`packages`。所以：

- 目标包必须**能干净导入**（没有在重新导入下会坏的顶层副作用，没有未解析的导入）。
- 进程 job 在 **Windows** 上的首次运行延迟**高于** Linux。

worker 是池化复用的，所以这个开销按 worker 计，而非按每次 job 运行计。

### `Ctrl+C` 与 worker 进程

Windows 上，`Ctrl+C` 被广播给**整个进程组**，不只是主进程。一个阻塞在工作队列上的进程池
worker 否则会收到该中断，并向 stderr 倾倒一段 `KeyboardInterrupt` 回溯。

GPScheduler 防止了这一点：每个派生的 worker 在初始化期间为 `SIGINT` 安装 `signal.SIG_IGN`，
所以 worker **绝不**响应 `Ctrl+C`。`Ctrl+C` 上的优雅关停完全由主进程独占，**两个**操作系统上都
如此（单一代码路径 —— 没有 per-OS 分支）。你按 `Ctrl+C`，主进程运行优雅关停，worker 进程退出而
不打印杂散回溯。

### 用于关停的信号

| 平台 | 优雅关停信号 |
| --- | --- |
| Linux / macOS | `SIGINT`（`Ctrl+C`）**和** `SIGTERM`（`kill <pid>`） |
| Windows | 仅 `SIGINT`（`Ctrl+C`） |

Windows 上，`taskkill` 不能可靠送达 `SIGTERM`，且关闭控制台窗口或用任务管理器**不保证**运行优
雅关停（进程只得到几秒钟，且 winapi 路径未被处理）。Windows 上请用 `Ctrl+C` 做优雅关停。
Windows 没有直接的 `SIGKILL` 等价物 —— `taskkill /F` 是硬杀，没有优雅路径。见
[CLI → 停止调度器](cli.md#停止调度器)。

### 信号处理器的线程约束

关停信号处理器从**主线程**安装（`signal.signal()` 的要求）。阻塞的 `run()` 循环以短超时轮询一
个 `threading.Event`，而非无限等待 —— 这是一个 Windows 专有的变通，因为无限 `Event.wait()` 会
阻塞在 `WaitForSingleObject` 中，无法被 `Ctrl+C` 可靠唤醒。POSIX 上这种轮询是无害的。这些都
在内部处理，你无需做任何事。

## `gpclog` 初始化

gpscheduler 自身的日志（启动、关停、被 APScheduler executor 捕获的 job 执行异常）走
`gpclog`。有两点需知：

- **logger 从主线程初始化。** `GPScheduler.__init__` 在后台调度器线程启动前获取 `gpclog`
  logger。请从主线程构造调度器；绝不从 job 线程内部首次调用 `gpclog.get_logger(...)`。
  （见 [API → 嵌入式用法](api.md#嵌入式用法)。）
- **进程 worker 重新初始化自己的 logger。** 每个派生的 worker 获取一个带进程号后缀的 per-进程
  logger，所以调度器的日志会按 worker 正确发出。`loguru` handler 不跨进程边界。

job 内部日志（*在* job 函数内部产生的日志）是 **job 自己的**责任 —— gpscheduler 不配置也不转
发它。
