# services/vectoplan-library/src/config/vplib_settings.py
"""
VPLIB settings for the vectoplan-library microservice.

Diese Datei ist der zentrale Konfigurationsanker für die VPLIB-Routen,
Services, Creator, Source-Scanner und Teststrecken.

Sie hat bewusst keine Flask-Abhängigkeit.

Aufgaben:
- Pfade aus Environment-Variablen lesen
- sichere Defaults für lokale Entwicklung setzen
- Schreib-/Validierungsmodi normalisieren
- Test-Route und Create-Route konfigurierbar machen
- Directory-Plan und optionales Directory-Ensure bereitstellen
- Health-/Debug-Payloads für JSON-Routen liefern

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Iterable, Mapping


VPLIB_SETTINGS_SCHEMA_VERSION: Final[str] = "vplib.settings.v1"

ENV_PREFIX: Final[str] = "VPLIB_"

ENV_SERVICE_NAME: Final[str] = "VPLIB_SERVICE_NAME"
ENV_RUNTIME_MODE: Final[str] = "VPLIB_RUNTIME_MODE"

ENV_SERVICE_ROOT: Final[str] = "VPLIB_SERVICE_ROOT"
ENV_SRC_ROOT: Final[str] = "VPLIB_SRC_ROOT"
ENV_SOURCE_ROOT: Final[str] = "VPLIB_SOURCE_ROOT"
ENV_LIBRARY_CATALOG_ROOT: Final[str] = "VPLIB_LIBRARY_CATALOG_ROOT"
ENV_GENERATED_ROOT: Final[str] = "VPLIB_GENERATED_ROOT"
ENV_ARCHIVE_ROOT: Final[str] = "VPLIB_ARCHIVE_ROOT"
ENV_TEST_OUTPUT_ROOT: Final[str] = "VPLIB_TEST_OUTPUT_ROOT"

ENV_ROUTE_PREFIX: Final[str] = "VPLIB_ROUTE_PREFIX"
ENV_DEFAULT_WRITE_MODE: Final[str] = "VPLIB_DEFAULT_WRITE_MODE"
ENV_DEFAULT_VALIDATION_MODE: Final[str] = "VPLIB_DEFAULT_VALIDATION_MODE"
ENV_PACKAGE_DIR_PATTERN: Final[str] = "VPLIB_PACKAGE_DIR_PATTERN"

ENV_CREATE_ARCHIVE_DEFAULT: Final[str] = "VPLIB_CREATE_ARCHIVE_DEFAULT"
ENV_DRY_RUN_DEFAULT: Final[str] = "VPLIB_DRY_RUN_DEFAULT"
ENV_TEST_ROUTE_ENABLED: Final[str] = "VPLIB_TEST_ROUTE_ENABLED"
ENV_CREATE_ROUTE_ENABLED: Final[str] = "VPLIB_CREATE_ROUTE_ENABLED"
ENV_STRICT_ROUTES: Final[str] = "VPLIB_STRICT_ROUTES"
ENV_ALLOW_EXTERNAL_ASSET_URI: Final[str] = "VPLIB_ALLOW_EXTERNAL_ASSET_URI"

DEFAULT_SERVICE_NAME: Final[str] = "vectoplan-library"
DEFAULT_RUNTIME_MODE: Final[str] = "development"

DEFAULT_ROUTE_PREFIX: Final[str] = "/api/v1/vplib"
DEFAULT_WRITE_MODE: Final[str] = "fail"
DEFAULT_VALIDATION_MODE: Final[str] = "strict"
DEFAULT_PACKAGE_DIR_PATTERN: Final[str] = "{family_slug}"

DEFAULT_SOURCE_DIR_NAME: Final[str] = "sources"
DEFAULT_LIBRARY_CATALOG_DIR_NAME: Final[str] = "creative_library"
DEFAULT_GENERATED_DIR_NAME: Final[str] = "generated"
DEFAULT_VPLIB_GENERATED_DIR_NAME: Final[str] = "vplib"
DEFAULT_ARCHIVE_DIR_NAME: Final[str] = "archives"
DEFAULT_TEST_OUTPUT_DIR_NAME: Final[str] = "vplib_test"
DEFAULT_SELF_TEST_PACKAGE_DIR_NAME: Final[str] = "self_test_package"

TRUE_VALUES: Final[tuple[str, ...]] = ("1", "true", "yes", "y", "on", "enabled")
FALSE_VALUES: Final[tuple[str, ...]] = ("0", "false", "no", "n", "off", "disabled")


class VplibSettingsError(ValueError):
    """Wird ausgelöst, wenn VPLIB-Settings ungültig sind."""


class VplibRuntimeMode(str, Enum):
    """Runtime-Modus des Microservice."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"

    @property
    def key(self) -> str:
        return str(self.value)


