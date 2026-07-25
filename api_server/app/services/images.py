from __future__ import annotations

import hashlib
import io
import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import ApiError

PIPELINE_VERSION = "preprocess-v1"
QUALITY_THRESHOLD_VERSION = "quality-v1"
SUPPORTED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
QUALITY_THRESHOLDS = {
    "blur_laplacian_variance_min": 85.0,
    "exposure_mean_min": 55.0,
    "exposure_mean_max": 225.0,
    "contrast_stddev_min": 28.0,
    "absolute_skew_degrees_max": 4.0,
    "short_edge_min": 900,
}


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    media_type: str
    width: int
    height: int
    exif_orientation: int | None


def _magic_format(path: Path) -> str | None:
    head = path.read_bytes()[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    return None


def _container_has_no_payload(path: Path, image_format: str) -> bool:
    data = path.read_bytes()
    if image_format == "PNG":
        marker = b"\x00\x00\x00\x00IEND\xaeB`\x82"
        return data.endswith(marker)
    if image_format == "JPEG":
        return data.rstrip(b"\x00\t\r\n ").endswith(b"\xff\xd9")
    if image_format == "WEBP" and len(data) >= 12:
        return int.from_bytes(data[4:8], "little") + 8 == len(data)
    return False


def validate_image(
    path: Path,
    declared_media_type: str,
    *,
    max_pixels: int,
    max_dimension: int,
) -> ValidatedImage:
    magic = _magic_format(path)
    if magic is None:
        raise ApiError(415, "unsupported_image_type", "Use a JPEG, PNG, or WebP image.")
    expected_type = SUPPORTED_FORMATS[magic]
    if declared_media_type.lower().split(";", 1)[0].strip() != expected_type:
        raise ApiError(415, "image_type_mismatch", "The declared image type does not match its contents.")
    if not _container_has_no_payload(path, magic):
        raise ApiError(422, "image_container_invalid", "The image container is malformed or contains trailing payload.")

    old_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format != magic:
                    raise ApiError(415, "image_decoder_mismatch", "The image decoder disagrees with its file signature.")
                width, height = image.size
                orientation = image.getexif().get(274)
                if width <= 0 or height <= 0:
                    raise ApiError(422, "image_dimensions_invalid", "The image dimensions are invalid.")
                if width > max_dimension or height > max_dimension or width * height > max_pixels:
                    raise ApiError(413, "image_pixel_limit_exceeded", "The image dimensions are too large.")
            with Image.open(path) as verified:
                verified.verify()
            with Image.open(path) as decoded:
                decoded.load()
    except ApiError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ApiError(413, "image_decompression_limit", "The image expands beyond the safe pixel limit.") from error
    except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as error:
        raise ApiError(422, "image_decode_failed", "The image could not be decoded safely.") from error
    finally:
        Image.MAX_IMAGE_PIXELS = old_limit
    return ValidatedImage(expected_type, width, height, int(orientation) if orientation else None)


def canonical_recipe(recipe: dict[str, Any]) -> str:
    return json.dumps(recipe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def recipe_hash(source_sha256: str, recipe_json: str) -> str:
    material = f"{PIPELINE_VERSION}\n{source_sha256}\n{recipe_json}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def source_to_rgb(source: Image.Image) -> Image.Image:
    """Apply orientation and place transparent pixels on a white paper background.

    A direct Pillow ``convert('RGB')`` turns transparent PNG pixels black.
    That is not the visual document the user selected and can make CRAFT
    interpret an otherwise empty alpha channel as ink.  Prepared documents
    are deliberately opaque RGB images, so the alpha compositing decision is
    made once at the server-owned preparation boundary.
    """
    oriented = ImageOps.exif_transpose(source)
    try:
        has_alpha = oriented.mode in {"RGBA", "LA"} or (
            oriented.mode == "P" and "transparency" in oriented.info
        )
        if not has_alpha:
            return oriented.convert("RGB")
        rgba = oriented.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        try:
            background.alpha_composite(rgba)
            return background.convert("RGB")
        finally:
            rgba.close()
            background.close()
    finally:
        oriented.close()


def prepare_image(path: Path, recipe: dict[str, Any], *, server_max_edge: int) -> Image.Image:
    requested_max_edge = min(recipe["max_edge"], server_max_edge)
    with Image.open(path) as source:
        image = source_to_rgb(source)
    rotation = recipe["rotation_degrees"]
    if rotation:
        image = image.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)
    crop = recipe.get("crop")
    if crop:
        left = round(crop["x"] * image.width)
        top = round(crop["y"] * image.height)
        right = round((crop["x"] + crop["width"]) * image.width)
        bottom = round((crop["y"] + crop["height"]) * image.height)
        if right <= left or bottom <= top:
            raise ApiError(422, "crop_invalid", "The normalized crop has no area.")
        image = image.crop((max(0, left), max(0, top), min(image.width, right), min(image.height, bottom)))
    perspective = recipe.get("perspective")
    if perspective:
        source_points = np.float32([[p["x"] * image.width, p["y"] * image.height] for p in perspective])
        tl, tr, br, bl = source_points
        width = max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))
        height = max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))
        if width < 2 or height < 2:
            raise ApiError(422, "perspective_invalid", "The perspective quadrilateral has no usable area.")
        target_scale = min(1.0, requested_max_edge / max(width, height))
        width *= target_scale
        height *= target_scale
        quad = [*tl, *bl, *br, *tr]
        image = image.transform((round(width), round(height)), Image.Transform.QUAD, tuple(float(value) for value in quad), Image.Resampling.BICUBIC)
    if max(image.size) > requested_max_edge:
        image.thumbnail((requested_max_edge, requested_max_edge), Image.Resampling.LANCZOS)
    return image


