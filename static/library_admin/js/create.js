/* services/vectoplan-library/static/library_admin/js/create.js */

/* -----------------------------------------------------------------------------
  VECTOPLAN Library · VPLIB Create Orchestrator

  Zweck:
  - Schlanker Orchestrator für /create.
  - Ersetzt die alte große create.js.
  - Initialisiert und verbindet die neuen Teilmodule.
  - Stellt die stabile öffentliche API window.VectoplanCreate bereit.
  - Enthält keine große Fachlogik mehr.
  - Delegiert Wizard, Payload, Actions, Preview, Theme und Legacy-Rows an Module.
  - Verhindert, dass Legacy-Code wieder direkte Step-Sprünge auslöst.

  Erwartete Moduldateien:
  - create_core.js
  - create_theme.js
  - create_wizard.js
  - create_preview.js
  - create_dynamic_rows_legacy.js
  - create_payload.js
  - create_actions.js

  Empfohlene spätere Ladereihenfolge im Template:
  1. create_core.js
  2. create_theme.js
  3. create_wizard.js
  4. create_preview.js
  5. create_dynamic_rows_legacy.js
  6. create_payload.js
  7. create_actions.js
  8. create_variant_utils.js
  9. create_variant_state.js
  10. create_variant_profiles.js
  11. create_variant_summary.js
  12. create_variant_field_renderer.js
  13. create_variant_optional_fields.js
  14. create_variant_validation.js
  15. create_variant_drawer.js
  16. create_variant_table.js
  17. create_definitions.js
  18. create.js

  Öffentliche API:
  - window.VectoplanCreate.getState()
  - window.VectoplanCreate.collectPayload()
  - window.VectoplanCreate.runAction("draft" | "validate" | "package-plan" | "download" | "save")
  - window.VectoplanCreate.goToStep(1..6)
  - window.VectoplanCreate.nextStep()
  - window.VectoplanCreate.prevStep()
  - window.VectoplanCreate.previousStep()
  - window.VectoplanCreate.setTheme("dark" | "light" | "system")
  - window.VectoplanCreate.cycleTheme()
  - window.VectoplanCreate.updatePreview()
  - window.VectoplanCreate.refresh()
  - window.VectoplanCreate.syncVariants()
  - window.VectoplanCreate.getDefinitionVariants()
----------------------------------------------------------------------------- */

