# 参与贡献

感谢你帮助改进 Long Horizon Orchestrator。

## 提交变更前

1. 行为变更或新增集成应先创建 issue。
2. 等待路径不得调用模型，并应保留现有授权边界。
3. 不要添加隐式 shell 执行、无界重试或终端输入模拟。
4. 状态机变更必须添加可观察的测试。

## 本地检查

```bash
python3 -m py_compile scripts/lho_core.py scripts/lho_worker.py
python3 -m unittest discover -s tests -v
```

Pull Request 应说明所处理的失败模式、受影响的状态转换，以及用于判定成功的证据。绝不要包含凭据、生产运行数据库或客户产物。
