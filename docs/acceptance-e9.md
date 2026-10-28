> 公开版说明：以下为历史工程记录摘要。原始日志、截图、CI制品与私有环境材料不随源码发布；相关链接指向[证据范围说明](publication-privacy.md#验收证据)。历史结果不代表公开副本已经重新验收。

# E9 验收记录

日期：2026-10-11（America/Los_Angeles）。范围仅 E9：simctl、受控 CI、本地交付与安全、第二示例。E10、公网/生产发布、外部定时任务与真实客户验证未开展。

## 前置复核与保存

按要求读取 AGENTS、进度、覆盖、决策、V2 Word 和提示词 E1/E9、代码与 diff，先说明方案再开发。AGENTS 仅改“当前只执行 E9”。仓库无提交、文件未跟踪，保存 `.local/e9-baseline/manifest.json` 与 1133 文件副本，保留原始需求和旧验收。核心变动理由在 D048—D054。

E8 重验命令：

```sh
ACCEPTANCE_EVIDENCE_DIR=docs/evidence/e8-recheck .venv/bin/python -m scripts.verify_e8
```

结果：282 passed，0 failed/0 skipped，169.21 秒，1 个既有 Starlette/httpx 弃用 warning；24 浏览器及 2 重启检查、构建/类型/静态/格式/双锁/扫描通过。真实 PostgreSQL 和全部服务重启后历史一致。首次沙箱端口拒绝未执行，获准重试后通过，原错误保留 `e8-recheck/sandbox-not-run.txt`。没有 E8 前置阻碍。

## 命令与干净环境

```sh
# E9 首轮专项：实际服务，六项通过
ACCEPTANCE_EVIDENCE_DIR=docs/evidence/e9-first .venv/bin/python -m scripts.verify_e9 --targeted --tests-only
# 完整候选：289 passed / 1 failed，详见下方修复
ACCEPTANCE_EVIDENCE_DIR=docs/evidence/e9-candidate .venv/bin/python -m scripts.verify_e9
# Schema 修复后的定点复验
.venv/bin/python -m scripts.export_schema
.venv/bin/python -m pytest tests/test_contracts.py::test_exported_schema_matches_versioned_model -q --tb=short
# 独立安装尝试，均保留日志
.venv/bin/python -m scripts.clean_e9 --evidence docs/evidence/e9-clean
.venv/bin/python -m scripts.clean_e9 --evidence docs/evidence/e9-clean-retry
# 第三轮：安装/README/290 后端/24 浏览器通过，登录检查未通过
.venv/bin/python -m scripts.clean_e9 --online --evidence docs/evidence/e9-clean-final
# 登录检查修正后的完整干净环境复验
.venv/bin/python -m scripts.clean_e9 --online --evidence docs/evidence/e9-verified
```

**E9 本机工程验收通过，停止于 E9。** 完整干净环境命令退出 0，2026-10-11 02:45:21 PDT 落盘；CI 退出码补强后的专项流水线退出 0，02:47:31 PDT 落盘。两者证据分别保存，未把重复测试累加为新测试数量。

| 最终检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 新源码/venv/node_modules 安装与 README 启动 | Python 31 个包实际安装；Node 48 个包实际安装，87 条锁定项通过供应链检查；dev.py 启动真实空库/全部服务，已安装 simctl help 通过 | [干净环境](publication-privacy.md#验收证据)、install-python.txt、install-node.txt、readme-startup.txt |
| buggy → fixed input replay → compare | 真实返回 1 → 0 → 0，repair_verified=true | [演示摘要](publication-privacy.md#验收证据) |
| 全套后端 | **290 passed，0 failed/0 skipped，207.36 秒**，1 个既有 Starlette/httpx 弃用 warning | [完整日志](publication-privacy.md#验收证据)、pytest.xml |
| CI 外层退出码补强后 | **8 项 E9 专项复验通过，52.60 秒**，同一既有 warning；0/1/2/3 均原样传播 | [专项日志](publication-privacy.md#验收证据)、[实际退出码](publication-privacy.md#验收证据) |
| 浏览器与重启 | 两轮均 **24 + 5 + 2** 通过；Chrome 155.0.8059.40，桌面/390px，PostgreSQL 与全部服务真实重启，history 完全一致 | 两轮 browser-results/e9-access-results/restart-results.json，各 27 张截图 |
| 完整严格业务 gate | fixed S01—S20，strict=true，suite exit_code=0，无缺证据理由 | [完整套件](publication-privacy.md#验收证据) |
| 构建与依赖 | Next.js production build、TypeScript、Ruff/格式、双锁离线检查通过 | [最终流水线](publication-privacy.md#验收证据) |
| 许可证 | **30 Python + 48 Node** 实际依赖，unknown=[]；项目自身另列，未授权对外开源或分发 | [许可清单](publication-privacy.md#验收证据) |
| 原件/工作区一致 | 原需求、旧迁移、业务规则和双锁哈希不变；139 个运行代码/脚本/测试/锁文件与验收副本一致 | [变更清单](publication-privacy.md#验收证据)、[副本一致性](publication-privacy.md#验收证据) |
| 秘密 | 源码/文本产物高置信模式扫描无命中；182 份最终文本产物与本次 20 个生成秘密精确比对无命中；关键截图目视无秘密 | [导出扫描](publication-privacy.md#验收证据)、[源码扫描](publication-privacy.md#验收证据) |

完整验收通过后仅同步 `scripts/verify_e9.py` 与已有 `tests/test_e9.py` 的 CI 退出码修正到同一干净安装副本；业务实现、Web、依赖和迁移未再变更。再实际运行全部 8 项 E9 专项及完整浏览器/空库迁移/全套 gate/重启/构建/双锁/许可/扫描。完整后端 290 与补强后 8 的范围分别记录，没有将 8 再加成 298 项独立测试。最终综合文件：[完整验收](publication-privacy.md#验收证据)、[CI 补强验收](publication-privacy.md#验收证据)。

补强复验在 `.local/e9-clean-8b66dbbe74b84ea1b275a9ea94a0a4b8` 中执行：

```sh
ACCEPTANCE_EVIDENCE_DIR=.local/e9-ci-final .venv/bin/python -m scripts.verify_e9 --targeted
```

E9 干净验收没有使用原开发 `.env` 和 `.local/postgres`，目录元数据保持；验收只停止自己的服务并清理自己的临时数据库。干净副本的 README 演示库和失败记录保留在 `.local` 供复核，不自动删除用户环境。

clean_e9 新建源码目录、venv、node_modules、PostgreSQL 集群与生成凭据；不复制用户 `.env`、应用数据或秘密。只复用公开下载缓存，仍实际执行 `uv sync --frozen` 和 `pnpm install --frozen-lockfile`。新目录中按 README 启动 dev.py，真实空库迁移，调用已安装 CLI 入口，再执行 buggy → fixed input replay → compare。随后用另一专属 PostgreSQL 空库执行整个 verify_e9，最后只停止自身进程、删除验收临时库。README 演示库保留在隔离副本中供复核。

## CLI、场景与复用证据

所有六个命令有 help 和 simctl-1 JSON。`ci_gates` 与 CLI 同源，原业务四态、历史证据和规则不改写。

| 核验 | 真实执行与产物 |
| --- | --- |
| buggy 业务失败，退出 1 | e9-cli-buggy.json；S01/S02/S04/S12 完整结束，独立账本确认违规 |
| fixed / replay / compare，退出 0 | e9-cli-fixed.json、e9-cli-compare.json；新 provider ID、新响应与修复核验 |
| 基础设施错误，退出 2 | 暂停验收器所有的 provider 进程，真实 preflight 失败；e9-cli-infrastructure.json |
| 必需证据不足，退出 3 | 审计删除指定测试 run 的独立账本观测后，report 撤回通过；e9-cli-evidence-loss.json |
| 预算与取消，退出 3 | 小事件预算实际停止；急停 queued 和已派发任务；e9-cli-budget.json、e9-emergency-stop.json |
| 严格 N/A 不能绕过 | 只选 S01 缺审批适用覆盖为 3；必需检查改为 N/A 的反证为 3；suite 缺选场景为 3 |
| 主示例 S01—S20 | 原完整测试和 ci-fixed-s01-s20.json；故障、并发、取消、实际子进程中断均保留证据 |
| 输入重放与恢复 | 原 10+10 连续 replay、跨 scope/资产完整性反证、真实 SIGKILL、租约/owner 围栏及 PostgreSQL/应用重启 |
| 第二示例 buggy/fixed | e9-second-buggy.json / e9-second-fixed.json；JSON-RPC POST /rpc、独立 credit_note 表、S01—S10，原 APPROVAL_001 检出旧审批漏洞 |

第二示例只证明不同接口上的工程复用；没有第二客户/staging 授权。未实现第二产品的 S11—S20、barrier 或 E6 重放，这些请求明确被拒绝。主示例承担完整 S01—S20/恢复/重放验收。

完整干净演示的项目为 `cb240810-7911-4502-8754-b7d3e5699d04`，buggy run `e2d3131b-5b05-47b3-b724-6ede760d9368`，fixed run `53855ab2-b634-4341-9327-4fd3725459e4`。第二 Adapter 在完整验收中的 buggy run 为 `2af65f1c-6201-4427-a7df-8ddd80e31db2`（1），fixed run 为 `6cd7c8a4-060a-407e-a48e-2e948954b841`（0）；原始 JSON 包含各自项目、契约哈希、wire 和 provider 证据。补强复验另外生成新 ID，不覆盖这些记录。

## 安全与数据生命周期证据

| 要求 | 执行方式 |
| --- | --- |
| 项目/run 隔离 | 真实跨项目/run API 访问拒绝、列表过滤、复合外键拒绝、比较两侧授权、run 范围令牌限制 |
| 出站 allowlist、DNS 与重定向 | SafeHTTP 的操作员 exact-origin/IP 检查、全部 DNS 结果和固定数字 IP；受控解析器/socket 反证验证 rebinding、metadata、重定向和路径逃逸 |
| Webhook 验签、防重放 | 签名时间/原始字节/范围反证，以及 S13/S14 真实 provider 重投、去重、冲突载荷与乱序结果 |
| 访问令牌与权限 | 匿名拒绝、无 registry 失败关闭、read/run/evidence/raw/admin、到期/撤销即时生效；e9-access.json |
| 浏览器会话 | 实际 Chrome 匿名/坏令牌/登录、HttpOnly/Strict cookie、DOM 无令牌、跨 Origin 拒绝、退出后 401；e9-access-results.json |
| 秘密脱敏与 raw 权限 | 请求及反射响应凭据剔除，非法金额/币种仍保留；raw 额外权限、跨 run/项目拒绝、期限到达 404 |
| 保留期与删除 | 零天测试契约实际清理私有副本/trace；项目删除清平台与两个远端，只留元数据审计；审计不可修改 |
| 急停 | 在途任务的 dispatch_started 已持久化后急停，同时取消 queued，断言后者从未派发；恢复需显式操作 |
| 删除失败 | 暂停自有 provider 后删除返回 503，该 run 的平台证据保留；恢复后重试成功 |

协议边界反证与真实 HTTP/进程执行在测试名及记录中区分；未进行公网攻击、安全认证或第三方审计。每轮 pytest.xml 列出实际运行的测试；没有用 SQLite、跳过失败测试或虚构指标。

## 实际失败与修复

1. 首轮 E9 专项六项通过（30.57 秒，1 个既有 warning）。补充两个生命周期/证据反证后，完整候选 289 passed / 1 failed（207.44 秒）。注册第二 Adapter 后导出 JSON Schema 未更新，原 schema 一致性测试检出；重新导出后单项通过，随后完整重验。原候选日志未覆盖。
2. 第一次 clean_e9 在安装前找不到受支持的基础 Python；失败日志在 e9-clean。显式设置已安装 Python 3.12 解释器后，第二次新 venv 安装通过。
3. 第二次 pnpm 安装缺少 nanoid 的离线供应链元数据，失败日志在 e9-clean-retry；没有关闭供应链校验。第三次新副本允许按锁文件下载缺失元数据，安装与供应链校验实际通过。缓存中已有 48 个包归档，本轮不把缓存存在当作安装成功。

4. 第三轮 290 后端（206.95 秒）及 24 原控制台浏览器检查通过，新增登录检查误等待通用 alert、在响应前断言字段已清空而失败。改为等待真实 POST 422 与明确错误文字，再核对字段，未降低断言。原失败保留于 e9-clean-final。
5. 收尾审阅发现 CI 外层异常会折叠 simctl 的非零退出码；改为保留 gate 的 1/2/3，并在真实 API/子进程上新增外层退出码传播验证。详见 e9-ci-exit-codes.json。

## 许可证、限制及未执行项

运行 licenses.py 读取实际安装的 Python/Node 元数据、许可文件及哈希；未知许可使检查失败。LGPL（psycopg/embedded-postgres）、MPL（certifi）、CC-BY（caniuse-lite）等列在 redistribution_review，分发前仍需逐项履行义务，本阶段没有对外分发。原 Python/Node 锁文件保留，不引入模型依赖。

本机环境为 macOS、Python 3.12.14；pnpm 仓库声明/CI 固定 11.19.0，本机预置执行器实际为 11.25.0，日志如实保留，未将其称作 11.19.0 实测。完整安装依赖版本以锁文件和安装日志为准。GitHub/Linux workflow 仅交付配置，未经推送或远端执行；Windows、容器实机、Safari/Firefox、屏幕阅读器、正式 WCAG 审计和大规模性能验证均未执行。

默认 loopback。宿主 OS、开发数据库账号仍是单团队信任边界，不支持托管多租户；令牌工具不是公网 IAM。raw 到期立即拒读，物理清理需管理员调用 retention；活跃 trace 延期，删除跨服务非原子。在线删除不删除手工导出或备份；元数据生命周期审计继续保留。急停不能撤回已执行支付。

没有真实资金、客户/staging、模型服务、自然语言产品或 AI 增量实验；未采集真实客户确认时间、误报或付费意愿。开放探索与夜间任务未启用，没有创建外部定时任务。E10、生产部署、发布和外部推送均未开展。
