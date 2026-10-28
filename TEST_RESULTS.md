# 验收结果 — 2026-10-26

环境：macOS arm64、Python 3.13.3、SQLite 3.49.2、Codex CLI 0.154.0、Codex Desktop 26.1013.31256。

## 已通过

- Skill 结构验证器：`Skill is valid!`
- Python 语法编译：通过
- 六个基于子进程的端到端 Runner 测试：通过
  - 两步预检、推理→训练、两轮迭代和一次最终唤醒
  - 失败命令不会被报告为成功
  - 重复 Supervisor 和重复进度摄取保持幂等
  - 在已调度阶段之间暂停和恢复
  - 显式推理检查点、必需的审查确认，然后进入训练
  - Runner 进程丢失时 Worker 继续运行，随后从持久状态恢复
- 两个文档测试：通过
  - 英文和简体中文路由公开互相对应的 `hreflang` 元数据
  - README 语言切换和所有本地页面资源均可解析
- 本地生成的 Codex App Server schema 包含 `thread/resume` 和 `turn/start`。

唤醒生命周期使用确定性的 `command` 适配器完成检验。打包时有意没有向用户当前对话发送真实 `codex queue`，因此真实 thread 投递受已验证的 CLI 接口支持，但这里不声称已经实际检验。

## 环境发现

`codex doctor --json` 确认认证、配置、安装、状态数据库和 Desktop 安装均可读取。由于非交互测试 shell 使用 `TERM=dumb`，总体结果为失败；它还报告了可选的 CDN/WebSocket 警告和 thread 清单差异。HTTPS 推理端点可达。本项目没有更改这些环境状况。

已安装的 CLI 版本为 0.154.0，而本地更新缓存报告 0.164.0。由于升级用户的全局工具链不属于本 Skill 的实现范围，因此未执行更新。

## Windows 适配验证 — 2026-10-28

环境：Windows x64、Python 3.12.7、Codex CLI 0.163.0。原始 macOS 记录保持不变。

- 完整单元及子进程验收：25 项通过，32.8 秒；不调用模型，不使用 GPU/NPU。
- 新增原生 Job Object：三层进程树取消和阶段超时、Worker 丢失后清理、无关进程存活、PID 创建身份不匹配时拒绝终止、分配失败不放行命令。
- 后台 Runner 丢失后的恢复、有限墙钟预算、暂停恢复、重复 Supervisor 幂等和中文/空格路径通过。
- Python 语法及 Skill 结构验证通过；CI 已增加 Windows、Linux、macOS 的 Python 3.10/3.13 矩阵。CI 的真实结果以本次 PR checks 为准。
- 本机 `codex help queue` 具有 `--thread`/`--message` 参数；上述测试使用确定性的 command 唤醒适配器，未将真实会话投递冒充模型回合完成。

CI 首轮额外发现 macOS 直接子进程已退出但尚未回收时的空进程组 EPERM，以及 Python 3.10 Windows 临时目录清理遇到短暂文件锁的问题；已增加直接子进程回收检测和有界测试清理重试。保留失败日志用于后续跨平台诊断，不屏蔽活进程的权限失败。

并发取消补充终态 CAS，避免旧 Supervisor 在同一终态已完成通知后把 wake_status 重置为 pending；新增有确定性覆盖的终态重复裁定测试。

## Linux 唤醒与恢复修复 — 2026-10-28

以 `2989a0c` 为基线，在隔离的 Linux/Python 3.10 容器中执行新增的首批 9 项故障回归：5 项断言失败、3 项异常、1 项通过。证实以下恢复缺陷存在；这些复现不依赖 DGM4 数据集或模型调用：

- 已持久化 `WAITING_FOR_CODEX`、但尚未发送的检查点，在重启 Supervisor 后被直接跳过。
- 中断的 `dispatching` 记录不会转为可诊断的 `dispatch_unknown`。
- Supervisor 丢失、租约过期的 `RUNNING` 任务，执行 `resume` 只打印成功而不重新启动 Supervisor。
- 并发报告共用 `report.tmp`，会因另一写入方已移动文件而抛出 `FileNotFoundError`。唤醒前报告失败又位于异常处理范围之外，导致状态遗留为 `dispatching`。
- 唤醒后的报告写入失败会撤销已确认的投递状态；旧检查点失败会覆盖更新的终态投递；等待检查点时的取消请求会被忽略。

修复后，在 Linux/Python 3.10 容器与 macOS/Python 3.13 各运行完整 35 项测试：32 项通过、3 项 Windows 专用测试按平台跳过。新增 10 项回归全部通过，另覆盖旧版 Linux attempt 缺少 `cancel_path` 时仍可取消。Python 编译、Skill 结构验证和差异格式检查通过。

恢复使用原有 SQLite 状态和 attempt，不重跑已完成阶段、不重置预算。未知投递不自动重试；显式重试保留诊断事件。生产使用仍需独立服务或 Watchdog 恢复失效的 Supervisor，详见 [Linux 唤醒排查](references/linux-recovery.md)。

本次未读取用户服务器上 `4186c5b1-a171-440d-afd5-28a5c0008604` 的实时证据：本机已配置的 SSH 入口 A/B 均返回 `Permission denied (publickey,password)`。因此这里不将已复现的通用缺陷宣称为该运行已证实的根因，也不声称完成了该服务器上的更新、真实 Codex 唤醒或 DGM4 benchmark 验证。

远程 CI 首轮的 Linux/macOS 四组和 Windows/Python 3.13 通过；Windows/Python 3.10 在并发替换报告时发现短暂的 `WinError 5`。补充仅针对 Windows 错误码 5/32、最长两秒的报告替换重试，以及确定性的短暂文件锁回归；不会重试缺失源文件或无限等待权限恢复。最终测试数量为 36 项，跨平台结果以对应提交的 CI checks 为准。
