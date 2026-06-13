# services/vectoplan-library/src/vplib/defaults/module_defaults.py
"""
Module defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    vplib.modules.json

Die modules-Datei beschreibt, welche VPLIB-Module in einem Package aktiv,
erforderlich, optional, empfohlen oder ausgeschlossen sind.

Typische Inhalte:
- schema_version
- profile_key
- object_kind
- active_modules
- required_modules
- recommended_modules
- optional_modules
- excluded_modules
- module_versions
- module_documents
- module_directories
- validation_mode
- metadata

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


MODULE_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.module_defaults.v1"
MODULE_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.modules.v1"
DEFAULT_MODULE_VERSION: Final[str] = "1.0.0"
DEFAULT_VALIDATION_MODE: Final[str] = "strict"


class ModuleDefaultsError(ValueError):
    """Wird ausgelöst, wenn Module-Defaults ungültig erzeugt werden."""


class ModuleSetKind(str, Enum):
    """Art einer Modulgruppe."""

    ACTIVE = "active"
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"
    EXCLUDED = "excluded"

    @property
    def key(self) -> str:
        return str(self.value)


class ModuleValidationMode(str, Enum):
    """Validierungsmodus für das Modulmanifest."""

    STRICT = "strict"
    NORMAL = "normal"
    PERMISSIVE = "permissive"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ModuleDocumentDefaults:
    """Dokument-Defaults eines einzelnen Moduls."""

    module_name: str
    required_files: tuple[str, ...] = field(default_factory=tuple)
    optional_files: tuple[str, ...] = field(default_factory=tuple)
    generated_files: tuple[str, ...] = field(default_factory=tuple)
    directories: tuple[str, ...] = field(default_factory=tuple)
    allowed_subdirectories: tuple[str, ...] = field(default_factory=tuple)

    def normalized(self) -> "ModuleDocumentDefaults":
        module_name = normalize_module_name(self.module_name)

        return ModuleDocumentDefaults(
            module_name=module_name,
            required_files=normalize_package_path_tuple(self.required_files),
            optional_files=normalize_package_path_tuple(self.optional_files),
            generated_files=normalize_package_path_tuple(self.generated_files),
            directories=normalize_package_path_tuple(self.directories),
            allowed_subdirectories=normalize_package_path_tuple(self.allowed_subdirectories),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "module_name": normalized.module_name,
            "required_files": list(normalized.required_files),
            "optional_files": list(normalized.optional_files),
            "generated_files": list(normalized.generated_files),
            "directories": list(normalized.directories),
            "allowed_subdirectories": list(normalized.allowed_subdirectories),
        }


@dataclass(frozen=True, slots=True)
class ModuleVersionDefaults:
    """Versionseintrag eines einzelnen Moduls."""

    module_name: str
    version: str = DEFAULT_MODULE_VERSION

    def normalized(self) -> "ModuleVersionDefaults":
        return ModuleVersionDefaults(
            module_name=normalize_module_name(self.module_name),
            version=clean_required_string(self.version or DEFAULT_MODULE_VERSION, "version"),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "module_name": normalized.module_name,
            "version": normalized.version,
        }


@dataclass(frozen=True, slots=True)
class ModuleDefaults:
    """
    Vollständige Defaults für vplib.modules.json.

    Diese Struktur ist die interne Quelle für documents/modules_document.py.
    """

    object_kind: str
    profile_key: str | None = None
    active_modules: tuple[str, ...] = field(default_factory=tuple)
    required_modules: tuple[str, ...] = field(default_factory=tuple)
    recommended_modules: tuple[str, ...] = field(default_factory=tuple)
    optional_modules: tuple[str, ...] = field(default_factory=tuple)
    excluded_modules: tuple[str, ...] = field(default_factory=tuple)
    module_versions: tuple[ModuleVersionDefaults, ...] = field(default_factory=tuple)
    module_documents: tuple[ModuleDocumentDefaults, ...] = field(default_factory=tuple)
    validation_mode: str = DEFAULT_VALIDATION_MODE
    schema_version: str = MODULE_DOCUMENT_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ModuleDefaults":
        object_kind = normalize_object_kind_value(self.object_kind)
        profile_key = clean_optional_string(self.profile_key)
        active_modules = normalize_module_tuple(self.active_modules)
        required_modules = normalize_module_tuple(self.required_modules)
        recommended_modules = normalize_module_tuple(self.recommended_modules)
        optional_modules = normalize_module_tuple(self.optional_modules)
        excluded_modules = normalize_module_tuple(self.excluded_modules)
        validation_mode = parse_validation_mode_value(self.validation_mode)
        schema_version = clean_required_string(self.schema_version or MODULE_DOCUMENT_SCHEMA_VERSION, "schema_version")
        metadata = normalize_metadata(self.metadata)

        required_modules = merge_module_tuples(get_core_modules_safe(), required_modules)
        active_modules = merge_module_tuples(active_modules, required_modules, recommended_modules)

        if excluded_modules:
            active_modules = tuple(module for module in active_modules if module not in set(excluded_modules))
            recommended_modules = tuple(module for module in recommended_modules if module not in set(excluded_modules))
            optional_modules = tuple(module for module in optional_modules if module not in set(excluded_modules))

        optional_modules = tuple(
            module
            for module in optional_modules
            if module not in set(active_modules)
            and module not in set(required_modules)
            and module not in set(recommended_modules)
            and module not in set(excluded_modules)
        )

        module_versions = normalize_module_versions(
            self.module_versions,
            active_modules=active_modules,
            required_modules=required_modules,
            recommended_modules=recommended_modules,
            optional_modules=optional_modules,
        )
        module_documents = normalize_module_documents(
            self.module_documents,
            modules=merge_module_tuples(
                active_modules,
                required_modules,
                recommended_modules,
                optional_modules,
            ),
        )

        defaults = ModuleDefaults(
            object_kind=object_kind,
            profile_key=profile_key,
            active_modules=active_modules,
            required_modules=required_modules,
            recommended_modules=recommended_modules,
            optional_modules=optional_modules,
            excluded_modules=excluded_modules,
            module_versions=module_versions,
            module_documents=module_documents,
            validation_mode=validation_mode,
            schema_version=schema_version,
            metadata=metadata,
        )

        valid, messages = validate_module_defaults(defaults)
        if not valid:
            raise ModuleDefaultsError(" ".join(messages))

        return defaults

    def to_document(self) -> dict[str, Any]:
        """Erzeugt den JSON-kompatiblen Inhalt für vplib.modules.json."""
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "object_kind": normalized.object_kind,
            "profile_key": normalized.profile_key,
            "validation_mode": normalized.validation_mode,
            "active_modules": list(normalized.active_modules),
            "required_modules": list(normalized.required_modules),
            "recommended_modules": list(normalized.recommended_modules),
            "optional_modules": list(normalized.optional_modules),
            "excluded_modules": list(normalized.excluded_modules),
            "module_versions": {
                item.module_name: item.version
                for item in normalized.module_versions
            },
            "module_documents": {
                item.module_name: {
                    "required_files": list(item.required_files),
                    "optional_files": list(item.optional_files),
                    "generated_files": list(item.generated_files),
                    "directories": list(item.directories),
                    "allowed_subdirectories": list(item.allowed_subdirectories),
                }
                for item in normalized.module_documents
            },
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        """Alias für to_document()."""
        return self.to_document()


def build_module_defaults(
    *,
    object_kind: str,
    profile_key: str | None = None,
    active_modules: Iterable[Any] = (),
    required_modules: Iterable[Any] = (),
    recommended_modules: Iterable[Any] = (),
    optional_modules: Iterable[Any] = (),
    excluded_modules: Iterable[Any] = (),
    validation_mode: str = DEFAULT_VALIDATION_MODE,
    metadata: Mapping[str, Any] | None = None,
) -> ModuleDefaults:
    """Baut ModuleDefaults aus expliziten Werten."""
    try:
        return ModuleDefaults(
            object_kind=object_kind,
            profile_key=profile_key,
            active_modules=tuple(active_modules or ()),
            required_modules=tuple(required_modules or ()),
            recommended_modules=tuple(recommended_modules or ()),
            optional_modules=tuple(optional_modules or ()),
            excluded_modules=tuple(excluded_modules or ()),
            validation_mode=validation_mode,
            metadata=dict(metadata or {}),
        ).normalized()
    except ModuleDefaultsError:
        raise
    except Exception as exc:
        raise ModuleDefaultsError(f"Could not build module defaults: {exc}") from exc


def build_modules_document(**kwargs: Any) -> dict[str, Any]:
    """Baut direkt den JSON-kompatiblen Modules-Payload."""
    return build_module_defaults(**kwargs).to_document()


def module_defaults_from_module_plan(
    module_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ModuleDefaults:
    """Baut ModuleDefaults aus einem ModulePlan-ähnlichen Objekt."""
    try:
        normalized_plan = module_plan.normalized() if hasattr(module_plan, "normalized") else module_plan

        documents = []
        for entry in normalized_plan.active_entries:
            documents.append(
                ModuleDocumentDefaults(
                    module_name=entry.module_name,
                    required_files=entry.required_files,
                    optional_files=entry.optional_files,
                    generated_files=entry.generated_files,
                    directories=entry.directories,
                    allowed_subdirectories=entry.allowed_subdirectories,
                ).normalized()
            )

        return ModuleDefaults(
            object_kind=normalized_plan.object_kind,
            profile_key=normalized_plan.profile_key,
            active_modules=tuple(normalized_plan.active_module_names),
            required_modules=tuple(normalized_plan.required_module_names),
            recommended_modules=tuple(normalized_plan.recommended_module_names),
            optional_modules=tuple(normalized_plan.optional_module_names),
            excluded_modules=tuple(normalized_plan.excluded_module_names),
            module_documents=tuple(documents),
            validation_mode=DEFAULT_VALIDATION_MODE,
            metadata={
                "source": "module_plan",
                **dict(metadata or {}),
            },
        ).normalized()
    except ModuleDefaultsError:
        raise
    except Exception as exc:
        raise ModuleDefaultsError(f"Could not build module defaults from ModulePlan: {exc}") from exc


def module_defaults_from_profile(
    profile: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ModuleDefaults:
    """Baut ModuleDefaults aus einem ObjectKindProfile-ähnlichen Objekt."""
    try:
        normalized_profile = profile.normalized() if hasattr(profile, "normalized") else profile

        documents_by_module: dict[str, ModuleDocumentDefaults] = {}

        for rule in normalized_profile.module_rules:
            documents_by_module[rule.module_name] = ModuleDocumentDefaults(
                module_name=rule.module_name,
                required_files=rule.required_files,
                optional_files=rule.optional_files,
                generated_files=rule.generated_files,
                allowed_subdirectories=rule.allowed_subdirectories,
            ).normalized()

        for rule in normalized_profile.document_rules:
            existing = documents_by_module.get(rule.module_name)

            if existing is None:
                existing = ModuleDocumentDefaults(module_name=rule.module_name).normalized()

            if rule.required:
                required_files = merge_path_tuples(existing.required_files, (rule.path,))
                optional_files = existing.optional_files
            else:
                required_files = existing.required_files
                optional_files = merge_path_tuples(existing.optional_files, (rule.path,))

            documents_by_module[rule.module_name] = ModuleDocumentDefaults(
                module_name=rule.module_name,
                required_files=required_files,
                optional_files=optional_files,
                generated_files=existing.generated_files,
                directories=existing.directories,
                allowed_subdirectories=existing.allowed_subdirectories,
            ).normalized()

        return ModuleDefaults(
            object_kind=normalized_profile.object_kind,
            profile_key=normalized_profile.profile_key,
            active_modules=tuple(normalized_profile.active_module_names),
            required_modules=tuple(normalized_profile.required_module_names),
            recommended_modules=tuple(normalized_profile.recommended_module_names),
            optional_modules=tuple(normalized_profile.optional_module_names),
            excluded_modules=tuple(normalized_profile.excluded_module_names),
            module_documents=tuple(documents_by_module.values()),
            validation_mode=normalized_profile.validation_mode,
            metadata={
                "source": "profile",
                **dict(metadata or {}),
            },
        ).normalized()
    except ModuleDefaultsError:
        raise
    except Exception as exc:
        raise ModuleDefaultsError(f"Could not build module defaults from profile: {exc}") from exc


def modules_document_from_module_plan(
    module_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut Modules-Dokument aus ModulePlan."""
    return module_defaults_from_module_plan(
        module_plan,
        metadata=metadata,
    ).to_document()


