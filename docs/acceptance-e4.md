> 公开版说明：以下为历史工程记录摘要。原始日志、截图、CI制品与私有环境材料不随源码发布；相关链接指向[证据范围说明](publication-privacy.md#验收证据)。历史结果不代表公开副本已经重新验收。

# E4 阶段三验收记录

结论：**E4 规则评估与四态报告验收通过，S01—S10 完成**。最终综合验收从 2026-10-07 12:07:12（Asia/Shanghai）开始，命令退出 0。只覆盖本机示例与本阶段；不代表 E5—E10、S11—S20、真实客户或生产部署完成。

## 前置复核与保留范围

用户明确授权从 E3 进入 E4，AGENTS 仅改当前阶段。先核对 V2 Word、E1/E4、进度、覆盖、决策和实际代码/diff。仓库无提交、文件均未跟踪，保存 `.local/e4-baseline` 作逐文件核对，不以空 diff 判断没有用户修改。未覆盖两份原需求和附录 B，也未改写 E2/E3 历史验收。

开发前实际复跑 E3：122 passed、0 failed、0 skipped；10 浏览器检查、真实 PostgreSQL 与所有服务停止重启、构建、类型、静态、双锁检查通过。没有阻碍 E4 的前置缺项。[E3 复核输出](publication-privacy.md#验收证据) 和 [后端输出](publication-privacy.md#验收证据) 独立保留。

## 用户验收项

| 条件 | 实际证据 | 结果 |
| --- | --- | --- |
| 正确实现无误报，合法部分退款通过 | fixed 全 S01—S10；S06 同支付 6000+4000；11 条独立示例成功账本 | 通过，0 Finding |
| 重复执行、失效审批正确触发 | buggy S05 两个成功 entry_id → REFUND_001；S04 改金额/版本后旧审批执行 → APPROVAL_001 | 通过 |
| 超额、币种错配不通过 | buggy S07 6000+5000 超 10000 → REFUND_002；CNY/USD 错配反证 fail；fixed 实际拒绝错误币种 | 通过 |
| 缺必需证据为 inconclusive | 移除持久账本后重新查询 run/report；缺最终查询、身份、审批请求、回调；取消/预算不足 | 通过，不沿用缓存成功 |
| 阈值两侧和相等 | 199999、200000 无需大额审批，200001 必须有效审批；真实执行与协议边界测试 | 通过 |
| 至少 S01—S10 | fixed 全部实际发出场景动作；S09 低权限审批、S10 客户查他人退款实际到达 PUT | 通过，详细映射见覆盖表 |
| 产品 success 但 provider 无执行 | PUT 内 false_success 行为返回 succeeded，真实 provider 空账本；STATE_001 fail | 通过 |
| provider 执行两次但产品声明一次 | S05 独立两条记录；REFUND_001 与 STATE_001 fail | 通过 |
| TIME_001 不提前 fail | 窗口前、恰好期限、期限后；证据不全及晚到终态无转移时间时 inconclusive | 通过，协议层时间反证 |
| 冲突/非法原始值保留 | 相同签名事件不同值保存双方、409；负数/浮点业务回调保存后 422；报告不可继续 pass | 通过 |
| Finding 归因、确认、去重 | 角色/Adapter/环境/依赖错误不自动归产品；稳定 ID；同支付超额合并；旧快照不覆盖 | 通过 |
| PostgreSQL 与迁移 | 空库、重复升级、含 E3 数据升级、降级/再升级、范围外键与不可变约束 | 通过，未使用 SQLite |
| 持久化 | PostgreSQL 与 API/Worker/PUT/provider/Web 全部重启，账本、观测、检查、evaluation_id 与 Finding 不变 | 通过 |
| JSON/HTML | 同一后端结果、范围/版本/规则/引用/未验证/失败链/预算/限制，转义/CSP、桌面/390px | 通过，无 readiness 分数 |

S11—S20 完整故障/并发/恢复没有执行。协议层负向观测与真实独立服务测试在测试文件和记录中区分，不能用协议替身声称真实资金、E5 时钟控制或并发验收。

## 可追溯运行

最终 fixed 项目 `f40ae9b8-9d61-4e4b-82d3-d54b42dbec3c`，run `6ec51113-489c-4aac-8707-673246eea5bb`，evaluation `32449df8-bd34-493f-81b9-d451278dd709`：`status=completed`、所选范围 `pass`，80 条规则检查为 65 pass、15 条附契约理由的 not_applicable，0 fail、0 inconclusive，完整套件 gate 为 inconclusive。

最终 buggy 项目 `74677ce0-08f4-4de9-9ef8-64a8535a412f`，run `0729f27b-f86d-4010-801a-1d6eb4e31c0c`：`status=completed`、`verdict=fail`。80 条检查中 5 fail、61 pass、14 not_applicable。去重后 4 个 Finding：3 critical（失效审批、重复执行、累计超额）和 1 high（产品声明与重复执行冲突）。两条 REFUND_002 检查针对同一 payment-S07 合并为一个 Finding；跨规则后果不声称是不同源码根因。

S05 独立执行 ID：`b78731a7-7d45-473d-80d2-f82d8c5ef885` 与 `d7848e86-68b5-46da-ad36-986ce28903d6`，均由 PUT 经 HTTP 调用独立 provider 新生成。不是 fixture 标签或硬编码答案。

完整 [运行/重启/reset 记录](publication-privacy.md#验收证据)、[fixed HTML](publication-privacy.md#验收证据)、[buggy HTML](publication-privacy.md#验收证据)、[false_success 原始证据](publication-privacy.md#验收证据) 可复核。演示临时库在验收结束清理；这些脱敏文件为保留产物。

fixed 实际记录 65 次预算事件，墙钟耗时 1.261 秒；buggy 为 1.344 秒。包含发生器、HTTP、持久化与 1 秒观察等待，不是 PUT 性能基准。模型调用/token 均为 0，未估算基础设施成本。

## 最终命令与输出

从项目根执行；完整入口需要相关本机端口空闲。

| 命令 | 实际结果 | 原始证据 |
| --- | --- | --- |
| `.venv/bin/python -m scripts.verify_e4` | 退出 0，全部综合检查完成 | [综合日志](publication-privacy.md#验收证据)、[启动日志](publication-privacy.md#验收证据) |
| `.venv/bin/python -m pytest -q --junitxml=docs/evidence/e4/pytest.xml`（验收器执行） | **187 passed、0 failed、0 skipped、1 warning，17.83 秒** | [文本](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据) |
| `node scripts/browser-smoke.mjs`（独立空验收库） | **10 项检查通过** | [结果](publication-privacy.md#验收证据) |
| `node scripts/report-browser.mjs` | **5 项检查通过**：fixed/buggy、证据锚点、390px、无运行时错误 | [结果](publication-privacy.md#验收证据) |
| `NEXT_TELEMETRY_DISABLED=1 pnpm build:web` | Webpack 生产构建退出 0 | [输出](publication-privacy.md#验收证据) |
| `pnpm typecheck` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/ruff check packages services migrations tests scripts examples adapters` | All checks passed | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/ruff format --check packages services migrations tests scripts examples adapters` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/uv lock --check --offline --cache-dir .local/uv-cache` | 退出 0，无新增依赖 | [输出](publication-privacy.md#验收证据) |
| `pnpm install --frozen-lockfile --offline --store-dir .local/pnpm-store` | 退出 0 | [输出](publication-privacy.md#验收证据) |
| `.venv/bin/python -m scripts.scan_secrets` | 源码和文本产物高置信凭据模式无发现 | [输出](publication-privacy.md#验收证据) |

唯一 warning 为既有 Starlette/httpx TestClient 弃用提示，未屏蔽。基础 Web 是已有项目/契约入口回归，不是 E8 完整 UI。已查看 fixed/buggy HTML 桌面与窄屏截图，表格横向滚动、证据锚点和报告内容可用；原始观测折叠显示，不依赖脚本或外部资源。

## 失败、修复与未执行记录

| 实际问题 | 修复与保留证据 |
| --- | --- |
| 1 failed / 121 passed：旧 E3 凭据集合断言缺新增客户身份 | 更新准确角色集合，保留 PUT 无 provider_reader/provider_admin 的限制；[失败输出](publication-privacy.md#验收证据) |
| 1 failed / 37 passed：缺最终产品查询误报产品失败 | 改为来源证据不足，不推断未观察到的产品状态；[失败输出](publication-privacy.md#验收证据) |
| 2 failed / 44 passed：非法审批结构和布尔版本未阻断通过 | 补齐原始字段类型/合法性反证，未修正原始观测；[失败输出](publication-privacy.md#验收证据) |
| HTML 窄屏虽无页面溢出但过度折字 | 固定列宽、短证据编号、表格横向滚动，重新查看截图和运行浏览器检查 |
| 审阅发现时间/覆盖/持久结果/回调边界 | 补充晚到终态不确定、缺重复动作不算覆盖、Finding 稳定 ID/历史保存、已验签非法业务回调保留；全部新增测试通过 |
| E3 兼容性 | 保持未显式选择 E4 的原请求键哈希；旧请求与显式 e3_smoke 重试指向同一 run，测试通过 |
| 本机沙箱/自动审批服务 | 首次端口绑定被沙箱拒绝；按授权执行。一次审批服务额度异常导致命令未执行，用户要求继续后恢复；未计入通过、未绕过审批 |

没有空测试、硬编码 PASS、跳过失败、降低断言或把计划当执行证据。初版完整通过之后的复验仅因上述新修正/新增反证进行。

## 限制与下一阶段

- **E4 必须验收条件无遗留失败项。** 串行重复执行、PUT 内缺陷选择、协议规则反证不等同 E5 的提交后响应丢失、故障命中、乱序调度、barrier、取消或恢复。
- 本机示例采用 gt 200000 与部分退款政策；CNY/USD 场景验证按币种隔离。未知产品、不同权限语义、任意 staging 需要另行接入审阅。
- API 信任本机用户，三个 schema 共用开发数据库账号；没有公网认证、数据库/OS 最小权限隔离或完整安全审计。扫描只是高置信模式检查。
- Worker 中断后的 leased 作业不自动重领；reset 不是跨服务原子事务。无 E6 input replay、E7 模型实验、E8 完整业务 UI、E9 simctl/第二适配器或 E10 发布验收。
- 未执行真实客户/staging、实际付款、模型/市场实验、Linux/Windows、容器实机与生产部署。

原始 Word SHA-256：`3ef139a1fc05ccab5205f353837e08f83865661fdb7cbc434843da5a82b647f6`；提示词 SHA-256：`def545990ebd371be5b506a2f4a0d42329078ed7d809f6da2158a4c1c2edf1db`。附录 B 和双锁文件保持不变。

下一阶段 E5 需要用户新的明确授权。**本次停止于 E4，不自动继续。**
