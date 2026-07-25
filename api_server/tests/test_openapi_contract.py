from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.errors import ErrorEnvelope
from app.main import create_app
from app.schemas.contracts import ApiErrorEnvelope, HealthLive
from scripts.export_openapi_contract import (
    CONTRACT_PATH,
    HTTP_METHODS,
    build_contract,
    canonical_bytes,
    main,
    validate_contract,
    validate_live_compatibility,
)

CONTRACTS = Path(__file__).parents[1] / "contracts"


def _operations(schema: dict):
    for path, item in schema["paths"].items():
        for method in HTTP_METHODS:
            operation = item.get(method)
            if isinstance(operation, dict):
                yield path, method, operation


def test_checked_in_contract_is_deterministic_and_current() -> None:
    generated = build_contract()
    assert validate_contract(generated) == []
    assert validate_live_compatibility(generated) == []
    assert CONTRACT_PATH.read_bytes() == canonical_bytes(generated)
    assert main(["--check"]) == 0


def test_contract_covers_every_required_resource_without_fake_routes() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    live = create_app().openapi()
    required = {
        "access",
        "documents",
        "pages",
        "jobs",
        "regions",
        "text-lines",
        "corrections",
        "exports",
        "diagnostics",
    }
    seen: set[str] = set()
    for path, method, operation in _operations(contract):
        seen.update(operation.get("tags", []))
        status = operation["x-implementation-status"]
        assert status in {"live", "planned"}
        is_live = method in live.get("paths", {}).get(path, {})
        assert is_live is (status == "live")
    assert required <= seen


def test_resource_ids_and_timestamps_have_wire_formats() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    schemas = contract["components"]["schemas"]
    resources = ("Document", "Page", "RecognitionJob", "RecognitionRegion", "TextLine", "Correction", "ExportArtifact")
    for resource in resources:
        properties = schemas[resource]["properties"]
        assert properties["id"]["format"] == "uuid"
        assert properties["created_at"]["format"] == "date-time"
        assert properties["updated_at"]["format"] == "date-time"
    for path, _method, operation in _operations(contract):
        for parameter in operation.get("parameters", []):
            if parameter["in"] == "path" and parameter["name"].endswith("_id"):
                assert parameter["schema"]["format"] == "uuid", path


def test_text_contract_keeps_raw_suggested_and_confirmed_separate() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    properties = contract["components"]["schemas"]["TextLine"]["properties"]
    assert {"raw_text", "suggested_text", "confirmed_text"} <= properties.keys()
    patch_properties = contract["components"]["schemas"]["TextLinePatch"]["properties"]
    assert "raw_text" not in patch_properties


def test_health_and_error_fixtures_match_runtime_and_public_schemas() -> None:
    health_fixture = json.loads((CONTRACTS / "health-live.json").read_text(encoding="utf-8"))
    error_fixture = json.loads((CONTRACTS / "error-envelope.json").read_text(encoding="utf-8"))
    assert HealthLive.model_validate(health_fixture).model_dump(mode="json") == health_fixture
    assert ApiErrorEnvelope.model_validate(error_fixture).model_dump(mode="json") == error_fixture
    assert ErrorEnvelope.model_validate(error_fixture).model_dump(mode="json") == error_fixture

    with TestClient(create_app()) as client:
        health = client.get("/api/v1/health/live", headers={"X-Request-ID": "contract-test"})
        denied = client.get("/api/v1/access/session", headers={"X-Request-ID": "contract-test"})
    assert health.status_code == 200
    assert health.json() == health_fixture
    assert denied.status_code == 401
    assert denied.json() == error_fixture


def test_every_operation_exposes_typed_error_response() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    expected = {"$ref": "#/components/responses/ApiError"}
    for _path, _method, operation in _operations(contract):
        assert operation["responses"]["default"] == expected
        validation = operation["responses"].get("422")
        if validation is not None:
            assert validation == expected
