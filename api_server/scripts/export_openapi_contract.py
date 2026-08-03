from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.main import create_app
from app.schemas.contracts import (
    AccessSession,
    AccountLoginRequest,
    AccountRegisterRequest,
    ApiErrorEnvelope,
    Correction,
    CorrectionCreate,
    CorrectionList,
    Diagnostics,
    Document,
    DocumentList,
    DocumentPatch,
    ExportArtifact,
    ExportCreate,
    HealthLive,
    Page,
    PageList,
    PagePatch,
    RecognitionJob,
    RecognitionRegion,
    RegionCreate,
    RegionList,
    RegionPatch,
    TextLine,
    TextLineList,
    TextLinePatch,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "openapi.v1.json"
WEB_CONTRACT_PATH = ROOT.parent / "web_app" / "contracts" / "openapi.v1.json"
HTTP_METHODS = ("get", "post", "put", "patch", "delete")
UUID_PARAMETER = {"type": "string", "format": "uuid"}
CONTRACT_MODELS: tuple[type[BaseModel], ...] = (
    AccessSession,
    AccountLoginRequest,
    AccountRegisterRequest,
    ApiErrorEnvelope,
    Correction,
    CorrectionCreate,
    CorrectionList,
    Diagnostics,
    Document,
    DocumentList,
    DocumentPatch,
    ExportArtifact,
    ExportCreate,
    HealthLive,
    Page,
    PageList,
    PagePatch,
    RecognitionJob,
    RecognitionRegion,
    RegionCreate,
    RegionList,
    RegionPatch,
    TextLine,
    TextLineList,
    TextLinePatch,
)


def _schema_ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _json_response(model: str, description: str = "Successful response") -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"schema": _schema_ref(model)}},
    }


def _json_body(model: str) -> dict[str, Any]:
    return {
        "required": True,
        "content": {"application/json": {"schema": _schema_ref(model)}},
    }


def _uuid_path_parameter(name: str) -> dict[str, Any]:
    return {"name": name, "in": "path", "required": True, "schema": UUID_PARAMETER}


def _planned_operation(
    operation_id: str,
    tag: str,
    summary: str,
    response_model: str | None,
    *,
    status: str = "200",
    parameters: list[dict[str, Any]] | None = None,
    request_model: str | None = None,
    response_media_type: str = "application/json",
) -> dict[str, Any]:
    if response_model is None:
        response: dict[str, Any] = {"description": "Successful response"}
    elif response_media_type == "application/json":
        response = _json_response(response_model)
    else:
        response = {
            "description": "Successful response",
            "content": {response_media_type: {"schema": {"type": "string", "format": "binary"}}},
        }
    operation: dict[str, Any] = {
        "operationId": operation_id,
        "summary": summary,
        "tags": [tag],
        "x-implementation-status": "planned",
        "security": [{"CookieSession": []}],
        "responses": {
            status: response,
            "default": {"$ref": "#/components/responses/ApiError"},
        },
    }
    if parameters:
        operation["parameters"] = parameters
    if request_model:
        operation["requestBody"] = _json_body(request_model)
    return operation


