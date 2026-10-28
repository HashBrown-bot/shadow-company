# V2 需求覆盖表

更新：2026-10-11（America/Los_Angeles）。当前仅 **E10**；独立安装与修复后核心验收已通过，346 后端测试、27 控制台/5 登录/2 重启检查均有实际证据。收尾 UI/viewport 复验和必要后检已完成；前端补验流水线的 PATH/uv 失败与独立补检分别保留，最终签收见 [发布检查表](release-checklist.md)。以下 E6—E9 分阶段表格保留历史边界，不替代 E10 结果。历史 [E9](acceptance-e9.md)、[E8](acceptance-e8.md)、[E7](acceptance-e7.md)、[E6](acceptance-e6.md)、 [E5](acceptance-e5.md)、 [E4](acceptance-e4.md)、[E3](acceptance-e3.md)、[E2](acceptance-e2.md) 保留。

| 需求 | 实现与证据 | 当前边界 |
| --- | --- | --- |
| REQ01 契约与预检 | 严格 schema/不可变版本与哈希，真实预检；五条规则必需；非法故障边界拒绝；test_contracts、test_api、test_e5_safety | 本机示例；未知产品与真实 staging 未接入 |
| REQ02 隔离与重置 | project/run 复合键；PUT/provider 独立 schema；reset 增加事件消费、journal、故障、服务审计及 E7 角色策略/调用/复核；跨 run 及重启测试 | E9 项目/run 令牌范围、审计 reset/项目删除已实现；非跨服务原子事务，共享 OS/数据库账号 |
| REQ03 三层证据 | 政策、PUT 观测、provider 账本分离；提交后响应丢失具有真实提交与超时证据 | 工程示例；不声称真实资金核验 |
| REQ04 四态评估 | REFUND_001/002、APPROVAL_001、STATE_001、TIME_001；Policy 2 严格校验审批类型与初始币种；七类归因、Finding、JSON/HTML；缺证据/取消/预算不通过 | E10 通用规则健壮性修复对两 Adapter 共用；旧契约/封存不覆盖；无 readiness 分数 |
| REQ05 故障注入 | 六类显式计划、实际命中、调用与投递证据；真实断连接、提交后读超时、重复/乱序回调、429、审批离线 | E5；S11 覆盖执行前连接中断，不是 DNS/TCP 建连拒绝 |
| REQ06 受控并发 | 平台线程和 PUT 入口 barrier；同指令、部分退款余额、取消/执行三组；开始结束与到达释放序号 | E5；受控本机边界，非任意 staging 完全确定性 |
| REQ07 输入重放 | history 纯只读；input 新命名空间/目标版本/新账本与回调；语义 fixture；planned Manifest + completion seal；E10 实际 10+10 次；比较核对实际 Evaluator 与冻结构建/政策 | controlled 仅已声明边界；fixture 偏离为环境原因及 gate 3；旧清单缺失或规则漂移不能确认仅修 PUT |
| REQ08 混合角色 | E7 版本化角色策略、身份可见 observation、结构化动作、有限修正、持久调用预算/限流/取消；真实 rule/hybrid 配对运行与人工根因分组；`test_e7_actors` / `test_e7_live` | 普通 API 回退 rule；离线协议替身单独标记；无真实模型服务/自然语言 PUT 实验，未证明 AI 增量 |
| REQ09 可用 UI | 中文项目/接入/预检/运行/Finding/input replay/比较；后端分页、URL 恢复、四来源时间线；E10 展示与 API/CLI 同源的业务 verdict、严格 gate 及 execution_issues | 实际 Chrome 27 控制台+5 登录+2 重启通过且文案修正后复验；两项新390×844视口复核通过；无客户验证 |
| REQ10 CLI 与 gate | simctl 六命令、JSON/help、e10-gate-2；同一 report/compare 快照提供 API/CLI/UI 结论；真实 subprocess 验证 0/1/2/3；并发预算/fixture 无效不误归为 2 | 本机流水线实际执行；全部 N/A 不替代必需覆盖；外部 GitHub runner 未触发；开放探索未启用 |
| REQ11 安全与恢复 | E3 出站/DNS/重定向、验签防重放；E5 租约/真实 SIGKILL/未知不重发；E9 token/权限/raw 限制、保留期、急停和删除 | 本机单团队；物理过期清理需显式调用；未做公网或独立安全审计 |
| REQ12 复用与交付 | E10 新源码/venv/node_modules/真实 PostgreSQL 空库按锁安装并迁移至 0007_e9；README 演示、第二 JSON-RPC S01—S10、许可证及实际清理记录通过 | 第二示例仅工程复用；真实客户、跨平台/容器实机和生产发布未开展；pnpm 实际 11.25.0/声明 11.19.0 |

