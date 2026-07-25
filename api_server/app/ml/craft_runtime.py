from __future__ import annotations

"""Worker-only local CRAFT runtime.

This module deliberately does not import torch at module import time.  The API
may inspect artifact readiness, but only the dedicated worker is allowed to
construct the model or allocate ML memory.
"""

import gc
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.ml.craft import CraftArtifactStatus, inspect_craft_artifacts

CRAFT_RUNTIME_VERSION = "craft_mlt_25k:runtime-v2"
CRAFT_THRESHOLD_VERSION = "craft-thresholds-v1"
DEFAULT_THRESHOLDS = {"text": 0.7, "link": 0.4, "low_text": 0.4}


class CraftRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CraftDetection:
    detector_version: str
    thresholds_version: str
    width: int
    height: int
    text_score_map: np.ndarray
    link_score_map: np.ndarray
    boxes: tuple[tuple[float, float, float, float], ...]
    polygons: tuple[tuple[tuple[float, float], ...], ...]
    scores: tuple[float, ...]
    duration_ms: int
    warmup_ms: int | None


@dataclass(frozen=True, slots=True)
class CraftReadinessEvidence:
    model_version: str
    runtime_version: str
    thresholds_version: str
    device: str
    dtype: str
    warmup_duration_ms: int


def _torch_modules() -> tuple[Any, Any, Any]:
    try:
        import torch
        import torch.nn as nn
        from torchvision import models
    except ImportError as error:  # Defensive: worker reports an explicit state.
        raise CraftRuntimeError("craft_runtime_dependencies_missing") from error
    return torch, nn, models


