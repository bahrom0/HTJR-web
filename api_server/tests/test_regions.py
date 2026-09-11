from __future__ import annotations

import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.settings import settings
from app.services.regions import (
    BoundingBox,
    DetectorComponent,
    GroupingParameters,
    group_components,
    grouping_metrics,
    LineReconstructionParameters,
    reading_order,
    reconstruct_line_regions,
)


def _image_bytes() -> bytes:
    image = Image.new("RGB", (1200, 1600), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    configured = replace(
        settings,
        database_path=tmp_path / "studio.sqlite3",
        storage_root=tmp_path / "assets",
    )
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", configured)
    with TestClient(main_module.create_app()) as current:
        register = current.post(
            "/api/v1/access/register",
            json={"email": "regions@example.test", "name": "Regions User", "password": "correct horse battery"},
        )
        assert register.status_code == 201
        yield current, register.json()["csrf_token"]


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


def _detected_region(region_id: str, left: float, top: float, right: float, bottom: float) -> dict[str, object]:
    return {
        "id": region_id,
        "polygon": [
            {"x": left, "y": top},
            {"x": right, "y": top},
            {"x": right, "y": bottom},
            {"x": left, "y": bottom},
        ],
        "source": "craft",
        "flags": [],
        "detector_version": "test-detector",
        "detector_score": 0.9,
    }


def test_line_reconstruction_merges_fragments_of_one_physical_line() -> None:
    regions, audit = reconstruct_line_regions(
        [
            _detected_region("left", 0.02, 0.10, 0.24, 0.15),
            _detected_region("middle", 0.25, 0.102, 0.48, 0.153),
            _detected_region("right", 0.49, 0.098, 0.78, 0.15),
        ]
    )

    assert len(regions) == 1
    assert regions[0]["source_region_ids"] == ["left", "middle", "right"]
    assert "line_reconstructed" in regions[0]["flags"]
    assert audit["merged_line_count"] == 1
    assert audit["merges"][0]["reason"] == "same_column_geometry"


def test_line_reconstruction_preserves_oriented_quad_geometry() -> None:
    regions, _ = reconstruct_line_regions(
        [
            {
                **_detected_region("sloped", 0.10, 0.20, 0.55, 0.28),
                "polygon": [
                    {"x": 0.10, "y": 0.20},
                    {"x": 0.55, "y": 0.26},
                    {"x": 0.54, "y": 0.31},
                    {"x": 0.09, "y": 0.25},
                ],
            }
        ],
        LineReconstructionParameters(page_aspect_ratio=2.0),
    )

    assert len(regions) == 1
    assert len(regions[0]["polygon"]) == 4
    assert "oriented_quad" in regions[0]["flags"]
    polygon = regions[0]["polygon"]
    assert any(
        abs(left["x"] - right["x"]) > 1e-6 and abs(left["y"] - right["y"]) > 1e-6
        for left, right in zip(polygon, (*polygon[1:], polygon[0]), strict=True)
    )


def test_line_reconstruction_keeps_detector_reading_order_when_available() -> None:
    first = _detected_region("detector-first", 0.05, 0.35, 0.85, 0.40)
    second = _detected_region("detector-second", 0.05, 0.10, 0.85, 0.15)
    first["reading_order"] = 0
    second["reading_order"] = 1

    regions, _ = reconstruct_line_regions([first, second])

    assert [region["source_region_ids"] for region in regions] == [["detector-first"], ["detector-second"]]
    assert [region["reading_order"] for region in regions] == [0, 1]


def test_line_reconstruction_keeps_two_neighbouring_lines_separate() -> None:
    regions, _ = reconstruct_line_regions(
        [
            _detected_region("top-a", 0.04, 0.10, 0.30, 0.14),
            _detected_region("top-b", 0.31, 0.101, 0.60, 0.141),
            _detected_region("bottom-a", 0.04, 0.20, 0.30, 0.24),
            _detected_region("bottom-b", 0.31, 0.201, 0.60, 0.241),
        ]
    )

    assert len(regions) == 2
    assert [region["reading_order"] for region in regions] == [0, 1]
    assert [region["source_region_ids"] for region in regions] == [["top-a", "top-b"], ["bottom-a", "bottom-b"]]


def test_line_reconstruction_respects_two_columns_reading_order() -> None:
    regions, _ = reconstruct_line_regions(
        [
            _detected_region("left-top", 0.04, 0.08, 0.30, 0.13),
            _detected_region("left-bottom", 0.04, 0.26, 0.30, 0.31),
            _detected_region("right-top", 0.64, 0.08, 0.90, 0.13),
            _detected_region("right-bottom", 0.64, 0.26, 0.90, 0.31),
        ]
    )

    assert [region["source_region_ids"] for region in regions] == [
        ["left-top"],
        ["left-bottom"],
        ["right-top"],
        ["right-bottom"],
    ]
    assert [region["reading_order"] for region in regions] == [0, 1, 2, 3]


def test_line_reconstruction_rejects_large_horizontal_gap() -> None:
    regions, audit = reconstruct_line_regions(
        [
            _detected_region("first", 0.03, 0.10, 0.20, 0.15),
            _detected_region("far-away", 0.72, 0.10, 0.92, 0.15),
        ],
        LineReconstructionParameters(max_horizontal_gap_multiplier=3.0),
    )

    assert len(regions) == 2
    assert audit["merges"] == []


def test_line_reconstruction_rejects_erroneous_height_or_baseline_merge() -> None:
    regions, audit = reconstruct_line_regions(
        [
            _detected_region("normal", 0.05, 0.10, 0.45, 0.15),
            _detected_region("tall-neighbour", 0.46, 0.102, 0.80, 0.30),
        ]
    )

    assert len(regions) == 2
    assert audit["merges"] == []


def test_line_reconstruction_rejects_incompatible_baseline_slope() -> None:
    sloped = _detected_region("sloped", 0.46, 0.10, 0.56, 0.20)
    sloped["baseline"] = [{"x": 0.46, "y": 0.15}, {"x": 0.56, "y": 0.20}]
    sloped["polygon"] = [
        {"x": 0.46, "y": 0.10},
        {"x": 0.56, "y": 0.15},
        {"x": 0.56, "y": 0.20},
        {"x": 0.46, "y": 0.15},
    ]
    regions, audit = reconstruct_line_regions(
        [_detected_region("normal", 0.05, 0.10, 0.40, 0.15), sloped]
    )

    assert len(regions) == 2
    assert audit["merges"] == []


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
