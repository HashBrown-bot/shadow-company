"""E3 serial execution only. E5 lease recovery/retry/concurrency is deliberately not claimed."""

import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from adapters.http.registry import RefundAdapter, validate_example
from packages.contracts.config import Configuration
from packages.evaluators.e3 import evaluate
from packages.transport.http import BoundaryError
from packages.transport.security import Scope, canonical, digest

LIMITS = [
    "仅 S01/S02 纵向闭环；未运行 S03—S20",
    "E4 完整规则和业务 gate 未实现",
    "E5 故障、并发与自动恢复未验收",
    "E6 input replay 未实现",
    "仅本机示例，无真实付款或客户验证",
]


def contract(db, project_id, version):
    with db.connect() as c:
        row = (
            c.execute(
                text("SELECT * FROM contracts WHERE project_id=:p AND version=:v"),
                {"p": project_id, "v": version},
            )
            .mappings()
            .first()
        )
    if not row:
        raise HTTPException(404, "契约不存在")
    return Configuration.model_validate(row["config"]), row["content_hash"]


def new_run(conn, scope, version, config, payload, *, request_hash=None):
    state = (
        conn.execute(text("SELECT stopped,deleting FROM projects WHERE id=:p FOR SHARE"), scope.params)
        .mappings()
        .first()
    )
    if not state or state["stopped"] or state["deleting"]:
        raise HTTPException(409, "项目已急停或正在删除，不能创建新运行")
    conn.execute(
        text("""INSERT INTO runs (project_id,run_id,contract_version,contract_hash,put_version,seed,time_mode)
      VALUES (:p,:r,:v,:h,:put,:seed,:mode)"""),
        scope.params
        | {
            "v": version,
            "h": config.content_hash(),
            "put": config.product.version,
            "seed": config.runtime.seed,
            "mode": config.runtime.time_mode,
        },
    )
    conn.execute(
        text(
            "INSERT INTO run_inputs (project_id,run_id,content_hash,payload,request_key,request_hash) VALUES (:p,:r,:h,CAST(:v AS jsonb),:key,:request_hash)"
        ),
        scope.params
        | {
            "h": digest(payload),
            "v": canonical(payload),
            "key": payload.get("request", {}).get("idempotency_key"),
            "request_hash": request_hash or digest(payload.get("request", {})),
        },
    )
    binding_id = uuid4()
    conn.execute(
        text("INSERT INTO webhook_bindings VALUES (:p,:r,:b,:s)"),
        scope.params | {"b": binding_id, "s": f"secret://demo/webhook/{scope.run_id}"},
    )
    return binding_id


def fixtures(scenarios):
    return [
        {
            "scenario_id": s,
            "refund_command_id": "refund-" + s,
            "payment_id": "payment-" + s,
            "amount_minor": 10000 if s == "S01" else 250000,
            "currency": "CNY",
            "recipient": "demo-recipient",
            "approval_required": s == "S02",
        }
        for s in scenarios
    ]


def seed_payload(expected, binding_id):
    return {
        "payments": [
            {"payment_id": w["payment_id"], "amount_minor": 1000000, "currency": w["currency"]}
            for w in expected
        ],
        "binding_id": str(binding_id),
    }


def require(response, status=200):
    if response["status"] != status:
        raise BoundaryError("示例接口返回非预期 HTTP 状态；原始脱敏响应已保存")
    return response["body"]


def lock_platform(c, scope):
    ok = c.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "platform:" + scope.namespace},
    ).scalar()
    if not ok:
        raise HTTPException(409, "该 run 正在执行，不能 reset")


