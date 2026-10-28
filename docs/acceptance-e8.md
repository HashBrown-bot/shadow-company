> 公开版说明：以下为历史工程记录摘要。原始日志、截图、CI制品与私有环境材料不随源码发布；相关链接指向[证据范围说明](publication-privacy.md#验收证据)。历史结果不代表公开副本已经重新验收。

# E8 中文工程控制台验收记录

更新：2026-10-11（America/Los_Angeles）。**E8 验收通过并停止于本阶段。**最终综合命令退出 0：282 项后端测试、24 项浏览器检查及 2 项真实重启恢复检查通过；构建、类型、静态、格式、双锁与秘密扫描通过。E9—E10、完整 V2 发布、真实客户和生产部署未完成。

## 授权与前置复核

用户明确授权进入 E8，只修改 AGENTS 的当前阶段；其他规则继续有效。先读 AGENTS、进度、需求映射、决策、V2 原始 Word、提示词 E1/E8、源码和 diff，说明方案后开发。仓库仍无提交，全文件未跟踪；保存 `.local/e8-baseline` 的 685 文件副本与 SHA-256，保留原始需求、旧迁移、锁文件、正确实现与用户修改。

E7 综合复核退出 0：277 后端测试（165.67 秒）、31 浏览器检查、PostgreSQL 与全部服务停止重启、构建/类型/静态/双锁/扫描通过。证据独立位于 [e7-recheck](publication-privacy.md#验收证据)，没有阻碍 E8 的缺项。首次端口绑定被沙箱拒绝，未执行测试；获准后重试通过，保留 [未执行日志](publication-privacy.md#验收证据)。

E7 的真实模型服务、供应商收费/token 实验、自然语言 PUT、真人独立根因/误报/确认时间及 AI 增量结论均未执行。本阶段继续关闭模型，不把协议替身、规则 Finding 或示例报告当作真实 AI/客户实验。

## 实现范围

- 项目列表、不可变契约接入向导、已保存预检结果、场景/时间/预算配置、实时运行、Finding、真实 input replay 与版本比较。
- 既有 API、Configuration、作业、证据与报告为唯一事实源；没有前端业务判定、演示状态库或假成功分支。新增 `console.py` 仅提供读取投影；原规则、契约内容、旧迁移和两个锁文件保留。
- 运行页以失败、证据缺失、覆盖和重放排序；四态同时显示符号、中文与英文 ID。Worker 失联依据 PostgreSQL 租约；生命周期独立于业务 verdict。
- 因果时间线区分角色、产品、provider、evaluator，显示实际时间与因果/引用 ID；没有关联时不推测关系。
- Finding 展示规则版本/哈希、预期实际、对象、独立支付账本、脱敏请求响应、来源与失败链。原始非法业务值不修正。
- URL 保存项目/run/Finding/比较源；刷新从后端恢复。长列表分页；中文标签、原生键盘控件、标题/分页焦点、跳过导航与减弱动效。
- 配置明确解释 realtime/event_compressed、真实观察窗口、预算和可控范围。controlled 时钟、真实模型不可选；示例系统与示例报告明确标注。

## 浏览器真实流程与状态验证

验收器实际启动 PostgreSQL 18.4、API、Worker、refund-put、payment-provider、Next.js Web，以及本机 Chrome。核心流程均通过页面控件操作；负向状态使用同一独立验收库和真实 API/进程/证据故障，不用前端 mock 成功。

| 检查 | 实际步骤与断言 | 证据 |
| --- | --- | --- |
| 项目与接入 | 空库创建示例项目 → buggy 契约向导 → 保存 → 真实预检 passed | [空项目](publication-privacy.md#验收证据)、[无运行](publication-privacy.md#验收证据)、[预检](publication-privacy.md#验收证据) |
| 配置 | 选择 S12，确认时间/预算/场景，controlled/模型禁用；表单提交创建真正 run | [桌面配置](publication-privacy.md#验收证据)、[窄屏配置](publication-privacy.md#验收证据) |
| buggy 失败 | completed/fail；同指令独立支付执行两次，REFUND_001 与 STATE_001 Finding | [失败页](publication-privacy.md#验收证据)、[后端报告](publication-privacy.md#验收证据) |
| 查看证据 | 打开 Finding，核对 v1、预期最多一次、实际两个 ledger entry、业务对象、脱敏 Authorization | [证据页](publication-privacy.md#验收证据)、[390px 证据](publication-privacy.md#验收证据) |
| fixed 重放 | 页面选 fixed → 新契约/预检 → input replay；新 run、PUT 调用、账本及回调 ID，completed/pass | [通过页](publication-privacy.md#验收证据)、[目标报告](publication-privacy.md#验收证据) |
| 比较 | 后端 repair_verified=true；没有混杂条件；provider 调用从 2→1，未选 19 场景仍列为未验证 | [桌面比较](publication-privacy.md#验收证据)、[窄屏比较](publication-privacy.md#验收证据)、[JSON](publication-privacy.md#验收证据) |
| 历史与刷新 | 深链接刷新后恢复目标与比较；源 history 前后 SHA-256 完全相同 | [哈希](publication-privacy.md#验收证据) |
| 因果与四态 | 四类来源真实记录、时间线/检查服务端分页；N/A 显示“— 不适用”，证据不足显示“? 证据不足” | [时间线](publication-privacy.md#验收证据) |
| 加载 | 暂缓真实网络请求后继续原请求；显示加载状态 | [加载](publication-privacy.md#验收证据) |
| 取消 | 暂停验收 Worker 后入队，页面取消；status=cancelled/verdict=inconclusive | [取消](publication-privacy.md#验收证据)、[JSON](publication-privacy.md#验收证据) |
| Worker 失联 | 实际 SIGSTOP 自身 Worker 进程组，租约到期显示失联，仍 running/inconclusive；取消后 SIGCONT，最终保留取消结论 | [失联](publication-privacy.md#验收证据)、[恢复后报告](publication-privacy.md#验收证据) |
| 证据不足 | 另一个实际 fixed run 先 pass；带 reset 审计删除其持久 provider_ledger 观测，刷新变为 inconclusive | [证据不足](publication-privacy.md#验收证据)、[当前后端报告](publication-privacy.md#验收证据) |
| 预算终止 | 真实 max_events=1 运行，failed/budget_exhausted/inconclusive | [终止](publication-privacy.md#验收证据)、[JSON](publication-privacy.md#验收证据) |
| 无权限 | 原页面请求转送给真实 BFF，带不允许的 Origin；原样转交实际 403 响应，项目数量不变 | [无权限](publication-privacy.md#验收证据) |
| 404 / 连接错误 | 请求不存在的 run；浏览器中止网络请求后显示错误且无数据表，恢复后实际重试 | [404](publication-privacy.md#验收证据)、[连接错误](publication-privacy.md#验收证据) |
| 字段错误 | 导入缺 provider_ledger 的 YAML，显示后端字段路径与 422 提示 | [字段错误](publication-privacy.md#验收证据) |
| 分页与键盘 | 实际创建 12 个示例项目，10+2 分页；Tab/Enter/Space、跳过导航、表单标签、展开证据、标题/分页焦点 | [分页窄屏](publication-privacy.md#验收证据)、[焦点](publication-privacy.md#验收证据)、[键盘展开](publication-privacy.md#验收证据) |
| 重启 | PostgreSQL 与全部应用实际停止再启动；target history 完全相同，页面刷新和比较继续有效 | [重启截图](publication-privacy.md#验收证据)、[重启结果](publication-privacy.md#验收证据) |

加载/断连检查只延迟或中止真实请求。403 检查转交后端实际响应，没有自行填充错误或业务结果；它验证本机同源防护及错误 UI，不冒充 E9 登录/IAM。证据缺失与进程故障只触及验收器创建的临时库/进程，原始成功报告和失败后报告分开保存。

本轮真实流程的产物标识如下；验收结束已清理专属临时库，标识用于复查保存的 JSON、截图与日志。再次执行会创建新的项目和运行。

| 对象 | 实际 ID / 结果 |
| --- | --- |
| 示例项目 | `ec5261c8-7376-4dae-88d1-7c88d7b09275` |
| buggy 源运行 | `b12e7cdd-cd21-4d22-b32b-b24a03c11033`；completed / fail |
| fixed 输入重放 | `a641cc64-3391-4944-9479-e1d835829a62`；completed / pass |
| 修复比较 | `repair_verified=true`；独立 provider 调用路径 2→1；只验证 S12，其他 19 场景未验证 |

最终截图共 25 张（24 个编号截图及重启截图），位置为 `docs/evidence/e8/browser/`。已目视核对最终 Finding、390px 比较、Worker 失联、403 和 YAML 错误页；展示的是生成的示例对象、秘密引用或 `[REDACTED]`，没有秘密明文。

## 测试命令与结果

当前综合入口：`.venv/bin/python -m scripts.verify_e8`。复验时先停止已有本机服务，建议设置新的 `ACCEPTANCE_EVIDENCE_DIR`，避免覆盖既有证据。测试数据库为随机命名的真实 PostgreSQL，不清空开发数据库。

最终 `docs/evidence/e8/verification.json` 于 **2026-10-11 01:55:52（America/Los_Angeles）**记录 passed；命令退出 0。后端 **282 passed / 0 failed / 0 skipped，167.81 秒**，保留 1 个既有 Starlette/httpx 弃用 warning；Chrome **155.0.8059.40** 的 **24+2 检查全部 passed**、无运行时错误。下表所有命令均实际执行并通过，没有用 targeted 结果代替最终全量回归。

| 命令 | 检查范围 | 产物 |
| --- | --- | --- |
| `.venv/bin/python -m scripts.verify_e8` | 完整后端、真实浏览器、全部服务/DB 重启及下列构建检查 | [综合结果](publication-privacy.md#验收证据) |
| `.venv/bin/python -m pytest -q --tb=short --junitxml=docs/evidence/e8/pytest.xml` | 原 277 + E8 5 项，含迁移、S01—S20、10+10 重放、独立证据与 E7 离线协议 | [文本](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据) |
| `node scripts/e8-browser.mjs` | 中文界面实际交互、异常、桌面/390px、键盘与后端一致性 | [实际输出](publication-privacy.md#验收证据)、[结果](publication-privacy.md#验收证据) |
| `E8_RESTART_ONLY=1 node scripts/e8-browser.mjs` | 服务与 PostgreSQL 实际重启后恢复 | [输出](publication-privacy.md#验收证据) |
| `pnpm build:web` / `pnpm typecheck` | Next.js 生产构建、TypeScript | [构建](publication-privacy.md#验收证据)、[类型](publication-privacy.md#验收证据) |
| `.venv/bin/ruff check packages services migrations tests scripts examples adapters` / `.venv/bin/ruff format --check packages services migrations tests scripts examples adapters` | Python 静态/格式 | [静态](publication-privacy.md#验收证据)、[格式](publication-privacy.md#验收证据) |
| `.venv/bin/uv lock --check --offline --cache-dir .local/uv-cache` / `pnpm install --frozen-lockfile --offline --store-dir .local/pnpm-store` | 双锁文件与依赖一致性 | [Python](publication-privacy.md#验收证据)、[Node](publication-privacy.md#验收证据) |
| `.venv/bin/python -m scripts.scan_secrets` | 高置信凭据模式；不打印匹配内容 | [扫描](publication-privacy.md#验收证据) |

## 实际失败、修复与复验

1. E7 复核首次被沙箱禁止 loopback 绑定，未执行测试。取得许可后同一真实服务复核通过，没有 SQLite 或假服务回退。
2. E8 首轮完整后端 282 passed（167.37 秒），浏览器加载检查因解除请求拦截与继续请求并发，发生 `Route is already handled`。改为只拦截一次且等待真实请求恢复。保留 [首轮后端](publication-privacy.md#验收证据)、[首轮浏览器失败](publication-privacy.md#验收证据)。
3. 第二轮前 18 个浏览器检查通过；Chrome 覆盖测试注入的 Origin，导致请求实际成功而未显示 403。改为测试工具向真实 BFF 发出带不允许 Origin 的请求并原样转交实际响应；仍断言没有写入。保留 [第二轮失败](publication-privacy.md#验收证据)。这是测试注入方式修复，没有改低后端授权标准。
4. 候选复验通过 23+2 浏览器及构建/双锁/扫描，产物保留在 `e8-candidate`。收尾过程中修正分页加载后的焦点与空页总数、加深小字对比度、更新过时阶段说明，并加入 YAML 字段错误 UI 验证。最终完整复验 282 后端、24+2 浏览器及全部构建检查通过，产物保存于 `e8`，未覆盖前两轮失败记录。

## 限制与未执行检查

- 仅本机 `http_refund_v1` 示例。没有真实资金、客户/staging、市场实验、自然语言 PUT 或真实模型服务；未证明 AI 增量。
- 沿用 schema 0.2、报告 e7-report-1、迁移 0006_e7；E8 新增读取投影，没有虚构新迁移或改变旧契约哈希。原资金/审批评估逻辑不变。
- 只对受支持的本机服务控制初始数据、语义故障、调度、回调及 barrier；不控制外部时钟、网络延迟、OS 调度与数据库锁胜者。
- loopback 信任模型与共享开发数据库账号保持；公网认证、多租户 IAM、最小权限生产部署、数据保留/项目删除、安全发布、第二适配器和 simctl 属 E9—E10，未完成。
- 验收浏览器为本机 Chrome，桌面 1440×1000 与窄屏 390×844；没有 Safari/Firefox、屏幕阅读器、触屏真机或正式 WCAG 审计。键盘/标签/焦点和无页面横向溢出是已验证范围。
- 浏览器 seed 表单限 JS 安全整数；更大合法值用原 API/YAML。读取投影目前按页重算终态报告，未做超大历史库性能基准。
- 默认启动入口保留原开发数据库；验收器清理自身服务与临时库，证据中的 ID 是可复查产物索引。旧阶段界面脚本保留作历史记录，当前 UI 用 `verify_e8` 验收。

**E8 验收后停止，不自动进入 E9，不宣称 E9—E10 或生产就绪。**
