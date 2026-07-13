# 命令行接口

GPScheduler 附带一个 `gpscheduler` 控制台命令（作为 `[project.scripts]` 入口点安装）。它有两个
子命令：[`run`](#gpscheduler-run)（启动调度器）和 [`list-jobs`](#gpscheduler-list-jobs)（校验
配置并启用 job 列表，不启动任何东西）。

```
gpscheduler [--help] {run,list-jobs}
```

## 命令

### `gpscheduler run`

从配置文件夹启动调度器并**阻塞**，直到收到关停信号（Windows 下 `Ctrl+C`，POSIX 下
`SIGINT`/`SIGTERM`），然后优雅关停。

```bash
gpscheduler run [--config PATH] [--project NAME]
```

| 选项 | 类型 | 默认值 | 描述 |
| --- | --- | --- | --- |
| `--config` | 路径 | `None` | gpconfig 配置文件夹（`cfg_folder`）路径。省略时使用 gpconfig 的搜索。 |
| `--project` | str | `gpscheduler` | gpconfig 项目名。 |

内部即 `run_scheduler(create_scheduler(cfg_folder=config, project_name=project))`。加载/校验期间
的任何 `GPSchedulerError` 会以 `error: <message>` 打到 stderr，进程以退出码 `1` 退出。一旦运
行，干净关停后进程以 `0` 退出。

**示例：**

```bash
gpscheduler run --config /etc/myapp/scheduler-config
```

### `gpscheduler list-jobs`

一次**预演（dry run）**：加载并校验完整配置（每个 job，启用或禁用都校验），并打印启用 job 及其
下一次触发时间。调度器**不启动**，所以什么都不会执行。用于部署前校验配置，或查看一个正在运行
的调度器会拾起什么。

```bash
gpscheduler list-jobs [--config PATH] [--project NAME]
```

`--config` 和 `--project` 选项及默认值与 `run` 相同。

**示例输出：**

```
4 enabled job(s):
  - cleanup: next run 2026-07-14 03:30:00+08:00 (max_runs: unlimited)
  - compute_stats: next run 2026-07-13 21:06:40+08:00 (max_runs: unlimited)
  - hello: next run 2026-07-13 21:06:34+08:00 (max_runs: 10)
  - ping_db: next run 2026-07-13 21:06:35+08:00 (max_runs: unlimited)
```

Job 按 id 字母序排列。每行末尾显示该 job 的 `max_runs` 设置 —— 正整数，或 `unlimited`（未设上限，
默认值）。见 [配置 → max_runs](configuration.md)。

如果没有启用 job，会打印 `No enabled jobs.`。因为 `list-jobs` 加载的是一个**未启动**的调度器，
下次触发时间直接由每个 job 的 trigger 计算；显示的是“如果现在启动，每个 job *将会*在何时下一次
触发”。

## 配置如何定位

`--config` 映射到 gpconfig 的 `cfg_folder`。省略时 gpconfig 按以下顺序搜索：

1. `--config` 参数（最高优先级）。
2. `{PROJECT}_CFG_PATH` 环境变量（如 `GPSCHEDULER_CFG_PATH`）。
3. 用户的 `~/.{project}/` 目录（如 `~/.gpscheduler/`）。

配置文件夹至少要包含：

```
<cfg_folder>/
├── global_env.yaml      # gpconfig 要求此文件位于文件夹根
├── scheduler.yaml       # GPSchedulerConfig
└── jobs/                # 每个文件一个 GPJobConfig
    ├── ...
```

完整参考见[配置 → 文件夹布局](configuration.md#文件夹布局)。

## 停止调度器

| 平台 | 信号 | 说明 |
| --- | --- | --- |
| **Linux / macOS** | `Ctrl+C`（`SIGINT`）或 `kill <pid>`（`SIGTERM`） | 两者都会被处理；运行优雅关停。 |
| **Windows** | `Ctrl+C`（`SIGINT`） | 受支持的优雅关停路径。 |

Windows 下，`taskkill` 不能可靠送达 `SIGTERM`，且没有直接的 `SIGKILL` 等价物 —— 关闭控制台窗口或
用任务管理器**不保证**运行优雅关停。请用 `Ctrl+C`。完整图景（包括 worker 进程在 `Ctrl+C` 下的
行为）见[性能 → 跨平台注意事项](performance.md#跨平台注意事项)。

收到关停信号后，调度器最多等待 `scheduler.yaml` 的 `timeout` 让运行中的 job 结束（未设
`timeout` 则永远等），然后退出。超时如何强制执行因 executor 模型而异 —— 见
[性能 → 关停超时](performance.md#优雅关停超时)。

## 退出码

| 码 | 含义 |
| --- | --- |
| `0` | 调度器已启动并干净关停。 |
| `1` | 加载/校验期间发生 `GPSchedulerError`（坏配置、未知函数、无效 cron……）。 |
