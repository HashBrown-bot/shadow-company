# Evaluators

`refund.py` 五条注册业务规则只接收 Policy、来源观测和完成/时间上下文，不读取 PUT 行为开关或场景答案。四态、七类归因、原始冲突和独立资金/审批证据保持。

`runtime.py` 核验故障命中、双 barrier 与 Worker 恢复；`reporting.py` 重算完整性、保存评估与 JSON/HTML。E6 `comparison.py` 区分 PUT 变化和规则、环境、契约、代码/依赖、fixture、调度变化，确认新调用与独立证据后才允许修复结论。

refund_core_20 仅为场景套件，不代表 E7—E10 或完整 V2 发布。计时口径、重放路径变化与不可比较项见 `docs/architecture.md`。
