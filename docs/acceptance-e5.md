> 公开版说明：以下为历史工程记录摘要。原始日志、截图、CI制品与私有环境材料不随源码发布；相关链接指向[证据范围说明](publication-privacy.md#验收证据)。历史结果不代表公开副本已经重新验收。

# E5 阶段四验收记录

结论：**E5 事件、故障、并发与恢复验收通过；S01—S20 已验证，E3/E4 有效回归保留。** 最终综合命令从 2026-10-07 21:59:45（Asia/Shanghai）开始，退出 0。仅覆盖本机工程示例；**不代表 E6—E10、完整 V2 发布、真实客户或生产部署完成。本次停止于 E5。**

## 授权与前置复核

用户明确授权把 AGENTS 当前阶段改为 E5，其余规则继续有效。先读取规则、进度、需求映射、决策、原始 V2 Word、提示词 E1/E5、代码与 diff。仓库没有提交、全部源码未跟踪；保存 `.local/e5-baseline` 和哈希，不把空 diff 当成没有用户修改。没有覆盖原始需求、附录 B 或旧验收记录。

E4 前置综合复核通过：187 后端测试、15 浏览器检查、独立服务与真实 PostgreSQL 重启持久化、构建/类型/静态/双锁与扫描。无阻碍 E5 的前置缺项。原始结果在 [E4 复核](publication-privacy.md#验收证据)。

## 用户验收条件

| 条件 | 实际实现与证据 | 结果 |
| --- | --- | --- |
| S11—S20，保留 S01—S10 | 最终 fixed 全 S01—S20；旧 E3/E4 测试纳入最终后端回归 | 通过 |
| 区分故障真实证据 | 六项计划及实际命中；提交前断连接、提交后真实读取超时、重复/旧回调、429、审批离线 | 通过，六项均 verified |
| commit_then_timeout 先提交 | provider PostgreSQL 事务提交后扣住响应头；PUT 发生真实 timeout，首次 entry_id 与全部调用可追溯 | 通过；buggy 产生两条独立成功记录 |
| barrier 与事件同步 | S16/S17/S19 平台与 PUT 双 barrier；请求开始结束时间及顺序、服务到达/释放序号 | 通过，三组均真实重叠 |
| 不吞掉有意重复 | S16 两事件 ID、两次 execute 请求；消费去重仅按事件 ID | 通过，fixed 一条资金、buggy 两条 |
| Worker 重启安全 | S20 两处 os._exit(86)、新 PID/owner/epoch；另在提交后 HTTP 在途时 SIGKILL；独立核验后确认 | 通过，无静默丢事件或重复资金 |
| 远端未知 | 持久派发意图但没有确定远端结果的反证：PUT 查询+零账本，unknown 后停止，provider 无执行调用 | 通过，不盲目重发 |
| 租约隔离与 fencing | 旧 owner 失租不能续期/派发/完成；旧会话锁仍在时第二 Worker 不能接管；释放后 epoch 递增 | 真实 PostgreSQL 通过 |
| 取消及预算 | queued 取消；provider 已提交后的在途取消；事件/墙钟/并发限制与重试预算 0 | 实际生效，完整 verdict/gate 不通过 |
| 缺证据不通过 | 删除实际命中观测后重新报告，规则正常也不能维持场景通过；旧缺账本回归保留 | 通过 |
| Evaluator 独立 | 真实 buggy 资金重复/余额竞争/终态回退触发规则；修改控制观测中的行为开关不改变 fixed 业务结论 | 通过 |
| 两种时间模式 | realtime/event_compressed 实测；真实观察窗口不少于 1 秒；simulation_time 与真实时间分别保存 | 通过；controlled 明确拒绝 |
| 时间与资源口径 | 发生器准备、线程 CPU、run 墙钟、PUT HTTP 样本分列 | 通过，不声称 PUT 吞吐量 |
| 实际进程和数据库 | API、监督 Worker/子 Worker、PUT、provider、Web、真实 PostgreSQL 实际运行 | 通过，不使用 SQLite |
| 必要迁移/持久化 | 0004_e5 空库、含 E4 记录升级、重复升级、降级/再升级；所有服务和数据库停止再启动 | 通过，历史原始观测、契约、运行与评估保持 |
| 文档与报告 | README、架构、映射、决策、进度、本记录及 JSON/HTML 更新 | 完成，无 E6—E10 完成声明 |

完整场景映射见 [需求覆盖表](requirements-map.md)。协议层反证和真实 HTTP/进程验证分别标记，测试数不冒充场景数。

## 最终可追溯运行

完整脱敏产物：[runtime.json](publication-privacy.md#验收证据)、[fixed 报告](publication-privacy.md#验收证据)、[buggy 报告](publication-privacy.md#验收证据)。验收临时数据库结束后清理，保留这些证据文件。

- fixed 项目 `123121ff-33b8-451f-a750-d7765d611de1`，run `9f67165b-283f-44da-9395-4f1b14078fd1`，evaluation `b8401560-5394-4772-bdb1-82fab9237393`。status completed，所选与 refund_core_20 gate pass；140 条检查：113 pass、27 有契约理由的 not_applicable、0 fail、0 inconclusive、0 Finding；20 条真实示例账本。
- buggy 项目 `3e93267c-2499-411e-98a6-dc19b0b4082e`，run `fe1ca2ce-2d92-42f0-a3db-b4157c608e59`，evaluation `b5295c1c-fa45-4720-9732-c535dc77b4e2`。140 条检查：13 fail、101 pass、26 not_applicable、0 inconclusive；归并 11 个已确认产品后果 Finding。没有将其称为 11 个独立源码根因。
- buggy 反证包含 S04 失效审批，S05/S12/S16 重复执行，S07/S17 超额，S14 成功终态退回处理中及观察期限超限。五条规则依据实际观测，不读 variant 作判断。
- 两轮各 123 个持久事件；六种故障均有命中、三组 barrier 均有真实重叠；S20 恢复有多 PID、多 owner 和核验记录。S19 谁先取得产品锁不预设，允许取消成功零资金或执行成功一笔资金；不能据此声称外部产品完全确定性。

fixed 本轮墙钟 9.183024 秒，发生器准备累计 119.414ms、线程 CPU 累计 56.694ms，已保存 PUT HTTP 样本累计 686.469ms。buggy 分别为 9.722457 秒、117.897ms、56.021ms、696.425ms。墙钟包含恢复租约等待/观察，准备含 barrier，HTTP 含产品依赖等待；并发样本不能相加推断吞吐量。被杀进程的未确认请求没有完整耗时样本，不补造。模型调用/token 均为 0，不估算基础设施费用。

[真实 SIGKILL 记录](publication-privacy.md#验收证据) 另证实 provider 已提交、HTTP 仍在途时中断 Worker，最终仅一次执行。[在途取消](publication-privacy.md#验收证据) 显示取消后的新派发为零，保留一笔已提交资金和结束观测。

数据库与全部应用重启后，ledger entry_id、原始观测、checks/evaluation_id、Finding 和 E5 runtime 逐项相等。reset 实际移除 123 事件/消费记录/Action、495 条 journal、140 个检查、Manifest 和相应故障、审计、回调/业务记录，并保留 reset 审计及契约/输入哈希墓碑。

## 命令、实际结果和原始输出

从项目根执行；综合入口需要本机端口空闲。

| 命令 | 实际结果 | 证据 |
| --- | --- | --- |
| `.venv/bin/python -m scripts.verify_e5` | **退出 0**，全部综合检查完成 | [综合日志](publication-privacy.md#验收证据)、[启动](publication-privacy.md#验收证据)、[PostgreSQL](publication-privacy.md#验收证据) |
| `.venv/bin/python -m pytest -q --tb=short --junitxml=docs/evidence/e5/pytest.xml`（验收器执行） | **207 passed、0 failed、0 skipped、1 warning，47.65 秒** | [文本](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据) |
| `node scripts/browser-smoke.mjs`（独立空验收库） | **10 项通过**：真实 API/迁移/持久化/校验/错误与基础页面 | [结果](publication-privacy.md#验收证据) |
| `REPORT_RUNTIME_PATH=docs/evidence/e5/runtime.json node scripts/report-browser.mjs` | **7 项通过**：真实 API fixed/buggy 报告、锚点、390px、E5 证据与耗时、运行时异常检查 | [结果](publication-privacy.md#验收证据) |
| `node /tmp/shadow-e5-report-qa.mjs`（已保存 API HTML 顶部截图补查；[脚本副本](publication-privacy.md#验收证据)） | **4 项通过**，单列附加视觉检查，不冒充服务集成 | [记录](publication-privacy.md#验收证据)、[输出](publication-privacy.md#验收证据) |
| `NEXT_TELEMETRY_DISABLED=1 pnpm build:web` | Webpack 生产构建退出 0 | [输出](publication-privacy.md#验收证据) |
| `pnpm typecheck` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/ruff check packages services migrations tests scripts examples adapters` | All checks passed | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/ruff format --check packages services migrations tests scripts examples adapters` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/uv lock --check --offline --cache-dir .local/uv-cache` | 退出 0，未新增依赖 | [输出](publication-privacy.md#验收证据) |
| `pnpm install --frozen-lockfile --offline --store-dir .local/pnpm-store` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/python -m scripts.scan_secrets` | 高置信凭据模式无发现 | [输出](publication-privacy.md#验收证据) |

唯一 warning 是既有 Starlette/httpx TestClient 弃用提示，未屏蔽。已查看桌面与 390px 报告截图，确认表格横向滚动、四态文字、证据锚点及 E5 记录可读。基础页面仍非 E8 完整业务 UI。

## 实际失败和修复

| 问题 | 修复与记录 |
| --- | --- |
| 首次本机复核在沙箱无法绑定端口 | 按既有授权流程执行真实本机服务；权限失败未算通过 |
| 首轮 14 failed / 173 passed，旧 E3/E4 状态未完成 | SQLAlchemy 将内嵌 JSON 识别为 bind 参数，改成参数化写入；[首轮输出](publication-privacy.md#验收证据) |
| 聚焦 1 failed / 8 passed | 定位同一完成路径错误，E5 各实际场景已跑通；修复后完整 203 项通过；[聚焦](publication-privacy.md#验收证据)、[修复回归](publication-privacy.md#验收证据) |
| 历史回调证据、缺结果确认与预算边界审阅 | 保存提交前旧回调并核验发生时间；确认不只看 end_time；只读收尾最多 3 秒；补充缺时间反证、Evaluator 开关独立性和重试预算 0，最终 207 项通过 |
| 首次综合浏览器检查仍期待 0003_e4 | 页面实际是正确 0004_e5，更新精确断言；[失败输出](publication-privacy.md#验收证据)、[首轮综合](publication-privacy.md#验收证据) |
| 桌面截图点击 E5 区块后处于页面下方 | 保留集成截图，另从保存的真实 API HTML 补充顶部桌面/窄屏截图并查看，未改业务输出 |
| pytest fixture 可能显示继承的进程环境片段 | fixture repr 改为不展示环境，首轮日志移除该表示；诊断只输出异常类型/代码位置/SQLSTATE，不打印凭据 |

没有降低断言、空测试、跳过失败、用 SQLite 替代，或把计划当执行证据。原需求、附录 B、双锁文件哈希保持；[改动基线清单](publication-privacy.md#验收证据) 确认 AGENTS 只改当前阶段。

## 限制、未执行与下一阶段

- E5 必须验收项无遗留失败。S11 是提交前实际连接中断，未声称覆盖 DNS/TCP 建连拒绝；历史回调与审批离线属于本机受控依赖/身份。
- 时间模式仅 realtime/event_compressed，真实观察等待不可被压缩；无外部时钟接口，不支持 controlled。seed 不能保证任意外部系统确定性。
- unknown 允许停止并阻断通过，不承诺任意非幂等外部产品自动恢复。未同时杀死 PUT/provider 或做主机断电、数据库网络分区测试。新产品需审阅幂等/查询、取消、权限和时钟契约。
- 取消/预算停止新业务派发，无法撤回已提交资金；在途动作和最多 3 秒只读收尾可能使总墙钟超过派发预算。缺后果证据保持不确定。
- 共用开发 PostgreSQL 账号、本机信任 API；无公网认证、数据库/OS 最小权限、全面安全审计，reset 非跨服务原子事务。凭据扫描仅高置信模式检查。
- 未执行真实客户/staging、实际付款、模型/市场实验、Linux/Windows、容器实机或生产部署。E6 重放/比较、E7 混合模型、E8 完整业务 UI、E9 CLI/第二适配器/公网安全、E10 发布验收均未完成。

下一阶段为 **E6，需要用户另行明确授权。当前停止于 E5，不自动继续。**
