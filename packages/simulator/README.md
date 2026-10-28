# Simulator

`e3.py` 保留预检、原 S01/S02 与 reset；`e4.py` 保留 S01—S10。`e5.py` 执行事件、故障、双 barrier、checkpoint、取消与预算；`jobs.py` 提供 PostgreSQL 租约、fencing、会话锁和 journal。

E6 `replay.py` 冻结输入资产与 Manifest，按语义及当前前置状态匹配，生成完成封存，提供纯只读 history。input/controlled 均实际调用新命名空间的目标版本；不复用旧产品输出。controlled 只承诺本机控制边界；runtime.time_mode 仍仅 realtime/event_compressed。

输入不含传给业务 Evaluator 的预期答案。远端资金未知时先核验，无法确认则停止，不能无条件重发。细节见 `docs/architecture.md`。