def reset_run(db, scope, config):
    # A remote reset cannot be atomically committed with PostgreSQL. Mark incomplete first,
    # retry idempotently, retain evidence until all services confirm their deletion.
    with db.begin() as c:
        lock_platform(c, scope)
        row = c.execute(
            text("SELECT status FROM runs WHERE project_id=:p AND run_id=:r FOR UPDATE"), scope.params
        ).scalar()
        if row is None:
            raise HTTPException(404, "run 不存在")
        if row == "running":
            raise HTTPException(409, "正在执行的 run 不能 reset")
        c.execute(
            text(
                "UPDATE runs SET verdict='inconclusive',stop_reason='reset_incomplete' WHERE project_id=:p AND run_id=:r"
            ),
            scope.params,
        )
        c.execute(
            text(
                "UPDATE jobs SET state='cancelled',cancel_requested=true WHERE project_id=:p AND run_id=:r AND state='queued'"
            ),
            scope.params,
        )
    with db.begin() as c:
        lock_platform(c, scope)
        adapter = RefundAdapter(db, scope, config)
        remote = {}
        for target, role, path in [
            ("put", "put_admin", config.product.reset.endpoint),
            ("provider", "provider_admin", config.provider.reset_path),
        ]:
            remote[target] = require(adapter.call(target, role, "POST", path))
            if remote[target].get("reset") is not True:
                raise BoundaryError("远端 reset 未确认")
        audit = {"remote": remote, "records": {}, "contract_hash": config.content_hash()}
        tables = [
            "private_evidence",
            "finding_reviews",
            "actor_calls",
            "actor_policies",
            "replay_seals",
            "replay_assets",
            "runtime_journal",
            "event_dispatches",
            "webhook_receipts",
            "webhook_bindings",
            "jobs",
            "findings",
            "check_results",
            "evaluations",
            "observations",
            "actions",
            "events",
            "manifests",
        ]
        for table in tables:
            rows = (
                c.execute(text(f"SELECT * FROM {table} WHERE project_id=:p AND run_id=:r"), scope.params)
                .mappings()
                .all()
            )
            audit["records"][table] = {
                "count": len(rows),
                "hashes": sorted(digest(dict(row)) for row in rows),
            }
        reset_id = uuid4()
        c.execute(
            text(
                "INSERT INTO reset_audits (project_id,run_id,reset_id,payload,content_hash) VALUES (:p,:r,:id,CAST(:v AS jsonb),:h)"
            ),
            scope.params | {"id": reset_id, "v": canonical(audit), "h": digest(audit)},
        )
        c.execute(text("SELECT set_config('simulation.reset_id',:id,true)"), {"id": str(reset_id)})
        for table in tables:
            c.execute(text(f"DELETE FROM {table} WHERE project_id=:p AND run_id=:r"), scope.params)
        c.execute(
            text(
                "UPDATE runs SET status='cancelled',verdict='inconclusive',stop_reason='reset' WHERE project_id=:p AND run_id=:r"
            ),
            scope.params,
        )
        c.execute(
            text("UPDATE run_inputs SET payload='{}',reset_at=now() WHERE project_id=:p AND run_id=:r"),
            scope.params,
        )
    return {
        "reset": True,
        "reset_id": str(reset_id),
        "audit_hash": digest(audit),
        "removed": {k: v["count"] for k, v in audit["records"].items()},
        "remote": remote,
    }