class VplibWriteMode(str, Enum):
    """Default-Schreibverhalten."""

    FAIL = "fail"
    SKIP = "skip"
    OVERWRITE = "overwrite"

    @property
    def key(self) -> str:
        return str(self.value)


class VplibValidationMode(str, Enum):
    """Default-Validierungsmodus."""

    STRICT = "strict"
    NORMAL = "normal"
    PERMISSIVE = "permissive"

    @property
    def key(self) -> str:
        return str(self.value)


class VplibDirectoryRole(str, Enum):
    """Rolle eines konfigurierten Verzeichnisses."""

    SERVICE_ROOT = "service_root"
    SRC_ROOT = "src_root"
    SOURCE_ROOT = "source_root"
    LIBRARY_CATALOG_ROOT = "library_catalog_root"
    GENERATED_ROOT = "generated_root"
    ARCHIVE_ROOT = "archive_root"
    TEST_OUTPUT_ROOT = "test_output_root"
    SELF_TEST_PACKAGE_ROOT = "self_test_package_root"

    @property
    def key(self) -> str:
        return str(self.value)


class VplibDirectoryEnsureStatus(str, Enum):
    """Status eines Directory-Ensure-Vorgangs."""

    EXISTS = "exists"
    CREATED = "created"
    DRY_RUN = "dry_run"
    FAILED = "failed"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class VplibDirectoryPlanItem:
    """Ein konfiguriertes Verzeichnis."""

    role: str
    path: Path
    required: bool = True
    create_by_default: bool = True
    description: str = ""

    def normalized(self) -> "VplibDirectoryPlanItem":
        return VplibDirectoryPlanItem(
            role=parse_directory_role_value(self.role),
            path=normalize_path(self.path, "path"),
            required=bool(self.required),
            create_by_default=bool(self.create_by_default),
            description=clean_optional_string(self.description) or "",
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "role": normalized.role,
            "path": str(normalized.path),
            "required": normalized.required,
            "create_by_default": normalized.create_by_default,
            "exists": normalized.path.exists(),
            "is_dir": normalized.path.is_dir() if normalized.path.exists() else False,
            "description": normalized.description,
        }


@dataclass(frozen=True, slots=True)
class VplibDirectoryEnsureResult:
    """Ergebnis eines Directory-Ensure-Vorgangs."""

    role: str
    path: Path
    status: str
    existed_before: bool = False
    error: str | None = None

    def normalized(self) -> "VplibDirectoryEnsureResult":
        role = parse_directory_role_value(self.role)
        path = normalize_path(self.path, "path")
        status = parse_directory_ensure_status_value(self.status)
        error = clean_optional_string(self.error)

        if error:
            status = VplibDirectoryEnsureStatus.FAILED.value

        return VplibDirectoryEnsureResult(
            role=role,
            path=path,
            status=status,
            existed_before=bool(self.existed_before),
            error=error,
        )

    @property
    def ok(self) -> bool:
        return self.normalized().status in {
            VplibDirectoryEnsureStatus.EXISTS.value,
            VplibDirectoryEnsureStatus.CREATED.value,
            VplibDirectoryEnsureStatus.DRY_RUN.value,
        }

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "role": normalized.role,
            "path": str(normalized.path),
            "status": normalized.status,
            "ok": normalized.ok,
            "existed_before": normalized.existed_before,
            "error": normalized.error,
        }


@dataclass(frozen=True, slots=True)
class VplibDirectoryEnsureBatchResult:
    """Ergebnis mehrerer Directory-Ensure-Vorgänge."""

    results: tuple[VplibDirectoryEnsureResult, ...] = field(default_factory=tuple)

    def normalized(self) -> "VplibDirectoryEnsureBatchResult":
        return VplibDirectoryEnsureBatchResult(
            results=tuple(result.normalized() for result in self.results or ())
        )

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.normalized().results)

    @property
    def failed_results(self) -> tuple[VplibDirectoryEnsureResult, ...]:
        return tuple(result for result in self.normalized().results if not result.ok)

    def raise_for_errors(self) -> None:
        normalized = self.normalized()

        if not normalized.ok:
            messages = "; ".join(
                f"{result.role}: {result.error or result.status}"
                for result in normalized.failed_results
            )
            raise VplibSettingsError(messages or "Could not ensure VPLIB directories.")

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "ok": normalized.ok,
            "result_count": len(normalized.results),
            "failed_count": len(normalized.failed_results),
            "results": [result.to_dict() for result in normalized.results],
        }


