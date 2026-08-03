from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from math import copysign, radians, tan
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageOps

from .database import AnnotationDatabase, corrected_dimensions, correction_parameters


PAGE_NAMESPACE = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"
ET.register_namespace("", PAGE_NAMESPACE)


def _tag(name: str) -> str:
    return f"{{{PAGE_NAMESPACE}}}{name}"


def _point(value: float) -> int:
    return round(value)


def _points(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{_point(x)},{_point(y)}" for x, y in points)


def _safe_filename(image_id: int, filename: str) -> str:
    clean = "".join(character if character.isalnum() or character in "._-" else "_" for character in filename)
    return f"{image_id:06d}_{clean}"


def _center_to_size(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_width, target_height = size
    left = max(0, (image.width - target_width) // 2)
    top = max(0, (image.height - target_height) // 2)
    cropped = image.crop(
        (left, top, min(image.width, left + target_width), min(image.height, top + target_height))
    )
    if cropped.size == size:
        return cropped
    canvas = Image.new("RGB", size, "white")
    canvas.paste(cropped, ((target_width - cropped.width) // 2, (target_height - cropped.height) // 2))
    return canvas


def _export_corrected_image(image: dict[str, object], destination: Path) -> tuple[int, int]:
    source = Path(str(image["source_path"]))
    metadata = dict(image["metadata"])  # type: ignore[arg-type]
    _, _, angle = correction_parameters(metadata)
    expected_size = corrected_dimensions(float(image["width"]), float(image["height"]), metadata)
    with Image.open(source) as opened:
        corrected = ImageOps.exif_transpose(opened).convert("RGB")
        if abs(angle % 360) > 1e-9:
            # Canvas uses positive angles clockwise; Pillow uses positive
            # angles counter-clockwise, hence the minus sign.
            corrected = corrected.rotate(
                -angle,
                resample=Image.Resampling.BICUBIC,
                expand=True,
                fillcolor="white",
            )
        corrected = _center_to_size(corrected, expected_size)
        suffix = destination.suffix.lower()
        save_options: dict[str, object] = {}
        if suffix in {".jpg", ".jpeg", ".webp"}:
            save_options["quality"] = 95
        if suffix == ".png":
            save_options["compress_level"] = 6
        corrected.save(destination, **save_options)
    return expected_size


def _page_xml(image: dict[str, object], exported_filename: str) -> bytes:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    root = ET.Element(_tag("PcGts"))
    metadata = ET.SubElement(root, _tag("Metadata"))
    ET.SubElement(metadata, _tag("Creator")).text = "Tajik HTR Kraken Annotator"
    ET.SubElement(metadata, _tag("Created")).text = now
    ET.SubElement(metadata, _tag("LastChange")).text = now
    page = ET.SubElement(
        root,
        _tag("Page"),
        {
            "imageFilename": f"../images/{exported_filename}",
            "imageWidth": str(int(image["width"])),
            "imageHeight": str(int(image["height"])),
        },
    )
    regions = list(image["regions"])  # type: ignore[arg-type]
    min_x = min(float(region["x"]) for region in regions)
    min_y = min(float(region["y"]) for region in regions)
    max_x = max(float(region["x"]) + float(region["width"]) for region in regions)
    max_y = max(float(region["y"]) + float(region["height"]) for region in regions)
    text_region = ET.SubElement(
        page,
        _tag("TextRegion"),
        {"id": f"region_{int(image['id']):06d}", "type": "TextRegion"},
    )
    ET.SubElement(
        text_region,
        _tag("Coords"),
        {"points": _points([(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)])},
    )
    for index, region in enumerate(regions):
        x = float(region["x"])
        y = float(region["y"])
        width = float(region["width"])
        height = float(region["height"])
        baseline_y = float(region["baseline_y"])
        baseline_angle = float(region.get("baseline_angle", 0.0))
        line = ET.SubElement(
            text_region,
            _tag("TextLine"),
            {
                "id": f"line_{int(image['id']):06d}_{index:04d}",
                "custom": f"structure {{type:{region['line_type']};}}",
            },
        )
        ET.SubElement(
            line,
            _tag("Coords"),
            {"points": _points([(x, y), (x + width, y), (x + width, y + height), (x, y + height)])},
        )
        inset = min(max(width * 0.02, 1.0), width / 4)
        half_span = max(0.0, width - 2 * inset) / 2
        requested_rise = tan(radians(baseline_angle)) * half_span
        available_rise = max(0.0, min(baseline_y - y, y + height - baseline_y))
        rise = copysign(min(abs(requested_rise), available_rise), requested_rise)
        ET.SubElement(
            line,
            _tag("Baseline"),
            {
                "points": _points(
                    [
                        (x + inset, baseline_y - rise),
                        (x + width - inset, baseline_y + rise),
                    ]
                )
            },
        )
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _automatic_split(image: dict[str, object]) -> str:
    split = str(image["split"])
    if split != "unassigned":
        return split
    return "validation" if int(str(image["sha256"])[:8], 16) % 10 == 0 else "train"


def export_dataset(database: AnnotationDatabase, export_root: Path) -> dict[str, object]:
    rows = database.export_rows()
    if not rows:
        raise ValueError("no_annotated_images")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = export_root / timestamp
    images_directory = target / "images"
    pages_directory = target / "page"
    images_directory.mkdir(parents=True, exist_ok=False)
    pages_directory.mkdir(parents=True, exist_ok=False)
    manifests: dict[str, list[str]] = {"train": [], "validation": [], "test": []}
    metadata_images: list[dict[str, object]] = []
    for image in rows:
        exported_filename = _safe_filename(int(image["id"]), str(image["filename"]))
        exported_image = images_directory / exported_filename
        corrected_width, corrected_height = _export_corrected_image(image, exported_image)
        exported_page = {
            **image,
            "width": corrected_width,
            "height": corrected_height,
        }
        page_filename = f"{Path(exported_filename).stem}.xml"
        (pages_directory / page_filename).write_bytes(_page_xml(exported_page, exported_filename))
        split = _automatic_split(image)
        manifests[split].append(f"page/{page_filename}")
        metadata_images.append(
            {
                "id": image["id"],
                "sha256": image["sha256"],
                "source_filename": image["filename"],
                "exported_image": f"images/{exported_filename}",
                "page_xml": f"page/{page_filename}",
                "width": corrected_width,
                "height": corrected_height,
                "split": split,
                "document_label": image["document_label"],
                "notes": image["notes"],
                "metadata": image["metadata"],
                "regions": image["regions"],
            }
        )
    for split, entries in manifests.items():
        (target / f"{split}.lst").write_text(
            "".join(f"{entry}\n" for entry in entries),
            encoding="utf-8",
        )
    experiment = """device: cuda:0
precision: bf16-mixed
num_workers: 2
num_threads: 1
segtrain:
  training_data:
    - train.lst
  evaluation_data:
    - validation.lst
  format_type: page
  checkpoint_path: checkpoints
  weights_format: safetensors
  topline: false
  augment: true
  line_class_mapping:
    - ['*', 3]
    - ['DefaultLine', 3]
  region_class_mapping: []
  quit: early
  min_epochs: 10
  lrate: 0.0002
"""
    (target / "experiment.yml").write_text(experiment, encoding="utf-8")
    metadata_payload = {
        "schema_version": 1,
        "format": "PAGE XML 2019-07-15",
        "kraken_target": "7.x BLLA segmentation",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database": str(database.path),
        "counts": {
            "images": len(metadata_images),
            "lines": sum(len(image["regions"]) for image in metadata_images),
            **{split: len(entries) for split, entries in manifests.items()},
        },
        "images": metadata_images,
    }
    (target / "metadata.json").write_text(
        json.dumps(metadata_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    readme = """# Kraken segmentation training export

This export contains PAGE XML line boundaries and baseline polylines.
Run the command from this export directory inside the Kraken WSL environment:

```bash
"${HOME}/.local/share/tajik-htr/kraken-7.0.3/venv/bin/ketos" --config experiment.yml segtrain
```

`region_class_mapping: []` intentionally trains line baselines only. Rectangle
boundaries remain available to Kraken for line extraction and evaluation.
"""
    (target / "README_TRAINING.md").write_text(readme, encoding="utf-8")
    archive = export_root / f"{timestamp}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(target))
    return {
        "export_id": timestamp,
        "directory": str(target),
        "archive": str(archive),
        "counts": metadata_payload["counts"],
    }
