> 公开版说明：以下为历史工程记录摘要。原始日志、截图、CI制品与私有环境材料不随源码发布；相关链接指向[证据范围说明](publication-privacy.md#验收证据)。历史结果不代表公开副本已经重新验收。

# E7 离线混合角色与对照运行验收记录

结论：**E7 在已声明的离线协议与本机示例范围内验收通过。真实模型服务和 AI 增量实验未执行，未证明 AI 增量。** 最终综合命令从 2026-10-11 01:08:12（America/Los_Angeles）开始，退出 0：277 后端测试、31 浏览器检查通过。**停止于 E7，不进入 E8；E8—E10、完整 V2 发布、客户或生产验证未完成。**

## 授权、需求与 E6 前置证据

用户明确允许进入 E7、更新 AGENTS 当前阶段，并允许可选模型适配器作为阶段性例外；核心套件不能依赖外部模型。无授权凭据时完成离线功能和明确协议替身，不读取真实凭据、开通服务或上传用户数据。2026-10-11 续接后的项目指令仍限定 E7，其他约束保留。

已读取 AGENTS、实施进度、覆盖表、决策、V2 原始 Word、提示词 E1/E7、源码与 diff，先说明方案后开发。仓库全部未跟踪、无提交；保存 `.local/e7-baseline` 的 457 文件副本与哈希，不以空 diff 忽视用户内容。AGENTS 仅修改当前阶段一行。原始需求、附录 B、旧迁移/验收证据和两个锁文件未改写；[变更清单](publication-privacy.md#验收证据) 可核查。

实际复跑 E6 综合验收：**229 后端、24 浏览器检查**，全部服务与真实 PostgreSQL 重启、持久化/reset、构建/静态/双锁/扫描通过。没有阻碍 E7 的前置缺项。另存 [复核综合日志](publication-privacy.md#验收证据)、[测试输出](publication-privacy.md#验收证据)，没有覆盖原 E6 证据。

## 用户验收条件

| 条件 | 实际实现与验证 | 结论及边界 |
| --- | --- | --- |
| 1. 关闭模型仍通过核心套件 | `test_e7_model_off_completes_all_twenty_and_real_permission_probes`，独立 API/Worker/PUT/provider 和 PostgreSQL | 通过；[S01—S20](publication-privacy.md#验收证据)：140 检查，113 pass、27 有理由 N/A、0 fail/inconclusive |
| 2. 非法动作、工具、越权 observation | 角色/对象/工具/参数类型/重复 JSON 字段反证；跨项目、run、角色、provider、管理路径和拒绝响应体隔离 | 通过；42 项 `protocol_double` 中实际运行，不冒充真实模型服务 |
| 3. 恶意产品文本不能改平台规则 | 带恶意指令的产品文本进入不可信数据字段；试图调用 provider_ledger 被拒，原契约哈希不变，无产品动作 | 通过；[注入反证](publication-privacy.md#验收证据)；资金规则实现未改变 |
| 4. 预算超限明确终止，不能通过 | 调用前预占、输出用量超限/低报、重建不清零、未知不重发；失败 run 为 model_budget_exhausted/inconclusive | 通过；[用量超限](publication-privacy.md#验收证据)、[实际实验预算终止](publication-privacy.md#验收证据) |
| 5. 协议替身与真实服务分别标记 | 42 项离线协议、6 项本机 PUT 服务测试分组；real model service 为 not_run；无跳过伪装成功 | 通过；[分类记录](publication-privacy.md#验收证据)；模型服务测试未执行 |
| 6. 没有真实实验不声称 AI 增量 | 运行/实验 JSON 与 HTML 都标记未证明；普通 API hybrid 回退 rule，实际模型调用 0 | 通过；[真实配对结果](publication-privacy.md#验收证据)、[fixed HTML](publication-privacy.md#验收证据)、[buggy HTML](publication-privacy.md#验收证据) |

模型接口与产品调用分离。模型只拿到 schema、当前身份可见投影和允许工具，不持有 HTTP/数据库/provider/凭据接口。输出只允许受限 read_refund、具有自然语言入口时的 send_message 和有界 wait；最多有限修正，最终 actor_error。已有规则角色的 S09/S10 仍向 PUT 实际发出低权限请求，平台边界测试不替代产品权限测试。

本机 `http_refund_v1` 没有自然语言入口，因此没有运行模糊退款、遗漏材料、用户改口等聊天场景。`ModelAdapter` 为 provider 无关接口，本次唯一注册实现是 `ProtocolTestAdapter`；没有已授权的供应商网络实现。不能把离线协议验收描述为真实模型接入或效果证明。

## 对照运行与指标口径

综合验收经实际 API 新建两个独立实验；每个实验固定产品版本、环境、规则、seed 集 `[17,23]`、初始快照、输入调度、运行预算及模型预算。所选场景为 S01/S09/S10/S12，其他场景明确列入未验证范围；完整 S01—S20 另有上表的核心套件运行。

| 产品版本 | 实验 ID | 每侧 seed 数 | rule / hybrid 结果 | 每侧规则 Finding | 人工确认独立缺陷 / 误报 / 耗时 | 模型调用与费用 |
| --- | --- | --- | --- | --- | --- | --- |
| fixed | `2ca2e769-d589-4e05-93f8-7fda7d8afb61` | 2 | 各两轮 completed/pass | 0 / 0 | 未测 / 未测 / 未测 | 各 0 调用；模型费用 0，来源为未调用服务 |
| buggy | `1063e034-2489-4c43-953a-4f5b78c96d3d` | 2 | 各两轮 completed/fail | 4 / 4 | 未测 / 未测 / 未测 | 各 0 调用；模型费用 0，来源为未调用服务 |

Finding 是规则证实的外部表现，不等同人工确认的独立根因，不能把 4 个 Finding 报成 4 个独立缺陷。人工复核 API 要求本实验当前产品 Finding 和证据哈希，确认后按显式 root_cause_id 跨 seed 去重。未采集的指标为 null/未测；部分复核明确显示覆盖数量。[合成 review 测试](publication-privacy.md#验收证据) 中的 reviewer/13 秒仅是协议输入，**不计入上表、真人时间或模型效果实验**。

两组实验均通过配对条件与封存证据核验。当前核心场景是确定性输入，seed 的不同取值不代表新增随机语义覆盖。两个策略都按产品能力使用规则角色；结果相同不能证明 LLM 有效或无效。没有生成客户满意度、购买意愿或市场预测。

## 持久化、取消与重启

迁移 `0006_e7` 新增策略、调用审计、实验/成员与人工复核表，保持旧契约与 Manifest。真实 PostgreSQL 18.4 验证空库、含 E6 数据升级、重复迁移、降级/升级、不可变触发器和复合作用域；没有 SQLite 或内存假库替代。

- PostgreSQL/API/Worker/PUT/provider/Web 全部实际停止再启动，八个配对 run 的 history/actor_policies、两个实验的条件/指标逐项相等。
- 单独的**离线协议 probe** 在真实 PostgreSQL 保存两次调用的五条审计阶段记录（含一次非法工具拒绝）。数据库重启后记录逐项相等；probe 没有产品 dispatch，业务 verdict 保持 inconclusive。
- 随后实际 reset 删除 probe 的 5 条 actor_calls 与 1 条 actor_policies。其他实验 run 保留；E6 源历史及新账本也保持不变。[重启摘要](publication-privacy.md#验收证据)、[协议持久化原记录](publication-privacy.md#验收证据)、[综合 runtime](publication-privacy.md#验收证据)。
- 模型预算在作业行锁内预占，Lease 检查和事件派发保留既有计数。按数据库时间限制每 run 调用间隔；限流等待、迟到响应和决策后派发前取消都有测试。失去 owner/epoch 的旧 Worker 不得追加模型停止或调用记录。
- 策略或调用证据缺失会使报告不确定；[删除必需策略反证](publication-privacy.md#验收证据) 没有通过。实验成员在 reset 后作为墓碑保留，证据不足不补造成功数据。

验收结束已清理自身进程与临时数据库，以上 ID 用于核查保存的证据，不能继续访问已删除临时库。README 的 `scripts/demo_e7` 可创建新的实际实验。

## 实际命令与结果

从项目根执行；综合入口配置本机测试身份、临时数据库和捆绑 Node/pnpm，不读取真实凭据。后续复验请另设 `ACCEPTANCE_EVIDENCE_DIR`，保留本次目录。

| 命令 | 实际结果 | 证据 |
| --- | --- | --- |
| `ACCEPTANCE_EVIDENCE_DIR=docs/evidence/e7 .venv/bin/python -m scripts.verify_e7 > docs/evidence/e7/verification.txt 2>&1` | **退出 0** | [综合日志](publication-privacy.md#验收证据)、[启动](publication-privacy.md#验收证据)、[PostgreSQL](publication-privacy.md#验收证据) |
| `.venv/bin/python -m pytest -q --tb=short --junitxml=docs/evidence/e7/pytest.xml`（验收器执行） | **277 passed、0 failed、0 skipped，168.78 秒，1 既有 warning** | [文本](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据) |
| `node scripts/browser-smoke.mjs` | 10 项通过 | [结果](publication-privacy.md#验收证据) |
| `REPORT_RUNTIME_PATH=docs/evidence/e7/runtime.json node scripts/report-browser.mjs` | 7 项通过 | [结果](publication-privacy.md#验收证据) |
| `REPORT_RUNTIME_PATH=docs/evidence/e7/runtime.json node scripts/replay-browser.mjs` | 7 项通过 | [结果](publication-privacy.md#验收证据) |
| `E7_RUNTIME_PATH=docs/evidence/e7/experiments.json node scripts/experiment-browser.mjs` | 7 项通过 | [结果](publication-privacy.md#验收证据) |
| `NEXT_TELEMETRY_DISABLED=1 pnpm build:web` | 生产构建退出 0 | [输出](publication-privacy.md#验收证据) |
| `pnpm typecheck` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/ruff check packages services migrations tests scripts examples adapters` | All checks passed | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/ruff format --check packages services migrations tests scripts examples adapters` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/uv lock --check --offline --cache-dir .local/uv-cache` | 退出 0，锁保持 | [输出](publication-privacy.md#验收证据) |
| `pnpm install --frozen-lockfile --offline --store-dir .local/pnpm-store` | 退出 0，无新增依赖 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/python -m scripts.scan_secrets` | 高置信模式无发现 | [综合扫描](publication-privacy.md#验收证据)、[文档收尾扫描](publication-privacy.md#验收证据) |

已目视四张 E7 实验截图：fixed/buggy 桌面及 390px。中文结论、未测指标、费用来源及“未证明 AI 增量”可见；窄屏表格在容器内横向滚动，无页面溢出，完整证据可用键盘展开。此处是最小工程报告，非 E8 完整业务 UI。

## 失败、修复与复验

| 实际过程 | 处理及结果 |
| --- | --- |
| 续接后的首次集成检查：6 errors，数据库返回 starting up | 未执行到业务，等待 PostgreSQL 明确就绪后原 6 项通过（33.51 秒）；[失败](publication-privacy.md#验收证据)、[复验](publication-privacy.md#验收证据) |
| 最初模型协议检查 | 35 passed；[输出](publication-privacy.md#验收证据)，不是外部模型服务测试 |
| 首轮完整验收 | 274 passed、31 浏览器及所有综合步骤通过；[综合](publication-privacy.md#验收证据)、[当时测试](publication-privacy.md#验收证据) |
| 收尾新增审计深度测试首次失败 | 深层数据未截断；增加深度限制、敏感键名清理，保持业务原始观测不变；[1 failed / 39 deselected](publication-privacy.md#验收证据) |
| 审计修正复验 | [1 passed / 41 deselected](publication-privacy.md#验收证据)；另加决策后取消与旧 owner 拒写检查，最终完整 277 项通过 |

没有降低业务断言、空测试、失败跳过、隐藏失败轮次或硬编码业务 PASS。唯一 warning 是原 Starlette/httpx TestClient 弃用提示，未屏蔽或借此新增模型依赖。

## 未执行与限制

真实模型服务、供应商 SDK/tokenizer、实时单价/收费调用、自然语言 PUT、授权客户/staging、真人误报与确认耗时、市场实验均未执行。协议替身的 UTF-8 单位不是供应商 token；没有真实价格来源，不能估算真实模型费用或增量。模型默认关闭，真实接入需先明确服务、可上传数据及安全凭据引用，并遵循环境凭据配置流程。

当前只有已审阅的本机示例与四个测试身份；按 run 限流不是供应商全局配额。通用外部模型的超时/断连接语义、任意私有文本 DLP、公网认证/最小数据库权限和生产安全审计未完成。保留 E6 的有限 controlled 边界，不控制外部时钟、OS 或数据库锁胜者。reset 仍非跨服务原子事务；未运行实际付款、Linux/Windows、容器实机或生产部署。

**本次 E7 离线工程必须项无遗留失败。E8—E10 及完整 V2/客户/生产验收均未完成，下一阶段需另行明确授权。**
