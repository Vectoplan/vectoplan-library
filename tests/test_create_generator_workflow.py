# services/vectoplan-library/tests/test_create_generator_workflow.py
"""Regression tests for the VPLIB create generator workflow integration.

These tests intentionally stay close to the generated service boundary:

- route-adjacent service functions must be importable without Flask request state
- generator workflow services must not import Flask or SQLAlchemy directly
- read/create action wrappers must return structured payloads instead of raising
- source-writing actions are only smoke-tested in blocked/dry-run mode

The tests are defensive because the library service is assembled from optional
domain services. A missing optional dependency should produce a structured
partial/error payload, not an import-time or request-time crash.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping

import pytest


TESTS_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = TESTS_DIR.parent
SRC_DIR = SERVICE_ROOT / "src"
ROUTES_DIR = SERVICE_ROOT / "routes"


for candidate in (SERVICE_ROOT, SRC_DIR):
    candidate_text = str(candidate)
    if candidate.exists() and candidate_text not in sys.path:
        sys.path.insert(0, candidate_text)


def _import_module_from_file(module_name: str, path: Path) -> ModuleType:
    if not path.exists():
        pytest.skip(f"Module file not found: {path}")

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        pytest.skip(f"Could not create import spec for {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _import_any(module_names: Iterable[str], fallback_file: Path | None = None) -> ModuleType:
    last_error: BaseException | None = None

    for module_name in module_names:
        try:
            return importlib.import_module(module_name)
        except BaseException as error:  # pragma: no cover - diagnostic path
            last_error = error

    if fallback_file is not None:
        return _import_module_from_file("_test_import_" + fallback_file.stem, fallback_file)

    pytest.skip(f"Could not import any of {list(module_names)}: {last_error}")


def _route_service_module() -> ModuleType:
    return _import_any(
        (
            "services.library_create_route_service",
            "src.services.library_create_route_service",
            "library_create_route_service",
        ),
        fallback_file=SRC_DIR / "services" / "library_create_route_service.py",
    )


def _workflow_module() -> ModuleType:
    return _import_any(
        (
            "library.services.library_generator_workflow_service",
            "src.library.services.library_generator_workflow_service",
        ),
        fallback_file=SRC_DIR / "library" / "services" / "library_generator_workflow_service.py",
    )


def _context_module() -> ModuleType:
    return _import_any(
        (
            "library.services.library_generator_context_service",
            "src.library.services.library_generator_context_service",
        ),
        fallback_file=SRC_DIR / "library" / "services" / "library_generator_context_service.py",
    )


def _module_source(module: ModuleType) -> str:
    path = Path(getattr(module, "__file__", "") or "")
    if not path.exists():
        pytest.skip(f"Module source path not available for {module!r}")
    return path.read_text(encoding="utf-8")


def _assert_no_forbidden_imports(module: ModuleType, forbidden_roots: set[str]) -> None:
    source = _module_source(module)
    tree = ast.parse(source)

    imported_roots: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.append(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_roots.append(node.module.split(".", 1)[0])

    forbidden_found = sorted({root for root in imported_roots if root in forbidden_roots})
    assert forbidden_found == [], f"Forbidden direct imports in {module.__name__}: {forbidden_found}"


def _assert_no_direct_db_write_tokens(module_or_path: ModuleType | Path) -> None:
    if isinstance(module_or_path, Path):
        if not module_or_path.exists():
            pytest.skip(f"Source file not found: {module_or_path}")
        source = module_or_path.read_text(encoding="utf-8")
        label = str(module_or_path)
    else:
        source = _module_source(module_or_path)
        label = module_or_path.__name__

    forbidden_tokens = (
        "db.create_all(",
        ".create_all(",
        "db.session",
        ".session.add(",
        ".session.delete(",
        ".session.commit(",
        ".query(",
        "session.query(",
    )

    found = [token for token in forbidden_tokens if token in source]
    assert found == [], f"Forbidden direct DB/write tokens in {label}: {found}"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, bytes):
        return {"bytes": len(value)}

    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]

    if isinstance(value, list):
        return [_jsonable(item) for item in value]

    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}

    if is_dataclass(value):
        return _jsonable(asdict(value))

    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())

    if hasattr(value, "__dict__"):
        return _jsonable(
            {
                key: item
                for key, item in vars(value).items()
                if not key.startswith("_")
            }
        )

    return str(value)


def _payload_from_response(response: Any) -> Any:
    if isinstance(response, tuple) and response:
        return _jsonable(response[0])

    return _jsonable(response)


def _payload_text(value: Any) -> str:
    try:
        return json.dumps(_jsonable(value), sort_keys=True, default=str).lower()
    except TypeError:
        return str(value).lower()


def _has_any_key(value: Any, keys: Iterable[str]) -> bool:
    wanted = {key.lower() for key in keys}

    def walk(item: Any) -> bool:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if str(key).lower() in wanted:
                    return True
                if walk(nested):
                    return True
            return False

        if isinstance(item, list):
            return any(walk(nested) for nested in item)

        return False

    return walk(_jsonable(value))


def _minimal_create_payload() -> dict[str, Any]:
    return {
        "vplib_uid": "vplib_test_generator_workflow_0001",
        "object_kind": "cell_block",
        "domain": "hochbau",
        "category": "bloecke",
        "subcategory": "basis",
        "name": "Pytest Generator Workflow",
        "label": "Pytest Generator Workflow",
        "description": "Smoke payload for route/workflow contract tests.",
        "taxonomy_path": "hochbau/bloecke/basis",
        "family_profile_id": "",
        "variant_profile_id": "",
        "default_variant_id": "default",
        "definition_variants_json": json.dumps(
            [
                {
                    "variant_id": "default",
                    "label": "Standard",
                    "is_default": True,
                    "kind": "standard",
                    "definition_values": {
                        "variant.variant_id": "default",
                        "variant.label": "Standard",
                    },
                    "additional_field_keys": [],
                }
            ],
            sort_keys=True,
        ),
        "technical_document_uploads_json": json.dumps(
            {
                "kind": "technical_documents",
                "backend_enabled": False,
                "local_only": True,
                "count": 0,
                "files": [],
            },
            sort_keys=True,
        ),
        "geometry_model_uploads_json": json.dumps(
            {
                "kind": "geometry_model",
                "backend_enabled": False,
                "local_only": True,
                "count": 0,
                "files": [],
            },
            sort_keys=True,
        ),
        "client": {
            "source": "pytest",
            "action": "contract-smoke",
        },
    }


def test_generator_workflow_module_imports_and_keeps_layer_contract() -> None:
    module = _workflow_module()

    assert hasattr(module, "LibraryGeneratorWorkflowService")
    _assert_no_forbidden_imports(module, {"flask", "sqlalchemy", "requests"})
    _assert_no_direct_db_write_tokens(module)


def test_generator_context_module_imports_and_keeps_layer_contract() -> None:
    module = _context_module()

    assert hasattr(module, "LibraryGeneratorContextService")
    _assert_no_forbidden_imports(module, {"flask", "sqlalchemy", "requests"})
    _assert_no_direct_db_write_tokens(module)


def test_route_adjacent_service_imports_and_exposes_public_contract() -> None:
    module = _route_service_module()

    expected = {
        "get_route_plan",
        "get_route_service_health",
        "get_options_response",
        "get_create_context_response",
        "get_current_definitions_response",
        "build_draft_response",
        "validate_draft_response",
        "build_package_plan_response",
        "build_download_response",
        "save_package_response",
        "clear_cache_response",
        "normalize_payload",
        "merge_payloads",
    }

    missing = sorted(name for name in expected if not hasattr(module, name))
    assert missing == []


def test_route_adjacent_service_keeps_non_flask_service_boundary() -> None:
    module = _route_service_module()

    _assert_no_forbidden_imports(module, {"flask", "sqlalchemy", "requests"})
    _assert_no_direct_db_write_tokens(module)


def test_flask_create_route_file_keeps_adapter_boundary() -> None:
    route_file = ROUTES_DIR / "create.py"
    if not route_file.exists():
        pytest.skip("routes/create.py not present in this checkout")

    source = route_file.read_text(encoding="utf-8")

    assert "db.create_all(" not in source
    assert ".create_all(" not in source
    assert "db.session" not in source
    assert "session.query(" not in source
    assert ".query(" not in source
    assert "requests.get(" not in source
    assert "requests.post(" not in source


def test_route_plan_contains_core_generator_actions() -> None:
    module = _route_service_module()
    plan = module.get_route_plan()
    payload = _payload_from_response(plan)
    text = _payload_text(payload)

    for expected_word in ("draft", "validate", "package", "download", "save"):
        assert expected_word in text

    assert "api/v1/vplib/create" in text or "create" in text


def test_route_service_health_returns_structured_payload() -> None:
    module = _route_service_module()
    response = module.get_route_service_health()
    payload = _payload_from_response(response)

    assert isinstance(payload, (dict, list))
    assert _has_any_key(payload, {"ok", "status", "health", "data", "issues", "checks"})


@pytest.mark.parametrize(
    "function_name",
    (
        "get_options_response",
        "get_create_context_response",
        "get_current_definitions_response",
    ),
)
def test_read_style_route_service_responses_do_not_raise(function_name: str) -> None:
    module = _route_service_module()
    function = getattr(module, function_name)

    response = function()
    payload = _payload_from_response(response)

    assert isinstance(payload, (dict, list))
    assert _has_any_key(payload, {"ok", "status", "data", "payload", "error", "issues", "definitions"})


@pytest.mark.parametrize(
    ("function_name", "expected_word"),
    (
        ("build_draft_response", "draft"),
        ("validate_draft_response", "validate"),
        ("build_package_plan_response", "package"),
        ("build_persistent_draft_payload_response", "draft"),
        ("build_publish_bundle_response", "publish"),
    ),
)
def test_generator_action_route_wrappers_return_structured_responses(
    function_name: str,
    expected_word: str,
) -> None:
    module = _route_service_module()

    if not hasattr(module, function_name):
        pytest.skip(f"{function_name} is not available")

    payload = _minimal_create_payload()
    response = getattr(module, function_name)(payload)
    result = _payload_from_response(response)
    text = _payload_text(result)

    assert isinstance(result, (dict, list))
    assert _has_any_key(result, {"ok", "status", "data", "payload", "error", "issues", "action"})
    assert expected_word in text or "ok" in text or "status" in text


def test_download_route_wrapper_is_non_throwing_and_metadata_safe() -> None:
    module = _route_service_module()

    payload = _minimal_create_payload()
    response = module.build_download_response(payload)
    result = _payload_from_response(response)

    assert isinstance(result, (dict, list))
    assert _has_any_key(
        result,
        {
            "ok",
            "status",
            "data",
            "payload",
            "error",
            "issues",
            "filename",
            "content_type",
            "headers",
            "bytes",
        },
    )


def test_save_route_wrapper_blocks_or_structures_write_without_explicit_permission() -> None:
    module = _route_service_module()

    payload = _minimal_create_payload()
    payload["allow_source_write"] = False
    payload["save_source"] = False
    payload["dry_run"] = True

    response = module.save_package_response(
        payload,
        overwrite=False,
        allow_source_write=False,
        save_source=False,
        dry_run=True,
    )
    result = _payload_from_response(response)
    text = _payload_text(result)

    assert isinstance(result, (dict, list))
    assert _has_any_key(result, {"ok", "status", "data", "payload", "error", "issues", "skipped"})
    assert "save" in text or "write" in text or "dry" in text or "status" in text


def test_normalize_payload_is_non_throwing_and_keeps_core_fields_visible() -> None:
    module = _route_service_module()

    payload = _minimal_create_payload()
    normalized = module.normalize_payload(payload)
    result = _payload_from_response(normalized)
    text = _payload_text(result)

    assert isinstance(result, (dict, list))
    assert "cell_block" in text
    assert "definition_variants_json" in text or "definition" in text
    assert "technical_document" in text or "upload" in text


def test_merge_payloads_prefers_patch_values_without_losing_base_payload() -> None:
    module = _route_service_module()

    base = {
        "object_kind": "cell_block",
        "domain": "hochbau",
        "category": "bloecke",
        "name": "Base",
        "nested": {
            "a": 1,
        },
    }
    patch = {
        "name": "Patch",
        "subcategory": "basis",
        "nested": {
            "b": 2,
        },
    }

    merged = module.merge_payloads(base, patch)
    result = _payload_from_response(merged)
    text = _payload_text(result)

    assert "patch" in text
    assert "hochbau" in text
    assert "basis" in text
    assert "nested" in text


def test_cache_clear_response_is_structured_and_non_throwing() -> None:
    module = _route_service_module()

    response = module.clear_cache_response()
    payload = _payload_from_response(response)

    assert isinstance(payload, (dict, list))
    assert _has_any_key(payload, {"ok", "status", "data", "payload", "cleared", "cache", "issues"})


def test_public_aliases_remain_available_for_route_service_compatibility() -> None:
    module = _route_service_module()

    aliases = {
        "health",
        "options",
        "create_context",
        "definitions_current",
        "draft",
        "validate",
        "package_plan",
        "download",
        "save",
        "cache_clear",
    }

    missing = sorted(alias for alias in aliases if not hasattr(module, alias))
    assert missing == []