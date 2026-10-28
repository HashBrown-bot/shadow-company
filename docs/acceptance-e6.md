> 公开版说明：以下为历史工程记录摘要。原始日志、截图、CI制品与私有环境材料不随源码发布；相关链接指向[证据范围说明](publication-privacy.md#验收证据)。历史结果不代表公开副本已经重新验收。

# E6 重放与修复验证验收记录

结论：**E6 在已声明的本机示例边界内验收通过。** 最终综合命令从 2026-10-08 21:56:51（Asia/Shanghai）开始，退出 0；229 后端测试、24 浏览器检查通过。S12 同条件 buggy 连续 10 次失败、fixed 连续 10 次通过，独立证据齐全。**本次停止于 E6；E7—E10、完整 V2 发布、真实客户及生产部署未完成。**

## 授权与前置复核

用户明确授权更新 AGENTS 的“当前只执行”为 E6，其他规则保持。实施前读取 AGENTS、实施进度、需求映射、决策、原始 V2 Word、提示词 E1/E6、代码和 diff，先说明方案再实际开发。仓库无提交且全部未跟踪，保存 `.local/e6-baseline` 的原文件及哈希作逐文件比较，未以空 diff 忽略用户内容。

执行 `ACCEPTANCE_EVIDENCE_DIR=docs/evidence/e5-recheck .venv/bin/python -m scripts.verify_e5`：207 passed，0 失败/跳过，1 既有 warning，48.59 秒；10 基础 + 7 报告浏览器检查，真实 PostgreSQL 与全部服务重启、持久化/reset、构建、类型、静态、双锁及扫描通过。没有阻碍 E6 的前置缺项。[E5 复核输出](publication-privacy.md#验收证据)、[测试](publication-privacy.md#验收证据)。原 E5 证据不覆盖。

## 验收条件与实现

| 条件 | 实际验证及证据 | 结果 |
| --- | --- | --- |
| history 仅展示历史 | API 纯 SELECT；SafeHTTP 间谍禁止任何出站调用；前后 jobs/runs/观测/journal/评估/双服务审计行数相同 | 通过，零 PUT 调用 |
| input 重新执行 | 新 run/命名空间、同初始支付快照、新 binding；目标契约预检；实际版本响应头、build 与服务端 business_call 审计 | 通过，新响应、新 Webhook、新独立账本 |
| 禁止输出复用 | StrictBool 拒绝 true、1 和字符串；无旧响应 fixture；来源仅为源输入计划及资产 | 通过 |
| controlled 准确边界 | 本机能力实测；初始数据、语义故障、平台排序/回调投递/barrier；控制契约条件变化明确拒绝 | 通过，不宣称时钟或任意 staging 确定性 |
| Manifest 可追溯且不覆盖 | 0005_e6 资产与 seal 不可变；契约/规则/环境/PUT/适配器/代码/依赖/seed/快照/角色/故障/计划和实际调度均有内容或引用哈希 | 通过，旧契约和旧 Manifest 保留 |
| 语义匹配而非旧序号 | 动作+对象+角色+body+当前业务字段/版本；故障检查实际提交状态；逆序存储仍通过且资产哈希相同 | 通过 |
| 故障不能按第 N 次盲投 | provider 第一次错误金额返回 fixture_mismatch；第二次物理请求才符合语义并得到 429，第三次正常新建账本 | [独立服务证据](publication-privacy.md#验收证据) |
| 删除必需 fixture 不能通过 | 移除 execute fixture 后 environment_error/fixture_mismatch、inconclusive、provider 调用 0；通过后分别移除 actors/faults/snapshot 也使当前结论失效 | [缺 fixture](publication-privacy.md#验收证据)、[资产丢失](publication-privacy.md#验收证据) |
| 不匹配不伪装产品错误 | 前置版本改为 99，停止在调用 provider 之前，记录候选/实际状态，比较不认定修复 | [前置状态不匹配](publication-privacy.md#验收证据) |
| 反馈角色可解释 | retry_if_unsettled_v1 使用新可见状态、保存理由及 skip_settled；跳过 S05 必需重复动作时 inconclusive、exact_actor_inputs=false | [反馈偏离](publication-privacy.md#验收证据) |
| 区分 PUT 与条件变化 | 单独比较规则、环境、契约语义、provider、适配器、平台/依赖、数据库、seed、快照、fixture、调度和边界 | [环境变化](publication-privacy.md#验收证据)、[规则变化](publication-privacy.md#验收证据) 均不认定修复 |
| buggy 10 次失败 / fixed 10 次通过 | 全部真实新 run，先保存每次证据再断言；检查实际目标版本、独立 ID、故障命中及业务检查 | 通过，详见下一节 |
| 原始历史不变 | history 规范哈希前后一致；没有修改源运行/观测/封存；目标 reset 后源仍相等 | 通过 |
| 保留 E5 正确实现 | E6 fixed S01—S20 基线及其 input 重放，保留真实故障/双 barrier/子 Worker 中断恢复；旧 E2—E5 全部回归 | 通过，各 140 检查：113 pass、27 not_applicable |
| 真实 PostgreSQL 和迁移 | PostgreSQL 18.4；空库、含 E5 记录升级、重复升级、降级/升级、隔离/不可变、reset | 通过，无 SQLite 替代 |
| 实际服务与持久化 | API、Worker、PUT、provider、Web 和 PostgreSQL 全部停止再启动；历史/封存/观测/独立账本相同 | 通过，重启后 compare 仍验证修复 |
| 文档与可见报告 | README、架构、需求表、决策、进度、本记录；真实 JSON/HTML/最小 Web 重放比较入口 | 完成；非 E8 完整 UI |

## 20 次连续重复的独立证据

选定 S12：provider 先提交成功账本，再扣住响应头，使 PUT 发生真实读取超时。buggy 在无法确认结果时以新幂等键再次执行，产生两笔成功资金；fixed 使用查询确认，只有一笔。Evaluator 依据新账本/回调/产品状态判定，既不读取缺陷开关，也不复用源 trace。

批次来源、20 个 run ID、各次结果和 Manifest 哈希见 [e6-repetitions.json](publication-privacy.md#验收证据)。每个下列文件包含本次完整报告（含原始观测）、run compare、计划/完成 Manifest 及 fixture 资产；不是只有成功标记。每次断言前写入，即使失败也保留产物。

| 次序 | buggy：fail，2 次 provider 执行 / 2 条账本 | fixed：pass，1 次 provider 执行 / 1 条账本 |
| --- | --- | --- |
| 1 | [独立证据 01](publication-privacy.md#验收证据) | [独立证据 01](publication-privacy.md#验收证据) |
| 2 | [独立证据 02](publication-privacy.md#验收证据) | [独立证据 02](publication-privacy.md#验收证据) |
| 3 | [独立证据 03](publication-privacy.md#验收证据) | [独立证据 03](publication-privacy.md#验收证据) |
| 4 | [独立证据 04](publication-privacy.md#验收证据) | [独立证据 04](publication-privacy.md#验收证据) |
| 5 | [独立证据 05](publication-privacy.md#验收证据) | [独立证据 05](publication-privacy.md#验收证据) |
| 6 | [独立证据 06](publication-privacy.md#验收证据) | [独立证据 06](publication-privacy.md#验收证据) |
| 7 | [独立证据 07](publication-privacy.md#验收证据) | [独立证据 07](publication-privacy.md#验收证据) |
| 8 | [独立证据 08](publication-privacy.md#验收证据) | [独立证据 08](publication-privacy.md#验收证据) |
| 9 | [独立证据 09](publication-privacy.md#验收证据) | [独立证据 09](publication-privacy.md#验收证据) |
| 10 | [独立证据 10](publication-privacy.md#验收证据) | [独立证据 10](publication-privacy.md#验收证据) |

20 次的 seed、初始业务快照、规范契约语义、角色/故障资产及规范输入调度相同；只有目标 PUT 行为版本及新 run 命名空间等明确变量变化。每次有 5 次真实 PUT 业务 HTTP 调用（含只读前置探测），审计版本分别为 buggy/fixed；20 个 run 的账本 entry_id、Webhook event_id、observation_id 均不相交。实际路径从 2 次 provider 执行变为 1 次，报告为 allowed_product_path_change。每个 fixed 比较均 repair_verified=true，buggy 均 false。

原源 history 重放前后规范 SHA-256 均为 `f78215d4be2d58feae0065239bc72bc6320eaa3f64a29c3ec0b7fa2bdc0e80ae`。没有硬编码业务结果、筛选成功轮次、降低断言或隐藏重复失败；正式 20 轮全部满足原断言。

## 独立演示、重启与清理

综合验收另执行真实 API 演示：[runtime.json](publication-privacy.md#验收证据)、[源 buggy 报告](publication-privacy.md#验收证据)、[新 fixed 报告](publication-privacy.md#验收证据)、[运行比较 HTML](publication-privacy.md#验收证据)。此演示不是前述 20 轮中的一轮。

- 项目 `003c877b-d9d2-4b26-8f0c-6f5284ad7df1`；源 run `37e45189-fc3d-4286-ab2e-53f742c336a4` fail；目标 run `8a5d0c9a-2ac7-4a01-9aec-d45018cc3c1e` pass，比较在声明范围验证修复。
- 新目标实际审计为 fixed；provider 一次新执行、一条新账本；与源的两笔、两个回调分离。PUT build 相同、实际行为版本不同，是本机示例的真实两个执行分支，不声称两个客户部署。
- 全部服务与 PostgreSQL 停止后确认端口释放，再重启；目标 history（含封存与观测）和独立账本逐项相等，compare 仍 repair_verified=true。
- 审计 reset 实际删除目标 3 个 replay_assets、1 个 replay_seal、18 个事件/Action/消费状态、77 个 journal、22 个观测、5 个业务检查及远端记录；源 history 保持相等。保留契约、输入哈希、请求键墓碑和 reset 审计。
- 验收器最终清理自身进程和临时数据库。持久证据文件保留；重新演示可用 README 命令创建新项目/运行，不能继续访问已清理临时库中的 ID。

## 实际命令与输出

从项目根执行，默认端口需空闲；综合入口自动配置示例凭据、临时数据库和捆绑 Node/pnpm 路径，不读取真实凭据。后续再次验收应设置新的 ACCEPTANCE_EVIDENCE_DIR，保留本次目录。

| 命令 | 实际结果 | 记录 |
| --- | --- | --- |
| `ACCEPTANCE_EVIDENCE_DIR=docs/evidence/e6 .venv/bin/python -m scripts.verify_e6 > docs/evidence/e6/verification.txt 2>&1` | **退出 0**，全部步骤完成 | [综合日志](publication-privacy.md#验收证据)、[服务启动](publication-privacy.md#验收证据)、[PostgreSQL](publication-privacy.md#验收证据) |
| `.venv/bin/python -m pytest -q --tb=short --junitxml=docs/evidence/e6/pytest.xml`（验收器执行） | **229 passed、0 failed、0 skipped、1 warning，141.05 秒** | [文本](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据) |
| `node scripts/browser-smoke.mjs` | **10 项通过**：真实健康、数据库/迁移、项目持久化、校验/错误、键盘/窄屏、跨来源拒绝 | [结果](publication-privacy.md#验收证据) |
| `REPORT_RUNTIME_PATH=docs/evidence/e6/runtime.json node scripts/report-browser.mjs` | **7 项通过**：真实 API 报告、证据锚点、四态/运行证据与窄屏 | [结果](publication-privacy.md#验收证据) |
| `REPORT_RUNTIME_PATH=docs/evidence/e6/runtime.json node scripts/replay-browser.mjs` | **7 项通过**：三模式、只读 history、真实 fixed 重放、比较/路径、窄屏/键盘和错误 | [结果](publication-privacy.md#验收证据) |
| `NEXT_TELEMETRY_DISABLED=1 pnpm build:web` | Webpack 生产构建退出 0 | [输出](publication-privacy.md#验收证据) |
| `pnpm typecheck` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/ruff check packages services migrations tests scripts examples adapters` | All checks passed | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/ruff format --check packages services migrations tests scripts examples adapters` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/uv lock --check --offline --cache-dir .local/uv-cache` | 退出 0，锁文件未改变 | [输出](publication-privacy.md#验收证据) |
| `pnpm install --frozen-lockfile --offline --store-dir .local/pnpm-store` | 退出 0，未新增依赖 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/python -m scripts.scan_secrets` | 高置信模式无发现；文档收尾后另扫一次 | [综合扫描](publication-privacy.md#验收证据)、[收尾扫描](publication-privacy.md#验收证据) |

唯一 warning 是既有 Starlette/httpx TestClient 弃用提示，保留未屏蔽。已目视查看 [桌面重放](publication-privacy.md#验收证据)、[390px 重放](publication-privacy.md#验收证据)、[桌面比较](publication-privacy.md#验收证据)、[390px 比较](publication-privacy.md#验收证据)：表单可访问、结果及偏离可读、无页面溢出。工程面板仍非 E8 完整业务 UI。

## 实际失败与修复

| 问题 | 处理与复验 |
| --- | --- |
| 第一个 E6 input 专项 1 failed / 11 deselected：fixed 得到 inconclusive | 故障覆盖将原始 recipient 与已脱敏语义记录比较，导致命中不被承认。统一计划/观测脱敏规范，继续严格核验全部故障字段和命中，不降低业务断言；[原失败](publication-privacy.md#验收证据) |
| 上述覆盖修复 | 同项 1 passed / 11 deselected，6.04 秒；随后 21 项 E6 专项通过，88.59 秒；[聚焦复验](publication-privacy.md#验收证据)、[专项回归](publication-privacy.md#验收证据) |
| 审阅发现版本指纹需在进程启动时冻结，比较还需覆盖输入调度 | 固定启动 provenance；规范化新 binding 与目标版本后的调度哈希进入比较；补 controlled 条件改变拒绝测试，最终 229 项回归通过 |
| 一次综合命令未能提交执行 | 自动审批服务返回额度限制；用户要求继续后重新提交同一命令，成功退出 0。该未执行尝试不算测试结果，不绕过审批 |

正式 10+10 轮无重复验收失败，无需降低断言。原始文档、附录 B、双锁、旧迁移和旧阶段证据的哈希对比见 [改动基线清单](publication-privacy.md#验收证据)。AGENTS 仅修改当前阶段；无模型依赖、虚假指标、空测试或跳过失败。

## 限制、未执行与下一阶段

- **controlled 只保证实际控制范围。** 墙钟、OS 调度、数据库锁胜者、网络延迟、UUID 和外部系统明确不可比较；S19 不强制指定竞争胜者。`runtime.time_mode=controlled` 不支持；不存在任意 staging 完全确定性的承诺。
- 当前只支持审阅过的本机 http_refund_v1 示例 buggy/fixed。E6 新基线可重放 S01—S20；旧运行缺少完整版本/资产清单只能 history，不能补造旧哈希。未验证任意外部 snapshot/reset/时钟接口或独立客户部署的跨版本迁移。
- 相同角色策略遇到新反馈也可能改变输入。所有偏离显式报告；跳过场景必需输入不能通过。合法产品重试减少可比较，不代表延迟/内部线程顺序可比较。
- API 采用本机信任模型，共用开发数据库账号；reset 非跨服务原子事务。未完成公网认证、数据库/OS 最小权限、全面安全审计；凭据扫描只覆盖高置信模式。
- 未执行真实客户/staging、实际付款、模型/市场实验、同时杀死 PUT/provider、主机断电/数据库网络分区、Linux/Windows、容器实机或生产部署。这些未执行项未计为通过。

E6 必須验收项无遗留失败。**下一阶段为 E7，需要另行明确授权；E7—E10 尚未完成，本次不继续。**
