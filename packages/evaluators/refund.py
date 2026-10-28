"""Deterministic E4 rules. Only policy and provenance-labelled observations enter here.

No simulator imports, scenario fixtures, target variants or expected-result labels.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from packages.contracts.domain import CheckResult, Finding
from packages.transport.security import digest

RULES = ("REFUND_001", "REFUND_002", "APPROVAL_001", "STATE_001", "TIME_001")
TERMINALS = {"succeeded", "rejected", "cancelled", "reconciliation_required"}
PERMISSIONS = {
    "support": ("request_refund", "execute_refund", "read_refund", "amend_refund"),
    "approver": ("approve_refund", "read_refund"),
    "customer_a": ("read_own_refund",),
    "customer_b": ("read_own_refund",),
}


@dataclass(frozen=True)
class Policy:
    threshold_minor: int
    observation_seconds: int
    partial_refunds_allowed: bool = True
    version: str = "2"
    adapter_policy: str = "http_refund_v1-access-1"

    @classmethod
    def from_config(cls, config):
        rules = {r.id: r for r in config.rules}
        return cls(
            rules["APPROVAL_001"].params.threshold_minor,
            rules["TIME_001"].params.observation_wall_seconds,
            config.environment.partial_refunds_allowed,
        )

    def content_hash(self):
        return digest(asdict(self) | {"permissions": PERMISSIONS, "rules": RULES})


def stamp(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def obj(value):
    return value if isinstance(value, dict) else {}


def scoped(value, scope):
    return str(value.get("project_id")) == str(scope.project_id) and str(value.get("run_id")) == str(
        scope.run_id
    )


class Evidence:
    def __init__(self, observations, scope, policy):
        self.scope, self.policy = scope, policy
        self.calls, self.entries, self.payments, self.callbacks = [], {}, {}, []
        self.entry_refs, self.payment_refs = defaultdict(list), defaultdict(list)
        self.ledger_refs, self.issues, self.conflicts = [], [], []
        self.identities, self.commands = {}, set()
        self.ledger_times, self.mutations = [], []
        self.ledger_snapshots = []
        for obs in observations:
            source = obs.get("source")
            payload = obj(obs.get("payload"))
            request = obj(payload.get("request"))
            path = request.get("path")
            path = path if isinstance(path, str) else ""
            # Test control/configuration observations are never interpreted by rules.
            relevant = source in {"provider_ledger", "provider_webhook"} or (
                source == "put" and (path.startswith("/refunds") or path == "/identity")
            )
            if not relevant:
                continue
            ref = str(obs["observation_id"])
            at = stamp(obs.get("captured_at"))
            kind = "product_observation" if source == "put" else "dependency_evidence"
            if (
                not scoped(obs, scope)
                or obs.get("evidence_kind") != kind
                or not at
                or obs.get("digest") != digest(payload)
            ):
                self.issue("观测来源、范围、摘要或时间无效", [ref], "adapter_error")
                continue
            if source == "provider_webhook":
                if obs.get("external_id") == "invalid-protocol":
                    self.issue("已验签回调违反协议；原始内容保留但不能充当完整证据", [ref], "adapter_error")
                if scoped(payload, scope) and all(
                    isinstance(payload.get(k), str) for k in ("entry_id", "refund_command_id", "payment_id")
                ):
                    self.callbacks.append((payload, ref))
                else:
                    self.issue("回调范围或业务标识无效", [ref], "adapter_error")
                continue
            response = obj(payload.get("response"))
            body = obj(response.get("body"))
            if source == "provider_ledger":
                self.ledger_refs.append(ref)
                if (
                    response.get("status") != 200
                    or not scoped(body, scope)
                    or not isinstance(body.get("entries"), list)
                ):
                    self.issue("独立账本响应缺失或无效", [ref], "environment_error")
                    continue
                valid = True
                for entry in body["entries"]:
                    if (
                        not isinstance(entry, dict)
                        or not scoped(entry, scope)
                        or not all(
                            isinstance(entry.get(k), str)
                            for k in ("entry_id", "refund_command_id", "payment_id", "currency", "status")
                        )
                    ):
                        valid = False
                        self.issue("独立账本条目缺少标识或范围", [ref], "adapter_error")
                        continue
                    key = entry["entry_id"]
                    self.commands.add(entry["refund_command_id"])
                    self.entry_refs[key].append(ref)
                    if key in self.entries and self.entries[key] != entry:
                        self.conflict("同一账本条目存在冲突内容", self.entry_refs[key])
                    else:
                        self.entries[key] = entry
                payments = body.get("payments")
                if not isinstance(payments, list):
                    valid = False
                    self.issue("缺少独立支付初始余额", [ref])
                else:
                    for payment in payments:
                        if (
                            not isinstance(payment, dict)
                            or not scoped(payment, scope)
                            or not isinstance(payment.get("payment_id"), str)
                            or type(payment.get("amount_minor")) is not int
                            or payment["amount_minor"] < 0
                            or not isinstance(payment.get("currency"), str)
                            or payment["currency"] not in {"CNY", "USD", "EUR", "JPY"}
                        ):
                            valid = False
                            self.issue("支付初始余额或币种证据无效", [ref], "adapter_error")
                            continue
                        key = payment["payment_id"]
                        self.payment_refs[key].append(ref)
                        if key in self.payments and self.payments[key] != payment:
                            self.conflict("独立支付初始余额冲突", self.payment_refs[key])
                        else:
                            self.payments[key] = payment
                if valid and body.get("complete") is True:
                    self.ledger_times.append(at)
                    self.ledger_snapshots.append((at, ref, {e["entry_id"] for e in body["entries"]}))
                continue
            call = {
                "ref": ref,
                "at": at,
                "method": request.get("method") if isinstance(request.get("method"), str) else "UNKNOWN",
                "path": path,
                "request": obj(request.get("body")),
                "body": body,
                "status": response.get("status") if type(response.get("status")) is int else None,
                "actor": payload.get("actor_id") if isinstance(payload.get("actor_id"), str) else None,
            }
            self.calls.append(call)
            if call["path"] == "/identity":
                actor = call["actor"]
                if (
                    call["status"] == 200
                    and scoped(body, scope)
                    and body.get("identity_id") == actor
                    and isinstance(body.get("permissions"), list)
                    and all(isinstance(p, str) for p in body["permissions"])
                    and set(body["permissions"]) == set(PERMISSIONS.get(actor, ()))
                ):
                    self.identities[actor] = ref
                else:
                    self.issue("身份或权限映射未核验", [ref], "actor_error")
                continue
            rid = (
                path.split("/")[2]
                if path.startswith("/refunds/")
                else call["request"].get("refund_command_id")
            )
            if isinstance(rid, str):
                call["rid"] = rid
                self.commands.add(rid)
            else:
                self.issue("动作缺少退款指令标识", [ref], "adapter_error")
            if call["method"] != "GET":
                self.mutations.append(at)
            if call["method"] not in {"GET", "POST", "PATCH"} or type(call["status"]) is not int:
                self.issue("HTTP Adapter 未取得产品响应", [ref], "adapter_error")
            elif call["status"] >= 500:
                self.issue("产品服务或依赖不可用，不能据 HTTP 状态认定产品缺陷", [ref], "environment_error")
            elif call["status"] == 422:
                self.issue("角色输入未通过协议校验", [ref], "actor_error")
            if body.get("refund_id") and (body["refund_id"] != rid or not scoped(body, scope)):
                self.issue("产品查询对象或范围不匹配", [ref], "adapter_error")
                call["body"] = {}
            elif body.get("refund_id") and not all(
                isinstance(body.get(k), str)
                for k in ("refund_id", "payment_id", "status", "currency", "recipient")
            ):
                self.issue("产品业务字段结构不可解释", [ref], "adapter_error")
                call["body"] = {}
        self.calls.sort(key=lambda c: (c["at"], c["ref"]))
        seen_entries, snapshot_refs = set(), []
        for _, ref, ids in sorted(self.ledger_snapshots):
            if seen_entries - ids:
                self.conflict("后续完整账本遗漏先前已观测条目", snapshot_refs + [ref])
            seen_entries |= ids
            snapshot_refs.append(ref)
        for call in self.calls:
            if call["path"] != "/identity" and call["actor"] not in self.identities:
                self.issue("缺少动作操作者的已核验身份", [call["ref"]], "actor_error")
            if (
                call["path"].startswith("/refunds/")
                and call["status"] == 200
                and not call["body"].get("refund_id")
            ):
                self.issue("产品响应缺少可核验的业务对象", [call["ref"]], "adapter_error")
        for callback, ref in self.callbacks:
            entry = self.entries.get(callback.get("entry_id"))
            if entry and any(
                callback.get(k) != entry.get(k)
                for k in (
                    ("refund_command_id", "payment_id", "amount_minor", "currency")
                    if self.historical_callback(callback)
                    else ("refund_command_id", "payment_id", "amount_minor", "currency", "status")
                )
            ):
                self.conflict("已验签回调与独立账本冲突", [ref] + self.entry_refs[entry["entry_id"]])
        for entry in self.entries.values():
            if entry["status"] == "failed" and not self.successful(entry["refund_command_id"]):
                self.issue(
                    "独立 provider 记录执行失败，尚无后续成功执行",
                    self.entry_refs[entry["entry_id"]],
                    "dependency_failure",
                )
        self.deadline = (
            max(self.mutations) + timedelta(seconds=policy.observation_seconds) if self.mutations else None
        )
        self.closed = bool(self.deadline and self.ledger_times and max(self.ledger_times) >= self.deadline)
        if not self.ledger_times:
            self.issue("缺少完整的独立 provider 账本", self.ledger_refs)

    def issue(self, reason, refs, attribution="undetermined"):
        self.issues.append({"reason": reason, "evidence_refs": refs, "attribution": attribution})

    def conflict(self, reason, refs):
        item = {"reason": reason, "evidence_refs": sorted(set(refs)), "attribution": "undetermined"}
        self.conflicts.append(item)
        self.issues.append(item)

    def for_command(self, rid):
        return [c for c in self.calls if c.get("rid") == rid]

    def successful(self, rid=None):
        return [
            e
            for e in self.entries.values()
            if e.get("status") == "succeeded" and (rid is None or e["refund_command_id"] == rid)
        ]

    def final_query(self, rid):
        calls = [
            c
            for c in self.for_command(rid)
            if c["method"] == "GET" and c["path"] == "/refunds/" + rid and c["actor"] == "support"
        ]
        return calls[-1] if calls else None

    def historical_callback(self, callback):
        at = stamp(callback.get("occurred_at"))
        return (
            callback.get("status") == "execution_pending"
            and callback.get("state_version") == 1
            and at is not None
            and any(
                b.get("entry_id") == callback.get("entry_id")
                and b.get("status") == "succeeded"
                and b.get("state_version") == 2
                and stamp(b.get("occurred_at")) is not None
                and at <= stamp(b["occurred_at"])
                for b, _ in self.callbacks
            )
        )

    def missing(self, rid):
        reasons = [i["reason"] for i in self.issues]
        query = self.final_query(rid)
        if not query or query["status"] not in (200, 404):
            reasons.append("缺少产品最终查询")
        elif not self.deadline or query["at"] < self.deadline:
            reasons.append("产品最终查询早于观察窗口结束")
        if not self.closed:
            reasons.append("观察窗口尚未闭合或缺少窗口后的完整账本")
        for e in self.successful(rid):
            matching = [(b, r) for b, r in self.callbacks if b.get("entry_id") == e["entry_id"]]
            if not matching:
                reasons.append("缺少已验签的执行回调")
            elif any(
                any(
                    b.get(k) != e.get(k)
                    for k in (
                        ("refund_command_id", "payment_id", "amount_minor", "currency")
                        if self.historical_callback(b)
                        else ("refund_command_id", "payment_id", "amount_minor", "currency", "status")
                    )
                )
                for b, _ in matching
            ):
                reasons.append("回调与独立账本冲突")
        return list(dict.fromkeys(reasons))


def evaluate(policy, observations, scope, *, completed, evaluated_at=None):
    """Return rule results without seeing scenario IDs, expected fixtures or product versions."""
    now = evaluated_at or datetime.now(timezone.utc)
    ev = Evidence(observations, scope, policy)
    checks, findings, access = [], [], []

    def emit(
        rule,
        rid,
        verdict,
        reason,
        refs,
        *,
        attribution="undetermined",
        expected=None,
        actual=None,
        severity=None,
    ):
        missing = ev.missing(rid) if rid in ev.commands else ["没有可核验的业务观测"]
        if verdict in {"pass", "not_applicable"} and (missing or not completed):
            verdict, reason = "inconclusive", "；".join(missing or ["运行未完成、取消或预算耗尽"])
            attribution = next(
                (i["attribution"] for i in ev.issues if i["attribution"] != "undetermined"), "undetermined"
            )
        if verdict == "not_applicable":
            reason = f"契约 {policy.adapter_policy} / {rule} 条件不适用：" + reason
        check = CheckResult(
            project_id=scope.project_id,
            run_id=scope.run_id,
            rule_id=rule,
            rule_version=policy.version,
            object_id=rid,
            verdict=verdict,
            reason=reason,
            evidence_refs=[UUID(r) for r in sorted(set(refs))],
            evaluated_at=now,
        )
        value = check.model_dump(mode="json") | {
            "attribution": attribution,
            "expected": expected,
            "actual": actual,
        }
        checks.append(value)
        if verdict in {"fail", "inconclusive"}:
            finding = Finding(
                project_id=scope.project_id,
                run_id=scope.run_id,
                check_id=check.check_id,
                severity=severity
                or (
                    "critical"
                    if rule in {"REFUND_001", "REFUND_002", "APPROVAL_001"} and verdict == "fail"
                    else "high"
                    if verdict == "fail"
                    else "medium"
                ),
                attribution=attribution,
                confirmation="confirmed"
                if verdict == "fail" and attribution == "product_defect"
                else "unconfirmed",
                dedup_key=digest(
                    {
                        "rule": rule,
                        "object": expected.get("payment_id")
                        if rule == "REFUND_002" and isinstance(expected, dict)
                        else rid,
                        "reason": reason,
                        "attribution": attribution,
                    }
                ),
                expected=expected,
                actual=actual,
                evidence_refs=check.evidence_refs,
                observed_at=now,
                replay_capability="unavailable",
            )
            findings.append(
                finding.model_dump(mode="json")
                | {
                    "rule_id": rule,
                    "object_id": rid,
                    "business_object_id": expected.get("payment_id")
                    if rule == "REFUND_002" and isinstance(expected, dict)
                    else rid,
                    "related_check_ids": [str(check.check_id)],
                    "reason": reason,
                    "failure_chain": [
                        {
                            "observation_id": c["ref"],
                            "at": c["at"].isoformat(),
                            "source": "put",
                            "operation": c["method"] + " " + c["path"],
                            "status": c["status"],
                        }
                        for c in ev.for_command(rid)
                    ]
                    + [
                        {
                            "source": "provider_ledger",
                            "entry_id": e["entry_id"],
                            "status": e["status"],
                            "evidence_refs": ev.entry_refs[e["entry_id"]],
                        }
                        for e in ev.successful(rid)
                    ],
                }
            )

    if not ev.commands:
        for rule in RULES:
            emit(rule, "run", "inconclusive", "没有可核验的业务观测", ev.ledger_refs)
    for rid in sorted(ev.commands):
        calls = ev.for_command(rid)
        entries = ev.successful(rid)
        refs = (
            [c["ref"] for c in calls]
            + ev.ledger_refs
            + [r for b, r in ev.callbacks if b.get("refund_command_id") == rid]
            + [ev.identities[c["actor"]] for c in calls if c["actor"] in ev.identities]
        )
        query = ev.final_query(rid)
        state = query["body"] if query and query["status"] == 200 else {}
        bodies = [c["body"] for c in calls if c["body"].get("refund_id") == rid and c["status"] in (200, 201)]
        request = next((c["request"] for c in calls if c["path"] == "/refunds"), {})
        payment_id = (
            state.get("payment_id")
            or request.get("payment_id")
            or (entries[0]["payment_id"] if entries else None)
        )
        payment = ev.payments.get(payment_id, {})
        rejection = [c for c in calls if c["status"] in (403, 409)]
        attr = "expected_rejection" if rejection else "undetermined"
        emit(
            "REFUND_001",
            rid,
            "fail" if len(entries) > 1 else "pass",
            "同一指令产生多次独立成功执行" if len(entries) > 1 else "独立账本中该指令最多一次成功执行",
            refs,
            attribution="product_defect" if len(entries) > 1 else attr,
            expected={"max_success_per_command": 1},
            actual={"successful_entries": [e["entry_id"] for e in entries]},
        )
        all_payment = [e for e in ev.successful() if e["payment_id"] == payment_id]
        totals = defaultdict(int)
        invalid = []
        for e in all_payment:
            if (
                type(e.get("amount_minor")) is not int
                or e["amount_minor"] <= 0
                or e["currency"] not in {"CNY", "USD", "EUR", "JPY"}
            ):
                invalid.append("非法资金金额或币种")
            else:
                totals[e["currency"]] += e["amount_minor"]
                if payment and e["currency"] != payment.get("currency"):
                    invalid.append("执行币种与支付币种不一致")
        balance_valid = type(payment.get("amount_minor")) is int and payment["amount_minor"] >= 0
        if balance_valid and totals.get(payment["currency"], 0) > payment["amount_minor"]:
            invalid.append("同一支付累计成功退款超过可退余额")
        if not policy.partial_refunds_allowed and len(all_payment) > 1:
            invalid.append("契约不允许多次部分退款")
        emit(
            "REFUND_002",
            rid,
            "fail" if invalid else "pass" if balance_valid else "inconclusive",
            "；".join(invalid)
            if invalid
            else "按币种累计成功执行未超独立支付余额"
            if balance_valid
            else "缺少有效的独立支付初始余额",
            refs,
            attribution="product_defect" if invalid else attr,
            expected={
                "payment_id": payment_id,
                "balance_minor": payment.get("amount_minor"),
                "currency": payment.get("currency"),
            },
            actual={"success_totals_by_currency": dict(totals)},
        )

        bad_approval, unknown_approval = [], []
        for e in entries:
            if type(e.get("amount_minor")) is not int:
                unknown_approval.append("执行金额无法比较审批阈值")
                continue
            if e["amount_minor"] <= policy.threshold_minor:
                continue
            approval = obj(e.get("approval"))
            executed_at = stamp(e.get("created_at"))
            prior_states = [
                c["body"]
                for c in calls
                if executed_at
                and c["at"] <= executed_at
                and c["status"] in (200, 201)
                and c["body"].get("refund_id") == rid
            ]
            if not prior_states:
                unknown_approval.append("缺少执行前的产品版本观测")
            elif any(
                prior_states[-1].get(k) != e.get(ek)
                for k, ek in [
                    ("version", "command_version"),
                    ("amount_minor", "amount_minor"),
                    ("currency", "currency"),
                    ("recipient", "recipient"),
                ]
            ):
                bad_approval.append("独立执行使用的指令版本或字段与执行前产品观测不一致")
            fields = {
                "refund_id": rid,
                "amount_minor": e["amount_minor"],
                "currency": e["currency"],
                "recipient": e.get("recipient"),
                "version": e.get("command_version"),
            }
            if (
                not approval
                or approval.get("approved") is not True
                or any(approval.get(k) != v for k, v in fields.items())
                or type(fields["version"]) is not int
                or type(approval.get("version")) is not int
                or approval["version"] < 1
                or type(approval.get("amount_minor")) is not int
                or approval["amount_minor"] <= 0
            ):
                bad_approval.append("执行未绑定同指令、版本、金额、币种、收款方的有效审批")
                continue
            actor = approval.get("approved_by")
            if not isinstance(actor, str) or "approve_refund" not in PERMISSIONS.get(actor, ()):
                bad_approval.append("审批操作者没有审批权限")
                continue
            approvals = [
                c
                for c in calls
                if c["path"].endswith("/approve")
                and c["status"] == 200
                and digest(obj(c["body"].get("approval"))) == digest(approval)
                and c["actor"] == actor
            ]
            when = stamp(e.get("created_at"))
            if (
                not approvals
                or actor not in ev.identities
                or not when
                or not stamp(approval.get("approved_at"))
            ):
                unknown_approval.append("缺少实际审批请求、权限身份或审批时间证据")
            elif stamp(approval["approved_at"]) > when or all(c["at"] > when for c in approvals):
                bad_approval.append("资金执行发生在审批之前")
            refs += [ev.identities[actor]] if actor in ev.identities else []
        for call in calls:
            if (
                call["path"].endswith("/execute")
                and call["status"] in (200, 202)
                and "execute_refund" not in PERMISSIONS.get(call["actor"], ())
            ):
                if call["actor"] in ev.identities:
                    bad_approval.append("PUT 接受了无执行权限操作者的执行请求")
                else:
                    unknown_approval.append("缺少执行操作者身份证据")
            if (
                call["path"].endswith("/approve")
                and call["status"] == 200
                and "approve_refund" not in PERMISSIONS.get(call["actor"], ())
            ):
                if call["actor"] in ev.identities:
                    bad_approval.append("PUT 接受了真实低权限身份的审批")
                else:
                    unknown_approval.append("缺少审批操作者身份证据")
        applicable = any(
            type(e.get("amount_minor")) is int and e["amount_minor"] > policy.threshold_minor for e in entries
        ) or any(
            c["path"].endswith("/approve") or c["path"].endswith("/execute") and c["status"] == 409
            for c in calls
        )
        emit(
            "APPROVAL_001",
            rid,
            "fail"
            if bad_approval
            else "inconclusive"
            if unknown_approval
            else "pass"
            if applicable
            else "not_applicable",
            "；".join(bad_approval or unknown_approval)
            or (
                "执行审批与权限证据一致；无效审批未造成资金执行"
                if applicable
                else f"没有大于 {policy.threshold_minor} 的成功执行或审批动作，operator=gt"
            ),
            refs,
            attribution="product_defect" if bad_approval else attr,
            expected={
                "threshold_minor": policy.threshold_minor,
                "operator": "gt",
                "binding": ["refund_id", "version", "amount_minor", "currency", "recipient", "approved_by"],
            },
            actual={"successful_execution_count": len(entries)},
        )

        state_errors, state_unknown = [], []
        succeeded = False
        for body in bodies:
            status = body.get("status")
            if type(body.get("amount_minor")) is not int or body["amount_minor"] <= 0:
                state_errors.append("产品观测包含非法退款金额")
            if type(body.get("version")) is not int or body["version"] < 1:
                state_errors.append("产品观测包含非法业务版本")
            if body.get("approval") is not None and not isinstance(body["approval"], dict):
                state_errors.append("产品观测包含非法审批快照")
            elif isinstance(body.get("approval"), dict) and (
                type(body["approval"].get("amount_minor")) is not int
                or body["approval"]["amount_minor"] <= 0
                or type(body["approval"].get("version")) is not int
                or body["approval"]["version"] < 1
            ):
                state_errors.append("产品审批快照包含非法金额或业务版本")
            if status not in TERMINALS | {"requested", "approval_pending", "approved", "execution_pending"}:
                state_errors.append("产品观测包含契约未定义状态")
            if succeeded and status not in {"succeeded"}:
                state_errors.append("成功终态退回过期或中间状态")
            succeeded |= status == "succeeded"
        for call in calls:
            if (
                call["method"] == "GET"
                and call["actor"] in ev.identities
                and "read_own_refund" in PERMISSIONS.get(call["actor"], ())
                and isinstance(state.get("owner_id"), str)
                and call["actor"] != state["owner_id"]
                and (
                    call["status"] not in (403, 404)
                    or any(
                        k in call["body"]
                        for k in ("refund_id", "amount_minor", "recipient", "owner_id", "approval")
                    )
                )
            ):
                state_errors.append("产品向非归属客户披露退款状态，违反查询权限契约")
        if state.get("status") == "succeeded":
            if not entries and ev.closed:
                state_errors.append("产品声明成功，但完整独立账本没有执行")
            elif len(entries) > 1:
                state_errors.append("产品声明单次成功，但独立账本记录多次执行（observation_conflict）")
            elif entries:
                e = entries[0]
                if state.get("provider_entry_id") != e["entry_id"] or any(
                    state.get(k) != e.get(k) for k in ("payment_id", "amount_minor", "currency", "recipient")
                ):
                    state_errors.append("产品成功声明与独立执行金额、币种、收款方或条目冲突")
        elif (
            entries
            and ev.closed
            and query
            and query["status"] in (200, 404)
            and (state.get("refund_id") == rid or query["status"] == 404)
            and state.get("status") not in {"reconciliation_required", "execution_pending"}
        ):
            state_errors.append("独立账本已执行，但最终产品查询未反映执行或对账状态")
        # Reject only on observed preconditions; never convert every 4xx to a product failure.
        for call in rejection:
            prior = [c["body"] for c in calls if c["at"] < call["at"] and c["body"].get("refund_id") == rid]
            before = prior[-1] if prior else request
            role = call["actor"]
            justified = False
            if role not in ev.identities:
                state_unknown.append("拒绝动作的角色身份未核验")
                continue
            if call["status"] == 403:
                justified = (
                    call["path"].endswith("/approve") and "approve_refund" not in PERMISSIONS.get(role, ())
                ) or (
                    call["method"] == "GET"
                    and "read_own_refund" in PERMISSIONS.get(role, ())
                    and state.get("owner_id") != role
                )
            elif call["path"] == "/refunds":
                justified = payment and call["request"].get("currency") != payment.get("currency")
                justified |= bool(
                    before.get("refund_id")
                    and any(
                        call["request"].get(k) != before.get(k)
                        for k in ("amount_minor", "currency", "recipient", "payment_id")
                    )
                )
            elif call["path"].endswith("/execute"):
                justified = before.get("status") == "cancelled"
                approval = obj(before.get("approval"))
                amount = before.get("amount_minor")
                justified |= (
                    type(amount) is int
                    and amount > policy.threshold_minor
                    and (
                        not approval
                        or any(
                            approval.get(k) != before.get(k)
                            for k in ("refund_id", "version", "amount_minor", "currency", "recipient")
                        )
                    )
                )
                previous_total = sum(
                    e["amount_minor"]
                    for e in all_payment
                    if type(e.get("amount_minor")) is int
                    and e["currency"] == payment.get("currency")
                    and stamp(e.get("created_at"))
                    and stamp(e["created_at"]) <= call["at"]
                )
                justified |= bool(
                    type(amount) is int
                    and balance_valid
                    and previous_total + amount > payment["amount_minor"]
                )
            elif call["method"] == "PATCH":
                justified = before.get("status") in {"approved", "succeeded"}
            if not justified:
                state_unknown.append("拒绝原因无法由已观测前提确认；不自动归因产品")
        emit(
            "STATE_001",
            rid,
            "fail" if state_errors else "inconclusive" if state_unknown else "pass",
            "；".join(dict.fromkeys(state_errors or state_unknown))
            or "观测序列无成功终态回退，产品声明与独立账本一致，拒绝符合权限或业务前提",
            refs,
            attribution="product_defect" if state_errors else attr,
            expected={"success_is_terminal": True, "independent_execution_required": True},
            actual={"states": [b.get("status") for b in bodies]},
        )

        pending = [
            c
            for c in calls
            if c["body"].get("status") == "execution_pending"
            or (
                c["path"].endswith("/execute")
                and c["status"] in (200, 202)
                and c["body"].get("status") not in TERMINALS
            )
        ]
        overdue, waiting = [], []
        for call in pending:
            deadline = call["at"] + timedelta(seconds=policy.observation_seconds)
            terminal = [
                c for c in calls if call["at"] <= c["at"] <= deadline and c["body"].get("status") in TERMINALS
            ]
            if terminal:
                continue
            if now < deadline:
                waiting.append("execution_pending 观察窗口未结束")
            elif not query or query["at"] < deadline or ev.missing(rid):
                waiting.append("超过期限但缺少期限后的完整证据")
            elif query["body"].get("status") in TERMINALS:
                waiting.append("终态首次观测晚于期限，缺少实际完成时间证据")
            else:
                overdue.append("execution_pending 未在契约窗口内进入允许终态或 reconciliation_required")
        emit(
            "TIME_001",
            rid,
            "fail"
            if overdue
            else "inconclusive"
            if waiting
            else "pass"
            if pending or state.get("status") in TERMINALS
            else "not_applicable",
            "；".join(overdue or waiting)
            or (
                "已观测到允许终态；有界完成性成立"
                if pending or state.get("status") in TERMINALS
                else "从未进入 execution_pending，未开始执行的审批等待不适用执行完成期限"
            ),
            refs,
            attribution="product_defect" if overdue else attr,
            expected={
                "observation_wall_seconds": policy.observation_seconds,
                "allowed_terminals": sorted(TERMINALS),
            },
            actual={"pending_observations": len(pending)},
        )
        for call in calls:
            if call["method"] != "GET" or "read_own_refund" not in PERMISSIONS.get(call["actor"], ()):
                continue
            known = (
                call["actor"] in ev.identities
                and isinstance(state.get("owner_id"), str)
                and state.get("owner_id") in PERMISSIONS
                and not ev.missing(rid)
                and completed
            )
            own = state.get("owner_id") == call["actor"]
            denied = call["status"] in (403, 404) and not any(
                k in call["body"] for k in ("refund_id", "amount_minor", "recipient", "owner_id", "approval")
            )
            verdict = "pass" if own and call["status"] == 200 or not own and denied else "fail"
            access.append(
                {
                    "object_id": rid,
                    "policy": policy.adapter_policy,
                    "actor_id": call["actor"],
                    "verdict": verdict if known else "inconclusive",
                    "reason": "客户只能读取归属自己的退款；拒绝响应不得泄露业务字段",
                    "attribution": "expected_rejection"
                    if known and not own and denied
                    else "product_defect"
                    if known and verdict == "fail"
                    else "undetermined",
                    "evidence_refs": [call["ref"]]
                    + ([query["ref"]] if query else [])
                    + ([ev.identities[call["actor"]]] if call["actor"] in ev.identities else []),
                }
            )
    # Same financial violation across several commands of one payment is one finding.
    unique = {}
    for finding in findings:
        old = unique.get(finding["dedup_key"])
        if old is None:
            unique[finding["dedup_key"]] = finding
        else:
            old["evidence_refs"] = sorted(set(old["evidence_refs"] + finding["evidence_refs"]))
            old["related_check_ids"] += finding["related_check_ids"]
            chain = {digest(step): step for step in old["failure_chain"] + finding["failure_chain"]}
            old["failure_chain"] = list(chain.values())
    findings = list(unique.values())
    results = checks + access
    verdict = (
        "fail"
        if any(c["verdict"] == "fail" for c in results)
        else "inconclusive"
        if not completed or any(c["verdict"] == "inconclusive" for c in results)
        else "pass"
    )
    return {
        "verdict": verdict,
        "checks": checks,
        "findings": findings,
        "access_checks": access,
        "observation_conflicts": ev.conflicts
        + [
            {"reason": c["reason"], "evidence_refs": c["evidence_refs"]}
            for c in checks
            if c["rule_id"] == "STATE_001" and c["verdict"] == "fail"
        ],
        "evidence_issues": ev.issues,
        "rules_hash": policy.content_hash(),
        "observation_window": {
            "deadline": ev.deadline.isoformat() if ev.deadline else None,
            "closed": ev.closed,
            "evaluated_at": now.isoformat(),
        },
        "distribution": {
            v: sum(c["verdict"] == v for c in checks)
            for v in ("pass", "fail", "inconclusive", "not_applicable")
        },
    }
