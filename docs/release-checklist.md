> 公开版说明：以下为历史工程记录摘要。原始日志、截图、CI制品与私有环境材料不随源码发布；相关链接指向[证据范围说明](publication-privacy.md#验收证据)。历史结果不代表公开副本已经重新验收。

# V2 首版工程审查与验收清单（E10）

日期：2026-10-11（America/Los_Angeles）。依据原始 [V2 需求](../enterprise_simulation_platform_project_spec_v2.docx)、[E1 / E10 提示词](../enterprise_simulation_platform_v2_vibe_coding_prompts.md) 和用户本次授权。范围仅为本机 V2 首版工程审查、必要修复及验收；不含公网部署、外部发布、生产访问或真实客户试点。

**工程结论：达到 V2 首版本机工程验收。** REQ01—REQ12、S01—S20 与 A—J 在本文声明范围内均有本轮证据，未遗留阻断项。346项后端测试、真实服务/数据库/浏览器、独立安装及补验通过。失败和未执行检查单列。本结论不表示生产就绪、真实模型增量已证明或客户与市场验证完成。后续任一关键 gate 未通过，结论应改为“未达到 V2 首版验收”。

## 证据口径与当前执行记录

“已实现”指已读取源码与测试；“定点通过”只证明该次命令中的断言；“前序已执行”只证明旧版本在旧环境的实际结果；三者都不能单独证明本轮最终通过。场景 pass 包含正确拒绝非法操作，不等于每笔请求均支付成功。测试数量、场景数量、Finding 数和独立缺陷数分别记录。

| 记录 | 已核对事实 | 本轮用途与限制 |
| --- | --- | --- |
| [E9 完整验收](acceptance-e9.md)、[干净环境](publication-privacy.md#验收证据)、[完整结果](publication-privacy.md#验收证据)、[CI 补强](publication-privacy.md#验收证据) | 前序有独立安装、真实服务、PostgreSQL、后端、浏览器、重启、锁与扫描产物；本轮需另核对源码差异 | 历史证据；不替代本轮修复后的重新运行 |
| [前序源码对应核验](publication-privacy.md#验收证据) | 对照前序验收副本与当前基线的内容证据 | 仅证明记录中的对应关系，不能证明新改动通过 |
| [本轮前置综合 pytest](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据)、[流水线](publication-privacy.md#验收证据) | 当前日志结尾为 263 passed、14 failed、13 errors、1 warning；不能算前置通过 | 已确认运行中源码变更触发 worker_version_drift；修复后的冻结副本完整复跑另记；不得删除失败记录或跳过失败测试 |
| [首次沙箱限制](publication-privacy.md#验收证据) | 首次无法完成服务验收 | 未执行，不计通过 |
| [资金修复前](publication-privacy.md#验收证据) / [修复后](publication-privacy.md#验收证据) | 新反证修复前 17 failed / 1 passed；修复后新 18 项加原规则 50 项，共 68 passed | 纯函数及规则测试；没有在这条命令中启动服务 |
| [预算 gate 修复前](publication-privacy.md#验收证据) / [修复后](publication-privacy.md#验收证据) | 修复后日志记录 6 passed | 预算归类定点证据，实际 API / CLI / 运行层重放随后已全量验证 |
| [访问与脱敏反证](publication-privacy.md#验收证据)、[部分单元复验](publication-privacy.md#验收证据)、[环境失败](publication-privacy.md#验收证据)、[沙箱失败](publication-privacy.md#验收证据) | 单元日志记录 21 passed；另一次包含 沙箱禁止 PostgreSQL 连接导致的 1 failed / 36 errors / 39 passed，不能算整体通过 | 后续新增断言及真实服务检查已由最终346项覆盖；环境错误保留，不作为产品失败或成功 |
| [一致性修复前](publication-privacy.md#验收证据) / [修复后](publication-privacy.md#验收证据) | 新增 API/CLI 同快照比较及规则版本一致性 6 项；修复前 5 failed / 1 passed；与其他 E10 反证组合复验 52 passed | 证明定点断言，未替代 Web 实际展示、运行层和最终综合检查 |
| [本轮核心流水线](publication-privacy.md#验收证据) | 新隔离安装退出0；全链14项通过；346 passed、0 failed/errors/skipped、1 warning，220.07秒；验证落盘2026-10-11 03:15:05 PDT | 新源码/venv/node_modules/真实PG，不是沿用E9结果 |
| [前端补验](publication-privacy.md#验收证据)、[后续四项](publication-privacy.md#验收证据) | 页脚与截图调整后8项既有服务测试、27+5+2浏览器、构建/类型/静态/格式通过；随后因PATH缺uv退出2，再以绝对路径补完双锁/许可/扫描 | 8项为重复，不加到346；不能把中止写成整条流水线退出0；后端源码未再变更 |

本轮[内容哈希清单](publication-privacy.md#验收证据)核对原始需求、旧迁移、双锁及前序证据未覆盖；规则必要修复必须另记版本及内容哈希变化。当前仓库基线并非可用提交差异，不能用空 `git diff` 推断无改动。详见 [决策](decisions.md) 与 [进度](implementation-status.md)。

## 按严重度排列的问题与处置

P1 表示阻断相关工程 gate；P2 表示必须修复的接口一致性或核验缺口。以下10项已由最终核心套件确认修复；修前失败记录保留。[测试保留核对](publication-privacy.md#验收证据)确认原290项全部保留，新增56项，未删除或跳过失败用例。

| 编号 / 严重度 | 位置与触发步骤 | 实际影响 | 修复方案及当前处置 | 验证方法与实际证据 |
| --- | --- | --- | --- | --- |
| E10-01 / P1 | [refund.py:547](../packages/evaluators/refund.py#L547)，审批绑定与产品快照校验；以有效的大额批准 trace 为基线，将 PUT 或 provider 审批的 `version` 改成 `1.0` / `true`，或 `amount_minor` 改成 `200001.0`，保留原始值并重新计算观测摘要 | Python 数值等价比较把非法金额/版本当作有效审批；修复前总 verdict 仍 pass，违反 C | 已修：审批金额与版本须为严格整数且有效；实际审批与执行快照使用类型敏感摘要匹配；非法产品快照产生 fail。规则 `Policy.version=2`，构建标识 `refund-v2`，原契约版本不变；二者一致性已有反证测试，最终346项综合通过 | [test_e10_funds.py](../tests/test_e10_funds.py) `test_approval_numeric_equality_cannot_accept_invalid_types`；[修复前](publication-privacy.md#验收证据)、[68 项通过](publication-privacy.md#验收证据)；原阈值、部分退款、币种与审批绑定测试一同回归 |
| E10-02 / P1 | [refund.py:143](../packages/evaluators/refund.py#L143)，独立支付初始余额解析；从 provider `payments[0]` 删除 `currency` 或设为 `{}` / `[]`，其余证据保持有效 | `KeyError` / `TypeError` 使评估崩溃；其他非法初始币种被错误归因产品缺陷，违反 C / F | 已修：初始余额须为非负整数，币种须为明确支持值；缺失或畸形依赖证据记录 adapter_error 并输出 inconclusive，不修正原始载荷 | `test_invalid_independent_payment_currency_is_inconclusive`、`test_missing_independent_payment_currency_is_inconclusive`；[修复前后](publication-privacy.md#验收证据)，完整 API 报告路径已随346项通过 |
| E10-03 / P1 | [gates.py:9](../packages/evaluators/gates.py#L9) 的未完成原因集合；令 run `status=failed`、`stop_reason=concurrency_budget_exhausted`，分别带/不带已有缺陷检查，读取 selected / suite gate | 并发预算未完成被当成基础设施错误 exit 2，未遵循证据不足/预算退出 3；CLI/API/CI 归类不一致风险，违反 F / H | 已修：并发预算原因归入未完成，优先于已有产品反例；保留业务事实，不改为通过；gate schema 升为 `e10-gate-2` | [test_e10_replay.py](../tests/test_e10_replay.py) `test_unfinished_budget_is_exit_three_even_with_observed_counterexample`；[6 项通过](publication-privacy.md#验收证据)；实际预算服务流程与四种子进程退出码已通过 |
| E10-04 / P1 | [access.py:143](../packages/transport/access.py#L143) 的 GET 证据权限路由；仅有 read 权限的项目令牌访问 `/api/runs/{run}/checks?project_id=...`，对照 report/findings 等接口 | checks 投影包含证据引用及业务判断，可绕过 evidence 权限；违反 G | 已修：checks 与其他证据投影使用 evidence 权限；实现见 access.py:143 | [test_e10_access.py](../tests/test_e10_access.py) `test_read_only_grant_cannot_read_any_evidence_projection` 覆盖八个接口；真实 HTTP / CLI / Web 权限回归通过 |
| E10-05 / P1 | [security.py:170](../packages/transport/security.py#L170)、[credit.py](../adapters/http/credit.py)；第二 Adapter 同时保存规范 `recipient` 与原始 JSON-RPC `wire.request.params.payee` | 规范视图被脱敏而 wire 仍可能泄露收款对象；导出/证据边界不一致，违反 G | 已修：`payee` 与 `recipient` 同样转换为可关联摘要；保留 `units=-50` 等非法业务值，不能借脱敏修正缺陷 | `test_rpc_wire_payee_is_redacted_without_changing_illegal_business_values`、`test_rpc_redaction_keeps_canonical_approval_and_business_semantics`；最终第二 Adapter、导出及关键截图核对通过 |
| E10-06 / P1 | [security.py:190](../packages/transport/security.py#L190)、[actors.py:37](../packages/simulator/actors.py#L37)；在普通 message 或响应对象键中回显本机 `sim_...` 令牌，不使用 token/authorization 字段名 | 裸令牌可能进入共享日志、报告或模型输入；仅按字段名脱敏不充分，违反 G | 已修：共享文本/对象键递归脱敏、模型输入沿用文本脱敏；仅使用合成 canary，不读取或输出真实凭据 | `test_bare_local_access_token_is_removed_from_shared_text`、`test_echoed_request_credential_is_also_removed_from_response_object_keys`；真实导出精确扫描与关键截图目检通过（范围见下表） |
| E10-08 / P1 | [replay.py:514](../packages/simulator/replay.py#L514)、[gates.py:9](../packages/evaluators/gates.py#L9)、[reporting.py](../packages/evaluators/reporting.py)：fixture 偏离的运行层到报告/CI 归因路径；计划与实际 provider/actor fixture 不一致或删除必需资产，再读取报告和 simctl gate。 | 应是 fixture_mismatch / inconclusive / exit 3，不能由运行层统一错误路径变成错误产品归因、exit 2 或假通过；违反 E / F | 已修：fixture_mismatch 返回3；JSON、HTML与Web展示独立 execution_issues，保留 environment_error 根因与证据引用、原业务检查不覆盖 | [test_e6_live.py](../tests/test_e6_live.py) 的 missing fixture / wrong prestate / feedback deviation、[test_e6_integrity.py](../tests/test_e6_integrity.py) 的 semantic mismatch / asset removal；新增 8 项定点测试通过；[fixture 修前](publication-privacy.md#验收证据)、[修后](publication-privacy.md#验收证据) |
| E10-09 / P1 | [reporting.py:354](../packages/evaluators/reporting.py#L354)、[comparison.py:148](../packages/evaluators/comparison.py#L148)、[simctl](../packages/simctl/main.py) 与 Web；只选 S12、buggy → fixed input replay 后，读取 console / compare / simctl。S12 业务修复可通过，但严格 gate 缺审批适用覆盖应为 exit 3 | console 的 report 原来不含 ci_gates，UI 的业务 pass 与 CLI 严格证据不足未区分；CLI 比较再单独请求目标报告会拼接不同快照，违反 H / F | 后端已修：report 统一生成 ci_gates，compare 同时返回比较 ci_gates 与 target_ci_gates，simctl 仅读取一次 compare 结果；Web 已使用同源 gate 展示，最终浏览器实测通过。保留业务 verdict，不伪造审批覆盖 | [test_e10_release.py](../tests/test_e10_release.py) `test_cli_compare_uses_api_gate_without_second_result_read`、`test_evaluator_version_matches_manifest_provenance`；[5 failed / 1 passed](publication-privacy.md#验收证据)、[组合 52 passed](publication-privacy.md#验收证据)；实际浏览器与同 run_id 的 API/CLI 对照通过，见 browser/e10-ui-cli-consistency.json |
| E10-10 / P1 | [comparison.py:71](../packages/evaluators/comparison.py#L71)、[reporting.py:281](../packages/evaluators/reporting.py#L281)；保留同一套旧 source/target Manifest，只把目标的实际 Evaluator 构建或政策版本/哈希换为新版本，再请求比较 | 冻结清单彼此相同掩盖了实际重评规则变化，仍可能错误 `repair_verified=true`，把变化全部归因 PUT；违反 E / F | 已修：记录实际进程规则构建；新增 `target_evaluator_since_manifest`、`target_evaluation_since_seal`，变更或缺构建证据进入 confounders，修复未确认、比较 gate 3；不改历史 seal | `test_comparison_detects_current_rules_drift_from_frozen_target` 的相同/构建变更/政策变更/缺构建四例；[修前 3 failed / 7 passed](publication-privacy.md#验收证据)、[修后相关 18 passed](publication-privacy.md#验收证据)；真实 E6 构建一致断言纳入最终套件 |
| E10-07 / P2 | [scan_secrets.py:9](../scripts/scan_secrets.py#L9)；在导出文字中放入合法但以 `-` 结尾的合成本机令牌，运行对应扫描模式 | 原单词边界不能覆盖所有合法 URL-safe token 结尾，扫描可能假阴性；违反 G 的验证关口 | 已修：使用明确的合法字符前后边界；覆盖字母、`-`、`_` 结尾 | `test_export_scanner_detects_every_legal_local_token_ending`；修复后最终导出/源码扫描通过，不以扫描规则存在代替执行 |


## REQ01—REQ12

| 需求 | 实现位置 | 验收断言与测试位置 | 本轮最终证据 | 本轮最终状态 | 限制 |
| --- | --- | --- | --- | --- | --- |
| REQ01 契约和预检 | [config.py](../packages/contracts/config.py)、[schema](../packages/contracts/schema.v0.2.json)、[API](../services/api/main.py)、[接入](../services/api/e3.py) | [test_contracts](../tests/test_contracts.py)：严格 YAML、未知字段/规则、预算、币种、Schema 同步；[test_api](../tests/test_api.py)：缺 ledger 拒绝、不可变版本；[test_e3_live](../tests/test_e3_live.py)：真实 preflight | [pytest](publication-privacy.md#验收证据)、[迁移JUnit](publication-privacy.md#验收证据)、[演示 summary](publication-privacy.md#验收证据) | 通过（声明范围） | 仅已审阅本机 Adapter；不自动接入未知客户规则或生产凭据 |
| REQ02 隔离与重置 | [复合键迁移](../migrations/versions/0002_e3.py)、[scope](../packages/transport/security.py)、[生命周期](../services/api/lifecycle.py)、PUT/provider reset | [test_migrations](../tests/test_migrations.py)：跨项目外键；[test_e3_live](../tests/test_e3_live.py)：同外部 ID 双 run、reset；[test_e9](../tests/test_e9.py)：项目/run 授权、删除失败保留证据 | [pytest](publication-privacy.md#验收证据)、[清理记录](publication-privacy.md#验收证据) | 通过（声明范围） | 共用 OS / 数据库账号；reset/delete 不是跨服务原子事务；手工导出和备份不在在线删除范围 |
| REQ03 三层证据 | [refund-put](../examples/refund-put/main.py)、[provider](../examples/payment-provider/main.py)、[Adapter](../adapters/http/refund.py)、[evidence](../packages/evidence/store.py)、[refund evaluator](../packages/evaluators/refund.py) | `test_s01_s02_real_call_chain_and_independent_ledger`、`test_real_put_false_success_has_no_provider_execution`、删除 ledger 后不能沿用 pass、非法观测追加保存 | [call-chain](publication-privacy.md#验收证据)、[false-success](publication-privacy.md#验收证据)、[fixed report](publication-privacy.md#验收证据) | 通过（声明范围） | 示例 provider 证明独立提交事实，不代表真实银行/支付机构核验 |
| REQ04 四态评估 | [五规则](../packages/evaluators/refund.py)、[报告](../packages/evaluators/reporting.py)、[gate](../packages/evaluators/gates.py) | [test_e4_rules](../tests/test_e4_rules.py)：四态、正常拒绝、缺证据、冲突、期限；[test_e10_funds](../tests/test_e10_funds.py)、[test_e10_replay](../tests/test_e10_replay.py) | [pytest](publication-privacy.md#验收证据)、[buggy](publication-privacy.md#验收证据)、[HTML](publication-privacy.md#验收证据) | 通过（声明范围） | 无综合 readiness 分数；生命周期与 verdict 分离；缺证据不能通过 |
| REQ05 故障注入 | [controls](../packages/transport/controls.py)、[provider](../examples/payment-provider/main.py)、[e5](../packages/simulator/e5.py)、[runtime](../packages/evaluators/runtime.py) | [test_e5_live](../tests/test_e5_live.py)：六类实际故障、缺命中反证、retry=0；S12 必须有先提交后实际超时 | [fixed-s01-s20](publication-privacy.md#验收证据)、[buggy-e5](publication-privacy.md#验收证据)、[retry=0](publication-privacy.md#验收证据) | 通过（声明范围） | S11 是提交前真实 HTTP 断开，并非 DNS/TCP 建连拒绝；仅声明故障边界 |
| REQ06 受控并发 | [e5 调度](../packages/simulator/e5.py)、[EntryBarriers](../packages/transport/controls.py)、[PUT](../examples/refund-put/main.py) | `test_all_twenty_real_scenarios_and_no_false_positives` 断言三组 actual_overlap/event_sync；buggy 余额争抢必须真实读取后重叠 | [runtime.concurrency](publication-privacy.md#验收证据)、[buggy](publication-privacy.md#验收证据) | 通过（声明范围） | 不使用随机 sleep 证明竞争；不承诺任意 staging 的锁胜者确定性 |
| REQ07 输入重放 | [replay](../packages/simulator/replay.py)、[API](../services/api/replay.py)、[comparison](../packages/evaluators/comparison.py)、[build](../packages/transport/build.py) | [test_e6_live](../tests/test_e6_live.py)：新调用/版本/账本、history 零调用、10+10、禁止输出复用、条件变化；[integrity](../tests/test_e6_integrity.py)：必需资产删除后阻断 | [repetitions](publication-privacy.md#验收证据)、[pytest](publication-privacy.md#验收证据)、每次 repeat 的 report/Manifest/compare | 通过（声明范围） | fixed/buggy 为同一独立服务的不同实际代码路径；历史缺完整 Manifest 的运行仅 history；controlled 仅列明边界 |
| REQ08 混合角色 | [actors](../packages/simulator/actors.py)、[actor schema](../packages/contracts/actors.py)、[LLM protocol](../adapters/llm/protocol.py)、[experiments](../services/api/experiments.py) | [test_e7_actors](../tests/test_e7_actors.py)：身份/工具/注入/预算/取消/未知调用；[test_e7_live](../tests/test_e7_live.py)：模型关闭 S01—S20、规则回退与同条件配对 | [model-off](publication-privacy.md#验收证据)、[pytest](publication-privacy.md#验收证据)、[协议输入](publication-privacy.md#验收证据) | 通过（声明范围） | 替身与实际模型分开；普通 API 无自然语言入口；真实模型实验、真人确认时间与 AI 增量未测 |
| REQ09 可用 UI | [Web components](../apps/web/app/components)、[console API](../services/api/console.py)、[BFF](../apps/web/app/api/backend/[...path]/route.ts)、[session](../apps/web/app/api/session/route.ts) | [test_e8_console](../tests/test_e8_console.py)；[e8-browser](../scripts/e8-browser.mjs)：真实创建/预检/buggy/Finding/fixed replay；[access-browser](../scripts/e9-access-browser.mjs) | [最终浏览器](publication-privacy.md#验收证据)、[登录](publication-privacy.md#验收证据)、[截图目录](publication-privacy.md#验收证据)、[重启](publication-privacy.md#验收证据) | 通过（声明范围） | 中文工程控制台；数据来自 API；桌面/390px/键盘不等于正式 WCAG 审计或用户研究 |
| REQ10 CLI 与 gate | [simctl](../packages/simctl/main.py)、[gates](../packages/evaluators/gates.py)、[验收器](../scripts/verify_e9.py)、[CI](../.github/workflows/regression.yml) | `test_cli_real_exit_codes_replay_and_export`、CI 子进程四种退出码；NA/缺证据/取消/预算/fixture 偏离不能出 0；E10-03/08 | [CLI 四码](publication-privacy.md#验收证据)、[suite report](publication-privacy.md#验收证据)、[CLI gate](publication-privacy.md#验收证据) | 通过（声明范围） | 外部 GitHub runner 未触发；开放探索未启用；本机配置与实际 runner 验证分开 |
| REQ11 安全与恢复 | [SafeHTTP](../packages/transport/http.py)、[security](../packages/transport/security.py)、[access](../packages/transport/access.py)、[jobs](../packages/simulator/jobs.py)、[Worker](../services/worker/main.py)、[lifecycle](../services/api/lifecycle.py) | [test_e3_security](../tests/test_e3_security.py)、[test_e5_safety](../tests/test_e5_safety.py)、[test_e9](../tests/test_e9.py)、[test_e10_access](../tests/test_e10_access.py)：scope/DNS/重定向/验签/租约/unknown/急停/retention | [SIGKILL](publication-privacy.md#验收证据)、[取消在途](publication-privacy.md#验收证据)、[扫描](publication-privacy.md#验收证据)、[pytest](publication-privacy.md#验收证据) | 通过（声明范围） | 默认 loopback；单团队信任边界；不支持公网敌对租户；急停不能撤回已执行资金 |
| REQ12 复用与交付 | [第二 PUT](../examples/credit-note-put/main.py)、[第二 Adapter](../adapters/http/credit.py)、[dev.py](../scripts/dev.py)、[迁移](../migrations/versions)、[双锁](../uv.lock)、[Node 锁](../pnpm-lock.yaml) | `test_second_rpc_adapter_real_buggy_fixed_and_isolation`；真实空库/升级/重复迁移/清理；[clean_e9](../scripts/clean_e9.py) 独立安装；构建/静态/锁/许可证 | [第二 fixed](publication-privacy.md#验收证据)、[第二 buggy](publication-privacy.md#验收证据)、[迁移JUnit](publication-privacy.md#验收证据)、[最终结果](publication-privacy.md#验收证据) | 通过（声明范围） | 第二示例仅 S01—S10，超范围拒绝；E10 通用规则修复对两 Adapter 一致，非迎合第二产品；不等于客户验证 |

## S01—S20 场景核对

统一实现入口为 [e4.py](../packages/simulator/e4.py) / [e5.py](../packages/simulator/e5.py)，资金判定为 [refund.py](../packages/evaluators/refund.py)，故障/并发/恢复覆盖由 [runtime.py](../packages/evaluators/runtime.py) 独立核对。S01—S10 的服务级断言在 [test_e4_live.py](../tests/test_e4_live.py)，S11—S20 在 [test_e5_live.py](../tests/test_e5_live.py)；[test_e6_all_twenty_input_scenarios_keep_e5_semantics](../tests/test_e6_live.py) 验证全场景 input replay。已逐条核对本轮对应 object、call、ledger、coverage 与 runtime 引用；fixed 20/20、113 pass＋27 N/A、selected/suite gate均0。N/A未替代任何必需检查。

| 场景 | 必须核对的实际输入及独立证据 | 测试函数 / 反证 | 本轮最终证据 | 本轮最终状态 / 限制 |
| --- | --- | --- | --- | --- |
| S01 | 199999 与等于阈值 200000，不需审批，各一次成功执行 | `test_s01_s10_fixed_real_evidence_no_false_positives`；`test_threshold_below_equal_above` | [fixed-s01-s10](publication-privacy.md#验收证据) | 通过；金额为最小单位，不能省略等于点 |
| S02 | 200001，approver 实际请求；版本、金额、币种、收款方、指令绑定；一次账本执行 | 上述服务测试；`test_each_approval_binding_and_authority`；E10-01 | [fixed-s01-s10](publication-privacy.md#验收证据) | 通过；不以产品 approved 标签自证 |
| S03 | 无审批大额 execute 实际被拒，provider 为零执行 | `test_s01_s10_fixed_real_evidence_no_false_positives` | [fixed-s01-s10](publication-privacy.md#验收证据) | 通过；正确拒绝归 expected_rejection |
| S04 | 审批后 PATCH 改金额并增版本；fixed 旧批准失效；buggy 执行旧快照应 fail | `test_buggy_duplicate_stale_approval_and_over_refund`；审批绑定单元反证 | [fixed](publication-privacy.md#验收证据)、[buggy](publication-privacy.md#验收证据) | 通过；重新审批使用独立指令，不能覆盖旧违规证据 |
| S05 | 故意重复 create / execute 保留不同动作；相同指令最多一个成功 entry_id | 上述 fixed/buggy 服务测试；`test_duplicate_entries_vs_repeated_snapshot_and_failed_attempts` | [fixed](publication-privacy.md#验收证据)、[buggy](publication-privacy.md#验收证据) | 通过；重复观察不算重复资金，平台去重不能吞测试动作 |
| S06 | 同支付两指令 6000＋4000，独立初始余额 10000，累计合法 | fixed 服务测试；`test_partial_refunds_property_and_currency_separation` | [fixed-s01-s10](publication-privacy.md#验收证据) | 通过；允许合法部分退款，不按订单粗略计次 |
| S07 | 两指令 6000＋5000 争用 10000；fixed 拒超额，buggy 超额被 REFUND_002 检出 | `test_buggy_duplicate_stale_approval_and_over_refund` | [fixed](publication-privacy.md#验收证据)、[buggy](publication-privacy.md#验收证据) | 通过；失败尝试不计成功累计 |
| S08 | 独立 CNY / USD 支付分别累计；对 CNY 支付创建 USD 退款实际被拒 | fixed 服务测试；`test_over_balance_mismatch_and_illegal_business_values`；E10-02 | [fixed-s01-s10](publication-privacy.md#验收证据) | 通过；缺失币种不能依赖环境默认值补齐 |
| S09 | support 身份真正向 PUT 发 `/approve`，PUT 403、无有效审批及资金 | fixed 服务测试实际 actor/path/status 断言；E7 模型关闭权限探测 | [fixed-s01-s10](publication-privacy.md#验收证据) | 通过；平台提前拦截不算 PUT 验证 |
| S10 | customer_a 查询自己 200，customer_b 查他人 403/404 且无业务字段 | fixed 服务测试；`test_cross_customer_disclosure_yields_confirmed_finding` | [fixed-s01-s10](publication-privacy.md#验收证据) | 通过；身份映射与 owner 必须有可核验观测 |
| S11 | provider ledger 提交前断开实际 HTTP；首次无提交、PUT 真连接失败，后续有界恢复 | `test_all_twenty_real_scenarios_and_no_false_positives` | [fixed-s01-s20](publication-privacy.md#验收证据) | 通过；不是 DNS/TCP 建连失败 |
| S12 | provider 事务先提交账本和审计，再扣住响应；PUT 真读超时；fixed 查账，buggy 换键重试导致重复 | `test_buggy_timeout_race_and_stale_callback_from_actual_observations`；10＋10 input replay | [fixed](publication-privacy.md#验收证据)、[buggy](publication-privacy.md#验收证据)、[重复](publication-privacy.md#验收证据) | 通过；不能在调用端伪造超时代替真实提交 |
| S13 | 相同签名 event_id 重投到 PUT / 平台，有 duplicate 响应和投递审计，资金不重复 | `test_all_twenty_real_scenarios_and_no_false_positives`；Webhook 防重放相关测试 | [fixed-s01-s20](publication-privacy.md#验收证据) | 通过；业务重复动作与相同回调去重分离 |
| S14 | 提交前持久处理中回调，在成功回调后投递；fixed 不退状态，buggy 被检出 | `test_buggy_timeout_race_and_stale_callback_from_actual_observations`；`test_old_callback_version_alone_cannot_override_conflicting_history` | [fixed](publication-privacy.md#验收证据)、[buggy](publication-privacy.md#验收证据) | 通过；需要实际发生时间/版本，不能仅凭“旧事件”标签豁免 |
| S15 | provider 实际 429 后受预算恢复；max_action_retries=0 时无第二 provider 调用 | `test_retry_budget_zero_prevents_second_provider_call` | [fixed](publication-privacy.md#验收证据)、[retry-budget-zero](publication-privacy.md#验收证据) | 通过；预算不足结论与 gate 同步 |
| S16 | 同一指令 execute 在平台与 PUT barrier 实际重叠；fixed 一条成功账本，buggy 多条 | `test_all_twenty_real_scenarios_and_no_false_positives`；buggy 服务测试 | [fixed](publication-privacy.md#验收证据)、[buggy](publication-privacy.md#验收证据) | 通过；需开始/结束与 barrier 到达/释放序号 |
| S17 | 6000 / 5000 两指令竞争 10000；buggy 读取余额后同步形成真实 check-then-act，fixed 锁内复查 | 上述 fixed/buggy 服务测试 | [fixed](publication-privacy.md#验收证据)、[buggy](publication-privacy.md#验收证据) | 通过；不预设线程胜者，只核账本余额约束 |
| S18 | approver 实际不可用 423，真实等待；未批准的大额 execute 被拒、零资金 | `test_all_twenty_real_scenarios_and_no_false_positives` | [fixed-s01-s20](publication-privacy.md#验收证据) | 通过；审批等待不冒充已进入支付处理中 |
| S19 | PUT cancel / execute 通过 barrier 真实竞争；保留取消或执行实际终态与资金后果 | 全 20 场景测试；`test_cancel_after_provider_commit_keeps_inflight_consequences` | [fixed](publication-privacy.md#验收证据)、[cancel-inflight](publication-privacy.md#验收证据) | 通过；取消不保证撤销已经发生的支付 |
| S20 | before_dispatch 与 after_remote_before_ack 真正终止 Worker 子进程；重启 owner/PID、checkpoint；每指令一笔资金 | `test_actual_process_restarts_checkpoint_and_no_duplicate_money`；`test_sigkill_worker_while_committed_provider_response_is_inflight`；`test_unknown_non_idempotent_dispatch_never_reissued` | [fixed](publication-privacy.md#验收证据)、[SIGKILL](publication-privacy.md#验收证据) | 通过；恢复不是 history/input replay；未知远端结果不自动重发 |

## 核心关口 A—J

| 关口 | 核验内容、实现与必要反证 | 本轮最终证据 | 本轮最终状态 / 保留边界 |
| --- | --- | --- | --- |
| A | PUT/provider 独立进程、origin、schema；[service_credentials](../packages/transport/security.py) 不给 PUT ledger 密钥；[false-success 测试](../tests/test_e4_live.py) 与 ledger 删除反证证明 success 不自证 | [call-chain](publication-privacy.md#验收证据)、[false-success](publication-privacy.md#验收证据)、[pytest](publication-privacy.md#验收证据) | 通过；同 OS/数据库账号，不声称敌对隔离 |
| B | [refund.py](../packages/evaluators/refund.py) 只读来源观测和 policy；PUT 内保留 buggy；`test_evaluator_does_not_read_scenario_inputs_or_target_selectors` / `test_rules_ignore_product_variant_and_test_control_payload` 改控制观测不改判断 | [pytest](publication-privacy.md#验收证据)、[buggy](publication-privacy.md#验收证据) | 通过；版本仅用于重放调用验证，不进入五条业务规则 |
| C | S01—S10 阈值边界、合法部分退款、币种、审批五字段/操作者、真实低权限请求；E10-01/02 新反证 | [fixed-s01-s10](publication-privacy.md#验收证据)、[funds-after](publication-privacy.md#验收证据) | 通过；本轮服务验收与局部68项均通过 |
| D | S12 provider 提交与超时证据；S16/S17/S19 actual_overlap/event_sync；S20 实际进程终止和 SIGKILL；[jobs](../packages/simulator/jobs.py) 租约/未知结果不重发 | [fixed-s01-s20](publication-privacy.md#验收证据)、[SIGKILL](publication-privacy.md#验收证据) | 通过；仅已控制边界 |
| E | input 新 run/资产/目标 fixed 实际 business_call，provider execution_received/ledger/outbox 全新；history 零调用；证据 ID 不重叠；fixture 删除和 output reuse 被拒 | [20 次重复](publication-privacy.md#验收证据)、每次 repeat report/Manifest/compare、[pytest](publication-privacy.md#验收证据) | 通过；合法减少重试可比较，条件变化不能直接认定修复 |
| F | [四态](../packages/evaluators/refund.py)、[runtime](../packages/evaluators/runtime.py)、[gate](../packages/evaluators/gates.py) 对缺证据/取消/预算/fixture 偏离一致；E10-03/08 | [预算](publication-privacy.md#验收证据)、[取消](publication-privacy.md#验收证据)、[CLI 四码](publication-privacy.md#验收证据)、[pytest](publication-privacy.md#验收证据) | 通过；不能把 N/A、未实现或部分执行转成通过 |
| G | 项目/run 复合范围、访问/raw 权限、出站、签名、保留期/删除；[E10 access 反证](../tests/test_e10_access.py)；精确合成秘密扫描＋关键截图人工核对 | [pytest](publication-privacy.md#验收证据)、[最终导出扫描](publication-privacy.md#验收证据)、[browser](publication-privacy.md#验收证据) | 通过；不得读取真实凭据；文本扫描不能替代截图检查 |
| H | CLI/API 共享 ci_gates；compare 同快照返回比较与目标 gate；UI 通过 BFF 调原 API，真实 create/preflight/run/Finding/replay/compare；业务修复与严格 CI gate 分别显示；E10-09 | [CLI gate](publication-privacy.md#验收证据)、[browser](publication-privacy.md#验收证据)、[登录](publication-privacy.md#验收证据)、[重启](publication-privacy.md#验收证据) | 通过；不可前端 mock 成功；同一结果需按 run_id 对照 |
| I | Schema 同步、真实 PostgreSQL 空库与升级/降级、依赖双锁、启动/持久化/清理、S01—S20、10+10、第二 Adapter；[verify_e9](../scripts/verify_e9.py) 与 [clean_e9](../scripts/clean_e9.py) | [pytest](publication-privacy.md#验收证据)、[迁移JUnit](publication-privacy.md#验收证据)、[build](publication-privacy.md#验收证据)、[锁](publication-privacy.md#验收证据)、[Node 锁](publication-privacy.md#验收证据)、[licenses](publication-privacy.md#验收证据)、[verification](publication-privacy.md#验收证据) | 通过；不能用 SQLite；本轮已实际执行新隔离安装 |
| J | [实验指标](../packages/evaluators/experiments.py)、[README](../README.md)、[进度](implementation-status.md) 明确工程/客户/市场边界；未测真人指标为 null，不编造 AI 增量 | 最终文档复核、[model-off 实验](publication-privacy.md#验收证据)、[verification](publication-privacy.md#验收证据) | 通过；客户试点、真实模型服务、市场实验未执行，不能称生产就绪 |

## 可复制的启动、演示与反证命令

在项目根执行，沿用已有锁文件与本机开发凭据引用，不复制或输出真实秘密。首次安装前确保 Python 3.12、Node.js 22—26、项目要求的 pnpm / uv 可用；实际执行版本必须记录到验收日志，不能只引用声明版本。

```sh
uv sync --frozen
pnpm install --frozen-lockfile
if [ ! -e .env ]; then cp .env.example .env; fi
.venv/bin/python scripts/dev.py
```

已有 `.env` 保留。启动器只启动本机服务；数据位于 `.local/postgres`，日志位于 `.local/logs`，Ctrl-C 停止其子进程并保留数据。已有开发服务占端口时应先由用户/原启动器正常停止；不能夺取或杀掉不属于本次验收的服务。访问 `http://127.0.0.1:3000`，按登录页面使用本次生成的本机令牌，不把令牌放入命令行、截图或报告。

保持服务运行，在第二终端执行真实 buggy → fixed input replay → compare。输出目录必须是未存在的新目录；脚本会新建项目，不 reset 用户原项目。

```sh
.venv/bin/python -m scripts.demo_e9 --output-dir .local/artifacts/e10-demo-01
```

脚本逐条检查 buggy 退出 1、fixed input replay 退出 0、compare 退出 0；实际 ID 与结果写入该目录的 `summary.json`、`buggy.json`、`fixed.json`、`compare.json`。预期退出码不是执行证据，本轮实际目录为 [demo](publication-privacy.md#验收证据)，退出码[1,0,0]、repair_verified=true。要逐项观察 buggy 场景及 fixed 全套：

```sh
.venv/bin/simctl run environments/refund_approval/local.e5.yaml --gate suite --output .local/e10-fixed-report.json
.venv/bin/python -m scripts.demo_e5 --version buggy
```

`demo_e5 --version buggy` 预期检出业务缺陷并返回 1，不能将此预期业务失败理解为验收器自身失败；报告中必须保留独立重复执行、过期审批和并发余额证据。第二 Adapter 的真实 S01—S10 命令：

```sh
.venv/bin/simctl run environments/refund_approval/local.e9-credit.yaml --suite-scope e4_core_10 --scenarios S01,S02,S03,S04,S05,S06,S07,S08,S09,S10
```

新增反证与原规则回归不启动共享服务：

```sh
.venv/bin/python -m pytest -q tests/test_e10_funds.py tests/test_e10_access.py tests/test_e10_replay.py tests/test_e10_release.py tests/test_e4_rules.py
```

停止开发启动器后，使用新的证据目录运行最终核心套件。该入口包含真实 PostgreSQL、全后端、浏览器、重启、构建、静态、双锁与扫描；不应同时运行另一套占用 3000/8000/8001/8002/8003/55432 的服务。

```sh
ACCEPTANCE_EVIDENCE_DIR=docs/evidence/e10-rerun .venv/bin/python -m scripts.verify_e9
```

若目录已有结果，改用新的后缀并同步本文链接，保留失败日志。`verify_e9` 仅是复用现有工程验收器的名称，不将本次阶段退回 E9。纯后端命令需真实 PostgreSQL 可用；数据库不可用是未执行/基础设施错误，不得换 SQLite 或 skip。

本轮已在新隔离源码、venv、node_modules 和数据库完成最终验收，以下命令退出0：

```sh
.venv/bin/python -m scripts.clean_e9 --online --evidence docs/evidence/e10-final
```

它不复制用户 `.env` 或数据库；只允许按锁文件补取公开依赖及供应链元数据，不调用生产或模型服务。结果保存在 `e10-final/clean-environment.json`，演示在 `e10-final/demo/`，完整核心套件在 `e10-final/verification/`。依赖安装失败即终止，不能算验收通过；安装日志与原环境未变证据须保留。重跑需使用新的证据目录。

## 最终执行结果与停止边界

以下为本轮实际结果，核心与补验分别记录，不重复计数。[机器可读核对](publication-privacy.md#验收证据)。

| 检查 | 本轮实际结果 | 证据 |
| --- | --- | --- |
| 文件保护 | 原始V2文档/提示词、旧迁移、双锁、前序证据未覆盖；冻结154文件中仅页脚与截图脚本随后变化并补验；最终副本153份同哈希，1份Next生成类型引用仅dev/build路径不同 | [变更清单](publication-privacy.md#验收证据)、[冻结154](publication-privacy.md#验收证据) |
| 后端 | 346 passed、0 failed/errors/skipped、1既有Starlette warning；220.07秒 | [pytest](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据) |
| PostgreSQL / schema | 18.4；空库至0007_e9、重复升级、降至base再升、旧数据升级、复合FK/追加证据、Schema同步通过 | [PG](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据)、[迁移断言](../tests/test_migrations.py#L38)；migration.txt为空stdout，不作唯一证据 |
| 持久化 / 隔离 / 恢复 / 清理 | 相同外部ID跨项目/run不串；PG及全部服务重启history不变；S20和SIGKILL不重复资金；raw清理33、trace reset1、删除4runs、保留6审计；临时验收库删、自有进程停、6端口释放 | [restart](publication-privacy.md#验收证据)、[cleanup](publication-privacy.md#验收证据)、[lifecycle](publication-privacy.md#验收证据)、[最后实际绑定](publication-privacy.md#验收证据) |
| S01—S20 | 20/20、113pass＋27NA、selected/suite均0；6/6实际故障、3/3并发重叠、恢复verified | [全套](publication-privacy.md#验收证据)、[CLI全套](publication-privacy.md#验收证据) |
| 10＋10 input replay | 10buggy fail、10fixed pass；20新run、410新observation、30新ledger及30新webhook ID跨轮无交集；原history哈希不变 | [repetitions](publication-privacy.md#验收证据)及同目录20组repeat明细 |
| 第二 Adapter | 真实JSON-RPC S01—S10；buggy gate1、fixed gate0；各62wire/17issue，payee均哈希；非法审批仍检出 | [buggy](publication-privacy.md#验收证据)、[fixed](publication-privacy.md#验收证据) |
| CLI / API / UI | 真子进程0/1/2/3保留；同S12源gate1、目标业务pass但strict3、比较API/UI/CLI均3；完整20场景strict0 | [四码](publication-privacy.md#验收证据)、[同run对照](publication-privacy.md#验收证据) |
| 浏览器 | 核心27主流程＋5登录＋2重启通过、30PNG；页脚修正后同27＋5＋2复验及8既有服务测试通过（53.09秒）；新建390×844浏览器另2真实页面/4截图核对通过 | [核心](publication-privacy.md#验收证据)、[补验](publication-privacy.md#验收证据)、[窄屏](publication-privacy.md#验收证据)、[目检](publication-privacy.md#验收证据) |
| 构建 / 类型 / 静态 / 格式 / 双锁 / 许可 | 核心全通过；补验构建/类型/静态/格式通过，随后uv PATH错误退出2；绝对路径补双锁/许可/扫描4项通过；30Python＋48Node许可、unknown0 | [核心14阶段](publication-privacy.md#验收证据)、[失败保留](publication-privacy.md#验收证据)、[四项后检](publication-privacy.md#验收证据) |
| 秘密与导出 | 源码模式扫描通过；最终200文本36,427,906字节，20合成秘密＋95组范围/1710派生令牌精确及模式命中0；68二进制不作文本扫描，仅列明关键截图已目检 | [源码](publication-privacy.md#验收证据)、[外置扫描/哈希](publication-privacy.md#验收证据)、[目检范围](publication-privacy.md#验收证据) |
| 新隔离安装 / README | 新source/venv/node_modules/PG实际执行，仅复用公开下载缓存；demo真实buggy→fixed input→compare=[1,0,0]、repair_verified=true | [clean](publication-privacy.md#验收证据)、[demo](publication-privacy.md#验收证据)、[启动](publication-privacy.md#验收证据) |
| 工程结论 | **达到V2首版本机工程验收；未验证生产、客户、模型增量或市场** | 上列42项映射及证据；验收后停止 |

补充核验与执行限制：

- [workspace.tsx:25](../apps/web/app/workspace.tsx#L25)原侧栏/页脚保留E9及“E10未开展”，登录后任意页面可见，阶段信息错误。已改为V2与“真实模型与客户验证未执行·未部署生产”，浏览器断言/构建复验通过。
- 调整窗口后的Chrome长截图出现重复首屏，影响视觉证据可信度。原截图保留；[截图函数](../scripts/e8-browser.mjs#L17)增加可见视口捕获，再以新建390×844、关闭GPU的Chrome核对真实页面：单个sidebar、无横向溢出、gate0/3可读。最终视觉结论使用[新截图](publication-privacy.md#验收证据)，不把旧截图异常当作页面验证正常。
- 补验shell PATH缺uv导致锁检查未启动、退出2；原失败日志保留，以根环境uv绝对路径补四项，命令见[后检](publication-privacy.md#验收证据)。没有跳过失败断言或合并成整条流水线通过。
- 隔离源码扫描的172文件未涵盖外置产物；补扫已覆盖全部最终证据目录及隔离日志。精确匹配仅使用本次隔离启动生成的测试秘密/派生令牌，未精确读取pytest外部临时目录的每个短期令牌，未读取真实凭据。
- `source_environment_unchanged`核对原`.env`/开发PG路径存在性与mtime，不是整个开发库逐字节比较；需求/源码另有哈希保护。隔离README演示库保留供复核，临时验收库已删。

使用限制与未执行检查：

- 仅本机 loopback、单团队信任模型、共享 OS/数据库账号；未实施公网认证、敌对多租户隔离、生产访问或真实支付。
- second Adapter 只覆盖 S01—S10；故障/barrier/E6 replay 的更高能力须明确拒绝，不能 N/A 通过。工程复用不等于客户成功。
- controlled 只控制声明的快照、输入、故障和调度边界，不控制任意外部系统时钟、网络或竞争胜者。
- raw 到期拒读与物理保留期清理分开；显式 retention/reset/delete 的结果须保留审计。跨服务删除非原子，外部导出/备份需独立治理。
- 真实模型服务、自然语言 PUT、供应商 token/费用、AI 增量、真人确认时间、客户规则访谈、授权 staging 试点、满意度、购买意愿及付费市场实验均未执行。本次无需模型 key。
- 实测Python3.12.14、PostgreSQL18.4、Chrome155.0.8059.40；实际pnpm11.25.0与packageManager声明11.19.0不同，声明执行器版本未实测，依赖内容通过frozen双锁校验。
- 外部 GitHub/Linux runner、Windows、容器实机、Safari/Firefox、屏幕阅读器、正式 WCAG/安全审计和大规模性能/容量试验未执行。实际本机测试不能外推这些环境。
- 依赖许可证清单不能替代分发合规履约；涉及 LGPL/MPL/CC-BY 等义务继续按已有交付说明处理，未开展外部分发。
- 本次没有公网部署、外部发布、生产访问或真实客户试点授权。完成 E10 工程验收后停止并汇报，不自动进入后续工作。

后续客户验证应在另行授权后开展：确认真实退款/审批业务规则和权限模型、接入隔离 staging、核验独立支付证据可获得性、由客户判断发现的业务价值与误报、测量人工确认耗时，再设计实际试点和市场验证；这些事项不能由模型生成指标或本机示例通过替代。
