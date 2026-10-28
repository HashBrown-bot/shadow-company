import importlib.util
import socket
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from packages.transport.http import BoundaryError, SafeHTTP
from packages.transport.security import Scope, digest, headers, signature, verify_signature
from tests.test_migrations import seed_run


def test_dns_rebinding_and_metadata_rejected(monkeypatch):
    http = SafeHTTP({"http://refund-put:8001": ["127.0.0.1"]})
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 8001))],
    )
    with pytest.raises(BoundaryError, match="DNS"):
        http.resolve("http://refund-put:8001")
    hostile = SafeHTTP({"http://refund-put:8001": ["169.254.169.254"]})
    with pytest.raises(BoundaryError, match="元数据"):
        hostile.resolve("http://refund-put:8001")


def test_transport_pins_resolved_ip_and_rejects_redirect(monkeypatch):
    import http.client

    calls = []

    class Response:
        status = 302

        def read(self, _):
            return b"{}"

    class Connection:
        def __init__(self, host, port, timeout):
            calls.append((host, port))

        def request(self, method, path, body, headers):
            calls.append(headers["Host"])

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 8001))],
    )
    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    http = SafeHTTP({"http://refund-put:8001": ["127.0.0.1"]})
    with pytest.raises(BoundaryError, match="重定向"):
        http.request("GET", "http://refund-put:8001", "/health")
    assert calls == [("127.0.0.1", 8001), "refund-put:8001"]


@pytest.mark.parametrize(
    "path", ["//169.254.169.254", "/../admin", "/%2e%2e/admin", "/x\\y", "/x\r\nHost:evil"]
)
def test_path_escape_rejected(path):
    with pytest.raises(BoundaryError):
        SafeHTTP().request("GET", "http://127.0.0.1:8001", path)


def test_webhook_future_and_signed_byte_integrity():
    scope = Scope(project_id=uuid4(), run_id=uuid4())
    now = int(time.time())
    body = b'{"a":1}'
    verify_signature(scope, now, body, signature(scope, now, body), now=now)
    with pytest.raises(HTTPException):
        verify_signature(scope, now, body + b" ", signature(scope, now, body), now=now)
    with pytest.raises(HTTPException):
        verify_signature(scope, now + 301, body, signature(scope, now + 301, body), now=now)


@pytest.mark.parametrize("service", ["refund-put", "payment-provider"])
def test_test_admin_disabled_outside_test_mode(service, database, monkeypatch):
    spec = importlib.util.spec_from_file_location("example_" + service, "examples/" + service + "/main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("EXAMPLE_TEST_MODE")
    scope = Scope(project_id=uuid4(), run_id=uuid4())
    role = "put_admin" if service == "refund-put" else "provider_admin"
    with TestClient(module.create_app(database)) as client:
        assert client.post("/test/reset", headers=headers(role, scope)).status_code == 404


def test_reset_audit_cannot_authorize_another_scope(database, config_data):
    scope = seed_run(database, config_data)
    other = seed_run(database, config_data)
    audit = uuid4()
    with database.begin() as c:
        c.execute(
            text(
                "INSERT INTO reset_audits (project_id,run_id,reset_id,payload,content_hash) VALUES (:p,:r,:id,'{}',:hash)"
            ),
            scope | {"id": audit, "hash": digest({})},
        )
        c.execute(
            text("""INSERT INTO observations (project_id,run_id,observation_id,source,external_id,evidence_kind,raw_ref,digest,captured_at,payload)
         VALUES (:p,:r,:id,'put','x','product_observation','private://x',:h,now(),'{}')"""),
            other | {"id": uuid4()},
        )
    with pytest.raises(IntegrityError, match="immutable record"):
        with database.begin() as c:
            c.execute(text("SELECT set_config('simulation.reset_id',:id,true)"), {"id": str(audit)})
            c.execute(text("DELETE FROM observations WHERE project_id=:p AND run_id=:r"), other)


def test_raw_trace_redacts_credentials_even_when_echoed_in_response(database, config_data):
    from packages.evidence.store import append

    scope = seed_run(database, config_data)
    scope = Scope(project_id=scope["p"], run_id=scope["r"])
    canary = "generated-for-test-" + uuid4().hex
    with database.begin() as c:
        oid = append(
            c,
            scope,
            "put",
            "redaction",
            "product_observation",
            {
                "request": {"headers": {"Authorization": "Bearer " + canary, "Cookie": canary}},
                "response": {"body": {"echo": canary, "amount_minor": -50, "currency": "INVALID"}},
            },
        )
        stored = c.execute(
            text("SELECT payload FROM observations WHERE project_id=:p AND run_id=:r AND observation_id=:id"),
            scope.params | {"id": oid},
        ).scalar_one()
    assert canary not in str(stored)
    assert (
        stored["response"]["body"]["amount_minor"] == -50
        and stored["response"]["body"]["currency"] == "INVALID"
    )


def test_generated_service_credentials_exclude_ledger_key_from_put(tmp_path):
    import json

    from packages.transport.security import provision, service_credentials

    root = tmp_path / "generated.json"
    provision(root)
    put = json.loads(service_credentials(root, "refund-put").read_text())
    assert "provider_reader" not in put and "provider_admin" not in put
    assert set(put) == {
        "support",
        "approver",
        "customer_a",
        "customer_b",
        "put_admin",
        "provider_execute",
        "webhook",
    }


def test_webhook_does_not_acknowledge_before_storage(database, config_data, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    import services.api.e3 as api
    from packages.transport.security import canonical
    from services.api.main import create_app

    scope = seed_run(database, config_data)
    scope = Scope(project_id=scope["p"], run_id=scope["r"])
    binding = uuid4()
    event_id = uuid4()
    with database.begin() as c:
        c.execute(
            text("INSERT INTO webhook_bindings VALUES (:p,:r,:b,:s)"),
            scope.params | {"b": binding, "s": "secret://demo/webhook/test"},
        )
    payload = scope.model_dump(mode="json") | {
        "event_id": str(event_id),
        "entry_id": str(uuid4()),
        "refund_command_id": "test-refund",
        "payment_id": "test-payment",
        "amount_minor": 100,
        "currency": "CNY",
        "status": "succeeded",
    }
    body = canonical(payload).encode()
    stamp = int(time.time())
    signed = {"X-Webhook-Timestamp": str(stamp), "X-Webhook-Signature": signature(scope, stamp, body)}

    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("injected storage outage")

    with TestClient(create_app(database)) as client:
        with monkeypatch.context() as patch:
            patch.setattr(api, "append", unavailable)
            assert (
                client.post("/api/webhooks/" + str(binding), content=body, headers=signed).status_code == 503
            )
        with database.connect() as c:
            assert (
                c.execute(
                    text("SELECT count(*) FROM webhook_receipts WHERE project_id=:p AND run_id=:r"),
                    scope.params,
                ).scalar_one()
                == 0
            )
        assert client.post("/api/webhooks/" + str(binding), content=body, headers=signed).status_code == 200
        with database.connect() as c:
            assert (
                c.execute(
                    text("SELECT count(*) FROM webhook_receipts WHERE project_id=:p AND run_id=:r"),
                    scope.params,
                ).scalar_one()
                == 1
            )