@dataclass(frozen=True, slots=True)
class VplibSettings:
    """VPLIB-Microservice-Settings."""

    service_name: str = DEFAULT_SERVICE_NAME
    runtime_mode: str = DEFAULT_RUNTIME_MODE

    service_root: Path = field(default_factory=lambda: get_default_service_root())
    src_root: Path = field(default_factory=lambda: get_default_src_root())
    source_root: Path | None = None
    library_catalog_root: Path | None = None
    generated_root: Path | None = None
    archive_root: Path | None = None
    test_output_root: Path | None = None

    route_prefix: str = DEFAULT_ROUTE_PREFIX
    default_write_mode: str = DEFAULT_WRITE_MODE
    default_validation_mode: str = DEFAULT_VALIDATION_MODE
    package_dir_pattern: str = DEFAULT_PACKAGE_DIR_PATTERN

    create_archive_default: bool = False
    dry_run_default: bool = True
    test_route_enabled: bool = True
    create_route_enabled: bool = True
    strict_routes: bool = True
    allow_external_asset_uri: bool = False

    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "VplibSettings":
        service_name = clean_required_string(self.service_name or DEFAULT_SERVICE_NAME, "service_name")
        runtime_mode = parse_runtime_mode_value(self.runtime_mode or DEFAULT_RUNTIME_MODE)

        service_root = normalize_path(self.service_root, "service_root")
        src_root = normalize_path(self.src_root, "src_root", base_dir=service_root)

        source_root = normalize_path(
            self.source_root or service_root / DEFAULT_SOURCE_DIR_NAME,
            "source_root",
            base_dir=service_root,
        )
        library_catalog_root = normalize_path(
            self.library_catalog_root or service_root / DEFAULT_LIBRARY_CATALOG_DIR_NAME,
            "library_catalog_root",
            base_dir=service_root,
        )
        generated_root = normalize_path(
            self.generated_root or service_root / DEFAULT_GENERATED_DIR_NAME / DEFAULT_VPLIB_GENERATED_DIR_NAME,
            "generated_root",
            base_dir=service_root,
        )
        archive_root = normalize_path(
            self.archive_root or service_root / DEFAULT_GENERATED_DIR_NAME / DEFAULT_ARCHIVE_DIR_NAME,
            "archive_root",
            base_dir=service_root,
        )
        test_output_root = normalize_path(
            self.test_output_root or service_root / DEFAULT_GENERATED_DIR_NAME / DEFAULT_TEST_OUTPUT_DIR_NAME,
            "test_output_root",
            base_dir=service_root,
        )

        route_prefix = normalize_route_prefix(self.route_prefix or DEFAULT_ROUTE_PREFIX)

        return VplibSettings(
            service_name=service_name,
            runtime_mode=runtime_mode,
            service_root=service_root,
            src_root=src_root,
            source_root=source_root,
            library_catalog_root=library_catalog_root,
            generated_root=generated_root,
            archive_root=archive_root,
            test_output_root=test_output_root,
            route_prefix=route_prefix,
            default_write_mode=parse_write_mode_value(self.default_write_mode or DEFAULT_WRITE_MODE),
            default_validation_mode=parse_validation_mode_value(self.default_validation_mode or DEFAULT_VALIDATION_MODE),
            package_dir_pattern=clean_required_string(self.package_dir_pattern or DEFAULT_PACKAGE_DIR_PATTERN, "package_dir_pattern"),
            create_archive_default=bool(self.create_archive_default),
            dry_run_default=bool(self.dry_run_default),
            test_route_enabled=bool(self.test_route_enabled),
            create_route_enabled=bool(self.create_route_enabled),
            strict_routes=bool(self.strict_routes),
            allow_external_asset_uri=bool(self.allow_external_asset_uri),
            metadata=normalize_metadata(self.metadata),
        )

    @property
    def self_test_package_root(self) -> Path:
        normalized = self.normalized()
        return normalized.test_output_root / DEFAULT_SELF_TEST_PACKAGE_DIR_NAME

    @property
    def test_route_path(self) -> str:
        return f"{self.normalized().route_prefix}/test"

    @property
    def create_route_path(self) -> str:
        return f"{self.normalized().route_prefix}/create"

    def directory_plan(self) -> tuple[VplibDirectoryPlanItem, ...]:
        """Erzeugt den Directory-Plan für Settings/Route-Startup."""
        normalized = self.normalized()

        return (
            VplibDirectoryPlanItem(
                role=VplibDirectoryRole.SERVICE_ROOT.value,
                path=normalized.service_root,
                required=True,
                create_by_default=False,
                description="Microservice root directory.",
            ).normalized(),
            VplibDirectoryPlanItem(
                role=VplibDirectoryRole.SRC_ROOT.value,
                path=normalized.src_root,
                required=True,
                create_by_default=False,
                description="Python src root directory.",
            ).normalized(),
            VplibDirectoryPlanItem(
                role=VplibDirectoryRole.SOURCE_ROOT.value,
                path=normalized.source_root,
                required=False,
                create_by_default=True,
                description="Prepared VPLIB source packages.",
            ).normalized(),
            VplibDirectoryPlanItem(
                role=VplibDirectoryRole.LIBRARY_CATALOG_ROOT.value,
                path=normalized.library_catalog_root,
                required=True,
                create_by_default=True,
                description="Creative library catalog root.",
            ).normalized(),
            VplibDirectoryPlanItem(
                role=VplibDirectoryRole.GENERATED_ROOT.value,
                path=normalized.generated_root,
                required=True,
                create_by_default=True,
                description="Generated VPLIB package root.",
            ).normalized(),
            VplibDirectoryPlanItem(
                role=VplibDirectoryRole.ARCHIVE_ROOT.value,
                path=normalized.archive_root,
                required=False,
                create_by_default=True,
                description="Generated .vplib archives.",
            ).normalized(),
            VplibDirectoryPlanItem(
                role=VplibDirectoryRole.TEST_OUTPUT_ROOT.value,
                path=normalized.test_output_root,
                required=False,
                create_by_default=True,
                description="Route self-test output root.",
            ).normalized(),
            VplibDirectoryPlanItem(
                role=VplibDirectoryRole.SELF_TEST_PACKAGE_ROOT.value,
                path=normalized.self_test_package_root,
                required=False,
                create_by_default=True,
                description="Dry-run package root for /test route.",
            ).normalized(),
        )

    def ensure_directories(
        self,
        *,
        dry_run: bool | None = None,
        include_source_root: bool = True,
        strict: bool | None = None,
    ) -> VplibDirectoryEnsureBatchResult:
        """Legt konfigurierbare Verzeichnisse an oder simuliert dies."""
        normalized = self.normalized()
        effective_dry_run = normalized.dry_run_default if dry_run is None else bool(dry_run)
        effective_strict = normalized.strict_routes if strict is None else bool(strict)

        results: list[VplibDirectoryEnsureResult] = []

        for item in normalized.directory_plan():
            if item.role == VplibDirectoryRole.SOURCE_ROOT.value and not include_source_root:
                continue

            if not item.create_by_default:
                results.append(ensure_directory_item(item, dry_run=effective_dry_run, strict=effective_strict))
                continue

            results.append(ensure_directory_item(item, dry_run=effective_dry_run, strict=effective_strict))

        batch = VplibDirectoryEnsureBatchResult(results=tuple(results)).normalized()

        if effective_strict:
            batch.raise_for_errors()

        return batch

    def to_route_defaults(self) -> dict[str, Any]:
        """Gibt kompakte Routen-Konfiguration zurück."""
        normalized = self.normalized()

        return {
            "route_prefix": normalized.route_prefix,
            "test_route_path": normalized.test_route_path,
            "create_route_path": normalized.create_route_path,
            "test_route_enabled": normalized.test_route_enabled,
            "create_route_enabled": normalized.create_route_enabled,
            "dry_run_default": normalized.dry_run_default,
            "create_archive_default": normalized.create_archive_default,
            "default_write_mode": normalized.default_write_mode,
            "default_validation_mode": normalized.default_validation_mode,
            "strict_routes": normalized.strict_routes,
        }

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": VPLIB_SETTINGS_SCHEMA_VERSION,
            "service_name": normalized.service_name,
            "runtime_mode": normalized.runtime_mode,
            "paths": {
                "service_root": str(normalized.service_root),
                "src_root": str(normalized.src_root),
                "source_root": str(normalized.source_root),
                "library_catalog_root": str(normalized.library_catalog_root),
                "generated_root": str(normalized.generated_root),
                "archive_root": str(normalized.archive_root),
                "test_output_root": str(normalized.test_output_root),
                "self_test_package_root": str(normalized.self_test_package_root),
            },
            "routes": normalized.to_route_defaults(),
            "package_dir_pattern": normalized.package_dir_pattern,
            "allow_external_asset_uri": normalized.allow_external_asset_uri,
            "directory_plan": [item.to_dict() for item in normalized.directory_plan()],
            "metadata": dict(normalized.metadata),
        }