def _planned_paths() -> dict[str, dict[str, Any]]:
    document_id = _uuid_path_parameter("document_id")
    page_id = _uuid_path_parameter("page_id")
    region_id = _uuid_path_parameter("region_id")
    line_id = _uuid_path_parameter("text_line_id")
    export_id = _uuid_path_parameter("export_id")
    return {
        "/api/v1/documents": {
            "get": _planned_operation("listDocumentsV1", "documents", "List owned documents", "DocumentList"),
        },
        "/api/v1/documents/{document_id}": {
            "get": _planned_operation("getDocumentV1", "documents", "Get an owned document", "Document", parameters=[document_id]),
            "patch": _planned_operation("updateDocumentV1", "documents", "Update an owned document", "Document", parameters=[document_id], request_model="DocumentPatch"),
            "delete": _planned_operation("deleteDocumentV1", "documents", "Move an owned document to trash", None, status="204", parameters=[document_id], request_model="DocumentPatch"),
        },
        "/api/v1/documents/{document_id}/pages": {
            "get": _planned_operation("listDocumentPagesV1", "pages", "List pages in reading order", "PageList", parameters=[document_id]),
        },
        "/api/v1/pages/{page_id}": {
            "get": _planned_operation("getPageV1", "pages", "Get a page", "Page", parameters=[page_id]),
            "patch": _planned_operation("updatePageV1", "pages", "Update page order", "Page", parameters=[page_id], request_model="PagePatch"),
        },
        "/api/v1/pages/{page_id}/regions": {
            "get": _planned_operation("listPageRegionsV1", "regions", "List persisted recognition regions", "RegionList", parameters=[page_id]),
            "post": _planned_operation("createPageRegionV1", "regions", "Create a manual recognition region", "RecognitionRegion", status="201", parameters=[page_id], request_model="RegionCreate"),
        },
        "/api/v1/regions/{region_id}": {
            "get": _planned_operation("getRegionV1", "regions", "Get a recognition region", "RecognitionRegion", parameters=[region_id]),
            "patch": _planned_operation("updateRegionV1", "regions", "Update region geometry or order", "RecognitionRegion", parameters=[region_id], request_model="RegionPatch"),
            "delete": _planned_operation("deleteRegionV1", "regions", "Delete a recognition region", None, status="204", parameters=[region_id], request_model="RegionPatch"),
        },
        "/api/v1/regions/{region_id}/text-lines": {
            "get": _planned_operation("listRegionTextLinesV1", "text-lines", "List recognized text lines", "TextLineList", parameters=[region_id]),
        },
        "/api/v1/text-lines/{text_line_id}": {
            "get": _planned_operation("getTextLineV1", "text-lines", "Get raw, suggested and confirmed text", "TextLine", parameters=[line_id]),
            "patch": _planned_operation("updateTextLineV1", "text-lines", "Save suggested or confirmed text", "TextLine", parameters=[line_id], request_model="TextLinePatch"),
        },
        "/api/v1/text-lines/{text_line_id}/corrections": {
            "get": _planned_operation("listTextLineCorrectionsV1", "corrections", "List correction history", "CorrectionList", parameters=[line_id]),
            "post": _planned_operation("createTextLineCorrectionV1", "corrections", "Persist a confirmed correction", "Correction", status="201", parameters=[line_id], request_model="CorrectionCreate"),
        },
        "/api/v1/documents/{document_id}/exports": {
            "post": _planned_operation("createDocumentExportV1", "exports", "Create a durable export", "ExportArtifact", status="202", parameters=[document_id], request_model="ExportCreate"),
        },
        "/api/v1/exports/{export_id}": {
            "get": _planned_operation("getExportV1", "exports", "Get export status", "ExportArtifact", parameters=[export_id]),
        },
        "/api/v1/exports/{export_id}/content": {
            "get": _planned_operation("downloadExportV1", "exports", "Download a completed export", "ExportArtifact", parameters=[export_id], response_media_type="application/octet-stream"),
        },
        "/api/v1/diagnostics": {
            "get": _planned_operation("getDiagnosticsV1", "diagnostics", "Get privacy-safe diagnostics", "Diagnostics"),
        },
    }


def _install_model_components(components: dict[str, Any]) -> None:
    schemas = components.setdefault("schemas", {})
    pending: list[type[BaseModel]] = list(CONTRACT_MODELS)
    while pending:
        model = pending.pop(0)
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        definitions = schema.pop("$defs", {})
        schemas[model.__name__] = schema
        for name, definition in definitions.items():
            schemas.setdefault(name, definition)