def modules_document_from_profile(
    profile: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut Modules-Dokument aus ObjectKindProfile."""
    return module_defaults_from_profile(
        profile,
        metadata=metadata,
    ).to_document()


def validate_module_defaults(defaults: ModuleDefaults) -> tuple[bool, tuple[str, ...]]:
    """Validiert ModuleDefaults grob."""
    messages: list[str] = []

    try:
        active = set(defaults.active_modules)
        required = set(defaults.required_modules)
        recommended = set(defaults.recommended_modules)
        optional = set(defaults.optional_modules)
        excluded = set(defaults.excluded_modules)

        for module_name in required:
            if module_name not in active:
                messages.append(f"Required module {module_name!r} must be active.")

        for module_name in recommended:
            if module_name in excluded:
                messages.append(f"Recommended module {module_name!r} cannot be excluded.")

        for module_name in required:
            if module_name in excluded:
                messages.append(f"Required module {module_name!r} cannot be excluded.")

        for module_name in get_core_modules_safe():
            if module_name not in required:
                messages.append(f"Core module {module_name!r} must be required.")

        known_modules = active | required | recommended | optional | excluded
        document_modules = {item.module_name for item in defaults.module_documents}
        missing_documents = active - document_modules

        for module_name in sorted(missing_documents):
            messages.append(f"Active module {module_name!r} has no module document defaults.")

        dependency_valid, dependency_messages = validate_module_dependencies_safe(active)
        if not dependency_valid:
            messages.extend(dependency_messages)

    except Exception as exc:
        messages.append(f"Could not validate module defaults: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_module_defaults(defaults: ModuleDefaults) -> None:
    """Wirft ModuleDefaultsError, wenn ModuleDefaults ungültig sind."""
    valid, messages = validate_module_defaults(defaults.normalized())

    if not valid:
        joined = " ".join(messages) if messages else "Invalid module defaults."
        raise ModuleDefaultsError(joined)


def validate_modules_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob die Modules-Payload-Struktur."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("Modules document must be a mapping.",)

        required_fields = (
            "schema_version",
            "object_kind",
            "active_modules",
            "required_modules",
            "optional_modules",
            "module_versions",
            "module_documents",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing modules field {field_name!r}.")

        if "object_kind" in document:
            try:
                normalize_object_kind_value(document["object_kind"])
            except Exception as exc:
                messages.append(str(exc))

        for key in ("active_modules", "required_modules", "recommended_modules", "optional_modules", "excluded_modules"):
            if key in document:
                try:
                    normalize_module_tuple(document.get(key, ()))
                except Exception as exc:
                    messages.append(f"Invalid {key}: {exc}")

    except Exception as exc:
        messages.append(f"Could not validate modules document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_modules_document(document: Mapping[str, Any]) -> None:
    """Wirft ModuleDefaultsError, wenn ein Modules-Dokument ungültig ist."""
    valid, messages = validate_modules_document(document)

    if not valid:
        joined = " ".join(messages) if messages else "Invalid modules document."
        raise ModuleDefaultsError(joined)


def normalize_module_versions(
    values: Iterable[ModuleVersionDefaults],
    *,
    active_modules: Iterable[str],
    required_modules: Iterable[str],
    recommended_modules: Iterable[str],
    optional_modules: Iterable[str],
) -> tuple[ModuleVersionDefaults, ...]:
    """Normalisiert Modulversionen und ergänzt fehlende Module."""
    versions_by_module: dict[str, ModuleVersionDefaults] = {}

    for value in values or ():
        version = value.normalized()
        versions_by_module[version.module_name] = version

    for module_name in merge_module_tuples(active_modules, required_modules, recommended_modules, optional_modules):
        if module_name not in versions_by_module:
            versions_by_module[module_name] = ModuleVersionDefaults(
                module_name=module_name,
                version=DEFAULT_MODULE_VERSION,
            ).normalized()

    return tuple(
        versions_by_module[module_name]
        for module_name in sort_modules_safe(versions_by_module.keys())
    )


def normalize_module_documents(
    values: Iterable[ModuleDocumentDefaults],
    *,
    modules: Iterable[str],
) -> tuple[ModuleDocumentDefaults, ...]:
    """Normalisiert Moduldokumente und ergänzt fehlende Module."""
    documents_by_module: dict[str, ModuleDocumentDefaults] = {}

    for value in values or ():
        document_defaults = value.normalized()
        documents_by_module[document_defaults.module_name] = document_defaults

    for module_name in normalize_module_tuple(modules):
        if module_name not in documents_by_module:
            documents_by_module[module_name] = module_document_defaults_for_module(module_name)

    return tuple(
        documents_by_module[module_name]
        for module_name in sort_modules_safe(documents_by_module.keys())
    )


def module_document_defaults_for_module(module_name: Any) -> ModuleDocumentDefaults:
    """Baut ModuleDocumentDefaults für ein einzelnes Modul aus package_paths."""
    module_value = normalize_module_name(module_name)

    return ModuleDocumentDefaults(
        module_name=module_value,
        required_files=get_required_files_for_module_safe(module_value),
        optional_files=get_optional_files_for_module_safe(module_value),
        generated_files=get_generated_files_for_module_safe(module_value),
        directories=tuple(filter(None, (get_module_directory_safe(module_value),))),
        allowed_subdirectories=get_allowed_subdirectories_for_module_safe(module_value),
    ).normalized()


def normalize_module_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Modulnamen ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        module_name = normalize_module_name(value)

        if module_name in seen:
            continue

        result.append(module_name)
        seen.add(module_name)

    return sort_modules_safe(result)


def merge_module_tuples(*groups: Iterable[Any]) -> tuple[str, ...]:
    """Merged mehrere Modulgruppen stabil ohne Duplikate."""
    merged: list[str] = []
    seen: set[str] = set()

    for group in groups:
        for value in group or ():
            module_name = normalize_module_name(value)

            if module_name in seen:
                continue

            merged.append(module_name)
            seen.add(module_name)

    return sort_modules_safe(merged)


def merge_path_tuples(*groups: Iterable[Any]) -> tuple[str, ...]:
    """Merged mehrere Pfadgruppen stabil ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for group in groups:
        for value in group or ():
            path = normalize_package_path(value)

            if path in seen:
                continue

            result.append(path)
            seen.add(path)

    return tuple(result)


def normalize_module_name(value: Any) -> str:
    """Normalisiert Modulnamen."""
    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception as exc:
        raise ModuleDefaultsError(f"Invalid module name {value!r}: {exc}") from exc


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert object_kind."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise ModuleDefaultsError(f"Invalid object_kind {value!r}: {exc}") from exc


def normalize_package_path(value: Any) -> str:
    """Normalisiert package-relative Pfade."""
    try:
        from ..domain.package_paths import normalize_package_path as normalize

        return normalize(value)
    except Exception as exc:
        raise ModuleDefaultsError(f"Invalid package path {value!r}: {exc}") from exc


def get_core_modules_safe() -> tuple[str, ...]:
    """Liest Core-Module robust."""
    try:
        from ..domain.module_names import get_core_module_names

        return tuple(module.value for module in get_core_module_names())
    except Exception:
        return (
            "manifest",
            "modules",
            "family",
            "variants",
            "editor",
            "manufacturer",
        )


def sort_modules_safe(values: Iterable[Any]) -> tuple[str, ...]:
    """Sortiert Module in kanonischer Reihenfolge."""
    try:
        from ..domain.module_names import sort_module_names

        return tuple(module.value for module in sort_module_names(values))
    except Exception:
        order = {
            "manifest": 10,
            "modules": 20,
            "family": 30,
            "variants": 40,
            "editor": 50,
            "render": 60,
            "physical": 70,
            "material": 80,
            "calculation": 90,
            "analysis": 100,
            "dynamic": 110,
            "manufacturer": 120,
            "docs": 130,
            "tests": 140,
        }
        normalized = [normalize_module_name(value) for value in values or ()]
        return tuple(sorted(normalized, key=lambda value: order.get(value, 999)))


def validate_module_dependencies_safe(values: Iterable[Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert Modulabhängigkeiten robust."""
    try:
        from ..domain.module_names import validate_module_dependencies

        return validate_module_dependencies(values)
    except Exception:
        return True, tuple()


def get_required_files_for_module_safe(module_name: Any) -> tuple[str, ...]:
    """Liest Pflichtdateien eines Moduls."""
    try:
        from ..domain.package_paths import get_required_files_for_module

        return tuple(get_required_files_for_module(module_name))
    except Exception:
        return tuple()


def get_optional_files_for_module_safe(module_name: Any) -> tuple[str, ...]:
    """Liest optionale Dateien eines Moduls."""
    try:
        from ..domain.package_paths import get_optional_files_for_module

        return tuple(get_optional_files_for_module(module_name))
    except Exception:
        return tuple()


def get_generated_files_for_module_safe(module_name: Any) -> tuple[str, ...]:
    """Liest generierte Dateien eines Moduls."""
    try:
        from ..domain.package_paths import get_generated_files_for_module

        return tuple(get_generated_files_for_module(module_name))
    except Exception:
        return tuple()


def get_module_directory_safe(module_name: Any) -> str | None:
    """Liest Modulordner."""
    try:
        from ..domain.package_paths import get_module_directory

        return get_module_directory(module_name)
    except Exception:
        return None


def get_allowed_subdirectories_for_module_safe(module_name: Any) -> tuple[str, ...]:
    """Liest erlaubte Unterordner eines Moduls."""
    try:
        from ..domain.package_paths import get_allowed_subdirectories_for_module

        return tuple(get_allowed_subdirectories_for_module(module_name))
    except Exception:
        return tuple()


@lru_cache(maxsize=128)
def parse_validation_mode_value(value: Any) -> str:
    """Parst ModuleValidationMode."""
    try:
        if isinstance(value, ModuleValidationMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "strict": ModuleValidationMode.STRICT.value,
            "normal": ModuleValidationMode.NORMAL.value,
            "default": ModuleValidationMode.NORMAL.value,
            "permissive": ModuleValidationMode.PERMISSIVE.value,
            "loose": ModuleValidationMode.PERMISSIVE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ModuleValidationMode(raw).value
    except Exception as exc:
        raise ModuleDefaultsError(f"Invalid module validation mode {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise ModuleDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except ModuleDefaultsError:
        raise
    except Exception as exc:
        raise ModuleDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise ModuleDefaultsError("metadata must be a mapping.")

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

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    return str(value)


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise ModuleDefaultsError(f"{field_name} is required.")

        return cleaned
    except ModuleDefaultsError:
        raise
    except Exception as exc:
        raise ModuleDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_module_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_validation_mode_value.cache_clear()


__all__ = [
    "DEFAULT_MODULE_VERSION",
    "DEFAULT_VALIDATION_MODE",
    "MODULE_DEFAULTS_SCHEMA_VERSION",
    "MODULE_DOCUMENT_SCHEMA_VERSION",
    "ModuleDefaults",
    "ModuleDefaultsError",
    "ModuleDocumentDefaults",
    "ModuleSetKind",
    "ModuleValidationMode",
    "ModuleVersionDefaults",
    "assert_valid_module_defaults",
    "assert_valid_modules_document",
    "build_module_defaults",
    "build_modules_document",
    "clean_optional_string",
    "clean_required_string",
    "clear_module_defaults_caches",
    "get_allowed_subdirectories_for_module_safe",
    "get_core_modules_safe",
    "get_generated_files_for_module_safe",
    "get_module_directory_safe",
    "get_optional_files_for_module_safe",
    "get_required_files_for_module_safe",
    "merge_module_tuples",
    "merge_path_tuples",
    "module_defaults_from_module_plan",
    "module_defaults_from_profile",
    "module_document_defaults_for_module",
    "modules_document_from_module_plan",
    "modules_document_from_profile",
    "normalize_enum_key",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_module_documents",
    "normalize_module_name",
    "normalize_module_tuple",
    "normalize_module_versions",
    "normalize_object_kind_value",
    "normalize_package_path",
    "parse_validation_mode_value",
    "sort_modules_safe",
    "validate_module_defaults",
    "validate_module_dependencies_safe",
    "validate_modules_document",
]