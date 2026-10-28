# HTTP Adapter

`refund.py` 将 request_refund、approve_refund、execute_refund、read_refund 映射到经预检的示例 PUT，绑定不同角色及项目/run。共享 `SafeHTTP` 检查操作员 allowlist、DNS 结果、固定 IP 连接、路径与重定向。

原始 HTTP 请求响应脱敏、按来源追加存入 PostgreSQL。provider 账本通过评估侧只读身份采集，PUT 凭据文件没有此读取密钥。当前只激活已审阅的 fixed/buggy 本机示例；真实 staging 与任意 action 映射须另行审阅，不自动扩展网络或解析真实秘密。

E6 调用继续走同一 HTTP 路径，记录 PUT 返回的实际版本/构建响应头；服务侧 business_call 审计独立核验调用。前置状态查询为本角色新查询，不读取旧产品 trace 作为新结果。

E9 的 `registry.py` 只根据严格注册 ID 选择 Adapter。`http_refund_v1` 保持原路径；`rpc_credit_v1` 的 `credit.py` 将相同 canonical 动作映射为 JSON-RPC 2.0 的 `POST /rpc` 与贷项单方法/字段，同时保存 wire 请求响应。它只重命名字段，不修复非法值、不产生业务成功结论。

第二示例在 8003 的独立 `credit-note-put` 和 `credit_note` schema 运行，复用独立 provider。其回调目的地由该 project/run 的受限管理配置保存。只声明 S01—S10，E5 故障/barrier 与 E6 replay 请求明确被拒绝；扩展这些能力必须先增加独立证据与验证。第二示例不等于真实客户接入。
