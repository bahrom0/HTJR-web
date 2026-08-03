from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from annotation_app.database import AnnotationDatabase, corrected_dimensions
from annotation_app.exporter import PAGE_NAMESPACE, export_dataset
from annotation_app.server import annotation_javascript, annotation_stylesheet


def _image(path: Path, size: tuple[int, int] = (320, 180)) -> None:
    Image.new("RGB", size, "white").save(path)


def test_browser_assets_have_explicit_mime_types() -> None:
    assert annotation_javascript().media_type == "application/javascript"
    assert annotation_stylesheet().media_type == "text/css"


def test_annotations_are_transactionally_replaced_and_revisioned(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    _image(source)
    database = AnnotationDatabase(tmp_path / "annotations.sqlite3")
    database.initialize()
    image_id, created = database.import_path(source)

    saved = database.save_annotations(
        image_id,
        regions=[
            {
                "x": 10,
                "y": 20,
                "width": 260,
                "height": 40,
                "baseline_y": 52,
                "line_type": "DefaultLine",
            }
        ],
        split="train",
        document_label="notebook-1",
        notes="clear sample",
        metadata={"writer": "A"},
        expected_revision=0,
    )

    assert created is True
    assert saved["revision"] == 1
    assert saved["status"] == "annotated"
    assert saved["region_count"] == 1
    assert saved["regions"][0]["baseline_y"] == 52
    assert saved["metadata"]["writer"] == "A"


def test_rotation_is_persisted_and_exported_in_page_coordinate_space(tmp_path: Path) -> None:
    source = tmp_path / "sideways.png"
    _image(source, (320, 180))
    database = AnnotationDatabase(tmp_path / "annotations.sqlite3")
    database.initialize()
    image_id, _ = database.import_path(source)
    saved = database.save_annotations(
        image_id,
        regions=[
            {
                "x": 10,
                "y": 20,
                "width": 150,
                "height": 260,
                "baseline_y": 250,
                "baseline_angle": 10,
                "line_type": "DefaultLine",
            }
        ],
        split="train",
        document_label="",
        notes="",
        metadata={"orientation_degrees": 90, "deskew_degrees": 0},
        expected_revision=0,
    )

    assert corrected_dimensions(320, 180, saved["metadata"]) == (180, 320)
    result = export_dataset(database, tmp_path / "exports")
    target = Path(str(result["directory"]))
    exported_image = next((target / "images").iterdir())
    page = ET.parse(next((target / "page").glob("*.xml"))).getroot().find(
        f".//{{{PAGE_NAMESPACE}}}Page"
    )
    baseline = ET.parse(next((target / "page").glob("*.xml"))).getroot().find(
        f".//{{{PAGE_NAMESPACE}}}Baseline"
    )

    with Image.open(exported_image) as image:
        assert image.size == (180, 320)
    assert page is not None
    assert page.attrib["imageWidth"] == "180"
    assert page.attrib["imageHeight"] == "320"
    assert baseline is not None
    left, right = baseline.attrib["points"].split()
    assert left.split(",")[1] != right.split(",")[1]


def test_export_contains_page_xml_baselines_manifests_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    _image(source)
    database = AnnotationDatabase(tmp_path / "annotations.sqlite3")
    database.initialize()
    image_id, _ = database.import_path(source)
    database.save_annotations(
        image_id,
        regions=[
            {
                "x": 12,
                "y": 24,
                "width": 250,
                "height": 36,
                "baseline_y": 53,
                "line_type": "DefaultLine",
            }
        ],
        split="validation",
        document_label="",
        notes="",
        metadata={"language": "Tajik"},
        expected_revision=0,
    )

    result = export_dataset(database, tmp_path / "exports")
    target = Path(str(result["directory"]))
    xml_path = next((target / "page").glob("*.xml"))
    root = ET.parse(xml_path).getroot()
    baseline = root.find(f".//{{{PAGE_NAMESPACE}}}Baseline")
    coords = root.find(f".//{{{PAGE_NAMESPACE}}}TextLine/{{{PAGE_NAMESPACE}}}Coords")
    metadata = json.loads((target / "metadata.json").read_text(encoding="utf-8"))

    assert baseline is not None
    assert baseline.attrib["points"] == "17,53 257,53"
    assert coords is not None
    assert coords.attrib["points"] == "12,24 262,24 262,60 12,60"
    assert (target / "validation.lst").read_text(encoding="utf-8").startswith("page/")
    assert metadata["counts"]["images"] == 1
    assert metadata["counts"]["lines"] == 1
    assert Path(str(result["archive"])).is_file()
