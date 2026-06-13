# services/vectoplan-library/Dockerfile

# -----------------------------------------------------------------------------
# VECTOPLAN Library - Dockerfile
# -----------------------------------------------------------------------------
# Ziele:
# - stabiler Container für den vectoplan-library Flask/Python-Service
# - explizite Docker-Build-Stage `runtime`, weil docker-compose.yml target: runtime nutzt
# - Flask/Gunicorn sauber in einem Python-Slim-Image betreiben
# - PostgreSQL/SQLAlchemy/Flask-Migrate Runtime-Abhängigkeiten unterstützen
# - pg_isready für entrypoint.sh bereitstellen
# - reproduzierbare Defaults für lokale Entwicklung und frühe Deployments
# - Non-Root-Betrieb
# - robuste Layer-Reihenfolge für besseren Build-Cache
# - PYTHONPATH für Service-Root und src/
# - VPLIB-Kernpfade explizit setzen
# - Creative-Library-Pfade explizit setzen
# - models/ im Container verfügbar machen
# - migrations/ NICHT künstlich im Build erzeugen, damit flask db init sauber laufen kann
# - src/library/source im Container verfügbar machen
# - optionaler entrypoint.sh-Support ohne harte Abhängigkeit
#
# Wichtig:
# - keine Migrationen beim Docker-Build
# - kein flask db init beim Docker-Build
# - kein flask db migrate beim Docker-Build
# - kein flask db upgrade beim Docker-Build
# - kein db.create_all() beim Docker-Build
# - kein Scan beim Docker-Build
# - keine DB-Schreiboperationen beim Container-Import
# - DB-Bootstrap läuft ausschließlich zur Container-Laufzeit über entrypoint.sh
# -----------------------------------------------------------------------------

FROM python:3.12-slim AS runtime


# -----------------------------------------------------------------------------
# Build-Argumente
# -----------------------------------------------------------------------------

ARG APP_HOME=/opt/vectoplan/services/vectoplan-library
ARG APP_USER=vectoplan
ARG APP_UID=10002
ARG APP_GID=10002


# -----------------------------------------------------------------------------
# Metadaten
# -----------------------------------------------------------------------------

LABEL org.opencontainers.image.title="vectoplan-library" \
      org.opencontainers.image.description="VECTOPLAN Library Flask/Python service with VPLIB, Creative Library and PostgreSQL backend" \
      org.opencontainers.image.vendor="VECTOPLAN"


