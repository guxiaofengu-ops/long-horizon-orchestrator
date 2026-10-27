# Windows 运行说明

需要 Python 3.10 或更新版本；无需新增 Python 依赖。PowerShell 示例：

```powershell
python "$env:USERPROFILE/.codex/skills/long-horizon-orchestrator/scripts/lho" doctor
python "$env:USERPROFILE/.codex/skills/long-horizon-orchestrator/scripts/lho" validate ./contract.json
python "$env:USERPROFILE/.codex/skills/long-horizon-orchestrator/scripts/lho" start ./contract.json --wait-preflight
```

使用绝对 `workspace` 路径、argv 命令数组和有限预算。JSON 契约、进度及日志按 UTF-8 读取，支持中文和空格路径。`doctor` 会显示 `windows_job_object` 进程树后端。

## 进程生命周期

- `local` 后台 Supervisor 和 Worker 使用隐藏窗口及独立进程组；结束启动命令不会主动取消 Worker。
- 每次尝试创建唯一的 Job Object。命令先在等待门后启动；加入 Job Object 成功后才放行，避免刚启动的子孙进程逃出管理范围。
- `cancel`、阶段超时及总预算终止整棵已登记进程树，并等待 Job Object 清空。Job Object 使用 kill-on-close，Worker 意外退出也会清理其命令及子孙进程。
- 需要终止 Worker 时，同时核验 PID 和创建时间；不使用 `taskkill /IM` 或按名称批量清理。认证、设备预约、SSH 容器清理等仍由任务执行器处理。
- `pause` 等待当前命令完成；需要立即结束当前命令时使用 `cancel`。本地后台进程不等于开机自启服务，机器重启后需要检查持久状态并恢复 Supervisor。

Windows 不使用 POSIX `killpg`、`SIGKILL` 或 `setsid`。`tmux`、SLURM、systemd 仍只在具备相应原生命令的主机运行。

## 会话唤醒

Windows 可执行 `codex.cmd` 由正常命令查找解析。部署时先检查 `codex help queue`；只有当前宿主确认的 thread ID 才能配置 `codex_queue`。CLI 支持或入队成功均不等于恢复回合已经执行，报告应区分这几种状态。无法确认投递时保留 `dispatch_unknown`，不要重发碰运气。

## 验证

```powershell
python -m unittest discover -s tests -v
python -m py_compile scripts/lho_core.py scripts/lho_worker.py scripts/lho_process.py
```

测试覆盖三层进程树取消和超时、无关进程存活、Worker 丢失后清理、PID 身份不匹配拒绝终止、Job Object 分配失败不执行命令、中文路径和正常断线恢复。测试不调用模型，也不使用 GPU/NPU。
