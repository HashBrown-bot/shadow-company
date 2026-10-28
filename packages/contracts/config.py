"""Version 0.2 configuration contract. Validation never contacts the PUT."""

import hashlib
import json
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


NonNegative = Annotated[StrictInt, Field(ge=0)]
Positive = Annotated[StrictInt, Field(gt=0)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SecretRef = Annotated[str, StringConstraints(pattern=r"^secret://[A-Za-z0-9_/-]+$")]
PrivateRef = Annotated[str, StringConstraints(pattern=r"^private://[A-Za-z0-9_./-]+$")]
Currency = Literal["CNY", "USD", "EUR", "JPY"]
TimeMode = Literal["realtime", "event_compressed"]
RuleId = Literal["REFUND_001", "REFUND_002", "APPROVAL_001", "STATE_001", "TIME_001"]
Severity = Literal["critical", "high", "medium", "low"]


class Money(Model):
    amount_minor: NonNegative
    currency: Currency


class Environment(Model):
    id: Literal["refund_approval"]
    version: Identifier
    business_timezone: str
    currency: Currency
    approval_threshold_minor: NonNegative
    threshold_operator: Literal["gt"]
    partial_refunds_allowed: StrictBool

    @field_validator("business_timezone")
    @classmethod
    def timezone_exists(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("business_timezone 必须是有效 IANA 时区") from None
        return value


class Credentials(Model):
    support: SecretRef
    approver: SecretRef

    @model_validator(mode="after")
    def distinct_roles(self):
        if self.support == self.approver:
            raise ValueError("客服和审批人必须使用不同身份引用")
        return self


def relative_path(value: str) -> str:
    parsed = urlsplit(value)
    if (
        not value.startswith("/")
        or value.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or ".." in value
        or "\\" in value
        or "%" in value
    ):
        raise ValueError("必须是无查询串的绝对接口路径，不能是 URL 或目录穿越")
    return value


class Endpoint(Model):
    path: str
    _path = field_validator("path")(relative_path)


class RequestRefund(Endpoint):
    method: Literal["POST"]
    semantic: Literal["create_application"]


class ApproveRefund(Endpoint):
    method: Literal["POST"]
    semantic: Literal["approve_snapshot"]


class ExecuteRefund(Endpoint):
    method: Literal["POST"]
    semantic: Literal["request_execution"]


class ReadRefund(Endpoint):
    method: Literal["GET"]
    semantic: Literal["observe_application"]


class Actions(Model):
    request_refund: RequestRefund
    approve_refund: ApproveRefund
    execute_refund: ExecuteRefund
    read_refund: ReadRefund


class ObservationSources(Model):
    product_query: Literal["required"]
    provider_ledger: Literal["required"]
    webhook: Literal["required"]


class Reset(Model):
    strategy: Literal["run_namespace"]
    endpoint: str
    scope: Literal["run_id"]
    _endpoint = field_validator("endpoint")(relative_path)


class Target(Model):
    base_url: str

    @field_validator("base_url")
    @classmethod
    def safe_url_shape(cls, value):
        try:
            url = urlsplit(value)
            port = url.port
        except ValueError:
            raise ValueError("base_url 格式无效") from None
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
            or port == 0
            or any(c.isspace() for c in value)
            or "\\" in value
        ):
            raise ValueError("base_url 必须是 HTTP(S) origin；凭据只能用 secret:// 引用")
        return value.rstrip("/")


class Product(Target):
    id: Identifier
    version: Identifier
    adapter: Literal["http_refund_v1", "rpc_credit_v1"]
    responsibility: Literal["approval_and_execution"]
    credentials: Credentials
    actions: Actions
    observations: ObservationSources
    reset: Reset
    clock_support: Annotated[list[TimeMode], Field(min_length=1)]


class Provider(Target):
    adapter: Literal["payment_stub_v1"]
    ledger_path: str
    reset_path: str
    idempotency_scope: Literal["tenant_and_idempotency_key"]
    _paths = field_validator("ledger_path", "reset_path")(relative_path)


class Runtime(Model):
    seed: Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]
    time_mode: TimeMode
    max_events: Positive
    max_wall_seconds: Positive
    max_concurrency: Annotated[StrictInt, Field(gt=0, le=64)]
    max_action_retries: NonNegative


class Actor(Model):
    strategy: Literal["rule"]


class Actors(Model):
    customer: Actor
    support: Actor
    approver: Actor


class LLM(Model):
    enabled: StrictBool
    max_calls: NonNegative
    max_tokens: NonNegative

    @model_validator(mode="after")
    def disabled_until_e7(self):
        if self.enabled or self.max_calls or self.max_tokens:
            raise ValueError("schema 0.2 保留无模型 rule 契约，LLM 必须关闭且预算为 0；E7 使用独立角色策略")
        return self


class RefundOnceParams(Model):
    max_success_per_command: Annotated[StrictInt, Field(ge=1, le=1)]


class RefundBalanceParams(Model):
    currency: Currency


class ApprovalParams(Model):
    threshold_minor: NonNegative
    operator: Literal["gt"]


class TimeParams(Model):
    observation_wall_seconds: Positive


