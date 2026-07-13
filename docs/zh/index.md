# GPScheduler

GPScheduler（通用调度器，General-Purpose Scheduler）是一个 cron 风格的 Python 调度器。
它通过配置文件把任意包中的函数转化为定时任务，可为任务配置启动参数，并提供装饰器来标记可被调度的函数。

> 本文档为中英双语。点击顶部栏的语言选择器可切换至 English。

## 特性

- **配置驱动的 cron 任务** —— 在 YAML 配置文件中声明调度计划、可调用对象与调用参数，
  无需在应用代码里硬编码定时器。见[配置](configuration.md)。
- **不绑定特定包** —— 任务可指向任意已安装包中可导入的函数，通过 dotted path 定位。
  `@scheduled` 装饰器可直接在源码中标记可调度函数。见
  [API 参考 → scheduled](api.md#scheduled)。
- **两个装饰器** —— `@scheduled` 标记函数为可调度；`@worker_init` 构建一次成本很高的对象
  （数据库连接、网络客户端……），并在该 job 的多次运行中复用。见
  [API 参考 → scheduled](api.md#scheduled) 与 [API 参考 → worker_init](api.md#worker_init)。
- **线程与进程两种 executor** —— 每个 job 各自选择线程池或进程池。I/O 密集型走线程，
  CPU 密集型或需要隔离的走进程。见[性能](performance.md)。
- **按 job 复用的初始化器** —— `@worker_init` 装饰器构建一次成本很高的对象（数据库连接、
  网络客户端……），并在该 job 的多次运行中复用。见
  [API 参考 → worker_init](api.md#worker_init)。
- **调度器级全局变量** —— 共享的配置值（`db_url`、`api_key`……）注入到所有声明了它的
  job 中。见[配置 → job_globals](configuration.md#job_globals-与-gp_globals)。
- **跨平台的优雅关停** —— Windows 下用 `Ctrl+C`，Linux 下用 `SIGINT`/`SIGTERM`，支持可配置
  的关停超时。见 [CLI](cli.md)。
- **Fail-Early 校验** —— 无效的配置（错误的 cron、未注册的函数、参数不匹配、process job 的
  参数不可 pickle）会在加载时立即报错，绝不在首次触发时静默失败。见
  [概览 → Fail-Early](overview.md#fail-early)。
- **可嵌入** —— 可通过 CLI 独立运行，也可嵌入宿主应用。见
  [API 参考 → 嵌入式用法](api.md#嵌入式用法)。

## 安装

```bash
pip install gpscheduler
```

克隆仓库后的本地开发环境：

```bash
source .venv/Scripts/activate   # Windows 下的 Git Bash
pip install -e ".[dev]"
```

## 快速上手

1. 安装 gpscheduler（见上）。
2. 编写一个包含 `@scheduled` 函数的包：

   ```python
   # myjobs/hello.py
   from gpscheduler import scheduled

   @scheduled
   def greet(name: str, *, greeting: str = "Hello") -> None:
       print(f"{greeting}, {name}!")
   ```

3. 用配置文件夹指向它：

   ```yaml
   # configs/scheduler.yaml
   cfg_class_name: GPSchedulerConfig
   configured_class_name: GPScheduler
   executor: thread
   packages: [myjobs]
   ```

   ```yaml
   # configs/jobs/hello.yaml
   cfg_class_name: GPJobConfig
   func: "myjobs.hello.greet"
   cron: "*/2 * * * * *"   # 每 2 秒（6 段式，带前导秒字段）
   args: ["world"]
   kwargs:
     greeting: "Hi"
   ```

   配置文件夹根下还需要一个 `global_env.yaml` —— 底层 [gpconfig](https://github.com/LinnetCodes/gpconfig)
   加载器必需。填一个空的 `{}` 即可（`global_env.yaml` 的用途见 [gpconfig 仓库](https://github.com/LinnetCodes/gpconfig)）：

   ```yaml
   # configs/global_env.yaml
   {}
   ```

4. 运行：

   ```bash
   gpscheduler run --config configs
   ```

完整带注释的 demo 见[使用样例](examples.md)，完整配置参考见[配置](configuration.md)。

## 文档

| 页面 | 内容 |
| --- | --- |
| [概览](overview.md) | 设计目的、架构、使用场景、限制 |
| [API 参考](api.md) | 公共 API：装饰器、类、配置数据类、异常、嵌入式用法 |
| [CLI](cli.md) | `gpscheduler` 命令（`run`、`list-jobs`） |
| [配置](configuration.md) | gpconfig 文件夹布局、配置字段、cron 格式 |
| [使用样例](examples.md) | 端到端 demo 演示 |
| [性能](performance.md) | 线程 vs 进程 executor、跨平台注意事项 |
