# gpscheduler

[![PyPI 版本](https://img.shields.io/pypi/v/gpscheduler.svg)](https://pypi.org/project/gpscheduler/)
[![Python](https://img.shields.io/pypi/pyversions/gpscheduler.svg)](https://pypi.org/project/gpscheduler/)
[![许可证：MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![文档](https://img.shields.io/badge/docs-mkdocs-blue.svg)](https://linnetcodes.github.io/gpscheduler/zh/)

**GPScheduler**（通用调度器，General-Purpose Scheduler）是一个 cron 风格的 Python 调度器。
它通过配置文件把任意包中的函数转化为定时任务，可为任务配置启动参数，并提供装饰器来标记可被调度的函数。

> **English**: [README.md](README.md)

---

## 特性

- **配置驱动的 cron 任务** —— 在 YAML 配置文件中声明调度计划、可调用对象与调用参数，无需在
  应用代码里硬编码定时器。
- **不绑定特定包** —— 任务可指向任意已安装包中可导入的函数，通过 dotted path 定位。
- **两个装饰器** —— `@scheduled` 标记函数为可调度；`@worker_init` 构建一次成本很高的对象
  （数据库连接、网络客户端……）并在多次运行中复用。
- **线程与进程两种 executor** —— 每个 job 各自选择线程池或进程池。I/O 密集型走线程，CPU 密集
  型或需要隔离的走进程。
- **调度器级全局变量** —— 共享的配置值（`db_url`、`api_key`……）注入到所有声明了它的 job 中。
- **跨平台的优雅关停** —— Windows 下用 `Ctrl+C`，Linux 下用 `SIGINT`/`SIGTERM`，支持可配置的
  关停超时。
- **Fail-Early 校验** —— 无效的配置会在加载时立即报错，绝不在首次触发时静默失败。
- **可嵌入** —— 可通过 CLI 独立运行，也可嵌入宿主应用。

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

1. 安装 gpscheduler（见[安装](#安装)）。

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

   配置文件夹还需要一个 `global_env.yaml`（底层 [gpconfig](https://github.com/LinnetCodes/gpconfig)
   加载器所需）—— 写一个空的 `{}` 即可。

4. 运行：

   ```bash
   gpscheduler run --config configs
   ```

   用 `gpscheduler list-jobs --config configs` 可做一次预演：校验配置并列出启用 job，但不启动
   任何东西。

完整带注释的 demo（涵盖参数、`job_globals` 注入、在线程池和进程池中的 `worker_init` 等）见
文档中的[使用样例](https://linnetcodes.github.io/gpscheduler/zh/examples/)页面。

## 文档

完整文档发布于 <https://linnetcodes.github.io/gpscheduler/zh/>（English / 简体中文）。

## 许可证

[MIT](LICENSE) © LinnetCodes
