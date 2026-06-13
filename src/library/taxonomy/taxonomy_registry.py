# services/vectoplan-library/src/library/taxonomy/taxonomy_registry.py
"""
VECTOPLAN Library Taxonomy Registry.

This module is responsible for loading the canonical taxonomy data file and
turning it into a TaxonomyRegistryModel.

It is intentionally framework-free:
- no Flask imports
- no route imports
- no scanner imports
- no create-service imports

Responsibilities:
- resolve the taxonomy JSON file path
- load JSON safely
- parse it through taxonomy_models.py
- cache the parsed registry
- detect file changes via fingerprint
- allow explicit reloads
- expose robust diagnostics for health/options routes

Default data file:
services/vectoplan-library/src/library/taxonomy/data/taxonomy.v1.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Mapping, Optional, Tuple, Union

try:
    from .taxonomy_models import (
        DEFAULT_SCHEMA_VERSION,
        DEFAULT_TAXONOMY_VERSION,
        TaxonomyIssue,
        TaxonomyRegistryModel,
        TaxonomyValidationResult,
        make_json_safe,
        safe_bool,
        safe_str,
    )
except ImportError:  # pragma: no cover - defensive fallback for direct script execution
    from taxonomy_models import (  # type: ignore
        DEFAULT_SCHEMA_VERSION,
        DEFAULT_TAXONOMY_VERSION,
        TaxonomyIssue,
        TaxonomyRegistryModel,
        TaxonomyValidationResult,
        make_json_safe,
        safe_bool,
        safe_str,
    )


PathLike = Union[str, os.PathLike[str], Path]

LOGGER = logging.getLogger(__name__)

DEFAULT_TAXONOMY_FILENAME = "taxonomy.v1.json"
DEFAULT_TAXONOMY_DATA_DIRNAME = "data"

ENV_TAXONOMY_FILE_KEYS: Tuple[str, ...] = (
    "VECTOPLAN_TAXONOMY_FILE",
    "VPLIB_TAXONOMY_FILE",
)

ENV_TAXONOMY_STRICT_KEYS: Tuple[str, ...] = (
    "VECTOPLAN_TAXONOMY_STRICT",
    "VPLIB_TAXONOMY_STRICT",
)

ENV_TAXONOMY_HASH_KEYS: Tuple[str, ...] = (
    "VECTOPLAN_TAXONOMY_HASH",
    "VPLIB_TAXONOMY_HASH",
)


class TaxonomyRegistryError(RuntimeError):
    """Base error for taxonomy registry operations."""


class TaxonomyRegistryPathError(TaxonomyRegistryError):
    """Raised when the taxonomy data file path cannot be resolved."""


class TaxonomyRegistryLoadError(TaxonomyRegistryError):
    """Raised when the taxonomy registry cannot be loaded."""


@dataclass(frozen=True)
class TaxonomyFileFingerprint:
    """
    Stable fingerprint of a taxonomy file.

    mtime/size are cheap and good enough for cache invalidation in development.
    sha256 adds extra safety and can be disabled if needed.
    """

    path: str
    exists: bool
    is_file: bool
    size_bytes: int = 0
    mtime_ns: int = 0
    sha256: str = ""
    error: str = ""

    @classmethod
    def from_path(
        cls,
        file_path: PathLike,
        *,
        compute_hash: bool = True,
    ) -> "TaxonomyFileFingerprint":
        path = normalize_path(file_path)

        try:
            exists = path.exists()
            is_file = path.is_file()

            if not exists:
                return cls(
                    path=str(path),
                    exists=False,
                    is_file=False,
                    error="file_not_found",
                )

            if not is_file:
                return cls(
                    path=str(path),
                    exists=True,
                    is_file=False,
                    error="path_is_not_file",
                )

            stat = path.stat()
            sha256 = compute_file_sha256(path) if compute_hash else ""

            return cls(
                path=str(path),
                exists=True,
                is_file=True,
                size_bytes=int(stat.st_size),
                mtime_ns=int(stat.st_mtime_ns),
                sha256=sha256,
                error="",
            )
        except Exception as exc:
            return cls(
                path=str(path),
                exists=False,
                is_file=False,
                error=f"fingerprint_failed: {exc}",
            )

    @property
    def cache_key(self) -> str:
        return f"{self.path}|{self.exists}|{self.is_file}|{self.size_bytes}|{self.mtime_ns}|{self.sha256}"

    @property
    def usable(self) -> bool:
        return self.exists and self.is_file and not self.error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "is_file": self.is_file,
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
            "sha256": self.sha256,
            "cache_key": self.cache_key,
            "usable": self.usable,
            "error": self.error,
        }


@dataclass(frozen=True)
class TaxonomyRegistryLoadResult:
    """Result object returned by TaxonomyRegistry.load_result()."""

    registry: Optional[TaxonomyRegistryModel]
    source_path: str
    fingerprint: TaxonomyFileFingerprint
    loaded_at: str
    from_cache: bool = False
    stale: bool = False
    strict: bool = True
    error: str = ""
    issues: TaxonomyValidationResult = field(default_factory=TaxonomyValidationResult.ok)

    @property
    def ok(self) -> bool:
        return self.registry is not None and not self.error and self.issues.valid

    @property
    def has_registry(self) -> bool:
        return self.registry is not None

    @property
    def taxonomy_version(self) -> str:
        if not self.registry:
            return ""
        return self.registry.taxonomy_version

    @property
    def schema_version(self) -> str:
        if not self.registry:
            return ""
        return self.registry.schema_version

    def require_registry(self) -> TaxonomyRegistryModel:
        if self.registry is None:
            raise TaxonomyRegistryLoadError(self.error or "Taxonomy registry is not loaded.")
        return self.registry

    def to_dict(self, *, include_registry: bool = False, include_tree: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": self.ok,
            "has_registry": self.has_registry,
            "from_cache": self.from_cache,
            "stale": self.stale,
            "strict": self.strict,
            "source_path": self.source_path,
            "loaded_at": self.loaded_at,
            "schema_version": self.schema_version,
            "taxonomy_version": self.taxonomy_version,
            "fingerprint": self.fingerprint.to_dict(),
            "error": self.error,
            "issues": self.issues.to_dict(),
        }

        if include_registry and self.registry:
            payload["registry"] = self.registry.to_dict()

        if include_tree and self.registry:
            payload["tree"] = self.registry.to_tree_dict(include_inactive=True)

        return make_json_safe(payload)


class TaxonomyRegistry:
    """
    File-backed taxonomy registry loader with robust cache behavior.

    Typical usage:

        registry_loader = TaxonomyRegistry()
        registry = registry_loader.load()

    The class caches the parsed TaxonomyRegistryModel. The cache is reused while
    the file fingerprint stays unchanged. A forced reload can be requested.
    """

    def __init__(
        self,
        file_path: Optional[PathLike] = None,
        *,
        strict: Optional[bool] = None,
        compute_hash: Optional[bool] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._configured_file_path = file_path
        self.strict = resolve_strict_default() if strict is None else bool(strict)
        self.compute_hash = resolve_hash_default() if compute_hash is None else bool(compute_hash)
        self.logger = logger or LOGGER

        self._lock = RLock()
        self._cached_result: Optional[TaxonomyRegistryLoadResult] = None
        self._cached_fingerprint: Optional[TaxonomyFileFingerprint] = None

    @property
    def configured_file_path(self) -> Optional[PathLike]:
        return self._configured_file_path

    def resolve_path(self) -> Path:
        return resolve_taxonomy_file_path(self._configured_file_path)

    def clear_cache(self) -> None:
        with self._lock:
            self._cached_result = None
            self._cached_fingerprint = None

    def has_cache(self) -> bool:
        with self._lock:
            return self._cached_result is not None and self._cached_result.registry is not None

    def get_cached_result(self) -> Optional[TaxonomyRegistryLoadResult]:
        with self._lock:
            return self._cached_result

    def get_cached_registry(self) -> Optional[TaxonomyRegistryModel]:
        with self._lock:
            if not self._cached_result:
                return None
            return self._cached_result.registry

    def load(
        self,
        *,
        force_reload: bool = False,
        allow_stale_on_error: bool = True,
    ) -> TaxonomyRegistryModel:
        result = self.load_result(
            force_reload=force_reload,
            allow_stale_on_error=allow_stale_on_error,
        )
        return result.require_registry()

    def load_result(
        self,
        *,
        force_reload: bool = False,
        allow_stale_on_error: bool = True,
    ) -> TaxonomyRegistryLoadResult:
        with self._lock:
            source_path = self.resolve_path()
            fingerprint = TaxonomyFileFingerprint.from_path(
                source_path,
                compute_hash=self.compute_hash,
            )

            if not force_reload and self._can_use_cache(fingerprint):
                assert self._cached_result is not None
                return replace(
                    self._cached_result,
                    from_cache=True,
                    stale=False,
                    loaded_at=utc_now_iso(),
                )

            try:
                registry = load_taxonomy_registry_model_from_file(source_path)
                result = TaxonomyRegistryLoadResult(
                    registry=registry,
                    source_path=str(source_path),
                    fingerprint=fingerprint,
                    loaded_at=utc_now_iso(),
                    from_cache=False,
                    stale=False,
                    strict=self.strict,
                    error="",
                    issues=TaxonomyValidationResult.ok(),
                )

                self._cached_result = result
                self._cached_fingerprint = fingerprint

                return result

            except Exception as exc:
                error_message = f"Taxonomy registry load failed: {exc}"
                self.logger.exception(error_message)

                stale_result = self._build_stale_result(
                    source_path=source_path,
                    fingerprint=fingerprint,
                    error_message=error_message,
                    allow_stale_on_error=allow_stale_on_error,
                )
                if stale_result:
                    return stale_result

                if self.strict:
                    raise TaxonomyRegistryLoadError(error_message) from exc

                result = self._build_non_strict_error_result(
                    source_path=source_path,
                    fingerprint=fingerprint,
                    error_message=error_message,
                )

                self._cached_result = result
                self._cached_fingerprint = fingerprint

                return result

    def reload(self, *, allow_stale_on_error: bool = False) -> TaxonomyRegistryModel:
        return self.load(
            force_reload=True,
            allow_stale_on_error=allow_stale_on_error,
        )

    def reload_result(self, *, allow_stale_on_error: bool = False) -> TaxonomyRegistryLoadResult:
        return self.load_result(
            force_reload=True,
            allow_stale_on_error=allow_stale_on_error,
        )

    def state(self) -> Dict[str, Any]:
        with self._lock:
            source_path = self.resolve_path()
            current_fingerprint = TaxonomyFileFingerprint.from_path(
                source_path,
                compute_hash=self.compute_hash,
            )

            cached_result = self._cached_result
            cached_fingerprint = self._cached_fingerprint

            return {
                "source_path": str(source_path),
                "strict": self.strict,
                "compute_hash": self.compute_hash,
                "has_cache": cached_result is not None and cached_result.registry is not None,
                "cache_valid": self._can_use_cache(current_fingerprint),
                "current_fingerprint": current_fingerprint.to_dict(),
                "cached_fingerprint": cached_fingerprint.to_dict() if cached_fingerprint else None,
                "cached_result": cached_result.to_dict(include_registry=False) if cached_result else None,
            }

    def _can_use_cache(self, fingerprint: TaxonomyFileFingerprint) -> bool:
        if self._cached_result is None or self._cached_fingerprint is None:
            return False
        if self._cached_result.registry is None:
            return False
        return self._cached_fingerprint.cache_key == fingerprint.cache_key

    def _build_stale_result(
        self,
        *,
        source_path: Path,
        fingerprint: TaxonomyFileFingerprint,
        error_message: str,
        allow_stale_on_error: bool,
    ) -> Optional[TaxonomyRegistryLoadResult]:
        if not allow_stale_on_error:
            return None
        if not self._cached_result or not self._cached_result.registry:
            return None

        issues = TaxonomyValidationResult.from_issues(
            (
                TaxonomyIssue.warning(
                    "taxonomy_registry_stale_cache_used",
                    "Taxonomy registry reload failed. Using stale cached registry.",
                    field="taxonomy_registry",
                    path=(str(source_path),),
                    details={"error": error_message},
                ),
            )
        )

        return TaxonomyRegistryLoadResult(
            registry=self._cached_result.registry,
            source_path=str(source_path),
            fingerprint=fingerprint,
            loaded_at=utc_now_iso(),
            from_cache=True,
            stale=True,
            strict=self.strict,
            error=error_message,
            issues=issues,
        )

    def _build_non_strict_error_result(
        self,
        *,
        source_path: Path,
        fingerprint: TaxonomyFileFingerprint,
        error_message: str,
    ) -> TaxonomyRegistryLoadResult:
        issues = TaxonomyValidationResult.from_issues(
            (
                TaxonomyIssue.error(
                    "taxonomy_registry_load_failed",
                    error_message,
                    field="taxonomy_registry",
                    path=(str(source_path),),
                ),
            )
        )

        fallback_registry = TaxonomyRegistryModel(
            schema_version=DEFAULT_SCHEMA_VERSION,
            taxonomy_version=DEFAULT_TAXONOMY_VERSION,
            label="VECTOPLAN Library Taxonomie",
            description="Fallback registry generated after taxonomy load failure.",
            domains=(),
            metadata={
                "fallback": True,
                "load_error": error_message,
                "source_path": str(source_path),
            },
        )

        return TaxonomyRegistryLoadResult(
            registry=fallback_registry,
            source_path=str(source_path),
            fingerprint=fingerprint,
            loaded_at=utc_now_iso(),
            from_cache=False,
            stale=False,
            strict=self.strict,
            error=error_message,
            issues=issues,
        )


_DEFAULT_REGISTRY_LOCK = RLock()
_DEFAULT_REGISTRY: Optional[TaxonomyRegistry] = None


def get_default_taxonomy_registry(
    *,
    file_path: Optional[PathLike] = None,
    strict: Optional[bool] = None,
    compute_hash: Optional[bool] = None,
    force_new: bool = False,
) -> TaxonomyRegistry:
    """
    Return the process-wide default taxonomy registry loader.

    If file_path is supplied, a separate configured default instance is created.
    force_new can be used by tests to reset the singleton.
    """

    global _DEFAULT_REGISTRY

    with _DEFAULT_REGISTRY_LOCK:
        if force_new or _DEFAULT_REGISTRY is None or file_path is not None:
            _DEFAULT_REGISTRY = TaxonomyRegistry(
                file_path=file_path,
                strict=strict,
                compute_hash=compute_hash,
            )

        return _DEFAULT_REGISTRY


def reset_default_taxonomy_registry() -> None:
    """Reset the module-level default registry singleton."""

    global _DEFAULT_REGISTRY

    with _DEFAULT_REGISTRY_LOCK:
        _DEFAULT_REGISTRY = None


def load_default_taxonomy_registry(
    *,
    force_reload: bool = False,
    allow_stale_on_error: bool = True,
) -> TaxonomyRegistryModel:
    """Load the default taxonomy registry model."""

    return get_default_taxonomy_registry().load(
        force_reload=force_reload,
        allow_stale_on_error=allow_stale_on_error,
    )


def load_default_taxonomy_result(
    *,
    force_reload: bool = False,
    allow_stale_on_error: bool = True,
) -> TaxonomyRegistryLoadResult:
    """Load the default taxonomy registry and return the rich result object."""

    return get_default_taxonomy_registry().load_result(
        force_reload=force_reload,
        allow_stale_on_error=allow_stale_on_error,
    )


def resolve_taxonomy_file_path(configured_file_path: Optional[PathLike] = None) -> Path:
    """
    Resolve the taxonomy file path.

    Priority:
    1. explicit configured_file_path
    2. environment variable VECTOPLAN_TAXONOMY_FILE / VPLIB_TAXONOMY_FILE
    3. default data/taxonomy.v1.json next to this module
    """

    if configured_file_path:
        return normalize_path(configured_file_path)

    env_path = first_non_empty_env(ENV_TAXONOMY_FILE_KEYS)
    if env_path:
        return normalize_path(env_path)

    return default_taxonomy_file_path()


def default_taxonomy_file_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / DEFAULT_TAXONOMY_DATA_DIRNAME
        / DEFAULT_TAXONOMY_FILENAME
    )


def load_taxonomy_registry_model_from_file(file_path: PathLike) -> TaxonomyRegistryModel:
    path = normalize_path(file_path)

    if not path.exists():
        raise TaxonomyRegistryPathError(f"Taxonomy file does not exist: {path}")

    if not path.is_file():
        raise TaxonomyRegistryPathError(f"Taxonomy path is not a file: {path}")

    data = read_json_file(path)
    return TaxonomyRegistryModel.from_dict(data)


def read_json_file(file_path: PathLike) -> Mapping[str, Any]:
    path = normalize_path(file_path)

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise TaxonomyRegistryLoadError(
            f"Invalid JSON in taxonomy file '{path}': line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise TaxonomyRegistryLoadError(f"Could not read taxonomy file '{path}': {exc}") from exc

    if not isinstance(data, Mapping):
        raise TaxonomyRegistryLoadError(
            f"Taxonomy file '{path}' must contain a JSON object at the root."
        )

    return data


def write_json_file_atomic(file_path: PathLike, data: Mapping[str, Any]) -> Path:
    """
    Write a JSON file atomically.

    This helper is not used by the loader itself, but is useful for future admin
    tooling and tests. It is intentionally kept here because the registry owns
    the taxonomy data file concern.
    """

    path = normalize_path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")

    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(make_json_safe(data), handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        tmp_path.replace(path)
        return path
    except OSError as exc:
        raise TaxonomyRegistryLoadError(f"Could not write taxonomy file '{path}': {exc}") from exc
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def compute_file_sha256(file_path: PathLike, *, chunk_size: int = 1024 * 1024) -> str:
    path = normalize_path(file_path)
    digest = hashlib.sha256()

    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise TaxonomyRegistryLoadError(f"Could not hash taxonomy file '{path}': {exc}") from exc


def resolve_strict_default() -> bool:
    value = first_non_empty_env(ENV_TAXONOMY_STRICT_KEYS)
    return safe_bool(value, True)


def resolve_hash_default() -> bool:
    value = first_non_empty_env(ENV_TAXONOMY_HASH_KEYS)
    return safe_bool(value, True)


def first_non_empty_env(keys: Tuple[str, ...]) -> str:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value.strip()
    return ""


def normalize_path(file_path: PathLike) -> Path:
    try:
        return Path(file_path).expanduser().resolve()
    except Exception as exc:
        raise TaxonomyRegistryPathError(f"Invalid taxonomy path '{file_path}': {exc}") from exc


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "DEFAULT_TAXONOMY_DATA_DIRNAME",
    "DEFAULT_TAXONOMY_FILENAME",
    "ENV_TAXONOMY_FILE_KEYS",
    "ENV_TAXONOMY_HASH_KEYS",
    "ENV_TAXONOMY_STRICT_KEYS",
    "TaxonomyFileFingerprint",
    "TaxonomyRegistry",
    "TaxonomyRegistryError",
    "TaxonomyRegistryLoadError",
    "TaxonomyRegistryLoadResult",
    "TaxonomyRegistryPathError",
    "compute_file_sha256",
    "default_taxonomy_file_path",
    "get_default_taxonomy_registry",
    "load_default_taxonomy_registry",
    "load_default_taxonomy_result",
    "load_taxonomy_registry_model_from_file",
    "read_json_file",
    "reset_default_taxonomy_registry",
    "resolve_hash_default",
    "resolve_strict_default",
    "resolve_taxonomy_file_path",
    "utc_now_iso",
    "write_json_file_atomic",
]