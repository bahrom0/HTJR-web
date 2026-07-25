import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_live_health_has_request_id() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/live", headers={"X-Request-ID": "contract-test"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "request_id": "contract-test"}
    assert response.headers["X-Request-ID"] == "contract-test"


def test_pipeline_readiness_is_explicit_when_no_warmed_worker_is_available() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["code"] in {"worker_unavailable", "craft_warmup_unavailable"}


def test_openapi_uses_versioned_live_path() -> None:
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()
    assert "/api/v1/health/live" in schema["paths"]


def test_health_fixture_is_the_contract() -> None:
    fixture_path = Path(__file__).parents[1] / "contracts" / "health-live.json"
    assert json.loads(fixture_path.read_text(encoding="utf-8")) == {"status": "ok", "request_id": "contract-test"}


def test_validation_error_is_content_free_error_envelope() -> None:
    submitted_secret = "S" * 65
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/access/exchange-code",
            json={"code": submitted_secret},
            headers={"X-Request-ID": "validation-contract-test"},
        )

    assert response.status_code == 422
    assert response.json() == {
        "code": "request_validation_failed",
        "message": "The request payload is invalid.",
        "retryable": False,
        "request_id": "validation-contract-test",
    }
    assert submitted_secret not in response.text
    assert "detail" not in response.json()


def test_legacy_access_exchange_route_is_not_exposed() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/access/exchange", json={"code": "AAAA-BBBB-CCCC"})

    assert response.status_code == 404
