# 使用样例

本页走读仓库 `examples/` 目录中附带的可运行 demo。它端到端地演练了每个主要特性 —— 参数、
`job_globals` 注入、在线程池和进程池中的 `worker_init`、executor 覆盖、`max_runs`（限定执行次数），
以及一个禁用的 job。

如果你克隆了仓库，可以直接跟着做；demo 只用 `print()` 输出，不需要任何外部服务。

## 布局

```
examples/
├── README.md
├── configs/
│   ├── global_env.yaml          # gpconfig 要求此文件位于文件夹根
│   ├── scheduler.yaml           # GPSchedulerConfig
│   └── jobs/
│       ├── hello.yaml           # args/kwargs
│       ├── cleanup.yaml         # job_globals 注入
│       ├── ping_db.yaml         # worker_init（线程 executor）
│       ├── compute_stats.yaml   # worker_init（进程 executor）
│       └── maintenance.yaml     # enable: false
└── demo_jobs/                   # 被 `packages: [demo_jobs]` 导入的包
    ├── __init__.py
    ├── hello.py
    ├── cleanup.py
    ├── db.py
    ├── compute.py
    └── maintenance.py
```

每个 job 演示一个特性：

| job / 文件 | 特性 | 说明 |
| --- | --- | --- |
| `hello` | 位置 + 关键字参数，`max_runs` | `greet("gpscheduler", greeting="Hi")`，限定执行 10 次 |
| `cleanup` | `job_globals` → `gp_globals` 注入 | 从注入的 globals 读 `work_dir` |
| `ping_db` | `worker_init` + `gp_context`，**线程** | 一个 DB handler 跨多次运行复用 |
| `compute_stats` | `worker_init` + `gp_context`，**进程** | 重对象在 worker 内部构建，从不 pickle |
| `maintenance` | `enable: false` | 被校验但不注册 |

## 前置条件

激活项目 venv 并以可编辑模式安装包（仅首次）：

```bash
source .venv/Scripts/activate    # Windows 下的 Git Bash
pip install -e ".[dev]"
```

这会让 `gpscheduler` 控制台命令可用。

## 运行

你必须从 `examples/` 目录运行，以便 `demo_jobs` 包可被导入。CLI 不会把当前目录加到
`sys.path`，所以也要设 `PYTHONPATH=.`。

**Git Bash（Windows）/ Linux / macOS：**

```bash
cd examples
PYTHONPATH=. gpscheduler list-jobs --config configs
PYTHONPATH=. gpscheduler run --config configs
```

**PowerShell（Windows）：**

```powershell
cd examples
$env:PYTHONPATH = "."
gpscheduler list-jobs --config configs
gpscheduler run --config configs
```

`list-jobs` 是一次**预演（dry run）** —— 它校验配置并打印启用 job，不启动任何东西。`run` 启动
调度器并阻塞，直到你按 `Ctrl+C`。

预期 `list-jobs` 输出（四个启用 job）：

```
4 enabled job(s):
  - cleanup: next run 2026-07-14 03:30:00+08:00 (max_runs: unlimited)
  - compute_stats: next run 2026-07-14 00:06:10+08:00 (max_runs: unlimited)
  - hello: next run 2026-07-14 00:06:02+08:00 (max_runs: 10)
  - ping_db: next run 2026-07-14 00:06:05+08:00 (max_runs: unlimited)
1 disabled job(s) validated but not registered: maintenance
```

`maintenance` 是 `enable: false`，所以它被校验但不注册 —— 它出现在末尾的摘要行里，而不是上面的启用列表中。（时间戳为示意；`list-jobs` 根据每个 job 的 trigger 按当前时间计算。）

## 走读

### 1. `hello` —— 参数

```python
# demo_jobs/hello.py
from gpscheduler import scheduled

@scheduled
def greet(name: str, *, greeting: str = "Hello") -> None:
    print(f"[hello] {greeting}, {name}!")
```