# -----------------------------------------------------------------------------
# Laufzeit-Umgebung
# -----------------------------------------------------------------------------
# Wichtig:
# - VPLIB_SOURCE_ROOT bleibt der Legacy-/VPLIB-Quellpfad.
# - VECTOPLAN_LIBRARY_SOURCE_ROOT zeigt auf die dateibasierte Creative Library:
#     ${APP_HOME}/src/library/source
# - COPY . . kopiert diesen Ordner inklusive manuell angelegter Testblöcke.
# - SQLALCHEMY_DATABASE_URI und Aliase zeigen standardmäßig auf den Compose-DB-Service.
# - Flask-Migrate wird per entrypoint.sh ausgeführt, nicht hier im Dockerfile.
# - Die Datenbank erzeugt keine fachliche VPLIB-ID. `vplib_uid` kommt aus
#   vplib.manifest.json und wird nur gespeichert/indexiert.
# -----------------------------------------------------------------------------

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=${APP_HOME}/src:${APP_HOME} \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SERVICE_NAME=vectoplan-library \
    APP_NAME=vectoplan-library \
    APP_HOME=${APP_HOME} \
    VECTOPLAN_SERVICE_NAME=vectoplan-library \
    VECTOPLAN_LIBRARY_HOST=0.0.0.0 \
    VECTOPLAN_LIBRARY_PORT=5000 \
    VECTOPLAN_LIBRARY_CONFIG=production \
    VECTOPLAN_LIBRARY_RUN_MODE=gunicorn \
    VECTOPLAN_LIBRARY_STARTUP_MODULE=src.bootstrap.startup \
    VECTOPLAN_LIBRARY_PRESTART_CHECK=true \
    VECTOPLAN_LIBRARY_PRESTART_CREATE_APP=false \
    VECTOPLAN_LIBRARY_PRINT_STARTUP_SUMMARY=true \
    VECTOPLAN_LIBRARY_STARTUP_STRICT=false \
    VECTOPLAN_LIBRARY_SERVICE_ROOT=${APP_HOME} \
    VECTOPLAN_LIBRARY_SRC_ROOT=${APP_HOME}/src \
    VECTOPLAN_LIBRARY_PACKAGE_ROOT=${APP_HOME}/src/library \
    VECTOPLAN_LIBRARY_SOURCE_ROOT=${APP_HOME}/src/library/source \
    VECTOPLAN_LIBRARY_CREATIVE_ROOT=${APP_HOME}/creative_library \
    VECTOPLAN_LIBRARY_GENERATED_ROOT=${APP_HOME}/generated/library \
    VECTOPLAN_LIBRARY_CACHE_ROOT=${APP_HOME}/generated/library_cache \
    VECTOPLAN_LIBRARY_ROUTE_PREFIX=/api/v1/vplib/library \
    VECTOPLAN_LIBRARY_AUTO_SCAN_ON_REQUEST=true \
    VECTOPLAN_LIBRARY_CACHE_ENABLED=false \
    VECTOPLAN_LIBRARY_CACHE_TTL_SECONDS=5 \
    VECTOPLAN_LIBRARY_SCAN_RECURSIVE=true \
    VECTOPLAN_LIBRARY_SCAN_MAX_DEPTH=12 \
    VECTOPLAN_LIBRARY_SCAN_FOLLOW_SYMLINKS=false \
    VECTOPLAN_LIBRARY_INCLUDE_INVALID_IN_SCAN=true \
    VECTOPLAN_LIBRARY_FAIL_ON_DUPLICATE_IDS=true \
    VECTOPLAN_LIBRARY_TREAT_MISSING_SOURCE_ROOT_AS_EMPTY=true \
    VECTOPLAN_LIBRARY_LIST_INCLUDE_INVALID=false \
    VECTOPLAN_LIBRARY_DETAIL_INCLUDE_RAW_DOCUMENTS=true \
    VECTOPLAN_LIBRARY_DETAIL_INCLUDE_VALIDATION_REPORT=true \
    LIBRARY_SERVICE_ROOT=${APP_HOME} \
    LIBRARY_SRC_ROOT=${APP_HOME}/src \
    LIBRARY_PACKAGE_ROOT=${APP_HOME}/src/library \
    LIBRARY_SOURCE_ROOT=${APP_HOME}/src/library/source \
    LIBRARY_CREATIVE_ROOT=${APP_HOME}/creative_library \
    LIBRARY_GENERATED_ROOT=${APP_HOME}/generated/library \
    LIBRARY_CACHE_ROOT=${APP_HOME}/generated/library_cache \
    LIBRARY_ROUTE_PREFIX=/api/v1/vplib/library \
    VPLIB_SERVICE_ROOT=${APP_HOME} \
    VPLIB_SRC_ROOT=${APP_HOME}/src \
    VPLIB_SOURCE_ROOT=${APP_HOME}/sources \
    VPLIB_LIBRARY_CATALOG_ROOT=${APP_HOME}/creative_library \
    VPLIB_GENERATED_ROOT=${APP_HOME}/generated/vplib \
    VPLIB_ARCHIVE_ROOT=${APP_HOME}/generated/archives \
    VPLIB_TEST_OUTPUT_ROOT=${APP_HOME}/generated/vplib_test \
    VPLIB_ROUTE_PREFIX=/api/v1/vplib \
    VPLIB_DRY_RUN_DEFAULT=true \
    VPLIB_TEST_ROUTE_ENABLED=true \
    VPLIB_CREATE_ROUTE_ENABLED=true \
    VPLIB_CREATE_WRITE_ENABLED=true \
    VPLIB_CREATE_OVERWRITE_ENABLED=false \
    VPLIB_DEFAULT_WRITE_MODE=fail \
    VPLIB_DEFAULT_VALIDATION_MODE=strict \
    VECTOPLAN_LIBRARY_DATABASE_DRIVER=postgresql+psycopg \
    VECTOPLAN_LIBRARY_DB_HOST=vectoplan-library-db \
    VECTOPLAN_LIBRARY_DB_PORT=5432 \
    VECTOPLAN_LIBRARY_DB_NAME=vectoplan_library \
    VECTOPLAN_LIBRARY_DB_USER=vectoplan \
    VECTOPLAN_LIBRARY_DB_PASSWORD=vectoplan \
    VECTOPLAN_LIBRARY_DATABASE_URI=postgresql+psycopg://vectoplan:vectoplan@vectoplan-library-db:5432/vectoplan_library \
    VECTOPLAN_LIBRARY_DATABASE_URL=postgresql+psycopg://vectoplan:vectoplan@vectoplan-library-db:5432/vectoplan_library \
    VPLIB_DATABASE_URL=postgresql+psycopg://vectoplan:vectoplan@vectoplan-library-db:5432/vectoplan_library \
    SQLALCHEMY_DATABASE_URI=postgresql+psycopg://vectoplan:vectoplan@vectoplan-library-db:5432/vectoplan_library \
    DATABASE_URL=postgresql+psycopg://vectoplan:vectoplan@vectoplan-library-db:5432/vectoplan_library \
    VECTOPLAN_LIBRARY_DATABASE_REQUIRED=true \
    VECTOPLAN_LIBRARY_DB_HEALTH_CHECK=false \
    SQLALCHEMY_TRACK_MODIFICATIONS=false \
    SQLALCHEMY_ECHO=false \
    SQLALCHEMY_RECORD_QUERIES=false \
    VECTOPLAN_LIBRARY_DB_POOL_PRE_PING=true \
    VECTOPLAN_LIBRARY_DB_POOL_RECYCLE_SECONDS=1800 \
    VECTOPLAN_LIBRARY_DB_POOL_SIZE=5 \
    VECTOPLAN_LIBRARY_DB_MAX_OVERFLOW=10 \
    VECTOPLAN_LIBRARY_DB_POOL_TIMEOUT_SECONDS=30 \
    VECTOPLAN_LIBRARY_DATABASE_CONNECT_TIMEOUT=15 \
    VECTOPLAN_LIBRARY_MIGRATIONS_DIRECTORY=migrations \
    ALEMBIC_MIGRATIONS_DIRECTORY=migrations \
    MIGRATIONS_DIRECTORY=migrations \
    FLASK_APP=wsgi:app \
    VECTOPLAN_LIBRARY_DB_WAIT_FOR_READY=true \
    VECTOPLAN_LIBRARY_DB_WAIT_TIMEOUT=60 \
    VECTOPLAN_LIBRARY_DB_WAIT_INTERVAL=2 \
    VECTOPLAN_LIBRARY_DB_BOOTSTRAP_ENABLED=true \
    VECTOPLAN_LIBRARY_DB_AUTO_INIT=true \
    VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE=true \
    VECTOPLAN_LIBRARY_DB_AUTO_UPGRADE=true \
    VECTOPLAN_LIBRARY_DB_MIGRATION_STRICT=true \
    VECTOPLAN_LIBRARY_DB_RECREATE_INCOMPLETE_MIGRATIONS=false \
    VECTOPLAN_LIBRARY_DB_AUTO_MIGRATE_MESSAGE="auto creative library migration" \
    VECTOPLAN_LIBRARY_DB_AUTO_CREATE=false \
    VECTOPLAN_LIBRARY_DB_AUTO_SEED=false \
    VECTOPLAN_LIBRARY_DB_DROP_ALL_ON_BOOT=false \
    GUNICORN_WORKERS=2 \
    GUNICORN_THREADS=2 \
    GUNICORN_TIMEOUT=120 \
    GUNICORN_KEEPALIVE=5 \
    GUNICORN_LOG_LEVEL=info \
    GUNICORN_ACCESSLOG=- \
    GUNICORN_ERRORLOG=-


