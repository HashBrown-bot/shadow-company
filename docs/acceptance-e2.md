> 公开版说明：以下为历史工程记录摘要。原始日志、截图、CI制品与私有环境材料不随源码发布；相关链接指向[证据范围说明](publication-privacy.md#验收证据)。历史结果不代表公开副本已经重新验收。

# E2 阶段一验收记录

结论：**E2 仓库骨架与需求契约验收通过**。最终综合验收完成于 2026-10-06 17:34（Asia/Shanghai）。结论只覆盖 E2，不代表 V2 全部功能、业务场景或生产就绪。

## 环境

macOS arm64；Python 3.12.14；Node.js 24.19.0；pnpm 11.19.0；uv 0.12.23；真实 PostgreSQL 18.4；本机 Chrome 154.0.8037.98。应用及依赖已锁定。未使用模型 API、客户数据、生产系统或真实付款。

## E2 必须条件

| 条件 | 实际验证 | 结果 |
| --- | --- | --- |
| 仓库与指令 | 初始仅两份需求；建立 AGENTS、Git、架构/决策/进度/REQ01—REQ12 映射 | 通过 |
| 可运行骨架 | Web、API、独立 Worker、PUT/provider 独立健康服务、PostgreSQL 均启动 | 通过 |
| 健康检查 | API 200，database=ready，migration=0001_e2；数据库失效返回 503 | 通过 |
| 空库迁移 | 临时 PostgreSQL 空库升级、重复升级、降级、再次升级；10 张业务表和版本表 | 通过 |
| 附录 B 解析 | 原样 YAML schema 0.2 成功，保存规范内容 SHA-256 | 通过 |
| 缺 provider_ledger | HTTP 422，错误定位 product.observations.provider_ledger | 通过 |
| 非法预算 | 负数、浮点、字符串和布尔值拒绝；真实 HTTP 负预算返回 422 | 通过 |
| 不支持 mode | controlled/time_travel/input 不作为当前 time_mode 接受；真实 HTTP 422 | 通过 |
| 严格字段与规则 | 缺角色、未知字段、规则 ID/版本/参数错误、重复 YAML 键、非法标签均拒绝 | 通过 |
| 契约版本保护 | 相同内容幂等；不同内容 409；并发写仅一个成功；DB 禁止覆盖/删除 | 通过 |
| 核心模型 | 九个必需模型及 RunLease；金额/币种明确，状态与四态结论分离 | 通过 |
| 原始值与范围 | 非法余额/币种原样入库；观测不可修改；跨项目作业引用拒绝 | 通过 |
| 本地配置与秘密 | 默认 loopback，样例无实际秘密；凭据模式扫描零发现；错误 canary 不回显 | 通过 |

附录 B 规范内容哈希：`ae52e1673302981a8f91d3cea1f466d4d4f09baa6477fd03f44a9673c5f0bb65`。

## 命令与真实结果

| 命令（项目根） | 实际结果 | 证据 |
| --- | --- | --- |
| `.venv/bin/python -m scripts.verify_e2` | 退出 0；后端、停止/重启、专用空库浏览器验收通过 | [运行记录](publication-privacy.md#验收证据)、[启动记录](publication-privacy.md#验收证据) |
| `.venv/bin/python -m pytest -q --junitxml=docs/evidence/pytest-e2.xml`（验收器执行） | **89 passed，0 failed，0 skipped，1 warning，0.85 秒** | [文本](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据) |
| `node scripts/browser-smoke.mjs`（验收器执行） | **10 项检查通过**，无浏览器运行时异常 | [JSON](publication-privacy.md#验收证据)、[日志](publication-privacy.md#验收证据) |
| `pnpm typecheck` | 退出 0 | [类型检查](publication-privacy.md#验收证据) |
| `NEXT_TELEMETRY_DISABLED=1 pnpm build:web` | Next.js Webpack 生产构建退出 0 | [构建输出](publication-privacy.md#验收证据) |
| `.venv/bin/ruff check packages services migrations tests scripts examples` | All checks passed | [静态检查](publication-privacy.md#验收证据) |
| `.venv/bin/ruff format --check packages services migrations tests scripts examples` | 31 files already formatted | [静态检查](publication-privacy.md#验收证据) |
| `.venv/bin/uv lock --check --offline --cache-dir .local/uv-cache` | 33 packages resolved，退出 0 | 本次工具执行记录 |
| `pnpm install --frozen-lockfile --offline --store-dir .local/pnpm-store` | Lockfile up to date，退出 0 | 本次工具执行记录 |
| `.venv/bin/python -m scripts.scan_secrets` | 零发现 | [扫描结果](publication-privacy.md#验收证据) |

唯一警告为 Starlette TestClient 对 httpx 的弃用提示；当前锁定组合可运行且全部断言通过。未屏蔽警告，后续依赖升级时处理。

浏览器覆盖真实健康、键盘跳过链接/焦点、空状态、项目创建/刷新/后端核对、配置校验/哈希、缺账本错误、390px 无水平溢出、断网恢复、跨来源写入拒绝和运行时异常。断网项明确为浏览器网络故障注入，其他主要路径访问真实 API 与 PostgreSQL。

截图已人工查看：[桌面](publication-privacy.md#验收证据)、[窄屏](publication-privacy.md#验收证据)、[空状态](publication-privacy.md#验收证据)、[契约错误](publication-privacy.md#验收证据)、[断网](publication-privacy.md#验收证据)。

## 实际失败与修复

| 发生情况 | 处理与复验 |
| --- | --- |
| 默认沙箱网络、PostgreSQL 共享内存与 loopback TCP 受限 | 按已有授权流程执行安装和本地测试，权限失败未算通过 |
| pnpm 11 构建许可写法不兼容，随后重复 YAML key | 改为 allowBuilds，移除自动生成的重复待决项；安装和 frozen offline 复验成功 |
| 首次 pytest 无法导入 tests 包 | 增加测试包初始化；保留断言，测试从 67、84 扩展至 89 项通过 |
| Web 启动探测超时 | loopback 探测绕过 macOS 系统代理，真实启动与浏览器均正常 |
| 创建项目误返回 403 | 修正 Next 请求 Origin/Host 核对；正向创建和跨来源拒绝均通过 |
| 会话中断后数据库停止、Web/API 子进程残留；两次复验连接失败 | 两次均为 1 failed、72 passed、16 errors；核实清理残留并增加端口检查。原始输出保存在 `.local/logs/pytest-db-unavailable.*` 与 `pytest-port-conflict.*` |
| 温重启将 TIME_WAIT 误报为端口占用 | 端口探测使用 SO_REUSEADDR；完整验收验证冲突拒绝、停止释放和重启持久化 |
| 辅助脚本直接执行受 editable-import 行为影响 | 文档改为根目录 `python -m scripts...`；校验/导出/扫描/验收器已实际运行 |
| 审阅发现未知规则 ID 的错误可能回显输入 | 改写消息，新增秘密 canary 断言；最终 89 项测试通过 |

## 未完成项与限制

- **E2 必须条件无遗留失败项。** Worker 执行、PUT/provider 业务和账本仍是后续边界。
- E3—E10 未执行；S01—S20 尚未进行业务验收。无预检、Webhook、资金评估、故障、barrier、恢复、重放、报告、simctl 或第二 Adapter。
- 仅 schema 0.2；不支持 controlled、LLM、任意币种/适配器。旧 schema 明确拒绝，不猜测迁移。
- 访问令牌、完整授权、统一出站策略执行、Webhook 验签、秘密解析/私有对象存储、retention/reset 删除尚未实现。本地 trust 只适用于本机开发。
- 扫描覆盖源码及文本证据的高置信凭据模式，结合截图人工查看，不等于完整安全审计。未提供或读取真实凭据。
- 本机验证为 macOS arm64。Linux/Windows、已有外部 PostgreSQL 启动路径、真实客户/市场/模型实验未运行，不声称其通过。
- 普通终止已验证清理；SIGKILL 可能残留进程，需核实身份再清理。

## 原始需求与下一阶段

两份输入原文保留；交付时 SHA-256：

- Word：`3ef139a1fc05ccab5205f353837e08f83865661fdb7cbc434843da5a82b647f6`
- 提示词 Markdown：`def545990ebd371be5b506a2f4a0d42329078ed7d809f6da2158a4c1c2edf1db`

下一阶段 E3：在当前骨架上实现独立 PUT/provider 和 S01/S02，证明真实调用后产生可追溯的独立账本。当前停在 E2，不自动扩展。
