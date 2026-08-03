"""Regression coverage for binary VPLIB assets and full-library exchange."""

from __future__ import annotations

import hashlib
import html as html_lib
import importlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest


SERVICE_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = SERVICE_ROOT / "src"
for candidate in (SERVICE_ROOT, SRC_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def create_service() -> Any:
    return importlib.import_module("library.services.library_create_service")


def archive_service() -> Any:
    return importlib.import_module("library.services.library_archive_service")


def minimal_payload() -> dict[str, Any]:
    return {
        "vplib_uid": "11111111-1111-4111-8111-111111111111",
        "family_name": "Asset Regression",
        "family_description": "VPLIB generator binary asset regression.",
        "object_kind": "cell_block",
        "domain": "hochbau",
        "category": "waende",
        "subcategory": "aussenwaende",
        "family_profile_id": "simple_cell_block",
        "variant_profile_id": "simple_cell_block.v1",
        "default_variant_id": "default",
        "geometry_width": "1",
        "geometry_height": "1",
        "geometry_depth": "1",
        "geometry_unit": "m",
        "definition_variants": [
            {
                "variant_id": "default",
                "label": "Standard",
                "is_default": True,
                "definition_values": {},
            }
        ],
    }


def binary_assets() -> list[dict[str, Any]]:
    return [
        {
            "field": "geometry_model_files",
            "filename": "cube.obj",
            "kind": "geometry_model",
            "purpose": "geometry_model",
            "relative_path": "assets/models/cube.obj",
            "content_type": "text/plain",
            "content": b"o cube\nv 0 0 0\n",
        },
        {
            "field": "texture_files",
            "filename": "stone.png",
            "kind": "textures",
            "purpose": "textures",
            "relative_path": "assets/textures/stone.png",
            "content_type": "image/png",
            "content": b"\x89PNG\r\n\x1a\nvplib-test-texture",
        },
    ]


def payload_with_assets() -> dict[str, Any]:
    return {**minimal_payload(), "_binary_assets": binary_assets()}


def rewrite_zip(content: bytes, replacements: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content), "r") as source:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                target.writestr(info.filename, replacements.get(info.filename, source.read(info.filename)))
    return output.getvalue()


def test_package_plan_exposes_binary_asset_metadata_without_bytes() -> None:
    result = create_service().build_package_plan(payload_with_assets())
    assert result.ok, [issue.to_dict() for issue in result.errors]
    assert result.data["asset_count"] == 2
    assert {item["kind"] for item in result.data["assets"]} == {"geometry_model", "textures"}
    assert all("content" not in item for item in result.data["assets"])
    assert all(item["binary"] for item in result.data["files"] if item.get("kind"))
    manifest = result.data["documents"]["vplib.manifest.json"]
    assert manifest["asset_count"] == 2
    assert manifest["assets"][0]["embedded"] is True


def test_vplib_archive_embeds_model_texture_and_asset_index() -> None:
    filename, content, result = create_service().build_vplib_archive(payload_with_assets())
    assert result.ok, [issue.to_dict() for issue in result.errors]
    assert filename.endswith(".vplib")
    with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
        names = set(archive.namelist())
        assert "assets/index.json" in names
        assert "assets/models/cube.obj" in names
        assert "assets/textures/stone.png" in names
        assert archive.read("assets/models/cube.obj") == binary_assets()[0]["content"]
        assert archive.read("assets/textures/stone.png") == binary_assets()[1]["content"]
        index = json.loads(archive.read("assets/index.json"))
        assert index["asset_count"] == 2
        assert {asset["kind"] for asset in index["assets"]} == {"geometry_model", "textures"}


def test_vplib_archive_is_deterministic_with_binary_assets() -> None:
    first = create_service().build_vplib_archive(payload_with_assets())
    second = create_service().build_vplib_archive(payload_with_assets())
    assert first[2].ok and second[2].ok
    assert first[0] == second[0]
    assert first[1] == second[1]


def test_vplib_archive_preserves_exact_cad_dimensions_per_variant() -> None:
    payload = minimal_payload()
    payload["geometry_height"] = "3"
    payload["geometry_depth"] = "0.365"
    payload["definition_variants"] = [
        {
            "variant_id": "default",
            "label": "Wand 365",
            "is_default": True,
            "definition_values": {
                "dimensions.width_mm": 1000,
                "dimensions.height_mm": 3000,
                "dimensions.depth_mm": 365,
                "dimensions.thickness_mm": 365,
                "technical.units": {"dimensions.thickness_mm": "mm"},
            },
        },
        {
            "variant_id": "wand_240",
            "label": "Wand 240",
            "is_default": False,
            "definition_values": {
                "dimensions.width_mm": 1000,
                "dimensions.height_mm": 3000,
                "dimensions.depth_mm": 240,
                "dimensions.thickness_mm": 240,
                "technical.units": {"dimensions.thickness_mm": "mm"},
            },
        },
    ]

    _, archive_content, result = create_service().build_vplib_archive(payload)

    assert result.ok, [issue.to_dict() for issue in result.errors]
    with zipfile.ZipFile(io.BytesIO(archive_content), "r") as archive:
        default_variant = json.loads(archive.read("variants/default.json"))
        second_variant = json.loads(archive.read("variants/wand_240.json"))
    assert default_variant["definition_values"]["dimensions.thickness_mm"] == 365
    assert second_variant["definition_values"]["dimensions.thickness_mm"] == 240
    assert default_variant["definition_values"]["dimensions.height_mm"] == 3000
    assert second_variant["definition_values"]["dimensions.height_mm"] == 3000
    assert default_variant["definition_values"]["dimensions.depth_mm"] == 365
    assert second_variant["definition_values"]["dimensions.depth_mm"] == 240
    assert default_variant["definition_values"]["technical.units"]["dimensions.thickness_mm"] == "mm"
    assert second_variant["definition_values"]["technical.units"]["dimensions.thickness_mm"] == "mm"


