"""E6: immutable input assets, semantic matching and bounded replay, never old outputs."""

from collections import Counter
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import text

from packages.contracts.replay import ActorFixture
from packages.simulator.jobs import journal
from packages.transport.build import provenance
from packages.transport.http import BoundaryError
from packages.transport.security import canonical, digest, redact

SCHEMA = "e6-replay-1"
LIMITS = [
    "仅已审阅的本机示例；不宣称任意 staging 完全确定性",
    "controlled 重放控制新命名空间、初始数据、语义故障、回调投递和平台事件/barrier；不控制外部时钟",
    "OS/数据库线程先后、HTTP 延迟、UUID、墙钟和外部定时任务不可比较；S19 不指定竞争胜者",
    "本报告只核验声明的业务与重放范围；平台工程验收见交付检查表；模型增量、真实客户和生产未验证",
]
BOUNDARY = {
    "profile": "local-refund-controls-v1",
    "controlled": [
        "new_run_namespace",
        "initial_payments",
        "semantic_fault_once",
        "platform_event_order",
        "callback_delivery_order",
        "entry_barrier",
    ],
    "uncontrolled": [
        "wall_clock",
        "OS_scheduling",
        "database_lock_winner",
        "network_latency",
        "UUIDs",
        "external_systems",
    ],
    "external_clock_control": False,
    "deterministic_external_staging": False,
}


def semantic_faults(plan):
    """A one-shot fault selects a business request AND the dependency's actual pre-state."""
    plan = deepcopy(plan)
    for f in plan["faults"]:
        if f["attempt"] != 1:
            raise BoundaryError(
                "E6 semantic fixtures only support the first eligible pre-state; not historical call ordinals"
            )
        step = next(
            s
            for s in plan["steps"]
            if s["command_id"] == f["command_id"] and s["operation"] == "request_refund"
        )
        fields = {k: step["body"][k] for k in ("payment_id", "amount_minor", "currency", "recipient")}
        operation, state = "execute_payment", "uncommitted"
        if f["behavior"].startswith("webhook_"):
            operation, state = "deliver_callback", "committed"
            fields.pop("recipient")
        else:
            fields["command_version"] = 1
        if f["behavior"] == "approver_offline":
            operation, state = "approve_snapshot", "approval_pending"
        f["semantic"] = {"operation": operation, "fields": fields, "state": state}
    return plan


def actor_fixtures(plan):
    values, objects = {}, {}
    for step in plan["steps"]:
        op, rid = step["operation"], step["command_id"]
        if op == "request_refund":
            fields = {k: step["body"][k] for k in ("payment_id", "amount_minor", "currency", "recipient")}
            precondition = {"kind": "absent_or_same", "fields": fields}
            objects.setdefault(rid, fields | {"version": 1})
        elif op == "read_refund":
            # Permission probes must use that actor's own visibility, never privileged feedback.
            precondition = {"kind": "visibility_probe", "fields": {}}
        else:
            precondition = {"kind": "object_fields", "fields": deepcopy(objects[rid])}
        value = {k: step[k] for k in ("operation", "command_id", "role", "body")} | {
            "precondition": precondition,
            "policy": "scripted_v1",
        }
        key = "actor-" + digest(value)[:32]
        if key not in values:
            values[key] = ActorFixture(fixture_id=key, **value).model_dump(mode="json")
        else:
            values[key]["uses"] += 1
        if op == "amend_refund":
            objects[rid] = objects[rid] | step["body"] | {"version": objects[rid]["version"] + 1}
    return list(values.values())


def asset_rows(c, scope):
    return {
        r["kind"]: dict(r)
        for r in c.execute(
            text("SELECT * FROM replay_assets WHERE project_id=:p AND run_id=:r"), scope.params
        ).mappings()
    }


def manifest_row(c, scope):
    return (
        c.execute(text("SELECT * FROM manifests WHERE project_id=:p AND run_id=:r"), scope.params)
        .mappings()
        .first()
    )


def check_assets(manifest, assets):
    problems = []
    for kind in ("snapshot", "actors", "faults"):
        row = assets.get(kind)
        if (
            not row
            or row["content_hash"] != manifest["assets"][kind]["content_hash"]
            or digest(row["payload"]) != row["content_hash"]
        ):
            problems.append("missing_or_corrupt_" + kind)
    return problems


