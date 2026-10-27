<div align="center">

[English](README.en.md) | **简体中文**

<img src="docs/assets/mark.svg" width="92" alt="Long Horizon Orchestrator 标识">

# Long Horizon Orchestrator

**让 Codex 负责判断，而不是消耗模型用量等待任务结束。**

一个用于“推理 → 审查 → 训练”长程循环的持久化 Codex Skill，内置 SQLite 状态、独立 Worker、有限启动预检和官方会话唤醒。

[![Tests](https://github.com/guxiaofengu-ops/long-horizon-orchestrator/actions/workflows/test.yml/badge.svg)](https://github.com/guxiaofengu-ops/long-horizon-orchestrator/actions/workflows/test.yml)
[![Codex Skill](https://img.shields.io/badge/Codex%20Skill-valid-16a34a)](SKILL.md)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776ab)](https://www.python.org/)
[![MIT](https://img.shields.io/badge/License-MIT-f59e0b.svg)](LICENSE)

[中文展示页](https://guxiaofengu-ops.github.io/long-horizon-orchestrator/zh/) · [快速开始](#快速开始) · [任务契约](references/task-contract.md) · [运维说明](references/operations.md)

</div>

## 为什么需要它

长时间推理和训练不应该让一个 Agent 回合及其模型上下文持续数小时。Long Horizon Orchestrator 把“判断”和“等待”分开：

```text
Codex 修改 pipeline
        │
        ▼
有限启动预检 ── 正常 ──▶ Codex 回合真正结束
        │                         │
        ▼                         ▼
独立 Worker ◀── SQLite 状态 ── Watchdog
        │
        ├── 验证后的检查点 ──▶ 官方 Codex 唤醒 ──▶ 分析
        ├── 严重失败 ───────▶ 官方 Codex 唤醒 ──▶ 诊断
        └── 最终成功 ───────▶ 官方 Codex 唤醒 ──▶ 报告
```

后台机械等待期间，Runner 的模型调用次数为 **0**。

## 核心能力

- 基于 SQLite WAL 的持久状态机和租约式防重复机制
- Runner 断线后仍可继续运行的独立阶段 Worker
- 支持 AI 显式审查检查点的推理/训练循环
- local、tmux、SLURM 和 systemd 四种调度后端
- 产物新鲜度、JSON 字段、文件大小和退出码验证
- 墙钟时间、阶段次数、失败次数和日志大小预算
- 幂等事件摄取与保守的至多一次唤醒
- 官方 `codex queue` 集成，以及 `codex exec resume` 回退路径
- 明确的终端边界：不模拟键盘，不抓取 PTY

## 快速开始

### 安装为 Codex Skill

```bash
git clone https://github.com/guxiaofengu-ops/long-horizon-orchestrator.git \
  ~/.codex/skills/long-horizon-orchestrator
```

重新开始一个 Codex 对话并输入：

```text
使用 $long-horizon-orchestrator 运行这个推理/训练 pipeline，
并在两个阶段之间设置审查检查点。
```

### 直接运行 CLI

```bash
scripts/lho doctor
cp examples/demo_contract.json ./my-run.json
# 编辑 workspace、命令、验证器、预算和唤醒配置。
scripts/lho validate ./my-run.json
scripts/lho start ./my-run.json --wait-preflight
```

常用运维命令：

```bash
scripts/lho status RUN_ID
scripts/lho logs RUN_ID --follow
scripts/lho attach RUN_ID
scripts/lho pause RUN_ID
scripts/lho resume RUN_ID
scripts/lho resume RUN_ID --approve-checkpoint
scripts/lho cancel RUN_ID
scripts/lho report RUN_ID --json
```

## 检查点，而不是模型轮询

在需要 AI 判断的阶段添加 `"checkpoint": true`。外部命令成功退出并通过全部产物验证后，Runner 会持久化 `WAITING_FOR_CODEX`，仅发送一次唤醒，然后停止推进。恢复后的 Agent 必须先查看报告，再显式批准下一阶段。

```json
{
  "name": "inference",
  "command": ["python", "infer.py"],
  "progress_jsonl": ".lho/inference.jsonl",
  "checkpoint": true,
  "success": [
    {"type": "json", "path": "outputs/metrics.json", "required_keys": ["accuracy"]}
  ]
}
```

## 唤醒模式

| 模式 | 适用场景 | 行为 |
|---|---|---|
| `codex_queue` | 受管理的 Codex App/App Server thread | 向经过验证的原 thread 排入可见消息 |
| `codex_exec` | 持久化 CLI session | 在新的非交互进程中恢复上下文 |
| `command` | 已批准的集成或测试 | 执行显式 argv 模板 |
| `none` | 手动运维 | 记录需要人工恢复 |

官方并未保证一个已经打开的普通 TUI 会因另一个进程恢复会话而实时重绘。本项目不会把键盘模拟包装成官方能力，详见[已验证的支持边界](references/codex-support.md)。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/lho_core.py scripts/lho_worker.py scripts/lho_process.py
```

验收覆盖两步预检、推理 → 训练循环、判断检查点、失败处理、暂停恢复、重复 Supervisor/事件和 Runner 断线恢复。详见 [TEST_RESULTS.md](TEST_RESULTS.md)。

## 安全模型

命令以启动者权限运行。优先使用 argv 数组，将验证路径限制在 workspace 内，设置有限预算，并且不要把凭据放入契约或进度日志。生产使用前请阅读 [SECURITY.md](SECURITY.md)。

## 项目状态

核心 Runner 支持 macOS/Linux 的 POSIX 进程组和 Windows 的原生 Job Object；Windows 使用 `python scripts/lho ...`。平台验证记录见 [TEST_RESULTS.md](TEST_RESULTS.md)，操作细节见 [Windows 运行说明](references/windows.md)。SLURM 和 systemd 适配器需要部署主机安装相应原生命令。真实会话投递依赖 Codex 宿主和经过验证的 thread ID。

## 参与贡献

欢迎提交聚焦的问题和 Pull Request。请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

MIT © 2026 Gu Xiaofeng。详见 [LICENSE](LICENSE)。
