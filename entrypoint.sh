#!/bin/sh
# services/vectoplan-library/entrypoint.sh

# -----------------------------------------------------------------------------
# VECTOPLAN Library - Container Entrypoint
# -----------------------------------------------------------------------------
# Aufgaben:
# - robuster Startpunkt für den Containerbetrieb
# - servicebezogene Defaults für vectoplan-library
# - VPLIB-Routenstruktur prüfen
# - Creative-Library-Routenstruktur prüfen
# - Runtime-Verzeichnisse vorbereiten
# - src/library/source Struktur prüfen
# - PostgreSQL-Verfügbarkeit abwarten
# - Flask-Migrate automatisiert initialisieren:
#     flask db init      falls migrations/env.py fehlt
#     flask db upgrade   vor migrate, falls Versionen bereits existieren
#     flask db migrate   nur neue Version, wenn Schemaänderungen erkannt werden
#     flask db upgrade   nach migrate, falls neue Version erzeugt wurde
# - wenn noch keine Version existiert, wird die erste Version automatisch erzeugt
# - wenn keine Schemaänderung existiert, wird keine neue versions-Datei erzeugt
# - Alembic-State-Mismatch erkennen:
#     DB enthält alembic_version, aber passende lokale revisions-Datei fehlt
# - bei fehlenden lokalen revisions-Dateien und vorhandener DB-Revision:
#     Datenbank-Schema im Dev-/Auto-Modus zurücksetzen
#     danach Migration automatisch neu erzeugen und anwenden
# - optionalen Python-Prestart-Check ausführen
# - Gunicorn oder Python-Modus starten
#
# Wichtig:
# - keine manuell erstellte migrations/versions-Datei erforderlich
# - kein manuelles Schreiben einer Revision-Datei
# - kein direkter Docker-Volume-Reset aus dem Container möglich
# - stattdessen automatischer PostgreSQL-Schema-Reset im Dev-/Auto-Modus
# - keine Prüfung auf ./routes/editor.py
# - keine Editor-Route /editor
# - keine Template-/Static-Pflicht für API-only-Betrieb
# - keine Creative-Library-DB-Upserts in diesem Entrypoint
# - kein Kopieren nach creative_library
# - keine fachliche VPLIB-ID-Erzeugung in der DB
# - `vplib_uid` entsteht im .vplib/Create-Flow und wird später nur gespeichert
# - Migrationen sind idempotent und per ENV steuerbar
# -----------------------------------------------------------------------------

set -eu
( set -o pipefail ) >/dev/null 2>&1 && set -o pipefail || true


# -----------------------------------------------------------------------------
# Grundkonstanten
# -----------------------------------------------------------------------------

APP_NAME="${APP_NAME:-vectoplan-library}"
APP_DISPLAY_NAME="${APP_DISPLAY_NAME:-VECTOPLAN Library}"
DEFAULT_APP_HOME="/opt/vectoplan/services/vectoplan-library"
DEFAULT_HOST="0.0.0.0"
DEFAULT_PORT="5000"
DEFAULT_CONFIG="production"
DEFAULT_RUN_MODE="gunicorn"
DEFAULT_GUNICORN_APP="wsgi:app"
DEFAULT_GUNICORN_WORKERS="2"
DEFAULT_GUNICORN_THREADS="2"
DEFAULT_GUNICORN_TIMEOUT="120"
DEFAULT_GUNICORN_KEEPALIVE="5"
DEFAULT_GUNICORN_LOG_LEVEL="info"
DEFAULT_GUNICORN_ACCESSLOG="-"
DEFAULT_GUNICORN_ERRORLOG="-"

DEFAULT_VPLIB_ROUTE_PREFIX="/api/v1/vplib"
DEFAULT_LIBRARY_ROUTE_PREFIX="/api/v1/vplib/library"

DEFAULT_DB_HOST="vectoplan-library-db"
DEFAULT_DB_PORT="5432"
DEFAULT_DB_NAME="vectoplan_library"
DEFAULT_DB_USER="vectoplan"
DEFAULT_DB_PASSWORD="vectoplan"
DEFAULT_DB_DRIVER="postgresql+psycopg"
DEFAULT_MIGRATIONS_DIRECTORY="migrations"


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

timestamp_utc() {
  if command -v date >/dev/null 2>&1; then
    date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || printf '%s' "1970-01-01T00:00:00Z"
  else
    printf '%s' "1970-01-01T00:00:00Z"
  fi
}

log_info() {
  printf '%s [INFO]  [%s] %s\n' "$(timestamp_utc)" "$APP_NAME" "$*"
}

log_warn() {
  printf '%s [WARN]  [%s] %s\n' "$(timestamp_utc)" "$APP_NAME" "$*" >&2
}

log_error() {
  printf '%s [ERROR] [%s] %s\n' "$(timestamp_utc)" "$APP_NAME" "$*" >&2
}

die() {
  log_error "$*"
  exit 1
}


# -----------------------------------------------------------------------------
# Kleine Hilfsfunktionen
# -----------------------------------------------------------------------------

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

is_true() {
  case "${1:-}" in
    1|true|TRUE|True|yes|YES|Yes|y|Y|on|ON|On|enabled|ENABLED|Enabled)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_false() {
  case "${1:-}" in
    0|false|FALSE|False|no|NO|No|n|N|off|OFF|Off|disabled|DISABLED|Disabled)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

normalize_log_level() {
  case "${1:-}" in
    debug|DEBUG|Debug) printf '%s' "debug" ;;
    info|INFO|Info) printf '%s' "info" ;;
    warning|WARNING|Warning|warn|WARN|Warn) printf '%s' "warning" ;;
    error|ERROR|Error) printf '%s' "error" ;;
    critical|CRITICAL|Critical) printf '%s' "critical" ;;
    *) printf '%s' "$DEFAULT_GUNICORN_LOG_LEVEL" ;;
  esac
}

require_file_any() {
  file_label="$1"
  shift

  for file_path in "$@"; do
    if [ -f "$file_path" ]; then
      return 0
    fi
  done

  log_error "Erforderliche Datei fehlt: ${file_label} ($(printf '%s ' "$@" | sed 's/[[:space:]]*$//'))"
  return 1
}

warn_if_missing_file_any() {
  file_label="$1"
  shift

  for file_path in "$@"; do
    if [ -f "$file_path" ]; then
      return 0
    fi
  done

  log_warn "Optionale Datei fehlt: ${file_label} ($(printf '%s ' "$@" | sed 's/[[:space:]]*$//'))"
  return 0
}

require_dir_any() {
  dir_label="$1"
  shift

  for dir_path in "$@"; do
    if [ -d "$dir_path" ]; then
      return 0
    fi
  done

  log_error "Erforderliches Verzeichnis fehlt: ${dir_label} ($(printf '%s ' "$@" | sed 's/[[:space:]]*$//'))"
  return 1
}

warn_if_missing_dir_any() {
  dir_label="$1"
  shift

  for dir_path in "$@"; do
    if [ -d "$dir_path" ]; then
      return 0
    fi
  done

  log_warn "Optionales Verzeichnis fehlt: ${dir_label} ($(printf '%s ' "$@" | sed 's/[[:space:]]*$//'))"
  return 0
}

ensure_dir() {
  dir_path="$1"

  if [ ! -d "$dir_path" ]; then
    mkdir -p "$dir_path"
  fi
}

ensure_uint() {
  value="$1"
  var_name="$2"
  fallback="$3"

  case "$value" in
    ''|*[!0-9]*)
      log_warn "Ungültiger numerischer Wert für ${var_name}: '${value}'. Fallback auf ${fallback}."
      printf '%s' "$fallback"
      ;;
    *)
      printf '%s' "$value"
      ;;
  esac
}

ensure_port() {
  raw_port="$1"
  validated_port="$(ensure_uint "$raw_port" "VECTOPLAN_LIBRARY_PORT" "$DEFAULT_PORT")"

  if [ "$validated_port" -lt 1 ] || [ "$validated_port" -gt 65535 ]; then
    log_warn "Port außerhalb des gültigen Bereichs: '${raw_port}'. Fallback auf ${DEFAULT_PORT}."
    printf '%s' "$DEFAULT_PORT"
    return
  fi

  printf '%s' "$validated_port"
}

safe_pwd() {
  pwd 2>/dev/null || printf '%s' "."
}

mask_uri() {
  uri_value="${1:-}"

  if [ -z "$uri_value" ]; then
    printf '%s' ""
    return 0
  fi

  printf '%s' "$uri_value" | sed -E 's#(://[^:/@]+):([^@]*)@#\1:***@#'
}

database_uri_component() {
  component="$1"
  uri_value="$2"

  if [ -z "$uri_value" ]; then
    return 0
  fi

  if ! command_exists python; then
    return 0
  fi

  python - "$component" "$uri_value" <<'PY' 2>/dev/null || true
import sys
from urllib.parse import urlparse

component = sys.argv[1]
uri = sys.argv[2]

try:
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]
    parsed = urlparse(uri)

    if component == "host":
        print(parsed.hostname or "")
    elif component == "port":
        print(parsed.port or "")
    elif component == "user":
        print(parsed.username or "")
    elif component == "password":
        print(parsed.password or "")
    elif component == "database":
        print((parsed.path or "").lstrip("/").split("/", 1)[0])
    elif component == "scheme":
        print(parsed.scheme or "")
except Exception:
    print("")
PY
}

