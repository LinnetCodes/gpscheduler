# 概览

GPScheduler（通用调度器，General-Purpose Scheduler）是一个 cron 风格的 Python **库**，
通过 YAML 配置文件把任意包中的函数转化为定时任务。你用 `@scheduled` 装饰器标记一个可调度
函数，在配置文件中用 dotted path 指向它，用 cron 表达式声明何时运行，其余交给 gpscheduler。

## 设计目的

应用代码里往往充斥着各种定时器、`while True: sleep(...)` 循环、手搓的调度器——难以审计，
更难修改。GPScheduler 的存在就是为了把这些东西从应用代码里挪到**声明式配置**中：

- **调度计划放在配置里，而不是代码里。** YAML 文件中的 cron 表达式说*何时*，函数说*做
  什么*。运维可以不改应用代码就调整时机，整个调度计划一目了然。
- **任意可导入的函数都能成为 job。** job 不需要子类化或手工注册——通过 dotted path
  （`mypkg.jobs.cleanup`）指向即可。`@scheduled` 装饰器是“选择加入”的信号：“gpscheduler
  可以调用我。”
- **调用参数也来自配置。** 每个 job 的位置参数和关键字参数在它的配置文件中声明，并在加载时
  对函数签名做绑定校验。

GPScheduler 是 [APScheduler 3.x](https://apscheduler.readthedocs.io/)（一个稳定、广泛使用的
调度引擎）的**薄封装**。它**不是**分布式调度器。它在**单进程**内调度任务，并专注于把这件事
做好：配置驱动的 job 定义、两种执行模型（线程与进程）、跨平台的优雅关停，以及响亮、即早的校验。

## 架构

GPScheduler 的依赖是单向流动的。除了调度器模块本身，没有任何模块依赖引擎，因此未来若有迁移
只会局限在一个地方。

```
                       ┌──────────────┐
   配置文件 ─────────▶ │   config     │   GPSchedulerConfig, GPJobConfig
   (gpconfig 文件夹)  └──────┬───────┘   （Pydantic 校验，extra="forbid"）
                              │
                              ▼
   @scheduled 函数   ┌──────────────┐
   （由 packages ──▶ │   loader     │   校验每个 job（cron、签名、注册表
    导入而触发）       └──────┬───────┘   查找、pickle 预检）……
         ▲                   │           ……返回一组 LoadedJob 记录
         │                   ▼
   ┌──────────────┐   ┌──────────────┐
   │  registry    │◀──│   cron       │   dotted path → 函数 的映射
   │  （进程本地）  │   │  （5/6 段）   │   严格查找，绝不回退到 importlib
   └──────────────┘   └──────────────┘   去调用未装饰的函数
                              │
                              ▼
                       ┌──────────────┐
                       │  scheduler   │   组合 APScheduler 的 BackgroundScheduler，
                       │  （引擎）     │   同时注册 "thread" + "process" 两个 executor，
                       │              │   处理 start/shutdown/信号
                       └──────┬───────┘
                              │
                              ▼
                       ┌──────────────┐
                       │     CLI      │   gpscheduler run / list-jobs
                       └──────────────┘
```

一个 job 从配置到执行的流程：

1. **加载配置** —— gpconfig 把 `scheduler.yaml` 还原为 `GPSchedulerConfig`，把每个
   `jobs/<name>.yaml` 还原为 `GPJobConfig`。未知字段会被拒绝。
2. **导入包** —— 导入 `scheduler.yaml:packages` 中的每个包，触发 `@scheduled` /
   `@worker_init` 的注册副作用，填充进程全局 Registry。
3. **逐个 job 校验** —— 加载器在 Registry 里查找 `func`，解析 cron 表达式，检查保留键，
   把 `args`/`kwargs` 对函数签名做绑定，并且（对 `process` job）把参数 pickle 一遍做预检。
   任何失败都会以精确异常中止启动。
4. **注册** —— 启用的 job 注册到 APScheduler，同时注册 `thread` 和 `process` 两个具名
   executor；每个 job 通过自己的 `executor` 字段选择池。
5. **执行** —— APScheduler 的后台线程按计划在所选池中触发 job。调度器自身的日志（启动、
   关停、job 执行异常）走 `gpclog`。

## 使用场景

当你想**在 Python 进程内**以声明式方式做 **cron 风格调度**时，GPScheduler 很合适：

- **批处理日常维护** —— 夜间清理、每日报表、每周索引重建，写成配置而不是指向独立脚本的
  `crontab` 行。
- **周期性 I/O 工作** —— 轮询 API、ping 数据库、定时刷队列。默认的**线程** executor 和
  `worker_init`（复用一个连接）正是为此设计。
- **CPU 密集型周期工作** —— 数据处理、模型推理、按计划的重计算。可选的**进程** executor 提供
  真正的并行与进程级隔离。
- **嵌入宿主应用** —— 需要 web 应用或服务自带一个后台调度器时，使用
  [嵌入式 API](api.md#嵌入式用法)（`create_scheduler(...)` 然后 `start()`/`shutdown()`），
  而非 CLI。

GPScheduler **不**适合：跨多机的分布式调度；亚秒级或事件驱动的工作负载（它是 cron 风格，
不是流处理器）；必须是 `async` 的 job（executor 是同步的）。

## 关键设计原则

### Fail-Early

GPScheduler 在**加载时**暴露问题，绝不拖到首次触发。如果 cron 表达式畸形、dotted path 未
注册、配置的参数对不上签名、或 process job 的参数不可 pickle，启动会立刻以精确异常失败。你
不会在生产跑了三天后才发现调度计划是坏的。

这对**禁用的 job**同样成立 —— 一个 `enable: false` 的 job 仍然会被完整校验。禁用 job 不是
装运坏配置的办法；它只跳过触发注册。

> **注意：** Fail-Early 针对的是*系统设计与配置错误*。它**并不**意味着 job 在运行时抛异常会
> 崩掉调度器 —— 运行时 job 失败会被捕获、记日志，且不影响下一次触发。调度器会继续运行。

### 单一真理来源

`@scheduled` 装饰器**不**携带任何调度信息 —— 没有 cron 表达式，没有参数，什么都没有。这些
全在配置里。说明 job 何时、如何运行的地方只有一处，就是配置文件。装饰器只声明“gpscheduler
可以调用我。”

### 严格的注册表查找

配置里的 `func` dotted path **必须**解析到一个被 `@scheduled` 装饰的函数。gpscheduler 绝不
对未装饰的函数回退到 `importlib` —— 装饰器就是你明确的“被调度”授权，未知路径会在加载时响亮
失败，而不是静默调用任意代码。

## 限制

请了解当前的边界：

- **单进程，非分布式。** 没有 APScheduler 4.x 的数据存储 / 事件总线；没有跨机协调。
- **不支持 `async` job。** 使用的是 APScheduler 3.x 的同步 executor；`async def` 会被装饰器
  拒绝。
- **运行时不能增删 job。** 所有 job 在启动时从配置加载并校验。要改调度计划就得重启调度器
  （不支持热重载）。
- **没有单次 job 执行超时。** 若 job 需要运行时长上限，请在函数内部强制（如 `signal.alarm`、
  线程超时）。调度器级的 `timeout` 仅用于*优雅关停*。
- **不消费返回值。** 需要交接数据的 job 必须通过外部通道（数据库、队列、文件）。
- **Windows 的优雅关停只有 `Ctrl+C`。** Windows 下 `SIGTERM` 不可靠送达；见
  [性能 → 跨平台注意事项](performance.md#跨平台注意事项)。
- **cron 仅支持 POSIX 特殊字符**（`* , - /`）；Quartz 扩展（`L`、`W`、`#`）和年份字段不被
  支持。见[配置 → cron 格式](configuration.md#cron-格式)。