def preflight(db, project_id, version):
    config, hash_ = contract(db, project_id, version)
    validate_example(config)
    if config.environment.currency != "CNY":
        raise BoundaryError("E3 固定场景仅开放 CNY，其他币种留待 E4")
    scope = Scope(project_id=project_id, run_id=uuid4())
    with db.begin() as c:
        binding = new_run(c, scope, version, config, {"kind": "preflight"})
    adapter = RefundAdapter(db, scope, config)
    checks = {}
    failure = None
    try:
        put = require(adapter.call("put", "support", "GET", "/capabilities"))
        provider = require(adapter.call("provider", "provider_reader", "GET", "/capabilities"))
        checks["connection"] = put.get("example") is True and provider.get("example") is True
        checks["semantics"] = (
            put.get("actions") == config.product.actions.model_dump()
            and config.product.version in put.get("supported_versions", [put.get("version")])
            and put.get("adapter") == config.product.adapter
        )
        checks["independent_ledger"] = (
            provider.get("adapter") == config.provider.adapter
            and provider.get("ledger_path") == config.provider.ledger_path
            and put.get("provider_origin") == config.provider.base_url
            and provider.get("idempotency_scope") == config.provider.idempotency_scope
        )
        identities = [
            require(adapter.call("put", role, "GET", "/identity")) for role in ["support", "approver"]
        ]
        checks["identities"] = (
            identities[0]["role"] == "support"
            and identities[1]["role"] == "approver"
            and identities[0]["identity_id"] != identities[1]["identity_id"]
        )
        checks["time"] = all(
            config.runtime.time_mode in cap.get("clock_support", []) for cap in [put, provider]
        )
        checks["policy"] = (
            put.get("approval_threshold_minor") == config.environment.approval_threshold_minor
            and put.get("threshold_operator") == "gt"
            and put.get("partial_refunds_allowed") is True
        )
        checks["reset_capability"] = (
            put.get("test_mode") is True
            and provider.get("test_mode") is True
            and put.get("reset_path") == config.product.reset.endpoint
            and provider.get("reset_path") == config.provider.reset_path
        )
        checks["outbound"] = True  # validate_example resolved both origins through operator policy above.
        if not all(checks.values()):
            raise BoundaryError("示例能力与契约不匹配")
        seed = seed_payload(fixtures(["S01"]), binding)
        for target, role in [("put", "put_admin"), ("provider", "provider_admin")]:
            result = require(adapter.call(target, role, "POST", "/test/seed", seed))
            if result.get("snapshot_hash") != digest(seed):
                raise BoundaryError("seed 快照哈希不一致")
        require(
            adapter.action(
                "request_refund",
                "refund-S01",
                {
                    k: v
                    for k, v in fixtures(["S01"])[0].items()
                    if k not in {"scenario_id", "approval_required"}
                },
            ),
            201,
        )
        forbidden = adapter.action("approve_refund", "refund-S01", role="support")
        checks["put_rejects_low_privilege"] = forbidden["status"] == 403
        ledger = require(adapter.ledger())
        checks["create_means_application"] = ledger.get("complete") is True and ledger.get("entries") == []
    except (BoundaryError, KeyError, TypeError):
        failure = "接入能力或协议验证失败；见预检检查与脱敏证据"
    # Save pre-reset observation hashes in reset provenance; reset itself must really execute.
    try:
        reset = reset_run(db, scope, config)
        after = adapter.action("read_refund", "refund-S01")
        ledger = require(adapter.ledger())
        checks["reset_verified"] = (
            reset["reset"]
            and after["status"] == 404
            and ledger.get("entries") == []
            and ledger.get("callbacks") == []
        )
        # Clear the post-reset verification probes too, retaining their hashes in a second audit.
        reset_run(db, scope, config)
    except (BoundaryError, HTTPException):
        checks["reset_verified"] = False
        failure = "reset 未完成；不能激活接入"
    result = {
        "passed": failure is None and all(checks.values()),
        "checks": checks,
        "error": failure,
        "limits": LIMITS,
        "run_id": str(scope.run_id),
        "contract_hash": hash_,
        "business_verdict": "inconclusive",
    }
    with db.begin() as c:
        c.execute(
            text(
                "INSERT INTO preflights (project_id,run_id,contract_hash,passed,payload) VALUES (:p,:r,:h,:ok,CAST(:v AS jsonb))"
            ),
            scope.params | {"h": hash_, "ok": result["passed"], "v": canonical(result)},
        )
    return result