def freeze(c, scope, config, plan, binding, contract_version, replay=None, actors=None, actor_policy=None):
    from packages.simulator.e5 import freeze as freeze_schedule
    from packages.simulator.e5 import schedule

    replay = replay or {"mode": "input", "source_run_id": None, "purpose": "record_baseline"}
    values = {
        "snapshot": {"payments": plan["payments"]},
        "actors": sorted(
            actors if actors is not None else actor_fixtures(plan), key=lambda f: f["fixture_id"]
        ),
        "faults": plan["faults"],
    }
    assets = {}
    for kind, payload in values.items():
        hash_ = digest(payload)
        c.execute(
            text("INSERT INTO replay_assets VALUES (:p,:r,:k,:h,CAST(:v AS jsonb))"),
            scope.params | {"k": kind, "h": hash_, "v": canonical(payload)},
        )
        assets[kind] = {"ref": f"private://replay/{scope.namespace}/{kind}", "content_hash": hash_}
    events = schedule(config, plan, binding)
    # Service provenance is observed again by the Worker, before any seed or business write.
    caps = [
        {
            "target": target,
            "role": role,
            "method": "GET",
            "path": "/capabilities",
            "body": None,
            "command_id": "protocol",
            "operation": "control",
            "offset_ms": 0,
            "priority": -1,
        }
        for target, role in [("put", "support"), ("provider", "provider_reader")]
    ]
    for index, event in enumerate(caps + events, 1):
        event["sequence"] = index
    normalized_schedule = deepcopy(caps + events)
    for event in normalized_schedule:
        if event.get("path") == "/test/seed":
            event["body"]["binding_id"] = "new_scope_binding"
        elif event.get("path") == "/test/behavior":
            event["body"]["variant"] = "target_product_version"
    version = provenance()
    data = config.model_dump(mode="json")
    normalized_contract = deepcopy(data)
    normalized_contract["product"].pop("version")
    manifest = {
        "schema_version": SCHEMA,
        **scope.model_dump(mode="json"),
        **replay,
        "target_product_version": config.product.version,
        "contract_version": contract_version,
        "contract_hash": config.content_hash(),
        "contract_semantics_hash": digest(normalized_contract),
        "environment": {
            "version": config.environment.version,
            "content_hash": digest(data["environment"]),
            "config": data["environment"],
        },
        "rules": {
            "versions": {r.id: r.version for r in config.rules},
            "content_hash": digest(data["rules"]),
            "code": version["rules"],
        },
        "versions": version,
        "seed": config.runtime.seed,
        "runtime": data["runtime"],
        "actors_config": data["actors"],
        "gate": data["gate"],
        "postgres_version": c.execute(text("SHOW server_version")).scalar_one(),
        "assets": assets,
        "snapshot_hash": assets["snapshot"]["content_hash"],
        "isolation": {
            "strategy": "new_run_namespace",
            "namespace": scope.namespace,
            "residual_state": "none in the declared local schemas",
        },
        "materialized_snapshot_hash": digest({"payments": plan["payments"], "binding_id": str(binding)}),
        "fault_plan": plan["faults"],
        "schedule_hash": digest(caps + events),
        "planned_input_schedule_hash": digest(normalized_schedule),
        "event_count": len(caps + events),
        "schedule_ref": f"private://events/{scope.namespace}",
        "actual_schedule": {
            "status": "pending",
            "seal_ref": f"private://replay/{scope.namespace}/completion",
        },
        "control_boundary": BOUNDARY,
        "external_clock_control": False,
        "time_mode": config.runtime.time_mode,
        "reuse_product_outputs": False,
        "fixture_matching": "operation + object + actor + body + current pre-state; never old ordinal",
        "on_fixture_mismatch": "inconclusive",
        "capability_limits": LIMITS,
    }
    if actor_policy is not None:
        from packages.simulator.actors import freeze_policy

        manifest["actor_policy"] = freeze_policy(c, scope, actor_policy)
    freeze_schedule(c, scope, config, plan, binding, events=caps + events, manifest=manifest)