```yaml
# configs/jobs/hello.yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.hello.greet"
cron: "*/2 * * * * *"        # 6 段式：每 2 秒
args: ["gpscheduler"]        # 位置 -> name
kwargs:
  greeting: "Hi"             # 关键字 -> greeting
max_runs: 10                 # 限定执行 10 次后自动移除该 job
```

6 段 cron（`second minute hour day month dow`）每 2 秒触发一次。`args` 映射到位置参数 `name`；
`kwargs` 映射到仅关键字参数 `greeting`。

`max_runs: 10` 把此 job 限定为最多执行 10 次。每次调用都会计数（无论函数正常返回还是抛异常）。
第 10 次运行后，调度器移除该 job 并记录 `job 'hello' reached max_runs=10, removing`。以 2 秒间隔
计算大约需要 20 秒，之后 `hello` 不再出现在输出中，而其它 job 继续运行。省略 `max_runs`（或设为
`null`）则表示无限次执行——这是默认行为，与经典 cron 一致。完整的 `max_runs`
参考见[配置](configuration.md)页面。

### 2. `cleanup` —— 注入 `job_globals`

```python
# demo_jobs/cleanup.py
from typing import Any
from gpscheduler import scheduled

@scheduled
def cleanup(retention_days: int, *, gp_globals: dict[str, Any]) -> None:
    target_dir = gp_globals.get("work_dir", "/tmp")
    print(f"[cleanup] would remove files older than {retention_days} day(s) from {target_dir}")
```

```yaml
# configs/jobs/cleanup.yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.cleanup.cleanup"
cron: "30 3 * * *"           # 5 段式：每天 03:30
args: [7]
kwargs: {}                   # gp_globals 被注入，绝不写在这里
```

函数**声明了** `gp_globals`，所以 gpscheduler 把 `scheduler.yaml` 的 `job_globals` dict 注入给
它。注意 `gp_globals` **不**出现在 `kwargs` 里 —— 写在那里会抛 `ReservedKeyError`。

### 3. `ping_db` —— 通过 `worker_init` 复用对象（线程）

```python
# demo_jobs/db.py
import os
from typing import Any
from gpscheduler import scheduled, worker_init

@worker_init
def init_db_handler(*, gp_globals: dict[str, Any]) -> dict[str, Any]:
    db_url = gp_globals["db_url"]
    print(f"[init_db_handler] opening connection to {db_url} (pid={os.getpid()})")
    return {"db_url": db_url, "pid": os.getpid(), "connect_count": 0}

@scheduled
def ping_db(*, gp_context: dict[str, Any]) -> None:
    gp_context["connect_count"] += 1
    print(f"[ping_db] connected to {gp_context['db_url']} "
          f"(pid={gp_context['pid']}, connect_count={gp_context['connect_count']})")
```

```yaml
# configs/jobs/ping_db.yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.db.ping_db"
worker_init: "demo_jobs.db.init_db_handler"
cron: "*/5 * * * * *"        # 每 5 秒
args: []
kwargs: {}
# 没有 executor 字段 -> 用调度器默认（"thread"）
```

由于这在**线程**池中运行，`init_db_handler` **在主进程里只跑一次**，同一个对象在每次运行中
复用。观察输出：`[init_db_handler]` 只打印一次，而 `[ping_db]` 的 `connect_count` 每 5 秒递增。

### 4. `compute_stats` —— 跨进程边界的 `worker_init`

```python
# demo_jobs/compute.py
import os, random
from typing import Any
from gpscheduler import scheduled, worker_init

@worker_init
def init_stats_client(*, gp_globals: dict[str, Any]) -> dict[str, Any]:
    client_id = f"client-{random.randint(1000, 9999)}"
    print(f"[init_stats_client] built client {client_id} "
          f"(api_key={gp_globals['api_key']}, pid={os.getpid()})")
    return {"client_id": client_id, "pid": os.getpid(), "calls": 0}

@scheduled
def compute_stats(dataset: str, *, iterations: int = 1000,
                  gp_context: dict[str, Any]) -> None:
    gp_context["calls"] += 1
    total = sum(i * i for i in range(iterations))
    print(f"[compute_stats] dataset={dataset!r} sum={total} "
          f"(client_id={gp_context['client_id']}, pid={gp_context['pid']}, "
          f"calls={gp_context['calls']})")
```