database_uri_is_postgres() {
  uri_value="${1:-}"

  case "$uri_value" in
    postgres://*|postgresql://*|postgresql+*://*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

database_uri_is_sqlite() {
  uri_value="${1:-}"

  case "$uri_value" in
    sqlite://*|sqlite+*://*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_development_like_config() {
  case "${VECTOPLAN_LIBRARY_CONFIG:-}${FLASK_ENV:-}" in
    *development*|*Development*|*dev*|*Dev*|*local*|*Local*|*test*|*Test*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

handle_database_bootstrap_error() {
  message="$1"

  if is_true "$VECTOPLAN_LIBRARY_DB_MIGRATION_STRICT"; then
    die "$message"
  fi

  log_warn "$message"
  return 0
}


# -----------------------------------------------------------------------------
# Umgebungsvariablen mit Defaults
# -----------------------------------------------------------------------------

APP_HOME="${APP_HOME:-$DEFAULT_APP_HOME}"

VECTOPLAN_LIBRARY_HOST="${VECTOPLAN_LIBRARY_HOST:-$DEFAULT_HOST}"
VECTOPLAN_LIBRARY_PORT="${VECTOPLAN_LIBRARY_PORT:-$DEFAULT_PORT}"
VECTOPLAN_LIBRARY_CONFIG="${VECTOPLAN_LIBRARY_CONFIG:-$DEFAULT_CONFIG}"
VECTOPLAN_LIBRARY_RUN_MODE="${VECTOPLAN_LIBRARY_RUN_MODE:-$DEFAULT_RUN_MODE}"

VECTOPLAN_LIBRARY_PRESTART_CHECK="${VECTOPLAN_LIBRARY_PRESTART_CHECK:-true}"
VECTOPLAN_LIBRARY_PRESTART_CREATE_APP="${VECTOPLAN_LIBRARY_PRESTART_CREATE_APP:-false}"
VECTOPLAN_LIBRARY_STARTUP_STRICT="${VECTOPLAN_LIBRARY_STARTUP_STRICT:-false}"
VECTOPLAN_LIBRARY_PRINT_STARTUP_SUMMARY="${VECTOPLAN_LIBRARY_PRINT_STARTUP_SUMMARY:-true}"

GUNICORN_APP="${GUNICORN_APP:-$DEFAULT_GUNICORN_APP}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-$DEFAULT_GUNICORN_WORKERS}"
GUNICORN_THREADS="${GUNICORN_THREADS:-$DEFAULT_GUNICORN_THREADS}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-$DEFAULT_GUNICORN_TIMEOUT}"
GUNICORN_KEEPALIVE="${GUNICORN_KEEPALIVE:-$DEFAULT_GUNICORN_KEEPALIVE}"
GUNICORN_LOG_LEVEL="${GUNICORN_LOG_LEVEL:-$DEFAULT_GUNICORN_LOG_LEVEL}"
GUNICORN_ACCESSLOG="${GUNICORN_ACCESSLOG:-$DEFAULT_GUNICORN_ACCESSLOG}"
GUNICORN_ERRORLOG="${GUNICORN_ERRORLOG:-$DEFAULT_GUNICORN_ERRORLOG}"

# VPLIB-Kernpfade
VPLIB_SERVICE_ROOT="${VPLIB_SERVICE_ROOT:-$APP_HOME}"
VPLIB_SRC_ROOT="${VPLIB_SRC_ROOT:-$APP_HOME/src}"
VPLIB_SOURCE_ROOT="${VPLIB_SOURCE_ROOT:-$APP_HOME/sources}"
VPLIB_LIBRARY_CATALOG_ROOT="${VPLIB_LIBRARY_CATALOG_ROOT:-$APP_HOME/creative_library}"
VPLIB_GENERATED_ROOT="${VPLIB_GENERATED_ROOT:-$APP_HOME/generated/vplib}"
VPLIB_ARCHIVE_ROOT="${VPLIB_ARCHIVE_ROOT:-$APP_HOME/generated/archives}"
VPLIB_TEST_OUTPUT_ROOT="${VPLIB_TEST_OUTPUT_ROOT:-$APP_HOME/generated/vplib_test}"
VPLIB_ROUTE_PREFIX="${VPLIB_ROUTE_PREFIX:-$DEFAULT_VPLIB_ROUTE_PREFIX}"
VPLIB_DRY_RUN_DEFAULT="${VPLIB_DRY_RUN_DEFAULT:-true}"
VPLIB_TEST_ROUTE_ENABLED="${VPLIB_TEST_ROUTE_ENABLED:-true}"
VPLIB_CREATE_ROUTE_ENABLED="${VPLIB_CREATE_ROUTE_ENABLED:-true}"
VPLIB_CREATE_WRITE_ENABLED="${VPLIB_CREATE_WRITE_ENABLED:-true}"
VPLIB_CREATE_OVERWRITE_ENABLED="${VPLIB_CREATE_OVERWRITE_ENABLED:-false}"
VPLIB_DEFAULT_WRITE_MODE="${VPLIB_DEFAULT_WRITE_MODE:-fail}"
VPLIB_DEFAULT_VALIDATION_MODE="${VPLIB_DEFAULT_VALIDATION_MODE:-strict}"

# Creative-Library-Pfade
VECTOPLAN_LIBRARY_SERVICE_ROOT="${VECTOPLAN_LIBRARY_SERVICE_ROOT:-$APP_HOME}"
VECTOPLAN_LIBRARY_SRC_ROOT="${VECTOPLAN_LIBRARY_SRC_ROOT:-$APP_HOME/src}"
VECTOPLAN_LIBRARY_PACKAGE_ROOT="${VECTOPLAN_LIBRARY_PACKAGE_ROOT:-$APP_HOME/src/library}"
VECTOPLAN_LIBRARY_SOURCE_ROOT="${VECTOPLAN_LIBRARY_SOURCE_ROOT:-$APP_HOME/src/library/source}"
VECTOPLAN_LIBRARY_CREATIVE_ROOT="${VECTOPLAN_LIBRARY_CREATIVE_ROOT:-$APP_HOME/creative_library}"
VECTOPLAN_LIBRARY_GENERATED_ROOT="${VECTOPLAN_LIBRARY_GENERATED_ROOT:-$APP_HOME/generated/library}"
VECTOPLAN_LIBRARY_CACHE_ROOT="${VECTOPLAN_LIBRARY_CACHE_ROOT:-$APP_HOME/generated/library_cache}"
VECTOPLAN_LIBRARY_ROUTE_PREFIX="${VECTOPLAN_LIBRARY_ROUTE_PREFIX:-$DEFAULT_LIBRARY_ROUTE_PREFIX}"

LIBRARY_SERVICE_ROOT="${LIBRARY_SERVICE_ROOT:-$VECTOPLAN_LIBRARY_SERVICE_ROOT}"
LIBRARY_SRC_ROOT="${LIBRARY_SRC_ROOT:-$VECTOPLAN_LIBRARY_SRC_ROOT}"
LIBRARY_PACKAGE_ROOT="${LIBRARY_PACKAGE_ROOT:-$VECTOPLAN_LIBRARY_PACKAGE_ROOT}"
LIBRARY_SOURCE_ROOT="${LIBRARY_SOURCE_ROOT:-$VECTOPLAN_LIBRARY_SOURCE_ROOT}"
LIBRARY_CREATIVE_ROOT="${LIBRARY_CREATIVE_ROOT:-$VECTOPLAN_LIBRARY_CREATIVE_ROOT}"
LIBRARY_GENERATED_ROOT="${LIBRARY_GENERATED_ROOT:-$VECTOPLAN_LIBRARY_GENERATED_ROOT}"
LIBRARY_CACHE_ROOT="${LIBRARY_CACHE_ROOT:-$VECTOPLAN_LIBRARY_CACHE_ROOT}"
LIBRARY_ROUTE_PREFIX="${LIBRARY_ROUTE_PREFIX:-$VECTOPLAN_LIBRARY_ROUTE_PREFIX}"

VECTOPLAN_LIBRARY_SCAN_RECURSIVE="${VECTOPLAN_LIBRARY_SCAN_RECURSIVE:-true}"
VECTOPLAN_LIBRARY_SCAN_MAX_DEPTH="${VECTOPLAN_LIBRARY_SCAN_MAX_DEPTH:-12}"
VECTOPLAN_LIBRARY_SCAN_FOLLOW_SYMLINKS="${VECTOPLAN_LIBRARY_SCAN_FOLLOW_SYMLINKS:-false}"
VECTOPLAN_LIBRARY_INCLUDE_INVALID_IN_SCAN="${VECTOPLAN_LIBRARY_INCLUDE_INVALID_IN_SCAN:-true}"
VECTOPLAN_LIBRARY_AUTO_SCAN_ON_REQUEST="${VECTOPLAN_LIBRARY_AUTO_SCAN_ON_REQUEST:-true}"
VECTOPLAN_LIBRARY_FAIL_ON_DUPLICATE_IDS="${VECTOPLAN_LIBRARY_FAIL_ON_DUPLICATE_IDS:-true}"
VECTOPLAN_LIBRARY_TREAT_MISSING_SOURCE_ROOT_AS_EMPTY="${VECTOPLAN_LIBRARY_TREAT_MISSING_SOURCE_ROOT_AS_EMPTY:-true}"
VECTOPLAN_LIBRARY_LIST_INCLUDE_INVALID="${VECTOPLAN_LIBRARY_LIST_INCLUDE_INVALID:-false}"
VECTOPLAN_LIBRARY_DETAIL_INCLUDE_RAW_DOCUMENTS="${VECTOPLAN_LIBRARY_DETAIL_INCLUDE_RAW_DOCUMENTS:-true}"
VECTOPLAN_LIBRARY_DETAIL_INCLUDE_VALIDATION_REPORT="${VECTOPLAN_LIBRARY_DETAIL_INCLUDE_VALIDATION_REPORT:-true}"
VECTOPLAN_LIBRARY_CACHE_ENABLED="${VECTOPLAN_LIBRARY_CACHE_ENABLED:-false}"
VECTOPLAN_LIBRARY_CACHE_TTL_SECONDS="${VECTOPLAN_LIBRARY_CACHE_TTL_SECONDS:-5}"

# PostgreSQL / SQLAlchemy / Flask-Migrate
VECTOPLAN_LIBRARY_DATABASE_DRIVER="${VECTOPLAN_LIBRARY_DATABASE_DRIVER:-$DEFAULT_DB_DRIVER}"
VECTOPLAN_LIBRARY_DB_HOST_RAW="${VECTOPLAN_LIBRARY_DB_HOST:-}"
VECTOPLAN_LIBRARY_DB_PORT_RAW="${VECTOPLAN_LIBRARY_DB_PORT:-}"
VECTOPLAN_LIBRARY_DB_NAME_RAW="${VECTOPLAN_LIBRARY_DB_NAME:-}"
VECTOPLAN_LIBRARY_DB_USER_RAW="${VECTOPLAN_LIBRARY_DB_USER:-}"
VECTOPLAN_LIBRARY_DB_PASSWORD_RAW="${VECTOPLAN_LIBRARY_DB_PASSWORD:-}"

VECTOPLAN_LIBRARY_DB_HOST_FOR_DEFAULT="${VECTOPLAN_LIBRARY_DB_HOST_RAW:-$DEFAULT_DB_HOST}"
VECTOPLAN_LIBRARY_DB_PORT_FOR_DEFAULT="${VECTOPLAN_LIBRARY_DB_PORT_RAW:-$DEFAULT_DB_PORT}"
VECTOPLAN_LIBRARY_DB_NAME_FOR_DEFAULT="${VECTOPLAN_LIBRARY_DB_NAME_RAW:-$DEFAULT_DB_NAME}"
VECTOPLAN_LIBRARY_DB_USER_FOR_DEFAULT="${VECTOPLAN_LIBRARY_DB_USER_RAW:-$DEFAULT_DB_USER}"
VECTOPLAN_LIBRARY_DB_PASSWORD_FOR_DEFAULT="${VECTOPLAN_LIBRARY_DB_PASSWORD_RAW:-$DEFAULT_DB_PASSWORD}"

DEFAULT_DATABASE_URI="${VECTOPLAN_LIBRARY_DATABASE_DRIVER}://${VECTOPLAN_LIBRARY_DB_USER_FOR_DEFAULT}:${VECTOPLAN_LIBRARY_DB_PASSWORD_FOR_DEFAULT}@${VECTOPLAN_LIBRARY_DB_HOST_FOR_DEFAULT}:${VECTOPLAN_LIBRARY_DB_PORT_FOR_DEFAULT}/${VECTOPLAN_LIBRARY_DB_NAME_FOR_DEFAULT}"

VECTOPLAN_LIBRARY_DATABASE_URI="${VECTOPLAN_LIBRARY_DATABASE_URI:-${VECTOPLAN_LIBRARY_DATABASE_URL:-${SQLALCHEMY_DATABASE_URI:-${VPLIB_DATABASE_URL:-${DATABASE_URL:-$DEFAULT_DATABASE_URI}}}}}"
VECTOPLAN_LIBRARY_DATABASE_URL="${VECTOPLAN_LIBRARY_DATABASE_URL:-$VECTOPLAN_LIBRARY_DATABASE_URI}"
VPLIB_DATABASE_URL="${VPLIB_DATABASE_URL:-$VECTOPLAN_LIBRARY_DATABASE_URI}"
SQLALCHEMY_DATABASE_URI="${SQLALCHEMY_DATABASE_URI:-$VECTOPLAN_LIBRARY_DATABASE_URI}"
DATABASE_URL="${DATABASE_URL:-$VECTOPLAN_LIBRARY_DATABASE_URI}"

PARSED_DB_HOST="$(database_uri_component host "$SQLALCHEMY_DATABASE_URI")"
PARSED_DB_PORT="$(database_uri_component port "$SQLALCHEMY_DATABASE_URI")"
PARSED_DB_NAME="$(database_uri_component database "$SQLALCHEMY_DATABASE_URI")"
PARSED_DB_USER="$(database_uri_component user "$SQLALCHEMY_DATABASE_URI")"
PARSED_DB_PASSWORD="$(database_uri_component password "$SQLALCHEMY_DATABASE_URI")"

VECTOPLAN_LIBRARY_DB_HOST="${VECTOPLAN_LIBRARY_DB_HOST_RAW:-${PARSED_DB_HOST:-$DEFAULT_DB_HOST}}"
VECTOPLAN_LIBRARY_DB_PORT="${VECTOPLAN_LIBRARY_DB_PORT_RAW:-${PARSED_DB_PORT:-$DEFAULT_DB_PORT}}"
VECTOPLAN_LIBRARY_DB_NAME="${VECTOPLAN_LIBRARY_DB_NAME_RAW:-${PARSED_DB_NAME:-$DEFAULT_DB_NAME}}"
VECTOPLAN_LIBRARY_DB_USER="${VECTOPLAN_LIBRARY_DB_USER_RAW:-${PARSED_DB_USER:-$DEFAULT_DB_USER}}"
VECTOPLAN_LIBRARY_DB_PASSWORD="${VECTOPLAN_LIBRARY_DB_PASSWORD_RAW:-${PARSED_DB_PASSWORD:-$DEFAULT_DB_PASSWORD}}"

SQLALCHEMY_TRACK_MODIFICATIONS="${SQLALCHEMY_TRACK_MODIFICATIONS:-${VECTOPLAN_LIBRARY_SQLALCHEMY_TRACK_MODIFICATIONS:-false}}"
SQLALCHEMY_ECHO="${SQLALCHEMY_ECHO:-${VECTOPLAN_LIBRARY_SQLALCHEMY_ECHO:-false}}"
SQLALCHEMY_RECORD_QUERIES="${SQLALCHEMY_RECORD_QUERIES:-${VECTOPLAN_LIBRARY_SQLALCHEMY_RECORD_QUERIES:-false}}"

VECTOPLAN_LIBRARY_DATABASE_REQUIRED="${VECTOPLAN_LIBRARY_DATABASE_REQUIRED:-true}"
VECTOPLAN_LIBRARY_DB_HEALTH_CHECK="${VECTOPLAN_LIBRARY_DB_HEALTH_CHECK:-false}"

VECTOPLAN_LIBRARY_DB_WAIT_FOR_READY="${VECTOPLAN_LIBRARY_DB_WAIT_FOR_READY:-true}"
VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT="${VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT:-60}"
VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL="${VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL:-2}"

VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED="${VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED:-true}"
VECTOPLAN_LIBRARY_DB_AUTO_INIT="${VECTOPLAN_LIBRARY_DB_AUTO_INIT:-true}"
VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE="${VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE:-true}"
VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE="${VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE:-true}"
VECTOPLAN_LIBRARY_DB_MIGRATION_STRICT="${VECTOPLAN_LIBRARY_DB_MIGRATION_STRICT:-true}"
VECTOPLAN_LIBRARY_DB_RECREATE_INCOMPLETE_MIGRATIONS="${VECTOPLAN_LIBRARY_DB_RECREATE_INCOMPLETE_MIGRATIONS:-true}"
VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE_MESSAGE="${VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE_MESSAGE:-auto creative library migration}"

# Alembic-State-Reparatur.
#
# Zweck:
# Wenn die DB bereits `alembic_version = <revision>` enthält, lokal aber keine
# passende Datei in migrations/versions existiert, kann Alembic nicht migrieren:
#
#   Can't locate revision identified by '<revision>'
#
# Für Development wird dann das DB-Schema zurückgesetzt, damit flask db migrate
# automatisch eine neue erste Revision erzeugen kann.
#
# Kein direkter Docker-Volume-Reset:
# Der Container kann sein Docker-Volume nicht löschen. Der sichere, im Container
# ausführbare Reset ist:
#
#   DROP SCHEMA public CASCADE;
#   CREATE SCHEMA public;
#
# Das entfernt Tabellen und alembic_version aus der Datenbank.
VECTOPLAN_LIBRARY_DB_RESET_ON_MISSING_REVISION="${VECTOPLAN_LIBRARY_DB_RESET_ON_MISSING_REVISION:-true}"
VECTOPLAN_LIBRARY_DB_ALLOW_DESTRUCTIVE_RESET="${VECTOPLAN_LIBRARY_DB_ALLOW_DESTRUCTIVE_RESET:-auto}"
VECTOPLAN_LIBRARY_DB_RESET_STRATEGY="${VECTOPLAN_LIBRARY_DB_RESET_STRATEGY:-schema}"

VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY="${VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY:-${ALEMBIC_MIGRATIONS_DIRECTORY:-${MIGRATIONS_DIRECTORY:-$DEFAULT_MIGRATIONS_DIRECTORY}}}"
ALEMBIC_MIGRATIONS_DIRECTORY="${ALEMBIC_MIGRATIONS_DIRECTORY:-$VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY}"
MIGRATIONS_DIRECTORY="${MIGRATIONS_DIRECTORY:-$VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY}"

FLASK_APP="${FLASK_APP:-wsgi:app}"
FLASK_ENV="${FLASK_ENV:-$VECTOPLAN_LIBRARY_CONFIG}"


# -----------------------------------------------------------------------------
# Normalisierung der Umgebungsvariablen
# -----------------------------------------------------------------------------

VECTOPLAN_LIBRARY_PORT="$(ensure_port "$VECTOPLAN_LIBRARY_PORT")"
GUNICORN_WORKERS="$(ensure_uint "$GUNICORN_WORKERS" "GUNICORN_WORKERS" "$DEFAULT_GUNICORN_WORKERS")"
GUNICORN_THREADS="$(ensure_uint "$GUNICORN_THREADS" "GUNICORN_THREADS" "$DEFAULT_GUNICORN_THREADS")"
GUNICORN_TIMEOUT="$(ensure_uint "$GUNICORN_TIMEOUT" "GUNICORN_TIMEOUT" "$DEFAULT_GUNICORN_TIMEOUT")"
GUNICORN_KEEPALIVE="$(ensure_uint "$GUNICORN_KEEPALIVE" "GUNICORN_KEEPALIVE" "$DEFAULT_GUNICORN_KEEPALIVE")"
GUNICORN_LOG_LEVEL="$(normalize_log_level "$GUNICORN_LOG_LEVEL")"

VECTOPLAN_LIBRARY_SCAN_MAX_DEPTH="$(ensure_uint "$VECTOPLAN_LIBRARY_SCAN_MAX_DEPTH" "VECTOPLAN_LIBRARY_SCAN_MAX_DEPTH" "12")"
VECTOPLAN_LIBRARY_CACHE_TTL_SECONDS="$(ensure_uint "$VECTOPLAN_LIBRARY_CACHE_TTL_SECONDS" "VECTOPLAN_LIBRARY_CACHE_TTL_SECONDS" "5")"

VECTOPLAN_LIBRARY_DB_PORT="$(ensure_uint "$VECTOPLAN_LIBRARY_DB_PORT" "VECTOPLAN_LIBRARY_DB_PORT" "$DEFAULT_DB_PORT")"
VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT="$(ensure_uint "$VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT" "VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT" "60")"
VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL="$(ensure_uint "$VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL" "VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL" "2")"

if [ "$VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL" -lt 1 ]; then
  VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL="1"
fi


# -----------------------------------------------------------------------------
# Exporte
# -----------------------------------------------------------------------------

export APP_NAME
export APP_DISPLAY_NAME
export APP_HOME

export VECTOPLAN_LIBRARY_HOST
export VECTOPLAN_LIBRARY_PORT
export VECTOPLAN_LIBRARY_CONFIG
export VECTOPLAN_LIBRARY_RUN_MODE
export VECTOPLAN_LIBRARY_PRESTART_CHECK
export VECTOPLAN_LIBRARY_PRESTART_CREATE_APP
export VECTOPLAN_LIBRARY_STARTUP_STRICT
export VECTOPLAN_LIBRARY_PRINT_STARTUP_SUMMARY

export VPLIB_SERVICE_ROOT
export VPLIB_SRC_ROOT
export VPLIB_SOURCE_ROOT
export VPLIB_LIBRARY_CATALOG_ROOT
export VPLIB_GENERATED_ROOT
export VPLIB_ARCHIVE_ROOT
export VPLIB_TEST_OUTPUT_ROOT
export VPLIB_ROUTE_PREFIX
export VPLIB_DRY_RUN_DEFAULT
export VPLIB_TEST_ROUTE_ENABLED
export VPLIB_CREATE_ROUTE_ENABLED
export VPLIB_CREATE_WRITE_ENABLED
export VPLIB_CREATE_OVERWRITE_ENABLED
export VPLIB_DEFAULT_WRITE_MODE
export VPLIB_DEFAULT_VALIDATION_MODE

export VECTOPLAN_LIBRARY_SERVICE_ROOT
export VECTOPLAN_LIBRARY_SRC_ROOT
export VECTOPLAN_LIBRARY_PACKAGE_ROOT
export VECTOPLAN_LIBRARY_SOURCE_ROOT
export VECTOPLAN_LIBRARY_CREATIVE_ROOT
export VECTOPLAN_LIBRARY_GENERATED_ROOT
export VECTOPLAN_LIBRARY_CACHE_ROOT
export VECTOPLAN_LIBRARY_ROUTE_PREFIX

export LIBRARY_SERVICE_ROOT
export LIBRARY_SRC_ROOT
export LIBRARY_PACKAGE_ROOT
export LIBRARY_SOURCE_ROOT
export LIBRARY_CREATIVE_ROOT
export LIBRARY_GENERATED_ROOT
export LIBRARY_CACHE_ROOT
export LIBRARY_ROUTE_PREFIX

export VECTOPLAN_LIBRARY_SCAN_RECURSIVE
export VECTOPLAN_LIBRARY_SCAN_MAX_DEPTH
export VECTOPLAN_LIBRARY_SCAN_FOLLOW_SYMLINKS
export VECTOPLAN_LIBRARY_INCLUDE_INVALID_IN_SCAN
export VECTOPLAN_LIBRARY_AUTO_SCAN_ON_REQUEST
export VECTOPLAN_LIBRARY_FAIL_ON_DUPLICATE_IDS
export VECTOPLAN_LIBRARY_TREAT_MISSING_SOURCE_ROOT_AS_EMPTY
export VECTOPLAN_LIBRARY_LIST_INCLUDE_INVALID
export VECTOPLAN_LIBRARY_DETAIL_INCLUDE_RAW_DOCUMENTS
export VECTOPLAN_LIBRARY_DETAIL_INCLUDE_VALIDATION_REPORT
export VECTOPLAN_LIBRARY_CACHE_ENABLED
export VECTOPLAN_LIBRARY_CACHE_TTL_SECONDS

export VECTOPLAN_LIBRARY_DATABASE_DRIVER
export VECTOPLAN_LIBRARY_DB_HOST
export VECTOPLAN_LIBRARY_DB_PORT
export VECTOPLAN_LIBRARY_DB_NAME
export VECTOPLAN_LIBRARY_DB_USER
export VECTOPLAN_LIBRARY_DB_PASSWORD
export VECTOPLAN_LIBRARY_DATABASE_URI
export VECTOPLAN_LIBRARY_DATABASE_URL
export VPLIB_DATABASE_URL
export SQLALCHEMY_DATABASE_URI
export DATABASE_URL
export SQLALCHEMY_TRACK_MODIFICATIONS
export SQLALCHEMY_ECHO
export SQLALCHEMY_RECORD_QUERIES
export VECTOPLAN_LIBRARY_DATABASE_REQUIRED
export VECTOPLAN_LIBRARY_DB_HEALTH_CHECK
export VECTOPLAN_LIBRARY_DB_WAIT_FOR_READY
export VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT
export VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL
export VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED
export VECTOPLAN_LIBRARY_DB_AUTO_INIT
export VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE
export VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE
export VECTOPLAN_LIBRARY_DB_MIGRATION_STRICT
export VECTOPLAN_LIBRARY_DB_RECREATE_INCOMPLETE_MIGRATIONS
export VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE_MESSAGE
export VECTOPLAN_LIBRARY_DB_RESET_ON_MISSING_REVISION
export VECTOPLAN_LIBRARY_DB_ALLOW_DESTRUCTIVE_RESET
export VECTOPLAN_LIBRARY_DB_RESET_STRATEGY
export VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY
export ALEMBIC_MIGRATIONS_DIRECTORY
export MIGRATIONS_DIRECTORY
export FLASK_APP
export FLASK_ENV

export PYTHONDONTWRITEBYTECODE="${PYTHONDONTWRITEBYTECODE:-1}"
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"

# src zuerst, damit config, routes, services, vplib und library bevorzugt gefunden werden.
export PYTHONPATH="$APP_HOME/src:$APP_HOME:${PYTHONPATH:-}"


# -----------------------------------------------------------------------------
# Arbeitsverzeichnis setzen
# -----------------------------------------------------------------------------

if [ ! -d "$APP_HOME" ]; then
  die "APP_HOME existiert nicht: ${APP_HOME}"
fi

cd "$APP_HOME" || die "Wechsel in APP_HOME fehlgeschlagen: ${APP_HOME}"


# -----------------------------------------------------------------------------
# Grundlegende Werkzeugprüfung
# -----------------------------------------------------------------------------

command_exists python || die "'python' ist im Container nicht verfügbar."
command_exists gunicorn || log_warn "'gunicorn' ist nicht im PATH verfügbar. Direkter Gunicorn-Start würde scheitern."

log_info "Arbeitsverzeichnis: $(safe_pwd)"
log_info "Python: $(python --version 2>/dev/null || printf '%s' 'unbekannt')"


# -----------------------------------------------------------------------------
# Runtime-Verzeichnisse vorbereiten
# -----------------------------------------------------------------------------

prepare_runtime_directories() {
  ensure_dir "$VPLIB_SOURCE_ROOT"
  ensure_dir "$VPLIB_LIBRARY_CATALOG_ROOT"
  ensure_dir "$VPLIB_GENERATED_ROOT"
  ensure_dir "$VPLIB_ARCHIVE_ROOT"
  ensure_dir "$VPLIB_TEST_OUTPUT_ROOT"

  ensure_dir "$VECTOPLAN_LIBRARY_SOURCE_ROOT"
  ensure_dir "$VECTOPLAN_LIBRARY_CREATIVE_ROOT"
  ensure_dir "$VECTOPLAN_LIBRARY_GENERATED_ROOT"
  ensure_dir "$VECTOPLAN_LIBRARY_CACHE_ROOT"

  # migrations/ wird bewusst nur vorbereitet, wenn es bereits existiert.
  # `flask db init` soll es bei Bedarf selbst anlegen.
  if [ -d "$VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY" ]; then
    ensure_dir "$VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY"
  fi
}


# -----------------------------------------------------------------------------
# Projektstruktur prüfen
# -----------------------------------------------------------------------------

run_structure_check() {
  missing=0

  require_file_any "Flask-App-Factory" "./app.py" || missing=$((missing + 1))
  require_file_any "WSGI-Einstiegspunkt" "./wsgi.py" || missing=$((missing + 1))
  require_file_any "Requirements" "./requirements.txt" || missing=$((missing + 1))
  require_file_any "Entrypoint" "./entrypoint.sh" || missing=$((missing + 1))

  require_file_any "Service-Konfiguration" "./config.py" "./src/config/__init__.py" || missing=$((missing + 1))
  require_file_any "Extensions" "./extensions.py" "./src/extensions.py" || missing=$((missing + 1))
  require_file_any "VPLIB Settings" "./src/config/vplib_settings.py" "./config/vplib_settings.py" || missing=$((missing + 1))
  require_file_any "Library Settings" "./src/config/library_settings.py" "./config/library_settings.py" || missing=$((missing + 1))

  require_file_any "Blueprint-Registrierung" "./src/routes/__init__.py" "./routes/__init__.py" || missing=$((missing + 1))
  require_file_any "VPLIB Routes" "./src/routes/vplib_routes.py" "./routes/vplib_routes.py" || missing=$((missing + 1))
  require_file_any "Library Routes" "./src/routes/library_routes.py" "./routes/library_routes.py" || missing=$((missing + 1))
  require_file_any "Create Routes" "./src/routes/create.py" "./routes/create.py" || missing=$((missing + 1))

  require_file_any "VPLIB Route Service" "./src/services/vplib_route_service.py" "./services/vplib_route_service.py" || missing=$((missing + 1))
  require_file_any "Library Route Service" "./src/services/library_route_service.py" "./services/library_route_service.py" || missing=$((missing + 1))
  require_file_any "Create Route Service" "./src/services/library_create_route_service.py" "./services/library_create_route_service.py" || missing=$((missing + 1))

  require_file_any "DB Models Package" "./models/__init__.py" "./src/models/__init__.py" || missing=$((missing + 1))
  require_file_any "Creative Library DB Models" "./models/creative_library.py" "./src/models/creative_library.py" || missing=$((missing + 1))

  require_dir_any "VPLIB Core Package" "./src/vplib" || missing=$((missing + 1))
  require_dir_any "Creative Library Package" "./src/library" || missing=$((missing + 1))
  require_dir_any "Creative Library Domain Package" "./src/library/domain" || missing=$((missing + 1))
  require_dir_any "Creative Library Scanner Package" "./src/library/scanner" || missing=$((missing + 1))
  require_dir_any "Creative Library Validation Package" "./src/library/validation" || missing=$((missing + 1))
  require_dir_any "Creative Library Read Models Package" "./src/library/read_models" || missing=$((missing + 1))
  require_dir_any "Creative Library Services Package" "./src/library/services" || missing=$((missing + 1))

  warn_if_missing_dir_any "Creative Library Source Root" "./src/library/source" "$VECTOPLAN_LIBRARY_SOURCE_ROOT"
  warn_if_missing_dir_any "Migrations Directory" "./migrations" "$VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY"

  if [ "$missing" -gt 0 ]; then
    return 1
  fi

  return 0
}


# -----------------------------------------------------------------------------
# Datenbank-Wait / Flask-Migrate
# -----------------------------------------------------------------------------

database_configured() {
  [ -n "${SQLALCHEMY_DATABASE_URI:-}" ]
}

wait_for_database_with_pg_isready() {
  elapsed="0"

  while true; do
    if pg_isready \
      -h "$VECTOPLAN_LIBRARY_DB_HOST" \
      -p "$VECTOPLAN_LIBRARY_DB_PORT" \
      -U "$VECTOPLAN_LIBRARY_DB_USER" \
      -d "$VECTOPLAN_LIBRARY_DB_NAME" \
      >/dev/null 2>&1; then
      log_info "PostgreSQL ist bereit: ${VECTOPLAN_LIBRARY_DB_HOST}:${VECTOPLAN_LIBRARY_DB_PORT}/${VECTOPLAN_LIBRARY_DB_NAME}"
      return 0
    fi

    if [ "$elapsed" -ge "$VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT" ]; then
      log_error "Timeout beim Warten auf PostgreSQL nach ${elapsed}s."
      return 1
    fi

    log_info "Warte auf PostgreSQL (${elapsed}s/${VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT}s): ${VECTOPLAN_LIBRARY_DB_HOST}:${VECTOPLAN_LIBRARY_DB_PORT}/${VECTOPLAN_LIBRARY_DB_NAME}"
    sleep "$VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL"
    elapsed=$((elapsed + VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL))
  done
}

wait_for_database_with_python_socket() {
  elapsed="0"

  while true; do
    if python <<'PY' >/dev/null 2>&1
import os
import socket
import sys

host = os.getenv("VECTOPLAN_LIBRARY_DB_HOST", "vectoplan-library-db")
port = int(os.getenv("VECTOPLAN_LIBRARY_DB_PORT", "5432"))

try:
    with socket.create_connection((host, port), timeout=3):
        pass
except Exception:
    sys.exit(1)

sys.exit(0)
PY
    then
      log_info "Datenbank-Port ist erreichbar: ${VECTOPLAN_LIBRARY_DB_HOST}:${VECTOPLAN_LIBRARY_DB_PORT}"
      return 0
    fi

    if [ "$elapsed" -ge "$VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT" ]; then
      log_error "Timeout beim Warten auf Datenbank-Port nach ${elapsed}s."
      return 1
    fi

    log_info "Warte auf Datenbank-Port (${elapsed}s/${VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT}s): ${VECTOPLAN_LIBRARY_DB_HOST}:${VECTOPLAN_LIBRARY_DB_PORT}"
    sleep "$VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL"
    elapsed=$((elapsed + VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL))
  done
}

wait_for_database() {
  if ! database_configured; then
    if is_true "$VECTOPLAN_LIBRARY_DATABASE_REQUIRED"; then
      log_error "Keine SQLALCHEMY_DATABASE_URI konfiguriert, aber VECTOPLAN_LIBRARY_DATABASE_REQUIRED=true."
      return 1
    fi

    log_warn "Keine SQLALCHEMY_DATABASE_URI konfiguriert. Datenbank-Wait wird übersprungen."
    return 0
  fi

  if database_uri_is_sqlite "$SQLALCHEMY_DATABASE_URI"; then
    log_info "SQLite-URI erkannt. Datenbank-Wait wird übersprungen."
    return 0
  fi

  if ! database_uri_is_postgres "$SQLALCHEMY_DATABASE_URI"; then
    log_warn "Nicht-PostgreSQL-URI erkannt. Datenbank-Wait wird übersprungen: $(mask_uri "$SQLALCHEMY_DATABASE_URI")"
    return 0
  fi

  if ! is_true "$VECTOPLAN_LIBRARY_DB_WAIT_FOR_READY"; then
    log_warn "Datenbank-Wait wurde deaktiviert."
    return 0
  fi

  if command_exists pg_isready; then
    wait_for_database_with_pg_isready
    return $?
  fi

  log_warn "'pg_isready' ist nicht verfügbar. Fallback auf Python-Socket-Check."
  wait_for_database_with_python_socket
}

migrations_dir_has_env() {
  [ -f "${VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY}/env.py" ]
}

migration_versions_dir() {
  printf '%s/versions' "$VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY"
}

count_migration_version_files() {
  versions_dir="$(migration_versions_dir)"

  if [ ! -d "$versions_dir" ]; then
    printf '%s' "0"
    return 0
  fi

  count="$(find "$versions_dir" -maxdepth 1 -type f -name '*.py' ! -name '__init__.py' 2>/dev/null | wc -l | tr -d '[:space:]')"

  if [ -z "$count" ]; then
    printf '%s' "0"
    return 0
  fi

  printf '%s' "$count"
}

migration_versions_exist() {
  [ "$(count_migration_version_files)" -gt 0 ]
}

list_migration_version_files() {
  versions_dir="$(migration_versions_dir)"

  if [ ! -d "$versions_dir" ]; then
    return 0
  fi

  find "$versions_dir" -maxdepth 1 -type f -name '*.py' ! -name '__init__.py' -printf '%f\n' 2>/dev/null | sort || true
}

local_revision_exists() {
  revision_id="${1:-}"
  versions_dir="$(migration_versions_dir)"

  if [ -z "$revision_id" ]; then
    return 1
  fi

  if [ ! -d "$versions_dir" ]; then
    return 1
  fi

  if find "$versions_dir" -maxdepth 1 -type f \( -name "${revision_id}_*.py" -o -name "*${revision_id}*.py" \) 2>/dev/null | grep -q .; then
    return 0
  fi

  if grep -R "revision[[:space:]]*=[[:space:]]*['\"]${revision_id}['\"]" "$versions_dir"/*.py >/dev/null 2>&1; then
    return 0
  fi

  return 1
}

migrations_dir_contains_only_empty_versions() {
  dir_path="$1"

  if [ ! -d "$dir_path" ]; then
    return 1
  fi

  if [ ! -d "${dir_path}/versions" ]; then
    return 1
  fi

  if find "${dir_path}/versions" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
    return 1
  fi

  if find "$dir_path" \
      -mindepth 1 \
      ! -path "${dir_path}/versions" \
      ! -path "${dir_path}/versions/*" \
      -print -quit 2>/dev/null | grep -q .; then
    return 1
  fi

  return 0
}

prepare_migrations_directory_for_init() {
  dir_path="$VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY"

  if [ ! -d "$dir_path" ]; then
    return 0
  fi

  if migrations_dir_has_env; then
    return 0
  fi

  if migrations_dir_contains_only_empty_versions "$dir_path"; then
    log_warn "Migrations-Verzeichnis enthält nur leeres versions/-Gerüst. Entferne es, damit 'flask db init' sauber laufen kann: ${dir_path}"
    rm -rf "$dir_path"
    return 0
  fi

  if is_true "$VECTOPLAN_LIBRARY_DB_RECREATE_INCOMPLETE_MIGRATIONS"; then
    backup_path="${dir_path}.incomplete.$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || printf '%s' backup)"
    log_warn "Unvollständiges migrations-Verzeichnis ohne env.py wird verschoben: ${dir_path} -> ${backup_path}"
    mv "$dir_path" "$backup_path"
    return 0
  fi

  log_error "Migrations-Verzeichnis existiert, aber env.py fehlt: ${dir_path}. Setze VECTOPLAN_LIBRARY_DB_RECREATE_INCOMPLETE_MIGRATIONS=true oder bereinige den Ordner."
  return 1
}

get_database_alembic_revision() {
  python <<'PY' 2>/dev/null || true
import os
import sys

from sqlalchemy import create_engine, text

uri = (
    os.getenv("SQLALCHEMY_DATABASE_URI")
    or os.getenv("VECTOPLAN_LIBRARY_DATABASE_URI")
    or os.getenv("DATABASE_URL")
)

if not uri:
    print("")
    sys.exit(0)

if uri.startswith("postgres://"):
    uri = "postgresql://" + uri[len("postgres://"):]

try:
    engine = create_engine(uri, pool_pre_ping=True)
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
        if not exists:
            print("")
            sys.exit(0)

        revision = conn.execute(text("SELECT version_num FROM public.alembic_version LIMIT 1")).scalar()
        print(str(revision or "").strip())
except Exception:
    print("")
    sys.exit(0)
PY
}

destructive_database_reset_allowed() {
  if ! is_true "$VECTOPLAN_LIBRARY_DB_RESET_ON_MISSING_REVISION"; then
    return 1
  fi

  case "${VECTOPLAN_LIBRARY_DB_ALLOW_DESTRUCTIVE_RESET:-auto}" in
    1|true|TRUE|True|yes|YES|Yes|y|Y|on|ON|On|enabled|ENABLED|Enabled)
      return 0
      ;;
    0|false|FALSE|False|no|NO|No|n|N|off|OFF|Off|disabled|DISABLED|Disabled)
      return 1
      ;;
    auto|AUTO|Auto|"")
      if is_development_like_config; then
        return 0
      fi

      return 1
      ;;
    *)
      return 1
      ;;
  esac
}

reset_database_schema_for_alembic_repair() {
  reason="${1:-unknown}"

  if [ "${VECTOPLAN_LIBRARY_DB_RESET_STRATEGY:-schema}" != "schema" ]; then
    log_error "Nicht unterstützte DB-Reset-Strategie: ${VECTOPLAN_LIBRARY_DB_RESET_STRATEGY}. Unterstützt ist aktuell nur: schema."
    return 1
  fi

  log_warn "Alembic-State-Reparatur aktiviert. Grund: ${reason}"
  log_warn "PostgreSQL-Schema 'public' wird vollständig zurückgesetzt."
  log_warn "Dies löscht alle Tabellen im Schema public inklusive alembic_version."
  log_warn "Danach erzeugt 'flask db migrate' automatisch eine neue erste Revision."

  python <<'PY'
import os
import sys

from sqlalchemy import create_engine, text

uri = (
    os.getenv("SQLALCHEMY_DATABASE_URI")
    or os.getenv("VECTOPLAN_LIBRARY_DATABASE_URI")
    or os.getenv("DATABASE_URL")
)

if not uri:
    print("[vectoplan-library] Keine Datenbank-URI für Reset vorhanden.", file=sys.stderr)
    sys.exit(1)

if uri.startswith("postgres://"):
    uri = "postgresql://" + uri[len("postgres://"):]

try:
    engine = create_engine(uri, isolation_level="AUTOCOMMIT", pool_pre_ping=True)

    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))

    print("[vectoplan-library] PostgreSQL schema public reset completed.")
    sys.exit(0)

except Exception as exc:
    print(f"[vectoplan-library] PostgreSQL schema reset failed: {exc!r}", file=sys.stderr)
    sys.exit(1)
PY
}

check_and_repair_alembic_state() {
  if ! migrations_dir_has_env; then
    log_info "Alembic-State-Prüfung übersprungen, weil migrations/env.py noch fehlt."
    return 0
  fi

  db_revision="$(get_database_alembic_revision)"
  local_version_count="$(count_migration_version_files)"

  if [ -z "$db_revision" ]; then
    log_info "Datenbank enthält keine alembic_version. Alembic-State ist für Initialmigration frei."
    return 0
  fi

  if local_revision_exists "$db_revision"; then
    log_info "Alembic-State konsistent. DB-Revision existiert lokal: ${db_revision}"
    return 0
  fi

  log_warn "Alembic-State-Mismatch erkannt."
  log_warn "Datenbank verweist auf Revision: ${db_revision}"
  log_warn "Lokale Migration-Versionen: ${local_version_count}"
  log_warn "Keine lokale revisions-Datei passt zur DB-Revision ${db_revision}."

  if [ "$local_version_count" -eq 0 ]; then
    log_warn "Es existiert keine einzige lokale revisions-Datei. Das ist der typische Fall nach nicht persistiertem migrations/versions-Ordner bei erhaltenem DB-Volume."
  else
    log_warn "Es existieren lokale revisions-Dateien, aber nicht die von der DB referenzierte Revision."
    log_warn "Lokale Versionen:"
    list_migration_version_files | while IFS= read -r version_file; do
      [ -n "$version_file" ] && log_warn "  - ${version_file}"
    done
  fi

  if ! destructive_database_reset_allowed; then
    log_error "Automatischer DB-Reset ist nicht erlaubt."
    log_error "Setze für Development entweder VECTOPLAN_LIBRARY_CONFIG=development oder explizit VECTOPLAN_LIBRARY_DB_ALLOW_DESTRUCTIVE_RESET=true."
    log_error "Alternativ fehlende Migration-Datei wiederherstellen oder DB-Volume extern löschen."
    return 1
  fi

  if ! reset_database_schema_for_alembic_repair "missing local revision for DB alembic_version ${db_revision}"; then
    return 1
  fi

  repaired_revision="$(get_database_alembic_revision)"

  if [ -n "$repaired_revision" ]; then
    log_error "DB-Reset wurde ausgeführt, aber alembic_version ist weiterhin vorhanden: ${repaired_revision}"
    return 1
  fi

  log_info "Alembic-State wurde repariert. Datenbank ist migrationsseitig leer und bereit für automatische Migration."
  return 0
}

check_flask_metadata_ready() {
  log_info "Prüfe, ob SQLAlchemy-Modelle in db.metadata sichtbar sind."

  python <<'PY'
import os
import sys

try:
    from app import create_app

    config_name = os.getenv("VECTOPLAN_LIBRARY_CONFIG", "production")
    app = create_app(config_name)

    with app.app_context():
        import models
        from extensions import db

        model_classes = models.import_all_models(strict=True)
        table_names = sorted(str(name) for name in db.metadata.tables.keys())

        print(f"[vectoplan-library] SQLAlchemy model classes: {len(model_classes)}")
        print(f"[vectoplan-library] SQLAlchemy metadata tables: {len(table_names)}")
        for table_name in table_names:
            print(f"[vectoplan-library] SQLAlchemy table: {table_name}")

        if not model_classes:
            print("[vectoplan-library] Keine Modelklassen importiert.", file=sys.stderr)
            sys.exit(2)

        if not table_names:
            print("[vectoplan-library] db.metadata enthält keine Tabellen.", file=sys.stderr)
            sys.exit(3)

except Exception as exc:
    print(f"[vectoplan-library] SQLAlchemy metadata check failed: {exc!r}", file=sys.stderr)
    sys.exit(1)
PY
}

run_flask_db_init_if_needed() {
  if ! is_true "$VECTOPLAN_LIBRARY_DB_AUTO_INIT"; then
    log_info "flask db init ist deaktiviert."
    return 0
  fi

  if migrations_dir_has_env; then
    log_info "Migrations-Umgebung existiert bereits: ${VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY}/env.py"
    return 0
  fi

  if ! prepare_migrations_directory_for_init; then
    return 1
  fi

  log_info "Initialisiere Flask-Migrate Umgebung mit 'flask db init'."

  if python -m flask db init; then
    log_info "flask db init erfolgreich."
    return 0
  fi

  log_error "flask db init ist fehlgeschlagen."
  return 1
}

run_flask_db_upgrade_if_enabled() {
  upgrade_phase="${1:-upgrade}"

  if ! is_true "$VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE"; then
    log_info "flask db upgrade ist deaktiviert."
    return 0
  fi

  if ! migrations_dir_has_env; then
    log_error "flask db upgrade kann nicht laufen, weil ${VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY}/env.py fehlt."
    return 1
  fi

  if ! migration_versions_exist; then
    log_warn "Keine Migration-Versionen vorhanden. flask db upgrade wird für Phase '${upgrade_phase}' übersprungen."
    return 0
  fi

  if ! check_and_repair_alembic_state; then
    return 1
  fi

  log_info "Wende Datenbankmigrationen mit 'flask db upgrade' an. Phase: ${upgrade_phase}"

  if python -m flask db upgrade; then
    log_info "flask db upgrade erfolgreich. Phase: ${upgrade_phase}"
    return 0
  fi

  log_error "flask db upgrade ist fehlgeschlagen. Phase: ${upgrade_phase}"
  return 1
}

run_flask_db_migrate_once() {
  migrate_message="$1"
  attempt_label="$2"
  before_count="$3"

  log_file="${TMPDIR:-/tmp}/vectoplan-library-flask-db-migrate-${attempt_label}-$$.log"
  rm -f "$log_file" 2>/dev/null || true

  log_info "Starte flask db migrate. Versuch: ${attempt_label}. Versionen vorher: ${before_count}"

  set +e
  python -m flask db migrate -m "$migrate_message" >"$log_file" 2>&1
  migrate_exit="$?"
  set -e

  if [ -f "$log_file" ]; then
    while IFS= read -r line; do
      log_info "flask db migrate: ${line}"
    done < "$log_file"
  fi

  after_count="$(count_migration_version_files)"

  if [ "$migrate_exit" -eq 0 ]; then
    if [ "$after_count" -gt "$before_count" ]; then
      log_info "Neue Migration-Version wurde erzeugt. Versionen vorher: ${before_count}, nachher: ${after_count}"
      log_info "Aktuelle Migration-Versionen:"
      list_migration_version_files | while IFS= read -r version_file; do
        [ -n "$version_file" ] && log_info "  - ${version_file}"
      done
    else
      log_info "Keine Schemaänderung erkannt. Es wurde keine neue versions-Datei erzeugt."
    fi

    rm -f "$log_file" 2>/dev/null || true
    return 0
  fi

  if [ -f "$log_file" ] && grep -qi "No changes in schema detected" "$log_file"; then
    log_info "Keine Schemaänderung erkannt. flask db migrate meldete keine Änderungen. Es wird keine neue Version erzeugt."
    rm -f "$log_file" 2>/dev/null || true
    return 0
  fi

  if [ -f "$log_file" ] && grep -qi "Target database is not up to date" "$log_file"; then
    log_warn "flask db migrate meldet: Target database is not up to date."
    rm -f "$log_file" 2>/dev/null || true
    return 2
  fi

  if [ -f "$log_file" ] && grep -qi "Can't locate revision identified by" "$log_file"; then
    log_warn "flask db migrate meldet: Can't locate revision identified by ..."
    rm -f "$log_file" 2>/dev/null || true
    return 3
  fi

  rm -f "$log_file" 2>/dev/null || true
  log_error "flask db migrate ist fehlgeschlagen. Exit-Code: ${migrate_exit}"
  return 1
}

run_flask_db_migrate_if_enabled() {
  if ! is_true "$VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE"; then
    log_info "flask db migrate ist deaktiviert."
    return 0
  fi

  if ! migrations_dir_has_env; then
    log_error "flask db migrate kann nicht laufen, weil ${VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY}/env.py fehlt."
    return 1
  fi

  if ! check_flask_metadata_ready; then
    log_error "SQLAlchemy-Metadaten sind nicht bereit. Migration wird nicht erzeugt."
    return 1
  fi

  if ! check_and_repair_alembic_state; then
    return 1
  fi

  before_count="$(count_migration_version_files)"

  if [ "$before_count" -eq 0 ]; then
    log_info "Noch keine lokale Alembic-Version vorhanden. Die erste Migration-Version wird automatisch erzeugt."
  else
    log_info "Vorhandene lokale Alembic-Versionen erkannt (${before_count}). Neue Version wird nur bei Schemaänderungen erzeugt."
  fi

  migrate_message="${VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE_MESSAGE} $(timestamp_utc)"

  set +e
  run_flask_db_migrate_once "$migrate_message" "initial" "$before_count"
  migrate_status="$?"
  set -e

  if [ "$migrate_status" -eq 0 ]; then
    return 0
  fi

  if [ "$migrate_status" -eq 2 ]; then
    log_warn "Datenbank ist nicht auf aktuellem Alembic-Stand. Führe upgrade aus und versuche migrate erneut."

    if ! run_flask_db_upgrade_if_enabled "pre-migrate-retry"; then
      return 1
    fi

    before_retry_count="$(count_migration_version_files)"

    set +e
    run_flask_db_migrate_once "$migrate_message" "retry_after_upgrade" "$before_retry_count"
    retry_status="$?"
    set -e

    if [ "$retry_status" -eq 0 ]; then
      return 0
    fi
  fi

  if [ "$migrate_status" -eq 3 ]; then
    log_warn "Alembic-Revision fehlt lokal. Versuche State-Reparatur und danach erneuten migrate-Lauf."

    if ! check_and_repair_alembic_state; then
      return 1
    fi

    before_repair_retry_count="$(count_migration_version_files)"

    set +e
    run_flask_db_migrate_once "$migrate_message" "retry_after_alembic_state_repair" "$before_repair_retry_count"
    repair_retry_status="$?"
    set -e

    if [ "$repair_retry_status" -eq 0 ]; then
      return 0
    fi
  fi

  log_error "flask db migrate konnte nicht abgeschlossen werden."
  return 1
}

run_database_bootstrap() {
  if ! is_true "$VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED"; then
    log_warn "Datenbank-Bootstrap wurde deaktiviert."
    return 0
  fi

  if ! database_configured; then
    if is_true "$VECTOPLAN_LIBRARY_DATABASE_REQUIRED"; then
      handle_database_bootstrap_error "Keine Datenbank-URI konfiguriert."
      return 1
    fi

    log_warn "Keine Datenbank-URI konfiguriert. DB-Bootstrap wird übersprungen."
    return 0
  fi

  log_info "Datenbank-URI: $(mask_uri "$SQLALCHEMY_DATABASE_URI")"
  log_info "Datenbank-Host: ${VECTOPLAN_LIBRARY_DB_HOST}:${VECTOPLAN_LIBRARY_DB_PORT}"
  log_info "Datenbank-Name: ${VECTOPLAN_LIBRARY_DB_NAME}"
  log_info "Migrations-Verzeichnis: ${VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY}"
  log_info "DB Auto Init: ${VECTOPLAN_LIBRARY_DB_AUTO_INIT}"
  log_info "DB Auto Migrate: ${VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE}"
  log_info "DB Auto Upgrade: ${VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE}"
  log_info "DB Reset On Missing Revision: ${VECTOPLAN_LIBRARY_DB_RESET_ON_MISSING_REVISION}"
  log_info "DB Allow Destructive Reset: ${VECTOPLAN_LIBRARY_DB_ALLOW_DESTRUCTIVE_RESET}"
  log_info "DB Reset Strategy: ${VECTOPLAN_LIBRARY_DB_RESET_STRATEGY}"

  if ! wait_for_database; then
    handle_database_bootstrap_error "Datenbank ist nicht bereit."
    return 1
  fi

  if ! command_exists python; then
    handle_database_bootstrap_error "'python' ist nicht verfügbar; DB-Bootstrap nicht möglich."
    return 1
  fi

  if ! python - <<'PY' >/dev/null 2>&1
import flask
import flask_migrate
import flask_sqlalchemy
import sqlalchemy
PY
  then
    handle_database_bootstrap_error "Flask-Migrate/SQLAlchemy-Abhängigkeiten sind nicht vollständig installiert."
    return 1
  fi

  if ! run_flask_db_init_if_needed; then
    handle_database_bootstrap_error "flask db init konnte nicht abgeschlossen werden."
    return 1
  fi

  if ! migrations_dir_has_env; then
    handle_database_bootstrap_error "Migrationsumgebung fehlt nach init weiterhin: ${VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY}/env.py"
    return 1
  fi

  if ! check_and_repair_alembic_state; then
    handle_database_bootstrap_error "Alembic-State-Prüfung/Reparatur konnte nicht abgeschlossen werden."
    return 1
  fi

  version_count_before="$(count_migration_version_files)"

  if [ "$version_count_before" -gt 0 ]; then
    if ! run_flask_db_upgrade_if_enabled "pre-migrate-existing-versions"; then
      handle_database_bootstrap_error "flask db upgrade vor migrate konnte nicht abgeschlossen werden."
      return 1
    fi
  elif ! is_true "$VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE"; then
    handle_database_bootstrap_error "Keine Alembic-Version vorhanden und VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE=false. Die erste Migration kann nicht erzeugt werden."
    return 1
  fi

  if ! run_flask_db_migrate_if_enabled; then
    handle_database_bootstrap_error "flask db migrate konnte nicht abgeschlossen werden."
    return 1
  fi

  if ! run_flask_db_upgrade_if_enabled "post-migrate"; then
    handle_database_bootstrap_error "flask db upgrade nach migrate konnte nicht abgeschlossen werden."
    return 1
  fi

  log_info "Datenbank-Bootstrap abgeschlossen."
  return 0
}


# -----------------------------------------------------------------------------
# Optionaler Python-Prestart-Check
# -----------------------------------------------------------------------------

run_prestart_check() {
  log_info "Starte Python-Prestart-Check."

  python <<'PY'
import importlib
import os
import sys

checks = []

def check_any(label, module_names):
    last_error = None

    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
            checks.append({
                "label": label,
                "ok": True,
                "module": getattr(module, "__name__", module_name),
            })
            return True
        except Exception as exc:
            last_error = exc

    checks.append({
        "label": label,
        "ok": False,
        "modules": list(module_names),
        "error": str(last_error) if last_error else "unknown error",
    })
    return False


def check_settings(label, module_names, getter_name):
    errors = []

    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
            getter = getattr(module, getter_name)
            settings = getter()
            if hasattr(settings, "to_dict"):
                settings.to_dict()
            checks.append({
                "label": label,
                "ok": True,
                "module": module_name,
            })
            return True
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")

    checks.append({
        "label": label,
        "ok": False,
        "modules": list(module_names),
        "errors": errors,
    })
    return False


def check_health(label, module_names, function_names):
    errors = []

    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)

            for function_name in function_names:
                function = getattr(module, function_name, None)
                if not callable(function):
                    continue

                health = function()
                checks.append({
                    "label": label,
                    "ok": bool(health.get("ok", health.get("healthy", True))) if isinstance(health, dict) else True,
                    "module": module_name,
                    "function": function_name,
                })
                return bool(health.get("ok", health.get("healthy", True))) if isinstance(health, dict) else True

            checks.append({
                "label": label,
                "ok": True,
                "module": module_name,
                "note": "module imported; no health function found",
            })
            return True
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")

    checks.append({
        "label": label,
        "ok": False,
        "modules": list(module_names),
        "errors": errors,
    })
    return False


ok = True

# Core app imports
ok = check_any("app", ("app",)) and ok
ok = check_any("wsgi", ("wsgi",)) and ok
ok = check_any("extensions", ("extensions", "src.extensions")) and ok

# DB imports
ok = check_any("flask_sqlalchemy", ("flask_sqlalchemy",)) and ok
ok = check_any("flask_migrate", ("flask_migrate",)) and ok
ok = check_any("sqlalchemy", ("sqlalchemy",)) and ok
ok = check_any("alembic", ("alembic",)) and ok
ok = check_any("psycopg", ("psycopg",)) and ok

# DB models
ok = check_any("models", ("models", "src.models")) and ok
ok = check_any("creative_library_models", ("models.creative_library", "src.models.creative_library")) and ok
ok = check_health(
    "models_health",
    ("models", "src.models"),
    ("get_models_health",),
) and ok

# Route imports
ok = check_any("routes", ("routes", "src.routes")) and ok
ok = check_any("vplib_routes", ("routes.vplib_routes", "src.routes.vplib_routes")) and ok
ok = check_any("library_routes", ("routes.library_routes", "src.routes.library_routes")) and ok
ok = check_any("create_routes", ("routes.create", "src.routes.create")) and ok

# Service imports
ok = check_any("vplib_route_service", ("services.vplib_route_service", "src.services.vplib_route_service")) and ok
ok = check_any("library_route_service", ("services.library_route_service", "src.services.library_route_service")) and ok
ok = check_any("library_create_route_service", ("services.library_create_route_service", "src.services.library_create_route_service")) and ok

# VPLIB imports
ok = check_any("vplib", ("vplib", "src.vplib")) and ok
ok = check_any("vplib_id_service", ("vplib.vplib_id_service", "src.vplib.vplib_id_service")) and ok
ok = check_any("vplib_validators", ("vplib.validators", "src.vplib.validators")) and ok
ok = check_any("vplib_creators", ("vplib.creators", "src.vplib.creators")) and ok
ok = check_any("vplib_sources", ("vplib.sources", "src.vplib.sources")) and ok

# Creative Library imports
ok = check_any("library", ("library", "src.library")) and ok
ok = check_any("library_domain", ("library.domain", "src.library.domain")) and ok
ok = check_any("library_scanner", ("library.scanner", "src.library.scanner")) and ok
ok = check_any("library_validation", ("library.validation", "src.library.validation")) and ok
ok = check_any("library_read_models", ("library.read_models", "src.library.read_models")) and ok
ok = check_any("library_services", ("library.services", "src.library.services")) and ok
ok = check_any("library_scan_service", ("library.services.library_scan_service", "src.library.services.library_scan_service")) and ok
ok = check_any("library_block_service", ("library.services.library_block_service", "src.library.services.library_block_service")) and ok
ok = check_any("library_create_service", ("library.services.library_create_service", "src.library.services.library_create_service")) and ok
ok = check_any("library_db_sync_service", ("library.services.library_db_sync_service", "src.library.services.library_db_sync_service")) and ok
ok = check_any("library_published_service", ("library.services.library_published_service", "src.library.services.library_published_service")) and ok

# Repository imports
ok = check_any("library_repositories", ("library.repositories", "src.library.repositories")) and ok
ok = check_any("library_sql_repositories", ("library.repositories.sql", "src.library.repositories.sql")) and ok

# Settings
ok = check_settings(
    "vplib_settings",
    ("config.vplib_settings", "src.config.vplib_settings"),
    "get_vplib_settings",
) and ok

ok = check_settings(
    "library_settings",
    ("config.library_settings", "src.config.library_settings"),
    "get_library_settings",
) and ok

# Health functions without running scan
ok = check_health(
    "library_health",
    ("library", "src.library"),
    ("get_library_health",),
) and ok

ok = check_health(
    "library_services_health",
    ("library.services", "src.library.services"),
    ("get_services_health",),
) and ok

source_root = os.getenv("VECTOPLAN_LIBRARY_SOURCE_ROOT") or os.getenv("LIBRARY_SOURCE_ROOT")
if source_root:
    checks.append({
        "label": "library_source_root_env",
        "ok": True,
        "path": source_root,
    })

database_uri = os.getenv("SQLALCHEMY_DATABASE_URI") or os.getenv("VECTOPLAN_LIBRARY_DATABASE_URL")
if database_uri:
    checks.append({
        "label": "database_uri_env",
        "ok": True,
        "uri_present": True,
    })

if os.getenv("VECTOPLAN_LIBRARY_PRESTART_CREATE_APP", "false").lower() in {"1", "true", "yes", "y", "on"}:
    try:
        from app import create_app
        config_name = os.getenv("VECTOPLAN_LIBRARY_CONFIG", "production")
        app = create_app(config_name)
        route_rules = sorted(str(rule) for rule in app.url_map.iter_rules())
        required_routes = [
            "/health/ready",
            "/api/v1/vplib/health",
            "/api/v1/vplib/library/health",
            "/api/v1/vplib/library/db/health",
            "/api/v1/vplib/library/scan",
            "/api/v1/vplib/library/sync",
            "/api/v1/vplib/library/blocks",
            "/api/v1/vplib/library/tree",
            "/api/v1/vplib/library/inventory",
            "/create",
            "/api/v1/vplib/create/health",
            "/api/v1/vplib/create/options",
        ]
        missing_routes = [route for route in required_routes if route not in route_rules]
        checks.append({
            "label": "create_app",
            "ok": not missing_routes,
            "config": config_name,
            "missing_routes": missing_routes,
            "route_count": len(route_rules),
        })
        if missing_routes:
            ok = False
    except Exception as exc:
        checks.append({
            "label": "create_app",
            "ok": False,
            "error": repr(exc),
        })
        ok = False

for check in checks:
    if check.get("ok"):
        extra = check.get("module") or check.get("config") or check.get("path") or ""
        print(f"[vectoplan-library] Prestart OK   {check['label']} {extra}")
    else:
        print(f"[vectoplan-library] Prestart FAIL {check['label']} -> {check}", file=sys.stderr)

sys.exit(0 if ok else 1)
PY
}


# -----------------------------------------------------------------------------
# Startzusammenfassung
# -----------------------------------------------------------------------------

print_startup_summary() {
  if ! is_true "$VECTOPLAN_LIBRARY_PRINT_STARTUP_SUMMARY"; then
    return 0
  fi

  log_info "Service: ${APP_NAME}"
  log_info "Startmodus: ${VECTOPLAN_LIBRARY_RUN_MODE}"
  log_info "Config: ${VECTOPLAN_LIBRARY_CONFIG}"
  log_info "Bind: ${VECTOPLAN_LIBRARY_HOST}:${VECTOPLAN_LIBRARY_PORT}"
  log_info "Gunicorn App: ${GUNICORN_APP}"
  log_info "Gunicorn Workers: ${GUNICORN_WORKERS}"
  log_info "Gunicorn Threads: ${GUNICORN_THREADS}"
  log_info "Gunicorn Timeout: ${GUNICORN_TIMEOUT}"
  log_info "Gunicorn Keepalive: ${GUNICORN_KEEPALIVE}"
  log_info "Gunicorn Log-Level: ${GUNICORN_LOG_LEVEL}"
  log_info "PYTHONPATH: ${PYTHONPATH}"

  log_info "VPLIB Route Prefix: ${VPLIB_ROUTE_PREFIX}"
  log_info "VPLIB Source Root: ${VPLIB_SOURCE_ROOT}"
  log_info "VPLIB Library Catalog Root: ${VPLIB_LIBRARY_CATALOG_ROOT}"
  log_info "VPLIB Generated Root: ${VPLIB_GENERATED_ROOT}"
  log_info "VPLIB Test Output Root: ${VPLIB_TEST_OUTPUT_ROOT}"

  log_info "Creative Library Route Prefix: ${VECTOPLAN_LIBRARY_ROUTE_PREFIX}"
  log_info "Creative Library Package Root: ${VECTOPLAN_LIBRARY_PACKAGE_ROOT}"
  log_info "Creative Library Source Root: ${VECTOPLAN_LIBRARY_SOURCE_ROOT}"
  log_info "Creative Library Creative Root: ${VECTOPLAN_LIBRARY_CREATIVE_ROOT}"
  log_info "Creative Library Generated Root: ${VECTOPLAN_LIBRARY_GENERATED_ROOT}"
  log_info "Creative Library Cache Root: ${VECTOPLAN_LIBRARY_CACHE_ROOT}"
  log_info "Creative Library Cache Enabled: ${VECTOPLAN_LIBRARY_CACHE_ENABLED}"
  log_info "Creative Library Scan Max Depth: ${VECTOPLAN_LIBRARY_SCAN_MAX_DEPTH}"

  log_info "Database Required: ${VECTOPLAN_LIBRARY_DATABASE_REQUIRED}"
  log_info "Database URI: $(mask_uri "$SQLALCHEMY_DATABASE_URI")"
  log_info "Database Wait: ${VECTOPLAN_LIBRARY_DB_WAIT_FOR_READY}"
  log_info "Database Bootstrap: ${VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED}"
  log_info "Database Auto Init: ${VECTOPLAN_LIBRARY_DB_AUTO_INIT}"
  log_info "Database Auto Migrate: ${VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE}"
  log_info "Database Auto Upgrade: ${VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE}"
  log_info "Database Reset On Missing Revision: ${VECTOPLAN_LIBRARY_DB_RESET_ON_MISSING_REVISION}"
  log_info "Database Allow Destructive Reset: ${VECTOPLAN_LIBRARY_DB_ALLOW_DESTRUCTIVE_RESET}"
  log_info "Database Reset Strategy: ${VECTOPLAN_LIBRARY_DB_RESET_STRATEGY}"
  log_info "Migrations Directory: ${VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY}"
  log_info "Migration Version Count: $(count_migration_version_files)"
}


# -----------------------------------------------------------------------------
# Startmodi
# -----------------------------------------------------------------------------

start_gunicorn() {
  command_exists gunicorn || die "'gunicorn' ist nicht installiert oder nicht im PATH."

  log_info "Starte ${APP_DISPLAY_NAME} über Gunicorn."

  exec gunicorn \
    --bind "${VECTOPLAN_LIBRARY_HOST}:${VECTOPLAN_LIBRARY_PORT}" \
    --workers "${GUNICORN_WORKERS}" \
    --threads "${GUNICORN_THREADS}" \
    --timeout "${GUNICORN_TIMEOUT}" \
    --keep-alive "${GUNICORN_KEEPALIVE}" \
    --log-level "${GUNICORN_LOG_LEVEL}" \
    --access-logfile "${GUNICORN_ACCESSLOG}" \
    --error-logfile "${GUNICORN_ERRORLOG}" \
    "${GUNICORN_APP}"
}

start_python_wsgi() {
  log_warn "Starte ${APP_DISPLAY_NAME} im Python-Direktmodus. Dies ist primär für Entwicklung gedacht."
  exec python ./wsgi.py
}


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main() {
  prepare_runtime_directories
  print_startup_summary

  if is_true "$VECTOPLAN_LIBRARY_PRESTART_CHECK"; then
    log_info "Prestart-Strukturprüfung wird ausgeführt."

    if ! run_structure_check; then
      die "Prestart-Strukturprüfung ist fehlgeschlagen."
    fi
  else
    log_warn "Prestart-Strukturprüfung wurde per ENV übersprungen."
  fi

  if ! run_database_bootstrap; then
    if is_true "$VECTOPLAN_LIBRARY_STARTUP_STRICT"; then
      die "Datenbank-Bootstrap ist fehlgeschlagen."
    fi

    log_warn "Datenbank-Bootstrap ist fehlgeschlagen, aber VECTOPLAN_LIBRARY_STARTUP_STRICT=false; Start wird fortgesetzt."
  fi

  if is_true "$VECTOPLAN_LIBRARY_PRESTART_CHECK"; then
    if ! run_prestart_check; then
      if is_true "$VECTOPLAN_LIBRARY_STARTUP_STRICT"; then
        die "Python-Prestart-Check ist fehlgeschlagen."
      fi

      log_warn "Python-Prestart-Check ist fehlgeschlagen, aber VECTOPLAN_LIBRARY_STARTUP_STRICT=false; Start wird fortgesetzt."
    fi
  fi

  if [ "$#" -gt 0 ]; then
    log_info "Benutzerdefiniertes Kommando erkannt. Übergabe an exec: $*"
    exec "$@"
  fi

  case "$VECTOPLAN_LIBRARY_RUN_MODE" in
    gunicorn)
      start_gunicorn
      ;;
    python|wsgi)
      start_python_wsgi
      ;;
    *)
      die "Unbekannter VECTOPLAN_LIBRARY_RUN_MODE: ${VECTOPLAN_LIBRARY_RUN_MODE}. Erlaubt sind: gunicorn, python, wsgi."
      ;;
  esac
}

main "$@"