class ReplayGuard:
    def __init__(self, db, scope, adapter):
        self.db, self.scope, self.adapter = db, scope, adapter
        with db.connect() as c:
            row = manifest_row(c, scope)
            self.manifest = row["payload"]
            assets = asset_rows(c, scope)
            self.problems = check_assets(self.manifest, assets)
            if digest(self.manifest) != row["content_hash"]:
                self.problems.append("manifest_hash_mismatch")
            self.fixtures = assets.get("actors", {}).get("payload", [])
            prior = c.execute(
                text(
                    "SELECT payload FROM runtime_journal WHERE project_id=:p AND run_id=:r AND kind='fixture_matched'"
                ),
                scope.params,
            ).scalars()
            self.used = Counter(p["fixture_id"] for p in prior)
        self.problems += (
            ["duplicate_fixture_id"]
            if len({f["fixture_id"] for f in self.fixtures}) != len(self.fixtures)
            else []
        )

    def log(self, kind, payload, event_id=None):
        with self.db.begin() as c:
            journal(c, self.scope, kind, redact(payload), event_id)

    def fail(self, reason, event=None, details=None):
        self.log(
            "fixture_mismatch",
            {"reason": reason, "attribution": "environment_error", "details": details},
            event and event["event_id"],
        )
        raise BoundaryError("fixture_mismatch")

    def validate(self):
        if self.problems:
            self.fail("missing_or_corrupt_required_fixture", details=self.problems)
        # Guard never guesses a missing actor input from an old response or planner defaults.
        with self.db.connect() as c:
            plan = c.execute(
                text("SELECT payload FROM run_inputs WHERE project_id=:p AND run_id=:r"), self.scope.params
            ).scalar_one()["plan"]
        expected = actor_fixtures(plan)
        required = Counter()
        available = Counter()
        for f in expected:
            required[self.key(f)] += f["uses"]
        for f in self.fixtures:
            ActorFixture.model_validate(f)
            available[self.key(f)] += f["uses"]
        if required - available:
            self.fail(
                "missing_required_actor_fixture",
                details={"missing_semantics": list((required - available).elements())},
            )
        version = provenance()
        for key in ("platform", "adapter", "rules", "dependencies"):
            if version[key] != self.manifest["versions"][key]:
                self.fail("worker_version_drift", details={"component": key})

    @staticmethod
    def key(spec):
        return digest({k: spec.get(k) for k in ("operation", "command_id", "role", "body")})

    def before(self, event):
        spec = event["payload"]
        if not spec.get("scenario_id"):
            return False
        candidates = [
            f
            for f in self.fixtures
            if self.key(f) == self.key(spec) and self.used[f["fixture_id"]] < f["uses"]
        ]
        if not candidates:
            self.fail(
                "no_semantic_fixture", event, {"operation": spec["operation"], "object": spec["command_id"]}
            )
        probe = self.adapter.call(
            "put", spec["role"], "GET", "/refunds/" + spec["command_id"], external_id=spec["command_id"]
        )
        actual = probe.get("body", {})
        matches = []
        for f in candidates:
            pre = f["precondition"]
            same = isinstance(actual, dict) and all(actual.get(k) == v for k, v in pre["fields"].items())
            valid = (
                (pre["kind"] == "visibility_probe" and probe["status"] in {200, 403, 404})
                or (pre["kind"] == "absent_or_same" and probe["status"] == 404)
                or (probe["status"] == 200 and same)
            )
            if valid:
                matches.append(f)
        if len(matches) != 1:
            self.fail(
                "precondition_mismatch_or_ambiguous_fixture",
                event,
                {
                    "candidates": [f["fixture_id"] for f in candidates],
                    "observed_status": probe["status"],
                    "observed_state": actual,
                },
            )
        f = matches[0]
        self.used[f["fixture_id"]] += 1
        self.log(
            "fixture_matched",
            {
                "fixture_id": f["fixture_id"],
                "operation": spec["operation"],
                "object": spec["command_id"],
                "precondition": f["precondition"],
                "observed_state": actual,
            },
            event["event_id"],
        )
        skip = f["policy"] == "retry_if_unsettled_v1" and actual.get("status") in {
            "succeeded",
            "cancelled",
            "rejected",
        }
        self.log(
            "actor_decision",
            {
                "fixture_id": f["fixture_id"],
                "policy": f["policy"],
                "decision": "skip_settled" if skip else "dispatch",
                "feedback_dependent": f["policy"] != "scripted_v1",
                "input_not_identical": skip,
                "explanation": "settled status => no additional execution; otherwise dispatch frozen action"
                if f["policy"] != "scripted_v1"
                else "fixed action after semantic precondition check",
            },
            event["event_id"],
        )
        return skip

    def after(self, event, result):
        spec = event["payload"]
        if spec.get("path") == "/capabilities":
            component = "put" if spec["target"] == "put" else "provider"
            body = result.get("body", {})
            if (
                result["status"] != 200
                or body.get("build") != self.manifest["versions"][component]
                or not body.get("test_mode")
            ):
                self.fail("service_version_or_capability_mismatch", event, {"component": component})
            required = {
                "new_namespace",
                "semantic_faults",
                "entry_barrier" if component == "put" else "callback_delivery",
            }
            if not required <= set(body.get("replay_controls", [])):
                self.fail("unsupported_control_boundary", event, {"component": component})
        if spec.get("path") == "/test/seed" and (
            result["status"] != 200
            or result.get("body", {}).get("snapshot_hash") != self.manifest["materialized_snapshot_hash"]
        ):
            self.fail("snapshot_initialization_mismatch", event)
        if spec.get("scenario_id"):
            headers = {k.lower(): v for k, v in result.get("headers", {}).items()}
            if (
                headers.get("x-put-version") != self.manifest["target_product_version"]
                or headers.get("x-put-build-hash") != self.manifest["versions"]["put"]["content_hash"]
            ):
                self.fail("target_product_version_not_observed", event)
        if result.get("body", {}).get("error") == "fixture_mismatch":
            self.fail("dependency_fixture_mismatch", event)


