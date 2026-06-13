# services/vectoplan-library/src/vplib/vplib_id_service.py
"""
VPLIB ID Service.

Zweck:
- Erzeugt stabile, kanonische VPLIB-IDs für neue Library-Packages.
- Die ID entsteht bewusst beim Erstellen des .vplib-Packages.
- Die Datenbank übernimmt diese ID später nur und erzeugt sie nicht selbst.
- Die ID sieht wie eine UUID aus, basiert intern aber auf Zeitkomponente,
  Zufallsanteil, Prozess-/Thread-Kontext und Hashing.
- Dadurch ist die Zusammensetzung nicht direkt aus der ID ablesbar.

Beispiel:
    123e4567-e89b-12d3-a456-426614174000

Wichtige Regel:
    vplib_uid ist die unveränderliche technische Paket-ID.
    family_id, package_id, slug oder label dürfen sich fachlich ändern,
    vplib_uid nicht.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import threading
import time
import uuid
from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

VPLIB_UID_FIELD = "vplib_uid"

# Nur bewusst sichere Aliase. "id" und "package_id" werden absichtlich nicht
# als Alias akzeptiert, weil diese Felder häufig semantisch anders genutzt werden.
VPLIB_UID_ALIASES = (
    VPLIB_UID_FIELD,
    "vplibUid",
    "vplib_uid_v1",
)

VPLIB_UID_GENERATOR_VERSION = "vplib.uid.generator.v1"

NIL_UUID = "00000000-0000-0000-0000-000000000000"

# Akzeptiert kanonische RFC-4122-artige UUIDs mit Version 1-8.
# Erzeugt wird durch diesen Service aktuell eine Version-4-artige UUID.
UUID_CANONICAL_RE = re.compile(
    r"^[0-9a-f]{8}-"
    r"[0-9a-f]{4}-"
    r"[1-8][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-"
    r"[0-9a-f]{12}$",
    re.IGNORECASE,
)

DEFAULT_GENERATION_ATTEMPTS = 32
DEFAULT_UNIQUE_GENERATION_ATTEMPTS = 128


# ---------------------------------------------------------------------------
# Internal process-local counter
# ---------------------------------------------------------------------------

_COUNTER_LOCK = threading.Lock()
_COUNTER_VALUE = 0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VplibIdError(ValueError):
    """Basisklasse für VPLIB-ID-Fehler."""


class VplibIdGenerationError(VplibIdError):
    """Wird ausgelöst, wenn keine gültige VPLIB-ID erzeugt werden kann."""


class VplibIdValidationError(VplibIdError):
    """Wird ausgelöst, wenn eine VPLIB-ID fehlt oder ungültig ist."""


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VplibIdGenerationContext:
    """
    Diagnosekontext für eine ID-Erzeugung.

    Dieser Kontext wird bewusst nicht in die ID geschrieben.
    Die erzeugte ID ist nur der gehashte, UUID-kompatible Endwert.
    """

    timestamp_ns: int
    generated_at_utc: str
    random_hex: str
    counter: int
    pid: int
    thread_id: int
    generator_version: str = VPLIB_UID_GENERATOR_VERSION


@dataclass(frozen=True)
class VplibIdValidationResult:
    """Strukturiertes Ergebnis einer VPLIB-ID-Validierung."""

    ok: bool
    uid: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _safe_time_ns() -> int:
    """
    Liefert eine möglichst präzise Zeit in Nanosekunden.

    Normalfall:
        time.time_ns()

    Fallback:
        time.time() * 1_000_000_000

    Letzter Fallback:
        datetime.now(timezone.utc).timestamp()
    """
    try:
        value = int(time.time_ns())
        if value > 0:
            return value
    except Exception as exc:  # pragma: no cover - defensiver Fallback
        LOGGER.debug("time.time_ns() failed while generating VPLIB UID: %s", exc)

    try:
        value = int(time.time() * 1_000_000_000)
        if value > 0:
            return value
    except Exception as exc:  # pragma: no cover - defensiver Fallback
        LOGGER.debug("time.time() fallback failed while generating VPLIB UID: %s", exc)

    try:
        value = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
        if value > 0:
            return value
    except Exception as exc:  # pragma: no cover - extrem unwahrscheinlich
        LOGGER.debug("datetime fallback failed while generating VPLIB UID: %s", exc)

    # Absoluter Notfall-Fallback. Nicht schön, aber deterministisch verwendbar.
    return 1


def _utc_iso_from_ns(timestamp_ns: int) -> str:
    """Konvertiert Nanosekunden-Zeitstempel in ISO-UTC für Diagnosezwecke."""
    try:
        seconds = int(timestamp_ns) / 1_000_000_000
        return (
            datetime.fromtimestamp(seconds, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    except Exception as exc:  # pragma: no cover - defensiver Fallback
        LOGGER.debug("Failed to format timestamp_ns as UTC ISO: %s", exc)
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00",
            "Z",
        )


def _safe_pid() -> int:
    """Liefert die Prozess-ID oder 0 als defensiven Fallback."""
    try:
        return int(os.getpid())
    except Exception as exc:  # pragma: no cover
        LOGGER.debug("os.getpid() failed while generating VPLIB UID: %s", exc)
        return 0


def _safe_thread_id() -> int:
    """Liefert die Thread-ID oder 0 als defensiven Fallback."""
    try:
        return int(threading.get_ident())
    except Exception as exc:  # pragma: no cover
        LOGGER.debug("threading.get_ident() failed while generating VPLIB UID: %s", exc)
        return 0


def _next_counter() -> int:
    """
    Prozesslokaler Monotonic-Counter.

    Dieser Counter ist kein Persistenzmechanismus.
    Er reduziert nur innerhalb eines sehr engen Zeitfensters zusätzlich
    das Kollisionsrisiko, falls zwei IDs im selben Prozess in derselben
    Nanosekunde erzeugt werden.
    """
    global _COUNTER_VALUE

    try:
        with _COUNTER_LOCK:
            _COUNTER_VALUE = (_COUNTER_VALUE + 1) & 0xFFFFFFFFFFFFFFFF
            return _COUNTER_VALUE
    except Exception as exc:  # pragma: no cover - Lockfehler praktisch unmöglich
        LOGGER.debug("Counter lock failed while generating VPLIB UID: %s", exc)

    try:
        return int(time.perf_counter_ns()) & 0xFFFFFFFFFFFFFFFF
    except Exception:
        return 0


def _safe_random_bytes(length: int = 32) -> bytes:
    """
    Liefert kryptographisch starke Zufallsbytes.

    Normalfall:
        secrets.token_bytes()

    Fallback:
        os.urandom()

    Letzter Fallback:
        Hash aus Zeit, PID, Thread und Counter.
    """
    safe_length = max(16, int(length or 32))

    try:
        return secrets.token_bytes(safe_length)
    except Exception as exc:  # pragma: no cover
        LOGGER.debug("secrets.token_bytes() failed while generating VPLIB UID: %s", exc)

    try:
        return os.urandom(safe_length)
    except Exception as exc:  # pragma: no cover
        LOGGER.debug("os.urandom() failed while generating VPLIB UID: %s", exc)

    # Letzter defensiver Fallback. Nicht kryptographisch ideal, aber für einen
    # extremen Ausnahmefall besser als ein harter Absturz.
    try:
        seed = (
            f"{_safe_time_ns()}:{_safe_pid()}:{_safe_thread_id()}:{_next_counter()}"
        ).encode("utf-8", errors="replace")
        digest = hashlib.sha512(seed).digest()
        while len(digest) < safe_length:
            digest += hashlib.sha512(digest + seed).digest()
        return digest[:safe_length]
    except Exception as exc:  # pragma: no cover
        raise VplibIdGenerationError(
            "Could not create any random entropy for VPLIB UID generation."
        ) from exc


def _int_to_bytes(value: int, length: int = 16) -> bytes:
    """
    Konvertiert einen Integer robust in unsigned big-endian Bytes.

    Negative oder zu große Werte werden defensiv in den verfügbaren Bereich
    gemappt, damit die ID-Erzeugung nicht an Randwerten scheitert.
    """
    safe_length = max(1, int(length or 16))

    try:
        mask = (1 << (safe_length * 8)) - 1
        safe_value = int(value) & mask
        return safe_value.to_bytes(safe_length, byteorder="big", signed=False)
    except Exception as exc:
        raise VplibIdGenerationError(
            f"Could not convert integer value to {safe_length} bytes."
        ) from exc


def _build_generation_context() -> VplibIdGenerationContext:
    """Erzeugt den Rohkontext für eine VPLIB-ID."""
    timestamp_ns = _safe_time_ns()
    random_bytes = _safe_random_bytes(32)

    return VplibIdGenerationContext(
        timestamp_ns=timestamp_ns,
        generated_at_utc=_utc_iso_from_ns(timestamp_ns),
        random_hex=random_bytes.hex(),
        counter=_next_counter(),
        pid=_safe_pid(),
        thread_id=_safe_thread_id(),
    )


def _build_entropy_payload(context: VplibIdGenerationContext) -> bytes:
    """
    Baut den Roh-Entropy-Payload.

    Der Payload enthält:
    - Generator-Version
    - Zeitstempel in Nanosekunden
    - UTC-Diagnosezeit
    - Zufallsbytes
    - Counter
    - PID
    - Thread-ID
    - perf_counter_ns als zusätzlicher Laufzeitanteil

    Dieser Payload wird danach gehasht. Die finale ID enthält diese Werte
    nicht direkt lesbar.
    """
    try:
        try:
            perf_ns = int(time.perf_counter_ns())
        except Exception:
            perf_ns = 0

        chunks = [
            b"VECTOPLAN",
            b"VPLIB",
            b"UID",
            b"GENERATOR",
            context.generator_version.encode("utf-8", errors="replace"),
            _int_to_bytes(context.timestamp_ns, 16),
            context.generated_at_utc.encode("utf-8", errors="replace"),
            bytes.fromhex(context.random_hex),
            _int_to_bytes(context.counter, 8),
            _int_to_bytes(context.pid, 8),
            _int_to_bytes(context.thread_id, 8),
            _int_to_bytes(perf_ns, 16),
        ]

        return b"|".join(chunks)
    except Exception as exc:
        raise VplibIdGenerationError(
            "Could not build entropy payload for VPLIB UID generation."
        ) from exc


def _hash_payload_to_uuid(payload: bytes) -> str:
    """
    Rechnet den Entropy-Payload in eine kanonische UUID-Stringform um.

    Vorgehen:
    - BLAKE2b-Hash mit 16 Byte Digest.
    - Danach werden RFC-4122-kompatible Version-/Variant-Bits gesetzt.
    - Die ID sieht dadurch wie eine normale UUID aus.
    """
    try:
        digest = bytearray(
            hashlib.blake2b(
                payload,
                digest_size=16,
                person=b"VPLIB_UID_V1",
            ).digest()
        )
    except Exception as exc:  # pragma: no cover - hashlib sollte vorhanden sein
        LOGGER.debug("blake2b failed while generating VPLIB UID: %s", exc)
        try:
            digest = bytearray(hashlib.sha256(payload).digest()[:16])
        except Exception as sha_exc:
            raise VplibIdGenerationError(
                "Could not hash entropy payload for VPLIB UID generation."
            ) from sha_exc

    try:
        # UUID Version 4 setzen: xxxx-xxxx-4xxx-....
        digest[6] = (digest[6] & 0x0F) | 0x40

        # RFC-4122 Variant setzen: ....-....-....-[8|9|a|b]xxx-....
        digest[8] = (digest[8] & 0x3F) | 0x80

        generated = str(uuid.UUID(bytes=bytes(digest))).lower()
        return generated
    except Exception as exc:
        raise VplibIdGenerationError(
            "Could not convert hashed payload to UUID string."
        ) from exc


def _generate_once() -> str:
    """Erzeugt genau eine VPLIB-ID ohne Retry-Schleife."""
    context = _build_generation_context()
    payload = _build_entropy_payload(context)
    return _hash_payload_to_uuid(payload)


# ---------------------------------------------------------------------------
# Public generation API
# ---------------------------------------------------------------------------


def generate_vplib_uid() -> str:
    """
    Erzeugt eine neue kanonische VPLIB-ID.

    Die ID:
    - sieht aus wie eine UUID
    - ist lowercase
    - ist RFC-4122-kompatibel
    - enthält keine direkt lesbare Zeit-/Random-Struktur
    - basiert intern auf Zeitstempel, Zufall, Counter und Hashing

    Returns:
        str: kanonische UUID-ähnliche VPLIB-ID.

    Raises:
        VplibIdGenerationError: wenn nach mehreren Versuchen keine gültige ID
        erzeugt werden konnte.
    """
    last_error: Exception | None = None

    for attempt in range(1, DEFAULT_GENERATION_ATTEMPTS + 1):
        try:
            candidate = _generate_once()
            normalized = normalize_vplib_uid(candidate)

            if normalized:
                return normalized

            last_error = VplibIdGenerationError(
                f"Generated invalid VPLIB UID candidate on attempt {attempt}."
            )
        except Exception as exc:
            last_error = exc
            LOGGER.debug(
                "VPLIB UID generation attempt %s/%s failed: %s",
                attempt,
                DEFAULT_GENERATION_ATTEMPTS,
                exc,
            )

    # Zusätzlicher Fallback über uuid.uuid4().
    # Normalerweise wird dieser Pfad nicht genutzt.
    try:
        fallback = str(uuid.uuid4()).lower()
        normalized = normalize_vplib_uid(fallback)
        if normalized:
            return normalized
    except Exception as exc:  # pragma: no cover
        last_error = exc

    raise VplibIdGenerationError(
        "Could not generate a valid VPLIB UID."
    ) from last_error


def generate_unique_vplib_uid(
    existing_uids: Iterable[Any] | None = None,
    *,
    max_attempts: int = DEFAULT_UNIQUE_GENERATION_ATTEMPTS,
) -> str:
    """
    Erzeugt eine neue VPLIB-ID, die nicht in existing_uids enthalten ist.

    Diese Funktion ersetzt keinen Datenbank-UNIQUE-Constraint.
    Sie ist ein zusätzlicher Schutz für:
    - Backfill-Skripte
    - Scanner-Dry-Runs
    - lokale Package-Erzeugung
    - Tests

    Args:
        existing_uids:
            Bereits bekannte IDs.
        max_attempts:
            Maximale Anzahl an Erzeugungsversuchen.

    Returns:
        str: neue, nicht enthaltene VPLIB-ID.

    Raises:
        VplibIdGenerationError: wenn keine freie ID erzeugt werden konnte.
    """
    normalized_existing: set[str] = set()

    try:
        for value in existing_uids or ():
            normalized = normalize_vplib_uid(value)
            if normalized:
                normalized_existing.add(normalized)
    except Exception as exc:
        LOGGER.debug("Could not normalize existing VPLIB UID set: %s", exc)

    attempts = max(1, int(max_attempts or DEFAULT_UNIQUE_GENERATION_ATTEMPTS))
    last_uid: str | None = None

    for _ in range(attempts):
        uid = generate_vplib_uid()
        last_uid = uid

        if uid not in normalized_existing:
            return uid

    raise VplibIdGenerationError(
        f"Could not generate unique VPLIB UID after {attempts} attempts. "
        f"Last candidate: {last_uid or '<none>'}"
    )


def ensure_vplib_uid(
    value: Any | None = None,
    *,
    existing_uids: Iterable[Any] | None = None,
) -> str:
    """
    Gibt eine vorhandene gültige VPLIB-ID normalisiert zurück oder erzeugt eine neue.

    Args:
        value:
            Potenziell vorhandene ID.
        existing_uids:
            Optional bekannte IDs, gegen die eine neu erzeugte ID geprüft wird.

    Returns:
        str: gültige kanonische VPLIB-ID.
    """
    normalized = normalize_vplib_uid(value)
    if normalized:
        return normalized

    return generate_unique_vplib_uid(existing_uids=existing_uids)


# ---------------------------------------------------------------------------
# Public validation API
# ---------------------------------------------------------------------------


def normalize_vplib_uid(value: Any) -> str | None:
    """
    Normalisiert eine VPLIB-ID in kanonische lowercase UUID-Schreibweise.

    Akzeptiert:
    - kanonische UUID mit Bindestrichen
    - UUID ohne Bindestriche
    - UUID mit geschweiften Klammern
    - urn:uuid:<uuid>

    Lehnt ab:
    - None
    - leere Strings
    - NIL UUID
    - nicht-RFC-4122-artige UUIDs
    - Werte mit ungültiger UUID-Version/Variant
    """
    if value is None:
        return None

    try:
        text = str(value).strip()
    except Exception:
        return None

    if not text:
        return None

    try:
        lowered = text.lower()

        if lowered.startswith("urn:uuid:"):
            text = text[9:].strip()

        if text.startswith("{") and text.endswith("}"):
            text = text[1:-1].strip()

        parsed = uuid.UUID(text)
        canonical = str(parsed).lower()

        if canonical == NIL_UUID:
            return None

        if not UUID_CANONICAL_RE.match(canonical):
            return None

        return canonical
    except Exception:
        return None


def is_valid_vplib_uid(value: Any) -> bool:
    """Prüft, ob ein Wert eine gültige VPLIB-ID ist."""
    return normalize_vplib_uid(value) is not None


def validate_vplib_uid(value: Any, *, field_name: str = VPLIB_UID_FIELD) -> str:
    """
    Validiert eine VPLIB-ID und gibt sie normalisiert zurück.

    Raises:
        VplibIdValidationError: wenn die ID fehlt oder ungültig ist.
    """
    normalized = normalize_vplib_uid(value)

    if normalized:
        return normalized

    raise VplibIdValidationError(
        f"Invalid or missing {field_name!r}. Expected canonical UUID-like VPLIB UID."
    )


def validate_vplib_uid_result(value: Any) -> VplibIdValidationResult:
    """
    Validiert eine VPLIB-ID ohne Exception.

    Returns:
        VplibIdValidationResult
    """
    normalized = normalize_vplib_uid(value)

    if normalized:
        return VplibIdValidationResult(ok=True, uid=normalized)

    return VplibIdValidationResult(
        ok=False,
        uid=None,
        reason="Invalid or missing VPLIB UID.",
    )


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def get_vplib_uid_from_mapping(
    data: Mapping[str, Any] | None,
    *,
    allow_aliases: bool = True,
) -> str | None:
    """
    Liest eine VPLIB-ID aus einem Mapping.

    Standardfeld:
        vplib_uid

    Optional unterstützte Aliase:
        vplibUid
        vplib_uid_v1

    Nicht unterstützte Aliase:
        id
        package_id
        family_id

    Grund:
        Diese Felder können andere fachliche Bedeutungen haben.
    """
    if not isinstance(data, Mapping):
        return None

    field_names = VPLIB_UID_ALIASES if allow_aliases else (VPLIB_UID_FIELD,)

    for field_name in field_names:
        try:
            if field_name in data:
                normalized = normalize_vplib_uid(data.get(field_name))
                if normalized:
                    return normalized
        except Exception as exc:
            LOGGER.debug(
                "Failed reading VPLIB UID field %r from mapping: %s",
                field_name,
                exc,
            )

    return None


def require_vplib_uid_from_mapping(
    data: Mapping[str, Any] | None,
    *,
    allow_aliases: bool = True,
    field_name: str = VPLIB_UID_FIELD,
) -> str:
    """
    Liest eine VPLIB-ID aus einem Mapping oder wirft einen Validierungsfehler.
    """
    uid = get_vplib_uid_from_mapping(data, allow_aliases=allow_aliases)

    if uid:
        return uid

    raise VplibIdValidationError(
        f"Missing valid {field_name!r} in VPLIB manifest/mapping."
    )


def ensure_mapping_vplib_uid(
    data: MutableMapping[str, Any],
    *,
    overwrite_invalid: bool = False,
    existing_uids: Iterable[Any] | None = None,
) -> str:
    """
    Stellt sicher, dass ein MutableMapping eine gültige `vplib_uid` enthält.

    Verhalten:
    - vorhandene gültige ID wird normalisiert und behalten
    - fehlende ID wird neu erzeugt
    - ungültige ID erzeugt standardmäßig einen Fehler
    - ungültige ID wird nur ersetzt, wenn overwrite_invalid=True

    Args:
        data:
            Manifest- oder Payload-Mapping, das mutiert wird.
        overwrite_invalid:
            Ob eine vorhandene ungültige ID ersetzt werden darf.
        existing_uids:
            Optional bekannte IDs zur zusätzlichen Kollisionsprüfung.

    Returns:
        str: gültige kanonische VPLIB-ID.

    Raises:
        VplibIdValidationError: wenn data kein MutableMapping ist oder eine
        ungültige ID nicht überschrieben werden darf.
    """
    if not isinstance(data, MutableMapping):
        raise VplibIdValidationError(
            "Cannot ensure VPLIB UID on non-mutable manifest/mapping."
        )

    try:
        current_raw = data.get(VPLIB_UID_FIELD)
        current_uid = normalize_vplib_uid(current_raw)

        if current_uid:
            data[VPLIB_UID_FIELD] = current_uid
            return current_uid

        has_invalid_value = current_raw is not None and str(current_raw).strip() != ""

        if has_invalid_value and not overwrite_invalid:
            raise VplibIdValidationError(
                f"Existing {VPLIB_UID_FIELD!r} is invalid and overwrite_invalid=False."
            )

        uid = generate_unique_vplib_uid(existing_uids=existing_uids)
        data[VPLIB_UID_FIELD] = uid
        return uid
    except VplibIdError:
        raise
    except Exception as exc:
        raise VplibIdValidationError(
            f"Could not ensure {VPLIB_UID_FIELD!r} on manifest/mapping."
        ) from exc


def set_mapping_vplib_uid(
    data: MutableMapping[str, Any],
    uid: Any,
    *,
    overwrite: bool = False,
) -> str:
    """
    Setzt eine konkrete VPLIB-ID auf ein MutableMapping.

    Verhalten:
    - uid wird validiert und normalisiert
    - wenn bereits eine andere gültige ID existiert, wird sie nur bei overwrite=True ersetzt
    """
    if not isinstance(data, MutableMapping):
        raise VplibIdValidationError(
            "Cannot set VPLIB UID on non-mutable manifest/mapping."
        )

    normalized_new = validate_vplib_uid(uid)

    try:
        existing = normalize_vplib_uid(data.get(VPLIB_UID_FIELD))

        if existing and existing != normalized_new and not overwrite:
            raise VplibIdValidationError(
                f"Refusing to overwrite existing {VPLIB_UID_FIELD!r} "
                f"{existing!r} with {normalized_new!r}."
            )

        data[VPLIB_UID_FIELD] = normalized_new
        return normalized_new
    except VplibIdError:
        raise
    except Exception as exc:
        raise VplibIdValidationError(
            f"Could not set {VPLIB_UID_FIELD!r} on manifest/mapping."
        ) from exc


def remove_mapping_vplib_uid(
    data: MutableMapping[str, Any],
) -> str | None:
    """
    Entfernt `vplib_uid` aus einem MutableMapping und gibt die vorherige gültige ID zurück.

    Diese Funktion sollte selten genutzt werden.
    Sie ist hauptsächlich für Tests, Migrationen und gezielte Reparaturskripte gedacht.
    """
    if not isinstance(data, MutableMapping):
        raise VplibIdValidationError(
            "Cannot remove VPLIB UID from non-mutable manifest/mapping."
        )

    try:
        previous = normalize_vplib_uid(data.get(VPLIB_UID_FIELD))
        data.pop(VPLIB_UID_FIELD, None)
        return previous
    except Exception as exc:
        raise VplibIdValidationError(
            f"Could not remove {VPLIB_UID_FIELD!r} from manifest/mapping."
        ) from exc


# ---------------------------------------------------------------------------
# Compatibility helpers for scanner/create code
# ---------------------------------------------------------------------------


def build_vplib_uid_payload_fragment(uid: Any | None = None) -> dict[str, str]:
    """
    Baut ein kleines Payload-Fragment für Manifest-/Create-Code.

    Beispiel:
        {"vplib_uid": "123e4567-e89b-12d3-a456-426614174000"}
    """
    return {VPLIB_UID_FIELD: ensure_vplib_uid(uid)}


def compare_vplib_uids(left: Any, right: Any) -> bool:
    """
    Vergleicht zwei VPLIB-IDs nach Normalisierung.

    Returns:
        True, wenn beide gültig und identisch sind.
    """
    left_normalized = normalize_vplib_uid(left)
    right_normalized = normalize_vplib_uid(right)

    return bool(left_normalized and right_normalized and left_normalized == right_normalized)


def assert_same_vplib_uid(
    left: Any,
    right: Any,
    *,
    left_name: str = "left",
    right_name: str = "right",
) -> str:
    """
    Validiert, dass zwei VPLIB-ID-Werte identisch sind.

    Returns:
        str: normalisierte ID.

    Raises:
        VplibIdValidationError: wenn einer der Werte ungültig ist oder beide
        Werte unterschiedlich sind.
    """
    left_normalized = validate_vplib_uid(left, field_name=left_name)
    right_normalized = validate_vplib_uid(right, field_name=right_name)

    if left_normalized != right_normalized:
        raise VplibIdValidationError(
            f"VPLIB UID mismatch: {left_name}={left_normalized!r}, "
            f"{right_name}={right_normalized!r}."
        )

    return left_normalized


__all__ = [
    "DEFAULT_GENERATION_ATTEMPTS",
    "DEFAULT_UNIQUE_GENERATION_ATTEMPTS",
    "NIL_UUID",
    "UUID_CANONICAL_RE",
    "VPLIB_UID_ALIASES",
    "VPLIB_UID_FIELD",
    "VPLIB_UID_GENERATOR_VERSION",
    "VplibIdError",
    "VplibIdGenerationContext",
    "VplibIdGenerationError",
    "VplibIdValidationError",
    "VplibIdValidationResult",
    "assert_same_vplib_uid",
    "build_vplib_uid_payload_fragment",
    "compare_vplib_uids",
    "ensure_mapping_vplib_uid",
    "ensure_vplib_uid",
    "generate_unique_vplib_uid",
    "generate_vplib_uid",
    "get_vplib_uid_from_mapping",
    "is_valid_vplib_uid",
    "normalize_vplib_uid",
    "remove_mapping_vplib_uid",
    "require_vplib_uid_from_mapping",
    "set_mapping_vplib_uid",
    "validate_vplib_uid",
    "validate_vplib_uid_result",
]