def execute_run(db, scope):
    with db.connect() as c:
        run = (
            c.execute(text("SELECT * FROM runs WHERE project_id=:p AND run_id=:r"), scope.params)
            .mappings()
            .one()
        )
        inputs = c.execute(
            text("SELECT payload FROM run_inputs WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()
        binding = c.execute(
            text("SELECT binding_id FROM webhook_bindings WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()
    config, _ = contract(db, scope.project_id, run["contract_version"])
    validate_example(config)
    adapter = RefundAdapter(db, scope, config)
    expected = inputs["expected"]
    start = time.monotonic()
    events = 0

    def budget():
        nonlocal events
        events += 1
        if events > config.runtime.max_events or time.monotonic() - start >= config.runtime.max_wall_seconds:
            raise BoundaryError("budget_exhausted")

    seed = seed_payload(expected, binding)
    for target, role in [("provider", "provider_admin"), ("put", "put_admin")]:
        budget()
        seeded = require(adapter.call(target, role, "POST", "/test/seed", seed))
        if seeded.get("snapshot_hash") != digest(seed):
            raise BoundaryError("seed_snapshot_mismatch")
    for wanted in expected:
        rid = wanted["refund_command_id"]
        payload = {k: v for k, v in wanted.items() if k not in {"scenario_id", "approval_required"}}
        budget()
        require(adapter.action("request_refund", rid, payload), 201)
        if wanted["approval_required"]:
            budget()
            require(adapter.action("approve_refund", rid))
        budget()
        require(adapter.action("execute_refund", rid))
        budget()
        require(adapter.call("provider", "provider_admin", "POST", "/test/deliver"))
        budget()
        require(adapter.action("read_refund", rid))
    budget()
    require(adapter.ledger())
    if time.monotonic() - start >= config.runtime.max_wall_seconds:
        raise BoundaryError("budget_exhausted")
    with db.begin() as c:
        # Full refund_core_20 gate remains inconclusive in E3 even when this narrow flow passes.
        c.execute(
            text(
                "UPDATE runs SET status='completed',verdict='inconclusive',stop_reason='e3_scope_complete' WHERE project_id=:p AND run_id=:r"
            ),
            scope.params,
        )


def report(db, scope):
    with db.connect() as c:
        run = (
            c.execute(text("SELECT * FROM runs WHERE project_id=:p AND run_id=:r"), scope.params)
            .mappings()
            .first()
        )
        if not run:
            raise HTTPException(404, "run 不存在")
        inputs = (
            c.execute(
                text(
                    "SELECT payload,content_hash,reset_at FROM run_inputs WHERE project_id=:p AND run_id=:r"
                ),
                scope.params,
            )
            .mappings()
            .first()
        )
        observations = (
            c.execute(
                text(
                    "SELECT * FROM observations WHERE project_id=:p AND run_id=:r ORDER BY captured_at,observation_id"
                ),
                scope.params,
            )
            .mappings()
            .all()
        )
        audits = (
            c.execute(
                text(
                    "SELECT reset_id,content_hash,created_at FROM reset_audits WHERE project_id=:p AND run_id=:r ORDER BY created_at"
                ),
                scope.params,
            )
            .mappings()
            .all()
        )
    result = evaluate((inputs or {}).get("payload", {}).get("expected", []), observations, scope)
    if run["status"] != "completed":
        result["verdict"] = "inconclusive"
    return {
        "schema_version": "e3-report-1",
        "project_id": str(scope.project_id),
        "run_id": str(scope.run_id),
        "status": run["status"],
        "verdict": "inconclusive",
        "e3_flow": result["verdict"],
        "checks": result["checks"],
        "stop_reason": run["stop_reason"],
        "contract_hash": run["contract_hash"],
        "input_hash": (inputs or {}).get("content_hash"),
        "observations": [dict(o) for o in observations],
        "reset_audits": [dict(a) for a in audits],
        "gate": {
            "suite": "refund_core_20",
            "verdict": "inconclusive",
            "reason": "E4 规则与 S03—S20 尚未验收",
        },
        "limits": LIMITS,
    }
