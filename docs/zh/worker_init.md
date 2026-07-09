# 工作初始化（`@worker_init`）

某些 job 需要一个构建成本很高的对象——数据库连接、网络客户端、重量级 client——这类对象
应当**只构建一次**并在该 job 的多次调度运行中**复用**，而不是每次执行都重建。

现有的 [`gp_globals`](index.md) 机制无法满足这个需求：它是一个纯 YAML dict，加载时会
pickle 进每个 process job，而一个活跃的连接 handler 既不可 pickle，也不是你想每次重建的
东西。

`@worker_init` 用来解决这个问题。它会在**首次执行**该 job 时，在**每个执行上下文**里（thread
job 是主进程，process job 是每个 worker 进程）跑一次初始化器，返回单个对象，之后 gpscheduler
在每次执行时把这个对象注入给 job 函数。

## 快速上手

```python
from gpscheduler import scheduled, worker_init


@worker_init
def init_db() -> DbHandler:
    """构建一次重对象。可通过 gp_globals 读配置。"""
    return DbHandler(connect_str="...")


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

## 工作机制

| Executor | `worker_init` 何时运行 | 缓存作用域 |
| --- | --- | --- |
| `thread`（默认） | 该 job 首次执行时（lazy） | 主进程，一个对象被所有线程共享 |
| `process` | 该 job 在**每个 worker 进程内**首次执行时（lazy） | 每个 worker 进程独立——各 worker 建各自的对象 |

- 初始化器**每个上下文至多运行一次**；后续执行复用缓存的对象。
- 一个 worker 进程独立于其它 worker 建自己的对象（例如各自的连接）。
- 若初始化器在首次执行时抛错，该次 job 执行失败（按正常的 job 失败处理记录日志），且
  结果**不缓存**——下次执行会重试初始化器。

## `gp_context` 参数

`gp_context` 是一个**保留关键字参数**（与 `gp_globals` 并列）。job 函数**当且仅当**声明了
`gp_context` 参数**且**其配置声明了 `worker_init` 时才会收到它。两边不匹配是加载时错误
（Fail-Early）：

| 配置 / 签名 | 结果 |
| --- | --- |
| 设了 `worker_init` + 函数声明 `gp_context` | 每次运行注入对象 |
| 设了 `worker_init` + 函数未声明 `gp_context` | 加载时 `JobSignatureError` |
| 函数声明 `gp_context` + 未设 `worker_init` | 加载时 `JobSignatureError` |
| job 的 `kwargs` 里出现 `gp_context` | 加载时 `ReservedKeyError` |

## 配置走 `gp_globals`；对象走 `gp_context`

这两个机制是互补的，不是竞争关系：

- **`gp_globals`** 承载**配置数据**——字符串、数字，任何可 pickle 的东西。它来自
  `scheduler.yaml` 的 `job_globals` dict，声明了它的 job 函数和 init 函数都能拿到。
- **`gp_context`** 承载 init 函数构建的**运行时对象**。它在执行上下文内部构建，**从不跨
  进程边界传递**——所以可以是活跃连接、锁，或任何不可 pickle 的对象。

推荐模式：从 `gp_globals` 读连接参数，在 `worker_init` 内部构建重对象，job 里通过
`gp_context` 使用它。

```python
@worker_init
def init_db(*, gp_globals: dict) -> DbHandler:
    # gp_globals 承载可 pickle 的配置（一个字符串 URL）...
    return DbHandler(connect_str=gp_globals["db_url"])


@scheduled
def report(*, gp_context: DbHandler) -> None:
    # ...gp_context 承载 init 构建的活跃 DbHandler。
    rows = gp_context.query("SELECT ...")
```

## 线程安全

gpscheduler 保证初始化器在每个执行上下文里只运行**一次**（内部用锁保证）。但返回的对象
是否能在**并发线程**间安全共享是**你的责任**——按对象性质使用连接池、自己加锁，或接受
串行化。

对 **process** job，每个 worker 进程有自己独立的对象，不存在跨进程共享的问题。

## `@worker_init` 函数契约

`@worker_init` 函数必须是：

- **模块级普通同步函数**（不能是 async、lambda、嵌套函数、绑定方法）——与 `@scheduled`
  相同的规则；
- 可选地声明 `gp_globals` 参数（用于读配置）；
- **不得**声明 `gp_context`（init *生产* context，不消费）；
- **不得**同时被 `@scheduled` 装饰（一个函数不能既是初始化器又是被调度的 job——装饰时
  强制）。

一个未注册为 `@worker_init` 函数的 `worker_init` dotted path，加载时会抛
`NotWorkerInitError`。