def test_save_package_writes_exact_binary_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_root = tmp_path / "source"
    monkeypatch.setenv("VECTOPLAN_LIBRARY_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("VPLIB_CREATE_WRITE_ENABLED", "true")
    result = create_service().save_package(payload_with_assets(), overwrite=True)
    assert result.ok, [issue.to_dict() for issue in result.errors]
    target = Path(result.data["target_dir"])
    assert (target / "assets/models/cube.obj").read_bytes() == binary_assets()[0]["content"]
    assert (target / "assets/textures/stone.png").read_bytes() == binary_assets()[1]["content"]
    assert result.data["written_file_count"] == len(result.data["written_files"])


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("../escape.obj", "geometry_model"),
        ("assets/models/run.exe", "geometry_model"),
        ("assets/textures/file.obj", "textures"),
        ("assets/models/duplicate.obj", "unknown"),
    ],
)
def test_unsafe_or_mismatched_binary_assets_fail_structurally(path: str, kind: str) -> None:
    payload = minimal_payload()
    payload["_binary_assets"] = [
        {
            "relative_path": path,
            "kind": kind,
            "content": b"payload",
        }
    ]
    result = create_service().build_package_plan(payload)
    assert result.ok is False
    assert result.errors


def test_default_creative_library_is_empty_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "source"
    creative = tmp_path / "creative"
    first = archive_service().initialize_default_library(
        source_root=source,
        creative_root=creative,
    )
    second = archive_service().initialize_default_library(
        source_root=source,
        creative_root=creative,
    )
    assert first["status"] == "initialized_empty"
    assert first["package_file_count"] == 0
    assert second["status"] == "existing"
    default_archive = creative / "default.vpcreative"
    assert default_archive.is_file()
    assert archive_service().validate_library_archive(default_archive.read_bytes())["package_file_count"] == 0


def test_creative_library_export_import_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "hochbau/example/assets/models").mkdir(parents=True)
    (source / "hochbau/example/vplib.manifest.json").write_text('{"ok": true}\n', encoding="utf-8")
    model_bytes = b"o exported\n"
    (source / "hochbau/example/assets/models/exported.obj").write_bytes(model_bytes)

    filename, content, metadata = archive_service().export_library_archive(
        source_root=source,
        library_id="regression",
    )
    assert filename == "regression.vpcreative"
    assert metadata["package_file_count"] == 2
    validation = archive_service().validate_library_archive(content)
    assert validation["package_file_count"] == 2

    imported_root = tmp_path / "imported"
    imported = archive_service().import_library_archive(content, source_root=imported_root)
    assert imported["ok"] is True
    assert imported["imported_file_count"] == 2
    assert (imported_root / "hochbau/example/assets/models/exported.obj").read_bytes() == model_bytes


def test_creative_library_merge_conflict_requires_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "same.json").write_text('{"source": true}', encoding="utf-8")
    _, content, _ = archive_service().export_library_archive(source_root=source)
    target = tmp_path / "target"
    target.mkdir()
    (target / "same.json").write_text('{"target": true}', encoding="utf-8")

    with pytest.raises(archive_service().LibraryArchiveError) as exc_info:
        archive_service().import_library_archive(content, source_root=target)
    assert exc_info.value.code == "import_conflict"
    imported = archive_service().import_library_archive(
        content,
        source_root=target,
        overwrite=True,
    )
    assert imported["ok"]
    assert (target / "same.json").read_text(encoding="utf-8") == '{"source": true}'


def test_creative_library_replace_removes_stale_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "fresh.json").write_text('{"fresh": true}', encoding="utf-8")
    _, content, _ = archive_service().export_library_archive(source_root=source)
    target = tmp_path / "target"
    target.mkdir()
    (target / "stale.json").write_text("stale", encoding="utf-8")
    result = archive_service().import_library_archive(content, source_root=target, mode="replace")
    assert result["ok"]
    assert not (target / "stale.json").exists()
    assert (target / "fresh.json").is_file()


def test_creative_library_rejects_checksum_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "entry.json").write_text('{"safe": true}', encoding="utf-8")
    _, content, _ = archive_service().export_library_archive(source_root=source)
    tampered = rewrite_zip(content, {"packages/entry.json": b'{"safe": false}'})
    with pytest.raises(archive_service().LibraryArchiveError) as exc_info:
        archive_service().validate_library_archive(tampered)
    assert exc_info.value.code in {"archive_entry_size_mismatch", "archive_entry_checksum_mismatch"}


