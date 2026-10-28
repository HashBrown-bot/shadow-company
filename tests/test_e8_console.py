"""E8 projections use the existing PostgreSQL/API/evaluator, without UI fixtures."""

from uuid import uuid4

from sqlalchemy import text

from packages.contracts.config import Configuration
from packages.transport.security import Scope
from tests.test_e7_live import project, start


def test_catalog_uses_existing_strict_contract_and_disables_unavailable_clock(client):
    catalog = client.get("/api/console/catalog").json()
    assert catalog["example"] is True
    Configuration.model_validate(catalog["config"])
    assert len(catalog["scenarios"]) == 20
    assert [m["id"] for m in catalog["time_modes"] if m["supported"]] == ["event_compressed", "realtime"]
    assert catalog["model"]["supported"] is False


def test_project_and_contract_pagination_and_scope(client, config_data):
    p = client.post("/api/projects", json={"name": "E8 pagination"}).json()["id"]
    for i in range(12):
        response = client.put(f"/api/projects/{p}/contract", json={"version": f"v{i}", "config": config_data})
        assert response.status_code == 200
    one = client.get(f"/api/projects/{p}/contracts?limit=5").json()
    two = client.get(f"/api/projects/{p}/contracts?limit=5&offset=5").json()
    assert one["total"] == two["total"] == 12
    assert len(one["items"]) == len(two["items"]) == 5
    assert not {c["version"] for c in one["items"]} & {c["version"] for c in two["items"]}
    assert client.get(f"/api/projects/{p}/runs").json()["total"] == 0
    assert client.get(f"/api/projects/{p}/preflight?contract_version=v0").json() == {"result": None}
    assert client.get(f"/api/projects/{uuid4()}/contracts").status_code == 404
    assert client.get(f"/api/projects/{p}/contracts?limit=101").status_code == 422
    summary = client.get(f"/api/projects/{p}").json()
    assert summary["product_versions"] == [config_data["product"]["version"]]
    assert summary["latest_run"] is None


def test_yaml_roundtrip_returns_backend_parsed_config(client):
    catalog = client.get("/api/console/catalog").json()
    value = client.post("/api/contracts/validate", json={"yaml": catalog["template_yaml"]}).json()
    assert value["config"] == catalog["config"]
    assert value["business_verdict"] == "inconclusive" and value["preflight"] == "not_performed"


def test_live_finding_and_timeline_are_scoped_and_evidence_based(live_stack):
    http = live_stack["http"]
    p = project(http, "buggy")
    scope, report = start(http, p, ["S12"], "buggy")

    def get(suffix, **params):
        response = http.get(
            f"http://127.0.0.1:8000/api/runs/{scope.run_id}/{suffix}", params={"project_id": p, **params}
        )
        assert response.status_code == 200, response.text
        return response.json()

    view = get("console")
    assert view["run"]["verdict"] == report["verdict"] == "fail"
    assert view["worker"]["state"] == "not_running"
    assert view["finding_count"] == len(report["findings"])
    assert view["report"]["ci_gates"] == report["ci_gates"]
    assert view["report"]["ci_gates"]["selected"]["exit_code"] == 1
    findings = get("findings", limit=1)
    assert findings["total"] > 0 and len(findings["items"]) == 1
    finding = get("findings/" + findings["items"][0]["finding_id"])
    assert finding["rule"]["version"] == "1" and finding["finding"]["expected"]
    assert finding["evaluation_rule_version"] == report["versions"]["rule_version"] == "2"
    assert finding["evidence"]["items"][0]["source"] == "provider_ledger"
    assert finding["missing_evidence_refs"] == []
    for observation in finding["evidence"]["items"]:
        assert str(observation["project_id"]) == p and str(observation["run_id"]) == str(scope.run_id)
        request = observation["payload"].get("request", {})
        if "Authorization" in request.get("headers", {}):
            assert request["headers"]["Authorization"] == "[REDACTED]"
    for lane in ["actor", "product", "provider", "evaluator"]:
        entries = get("timeline", lane=lane, limit=2)
        assert entries["total"] >= 1
        assert all(e["lane"] == lane for e in entries["items"])
    first = get("timeline", limit=5)
    second = get("timeline", limit=5, offset=5)
    assert first["total"] == second["total"]
    beyond = get("timeline", limit=5, offset=100000)
    assert beyond["items"] == [] and beyond["total"] == first["total"]
    assert not {e["id"] for e in first["items"]} & {e["id"] for e in second["items"]}
    for suffix in [
        "console",
        "timeline",
        "findings",
        "checks",
        "findings/" + findings["items"][0]["finding_id"],
    ]:
        assert (
            http.get(
                f"http://127.0.0.1:8000/api/runs/{scope.run_id}/{suffix}", params={"project_id": str(uuid4())}
            ).status_code
            == 404
        )
    listing = http.get(f"http://127.0.0.1:8000/api/projects/{p}/runs").json()
    assert listing["total"] == 1  # preflight probes are not user runs
    assert listing["items"][0]["verdict"] == "fail"


def test_worker_lost_is_lease_state_not_business_failure(client, database, config_data):
    p = client.post("/api/projects", json={"name": "E8 lease projection"}).json()["id"]
    saved = client.put(f"/api/projects/{p}/contract", json={"version": "v1", "config": config_data}).json()
    scope = Scope(project_id=p, run_id=uuid4())
    with database.begin() as c:
        c.execute(
            text(
                "INSERT INTO runs(project_id,run_id,contract_version,contract_hash,put_version,seed,time_mode,status) VALUES (:p,:r,'v1',:h,'fixed',1,'realtime','running')"
            ),
            scope.params | {"h": saved["content_hash"]},
        )
        c.execute(
            text(
                "INSERT INTO jobs(project_id,run_id,job_id,idempotency_key,state,owner,expires_at,heartbeat) VALUES (:p,:r,:j,:k,'leased','test-owner',now()-interval '1 second',now()-interval '4 seconds')"
            ),
            scope.params | {"j": uuid4(), "k": uuid4().hex},
        )
    view = client.get(f"/api/runs/{scope.run_id}/console", params={"project_id": p}).json()
    assert view["worker"]["state"] == "lost"
    assert view["run"]["status"] == "running" and view["run"]["verdict"] == "inconclusive"
    assert view["report"] is None
