# services/vectoplan-library/src/routes/create.py
"""
VECTOPLAN Library – Create Blueprint

Purpose:
    Flask adapter for the simple VPLIB create flow.

Scope:
    - Provides /create frontend route.
    - Provides /api/v1/vplib/create/* API routes.
    - Does not generate VPLIB documents directly.
    - Does not validate package semantics directly.
    - Does not write package files directly.
    - Delegates all HTTP-near work to:
        services.library_create_route_service
    - Delegates all domain/package work indirectly to:
        library.services.library_create_service

Expected integration:
    In app.py or the central route registration:
        from routes.create import create_bp
        app.register_blueprint(create_bp)

Primary routes:
    GET  /create
    GET  /api/v1/vplib/create/health
    GET  /api/v1/vplib/create/options
    POST /api/v1/vplib/create/draft
    POST /api/v1/vplib/create/validate
    POST /api/v1/vplib/create/package-plan
    POST /api/v1/vplib/create/download
    POST /api/v1/vplib/create/save
    POST /api/v1/vplib/create/cache/clear

Important:
    /save writes only when the lower service explicitly allows writing via env/settings.
"""

from __future__ import annotations

import io
import json
import traceback
from typing import Any, Mapping

from flask import Blueprint, Response, jsonify, make_response, render_template, request, send_file


CREATE_BLUEPRINT_VERSION = "0.1.0"
CREATE_BLUEPRINT_COMPONENT = "create-blueprint"

CREATE_PAGE_ROUTE = "/create"
CREATE_API_PREFIX = "/api/v1/vplib/create"

CREATE_TEMPLATE = "library_admin/create.html"
FALLBACK_TEMPLATE_TITLE = "VPLIB erstellen"


try:
    from services import library_create_route_service as _route_service

    _ROUTE_SERVICE_IMPORT_ERROR: BaseException | None = None
except Exception as import_error:  # pragma: no cover - defensive runtime guard
    _route_service = None  # type: ignore[assignment]
    _ROUTE_SERVICE_IMPORT_ERROR = import_error


create_bp = Blueprint("vplib_create", __name__)


@create_bp.get(CREATE_PAGE_ROUTE)
def create_page() -> Response | str:
    """Render the simple VPLIB create frontend.

    The route intentionally stays small.
    If the final template is not present yet, a minimal fallback page is rendered
    so the backend route can already be smoke-tested.
    """
    try:
        route_health = _safe_route_health_payload()
        options_payload = _safe_options_payload()

        context = {
            "create_blueprint": {
                "component": CREATE_BLUEPRINT_COMPONENT,
                "version": CREATE_BLUEPRINT_VERSION,
                "api_prefix": CREATE_API_PREFIX,
                "page_route": CREATE_PAGE_ROUTE,
            },
            "create_api_prefix": CREATE_API_PREFIX,
            "create_options": options_payload.get("data", {}),
            "create_health": route_health,
            "active_screen": "create",
            "_active_screen": "create",
        }

        try:
            return render_template(CREATE_TEMPLATE, **context)
        except Exception as template_error:
            return _render_fallback_page(
                template_error=template_error,
                health_payload=route_health,
                options_payload=options_payload,
            )
    except Exception as exc:
        payload = _failure_payload(
            route="page",
            code="create_page_failed",
            message="Die Create-Seite konnte nicht gerendert werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@create_bp.get(f"{CREATE_API_PREFIX}/health")
def create_health() -> Response:
    """Health for the create blueprint, route service and create service."""
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="health")
        return _json_response(payload, 503)

    try:
        response = _route_service.get_route_service_health()  # type: ignore[union-attr]
        return _json_route_response(response)
    except Exception as exc:
        payload = _failure_payload(
            route="health",
            code="health_failed",
            message="Create-Health konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@create_bp.get(f"{CREATE_API_PREFIX}/options")
def create_options() -> Response:
    """Return create options for the frontend."""
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="options")
        return _json_response(payload, 503)

    try:
        response = _route_service.get_options_response()  # type: ignore[union-attr]
        return _json_route_response(response)
    except Exception as exc:
        payload = _failure_payload(
            route="options",
            code="options_failed",
            message="Create-Optionen konnten nicht geladen werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@create_bp.post(f"{CREATE_API_PREFIX}/draft")
def create_draft() -> Response:
    """Normalize incoming form/JSON data into a stable draft."""
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="draft")
        return _json_response(payload, 503)

    try:
        payload = _request_payload()
        response = _route_service.build_draft_response(payload)  # type: ignore[union-attr]
        return _json_route_response(response)
    except Exception as exc:
        payload = _failure_payload(
            route="draft",
            code="draft_failed",
            message="Der Draft konnte nicht erzeugt werden.",
            exc=exc,
            http_status=422,
        )
        return _json_response(payload, 422)


