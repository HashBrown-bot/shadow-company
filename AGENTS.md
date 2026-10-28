# 项目规则

## 需求与阶段
- 需求权威：`enterprise_simulation_platform_project_spec_v2.docx` 与 `enterprise_simulation_platform_v2_vibe_coding_prompts.md` 的 E1；用户明确修订优先。
- 当前只执行 E10。后续工作先读 `docs/implementation-status.md`、需求映射和当前 diff；阶段验收通过后汇报，不自动进入下一阶段。
- 保留原始需求文件，不覆盖用户修改。实施差异记录在 `docs/decisions.md`。

## 架构约束
- TypeScript / Next.js Web、Python / FastAPI 模块化 API、独立 Worker、PostgreSQL 作业与持久化；模块边界遵循 E1。
- 预期规则、PUT 观测、独立 provider 证据分离；原始观测追加保存，允许非法业务值。
- 金额用整数最小单位和明确币种；run 生命周期与四态 verdict 分离。
- 契约和 Manifest 版本化并计算内容哈希；不得覆盖旧运行依赖的契约。
- YAML 严格字段与类型校验；规则仅允许注册 ID 和参数，禁止 eval 或可执行配置。
- 所有运行记录带 project_id 与 run_id；默认 loopback；不读取或打印真实凭据，不连接生产。
- 缺证据、未实现、取消、预算耗尽均不能报告通过；Evaluator 不读取 PUT 缺陷开关。
- 不引入模型依赖、虚假指标、前端 mock 成功、空测试或跳过失败测试。

## 交付要求
- 每阶段先说明方案，实际启动并验证服务；使用真实 PostgreSQL 验证迁移，不能以 SQLite 替代。
- 锁定依赖；维护 README、架构、需求覆盖表、决策与进度。
- 测试命令、实际结果、失败及修复、未执行检查、限制与下一阶段写入进度及验收记录。
- E2 不宣称完成 E3—E10、S01—S20、真实客户验证或生产部署。