def test_creative_library_rejects_path_traversal() -> None:
    output = io.BytesIO()
    manifest = {
        "format": "vectoplan.creative-library",
        "format_version": "1.0.0",
        "library_id": "unsafe",
        "package_file_count": 1,
        "entries": [
            {
                "path": "packages/../escape.json",
                "size_bytes": 2,
                "sha256": hashlib.sha256(b"{}").hexdigest(),
            }
        ],
    }
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("creative-library.manifest.json", json.dumps(manifest))
        archive.writestr("packages/../escape.json", b"{}")
    with pytest.raises(archive_service().LibraryArchiveError) as exc_info:
        archive_service().validate_library_archive(output.getvalue())
    assert exc_info.value.code == "archive_path_unsafe"


def flask_runtime() -> Any:
    return pytest.importorskip("flask")


def create_route_module() -> Any:
    flask_runtime()
    return importlib.import_module("routes.create")


def test_request_payload_reads_real_multipart_model_and_texture() -> None:
    flask = flask_runtime()
    route = create_route_module()
    app = flask.Flask(__name__)
    with app.test_request_context(
        "/api/v1/vplib/create/download",
        method="POST",
        data={
            "payload_json": json.dumps(minimal_payload()),
            "geometry_model_files": (io.BytesIO(b"o route\n"), "route.obj"),
            "texture_files": (io.BytesIO(b"\x89PNG\r\n\x1a\nroute"), "route.png"),
        },
        content_type="multipart/form-data",
    ):
        payload = route._request_payload()
    assert payload["uploaded_file_count"] == 2
    assert [asset["kind"] for asset in payload["_binary_assets"]] == ["geometry_model", "textures"]
    assert payload["_binary_assets"][0]["content"] == b"o route\n"
    assert payload["_binary_assets"][1]["relative_path"] == "assets/textures/route.png"


def test_request_payload_rejects_unsupported_upload_type() -> None:
    flask = flask_runtime()
    route = create_route_module()
    app = flask.Flask(__name__)
    with app.test_request_context(
        "/api/v1/vplib/create/download",
        method="POST",
        data={
            "payload_json": json.dumps(minimal_payload()),
            "geometry_model_files": (io.BytesIO(b"not executable"), "unsafe.exe"),
        },
        content_type="multipart/form-data",
    ):
        with pytest.raises(route.CreateRequestError) as exc_info:
            route._request_payload()
    assert exc_info.value.code == "upload_file_type_unsupported"
    assert exc_info.value.http_status == 422


