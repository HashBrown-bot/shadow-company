> 公开版说明：以下为历史工程记录摘要。原始日志、截图、CI制品与私有环境材料不随源码发布；相关链接指向[证据范围说明](publication-privacy.md#验收证据)。历史结果不代表公开副本已经重新验收。

# 实施进度

更新日期：2026-10-11（America/Los_Angeles）。当前仅 **E10：V2 首版工程审查、必要修复和验收**。修复后核心工程套件及独立安装验收已通过；收尾前端复验、独立后检及真实 viewport 视觉复核也已完成必要检查，最终工程签收为“达到V2首版本机工程验收”，逐项依据见 [发布检查表](release-checklist.md)。前端补验命令曾因 PATH 缺少 uv 退出2，其失败与后续补检分开记录，不合写成整条流水线退出0。不授权公网部署、公开发布、生产访问或真实客户试点，验收后停止。2026-10-11 用户另行授权本地首次提交及 GitHub 私有仓库备份，范围见下方版本管理记录。

## 本地 Git 基线与私有仓库备份

用户确认全部文件未跟踪时空 `git diff` 不能证明没有用户修改，明确授权先检查上传范围、做首次提交，再推送到 GitHub 私有仓库。准备阶段实际确认没有 HEAD、0 个已跟踪文件、2108 个未跟踪候选文件，约401 MB，包含正式历次验收材料；没有符号链接或超过10 MiB的单文件。

保留原始需求、源码、迁移、双锁和正式验收证据；补充 `.gitignore` 的认证/密钥、数据库文件及备份、构建/测试临时输出规则。`git check-ignore --stdin` 实测确认真实 `.env`、`.local/postgres`、阶段本地备份、依赖和临时文件排除，`.env.example`、原需求、迁移、锁文件和正式验收日志保留。配置模板和合成测试夹具不代表真实凭据。初始提交仅固定当前状态，不补造早期提交历史，也不替代历史 SHA-256 保护记录。

本次仅修改版本管理规则和说明，不改应用、业务规则、迁移或锁文件；未重新启动服务或重跑本机业务验收套件，既有 E10 实测结果仍按原记录解释。实际上传范围及检查结果另存于 [首次提交范围核验](publication-privacy.md#验收证据)。首次提交 `c6993819f3ba56d0a2cb4acd34e62e0b210cc716` 已推送至 [HashBrown-bot/shadow-company](https://github.com/HashBrown-bot/shadow-company)，GitHub API 和页面均确认 Private；远程 main 与本地首次提交一致，递归树的2,109个文件路径、模式和blob哈希全部匹配，排除目录未上传，已有 workflow 字节未改。`main` 已关联 `origin/main`。当前仍只执行 E10，不进入下一阶段或生产发布。

首次无HTTPS凭据的推送失败；追加workflow权限的初次自动审批拒绝，随后标准repo/read:org/gist授权成功，但GitHub实际拒绝上传已有 `.github/workflows/regression.yml`。用户明确授权增加workflow权限后，官方CLI刷新授权及完整推送成功。凭据保存在系统keyring，Git helper仅配置本仓库，CLI和配置位于忽略的 `.tools`；无令牌、设备码或认证配置进入提交。完整尝试和核验见 [备份操作记录](publication-privacy.md#验收证据)，[仓库页面截图](publication-privacy.md#验收证据)仅证明当时的Private及首次提交文件列表。

首次push实际触发 [GitHub回归CI](https://github.com/HashBrown-bot/shadow-company/actions/runs/38134784670)，记录时为 `in_progress`、conclusion为空，不能计为通过。此前“外部CI未触发”的说明仅对应私有备份前的本机E10验收；本次CI不改变已有本机验收结果。 文档收尾实际执行 `python3 scripts/scan_secrets.py`，扫描1,743个文本文件、无命中、退出0；`git diff --check` 对本次已跟踪文档差异退出0，新截图已目视复核。

首次完整暂存的 `git diff --cached --check` 实际退出2，发现的空白格式问题全部来自既有工具生成验收日志/JUnit（尾空格或末尾空行）；为保留原始证据不重写这些文件。本次修改的 `.gitignore`、README、进度、决策和新范围报告另作同命令限定文件检查并通过。完整失败范围及处置写入范围核验报告，不把整仓空白检查改记为通过。

## E10 实际执行与结果

先读 AGENTS、进度、需求映射、决策、原 V2 Word、提示词 E1/E10 与实际代码，说明审查方案后核验独立证据。仓库无提交且所有文件未跟踪，保存 `.local/e10-baseline` 的 1775 文件与 SHA-256；[前序源码核对](publication-privacy.md#验收证据)确认进入 E10 时的 139 个运行源码/测试/锁文件与 E9 最终记录一致。E9 的真实安装、JUnit、服务和场景产物仅作前序证据，不充当本轮通过结论。

前序复跑首次受沙箱端口限制未执行；获准后运行时同时发生源码修复，新 Worker 与已启动 API 的版本保护触发 `worker_version_drift`，实际为 **263 passed、14 failed、13 errors、1 warning**。保留 [pytest](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据)；该轮不能计为通过，未关闭版本保护或跳过失败测试。

审查发现的十项问题已修复：审批金额/版本类型、独立初始币种、并发预算 gate、checks 证据权限、RPC wire 收款信息脱敏、裸令牌/对象键清洗、扫描边界、fixture 环境归因、CLI/API/UI 同源 gate、旧运行使用新规则重评时的比较归因。每项触发、位置、影响、修复与反证在 [问题清单](release-checklist.md#按严重度排列的问题与处置)；修前失败日志保留于 [e10-review](publication-privacy.md#验收证据)。业务评估器为 `refund-v2` / Policy 2，严格 gate 为 `e10-gate-2`；旧契约、Manifest、seal 与原始需求不覆盖。

冻结代码后实际执行：

```sh
.venv/bin/python -m scripts.clean_e9 --online --evidence docs/evidence/e10-final
```

`clean_e9` 的名称表示其建立阶段；本轮实际收集全部 E10 新反证与原核心套件。新源码目录、新 venv、新 node_modules 按双锁安装，使用真实 PostgreSQL 空库迁移和独立服务，随后执行 README 的启动、buggy/fixed/input replay/compare 演示。仅复用公开依赖下载缓存；[干净环境结果](publication-privacy.md#验收证据) 与 [综合结果](publication-privacy.md#验收证据) 均为 `passed`。其中 `source_environment_unchanged` 检查的是源 `.env` 与开发数据库相关路径的存在性/元数据，不代表逐字节数据库一致性证明。

- **346 后端 passed，0 failed / 0 errors / 0 skipped，1 warning，220.07 秒**：[实际日志](publication-privacy.md#验收证据)、[JUnit](publication-privacy.md#验收证据)。
- **27 控制台 + 5 登录 + 2 重启检查通过**：[控制台](publication-privacy.md#验收证据)、[登录](publication-privacy.md#验收证据)、[重启](publication-privacy.md#验收证据)。浏览器实际创建项目、预检、运行、查看 Finding、重放及比较；同 run_id 的 API/CLI/UI gate 对照保存在 [一致性证据](publication-privacy.md#验收证据)。
- [fixed S01—S20](publication-privacy.md#验收证据) 为 113 pass、27 not_applicable、0 fail、0 inconclusive；27 个有理由的不适用检查不冒充场景通过。20 场景均执行，严格 [selected/suite gate](publication-privacy.md#验收证据) 都为 0。
- [20 次连续重放](publication-privacy.md#验收证据)：10 次 buggy 失败、10 次 fixed 通过，20 个独立 run、全新证据 ID，源 history 前后哈希相同；每次报告、Manifest、比较单独落盘。规则构建/政策变化阻止仅归因 PUT 的修复确认。
- 第二 JSON-RPC 示例 [buggy](publication-privacy.md#验收证据) / [fixed](publication-privacy.md#验收证据) 分别真实执行 S01—S10，各含 62 个 wire 记录及 17 次 `notes.issue`，共用当前规则；不宣称第二示例具备 S11—S20 或 E6 重放能力。
- 真实 PostgreSQL 18.4 从空库至 0007_e9、迁移/隔离/恢复/清理通过；全部服务及 PostgreSQL 重启后 history 不变。[cleanup](publication-privacy.md#验收证据) 确认验收临时库已删除、自有进程退出、3000/8000/8001/8002/8003/55432 六端口释放。隔离副本的 README 演示库保留复核，开发库不清空。
- 构建、类型、静态、格式、[Python 锁](publication-privacy.md#验收证据)、[Node 锁](publication-privacy.md#验收证据)、[许可证](publication-privacy.md#验收证据)、[文本秘密扫描](publication-privacy.md#验收证据) 均通过。实际 Python 3.12.14、PostgreSQL 18.4、Chrome 155.0.8059.40；实际 pnpm 11.25.0，声明版本 11.19.0，差异如实保留。

## E10 收尾补验与未执行范围

核心通过后还发现两处旧 UI 阶段文案，以及窄屏截图 `fullPage` 取景不能直接代表真实 viewport 的证据展示问题。修正只影响文案/截图采集，实际执行 `ACCEPTANCE_EVIDENCE_DIR=docs/evidence/e10-frontend-final SIM_PNPM_STORE=.local/pnpm-store .venv/bin/python -m scripts.verify_e9 --targeted`：**8 passed、1 warning、53.09秒**，27控制台/5登录/2重启及 build/typecheck/lint/format 均通过；随后 lock-python 因隔离 shell PATH 未包含 uv 而失败，命令整体退出2。[流水线](publication-privacy.md#验收证据)、[pytest](publication-privacy.md#验收证据) 和 [原空 lock 日志](publication-privacy.md#验收证据) 保留。8项为已有测试，不能与346项重复相加。

随后 `.local/e10-frontend-postchecks.py` 显式使用工作区 `.venv/bin/uv` 绝对路径，按原断言独立补跑 Python锁、Node锁、许可证和秘密扫描，四项均退出0，见 [补检结果与实际命令](publication-privacy.md#验收证据)。该成功只证明这四项后检完成，不改变前一条流水线退出2的事实。

最后为运行详情和比较页各新建390×844页面，禁用GPU进行截图质量复核，避免窗口resize导致的截图残影；[两项视觉结果](publication-privacy.md#验收证据) 确认单侧栏、无横向溢出、DOM无令牌且显示真实后端gate，四张截图为 [运行顶部](publication-privacy.md#验收证据)、[运行gate](publication-privacy.md#验收证据)、[比较顶部](publication-privacy.md#验收证据)、[比较gate](publication-privacy.md#验收证据)。[收尾清理](publication-privacy.md#验收证据) 记录开发启动器退出0，六端口分别实际bind成功；仅保留隔离README演示库复核。此项不构成其他浏览器/GPU组合兼容性验收。

没有真实客户/staging、真实资金、真实模型服务、自然语言 PUT 或 AI 增量实验；本机E10验收收尾时外部 GitHub/Linux CI 未实际触发，后续私有备份触发的CI另见上方记录，Windows、容器实机、Safari/Firefox、屏幕阅读器、正式安全/WCAG 审计和大规模性能未执行。默认 loopback、单团队/共享数据库账号；不是公网 IAM 或敌对租户隔离。retention 物理清理需显式调用；跨服务删除非原子、急停不撤回已执行资金。工程验收不等于生产就绪或市场验证；仍需另行授权的真实客户规则确认、接入及持续复用验证。

以下为 **E9 历史阶段记录**，其中完成时间、数量和当时停止边界仅对应 E9。

## E9 历史前置复核与文件保护

先读 AGENTS、进度、覆盖、决策、V2 Word 和提示词 E1/E9、代码与 diff，说明方案后开发。仓库无提交、全文件未跟踪；保存 `.local/e9-baseline` 的 1133 文件与 SHA-256，不能用空 diff 推断没有用户修改。原始需求、旧验收、旧迁移和原业务规则保留，核心差异见 [D048—D054](decisions.md)。

实际复核 E8：282 后端测试（169.21 秒、0 failed/0 skipped、1 个既有 warning）、24 浏览器及 2 重启检查、真实 PostgreSQL/服务重启、构建/类型/静态/格式/双锁/扫描通过，证据在 `docs/evidence/e8-recheck`。首次沙箱不能绑定 loopback 未运行，获准重试通过，原错误保留。没有阻碍本阶段的 E8 缺项；原 E8 最终结果与 25 张截图仍见 [E8 验收](acceptance-e8.md)。

## E9 历史实现

- simctl 六命令：validate、preflight、run、report、replay、compare，安装入口、help、默认机器可读 JSON、明确错误和真实 0/1/2/3 退出码。API 提供统一严格 ci_gates；必需规则全 N/A、缺证据、取消或预算未完成不能通过。
- 本机随机访问令牌、服务器哈希 registry、项目/run/操作权限、到期/撤销；Web 同源登录、HttpOnly/Strict cookie、按当前用户转发。原出站 allowlist、完整 DNS/固定 IP、重定向禁用和 Webhook HMAC/防重放继续回归。
- 0007_e9 新迁移：私有证据期限、元数据生命周期审计、项目急停/删除状态。raw 需要额外权限且到期拒读；管理员 retention/reset/delete 保留审计、远端失败如实返回，急停阻断新运行和后续派发。
- 独立 JSON-RPC 贷项单示例与 rpc_credit_v1，使用不同方法/字段、独立数据表、实际 provider；原五条 Evaluator 不变。只覆盖 S01—S10；更高能力请求拒绝，第二示例仅证明工程复用。
- 等价本地启动器、真实 PostgreSQL/迁移、契约 seed、scope reset、完整 .env.example、README/排障；全新源码/venv/node_modules/数据库验收脚本。无模型 key 可运行核心测试。
- 受控 CI workflow、锁文件核对、实际依赖许可证清单和导出秘密检查；无外部 schedule、发布或推送，开放探索未启用。

## E9 历史最终实际验收结果

首轮新增专项 6 passed（30.57 秒）；补充两项证据/急停/删除失败测试后，完整候选 289 passed / 1 failed（207.44 秒）。失败是第二 Adapter 枚举注册后导出 Schema 未同步，修复并定点通过，原失败日志保留。

干净安装首轮未找到 Python，显式指定已安装基础解释器后第二轮 Python 新 venv 安装通过；Node 离线供应链元数据缺失使第二轮安装失败。没有禁用供应链检查，第三轮在新目录按锁文件联网补取元数据，Python/Node 安装、已安装 simctl 入口、README 真实服务启动和 buggy/fixed/input replay/compare 演示均已通过。第三轮后端 290 和原控制台 24 项通过，但登录检查未等待实际响应而失败；改为等待真实 422 与明确错误文字后，新干净副本完整验收通过。


最终完整干净命令退出 0，02:45:21 PDT 落盘：**290 后端 passed，0 failed/0 skipped，207.36 秒**；24 控制台 + 5 登录 + 2 重启检查通过，共 27 张截图；真实 PostgreSQL 18.4 从空库迁移至 0007_e9、S01—S20 strict suite gate、10+10 重放、真实中断恢复及安全回归通过。PostgreSQL/全部服务重启后 history 一致，构建、类型、静态、格式、双锁、许可证和扫描通过。

随后修正 CI 外层异常折叠退出码的问题。只同步验收器与已有回归用例，在同一隔离安装环境补强复验 **8 项 E9（52.60 秒）**及全部浏览器/重启/构建检查，02:47:31 PDT 退出 0。真实子进程分别验证 0→0、1→1、2→2、3→3；两轮不重复计为 298 项独立测试。当前 139 个运行源码/脚本/测试/锁文件与验收副本一致。

已安装依赖许可识别为 30 Python + 48 Node，未知项为空；LGPL/MPL/CC-BY 分发义务另列。源码与文本扫描无命中，182 个最终文本导出/日志与 20 个本次生成秘密精确比对无命中；目视检查登录、登录后和脱敏证据关键截图。原需求、旧迁移、双锁与原业务规则哈希不变，AGENTS 仅改阶段。

最终证据为 [干净环境结果](publication-privacy.md#验收证据)、[完整结果](publication-privacy.md#验收证据)、[CI 补强结果](publication-privacy.md#验收证据)、[退出码](publication-privacy.md#验收证据)、[变更清单](publication-privacy.md#验收证据) 与 [完整验收记录](acceptance-e9.md)。失败安装、Schema 和登录检查日志均保留。验收器已停止自有服务和临时验收数据库，E9 最终验收只使用隔离副本，原开发数据库未被清空。

## E9 历史限制、未执行与停止边界

默认 loopback、单团队 OS/共享数据库账号，不提供敌对租户或公网 IAM。raw 到期立即拒读；物理 retention 需显式调用，运行中 trace 延期。删除不是跨服务原子事务，已完成远端 reset 不回滚，手工导出/备份不属于在线删除范围；急停不撤回已执行支付。

没有真实客户/staging、真实资金、模型服务、自然语言 PUT 或 AI 增量验证。外部 GitHub/Linux workflow 仅交付配置，未实际触发；Windows、容器实机、Safari/Firefox、屏幕阅读器、正式安全/WCAG 审计和大规模性能未执行。pnpm 声明/CI 为 11.19.0，本机预置执行器为 11.25.0，实际版本见安装日志。

E9 当时已验收并停止，未自动进入 E10。用户随后明确授权本轮 E10，当前结果见本页上方及发布检查表；公网部署、外部发布、生产和真实客户试点仍未授权。
