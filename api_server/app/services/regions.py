from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable


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