def build_vplib_settings_from_env(
    env: Mapping[str, Any] | None = None,
    *,
    service_root: str | Path | None = None,
) -> VplibSettings:
    """Baut VplibSettings aus Environment-Variablen."""
    environment = normalize_env_mapping(env or os.environ)

    default_service_root = normalize_path(
        service_root or get_env_path(environment, ENV_SERVICE_ROOT) or get_default_service_root(),
        "service_root",
    )

    default_src_root = get_default_src_root()

    return VplibSettings(
        service_name=get_env_string(environment, ENV_SERVICE_NAME, default=DEFAULT_SERVICE_NAME),
        runtime_mode=get_env_string(environment, ENV_RUNTIME_MODE, default=DEFAULT_RUNTIME_MODE),
        service_root=default_service_root,
        src_root=get_env_path(environment, ENV_SRC_ROOT) or default_src_root,
        source_root=get_env_path(environment, ENV_SOURCE_ROOT) or default_service_root / DEFAULT_SOURCE_DIR_NAME,
        library_catalog_root=get_env_path(environment, ENV_LIBRARY_CATALOG_ROOT) or default_service_root / DEFAULT_LIBRARY_CATALOG_DIR_NAME,
        generated_root=get_env_path(environment, ENV_GENERATED_ROOT) or default_service_root / DEFAULT_GENERATED_DIR_NAME / DEFAULT_VPLIB_GENERATED_DIR_NAME,
        archive_root=get_env_path(environment, ENV_ARCHIVE_ROOT) or default_service_root / DEFAULT_GENERATED_DIR_NAME / DEFAULT_ARCHIVE_DIR_NAME,
        test_output_root=get_env_path(environment, ENV_TEST_OUTPUT_ROOT) or default_service_root / DEFAULT_GENERATED_DIR_NAME / DEFAULT_TEST_OUTPUT_DIR_NAME,
        route_prefix=get_env_string(environment, ENV_ROUTE_PREFIX, default=DEFAULT_ROUTE_PREFIX),
        default_write_mode=get_env_string(environment, ENV_DEFAULT_WRITE_MODE, default=DEFAULT_WRITE_MODE),
        default_validation_mode=get_env_string(environment, ENV_DEFAULT_VALIDATION_MODE, default=DEFAULT_VALIDATION_MODE),
        package_dir_pattern=get_env_string(environment, ENV_PACKAGE_DIR_PATTERN, default=DEFAULT_PACKAGE_DIR_PATTERN),
        create_archive_default=get_env_bool(environment, ENV_CREATE_ARCHIVE_DEFAULT, default=False),
        dry_run_default=get_env_bool(environment, ENV_DRY_RUN_DEFAULT, default=True),
        test_route_enabled=get_env_bool(environment, ENV_TEST_ROUTE_ENABLED, default=True),
        create_route_enabled=get_env_bool(environment, ENV_CREATE_ROUTE_ENABLED, default=True),
        strict_routes=get_env_bool(environment, ENV_STRICT_ROUTES, default=True),
        allow_external_asset_uri=get_env_bool(environment, ENV_ALLOW_EXTERNAL_ASSET_URI, default=False),
        metadata={
            "source": "environment",
            "env_prefix": ENV_PREFIX,
        },
    ).normalized()


