> 公开版说明：以下为历史工程记录摘要。原始日志、截图、CI制品与私有环境材料不随源码发布；相关链接指向[证据范围说明](publication-privacy.md#验收证据)。历史结果不代表公开副本已经重新验收。

# E3 阶段二验收记录

结论：**E3 独立示例产品与纵向闭环验收通过**。记录更新于 2026-10-07（Asia/Shanghai）；最终综合验收从当天 07:13 开始，退出 0。结论仅覆盖本机示例和 E3 要求，不代表 E4—E10、全部 20 场景、真实客户验证或生产就绪。

## 前置复核与范围

用户明确授权进入 E3；AGENTS 只修改当前阶段，其他规则保持。已读取 V2 Word、提示词 E1/E3、进度、覆盖表、决策和实际代码。仓库无提交且全为未跟踪文件，除 git status/diff 外使用实施前源码副本逐文件核对，没有重建或覆盖原始需求。

开发业务前复跑 E2 综合验收：**89 passed、0 failed、0 skipped，10 项浏览器检查通过**，真实 PostgreSQL 迁移、停止重启与持久化通过。没有阻碍 E3 的 E2 遗留项。证据保存在 [E2 复核运行结果](publication-privacy.md#验收证据) 与 [后端复核输出](publication-privacy.md#验收证据)，原 [E2 验收](acceptance-e2.md) 及原证据保持不变。

本次环境沿用 macOS arm64、Python 3.12.14、Node.js 24.19.0、pnpm 11.19.0、uv 0.12.23、真实 PostgreSQL 18.4、Chrome 154.0.8037.98。没有模型 API、真实秘密、生产连接或真实资金。

## 必须条件与证据

| E3 条件 | 实际验证 | 结果 |
| --- | --- | --- |
| 独立 PUT/provider | 分别启动 8001/8002 FastAPI OS 进程，读写自身 schema；PUT 通过 HTTP 调用 provider | 通过 |
| 退款与审批 | 创建、审批、执行、查询、测试 seed/reset；整数金额/币种、gt 200000 快照审批、幂等指令、部分退款及超额拒绝 | 通过；仅 S01/S02 是完整场景验收 |
| 独立支付后果 | provider 保存真实 entry_id 与 outbox；执行查询和只读账本身份分离；不使用 PUT success 自证 | 通过 |
| S01/S02 闭环 | 平台 202 入队 → PostgreSQL 作业 → 独立 Worker → Adapter → PUT → provider → 签名回调 → 查询/账本关联 | 通过 |
| 不同身份 | 客服与审批人不同密钥/身份；低权限审批真实请求到达 PUT 并返回 403；执行身份不能读测试账本 | 通过 |
| 运行与项目隔离 | 两 run 相同外部 ID 产生不同账本条目；跨项目查询 404；交换 run 头而保留旧令牌返回 403 | 通过 |
| 预检 | 连接、身份、动作含义、创建只申请不支付、独立账本、reset、时钟、政策和出站允许范围 | 通过 |
| 完整 reset | 清理 PUT、provider、outbox、平台观测/事件/动作/队列/绑定；保留契约、输入哈希、请求键和审计墓碑 | 通过 |
| 缺证据不能成功 | 对真实运行删除已采集的 provider_ledger 观测后，completed run 的 e3_flow 变为 inconclusive；provider 本身仍有条目 | 通过 |
| 反证不能成功 | 从真实记录派生收款方、项目/run、指令 ID、浮点金额冲突；畸形账本内容不造成成功或报告崩溃 | 通过 |
| Webhook | HMAC/原始字节、五分钟窗口、未来/陈旧时间、错误签名、范围绑定、重复/冲突事件、DB 失败不确认 | 通过 |
| 出站与脱敏 | 恶意 origin/管理端口/云元数据/路径/真实凭据引用拒绝；DNS 校验、数值 IP 固定和重定向拒绝；授权头及文本回显脱敏 | 通过 |
| 真实 PostgreSQL | 空库升级、重复升级、降级/再升级；含 E2 项目的库升级；所有应用及数据库停止重启后证据不变 | 通过 |
| 后续范围不冒充通过 | S01/S02 可为 e3_flow=pass，但完整 run verdict 与 refund_core_20 gate=inconclusive | 通过 |

DNS/重定向传输测试采用明确的协议替身；Webhook 存储失败采用明确的数据库异常注入。S01/S02、provider 账本、隔离/reset 和重启证据来自真实独立进程与 PostgreSQL，不由这些替身提供资金结论。

## 可追溯调用链

最终综合运行的项目为 `4a59859a-85a3-401b-b3c0-12799766b5cd`，run 为 `0cf56dad-85d0-425c-9a4f-fbdb6311431a`。这是验收器生成的示例命名空间，验收后临时数据库已清理，脱敏报告保留在仓库。

| 场景 | 外部退款指令 | 独立 provider entry_id | 闭环结果 |
| --- | --- | --- | --- |
| S01 | refund-S01 | a62df4a5-fcc1-43e8-a46e-1323cb0c4442 | pass |
| S02 | refund-S02 | 8dda7af9-277c-4840-94d5-f21f87f6c502 | pass |

[完整运行与重启/reset 记录](publication-privacy.md#验收证据) 包含两条独立账本、产品查询、审批快照、回调及各条观测引用。另有 [集成测试调用链](publication-privacy.md#验收证据)。最终报告为 `status=completed`、`e3_flow=pass`、完整 gate `inconclusive`。

该运行 reset 实际删除 2 条 PUT 退款、2 条 PUT 支付对象及 2 条回调收据；provider 删除 2 条账本、2 条 outbox、2 条支付对象；平台删除 16 条观测（包含 reset 控制响应）、7 个动作、7 个事件、1 个作业及绑定/收据。reset 审计哈希为 `2d289778526ce7f9a282003772347a5d2d3bd85719d5ea6a44f16a26b36363b9`。另有测试确认另一 run 不受影响、重复 reset 幂等、旧请求键不重建支付运行。

## 命令与最终结果

从项目根执行，完整验收器要求相关本地端口空闲：

| 命令 | 实际结果 | 证据 |
| --- | --- | --- |
| `.venv/bin/python -m scripts.verify_e3` | **退出 0**；启动/业务/停止重启/reset/后续检查均通过 | [综合日志](publication-privacy.md#验收证据)、[启动日志](publication-privacy.md#验收证据) |
| `.venv/bin/python -m pytest -q --junitxml=docs/evidence/e3/pytest.xml`（验收器执行） | **122 passed，0 failed，0 skipped，1 warning，5.46 秒** | [文本](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据) |
| `node scripts/browser-smoke.mjs`（专用空库） | **10 项检查通过** | [结果 JSON](publication-privacy.md#验收证据)、[日志](publication-privacy.md#验收证据) |
| `NEXT_TELEMETRY_DISABLED=1 pnpm build:web` | 退出 0，Webpack 生产构建成功 | [输出](publication-privacy.md#验收证据) |
| `pnpm typecheck` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/ruff check packages services migrations tests scripts examples adapters` | All checks passed | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/ruff format --check packages services migrations tests scripts examples adapters` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/uv lock --check --offline --cache-dir .local/uv-cache` | 退出 0；未新增依赖 | [输出](publication-privacy.md#验收证据) |
| `pnpm install --frozen-lockfile --offline --store-dir .local/pnpm-store` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/python -m scripts.scan_secrets` | 高置信凭据模式扫描无发现 | [最终扫描](publication-privacy.md#验收证据) |

唯一警告仍为 Starlette TestClient 使用当前锁定 httpx 的弃用提示；未屏蔽，非测试失败。浏览器是既有项目/契约界面回归，不声称已完成 E8 业务 UI。

已查看桌面、390px 窄屏、空状态、契约错误和断网截图；截图无秘密明文或明显布局缺陷。脚本沿用 e2 文件名，E3 图片单独位于 `evidence/e3/browser/`，页面明确显示 E3，没有覆盖历史截图。

## 失败、审阅修正与复验

| 实际问题 | 处理和证据 |
| --- | --- |
| 首次后端测试 2 failed、101 passed：reset 触发器在 contracts 上引用不存在的 run_id | 先分表判断再引用字段；保留 [失败文本](publication-privacy.md#验收证据) 和 [JUnit](publication-privacy.md#验收证据)，最终契约不可变回归通过 |
| 审阅发现收款方一致性布尔结果被后续条件覆盖 | 保留已有条件并补充项目/run/指令绑定、整数类型检查；基于真实记录的负向关联测试通过。未把这项审阅发现伪称为曾经运行失败的测试 |
| 审阅发现 E3 内部标签不应写入 E4 注册规则表 | 改为读取观测时生成 scenario_id 闭环结果；新增检查证明不写入未注册规则，不改变 E2 RuleId/schema |
| 一轮 121 后端测试和服务验证通过后，TypeScript 因 `.next/types/* 2.ts` 重复声明失败 | 已核对重复文件内容哈希一致，保留 [错误输出](publication-privacy.md#验收证据) 和 [该轮日志](publication-privacy.md#验收证据)。停止开发服务后清理可再生 .next，先生产构建再类型检查；最终两项退出 0。没有过滤重复文件或降低类型检查；未断言重复文件的外部成因 |
| 原默认沙箱限制 PostgreSQL/本地进程检查 | 在已授权的本地执行权限范围内运行；权限错误不计通过，仅停止核实属于本任务的进程 |

## 限制与未执行检查

- **E3 必须验收条件无遗留失败项。** 当前仅 fixed 示例和 S01/S02；完整 buggy 缺陷样例、完整规则/归因、S03—S20、故障、并发、取消与自动恢复、input replay、HTML 报告、simctl、完整 UI、第二适配器未验收，保留给 E4—E10。
- Worker 串行、单次认领；进程崩溃可能留下 running/leased，不自动重复可能产生资金副作用的操作。没有宣称 E5 中断恢复能力。
- reset 只允许非运行中的命名空间；跨服务不是原子分布式事务。失败会保留证据并标记 reset_incomplete，恢复后可重试。未实现整项目删除/保留期执行。
- 本机信任模式，无公网访问令牌/SSO/多租户授权；独立 schema 共用开发数据库账号。测试密钥按进程拆分不等于 OS 进程安全隔离。
- 未运行真实客户/staging、实际付款、模型/市场实验、Linux/Windows、实际隔离容器网络或生产部署。没有扩大网络范围或自动使用生产秘密。
- 出站固定 allowlist/DNS/重定向测试已执行，容器固定 IP 仅协议层验证。E3 不支持任意 endpoint 映射、任意 origin 或自定义本机 API 回调端口。
- 高置信凭据扫描及截图检查不是完整安全审计。未扫描生成的秘密文件内容到输出；报告与 trace 仅保存引用/脱敏结果。

## 原始需求与下一阶段

两份输入保持原内容：

- Word SHA-256：`3ef139a1fc05ccab5205f353837e08f83865661fdb7cbc434843da5a82b647f6`。
- 提示词 SHA-256：`def545990ebd371be5b506a2f4a0d42329078ed7d809f6da2158a4c1c2edf1db`。

下一阶段为 E4：完整注册规则、四态归因/Finding、JSON/HTML 报告及 S01—S10 套件。**本次不进入 E4。** 后续需用户明确授权，先读进度、需求映射、原始要求与当前代码/diff。