(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreate";
  var CREATE_VERSION = "0.4.0";
  var CORE_NAME = "VectoplanCreateCore";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 100;

  var MODULES = {
    core: "VectoplanCreateCore",
    theme: "VectoplanCreateTheme",
    wizard: "VectoplanCreateWizard",
    preview: "VectoplanCreatePreview",
    dynamicRowsLegacy: "VectoplanCreateDynamicRowsLegacy",
    payload: "VectoplanCreatePayload",
    actions: "VectoplanCreateActions",

    variantUtils: "VectoplanCreateVariantUtils",
    variantState: "VectoplanCreateVariantState",
    variantProfiles: "VectoplanCreateVariantProfiles",
    variantSummary: "VectoplanCreateVariantSummary",
    variantFieldRenderer: "VectoplanCreateVariantFieldRenderer",
    variantOptionalFields: "VectoplanCreateVariantOptionalFields",
    variantValidation: "VectoplanCreateVariantValidation",
    variantDrawer: "VectoplanCreateVariantDrawer",
    variantTable: "VectoplanCreateVariantTable",

    definitionsRuntime: "VectoplanCreateDefinitionsRuntime"
  };

  var INIT_ORDER = [
    "core",
    "theme",
    "wizard",
    "preview",
    "dynamicRowsLegacy",
    "payload",
    "actions",
    "variantState",
    "variantProfiles",
    "variantSummary",
    "variantFieldRenderer",
    "variantOptionalFields",
    "variantValidation",
    "variantDrawer",
    "variantTable",
    "definitionsRuntime"
  ];

  var state = {
    version: CREATE_VERSION,
    initialized: false,
    ready: false,
    bootAttempts: 0,
    bootStartedAt: "",
    bootFinishedAt: "",
    lastRefreshAt: "",
    lastError: null,
    moduleStatus: {},
    publicApiExposed: false,
    refreshCount: 0,
    actionCount: 0,
    payloadCollectCount: 0,
    variantSyncCount: 0
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
        fallbackWarn("Core runtime missing; create orchestrator initialized in degraded mode.");
        markRuntimeReady(false);
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
      state.bootFinishedAt = timestamp();

      safeSetRootAttribute("data-vp-create-runtime-ready", "true");
      safeSetRootAttribute("data-vp-create-version", CREATE_VERSION);
      safeSetRootAttribute("data-vp-create-orchestrator-ready", "true");
      safeSetRootAttribute("data-vp-create-orchestrator-version", CREATE_VERSION);

      dispatch("vectoplan:create:ready", getState());

      log("Create orchestrator ready.", getState());

      return api;
    } catch (error) {
      state.initialized = false;
      state.ready = false;
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

          if (moduleApi && typeof moduleApi.initialize === "function") {
            try {
              moduleApi.initialize(getCore());
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

  function wireCompatibilityEvents() {
    try {
      var core = getCore();

      if (!core || typeof core.bindOnce !== "function") {
        return;
      }

      core.bindOnce("create-orchestrator-profile-context-sync", function () {
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

      core.bindOnce("create-orchestrator-step-changed-refresh", function () {
        document.addEventListener("vectoplan:create:step-changed", function () {
          try {
            refresh({
              source: "step-changed",
              silent: true,
              light: true
            });
          } catch (error) {
            warn("Refresh after step change failed.", error);
          }
        });
      });

      core.bindOnce("create-orchestrator-variant-state-sync", function () {
        document.addEventListener("vectoplan:create:variant-state-changed", function () {
          try {
            syncVariants({
              source: "variant-state-changed"
            });
          } catch (error) {
            warn("Variant state changed sync failed.", error);
          }
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
          source: "public-api"
        }, options || {}));
      }

      return collectPayloadFallback(form);
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("collectPayload failed.", error);
      return {};
    }
  }

  function runAction(action) {
    try {
      state.actionCount += 1;

      var actionsModule = getModule("actions");
      var form = resolveForm();

      if (actionsModule && typeof actionsModule.runAction === "function") {
        return actionsModule.runAction(action, form, null);
      }

      var result = {
        ok: false,
        status: "actions_runtime_missing",
        action: action,
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
        core.state.theme = normalized;
        return normalized;
      }

      return "system";
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("setTheme failed.", error);
      return "system";
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

      var current = getTheme();
      var next = current === "system" ? "dark" : current === "dark" ? "light" : "system";
      return setTheme(next, options || {});
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

  function refresh(options) {
    try {
      var safeOptions = options || {};
      var core = getCore();

      state.refreshCount += 1;
      state.lastRefreshAt = timestamp();

      if (core && typeof core.refreshContext === "function") {
        core.refreshContext();
      }

      callModule("theme", "updateControls");

      if (!safeOptions.light) {
        callModule("preview", "refresh", {
          source: safeOptions.source || "public-api",
          animate: safeOptions.animate === true
        });

        callModule("dynamicRowsLegacy", "reindexAll", resolveForm(), {
          source: safeOptions.source || "public-api",
          silent: true
        });
      } else {
        callModule("preview", "updatePreview", resolveForm(), {
          source: safeOptions.source || "public-api",
          animate: false
        });
      }

      callModule("payload", "ensureDefinitionVariantHiddenFields", resolveForm());
      callModule("payload", "syncProfileIdsIntoForm", resolveForm());
      callModule("payload", "syncVariantRuntimeToForm", resolveForm(), {
        source: safeOptions.source || "public-api"
      });

      callModule("actions", "enforceStaticDisabledButtons", resolveForm());
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

  function getState() {
    try {
      var core = getCore();

      return {
        version: CREATE_VERSION,
        initialized: state.initialized,
        ready: state.ready,
        publicApiExposed: state.publicApiExposed,
        bootAttempts: state.bootAttempts,
        bootStartedAt: state.bootStartedAt,
        bootFinishedAt: state.bootFinishedAt,
        lastRefreshAt: state.lastRefreshAt,
        refreshCount: state.refreshCount,
        actionCount: state.actionCount,
        payloadCollectCount: state.payloadCollectCount,
        variantSyncCount: state.variantSyncCount,
        lastError: state.lastError,
        writeEnabled: core && typeof core.isWriteEnabled === "function" ? core.isWriteEnabled() : false,
        theme: getTheme(),
        wizard: getWizardState(),
        modules: getModulesState(),
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

      return document.documentElement.getAttribute("data-theme") || "system";
    } catch (error) {
      return "system";
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

      return document.querySelector("[data-vp-create-form], [data-create-form='true'], #vp-create-form");
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
          warn("Fallback payload entry skipped: " + key, entryError);
        }
      });

      if (!payload.definition_variants_json) {
        payload.definition_variants_json = "[]";
      }

      if (!payload.default_variant_id) {
        payload.default_variant_id = "default";
      }

      return payload;
    } catch (error) {
      warn("collectPayloadFallback failed.", error);
      return {};
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

  function markRuntimeReady(isReady) {
    try {
      state.ready = !!isReady;
      safeSetRootAttribute("data-vp-create-runtime-ready", isReady ? "true" : "false");
      safeSetRootAttribute("data-vp-create-orchestrator-ready", isReady ? "true" : "false");
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
      if (state.publicApiExposed && window[GLOBAL_NAME]) {
        return window[GLOBAL_NAME];
      }

      window[GLOBAL_NAME] = api;
      state.publicApiExposed = true;

      return api;
    } catch (error) {
      fallbackWarn("Expose public API failed.", error);
      return api;
    }
  }

  var api = {
    version: CREATE_VERSION,

    initialize: initialize,
    refresh: refresh,

    getState: getState,
    getModulesState: getModulesState,
    getModule: getModule,

    collectPayload: collectPayload,
    collectFormPayload: collectPayload,

    runAction: runAction,

    goToStep: goToStep,
    nextStep: nextStep,
    prevStep: previousStep,
    previousStep: previousStep,

    setTheme: setTheme,
    cycleTheme: cycleTheme,

    updatePreview: updatePreview,

    syncVariants: syncVariants,
    syncVariantRuntimeToForm: syncVariants,
    getDefinitionVariants: getDefinitionVariants,
    getDefinitionVariantsJson: getDefinitionVariantsJson,

    getCurrentStep: getCurrentStep,
    getTheme: getTheme
  };
})();