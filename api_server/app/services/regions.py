from __future__ import annotations

from dataclasses import dataclass, asdict
from math import atan2, cos, pi, sin
from statistics import median
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class BoundingBox:
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        if not (0 <= self.left < self.right <= 1 and 0 <= self.top < self.bottom <= 1):
            raise ValueError("Bounding boxes must be normalized and non-empty")

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    def union(self, other: BoundingBox) -> BoundingBox:
        return BoundingBox(
            min(self.left, other.left), min(self.top, other.top), max(self.right, other.right), max(self.bottom, other.bottom)
        )


@dataclass(frozen=True, slots=True)
class DetectorComponent:
    id: str
    bbox: BoundingBox
    score: float

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 1:
            raise ValueError("Detector scores must be normalized")


@dataclass(frozen=True, slots=True)
class LineCandidate:
    bbox: BoundingBox
    component_ids: tuple[str, ...]
    score: float
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GroupingParameters:
    baseline_tolerance: float = 0.75
    horizontal_gap_multiplier: float = 2.5
    min_vertical_overlap: float = 0.25
    column_gap_minimum: float = 0.08
    split_review_height_multiplier: float = 2.4

    def __post_init__(self) -> None:
        if not 0 < self.baseline_tolerance <= 2:
            raise ValueError("baseline_tolerance must be in (0, 2]")
        if self.horizontal_gap_multiplier <= 0 or not 0 <= self.min_vertical_overlap <= 1:
            raise ValueError("Invalid grouping parameters")
        if not 0 < self.column_gap_minimum < 1:
            raise ValueError("column_gap_minimum must be in (0, 1)")
        if self.split_review_height_multiplier <= 1:
            raise ValueError("split_review_height_multiplier must exceed 1")


@dataclass(frozen=True, slots=True)
class LineReconstructionParameters:
    """Conservative geometry gates for turning detector fragments into lines."""

    min_vertical_overlap: float = 0.35
    baseline_delta_multiplier: float = 0.75
    max_slope_delta_radians: float = 0.30
    max_height_ratio: float = 2.5
    max_horizontal_gap_multiplier: float = 6.0
    column_gap_minimum: float = 0.08
    column_min_y_span_multiplier: float = 2.5
    page_aspect_ratio: float = 1.0

    def __post_init__(self) -> None:
        if not 0 < self.min_vertical_overlap <= 1:
            raise ValueError("min_vertical_overlap must be in (0, 1]")
        if self.baseline_delta_multiplier <= 0:
            raise ValueError("baseline_delta_multiplier must be positive")
        if not 0 < self.max_slope_delta_radians < pi / 2:
            raise ValueError("max_slope_delta_radians must be in (0, pi/2)")
        if self.max_height_ratio < 1:
            raise ValueError("max_height_ratio must be at least 1")
        if self.max_horizontal_gap_multiplier <= 0:
            raise ValueError("max_horizontal_gap_multiplier must be positive")
        if not 0 < self.column_gap_minimum < 1:
            raise ValueError("column_gap_minimum must be in (0, 1)")
        if self.column_min_y_span_multiplier <= 0:
            raise ValueError("column_min_y_span_multiplier must be positive")
        if self.page_aspect_ratio <= 0:
            raise ValueError("page_aspect_ratio must be positive")


@dataclass(frozen=True, slots=True)
class _RegionFragment:
    id: str
    polygon: tuple[tuple[float, float], ...]
    bbox: BoundingBox
    source: str
    flags: tuple[str, ...]
    detector_version: str | None
    detector_score: float | None
    slope: float
    reading_order: int | None


def _region_points(value: object, *, minimum: int = 4) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("region polygon must be a list")
    points: list[tuple[float, float]] = []
    for point in value:
        if isinstance(point, Mapping):
            x, y = point.get("x"), point.get("y")
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            x, y = point
        else:
            raise ValueError("region polygon point is invalid")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise ValueError("region polygon point is invalid")
        if not 0 <= float(x) <= 1 or not 0 <= float(y) <= 1:
            raise ValueError("region polygon must be normalized")
        points.append((float(x), float(y)))
    if len(points) < minimum:
        raise ValueError(f"region geometry must have at least {minimum} points")
    return tuple(points)


