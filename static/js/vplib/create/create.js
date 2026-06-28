/* services/vectoplan-library/static/js/vplib/create/create.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreate";
  var CREATE_VERSION = "0.7.0";
  var CORE_NAME = "VectoplanCreateCore";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 100;
  var REFRESH_DEBOUNCE_MS = 80;

  var MODULES = {
    core: "VectoplanCreateCore",
    theme: "VectoplanCreateTheme",
    wizard: "VectoplanCreateWizard",
    preview: "VectoplanCreatePreview",
    dynamicRowsLegacy: "VectoplanCreateDynamicRowsLegacy",
    uploads: "VectoplanCreateUploads",
    payload: "VectoplanCreatePayload",
    actions: "VectoplanCreateActions",

    variantUtils: "VectoplanCreateVariantUtils",
    variantState: "VectoplanCreateVariantState",
    variantProfiles: "VectoplanCreateVariantProfiles",
    variantSummary: "VectoplanCreateVariantSummary",
    variantFieldRenderer: "VectoplanCreateVariantFieldRenderer",
    variantOptionalFields: "VectoplanCreateVariantOptionalFields",
    variantValidation: "VectoplanCreateVariantValidation",
    variantDrawerShell: "VectoplanCreateVariantDrawerShell",
    variantDrawer: "VectoplanCreateVariantDrawer",
    variantTable: "VectoplanCreateVariantTable",
    variantWorkspace: "VectoplanCreateVariantWorkspace",

    definitionsRuntime: "VectoplanCreateDefinitionsRuntime"
  };

  var INIT_ORDER = [
    "core",
    "theme",
    "wizard",
    "preview",
    "dynamicRowsLegacy",
    "uploads",
    "payload",
    "actions",
    "variantUtils",
    "variantState",
    "variantProfiles",
    "variantSummary",
    "variantFieldRenderer",
    "variantOptionalFields",
    "variantValidation",
    "variantDrawerShell",
    "variantDrawer",
    "variantTable",
    "variantWorkspace",
    "definitionsRuntime"
  ];

  var ACTION_ALIASES = {
    package_plan: "package-plan",
    "package-plan": "package-plan",
    persist_draft: "persist-draft",
    "persist-draft": "persist-draft",
    persistent_draft: "persist-draft",
    "persistent-draft": "persist-draft",
    publish_prepare: "publish-prepare",
    "publish-prepare": "publish-prepare",
    publish_bundle: "publish-prepare",
    "publish-bundle": "publish-prepare"
  };

  var state = {
    version: CREATE_VERSION,
    initialized: false,
    ready: false,
    degraded: false,
    bootAttempts: 0,
    bootStartedAt: "",
    bootFinishedAt: "",
    lastRefreshAt: "",
    lastLightRefreshAt: "",
    lastError: null,
    moduleStatus: {},
    publicApiExposed: false,
    refreshCount: 0,
    lightRefreshCount: 0,
    actionCount: 0,
    payloadCollectCount: 0,
    variantSyncCount: 0,
    uploadSyncCount: 0,
    finalSubmitCount: 0,
    compatibilityEventsBound: false,
    pendingRefreshTimer: null
  };

  var api = {
    version: CREATE_VERSION,

    initialize: initialize,
    boot: boot,
    refresh: refresh,
    refreshLight: refreshLight,

    getState: getState,
    getModulesState: getModulesState,
    getModule: getModule,
    getCore: getCore,

    getCreateContext: getCreateContext,
    getGeneratorContext: getGeneratorContext,
    getPayloadContract: getPayloadContract,
    getRoutes: getRoutes,

    collectPayload: collectPayload,
    collectFormPayload: collectPayload,

    runAction: runAction,

    goToStep: goToStep,
    nextStep: nextStep,
    prevStep: previousStep,
    previousStep: previousStep,

    setTheme: setTheme,
    cycleTheme: cycleTheme,
    getTheme: getTheme,

    updatePreview: updatePreview,

    syncVariants: syncVariants,
    syncVariantRuntimeToForm: syncVariants,
    syncUploads: syncUploads,
    syncUploadsRuntimeToForm: syncUploads,

    getDefinitionVariants: getDefinitionVariants,
    getDefinitionVariantsJson: getDefinitionVariantsJson,
    getUploadMetadata: getUploadMetadata,

    getCurrentStep: getCurrentStep
  };

  exposePublicApi();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      boot(0);
    }, { once: true });
  } else {
    boot(0);
  }

  function boot(attempt) {
    try {
      var safeAttempt = typeof attempt === "number" ? attempt : 0;
      state.bootAttempts = safeAttempt;
      state.bootStartedAt = state.bootStartedAt || timestamp();

      var core = getCore();

      if (!core || !core.state || !core.selectors) {
        if (safeAttempt < BOOT_MAX_ATTEMPTS) {
          window.setTimeout(function () {
            boot(safeAttempt + 1);
          }, BOOT_RETRY_MS);
          return;
        }

        state.lastError = normalizeError(new Error("VectoplanCreateCore is not available."));
        state.degraded = true;
        fallbackWarn("Core runtime missing; create orchestrator initialized in degraded mode.");
        wireCompatibilityEvents();
        markRuntimeReady(false);
        dispatch("vectoplan:create:degraded-ready", getState());
        return;
      }

      initialize();
    } catch (error) {
      state.lastError = normalizeError(error);
      fallbackWarn("Create orchestrator boot failed.", error);
      markRuntimeReady(false);
    }
  }

  function initialize() {
    try {
      if (state.initialized) {
        return api;
      }

      var core = getCore();

      if (!core) {
        throw new Error("VectoplanCreateCore is not available.");
      }

      if (typeof core.refreshContext === "function") {
        core.refreshContext();
      }

      initializeModules();
      wireCompatibilityEvents();

      refresh({
        source: "initialize",
        silent: true
      });

      state.initialized = true;
      state.ready = true;
      state.degraded = false;
      state.bootFinishedAt = timestamp();

      safeSetRootAttribute("data-vp-create-runtime-ready", "true");
      safeSetRootAttribute("data-vp-create-version", CREATE_VERSION);
      safeSetRootAttribute("data-vp-create-orchestrator-ready", "true");
      safeSetRootAttribute("data-vp-create-orchestrator-version", CREATE_VERSION);
      safeSetRootAttribute("data-vp-create-generator-context-ready", hasGeneratorContext() ? "true" : "false");

      dispatch("vectoplan:create:ready", getState());

      log("Create orchestrator ready.", getState());

      return api;
    } catch (error) {
      state.initialized = false;
      state.ready = false;
      state.degraded = true;
      state.lastError = normalizeError(error);

      fallbackWarn("Create orchestrator initialization failed.", error);
      markRuntimeReady(false);

      return api;
    }
  }

  function initializeModules() {
    try {
      INIT_ORDER.forEach(function (moduleKey) {
        try {
          var moduleApi = getModule(moduleKey);
          var status = {
            key: moduleKey,
            globalName: MODULES[moduleKey],
            present: !!moduleApi,
            initialized: false,
            error: ""
          };

          if (moduleKey === "core") {
            status.initialized = !!moduleApi;
            state.moduleStatus[moduleKey] = status;
            return;
          }

          if (moduleApi && typeof moduleApi.initialize === "function") {
            try {
              initializeModule(moduleKey, moduleApi);
              status.initialized = true;
            } catch (initError) {
              status.error = String(initError && initError.message ? initError.message : initError);
              fallbackWarn("Module initialization failed: " + moduleKey, initError);
            }
          } else if (moduleApi) {
            status.initialized = true;
          }

          state.moduleStatus[moduleKey] = status;
        } catch (moduleError) {
          state.moduleStatus[moduleKey] = {
            key: moduleKey,
            globalName: MODULES[moduleKey],
            present: false,
            initialized: false,
            error: String(moduleError && moduleError.message ? moduleError.message : moduleError)
          };
        }
      });
    } catch (error) {
      fallbackWarn("Initialize modules failed.", error);
    }
  }

  function initializeModule(moduleKey, moduleApi) {
    var core = getCore();

    if (!moduleApi || typeof moduleApi.initialize !== "function") {
      return null;
    }

    if (moduleKey === "uploads") {
      return moduleApi.initialize(resolveForm() || document);
    }

    if (moduleKey === "definitionsRuntime") {
      return moduleApi.initialize({
        core: core,
        context: getCreateContext(),
        generatorContext: getGeneratorContext()
      });
    }

    return moduleApi.initialize(core);
  }

  function wireCompatibilityEvents() {
    try {
      if (state.compatibilityEventsBound) {
        return;
      }

      state.compatibilityEventsBound = true;

      bindOnce("create-orchestrator-profile-context-sync", function () {
        document.addEventListener("vectoplan:create:variant-profile-context-changed", function () {
          try {
            syncVariants({
              source: "profile-context-changed"
            });
          } catch (error) {
            warn("Variant sync after profile context change failed.", error);
          }
        });
      });

      bindOnce("create-orchestrator-step-changed-refresh", function () {
        [
          "vectoplan:create:step-changed",
          "vectoplan:create:wizard-step-changed",
          "vectoplan:create:wizard-ui-updated"
        ].forEach(function (eventName) {
          document.addEventListener(eventName, function () {
            scheduleRefresh({
              source: eventName,
              silent: true,
              light: true
            });
          });
        });
      });

      bindOnce("create-orchestrator-variant-state-sync", function () {
        [
          "vectoplan:create:variant-state-changed",
          "vectoplan:create:variant-state-synced",
          "vectoplan:create:variant-added",
          "vectoplan:create:variant-updated",
          "vectoplan:create:variant-removed",
          "vectoplan:create:variant-profile-resolved",
          "vectoplan:create:variant-empty-values-ready"
        ].forEach(function (eventName) {
          document.addEventListener(eventName, function () {
            try {
              syncVariants({
                source: eventName
              });
              scheduleRefresh({
                source: eventName,
                silent: true,
                light: true
              });
            } catch (error) {
              warn("Variant state sync failed: " + eventName, error);
            }
          });
        });
      });

      bindOnce("create-orchestrator-upload-sync", function () {
        [
          "vectoplan:create:uploads-runtime-ready",
          "vectoplan:create:upload-changed",
          "vectoplan:create:upload-cleared",
          "vectoplan:create:geometry-upload-changed",
          "vectoplan:create:technical-upload-changed",
          "vectoplan:create:variables-upload-changed"
        ].forEach(function (eventName) {
          document.addEventListener(eventName, function () {
            try {
              syncUploads({
                source: eventName,
                fromUploadEvent: true,
                skipRuntimeSync: true,
                silent: true
              });
              scheduleRefresh({
                source: eventName,
                silent: true,
                light: true
              });
            } catch (error) {
              warn("Upload sync failed: " + eventName, error);
            }
          });
        });
      });

      bindOnce("create-orchestrator-final-submit", function () {
        document.addEventListener("vectoplan:create:final-submit-requested", function (event) {
          try {
            state.finalSubmitCount += 1;

            dispatch("vectoplan:create:final-step-ready", {
              source: event && event.detail ? event.detail.source || "final-submit" : "final-submit",
              state: getState()
            });

            setStatus("Finaler Schritt. Aktion auswählen.", "ok");
          } catch (error) {
            warn("Final submit handling failed.", error);
          }
        });
      });

      bindOnce("create-orchestrator-context-refresh", function () {
        [
          "vectoplan:create:context-ready",
          "vectoplan:create:uploads-ready",
          "vectoplan:create:definitions-ready",
          "vectoplan:create:definitions-unavailable",
          "vectoplan:create:core-ready",
          "vectoplan:create:core-context-refreshed"
        ].forEach(function (eventName) {
          document.addEventListener(eventName, function () {
            scheduleRefresh({
              source: eventName,
              silent: true,
              light: true
            });
          });
        });
      });

      bindOnce("create-orchestrator-action-trace", function () {
        [
          "vectoplan:create:action-start",
          "vectoplan:create:action-complete",
          "vectoplan:create:action-error"
        ].forEach(function (eventName) {
          document.addEventListener(eventName, function (event) {
            try {
              var detail = event && event.detail ? event.detail : {};
              if (detail.action) {
                state.lastAction = detail.action;
              }
            } catch (error) {
              warn("Action trace failed: " + eventName, error);
            }
          });
        });
      });
    } catch (error) {
      fallbackWarn("Compatibility event wiring failed.", error);
    }
  }

  function collectPayload(options) {
    try {
      state.payloadCollectCount += 1;

      var payloadModule = getModule("payload");
      var form = resolveForm();

      if (payloadModule && typeof payloadModule.collectPayload === "function") {
        return payloadModule.collectPayload(form, Object.assign({
          source: "public-api",
          syncVariants: true,
          syncUploads: true
        }, options || {}));
      }

      return collectPayloadFallback(form);
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("collectPayload failed.", error);
      return {};
    }
  }

  function runAction(action, sourceButton) {
    try {
      state.actionCount += 1;

      var normalizedAction = normalizeAction(action);
      var actionsModule = getModule("actions");
      var form = resolveForm();

      if (actionsModule && typeof actionsModule.runAction === "function") {
        return actionsModule.runAction(normalizedAction || action, form, sourceButton || null);
      }

      var result = {
        ok: false,
        status: "actions_runtime_missing",
        action: normalizedAction || action,
        errors: [
          {
            severity: "error",
            code: "actions_runtime_missing",
            message: "create_actions.js ist nicht geladen oder nicht initialisiert."
          }
        ]
      };

      warn("runAction failed because create_actions.js is missing.", result);

      return Promise.resolve(result);
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("runAction failed.", error);

      return Promise.resolve({
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
      });
    }
  }

  function goToStep(stepIndex, options) {
    try {
      var wizardModule = getModule("wizard");

      if (wizardModule && typeof wizardModule.goToStep === "function") {
        return wizardModule.goToStep(stepIndex, Object.assign({
          source: "public-api",
          validate: false,
          focus: true
        }, options || {}));
      }

      warn("goToStep ignored because create_wizard.js is missing.");
      return getCurrentStep();
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("goToStep failed.", error);
      return getCurrentStep();
    }
  }

  function nextStep(options) {
    try {
      var wizardModule = getModule("wizard");

      if (wizardModule && typeof wizardModule.nextStep === "function") {
        return wizardModule.nextStep(Object.assign({
          source: "public-api",
          validate: true,
          focus: true
        }, options || {}));
      }

      return goToStep(getCurrentStep() + 1, options || {});
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("nextStep failed.", error);
      return getCurrentStep();
    }
  }

  function previousStep(options) {
    try {
      var wizardModule = getModule("wizard");

      if (wizardModule && typeof wizardModule.previousStep === "function") {
        return wizardModule.previousStep(Object.assign({
          source: "public-api",
          focus: true
        }, options || {}));
      }

      return goToStep(getCurrentStep() - 1, Object.assign({
        validate: false
      }, options || {}));
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("previousStep failed.", error);
      return getCurrentStep();
    }
  }

  function setTheme(theme, options) {
    try {
      var themeModule = getModule("theme");

      if (themeModule && typeof themeModule.setTheme === "function") {
        return themeModule.setTheme(theme, Object.assign({
          persist: true,
          source: "public-api"
        }, options || {}));
      }

      var core = getCore();

      if (core && typeof core.normalizeTheme === "function") {
        var normalized = core.normalizeTheme(theme);
        document.documentElement.setAttribute("data-theme", normalized);
        document.documentElement.setAttribute("data-vp-theme", normalized);
        document.documentElement.setAttribute("data-vp-create-theme", normalized);
        core.state.theme = normalized;
        return normalized;
      }

      return "dark";
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("setTheme failed.", error);
      return "dark";
    }
  }

  function cycleTheme(options) {
    try {
      var themeModule = getModule("theme");

      if (themeModule && typeof themeModule.cycleTheme === "function") {
        return themeModule.cycleTheme(Object.assign({
          source: "public-api"
        }, options || {}));
      }

      return setTheme("dark", options || {});
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("cycleTheme failed.", error);
      return getTheme();
    }
  }

  function updatePreview(options) {
    try {
      var previewModule = getModule("preview");
      var form = resolveForm();

      if (previewModule && typeof previewModule.updatePreview === "function") {
        return previewModule.updatePreview(form, Object.assign({
          source: "public-api",
          animate: true
        }, options || {}));
      }

      if (previewModule && typeof previewModule.refresh === "function") {
        return previewModule.refresh(Object.assign({
          source: "public-api",
          animate: true
        }, options || {}));
      }

      return false;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("updatePreview failed.", error);
      return false;
    }
  }

  function syncVariants(options) {
    try {
      state.variantSyncCount += 1;

      var payloadModule = getModule("payload");
      var form = resolveForm();

      if (payloadModule && typeof payloadModule.syncVariantRuntimeToForm === "function") {
        return payloadModule.syncVariantRuntimeToForm(form, Object.assign({
          source: "public-api"
        }, options || {}));
      }

      return false;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("syncVariants failed.", error);
      return false;
    }
  }

  function syncUploads(options) {
    try {
      state.uploadSyncCount += 1;

      var safeOptions = options || {};
      var uploadsModule = getModule("uploads");
      var payloadModule = getModule("payload");
      var form = resolveForm();
      var ok = false;

      if (uploadsModule && typeof uploadsModule.syncAll === "function" && safeOptions.skipRuntimeSync !== true) {
        uploadsModule.syncAll(form || document, {
          source: safeOptions.source || "public-api",
          silent: safeOptions.silent !== false,
          emitEvents: false,
          emitNativeEvents: false
        });
        ok = true;
      }

      if (payloadModule && typeof payloadModule.syncUploadsRuntimeToForm === "function") {
        payloadModule.syncUploadsRuntimeToForm(form, Object.assign({
          source: "public-api",
          skipRuntimeSync: true,
          fromUploadEvent: !!safeOptions.fromUploadEvent,
          emitEvents: false
        }, safeOptions));
        ok = true;
      }

      return ok;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("syncUploads failed.", error);
      return false;
    }
  }

  function getDefinitionVariants() {
    try {
      var payloadModule = getModule("payload");
      var form = resolveForm();

      if (payloadModule && typeof payloadModule.getDefinitionVariants === "function") {
        return payloadModule.getDefinitionVariants(form);
      }

      var variantState = getModule("variantState");

      if (variantState && typeof variantState.getVariants === "function") {
        return variantState.getVariants();
      }

      return [];
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("getDefinitionVariants failed.", error);
      return [];
    }
  }

  function getDefinitionVariantsJson() {
    try {
      var payloadModule = getModule("payload");
      var form = resolveForm();

      if (payloadModule && typeof payloadModule.getDefinitionVariantsJson === "function") {
        return payloadModule.getDefinitionVariantsJson(form);
      }

      return JSON.stringify(getDefinitionVariants());
    } catch (error) {
      return "[]";
    }
  }

  function getUploadMetadata() {
    try {
      var payloadModule = getModule("payload");
      var uploadsModule = getModule("uploads");
      var form = resolveForm();

      if (payloadModule && typeof payloadModule.getUploadMetadata === "function") {
        return payloadModule.getUploadMetadata(form, {
          source: "public-api"
        });
      }

      if (uploadsModule && typeof uploadsModule.getSummary === "function") {
        return uploadsModule.getSummary(form || document);
      }

      return {
        byKind: {},
        summary: {
          fileCount: 0,
          errorCount: 0,
          ok: true
        }
      };
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("getUploadMetadata failed.", error);

      return {
        byKind: {},
        summary: {
          fileCount: 0,
          errorCount: 1,
          ok: false
        },
        error: normalizeError(error)
      };
    }
  }

  function refresh(options) {
    try {
      var safeOptions = options || {};
      var core = getCore();
      var form = resolveForm();

      state.refreshCount += 1;
      state.lastRefreshAt = timestamp();

      if (core && typeof core.refreshContext === "function") {
        core.refreshContext();
      }

      callModule("theme", "updateControls");

      if (!safeOptions.light) {
        callModule("uploads", "initialize", form || document);
        callModule("uploads", "syncAll", form || document, {
          source: safeOptions.source || "public-api",
          silent: true,
          emitEvents: false
        });

        callModule("preview", "refresh", {
          source: safeOptions.source || "public-api",
          animate: safeOptions.animate === true
        });

        callModule("dynamicRowsLegacy", "reindexAll", form, {
          source: safeOptions.source || "public-api",
          silent: true
        });
      } else {
        refreshLight(Object.assign({}, safeOptions, {
          nested: true
        }));
      }

      callModule("payload", "ensureDefinitionVariantHiddenFields", form);
      callModule("payload", "ensureUploadHiddenFields", form);
      callModule("payload", "syncProfileIdsIntoForm", form, {
        source: safeOptions.source || "public-api"
      });
      callModule("payload", "syncVariantRuntimeToForm", form, {
        source: safeOptions.source || "public-api"
      });
      callModule("payload", "syncUploadsRuntimeToForm", form, {
        source: safeOptions.source || "public-api",
        skipRuntimeSync: true,
        emitEvents: false
      });

      callModule("actions", "enforceStaticDisabledButtons", form);
      callModule("wizard", "update");

      if (!safeOptions.silent) {
        setStatus("Create Runtime aktualisiert.", "ok");
      }

      dispatch("vectoplan:create:refreshed", getState());

      return getState();
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("refresh failed.", error);
      return getState();
    }
  }

  function refreshLight(options) {
    try {
      var safeOptions = options || {};
      var form = resolveForm();

      if (!safeOptions.nested) {
        state.lightRefreshCount += 1;
        state.lastLightRefreshAt = timestamp();
      }

      callModule("preview", "updatePreview", form, {
        source: safeOptions.source || "public-api",
        animate: false
      });

      callModule("uploads", "syncAll", form || document, {
        source: safeOptions.source || "public-api-light",
        silent: true,
        emitEvents: false
      });

      callModule("payload", "syncVariantRuntimeToForm", form, {
        source: safeOptions.source || "public-api-light"
      });

      callModule("payload", "syncUploadsRuntimeToForm", form, {
        source: safeOptions.source || "public-api-light",
        skipRuntimeSync: true,
        emitEvents: false
      });

      callModule("actions", "enforceStaticDisabledButtons", form);

      if (!safeOptions.silent) {
        setStatus("Create Runtime aktualisiert.", "ok");
      }

      dispatch("vectoplan:create:light-refreshed", getState());

      return getState();
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("refreshLight failed.", error);
      return getState();
    }
  }

  function scheduleRefresh(options) {
    try {
      var safeOptions = options || {};

      if (state.pendingRefreshTimer) {
        window.clearTimeout(state.pendingRefreshTimer);
      }

      state.pendingRefreshTimer = window.setTimeout(function () {
        try {
          state.pendingRefreshTimer = null;

          if (safeOptions.light) {
            refreshLight(safeOptions);
          } else {
            refresh(safeOptions);
          }
        } catch (error) {
          warn("Scheduled refresh failed.", error);
        }
      }, REFRESH_DEBOUNCE_MS);
    } catch (error) {
      warn("scheduleRefresh failed.", error);
    }
  }

  function getState() {
    try {
      var core = getCore();

      return {
        version: CREATE_VERSION,
        initialized: state.initialized,
        ready: state.ready,
        degraded: state.degraded,
        publicApiExposed: state.publicApiExposed,
        bootAttempts: state.bootAttempts,
        bootStartedAt: state.bootStartedAt,
        bootFinishedAt: state.bootFinishedAt,
        lastRefreshAt: state.lastRefreshAt,
        lastLightRefreshAt: state.lastLightRefreshAt,
        refreshCount: state.refreshCount,
        lightRefreshCount: state.lightRefreshCount,
        actionCount: state.actionCount,
        payloadCollectCount: state.payloadCollectCount,
        variantSyncCount: state.variantSyncCount,
        uploadSyncCount: state.uploadSyncCount,
        finalSubmitCount: state.finalSubmitCount,
        lastError: state.lastError,
        writeEnabled: core && typeof core.isWriteEnabled === "function" ? core.isWriteEnabled() : false,
        theme: getTheme(),
        wizard: getWizardState(),
        modules: getModulesState(),
        context: {
          createContextReady: hasCreateContext(),
          generatorContextReady: hasGeneratorContext(),
          payloadContractReady: hasPayloadContract(),
          routes: getRoutes()
        },
        core: core && typeof core.snapshot === "function" ? core.snapshot() : null
      };
    } catch (error) {
      return {
        version: CREATE_VERSION,
        initialized: state.initialized,
        ready: state.ready,
        state_error: String(error && error.message ? error.message : error)
      };
    }
  }

  function getModulesState() {
    try {
      var result = {};

      Object.keys(MODULES).forEach(function (key) {
        var moduleApi = getModule(key);
        var status = state.moduleStatus[key] || {
          key: key,
          globalName: MODULES[key],
          present: !!moduleApi,
          initialized: !!moduleApi,
          error: ""
        };

        result[key] = {
          key: key,
          globalName: MODULES[key],
          present: !!moduleApi,
          initialized: !!moduleApi && status.initialized !== false,
          error: status.error || "",
          state: moduleApi && typeof moduleApi.getState === "function" ? safeGetModuleState(moduleApi) : null
        };
      });

      return result;
    } catch (error) {
      return {
        modules_error: String(error && error.message ? error.message : error)
      };
    }
  }

  function safeGetModuleState(moduleApi) {
    try {
      return moduleApi.getState();
    } catch (error) {
      return {
        state_error: String(error && error.message ? error.message : error)
      };
    }
  }

  function getWizardState() {
    try {
      var wizardModule = getModule("wizard");

      if (wizardModule && typeof wizardModule.getState === "function") {
        return wizardModule.getState();
      }

      var core = getCore();

      if (core && core.state) {
        return {
          currentStep: core.state.currentStep,
          stepCount: core.state.stepCount,
          maxReachedStep: core.state.maxReachedStep,
          steps: core.state.steps
        };
      }

      return {
        currentStep: 1,
        stepCount: 0,
        maxReachedStep: 1,
        steps: []
      };
    } catch (error) {
      return {
        wizard_error: String(error && error.message ? error.message : error)
      };
    }
  }

  function getCurrentStep() {
    try {
      var wizardState = getWizardState();
      var parsed = parseInt(wizardState.currentStep || 1, 10);

      return Number.isFinite(parsed) ? parsed : 1;
    } catch (error) {
      return 1;
    }
  }

  function getTheme() {
    try {
      var themeModule = getModule("theme");

      if (themeModule && typeof themeModule.getTheme === "function") {
        return themeModule.getTheme();
      }

      var core = getCore();

      if (core && core.state && core.state.theme) {
        return core.state.theme;
      }

      return document.documentElement.getAttribute("data-vp-create-theme") ||
        document.documentElement.getAttribute("data-vp-theme") ||
        document.documentElement.getAttribute("data-theme") ||
        "dark";
    } catch (error) {
      return "dark";
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

  function getRoutes() {
    try {
      var context = getCreateContext();
      var core = getCore();

      return Object.assign(
        {},
        core && core.state && core.state.routes ? core.state.routes : {},
        context.routes || {},
        window.VectoplanCreateRoutes || {}
      );
    } catch (error) {
      return {};
    }
  }

  function hasCreateContext() {
    try {
      return !!Object.keys(getCreateContext()).length;
    } catch (error) {
      return false;
    }
  }

  function hasGeneratorContext() {
    try {
      return !!Object.keys(getGeneratorContext()).length;
    } catch (error) {
      return false;
    }
  }

  function hasPayloadContract() {
    try {
      return !!Object.keys(getPayloadContract()).length;
    } catch (error) {
      return false;
    }
  }

  function getModule(key) {
    try {
      var globalName = MODULES[key] || key;

      if (!globalName) {
        return null;
      }

      return window[globalName] || null;
    } catch (error) {
      return null;
    }
  }

  function getCore() {
    try {
      return window[CORE_NAME] || null;
    } catch (error) {
      return null;
    }
  }

  function callModule(moduleKey, methodName) {
    try {
      var moduleApi = getModule(moduleKey);

      if (!moduleApi || typeof moduleApi[methodName] !== "function") {
        return undefined;
      }

      var args = Array.prototype.slice.call(arguments, 2);
      return moduleApi[methodName].apply(moduleApi, args);
    } catch (error) {
      warn("Module call failed: " + moduleKey + "." + methodName, error);
      return undefined;
    }
  }

  function resolveForm() {
    try {
      var core = getCore();

      if (core && typeof core.qs === "function" && core.selectors) {
        return core.qs(core.selectors.form);
      }

      return document.querySelector("[data-vp-create-form], [data-create-form='true'], #vp-create-form, form[data-create-form]");
    } catch (error) {
      return null;
    }
  }

  function collectPayloadFallback(form) {
    try {
      var safeForm = form || resolveForm();
      var payload = {};

      if (!safeForm || typeof FormData === "undefined") {
        return payload;
      }

      var formData = new FormData(safeForm);

      formData.forEach(function (value, key) {
        try {
          if (isFileValue(value)) {
            if (value.name) {
              assignPayloadValue(payload, key, {
                name: value.name,
                size: value.size,
                type: value.type || "",
                extension: extensionFromName(value.name || ""),
                last_modified: value.lastModified || null,
                backend_stored: false,
                local_only: true
              });
            }

            return;
          }

          assignPayloadValue(payload, key, value);
        } catch (entryError) {
          warn("Fallback payload entry skipped: " + key, entryError);
        }
      });

      if (!payload.definition_variants_json) {
        payload.definition_variants_json = "[]";
      }

      if (!payload.default_variant_id) {
        payload.default_variant_id = "default";
      }

      if (!payload.geometry_model_uploads_json) {
        payload.geometry_model_uploads_json = emptyUploadJson("geometry_model");
      }

      if (!payload.technical_document_uploads_json) {
        payload.technical_document_uploads_json = emptyUploadJson("technical_documents");
      }

      if (!payload.variant_document_uploads_json) {
        payload.variant_document_uploads_json = emptyUploadJson("variant_documents");
      }

      if (!payload.domain) {
        payload.domain = "hochbau";
      }

      if (!payload.category) {
        payload.category = "bloecke";
      }

      if (!payload.subcategory) {
        payload.subcategory = "basis";
      }

      if (!payload.taxonomy_path) {
        payload.taxonomy_path = [payload.domain, payload.category, payload.subcategory].join("/");
      }

      if (!payload.object_kind) {
        payload.object_kind = "cell_block";
      }

      return payload;
    } catch (error) {
      warn("collectPayloadFallback failed.", error);
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
      warn("assignPayloadValue failed.", error);
    }
  }

  function isFileValue(value) {
    try {
      return typeof File !== "undefined" && value instanceof File;
    } catch (error) {
      return false;
    }
  }

  function extensionFromName(fileName) {
    try {
      var text = String(fileName || "");

      if (text.indexOf(".") < 0) {
        return "";
      }

      return text.split(".").pop().toLowerCase();
    } catch (error) {
      return "";
    }
  }

  function emptyUploadJson(kind) {
    try {
      return JSON.stringify({
        version: CREATE_VERSION,
        kind: kind || "generic_upload",
        backend_enabled: true,
        backendEnabled: true,
        local_only: true,
        localOnly: true,
        count: 0,
        files: [],
        errors: [],
        ok: true,
        source: "orchestrator_fallback",
        updated_at: timestamp(),
        updatedAt: timestamp()
      });
    } catch (error) {
      return '{"count":0,"files":[]}';
    }
  }

  function normalizeAction(action) {
    try {
      var text = String(action || "").trim();

      if (!text) {
        return "";
      }

      return ACTION_ALIASES[text] || ACTION_ALIASES[text.replace(/-/g, "_")] || text.replace(/_/g, "-");
    } catch (error) {
      return String(action || "");
    }
  }

  function setStatus(message, status) {
    try {
      var core = getCore();

      if (core && typeof core.setStatus === "function") {
        core.setStatus(message, status);
      }
    } catch (error) {
      warn("setStatus failed.", error);
    }
  }

  function dispatch(eventName, detail) {
    try {
      var core = getCore();

      if (core && typeof core.dispatch === "function") {
        return core.dispatch(eventName, detail || {});
      }

      document.dispatchEvent(new CustomEvent(eventName, {
        bubbles: true,
        cancelable: false,
        detail: detail || {}
      }));

      return null;
    } catch (error) {
      warn("dispatch failed: " + eventName, error);
      return null;
    }
  }

  function bindOnce(key, callback) {
    try {
      var core = getCore();

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
      warn("bindOnce failed: " + key, error);
    }
  }

  function markRuntimeReady(isReady) {
    try {
      state.ready = !!isReady;
      safeSetRootAttribute("data-vp-create-runtime-ready", isReady ? "true" : "false");
      safeSetRootAttribute("data-vp-create-orchestrator-ready", isReady ? "true" : "false");
      safeSetRootAttribute("data-vp-create-version", CREATE_VERSION);
      safeSetRootAttribute("data-vp-create-orchestrator-version", CREATE_VERSION);
    } catch (error) {
      /* no-op */
    }
  }

  function safeSetRootAttribute(name, value) {
    try {
      document.documentElement.setAttribute(name, String(value));
    } catch (error) {
      /* no-op */
    }
  }

  function timestamp() {
    try {
      return new Date().toISOString();
    } catch (error) {
      return "";
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

  function log(message, payload) {
    try {
      var core = getCore();

      if (core && typeof core.log === "function") {
        core.log(message, payload);
        return;
      }

      if (window.console && typeof window.console.log === "function") {
        if (typeof payload !== "undefined") {
          window.console.log("[VPLIB Create] " + message, payload);
        } else {
          window.console.log("[VPLIB Create] " + message);
        }
      }
    } catch (error) {
      /* no-op */
    }
  }

  function warn(message, error) {
    try {
      var core = getCore();

      if (core && typeof core.warn === "function") {
        core.warn(message, error);
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
          window.console.warn("[VPLIB Create] " + message, error);
        } else {
          window.console.warn("[VPLIB Create] " + message);
        }
      }
    } catch (consoleError) {
      /* no-op */
    }
  }

  function exposePublicApi() {
    try {
      window[GLOBAL_NAME] = api;
      state.publicApiExposed = true;

      return api;
    } catch (error) {
      fallbackWarn("Expose public API failed.", error);
      return api;
    }
  }
})();