@create_bp.post(f"{CREATE_API_PREFIX}/validate")
def create_validate() -> Response:
    """Validate incoming form/JSON data."""
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="validate")
        return _json_response(payload, 503)

    try:
        payload = _request_payload()
        response = _route_service.validate_draft_response(payload)  # type: ignore[union-attr]
        return _json_route_response(response)
    except Exception as exc:
        payload = _failure_payload(
            route="validate",
            code="validation_failed",
            message="Die Validierung konnte nicht ausgeführt werden.",
            exc=exc,
            http_status=422,
        )
        return _json_response(payload, 422)


@create_bp.post(f"{CREATE_API_PREFIX}/package-plan")
def create_package_plan() -> Response:
    """Build package plan without writing files."""
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="package-plan")
        return _json_response(payload, 503)

    try:
        payload = _request_payload()
        include_documents = _request_bool("include_documents", default=True)
        response = _route_service.build_package_plan_response(  # type: ignore[union-attr]
            payload,
            include_documents=include_documents,
        )
        return _json_route_response(response)
    except Exception as exc:
        payload = _failure_payload(
            route="package-plan",
            code="package_plan_failed",
            message="Der Package-Plan konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@create_bp.post(f"{CREATE_API_PREFIX}/save")
def create_save() -> Response:
    """Save package into source root when write mode is enabled."""
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="save")
        return _json_response(payload, 503)

    try:
        payload = _request_payload()
        overwrite = _request_optional_bool("overwrite")
        response = _route_service.save_package_response(  # type: ignore[union-attr]
            payload,
            overwrite=overwrite,
        )
        return _json_route_response(response)
    except Exception as exc:
        payload = _failure_payload(
            route="save",
            code="save_failed",
            message="Das Package konnte nicht gespeichert werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@create_bp.post(f"{CREATE_API_PREFIX}/download")
def create_download() -> Response:
    """Return an in-memory .vplib archive as file download."""
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="download")
        return _json_response(payload, 503)

    try:
        payload = _request_payload()
        binary_response = _route_service.build_download_response(payload)  # type: ignore[union-attr]

        if not bool(getattr(binary_response, "ok", False)):
            meta_payload = _binary_response_to_payload(binary_response)
            return _json_response(meta_payload, _safe_http_status(getattr(binary_response, "http_status", 500)))

        filename = _safe_filename(getattr(binary_response, "filename", "package.vplib"))
        content = getattr(binary_response, "content", b"") or b""
        mimetype = getattr(binary_response, "mimetype", "application/octet-stream") or "application/octet-stream"
        status_code = _safe_http_status(getattr(binary_response, "http_status", 200))

        file_response = send_file(
            io.BytesIO(content),
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
            max_age=0,
        )
        file_response.status_code = status_code
        file_response.headers["X-VECTOPLAN-Create-Status"] = str(getattr(binary_response, "status", "archive_ready"))
        file_response.headers["X-VECTOPLAN-Create-Route"] = "download"
        file_response.headers["X-VECTOPLAN-Create-Version"] = CREATE_BLUEPRINT_VERSION
        file_response.headers["Cache-Control"] = "no-store"

        return file_response
    except Exception as exc:
        payload = _failure_payload(
            route="download",
            code="download_failed",
            message="Das VPLIB-Archiv konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@create_bp.post(f"{CREATE_API_PREFIX}/cache/clear")
def create_cache_clear() -> Response:
    """Clear create cache.

    Phase 1 currently has no cache, but this endpoint is useful for stable UI wiring.
    """
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="cache-clear")
        return _json_response(payload, 503)

    try:
        response = _route_service.clear_cache_response()  # type: ignore[union-attr]
        return _json_route_response(response)
    except Exception as exc:
        payload = _failure_payload(
            route="cache-clear",
            code="cache_clear_failed",
            message="Create-Cache konnte nicht geleert werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


@create_bp.get(f"{CREATE_API_PREFIX}/")
@create_bp.get(CREATE_API_PREFIX)
def create_index() -> Response:
    """Small API index for manual checks."""
    if not _is_route_service_available():
        payload = _route_service_unavailable_payload(route="index")
        return _json_response(payload, 503)

    try:
        health_response = _route_service.get_route_service_health()  # type: ignore[union-attr]
        health_payload = _route_response_to_payload(health_response)
        route_plan = health_payload.get("data", {}).get("route_plan", {})

        payload = {
            "ok": True,
            "status": "ok",
            "route": "index",
            "component": CREATE_BLUEPRINT_COMPONENT,
            "version": CREATE_BLUEPRINT_VERSION,
            "api_prefix": CREATE_API_PREFIX,
            "page_route": CREATE_PAGE_ROUTE,
            "routes": route_plan,
            "_http_status": 200,
        }
        return _json_response(payload, 200)
    except Exception as exc:
        payload = _failure_payload(
            route="index",
            code="index_failed",
            message="Create-Index konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )
        return _json_response(payload, 500)


def _request_payload() -> dict[str, Any]:
    """Collect query, JSON and form data into one payload.

    Precedence:
        1. query args
        2. JSON body
        3. form body

    Form values override JSON values because browser forms are the primary
    phase-1 frontend path.
    """
    payload: dict[str, Any] = {}

    try:
        payload.update(_mapping_to_plain_dict(request.args))
    except Exception:
        pass

    try:
        if request.is_json:
            json_body = request.get_json(silent=True)
            if isinstance(json_body, Mapping):
                payload.update(_mapping_to_plain_dict(json_body))
    except Exception:
        pass

    try:
        if request.form:
            payload.update(_mapping_to_plain_dict(request.form))
    except Exception:
        pass

    try:
        raw_data = request.get_data(cache=True, as_text=True)
        if raw_data and not request.form and not request.is_json:
            raw_text = raw_data.strip()
            if raw_text.startswith("{") and raw_text.endswith("}"):
                decoded = json.loads(raw_text)
                if isinstance(decoded, Mapping):
                    payload.update(_mapping_to_plain_dict(decoded))
    except Exception:
        pass

    return payload


def _mapping_to_plain_dict(mapping: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    for key, value in mapping.items():
        key_text = str(key)

        if isinstance(value, (list, tuple)):
            if len(value) == 1:
                result[key_text] = value[0]
            else:
                result[key_text] = list(value)
        else:
            getlist = getattr(mapping, "getlist", None)
            if callable(getlist):
                try:
                    values = getlist(key)
                    if len(values) == 1:
                        result[key_text] = values[0]
                    elif len(values) > 1:
                        result[key_text] = values
                    else:
                        result[key_text] = value
                    continue
                except Exception:
                    pass

            result[key_text] = value

    return result


def _request_bool(name: str, *, default: bool = False) -> bool:
    value = request.args.get(name, None)
    if value is None and request.form:
        value = request.form.get(name, None)
    return _safe_bool(value, default=default)


def _request_optional_bool(name: str) -> bool | None:
    value = request.args.get(name, None)
    if value is None and request.form:
        value = request.form.get(name, None)
    if value is None:
        return None
    return _safe_bool(value, default=False)


def _json_route_response(route_response: Any) -> Response:
    payload = _route_response_to_payload(route_response)
    status_code = _safe_http_status(payload.get("_http_status", 200))
    return _json_response(payload, status_code)


def _json_response(payload: Mapping[str, Any], status_code: int = 200) -> Response:
    response = jsonify(_json_safe(dict(payload)))
    response.status_code = _safe_http_status(status_code)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-VECTOPLAN-Create-Blueprint"] = CREATE_BLUEPRINT_VERSION
    return response


def _route_response_to_payload(route_response: Any) -> dict[str, Any]:
    if route_response is None:
        return _failure_payload(
            route="unknown",
            code="empty_route_response",
            message="Route-Service hat keine Antwort geliefert.",
            http_status=500,
        )

    if hasattr(route_response, "to_dict") and callable(route_response.to_dict):
        try:
            payload = route_response.to_dict(include_http_status=True)
        except TypeError:
            payload = route_response.to_dict()

        if isinstance(payload, Mapping):
            return dict(payload)

    if isinstance(route_response, Mapping):
        return dict(route_response)

    return _failure_payload(
        route="unknown",
        code="invalid_route_response",
        message="Route-Service hat einen unerwarteten Antworttyp geliefert.",
        details={"type": type(route_response).__name__, "repr": repr(route_response)},
        http_status=500,
    )


def _binary_response_to_payload(binary_response: Any) -> dict[str, Any]:
    if binary_response is None:
        return _failure_payload(
            route="download",
            code="empty_binary_response",
            message="Route-Service hat keine Download-Antwort geliefert.",
            http_status=500,
        )

    if hasattr(binary_response, "to_dict") and callable(binary_response.to_dict):
        try:
            payload = binary_response.to_dict(include_http_status=True)
        except TypeError:
            payload = binary_response.to_dict()

        if isinstance(payload, Mapping):
            return dict(payload)

    if isinstance(binary_response, Mapping):
        return dict(binary_response)

    return _failure_payload(
        route="download",
        code="invalid_binary_response",
        message="Route-Service hat einen unerwarteten Download-Antworttyp geliefert.",
        details={"type": type(binary_response).__name__, "repr": repr(binary_response)},
        http_status=500,
    )


def _safe_route_health_payload() -> dict[str, Any]:
    if not _is_route_service_available():
        return _route_service_unavailable_payload(route="health")

    try:
        response = _route_service.get_route_service_health()  # type: ignore[union-attr]
        return _route_response_to_payload(response)
    except Exception as exc:
        return _failure_payload(
            route="health",
            code="health_failed",
            message="Create-Health konnte für das Template nicht geladen werden.",
            exc=exc,
            http_status=500,
        )


def _safe_options_payload() -> dict[str, Any]:
    if not _is_route_service_available():
        return _route_service_unavailable_payload(route="options")

    try:
        response = _route_service.get_options_response()  # type: ignore[union-attr]
        return _route_response_to_payload(response)
    except Exception as exc:
        return _failure_payload(
            route="options",
            code="options_failed",
            message="Create-Optionen konnten für das Template nicht geladen werden.",
            exc=exc,
            http_status=500,
        )


def _render_fallback_page(
    *,
    template_error: BaseException,
    health_payload: Mapping[str, Any],
    options_payload: Mapping[str, Any],
) -> Response:
    """Render a minimal fallback page until create.html exists.

    This keeps GET /create testable before the frontend template is added.
    """
    health_json = json.dumps(_json_safe(dict(health_payload)), ensure_ascii=False, indent=2)
    options_json = json.dumps(_json_safe(dict(options_payload)), ensure_ascii=False, indent=2)
    template_error_text = _html_escape(str(template_error) or type(template_error).__name__)

    html = f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>{FALLBACK_TEMPLATE_TITLE}</title>
  <style>
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f172a;
      color: #e5e7eb;
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px;
    }}
    .card {{
      background: rgba(15, 23, 42, 0.9);
      border: 1px solid rgba(148, 163, 184, 0.35);
      border-radius: 16px;
      padding: 20px;
      margin: 16px 0;
    }}
    h1, h2 {{
      margin-top: 0;
    }}
    code, pre {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }}
    pre {{
      overflow: auto;
      background: rgba(2, 6, 23, 0.8);
      border-radius: 12px;
      padding: 16px;
      max-height: 420px;
    }}
    a {{
      color: #93c5fd;
    }}
  </style>
