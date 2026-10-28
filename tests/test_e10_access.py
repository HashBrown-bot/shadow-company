"""E10 counterexamples for evidence permissions and shared redaction boundaries."""

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from adapters.http.credit import FIELDS, REVERSE, rename
from packages.simulator.actors import scrub
from packages.transport.access import access_request
from packages.transport.security import canonical, digest, redact
from scripts.scan_secrets import PATTERNS


@pytest.mark.parametrize(
    "endpoint", ["report", "history", "manifest", "findings", "timeline", "events", "console", "checks"]
)
def test_read_only_grant_cannot_read_any_evidence_projection(monkeypatch, endpoint):
    project, run = str(uuid4()), str(uuid4())
    monkeypatch.setattr(
        "packages.transport.access.authenticate",
        lambda _: {"projects": [project], "runs": None, "permissions": ["read"]},
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/runs/{run}/{endpoint}",
            "query_string": f"project_id={project}".encode(),
            "headers": [],
        }
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(access_request(request))
    assert error.value.status_code == 403


def test_rpc_wire_payee_is_redacted_without_changing_illegal_business_values():
    payee = "synthetic-recipient-" + uuid4().hex
    clean = redact(
        {
            "body": {"recipient": payee},
            "wire": {"request": {"params": {"payee": payee, "units": -50, "unitCurrency": "INVALID"}}},
        }
    )
    if payee in canonical(clean):
        pytest.fail("RPC wire retained a recipient value that the canonical projection redacted")
    assert clean["body"]["recipient"] == "sha256:" + digest(payee)
    assert clean["wire"]["request"]["params"]["units"] == -50
    assert clean["wire"]["request"]["params"]["unitCurrency"] == "INVALID"


@pytest.mark.parametrize("cleaner", [redact, scrub])
@pytest.mark.parametrize("last_character", ["x", "-", "_"])
def test_bare_local_access_token_is_removed_from_shared_text(cleaner, last_character):
    synthetic_token = "sim_" + "x" * 42 + last_character
    clean = cleaner({"message": "Returned credential " + synthetic_token})
    if synthetic_token in canonical(clean):
        pytest.fail("Recognizable local access credential survived the text sharing boundary")


def test_echoed_request_credential_is_also_removed_from_response_object_keys():
    synthetic_token = "synthetic-request-" + uuid4().hex
    clean = redact({synthetic_token: {"message": synthetic_token}}, [synthetic_token])
    if synthetic_token in canonical(clean):
        pytest.fail("A credential echoed as an object key escaped the shared evidence boundary")


def test_rpc_redaction_keeps_canonical_approval_and_business_semantics():
    document = {
        "refund_id": "r1",
        "payment_id": "p1",
        "amount_minor": 200001,
        "currency": "CNY",
        "recipient": "synthetic-recipient",
        "version": 2,
        "status": "approved",
        "approval": {
            "version": 1,
            "amount_minor": 200001,
            "currency": "CNY",
            "recipient": "synthetic-recipient",
            "actor_role": "approver",
        },
    }
    wire = rename(document, FIELDS)
    canonical_document = rename(wire, REVERSE)
    assert canonical_document == document
    clean = redact({"body": canonical_document, "wire": wire})
    assert clean["body"] == redact(document)
    assert clean["body"]["approval"]["version"] == 1
    assert clean["body"]["version"] == 2
    assert clean["body"]["approval"]["recipient"] == clean["body"]["recipient"]
    assert clean["wire"]["payee"] == clean["body"]["recipient"]
    assert clean["wire"]["units"] == document["amount_minor"]


@pytest.mark.parametrize("last_character", ["x", "-", "_"])
def test_export_scanner_detects_every_legal_local_token_ending(last_character):
    synthetic_token = "sim_" + "x" * 42 + last_character
    if not PATTERNS["local_access_token"].search("credential " + synthetic_token + " end"):
        pytest.fail("Export scanner missed a legal local access credential ending")