def _annotate_scalar_formats(node: Any, property_name: str | None = None) -> None:
    if isinstance(node, dict):
        if node.get("type") == "string" and property_name is not None:
            if property_name == "id" or property_name.endswith("_id"):
                node.setdefault("format", "uuid")
            elif property_name.endswith("_at"):
                node.setdefault("format", "date-time")
        properties = node.get("properties")
        if isinstance(properties, dict):
            for name, schema in properties.items():
                _annotate_scalar_formats(schema, name)
        for key, value in node.items():
            if key != "properties":
                _annotate_scalar_formats(value, property_name)
    elif isinstance(node, list):
        for value in node:
            _annotate_scalar_formats(value, property_name)


def _normalize_live_operation(path: str, method: str, operation: dict[str, Any]) -> None:
    operation["operationId"] = "live" + re.sub(r"[^A-Za-z0-9]+", "_", f"_{method}_{path}").strip("_").title().replace("_", "") + "V1"
    operation["x-implementation-status"] = "live"
    if path != "/api/v1/health/live":
        operation["security"] = [{"CookieSession": []}]
    for parameter in operation.get("parameters", []):
        name = parameter.get("name", "")
        if parameter.get("in") == "path" and (name == "id" or name.endswith("_id")):
            parameter["schema"] = copy.deepcopy(UUID_PARAMETER)
    responses = operation.setdefault("responses", {})
    if "422" in responses:
        responses["422"] = {"$ref": "#/components/responses/ApiError"}
    responses.setdefault("default", {"$ref": "#/components/responses/ApiError"})


def build_contract() -> dict[str, Any]:
    live = create_app().openapi()
    contract = copy.deepcopy(live)
    contract["info"] = {
        "title": "Tajik HTR Studio API",
        "version": "1.0.0",
        "description": "Versioned API v1 contract. Operations marked planned are contracts only and are not exposed by the runtime until implemented.",
    }
    contract["x-contract-version"] = "api-v1"
    contract["x-generated-from-live-routes"] = True
    contract["servers"] = [{"url": "/", "description": "Same-origin deployment"}]
    contract["tags"] = [{"name": name} for name in (
        "health", "access", "documents", "pages", "jobs", "regions", "text-lines", "corrections", "exports", "diagnostics"
    )]
    components = contract.setdefault("components", {})
    _install_model_components(components)
    components.setdefault("securitySchemes", {})["CookieSession"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": "htr_session",
        "description": "HttpOnly same-origin session cookie",
    }
    components.setdefault("responses", {})["ApiError"] = {
        "description": "Typed, content-free API error",
        "content": {"application/json": {"schema": _schema_ref("ApiErrorEnvelope")}},
    }
    for path, item in contract.get("paths", {}).items():
        for method in HTTP_METHODS:
            operation = item.get(method)
            if isinstance(operation, dict):
                _normalize_live_operation(path, method, operation)
    for path, planned_item in _planned_paths().items():
        current = contract.setdefault("paths", {}).setdefault(path, {})
        for method, operation in planned_item.items():
            current.setdefault(method, operation)
    _annotate_scalar_formats(contract.get("components", {}).get("schemas", {}))
    return contract


