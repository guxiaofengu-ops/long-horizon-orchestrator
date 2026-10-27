# 真实 CLI 验收阶梯

可选的 `scripts/acceptance.py` 测试工具通过真实 Codex CLI 回合检验**已安装的** Skill，不会用模拟时钟替代真实经过时间。

默认阶梯为 10 秒 → 60 秒 → 300 秒 → 18,010 秒（5 小时 10 秒）。每个阶段先运行合成数值推理，再恢复同一个已验证的 Codex session 进行审查，运行一个五秒训练 fixture，最后再次恢复 Codex 以检查结果并写入验证回执。这些是验收 fixture，不是生产 ML benchmark。

使用显式创建的验收 session ID，并保存其初始 `thread.started` 事件作为证据：

```sh
python3 scripts/acceptance.py ladder --execute \
  --output /absolute/path/to/acceptance-evidence \
  --thread-id VERIFIED_TEST_SESSION_ID
```

该流程会在阶段边界发起真实模型调用。本地监控循环不调用模型；它每 30 秒记录一次进度，并能重启已失效的 run Supervisor。在 macOS 上，有界的 `caffeinate -i -w DRIVER_PID` 可以在不修改电源设置的情况下防止活动测试因空闲进入睡眠。合盖、关机、注销或断电仍会影响本地测试。

证据包括 `ladder.json`、`monitor.jsonl`、各阶段契约与产物、Codex JSONL 流、SQLite attempts 与 wakeup ledger，以及由 Codex 写入的验证回执。只有达到最短时长、两个产物验证器均通过、恢复回合成功且观察到验证回执后，该阶段才会标记为通过。

不要把仍在运行的五小时阶段描述为已通过。分别保留远程安装 ref 与文件哈希、基线失败、修复以及最终经过时间。
