/* services/vectoplan-library/static/library_admin/js/create_actions.js */

/* -----------------------------------------------------------------------------
  VECTOPLAN Library · VPLIB Create Actions Runtime

  Zweck:
  - Eigenständige Action-Schicht für /create.
  - Entlastet die bisher zu große create.js.
  - Führt Draft, Validate, Package-Plan, Download und Save aus.
  - Nutzt create_payload.js für robuste Payload-Erzeugung.
  - Hält Result-/Status-/Fehler-UI stabil.
  - Markiert Backend-Fehler an Feldern.
  - Verhindert parallele Actions.
  - Erzeugt keine VPLIB-Dateien im Browser.
  - Download wird nur vom Backend als Blob übernommen.

  Abhängigkeit:
  - Muss nach create_core.js geladen werden.
  - Sollte nach create_payload.js geladen werden.
  - Erwartet window.VectoplanCreateCore.
  - Nutzt optional window.VectoplanCreatePayload.

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
  var ACTIONS_VERSION = "0.4.0";
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
    resultVisible: false
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

        fallbackWarn("Core runtime missing; actions runtime not initialized.");
        return;
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

      core = coreRuntime || window[CORE_NAME];

      if (!core) {
        fallbackWarn("Cannot initialize actions without create_core.js.");
        return api;
      }

      payloadRuntime = window[PAYLOAD_NAME] || null;
      selectors = core.selectors || {};
      classes = core.classes || {};

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

      core.safeSetAttribute(document.documentElement, "data-vp-create-actions-ready", "true");
      core.safeSetAttribute(document.documentElement, "data-vp-create-actions-version", ACTIONS_VERSION);

      core.dispatch("vectoplan:create:actions-ready", getState());

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

      if (core && typeof core.bindOnce === "function") {
        core.bindOnce("create-actions-click", bindActionButtons);
        core.bindOnce("create-actions-result-controls", bindResultControls);
        core.bindOnce("create-actions-write-state", bindWriteStateUpdates);
      } else {
        bindActionButtons();
        bindResultControls();
        bindWriteStateUpdates();
      }
    } catch (error) {
      safeError("Actions control binding failed.", error);
    }
  }

  function bindActionButtons() {
    try {
      document.addEventListener("click", function (event) {
        try {
          var button = event.target && event.target.closest ? event.target.closest(selectors.actionButton) : null;

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

          if (localState.pending || core.state.pending) {
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
          var copyButton = event.target && event.target.closest ? event.target.closest(selectors.resultCopy) : null;

          if (copyButton) {
            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            copyResult(copyButton);
            return;
          }

          var clearButton = event.target && event.target.closest ? event.target.closest(selectors.resultClear) : null;

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

      document.addEventListener("vectoplan:create:payload-ready", function () {
        try {
          payloadRuntime = window[PAYLOAD_NAME] || payloadRuntime;
        } catch (error) {
          safeWarn("Payload ready binding failed.", error);
        }
      });
    } catch (error) {
      safeWarn("Write state update binding failed.", error);
    }
  }

  async function runAction(action, form, sourceButton) {
    var lockAcquired = false;

    try {
      ensureCore();

      var normalizedAction = normalizeAction(action);

      if (!normalizedAction) {
        throw new Error("Unbekannte Aktion: " + action);
      }

      if (localState.pending || core.state.pending) {
        return buildBlockedResult(normalizedAction, "action_pending", "Es läuft bereits eine Aktion.");
      }

      lockAcquired = core.acquireLock(ACTION_LOCK, ACTION_LOCK_MS);

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
        }, { reveal: false });
      }

      localState.pending = true;
      localState.currentAction = normalizedAction;
      localState.actionCount += 1;

      dispatchActionEvent("vectoplan:create:action-start", normalizedAction, {
        label: core.actionLabel(normalizedAction)
      });

      setBusy(safeForm, true, sourceButton);
      core.setStatus(core.actionLabel(normalizedAction) + " läuft …", "loading");
      updateResultFromPayload(normalizedAction, {
        ok: true,
        status: "pending",
        _http_status: "—",
        errors: [],
        warnings: []
      });

      var payload = collectPayload(safeForm, {
        source: "action:" + normalizedAction
      });

      localState.lastPayloadSummary = summarizePayload(payload);

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

      dispatchActionEvent("vectoplan:create:action-complete", normalizedAction, {
        result: result
      });

      return result;
    } catch (error) {
      var failedAction = normalizeAction(action) || String(action || "unknown");

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
      core.setPending(false);

      if (lockAcquired) {
        window.setTimeout(function () {
          try {
            core.releaseLock(ACTION_LOCK);
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

      core.state.lastResult = response;
      core.state.lastAction = normalizedAction;

      printOutput(response, { reveal: true });
      applyResultToUi(response);
      updateResultFromPayload(normalizedAction, response);

      if (response && response.ok) {
        core.setStatus(core.actionLabel(normalizedAction) + " erfolgreich.", "ok");
      } else {
        core.setStatus(core.actionLabel(normalizedAction) + " fehlgeschlagen.", "error");
      }

      return response;
    } catch (error) {
      throw error;
    }
  }

  async function confirmAndSave(payload) {
    try {
      var writeEnabled = core.isWriteEnabled();

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
          ]
        };

        localState.lastResult = blocked;
        localState.lastAction = "save";

        core.state.lastResult = blocked;
        core.state.lastAction = "save";

        printOutput(blocked, { reveal: true });
        applyResultToUi(blocked);
        updateResultFromPayload("save", blocked);
        core.setStatus("Speichern ist deaktiviert.", "warning");

        return blocked;
      }

      localState.saveConfirmCount += 1;

      var familyName = String(payload && payload.family_name ? payload.family_name : "").trim();
      var message = "Package wirklich in den Library-Source-Bereich speichern?";

      if (familyName) {
        message += "\n\nFamily: " + familyName;
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
          ]
        };

        localState.lastResult = cancelled;
        localState.lastAction = "save";

        core.state.lastResult = cancelled;
        core.state.lastAction = "save";

        printOutput(cancelled, { reveal: true });
        updateResultFromPayload("save", cancelled);
        core.setStatus("Speichern abgebrochen.", "warning");

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

      var response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/octet-stream, application/json"
        },
        body: JSON.stringify(payload || {}),
        credentials: "same-origin"
      });

      var contentType = response.headers.get("content-type") || "";

      if (!response.ok || contentType.indexOf("application/json") !== -1) {
        var errorPayload = await readResponseAsJson(response);

        localState.lastResult = errorPayload;
        localState.lastAction = "download";
        localState.lastHttpStatus = response.status;

        core.state.lastResult = errorPayload;
        core.state.lastAction = "download";

        printOutput(errorPayload, { reveal: true });
        applyResultToUi(errorPayload);
        updateResultFromPayload("download", errorPayload);
        core.setStatus("Download fehlgeschlagen.", "error");

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
        _http_status: response.status,
        headers: {
          create_status: response.headers.get("x-vectoplan-create-status") || "",
          create_route: response.headers.get("x-vectoplan-create-route") || "",
          create_version: response.headers.get("x-vectoplan-create-version") || ""
        }
      };

      localState.lastResult = result;
      localState.lastAction = "download";
      localState.lastHttpStatus = response.status;

      core.state.lastResult = result;
      core.state.lastAction = "download";

      printOutput(result, { reveal: true });
      updateResultFromPayload("download", result);
      core.setStatus("Download gestartet.", "ok");

      return result;
    } catch (error) {
      throw error;
    }
  }

  async function fetchJson(action, payload) {
    try {
      var normalizedAction = normalizeAction(action);
      var fallbackPath = "/" + normalizedAction;

      if (normalizedAction === "package-plan") {
        fallbackPath = "/package-plan";
      }

      var url = resolveActionRouteUrl(normalizedAction, fallbackPath);

      var response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
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
        return payloadRuntime.collectPayload(form || resolveForm(), options || {});
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
          if (value instanceof File) {
            if (value.name) {
              payload[key] = {
                name: value.name,
                size: value.size,
                type: value.type || ""
              };
            }

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
        } catch (entryError) {
          safeWarn("Fallback payload entry skipped: " + key, entryError);
        }
      });

      if (!payload.domain) {
        payload.domain = core.getFieldValue(safeForm, "domain") || "hochbau";
      }

      if (!payload.category) {
        payload.category = core.getFieldValue(safeForm, "category") || "bloecke";
      }

      if (!payload.subcategory) {
        payload.subcategory = core.getFieldValue(safeForm, "subcategory") || "basis";
      }

      if (!payload.object_kind) {
        payload.object_kind = core.getFieldValue(safeForm, "object_kind") || "cell_block";
      }

      if (!payload.definition_variants_json) {
        payload.definition_variants_json = "[]";
      }

      if (!payload.default_variant_id) {
        payload.default_variant_id = "default";
      }

      return payload;
    } catch (error) {
      safeError("Fallback payload collection failed.", error);
      return {};
    }
  }

  function setBusy(form, busy, sourceButton) {
    try {
      var safeForm = form || resolveForm();
      var isBusy = !!busy;

      localState.pending = isBusy;
      core.setPending(isBusy);

      if (safeForm) {
        safeForm.setAttribute("data-create-form-state", isBusy ? "loading" : "idle");
        safeForm.classList.toggle(classes.loading, isBusy);
        safeForm.setAttribute("aria-busy", isBusy ? "true" : "false");
      }

      var actionButtons = core.qsa(selectors.actionButton);

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

          button.classList.toggle(classes.running, isBusy && button === sourceButton);
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
      var saveButton = core.qs("[data-create-action='save']");

      if (saveButton && !core.isWriteEnabled()) {
        saveButton.disabled = true;
        saveButton.setAttribute("aria-disabled", "true");
        saveButton.setAttribute("title", "Speichern ist deaktiviert. Backend-Schreibmodus erforderlich.");
      } else if (saveButton && core.isWriteEnabled()) {
        saveButton.removeAttribute("title");

        if (saveButton.getAttribute("data-create-static-disabled") !== "true") {
          saveButton.disabled = false;
          saveButton.setAttribute("aria-disabled", "false");
        }
      }

      var fixedButtons = core.qsa("button[data-create-static-disabled='true']", scope);

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
      var output = core.qs(selectors.resultOutput);
      var code = output ? core.qs(selectors.resultCode, output) : core.qs(selectors.resultCode);
      var text = core.stringifyJson(value);
      var reveal = !options || options.reveal !== false;

      if (!output) {
        return;
      }

      if (code) {
        code.textContent = text;
      } else {
        output.textContent = text;
      }

      if (reveal) {
        output.hidden = false;
        localState.resultVisible = true;
      }

      updateResultSummary(value, reveal);
      setResultToolsEnabled(true);
    } catch (error) {
      safeWarn("Print output failed.", error);
    }
  }

  function updateResultSummary(value, reveal) {
    try {
      var summary = core.qs(selectors.resultSummary);

      if (!summary) {
        return;
      }

      var ok = value && value.ok;
      var status = value && value.status ? value.status : "ready";
      var route = value && (value.route || value.action) ? value.route || value.action : "";
      var httpStatus = value && typeof value._http_status !== "undefined" ? value._http_status : "—";

      summary.textContent = (ok ? "OK" : "Hinweis") + " · " + status + (route ? " · " + route : "") + " · HTTP " + httpStatus;
      summary.hidden = !reveal;
    } catch (error) {
      safeWarn("Result summary update failed.", error);
    }
  }

  function clearResult(options) {
    try {
      var output = core.qs(selectors.resultOutput);
      var code = output ? core.qs(selectors.resultCode, output) : core.qs(selectors.resultCode);
      var summary = core.qs(selectors.resultSummary);
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
        core.setStatus("Ergebnis geleert.", "ok");
      }
    } catch (error) {
      safeWarn("Clear result failed.", error);
    }
  }

  function setResultToolsEnabled(enabled) {
    try {
      var copyButton = core.qs(selectors.resultCopy);
      var clearButton = core.qs(selectors.resultClear);

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
      var output = core.qs(selectors.resultOutput);
      var code = output ? core.qs(selectors.resultCode, output) : core.qs(selectors.resultCode);
      var text = code ? code.textContent || "" : output ? output.textContent || "" : "";

      core.copyText(text).then(function () {
        flashButton(button, classes.copied, "Kopiert");
        core.setStatus("Ergebnis kopiert.", "ok");
      }).catch(function (error) {
        safeWarn("Copy result clipboard failed.", error);
        core.setStatus("Kopieren nicht möglich.", "warning");
      });
    } catch (error) {
      safeWarn("Copy result failed.", error);
      core.setStatus("Kopieren nicht möglich.", "warning");
    }
  }

  function updateResultFromPayload(action, payload) {
    try {
      var errors = core.normalizeIssues(payload && payload.errors);
      var warnings = core.normalizeIssues(payload && payload.warnings);

      updateResultMeta({
        action: action ? core.actionLabel(action) : "Keine",
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
      core.setText(selectors.resultLastAction, meta.action || "Keine");
      core.setText(selectors.resultStatus, meta.status || "—");
      core.setText(selectors.resultHttpStatus, String(typeof meta.httpStatus !== "undefined" ? meta.httpStatus : "—"));
      core.setText(selectors.resultErrorCount, String(typeof meta.errors === "number" ? meta.errors : 0));
      core.setText(selectors.resultWarningCount, String(typeof meta.warnings === "number" ? meta.warnings : 0));
    } catch (error) {
      safeWarn("Update result meta failed.", error);
    }
  }

  function applyResultToUi(result) {
    try {
      clearFieldIssues(document);

      var errors = core.normalizeIssues(result && result.errors);
      var warnings = core.normalizeIssues(result && result.warnings);
      var info = core.normalizeIssues(result && result.info);

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

      core.qsa("." + classes.invalid, scope).forEach(function (field) {
        field.classList.remove(classes.invalid);
        field.removeAttribute("aria-invalid");
      });

      core.qsa("." + classes.valid, scope).forEach(function (field) {
        field.classList.remove(classes.valid);
      });

      core.qsa("[data-create-field-message='true']", scope).forEach(function (node) {
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

      var normalized = core.normalizeIssueFieldName(fieldName);
      var field = null;

      if (normalized === "save") {
        field = core.qs("[data-create-action='save']");
      }

      if (!field) {
        var candidates = [
          "[name='" + core.cssEscape(normalized) + "']",
          "[data-create-field='" + core.cssEscape(normalized) + "']"
        ];

        for (var i = 0; i < candidates.length; i += 1) {
          field = core.qs(candidates[i]);

          if (field) {
            break;
          }
        }
      }

      if (!field && normalized.indexOf(".") !== -1) {
        var lastPart = normalized.split(".").pop();

        field = core.qs("[name='" + core.cssEscape(lastPart) + "'], [data-create-field='" + core.cssEscape(lastPart) + "']");
      }

      if (!field) {
        return;
      }

      if (level === "error") {
        field.classList.add(classes.invalid);
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
      var requiredFields = core.qsa("[data-create-required='true'], input[required], select[required], textarea[required]");

      requiredFields.forEach(function (field) {
        try {
          if (field && field.value) {
            field.classList.add(classes.valid);
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

      core.state.lastResult = payload;
      core.state.lastAction = action;
      core.state.lastError = error;

      printOutput(payload, { reveal: true });
      updateResultFromPayload(action, payload);
      core.setStatus(core.actionLabel(action) + " fehlgeschlagen.", "error");

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
      core.setStatus(message || "Aktion blockiert.", "warning");

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
        label: core.actionLabel(action)
      }, extraDetail || {});

      core.dispatch(eventName, detail);
    } catch (error) {
      safeWarn("Action event dispatch failed: " + eventName, error);
    }
  }

  function resolveActionRouteUrl(action, fallbackPath) {
    try {
      var normalizedAction = action === "package_plan" ? "package-plan" : action;
      var routeKey = normalizedAction === "package-plan" ? "package_plan" : normalizedAction;

      return core.resolveRouteUrl(routeKey, fallbackPath || "/" + normalizedAction);
    } catch (error) {
      safeWarn("Resolve action route URL failed.", error);
      return core.state.apiPrefix + (fallbackPath || "");
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
      var name = payload && (payload.family_name || payload.family_slug) ? payload.family_name || payload.family_slug : "package";
      var filename = core.slugify(name) || "package";

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

  function flashButton(button, className, temporaryText) {
    try {
      if (!button) {
        return;
      }

      var oldText = button.textContent;

      button.classList.add(className);

      if (temporaryText) {
        button.textContent = temporaryText;
      }

      window.setTimeout(function () {
        try {
          button.classList.remove(className);

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

      if (text === "package-plan" && KNOWN_ACTIONS[text]) {
        return text;
      }

      if (KNOWN_ACTIONS[text]) {
        return text;
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
        variants = core.safeJsonParse(payload.definition_variants_json, []);
      }

      return {
        family_name: payload && payload.family_name ? payload.family_name : "",
        domain: payload && payload.domain ? payload.domain : "",
        category: payload && payload.category ? payload.category : "",
        subcategory: payload && payload.subcategory ? payload.subcategory : "",
        object_kind: payload && payload.object_kind ? payload.object_kind : "",
        definition_variant_count: Array.isArray(variants) ? variants.length : 0,
        default_variant_id: payload && payload.default_variant_id ? payload.default_variant_id : "",
        timestamp: timestamp()
      };
    } catch (error) {
      return {
        summary_error: String(error && error.message ? error.message : error)
      };
    }
  }

  function resolveForm(form) {
    try {
      if (form && form.nodeType === 1) {
        return form;
      }

      return core && typeof core.qs === "function" ? core.qs(selectors.form) : document.querySelector("[data-vp-create-form], [data-create-form='true'], #vp-create-form");
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
        lastResult: core && typeof core.clone === "function" ? core.clone(localState.lastResult) : localState.lastResult,
        lastError: localState.lastError,
        lastHttpStatus: localState.lastHttpStatus,
        lastPayloadSummary: localState.lastPayloadSummary,
        actionCount: localState.actionCount,
        downloadCount: localState.downloadCount,
        saveConfirmCount: localState.saveConfirmCount,
        resultVisible: localState.resultVisible,
        writeEnabled: core ? core.isWriteEnabled() : false
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
        core = window[CORE_NAME];
      }

      if (!core) {
        throw new Error("VectoplanCreateCore is not available.");
      }

      if (!selectors) {
        selectors = core.selectors || {};
      }

      if (!classes) {
        classes = core.classes || {};
      }

      if (!payloadRuntime) {
        payloadRuntime = window[PAYLOAD_NAME] || null;
      }

      return core;
    } catch (error) {
      throw error;
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      boot(0);
    }, { once: true });
  } else {
    boot(0);
  }
})();