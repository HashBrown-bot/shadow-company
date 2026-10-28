from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from packages.contracts.config import Configuration
from packages.transport.access import client_headers
from services.api.main import create_app
from tests.conftest import EXAMPLE_PATH


def project(client):
    response = client.post("/api/projects", json={"name": "示例 E2 测试 " + uuid4().hex})
    assert response.status_code == 201
    return response.json()["id"]


def test_health_and_schema(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ready"
    assert health.json()["business_execution"] == "e7_hybrid_offline"
    assert client.get("/api/contracts/schema").json() == Configuration.model_json_schema()


def test_project_persistence_and_validation(client, database):
    identifier = project(client)
    with TestClient(create_app(database), headers=client_headers()) as second_client:
        items = second_client.get("/api/projects").json()["items"]
        assert identifier in {p["id"] for p in items}
    assert client.post("/api/projects", json={"name": "   "}).status_code == 422
    assert (
        client.post("/api/projects", json={"name": "x", "local_access_policy": "public"}).status_code == 422
    )
    assert client.get("/api/projects?limit=101").status_code == 422


def test_contract_versions_cannot_be_overwritten(client, config_data):
    identifier = project(client)
    route = f"/api/projects/{identifier}/contract"
    first = client.put(route, json={"version": "v1", "config": config_data})
    assert first.status_code == 200
    assert client.put(route, json={"version": "v1", "config": config_data}).json() == first.json()
    config_data["runtime"]["seed"] += 1
    conflict = client.put(route, json={"version": "v1", "config": config_data})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "version_conflict"
    assert client.get(route + "/v1").json() == first.json()
    assert client.put(route, json={"version": "v2", "config": config_data}).status_code == 200
    assert client.get(f"/api/projects/{uuid4()}/contract/v1").status_code == 404


def test_concurrent_contract_writes_cannot_replace_winner(client, config_data):
    identifier = project(client)
    route = f"/api/projects/{identifier}/contract"
    other = Configuration.model_validate(config_data).model_dump(mode="json")
    other["runtime"]["seed"] += 1
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda c: client.put(route, json={"version": "same", "config": c}), [config_data, other]
            )
        )
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r for r in responses if r.status_code == 200).json()
    assert client.get(route + "/same").json() == winner


def test_yaml_validation_is_not_business_success(client):
    response = client.post("/api/contracts/validate", json={"yaml": EXAMPLE_PATH.read_text()})
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["business_verdict"] == "inconclusive"
    assert response.json()["preflight"] == "not_performed"


def test_missing_ledger_has_clear_path(client):
    response = client.post(
        "/api/contracts/validate",
        json={"yaml": EXAMPLE_PATH.read_text().replace("    provider_ledger: required\n", "")},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["details"][0]["path"] == "product.observations.provider_ledger"
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_rejected_secret_never_returned(client, config_data):
    identifier = project(client)
    sentinel = "sensitive" + "-negative-test-canary"
    config_data["product"]["credentials"]["support"] = sentinel
    response = client.put(
        f"/api/projects/{identifier}/contract", json={"version": "v1", "config": config_data}
    )
    assert response.status_code == 422
    assert sentinel not in response.text
    assert "input" not in response.json()["error"]["details"][0]


def test_unknown_rule_diagnostic_does_not_echo_secret(client, config_data):
    import yaml

    sentinel = "sensitive" + "-rule-id-canary"
    config_data["rules"][0]["id"] = sentinel
    response = client.post("/api/contracts/validate", json={"yaml": yaml.safe_dump(config_data)})
    assert response.status_code == 422
    assert sentinel not in response.text
    assert response.json()["error"]["details"][0]["type"] == "union_tag_invalid"


def test_invalid_run_never_enqueues_fake_success(client, database):
    response = client.post("/api/runs", json={})
    assert response.status_code == 422
    with database.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0


def test_database_outage_is_not_healthy():
    db = create_engine(
        "postgresql+psycopg://sim@127.0.0.1:1/unavailable", connect_args={"connect_timeout": 1}
    )
    try:
        with TestClient(create_app(db)) as client:
            response = client.get("/api/health")
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "database_unavailable"
            assert "postgresql" not in response.text
    finally:
        db.dispose()


def test_unknown_route_has_uniform_error(client):
    response = client.get("/api/not-a-route")
    assert response.status_code == 404
    assert set(response.json()["error"]) == {"code", "message", "details", "request_id"}
