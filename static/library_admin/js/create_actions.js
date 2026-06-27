/* services/vectoplan-library/static/library_admin/js/create_actions.js */

/* -----------------------------------------------------------------------------
  VECTOPLAN Library · VPLIB Create Actions Runtime

  Zweck:
  - Eigenständige Action-Schicht für /create.
  - Entlastet create.js.
  - Führt Draft, Validate, Package-Plan, Download und Save aus.
  - Nutzt create_payload.js für robuste Payload-Erzeugung.
  - Übergibt Upload-Metadaten aus create_payload.js an alle Backend-Aktionen.
  - Hält Result-/Status-/Fehler-UI stabil.
  - Markiert Backend-Fehler an Feldern.
  - Verhindert parallele Actions.
  - Erzeugt keine VPLIB-Dateien im Browser.
  - Download wird nur vom Backend als Blob übernommen.
  - Keine Datei-Bytes werden manuell gelesen oder per Frontend-Logik verarbeitet.

  Abhängigkeit:
  - Sollte nach create_core.js geladen werden.
  - Sollte nach create_payload.js geladen werden.
  - Erwartet bevorzugt window.VectoplanCreateCore.
  - Nutzt bevorzugt window.VectoplanCreatePayload.
  - Hat defensive Fallbacks, falls eine Runtime noch nicht bereit ist.

  Öffentliche API:
  - window.VectoplanCreateActions.initialize()
  - window.VectoplanCreateActions.runAction(action, form, sourceButton)
  - window.VectoplanCreateActions.postJson(action, payload)
  - window.VectoplanCreateActions.downloadVplib(payload)
  - window.VectoplanCreateActions.clearResult()
  - window.VectoplanCreateActions.printOutput(value, options)
  - window.VectoplanCreateActions.applyResultToUi(result)
  - window.VectoplanCreateActions.getState()
----------------------------------------------------------------------------- */