def encode_prepared(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=6)
    return output.getvalue()


def assess_quality(image: Image.Image) -> tuple[dict[str, float | int], list[str]]:
    # Quality statistics deliberately operate on a bounded grayscale sample.
    # Materializing the original RGB image first made a large temporary float64
    # array before the downscale happened, which could exhaust worker memory.
    # Pillow's grayscale conversion uses the same standard luma coefficients as
    # the previous RGB dot product, while float32 keeps all later calculations
    # stable and bounded.
    scale = min(1.0, 1600.0 / max(image.size))
    sampled_image = image
    if scale < 1:
        sampled_image = image.copy()
        sampled_image.thumbnail(
            (round(image.width * scale), round(image.height * scale)),
            Image.Resampling.BILINEAR,
        )
    sample = np.asarray(ImageOps.grayscale(sampled_image), dtype=np.float32)
    center = sample[1:-1, 1:-1]
    laplacian = sample[:-2, 1:-1] + sample[2:, 1:-1] + sample[1:-1, :-2] + sample[1:-1, 2:] - 4 * center
    laplacian_variance = float(laplacian.var()) if laplacian.size else 0.0
    exposure_mean = float(sample.mean())
    contrast_stddev = float(sample.std())
    gradient_y, gradient_x = np.gradient(sample)
    magnitude = np.hypot(gradient_x, gradient_y)
    cutoff = float(np.percentile(magnitude, 90)) if magnitude.size else 0.0
    mask = magnitude > max(cutoff, 8.0)
    skew_degrees = 0.0
    if contrast_stddev >= 8 and mask.sum() >= 100:
        skew_image = image.copy()
        skew_image.thumbnail((600, 600), Image.Resampling.BILINEAR)
        skew_gray = ImageOps.grayscale(skew_image)
        gray_array = np.asarray(skew_gray, dtype=np.float32)
        background = float(np.percentile(gray_array, 90))
        best_score = -1.0
        best_correction = 0.0
        for correction in np.arange(-12.0, 12.01, 0.5):
            rotated = skew_gray.rotate(float(correction), resample=Image.Resampling.BILINEAR, expand=False, fillcolor=round(background))
            ink = np.clip(background - np.asarray(rotated, dtype=np.float32), 0, None)
            score = float(ink.sum(axis=1).var())
            if score > best_score:
                best_score, best_correction = score, float(correction)
        skew_degrees = -best_correction
    metrics: dict[str, float | int] = {
        "blur_laplacian_variance": round(laplacian_variance, 3),
        "exposure_mean": round(exposure_mean, 3),
        "contrast_stddev": round(contrast_stddev, 3),
        "skew_degrees": round(skew_degrees, 3),
        "width": image.width,
        "height": image.height,
        "short_edge": min(image.size),
        "skew_edge_samples": int(mask.sum()),
    }
    warnings_out: list[str] = []
    if laplacian_variance < QUALITY_THRESHOLDS["blur_laplacian_variance_min"]:
        warnings_out.append("image_blurry")
    if exposure_mean < QUALITY_THRESHOLDS["exposure_mean_min"]:
        warnings_out.append("image_too_dark")
    elif exposure_mean > QUALITY_THRESHOLDS["exposure_mean_max"]:
        warnings_out.append("image_too_bright")
    if contrast_stddev < QUALITY_THRESHOLDS["contrast_stddev_min"]:
        warnings_out.append("image_low_contrast")
    if abs(skew_degrees) > QUALITY_THRESHOLDS["absolute_skew_degrees_max"]:
        warnings_out.append("image_skewed")
    if min(image.size) < QUALITY_THRESHOLDS["short_edge_min"]:
        warnings_out.append("image_resolution_low")
    return metrics, warnings_out