## 场景与实际证据

以下 S01—S20 在本轮 [fixed 完整报告](publication-privacy.md#验收证据) 中均已执行并通过；140 条规则检查为 113 pass、27 有理由的 not_applicable、0 fail / inconclusive。严格 [selected/suite gate](publication-privacy.md#验收证据) 均为 0。表中 E4/E5 表示实现建立阶段，本轮真实复跑证据由 [346 项 JUnit](publication-privacy.md#验收证据) 支持。

| 场景 | 触发及核验 | 范围 |
| --- | --- | --- |
| S01 | 199999、200000 无审批合法退款，各一次执行 | E4 保留，E5 回归 |
| S02 | 200001、独立审批身份、有效快照与账本 | E4 保留，E5 回归 |
| S03 | 大额未审批，实际执行请求被拒与零执行 | E4 保留，E5 回归 |
| S04 | 审批后改金额/版本；fixed 失效，buggy 被 APPROVAL_001 检出 | E4 保留，E5 回归 |
| S05 | 同指令重复创建/执行；按 entry_id 计数，不能吞掉重复请求 | E4 保留，E5 回归 |
| S06 | 同支付 6000+4000 合法部分退款 | E4 保留，E5 回归 |
| S07 | 6000+5000 超过 10000；fixed 拒绝，buggy 超额 | E4 保留，E5 回归 |
| S08 | CNY/USD 不混算，向 CNY 支付提交 USD 实际被拒 | E4 保留，E5 回归 |
| S09 | support 实际发出审批请求，PUT 403 | E4 保留，E5 回归 |
| S10 | customer_a 自查、customer_b 查他人，实际 403 且无业务字段 | E4 保留，E5 回归 |
| S11 | provider 提交前断开真实 HTTP 连接；无首次提交、PUT 记录连接失败并有界恢复 | E5 独立服务 |
| S12 | ledger 事务提交后扣住响应；PUT 真正读超时；fixed 核验，buggy 更换键导致重复资金 | E5 独立服务 |
| S13 | 同一签名 event_id 重复到 PUT 和平台，记录 duplicate 响应与投递审计 | E5 独立服务 |
| S14 | provider 提交前持久处理中事件，成功后才投递；fixed 不回退，buggy STATE_001/TIME_001 | E5 独立服务 |
| S15 | provider 实际 429 后恢复，保存调用次数；重试预算 0 时不得再调用 | E5 独立服务 |
| S16 | 两次同指令 execute 通过双方 barrier 同时到达；fixed 一条，buggy 重复 | E5 实际重叠 |
| S17 | 6000/5000 争 10000；buggy 读取后同步与过期余额，fixed 锁内重查；累计账本核验 | E5 实际重叠 |
| S18 | 审批人离线返回 423；真实等待后仍无批准，大额执行拒绝，无资金 | E5 独立服务 |
| S19 | 产品 cancel/execute 通过 barrier 竞争；取消或已执行状态保留可核验后果 | E5 实际重叠；不预设谁胜出 |
| S20 | 派发前及远端返回后未确认位置真实退出 Worker 子进程，owner/PID 变化，checkpoint 恢复，各一笔 | E5 实际进程中断；另测 SIGKILL |

后端额外覆盖真实 PostgreSQL 空库/升级/降级、租约过期与旧 owner 拒写、会话锁隔离、未知远端结果不重发、queued 取消、提交后在途取消、事件/墙钟/并发/重试预算、缺实际命中证据阻断、runtime.time_mode=controlled 拒绝、Evaluator 不读行为开关，以及原 E3/E4 的隔离/安全/非法值/缺证据回归。

协议层反证与真实 HTTP/进程测试在测试文件和验收记录中分别标记。S20 的恢复核验不是 E6 输入重放；测试数、Finding 数和场景数不是同一指标。E7 协议测试不代表真实模型实验；E9 新增验证见下表，E10、真实客户、模型增量或生产未执行。

## E6 历史验收映射

| 要求 | 实现与证据 |
| --- | --- |
| history 不调用 PUT、不改原始历史 | `history()` 纯 SELECT；HTTP spy + 数据库计数；20 次前后 history 哈希一致 |
| input 实际调用目标版本 | 新 run/binding/资产，PUT business_call 的实际版本/构建、独立 provider 调用与 ledger/outbox；不允许 reuse_product_outputs=true |
| Manifest 完整追溯 | `replay.freeze`、`transport/build`、0005_e6；版本/逐文件/锁文件/资产/计划/实际调度哈希；旧契约不可变 |
| 语义 fixture 与缺项 | `ReplayGuard`、`match_fault`；存储顺序改变仍能匹配，错前置版本/缺 actor 不通过；actors/faults/snapshot 删除后重新阻断通过 |
| 合法路径变化与反馈输入 | S12 fixed 从二次执行变为一次执行加查询；反馈策略 skip_settled 显示输入变化，不能消除 S05 必需覆盖 |
| compare 分离条件变化 | PUT 与规则/环境/契约/依赖/调度分列；规则或环境变化时业务可通过但修复未确认；独立证据 ID 不重叠 |
| controlled 有限承诺 | 仅本机已审阅控制契约，能力实测；时钟/网络/OS/锁胜者不可比较，changed control conditions 拒绝 |
| 10 + 10 重复 | `test_e6_twenty_consecutive_replays_no_hidden_failures`；每次完整报告、Manifest、比较独立落盘，断言前保存失败产物 |
| 保留 E5 与迁移 | S01—S20 E6 基线与 input 重放，真实子 Worker 中断恢复；0004→0005 保留旧记录、空库、重复及降级/升级 |

专项结果与最终综合命令分别列于验收记录，未完成检查不计通过。E6 的阶段验收不代表完整 V2 发布、E8—E10、真实模型或客户验证。


## E7 历史验收映射

| 要求 | 实现与证据 | 明确边界 |
| --- | --- | --- |
| 默认关闭模型、核心套件可用 | `ActorPolicy` 默认关闭；`test_e7_model_off_completes_all_twenty_and_real_permission_probes`，真实 API/Worker/PUT/provider/PostgreSQL | S01—S20 工程基线，不代表完整 V2 |
| 身份可见 observation | 同 project/run/actor、业务 GET/对象范围/字段白名单；跨角色、跨 run/项目、provider、管理接口和拒绝体反证 | 当前本机四个测试身份；非通用 IAM |
| 非法动作/工具/参数被拒 | `ACTION_SCHEMA` 严格 JSON/类型/角色/对象/工具；非法动作不 dispatch，有限修正后 actor_error | 模型只允许受限 read/message/wait；权限探测仍由真实低权限规则角色执行 |
| 恶意产品文本不能改规则 | `test_malicious_product_text_cannot_change_policy_rules_or_invoke_tools`；检查原契约哈希、无未授权 Action、actor_error | 离线协议替身，不是生产攻击测试 |
| 调用限流、取消、预算终止 | PostgreSQL 预占/保守计数、实际调用间隔、等待取消、迟到响应、未知调用不重发、超量和低报反证 | 每 run 限流；替身 UTF-8 单位不冒充 vendor token |
| 真实服务和替身分开 | pytest `protocol_double` 与 `live_local`；记录 `model_service_test=not_run`，审计含 model_id/策略版本/预算/脱敏 I/O | 无真实模型授权、供应商 SDK、模型网络调用或外传用户数据 |
| rule/hybrid 对照 | `POST /api/experiments`，同产品/环境/seed/快照/调度/预算，核验两边 seal/证据；条件缺失不可比较 | API 无语言入口，模型调用 0；自然语言业务场景未运行 |
| 独立缺陷、误报、确认耗时、费用来源 | 规则 Finding 与人工根因组分开；未采集指标为 null/未测；合成 review 测试单独标记 | 无真人确认时间、无市场满意度/购买预测；未证明 AI 增量 |
| PostgreSQL 与持久化 | 0006_e7 空库/含 E6 数据升级/重复/降级升级；策略/调用不可变；真实服务及 PostgreSQL 重启/作用域 reset | 本机信任模型，共用数据库账号；E9 安全与保留期未完成 |
| 交付与停止边界 | README、架构、覆盖、决策、进度、`acceptance-e7.md` 与独立证据目录 | 仅 E7，不自动进入 E8 |


## E8 历史验收映射

| 要求 | 实现与验证 | 边界 |
| --- | --- | --- |
| 项目、接入契约、预检 | `components/projects.tsx`、`contract.tsx`；既有 create/save/preflight；目录模板经原 Configuration 解析 | 保存新版本；不覆盖旧契约，只展示秘密引用 |
| 配置与实际运行 | `configure.tsx` → 原 `POST /api/runs`，冻结独立运行契约、场景和预算；规则角色/模型关闭 | realtime/event_compressed，controlled 时钟禁用；seed 表单为 JS 安全整数 |
| 后端四态与失联 | `console.py` 读取报告、数据库租约与 event_dispatches；文字+符号显示四态 | 失联不是业务失败，取消/预算/缺证据不可通过 |
| Finding 证据 | 当前规则 Finding、规则版本/哈希、预期实际、对象、来源、脱敏请求与独立账本分页 | 不把产品 success 自证为资金成功；Finding 不等于人工根因数 |
| 因果时间线 | 真实 actions/observations/current check_results；角色、产品、provider、evaluator 泳道及分页 | 仅持久化 ID/引用表达因果；未知关联不推测 |
| 真实 input replay | 源配置复制为目标不可变契约、预检、原 replay API；后端 compare | 新 PUT 调用/账本/回调，路径偏离与未验证范围可见；源历史不变 |
| 异常与恢复 | Chrome 实测加载、空项目/无运行、网络错误、真实 403/404、取消、Worker 真实暂停、账本观测缺失、预算终止 | 403 是同源防护，不是 E9 登录/IAM；故障仅专属验收库 |
| 可访问性与布局 | 跳过导航、原生控件、标题/分页焦点、表单标签、details 键盘、四态符号、1440px/390px | 未做屏幕阅读器或正式 WCAG 审计；不宣称完整认证 |
| 刷新与服务重启 | URL 查询标识恢复；PostgreSQL/API/Worker/PUT/provider/Web 全停重启后 history 不变、比较仍确认修复 | 仅本机真实服务，不是外部 staging 恢复承诺 |

E8 当时完整回归 282 项后端、24 项浏览器及 2 项真实 PostgreSQL/服务重启检查通过；构建、类型、静态、双锁与扫描通过。实际命令、失败修复、25 张截图与未执行范围以 [E8 验收](acceptance-e8.md) 为准。这是历史验收，之后分别获得 E9、E10 授权；当前仅进行本轮 E10。


## E9 历史验收映射

| 要求 | 实现与实际证据入口 | 边界 |
| --- | --- | --- |
| validate/preflight/run/report/replay/compare | `packages/simctl`，`test_cli_help_validation_and_redacted_errors`、`test_cli_real_exit_codes_replay_and_export`；已安装 CLI 和 README 演示 | validate/preflight/history 的 0 只针对对应 gate，业务未被隐式验证 |
| 四种退出码与严格 N/A | 真实 CLI buggy=1、fixed/replay/compare=0、provider SIGSTOP=2、预算/删必需账本/S01 缺审批适用=3；`e9-cli-*.json` | 完成的业务失败与未完成生命周期分开；没有放宽模式 |
| 默认受控 CI | `.github/workflows/regression.yml` 和本机 `verify_e9`；完整 S01—S20 strict suite JSON | 外部 runner 未运行，无 schedule/发布；未经人工确认的探索不阻断发布 |
| 干净安装与真实空库 | `clean_e9` 实际新源码、新 venv/node_modules/数据库；README dev.py + demo_e9；migration.txt/pytest.xml | 复用公开下载缓存，未复制用户状态；失败安装独立保存 |
| 项目/run 与权限隔离 | `test_project_run_permissions_expiry_revocation_and_private_evidence`、原跨范围复合键/租约/审计测试；撤销/到期/缺配置 | 逻辑/API 隔离，非敌对数据库/OS 租户隔离 |
| 出站/重定向/DNS | `test_dns_rebinding_and_metadata_rejected`、`test_transport_pins_resolved_ip_and_rejects_redirect`、path escape；真实请求沿同一 SafeHTTP | DNS/传输边界反证含受控解析器/socket 替身；不是互联网扫描 |
| Webhook 验签/重放 | 签名字节/时间/范围反证；S13/S14 真实 provider 投递、event ID 去重、冲突载荷拒绝 | 测试生成密钥，无真实付款或第三方回调服务 |
| Web 登录及退出 | `e9-access-browser.mjs`：匿名 401、坏令牌拒绝/清空、真实登录、HttpOnly/无 DOM 令牌、Origin 拒绝、退出失效 | 本机 HTTP，不宣称公网 SSO/IAM |
| 秘密与原始证据 | 反射凭据脱敏并保留非法金额；evidence/raw 权限；导出 JSON/HTML、源码文本扫描和截图目视 | 永不存未脱敏凭据；普通证据是已脱敏事实，非通用 DLP |
| 保留期/删除/急停 | `test_retention_delete_provenance_and_emergency_stop`、真实在途/queued 急停、provider 暂停删除失败保留证据；`e9-lifecycle*.json` | 在途后果不撤销，跨 run 清理不原子，活跃 trace 延期，备份/文件另管理 |
| 第二不同接口产品 | `test_second_rpc_adapter_real_buggy_fixed_and_isolation`；e9-second-buggy/fixed.json，POST /rpc、独立表与新 provider ID | S01—S10；无第二产品 E6/故障/barrier、无客户验证 |
| 既有 S01—S20/重放/恢复 | 原全套真实服务回归，10+10 replay、S20 和额外 SIGKILL、DB/应用重启；ci-fixed-s01-s20.json | 本机受控边界；不保证任意 staging 的确定性 |
| 锁定/许可证/交付文档 | 双锁检查、已安装 Python/Node 许可及文件哈希、README/架构/决策/进度/验收 | 含 LGPL/MPL/CC-BY 分发复核项，未发布 |

E9 的最终数目、命令、错误与修复逐项见 [验收记录](acceptance-e9.md)。安装失败、未运行的外部 CI、真实客户/模型与 E10 不计入通过项。

E9 当时最终本机验收通过：完整 290 后端、24+5+2 浏览器/重启、严格完整套件、构建/双锁/许可证/扫描；CI 退出码补强后另外复跑已有 8 项 E9 专项及完整后续流水线通过。重复项不计为新增测试。当时核对 139 份运行源码/脚本/测试/锁文件与副本一致，证据链接见验收记录；E9 当时停止且未自动进入 E10，本轮另获 E10 明确授权。


## E10 审查映射

REQ01—REQ12、S01—S20、A—J 的源码、测试函数、独立证据、状态与限制完整列于 [发布检查表](release-checklist.md)。新增资金字段反证见 `tests/test_e10_funds.py`，预算/fixture 归因见 `tests/test_e10_replay.py`，权限/秘密/第二接口 wire 见 `tests/test_e10_access.py`，CLI 同源 gate 与规则版本见 `tests/test_e10_release.py`。相关真实服务断言在原 E5/E6/E8/E9 测试中加强，没有删除失败用例或减少场景。

资金评估实现升级为 `refund-v2` / Policy 2；原契约规则版本、旧 Manifest、旧运行封存和原始需求不覆盖。严格 gate 使用 `e10-gate-2`，比较 gate 为 `e10-compare-gate-1`。API、CLI 与中文界面展示同一后端严格 gate、业务结论及运行层环境原因；Finding 区分契约规则版本与 Evaluator 版本。十项审查问题均纳入最终核心回归，不用定点测试取代完整实际服务验收。

| E10 核验范围 | 本轮实际证据 | 当前状态与限制 |
| --- | --- | --- |
| REQ01 契约/schema/预检 | [pytest/JUnit](publication-privacy.md#验收证据)、[迁移](publication-privacy.md#验收证据)、[浏览器 schema 错误](publication-privacy.md#验收证据) | 核心通过；旧契约不可覆盖，未知真实产品未接入 |
| REQ02 隔离与 reset | [访问范围](publication-privacy.md#验收证据)、[生命周期](publication-privacy.md#验收证据)、[清理](publication-privacy.md#验收证据) | 核心通过；同业务 ID 不串 run/project，删除不承诺跨服务原子性 |
| REQ03 独立证据 | [调用链](publication-privacy.md#验收证据)、[fixed20](publication-privacy.md#验收证据) | 核心通过；provider 独立服务和持久账本，无真实资金 |
| REQ04 四态/归因 | [fixed20](publication-privacy.md#验收证据)、[缺 fixture](publication-privacy.md#验收证据)、[346 项结果](publication-privacy.md#验收证据) | 核心通过；缺依赖、非法类型、取消/预算不得假通过 |
| REQ05 故障 | [buggy 故障](publication-privacy.md#验收证据)、[fixed20](publication-privacy.md#验收证据) | 六种实际命中通过；提交后超时有 provider 提交证据 |
| REQ06 并发 | [fixed20 runtime](publication-privacy.md#验收证据) | 三组实际动作重叠与 PUT barrier 同步通过；S19 不预设胜者 |
| REQ07 重放/比较 | [10+10](publication-privacy.md#验收证据)、[全部20场景 input](publication-privacy.md#验收证据)、[新规则漂移反证](publication-privacy.md#验收证据) | 核心通过；新代码响应/账本 ID 不复用，源 history 不变；规则漂移不可称仅修 PUT |
| REQ08 混合角色边界 | [JUnit](publication-privacy.md#验收证据)、[综合结果](publication-privacy.md#验收证据) | 规则模式/离线协议替身通过；真实模型实验未执行，未证明 AI 增量 |
| REQ09 UI | [27 控制台](publication-privacy.md#验收证据)、[5 登录](publication-privacy.md#验收证据)、[2 重启](publication-privacy.md#验收证据)、[文案修正后复验](publication-privacy.md#验收证据)、[真实viewport复核](publication-privacy.md#验收证据) | 主流程及展示修正复验通过；后续锁检查PATH失败另记并已独立补检，不称前端整条流水线退出0 |
| REQ10 CLI/CI gate | [四种退出码](publication-privacy.md#验收证据)、[完整严格套件](publication-privacy.md#验收证据)、[UI/API/CLI对照](publication-privacy.md#验收证据) | 本机通过；外部 GitHub runner 未触发 |
| REQ11 安全/恢复 | [346 项结果](publication-privacy.md#验收证据)、[急停](publication-privacy.md#验收证据)、[最终导出扫描](publication-privacy.md#验收证据)、[重启](publication-privacy.md#验收证据) | 核心通过；共享 OS/数据库账号，不是敌对租户或公网安全认证 |
| REQ12 交付/复用 | [干净安装](publication-privacy.md#验收证据)、[第二 buggy](publication-privacy.md#验收证据)/[fixed](publication-privacy.md#验收证据)、[清理](publication-privacy.md#验收证据) | 核心通过；第二示例各62个RPC wire、17次notes.issue，仅S01—S10；实际 pnpm/声明版本有差异 |

本轮完整命令为 `.venv/bin/python -m scripts.clean_e9 --online --evidence docs/evidence/e10-final`，实际346 passed、0 failed/errors/skipped、1 warning、220.07秒。其源环境保护字段核对路径存在性/元数据，不是逐字节数据库证明。`e10-frontend-final --targeted` 实际8 passed、1 warning、53.09秒，27控制台/5登录/2重启及构建/类型/静态/格式通过；随后因隔离shell PATH缺uv，lock-python未执行成功、流水线退出2，见 [原日志](publication-privacy.md#验收证据)。改用uv绝对路径的 [独立后检](publication-privacy.md#验收证据) 完成双锁、许可、秘密扫描，四项均退出0；不把两条结果合并为第二条流水线退出0。8项已有测试不重复增加到346。

最后 [两项真实390×844视觉复核](publication-privacy.md#验收证据) 使用新页面/禁用GPU，四张截图消除resize采集残影；[清理](publication-privacy.md#验收证据) 记录启动器退出0及六端口实际bind成功。全部必要检查现已成功执行，最终状态以发布检查表为准。真实客户试点、生产访问/部署、市场验证、真实模型、外部CI、其他浏览器/平台及正式安全/WCAG审计未执行。