(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateActions";
  var MODULE_NAME = "actions";
  var ACTIONS_VERSION = "0.6.0";
  var CORE_NAME = "VectoplanCreateCore";
  var PAYLOAD_NAME = "VectoplanCreatePayload";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 80;
  var ACTION_LOCK = "create-actions-run";
  var ACTION_LOCK_MS = 1500;

  var KNOWN_ACTIONS = {
    draft: true,
    validate: true,
    "package-plan": true,
    package_plan: true,
    download: true,
    save: true
  };

  var ACTION_PATHS = {
    draft: "/draft",
    validate: "/validate",
    "package-plan": "/package-plan",
    download: "/download",
    save: "/save"
  };

  var ACTION_LABELS = {
    draft: "Draft bauen",
    validate: "Validieren",
    "package-plan": "Package-Plan",
    download: "VPLIB downloaden",
    save: "In Library speichern"
  };

  var DEFAULT_SELECTORS = {
    form: "[data-vp-create-form], [data-create-form='true'], #vp-create-form, form[data-create-form]",
    actionCard: "[data-create-actions-card='true'], [data-vp-actions-root='true'], [data-vp-create-section='actions']",
    actionButton: "[data-create-action]",
    resultSection: "[data-vp-actions-result], [data-create-result-section='true']",
    resultSummary: "[data-vp-actions-result-summary], [data-create-result-summary='true']",
    resultOutput: "[data-vp-actions-result-output], [data-create-result-output='true']",
    resultCode: "[data-vp-actions-result-code]",
    resultCopy: "[data-vp-actions-result-copy], [data-create-copy-result='true']",
    resultClear: "[data-vp-actions-result-clear], [data-create-clear-result='true']",
    resultLastAction: "[data-create-result-last-action], [data-vp-result-last-action]",
    resultStatus: "[data-create-result-status], [data-vp-result-status]",
    resultHttpStatus: "[data-create-result-http-status], [data-vp-result-http-status]",
    resultErrorCount: "[data-create-result-error-count], [data-vp-result-error-count]",
    resultWarningCount: "[data-create-result-warning-count], [data-vp-result-warning-count]",
    actionStatus: "[data-create-action-status='true'], [data-vp-action-status]",
    uploadInput: "[data-vp-upload-input], input[type='file'][data-vp-upload-kind], input[type='file'][name='geometry_model_files'], input[type='file'][name='technical_document_files'], input[type='file'][name^='variant_document_files']"
  };

  var DEFAULT_CLASSES = {
    loading: "is-loading",
    running: "is-running",
    invalid: "is-invalid",
    valid: "is-valid",
    copied: "is-copied"
  };

  var core = null;
  var payloadRuntime = null;
  var selectors = null;
  var classes = null;
  var initialized = false;
  var bindingDone = false;

  var localState = {
    version: ACTIONS_VERSION,
    initialized: false,
    bindingDone: false,
    pending: false,
    currentAction: "",
    lastAction: "",
    lastResult: null,
    lastError: null,
    lastHttpStatus: null,
    lastPayloadSummary: null,
    actionCount: 0,
    downloadCount: 0,
    saveConfirmCount: 0,
    resultVisible: false,
    lastRoute: "",
    lastRequestAt: "",
    lastResponseAt: "",
    lastUploadFileCount: 0,
    lastUploadErrorCount: 0
  };

  function boot(attempt) {
    try {
      var safeAttempt = typeof attempt === "number" ? attempt : 0;
      var maybeCore = window[CORE_NAME];

      if (!maybeCore || !maybeCore.selectors || !maybeCore.state) {
        if (safeAttempt < BOOT_MAX_ATTEMPTS) {
          window.setTimeout(function () {
            boot(safeAttempt + 1);
          }, BOOT_RETRY_MS);
          return;
        }

        fallbackWarn("Core runtime missing; initializing actions with fallback core.");
        maybeCore = buildFallbackCore();
      }

      initialize(maybeCore);
    } catch (error) {
      fallbackWarn("Actions boot failed.", error);
    }
  }

  function initialize(coreRuntime) {
    try {
      if (initialized) {
        return api;
      }

      core = coreRuntime || window[CORE_NAME] || buildFallbackCore();

      if (!core) {
        fallbackWarn("Cannot initialize actions runtime.");
        return api;
      }

      payloadRuntime = window[PAYLOAD_NAME] || null;
      selectors = Object.assign({}, DEFAULT_SELECTORS, core.selectors || {});
      classes = Object.assign({}, DEFAULT_CLASSES, core.classes || {});

      if (typeof core.refreshContext === "function") {
        core.refreshContext();
      }

      bindControls();
      clearResult({ silent: true });
      enforceStaticDisabledButtons();

      initialized = true;
      localState.initialized = true;

      if (typeof core.registerModule === "function") {
        core.registerModule(MODULE_NAME, api);
      }

      safeSetAttribute(document.documentElement, "data-vp-create-actions-ready", "true");
      safeSetAttribute(document.documentElement, "data-vp-create-actions-version", ACTIONS_VERSION);

      safeDispatch("vectoplan:create:actions-ready", getState());

      return api;
    } catch (error) {
      localState.initialized = false;
      localState.lastError = normalizeError(error);
      safeError("Actions initialization failed.", error);
      return api;
    }
  }

  function bindControls() {
    try {
      if (bindingDone) {
        return;
      }

      bindingDone = true;
      localState.bindingDone = true;

      bindOnce("create-actions-click", bindActionButtons);
      bindOnce("create-actions-result-controls", bindResultControls);
      bindOnce("create-actions-write-state", bindWriteStateUpdates);
      bindOnce("create-actions-payload-refresh", bindPayloadRuntimeUpdates);
    } catch (error) {
      safeError("Actions control binding failed.", error);
    }
  }

  function bindActionButtons() {
    try {
      document.addEventListener("click", function (event) {
        try {
          var button = event.target && event.target.closest
            ? event.target.closest(selectorFor("actionButton"))
            : null;

          if (!button) {
            return;
          }

          var form = resolveForm();

          if (form && !form.contains(button)) {
            return;
          }

          event.preventDefault();

          if (typeof event.stopPropagation === "function") {
            event.stopPropagation();
          }

          var action = normalizeAction(button.getAttribute("data-create-action") || "");

          if (!action) {
            safeWarn("Action button without known action ignored.");
            return;
          }

          if (localState.pending || isCorePending()) {
            safeWarn("Action ignored because another action is pending.", {
              requested: action,
              current: localState.currentAction
            });
            return;
          }

          runAction(action, form, button);
        } catch (clickError) {
          safeWarn("Action click handling failed.", clickError);
        }
      }, true);
    } catch (error) {
      safeError("Action button binding failed.", error);
    }
  }

  function bindResultControls() {
    try {
      document.addEventListener("click", function (event) {
        try {
          var copyButton = event.target && event.target.closest
            ? event.target.closest(selectorFor("resultCopy"))
            : null;

          if (copyButton) {
            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            copyResult(copyButton);
            return;
          }

          var clearButton = event.target && event.target.closest
            ? event.target.closest(selectorFor("resultClear"))
            : null;

          if (clearButton) {
            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            clearResult();
          }
        } catch (clickError) {
          safeWarn("Result control click handling failed.", clickError);
        }
      }, true);
    } catch (error) {
      safeError("Result controls binding failed.", error);
    }
  }

  function bindWriteStateUpdates() {
    try {
      document.addEventListener("vectoplan:create:core-context-refreshed", function () {
        try {
          enforceStaticDisabledButtons();
        } catch (error) {
          safeWarn("Write state refresh handling failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:context-ready", function () {
        try {
          enforceStaticDisabledButtons();
        } catch (error) {
          safeWarn("Context ready write-state handling failed.", error);
        }
      });
    } catch (error) {
      safeWarn("Write state update binding failed.", error);
    }
  }

  function bindPayloadRuntimeUpdates() {
    try {
      document.addEventListener("vectoplan:create:payload-ready", function () {
        try {
          payloadRuntime = window[PAYLOAD_NAME] || payloadRuntime;
        } catch (error) {
          safeWarn("Payload ready binding failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:payload-collected", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail.summary) {
            localState.lastPayloadSummary = clone(detail.summary);
            updateUploadCountsFromSummary(detail.summary);
          }
        } catch (error) {
          safeWarn("Payload collected handling failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:payload-uploads-synced", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail.summary) {
            localState.lastUploadFileCount = parseInt(detail.summary.fileCount || detail.summary.file_count || 0, 10) || 0;
            localState.lastUploadErrorCount = parseInt(detail.summary.errorCount || detail.summary.error_count || 0, 10) || 0;
          }
        } catch (error) {
          safeWarn("Payload uploads synced handling failed.", error);
        }
      });
    } catch (error) {
      safeWarn("Payload runtime update binding failed.", error);
    }
  }

  async function runAction(action, form, sourceButton) {
    var lockAcquired = false;
    var normalizedAction = normalizeAction(action);

    try {
      ensureCore();

      if (!normalizedAction) {
        throw new Error("Unbekannte Aktion: " + action);
      }

      if (localState.pending || isCorePending()) {
        return buildBlockedResult(normalizedAction, "action_pending", "Es läuft bereits eine Aktion.");
      }

      lockAcquired = acquireActionLock(ACTION_LOCK, ACTION_LOCK_MS);

      if (!lockAcquired) {
        return buildBlockedResult(normalizedAction, "action_lock_active", "Aktion wurde blockiert, weil gerade eine andere Aktion verarbeitet wird.");
      }

      var safeForm = resolveForm(form);

      if (!safeForm) {
        throw new Error("Create form not found.");
      }

      clearFieldIssues(safeForm);

      if (normalizedAction !== "download") {
        printOutput({
          ok: true,
          status: "pending",
          action: normalizedAction,
          message: "Anfrage läuft …"
        }, {
          reveal: false
        });
      }

      localState.pending = true;
      localState.currentAction = normalizedAction;
      localState.actionCount += 1;
      localState.lastRequestAt = timestamp();

      dispatchActionEvent("vectoplan:create:action-start", normalizedAction, {
        label: actionLabel(normalizedAction)
      });

      setBusy(safeForm, true, sourceButton);
      setStatus(actionLabel(normalizedAction) + " läuft …", "loading");

      updateResultFromPayload(normalizedAction, {
        ok: true,
        status: "pending",
        _http_status: "—",
        errors: [],
        warnings: []
      });

      var payload = collectPayload(safeForm, {
        source: "action:" + normalizedAction,
        syncVariants: true,
        syncUploads: true
      });

      localState.lastPayloadSummary = summarizePayload(payload);
      updateUploadCountsFromSummary(localState.lastPayloadSummary);

      var result;

      if (normalizedAction === "draft") {
        result = await postJson("draft", payload);
      } else if (normalizedAction === "validate") {
        result = await postJson("validate", payload);
      } else if (normalizedAction === "package-plan") {
        result = await postJson("package-plan", payload);
      } else if (normalizedAction === "save") {
        result = await confirmAndSave(payload);
      } else if (normalizedAction === "download") {
        result = await downloadVplib(payload);
      } else {
        throw new Error("Unbekannte Aktion: " + normalizedAction);
      }

      localState.lastResponseAt = timestamp();

      dispatchActionEvent("vectoplan:create:action-complete", normalizedAction, {
        result: result,
        summary: localState.lastPayloadSummary
      });

      return result;
    } catch (error) {
      var failedAction = normalizedAction || normalizeAction(action) || String(action || "unknown");

      dispatchActionEvent("vectoplan:create:action-error", failedAction, {
        error: normalizeError(error)
      });

      return handleRuntimeError(failedAction, error);
    } finally {
      try {
        setBusy(form || resolveForm(), false, sourceButton);
      } catch (busyError) {
        safeWarn("Busy reset failed.", busyError);
      }

      localState.pending = false;
      localState.currentAction = "";
      setCorePending(false);

      if (lockAcquired) {
        window.setTimeout(function () {
          try {
            releaseActionLock(ACTION_LOCK);
          } catch (releaseError) {
            safeWarn("Action lock release failed.", releaseError);
          }
        }, ACTION_LOCK_MS);
      }
    }
  }

  async function postJson(action, payload) {
    try {
      var normalizedAction = normalizeAction(action);
      var response = await fetchJson(normalizedAction, payload);

      localState.lastResult = response;
      localState.lastAction = normalizedAction;
      localState.lastHttpStatus = response && typeof response._http_status !== "undefined" ? response._http_status : null;

      if (core && core.state) {
        core.state.lastResult = response;
        core.state.lastAction = normalizedAction;
      }

      printOutput(response, { reveal: true });
      applyResultToUi(response);
      updateResultFromPayload(normalizedAction, response);

      if (response && response.ok) {
        setStatus(actionLabel(normalizedAction) + " erfolgreich.", "ok");
      } else {
        setStatus(actionLabel(normalizedAction) + " fehlgeschlagen.", "error");
      }

      return response;
    } catch (error) {
      throw error;
    }
  }

  async function confirmAndSave(payload) {
    try {
      var writeEnabled = isWriteEnabled();

      if (!writeEnabled) {
        var blocked = {
          ok: false,
          status: "write_disabled_client",
          route: "save",
          errors: [
            {
              severity: "error",
              code: "write_disabled_client",
              field: "save",
              message: "Speichern ist im Frontend-Kontext deaktiviert. Das Backend muss VPLIB_CREATE_WRITE_ENABLED=true melden."
            }
          ],
          _payload_summary: summarizePayload(payload)
        };

        localState.lastResult = blocked;
        localState.lastAction = "save";

        if (core && core.state) {
          core.state.lastResult = blocked;
          core.state.lastAction = "save";
        }

        printOutput(blocked, { reveal: true });
        applyResultToUi(blocked);
        updateResultFromPayload("save", blocked);
        setStatus("Speichern ist deaktiviert.", "warning");

        return blocked;
      }

      localState.saveConfirmCount += 1;

      var familyName = String(payload && payload.family_name ? payload.family_name : "").trim();
      var uploadSummary = payload && (payload.uploads_summary || payload.uploadsSummary) ? payload.uploads_summary || payload.uploadsSummary : {};
      var uploadFileCount = parseInt(uploadSummary.fileCount || uploadSummary.file_count || 0, 10) || 0;
      var message = "Package wirklich in den Library-Source-Bereich speichern?";

      if (familyName) {
        message += "\n\nFamily: " + familyName;
      }

      if (uploadFileCount) {
        message += "\n\nHinweis: " + uploadFileCount + " lokale Upload-Datei(en) sind im Payload nur als Metadaten enthalten. Datei-Bytes werden aktuell nicht gespeichert.";
      }

      message += "\n\nDas Backend blockiert den Vorgang weiterhin, falls der Schreibmodus nicht aktiv ist oder der Zielordner existiert.";

      if (!window.confirm(message)) {
        var cancelled = {
          ok: false,
          status: "cancelled",
          route: "save",
          info: [
            {
              severity: "info",
              code: "user_cancelled",
              message: "Speichern wurde durch den Nutzer abgebrochen."
            }
          ],
          _payload_summary: summarizePayload(payload)
        };

        localState.lastResult = cancelled;
        localState.lastAction = "save";

        if (core && core.state) {
          core.state.lastResult = cancelled;
          core.state.lastAction = "save";
        }

        printOutput(cancelled, { reveal: true });
        updateResultFromPayload("save", cancelled);
        setStatus("Speichern abgebrochen.", "warning");

        return cancelled;
      }

      return postJson("save", payload);
    } catch (error) {
      throw error;
    }
  }

  async function downloadVplib(payload) {
    try {
      var url = resolveActionRouteUrl("download", "/download");

      localState.lastRoute = url;

      var response = await fetch(url, {
        method: "POST",
        headers: buildJsonHeaders("application/octet-stream, application/json"),
        body: JSON.stringify(payload || {}),
        credentials: "same-origin"
      });

      var contentType = response.headers.get("content-type") || "";

      if (!response.ok || contentType.indexOf("application/json") !== -1) {
        var errorPayload = await readResponseAsJson(response);

        localState.lastResult = errorPayload;
        localState.lastAction = "download";
        localState.lastHttpStatus = response.status;

        if (core && core.state) {
          core.state.lastResult = errorPayload;
          core.state.lastAction = "download";
        }

        printOutput(errorPayload, { reveal: true });
        applyResultToUi(errorPayload);
        updateResultFromPayload("download", errorPayload);
        setStatus("Download fehlgeschlagen.", "error");

        return errorPayload;
      }

      var blob = await response.blob();
      var filename = extractDownloadFilename(response) || inferDownloadFilename(payload);

      triggerBrowserDownload(blob, filename);

      localState.downloadCount += 1;

      var result = {
        ok: true,
        status: "download_started",
        route: "download",
        filename: filename,
        size_bytes: blob.size,
        sizeBytes: blob.size,
        _http_status: response.status,
        headers: {
          create_status: response.headers.get("x-vectoplan-create-status") || "",
          create_route: response.headers.get("x-vectoplan-create-route") || "",
          create_version: response.headers.get("x-vectoplan-create-version") || ""
        },
        _payload_summary: summarizePayload(payload)
      };

      localState.lastResult = result;
      localState.lastAction = "download";
      localState.lastHttpStatus = response.status;

      if (core && core.state) {
        core.state.lastResult = result;
        core.state.lastAction = "download";
      }

      printOutput(result, { reveal: true });
      updateResultFromPayload("download", result);
      setStatus("Download gestartet.", "ok");

      return result;
    } catch (error) {
      throw error;
    }
  }

  async function fetchJson(action, payload) {
    try {
      var normalizedAction = normalizeAction(action);
      var fallbackPath = ACTION_PATHS[normalizedAction] || "/" + normalizedAction;
      var url = resolveActionRouteUrl(normalizedAction, fallbackPath);

      localState.lastRoute = url;

      var response = await fetch(url, {
        method: "POST",
        headers: buildJsonHeaders("application/json"),
        body: JSON.stringify(payload || {}),
        credentials: "same-origin"
      });

      var json = await readResponseAsJson(response);

      if (!json || typeof json !== "object") {
        json = {
          ok: false,
          status: "invalid_json_response",
          route: normalizedAction,
          errors: [
            {
              severity: "error",
              code: "invalid_json_response",
              message: "Backend hat keine gültige JSON-Antwort geliefert."
            }
          ],
          _http_status: response.status
        };
      }

      if (typeof json._http_status === "undefined") {
        json._http_status = response.status;
      }

      if (!json.route) {
        json.route = normalizedAction;
      }

      return json;
    } catch (error) {
      throw error;
    }
  }

  async function readResponseAsJson(response) {
    try {
      var text = await response.text();

      if (!text) {
        return {
          ok: response.ok,
          status: response.ok ? "empty_response" : "empty_error_response",
          _http_status: response.status
        };
      }

      var parsed = JSON.parse(text);

      if (parsed && typeof parsed === "object" && typeof parsed._http_status === "undefined") {
        parsed._http_status = response.status;
      }

      return parsed;
    } catch (error) {
      return {
        ok: false,
        status: "response_parse_failed",
        errors: [
          {
            severity: "error",
            code: "response_parse_failed",
            message: String(error && error.message ? error.message : error)
          }
        ],
        _http_status: response && response.status ? response.status : 0
      };
    }
  }

  function collectPayload(form, options) {
    try {
      payloadRuntime = window[PAYLOAD_NAME] || payloadRuntime;

      if (payloadRuntime && typeof payloadRuntime.collectPayload === "function") {
        return payloadRuntime.collectPayload(form || resolveForm(), Object.assign({
          syncVariants: true,
          syncUploads: true
        }, options || {}));
      }

      return collectPayloadFallback(form || resolveForm());
    } catch (error) {
      safeWarn("Payload runtime failed, using fallback payload.", error);
      return collectPayloadFallback(form || resolveForm());
    }
  }

  function collectPayloadFallback(form) {
    try {
      var safeForm = resolveForm(form);
      var payload = {};

      if (!safeForm) {
        return payload;
      }

      var formData = new FormData(safeForm);

      formData.forEach(function (value, key) {
        try {
          if (isFileValue(value)) {
            if (value.name) {
              assignPayloadValue(payload, key, fileToPayloadValue(value));
            }

            return;
          }

          assignPayloadValue(payload, key, value);
        } catch (entryError) {
          safeWarn("Fallback payload entry skipped: " + key, entryError);
        }
      });

      if (!payload.domain) {
        payload.domain = getFieldValue(safeForm, "domain") || "hochbau";
      }

      if (!payload.category) {
        payload.category = getFieldValue(safeForm, "category") || "bloecke";
      }

      if (!payload.subcategory) {
        payload.subcategory = getFieldValue(safeForm, "subcategory") || "basis";
      }

      if (!payload.object_kind) {
        payload.object_kind = getFieldValue(safeForm, "object_kind") || "cell_block";
      }

      if (!payload.definition_variants_json) {
        payload.definition_variants_json = "[]";
      }

      if (!payload.default_variant_id) {
        payload.default_variant_id = "default";
      }

      augmentFallbackUploadPayload(payload, safeForm);

      return payload;
    } catch (error) {
      safeError("Fallback payload collection failed.", error);
      return {};
    }
  }

  function assignPayloadValue(payload, key, value) {
    try {
      if (!payload || !key) {
        return;
      }

      if (Object.prototype.hasOwnProperty.call(payload, key)) {
        if (!Array.isArray(payload[key])) {
          payload[key] = [payload[key]];
        }

        payload[key].push(value);
      } else {
        payload[key] = value;
      }
    } catch (error) {
      safeWarn("Assign fallback payload value failed.", error);
    }
  }

  function augmentFallbackUploadPayload(payload, form) {
    try {
      var geometry = readUploadJsonField(form, "geometry_model_uploads_json", "geometry_model");
      var technical = readUploadJsonField(form, "technical_document_uploads_json", "technical_documents");
      var variant = readUploadJsonField(form, "variant_document_uploads_json", "variant_documents");

      if (!geometry.count) {
        geometry = uploadPayloadFromFileInputs(form, "geometry_model");
      }

      if (!technical.count) {
        technical = uploadPayloadFromFileInputs(form, "technical_documents");
      }

      if (!variant.count) {
        variant = uploadPayloadFromFileInputs(form, "variant_documents");
      }

      payload.geometry_model_uploads = geometry;
      payload.geometryModelUploads = geometry;
      payload.geometry_model_uploads_json = stringifyJson(geometry);
      payload.geometryModelUploadsJson = payload.geometry_model_uploads_json;

      payload.technical_document_uploads = technical;
      payload.technicalDocumentUploads = technical;
      payload.technical_document_uploads_json = stringifyJson(technical);
      payload.technicalDocumentUploadsJson = payload.technical_document_uploads_json;

      payload.variant_document_uploads = variant;
      payload.variantDocumentUploads = variant;
      payload.variant_document_uploads_json = stringifyJson(variant);
      payload.variantDocumentUploadsJson = payload.variant_document_uploads_json;

      payload.uploads = {
        geometry_model: geometry,
        technical_documents: technical,
        variant_documents: variant
      };
      payload.uploadsByKind = payload.uploads;
      payload.uploads_summary = {
        fileCount: (geometry.count || 0) + (technical.count || 0) + (variant.count || 0),
        errorCount: (geometry.errors || []).length + (technical.errors || []).length + (variant.errors || []).length,
        ok: true,
        timestamp: timestamp()
      };
      payload.uploadsSummary = payload.uploads_summary;
      payload.uploads_json = stringifyJson(payload.uploads);
      payload.uploadsJson = payload.uploads_json;
    } catch (error) {
      safeWarn("Fallback upload payload augmentation failed.", error);
    }
  }

  function readUploadJsonField(form, name, kind) {
    try {
      var field = form ? form.elements[name] || qs("[name='" + cssEscape(name) + "']", form) : null;

      if (!field || typeof field.value === "undefined" || !String(field.value || "").trim()) {
        return emptyUploadPayload(kind);
      }

      var parsed = safeJsonParse(field.value, null);

      if (parsed && typeof parsed === "object") {
        return normalizeUploadPayload(parsed, kind);
      }

      return emptyUploadPayload(kind);
    } catch (error) {
      return emptyUploadPayload(kind);
    }
  }

  function uploadPayloadFromFileInputs(form, kind) {
    try {
      var selector = "";

      if (kind === "geometry_model") {
        selector = "input[type='file'][name='geometry_model_files']";
      } else if (kind === "technical_documents") {
        selector = "input[type='file'][name='technical_document_files']";
      } else if (kind === "variant_documents") {
        selector = "input[type='file'][name^='variant_document_files']";
      } else {
        selector = selectorFor("uploadInput");
      }

      var files = [];
      var purpose = getDefaultUploadPurpose(kind);

      qsa(selector, form).forEach(function (input) {
        try {
          var fieldKey = inferFieldKeyFromName(input.name || "");

          files = files.concat(toArray(input.files || []).map(function (file, index) {
            return fileToUploadFile(file, files.length + index, kind, purpose, fieldKey);
          }));
        } catch (inputError) {
          safeWarn("Fallback upload input skipped.", inputError);
        }
      });

      return normalizeUploadPayload({
        kind: kind,
        purpose: purpose,
        count: files.length,
        files: files,
        errors: [],
        ok: true,
        backend_enabled: false,
        backendEnabled: false,
        local_only: true,
        localOnly: true,
        source: "actions_fallback"
      }, kind);
    } catch (error) {
      return emptyUploadPayload(kind);
    }
  }

  function setBusy(form, busy, sourceButton) {
    try {
      var safeForm = form || resolveForm();
      var isBusy = !!busy;

      localState.pending = isBusy;
      setCorePending(isBusy);

      if (safeForm) {
        safeForm.setAttribute("data-create-form-state", isBusy ? "loading" : "idle");
        safeForm.classList.toggle(className("loading"), isBusy);
        safeForm.setAttribute("aria-busy", isBusy ? "true" : "false");
      }

      var actionButtons = qsa(selectorFor("actionButton"));

      actionButtons.forEach(function (button) {
        try {
          if (isBusy) {
            if (!button.disabled) {
              button.setAttribute("data-create-was-enabled", "true");
              button.disabled = true;
              button.setAttribute("aria-disabled", "true");
            }
          } else if (button.getAttribute("data-create-was-enabled") === "true") {
            button.disabled = false;
            button.removeAttribute("data-create-was-enabled");
            button.setAttribute("aria-disabled", "false");
          }

          button.classList.toggle(className("running"), isBusy && button === sourceButton);
          button.setAttribute("aria-busy", isBusy && button === sourceButton ? "true" : "false");
          button.setAttribute("data-vp-action-running", isBusy && button === sourceButton ? "true" : "false");
        } catch (buttonError) {
          safeWarn("Busy button update skipped.", buttonError);
        }
      });

      if (!isBusy) {
        enforceStaticDisabledButtons(safeForm || document);
      }
    } catch (error) {
      safeWarn("Set busy failed.", error);
    }
  }

  function enforceStaticDisabledButtons(root) {
    try {
      var scope = root || document;
      var saveButton = qs("[data-create-action='save']");

      if (saveButton && !isWriteEnabled()) {
        saveButton.disabled = true;
        saveButton.setAttribute("aria-disabled", "true");
        saveButton.setAttribute("title", "Speichern ist deaktiviert. Backend-Schreibmodus erforderlich.");
      } else if (saveButton && isWriteEnabled()) {
        saveButton.removeAttribute("title");

        if (saveButton.getAttribute("data-create-static-disabled") !== "true") {
          saveButton.disabled = false;
          saveButton.setAttribute("aria-disabled", "false");
        }
      }

      var fixedButtons = qsa("button[data-create-static-disabled='true']", scope);

      fixedButtons.forEach(function (button) {
        try {
          button.disabled = true;
          button.setAttribute("aria-disabled", "true");
        } catch (buttonError) {
          safeWarn("Static disabled button enforcement skipped.", buttonError);
        }
      });
    } catch (error) {
      safeWarn("Enforce static disabled buttons failed.", error);
    }
  }

  function printOutput(value, options) {
    try {
      var output = qs(selectorFor("resultOutput"));
      var code = output ? qs(selectorFor("resultCode"), output) : qs(selectorFor("resultCode"));
      var text = stringifyJson(value);
      var reveal = !options || options.reveal !== false;

      if (!output) {
        return;
      }

      if (code) {
        code.textContent = text;
      } else {
        output.textContent = text;
      }

      if (reveal && hasUsefulResultText(text)) {
        output.hidden = false;
        localState.resultVisible = true;

        var resultSection = qs(selectorFor("resultSection"));
        if (resultSection) {
          resultSection.setAttribute("data-vp-actions-result-visible", "true");
        }

        setResultToolsEnabled(true);
      } else if (!reveal) {
        setResultToolsEnabled(false);
      }

      updateResultSummary(value, reveal && hasUsefulResultText(text));
    } catch (error) {
      safeWarn("Print output failed.", error);
    }
  }

  function updateResultSummary(value, reveal) {
    try {
      var summary = qs(selectorFor("resultSummary"));

      if (!summary) {
        return;
      }

      var ok = value && value.ok;
      var status = value && value.status ? value.status : "ready";
      var route = value && (value.route || value.action) ? value.route || value.action : "";
      var httpStatus = value && typeof value._http_status !== "undefined" ? value._http_status : "—";
      var uploadSummary = value && value._payload_summary ? value._payload_summary : null;
      var uploadText = "";

      if (uploadSummary && uploadSummary.upload_file_count) {
        uploadText = " · Upload-Metadaten: " + uploadSummary.upload_file_count;
      }

      summary.textContent = (ok ? "OK" : "Hinweis") + " · " + status + (route ? " · " + route : "") + " · HTTP " + httpStatus + uploadText;
      summary.hidden = !reveal;
    } catch (error) {
      safeWarn("Result summary update failed.", error);
    }
  }

  function clearResult(options) {
    try {
      var output = qs(selectorFor("resultOutput"));
      var code = output ? qs(selectorFor("resultCode"), output) : qs(selectorFor("resultCode"));
      var summary = qs(selectorFor("resultSummary"));
      var silent = options && options.silent;

      if (code) {
        code.textContent = "{}";
      } else if (output) {
        output.textContent = "{}";
      }

      if (output) {
        output.hidden = true;
      }

      if (summary) {
        summary.textContent = "";
        summary.hidden = true;
      }

      var resultSection = qs(selectorFor("resultSection"));
      if (resultSection) {
        resultSection.setAttribute("data-vp-actions-result-visible", "false");
      }

      localState.resultVisible = false;

      setResultToolsEnabled(false);
      updateResultMeta({
        action: "Keine",
        status: "—",
        httpStatus: "—",
        errors: 0,
        warnings: 0
      });

      if (!silent) {
        setStatus("Ergebnis geleert.", "ok");
        safeDispatch("vectoplan:create:actions-result-cleared", {
          component: GLOBAL_NAME,
          version: ACTIONS_VERSION
        });
      }
    } catch (error) {
      safeWarn("Clear result failed.", error);
    }
  }

  function setResultToolsEnabled(enabled) {
    try {
      var copyButton = qs(selectorFor("resultCopy"));
      var clearButton = qs(selectorFor("resultClear"));

      [copyButton, clearButton].forEach(function (button) {
        if (!button) {
          return;
        }

        button.disabled = !enabled;
        button.setAttribute("aria-disabled", enabled ? "false" : "true");
      });
    } catch (error) {
      safeWarn("Result tools update failed.", error);
    }
  }

  function copyResult(button) {
    try {
      var output = qs(selectorFor("resultOutput"));
      var code = output ? qs(selectorFor("resultCode"), output) : qs(selectorFor("resultCode"));
      var text = code ? code.textContent || "" : output ? output.textContent || "" : "";

      if (!hasUsefulResultText(text)) {
        setStatus("Kein Ergebnis zum Kopieren vorhanden.", "warning");
        return;
      }

      copyText(text).then(function () {
        flashButton(button, className("copied"), "Kopiert");
        setStatus("Ergebnis kopiert.", "ok");

        safeDispatch("vectoplan:create:actions-result-copied", {
          component: GLOBAL_NAME,
          version: ACTIONS_VERSION,
          ok: true
        });
      }).catch(function (error) {
        safeWarn("Copy result clipboard failed.", error);
        setStatus("Kopieren nicht möglich.", "warning");

        safeDispatch("vectoplan:create:actions-result-copied", {
          component: GLOBAL_NAME,
          version: ACTIONS_VERSION,
          ok: false,
          error: normalizeError(error)
        });
      });
    } catch (error) {
      safeWarn("Copy result failed.", error);
      setStatus("Kopieren nicht möglich.", "warning");
    }
  }

  function updateResultFromPayload(action, payload) {
    try {
      var errors = normalizeIssues(payload && payload.errors);
      var warnings = normalizeIssues(payload && payload.warnings);

      updateResultMeta({
        action: action ? actionLabel(action) : "Keine",
        status: payload && payload.status ? payload.status : "ready",
        httpStatus: payload && typeof payload._http_status !== "undefined" ? payload._http_status : "—",
        errors: errors.length,
        warnings: warnings.length
      });
    } catch (error) {
      safeWarn("Update result from payload failed.", error);
    }
  }

  function updateResultMeta(meta) {
    try {
      setText(selectorFor("resultLastAction"), meta.action || "Keine");
      setText(selectorFor("resultStatus"), meta.status || "—");
      setText(selectorFor("resultHttpStatus"), String(typeof meta.httpStatus !== "undefined" ? meta.httpStatus : "—"));
      setText(selectorFor("resultErrorCount"), String(typeof meta.errors === "number" ? meta.errors : 0));
      setText(selectorFor("resultWarningCount"), String(typeof meta.warnings === "number" ? meta.warnings : 0));
    } catch (error) {
      safeWarn("Update result meta failed.", error);
    }
  }

  function applyResultToUi(result) {
    try {
      clearFieldIssues(document);

      var errors = normalizeIssues(result && result.errors);
      var warnings = normalizeIssues(result && result.warnings);
      var info = normalizeIssues(result && result.info);

      errors.forEach(function (issue) {
        markFieldIssue(issue, "error");
      });

      warnings.forEach(function (issue) {
        markFieldIssue(issue, "warning");
      });

      info.forEach(function (issue) {
        markFieldIssue(issue, "info");
      });

      if (result && result.ok) {
        markKnownRequiredFieldsValid();
      }
    } catch (error) {
      safeWarn("Apply result to UI failed.", error);
    }
  }

  function clearFieldIssues(root) {
    try {
      var scope = root || document;

      qsa("." + className("invalid"), scope).forEach(function (field) {
        field.classList.remove(className("invalid"));
        field.removeAttribute("aria-invalid");
      });

      qsa("." + className("valid"), scope).forEach(function (field) {
        field.classList.remove(className("valid"));
      });

      qsa("[data-create-field-message='true']", scope).forEach(function (node) {
        node.remove();
      });
    } catch (error) {
      safeWarn("Clear field issues failed.", error);
    }
  }

  function markFieldIssue(issue, level) {
    try {
      var fieldName = issue && issue.field ? issue.field : "";

      if (!fieldName) {
        return;
      }

      var normalized = normalizeIssueFieldName(fieldName);
      var field = null;

      if (normalized === "save") {
        field = qs("[data-create-action='save']");
      }

      if (!field) {
        var candidates = [
          "[name='" + cssEscape(normalized) + "']",
          "[data-create-field='" + cssEscape(normalized) + "']"
        ];

        for (var i = 0; i < candidates.length; i += 1) {
          field = qs(candidates[i]);

          if (field) {
            break;
          }
        }
      }

      if (!field && normalized.indexOf(".") !== -1) {
        var lastPart = normalized.split(".").pop();

        field = qs("[name='" + cssEscape(lastPart) + "'], [data-create-field='" + cssEscape(lastPart) + "']");
      }

      if (!field) {
        return;
      }

      if (level === "error") {
        field.classList.add(className("invalid"));
        field.setAttribute("aria-invalid", "true");
      }

      var label = field.closest(".vp-create-field") ||
        field.closest(".vp-variant-field") ||
        field.closest("label") ||
        field.parentElement;

      if (!label) {
        return;
      }

      var message = document.createElement("span");
      message.setAttribute("data-create-field-message", "true");

      if (level === "error") {
        message.className = "vp-create-field-error";
      } else if (level === "warning") {
        message.className = "vp-create-field-warning";
      } else {
        message.className = "vp-create-field-info";
      }

      message.textContent = issue.message || issue.code || "Hinweis";

      label.appendChild(message);
    } catch (error) {
      safeWarn("Mark field issue failed.", error);
    }
  }

  function markKnownRequiredFieldsValid() {
    try {
      var requiredFields = qsa("[data-create-required='true'], input[required], select[required], textarea[required]");

      requiredFields.forEach(function (field) {
        try {
          if (field && field.value) {
            field.classList.add(className("valid"));
          }
        } catch (fieldError) {
          safeWarn("Required field valid mark skipped.", fieldError);
        }
      });
    } catch (error) {
      safeWarn("Mark known required fields valid failed.", error);
    }
  }

  function handleRuntimeError(action, error) {
    try {
      var payload = {
        ok: false,
        status: "frontend_error",
        action: action,
        errors: [
          {
            severity: "error",
            code: "frontend_error",
            message: String(error && error.message ? error.message : error)
          }
        ]
      };

      localState.lastResult = payload;
      localState.lastAction = action;
      localState.lastError = normalizeError(error);

      if (core && core.state) {
        core.state.lastResult = payload;
        core.state.lastAction = action;
        core.state.lastError = error;
      }

      printOutput(payload, { reveal: true });
      updateResultFromPayload(action, payload);
      setStatus(actionLabel(action) + " fehlgeschlagen.", "error");

      safeError("Action failed: " + action, error);

      return payload;
    } catch (handlerError) {
      safeError("Runtime error handler failed.", handlerError);

      return {
        ok: false,
        status: "frontend_error_handler_failed",
        action: action
      };
    }
  }

  function buildBlockedResult(action, code, message) {
    try {
      var result = {
        ok: false,
        status: code || "blocked",
        action: action,
        errors: [
          {
            severity: "warning",
            code: code || "blocked",
            message: message || "Aktion wurde blockiert."
          }
        ]
      };

      localState.lastResult = result;
      localState.lastAction = action;

      printOutput(result, { reveal: true });
      updateResultFromPayload(action, result);
      setStatus(message || "Aktion blockiert.", "warning");

      return result;
    } catch (error) {
      return {
        ok: false,
        status: code || "blocked",
        action: action
      };
    }
  }

  function dispatchActionEvent(eventName, action, extraDetail) {
    try {
      var detail = Object.assign({
        action: action,
        label: actionLabel(action)
      }, extraDetail || {});

      safeDispatch(eventName, detail);
    } catch (error) {
      safeWarn("Action event dispatch failed: " + eventName, error);
    }
  }

  function resolveActionRouteUrl(action, fallbackPath) {
    try {
      var normalizedAction = action === "package_plan" ? "package-plan" : action;
      var routeKey = normalizedAction === "package-plan" ? "package_plan" : normalizedAction;
      var fallback = fallbackPath || ACTION_PATHS[normalizedAction] || "/" + normalizedAction;

      if (core && typeof core.resolveRouteUrl === "function") {
        return core.resolveRouteUrl(routeKey, fallback);
      }

      var apiPrefix = getApiPrefix();

      return apiPrefix.replace(/\/$/, "") + fallback;
    } catch (error) {
      safeWarn("Resolve action route URL failed.", error);
      return getApiPrefix().replace(/\/$/, "") + (fallbackPath || "");
    }
  }

  function triggerBrowserDownload(blob, filename) {
    try {
      var url = URL.createObjectURL(blob);
      var anchor = document.createElement("a");

      anchor.href = url;
      anchor.download = filename || "package.vplib";
      anchor.rel = "noopener";
      anchor.style.display = "none";

      document.body.appendChild(anchor);
      anchor.click();

      window.setTimeout(function () {
        try {
          URL.revokeObjectURL(url);
          anchor.remove();
        } catch (error) {
          /* no-op */
        }
      }, 0);
    } catch (error) {
      safeError("Browser download trigger failed.", error);
      throw error;
    }
  }

  function extractDownloadFilename(response) {
    try {
      var disposition = response.headers.get("content-disposition") || "";
      var utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);

      if (utf8Match && utf8Match[1]) {
        try {
          return sanitizeFilename(decodeURIComponent(utf8Match[1]));
        } catch (error) {
          return sanitizeFilename(utf8Match[1]);
        }
      }

      var normalMatch = disposition.match(/filename="?([^"]+)"?/i);

      if (normalMatch && normalMatch[1]) {
        return sanitizeFilename(normalMatch[1]);
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function inferDownloadFilename(payload) {
    try {
      var name = payload && (payload.family_name || payload.family_slug)
        ? payload.family_name || payload.family_slug
        : "package";
      var filename = slugify(name) || "package";

      return sanitizeFilename(filename + ".vplib");
    } catch (error) {
      return "package.vplib";
    }
  }

  function sanitizeFilename(value) {
    try {
      var text = String(value || "package.vplib")
        .replace(/\\/g, "/")
        .split("/")
        .pop()
        .replace(/\0/g, "")
        .trim();

      if (!text) {
        text = "package.vplib";
      }

      text = text.replace(/[^a-zA-Z0-9._ -]+/g, "_").replace(/^[ ._]+|[ ._]+$/g, "");

      if (!text) {
        text = "package.vplib";
      }

      if (!/\.vplib$/i.test(text)) {
        text += ".vplib";
      }

      return text.slice(0, 180);
    } catch (error) {
      return "package.vplib";
    }
  }

  function flashButton(button, flashClass, temporaryText) {
    try {
      if (!button) {
        return;
      }

      var oldText = button.textContent;

      if (flashClass) {
        button.classList.add(flashClass);
      }

      if (temporaryText) {
        button.textContent = temporaryText;
      }

      window.setTimeout(function () {
        try {
          if (flashClass) {
            button.classList.remove(flashClass);
          }

          if (temporaryText) {
            button.textContent = oldText;
          }
        } catch (error) {
          /* no-op */
        }
      }, 900);
    } catch (error) {
      safeWarn("Flash button failed.", error);
    }
  }

  function normalizeAction(action) {
    try {
      var text = String(action || "").trim();

      if (!text) {
        return "";
      }

      text = text.replace(/_/g, "-");

      if (KNOWN_ACTIONS[text]) {
        return text === "package_plan" ? "package-plan" : text;
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function summarizePayload(payload) {
    try {
      if (payloadRuntime && typeof payloadRuntime.getState === "function") {
        var payloadState = payloadRuntime.getState();

        if (payloadState && payloadState.lastPayloadSummary) {
          return payloadState.lastPayloadSummary;
        }
      }

      var variants = [];

      if (payload && Array.isArray(payload.definition_variants)) {
        variants = payload.definition_variants;
      } else if (payload && payload.definition_variants_json) {
        variants = safeJsonParse(payload.definition_variants_json, []);
      }

      var uploadsSummary = payload && (payload.uploads_summary || payload.uploadsSummary)
        ? payload.uploads_summary || payload.uploadsSummary
        : {};

      return {
        family_name: payload && payload.family_name ? payload.family_name : "",
        domain: payload && payload.domain ? payload.domain : "",
        category: payload && payload.category ? payload.category : "",
        subcategory: payload && payload.subcategory ? payload.subcategory : "",
        object_kind: payload && payload.object_kind ? payload.object_kind : "",
        definition_variant_count: Array.isArray(variants) ? variants.length : 0,
        default_variant_id: payload && payload.default_variant_id ? payload.default_variant_id : "",
        upload_file_count: uploadsSummary.fileCount || uploadsSummary.file_count || 0,
        upload_error_count: uploadsSummary.errorCount || uploadsSummary.error_count || 0,
        timestamp: timestamp()
      };
    } catch (error) {
      return {
        summary_error: String(error && error.message ? error.message : error)
      };
    }
  }

  function updateUploadCountsFromSummary(summary) {
    try {
      localState.lastUploadFileCount = parseInt(summary.upload_file_count || summary.fileCount || summary.file_count || 0, 10) || 0;
      localState.lastUploadErrorCount = parseInt(summary.upload_error_count || summary.errorCount || summary.error_count || 0, 10) || 0;
    } catch (error) {
      /* no-op */
    }
  }

  function resolveForm(form) {
    try {
      if (form && form.nodeType === 1) {
        return form;
      }

      return qs(selectorFor("form"));
    } catch (error) {
      return null;
    }
  }

  function getState() {
    try {
      return {
        version: ACTIONS_VERSION,
        initialized: initialized,
        bindingDone: bindingDone,
        pending: localState.pending,
        currentAction: localState.currentAction,
        lastAction: localState.lastAction,
        lastResult: clone(localState.lastResult),
        lastError: localState.lastError,
        lastHttpStatus: localState.lastHttpStatus,
        lastPayloadSummary: localState.lastPayloadSummary,
        actionCount: localState.actionCount,
        downloadCount: localState.downloadCount,
        saveConfirmCount: localState.saveConfirmCount,
        resultVisible: localState.resultVisible,
        writeEnabled: isWriteEnabled(),
        lastRoute: localState.lastRoute,
        lastRequestAt: localState.lastRequestAt,
        lastResponseAt: localState.lastResponseAt,
        lastUploadFileCount: localState.lastUploadFileCount,
        lastUploadErrorCount: localState.lastUploadErrorCount
      };
    } catch (error) {
      return {
        version: ACTIONS_VERSION,
        initialized: initialized,
        state_error: String(error && error.message ? error.message : error)
      };
    }
  }

  function normalizeError(error) {
    try {
      return {
        message: String(error && error.message ? error.message : error),
        stack: error && error.stack ? String(error.stack) : "",
        timestamp: timestamp()
      };
    } catch (normalizationError) {
      return {
        message: "Unknown error",
        timestamp: timestamp()
      };
    }
  }

  function timestamp() {
    try {
      return new Date().toISOString();
    } catch (error) {
      return "";
    }
  }

  function ensureCore() {
    try {
      if (!core) {
        core = window[CORE_NAME] || buildFallbackCore();
      }

      if (!core) {
        throw new Error("VectoplanCreateCore is not available.");
      }

      if (!selectors) {
        selectors = Object.assign({}, DEFAULT_SELECTORS, core.selectors || {});
      }

      if (!classes) {
        classes = Object.assign({}, DEFAULT_CLASSES, core.classes || {});
      }

      if (!payloadRuntime) {
        payloadRuntime = window[PAYLOAD_NAME] || null;
      }

      return core;
    } catch (error) {
      throw error;
    }
  }

  function selectorFor(key) {
    try {
      if (!selectors) {
        selectors = Object.assign({}, DEFAULT_SELECTORS, core && core.selectors ? core.selectors : {});
      }

      return selectors[key] || DEFAULT_SELECTORS[key] || "";
    } catch (error) {
      return DEFAULT_SELECTORS[key] || "";
    }
  }

  function className(key) {
    try {
      if (!classes) {
        classes = Object.assign({}, DEFAULT_CLASSES, core && core.classes ? core.classes : {});
      }

      return classes[key] || DEFAULT_CLASSES[key] || key;
    } catch (error) {
      return DEFAULT_CLASSES[key] || key;
    }
  }

  function qs(selector, root) {
    try {
      if (!selector) {
        return null;
      }

      if (core && typeof core.qs === "function") {
        return core.qs(selector, root || document);
      }

      return (root || document).querySelector(selector);
    } catch (error) {
      return null;
    }
  }

  function qsa(selector, root) {
    try {
      if (!selector) {
        return [];
      }

      if (core && typeof core.qsa === "function") {
        return core.qsa(selector, root || document);
      }

      return Array.prototype.slice.call((root || document).querySelectorAll(selector));
    } catch (error) {
      return [];
    }
  }

  function toArray(value) {
    try {
      return Array.prototype.slice.call(value || []);
    } catch (error) {
      return [];
    }
  }

  function getFieldValue(form, name) {
    try {
      if (core && typeof core.getFieldValue === "function") {
        return core.getFieldValue(form, name);
      }

      var safeForm = resolveForm(form);

      if (!safeForm || !name) {
        return "";
      }

      var field = safeForm.elements ? safeForm.elements[name] : null;

      if (!field || field.nodeType !== 1) {
        field = qs("[name='" + cssEscape(name) + "']", safeForm);
      }

      if (!field || typeof field.value === "undefined") {
        return "";
      }

      return String(field.value || "");
    } catch (error) {
      return "";
    }
  }

  function setText(selector, value) {
    try {
      if (core && typeof core.setText === "function") {
        core.setText(selector, value);
        return true;
      }

      var node = qs(selector);

      if (node) {
        node.textContent = value === null || typeof value === "undefined" ? "" : String(value);
      }

      return !!node;
    } catch (error) {
      return false;
    }
  }

  function setStatus(message, state) {
    try {
      if (core && typeof core.setStatus === "function") {
        core.setStatus(message, state);
      }

      var statusNode = qs(selectorFor("actionStatus"));

      if (statusNode) {
        statusNode.textContent = message || "Bereit.";
      }

      var card = qs(selectorFor("actionCard"));
      if (card) {
        card.setAttribute("data-vp-actions-state", state || "idle");
      }

      safeDispatch("vectoplan:create:actions-status-changed", {
        component: GLOBAL_NAME,
        version: ACTIONS_VERSION,
        message: message || "",
        state: state || "idle"
      });
    } catch (error) {
      safeWarn("Set status failed.", error);
    }
  }

  function buildJsonHeaders(accept) {
    try {
      var headers = {
        "Content-Type": "application/json",
        "Accept": accept || "application/json"
      };

      var csrf = getCsrfToken();

      if (csrf) {
        headers["X-CSRFToken"] = csrf;
        headers["X-CSRF-Token"] = csrf;
      }

      return headers;
    } catch (error) {
      return {
        "Content-Type": "application/json",
        "Accept": accept || "application/json"
      };
    }
  }

  function getCsrfToken() {
    try {
      var meta = qs("meta[name='csrf-token'], meta[name='csrf_token']");
      if (meta && meta.getAttribute("content")) {
        return meta.getAttribute("content");
      }

      var field = qs("input[name='csrf_token'], input[name='csrfmiddlewaretoken']");
      if (field && field.value) {
        return field.value;
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function getApiPrefix() {
    try {
      var card = qs(selectorFor("actionCard"));
      var fromCard = card ? card.getAttribute("data-create-api-prefix") : "";

      if (fromCard) {
        return fromCard;
      }

      if (core && core.state && core.state.apiPrefix) {
        return core.state.apiPrefix;
      }

      return "/api/v1/vplib/create";
    } catch (error) {
      return "/api/v1/vplib/create";
    }
  }

  function isWriteEnabled() {
    try {
      if (core && typeof core.isWriteEnabled === "function") {
        return core.isWriteEnabled();
      }

      var card = qs(selectorFor("actionCard"));
      var raw = card ? card.getAttribute("data-create-write-enabled") : "";

      return toBoolean(raw, false);
    } catch (error) {
      return false;
    }
  }

  function isCorePending() {
    try {
      return !!(core && core.state && core.state.pending);
    } catch (error) {
      return false;
    }
  }

  function setCorePending(value) {
    try {
      if (core && typeof core.setPending === "function") {
        core.setPending(!!value);
        return;
      }

      if (core && core.state) {
        core.state.pending = !!value;
      }
    } catch (error) {
      /* no-op */
    }
  }

  function acquireActionLock(name, ttl) {
    try {
      if (core && typeof core.acquireLock === "function") {
        return core.acquireLock(name, ttl);
      }

      var attr = "data-vp-lock-" + String(name || "lock").replace(/[^a-z0-9_-]/gi, "-");
      var now = Date.now();
      var existing = parseInt(document.documentElement.getAttribute(attr) || "0", 10);

      if (existing && now - existing < (ttl || ACTION_LOCK_MS)) {
        return false;
      }

      document.documentElement.setAttribute(attr, String(now));
      return true;
    } catch (error) {
      return true;
    }
  }

  function releaseActionLock(name) {
    try {
      if (core && typeof core.releaseLock === "function") {
        core.releaseLock(name);
        return;
      }

      var attr = "data-vp-lock-" + String(name || "lock").replace(/[^a-z0-9_-]/gi, "-");
      document.documentElement.removeAttribute(attr);
    } catch (error) {
      /* no-op */
    }
  }

  function actionLabel(action) {
    try {
      if (core && typeof core.actionLabel === "function") {
        return core.actionLabel(action);
      }

      return ACTION_LABELS[normalizeAction(action)] || action || "Aktion";
    } catch (error) {
      return action || "Aktion";
    }
  }

  function stringifyJson(value) {
    try {
      if (core && typeof core.stringifyJson === "function") {
        return core.stringifyJson(value);
      }

      return JSON.stringify(value === undefined ? null : value, null, 2);
    } catch (error) {
      return "null";
    }
  }

  function safeJsonParse(value, fallbackValue) {
    try {
      if (core && typeof core.safeJsonParse === "function") {
        return core.safeJsonParse(value, fallbackValue);
      }

      if (value === null || typeof value === "undefined" || String(value).trim() === "") {
        return fallbackValue;
      }

      return JSON.parse(value);
    } catch (error) {
      return fallbackValue;
    }
  }

  function clone(value) {
    try {
      if (core && typeof core.clone === "function") {
        return core.clone(value);
      }

      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      return value;
    }
  }

  function normalizeIssues(value) {
    try {
      if (core && typeof core.normalizeIssues === "function") {
        return core.normalizeIssues(value);
      }

      if (!value) {
        return [];
      }

      if (Array.isArray(value)) {
        return value;
      }

      if (typeof value === "object") {
        return [value];
      }

      return [{
        severity: "info",
        message: String(value)
      }];
    } catch (error) {
      return [];
    }
  }

  function normalizeIssueFieldName(value) {
    try {
      if (core && typeof core.normalizeIssueFieldName === "function") {
        return core.normalizeIssueFieldName(value);
      }

      return String(value || "").trim().replace(/\./g, "_");
    } catch (error) {
      return "";
    }
  }

  function cssEscape(value) {
    try {
      if (core && typeof core.cssEscape === "function") {
        return core.cssEscape(value);
      }

      if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(String(value || ""));
      }

      return String(value || "").replace(/["\\]/g, "\\$&");
    } catch (error) {
      return String(value || "");
    }
  }

  function slugify(value) {
    try {
      if (core && typeof core.slugify === "function") {
        return core.slugify(value);
      }

      return String(value || "")
        .trim()
        .toLowerCase()
        .replace(/ä/g, "ae")
        .replace(/ö/g, "oe")
        .replace(/ü/g, "ue")
        .replace(/ß/g, "ss")
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
    } catch (error) {
      return "";
    }
  }

  function copyText(text) {
    try {
      if (core && typeof core.copyText === "function") {
        return core.copyText(text);
      }

      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        return navigator.clipboard.writeText(text);
      }

      return new Promise(function (resolve, reject) {
        try {
          var textarea = document.createElement("textarea");
          textarea.value = text || "";
          textarea.setAttribute("readonly", "readonly");
          textarea.style.position = "fixed";
          textarea.style.left = "-9999px";
          textarea.style.top = "0";
          document.body.appendChild(textarea);
          textarea.focus();
          textarea.select();

          var ok = document.execCommand("copy");
          document.body.removeChild(textarea);

          if (ok) {
            resolve();
          } else {
            reject(new Error("execCommand copy failed"));
          }
        } catch (error) {
          reject(error);
        }
      });
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function safeSetAttribute(node, name, value) {
    try {
      if (!node || !name) {
        return false;
      }

      if (core && typeof core.safeSetAttribute === "function") {
        core.safeSetAttribute(node, name, value);
        return true;
      }

      node.setAttribute(name, value);
      return true;
    } catch (error) {
      return false;
    }
  }

  function safeDispatch(eventName, detail) {
    try {
      if (core && typeof core.dispatch === "function") {
        core.dispatch(eventName, detail || {});
        return true;
      }

      document.dispatchEvent(new CustomEvent(eventName, {
        bubbles: true,
        cancelable: false,
        detail: detail || {}
      }));

      return true;
    } catch (error) {
      fallbackWarn("Dispatch failed: " + eventName, error);
      return false;
    }
  }

  function bindOnce(key, callback) {
    try {
      if (core && typeof core.bindOnce === "function") {
        core.bindOnce(key, callback);
        return;
      }

      var attr = "data-vp-" + String(key || "bind-once").replace(/[^a-z0-9_-]/gi, "-");

      if (document.documentElement.getAttribute(attr) === "true") {
        return;
      }

      document.documentElement.setAttribute(attr, "true");

      if (typeof callback === "function") {
        callback();
      }
    } catch (error) {
      safeWarn("bindOnce failed: " + key, error);
    }
  }

  function hasUsefulResultText(text) {
    try {
      var value = String(text || "").trim();

      return !!value && value !== "{}" && value !== "null" && value !== "undefined";
    } catch (error) {
      return false;
    }
  }

  function emptyUploadPayload(kind) {
    return {
      version: ACTIONS_VERSION,
      kind: kind || "generic_upload",
      purpose: getDefaultUploadPurpose(kind),
      count: 0,
      files: [],
      errors: [],
      ok: true,
      backend_enabled: false,
      backendEnabled: false,
      local_only: true,
      localOnly: true,
      updated_at: timestamp(),
      updatedAt: timestamp()
    };
  }

  function normalizeUploadPayload(payload, fallbackKind) {
    try {
      var source = payload && typeof payload === "object" ? payload : {};
      var kind = source.kind || fallbackKind || "generic_upload";
      var files = Array.isArray(source.files) ? source.files : [];
      var errors = Array.isArray(source.errors) ? source.errors : [];

      return {
        version: source.version || ACTIONS_VERSION,
        kind: kind,
        purpose: source.purpose || getDefaultUploadPurpose(kind),
        count: parseInt(source.count, 10) || files.length,
        files: files,
        errors: errors,
        ok: source.ok !== false && errors.length === 0,
        backend_enabled: false,
        backendEnabled: false,
        local_only: true,
        localOnly: true,
        updated_at: source.updated_at || source.updatedAt || timestamp(),
        updatedAt: source.updatedAt || source.updated_at || timestamp(),
        source: source.source || "actions"
      };
    } catch (error) {
      return emptyUploadPayload(fallbackKind || "generic_upload");
    }
  }

  function fileToPayloadValue(file) {
    try {
      return {
        name: file.name || "",
        size: file.size || 0,
        size_label: fileSizeLabel(file.size || 0),
        sizeLabel: fileSizeLabel(file.size || 0),
        type: file.type || "",
        extension: extensionFromName(file.name || ""),
        last_modified: file.lastModified || null,
        lastModified: file.lastModified || null,
        backend_stored: false,
        backendStored: false,
        local_only: true,
        localOnly: true
      };
    } catch (error) {
      return {
        name: "",
        size: 0,
        type: "",
        backend_stored: false,
        local_only: true
      };
    }
  }

  function fileToUploadFile(file, index, kind, purpose, fieldKey) {
    try {
      var base = file ? fileToPayloadValue(file) : {};

      base.index = index || 0;
      base.kind = kind || "generic_upload";
      base.purpose = purpose || getDefaultUploadPurpose(kind);
      base.field_key = fieldKey || "";
      base.fieldKey = fieldKey || "";
      base.valid = true;
      base.errors = [];

      return base;
    } catch (error) {
      return {
        index: index || 0,
        name: "",
        size: 0,
        type: "",
        kind: kind || "generic_upload",
        purpose: purpose || getDefaultUploadPurpose(kind),
        field_key: fieldKey || "",
        fieldKey: fieldKey || "",
        valid: true,
        errors: []
      };
    }
  }

  function isFileValue(value) {
    try {
      return typeof File !== "undefined" && value instanceof File;
    } catch (error) {
      return false;
    }
  }

  function inferFieldKeyFromName(fieldName) {
    try {
      var match = String(fieldName || "").match(/\[([^\]]+)\]/);

      return match && match[1] ? match[1] : "";
    } catch (error) {
      return "";
    }
  }

  function getDefaultUploadPurpose(kind) {
    try {
      if (kind === "geometry_model") {
        return "geometry_model";
      }

      if (kind === "technical_documents") {
        return "manufacturer_documents";
      }

      if (kind === "variant_documents") {
        return "variant_document_list";
      }

      return kind || "upload";
    } catch (error) {
      return "upload";
    }
  }

  function extensionFromName(fileName) {
    try {
      var text = String(fileName || "").trim();

      if (!text || text.indexOf(".") < 0) {
        return "";
      }

      return text.split(".").pop().toLowerCase();
    } catch (error) {
      return "";
    }
  }

  function fileSizeLabel(bytes) {
    try {
      var value = parseInt(bytes, 10);

      if (!Number.isFinite(value) || value <= 0) {
        return "0 B";
      }

      if (value < 1024) {
        return value + " B";
      }

      if (value < 1024 * 1024) {
        return (value / 1024).toFixed(1).replace(".0", "") + " KB";
      }

      return (value / (1024 * 1024)).toFixed(1).replace(".0", "") + " MB";
    } catch (error) {
      return "";
    }
  }

  function toBoolean(value, fallbackValue) {
    try {
      if (core && typeof core.toBoolean === "function") {
        return core.toBoolean(value, fallbackValue);
      }

      if (value === true || value === false) {
        return value;
      }

      var text = String(value || "").trim().toLowerCase();

      if (["true", "1", "yes", "ja", "on", "active", "enabled"].indexOf(text) >= 0) {
        return true;
      }

      if (["false", "0", "no", "nein", "off", "inactive", "disabled"].indexOf(text) >= 0) {
        return false;
      }

      return !!fallbackValue;
    } catch (error) {
      return !!fallbackValue;
    }
  }

  function safeWarn(message, error) {
    try {
      if (core && typeof core.warn === "function") {
        core.warn(message, error);
        return;
      }
    } catch (coreError) {
      /* fallback below */
    }

    fallbackWarn(message, error);
  }

  function safeError(message, error) {
    try {
      if (core && typeof core.error === "function") {
        core.error(message, error);
        return;
      }
    } catch (coreError) {
      /* fallback below */
    }

    fallbackWarn(message, error);
  }

  function fallbackWarn(message, error) {
    try {
      if (window.console && typeof window.console.warn === "function") {
        if (typeof error !== "undefined") {
          window.console.warn("[VPLIB Create Actions] " + message, error);
        } else {
          window.console.warn("[VPLIB Create Actions] " + message);
        }
      }
    } catch (consoleError) {
      /* no-op */
    }
  }

  function buildFallbackCore() {
    try {
      return {
        selectors: DEFAULT_SELECTORS,
        classes: DEFAULT_CLASSES,
        state: {
          pending: false,
          apiPrefix: "/api/v1/vplib/create"
        },
        qs: function (selector, root) {
          return (root || document).querySelector(selector);
        },
        qsa: function (selector, root) {
          return Array.prototype.slice.call((root || document).querySelectorAll(selector));
        },
        cssEscape: cssEscape,
        stringifyJson: stringifyJson,
        safeJsonParse: safeJsonParse,
        clone: clone,
        slugify: slugify,
        toBoolean: toBoolean,
        getFieldValue: getFieldValue,
        normalizeIssues: normalizeIssues,
        normalizeIssueFieldName: normalizeIssueFieldName,
        actionLabel: actionLabel,
        isWriteEnabled: isWriteEnabled,
        setPending: setCorePending,
        setStatus: setStatus,
        setText: setText,
        safeSetAttribute: safeSetAttribute,
        dispatch: safeDispatch,
        copyText: copyText,
        bindOnce: bindOnce,
        registerModule: function () {},
        refreshContext: function () {},
        resolveRouteUrl: function (routeKey, fallbackPath) {
          return getApiPrefix().replace(/\/$/, "") + (fallbackPath || "/" + routeKey);
        },
        acquireLock: acquireActionLock,
        releaseLock: releaseActionLock,
        warn: fallbackWarn,
        error: fallbackWarn
      };
    } catch (error) {
      return null;
    }
  }

  var api = {
    version: ACTIONS_VERSION,

    initialize: initialize,

    runAction: runAction,
    postJson: postJson,
    fetchJson: fetchJson,
    confirmAndSave: confirmAndSave,
    downloadVplib: downloadVplib,

    printOutput: printOutput,
    clearResult: clearResult,
    copyResult: copyResult,
    applyResultToUi: applyResultToUi,
    updateResultFromPayload: updateResultFromPayload,
    updateResultMeta: updateResultMeta,

    setBusy: setBusy,
    enforceStaticDisabledButtons: enforceStaticDisabledButtons,
    clearFieldIssues: clearFieldIssues,
    markFieldIssue: markFieldIssue,

    getState: getState
  };

  window[GLOBAL_NAME] = api;

  try {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        boot(0);
      }, { once: true });
    } else {
      boot(0);
    }
  } catch (error) {
    fallbackWarn("Actions runtime scheduling failed.", error);
  }
})();