def bundle(db, scope, require_seal=False):
    with db.connect() as c:
        run = (
            c.execute(text("SELECT * FROM runs WHERE project_id=:p AND run_id=:r"), scope.params)
            .mappings()
            .first()
        )
        if not run:
            raise HTTPException(404, "run 不存在")
        manifest = manifest_row(c, scope)
        seal = (
            c.execute(text("SELECT * FROM replay_seals WHERE project_id=:p AND run_id=:r"), scope.params)
            .mappings()
            .first()
        )
        assets = asset_rows(c, scope)
        data = c.execute(
            text("SELECT payload FROM run_inputs WHERE project_id=:p AND run_id=:r"), scope.params
        ).scalar_one()
    if not manifest or manifest["payload"].get("schema_version") != SCHEMA:
        raise HTTPException(409, "旧运行缺少 E6 版本/fixture 清单，仅支持 history；请新建 e6_core_20 基线")
    if require_seal and not seal:
        raise HTTPException(409, "源运行未封存，不可用于修复验证")
    return dict(run), dict(manifest), dict(seal) if seal else None, assets, data


def seal_run(db, scope, report):
    with db.begin() as c:
        manifest = manifest_row(c, scope)
        if (
            not manifest
            or manifest["payload"].get("schema_version") != SCHEMA
            or report["status"] not in {"completed", "failed", "cancelled"}
        ):
            return
        actual = {k: report["runtime"][k] for k in ("events", "actions", "journal", "faults", "concurrency")}
        payload = deepcopy(manifest["payload"]) | {
            "phase": "completed_evidence",
            "parent_hash": manifest["content_hash"],
            "actual_schedule": {"content_hash": digest(actual), "records": actual},
            "report": report,
            "report_hash": digest(report),
        }
        c.execute(
            text(
                "INSERT INTO replay_seals(project_id,run_id,parent_hash,content_hash,payload) VALUES (:p,:r,:parent,:h,CAST(:v AS jsonb)) ON CONFLICT DO NOTHING"
            ),
            scope.params
            | {"parent": manifest["content_hash"], "h": digest(payload), "v": canonical(payload)},
        )


def history(db, scope):
    """Pure SELECT. No report recomputation, no preflight, no job, no HTTP."""
    with db.connect() as c:
        run = (
            c.execute(text("SELECT * FROM runs WHERE project_id=:p AND run_id=:r"), scope.params)
            .mappings()
            .first()
        )
        if not run:
            raise HTTPException(404, "run 不存在")
        result = {"mode": "history", "calls_put": False, **scope.model_dump(mode="json"), "run": dict(run)}
        for name in (
            "manifests",
            "replay_seals",
            "observations",
            "events",
            "evaluations",
            "actor_policies",
            "actor_calls",
            "finding_reviews",
        ):
            rows = c.execute(
                text(f"SELECT * FROM {name} WHERE project_id=:p AND run_id=:r"), scope.params
            ).mappings()
            result[name] = sorted([dict(r) for r in rows], key=canonical)
    return result