</head>
<body>
  <main>
    <section class="card">
      <p>VECTOPLAN Library</p>
      <h1>VPLIB erstellen</h1>
      <p>
        Die Route <code>/create</code> funktioniert. Das finale Template
        <code>{_html_escape(CREATE_TEMPLATE)}</code> ist noch nicht verfügbar oder konnte nicht gerendert werden.
      </p>
      <p><strong>Template-Fehler:</strong> {template_error_text}</p>
      <p>
        API-Health:
        <a href="{CREATE_API_PREFIX}/health">{CREATE_API_PREFIX}/health</a>
      </p>
      <p>
        API-Options:
        <a href="{CREATE_API_PREFIX}/options">{CREATE_API_PREFIX}/options</a>
      </p>
    </section>

    <section class="card">
      <h2>Health</h2>
      <pre>{_html_escape(health_json)}</pre>
    </section>

    <section class="card">
      <h2>Options</h2>
      <pre>{_html_escape(options_json)}</pre>
    </section>
  </main>
</body>
</html>
"""

    response = make_response(html, 200)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-VECTOPLAN-Create-Fallback"] = "true"
    return response


def _is_route_service_available() -> bool:
    return _route_service is not None and _ROUTE_SERVICE_IMPORT_ERROR is None


def _route_service_unavailable_payload(*, route: str) -> dict[str, Any]:
    details: dict[str, Any] = {
        "dependency": "services.library_create_route_service",
        "available": False,
    }

    if _ROUTE_SERVICE_IMPORT_ERROR is not None:
        details["exception_type"] = type(_ROUTE_SERVICE_IMPORT_ERROR).__name__
        details["exception"] = str(_ROUTE_SERVICE_IMPORT_ERROR)
        try:
            details["traceback"] = traceback.format_exception(
                type(_ROUTE_SERVICE_IMPORT_ERROR),
                _ROUTE_SERVICE_IMPORT_ERROR,
                _ROUTE_SERVICE_IMPORT_ERROR.__traceback__,
            )
        except Exception:
            pass

    return {
        "ok": False,
        "status": "route_service_unavailable",
        "route": route,
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "api_prefix": CREATE_API_PREFIX,
        "data": {
            "dependency": details,
        },
        "errors": [
            {
                "severity": "error",
                "code": "route_service_unavailable",
                "field": "services.library_create_route_service",
                "message": "Der Create-Route-Service konnte nicht importiert werden.",
                "details": details,
            }
        ],
        "warnings": [],
        "info": [],
        "_http_status": 503,
    }


def _failure_payload(
    *,
    route: str,
    code: str,
    message: str,
    exc: BaseException | None = None,
    details: Mapping[str, Any] | None = None,
    http_status: int = 500,
) -> dict[str, Any]:
    issue_details: dict[str, Any] = dict(details or {})

    if exc is not None:
        issue_details["exception_type"] = type(exc).__name__
        issue_details["exception"] = str(exc)
        try:
            issue_details["traceback"] = traceback.format_exc()
        except Exception:
            pass

    return {
        "ok": False,
        "status": code,
        "route": route,
        "component": CREATE_BLUEPRINT_COMPONENT,
        "version": CREATE_BLUEPRINT_VERSION,
        "api_prefix": CREATE_API_PREFIX,
        "data": {},
        "errors": [
            {
                "severity": "error",
                "code": code,
                "field": route,
                "message": message,
                "details": _json_safe(issue_details),
            }
        ],
        "warnings": [],
        "info": [],
        "_http_status": _safe_http_status(http_status),
    }


def _safe_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"1", "true", "yes", "ja", "on", "enabled", "active", "allow", "allowed"}:
        return True

    if text in {"0", "false", "no", "nein", "off", "disabled", "inactive", "deny", "blocked"}:
        return False

    return default


def _safe_http_status(value: Any) -> int:
    try:
        status = int(value)
    except Exception:
        return 500

    if status < 100 or status > 599:
        return 500

    return status


def _safe_filename(value: Any) -> str:
    text = str(value or "package.vplib").strip()
    text = text.replace("\\", "/").split("/")[-1]
    text = text.replace("\x00", "")

    if not text:
        text = "package.vplib"

    cleaned = []
    for char in text:
        if char.isalnum() or char in {"-", "_", ".", " "}:
            cleaned.append(char)
        else:
            cleaned.append("_")

    filename = "".join(cleaned).strip(" ._")

    if not filename:
        filename = "package.vplib"

    if not filename.endswith(".vplib"):
        filename = f"{filename}.vplib"

    return filename[:180]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, bytes):
        return {
            "type": "bytes",
            "size_bytes": len(value),
        }

    if isinstance(value, Mapping):
        return {str(key): _json_safe(inner_value) for key, inner_value in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]

    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _html_escape(value: Any) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )