"""Domain contracts. Raw observations intentionally do not use Money validation."""

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from .config import (
    Configuration,
    Hash,
    Identifier,
    Model,
    NonNegative,
    PrivateRef,
    RuleId,
    Severity,
    TimeMode,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    NOT_APPLICABLE = "not_applicable"


class Attribution(StrEnum):
    PRODUCT_DEFECT = "product_defect"
    EXPECTED_REJECTION = "expected_rejection"
    ACTOR_ERROR = "actor_error"
    ADAPTER_ERROR = "adapter_error"
    ENVIRONMENT_ERROR = "environment_error"
    DEPENDENCY_FAILURE = "dependency_failure"
    UNDETERMINED = "undetermined"


class Project(Model):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    ownership: Literal["local_team"] = "local_team"
    local_access_policy: Literal["loopback_only"] = "loopback_only"
    created_at: AwareDatetime = Field(default_factory=utcnow)


class Contract(Model):
    project_id: UUID
    version: Identifier
    schema_version: Literal["0.2"] = "0.2"
    content_hash: Hash
    config: Configuration
    created_at: AwareDatetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def verify_digest(self):
        if self.content_hash != self.config.content_hash():
            raise ValueError("契约内容与 content_hash 不一致")
        return self


class Scoped(Model):
    project_id: UUID
    run_id: UUID


class Run(Scoped):
    contract_version: Identifier
    contract_hash: Hash
    put_version: Identifier
    seed: NonNegative
    time_mode: TimeMode
    status: RunStatus = RunStatus.QUEUED
    verdict: Verdict = Verdict.INCONCLUSIVE
    manifest_hash: Hash | None = None
    stop_reason: str | None = None
    created_at: AwareDatetime = Field(default_factory=utcnow)


class Event(Scoped):
    event_id: UUID = Field(default_factory=uuid4)
    parent_id: UUID | None = None
    causation_id: UUID | None = None
    business_object_id: str
    simulation_time: AwareDatetime
    wall_time: AwareDatetime = Field(default_factory=utcnow)
    ingress_sequence: NonNegative
    payload: JsonValue


class Action(Scoped):
    action_id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    actor_id: Identifier
    operation: Literal[
        "request_refund",
        "approve_refund",
        "execute_refund",
        "read_refund",
        "amend_refund",
        "cancel_refund",
        "control",
        "wait",
    ]
    request_ref: PrivateRef
    start_time: AwareDatetime
    end_time: AwareDatetime | None = None


class Observation(Scoped):
    observation_id: UUID = Field(default_factory=uuid4)
    source: Identifier
    external_id: str
    evidence_kind: Literal["product_observation", "dependency_evidence"]
    raw_ref: PrivateRef
    digest: Hash
    captured_at: AwareDatetime = Field(default_factory=utcnow)
    payload: JsonValue


class CheckResult(Scoped):
    check_id: UUID = Field(default_factory=uuid4)
    rule_id: RuleId
    rule_version: Identifier
    object_id: str
    verdict: Verdict
    reason: str = Field(min_length=1)
    evidence_refs: list[UUID]
    evaluated_at: AwareDatetime = Field(default_factory=utcnow)


class Finding(Scoped):
    finding_id: UUID = Field(default_factory=uuid4)
    check_id: UUID
    severity: Severity
    attribution: Attribution
    confirmation: Literal["unconfirmed", "confirmed", "dismissed"]
    dedup_key: str
    expected: JsonValue
    actual: JsonValue
    evidence_refs: list[UUID]
    observed_at: AwareDatetime
    replay_capability: Literal["unavailable", "input", "controlled"]


class Manifest(Scoped):
    schema_version: Literal["0.2"] = "0.2"
    source_run_id: UUID | None = None
    mode: Literal["history", "input", "controlled"]
    target_product_version: Identifier
    environment_version: Identifier
    contract_version: Identifier
    contract_hash: Hash
    ruleset_version: Identifier
    seed: NonNegative
    snapshot_ref: PrivateRef
    snapshot_hash: Hash
    actor_fixture_ref: PrivateRef
    actor_fixture_hash: Hash
    fault_plan_ref: PrivateRef
    fault_plan_hash: Hash
    code_commit: str
    dependency_versions: dict[str, str]
    adapter_version: Identifier
    schedule_ref: PrivateRef
    capability_limits: list[str]
    reuse_product_outputs: Literal[False]
    external_clock_control: bool
    on_fixture_mismatch: Literal["inconclusive"]
    created_at: AwareDatetime = Field(default_factory=utcnow)

    def content_hash(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class RunLease(Scoped):
    owner: Identifier
    expires_at: AwareDatetime
    heartbeat: AwareDatetime
    checkpoint: JsonValue