def evidence_summary(report):
    records = {"put": [], "provider": []}
    entries, callbacks = set(), set()
    for o in report["observations"]:
        p = o["payload"]
        if o["source"] == "provider_ledger":
            entries.update(e["entry_id"] for e in p.get("response", {}).get("body", {}).get("entries", []))
        if o["source"] == "provider_webhook":
            callbacks.add(p["event_id"])
        if p.get("request", {}).get("path") == "/test/evidence":
            records["put" if o["source"] == "put" else "provider"] = (
                p.get("response", {}).get("body", {}).get("records", [])
            )
    business = [r for r in records["put"] if r["kind"] == "business_call"]
    provider = [r for r in records["provider"] if r["kind"] == "execution_received"]
    return {
        "put_business_calls": len(business),
        "put_versions": sorted({r["payload"]["variant"] for r in business}),
        "put_build_hashes": sorted({r["payload"]["build_hash"] for r in business}),
        "provider_execution_calls": len(provider),
        "provider_calls_by_command": dict(Counter(r["payload"]["command_id"] for r in provider)),
        "ledger_entry_ids": sorted(entries),
        "webhook_event_ids": sorted(callbacks),
        "observation_ids": sorted(str(o["observation_id"]) for o in report["observations"]),
        "fixture_mismatches": [
            r for records_ in records.values() for r in records_ if r["kind"] == "fixture_mismatch"
        ],
    }


def replay_report(db, scope, report):
    _, row, seal, assets, _ = bundle(db, scope)
    manifest = row["payload"]
    issues = check_assets(manifest, assets)
    summary = evidence_summary(report)
    journal_ = report["runtime"]["journal"]
    journal_mismatches = [r for r in journal_ if r["kind"] == "fixture_mismatch"]
    mismatches = journal_mismatches + summary["fixture_mismatches"]
    decisions = [r for r in journal_ if r["kind"] == "actor_decision"]
    if mismatches:
        issues.append("fixture_mismatch")
    if summary["put_versions"] != [manifest["target_product_version"]] or summary["put_build_hashes"] != [
        manifest["versions"]["put"]["content_hash"]
    ]:
        issues.append("target_version_calls_not_verified")
    observed = Counter(r["payload"]["fixture_id"] for r in journal_ if r["kind"] == "fixture_matched")
    if any(observed[f["fixture_id"]] != f["uses"] for f in assets.get("actors", {}).get("payload", [])):
        issues.append("fixture_coverage_incomplete")
    inputs_changed = [r for r in decisions if r["payload"].get("input_not_identical")]
    if inputs_changed:
        issues.append("required_scenario_input_skipped_by_feedback_policy")
    # Execution failures explain why evidence is missing. Keep the business evaluator's
    # observed gaps unchanged, and expose the independent runtime cause with durable refs.
    execution_issues = []
    for mismatch in mismatches:
        payload = mismatch["payload"]
        if mismatch in journal_mismatches:
            refs = [f"private://postgres/{scope.namespace}/runtime_journal/{mismatch['sequence']}"]
        else:
            refs = [
                str(o["observation_id"])
                for o in report["observations"]
                if isinstance(o["payload"].get("response", {}).get("body"), dict)
                and mismatch in o["payload"]["response"]["body"].get("records", [])
            ]
        execution_issues.append(
            {
                "kind": "fixture_mismatch",
                "attribution": "environment_error",
                "reason": payload.get("reason", "dependency_fixture_mismatch"),
                "details": redact(payload.get("details", payload)),
                "evidence_refs": refs,
            }
        )
    for issue in issues:
        if issue == "fixture_mismatch":
            continue
        execution_issues.append(
            {
                "kind": "replay_evidence_incomplete",
                "attribution": "environment_error",
                "reason": issue,
                "details": None,
                "evidence_refs": [f"private://postgres/{scope.namespace}/manifests/{row['content_hash']}"],
            }
        )
    report["execution_issues"] = execution_issues
    report["schema_version"] = "e6-report-1"
    report["scope"]["phase"] = "E6"
    report["versions"]["schema_revision"] = "0005_e6"
    report["limits"] = LIMITS
    report["replay"] = {
        "mode": manifest["mode"],
        "source_run_id": manifest.get("source_run_id"),
        "capability": ["history", "input", "controlled"],
        "manifest": manifest,
        "manifest_hash": row["content_hash"],
        "completion_seal_hash": seal and seal["content_hash"],
        "issues": issues,
        "fixture_mismatches": mismatches,
        "actor_decisions": decisions,
        "input_deviations": inputs_changed,
        "fresh_evidence": summary,
        "control_boundary": BOUNDARY,
        "non_comparable": BOUNDARY["uncontrolled"],
    }
    if issues:
        # Fixture/environment errors are not invented product failures. Real business counterevidence stays visible.
        report["verdict"] = "inconclusive"
        report["selected_gate"]["verdict"] = "inconclusive"
        report["gate"]["verdict"] = "inconclusive"
        report["unverified"] += issues
    report["selected_gate"]["scope"] = "E6 selected scenarios"
    report["gate"]["reason"] = "仅 refund_core_20 场景套件；不代表平台整体工程、客户或生产验收"
    return report
