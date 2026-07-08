# gpscheduler

[![PyPI 版本](https://img.shields.io/pypi/v/gpscheduler.svg)](https://pypi.org/project/gpscheduler/)
[![Python](https://img.shields.io/pypi/pyversions/gpscheduler.svg)](https://pypi.org/project/gpscheduler/)
[![许可证：MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![文档](https://img.shields.io/badge/docs-mkdocs-blue.svg)](https://linnetcodes.github.io/gpscheduler/zh/)
[![构建](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://github.com/LinnetCodes/gpscheduler/actions)

**GPScheduler**（通用调度器，General-Purpose Scheduler）是一个 cron 风格的 Python 调度器。
它通过配置文件把任意包中的函数转化为定时任务，可为任务配置启动参数，并提供装饰器来标记可被调度的函数。

> **English**: [README.md](README.md)

---

## 特性

- **配置驱动** —— 在配置文件中声明调度计划与可调用对象，无需在应用代码里硬编码定时器。
- **不绑定特定包** —— 任务可指向任意已安装包中可导入的函数。
- **装饰器支持** —— 可直接在源码中用装饰器标记可调度函数。
- **启动参数** —— 在调度时为任务传入参数。

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

*（待核心 API 实现后补充。）*

## 文档

完整文档发布于 <https://linnetcodes.github.io/gpscheduler/zh/>（English / 简体中文）。

## 许可证

[MIT](LICENSE) © LinnetCodes
