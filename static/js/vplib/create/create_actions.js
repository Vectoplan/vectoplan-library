/* services/vectoplan-library/static/js/vplib/create/create_actions.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateActions";
  var MODULE_NAME = "actions";
  var ACTIONS_VERSION = "0.9.0";
  var CORE_NAME = "VectoplanCreateCore";
  var PAYLOAD_NAME = "VectoplanCreatePayload";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 80;
  var ACTION_LOCK = "create-actions-run";
  var ACTION_LOCK_MS = 120000;
  var DEFAULT_REQUEST_TIMEOUT_MS = 60000;
  var DEFAULT_PREFLIGHT_TIMEOUT_MS = 45000;
  var DEFAULT_DOWNLOAD_TIMEOUT_MS = 120000;
  var DEFAULT_MIN_ARCHIVE_BYTES = 64;
  var DOWNLOAD_URL_REVOKE_DELAY_MS = 60000;
  var MUTATION_REBIND_DELAY_MS = 40;
  var MAX_BINDING_ERROR_HISTORY = 16;
  var BINDING_REGISTRY_NAME = "__VECTOPLAN_CREATE_ACTIONS_BINDINGS__";
  var EVENT_HANDLED_KEY = "__vpCreateActionsHandled";
  var DIRECT_HANDLER_KEY = "__vpCreateActionsDirectHandler";
  var DIRECT_BOUND_ATTR = "data-vp-create-actions-direct-bound";
  var DIRECT_BOUND_VERSION_ATTR = "data-vp-create-actions-direct-bound-version";
  var BINDING_VERIFY_DELAYS = [0, 120, 600, 1600];
  var VPLIB_ARCHIVE_MIME_TYPES = {
    "application/zip": true,
    "application/x-zip-compressed": true,
    "application/octet-stream": true,
    "application/vnd.vectoplan.vplib": true,
    "application/vnd.vectoplan-library": true
  };
  var CRITICAL_ACTIONS = {
    validate: true,
    "package-plan": true,
    download: true,
    save: true,
    "publish-prepare": true
  };

  var KNOWN_ACTIONS = {
    draft: true,
    validate: true,
    "package-plan": true,
    package_plan: true,
    download: true,
    save: true,
    "persist-draft": true,
    persist_draft: true,
    "persistent-draft": true,
    persistent_draft: true,
    "publish-prepare": true,
    publish_prepare: true,
    "publish-bundle": true,
    publish_bundle: true
  };

  var ACTION_PATHS = {
    draft: "/draft",
    validate: "/validate",
    "package-plan": "/package-plan",
    download: "/download",
    save: "/save",
    "persist-draft": "/drafts",
    "publish-prepare": "/publish-bundle"
  };

  var ACTION_LABELS = {
    draft: "Draft bauen",
    validate: "Validieren",
    "package-plan": "Package-Plan",
    download: "VPLIB downloaden",
    save: "In Library speichern",
    "persist-draft": "Draft speichern",
    "publish-prepare": "Publish vorbereiten"
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
  var actionClickHandler = null;
  var resultClickHandler = null;
  var mutationObserver = null;
  var mutationRebindTimer = null;
  var bindingVerifyTimers = [];
  var runtimeToken = [
    GLOBAL_NAME,
    ACTIONS_VERSION,
    Date.now(),
    Math.random().toString(36).slice(2)
  ].join(":");

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
    persistDraftCount: 0,
    publishPrepareCount: 0,
    resultVisible: false,
    lastRoute: "",
    lastRequestAt: "",
    lastResponseAt: "",
    lastUploadFileCount: 0,
    lastUploadErrorCount: 0,
    operational: false,
    status: "created",
    readinessPromise: null,
    readinessResult: null,
    activeActionPromise: null,
    activeActionKey: "",
    actionGeneration: 0,
    requestSequence: 0,
    lastRequestId: "",
    lastPreflight: null,
    lastDownloadValidation: null,
    suppressedActionCount: 0,
    abortController: null,
    bindingAttempts: 0,
    bindingSuccessCount: 0,
    bindingRepairCount: 0,
    delegatedActionListenerBound: false,
    delegatedResultListenerBound: false,
    mutationObserverActive: false,
    directButtonCount: 0,
    actionButtonCount: 0,
    clickCount: 0,
    delegatedClickCount: 0,
    directClickCount: 0,
    suppressedDuplicateClickCount: 0,
    blockedClickCount: 0,
    lastClick: null,
    lastBindingVerification: null,
    bindingErrors: [],
    downloadTriggerCount: 0,
    lastDownloadTrigger: null,
    objectUrlCleanupCount: 0
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
        repairControlBindings({
          source: "initialize_existing",
          quiet: true
        });

        if (!localState.operational && !localState.readinessPromise) {
          ensureActionsReady({
            source: "initialize_existing",
            rejectOnError: false
          }).catch(function (readinessError) {
            safeWarn("Existing actions readiness check failed.", readinessError);
          });
        }

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

      bindControls({
        source: "initialize",
        force: true
      });
      clearResult({ silent: true });

      initialized = true;
      localState.initialized = true;
      setActionsStatus("initialized", null, {
        source: "initialize"
      });

      if (typeof core.registerModule === "function") {
        core.registerModule(MODULE_NAME, api);
      }

      safeSetAttribute(document.documentElement, "data-vp-create-actions-initialized", "true");
      safeSetAttribute(document.documentElement, "data-vp-create-actions-ready", "false");
      safeSetAttribute(document.documentElement, "data-vp-create-actions-version", ACTIONS_VERSION);

      enforceStaticDisabledButtons();
      safeDispatch("vectoplan:create:actions-initialized", getState());

      ensureActionsReady({
        source: "initialize",
        rejectOnError: false
      }).catch(function (readinessError) {
        safeWarn("Initial actions readiness check failed.", readinessError);
      });

      return api;
    } catch (error) {
      initialized = false;
      localState.initialized = false;
      localState.operational = false;
      localState.lastError = normalizeError(error);
      setActionsStatus("unavailable", error, {
        source: "initialize"
      });
      safeError("Actions initialization failed.", error);
      return api;
    }
  }

  function getBindingRegistry() {
    try {
      var registry = window[BINDING_REGISTRY_NAME];

      if (!registry || typeof registry !== "object") {
        registry = {
          version: ACTIONS_VERSION,
          ownerToken: runtimeToken,
          events: {},
          observer: null,
          createdAt: timestamp()
        };
        window[BINDING_REGISTRY_NAME] = registry;
      }

      if (!registry.events || typeof registry.events !== "object") {
        registry.events = {};
      }

      return registry;
    } catch (error) {
      return {
        version: ACTIONS_VERSION,
        ownerToken: runtimeToken,
        events: {},
        observer: null,
        ephemeral: true
      };
    }
  }

  function rememberBindingError(stage, error) {
    try {
      localState.bindingErrors.push({
        stage: String(stage || "binding"),
        error: normalizeError(error),
        timestamp: timestamp()
      });

      if (localState.bindingErrors.length > MAX_BINDING_ERROR_HISTORY) {
        localState.bindingErrors.splice(
          0,
          localState.bindingErrors.length - MAX_BINDING_ERROR_HISTORY
        );
      }
    } catch (historyError) {
      /* Binding diagnostics must never break the UI. */
    }
  }

  function bindManagedEvent(slot, target, eventName, handler, capture) {
    try {
      if (!slot || !target || typeof target.addEventListener !== "function" || typeof handler !== "function") {
        return false;
      }

      var registry = getBindingRegistry();
      var existing = registry.events[slot];

      if (
        existing &&
        existing.target &&
        typeof existing.target.removeEventListener === "function" &&
        typeof existing.handler === "function"
      ) {
        try {
          existing.target.removeEventListener(
            existing.eventName,
            existing.handler,
            !!existing.capture
          );
        } catch (removeError) {
          rememberBindingError(slot + ":remove_previous", removeError);
        }
      }

      target.addEventListener(eventName, handler, !!capture);
      registry.events[slot] = {
        target: target,
        eventName: eventName,
        handler: handler,
        capture: !!capture,
        ownerToken: runtimeToken,
        version: ACTIONS_VERSION,
        boundAt: timestamp()
      };
      registry.version = ACTIONS_VERSION;
      registry.ownerToken = runtimeToken;

      return true;
    } catch (error) {
      rememberBindingError(slot, error);
      safeError("Managed event binding failed: " + slot, error);
      return false;
    }
  }

  function bindControls(options) {
    var config = options || {};

    try {
      localState.bindingAttempts += 1;

      var actionBound = bindActionButtons({
        source: config.source || "bind_controls",
        force: config.force === true
      });
      var resultBound = bindResultControls();
      var writeBound = bindWriteStateUpdates();
      var payloadBound = bindPayloadRuntimeUpdates();
      var readinessBound = bindReadinessUpdates();
      var observerBound = bindActionButtonObserver();
      var directCount = bindDirectActionButtons(document, {
        source: config.source || "bind_controls"
      });

      bindingDone = actionBound === true && resultBound === true;
      localState.bindingDone = bindingDone;
      localState.delegatedActionListenerBound = actionBound === true;
      localState.delegatedResultListenerBound = resultBound === true;
      localState.mutationObserverActive = observerBound === true;
      localState.directButtonCount = directCount;
      localState.actionButtonCount = qsa(selectorFor("actionButton")).length;

      if (bindingDone) {
        localState.bindingSuccessCount += 1;
      }

      safeSetAttribute(
        document.documentElement,
        "data-vp-create-actions-binding-ready",
        bindingDone ? "true" : "false"
      );
      safeSetAttribute(
        document.documentElement,
        "data-vp-create-actions-binding-version",
        ACTIONS_VERSION
      );

      scheduleBindingVerification(config.source || "bind_controls");

      return {
        ok: bindingDone,
        ready: bindingDone,
        status: bindingDone ? "bound" : "binding_failed",
        actionDelegated: actionBound,
        resultDelegated: resultBound,
        writeUpdates: writeBound,
        payloadUpdates: payloadBound,
        readinessUpdates: readinessBound,
        mutationObserver: observerBound,
        directButtonCount: directCount,
        actionButtonCount: localState.actionButtonCount,
        version: ACTIONS_VERSION,
        runtimeToken: runtimeToken
      };
    } catch (error) {
      bindingDone = false;
      localState.bindingDone = false;
      rememberBindingError("bind_controls", error);
      safeError("Actions control binding failed.", error);
      return {
        ok: false,
        ready: false,
        status: "binding_failed",
        error: normalizeError(error)
      };
    }
  }

  function bindActionButtons() {
    try {
      if (!actionClickHandler) {
        actionClickHandler = function (event) {
          handleActionButtonClick(event, "delegated");
        };
      }

      var bound = bindManagedEvent(
        "actions:document-click",
        document,
        "click",
        actionClickHandler,
        true
      );

      localState.delegatedActionListenerBound = bound;
      return bound;
    } catch (error) {
      rememberBindingError("bind_action_buttons", error);
      safeError("Action button binding failed.", error);
      return false;
    }
  }

  function handleActionButtonClick(event, source) {
    try {
      var target = event && event.target ? event.target : null;
      var button = target && target.closest
        ? target.closest(selectorFor("actionButton"))
        : null;

      if (!button) {
        return false;
      }

      var handledBy = event ? event[EVENT_HANDLED_KEY] : null;

      if (handledBy) {
        localState.suppressedDuplicateClickCount += 1;
        return false;
      }

      try {
        event[EVENT_HANDLED_KEY] = runtimeToken;
      } catch (markerError) {
        /* Event marker is an optimization; direct/delegated dedupe remains best effort. */
      }

      var form = resolveForm();

      if (form && !form.contains(button)) {
        return false;
      }

      if (event && typeof event.preventDefault === "function") {
        event.preventDefault();
      }

      if (event && typeof event.stopPropagation === "function") {
        event.stopPropagation();
      }

      var action = normalizeAction(button.getAttribute("data-create-action") || "");
      var clickSource = source || "unknown";

      localState.clickCount += 1;
      if (clickSource === "delegated") {
        localState.delegatedClickCount += 1;
      } else {
        localState.directClickCount += 1;
      }

      localState.lastClick = {
        action: action,
        source: clickSource,
        timestamp: timestamp(),
        disabled: !!button.disabled,
        ariaDisabled: button.getAttribute("aria-disabled") || "",
        buttonId: button.id || ""
      };

      if (!action) {
        localState.blockedClickCount += 1;
        safeWarn("Action button without known action ignored.");
        return false;
      }

      if (button.disabled || button.getAttribute("aria-disabled") === "true") {
        localState.blockedClickCount += 1;
        buildBlockedResult(
          action,
          "action_button_disabled",
          "Die Aktion ist derzeit deaktiviert."
        );
        return true;
      }

      if (localState.pending || isCorePending()) {
        localState.blockedClickCount += 1;
        buildBlockedResult(
          action,
          "action_pending",
          "Es läuft bereits eine Aktion."
        );
        return true;
      }

      Promise.resolve(runAction(action, form, button)).catch(function (actionError) {
        handleRuntimeError(action, actionError);
      });

      return true;
    } catch (clickError) {
      rememberBindingError("handle_action_click", clickError);
      safeWarn("Action click handling failed.", clickError);
      return false;
    }
  }

  function bindDirectActionButtons(root, options) {
    try {
      var config = options || {};
      var scope = root && root.querySelectorAll ? root : document;
      var buttons = qsa(selectorFor("actionButton"), scope);
      var currentCount = 0;

      if (
        scope &&
        scope.nodeType === 1 &&
        scope.matches &&
        scope.matches(selectorFor("actionButton"))
      ) {
        buttons.unshift(scope);
      }

      buttons.forEach(function (button) {
        try {
          if (!button || typeof button.addEventListener !== "function") {
            return;
          }

          var existingHandler = button[DIRECT_HANDLER_KEY];

          if (existingHandler && existingHandler.__vpOwnerToken === runtimeToken) {
            currentCount += 1;
            return;
          }

          if (existingHandler && typeof button.removeEventListener === "function") {
            try {
              button.removeEventListener("click", existingHandler, false);
            } catch (removeError) {
              rememberBindingError("direct_button_remove", removeError);
            }
          }

          var directHandler = function (event) {
            handleActionButtonClick(event, "direct");
          };
          directHandler.__vpOwnerToken = runtimeToken;
          directHandler.__vpSource = config.source || "direct_button";

          button.addEventListener("click", directHandler, false);
          button[DIRECT_HANDLER_KEY] = directHandler;
          button.setAttribute(DIRECT_BOUND_ATTR, "true");
          button.setAttribute(DIRECT_BOUND_VERSION_ATTR, ACTIONS_VERSION);
          currentCount += 1;
        } catch (buttonError) {
          rememberBindingError("direct_button_bind", buttonError);
        }
      });

      localState.directButtonCount = currentCount;
      localState.actionButtonCount = qsa(selectorFor("actionButton")).length;
      return currentCount;
    } catch (error) {
      rememberBindingError("bind_direct_buttons", error);
      safeWarn("Direct action-button binding failed.", error);
      return 0;
    }
  }

  function scheduleDirectButtonRefresh(reason) {
    try {
      if (mutationRebindTimer !== null) {
        window.clearTimeout(mutationRebindTimer);
      }

      mutationRebindTimer = window.setTimeout(function () {
        mutationRebindTimer = null;

        try {
          bindDirectActionButtons(document, {
            source: reason || "mutation"
          });
          enforceStaticDisabledButtons();
          verifyControlBindings({
            source: reason || "mutation",
            repair: false
          });
        } catch (error) {
          rememberBindingError("mutation_refresh", error);
        }
      }, MUTATION_REBIND_DELAY_MS);

      return true;
    } catch (error) {
      rememberBindingError("schedule_button_refresh", error);
      return false;
    }
  }

  function bindActionButtonObserver() {
    try {
      var Observer = window.MutationObserver || window.WebKitMutationObserver;

      if (typeof Observer !== "function" || !document.documentElement) {
        localState.mutationObserverActive = false;
        return false;
      }

      var registry = getBindingRegistry();

      if (registry.observer && registry.observer.observer) {
        try {
          registry.observer.observer.disconnect();
        } catch (disconnectError) {
          rememberBindingError("observer_disconnect", disconnectError);
        }
      }

      mutationObserver = new Observer(function (mutations) {
        try {
          var relevant = false;

          toArray(mutations).forEach(function (mutation) {
            if (mutation && mutation.type === "childList" && mutation.addedNodes && mutation.addedNodes.length) {
              relevant = true;
            }
          });

          if (relevant) {
            scheduleDirectButtonRefresh("dom_mutation");
          }
        } catch (observerError) {
          rememberBindingError("observer_callback", observerError);
        }
      });

      mutationObserver.observe(document.documentElement, {
        childList: true,
        subtree: true
      });

      registry.observer = {
        observer: mutationObserver,
        ownerToken: runtimeToken,
        version: ACTIONS_VERSION,
        boundAt: timestamp()
      };
      localState.mutationObserverActive = true;
      return true;
    } catch (error) {
      mutationObserver = null;
      localState.mutationObserverActive = false;
      rememberBindingError("bind_mutation_observer", error);
      return false;
    }
  }

  function bindResultControls() {
    try {
      if (!resultClickHandler) {
        resultClickHandler = function (event) {
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
            rememberBindingError("result_click", clickError);
            safeWarn("Result control click handling failed.", clickError);
          }
        };
      }

      var bound = bindManagedEvent(
        "actions:result-document-click",
        document,
        "click",
        resultClickHandler,
        true
      );
      localState.delegatedResultListenerBound = bound;
      return bound;
    } catch (error) {
      rememberBindingError("bind_result_controls", error);
      safeError("Result controls binding failed.", error);
      return false;
    }
  }

  function bindWriteStateUpdates() {
    try {
      var coreRefreshBound = bindManagedEvent(
        "actions:core-context-refreshed",
        document,
        "vectoplan:create:core-context-refreshed",
        function () {
          try {
            enforceStaticDisabledButtons();
            bindDirectActionButtons(document, { source: "core_context_refreshed" });
          } catch (error) {
            safeWarn("Write state refresh handling failed.", error);
          }
        },
        false
      );

      var contextReadyBound = bindManagedEvent(
        "actions:context-ready",
        document,
        "vectoplan:create:context-ready",
        function () {
          try {
            enforceStaticDisabledButtons();
            bindDirectActionButtons(document, { source: "context_ready" });
          } catch (error) {
            safeWarn("Context ready write-state handling failed.", error);
          }
        },
        false
      );

      return coreRefreshBound && contextReadyBound;
    } catch (error) {
      rememberBindingError("bind_write_state", error);
      safeWarn("Write state update binding failed.", error);
      return false;
    }
  }

  function bindPayloadRuntimeUpdates() {
    try {
      var payloadReadyBound = bindManagedEvent(
        "actions:payload-ready",
        document,
        "vectoplan:create:payload-ready",
        function () {
          try {
            payloadRuntime = window[PAYLOAD_NAME] || payloadRuntime;
          } catch (error) {
            safeWarn("Payload ready binding failed.", error);
          }
        },
        false
      );

      var payloadCollectedBound = bindManagedEvent(
        "actions:payload-collected",
        document,
        "vectoplan:create:payload-collected",
        function (event) {
          try {
            var detail = event && event.detail ? event.detail : {};

            if (detail.summary) {
              localState.lastPayloadSummary = clone(detail.summary);
              updateUploadCountsFromSummary(detail.summary);
            }
          } catch (error) {
            safeWarn("Payload collected handling failed.", error);
          }
        },
        false
      );

      var uploadsSyncedBound = bindManagedEvent(
        "actions:payload-uploads-synced",
        document,
        "vectoplan:create:payload-uploads-synced",
        function (event) {
          try {
            var detail = event && event.detail ? event.detail : {};

            if (detail.summary) {
              localState.lastUploadFileCount = parseInt(detail.summary.fileCount || detail.summary.file_count || 0, 10) || 0;
              localState.lastUploadErrorCount = parseInt(detail.summary.errorCount || detail.summary.error_count || 0, 10) || 0;
            }
          } catch (error) {
            safeWarn("Payload uploads synced handling failed.", error);
          }
        },
        false
      );

      return payloadReadyBound && payloadCollectedBound && uploadsSyncedBound;
    } catch (error) {
      rememberBindingError("bind_payload_updates", error);
      safeWarn("Payload runtime update binding failed.", error);
      return false;
    }
  }

  function bindReadinessUpdates() {
    try {
      var results = [];

      [
        "vectoplan:create:core-ready",
        "vectoplan:create:core-operational",
        "vectoplan:create:payload-ready"
      ].forEach(function (eventName) {
        results.push(bindManagedEvent(
          "actions:readiness:" + eventName,
          document,
          eventName,
          function () {
            ensureActionsReady({
              source: eventName,
              rejectOnError: false
            }).catch(function (error) {
              safeWarn("Actions readiness refresh failed: " + eventName, error);
            });
          },
          false
        ));
      });

      [
        "vectoplan:create:core-blocked",
        "vectoplan:create:payload-blocked"
      ].forEach(function (eventName) {
        results.push(bindManagedEvent(
          "actions:blocked:" + eventName,
          document,
          eventName,
          function (event) {
            var detail = event && event.detail ? event.detail : {};
            setActionsStatus("blocked", detail.error || detail, detail);
          },
          false
        ));
      });

      return results.every(function (value) {
        return value === true;
      });
    } catch (error) {
      rememberBindingError("bind_readiness_updates", error);
      safeWarn("Actions readiness event binding failed.", error);
      return false;
    }
  }

  function getBindingSnapshot() {
    try {
      var buttons = qsa(selectorFor("actionButton"));
      var directCount = buttons.filter(function (button) {
        try {
          return !!(
            button &&
            button[DIRECT_HANDLER_KEY] &&
            button[DIRECT_HANDLER_KEY].__vpOwnerToken === runtimeToken
          );
        } catch (error) {
          return false;
        }
      }).length;
      var registry = getBindingRegistry();
      var eventRecords = registry.events || {};

      return {
        ok: localState.delegatedActionListenerBound === true || directCount > 0,
        ready: bindingDone,
        bindingDone: bindingDone,
        version: ACTIONS_VERSION,
        runtimeToken: runtimeToken,
        actionButtonCount: buttons.length,
        directButtonCount: directCount,
        delegatedActionListenerBound: localState.delegatedActionListenerBound,
        delegatedResultListenerBound: localState.delegatedResultListenerBound,
        mutationObserverActive: localState.mutationObserverActive,
        managedEventSlots: Object.keys(eventRecords),
        bindingAttempts: localState.bindingAttempts,
        bindingSuccessCount: localState.bindingSuccessCount,
        bindingRepairCount: localState.bindingRepairCount,
        clickCount: localState.clickCount,
        delegatedClickCount: localState.delegatedClickCount,
        directClickCount: localState.directClickCount,
        suppressedDuplicateClickCount: localState.suppressedDuplicateClickCount,
        lastClick: clone(localState.lastClick),
        errors: clone(localState.bindingErrors)
      };
    } catch (error) {
      return {
        ok: false,
        ready: false,
        bindingDone: false,
        version: ACTIONS_VERSION,
        error: normalizeError(error)
      };
    }
  }

  function verifyControlBindings(options) {
    var config = options || {};

    try {
      var snapshot = getBindingSnapshot();
      var needsRepair = snapshot.delegatedActionListenerBound !== true ||
        snapshot.delegatedResultListenerBound !== true ||
        (snapshot.actionButtonCount > 0 && snapshot.directButtonCount < snapshot.actionButtonCount);

      if (needsRepair && config.repair !== false) {
        localState.bindingRepairCount += 1;
        bindControls({
          source: config.source || "binding_verification",
          force: true,
          quiet: true
        });
        snapshot = getBindingSnapshot();
      }

      snapshot.verifiedAt = timestamp();
      snapshot.source = config.source || "verify";
      snapshot.repaired = needsRepair && config.repair !== false;
      localState.lastBindingVerification = clone(snapshot);
      bindingDone = snapshot.delegatedActionListenerBound === true &&
        snapshot.delegatedResultListenerBound === true;
      localState.bindingDone = bindingDone;

      return snapshot;
    } catch (error) {
      rememberBindingError("verify_bindings", error);
      return {
        ok: false,
        ready: false,
        status: "verification_failed",
        error: normalizeError(error)
      };
    }
  }

  function scheduleBindingVerification(reason) {
    try {
      bindingVerifyTimers.forEach(function (timerId) {
        try {
          window.clearTimeout(timerId);
        } catch (error) {
          /* no-op */
        }
      });
      bindingVerifyTimers = [];

      BINDING_VERIFY_DELAYS.forEach(function (delay) {
        var timerId = window.setTimeout(function () {
          verifyControlBindings({
            source: (reason || "scheduled") + ":" + String(delay),
            repair: true
          });
        }, delay);
        bindingVerifyTimers.push(timerId);
      });

      return true;
    } catch (error) {
      rememberBindingError("schedule_binding_verification", error);
      return false;
    }
  }

  function repairControlBindings(options) {
    try {
      localState.bindingRepairCount += 1;
      return bindControls(Object.assign({}, options || {}, {
        force: true,
        source: options && options.source ? options.source : "manual_repair"
      }));
    } catch (error) {
      rememberBindingError("repair_bindings", error);
      return {
        ok: false,
        ready: false,
        status: "repair_failed",
        error: normalizeError(error)
      };
    }
  }

  function createActionsError(code, message, details, cause) {
    var actionError;

    try {
      actionError = new Error(String(message || code || "Create action failed."));
    } catch (constructionError) {
      actionError = {
        name: "Error",
        message: String(message || code || "Create action failed.")
      };
    }

    try {
      actionError.name = "VectoplanCreateActionsError";
      actionError.code = String(code || "create_actions_error");
      actionError.component = GLOBAL_NAME;
      actionError.componentVersion = ACTIONS_VERSION;
      actionError.__vp_create_actions_error = true;

      if (details && typeof details === "object") {
        actionError.details = clone(details);
        actionError.status = details.status || null;
        actionError.action = details.action || null;
        actionError.url = details.url || null;
        actionError.requestId = details.requestId || null;
        actionError.payload = details.payload || null;
      }

      if (cause !== undefined && cause !== null) {
        actionError.cause = cause;
      }
    } catch (enrichmentError) {
      /* Preserve the Error instance. */
    }

    return actionError;
  }

  function ensureActionsError(error, fallbackCode, fallbackMessage, details) {
    try {
      if (error && error.__vp_create_actions_error === true && error.message) {
        return error;
      }

      if (error instanceof Error) {
        error.code = error.code || fallbackCode || error.name || "create_actions_error";
        error.component = error.component || GLOBAL_NAME;
        error.__vp_create_actions_error = true;

        if (details && !error.details) {
          error.details = clone(details);
        }

        return error;
      }

      var source = error && error.error && typeof error.error === "object"
        ? error.error
        : (error || {});

      return createActionsError(
        source.code || source.error_code || source.status || fallbackCode || "create_actions_error",
        source.message || source.detail || source.description || fallbackMessage || (typeof error === "string" ? error : "") || "Create action failed.",
        Object.assign({}, details || {}, {
          status: source.status || null,
          url: source.url || null,
          requestId: source.requestId || source.request_id || null,
          payload: source.payload || source.raw || source.response || null
        }),
        error
      );
    } catch (normalizationError) {
      return createActionsError(
        fallbackCode || "create_actions_error",
        fallbackMessage || "Create action failed.",
        details || {},
        error
      );
    }
  }

  function setActionsStatus(status, error, details) {
    try {
      var nextStatus = String(status || "created").trim().toLowerCase() || "created";
      var ready = nextStatus === "ready";

      localState.status = nextStatus;
      localState.operational = ready;
      localState.lastError = error ? normalizeError(error) : null;

      safeSetAttribute(document.documentElement, "data-vp-create-actions-initialized", initialized ? "true" : "false");
      safeSetAttribute(document.documentElement, "data-vp-create-actions-ready", ready ? "true" : "false");
      safeSetAttribute(document.documentElement, "data-vp-create-actions-operational", ready ? "true" : "false");
      safeSetAttribute(document.documentElement, "data-vp-create-actions-status", nextStatus);
      safeSetAttribute(document.documentElement, "data-vp-create-actions-version", ACTIONS_VERSION);

      enforceStaticDisabledButtons();

      safeDispatch("vectoplan:create:actions-status-changed", {
        component: GLOBAL_NAME,
        version: ACTIONS_VERSION,
        initialized: initialized,
        ready: ready,
        operational: ready,
        status: nextStatus,
        error: localState.lastError,
        details: details || null
      });

      return nextStatus;
    } catch (statusError) {
      localState.status = String(status || "created");
      localState.operational = localState.status === "ready";
      return localState.status;
    }
  }

  function getPayloadRuntime() {
    payloadRuntime = window[PAYLOAD_NAME] || payloadRuntime;
    return payloadRuntime;
  }

  function ensureActionsReady(options) {
    var config = options || {};

    try {
      if (
        localState.operational === true &&
        localState.readinessResult &&
        config.force !== true &&
        config.forceReload !== true
      ) {
        return Promise.resolve(localState.readinessResult);
      }

      if (
        localState.readinessPromise &&
        config.force !== true &&
        config.forceReload !== true
      ) {
        return localState.readinessPromise;
      }

      ensureCore();
      setActionsStatus("loading", null, {
        source: config.source || "ensure_actions_ready"
      });

      var corePromise = Promise.resolve({ ok: true, ready: true });

      if (core && typeof core.ensureReady === "function") {
        corePromise = Promise.resolve(core.ensureReady({
          source: config.source || "actions",
          force: config.force === true || config.forceReload === true,
          rejectOnError: false,
          timeoutMs: config.timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS
        }));
      }

      localState.readinessPromise = corePromise
        .then(function (coreReadiness) {
          if (!coreReadiness || coreReadiness.ok === false || coreReadiness.ready !== true) {
            throw createActionsError(
              "create_core_not_ready",
              "Create Core is not ready.",
              { readiness: coreReadiness }
            );
          }

          var payloadApi = getPayloadRuntime();

          if (!payloadApi) {
            throw createActionsError(
              "payload_runtime_missing",
              "VectoplanCreatePayload is not available."
            );
          }

          if (typeof payloadApi.ensureReady === "function") {
            return Promise.resolve(payloadApi.ensureReady({
              source: config.source || "actions",
              force: config.force === true || config.forceReload === true,
              rejectOnError: false,
              timeoutMs: config.timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS
            })).then(function (payloadReadiness) {
              return {
                core: coreReadiness,
                payload: payloadReadiness
              };
            });
          }

          return {
            core: coreReadiness,
            payload: {
              ok: true,
              ready: true,
              status: "legacy_payload_runtime"
            }
          };
        })
        .then(function (resolved) {
          if (!resolved.payload || resolved.payload.ok === false || resolved.payload.ready !== true) {
            throw createActionsError(
              "payload_runtime_not_ready",
              "Payload runtime is not ready.",
              { readiness: resolved.payload }
            );
          }

          var result = {
            ok: true,
            ready: true,
            healthy: true,
            operational: true,
            status: "ready",
            component: GLOBAL_NAME,
            version: ACTIONS_VERSION,
            core: resolved.core,
            payload: resolved.payload
          };

          localState.readinessResult = result;
          localState.lastError = null;
          setActionsStatus("ready", null, result);
          safeDispatch("vectoplan:create:actions-ready", getState());

          return result;
        })
        .catch(function (error) {
          var normalized = ensureActionsError(
            error,
            "actions_readiness_failed",
            "Create actions could not become ready."
          );
          var failed = {
            ok: false,
            ready: false,
            operational: false,
            status: "blocked",
            component: GLOBAL_NAME,
            version: ACTIONS_VERSION,
            error: normalizeError(normalized)
          };

          localState.readinessResult = failed;
          setActionsStatus("blocked", normalized, failed);
          safeDispatch("vectoplan:create:actions-blocked", failed);

          if (config.rejectOnError === true) {
            throw normalized;
          }

          return failed;
        })
        .then(function (result) {
          localState.readinessPromise = null;
          return result;
        }, function (error) {
          localState.readinessPromise = null;
          throw error;
        });

      return localState.readinessPromise;
    } catch (error) {
      var failedError = ensureActionsError(
        error,
        "actions_readiness_setup_failed",
        "Create actions readiness could not be prepared."
      );

      setActionsStatus("unavailable", failedError, null);

      if (config.rejectOnError === true) {
        return Promise.reject(failedError);
      }

      return Promise.resolve({
        ok: false,
        ready: false,
        operational: false,
        status: "unavailable",
        error: normalizeError(failedError)
      });
    }
  }

  function isOperational() {
    return localState.operational === true;
  }

  function actionRequiresReadiness(action) {
    return CRITICAL_ACTIONS[normalizeAction(action)] === true;
  }

  function ensureActionRuntimeReady(action, options) {
    var normalizedAction = normalizeAction(action);
    var config = options || {};

    if (!actionRequiresReadiness(normalizedAction)) {
      return Promise.resolve({
        ok: true,
        ready: true,
        action: normalizedAction,
        bypassed: true
      });
    }

    if (core && typeof core.ensureActionReady === "function") {
      return Promise.resolve(core.ensureActionReady(normalizedAction, {
        source: config.source || "actions:" + normalizedAction,
        force: config.force === true,
        rejectOnError: false,
        timeoutMs: config.timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS
      })).then(function (readiness) {
        if (!readiness || readiness.ok === false || readiness.ready !== true) {
          throw createActionsError(
            "action_blocked_core_not_ready",
            actionLabel(normalizedAction) + " kann nicht gestartet werden, weil der Creator noch nicht bereit ist.",
            {
              action: normalizedAction,
              readiness: readiness
            }
          );
        }

        return readiness;
      });
    }

    return ensureActionsReady({
      source: config.source || "actions:" + normalizedAction,
      rejectOnError: true,
      timeoutMs: config.timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS
    });
  }

  function prepareActionPayload(form, action, options) {
    var safeForm = resolveForm(form);
    var normalizedAction = normalizeAction(action);
    var config = options || {};
    var runtime = getPayloadRuntime();

    if (!runtime) {
      return Promise.reject(createActionsError(
        "payload_runtime_missing",
        "VectoplanCreatePayload is not available.",
        { action: normalizedAction }
      ));
    }

    if (typeof runtime.preparePayload === "function") {
      return Promise.resolve(runtime.preparePayload(safeForm, {
        action: normalizedAction,
        source: config.source || "action:" + normalizedAction,
        force: config.force === true,
        rejectOnError: false,
        timeoutMs: config.timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS,
        syncVariants: true,
        syncUploads: true,
        strictValidation: true
      })).then(function (prepared) {
        if (!prepared || prepared.ok === false || prepared.ready !== true || !prepared.payload) {
          throw createActionsError(
            "payload_prepare_failed",
            "Der Create-Payload für " + actionLabel(normalizedAction) + " konnte nicht vorbereitet werden.",
            {
              action: normalizedAction,
              prepared: prepared
            }
          );
        }

        return prepared;
      });
    }

    var payload = collectPayload(safeForm, {
      source: config.source || "action:" + normalizedAction,
      syncVariants: true,
      syncUploads: true
    });

    if (!payload || typeof payload !== "object" || !Object.keys(payload).length) {
      return Promise.reject(createActionsError(
        "payload_empty",
        "Der Create-Payload ist leer.",
        { action: normalizedAction }
      ));
    }

    return Promise.resolve({
      ok: true,
      ready: true,
      status: "legacy_payload",
      payload: payload,
      summary: summarizePayload(payload)
    });
  }


  function runAction(action, form, sourceButton) {
    var normalizedAction = normalizeAction(action);
    var safeForm = resolveForm(form);
    var actionKey = normalizedAction + "::" + String(
      safeForm && (safeForm.id || safeForm.name || "form") || "form"
    );

    try {
      ensureCore();

      if (!normalizedAction) {
        return Promise.resolve(handleRuntimeError(
          String(action || "unknown"),
          createActionsError("unknown_action", "Unbekannte Aktion: " + action)
        ));
      }

      if (
        localState.activeActionPromise &&
        localState.activeActionKey === actionKey
      ) {
        localState.suppressedActionCount += 1;
        return localState.activeActionPromise;
      }

      if (localState.pending || isCorePending()) {
        return Promise.resolve(buildBlockedResult(
          normalizedAction,
          "action_pending",
          "Es läuft bereits eine Aktion."
        ));
      }

      if (!safeForm) {
        return Promise.resolve(handleRuntimeError(
          normalizedAction,
          createActionsError("create_form_not_found", "Create form not found.")
        ));
      }

      localState.actionGeneration += 1;
      var generation = localState.actionGeneration;
      localState.activeActionKey = actionKey;

      var execute = async function () {
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
        setStatus(actionLabel(normalizedAction) + " wird vorbereitet …", "loading");

        updateResultFromPayload(normalizedAction, {
          ok: true,
          status: "preparing",
          _http_status: "—",
          errors: [],
          warnings: []
        });

        await ensureActionRuntimeReady(normalizedAction, {
          source: "action:" + normalizedAction,
          timeoutMs: normalizedAction === "download"
            ? DEFAULT_DOWNLOAD_TIMEOUT_MS
            : DEFAULT_REQUEST_TIMEOUT_MS
        });

        var prepared = await prepareActionPayload(safeForm, normalizedAction, {
          source: "action:" + normalizedAction,
          timeoutMs: normalizedAction === "download"
            ? DEFAULT_DOWNLOAD_TIMEOUT_MS
            : DEFAULT_REQUEST_TIMEOUT_MS
        });
        var payload = enrichPayloadForAction(prepared.payload, normalizedAction);

        localState.lastPayloadSummary = prepared.summary || summarizePayload(payload);
        updateUploadCountsFromSummary(localState.lastPayloadSummary);

        setStatus(actionLabel(normalizedAction) + " läuft …", "loading");

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
          result = await runDownloadWorkflow(payload);
        } else if (normalizedAction === "persist-draft") {
          result = await postJson("persist-draft", enrichPayloadForAction(payload, "persist-draft"));
          localState.persistDraftCount += 1;
        } else if (normalizedAction === "publish-prepare") {
          result = await postJson("publish-prepare", enrichPayloadForAction(payload, "publish-prepare"));
          localState.publishPrepareCount += 1;
        } else {
          throw createActionsError("unknown_action", "Unbekannte Aktion: " + normalizedAction);
        }

        localState.lastResponseAt = timestamp();

        dispatchActionEvent("vectoplan:create:action-complete", normalizedAction, {
          result: result,
          summary: localState.lastPayloadSummary
        });

        return result;
      };

      var execution;

      if (core && typeof core.withLock === "function") {
        execution = core.withLock(ACTION_LOCK, execute, ACTION_LOCK_MS);

        if (execution === undefined) {
          return Promise.resolve(buildBlockedResult(
            normalizedAction,
            "action_lock_active",
            "Aktion wurde blockiert, weil gerade eine andere Aktion verarbeitet wird."
          ));
        }
      } else {
        if (!acquireActionLock(ACTION_LOCK, ACTION_LOCK_MS)) {
          return Promise.resolve(buildBlockedResult(
            normalizedAction,
            "action_lock_active",
            "Aktion wurde blockiert, weil gerade eine andere Aktion verarbeitet wird."
          ));
        }

        execution = Promise.resolve().then(execute).then(function (result) {
          releaseActionLock(ACTION_LOCK);
          return result;
        }, function (error) {
          releaseActionLock(ACTION_LOCK);
          throw error;
        });
      }

      localState.activeActionPromise = Promise.resolve(execution)
        .catch(function (error) {
          dispatchActionEvent("vectoplan:create:action-error", normalizedAction, {
            error: normalizeError(error)
          });

          return handleRuntimeError(normalizedAction, error);
        })
        .then(function (result) {
          if (generation === localState.actionGeneration) {
            localState.activeActionPromise = null;
            localState.activeActionKey = "";
          }

          return result;
        }, function (error) {
          if (generation === localState.actionGeneration) {
            localState.activeActionPromise = null;
            localState.activeActionKey = "";
          }

          return handleRuntimeError(normalizedAction, error);
        })
        .finally(function () {
          try {
            setBusy(safeForm, false, sourceButton);
          } catch (busyError) {
            safeWarn("Busy reset failed.", busyError);
          }

          localState.pending = false;
          localState.currentAction = "";
          setCorePending(false);
        });

      return localState.activeActionPromise;
    } catch (error) {
      localState.activeActionPromise = null;
      localState.activeActionKey = "";
      localState.pending = false;
      localState.currentAction = "";
      setCorePending(false);
      return Promise.resolve(handleRuntimeError(normalizedAction || action, error));
    }
  }

  async function runDownloadWorkflow(payload) {
    var preflight = {
      validate: null,
      packagePlan: null,
      startedAt: timestamp()
    };

    setStatus("Download wird validiert …", "loading");
    preflight.validate = await fetchJson("validate", enrichPayloadForAction(payload, "validate"), {
      timeoutMs: DEFAULT_PREFLIGHT_TIMEOUT_MS,
      purpose: "download_preflight_validate"
    });

    if (!responseIndicatesSuccess(preflight.validate)) {
      localState.lastPreflight = preflight;
      renderFailedResponse("download", preflight.validate, "Validierung für Download fehlgeschlagen.");
      return Object.assign({}, preflight.validate, {
        route: "download",
        status: preflight.validate.status || "download_validation_failed",
        preflight: preflight
      });
    }

    setStatus("Package-Plan wird geprüft …", "loading");
    preflight.packagePlan = await fetchJson("package-plan", enrichPayloadForAction(payload, "package-plan"), {
      timeoutMs: DEFAULT_PREFLIGHT_TIMEOUT_MS,
      purpose: "download_preflight_package_plan"
    });

    if (!responseIndicatesSuccess(preflight.packagePlan)) {
      localState.lastPreflight = preflight;
      renderFailedResponse("download", preflight.packagePlan, "Package-Plan für Download fehlgeschlagen.");
      return Object.assign({}, preflight.packagePlan, {
        route: "download",
        status: preflight.packagePlan.status || "download_package_plan_failed",
        preflight: preflight
      });
    }

    preflight.completedAt = timestamp();
    localState.lastPreflight = clone(preflight);

    setStatus("VPLIB wird erzeugt und heruntergeladen …", "loading");
    return downloadVplib(payload, {
      preflight: preflight,
      timeoutMs: DEFAULT_DOWNLOAD_TIMEOUT_MS
    });
  }

  function responseIndicatesSuccess(response) {
    try {
      if (!response || typeof response !== "object") {
        return false;
      }

      if (response.ok === true || response.valid === true || response.ready === true) {
        return true;
      }

      var status = String(response.status || "").toLowerCase();
      return ["ok", "valid", "ready", "success", "created", "planned"].indexOf(status) !== -1;
    } catch (error) {
      return false;
    }
  }

  function renderFailedResponse(action, response, message) {
    localState.lastResult = response;
    localState.lastAction = action;
    localState.lastHttpStatus = response && response._http_status !== undefined
      ? response._http_status
      : null;

    if (core && core.state) {
      core.state.lastResult = response;
      core.state.lastAction = action;
    }

    printOutput(response, { reveal: true });
    applyResultToUi(response);
    updateResultFromPayload(action, response);
    setStatus(message || actionLabel(action) + " fehlgeschlagen.", "error");
  }

  async function postJson(action, payload) {
    var normalizedAction = normalizeAction(action);
    var response = await fetchJson(
      normalizedAction,
      enrichPayloadForAction(payload, normalizedAction),
      {
        timeoutMs: DEFAULT_REQUEST_TIMEOUT_MS,
        purpose: normalizedAction
      }
    );

    localState.lastResult = response;
    localState.lastAction = normalizedAction;
    localState.lastHttpStatus = response && typeof response._http_status !== "undefined"
      ? response._http_status
      : null;

    if (core && core.state) {
      core.state.lastResult = response;
      core.state.lastAction = normalizedAction;
    }

    printOutput(response, { reveal: true });
    applyResultToUi(response);
    updateResultFromPayload(normalizedAction, response);

    if (responseIndicatesSuccess(response)) {
      setStatus(actionLabel(normalizedAction) + " erfolgreich.", "ok");
    } else {
      setStatus(actionLabel(normalizedAction) + " fehlgeschlagen.", "error");
    }

    return response;
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
              message: "Speichern ist im Frontend-Kontext deaktiviert. Das Backend muss Schreibmodus melden."
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
        message += "\n\nHinweis: " + uploadFileCount + " lokale Upload-Datei(en) sind im Payload als Metadaten enthalten. Datei-Bytes werden vom Backend-Uploadpfad separat verarbeitet.";
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

      return postJson("save", enrichPayloadForAction(payload, "save"));
    } catch (error) {
      throw error;
    }
  }

  async function downloadVplib(payload, options) {
    var config = options || {};
    var enrichedPayload = enrichPayloadForAction(payload, "download");
    var url = resolveActionRouteUrl("download", "/download");
    var requestId = nextRequestId("download");

    localState.lastRoute = url;
    localState.lastRequestId = requestId;

    var response = await fetchWithTimeout(url, {
      method: "POST",
      headers: buildJsonHeaders("application/vnd.vectoplan.vplib, application/zip, application/octet-stream, application/json", requestId),
      body: JSON.stringify(enrichedPayload || {}),
      credentials: "same-origin",
      cache: "no-store"
    }, config.timeoutMs || DEFAULT_DOWNLOAD_TIMEOUT_MS, {
      action: "download",
      requestId: requestId
    });

    var contentType = String(response.headers.get("content-type") || "").toLowerCase();
    var disposition = response.headers.get("content-disposition") || "";
    var appearsJson = contentType.indexOf("application/json") !== -1;
    var appearsHtml = contentType.indexOf("text/html") !== -1;
    var hasAttachmentHeader = /attachment/i.test(disposition);

    if (!response.ok || appearsJson || appearsHtml) {
      var errorPayload = await readResponseAsJson(response);
      errorPayload.route = errorPayload.route || "download";
      errorPayload._request_id = requestId;
      renderFailedResponse("download", errorPayload, "Download fehlgeschlagen.");
      return errorPayload;
    }

    var blob = await response.blob();
    var archiveValidation = await validateVplibBlob(blob, {
      contentType: contentType,
      disposition: disposition,
      hasAttachmentHeader: hasAttachmentHeader
    });

    localState.lastDownloadValidation = clone(archiveValidation);

    if (!archiveValidation.ok) {
      var invalidArchive = {
        ok: false,
        status: "invalid_vplib_archive",
        route: "download",
        _http_status: response.status,
        _request_id: requestId,
        errors: archiveValidation.errors,
        archive_validation: archiveValidation,
        archiveValidation: archiveValidation,
        _payload_summary: summarizePayload(enrichedPayload)
      };

      renderFailedResponse("download", invalidArchive, "Download-Antwort ist kein gültiges VPLIB-Archiv.");
      return invalidArchive;
    }

    var filename = extractDownloadFilename(response) || inferDownloadFilename(enrichedPayload);
    triggerBrowserDownload(blob, filename);

    localState.downloadCount += 1;

    var result = {
      ok: true,
      ready: true,
      status: "download_started",
      route: "download",
      filename: filename,
      size_bytes: blob.size,
      sizeBytes: blob.size,
      content_type: contentType,
      contentType: contentType,
      archive_validation: archiveValidation,
      archiveValidation: archiveValidation,
      preflight: config.preflight || null,
      _http_status: response.status,
      _request_id: requestId,
      headers: {
        create_status: response.headers.get("x-vectoplan-create-status") || "",
        create_route: response.headers.get("x-vectoplan-create-route") || "",
        create_version: response.headers.get("x-vectoplan-create-version") || "",
        vplib_uid: response.headers.get("x-vectoplan-vplib-uid") || "",
        content_disposition: disposition
      },
      _payload_summary: summarizePayload(enrichedPayload)
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
    setStatus("Download gestartet: " + filename, "ok");

    return result;
  }

  async function validateVplibBlob(blob, metadata) {
    var errors = [];
    var contentType = String(metadata && metadata.contentType || "").toLowerCase();

    if (!blob || typeof blob.size !== "number") {
      errors.push({
        severity: "error",
        code: "download_blob_missing",
        message: "Die Download-Antwort enthält keinen Blob."
      });
    } else if (blob.size < DEFAULT_MIN_ARCHIVE_BYTES) {
      errors.push({
        severity: "error",
        code: "download_blob_too_small",
        message: "Das erzeugte VPLIB-Archiv ist ungewöhnlich klein.",
        size_bytes: blob.size
      });
    }

    if (
      contentType &&
      !VPLIB_ARCHIVE_MIME_TYPES[contentType] &&
      contentType.indexOf("zip") === -1 &&
      contentType.indexOf("octet-stream") === -1 &&
      contentType.indexOf("vectoplan") === -1
    ) {
      errors.push({
        severity: "error",
        code: "download_content_type_invalid",
        message: "Die Download-Antwort hat einen unerwarteten Content-Type: " + contentType
      });
    }

    var signature = "";

    if (blob && blob.size >= 4 && typeof blob.slice === "function") {
      try {
        var headerBuffer = await blob.slice(0, 4).arrayBuffer();
        var header = new Uint8Array(headerBuffer);
        signature = Array.prototype.map.call(header, function (value) {
          return value.toString(16).padStart(2, "0");
        }).join("");

        var zipSignature = header[0] === 0x50 && header[1] === 0x4b && (
          (header[2] === 0x03 && header[3] === 0x04) ||
          (header[2] === 0x05 && header[3] === 0x06) ||
          (header[2] === 0x07 && header[3] === 0x08)
        );

        if (!zipSignature) {
          errors.push({
            severity: "error",
            code: "download_archive_signature_invalid",
            message: "Die Antwort besitzt keine gültige ZIP/VPLIB-Signatur.",
            signature: signature
          });
        }
      } catch (signatureError) {
        errors.push({
          severity: "error",
          code: "download_archive_signature_unreadable",
          message: String(signatureError && signatureError.message ? signatureError.message : signatureError)
        });
      }
    }

    return {
      ok: errors.length === 0,
      valid: errors.length === 0,
      status: errors.length === 0 ? "valid" : "invalid",
      size_bytes: blob && blob.size || 0,
      sizeBytes: blob && blob.size || 0,
      content_type: contentType,
      contentType: contentType,
      signature: signature,
      attachment: !!(metadata && metadata.hasAttachmentHeader),
      errors: errors
    };
  }

  async function fetchJson(action, payload, options) {
    var config = options || {};
    var normalizedAction = normalizeAction(action);
    var fallbackPath = ACTION_PATHS[normalizedAction] || "/" + normalizedAction;
    var url = resolveActionRouteUrl(normalizedAction, fallbackPath);
    var requestId = nextRequestId(config.purpose || normalizedAction);

    localState.lastRoute = url;
    localState.lastRequestId = requestId;

    var response = await fetchWithTimeout(url, {
      method: "POST",
      headers: buildJsonHeaders("application/json", requestId),
      body: JSON.stringify(enrichPayloadForAction(payload || {}, normalizedAction)),
      credentials: "same-origin",
      cache: "no-store"
    }, config.timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS, {
      action: normalizedAction,
      requestId: requestId
    });

    var json = await readResponseAsJson(response);

    if (!json || typeof json !== "object") {
      json = {
        ok: false,
        status: "invalid_json_response",
        route: normalizedAction,
        errors: [{
          severity: "error",
          code: "invalid_json_response",
          message: "Backend hat keine gültige JSON-Antwort geliefert."
        }],
        _http_status: response.status
      };
    }

    if (typeof json._http_status === "undefined") {
      json._http_status = response.status;
    }

    json._request_id = json._request_id || requestId;
    json.route = json.route || normalizedAction;
    json._payload_summary = json._payload_summary || summarizePayload(payload || {});

    if (!response.ok && json.ok !== false) {
      json.ok = false;
    }

    return json;
  }

  async function fetchWithTimeout(url, fetchOptions, timeoutMs, metadata) {
    var safeTimeout = parseInt(timeoutMs, 10);

    if (!Number.isFinite(safeTimeout) || safeTimeout < 1000) {
      safeTimeout = DEFAULT_REQUEST_TIMEOUT_MS;
    }

    var controller = typeof AbortController === "function"
      ? new AbortController()
      : null;
    var timeoutId = null;
    var requestMetadata = metadata || {};

    if (controller) {
      fetchOptions.signal = controller.signal;
      localState.abortController = controller;
      timeoutId = window.setTimeout(function () {
        try {
          controller.abort();
        } catch (abortError) {
          /* no-op */
        }
      }, safeTimeout);
    }

    try {
      return await fetch(url, fetchOptions);
    } catch (error) {
      var aborted = error && (
        error.name === "AbortError" ||
        String(error.message || "").toLowerCase().indexOf("abort") !== -1
      );

      if (aborted) {
        throw createActionsError(
          "request_timeout",
          actionLabel(requestMetadata.action) + " wurde nach " + String(safeTimeout) + " ms abgebrochen.",
          {
            action: requestMetadata.action,
            url: url,
            requestId: requestMetadata.requestId,
            timeoutMs: safeTimeout
          },
          error
        );
      }

      throw ensureActionsError(
        error,
        "network_request_failed",
        actionLabel(requestMetadata.action) + " konnte das Backend nicht erreichen.",
        {
          action: requestMetadata.action,
          url: url,
          requestId: requestMetadata.requestId
        }
      );
    } finally {
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }

      if (localState.abortController === controller) {
        localState.abortController = null;
      }
    }
  }

  async function readResponseAsJson(response) {
    var text = "";

    try {
      text = await response.text();

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
        errors: [{
          severity: "error",
          code: "response_parse_failed",
          message: String(error && error.message ? error.message : error),
          response_preview: String(text || "").slice(0, 500)
        }],
        _http_status: response && response.status ? response.status : 0
      };
    }
  }

  function nextRequestId(purpose) {
    localState.requestSequence += 1;
    return [
      "vp-create",
      String(purpose || "request").replace(/[^a-z0-9_-]/gi, "-").toLowerCase(),
      Date.now(),
      localState.requestSequence
    ].join("-");
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

      if (!payload.taxonomy_path) {
        payload.taxonomy_path = [payload.domain, payload.category, payload.subcategory].filter(Boolean).join("/");
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

  function enrichPayloadForAction(payload, action) {
    try {
      var normalizedAction = normalizeAction(action);
      var enriched = clone(payload || {}) || {};
      var createContext = getCreateContext();
      var generatorContext = getGeneratorContext();
      var contract = getPayloadContract();

      enriched.workflow_action = normalizedAction;
      enriched.action = normalizedAction;
      enriched.client_action = normalizedAction;
      enriched.clientAction = normalizedAction;
      enriched.client_actions_version = ACTIONS_VERSION;
      enriched.clientActionsVersion = ACTIONS_VERSION;

      if (!enriched.vplib_uid && !enriched.vplibUid) {
        var uid = firstNonEmpty(
          getNested(generatorContext, ["vplib_uid"], ""),
          getNested(generatorContext, ["data", "vplib_uid"], ""),
          getNested(createContext, ["context", "vplib_uid"], "")
        );
        if (uid) {
          enriched.vplib_uid = uid;
          enriched.vplibUid = uid;
        }
      }

      if (!enriched.taxonomy_path && !enriched.taxonomyPath) {
        enriched.taxonomy_path = [enriched.domain, enriched.category, enriched.subcategory].filter(Boolean).join("/");
        enriched.taxonomyPath = enriched.taxonomy_path;
      }

      enriched.generator_context_uid = enriched.generator_context_uid ||
        enriched.generatorContextUid ||
        getNested(generatorContext, ["context_uid"], "") ||
        getNested(generatorContext, ["data", "context_uid"], "");

      enriched.generatorContextUid = enriched.generatorContextUid || enriched.generator_context_uid;

      enriched.payload_contract_schema_version = enriched.payload_contract_schema_version ||
        enriched.payloadContractSchemaVersion ||
        contract.schema_version ||
        contract.schemaVersion ||
        "create_payload.v1";

      enriched.payloadContractSchemaVersion = enriched.payloadContractSchemaVersion || enriched.payload_contract_schema_version;

      if (normalizedAction === "save") {
        enriched.save_source = true;
        enriched.saveSource = true;
        enriched.allow_source_write = isWriteEnabled();
        enriched.allowSourceWrite = enriched.allow_source_write;
      }

      if (normalizedAction === "persist-draft") {
        enriched.persist = true;
        enriched.save_draft = true;
        enriched.saveDraft = true;
        enriched.allow_draft_write = true;
        enriched.allowDraftWrite = true;
      }

      if (normalizedAction === "publish-prepare") {
        enriched.publish_prepare = true;
        enriched.publishPrepare = true;
        enriched.include_draft = true;
        enriched.includeDraft = true;
      }

      return enriched;
    } catch (error) {
      safeWarn("Payload action enrichment failed.", error);
      return payload || {};
    }
  }

  function getCreateContext() {
    try {
      return window.VectoplanCreateContext || {};
    } catch (error) {
      return {};
    }
  }

  function getGeneratorContext() {
    try {
      var context = getCreateContext();
      return window.VectoplanGeneratorContext ||
        context.generatorContext ||
        context.generator_context ||
        {};
    } catch (error) {
      return {};
    }
  }

  function getPayloadContract() {
    try {
      var context = getCreateContext();
      return window.VectoplanCreatePayloadContract ||
        context.payloadContract ||
        context.payload_contract ||
        {};
    } catch (error) {
      return {};
    }
  }

  function firstNonEmpty() {
    try {
      for (var index = 0; index < arguments.length; index += 1) {
        var value = arguments[index];

        if (value === null || value === undefined) {
          continue;
        }

        if (typeof value === "string" && !value.trim()) {
          continue;
        }

        return value;
      }

      return "";
    } catch (error) {
      return "";
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
        backend_enabled: true,
        backendEnabled: true,
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
      var ready = localState.operational === true;

      qsa(selectorFor("actionButton"), scope).forEach(function (button) {
        try {
          var action = normalizeAction(button.getAttribute("data-create-action") || "");
          var staticallyDisabled = button.getAttribute("data-create-static-disabled") === "true";
          var requiresReady = actionRequiresReadiness(action);
          var disabledByReadiness = requiresReady && !ready;
          var disabledByWriteMode = action === "save" && !isWriteEnabled();
          var shouldDisable = staticallyDisabled || disabledByReadiness || disabledByWriteMode || localState.pending;

          button.disabled = shouldDisable;
          button.setAttribute("aria-disabled", shouldDisable ? "true" : "false");
          button.setAttribute("data-vp-action-readiness-required", requiresReady ? "true" : "false");
          button.setAttribute("data-vp-action-readiness-blocked", disabledByReadiness ? "true" : "false");

          if (disabledByWriteMode) {
            button.setAttribute("title", "Speichern ist deaktiviert. Backend-Schreibmodus erforderlich.");
          } else if (disabledByReadiness) {
            button.setAttribute("title", "Creator wird vorbereitet. Die Aktion wird freigegeben, sobald Profile und Payload bereit sind.");
          } else if (!staticallyDisabled) {
            button.removeAttribute("title");
          }
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
      var normalizedAction = normalizeAction(action);
      var routeKey = routeKeyForAction(normalizedAction);
      var fallback = fallbackPath || ACTION_PATHS[normalizedAction] || "/" + normalizedAction;

      if (core && typeof core.resolveRouteUrl === "function") {
        return core.resolveRouteUrl(routeKey, fallback);
      }

      var context = getCreateContext();
      var routes = context.routes || {};
      var routeFromContext = routes[routeKey] ||
        routes[normalizedAction] ||
        routes[camelRouteKey(routeKey)] ||
        "";

      if (routeFromContext) {
        return routeFromContext;
      }

      var apiPrefix = getApiPrefix();

      return apiPrefix.replace(/\/$/, "") + fallback;
    } catch (error) {
      safeWarn("Resolve action route URL failed.", error);
      return getApiPrefix().replace(/\/$/, "") + (fallbackPath || "");
    }
  }

  function routeKeyForAction(action) {
    if (action === "package-plan") {
      return "package_plan";
    }

    if (action === "persist-draft") {
      return "persistent_draft";
    }

    if (action === "publish-prepare") {
      return "publish_bundle";
    }

    return action;
  }

  function camelRouteKey(value) {
    if (value === "package_plan") {
      return "packagePlan";
    }

    if (value === "persistent_draft") {
      return "persistentDraft";
    }

    if (value === "publish_bundle") {
      return "publishBundle";
    }

    return value;
  }

  function triggerBrowserDownload(blob, filename) {
    try {
      if (!blob || typeof blob.size !== "number") {
        throw createActionsError(
          "download_blob_missing",
          "Der Browser-Download kann ohne Blob nicht gestartet werden."
        );
      }

      var objectUrl = URL.createObjectURL(blob);
      var anchor = document.createElement("a");
      var safeFilename = sanitizeFilename(filename || "package.vplib");
      var host = document.body || document.documentElement;

      anchor.href = objectUrl;
      anchor.download = safeFilename;
      anchor.rel = "noopener";
      anchor.style.display = "none";
      anchor.setAttribute("data-vp-create-temporary-download", "true");

      if (!host || typeof host.appendChild !== "function") {
        URL.revokeObjectURL(objectUrl);
        throw createActionsError(
          "download_dom_unavailable",
          "Der temporäre Download-Link konnte nicht in das Dokument eingefügt werden."
        );
      }

      host.appendChild(anchor);

      if (typeof anchor.click === "function") {
        anchor.click();
      } else if (typeof MouseEvent === "function") {
        anchor.dispatchEvent(new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          view: window
        }));
      } else {
        throw createActionsError(
          "download_click_unavailable",
          "Der Browser unterstützt keinen programmatischen Download-Klick."
        );
      }

      localState.downloadTriggerCount += 1;
      localState.lastDownloadTrigger = {
        ok: true,
        filename: safeFilename,
        sizeBytes: blob.size,
        objectUrlCreated: true,
        cleanupDelayMs: DOWNLOAD_URL_REVOKE_DELAY_MS,
        timestamp: timestamp()
      };

      window.setTimeout(function () {
        try {
          URL.revokeObjectURL(objectUrl);
          if (anchor && typeof anchor.remove === "function") {
            anchor.remove();
          } else if (anchor && anchor.parentNode) {
            anchor.parentNode.removeChild(anchor);
          }
          localState.objectUrlCleanupCount += 1;
        } catch (cleanupError) {
          rememberBindingError("download_url_cleanup", cleanupError);
        }
      }, DOWNLOAD_URL_REVOKE_DELAY_MS);

      return clone(localState.lastDownloadTrigger);
    } catch (error) {
      localState.lastDownloadTrigger = {
        ok: false,
        filename: sanitizeFilename(filename || "package.vplib"),
        error: normalizeError(error),
        timestamp: timestamp()
      };
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

      if (text === "package-plan") {
        return "package-plan";
      }

      if (text === "persist-draft" || text === "persistent-draft") {
        return "persist-draft";
      }

      if (text === "publish-prepare" || text === "publish-bundle") {
        return "publish-prepare";
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
        variants = safeJsonParse(payload.definition_variants_json, []);
      }

      var uploadsSummary = payload && (payload.uploads_summary || payload.uploadsSummary)
        ? payload.uploads_summary || payload.uploadsSummary
        : {};

      return {
        vplib_uid: payload && (payload.vplib_uid || payload.vplibUid) ? payload.vplib_uid || payload.vplibUid : "",
        family_name: payload && payload.family_name ? payload.family_name : "",
        domain: payload && payload.domain ? payload.domain : "",
        category: payload && payload.category ? payload.category : "",
        subcategory: payload && payload.subcategory ? payload.subcategory : "",
        taxonomy_path: payload && (payload.taxonomy_path || payload.taxonomyPath) ? payload.taxonomy_path || payload.taxonomyPath : "",
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
        persistDraftCount: localState.persistDraftCount,
        publishPrepareCount: localState.publishPrepareCount,
        resultVisible: localState.resultVisible,
        writeEnabled: isWriteEnabled(),
        lastRoute: localState.lastRoute,
        lastRequestAt: localState.lastRequestAt,
        lastResponseAt: localState.lastResponseAt,
        lastUploadFileCount: localState.lastUploadFileCount,
        lastUploadErrorCount: localState.lastUploadErrorCount,
        operational: localState.operational,
        ready: localState.operational,
        status: localState.status,
        readiness: clone(localState.readinessResult),
        activeAction: localState.activeActionKey,
        actionInFlight: !!localState.activeActionPromise,
        suppressedActionCount: localState.suppressedActionCount,
        lastRequestId: localState.lastRequestId,
        lastPreflight: clone(localState.lastPreflight),
        lastDownloadValidation: clone(localState.lastDownloadValidation),
        binding: getBindingSnapshot(),
        bindingAttempts: localState.bindingAttempts,
        bindingSuccessCount: localState.bindingSuccessCount,
        bindingRepairCount: localState.bindingRepairCount,
        delegatedActionListenerBound: localState.delegatedActionListenerBound,
        delegatedResultListenerBound: localState.delegatedResultListenerBound,
        mutationObserverActive: localState.mutationObserverActive,
        directButtonCount: localState.directButtonCount,
        actionButtonCount: localState.actionButtonCount,
        clickCount: localState.clickCount,
        delegatedClickCount: localState.delegatedClickCount,
        directClickCount: localState.directClickCount,
        suppressedDuplicateClickCount: localState.suppressedDuplicateClickCount,
        blockedClickCount: localState.blockedClickCount,
        lastClick: clone(localState.lastClick),
        lastBindingVerification: clone(localState.lastBindingVerification),
        bindingErrors: clone(localState.bindingErrors),
        downloadTriggerCount: localState.downloadTriggerCount,
        lastDownloadTrigger: clone(localState.lastDownloadTrigger),
        objectUrlCleanupCount: localState.objectUrlCleanupCount,
        routes: clone(getCreateContext().routes || {})
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
      var normalized = ensureActionsError(
        error,
        "create_actions_error",
        "Create action failed."
      );

      return {
        code: normalized.code || normalized.name || "create_actions_error",
        message: String(normalized.message || "Create action failed."),
        name: normalized.name || "Error",
        status: normalized.status || null,
        action: normalized.action || null,
        url: normalized.url || null,
        requestId: normalized.requestId || null,
        payload: normalized.payload || null,
        details: normalized.details || null,
        stack: normalized.stack ? String(normalized.stack) : "",
        timestamp: timestamp()
      };
    } catch (normalizationError) {
      return {
        code: "create_actions_error",
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

  function getNested(object, path, fallbackValue) {
    try {
      var cursor = object || {};

      for (var index = 0; index < path.length; index += 1) {
        if (!cursor || typeof cursor !== "object" || !(path[index] in cursor)) {
          return fallbackValue;
        }

        cursor = cursor[path[index]];
      }

      return cursor === undefined || cursor === null ? fallbackValue : cursor;
    } catch (error) {
      return fallbackValue;
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

  function buildJsonHeaders(accept, requestId) {
    try {
      var headers = {
        "Content-Type": "application/json",
        "Accept": accept || "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-Vectoplan-Component": GLOBAL_NAME,
        "X-Vectoplan-Component-Version": ACTIONS_VERSION,
        "X-Vectoplan-Request-Id": requestId || nextRequestId("headers")
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

      var context = getCreateContext();
      if (context.apiPrefix || context.api_prefix) {
        return context.apiPrefix || context.api_prefix;
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

      var context = getCreateContext();

      if (typeof context.writeEnabled !== "undefined" || typeof context.write_enabled !== "undefined") {
        return toBoolean(context.writeEnabled !== undefined ? context.writeEnabled : context.write_enabled, false);
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
      if (typeof callback !== "function") {
        return false;
      }

      if (core && typeof core.bindOnce === "function") {
        return core.bindOnce(key, callback) === true;
      }

      var attr = "data-vp-" + String(key || "bind-once").replace(/[^a-z0-9_-]/gi, "-");

      if (document.documentElement.getAttribute(attr) === "true") {
        return false;
      }

      var result = callback();

      if (result === false) {
        return false;
      }

      document.documentElement.setAttribute(attr, "true");
      return true;
    } catch (error) {
      rememberBindingError("bind_once:" + key, error);
      safeWarn("bindOnce failed: " + key, error);
      return false;
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
      backend_enabled: true,
      backendEnabled: true,
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
        backend_enabled: source.backend_enabled !== undefined ? toBoolean(source.backend_enabled, true) : toBoolean(source.backendEnabled, true),
        backendEnabled: source.backendEnabled !== undefined ? toBoolean(source.backendEnabled, true) : toBoolean(source.backend_enabled, true),
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
        withLock: function (name, callback, ttl) {
          if (!acquireActionLock(name, ttl)) {
            return undefined;
          }

          var result;
          try {
            result = callback();
          } catch (error) {
            releaseActionLock(name);
            throw error;
          }

          return Promise.resolve(result).then(function (value) {
            releaseActionLock(name);
            return value;
          }, function (error) {
            releaseActionLock(name);
            throw error;
          });
        },
        ensureReady: function () {
          return Promise.resolve({ ok: true, ready: true });
        },
        ensureActionReady: function () {
          return Promise.resolve({ ok: true, ready: true });
        },
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
    bindControls: bindControls,
    repairBindings: repairControlBindings,
    verifyBindings: verifyControlBindings,
    diagnoseBindings: getBindingSnapshot,
    bindDirectActionButtons: bindDirectActionButtons,
    ensureReady: ensureActionsReady,
    whenReady: ensureActionsReady,
    waitUntilReady: ensureActionsReady,
    isOperational: isOperational,

    runAction: runAction,
    runDownloadWorkflow: runDownloadWorkflow,
    prepareActionPayload: prepareActionPayload,
    ensureActionReady: ensureActionRuntimeReady,
    postJson: postJson,
    fetchJson: fetchJson,
    confirmAndSave: confirmAndSave,
    downloadVplib: downloadVplib,
    triggerBrowserDownload: triggerBrowserDownload,
    validateVplibBlob: validateVplibBlob,
    responseIndicatesSuccess: responseIndicatesSuccess,

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

    enrichPayloadForAction: enrichPayloadForAction,
    getCreateContext: getCreateContext,
    getGeneratorContext: getGeneratorContext,
    getPayloadContract: getPayloadContract,

    createError: createActionsError,
    ensureError: ensureActionsError,
    normalizeError: normalizeError,
    setActionsStatus: setActionsStatus,
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