def _region_slope(polygon: tuple[tuple[float, float], ...], baseline: object = None) -> float:
    points = _region_points(baseline, minimum=2) if baseline else polygon
    ordered = sorted(points, key=lambda point: point[0])
    left, right = ordered[0], ordered[-1]
    delta_x = right[0] - left[0]
    if abs(delta_x) < 1e-9:
        return 0.0
    return atan2(right[1] - left[1], delta_x)


def _as_region_fragment(region: Mapping[str, object], index: int) -> _RegionFragment:
    polygon = _region_points(region.get("polygon"))
    xs, ys = zip(*polygon, strict=True)
    bbox = BoundingBox(min(xs), min(ys), max(xs), max(ys))
    raw_flags = region.get("flags", ())
    flags = tuple(str(value) for value in raw_flags) if isinstance(raw_flags, (list, tuple)) else ()
    raw_score = region.get("detector_score")
    score = float(raw_score) if isinstance(raw_score, (int, float)) else None
    raw_version = region.get("detector_version")
    raw_reading_order = region.get("reading_order")
    return _RegionFragment(
        id=str(region.get("id") or f"source-region-{index}"),
        polygon=polygon,
        bbox=bbox,
        source=str(region.get("source") or "adjusted"),
        flags=flags,
        detector_version=str(raw_version) if raw_version is not None else None,
        detector_score=score,
        slope=_region_slope(polygon, region.get("baseline")),
        reading_order=int(raw_reading_order) if isinstance(raw_reading_order, int) else None,
    )


def _horizontal_gap(left: BoundingBox, right: BoundingBox) -> float:
    if left.right < right.left:
        return right.left - left.right
    if right.right < left.left:
        return left.left - right.right
    return 0.0


def _vertical_gap(left: BoundingBox, right: BoundingBox) -> float:
    if left.bottom < right.top:
        return right.top - left.bottom
    if right.bottom < left.top:
        return left.top - right.bottom
    return 0.0


def _column_bands(
    fragments: list[_RegionFragment],
    parameters: LineReconstructionParameters,
) -> dict[str, int]:
    """Detect only an explicit two-column split, never from one short line."""
    if len(fragments) < 4:
        return {fragment.id: 0 for fragment in fragments}
    median_height = median(fragment.bbox.height for fragment in fragments)
    ordered = sorted(fragments, key=lambda item: (item.bbox.center_x, item.bbox.left, item.id))
    best: tuple[float, list[_RegionFragment], list[_RegionFragment]] | None = None
    for index in range(2, len(ordered) - 1):
        left, right = ordered[:index], ordered[index:]
        gap = min(item.bbox.left for item in right) - max(item.bbox.right for item in left)
        if gap < max(parameters.column_gap_minimum, median_height * 2.0 / parameters.page_aspect_ratio):
            continue
        y_span = max(item.bbox.center_y for item in ordered) - min(item.bbox.center_y for item in ordered)
        if y_span < median_height * parameters.column_min_y_span_multiplier:
            continue
        if best is None or gap > best[0]:
            best = (gap, left, right)
    if best is None:
        return {fragment.id: 0 for fragment in fragments}
    return {fragment.id: 0 for fragment in best[1]} | {fragment.id: 1 for fragment in best[2]}


