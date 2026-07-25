from __future__ import annotations

import numpy as np

from app.ml.craft_runtime import _score_maps_to_regions


def test_affinity_chain_does_not_expand_line_geometry_to_page() -> None:
    text = np.full((40, 100), 0.5, dtype=np.float32)
    link = np.full_like(text, 0.5)
    # Two high-confidence text cores on one baseline; the low-confidence
    # background intentionally forms a page-sized merged component.
    text[16:21, 12:28] = 0.9
    text[17:22, 36:55] = 0.85

    boxes, polygons, scores = _score_maps_to_regions(
        text,
        link,
        scale_x=1.0,
        scale_y=1.0,
        thresholds={"text": 0.7, "link": 0.4, "low_text": 0.4},
    )

    assert len(boxes) == 2
    assert len(polygons) == len(boxes) == len(scores)
    assert all(box[0] > 0 and box[2] < 100 and box[1] > 0 and box[3] < 40 for box in boxes)


def test_link_only_pixels_are_not_included_in_normal_component_bbox() -> None:
    text = np.zeros((32, 96), dtype=np.float32)
    link = np.zeros_like(text)
    text[12:17, 10:26] = 0.9
    text[12:17, 32:48] = 0.88
    link[14:15, 26:32] = 0.9

    boxes, _, _ = _score_maps_to_regions(
        text,
        link,
        scale_x=1.0,
        scale_y=1.0,
        thresholds={"text": 0.7, "link": 0.4, "low_text": 0.4},
    )

    assert len(boxes) == 1
    assert boxes[0][0] <= 10 and boxes[0][2] >= 48
    assert boxes[0][1] >= 10 and boxes[0][3] <= 20