class RuleBase(Model):
    version: Literal["1"]


class RefundOnce(RuleBase):
    id: Literal["REFUND_001"]
    params: RefundOnceParams


class RefundBalance(RuleBase):
    id: Literal["REFUND_002"]
    params: RefundBalanceParams


class Approval(RuleBase):
    id: Literal["APPROVAL_001"]
    params: ApprovalParams


class State(RuleBase):
    id: Literal["STATE_001"]
    params: Model = Field(default_factory=Model)


class Time(RuleBase):
    id: Literal["TIME_001"]
    params: TimeParams


Rule = Annotated[RefundOnce | RefundBalance | Approval | State | Time, Field(discriminator="id")]


class FaultMatch(Model):
    scenario_id: Annotated[str, StringConstraints(pattern=r"^S(0[1-9]|1[0-9]|20)$")]
    attempt: Positive


class Fault(Model):
    id: Identifier
    boundary: Literal[
        "provider_response",
        "provider_connection",
        "provider_webhook",
        "provider_request",
        "actor_availability",
    ]
    match: FaultMatch
    behavior: Literal[
        "commit_then_timeout",
        "connection_failure",
        "webhook_duplicate",
        "webhook_reorder",
        "rate_limit",
        "approver_offline",
    ]

    @model_validator(mode="after")
    def fault_boundary(self):
        expected = {
            "commit_then_timeout": "provider_response",
            "connection_failure": "provider_connection",
            "webhook_duplicate": "provider_webhook",
            "webhook_reorder": "provider_webhook",
            "rate_limit": "provider_request",
            "approver_offline": "actor_availability",
        }
        if self.boundary != expected[self.behavior]:
            raise ValueError("故障 behavior 与 boundary 不匹配")
        return self


class Gate(Model):
    fail_on_severity: Annotated[list[Severity], Field(min_length=1)]
    required_checks: Annotated[list[RuleId], Field(min_length=1)]
    inconclusive: Literal["block"]


class Artifacts(Model):
    redact_secrets: StrictBool
    trace_retention_days: NonNegative
    raw_retention_days: NonNegative

    @field_validator("redact_secrets")
    @classmethod
    def redaction_required(cls, value):
        if not value:
            raise ValueError("秘密脱敏不能关闭")
        return value


class Configuration(Model):
    schema_version: Literal["0.2"]
    environment: Environment
    product: Product
    provider: Provider
    runtime: Runtime
    actors: Actors
    llm: LLM
    rules: Annotated[list[Rule], Field(min_length=1)]
    faults: list[Fault]
    suite: Literal["refund_core_20"]
    gate: Gate
    artifacts: Artifacts

    @model_validator(mode="after")
    def cross_field_invariants(self):
        if self.runtime.time_mode not in self.product.clock_support:
            raise ValueError("runtime.time_mode 不在 product.clock_support 声明的能力中")
        ids = [rule.id for rule in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("rules 中不能重复注册规则 ID")
        if not set(self.gate.required_checks) <= set(ids):
            raise ValueError("gate.required_checks 必须引用已配置规则")
        if not {"REFUND_001", "REFUND_002", "APPROVAL_001"} <= set(self.gate.required_checks):
            raise ValueError("refund_core_20 必须包含三项资金与审批 gate")
        if len({fault.id for fault in self.faults}) != len(self.faults):
            raise ValueError("faults.id 不能重复")
        for rule in self.rules:
            if isinstance(rule, RefundBalance) and rule.params.currency != self.environment.currency:
                raise ValueError("REFUND_002 币种必须与 environment.currency 一致")
            if isinstance(rule, Approval) and (
                rule.params.threshold_minor != self.environment.approval_threshold_minor
                or rule.params.operator != self.environment.threshold_operator
            ):
                raise ValueError("APPROVAL_001 阈值必须与环境规则一致")
        return self

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


class ConfigSyntaxError(ValueError):
    pass


def safe_validation_errors(errors):
    """Exclude input/context and redact discriminator diagnostics that echo input."""
    result = []
    for error in errors:
        message = error["msg"]
        if error["type"] == "union_tag_invalid":
            message = "规则 ID 未注册；只允许 REFUND_001、REFUND_002、APPROVAL_001、STATE_001、TIME_001"
        result.append(
            {
                "path": ".".join(str(part) for part in error["loc"]),
                "type": error["type"],
                "message": message,
            }
        )
    return result


class UniqueSafeLoader(yaml.SafeLoader):
    """Reject aliases, duplicate keys and executable YAML tags."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ConfigSyntaxError("YAML 不允许 alias/anchor 引用")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in mapping:
                raise ConfigSyntaxError("YAML 字段必须是唯一字符串，不能重复覆盖")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def parse_yaml(text: str) -> Configuration:
    if len(text.encode()) > 128 * 1024:
        raise ConfigSyntaxError("配置不得超过 128 KiB")
    try:
        data = yaml.load(text, Loader=UniqueSafeLoader)
    except (yaml.YAMLError, RecursionError):
        raise ConfigSyntaxError("YAML 语法无效或使用了不允许的标签") from None
    return Configuration.model_validate(data)