def canonical_bytes(contract: dict[str, Any]) -> bytes:
    return (json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _success_schema(operation: dict[str, Any]) -> Any:
    for status, response in sorted(operation.get("responses", {}).items()):
        if str(status).startswith("2"):
            return response.get("content", {}).get("application/json", {}).get("schema")
    return None


def validate_live_compatibility(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    live = create_app().openapi()
    for path, item in live.get("paths", {}).items():
        for method in HTTP_METHODS:
            live_operation = item.get(method)
            if not isinstance(live_operation, dict):
                continue
            operation = contract.get("paths", {}).get(path, {}).get(method)
            label = f"{method.upper()} {path}"
            if not isinstance(operation, dict):
                errors.append(f"missing live operation: {label}")
                continue
            if operation.get("x-implementation-status") != "live":
                errors.append(f"live operation is not marked live: {label}")
            live_parameters = {(item.get("name"), item.get("in"), item.get("required", False)) for item in live_operation.get("parameters", [])}
            contract_parameters = {(item.get("name"), item.get("in"), item.get("required", False)) for item in operation.get("parameters", [])}
            if live_parameters != contract_parameters:
                errors.append(f"parameter drift: {label}")
            live_body = live_operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            contract_body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            if live_body != contract_body:
                errors.append(f"request body drift: {label}")
            if _success_schema(live_operation) != _success_schema(operation):
                errors.append(f"success response drift: {label}")
    return errors


def validate_contract(contract: dict[str, Any]) -> list[str]:
    errors = validate_live_compatibility(contract)
    if contract.get("openapi", "").split(".", 1)[0] != "3":
        errors.append("OpenAPI 3.x is required")
    required_tags = {"access", "documents", "pages", "jobs", "regions", "text-lines", "corrections", "exports", "diagnostics"}
    seen_tags: set[str] = set()
    operation_ids: set[str] = set()
    for path, item in contract.get("paths", {}).items():
        if not path.startswith("/api/v1/"):
            errors.append(f"unversioned contract path: {path}")
        for method in HTTP_METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            seen_tags.update(operation.get("tags", []))
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*V1", operation_id):
                errors.append(f"unstable operationId: {method.upper()} {path}")
            elif operation_id in operation_ids:
                errors.append(f"duplicate operationId: {operation_id}")
            else:
                operation_ids.add(operation_id)
            if operation.get("x-implementation-status") not in {"live", "planned"}:
                errors.append(f"missing implementation status: {method.upper()} {path}")
            for parameter in operation.get("parameters", []):
                name = parameter.get("name", "")
                if parameter.get("in") == "path" and (name == "id" or name.endswith("_id")):
                    if parameter.get("schema", {}).get("format") != "uuid":
                        errors.append(f"non-UUID path id: {method.upper()} {path} {name}")
    missing_tags = sorted(required_tags - seen_tags)
    if missing_tags:
        errors.append(f"missing resource tags: {', '.join(missing_tags)}")
    schemas = contract.get("components", {}).get("schemas", {})
    for name in ("Document", "Page", "RecognitionJob", "RecognitionRegion", "TextLine", "Correction", "ExportArtifact"):
        properties = schemas.get(name, {}).get("properties", {})
        if properties.get("id", {}).get("format") != "uuid":
            errors.append(f"{name}.id must use uuid format")
        for timestamp in ("created_at", "updated_at"):
            if properties.get(timestamp, {}).get("format") != "date-time":
                errors.append(f"{name}.{timestamp} must use date-time format")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or validate the deterministic API v1 OpenAPI contract")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true", help="write contracts/openapi.v1.json")
    action.add_argument("--check", action="store_true", help="validate and fail when the artifact differs")
    args = parser.parse_args(argv)
    contract = build_contract()
    errors = validate_contract(contract)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    expected = canonical_bytes(contract)
    if args.write:
        CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        WEB_CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT_PATH.write_bytes(expected)
        WEB_CONTRACT_PATH.write_bytes(expected)
        print(
            f"wrote {CONTRACT_PATH.relative_to(ROOT)} and "
            f"{WEB_CONTRACT_PATH.relative_to(ROOT.parent)} ({len(expected)} bytes each)"
        )
        return 0
    if not CONTRACT_PATH.exists():
        print(f"missing artifact: {CONTRACT_PATH.relative_to(ROOT)}", file=sys.stderr)
        return 1
    actual = CONTRACT_PATH.read_bytes()
    if actual != expected:
        print("contracts/openapi.v1.json is stale; run python -m scripts.export_openapi_contract --write", file=sys.stderr)
        return 1
    if not WEB_CONTRACT_PATH.exists() or WEB_CONTRACT_PATH.read_bytes() != expected:
        print(
            "web_app/contracts/openapi.v1.json is missing or stale; "
            "run python -m scripts.export_openapi_contract --write",
            file=sys.stderr,
        )
        return 1
    print("OpenAPI v1 contract is valid, deterministic, and compatible with live routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