@lru_cache(maxsize=1)
def get_vplib_settings() -> VplibSettings:
    """Lädt VPLIB-Settings aus os.environ und cached das Ergebnis."""
    return build_vplib_settings_from_env(os.environ).normalized()


def reload_vplib_settings() -> VplibSettings:
    """Leert den Settings-Cache und lädt Settings neu."""
    clear_vplib_settings_cache()
    return get_vplib_settings()


def get_vplib_settings_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot der Settings zurück."""
    try:
        settings = get_vplib_settings()
        normalized = settings.normalized()

        return {
            "schema_version": VPLIB_SETTINGS_SCHEMA_VERSION,
            "healthy": True,
            "settings": normalized.to_dict(),
        }
    except Exception as exc:
        return {
            "schema_version": VPLIB_SETTINGS_SCHEMA_VERSION,
            "healthy": False,
            "error": str(exc),
        }


def ensure_vplib_runtime_directories(
    *,
    dry_run: bool | None = None,
    include_source_root: bool = True,
    strict: bool | None = None,
) -> VplibDirectoryEnsureBatchResult:
    """Legt Runtime-Verzeichnisse anhand gecachter Settings an."""
    return get_vplib_settings().ensure_directories(
        dry_run=dry_run,
        include_source_root=include_source_root,
        strict=strict,
    )


def ensure_directory_item(
    item: VplibDirectoryPlanItem,
    *,
    dry_run: bool,
    strict: bool,
) -> VplibDirectoryEnsureResult:
    """Legt ein einzelnes Directory-Plan-Item an."""
    normalized = item.normalized()
    existed_before = normalized.path.exists()

    try:
        if existed_before:
            if not normalized.path.is_dir():
                raise VplibSettingsError(f"Path exists but is not a directory: {normalized.path}")

            return VplibDirectoryEnsureResult(
                role=normalized.role,
                path=normalized.path,
                status=VplibDirectoryEnsureStatus.EXISTS.value,
                existed_before=True,
            ).normalized()

        if dry_run:
            return VplibDirectoryEnsureResult(
                role=normalized.role,
                path=normalized.path,
                status=VplibDirectoryEnsureStatus.DRY_RUN.value,
                existed_before=False,
            ).normalized()

        normalized.path.mkdir(parents=True, exist_ok=True)

        return VplibDirectoryEnsureResult(
            role=normalized.role,
            path=normalized.path,
            status=VplibDirectoryEnsureStatus.CREATED.value,
            existed_before=False,
        ).normalized()
    except Exception as exc:
        if strict and normalized.required:
            raise VplibSettingsError(f"Could not ensure directory {normalized.role}: {exc}") from exc

        return VplibDirectoryEnsureResult(
            role=normalized.role,
            path=normalized.path,
            status=VplibDirectoryEnsureStatus.FAILED.value,
            existed_before=existed_before,
            error=str(exc),
        ).normalized()


@lru_cache(maxsize=1)
def get_default_src_root() -> Path:
    """Leitet src-root aus dieser Datei ab."""
    try:
        return Path(__file__).resolve().parents[1]
    except Exception:
        return Path.cwd()


@lru_cache(maxsize=1)
def get_default_service_root() -> Path:
    """Leitet Microservice-Root aus dieser Datei ab."""
    try:
        return Path(__file__).resolve().parents[2]
    except Exception:
        return Path.cwd()


def get_env_string(env: Mapping[str, str], name: str, *, default: str | None = None) -> str:
    """Liest String aus Environment."""
    value = clean_optional_string(env.get(name))

    if value is not None:
        return value

    if default is not None:
        return default

    raise VplibSettingsError(f"Missing required environment variable {name!r}.")


def get_env_path(env: Mapping[str, str], name: str) -> Path | None:
    """Liest optionalen Pfad aus Environment."""
    value = clean_optional_string(env.get(name))

    if value is None:
        return None

    return Path(value).expanduser()


def get_env_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    """Liest Boolean aus Environment."""
    value = clean_optional_string(env.get(name))

    if value is None:
        return bool(default)

    return parse_bool_value(value)


def normalize_env_mapping(env: Mapping[str, Any]) -> dict[str, str]:
    """Normalisiert Environment-Mapping auf str -> str."""
    if not isinstance(env, Mapping):
        raise VplibSettingsError("env must be a mapping.")

    result: dict[str, str] = {}

    for key, value in env.items():
        if value is None:
            continue
        result[str(key)] = str(value)

    return result


def normalize_path(value: Any, field_name: str, *, base_dir: Path | None = None) -> Path:
    """Normalisiert Pfade robust, ohne Existenz zu erzwingen."""
    try:
        if value is None:
            raise VplibSettingsError(f"{field_name} is required.")

        path = Path(value).expanduser()

        if not path.is_absolute() and base_dir is not None:
            path = Path(base_dir).expanduser() / path

        return path
    except VplibSettingsError:
        raise
    except Exception as exc:
        raise VplibSettingsError(f"Invalid path for {field_name}: {value!r}.") from exc


def normalize_route_prefix(value: Any) -> str:
    """Normalisiert Flask-Route-Prefix."""
    raw = clean_required_string(value, "route_prefix").strip()

    if not raw.startswith("/"):
        raw = f"/{raw}"

    raw = raw.rstrip("/")

    if not raw:
        return DEFAULT_ROUTE_PREFIX

    if " " in raw:
        raise VplibSettingsError(f"route_prefix must not contain spaces: {value!r}")

    return raw


@lru_cache(maxsize=128)
def parse_runtime_mode_value(value: Any) -> str:
    """Parst Runtime-Modus."""
    try:
        if isinstance(value, VplibRuntimeMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "dev": VplibRuntimeMode.DEVELOPMENT.value,
            "development": VplibRuntimeMode.DEVELOPMENT.value,
            "test": VplibRuntimeMode.TESTING.value,
            "testing": VplibRuntimeMode.TESTING.value,
            "prod": VplibRuntimeMode.PRODUCTION.value,
            "production": VplibRuntimeMode.PRODUCTION.value,
        }

        if raw in aliases:
            return aliases[raw]

        return VplibRuntimeMode(raw).value
    except Exception as exc:
        raise VplibSettingsError(f"Invalid runtime mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_write_mode_value(value: Any) -> str:
    """Parst Default-Schreibmodus."""
    try:
        if isinstance(value, VplibWriteMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "fail": VplibWriteMode.FAIL.value,
            "error": VplibWriteMode.FAIL.value,
            "strict": VplibWriteMode.FAIL.value,
            "skip": VplibWriteMode.SKIP.value,
            "ignore": VplibWriteMode.SKIP.value,
            "overwrite": VplibWriteMode.OVERWRITE.value,
            "replace": VplibWriteMode.OVERWRITE.value,
            "update": VplibWriteMode.OVERWRITE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return VplibWriteMode(raw).value
    except Exception as exc:
        raise VplibSettingsError(f"Invalid write mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_validation_mode_value(value: Any) -> str:
    """Parst Default-Validierungsmodus."""
    try:
        if isinstance(value, VplibValidationMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "strict": VplibValidationMode.STRICT.value,
            "normal": VplibValidationMode.NORMAL.value,
            "default": VplibValidationMode.NORMAL.value,
            "permissive": VplibValidationMode.PERMISSIVE.value,
            "loose": VplibValidationMode.PERMISSIVE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return VplibValidationMode(raw).value
    except Exception as exc:
        raise VplibSettingsError(f"Invalid validation mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_directory_role_value(value: Any) -> str:
    """Parst Directory-Rolle."""
    try:
        if isinstance(value, VplibDirectoryRole):
            return value.value

        raw = normalize_enum_key(value)
        return VplibDirectoryRole(raw).value
    except Exception as exc:
        raise VplibSettingsError(f"Invalid directory role {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_directory_ensure_status_value(value: Any) -> str:
    """Parst Directory-Ensure-Status."""
    try:
        if isinstance(value, VplibDirectoryEnsureStatus):
            return value.value

        raw = normalize_enum_key(value)
        return VplibDirectoryEnsureStatus(raw).value
    except Exception as exc:
        raise VplibSettingsError(f"Invalid directory ensure status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_bool_value(value: Any) -> bool:
    """Parst boolesche Werte robust."""
    raw = normalize_enum_key(value)

    if raw in TRUE_VALUES:
        return True

    if raw in FALSE_VALUES:
        return False

    raise VplibSettingsError(f"Invalid boolean value {value!r}.")


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise VplibSettingsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except VplibSettingsError:
        raise
    except Exception as exc:
        raise VplibSettingsError(f"Invalid enum value {value!r}.") from exc


def normalize_non_negative_int(value: Any, field_name: str) -> int:
    """Normalisiert nicht-negative Integer."""
    try:
        if isinstance(value, bool):
            raise VplibSettingsError(f"{field_name} must be an integer.")

        number = int(value)

        if number < 0:
            raise VplibSettingsError(f"{field_name} must be >= 0.")

        return number
    except VplibSettingsError:
        raise
    except Exception as exc:
        raise VplibSettingsError(f"{field_name} must be a non-negative integer.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise VplibSettingsError("metadata must be a mapping.")

    return {
        str(key): normalize_metadata_value(child_value)
        for key, child_value in value.items()
    }


def normalize_metadata_value(value: Any) -> Any:
    """Normalisiert Metadata-Werte JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    return str(value)


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise VplibSettingsError(f"{field_name} is required.")

        return cleaned
    except VplibSettingsError:
        raise
    except Exception as exc:
        raise VplibSettingsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_vplib_settings_cache() -> None:
    """Leert alle Settings-Caches."""
    get_vplib_settings.cache_clear()
    get_default_src_root.cache_clear()
    get_default_service_root.cache_clear()
    parse_runtime_mode_value.cache_clear()
    parse_write_mode_value.cache_clear()
    parse_validation_mode_value.cache_clear()
    parse_directory_role_value.cache_clear()
    parse_directory_ensure_status_value.cache_clear()
    parse_bool_value.cache_clear()


