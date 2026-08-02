# argus-report-materialize

将不可变 PolicyDecision、MetaDecision 和 AgentResult 原子物化为 `report.json` 与 `report.md`。

## 输出

机器 JSON schema v2 + 双受众 Markdown 报告，均包含 snapshot/AgentVersion/rule/coverage。

## 禁止

不得创建新 finding、改写事实、重新扫描源码、只写 Markdown 后伪装成功、包含原始 secret 或绝对源码路径。