```yaml
# configs/jobs/compute_stats.yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.compute.compute_stats"
worker_init: "demo_jobs.compute.init_stats_client"
cron: "*/10 * * * * *"        # 每 10 秒
args: ["metrics"]
kwargs:
  iterations: 5000
executor: process             # 覆盖调度器默认
```

这是最有意思的路径。`executor: process` 把 job 送进一个派生的 worker 进程。worker 重新导入
`demo_jobs`（重新注册装饰器），然后在首次执行时**在 worker 内部**构建 `init_stats_client`。重
对象从不跨进程边界 —— 所以尽管本 demo 里它只是一个 dict，它同样可以是活跃 socket、锁或 ML 模型。

### 5. `maintenance` —— 禁用但仍校验

```yaml
# configs/jobs/maintenance.yaml
cfg_class_name: GPJobConfig
func: "demo_jobs.maintenance.rebuild_index"
cron: "0 2 * * 1"             # 每周一 02:00
args: []
kwargs: {}
enable: false                 # 校验，但不注册
```

`enable: false` 把该 job 从 `run` 和 `list-jobs` 的启用列表中排除，但它的配置仍会在加载时被
完整校验 —— 且 `list-jobs` 会在末尾打印一行摘要点名它，让你知道它被校验过。把 `enable` 翻成
`true`（或删掉这一行）它就会出现在启用列表中。

## 可以尝试的事情

demo 是 gpscheduler Fail-Early 行为的好实验场。下面每一项都会破坏配置，并应在加载时响亮失败
（`list-jobs` 在任何东西运行前以错误退出）：

- **未知函数** —— 把 `hello.yaml` 的 `func` 改成 `demo_jobs.hello.nope` → `NotScheduledError`。
- **保留键** —— 在某个 job 的 `kwargs` 里加 `gp_globals: foo` → `ReservedKeyError`。
- **坏 cron** —— 设 `cron: "99 * * * *"` → `CronExpressionError`。
- **签名不匹配** —— 把 `hello.yaml` 的 `args` 设为 `[]`（缺少必填的 `name`）→
  `JobSignatureError`。
- **Quartz 扩展** —— 设 `cron: "* * * * * 5L"` → `CronExpressionError`。
- **启用被禁用的 job** —— 把 `maintenance.yaml` 的 `enable` 设为 `true` → 它会出现在
  `list-jobs` 里。
- **切换默认 executor** —— 把 `scheduler.yaml` 的 `executor` 设为 `process` → 每个没有 per-job
  覆盖的 job 都移到进程池（注意 Windows 下 worker 派生时更高的启动开销）。
- **更快冒烟测试** —— 临时把 `hello.yaml` 的 cron 改为 `* * * * * *`（每秒）以看到频繁输出。

## gpscheduler 如何找到东西

1. 配置文件夹通过 `--config` 传入（它必须包含 `global_env.yaml`）。
2. `scheduler.yaml` 还原为 `GPSchedulerConfig`。
3. `packages:` 中的每个包都被导入；导入 `demo_jobs` 会运行它的 `__init__.py`，进而导入 job 子
   模块并触发全局 Registry 中的 `@scheduled` / `@worker_init` 注册副作用。
4. `jobs/` 下的每个文件还原为 `GPJobConfig`；文件名 stem 成为 job id。
5. 每个 job 的 `func`（以及若设置的 `worker_init`）都对 Registry 解析 —— 它必须恰好等于被装饰
   函数的 `"{module}.{qualname}"`，否则启动抛 `NotScheduledError` / `NotWorkerInitError`。

更多内容见[配置](configuration.md)与[API 参考](api.md)页面。
