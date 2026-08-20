from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


SERVICE_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = SERVICE_ROOT / "src"
for candidate in (SERVICE_ROOT, SRC_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def db_sync_module() -> Any:
    return importlib.import_module("library.services.library_db_sync_service")


class RecordingRepository:
    def __init__(self) -> None:
        self.finished: list[tuple[Any, dict[str, Any]]] = []
        self.failed: list[tuple[Any, BaseException]] = []
        self.issues: list[tuple[Any, dict[str, Any]]] = []

    def finish_scan_run(self, scan_run_ref: Any, **kwargs: Any) -> None:
        self.finished.append((scan_run_ref, kwargs))

    def fail_scan_run(self, scan_run_ref: Any, *, error: BaseException, **kwargs: Any) -> None:
        self.failed.append((scan_run_ref, error))

    def record_scan_issue(
        self,
        scan_run_ref: Any,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        self.issues.append((scan_run_ref, payload))


def test_scan_run_repository_calls_use_scalar_reference() -> None:
    module = db_sync_module()
    service = object.__new__(module.LibraryDbSyncService)
    repository = RecordingRepository()
    scan_run = SimpleNamespace(id=17, scan_run_uid="scan-17")
    result = SimpleNamespace(
        ok=True,
        stats=SimpleNamespace(to_dict=lambda: {"candidate_count": 1}),
        issues=[],
    )
    issue = SimpleNamespace(to_dict=lambda: {"code": "test.issue"})

    service._finish_scan_run(repository, scan_run, result)
    error = RuntimeError("test")
    service._fail_scan_run(repository, scan_run, error)
    service._save_issue(repository, issue, scan_run=scan_run)

    assert repository.finished[0][0] == 17
    assert repository.failed[0] == (17, error)
    assert repository.issues[0] == (17, {"code": "test.issue"})


def test_repository_finishes_current_scan_run_model_contract() -> None:
    module = importlib.import_module(
        "library.repositories.creative_library_repository"
    )

    class ScanRun:
        def __init__(self) -> None:
            self.status: Any = None
            self.summary: dict[str, Any] = {}
            self.counts: dict[str, Any] = {}

        def finish(
            self,
            *,
            status: Any = None,
            summary: dict[str, Any] | None = None,
        ) -> None:
            self.status = status
            self.summary = summary or {}

        def apply_counts(self, *, counts: dict[str, Any]) -> None:
            self.counts = counts

    class RepositoryHarness:
        def __init__(self, scan_run: ScanRun) -> None:
            self.scan_run = scan_run
            self.finish_write_calls: list[bool] = []

        def require_scan_run(self, scan_run_ref: Any, *, for_update: bool) -> ScanRun:
            assert scan_run_ref == 17
            assert for_update is True
            return self.scan_run

        def _finish_write(self, *, commit: bool) -> None:
            self.finish_write_calls.append(commit)

        def rollback(self) -> None:
            raise AssertionError("rollback must not be called")

    scan_run = ScanRun()
    repository = RepositoryHarness(scan_run)
    result = module.CreativeLibraryRepository.finish_scan_run(
        repository,
        17,
        status="completed",
        counters={"candidate_count": 5},
        errors=[{"code": "test.warning"}],
        commit=False,
    )

    assert result is scan_run
    assert scan_run.status == "completed"
    assert scan_run.summary["counters"] == {"candidate_count": 5}
    assert scan_run.summary["errors"] == [{"code": "test.warning"}]
    assert scan_run.counts == {"candidate_count": 5}
    assert repository.finish_write_calls == [False]


def test_repository_start_scan_run_prefers_current_model_factory() -> None:
    module = importlib.import_module(
        "library.repositories.creative_library_repository"
    )
    captured: dict[str, Any] = {}

    class ScanRunModel:
        @classmethod
        def start(cls, **kwargs: Any) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(status="running", payload={}, started_at=object())

    class Session:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add(self, value: Any) -> None:
            self.added.append(value)

    class RepositoryHarness:
        models = SimpleNamespace(CreativeLibraryScanRun=ScanRunModel)

        def __init__(self) -> None:
            self.session = Session()
            self.finish_write_calls: list[bool] = []

        def _finish_write(self, *, commit: bool) -> None:
            self.finish_write_calls.append(commit)

        def rollback(self) -> None:
            raise AssertionError("rollback must not be called")

    repository = RepositoryHarness()
    scan_run = module.CreativeLibraryRepository.start_scan_run(
        repository,
        {
            "source_root": "/tmp/library",
            "mode": "filesystem_to_db",
            "triggered_by": "pytest",
            "started_at": "2026-08-03T16:40:05+00:00",
            "metadata": {"scope": "targeted"},
            "status": "running",
        },
        commit=False,
    )

    assert captured == {
        "source_root": "/tmp/library",
        "mode": "filesystem_to_db",
        "triggered_by": "pytest",
        "metadata": {"scope": "targeted"},
    }
    assert scan_run.status == "running"
    assert scan_run.payload["started_at"] == "2026-08-03T16:40:05+00:00"
    assert repository.session.added == [scan_run]
    assert repository.finish_write_calls == [False]


def test_extract_manifest_payload_prefers_documents_and_falls_back() -> None:
    module = db_sync_module()
    documents = {
        "vplib.manifest.json": {
            "vplib_uid": "11111111-1111-4111-8111-111111111111",
        }
    }

    assert module.extract_manifest_payload({}, documents) == documents[
        "vplib.manifest.json"
    ]
    assert module.extract_manifest_payload(
        {"manifest_payload": {"package_id": "vplib.test"}},
        {},
    ) == {"package_id": "vplib.test"}


def test_for_update_disables_eager_outer_joins() -> None:
    module = importlib.import_module(
        "library.repositories.creative_library_repository"
    )

    class Query:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def enable_eagerloads(self, enabled: bool) -> "Query":
            self.calls.append(("enable_eagerloads", enabled))
            return self

        def with_for_update(self) -> "Query":
            self.calls.append(("with_for_update", None))
            return self

    query = Query()
    repository = object.__new__(module.CreativeLibraryRepository)

    result = repository._with_for_update(query)

    assert result is query
    assert query.calls == [
        ("enable_eagerloads", False),
        ("with_for_update", None),
    ]


def test_failed_publish_response_is_not_treated_as_revision() -> None:
    module = db_sync_module()
    service = object.__new__(module.LibraryDbSyncService)
    candidate = module.LibrarySyncCandidateResult()

    with pytest.raises(module.LibraryDbSyncCandidateError, match="publish failed"):
        service._apply_publish_result_to_candidate(
            candidate,
            {
                "ok": False,
                "status": "invalid_request",
                "errors": ["publish failed"],
            },
        )

    assert candidate.revision_created is False


def test_candidate_sync_uses_nested_transaction_when_available() -> None:
    module = db_sync_module()
    service = object.__new__(module.LibraryDbSyncService)
    events: list[str] = []
    expected = module.LibrarySyncCandidateResult(status="updated")

    class Transaction:
        def __enter__(self) -> "Transaction":
            events.append("enter")
            return self

        def __exit__(
            self,
            exc_type: Any,
            exc: Any,
            traceback: Any,
        ) -> None:
            events.append("exit")

    class Session:
        def begin_nested(self) -> Transaction:
            events.append("begin_nested")
            return Transaction()

    def sync_candidate(*args: Any, **kwargs: Any) -> Any:
        events.append("sync")
        return expected

    service.sync_candidate_to_db = sync_candidate
    repository = SimpleNamespace(session=Session())

    result = service._sync_candidate_with_savepoint(
        {"candidate": True},
        scan_run=None,
        repository=repository,
        publish_valid_only=True,
    )

    assert result is expected
    assert events == ["begin_nested", "enter", "sync", "exit"]


def test_revision_payload_preserves_publish_identity_and_hash() -> None:
    module = importlib.import_module("library.services.creative_library_service")
    service = object.__new__(module.CreativeLibraryService)
    service.repository = SimpleNamespace(
        get_scan_run=lambda scan_run_ref: SimpleNamespace(id=scan_run_ref)
    )
    item = SimpleNamespace(
        vplib_uid="11111111-1111-4111-8111-111111111111",
        family_id="vp.hochbau.waende.test",
        package_id="vplib.vp.hochbau.waende.test",
        source_path="hochbau/waende/test",
        current_revision_hash="previous-hash",
    )

    result = service.build_revision_payload_from_publish_payload(
        {
            "revision_hash": "current-hash",
            "package_version": "0.1.0",
            "manifest_payload": {
                "vplib_uid": item.vplib_uid,
                "family_id": item.family_id,
                "package_id": item.package_id,
                "schema_version": "0.1.0",
            },
            "family_payload": {"slug": "test"},
            "document_bundle": {"documents": {"variants/index.json": {}}},
        },
        item=item,
        scan_run_ref=17,
    )

    assert result["vplib_uid"] == item.vplib_uid
    assert result["family_id"] == item.family_id
    assert result["package_id"] == item.package_id
    assert result["revision_hash"] == "current-hash"
    assert result["previous_revision_hash"] == "previous-hash"
    assert result["package_version"] == "0.1.0"
    assert result["scan_run_id"] == 17


def test_repository_revision_fallback_matches_current_model_fields() -> None:
    module = importlib.import_module(
        "library.repositories.creative_library_repository"
    )
    repository = object.__new__(module.CreativeLibraryRepository)
    item = SimpleNamespace(
        id=23,
        vplib_uid="11111111-1111-4111-8111-111111111111",
        family_id="vp.hochbau.waende.test",
        package_id="vplib.vp.hochbau.waende.test",
        owner_user_id=None,
        source_scope="imported",
        owner_scope="imported",
        source_root="/library/source",
        source_path="hochbau/waende/test",
        current_revision_hash="previous-hash",
    )

    attrs = repository._fallback_revision_attrs(
        {
            "revision_hash": "current-hash",
            "package_version": "0.1.0",
            "scan_run_id": 17,
            "manifest_payload": {
                "vplib_uid": item.vplib_uid,
                "family_id": item.family_id,
                "package_id": item.package_id,
                "schema_version": "0.1.0",
            },
            "family_payload": {"slug": "test"},
            "classification_payload": {"domain": "hochbau"},
            "document_bundle": {
                "documents": {"variants/index.json": {"variant_count": 3}}
            },
            "validation_payload": {"valid": True},
        },
        item=item,
        mark_current=True,
    )

    assert attrs["family_db_id"] == 23
    assert attrs["item_id"] == 23
    assert attrs["scan_run_id"] == 17
    assert attrs["revision_hash"] == "current-hash"
    assert attrs["previous_revision_hash"] == "previous-hash"
    assert attrs["vplib_uid"] == item.vplib_uid
    assert attrs["manifest_json"]["schema_version"] == "0.1.0"
    assert attrs["identity_json"] == {"slug": "test"}
    assert attrs["classification_json"] == {"domain": "hochbau"}
    assert attrs["document_paths_json"] == ["variants/index.json"]
    assert attrs["validation_payload"] == {"valid": True}


def test_repository_revision_fallback_requires_hash() -> None:
    module = importlib.import_module(
        "library.repositories.creative_library_repository"
    )
    repository = object.__new__(module.CreativeLibraryRepository)

    with pytest.raises(module.CreativeLibraryConflictError, match="revision_hash"):
        repository._fallback_revision_attrs(
            {},
            item=SimpleNamespace(id=23),
            mark_current=True,
        )


def test_model_payload_factory_supports_keyword_only_contract() -> None:
    module = importlib.import_module(
        "library.repositories.creative_library_repository"
    )

    def factory(*, item: Any, revision: Any, payload: dict[str, Any]) -> Any:
        return item, revision, payload

    result = module.call_model_payload_factory(
        factory,
        {"variant_id": "default"},
        item="item",
        revision="revision",
        variant="ignored",
    )

    assert result == ("item", "revision", {"variant_id": "default"})


def test_creative_service_preserves_document_storage_path() -> None:
    module = importlib.import_module("library.services.creative_library_service")
    service = object.__new__(module.CreativeLibraryService)

    documents = service.extract_document_payloads(
        {
            "documents": [
                {
                    "relative_path": "variants/default.json",
                    "module": "variants",
                    "document_type": "json",
                    "payload": {"content": {"variant_id": "default"}},
                }
            ]
        }
    )

    assert documents[0]["relative_path"] == "variants/default.json"
    assert documents[0]["path"] == "variants/default.json"
    assert documents[0]["module"] == "variants"


def test_write_resolution_reuses_materialized_item_and_revision() -> None:
    module = importlib.import_module(
        "library.repositories.creative_library_repository"
    )

    class RepositoryHarness:
        def require_item(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("materialized item must not be reloaded")

        def require_revision(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("materialized revision must not be reloaded")

    item = SimpleNamespace(id=23)
    revision = SimpleNamespace(id=29)

    resolved = module.CreativeLibraryRepository._resolve_item_revision_for_write(
        RepositoryHarness(),
        {},
        item_ref=item,
        revision_ref=revision,
    )

    assert resolved == (item, revision)


def test_asset_extraction_skips_empty_summary_references() -> None:
    module = db_sync_module()
    assets = module.extract_asset_payloads(
        {
            "summary": {
                "assets": {
                    "icon_ref": None,
                    "preview_ref": None,
                    "mesh_ref": None,
                    "material_refs": [],
                }
            }
        }
    )

    assert assets == []


def test_family_slug_prefers_package_identity_over_summary_slug() -> None:
    module = db_sync_module()
    uid = "11111111-1111-4111-8111-111111111111"
    payload = module.build_family_upsert_payload(
        {
            "slug": "vp_hochbau_waende_wrong",
            "documents": {
                "vplib.manifest.json": {
                    "vplib_uid": uid,
                    "family_id": "vp.hochbau.waende.test",
                    "package_id": "vplib.vp.hochbau.waende.test",
                    "family_slug": "wand_test",
                    "family_name": "Wand Test",
                },
                "family/identity.json": {"slug": "wand_test"},
                "family/classification.json": {"domain": "hochbau"},
            },
        }
    )

    assert payload["family_slug"] == "wand_test"


def test_publish_bundle_does_not_reload_complete_item_graph() -> None:
    module = importlib.import_module("library.services.creative_library_service")

    class Entity:
        id = 23
        vplib_uid = "11111111-1111-4111-8111-111111111111"
        family_id = "vp.hochbau.waende.test"
        package_id = "vplib.vp.hochbau.waende.test"
        source_path = "hochbau/waende/test"
        variant_count = 99
        asset_count = 99
        document_count = 99
        current_revision_hash = None

        def to_dict(self) -> dict[str, Any]:
            return {"id": self.id, "vplib_uid": self.vplib_uid}

    class Repository:
        def __init__(self) -> None:
            self.item = Entity()

        def upsert_item(self, payload: Any, *, commit: bool) -> tuple[Any, bool]:
            return self.item, True

        def create_revision(self, item_ref: Any, *args: Any, **kwargs: Any) -> Any:
            assert item_ref is self.item
            return Entity()

        def flush(self) -> None:
            return None

        def get_item_payload(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("complete item graph must not be reloaded")

    repository = Repository()
    service = module.CreativeLibraryService(
        repository=repository,
        definition_service=None,
        file_service=None,
    )
    service.publish_children = lambda *args, **kwargs: {
        "variants": [],
        "assets": [],
        "documents": [],
        "counts": {"variant_count": 0, "asset_count": 0, "document_count": 0},
    }

    result = service.publish_bundle(
        {
            "vplib_uid": Entity.vplib_uid,
            "family_id": Entity.family_id,
            "package_id": Entity.package_id,
            "revision_hash": "current-hash",
            "manifest_payload": {"vplib_uid": Entity.vplib_uid},
        },
        validate=False,
        commit=False,
    )

    assert result["ok"] is True
    assert result["payload"]["item"]["current_revision"]["id"] == 23
    assert repository.item.variant_count == 0
    assert repository.item.asset_count == 0
    assert repository.item.document_count == 0


def test_publish_bundle_is_idempotent_for_current_revision_hash() -> None:
    service_module = importlib.import_module("library.services.creative_library_service")
    sync_module = db_sync_module()

    class Entity:
        id = 23
        vplib_uid = "11111111-1111-4111-8111-111111111111"
        family_id = "vp.hochbau.waende.test"
        package_id = "vplib.vp.hochbau.waende.test"
        source_path = "hochbau/waende/test"
        current_revision_id = 41
        current_revision_hash = "current-hash"
        variant_count = 3
        asset_count = 0
        document_count = 28

        def to_dict(self) -> dict[str, Any]:
            return {
                "id": self.id,
                "vplib_uid": self.vplib_uid,
                "current_revision_id": self.current_revision_id,
                "current_revision_hash": self.current_revision_hash,
            }

    class Repository:
        def __init__(self) -> None:
            self.item = Entity()
            self.flushed = False

        def upsert_item(self, payload: Any, *, commit: bool) -> tuple[Any, bool]:
            return self.item, False

        def create_revision(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("current revision must not be inserted again")

        def flush(self) -> None:
            self.flushed = True

    repository = Repository()
    service = service_module.CreativeLibraryService(
        repository=repository,
        definition_service=None,
        file_service=None,
    )
    service.publish_children = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("children must not be replaced for an unchanged revision")
    )

    result = service.publish_bundle(
        {
            "vplib_uid": Entity.vplib_uid,
            "family_id": Entity.family_id,
            "package_id": Entity.package_id,
            "revision_hash": Entity.current_revision_hash,
            "manifest_payload": {"vplib_uid": Entity.vplib_uid},
        },
        validate=False,
        commit=False,
    )

    assert result["ok"] is True
    assert result["payload"]["unchanged"] is True
    assert result["payload"]["revision_created"] is False
    assert result["payload"]["children"]["counts"]["document_count"] == 28
    assert repository.flushed is True

    candidate = sync_module.LibrarySyncCandidateResult()
    sync_service = object.__new__(sync_module.LibraryDbSyncService)
    sync_service._apply_publish_result_to_candidate(candidate, result)

    assert candidate.revision_created is False
    assert candidate.variant_count == 3
    assert candidate.document_count == 28
    assert all(
        operation.operation != sync_module.LibrarySyncOperation.CREATE_REVISION.value
        for operation in candidate.operations
    )


def test_direct_repository_publish_is_idempotent_for_current_revision_hash() -> None:
    module = db_sync_module()

    class Entity:
        id = 23
        current_revision_id = 41
        current_revision_hash = "current-hash"
        variant_count = 3
        asset_count = 2
        document_count = 28

    class Repository:
        def upsert_item(self, payload: Any, *, commit: bool) -> tuple[Any, bool]:
            return Entity(), False

        def create_revision(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("current revision must not be inserted again")

        def upsert_variant(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("children must not be replaced for an unchanged revision")

        def create_asset(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("children must not be replaced for an unchanged revision")

        def create_document(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("children must not be replaced for an unchanged revision")

    service = module.LibraryDbSyncService(repository=Repository())
    result = service._publish_with_repository(
        service.get_repository(),
        {
            "vplib_uid": "11111111-1111-4111-8111-111111111111",
            "family_id": "vp.hochbau.waende.test",
            "package_id": "vplib.vp.hochbau.waende.test",
            "revision_hash": Entity.current_revision_hash,
            "variants": [{"variant_id": "default"}],
            "assets": [{"asset_id": "preview"}],
            "documents": [{"document_id": "manifest"}],
        },
    )

    assert result["ok"] is True
    assert result["payload"]["unchanged"] is True
    assert result["payload"]["revision_created"] is False
    assert result["payload"]["revision"]["id"] == Entity.current_revision_id
    assert result["payload"]["children"]["counts"] == {
        "variant_count": 3,
        "asset_count": 2,
        "document_count": 28,
    }


def test_unset_current_revisions_uses_bulk_update_without_loading_graph() -> None:
    module = importlib.import_module(
        "library.repositories.creative_library_repository"
    )

    class Column:
        def __init__(self, name: str) -> None:
            self.name = name

        __hash__ = object.__hash__

        def __eq__(self, value: Any) -> tuple[str, str, Any]:
            return ("eq", self.name, value)

    class Revision:
        item_id = Column("item_id")
        status = Column("status")

    class Query:
        def __init__(self) -> None:
            self.filters: list[Any] = []
            self.updates: list[tuple[dict[Any, Any], Any]] = []

        def filter(self, expression: Any) -> "Query":
            self.filters.append(expression)
            return self

        def update(self, values: dict[Any, Any], *, synchronize_session: Any) -> None:
            self.updates.append((values, synchronize_session))

        def all(self) -> Any:
            raise AssertionError("revision object graphs must not be loaded")

    query = Query()
    repository = SimpleNamespace(
        models=SimpleNamespace(CreativeLibraryRevision=Revision),
        session=SimpleNamespace(query=lambda model: query),
    )

    module.CreativeLibraryRepository._unset_current_revisions(repository, 42)

    assert ("eq", "item_id", 42) in query.filters
    assert ("eq", "status", module.REVISION_STATUS_CURRENT) in query.filters
    assert query.updates == [
        ({Revision.status: module.REVISION_STATUS_ARCHIVED}, False)
    ]


def test_catalog_item_list_disables_recursive_model_eagerloads() -> None:
    module = importlib.import_module(
        "library.repositories.creative_library_repository"
    )

    class Column:
        def __init__(self, name: str) -> None:
            self.name = name

        def __ne__(self, value: Any) -> tuple[str, str, Any]:
            return ("ne", self.name, value)

    class Item:
        status = Column("status")

    class Query:
        def __init__(self) -> None:
            self.eagerload_flags: list[bool] = []
            self.filters: list[Any] = []
            self.limit_value: int | None = None

        def filter(self, expression: Any) -> "Query":
            self.filters.append(expression)
            return self

        def limit(self, value: int) -> "Query":
            self.limit_value = value
            return self

        def enable_eagerloads(self, value: bool) -> "Query":
            self.eagerload_flags.append(value)
            return self

        def all(self) -> list[str]:
            return ["published-item"]

    query = Query()
    repository = SimpleNamespace(
        models=SimpleNamespace(CreativeLibraryItem=Item),
        session=SimpleNamespace(query=lambda model: query),
        _apply_item_sort=lambda value, model: value,
        _without_default_eagerloads=(
            lambda value: module.CreativeLibraryRepository._without_default_eagerloads(
                repository,
                value,
            )
        ),
    )

    result = module.CreativeLibraryRepository.list_items(
        repository,
        query={
            "active_only": False,
            "visible_only": False,
            "limit": 5,
        },
    )

    assert result == ["published-item"]
    assert query.eagerload_flags == [False]
    assert query.limit_value == 5


def test_item_payload_reads_children_from_current_revision_only() -> None:
    module = importlib.import_module(
        "library.repositories.creative_library_repository"
    )
    captured: dict[str, dict[str, Any]] = {}

    def capture(kind: str) -> Any:
        def reader(*, query: dict[str, Any], as_dict: bool) -> list[Any]:
            captured[kind] = query
            assert as_dict is True
            return []

        return reader

    repository = SimpleNamespace(
        list_variants=capture("variants"),
        list_assets=capture("assets"),
        list_documents=capture("documents"),
    )
    item = SimpleNamespace(id=7, current_revision_id=12)

    payload = module.CreativeLibraryRepository.get_item_payload(
        repository,
        item,
        include_variants=True,
        include_assets=True,
        include_documents=True,
    )

    expected_query = {
        "item_id": 7,
        "revision_id": 12,
        "include_deleted": True,
    }
    assert captured == {
        "variants": expected_query,
        "assets": expected_query,
        "documents": expected_query,
    }
    assert payload["variants"] == []
    assert payload["assets"] == []
    assert payload["documents"] == []
