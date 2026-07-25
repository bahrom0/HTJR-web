from __future__ import annotations

import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.settings import settings
from app.services.regions import BoundingBox, DetectorComponent, GroupingParameters, group_components, grouping_metrics, reading_order


def _image_bytes() -> bytes:
    image = Image.new("RGB", (1200, 1600), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    configured = replace(settings, database_path=tmp_path / "studio.sqlite3", storage_root=tmp_path / "assets")
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", configured)
    with TestClient(main_module.create_app()) as current:
        code, _ = current.app.state.access.issue_code("regions-tests")
        exchange = current.post("/api/v1/access/exchange-code", json={"code": code})
        assert exchange.status_code == 200
        yield current, exchange.json()["csrf_token"]


def _page(client: TestClient, csrf: str) -> str:
    uploaded = client.post(
        "/api/v1/documents",
        content=_image_bytes(),
        headers={
            "Content-Type": "image/png",
            "Idempotency-Key": "regions-upload-key-00001",
            "X-CSRF-Token": csrf,
        },
    )
    assert uploaded.status_code == 201
    return uploaded.json()["page_id"]


def _manual_region(order: int = 0) -> dict[str, object]:
    return {
        "polygon": [
            {"x": 0.1, "y": 0.1},
            {"x": 0.9, "y": 0.1},
            {"x": 0.9, "y": 0.2},
            {"x": 0.1, "y": 0.2},
        ],
        "reading_order": order,
        "source": "manual",
        "flags": [],
    }


def test_grouping_is_deterministic_and_does_not_guess_columns() -> None:
    components = [
        DetectorComponent("c", BoundingBox(0.12, 0.10, 0.22, 0.16), 0.8),
        DetectorComponent("a", BoundingBox(0.01, 0.11, 0.10, 0.17), 0.9),
        DetectorComponent("b", BoundingBox(0.02, 0.42, 0.10, 0.48), 0.7),
    ]
    lines = group_components(reversed(components), GroupingParameters())
    assert len(lines) == 2
    assert lines[0].component_ids == ("a", "c")
    assert [line.component_ids for line in reading_order(reversed(lines))] == [("a", "c"), ("b",)]


def test_grouping_covers_columns_close_skew_overlap_empty_and_metrics() -> None:
    parameters = GroupingParameters()
    columns = [
        DetectorComponent("l1", BoundingBox(0.04, 0.08, 0.35, 0.14), 0.9),
        DetectorComponent("l2", BoundingBox(0.04, 0.26, 0.35, 0.32), 0.9),
        DetectorComponent("r1", BoundingBox(0.62, 0.09, 0.94, 0.15), 0.9),
        DetectorComponent("r2", BoundingBox(0.62, 0.27, 0.94, 0.33), 0.9),
    ]
    ordered = reading_order(group_components(reversed(columns), parameters), parameters)
    assert [line.component_ids for line in ordered] == [("l1",), ("l2",), ("r1",), ("r2",)]
    assert [line.flags[-1] for line in ordered] == [
        "reading_order_column_0",
        "reading_order_column_0",
        "reading_order_column_1",
        "reading_order_column_1",
    ]

    joined_components = [
        DetectorComponent("a", BoundingBox(0.10, 0.10, 0.20, 0.15), 0.8),
        DetectorComponent("b", BoundingBox(0.205, 0.13, 0.30, 0.18), 0.9),
        DetectorComponent("c", BoundingBox(0.295, 0.125, 0.39, 0.175), 0.7),
    ]
    joined = group_components(joined_components, parameters)
    assert len(joined) == 1
    assert {"merged_components", "close_component_gap", "baseline_skew", "component_overlap"} <= set(joined[0].flags)
    assert grouping_metrics(joined) == {
        "line_candidate_count": 1,
        "component_count": 3,
        "merged_line_count": 1,
        "flag_counts": {
            "baseline_skew": 1,
            "close_component_gap": 1,
            "component_overlap": 1,
            "merged_components": 1,
        },
    }
    assert group_components([], parameters) == []
    with pytest.raises(ValueError):
        BoundingBox(0.4, 0.1, 0.4, 0.2)


def test_unusually_tall_single_component_is_flagged_for_review_without_implicit_split() -> None:
    candidates = group_components(
        [
            DetectorComponent("normal-a", BoundingBox(0.05, 0.05, 0.85, 0.10), 0.9),
            DetectorComponent("tall", BoundingBox(0.05, 0.20, 0.85, 0.42), 0.8),
            DetectorComponent("normal-b", BoundingBox(0.05, 0.60, 0.85, 0.65), 0.9),
        ]
    )

    assert len(candidates) == 3
    tall = next(candidate for candidate in candidates if candidate.component_ids == ("tall",))
    assert tall.flags == ("split_review_required",)


def test_regions_are_owned_atomic_and_revisioned(client) -> None:
    current, csrf = client
    page_id = _page(current, csrf)
    initial = current.get(f"/api/v1/pages/{page_id}/regions")
    assert initial.status_code == 200
    assert initial.json()["regions"] == [] and initial.json()["confirmed"] is False
    saved = current.put(
        f"/api/v1/pages/{page_id}/regions",
        json={"revision": initial.json()["revision"], "regions": [_manual_region()]},
        headers={"X-CSRF-Token": csrf},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["regions"][0]["source"] == "manual"
    assert saved.json()["confirmed"] is False
    stale = current.put(
        f"/api/v1/pages/{page_id}/regions",
        json={"revision": initial.json()["revision"], "regions": []},
        headers={"X-CSRF-Token": csrf},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "revision_conflict"
    confirmed = current.post(
        f"/api/v1/pages/{page_id}/regions/confirm",
        json={"revision": saved.json()["revision"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed"] is True
    invalid_order = current.put(
        f"/api/v1/pages/{page_id}/regions",
        json={"revision": confirmed.json()["revision"], "regions": [_manual_region(1)]},
        headers={"X-CSRF-Token": csrf},
    )
    assert invalid_order.status_code == 422 and invalid_order.json()["code"] == "request_validation_failed"
