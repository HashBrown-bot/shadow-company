# 实施决策

## D001 E2 范围与初始仓库

2026-10-06。目录起始只有 V2 Word 和提示词，无项目指令或源码。建立本地 Git（无提交、无远程）、AGENTS.md 和进度文件。只交付 E2；独立 Worker 与两示例服务为可运行边界，不实现 E3 业务或制造假结果。

## D002 技术栈与锁定

使用 Python 3.12、FastAPI 0.142.2、Pydantic 2.13.5、SQLAlchemy 2.1.3、Alembic 1.20.0、psycopg 3.3.6，依赖与传递依赖写入 uv.lock。前端 Next.js 16.3.8、React 19.3.0、TypeScript 5.9.3，使用 pnpm 11.19.0 与 pnpm-lock.yaml。实际 Node 为 24.19.0。

兼容性核对：[Next.js 官方 Node 要求](https://github.com/vercel/next.js/blob/canary/docs/01-app/02-guides/upgrading/version-16.mdx)、[FastAPI 官方依赖说明](https://fastapi.tiangolo.com/release-notes/)。版本可安装性读取 PyPI/npm 官方元数据，兼容性最终用安装、生产构建、类型检查和实际测试验证。未使用系统 Python 3.9。

## D003 无 Docker 的真实 PostgreSQL 验收

本机无 Docker、psql 或 PostgreSQL，因此提供等价本地启动器：`embedded-postgres@18.4.0-beta.17` 只负责下载的真实 PostgreSQL 18.4 二进制生命周期，不以 SQLite 或内存假库替代。该 npm 包发布标签含 beta，仅作本地开发依赖；应用连接标准 PostgreSQL，亦可配置已安装的 PostgreSQL 18。

本地数据仅写入 `.local/postgres`，不安装系统服务或创建 OS 用户。仅 loopback trust，不含实际数据库密码。验收测试创建随机命名的独立临时数据库，完成后删除，不清空开发数据库。代码不提供生产部署。

首次默认沙箱启动因 macOS 共享内存权限受限失败，本地 TCP 连接也被沙箱限制。按已有权限流程在授权执行环境重跑，记录真实结果。网络安装同样使用授权流程。

## D004 pnpm 11 构建策略

旧 `onlyBuiltDependencies` 配置未生效，首次安装退出 1。依据 [pnpm 构建配置](https://pnpm.io/settings/build#allowbuilds) 改为明确的 allowBuilds，仅批准本地 PostgreSQL 平台包符号链接初始化与 sharp。pnpm 自动写入的待决配置导致一次重复 YAML key，随后移除重复项，锁定安装成功。未关闭全局脚本保护。

## D005 配置支持范围

实现附录 B 全部字段，禁止未注册规则和任意执行表达式。当前 schema 0.2 仅开放 realtime/event_compressed、rule actor、disabled LLM，以及附录 B 的 commit_then_timeout 配置形状；故障执行在 E5。controlled 将在相关系统声明可控时钟且实现通过后才开放。货币支持 CNY/USD/EUR/JPY，其他币种清晰拒绝。不同责任范围/适配器须新增版本化 schema，不能静默补齐动作。

## D006 不可变证据与后续删除

契约、事件、原始观测、Manifest 在数据库层禁止普通 UPDATE/DELETE，保障历史引用和原始证据。E3 reset 和 E9 保留期/项目删除需要单独设计受控清理路径和 provenance 审计；E2 没有声称完成 reset 或数据删除。运行状态默认 inconclusive，业务执行未实现时返回 501。

## D007 最小 Web

采用 Next.js 工程控制台，仅显示真实后端响应。没有完整 Dashboard 或假业务指标。客户端同源固定代理减少跨端口配置，API_BASE_URL 只用于服务端。样例 YAML 来自本地原始附录 B 文件，明确标注示例。E8 再扩展业务页面。

## D008 启动与浏览器验证中的修正

实际浏览器发现同源 POST 返回 403：Next.js 对 nextUrl 主机名的归一化与浏览器 Origin 不同。改为核对真实 HTTP Host、明确的 loopback 主机白名单与同源 Origin；正向项目创建和跨来源拒绝均由浏览器测试验证。

macOS 系统代理使启动器的 loopback 页面探测超时，显式使用无代理的本地探测器修复。开发与生产构建均明确使用 Webpack；未将诊断期间切换构建器解释为已证明的 Turbopack 缺陷。Next 自动生成的 apps/web/AGENTS.md 和 CLAUDE.md 已读取并保留，前端变更核对其捆绑版本文档。

会话中断后可能留下已分离的子进程，因此启动前检测端口，发现冲突即退出，不能误把旧服务健康当新启动成功。端口探测设置 SO_REUSEADDR，避免将正常关闭后的 TIME_WAIT 误报为监听冲突。普通 SIGINT/SIGTERM 会按逆序停止子进程；SIGKILL 无法保证清理，应先核实残留进程身份。

重复启动检查 PostgreSQL PG_VERSION，已初始化的数据不重新 initdb。完整验收器验证停止后所有端口释放及再启动数据保留；浏览器测试使用新建临时库，不清空开发库。

## D009 错误脱敏与辅助模块

除移除验证错误 input/context 外，额外改写 union_tag_invalid 消息，防止未注册规则 ID 被作为秘密原样回显。配置和 Manifest 都有规范内容哈希测试。辅助 Python 工具以 `python -m scripts...` 从仓库根调用，兼容当前工作区运行时的 editable-import 行为。

## D010 用户授权进入 E3 与 E2 复核

2026-10-07 记录。用户明确将当前阶段从 E2 改为 E3；仅修改 AGENTS 对应一行，其他规则保持。进入 E3 前读取原始 Word、提示词 E1/E3、覆盖表、进度、决策和代码。仓库仍无提交、所有文件未跟踪，因此空 git diff 不代表代码为空；保留原文件，并在 `.local/e3-baseline` 保存实施前源码用于逐文件核对。

修改业务前实际复跑 E2：89 后端测试、10 浏览器检查、迁移、服务停止/重启与持久化通过，无阻碍 E3 的缺项。复核产物单独放在 `docs/evidence/e2-recheck`，没有覆盖 E2 原验收证据。两份原需求文件内容哈希未变。

## D011 E3 的闭环结果与后续规则边界

E3 只激活明确标记的 fixed 示例，标准运行只接受 S01/S02、CNY、gt 200000 和部分退款政策；其他产品版本/凭据、语义路径与政策不静默兼容。完整 buggy 缺陷样例及其规则/故障验收留待 E4/E5，不能把 E3 正常路径视为 E1 全部要求交付。

完整规则实现属于 E4，所以 E3 报告单列 `e3_flow`，从独立账本、产品查询和已验签回调核验选定场景。完整 `refund_core_20` 的 run verdict 与 gate 保持 inconclusive，列出 S03—S20、规则与重放未完成。窄范围场景关联在读取报告时计算，不将内部标签写成未注册规则 ID，不替换现有 CheckResult/RuleId 契约。JSON 报告 schema 为 `e3-report-1`，不是 E4 的完整 JSON/HTML 报告。

## D012 独立服务持久化与 provider 职责

PUT/provider 各自是独立 FastAPI OS 进程，分别使用 `refund_put` 与 `payment_provider` schema，同一 PostgreSQL 实例由统一迁移管理。两者不读取对方或平台预期表。共用模块仅处理 wire types、HMAC、HTTP 和脱敏，不共享审批、余额算法或 pass/fail 标记。

provider 真实保存每次成功执行和幂等键，不代替 PUT 检查审批与累计可退余额。PUT 负责 gt 阈值、版本审批快照、余额锁和稳定指令幂等键。schema 隔离是持久化范围，未声称数据库账号或 OS 隔离；完整最小权限部署在 E9。

## D013 示例凭据与出站策略

不读取真实产品凭据。启动器随机生成示例密钥，分角色并按进程所需写入 0600 文件；PUT 没有 provider_reader/provider_admin 密钥。每个令牌绑定 project_id 与 run_id，平台数据库只存 secret:// 引用。收款方以稳定摘要保留审批比较语义；敏感字段和已知凭据的任意文本回显脱敏。

允许范围由操作员环境 `EXAMPLE_OUTBOUND_POLICY` 指定完整 origin 和固定 IP 集，不能从契约扩展；所有 DNS 结果需被允许，HTTP 连接固定到已验证 IP，拒绝重定向/代理/元数据/路径逃逸。默认仅批准本机 8000/8001/8002。容器固定 IP 配置有协议测试，未实际部署容器；真实 staging 整体未开放。为确保回调与策略一致，E3 一键启动明确拒绝自定义 API 端口/主机，替代 E2 更宽的配置范围。

## D014 reset 的受控删除与 provenance

原追加证据约束保留。reset 必须先通过远端 PUT/provider 清理，再在事务内保存审计记录及各类证据哈希，由匹配项目/run 的 reset_id 开启受控删除。保留契约、输入哈希、请求键及 run 墓碑；同一请求键不能在 reset 后创建新支付运行。reset 不是普通覆盖输入的接口。

跨三个服务不能用单个数据库事务完成，远端失败时标记 reset_incomplete、保留证据并允许恢复后重试。运行中 reset 拒绝；取消在途与崩溃恢复留待 E5。第一次真实回归发现触发器在契约表上解析不存在的 run_id，改为先分表判断再引用字段；原失败输出保留。

## D015 Webhook 与 Worker 的交付范围

provider 先提交独立账本及 outbox，再由真实 HTTP 投递 PUT 与平台。平台验签 HMAC、五分钟时间窗口、binding/run 范围与重复事件内容，观测和收据原子提交后才确认。存储失败返回 503、不留成功收据；重复同内容幂等，不同内容 409。

Worker 单次认领 PostgreSQL 作业、串行执行、记录状态和预算；不对已租赁的中断作业自动重领，不在未知支付结果上无条件重试。E5 再实现完整租约恢复、取消、并发 barrier 和故障命中。当前没有把先成功的部分步骤概括成未完成整轮通过。

## D016 依赖与可复跑交付

E3 出站使用 Python 标准库，未新增运行依赖；Python/Node 现有精确锁文件保持并离线复验。沿用本机真实 PostgreSQL 18.4。`verify_e3` 创建临时数据库，验证独立进程、业务、浏览器、PostgreSQL 与全部服务重启、reset、构建、静态检查及锁文件，然后清理自身服务/临时库。`demo_e3` 是实际 API 演示助手，不是 E9 simctl。

## D017 最终审阅与生成缓存处理

最终审阅发现收款方关联的布尔条件被后续条件覆盖，已改为合并条件，并增加从真实观测派生的收款方/命名空间/指令/金额类型反证及畸形账本测试。原始证据不修正，缺字段或格式不完整保持 inconclusive，存在完整反证则 fail。

一轮 typecheck 因 `.next` 下相同内容、带 ` 2` 后缀的生成类型副本冲突失败。保留失败日志和本地副本，没有归因未经验证的外部原因。验收器改为先停止开发服务，再清理可再生 .next、生产构建、类型检查，避免开发/构建同时写入生成目录。最终综合验收退出 0，122 后端测试与 10 浏览器检查通过。

## D018 用户授权 E4 与 E3 实际复核

2026-10-07。用户明确授权只进入 E4，并把 AGENTS 当前阶段改为 E4，其余规则有效。先读 AGENTS、进度、覆盖表、决策、V2 Word 与 E1/E4，再检查源码和 diff。仓库依旧全为未跟踪文件；保存 `.local/e4-baseline` 与内容哈希，不能用空 diff 认定没有用户修改。原始需求不改写。

E4 开发前复跑 E3 综合验收：122 后端测试、10 浏览器检查、真实 PostgreSQL 与服务重启、构建、静态与锁文件检查通过，无阻碍 E4 的缺项。证据独立保存于 `docs/evidence/e3-recheck`。默认沙箱禁止本地端口，使用已授权的本机执行环境；权限失败不算测试通过。

## D019 兼容入口与必要模型扩展

E3 的 S01/S02 兼容入口保留，`suite_scope=e4_core_10` 明确选择 E4；报告 schema 为 e4-report-1。E4 要求全部五条注册规则，不能通过省略规则绕过检查。契约 schema 0.2 和旧内容哈希保持，新增 `local.e4.yaml`，未改附录 B/E3 配置。E4 本机示例采用 1 秒真实观察窗口；旧文件 30 秒不变。

迁移 0003_e4 追加客户归属、PUT 行为、provider 执行时版本/审批上下文与评估快照。S04 用 PUT 的 PATCH 改金额产生新版本，fixed 清除旧批准、buggy 保留；S10 新增两个独立示例客户身份，服务按 owner_id 检查读取权限。身份/所有权规则属于已审阅的 http_refund_v1-access-1；不是任意 staging 权限模型。E3 的“只接受 fixed”负向测试改为未审阅版本，新增真实 buggy 验收；PUT 仍没有独立账本读取密钥。

## D020 规则独立性与语义范围

新评估器只接收 Policy、实际来源观测和完成/时间上下文；不导入 simulator/PUT，不接收场景答案或版本选择。报告层的计划动作匹配仅判断覆盖是否完整，不参与资金/审批事实判定。provider 返回自身初始支付余额，不能用 seed 中的预期余额替代已采集的独立证据。

REFUND_001 按指令统计唯一成功 entry_id；REFUND_002 按支付和币种累加成功金额，失败尝试不计，环境默认 currency 不意味着跨币种相加。APPROVAL_001 交叉验证 provider 执行上下文、实际审批、版本和操作者权限。STATE_001 除终态回退，也负责声明/执行矛盾及状态可见性的权限约束，以覆盖用户要求的 success 无执行与 S10；access_checks 提供额外的客户权限明细，不引入未注册 RuleId。

TIME_001 的期限前不失败；期限后观察到仍等待、且证据完整才失败。晚到的终态观测不能倒推真实完成时间，保持 inconclusive。已接受执行请求但未进入任何终态也不能因没看到 execution_pending 就规避完成性要求。缺查询、账本、必要回调、身份或未完成运行不能通过；N/A 明确给出契约条件。

## D021 冲突、持久结果与去重

所有认证且属于该 run 的业务观测保持原值。不同内容的同 ID 回调追加保存并返回 409；已验签、范围有效、JSON 结构合法但业务值违反 Callback schema 的观测仍保存，再返回 422。拒绝协议输入不能消除反证。账本同 ID 内容冲突、后续完整快照遗漏旧条目、回调与账本冲突都保留引用；不采用最后写入覆盖。

评估快照追加保存；报告每次先从当前观测推导，再复用匹配的快照。run 查询刷新当前 E4 verdict；历史 completed 不保证继续通过。Finding 按规则/业务对象/已证实外部表现去重，同一支付超额关联的检查合并，保留稳定 Finding ID、合并证据与失败链。新的结果更新 Finding 索引，旧评估中的原始结果保留。报告只展示当前评估的发现，不把历史证据不足累计成新的独立缺陷。

## D022 报告、范围与交付边界

JSON/HTML 来自同一后端结果；HTML 使用静态转义、CSP 和证据锚点，无脚本或外部资源。实际视觉检查发现初版窄屏表格虽然未溢出却过度折字，改为可横向滚动的固定列宽和短证据编号，再进行浏览器验证。检查失败/不确定优先排列；没有 readiness 分数、模拟客户指标或空成功占位。

`selected_gate` 是 E4 选定场景，完整 refund_core_20 gate 保留未验证 S11—S20。E4 的串行重复调用与 PUT 缺陷选择不是 E5 的提交后丢失响应、故障命中、barrier 或恢复；本次未实现和未宣称 E5—E10。原 E3 JSON 与报告仍可复跑。未新增依赖，双锁文件保持。

## D023 E4 实际失败与修复

首次回归 1 failed / 121 passed：E3 原凭据集合断言未包含新增客户身份。更新精确集合并继续断言 PUT 无账本读取/管理密钥。规则测试发现缺少最终产品查询被误判为状态失败，改为证据不足；另发现非法审批结构和布尔业务版本未阻断通过，补齐原始字段验证。失败日志留在 E4 evidence，未降低断言、跳过失败或硬编码结果。

审阅进一步补充晚到终态的保守时间判定、报告与持久 Finding ID 一致、新证据重算、缺少故意重复请求的覆盖校验、已验签非法业务回调保留及相关反证测试。一次本机测试调用因自动审批服务额度异常没有执行，用户要求继续后同一授权范围重新执行成功；没有绕过自动审批或把未执行命令记为通过。最终命令、结果和限制见 E4 验收记录。

## D024 用户授权 E5 与 E4 前置复核

2026-10-07（Asia/Shanghai）。用户明确授权进入 E5，仅改 AGENTS 的当前阶段，其他规则保持。读取 AGENTS、进度、覆盖、决策、原始 V2 Word 和 E1/E5、源码与 diff。仓库仍无提交、文件未跟踪；保存 `.local/e5-baseline` 原文件及 SHA-256，未把空 diff 当作没有用户内容。

复跑 E4 综合验收：187 后端测试、15 浏览器检查、独立服务与 PostgreSQL 停止重启、构建/类型/静态/双锁/扫描通过。证据另存 `docs/evidence/e4-recheck`。沙箱最初禁止 loopback 绑定，按授权流程在本机运行；权限失败不记测试通过。没有阻碍 E5 的前置缺项。

## D025 持久事件与租约恢复

新增迁移 0004_e5，不改旧迁移。事件按 simulation_time/priority/ingress_sequence/event_id 排序，使用本 run 的稳定 ID；并发兄弟共享前驱。单独 event_dispatches 保存 pending/inflight/done/unknown/cancelled，journal 追加保存检查点与真实顺序。故意重复业务动作分配不同事件 ID。

采用 3 秒租约、0.5 秒续期、owner/epoch fencing 和每 run 的 PostgreSQL 会话锁。进程仍在执行时，即使租约过期也不能由第二个 Worker 接管并行资金请求；进程退出释放锁。派发前和取消在同一作业行锁上线性化。epoch 过期写入被拒绝。

事件恢复保守处理：执行类先读 PUT 和独立账本，已证实成功/终止才确认；不能确认则 unknown 并停止，不发第二次执行。仅有动作 end_time 不足以证明操作已确认。旧 E3/E4 串行作业没有持久事件，不安全地自动重跑会重复资金，因此中断后显式未知，正常兼容入口继续回归。

## D026 在依赖边界注入故障

故障控制线协议集中于 transport/controls，但每个服务只读写自己的 schema，不共享资金算法或答案。S11 在 ledger 写入前截断 HTTP 响应连接，客户端发生真实连接读取失败；精确范围是连接中断，不冒充 DNS/TCP 建连失败。S12 必须退出 ledger 成功事务后才扣住响应头，客户端 350ms 读取超时，PUT 自己查询或重试；不在 Adapter 伪造超时。

每个计划保存 ID、命令、尝试、次数、持续时间，实际命中写入服务审计。S13 保存原始重复投递结果；S14 先保存真实处理中事件，再提交成功，故障只改变投递顺序。版本 1 标签本身不能证明历史事件，Evaluator 还核验正常成功回调和发生时间。S15 真实 429 与有界重试；S18 是审批身份不可用 423，不把普通服务 5xx 当作符合产品规范的成功。

schema 0.2 的旧输入和内容哈希不变，只增加明确故障字面值及 boundary 校验；新 local.e5.yaml 明列六项。运行输入/事件与 `e5-schedule-1` Manifest 固定本次计划，不覆盖历史依赖。该 Manifest 用于恢复追溯，不宣称 E6 fixture 重放完成。

## D027 并发与真实 Worker 中断

平台 ThreadPoolExecutor/Barrier 与 PUT 入口 Barrier 双重同步，双方 HTTP 已进入后才释放。保存每个 Action 的真实开始结束及单调数据库顺序，服务保存 arrival/release。S17 buggy 额外同步余额读取点，故障仍只在 PUT；fixed 在产品锁内读取最新余额。S19 接受任一合法胜出顺序，不伪造固定顺序。并发不依赖随机 sleep；固定等待仅用于真实观察、轮询和有界限流恢复。

Worker 采用监督进程与独立作业子进程。S20 在两个持久位置调用 os._exit(86)，确实不运行 finally；监督器启动新 PID，租约到期后核验恢复。另一个集成测试在 provider 已提交且 HTTP 在途时向已验证的该 run Worker PID 发 SIGKILL。恢复测试不是 E6 input replay，也不承诺同时杀死 PUT/provider 后的任意外部产品恢复。

## D028 取消、预算与计时口径

取消停止派发新事件，允许已派发动作结束，保留资金后果与证据。停止后最多额外 3 秒只读收集，缺少证据时不确定；不能把取消当成撤回已经执行的退款。派发预算包括事件数、墙钟和并发，PUT 的内部重试上限取配置与 2 的较小值。全部模型预算为 0。

run 墙钟包含中断恢复、观察和收尾；可能超过派发截止，报告明确保留。发生器准备/线程 CPU 与 PUT HTTP 往返分别记录，准备含 barrier 等待，往返含产品依赖等待；不相加推算吞吐量或声称服务器性能。realtime/event_compressed 只控制平台日程，controlled 继续拒绝。

## D029 报告覆盖与 gate 范围

五条业务规则仍只接收政策和原始观测。E5 报告层另核对故障实际命中、barrier 实际重叠、Worker owner/PID/检查点与计划动作数量；这些决定覆盖完整性，不代替资金与审批结论。没有故障证据，即使正常路径规则通过，也不能声称该故障场景通过。

完整 refund_core_20 可以有自己的套件 gate；它不等同 V2 发布验收。HTML 明确使用套件名称，E6—E10 仍未实施。原 E3/E4 的 schema 和兼容入口保留；Web 只更新阶段说明，不扩展 E8 范围。

## D030 实际失败与修复

首轮 14 failed / 173 passed：完成旧 E3/E4 作业的内嵌 JSON 被 SQLAlchemy 识别为绑定参数，错误地标为未完成。改成参数化 JSON；没有弱化业务断言。聚焦检查 1 failed / 8 passed 确认 E5 路径有效及同一旧路径缺陷；随后完整 203 项通过。

最终审阅增加历史回调时间反证、行为开关独立性、重试预算和收尾上限，后端 207 项通过。首次综合验收在浏览器脚本失败：旧断言期待 0003_e4，实际页面已显示正确 0004_e5；更新精确迁移断言后复验。保留失败输出。pytest 默认 fixture 表示包含继承环境的片段，改成不展示进程环境的 repr，并从失败日志移除该 fixture 表示；不读取或打印凭据值。

最终命令、实际结果、限制和未执行项以 E5 验收记录为准。没有新增依赖、空测试、失败跳过或前端 mock 成功。

## D031 用户授权 E6 与前置复核

2026-10-08（Asia/Shanghai）。用户明确授权只执行 E6，将 AGENTS 当前阶段改为 E6，其余规则继续有效。读取原始 V2 Word、E1/E6 提示词、状态/映射/决策和实际源码及 diff，先说明方案后开发。全仓仍未提交；保存 `.local/e6-baseline` 的 311 个文件及哈希，保留已有正确实现与用户内容。

实际复跑 E5：207 后端测试、17 浏览器检查，全部服务/真实 PostgreSQL 停止重启、持久化/reset、构建、静态、双锁与扫描通过。证据单独存入 `evidence/e5-recheck`，没有阻碍 E6 的前置缺项。原始需求、附录 B、旧迁移和旧阶段证据不改写。

## D032 三种重放与快照隔离

history 只 SELECT 已有记录，不调用 PUT、不重算报告、不创建 job。input 在同一 project 中使用新的 run 命名空间；复制输入计划和初始支付快照，生成新的回调 binding，再调用明确目标版本。不跨项目搬运证据。严格布尔字段拒绝 reuse_product_outputs=true 及字符串/数字冒充；没有旧产品响应 fixture 入口。

controlled 与 input 共用真实执行链，但额外要求相同已审阅的环境、规则、预算和控制契约，核验本机服务控制能力。其承诺仅包括初始数据、语义故障、平台排序、回调投递及入口 barrier。不能控制外部时钟、OS、网络或数据库锁胜者；runtime.time_mode=controlled 继续拒绝。E6 提示词中的可控重放按用户要求收窄到实际边界，不推广为任意 staging 确定性。

## D033 两段 Manifest 与内容追溯

新增 0005_e6，保留原契约表及旧迁移。计划 Manifest `e6-replay-1` 保存环境/规则/契约版本与内容哈希、PUT 目标版本、适配器与源码逐文件哈希、进程启动时依赖版本/双锁哈希、seed、初始快照、角色/故障资产、计划调度和边界。仓库无 Git commit 时明确为 null，并用工作树内容哈希追溯，不虚构提交号。

初始业务快照与含本次 binding 的物化 seed 分开哈希；Worker 要求 PUT/provider 初始化响应匹配物化哈希。完成 seal 引用计划哈希，追加实际事件、Action、journal、故障、并发及报告内容和哈希；不 UPDATE 原 Manifest。数据库禁止普通修改/删除资产或封存，仅受审计 reset 清理目标 run。旧 E3/E4/E5 记录缺少当时完整清单，只保留 history，不用当前代码伪造旧版本清单。

## D034 语义 fixture 与反馈策略

角色 fixture 匹配 operation、command_id、role、请求 body 和当前 PUT 可见业务字段/版本；创建允许对象不存在或相同，权限探测允许 200/403/404。需要刻意重复的动作记录 uses，不按旧调用序号投递响应。仅调整存储顺序不改变资产语义或匹配；同语义多个候选歧义时停止。

provider 故障要求实际请求字段、对象、动作及 uncommitted/committed 前置状态，审批离线另要求审批前置状态；上限针对首个符合条件的命中。当前不支持把任意历史 attempt 数当语义，直接拒绝无法映射的配置。实测第二个物理请求才是第一个语义匹配请求，得到 429；先前不匹配请求报告 fixture_mismatch，不能吞成业务失败。

scripted_v1 固定角色输入；retry_if_unsettled_v1 依据新可见状态决定是否重试，记录输入、理由与 skip_settled，标记 input_not_identical。省略场景必需输入时 verdict 保持 inconclusive。fixture 缺失或匹配失败归为 environment_error；不产生伪造的 product_defect，也不补造产品响应。

## D035 修复归因必须依据新调用与新证据

PUT 服务端记录真实 business_call、实际 variant/build；provider 记录 execution_received 并生成本轮 ledger/outbox。Worker 核验 capabilities、版本响应头与冻结代码版本，比较器核验资产/封存/观测完整性及新 run 的独立 ID。history 的零调用由 SafeHTTP 间谍和数据库行数反证验证。

compare 把 PUT 版本/build 与契约语义、规则、环境、provider、适配器、平台、依赖、数据库、seed、快照、fixture、计划输入调度和控制边界分别比较。去除新 binding 和 PUT 版本选择后计算输入调度哈希；条件变化阻止直接归因于 PUT。源 fail、目标 completed/pass、旧失败逐项转 pass、条件可比且新调用/证据可信才标记 repair_verified。

S12 fixed 可在提交后超时改为查询确认，provider 执行从 2 次降为 1 次；报告记为合法产品路径变化，不能强迫复用旧调用轨迹。金额/状态结论仍来自新独立账本和观测，Evaluator 不读取缺陷开关。示例 buggy/fixed 是同一受控服务的两个实际行为版本，build 相同；没有声称独立客户二进制或任意客户端支持。

## D036 E6 验证与实际修复

首轮单项 1 failed / 11 deselected，fixed verdict 因故障覆盖为 inconclusive：新语义故障含 recipient，而保存观测已将其脱敏，原始计划不能直接比较。统一计划/证据的脱敏规范后复验通过，保留实际命中与资金断言。随后 21 项专项通过；补充 controlled 条件变化反证、进程启动版本冻结和计划调度比较后，最终综合 229 项通过，0 失败/跳过。

一次综合命令因自动审批服务额度限制未执行，用户要求继续后同一命令成功；不绕过审批、不将此视为测试成功或产品失败。20 次正式重复批次全部满足原断言，不降低标准、不隐藏失败；每次先保存报告、Manifest、比较再断言。旧历史逐字节规范哈希一致。24 项浏览器检查、真实 PostgreSQL/全部服务重启、迁移、构建/静态/双锁/扫描通过；实际输出与未执行项见 E6 验收记录。

仅增加 E6 最小重放和比较入口，未实现 E8 完整 UI 或 E9 CLI；无新增依赖与模型调用。E6 验收完成后停止，不自动进入 E7—E10。


## D037 E7 授权、原始文件与 E6 复核

用户明确授权只进入 E7，并允许可选模型适配器作为“不引入模型依赖”的阶段性例外，核心套件仍不能依赖外部模型。AGENTS 只改当前阶段一行；2026-10-11 续接时用户提供的替代项目指令同样限定 E7。原请求中的凭据、数据与服务授权约束继续有效，未授权实际模型服务。

先读 AGENTS、状态/覆盖/决策、V2 Word 和 E1/E7、代码与 diff，并说明方案。仓库仍无提交，全文件未跟踪；保存 `.local/e7-baseline` 的 457 个文件/哈希，不能把空 diff 当作无用户修改。实际复核 E6：229 后端测试、24 浏览器检查、PostgreSQL/全部服务重启、构建/类型/静态/双锁/扫描通过，证据另存 `evidence/e6-recheck`，没有阻碍本阶段的前置缺项。

## D038 独立 E7 策略而不改变旧业务契约

现有 v0.2 契约只声明结构化 API 和 rule actors。为保持旧序列化/哈希，不向它加入默认模型字段；新增 run 级 `e7-actors-1`，通过 `e7_core_20` 显式选择并在 Manifest 与 actor_policies 同时冻结。旧 v0.2 llm 继续关闭。重放继承 E7 策略，compare 将策略作为独立条件，不因角色输入变化误判 PUT 修复。

本机 PUT 没有自然语言入口，两侧真实运行均使用规则角色且记录回退原因。没有构造缺乏业务意义的聊天，也没有把协议替身另装成假产品或伪造 AI 增量。模糊表达、遗漏材料和改口的真实产品场景未执行。

## D039 模型接口、观察与授权边界

实现 provider 无关可选 ModelAdapter 和明确标记的 ProtocolTestAdapter，无新增 SDK 或网络供应商依赖。当前只注册离线替身；真实服务、数据上传与安全凭据解析在获得授权后再接入，并先遵循环境凭据技能流程。用户已明确允许无授权凭据时完成离线功能，因此不为离线工作索取/检查真实密钥、不创建账号或收费服务。

observation 从当前身份自己的成功业务读取投影，限制 project/run、身份、路径、对象和字段；不传 provider、管理观测、其他身份、拒绝响应体、头或收款信息。原始非法业务值仍保存。产品文本为不可信数据；严格结构化动作只允许角色/对象授权范围内的 read_refund、条件允许的 send_message 和有界 wait，禁止模型改规则、直接执行资金或查询秘密。低权限业务测试由原规则场景真实向 PUT 发请求，不能用平台拦截代替。

## D040 持久预算、审计与未知调用

新增 0006_e7，不改旧迁移。actor_policies、actor_calls、实验/成员与 finding_reviews 使用作用域外键和不可变约束；允许受审计 reset 清理角色数据，同时保留实验成员指向已 reset run 的墓碑。报告在策略/调用/封存证据缺失时不通过。

复用租约/作业行锁预占调用量和保守用量；事件检查不能重置模型计数。返回后继续核验用量、取消和动作权限。超限停止为 model_budget_exhausted；有限修正耗尽归 actor_error，错误文本不直接落盘，以免供应商异常回显秘密。未知调用消耗预占、不自动重发。每 run 的调用间隔可中断等待，纳入墙钟；没有宣称服务级全局配额。

协议替身记录实际 UTF-8 单位与明确来源，不当作真实模型 token。模型/策略标识、脱敏输入输出、预算和用量留存；实际模型价格未采集。无调用模型费用 0 的来源是未调用服务，基础设施成本未测。

## D041 配对与人工确认口径

实验按每个 seed 新建不可变契约，rule/hybrid 共用产品、环境、规则、快照、调度和预算；实际运行并核验 Manifest、seal、独立证据。源与目标条件不同、缺 run、取消、预算不足或 reset 均使比较不可用。

规则 Finding 不是人工确认的独立根因数。显式人工 review 关联实验成员、当前产品 Finding 和证据哈希，以 root_cause_id 分组跨 seed 去重；误报和耗时只能来自已采集输入。无复核显示 null/未测，部分复核显示数量。测试中的合成 reviewer/time 只验证 API，不计入演示或实验结论。报告不含模型满意度、购买意愿或真实市场预测，始终标记真实模型未运行、AI 增量未证明。


## D042 E7 实测过程与收尾修正

35 项最初协议测试通过；续接后的首次真实服务测试在 PostgreSQL 尚处启动阶段时发起，6 项建库 fixture errors，未执行到业务。保留 `pytest-live-first.txt`，等数据库输出就绪后同样测试 6 passed / 33.51 秒。无失败跳过或 SQLite 回退。

首轮综合退出 0：274 后端、31 浏览器、真实 PostgreSQL/服务重启、构建/静态/双锁/扫描通过。收尾审阅补充审计深度/键名清理、决策后派发前取消与旧 owner 围栏。新增审计测试先失败（缺深度截断），修正后单项通过，原失败输出保留；没有降低业务断言。最终完整复验结果以 E7 验收记录为准。

最终综合从 2026-10-11 01:08:12（America/Los_Angeles）开始，退出 0：277 后端（42 离线协议 + 6 E7 本机服务 + 229 原回归）、31 浏览器、S01—S20 关闭模型、E6 10+10、PostgreSQL 与服务重启、构建/双锁/扫描全部通过。协议 probe 的 5 条审计在 PostgreSQL 重启后完全一致，业务 verdict 仍 inconclusive，随后审计 reset 清理。真实模型未运行，所有实际产品实验的模型调用为 0；人工独立缺陷、误报和确认时间未测，不声称 AI 增量。E7 离线工程验收后停止，不进入 E8。

## D043 E8 授权、基线与前置复核

2026-10-11（America/Los_Angeles）。用户明确授权仅进入 E8，把 AGENTS 的“当前只执行”改为 E8；其他项目规则不变，不自动进入 E9。先核对 AGENTS、实施进度、需求覆盖、决策、V2 Word、提示词 E1/E8、实际代码及 diff。仓库全为未跟踪文件，保存 `.local/e8-baseline` 的 685 文件副本与 SHA-256，保留原需求、旧证据和用户内容。

先复跑 E7 综合验收，277 后端、31 浏览器、PostgreSQL 与全部服务重启、构建/静态/双锁/扫描均通过，结果另存 `docs/evidence/e7-recheck`。第一次端口绑定被沙箱拒绝，未执行测试；获准后按原要求重跑，失败与重试日志分别保留。真实模型服务、自然语言 PUT 与 AI 增量实验明确未执行，不是本阶段中文界面的前置阻碍。

## D044 同一事实源上的 E8 查询与页面

复用既有 Project、Configuration、preflight、Run、job、report、Finding、history 与 input replay。`services/api/console.py` 只添加目录、分页列表、Worker 租约/进度、当前 Finding 证据与四来源时间线等读取投影，不增加另一套运行状态、不修改资金/审批规则、不新增迁移或依赖。终态列表与详情从原报告器核验当前证据，不能继续展示证据丢失前的缓存通过。

运行配置保存为新的不可变契约，保留源契约与所有旧 run 依赖。目标版本重放复制源输入条件，仅改变产品版本；仍调用原预检与 input replay API，明确 `reuse_product_outputs=false`，新旧差异、路径变化和修复确认由后端比较器提供。协议/规则版本不因 UI 阶段改为虚构的新版本。

## D045 恢复、分页和异常状态

当前项目、视图、run、Finding、比较源保存在 URL；刷新后重新查询 PostgreSQL。组件仅保留表单、分页与网络请求状态；项目切换会取消旧读取，连接失败会撤下当前查询结果并显示真实错误，不回退假数据。项目/契约/run/Finding/检查/证据/时间线由服务器分页；固定大小的场景范围与比较维度在界面分段。

Worker 状态依据数据库租约截止与数据库时间；过期显示失联，queued 显示等待领取，不把缺少 Worker 响应当作业务失败。取消、预算终止、证据不足、404、配置/版本错误和 401/403 分别反馈。页面通过现有本机同源代理访问 API，增加严格限定的 PUT/POST/GET 路由，不开放 reset、任意管理接口或任意代理目标。

## D046 界面与验收边界

中文工程控制台优先显示关键失败、证据缺失、覆盖与重放；四态有文字、符号与色彩。因果时间线区分角色、产品、provider、evaluator，按实际墙钟排列，但仅存储的 event/causation/evidence_refs 表达因果，不把时间相邻伪称因果关系。无关联观测明确保留为空。

键盘使用原生表单、链接、按钮、details 和表格滚动容器；导航移交标题焦点，分页保留焦点，提供跳过导航、可见焦点与 reduced-motion。示例产品和报告明确标注；禁用 controlled 时钟和真实模型，说明已控制与未控制边界及预算终止语义。

异常验收在专属真实 PostgreSQL 库进行：暂停验收器持有的 Worker 进程组令租约真实过期；调用取消 API；带 reset 审计删除单个测试 run 的 provider_ledger 观测，验证通过结论撤回。浏览器加载测试延迟真实响应，连接测试中止网络请求，403 由真实同源防护返回，均不注入伪造成功响应。403 检查不等同 E9 登录/IAM 验收。

## D047 E8 实际失败修复与最终验收

首轮完整后端 282 passed；浏览器加载检查发生 `Route is already handled`，将请求延迟改为一次性拦截并等待真实请求恢复。第二轮前 18 项通过，Chrome 覆盖测试注入 Origin，改为工具向真实 BFF 请求并原样转交 403，继续断言没有写入；没有替换业务数据或降低授权检查。两轮失败保留于 `e8-attempt1`、`e8-attempt2`。

收尾修正翻页加载后的焦点恢复、越界空页的总数、辅助文字对比度，并验证缺少 provider_ledger 的 YAML 在页面显示真实 422 字段路径。旧报告中的“E8 未完成”改为当前“E9—E10 未完成”；业务评估规则与旧契约格式不变，真实模型仍未运行。

最终 `.venv/bin/python -m scripts.verify_e8` 退出 0，`docs/evidence/e8` 保存 282 passed（167.81 秒、0 failed/0 skipped、1 个既有弃用 warning）、Chrome 24+2 passed、真实 PostgreSQL 与全部服务重启、源/目标历史持久化及构建/类型/静态/格式/双锁/扫描结果。浏览器实际创建项目、buggy S12 失败、查看独立账本、fixed input replay 通过；后端确认修复且路径由 2 次 provider 调用变为 1 次。25 张截图与报告可复查。仅完成 E8，E9—E10 未开展；详细限制见 `acceptance-e8.md`。

## D048 E9 授权、基线和 E8 复核

2026-10-11（America/Los_Angeles），用户明确授权只进入 E9，并要求更新 AGENTS 的当前阶段，其他规则继续有效。先读 AGENTS、实施进度、需求覆盖、决策、原 V2 Word 和提示词 E1/E9、实际代码及 diff；说明方案后开发。仓库仍无提交、全文件未跟踪，保存 `.local/e9-baseline` 的 1133 文件和 SHA-256，不以空 diff 推断没有用户修改。原需求和旧验收产物保留。

前置复核真实启动 E8：282 后端测试、24+2 浏览器/重启检查、真实 PostgreSQL、构建/类型/静态/双锁/扫描通过，证据在 `evidence/e8-recheck`。沙箱首次拒绝绑定端口，获准后重试；未执行不记为通过。未发现阻碍 E9 的前置缺项。没有真实 staging 授权，使用第二示例；没有连接生产、模型服务或外部发布服务。

## D049 严格 gate 与历史事实分离

新增 `e9-gate-1`，API、simctl 与 CI 使用同一判定。保留原业务报告四态和历史 gate，避免修改旧规则或旧证据来满足 CLI。每条契约必需规则和最低资金/审批规则都需要有适用、通过且带 evidence_refs 的检查，全部 N/A 返回 3。只选 S01 可以业务正确但缺审批适用覆盖，严格 gate 仍不通过；增加 S02 提供实际覆盖。

未完成/取消/预算/证据清理优先为 3；终止的基础设施执行错误为 2；完成且有产品缺陷反证为 1；所选 gate 完整通过为 0。validate/preflight/history 明确各自 gate，不把配置、接入或读取成功称为业务通过。compare 同时要求目标 gate 通过和 repair_verified。没有宽松模式或把检查改成 N/A 的绕过选项。

## D050 本机授权和浏览器会话

新增随机 Bearer、服务器哈希 registry、项目/run/操作权限、到期和撤销，默认失败关闭。工具只签发本地生成的测试访问凭据，不读取真实秘密；registry 和 token 文件限 0600，不打印 bearer。认证覆盖 API，Webhook 使用原独立 HMAC。原 BFF 改为转发用户会话令牌，新增同源登录/退出、HttpOnly、SameSite=Strict、一小时 cookie，不使用共享管理员令牌冒充用户权限。

这解决本机不同访问角色的能力边界，不构成公网 IAM、托管多租户或敌对 OS 用户隔离。所有服务默认 loopback，共享数据库账号保留。没有创建外部账号、SSO 或公网部署，浏览器 Secure cookie/HTTPS 等需在未来授权的部署范围另行设计。

## D051 追加证据、保留期和急停删除

原追加观察继续脱敏并保留非法业务值；新增 private_evidence 保存同一观察的私有协议副本和到期时间，不建立可读取未脱敏凭据的仓库。raw API 额外要求 raw 权限，到期即拒绝。默认私有副本七天、trace 三十天来自不可变契约，物理清理由管理员主动调用 retention。运行中延期并返回未完成，没有擅自创建定时任务。

项目锁与 new_run 的共享锁协调停止/删除，覆盖 preflight、run、replay、experiment；已有派发按原取消围栏停止后续动作，串行 E4 也补充边界检查。先等待在途任务，再远端 reset 每个 run 后清平台证据，最后删除项目与契约；远端失败保留该 run 平台证据并返回错误。已成功的 run 清理不回滚，不能宣称跨服务原子删除。不可变生命周期审计仅保留 UUID/操作/时间/数量；备份和用户导出由文件持有人管理。

## D052 第二接口产品及通用能力缺口

第二示例 `credit-note-put` 是独立 JSON-RPC 贷项单服务，使用新 schema、不同方法/字段和实际 provider 执行/回调；未导入原 PUT、Runtime 或 Evaluator。`rpc_credit_v1` 只映射协议字段，保存 wire 请求响应，保留非法值。buggy 的旧审批快照漏洞由原 APPROVAL_001 检出；原五条业务规则不修改。

原核心把 RefundAdapter 构造和 provider 回调固定为单一产品，无法挂接接口不同的第二产品。因此增加版本化 Adapter 工厂与 request 覆写点、provider 命名空间的受限回调 origin、注册枚举和导出 Schema。这些是通用接入缺口，不是按产品改资金/审批规则。验证包括同一 S01—S10 在第二产品的 buggy/fixed 实际运行、独立 JSON-RPC wire、credit_note 表有数据而 refund_put 同范围为空、独立 provider ID 无重叠。核心变动和完整旧回归一起验收。

第二示例没有声明故障/barrier/E6 replay 能力，接口明确拒绝超范围请求，不能将其作为 N/A 通过。它只证明本机工程复用，不等于客户验证；S01—S20、重放和崩溃恢复仍由主示例承担。

## D053 本地等价部署、CI 与许可证

沿用真实 embedded PostgreSQL 的本地启动器作为 Compose 等价方式；精确锁定 Python/Node 依赖，新增 CLI 入口但没有新增运行依赖。干净验收必须新建源码副本、venv、node_modules、数据库和生成凭据，只允许复用下载缓存；安装失败立即停止并保留日志，不得借用既有 node_modules 充当安装通过。

CI 默认受控回归、模型关闭，并运行真实 strict suite CLI。actions 固定 SHA、仓库只读权限，无 schedule、部署、发布、生产/staging 秘密。只交付 workflow 文件，未推送或触发外部 GitHub runner。开放探索未启用；以后独立探索的新发现必须经人工确认才可转为发布阻断。

许可证脚本读取已安装 Python/Node 包的元数据和许可文件，未知或缺失不通过；报告单独列出 LGPL/MPL/CC-BY 等分发复核项。它不是律师意见，也不是发布授权。该 E9 决策记录时平台为本机原型，Linux/Windows/容器实机、公网安全、客户验证和 E10 尚未开展；本轮 E10 另见 D055 起的记录。

## D054 E9 实际失败及验收记录

新增首轮六项 E9 专项真实服务测试通过；补充证据丢失、急停排队/在途任务和删除失败反证后，完整候选为 289 passed / 1 failed。失败是 adapter 注册枚举扩展后未同步导出的 schema.v0.2.json；重新导出后该单项通过，保留原失败日志，不修改旧业务规则或降低断言。

干净安装首轮因隔离 PATH 找不到 Python 3.12 停止，修正为显式选择已安装的基础解释器。第二轮新 venv 安装成功，但 pnpm 离线供应链检查缺少 nanoid 元数据，安装失败；未关闭供应链检查或删减锁文件。随后在新隔离目录按同一锁文件允许下载缺失注册表元数据，保留两次失败日志。最终命令、真实结果和未执行范围以 `acceptance-e9.md` 为准；没有将失败或安装后未运行的检查写成通过。


第三轮干净环境安装、README 演示、290 后端和 24 原控制台浏览器检查通过；新增登录检查在响应完成前读取了输入值。通用 role=alert 会匹配 Next.js 提示，改为等待真实 session POST 的 422 和明确错误文字，再断言字段为空，没有取消清空断言。该失败保留于 e9-clean-final；继续在新干净副本复验。

收尾代码审阅发现 CI 外层的 CalledProcessError 会将 simctl 的 2/3 折叠为 Python 默认退出 1。增加 checked_command/entrypoint 保留 gate 的 1/2/3；其他配置、安装或验收执行错误返回 2，中断返回 3。专项通过真实子进程与 API 分别取得通过、业务失败、暂停 provider 和覆盖不足，再核对 CLI JSON、CLI 进程与 CI 外层退出码，结果写入 e9-ci-exit-codes.json。业务规则和 Runtime 不因该修正改变。

最终完整干净验收于 2026-10-11 02:45:21 PDT 退出 0：290 passed / 207.36 秒、24+5+2 浏览器及重启检查、完整严格 gate、构建/双锁/许可/扫描通过。CI 退出码补强后，仅同步验收器与已有测试文件，8 项 E9 专项 / 52.60 秒及完整后续流水线在同一干净安装环境于 02:47:31 PDT 退出 0，真实四种退出码均传递正确。当时工作区与副本 139 个运行源码/脚本/测试/锁文件一致。所有失败记录保留，未将重复测试增加为独立数量。详细结果、原始 ID 和未执行范围见 acceptance-e9.md。E9 当时完成后停止，未自动进入 E10；本轮 E10 另获授权，生产发布仍未开展。


## D055 E10 授权、基线与前序证据复核

2026-10-11（America/Los_Angeles），用户明确授权进入 E10，仅进行 V2 首版工程审查、必要修复及验收。AGENTS 仅将当前阶段由 E9 改为 E10；其他规则保留，不进行公网部署、外部发布、生产访问或真实客户试点。读取原 V2 Word、提示词 E1/E10、进度、映射、决策与源码；无提交且所有文件未跟踪，保存 `.local/e10-baseline` 的 1775 文件和 SHA-256，不用空 diff 推断没有用户修改。

直接核验 E9 完整安装/执行日志、JUnit、场景报告和副本哈希：本轮进入时的 139 个运行源码/测试/锁文件与 E9 最终副本记录一致，见 `evidence/e10-review/prior-e9-parity.json`。E9 已完成的本机工程范围保留；真实客户、真实模型、外部 CI 和生产未执行，不以 README 声明替代事实。

前序复跑首次因沙箱禁止端口未执行，获准本机隔离运行。该轮执行中修复代码，使新 Worker 与启动时已冻结的 API 版本不一致，真实报告出现 `worker_version_drift`，结果 263 passed、14 failed、13 errors，不能计为通过。日志保留于 `evidence/e10-precheck`；后续先冻结代码，再由全新源码副本完整验收。版本保护不关闭，断言不降低。


## D056 E10 反证驱动的必要修复

独立审查发现并以失败测试确认：非法审批金额/版本可利用 Python 数值相等通过；缺失或畸形 provider 初始币种导致异常或错归因；并发预算及 fixture 偏离被归为基础设施退出码；checks 漏 evidence 权限；JSON-RPC wire 的 payee 未脱敏；裸本机访问令牌、回显对象键和末尾特殊字符未完整清洗/扫描。针对相应来源修复，保留非法业务值，不删除核心规则或降低原断言。fixture 环境原因增加独立 execution_issues，保留已观察到的业务检查事实。

审批与独立初始余额校验变更属于两 Adapter 共用的规则健壮性修复，不是为第二产品改答案。评估器 Policy 由 1 升为 2，构建版本为 refund-v2；旧契约的注册规则参数版本仍保留 1，Finding 分别显示契约版本与实际 Evaluator 版本。历史 Manifest、seal 和原始观测不覆盖；重新读取报告可以追加新评估。

gate 版本改为 e10-gate-2，并发预算/fixture 无效运行返回3。归因字段说明具体来源，不以退出码冒充业务四态。当前规则构建与目标冻结 Manifest、当前评估政策与目标历史 seal 另外比较；有变化或缺当前构建证据时，不能把结果归因为 PUT 单独修复。旧运行仍可 history 查看，需以当前代码新建基线及 input replay 才能重新确认修复。

## D057 E10 CLI、API 与 Web 的同源 gate

审查确认旧 UI 仅展示业务 verdict / repair_verified，严格 gate 只在 report API 末端附加。S12 fixed 可在声明范围修复，但审批规则没有适用覆盖时严格 gate 必须为3。将 gate 集中到 report 生成器，console 和 HTML 也消费同一结果；比较器一次读取目标结果，返回严格比较 gate 与目标 gate。CLI 不再在比较后另读一次报告拼接两个时刻的结论。Web 分列业务结论、selected/suite 严格 gate、退出码与理由，并显示运行层环境原因。

严格比较 gate 使用 e10-compare-gate-1；目标 gate 非零继续保持1/2/3，目标通过但修复未确认则3。既有修复范围字段保留，不把所有窄范围业务检查强制改成不通过，也不将窄范围业务通过冒充严格 gate 通过。此变更由新增同快照反证、真实浏览器的 S12/CLI/API 对照与完整 suite 验证。

## D058 E10 最终验收口径与清理

源码冻结后，在新的独立目录从锁文件安装 Python/Node 依赖，使用新的 PostgreSQL 集群、数据库和本机生成凭据；执行 README 启动及 buggy→fixed input replay→compare，随后执行包含新增反证的全部后端、浏览器、迁移、重启、构建、锁与扫描检查。只复用公开依赖缓存，不复制用户 .env、数据库或凭据。完整命令与实际结果由发布检查表记录，不把安装或服务失败写成通过。

沿用 verify_e9 综合执行器（名称表示建立阶段，不限制测试收集），增加实际 cleanup.json：自有进程退出、六个端口释放、验收数据库在 PostgreSQL 系统目录确认已删除。开发环境保留，隔离副本的 README 演示库留作复核；在线 reset/delete 的数据清理另由原真实服务测试验证。所有失败记录保留；工程验收不代表真实客户、模型增量、市场或生产验证。验收后停止，不自动扩展范围。

## D059 E10 核心验收实际结果与证据边界

实际执行 `.venv/bin/python -m scripts.clean_e9 --online --evidence docs/evidence/e10-final`，在新的隔离源码/venv/node_modules/真实 PostgreSQL 环境安装并运行。[clean-environment.json](publication-privacy.md#验收证据) 与 [verification.json](publication-privacy.md#验收证据) 均记录 `passed`。完整后端 **346 passed、0 failed、0 errors、0 skipped、1 warning、220.07秒**，见 [pytest](publication-privacy.md#验收证据) 与 [JUnit](publication-privacy.md#验收证据)；十项必要修复及原场景、安全、隔离、恢复、第二 Adapter 都在本轮重新执行，修前失败没有删除。

真实 Chrome **27 控制台、5 登录、2 重启检查通过**，分别见 [控制台](publication-privacy.md#验收证据)、[登录](publication-privacy.md#验收证据)、[重启](publication-privacy.md#验收证据)。包括同一 run_id 的 API/UI/CLI 严格 gate：S12 fixed 可显示业务修复通过，但缺审批适用覆盖时严格 gate 为3；完整 S01—S20 selected/suite 均为0。不根据截图或 README 声明推断后端执行。

[fixed20](publication-privacy.md#验收证据) 为113 pass、27 not_applicable、0 fail/inconclusive，20场景全部执行；N/A 有契约原因，不能替代必需适用覆盖。[20次重放](publication-privacy.md#验收证据) 为10次buggy失败、10次fixed通过，20个独立run、全新响应及provider账本/回调ID，源history哈希不变。第二 [buggy](publication-privacy.md#验收证据) 和 [fixed](publication-privacy.md#验收证据) 各实际产生62个JSON-RPC wire记录、17次notes.issue，只覆盖声明的S01—S10，不扩称为真实客户或第二产品全能力验证。

空库迁移至0007_e9、应用及PostgreSQL重启、持久化/隔离/Worker恢复和清理真实执行。[cleanup.json](publication-privacy.md#验收证据) 确认自有进程退出、临时验收库删除、3000/8000/8001/8002/8003/55432六端口释放。双锁、构建、类型、静态、格式、许可及文本秘密扫描通过。实际Python 3.12.14、PostgreSQL 18.4、Chrome 155.0.8059.40、pnpm 11.25.0；pnpm声明/CI为11.19.0，保留差异而不声称执行器版本完全一致。

`clean-environment.json` 的 `source_environment_unchanged` 来自源 `.env`/开发数据库相关路径的存在性与元数据比较；不将该布尔字段扩张为逐字节数据库一致性或所有用户文件保护证明。原始需求、旧迁移/锁等文件是否保持另依据源清单/哈希；隔离副本的演示库允许保留复核，临时验收库删除有独立查询证据。最终工程签收与文件保护结果以 [发布检查表](release-checklist.md) 为准。

## D060 E10 收尾展示修正、补验与停止边界

核心套件通过后，继续修正两处沿用旧阶段的UI文案，以及窄屏截图 `fullPage` 取景与真实viewport展示之间的差异。它们属于展示/截图证据修正，不改业务语义；实际使用 `ACCEPTANCE_EVIDENCE_DIR=docs/evidence/e10-frontend-final SIM_PNPM_STORE=.local/pnpm-store .venv/bin/python -m scripts.verify_e9 --targeted` 复跑，结果 **8 passed、1 warning、53.09秒**，27控制台/5登录/2重启、build/typecheck/lint/format均通过。但后续lock-python因隔离shell PATH未包含uv而失败，命令整体退出2；保留 [流水线](publication-privacy.md#验收证据)、[pytest](publication-privacy.md#验收证据) 与 [原空锁检查日志](publication-privacy.md#验收证据)，不将未执行的锁检查计为该轮通过。这8项不另加到346项独立测试中。

后续 `.local/e10-frontend-postchecks.py` 显式指定工作区 `.venv/bin/uv` 绝对路径，继续同样的Python锁、Node锁、许可和秘密扫描断言，四项实际退出0，具体命令及结果见 [独立补检](publication-privacy.md#验收证据)。此项补全必要检查，不重写前一条命令退出2的事实，不宣称第二条完整流水线退出0。

视觉复核最终各新建一个390×844页面，禁用GPU读取运行详情和比较页，隔离resize导致的截图采集残影。[两项结果](publication-privacy.md#验收证据) 与 [运行顶部](publication-privacy.md#验收证据)/[运行gate](publication-privacy.md#验收证据)/[比较顶部](publication-privacy.md#验收证据)/[比较gate](publication-privacy.md#验收证据) 四张截图确认实际视口、单侧栏、无横向溢出、DOM无令牌及真实后端gate。[cleanup](publication-privacy.md#验收证据) 记录开发启动器退出0，六端口逐一bind成功，保留的仅为隔离README演示库。该补查不外推到所有GPU或其他浏览器兼容性。

没有真实客户/staging、真实资金、真实模型/自然语言PUT/AI增量实验；外部GitHub/Linux runner、Windows/容器实机、Safari/Firefox、屏幕阅读器、正式安全/WCAG审计和大规模性能均未执行。默认loopback与共享OS/数据库账号的本机边界继续有效，不宣称生产就绪或市场验证。完成本轮工程验收后停止汇报；客户规则确认、试点及持续复用/付费意愿验证需要另行授权，不能由工程场景结果替代。

## D061 本地首次提交与 GitHub 私有版本备份

2026-10-11（America/Los_Angeles），用户明确授权检查上传范围、建立本地首次提交，再推送到 GitHub 私有仓库，并排除凭据、数据库及临时文件。该授权只扩展版本管理和私有备份范围；不改变 E10 阶段、应用代码、原始需求、既有验收结论或生产/公开发布边界。

沿用当前 `main` 分支；本地仓库此前没有 HEAD 或已跟踪文件。补充 `.gitignore` 排除常见认证/密钥文件、本地数据库及备份、依赖、构建/测试临时产物；保留 `.env.example`、源码、双锁、原始需求和完整正式验收证据。首次提交固定当前用户文件，先前变化仍由 `.local` 阶段备份和内容哈希解释，不从空 diff 或首次提交反推历史修改者。使用当前已连接账号 `HashBrown-bot`，仓库名选择 `shadow-company`，已在 GitHub 表单确认名称可用及 Private；不自动添加远程 README、许可证或模板。

范围核验只输出路径、类别和数量，不读取真实 `.env`/认证存储或打印秘密值；真实配置和数据库继续留在本地。实际检查记录见 [首次提交范围核验](publication-privacy.md#验收证据)，完成后的提交/远程核验另写进度。此项不触发业务开发或本机工程套件重跑；GitHub 自带 push workflow 的运行结果如有实际触发，应单独记录，不能冒充已通过。

完整首次暂存的空白检查退出2，定位全部为原有验收日志/JUnit的工具格式；保持证据原始字节，不为首次提交修剪历史失败/成功日志。本次五个修改文件的限定空白检查通过，完整失败和处置保留在范围核验报告中。

首次基线提交 `c6993819f3ba56d0a2cb4acd34e62e0b210cc716` 含2,109个文件，已完整推送至 [HashBrown-bot/shadow-company](https://github.com/HashBrown-bot/shadow-company)，API与页面确认私有；远程main与本地提交相同，递归树路径、模式、blob哈希一致。仓库本地设置Git作者为账号及GitHub noreply地址，不更改全局作者或credential helper。官方GitHub CLI release checksum已核验，认证存于系统keyring，CLI配置在忽略的 `.tools`。

无HTTPS凭据和标准授权缺workflow权限的两次推送均失败，未删除workflow绕过上传；初次额外权限请求被自动审批拒绝的事实保留。用户明确允许追加workflow权限后，授权刷新和完整推送成功；此权限本次仅用于上传原有未修改的工作流。各次失败、授权与成功见 [备份操作记录](publication-privacy.md#验收证据)。现有push工作流实际自动运行，首次查询为in_progress，未冒充CI通过；此项独立于既有本机E10验收。


## PUB01：开源发布副本与私有运行档案分离

2026-10-28。用户授权进行隐私检查、完善项目主页并公开源码，明确选择 MIT。公开副本以 E10 主分支基线为范围，原始证据、真实云绑定、旧提交和 Actions 材料保留在私有档案；不改变工程阶段或把历史结果升级为当前验收。仅公开副本清理个人路径和 Office 个人元数据，本地原始需求与未提交工作保留。实施范围和限制见 [发布说明](publication-privacy.md)。