def test_download_route_returns_vplib_with_real_uploaded_assets() -> None:
    flask = flask_runtime()
    route = create_route_module()
    app = flask.Flask(__name__)
    app.register_blueprint(route.create_bp)
    response = app.test_client().post(
        "/api/v1/vplib/create/download",
        data={
            "payload_json": json.dumps(minimal_payload()),
            "geometry_model_files": (io.BytesIO(b"o endpoint\n"), "endpoint.obj"),
            "texture_files": (io.BytesIO(b"\x89PNG\r\n\x1a\nendpoint"), "endpoint.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.data.startswith(b"PK")
    with zipfile.ZipFile(io.BytesIO(response.data), "r") as archive:
        assert archive.read("assets/models/endpoint.obj") == b"o endpoint\n"
        assert archive.read("assets/textures/endpoint.png") == b"\x89PNG\r\n\x1a\nendpoint"


def test_save_route_defaults_to_source_write_sync_and_update(monkeypatch: pytest.MonkeyPatch) -> None:
    flask = flask_runtime()
    route = create_route_module()
    captured: dict[str, Any] = {}

    class FakeRouteService:
        def save_package_response(self, payload: Any, *, overwrite: bool | None = None) -> dict[str, Any]:
            captured["payload"] = payload
            captured["overwrite"] = overwrite
            return {"ok": True, "status": "saved", "route": "save", "data": {}}

    monkeypatch.setattr(route, "_is_route_service_available", lambda: True)
    monkeypatch.setattr(route, "_route_service", lambda: FakeRouteService())
    app = flask.Flask(__name__)
    app.register_blueprint(route.create_bp)
    response = app.test_client().post(
        "/api/v1/vplib/create/save",
        json=minimal_payload(),
    )
    assert response.status_code == 200
    assert captured["payload"]["allow_source_write"] is True
    assert captured["payload"]["sync_after_save"] is True
    assert captured["payload"]["save_source"] is True
    assert captured["overwrite"] is True


def test_library_export_import_routes_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    flask = flask_runtime()
    source = tmp_path / "source"
    source.mkdir()
    (source / "package.json").write_text('{"route": true}', encoding="utf-8")
    monkeypatch.setenv("VECTOPLAN_LIBRARY_SOURCE_ROOT", str(source))
    routes = importlib.import_module("routes.library_routes")
    app = flask.Flask(__name__)
    app.register_blueprint(routes.get_library_blueprint())
    exported = app.test_client().get("/api/v1/vplib/library/export?library_id=route-test")
    assert exported.status_code == 200
    assert exported.data.startswith(b"PK")
    assert exported.headers["Content-Disposition"].endswith("route-test.vpcreative")

    imported_root = tmp_path / "imported"
    monkeypatch.setenv("VECTOPLAN_LIBRARY_SOURCE_ROOT", str(imported_root))
    imported = app.test_client().post(
        "/api/v1/vplib/library/import",
        data={"file": (io.BytesIO(exported.data), "route-test.vpcreative")},
        content_type="multipart/form-data",
    )
    assert imported.status_code == 200, imported.get_data(as_text=True)
    assert imported.get_json()["ok"] is True
    assert (imported_root / "package.json").is_file()


def test_create_ui_has_texture_upload_and_no_global_step3_documents() -> None:
    geometry = (SERVICE_ROOT / "templates/vplib/create/sections/_geometry.html").read_text(encoding="utf-8")
    variant_table = (SERVICE_ROOT / "templates/vplib/create/variants/_variant_table.html").read_text(encoding="utf-8")
    variant_table_js = (SERVICE_ROOT / "static/js/vplib/create/create_variant_table.js").read_text(encoding="utf-8")
    variables = (SERVICE_ROOT / "templates/vplib/create/sections/_variables.html").read_text(encoding="utf-8")
    drawer = (SERVICE_ROOT / "templates/vplib/create/variants/_variant_drawer_shell.html").read_text(encoding="utf-8")
    actions = (SERVICE_ROOT / "static/js/vplib/create/create_actions.js").read_text(encoding="utf-8")
    assert 'name="texture_files"' in geometry
    assert 'name="geometry_model_files"' in geometry
    assert "Backend-Upload folgt später" not in geometry
    assert 'name="technical_document_files"' not in variables
    assert "PDF, Tabellen, Bilder oder ZIPs werden hier nur als lokale Metadaten" not in variables
    assert 'data-vp-upload-kind="variant_documents"' in drawer
    assert 'data-vp-upload-backend-enabled="true"' in drawer
    assert "buildMultipartFormData" in actions
    assert 'data.append("payload_json"' in actions

def test_create_template_context_has_builtin_definitions_when_services_are_empty() -> None:
    flask = flask_runtime()
    route = create_route_module()
    app = flask.Flask(__name__)
    with app.test_request_context("/create", base_url="http://127.0.0.1:5101"):
        context = route._build_create_template_context(
            route_health={},
            options_payload={},
            context_payload={},
            definitions_payload={},
        )
    catalogs = context["definition_catalogs"]
    assert len(catalogs["object_kinds"]) >= 4
    assert any(item["id"] == "simple_cell_block" for item in catalogs["family_profiles"])
    assert any(item["id"] == "simple_cell_block.v1" for item in catalogs["variant_profiles"])
    assert any(item["key"] == "variant.variant_id" for item in catalogs["variables"])
    assert context["definitions"]["ready"] is True
    assert context["create_options"]["definitions"]["definitions"] == catalogs
    assert {item["id"] for item in context["_primitive_shapes"]} >= {"block", "custom"}
    assert any(item["id"] == "m" for item in context["_units"])


def test_wizard_click_capture_does_not_treat_step_panels_as_buttons() -> None:
    wizard = (SERVICE_ROOT / "static/js/vplib/create/create_wizard.js").read_text(
        encoding="utf-8"
    )
    create_template = (SERVICE_ROOT / "templates/vplib/create.html").read_text(
        encoding="utf-8"
    )

    assert 'stepperButton: "[data-vp-step-button]"' in wizard
    assert (
        'stepperButton: "[data-vp-step-button], [data-vp-step-target]' not in wizard
    )
    assert "if (!nextButton && !prevButton && !stepButton)" in wizard
    assert "data-vp-create-step" in create_template
    assert 'data-vp-step-target="identity"' in create_template



def test_create_ui_exposes_full_width_variants_and_functional_technical_inputs() -> None:
    css = (SERVICE_ROOT / "static/css/vplib/create.css").read_text(encoding="utf-8")
    variables = (SERVICE_ROOT / "templates/vplib/create/sections/_variables.html").read_text(encoding="utf-8")
    technical = (SERVICE_ROOT / "templates/vplib/create/sections/_technical_cad.html").read_text(encoding="utf-8")
    technical_js = (SERVICE_ROOT / "static/js/vplib/create/create_technical.js").read_text(encoding="utf-8")
    geometry = (SERVICE_ROOT / "templates/vplib/create/sections/_geometry.html").read_text(encoding="utf-8")
    variant_table = (SERVICE_ROOT / "templates/vplib/create/variants/_variant_table.html").read_text(encoding="utf-8")
    variant_table_js = (SERVICE_ROOT / "static/js/vplib/create/create_variant_table.js").read_text(encoding="utf-8")
    variant_drawer = (SERVICE_ROOT / "templates/vplib/create/variants/_variant_drawer_shell.html").read_text(encoding="utf-8")
    variant_drawer_js = (SERVICE_ROOT / "static/js/vplib/create/create_variant_drawer.js").read_text(encoding="utf-8")
    assert "grid-template-columns: minmax(260px, 0.42fr) minmax(0, 1fr)" not in css
    assert "grid-template-columns: minmax(0, 1fr)" in css
    assert "Variable anklicken und rechts bearbeiten" in variables
    assert "als lokale Metadaten" not in variables
    assert 'name="technical_document_files"' not in technical
    assert 'data-vp-technical-variant-select' in technical
    assert 'data-vp-technical-material-select' not in technical
    assert 'data-vp-technical-add-select' not in technical
    assert 'data-vp-technical-controller="dimensions"' in technical
    assert 'data-vp-technical-dimension-table="true"' in technical
    assert "Reale Maße für CAD" in technical
    assert "var DIMENSION_FIELDS = [" in technical_js
    assert '"dimensions.thickness_mm"' in technical_js
    assert '"dimensions.length_mm"' in technical_js
    assert "isTechnicalVariable" not in technical_js
    assert "populateAddSelect" not in technical_js
    assert 'data-vp-technical-dimension-value' in technical_js
    assert 'quantity === "length"' in technical_js
    assert '"variables[" + index + "][variant_id]"' not in technical_js
    assert 'variant_id: variantId(variant)' in technical_js
    assert 'class="vp-create-variant-row__name-button"' in variant_table
    assert 'data-vp-edit-definition-variant="true"' in variant_table
    assert '<span role="columnheader">Zusatzfelder</span>' in variant_table
    assert 'U().createElement("button", {' in variant_table_js
    assert 'createProfileCell' not in variant_table_js
    assert 'text: getSummary(variant)' not in variant_table_js
    assert 'data-vp-variant-drawer-name-input="true"' in variant_drawer
    assert 'name="definition_values[variant.label]"' in variant_drawer
    assert 'values["variant.label"] = String(cache.nameInput.value || "").trim()' in variant_drawer_js
    assert 'name="geometry_model_files"' in geometry
    assert 'name="texture_files"' in geometry
    assert "direkt in das VPLIB eingebettet" in geometry




def test_create_ui_uses_light_cad_workspace_and_visible_variable_drawer() -> None:
    css = (SERVICE_ROOT / "static/css/vplib/create.css").read_text(encoding="utf-8")
    template = (SERVICE_ROOT / "templates/vplib/create.html").read_text(encoding="utf-8")
    optional_fields = (
        SERVICE_ROOT / "static/js/vplib/create/create_variant_optional_fields.js"
    ).read_text(encoding="utf-8")
    variables_template = (
        SERVICE_ROOT / "templates/vplib/create/sections/_variables.html"
    ).read_text(encoding="utf-8")
    drawer_template = (
        SERVICE_ROOT / "templates/vplib/create/variants/_variant_drawer_shell.html"
    ).read_text(encoding="utf-8")
    actions_template = (
        SERVICE_ROOT / "templates/vplib/create/sections/_actions.html"
    ).read_text(encoding="utf-8")
    uploads = (
        SERVICE_ROOT / "static/js/vplib/create/create_uploads.js"
    ).read_text(encoding="utf-8")

    assert "/* VECTOPLAN CAD light workspace */" in css
    assert "--vp-create-preview-width: clamp(660px, 44vw, 840px)" in css
    assert (
        ".vp-create-variant-drawer__body {\n"
        "  grid-template-columns: minmax(0, 1fr)"
    ) in css
    assert 'data-theme="light"' in template
    assert 'data-vp-create-style="cad-light"' in template
    assert "var defaultTheme = \"light\";" in template
    assert 'button.setAttribute("data-vp-variant-optional-add", key)' in optional_fields
    assert "/* VECTOPLAN variable list and focused detail editor */" in css
    assert 'data-vp-profile-fields-storage="true"' in drawer_template
    assert 'data-vp-optional-ui-mode="list-detail"' in drawer_template
    assert 'data-vp-variant-detail-pane="true"' in drawer_template
    assert 'data-vp-variable-configured' in optional_fields
    assert 'activeFieldKey' in optional_fields
    assert 'hasMeaningfulValue' in optional_fields
    assert 'function areProfileFieldsHidden()' in optional_fields
    assert 'function isHiddenProfileFieldAvailable(key)' in optional_fields
    assert 'function syncHiddenProfileFieldControls(values)' in optional_fields
    assert 'syncHiddenProfileFieldControls(optionalValues)' in optional_fields
    assert '!isHiddenProfileFieldAvailable(key)' in optional_fields
    assert 'remove.textContent = "Profilfeld"' in optional_fields
    assert 'data-vp-optional-document-upload' in optional_fields
    assert 'variant_document_files[" + key + "][]' in optional_fields
    assert 'fileInput.multiple = true' in optional_fields
    assert 'data-vp-upload-accumulate' in optional_fields
    assert 'data-vp-upload-max-files' in optional_fields
    assert 'mergeAccumulatedFiles' in uploads
    assert 'input.files = transfer.files' in uploads
    assert 'button.appendChild(descriptionCell)' not in optional_fields
    assert 'button.appendChild(typeCell)' not in optional_fields
    assert 'Variablenbezeichnung' in drawer_template
    assert 'data-vp-optional-available-description="true"' not in drawer_template
    assert 'data-vp-optional-available-type="true"' not in drawer_template
    assert '/* VECTOPLAN concise variable catalog and document upload */' in css
    assert 'data-vp-optional-ui-mode", "list-detail"' in optional_fields
    assert "/* VECTOPLAN CAD light layout corrections and compact variable picker */" in css
    assert "/* VECTOPLAN compact variant actions and clean create step */" in css
    assert "Weitere technische Angaben" not in drawer_template
    assert "Variable suchen" not in drawer_template
    assert "Alle Kategorien" not in drawer_template
    assert 'data-vp-variant-drawer-footer="true"' not in drawer_template
    assert drawer_template.index('data-vp-variant-drawer-cancel="true"') < drawer_template.index(
        'data-vp-variant-drawer-close="true"'
    )
    assert 'data-vp-actions-health-pill="true"' not in actions_template
    assert 'data-create-action-status="true"' not in actions_template
    assert (
        'data-vp-object-kind-hidden-context="true"'
        in variables_template
    )
    assert (
        '    </div>\n\n    <div\n'
        '      class="vp-create-object-variants__workspace vp-create-variables__workspace"'
        in variables_template
    )


def test_variant_editor_keeps_workspace_visible_when_drawer_opens() -> None:
    css = (SERVICE_ROOT / "static/css/vplib/create.css").read_text(encoding="utf-8")
    variables = (SERVICE_ROOT / "templates/vplib/create/sections/_variables.html").read_text(
        encoding="utf-8"
    )
    drawer_js = (SERVICE_ROOT / "static/js/vplib/create/create_variant_drawer.js").read_text(
        encoding="utf-8"
    )
    assert 'setManagedHidden(cache.objectTop, state === "open"' not in variables
    assert "setManagedEditorHidden(c.objectVariantsTop, isOpen" not in drawer_js
    assert "setManagedEditorHidden(c.objectKindArea, isOpen" not in drawer_js
    assert (
        '[data-vp-variant-editor-state="open"] [data-vp-object-variants-top]'
        not in css
    )
    assert (
        ':has([data-vp-variant-drawer-root="true"]:not([hidden])) '
        "[data-vp-object-variants-top]"
        not in css
    )


def test_variant_scoped_calculation_variables_keep_variant_id() -> None:
    service = importlib.import_module("src.library.services.library_create_service")
    variables, warnings = service._normalize_variables(
        {
            "variables": [
                {
                    "key": "dimensions.thickness_mm",
                    "value": "365",
                    "unit": "mm",
                    "description": "Reale Bauteildicke",
                    "value_type": "number",
                    "scope": "variant",
                    "variant_id": "t90-365",
                }
            ]
        }
    )
    assert warnings == []
    assert variables == [
        {
            "key": "dimensions.thickness_mm",
            "value": "365",
            "unit": "mm",
            "description": "Reale Bauteildicke",
            "value_type": "number",
            "scope": "variant",
            "variant_id": "t90-365",
        }
    ]

def test_download_route_embeds_technical_document_without_write_flag() -> None:
    flask = flask_runtime()
    route = create_route_module()
    app = flask.Flask(__name__)
    app.register_blueprint(route.create_bp)
    response = app.test_client().post(
        "/api/v1/vplib/create/download",
        data={
            "payload_json": json.dumps(minimal_payload()),
            "technical_document_files": (
                io.BytesIO(b"%PDF-1.4\ntechnical regression\n"),
                "datasheet.pdf",
            ),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.headers["Content-Disposition"].endswith(".vplib")
    with zipfile.ZipFile(io.BytesIO(response.data), "r") as archive:
        assert (
            archive.read("assets/documents/technical/datasheet.pdf")
            == b"%PDF-1.4\ntechnical regression\n"
        )

def test_download_route_embeds_document_list_upload() -> None:
    flask = flask_runtime()
    route = create_route_module()
    app = flask.Flask(__name__)
    app.register_blueprint(route.create_bp)
    response = app.test_client().post(
        "/api/v1/vplib/create/download",
        data={
            "payload_json": json.dumps(minimal_payload()),
            "variant_document_files[documents.datasheets][]": [
                (
                    io.BytesIO(b"%PDF-1.4\nvariant datasheet regression\n"),
                    "product-datasheet.pdf",
                ),
                (
                    io.BytesIO(b"property,value\nfire_resistance,F90\n"),
                    "product-properties.csv",
                ),
            ],
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    with zipfile.ZipFile(io.BytesIO(response.data), "r") as archive:
        assert (
            archive.read("assets/documents/variants/product-datasheet.pdf")
            == b"%PDF-1.4\nvariant datasheet regression\n"
        )
        assert (
            archive.read("assets/documents/variants/product-properties.csv")
            == b"property,value\nfire_resistance,F90\n"
        )
        asset_index = json.loads(archive.read("assets/index.json"))
        variant_documents = [
            item
            for item in asset_index["assets"]
            if item["kind"] == "variant_documents"
        ]
        assert {
            item["relative_path"]
            for item in variant_documents
        } >= {
            "assets/documents/variants/product-datasheet.pdf",
            "assets/documents/variants/product-properties.csv",
        }

def test_simple_cell_block_supports_requested_basic_materials() -> None:
    materials = json.loads(
        (SRC_ROOT / "library/definitions/data/materials.v1.json").read_text(
            encoding="utf-8"
        )
    )
    by_id = {item["id"]: item for item in materials["items"]}

    for material_id in ("brick", "reinforced_concrete", "steel", "wood"):
        material = by_id[material_id]
        assert "simple_cell_block" in material["compatible_family_profiles"]
        assert "simple_cell_block.v1" in material["compatible_variant_profiles"]


def test_generator_options_expose_active_create_write_mode(monkeypatch: Any) -> None:
    monkeypatch.setenv("VPLIB_CREATE_WRITE_ENABLED", "true")
    service = importlib.import_module("src.services.library_create_route_service")

    options = service.get_options_response()
    template_context = service.get_template_context_response()

    assert options.data["write_enabled"] is True
    assert options.data["capabilities"]["save_to_source_root"] is True
    assert template_context.data["_write_enabled"] is True


def test_generator_options_expose_complete_taxonomy_and_definition_catalogs() -> None:
    service = importlib.import_module("src.services.library_create_route_service")
    response = service.get_options_response()
    data = response.data

    assert response.ok is True
    assert len(data["domains"]) == 3
    assert len(data["categories"]) >= 35
    assert len(data["subcategories"]) >= 200
    assert len(data["object_kinds"]) >= 4
    assert len(data["family_profiles"]) >= 19
    assert len(data["variant_profiles"]) >= 8
    assert len(data["variables"]) >= 68
    assert len(data["units"]) >= 24
    assert len(data["materials"]) >= 19

    wall = next(item for item in data["categories"] if item["id"] == "waende")
    exterior_wall = next(
        item for item in data["subcategories"] if item["id"] == "aussenwaende"
    )
    assert wall["parent_domain"] == "hochbau"
    assert exterior_wall["parent_domain"] == "hochbau"
    assert exterior_wall["parent_category"] == "waende"
    assert {"variables", "units", "materials"} <= set(
        data["definitions"].get("fallback_datasets", [])
    )


def test_create_page_renders_operational_starter_definitions() -> None:
    flask = flask_runtime()
    route = create_route_module()
    app = flask.Flask(
        __name__,
        template_folder=str(SERVICE_ROOT / "templates"),
        static_folder=str(SERVICE_ROOT / "static"),
    )
    app.register_blueprint(route.create_bp)
    response = app.test_client().get("/create")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-vp-create-definitions-available="true"' in html
    assert 'data-vp-definitions-available="true"' in html
    assert 'data-vp-action-disabled-reason="definitions_unavailable"' not in html
    assert '"simple_cell_block.v1"' in html
    assert '"variant.variant_id"' in html
    assert 'name="primitive_shape"' in html
    assert 'name="geometry_unit"' in html

def _rendered_create_page() -> tuple[Any, str]:
    flask = flask_runtime()
    route = create_route_module()
    app = flask.Flask(
        __name__,
        template_folder=str(SERVICE_ROOT / "templates"),
        static_folder=str(SERVICE_ROOT / "static"),
    )
    app.register_blueprint(route.create_bp)
    response = app.test_client().get("/create")
    return app, response.get_data(as_text=True)


def _named_form_tags(html: str, name: str) -> list[str]:
    tags = re.findall(r"<(?:input|select|textarea)\b[^>]*>", html, flags=re.IGNORECASE)
    pattern = re.compile(rf'\bname="{re.escape(name)}"', flags=re.IGNORECASE)
    return [tag for tag in tags if pattern.search(tag)]


def _tag_value(tag: str) -> str:
    match = re.search(r'\bvalue="([^"]*)"', tag, flags=re.IGNORECASE)
    return html_lib.unescape(match.group(1)) if match else ""


def _selected_value(html: str, name: str) -> str:
    select_match = re.search(
        rf'<select\b(?=[^>]*\bname="{re.escape(name)}")[^>]*>(.*?)</select>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert select_match, name
    for option in re.findall(
        r"<option\b[^>]*>",
        select_match.group(1),
        flags=re.IGNORECASE,
    ):
        if re.search(r"\bselected\b", option, flags=re.IGNORECASE):
            return _tag_value(option)
    return ""


def test_rendered_generator_uses_fresh_assets_and_one_operational_variant_state() -> None:
    app, html = _rendered_create_page()
    assert app
    assert "/static/css/vplib/create.css?v=20260729.6" in html
    assert "/static/js/vplib/create/create_uploads.js?v=20260729.6" in html
    assert "/static/js/vplib/create/create_variant_drawer.js?v=20260729.6" in html
    assert "/static/js/vplib/create/create_actions.js?v=20260729.6" in html

    for name in (
        "object_kind",
        "family_profile_id",
        "variant_profile_id",
        "definition_variants_json",
        "default_variant_id",
        "geometry_model_files",
        "texture_files",
    ):
        assert len(_named_form_tags(html, name)) == 1, name

    family_profile = _tag_value(_named_form_tags(html, "family_profile_id")[0])
    variant_profile = _tag_value(_named_form_tags(html, "variant_profile_id")[0])
    variants = json.loads(_tag_value(_named_form_tags(html, "definition_variants_json")[0]))
    assert family_profile == "simple_cell_block"
    assert variant_profile == "simple_cell_block.v1"
    assert variants[0]["variant_id"] == "default"
    assert variants[0]["is_default"] is True
    assert variants[0]["definition_values"]["dimensions.width_mm"] == 1000
    assert variants[0]["definition_values"]["dimensions.height_mm"] == 1000
    assert variants[0]["definition_values"]["dimensions.depth_mm"] == 1000
    assert 'data-create-add-variant="true"' in html
    assert 'data-vp-edit-definition-variant="true"' in html


def test_rendered_generator_embeds_isolated_editor_preview() -> None:
    _, html = _rendered_create_page()

    assert 'data-vp-preview-mode="editor-iframe"' in html
    assert 'data-vp-editor-generator-preview-frame' in html
    assert 'data-editor-preview-contract="vectoplan-generator-preview.v1"' in html
    assert 'data-vp-preview-render-enabled="false"' in html
    assert "http://127.0.0.1:5100/editor/test-generator" in html
    assert "parentOrigin=http%3A%2F%2Flocalhost" in html
    assert (
        "/static/js/vplib/create/create_editor_preview_bridge.js?v=20260729.6"
        in html
    )
    assert 'data-vp-preview-mode="dev-empty"' not in html


def test_editor_preview_bridge_deduplicates_equivalent_updates() -> None:
    bridge = (
        SERVICE_ROOT / "static/js/vplib/create/create_editor_preview_bridge.js"
    ).read_text(encoding="utf-8")

    assert 'var lastFingerprint = "";' in bridge
    assert 'fingerprint === lastFingerprint' in bridge
    assert 'root.dataset.editorPreviewLastReason = "duplicate-skipped"' in bridge
    assert "file.lastModified" in bridge
    assert "/_uploads_json$/i.test(element.name)" in bridge


def test_rendered_generator_lists_complete_dependent_taxonomy() -> None:
    _, html = _rendered_create_page()
    domain_count = re.search(r'data-create-domain-count="(\d+)"', html)
    category_count = re.search(r'data-create-category-count="(\d+)"', html)
    subcategory_count = re.search(r'data-create-subcategory-count="(\d+)"', html)

    assert domain_count and int(domain_count.group(1)) == 3
    assert category_count and int(category_count.group(1)) >= 35
    assert subcategory_count and int(subcategory_count.group(1)) >= 200
    assert 'data-vp-parent-domain="hochbau"' in html
    assert 'data-vp-parent-category="waende"' in html
    assert '"category": "waende"' in html
    assert '"subcategory": "aussenwaende"' in html

    definitions_script = re.search(
        r'<script[^>]*id="vp-create-definitions-json"[^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert definitions_script
    definitions = json.loads(definitions_script.group(1))
    assert len(definitions["variables"]) >= 68
    assert len(definitions["units"]) >= 24
    assert len(definitions["materials"]) >= 19


def test_rendered_generator_defaults_download_with_all_three_upload_types() -> None:
    app, html = _rendered_create_page()
    variants_json = _tag_value(_named_form_tags(html, "definition_variants_json")[0])
    payload = {
        "vplib_uid": "22222222-2222-4222-8222-222222222222",
        "family_name": "Rendered Generator Regression",
        "family_description": "Rendered form contract download.",
        "object_kind": _tag_value(_named_form_tags(html, "object_kind")[0]),
        "domain": _selected_value(html, "domain"),
        "category": _selected_value(html, "category"),
        "subcategory": _selected_value(html, "subcategory"),
        "family_profile_id": _tag_value(_named_form_tags(html, "family_profile_id")[0]),
        "variant_profile_id": _tag_value(_named_form_tags(html, "variant_profile_id")[0]),
        "default_variant_id": _tag_value(_named_form_tags(html, "default_variant_id")[0]),
        "definition_variants_json": variants_json,
        "geometry_width": "2.50",
        "geometry_height": "3.00",
        "geometry_depth": "0.40",
        "geometry_unit": "m",
    }
    response = app.test_client().post(
        "/api/v1/vplib/create/download",
        data={
            "payload_json": json.dumps(payload),
            "geometry_model_files": (io.BytesIO(b"o rendered-generator\n"), "house.obj"),
            "texture_files": (io.BytesIO(b"\x89PNG\r\n\x1a\nrendered"), "wall.png"),
            "technical_document_files": (io.BytesIO(b"%PDF-1.4\nrendered\n"), "datasheet.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.data.startswith(b"PK")
    with zipfile.ZipFile(io.BytesIO(response.data), "r") as archive:
        assert archive.read("assets/models/house.obj") == b"o rendered-generator\n"
        assert archive.read("assets/textures/wall.png") == b"\x89PNG\r\n\x1a\nrendered"
        assert (
            archive.read("assets/documents/technical/datasheet.pdf")
            == b"%PDF-1.4\nrendered\n"
        )



def test_single_native_variant_and_nested_geometry_survive_normalization_roundtrip() -> None:
    payload = minimal_payload()
    payload["geometry_height"] = "3"
    payload["geometry_depth"] = "0.365"
    payload["definition_variants"][0]["definition_values"] = {
        "dimensions.width_mm": 1000,
        "dimensions.height_mm": 3000,
        "dimensions.depth_mm": 365,
    }
    normalizer = importlib.import_module(
        "src.services.library_create_variant_payload_service"
    )

    normalized = normalizer.normalize_create_variant_payload(payload)
    assert len(normalized["definition_variants"]) == 1
    assert normalized["definition_variants"][0]["variant_id"] == "default"

    first = create_service().build_draft(payload)
    second = create_service().build_draft(first.data["draft"])

    assert first.ok and second.ok
    assert len(second.data["draft"]["variants"]) == 1
    assert second.data["draft"]["variants"][0]["variant_id"] == "default"
    assert second.data["draft"]["geometry"]["dimensions"] == {
        "width": 1.0,
        "height": 3.0,
        "depth": 0.365,
        "unit": "m",
    }