__all__ = [
    "DEFAULT_ARCHIVE_DIR_NAME",
    "DEFAULT_DRY_RUN_DEFAULT",
    "DEFAULT_GENERATED_DIR_NAME",
    "DEFAULT_LIBRARY_CATALOG_DIR_NAME",
    "DEFAULT_PACKAGE_DIR_PATTERN",
    "DEFAULT_ROUTE_PREFIX",
    "DEFAULT_SELF_TEST_PACKAGE_DIR_NAME",
    "DEFAULT_SERVICE_NAME",
    "DEFAULT_SOURCE_DIR_NAME",
    "DEFAULT_TEST_OUTPUT_DIR_NAME",
    "DEFAULT_VALIDATION_MODE",
    "DEFAULT_VPLIB_GENERATED_DIR_NAME",
    "DEFAULT_WRITE_MODE",
    "ENV_ALLOW_EXTERNAL_ASSET_URI",
    "ENV_ARCHIVE_ROOT",
    "ENV_CREATE_ARCHIVE_DEFAULT",
    "ENV_CREATE_ROUTE_ENABLED",
    "ENV_DEFAULT_VALIDATION_MODE",
    "ENV_DEFAULT_WRITE_MODE",
    "ENV_DRY_RUN_DEFAULT",
    "ENV_GENERATED_ROOT",
    "ENV_LIBRARY_CATALOG_ROOT",
    "ENV_PACKAGE_DIR_PATTERN",
    "ENV_PREFIX",
    "ENV_ROUTE_PREFIX",
    "ENV_RUNTIME_MODE",
    "ENV_SERVICE_NAME",
    "ENV_SERVICE_ROOT",
    "ENV_SOURCE_ROOT",
    "ENV_SRC_ROOT",
    "ENV_STRICT_ROUTES",
    "ENV_TEST_OUTPUT_ROOT",
    "ENV_TEST_ROUTE_ENABLED",
    "FALSE_VALUES",
    "TRUE_VALUES",
    "VPLIB_SETTINGS_SCHEMA_VERSION",
    "VplibDirectoryEnsureBatchResult",
    "VplibDirectoryEnsureResult",
    "VplibDirectoryEnsureStatus",
    "VplibDirectoryPlanItem",
    "VplibDirectoryRole",
    "VplibRuntimeMode",
    "VplibSettings",
    "VplibSettingsError",
    "VplibValidationMode",
    "VplibWriteMode",
    "build_vplib_settings_from_env",
    "clean_optional_string",
    "clean_required_string",
    "clear_vplib_settings_cache",
    "ensure_directory_item",
    "ensure_vplib_runtime_directories",
    "get_default_service_root",
    "get_default_src_root",
    "get_env_bool",
    "get_env_path",
    "get_env_string",
    "get_vplib_settings",
    "get_vplib_settings_health",
    "normalize_enum_key",
    "normalize_env_mapping",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_non_negative_int",
    "normalize_path",
    "normalize_route_prefix",
    "parse_bool_value",
    "parse_directory_ensure_status_value",
    "parse_directory_role_value",
    "parse_runtime_mode_value",
    "parse_validation_mode_value",
    "parse_write_mode_value",
    "reload_vplib_settings",
]