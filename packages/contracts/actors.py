"""E7 run policy, separate from immutable v0.2 business contracts.

No URLs, executable tools, credentials or evaluator settings are accepted from actors.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, StringConstraints, TypeAdapter, model_validator

from packages.contracts.config import Identifier, Model, NonNegative

Role = Literal["customer_a", "customer_b", "support", "approver"]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class ModelBudget(Model):
    max_calls: Annotated[StrictInt, Field(ge=0, le=1000)] = 0
    max_tokens: Annotated[StrictInt, Field(ge=0, le=1000000)] = 0
    max_output_tokens: Annotated[StrictInt, Field(ge=1, le=4096)] = 512
    min_call_interval_ms: Annotated[StrictInt, Field(ge=0, le=60000)] = 1000
    max_repairs: Annotated[StrictInt, Field(ge=0, le=2)] = 1


class ActorPolicy(Model):
    schema_version: Literal["e7-actors-1"] = "e7-actors-1"
    strategy_version: Literal["hybrid-visible-v1"] = "hybrid-visible-v1"
    mode: Literal["rule", "hybrid"] = "rule"
    model_enabled: StrictBool = False
    adapter: Literal["disabled", "protocol_test"] = "disabled"
    model_id: Literal["none", "protocol-test/actions-v1"] = "none"
    budget: ModelBudget = Field(default_factory=ModelBudget)

    @model_validator(mode="after")
    def available_adapter(self):
        if self.model_enabled:
            if (self.mode, self.adapter, self.model_id) != (
                "hybrid",
                "protocol_test",
                "protocol-test/actions-v1",
            ):
                raise ValueError("本次只开放明确标记的离线协议替身；真实服务需另行授权与接入")
        elif self.adapter != "disabled" or self.model_id != "none":
            raise ValueError("模型关闭时 adapter=disabled、model_id=none")
        return self


class ReadArguments(Model):
    command_id: Identifier


class MessageArguments(ReadArguments):
    text: ShortText


class WaitArguments(Model):
    milliseconds: Annotated[StrictInt, Field(ge=1, le=1000)]


class ReadAction(Model):
    role: Role
    tool: Literal["read_refund"]
    arguments: ReadArguments


class MessageAction(Model):
    role: Role
    tool: Literal["send_message"]
    arguments: MessageArguments


class WaitAction(Model):
    role: Role
    tool: Literal["wait"]
    arguments: WaitArguments


StructuredAction = Annotated[ReadAction | MessageAction | WaitAction, Field(discriminator="tool")]
ACTION_SCHEMA = TypeAdapter(StructuredAction)


class ExperimentInput(Model):
    project_id: UUID
    contract_version: Identifier
    idempotency_key: Identifier
    seeds: Annotated[
        list[Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]], Field(min_length=1, max_length=10)
    ]
    scenarios: Annotated[
        list[Annotated[str, StringConstraints(pattern=r"^S(0[1-9]|1[0-9]|20)$")]],
        Field(min_length=1, max_length=20),
    ]
    model_budget: ModelBudget = Field(default_factory=ModelBudget)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.seeds)) != len(self.seeds) or len(set(self.scenarios)) != len(self.scenarios):
            raise ValueError("seed 与场景列表不能重复")
        return self


class FindingReview(Model):
    project_id: UUID
    run_id: UUID
    finding_id: UUID
    decision: Literal["confirmed", "false_positive"]
    root_cause_id: Identifier | None = None
    reviewer: Identifier
    human_seconds: NonNegative | None = None

    @model_validator(mode="after")
    def root_cause(self):
        if (self.decision == "confirmed") != (self.root_cause_id is not None):
            raise ValueError("确认独立缺陷需要人工根因组；误报不填写根因组")
        return self
