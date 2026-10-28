from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.contracts.config import Configuration
from packages.contracts.domain import Contract, Manifest, Observation, Run, RunStatus, Verdict


def test_lifecycle_is_not_verdict():
    run = Run(
        project_id=uuid4(),
        run_id=uuid4(),
        contract_version="v1",
        contract_hash="a" * 64,
        put_version="fixed",
        seed=1,
        time_mode="realtime",
        status=RunStatus.COMPLETED,
    )
    assert run.verdict == Verdict.INCONCLUSIVE
    assert set(Verdict) == {"pass", "fail", "inconclusive", "not_applicable"}
    with pytest.raises(ValidationError):
        Run(**(run.model_dump() | {"status": "pass"}))


def test_raw_observation_preserves_illegal_business_values():
    observation = Observation(
        project_id=uuid4(),
        run_id=uuid4(),
        source="put_query",
        external_id="r1",
        evidence_kind="product_observation",
        raw_ref="private://raw/r1",
        digest="0" * 64,
        payload={"balance_minor": -500, "currency": "ILLEGAL", "status": "success"},
    )
    assert observation.payload["balance_minor"] == -500
    assert observation.payload["currency"] == "ILLEGAL"


def test_contract_rejects_false_content_digest(config_data):
    config = Configuration.model_validate(config_data)
    with pytest.raises(ValidationError, match="content_hash"):
        Contract(project_id=uuid4(), version="v1", content_hash="0" * 64, config=config)


def test_manifest_hash_and_new_output_requirement():
    manifest = Manifest(
        project_id=uuid4(),
        run_id=uuid4(),
        mode="input",
        target_product_version="fixed",
        environment_version="0.2.0",
        contract_version="demo-v1",
        contract_hash="a" * 64,
        ruleset_version="refund-v1",
        seed=8427192,
        snapshot_ref="private://snapshots/initial",
        snapshot_hash="b" * 64,
        actor_fixture_ref="private://fixtures/inputs",
        actor_fixture_hash="c" * 64,
        fault_plan_ref="private://faults/S12",
        fault_plan_hash="d" * 64,
        code_commit="test-revision",
        dependency_versions={"adapter": "0.2"},
        adapter_version="0.2",
        schedule_ref="private://schedule/run",
        capability_limits=["no_external_clock_control"],
        reuse_product_outputs=False,
        external_clock_control=False,
        on_fixture_mismatch="inconclusive",
    )
    restored = Manifest.model_validate_json(manifest.model_dump_json())
    assert restored.content_hash() == manifest.content_hash()
    restored.target_product_version = "buggy"
    assert restored.content_hash() != manifest.content_hash()
    with pytest.raises(ValidationError):
        Manifest(**(manifest.model_dump() | {"reuse_product_outputs": True}))