def _compatible_fragments(
    left: _RegionFragment,
    right: _RegionFragment,
    parameters: LineReconstructionParameters,
) -> tuple[bool, dict[str, float]]:
    overlap = _vertical_overlap(left.bbox, right.bbox)
    baseline_delta = abs(left.bbox.center_y - right.bbox.center_y)
    height_ratio = max(left.bbox.height, right.bbox.height) / min(left.bbox.height, right.bbox.height)
    gap = _horizontal_gap(left.bbox, right.bbox)
    vertical_gap = _vertical_gap(left.bbox, right.bbox)
    slope_delta = abs(left.slope - right.slope)
    max_height = max(left.bbox.height, right.bbox.height)
    evidence = {
        "vertical_overlap": overlap,
        "baseline_delta": baseline_delta,
        "height_ratio": height_ratio,
        "horizontal_gap": gap,
        "vertical_gap": vertical_gap,
        "slope_delta_radians": slope_delta,
        "horizontal_gap_to_height": gap / min_height(left, right) * parameters.page_aspect_ratio,
    }
    vertical_match = overlap >= parameters.min_vertical_overlap or (
        baseline_delta <= max_height * parameters.baseline_delta_multiplier
        and vertical_gap <= max_height * 0.5
    )
    compatible = (
        left.source == right.source
        and vertical_match
        and height_ratio <= parameters.max_height_ratio
        and slope_delta <= parameters.max_slope_delta_radians
        and gap * parameters.page_aspect_ratio <= min_height(left, right) * parameters.max_horizontal_gap_multiplier
    )
    return compatible, evidence


def min_height(left: _RegionFragment, right: _RegionFragment) -> float:
    return min(left.bbox.height, right.bbox.height)