# -----------------------------------------------------------------------------
# Arbeitsverzeichnis
# -----------------------------------------------------------------------------

WORKDIR ${APP_HOME}


# -----------------------------------------------------------------------------
# Systempakete und Non-Root-Benutzer
# -----------------------------------------------------------------------------
# libpq5:
#   Laufzeitbibliothek für PostgreSQL-Clients/Treiber.
#
# curl:
#   einfache Diagnose im Container.
#
# postgresql-client:
#   pg_isready/psql für entrypoint.sh und manuelle Diagnose.
#
# Wichtig:
# - migrations/ wird hier bewusst nicht erzeugt.
# - Wenn migrations/ im Repo existiert, kommt es später über COPY . .
# - Wenn migrations/ im Repo nicht existiert, erzeugt entrypoint.sh es per flask db init.
# -----------------------------------------------------------------------------

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libpq5 \
        postgresql-client \
    ; \
    rm -rf /var/lib/apt/lists/*; \
    if ! getent group "${APP_USER}" > /dev/null 2>&1; then \
        addgroup --system --gid "${APP_GID}" "${APP_USER}"; \
    fi; \
    if ! id -u "${APP_USER}" > /dev/null 2>&1; then \
        adduser \
            --system \
            --uid "${APP_UID}" \
            --ingroup "${APP_USER}" \
            --home "${APP_HOME}" \
            --shell /usr/sbin/nologin \
            "${APP_USER}"; \
    fi; \
    mkdir -p \
        "${APP_HOME}" \
        "${APP_HOME}/models" \
        "${APP_HOME}/sources" \
        "${APP_HOME}/creative_library" \
        "${APP_HOME}/generated/vplib" \
        "${APP_HOME}/generated/archives" \
        "${APP_HOME}/generated/vplib_test" \
        "${APP_HOME}/generated/library" \
        "${APP_HOME}/generated/library_cache" \
        "${APP_HOME}/src/library/source" \
    ; \
    chown -R "${APP_USER}:${APP_USER}" "${APP_HOME}"


# -----------------------------------------------------------------------------
# Python-Abhängigkeiten zuerst kopieren
# -----------------------------------------------------------------------------

COPY --chown=${APP_USER}:${APP_USER} requirements.txt ./


# -----------------------------------------------------------------------------
# Python-Abhängigkeiten installieren
# -----------------------------------------------------------------------------

RUN set -eux; \
    python -m pip install --upgrade pip setuptools wheel; \
    python -m pip install --requirement requirements.txt; \
    python -m pip check


# -----------------------------------------------------------------------------
# Anwendungscode kopieren
# -----------------------------------------------------------------------------
# COPY . . kopiert auch:
# - models/**
# - migrations/**, falls im Repo vorhanden
# - src/library/**
# - src/library/source/**
# - manuell gepflegte .vplib-Source-Packages
# -----------------------------------------------------------------------------

COPY --chown=${APP_USER}:${APP_USER} . .


# -----------------------------------------------------------------------------
# Dateirechte und optionale Bereinigung
# -----------------------------------------------------------------------------
# Wichtig:
# - migrations/ wird auch hier nicht künstlich erzeugt.
# - Ein vorhandenes migrations/ aus dem Repo bleibt erhalten.
# - Ein fehlendes migrations/ wird zur Laufzeit durch flask db init erzeugt.
# -----------------------------------------------------------------------------

RUN set -eux; \
    if [ -f "./entrypoint.sh" ]; then \
        chmod +x ./entrypoint.sh; \
    fi; \
    mkdir -p \
        "${APP_HOME}/models" \
        "${APP_HOME}/sources" \
        "${APP_HOME}/creative_library" \
        "${APP_HOME}/generated/vplib" \
        "${APP_HOME}/generated/archives" \
        "${APP_HOME}/generated/vplib_test" \
        "${APP_HOME}/generated/library" \
        "${APP_HOME}/generated/library_cache" \
        "${APP_HOME}/src/library/source" \
    ; \
    find "${APP_HOME}" -type d -name "__pycache__" -prune -exec rm -rf {} + || true; \
    chown -R "${APP_USER}:${APP_USER}" "${APP_HOME}"


# -----------------------------------------------------------------------------
# Nicht als root laufen
# -----------------------------------------------------------------------------

USER ${APP_USER}


# -----------------------------------------------------------------------------
# Exponierter Port
# -----------------------------------------------------------------------------

EXPOSE 5000


# -----------------------------------------------------------------------------
# Stop-Signal
# -----------------------------------------------------------------------------

STOPSIGNAL SIGTERM


# -----------------------------------------------------------------------------
# Healthcheck
# -----------------------------------------------------------------------------
# /health/ready prüft:
# - App läuft
# - Blueprints sind registriert
# - VPLIB-Settings sind geladen
# - Library-Settings sind geladen
# - Library-Routen sind bekannt
# - falls DB required: SQLAlchemy initialisiert und Models importiert
#
# docker-compose.yml kann diesen Healthcheck weiterhin überschreiben.
# -----------------------------------------------------------------------------

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import os,sys,urllib.request; port=os.getenv('VECTOPLAN_LIBRARY_PORT','5000'); url='http://127.0.0.1:%s/health/ready' % port; resp=urllib.request.urlopen(url, timeout=3); sys.exit(0 if 200 <= getattr(resp,'status',200) < 400 else 1)" || exit 1


# -----------------------------------------------------------------------------
# Standardstart
# -----------------------------------------------------------------------------

CMD ["/bin/sh", "-c", "if [ -x ./entrypoint.sh ]; then exec ./entrypoint.sh; else exec gunicorn --bind ${VECTOPLAN_LIBRARY_HOST:-0.0.0.0}:${VECTOPLAN_LIBRARY_PORT:-5000} --workers ${GUNICORN_WORKERS:-2} --threads ${GUNICORN_THREADS:-2} --timeout ${GUNICORN_TIMEOUT:-120} --keep-alive ${GUNICORN_KEEPALIVE:-5} --log-level ${GUNICORN_LOG_LEVEL:-info} --access-logfile ${GUNICORN_ACCESSLOG:--} --error-logfile ${GUNICORN_ERRORLOG:--} wsgi:app; fi"]