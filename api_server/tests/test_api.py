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


def test_openapi_uses_versioned_live_path() -> None:
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()
    assert "/api/v1/health/live" in schema["paths"]


def test_health_fixture_is_the_contract() -> None:
    fixture_path = Path(__file__).parents[1] / "contracts" / "health-live.json"
    assert json.loads(fixture_path.read_text(encoding="utf-8")) == {"status": "ok", "request_id": "contract-test"}
