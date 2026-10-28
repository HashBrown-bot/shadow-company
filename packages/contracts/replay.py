"""E6 replay requests: no executable configuration and no saved product outputs."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, JsonValue, StrictBool, StrictInt, model_validator

from packages.contracts.config import Identifier, Model

Operation = Literal[
    "request_refund", "approve_refund", "execute_refund", "read_refund", "amend_refund", "cancel_refund"
]


class Precondition(Model):
    kind: Literal["absent_or_same", "object_fields", "visibility_probe"]
    fields: dict[Literal["payment_id", "amount_minor", "currency", "recipient", "version"], JsonValue] = (
        Field(default_factory=dict)
    )

    @model_validator(mode="after")
    def field_types(self):
        for key, value in self.fields.items():
            if key in {"amount_minor", "version"}:
                if type(value) is not int or value < 1:
                    raise ValueError("金额/版本前置条件必须是正整数")
            elif not isinstance(value, str) or not value:
                raise ValueError("业务字段前置条件必须是非空字符串")
        return self


class ActorFixture(Model):
    fixture_id: Identifier
    operation: Operation
    command_id: Identifier
    role: Literal["support", "approver", "customer_a", "customer_b"]
    body: JsonValue = None
    precondition: Precondition
    uses: Annotated[StrictInt, Field(ge=1, le=20)] = 1
    policy: Literal["scripted_v1", "retry_if_unsettled_v1"] = "scripted_v1"

    @model_validator(mode="after")
    def policy_scope(self):
        if self.policy != "scripted_v1" and self.operation != "execute_refund":
            raise ValueError("反馈策略仅支持 execute_refund，其他动作保留脚本策略")
        return self


class ReplayInput(Model):
    project_id: UUID
    mode: Literal["history", "input", "controlled"]
    target_contract_version: Identifier | None = None
    target_product_version: Literal["buggy", "fixed"] | None = None
    idempotency_key: Identifier | None = None
    reuse_product_outputs: StrictBool = False
    actor_fixtures: list[ActorFixture] | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def mode_contract(self):
        if self.reuse_product_outputs:
            raise ValueError("禁止 reuse_product_outputs=true；history 通过只读历史入口展示")
        if self.mode == "history":
            if any(
                x is not None
                for x in [
                    self.target_contract_version,
                    self.target_product_version,
                    self.idempotency_key,
                    self.actor_fixtures,
                ]
            ):
                raise ValueError("history 不接受目标版本、fixture 或新运行参数")
        elif not all([self.target_contract_version, self.target_product_version, self.idempotency_key]):
            raise ValueError("input/controlled 必须明确目标契约、PUT 版本和请求幂等键")
        return self