def _build_craft_model() -> Any:
    torch, nn, models = _torch_modules()

    class DoubleConv(nn.Module):
        def __init__(self, in_ch: int, mid_ch: int, out_ch: int) -> None:
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv2d(in_ch + mid_ch, mid_ch, kernel_size=1),
                nn.BatchNorm2d(mid_ch),
                nn.ReLU(inplace=True),
                nn.Conv2d(mid_ch, out_ch, kernel_size=3, stride=1, padding=1),
                nn.BatchNorm2d(out_ch),
                nn.ReLU(inplace=True),
            )

        def forward(self, x: Any) -> Any:
            return self.conv(x)

    class Vgg16Bn(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            backbone = models.vgg16_bn(weights=None)
            features = list(backbone.features)
            # Keep the original VGG indices in state-dict keys.  The published
            # MLT-25k checkpoint was serialized with these names.
            def section(start: int, end: int) -> Any:
                return nn.Sequential(OrderedDict((str(index), features[index]) for index in range(start, end)))

            self.slice1 = section(0, 12)
            self.slice2 = section(12, 19)
            self.slice3 = section(19, 29)
            self.slice4 = section(29, 39)
            self.slice5 = nn.Sequential(
                nn.MaxPool2d(kernel_size=3, stride=1, padding=1),
                nn.Conv2d(512, 1024, kernel_size=3, padding=6, dilation=6),
                nn.Conv2d(1024, 1024, kernel_size=1),
            )

        def forward(self, x: Any) -> list[Any]:
            h_relu2_2 = self.slice1(x)
            h_relu3_2 = self.slice2(h_relu2_2)
            h_relu4_3 = self.slice3(h_relu3_2)
            h_relu5_3 = self.slice4(h_relu4_3)
            h_fc7 = self.slice5(h_relu5_3)
            return [h_fc7, h_relu5_3, h_relu4_3, h_relu3_2, h_relu2_2]

    class Craft(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.basenet = Vgg16Bn()
            self.upconv1 = DoubleConv(1024, 512, 256)
            self.upconv2 = DoubleConv(512, 256, 128)
            self.upconv3 = DoubleConv(256, 128, 64)
            self.upconv4 = DoubleConv(128, 64, 32)
            self.conv_cls = nn.Sequential(
                nn.Conv2d(32, 32, kernel_size=3, padding=1), nn.ReLU(inplace=True),
                nn.Conv2d(32, 32, kernel_size=3, padding=1), nn.ReLU(inplace=True),
                nn.Conv2d(32, 16, kernel_size=3, padding=1), nn.ReLU(inplace=True),
                nn.Conv2d(16, 16, kernel_size=1), nn.ReLU(inplace=True),
                nn.Conv2d(16, 2, kernel_size=1),
            )

        def forward(self, x: Any) -> Any:
            source = self.basenet(x)
            y = self.upconv1(torch.cat([source[0], source[1]], dim=1))
            y = torch.nn.functional.interpolate(y, size=source[2].shape[2:], mode="bilinear", align_corners=False)
            y = self.upconv2(torch.cat([y, source[2]], dim=1))
            y = torch.nn.functional.interpolate(y, size=source[3].shape[2:], mode="bilinear", align_corners=False)
            y = self.upconv3(torch.cat([y, source[3]], dim=1))
            y = torch.nn.functional.interpolate(y, size=source[4].shape[2:], mode="bilinear", align_corners=False)
            feature = self.upconv4(torch.cat([y, source[4]], dim=1))
            return self.conv_cls(feature), feature

    return Craft()


def _resize_for_detector(image: Image.Image, max_edge: int) -> tuple[Image.Image, float]:
    if image.width < 1 or image.height < 1:
        raise CraftRuntimeError("craft_image_invalid")
    if max(image.size) <= max_edge:
        return image, 1.0
    scale = max_edge / max(image.size)
    return image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS), scale


def _score_maps_to_regions(
    text_score: np.ndarray, link_score: np.ndarray, *, scale_x: float, scale_y: float, thresholds: dict[str, float]
) -> tuple[tuple[tuple[float, float, float, float], ...], tuple[tuple[tuple[float, float], ...], ...], tuple[float, ...]]:
    try:
        import cv2
    except ImportError as error:
        raise CraftRuntimeError("craft_runtime_dependencies_missing") from error
    # CRAFT uses the low text mask and affinity mask only to discover a
    # connected instance.  Affinity pixels are then removed before geometry
    # is measured; using the merged component itself makes a long affinity
    # chain expand a line box to the whole page.
    text_mask = (text_score >= thresholds["low_text"]).astype(np.uint8)
    link_mask = (link_score >= thresholds["link"]).astype(np.uint8)
    merged = np.clip(text_mask + link_mask, 0, 1).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=4)
    boxes: list[tuple[float, float, float, float]] = []
    polygons: list[tuple[tuple[float, float], ...]] = []
    scores: list[float] = []
    for label in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[label])
        component = labels[y:y + height, x:x + width] == label
        component_text = text_score[y:y + height, x:x + width][component]
        if area < 10 or component_text.size == 0 or float(component_text.max()) < thresholds["text"]:
            continue

        # Match craft_utils.getDetBoxes_core: affinity-only pixels connect
        # characters, but must not become part of the text polygon.
        contour_mask = component & ~(link_mask[y:y + height, x:x + width].astype(bool) & ~text_mask[y:y + height, x:x + width].astype(bool))

        # Some small, ruled-page photos produce a near-uniform low-confidence
        # map.  In that case the merged component can cover almost the entire
        # image even though the high-confidence text cores are localized.  A
        # high-confidence core is a CRAFT-derived recovery, not a fabricated
        # detector: it is used only for this measurable full-page anomaly.
        component_fraction = area / float(text_score.shape[0] * text_score.shape[1])
        geometry_fraction = float(contour_mask.sum()) / float(max(area, 1))
        used_high_core = False
        if component_fraction >= 0.85 and geometry_fraction >= 0.9:
            high_core = component & (text_score[y:y + height, x:x + width] >= thresholds["text"])
            if int(high_core.sum()) >= 10 and int(high_core.sum()) < int(component.sum() * 0.9):
                contour_mask = high_core
                used_high_core = True

        # A page-sized anomaly may contain several high-confidence line cores.
        # Split those cores before geometry is measured; the worker's existing
        # grouping stage then joins character/word boxes on the same baseline.
        geometry_components: list[np.ndarray] = [contour_mask]
        if used_high_core:
            sub_count, sub_labels, sub_stats, _ = cv2.connectedComponentsWithStats(contour_mask.astype(np.uint8), connectivity=8)
            geometry_components = [sub_labels == sub_label for sub_label in range(1, sub_count) if int(sub_stats[sub_label, cv2.CC_STAT_AREA]) >= 3]
        for geometry_component in geometry_components:
            ys, xs = np.where(geometry_component)
            if xs.size == 0:
                continue
            # Dilate the text core by the same scale-aware rule used by the
            # reference implementation, without reintroducing affinity.
            core_x, core_y = int(xs.min()), int(ys.min())
            core_w, core_h = int(xs.max() - core_x + 1), int(ys.max() - core_y + 1)
            niter = int(np.sqrt(max(int(geometry_component.sum()), 1) * min(core_w, core_h) / max(core_w * core_h, 1)) * 2)
            niter = max(1, niter)
            expanded = np.zeros_like(geometry_component, dtype=np.uint8)
            expanded[geometry_component] = 255
            sx, ex = max(0, core_x - niter), min(width, core_x + core_w + niter + 1)
            sy, ey = max(0, core_y - niter), min(height, core_y + core_h + niter + 1)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1 + niter, 1 + niter))
            expanded[sy:ey, sx:ex] = cv2.dilate(expanded[sy:ey, sx:ex], kernel)

            expanded_ys, expanded_xs = np.where(expanded != 0)
            left, top = (x + int(expanded_xs.min())) * scale_x, (y + int(expanded_ys.min())) * scale_y
            right, bottom = (x + int(expanded_xs.max()) + 1) * scale_x, (y + int(expanded_ys.max()) + 1) * scale_y
            boxes.append((left, top, right, bottom))
            contours, _ = cv2.findContours(expanded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                contour = max(contours, key=cv2.contourArea)
                epsilon = max(1.0, cv2.arcLength(contour, True) * 0.01)
                approximated = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
                polygon = tuple((float(x + point_x) * scale_x, float(y + point_y) * scale_y) for point_x, point_y in approximated)
                polygons.append(polygon if len(polygon) >= 3 else ((left, top), (right, top), (right, bottom), (left, bottom)))
            else:
                polygons.append(((left, top), (right, top), (right, bottom), (left, bottom)))
            scores.append(float(text_score[y:y + height, x:x + width][geometry_component].max()))
    return tuple(boxes), tuple(polygons), tuple(scores)


class CraftRuntime:
    """One model per worker process; serialized inference protects CPU/GPU memory."""

    def __init__(self, models_root: Path, *, max_edge: int = 2048, device: str = "auto") -> None:
        self.models_root = models_root
        self.max_edge = max_edge
        self.requested_device = device
        self._lock = threading.Lock()
        self._model: Any | None = None
        self._device: Any | None = None
        self._warmup_ms: int | None = None
        self._evidence: CraftReadinessEvidence | None = None

    def artifact_status(self) -> CraftArtifactStatus:
        return inspect_craft_artifacts(self.models_root)

    @property
    def evidence(self) -> CraftReadinessEvidence | None:
        return self._evidence

    def load(self) -> None:
        if self._model is not None:
            return
        status = self.artifact_status()
        if not status.ready:
            raise CraftRuntimeError(status.code)
        torch, _, _ = _torch_modules()
        use_cuda = self.requested_device == "cuda" or (self.requested_device == "auto" and torch.cuda.is_available())
        if self.requested_device == "cuda" and not torch.cuda.is_available():
            raise CraftRuntimeError("craft_cuda_unavailable")
        self._device = torch.device("cuda" if use_cuda else "cpu")
        assert status.weight_path is not None
        checkpoint = status.weight_path
        try:
            weights = torch.load(checkpoint, map_location="cpu", weights_only=True)
            weights = {key.removeprefix("module."): value for key, value in weights.items()}
            model = _build_craft_model()
            missing, unexpected = model.load_state_dict(weights, strict=False)
            if missing or unexpected:
                raise CraftRuntimeError("craft_checkpoint_incompatible")
            self._model = model.eval().to(self._device)
        except CraftRuntimeError:
            self.close()
            raise
        except Exception as error:
            self.close()
            raise CraftRuntimeError("craft_checkpoint_load_failed") from error

    def warmup(self) -> int:
        self.load()
        assert self._model is not None
        torch, _, _ = _torch_modules()
        started = time.perf_counter()
        with self._lock, torch.inference_mode():
            sample = torch.zeros((1, 3, 64, 64), device=self._device)
            self._model(sample)
            if self._device.type == "cuda":
                torch.cuda.synchronize(self._device)
        self._warmup_ms = round((time.perf_counter() - started) * 1000)
        status = self.artifact_status()
        parameter = next(self._model.parameters())
        self._evidence = CraftReadinessEvidence(
            model_version=status.model_version or "unknown",
            runtime_version=CRAFT_RUNTIME_VERSION,
            thresholds_version=CRAFT_THRESHOLD_VERSION,
            device=str(self._device),
            dtype=str(parameter.dtype).removeprefix("torch."),
            warmup_duration_ms=self._warmup_ms,
        )
        return self._warmup_ms

    def detect(self, image: Image.Image, *, thresholds: dict[str, float] | None = None) -> CraftDetection:
        active_thresholds = dict(DEFAULT_THRESHOLDS if thresholds is None else thresholds)
        if set(active_thresholds) != set(DEFAULT_THRESHOLDS) or not all(0 < value <= 1 for value in active_thresholds.values()):
            raise CraftRuntimeError("craft_thresholds_invalid")
        self.load()
        assert self._model is not None
        torch, _, _ = _torch_modules()
        prepared, resize_scale = _resize_for_detector(image.convert("RGB"), self.max_edge)
        array = np.asarray(prepared, dtype=np.float32) / 255.0
        normalized = (array - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
        tensor = torch.from_numpy(np.ascontiguousarray(normalized.transpose(2, 0, 1))).unsqueeze(0).to(self._device)
        started = time.perf_counter()
        with self._lock, torch.inference_mode():
            output, _ = self._model(tensor)
            maps = torch.sigmoid(output[0]).detach().float().cpu().numpy()
            if self._device.type == "cuda":
                torch.cuda.synchronize(self._device)
        text_map, link_map = maps[0], maps[1]
        output_scale_x = image.width / text_map.shape[1]
        output_scale_y = image.height / text_map.shape[0]
        boxes, polygons, scores = _score_maps_to_regions(text_map, link_map, scale_x=output_scale_x, scale_y=output_scale_y, thresholds=active_thresholds)
        duration_ms = round((time.perf_counter() - started) * 1000)
        return CraftDetection(
            CRAFT_RUNTIME_VERSION, CRAFT_THRESHOLD_VERSION, image.width, image.height,
            text_map, link_map, boxes, polygons, scores, duration_ms, self._warmup_ms,
        )

    def close(self) -> None:
        model, self._model = self._model, None
        self._evidence = None
        if model is not None:
            del model
        try:
            torch, _, _ = _torch_modules()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except CraftRuntimeError:
            pass
        gc.collect()