def _polygon_area(points: tuple[tuple[float, float], ...]) -> float:
    return 0.5 * sum(
        point[0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * point[1]
        for index, point in enumerate(points)
    )


def _is_axis_aligned(points: tuple[tuple[float, float], ...]) -> bool:
    if len(points) != 4:
        return False
    return all(
        abs(left[0] - right[0]) < 1e-7 or abs(left[1] - right[1]) < 1e-7
        for left, right in zip(points, (*points[1:], points[0]), strict=True)
    )


def _oriented_quad(
    members: list[_RegionFragment],
    *,
    page_aspect_ratio: float,
) -> tuple[tuple[tuple[float, float], ...], bool]:
    """Return a stable four-corner line geometry when detector geometry allows it.

    A single four-point detector polygon is retained verbatim.  For merged
    fragments, a small PCA projection over all detector points estimates the
    dominant writing direction and encloses the fragments in that oriented
    rectangle.  Coordinates are normalized, while the page aspect ratio keeps
    the projection in pixel-like units.
    """
    if len(members) == 1 and len(members[0].polygon) == 4 and not _is_axis_aligned(members[0].polygon):
        return members[0].polygon, True
    points = tuple(point for member in members for point in member.polygon)
    if len(points) < 4:
        return (), False
    scale_x = max(page_aspect_ratio, 1e-9)
    scaled = tuple((x * scale_x, y) for x, y in points)
    center_x = sum(point[0] for point in scaled) / len(scaled)
    center_y = sum(point[1] for point in scaled) / len(scaled)
    covariance_xx = sum((point[0] - center_x) ** 2 for point in scaled)
    covariance_yy = sum((point[1] - center_y) ** 2 for point in scaled)
    covariance_xy = sum((point[0] - center_x) * (point[1] - center_y) for point in scaled)
    if covariance_xx + covariance_yy < 1e-12:
        return (), False
    angle = 0.5 * atan2(2 * covariance_xy, covariance_xx - covariance_yy)
    unit_x, unit_y = cos(angle), sin(angle)
    perp_x, perp_y = -unit_y, unit_x
    along = tuple((point[0] - center_x) * unit_x + (point[1] - center_y) * unit_y for point in scaled)
    across = tuple((point[0] - center_x) * perp_x + (point[1] - center_y) * perp_y for point in scaled)
    min_along, max_along = min(along), max(along)
    min_across, max_across = min(across), max(across)
    corners_scaled = (
        (center_x + min_along * unit_x + min_across * perp_x, center_y + min_along * unit_y + min_across * perp_y),
        (center_x + max_along * unit_x + min_across * perp_x, center_y + max_along * unit_y + min_across * perp_y),
        (center_x + max_along * unit_x + max_across * perp_x, center_y + max_along * unit_y + max_across * perp_y),
        (center_x + min_along * unit_x + max_across * perp_x, center_y + min_along * unit_y + max_across * perp_y),
    )
    corners = tuple(
        (max(0.0, min(1.0, x / scale_x)), max(0.0, min(1.0, y)))
        for x, y in corners_scaled
    )
    if len(corners) != 4 or abs(_polygon_area(corners)) < 1e-8:
        return (), False
    oriented = not _is_axis_aligned(corners)
    return corners, oriented


def reconstruct_line_regions(
    regions: Iterable[Mapping[str, object]],
    parameters: LineReconstructionParameters = LineReconstructionParameters(),
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Merge detector fragments into physical line regions with auditable evidence.

    This is deliberately geometry-only.  It never changes recognized text and it
    is called before a region is cropped for TrOCR, while the source detector
    output remains available in the returned audit payload.
    """
    fragments = [_as_region_fragment(region, index) for index, region in enumerate(regions)]
    bands = _column_bands(fragments, parameters)
    parents = list(range(len(fragments)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    pair_evidence: dict[tuple[str, str], dict[str, float]] = {}
    for left_index, left in enumerate(fragments):
        for right_index in range(left_index + 1, len(fragments)):
            right = fragments[right_index]
            if bands[left.id] != bands[right.id]:
                continue
            compatible, evidence = _compatible_fragments(left, right, parameters)
            if compatible:
                union(left_index, right_index)
                pair_evidence[(left.id, right.id)] = evidence

    groups: dict[int, list[_RegionFragment]] = {}
    for index, fragment in enumerate(fragments):
        groups.setdefault(find(index), []).append(fragment)

    line_regions: list[dict[str, object]] = []
    merges: list[dict[str, object]] = []
    for members in groups.values():
        members.sort(key=lambda item: (item.bbox.left, item.bbox.top, item.id))
        bounds = members[0].bbox
        for member in members[1:]:
            bounds = bounds.union(member.bbox)
        geometry, oriented = _oriented_quad(members, page_aspect_ratio=parameters.page_aspect_ratio)
        if not geometry:
            geometry = (
                (bounds.left, bounds.top),
                (bounds.right, bounds.top),
                (bounds.right, bounds.bottom),
                (bounds.left, bounds.bottom),
            )
        source_ids = [member.id for member in members]
        line_id = source_ids[0] if len(source_ids) == 1 else f"line:{source_ids[0]}:{len(source_ids)}"
        flags = list(dict.fromkeys(flag for member in members for flag in member.flags))
        if oriented:
            flags.append("oriented_quad")
        if len(members) > 1:
            flags.extend(("line_reconstructed", f"merged_{len(members)}_regions", "merge_geometry_verified"))
            evidence = []
            for left, right in zip(members, members[1:]):
                key = (left.id, right.id)
                if key not in pair_evidence:
                    key = (right.id, left.id)
                if key in pair_evidence:
                    evidence.append({"left_id": left.id, "right_id": right.id, **pair_evidence[key]})
            merges.append(
                {
                    "line_region_id": line_id,
                    "source_region_ids": source_ids,
                    "reason": "same_column_geometry",
                    "column_index": bands[members[0].id],
                    "evidence": evidence,
                }
            )
        line_regions.append(
            {
                "id": line_id,
                "polygon": [{"x": x, "y": y} for x, y in geometry],
                "source_region_ids": source_ids,
                "source": members[0].source,
                "flags": list(dict.fromkeys(flags)),
                "detector_version": members[0].detector_version,
                "detector_score": max(
                    (member.detector_score for member in members if member.detector_score is not None),
                    default=None,
                ),
                "column_index": bands[members[0].id],
                "source_reading_order": min(
                    (member.reading_order for member in members if member.reading_order is not None),
                    default=None,
                ),
            }
        )

    has_source_order = bool(line_regions) and all(item["source_reading_order"] is not None for item in line_regions)
    if has_source_order:
        line_regions.sort(key=lambda item: (int(item["source_reading_order"]), str(item["id"])))
    else:
        line_regions.sort(
            key=lambda item: (
                int(item["column_index"]),
                min(float(point["y"]) for point in item["polygon"]),
                min(float(point["x"]) for point in item["polygon"]),
                str(item["id"]),
            )
        )
    for reading_order, region in enumerate(line_regions):
        region["reading_order"] = reading_order
        region.pop("column_index", None)
        region.pop("source_reading_order", None)
    source_payload = []
    for fragment in fragments:
        source_payload.append(
            {
                "id": fragment.id,
                "polygon": [{"x": x, "y": y} for x, y in fragment.polygon],
                "bbox": [fragment.bbox.left, fragment.bbox.top, fragment.bbox.right, fragment.bbox.bottom],
                "source": fragment.source,
                "flags": list(fragment.flags),
                "detector_version": fragment.detector_version,
                "detector_score": fragment.detector_score,
                "slope_radians": fragment.slope,
                "reading_order": fragment.reading_order,
            }
        )
    audit = {
        "schema_version": 1,
        "parameters": asdict(parameters),
        "source_regions": source_payload,
        "line_regions": line_regions,
        "merges": merges,
        "source_region_count": len(fragments),
        "line_region_count": len(line_regions),
        "merged_line_count": len(merges),
    }
    return line_regions, audit


def _vertical_overlap(left: BoundingBox, right: BoundingBox) -> float:
    shared = max(0.0, min(left.bottom, right.bottom) - max(left.top, right.top))
    return shared / min(left.height, right.height)


def _same_line(line: BoundingBox, component: BoundingBox, parameters: GroupingParameters) -> bool:
    overlap = _vertical_overlap(line, component)
    baseline_delta = abs(line.center_y - component.center_y)
    max_height = max(line.height, component.height)
    gap = component.left - line.right
    return (
        (overlap >= parameters.min_vertical_overlap or baseline_delta <= max_height * parameters.baseline_tolerance)
        and gap <= max_height * parameters.horizontal_gap_multiplier
    )


def _line_flags(
    components: list[DetectorComponent],
    parameters: GroupingParameters,
    *,
    median_component_height: float,
) -> tuple[str, ...]:
    if len(components) < 2:
        if (
            len(components) == 1
            and median_component_height > 0
            and components[0].bbox.height >= median_component_height * parameters.split_review_height_multiplier
        ):
            # This is deliberately a review flag, not an implicit split.  It
            # exposes detector geometry which is atypical for the current
            # page and leaves the final operation to the user.
            return ("split_review_required",)
        return ()
    flags: list[str] = ["merged_components"]
    pairs = zip(components, components[1:])
    for left, right in pairs:
        gap = right.bbox.left - left.bbox.right
        if gap < 0:
            flags.append("component_overlap")
        elif gap <= max(left.bbox.height, right.bbox.height) * 0.15:
            flags.append("close_component_gap")
        if abs(left.bbox.center_y - right.bbox.center_y) > max(left.bbox.height, right.bbox.height) * parameters.baseline_tolerance * 0.5:
            flags.append("baseline_skew")
    return tuple(dict.fromkeys(flags))


def group_components(
    components: Iterable[DetectorComponent],
    parameters: GroupingParameters = GroupingParameters(),
) -> list[LineCandidate]:
    """Group detector components using explicit vertical/baseline/gap rules."""
    groups: list[list[DetectorComponent]] = []
    ordered = sorted(components, key=lambda item: (item.bbox.top, item.bbox.left, item.id))
    median_component_height = median([item.bbox.height for item in ordered]) if ordered else 0.0
    for component in ordered:
        candidates: list[tuple[int, BoundingBox]] = []
        for index, group in enumerate(groups):
            bounds = group[0].bbox
            for existing in group[1:]:
                bounds = bounds.union(existing.bbox)
            if _same_line(bounds, component.bbox, parameters):
                candidates.append((index, bounds))
        if not candidates:
            groups.append([component])
            continue
        index, _ = min(candidates, key=lambda item: (abs(item[1].center_y - component.bbox.center_y), item[1].left, item[0]))
        groups[index].append(component)

    candidates: list[LineCandidate] = []
    for group in groups:
        spatial = sorted(group, key=lambda item: (item.bbox.left, item.bbox.top, item.id))
        bounds = spatial[0].bbox
        for component in spatial[1:]:
            bounds = bounds.union(component.bbox)
        candidates.append(
            LineCandidate(
                bbox=bounds,
                component_ids=tuple(component.id for component in spatial),
                score=max(component.score for component in spatial),
                flags=_line_flags(
                    spatial,
                    parameters,
                    median_component_height=median_component_height,
                ),
            )
        )
    return sorted(candidates, key=lambda item: (item.bbox.top, item.bbox.left, item.component_ids))


def _with_flag(line: LineCandidate, flag: str) -> LineCandidate:
    return LineCandidate(line.bbox, line.component_ids, line.score, tuple(dict.fromkeys((*line.flags, flag))))


def _clear_two_column_split(lines: list[LineCandidate], parameters: GroupingParameters) -> tuple[list[LineCandidate], list[LineCandidate]] | None:
    """Accept only an explicit non-overlapping two-column geometry.

    A sparse or overlapping layout remains top-to-bottom rather than being
    silently guessed as columns.  Requiring two candidates per side avoids a
    single marginal note changing the entire reading order.
    """
    if len(lines) < 4:
        return None
    by_center = sorted(lines, key=lambda item: (item.bbox.center_x, item.bbox.left, item.bbox.top))
    best: tuple[float, list[LineCandidate], list[LineCandidate]] | None = None
    for index in range(2, len(by_center) - 1):
        left, right = by_center[:index], by_center[index:]
        gap = min(item.bbox.left for item in right) - max(item.bbox.right for item in left)
        minimum_width = median([item.bbox.width for item in by_center])
        if gap < max(parameters.column_gap_minimum, minimum_width * 0.5):
            continue
        if best is None or gap > best[0]:
            best = (gap, left, right)
    if best is None:
        return None
    return best[1], best[2]


def reading_order(
    lines: Iterable[LineCandidate],
    parameters: GroupingParameters = GroupingParameters(),
) -> list[LineCandidate]:
    """Return a deterministic order with an explicit simple-column policy."""
    candidates = list(lines)
    split = _clear_two_column_split(candidates, parameters)
    if split is None:
        return [
            _with_flag(line, "reading_order_top_to_bottom")
            for line in sorted(candidates, key=lambda item: (round(item.bbox.top, 6), round(item.bbox.left, 6), item.component_ids))
        ]
    left, right = split
    ordered: list[LineCandidate] = []
    for column_index, column in enumerate((left, right)):
        ordered.extend(
            _with_flag(line, f"reading_order_column_{column_index}")
            for line in sorted(column, key=lambda item: (round(item.bbox.top, 6), round(item.bbox.left, 6), item.component_ids))
        )
    return ordered


def grouping_metrics(lines: Iterable[LineCandidate]) -> dict[str, object]:
    """Return deterministic detector diagnostics without inventing quality scores."""
    values = list(lines)
    flag_counts: dict[str, int] = {}
    for line in values:
        for flag in line.flags:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
    return {
        "line_candidate_count": len(values),
        "component_count": sum(len(line.component_ids) for line in values),
        "merged_line_count": sum(len(line.component_ids) > 1 for line in values),
        "flag_counts": dict(sorted(flag_counts.items())),
    }
