/* services/vectoplan-library/static/library_admin/js/create_core.js */

/* -----------------------------------------------------------------------------
  VECTOPLAN Library · VPLIB Create Core Runtime

  Zweck:
  - Gemeinsame Basisschicht für den /create Fullscreen-Wizard.
  - Entlastet die bisher zu große create.js.
  - Stellt zentrale Konstanten, Selektoren, State, Utility-Funktionen,
    Kontextauflösung, Logging, Locking, Events und robuste DOM-Helfer bereit.
  - Enthält bewusst keine fachliche Wizard-Navigation, keine Actions,
    keine Preview-Logik und keine VPLIB-Erzeugung.
  - Die Datei darf mehrfach geladen werden, ohne bestehende Runtime hart zu brechen.

  Geplante Modulaufteilung:
  - create_core.js                 diese Basisschicht
  - create_wizard.js               Schrittlogik, Navigation, Reentrancy-Schutz
  - create_payload.js              Form-/Variant-Payload-Brücke
  - create_actions.js              Draft, Validate, Package-Plan, Download, Save
  - create_preview.js              Taxonomie/Object-Kind/Preview/UI-Summaries
  - create_dynamic_rows_legacy.js  Legacy-Tabellenkompatibilität
  - create.js                      schlanker Orchestrator/Public API

  Architekturregeln:
  - Backend bleibt Source of Truth.
  - Browser erzeugt keine VPLIB-Dateien.
  - Variant Runtime bleibt definition-managed.
  - Navigation wird später ausschließlich in create_wizard.js gesteuert.
----------------------------------------------------------------------------- */

(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateCore";
  var CORE_VERSION = "0.4.0";
  var DEFAULT_API_PREFIX = "/api/v1/vplib/create";
  var DEFAULT_THEME_STORAGE_KEY = "vectoplan.create.theme";
  var DEFAULT_LOCK_TIMEOUT_MS = 2500;

  if (window[GLOBAL_NAME] && window[GLOBAL_NAME].version) {
    try {
      window[GLOBAL_NAME].log("create_core.js already initialized; keeping existing runtime.", {
        existingVersion: window[GLOBAL_NAME].version,
        incomingVersion: CORE_VERSION
      });
    } catch (error) {
      /* no-op */
    }

    return;
  }

  var SELECTORS = {
    page: "[data-create-page='true'], [data-vp-create-page='true']",
    app: "[data-vp-create-app]",
    form: "[data-vp-create-form], [data-create-form='true'], #vp-create-form",

    stepper: "[data-vp-create-stepper]",
    stepperButton: "[data-vp-step-button]",
    stepperItem: "[data-vp-step-item]",
    stepperProgressFill: "[data-vp-step-progress-fill]",
    stepperCurrentLabel: "[data-vp-current-step-label]",
    stepperTotalLabel: "[data-vp-total-step-label]",
    stepperLiveRegion: "[data-vp-step-live-region]",

    wizardNav: "[data-vp-wizard-nav]",
    wizardPrev: "[data-vp-wizard-prev]",
    wizardNext: "[data-vp-wizard-next]",
    wizardNextLabel: "[data-vp-wizard-next-label]",
    wizardProgressText: "[data-vp-wizard-progress-text]",
    wizardStepLabel: "[data-vp-wizard-step-label]",
    wizardHint: "[data-vp-wizard-hint]",

    stepsRoot: "[data-vp-create-steps]",
    step: "[data-vp-create-step]",
    activeStep: "[data-vp-create-step].is-active",

    actionSection: "[data-vp-create-section='actions'], [data-create-actions-card='true']",
    actionButton: "[data-create-action]",
    status: "[data-vp-action-status], [data-create-action-status='true']",

    resultOutput: "[data-vp-actions-result-output], [data-create-result-output='true'], [data-create-output='true']",
    resultCode: "[data-vp-actions-result-code]",
    resultSummary: "[data-vp-actions-result-summary], [data-create-result-summary='true']",
    resultCopy: "[data-vp-actions-result-copy], [data-create-copy-result='true'], [data-create-result-copy='true']",
    resultClear: "[data-vp-actions-result-clear], [data-create-clear-result='true'], [data-create-result-clear='true']",
    resultLastAction: "[data-create-result-last-action='true']",
    resultStatus: "[data-create-result-status='true']",
    resultHttpStatus: "[data-create-result-http-status='true']",
    resultErrorCount: "[data-create-result-error-count='true']",
    resultWarningCount: "[data-create-result-warning-count='true']",

    addVariant: "[data-create-add-variant='true']",
    addVariable: "[data-create-add-variable='true']",
    removeRow: "[data-create-remove-row='true']",
    clearVariable: "[data-create-clear-variable='true']",

    variantTable: "[data-create-variant-table='true']",
    variantRow: "[data-create-variant-row='true']",
    variantTemplate: "[data-create-variant-row-template='true']",

    variableTable: "[data-create-variable-table='true']",
    variableRow: "[data-create-variable-row='true']",
    variableTemplate: "[data-create-variable-row-template='true']",

    domainSelect: "[data-create-taxonomy-select='domain']",
    categorySelect: "[data-create-taxonomy-select='category']",
    subcategorySelect: "[data-create-taxonomy-select='subcategory']",
    taxonomyPathDomain: "[data-vp-taxonomy-path-domain]",
    taxonomyPathCategory: "[data-vp-taxonomy-path-category]",
    taxonomyPathFamily: "[data-vp-taxonomy-path-family]",
    taxonomyLegacyPath: "[data-create-taxonomy-path-value='true']",

    objectKindSelect: "[data-create-object-kind='true'], [name='object_kind']",
    objectKindNote: "[data-create-object-kind-note='true'], [data-vp-object-kind-note]",
    objectKindNoteLabel: "[data-create-object-kind-note-label='true']",
    objectKindNoteText: "[data-create-object-kind-note-text='true']",

    primitiveShapeSelect: "[data-create-field='primitive_shape'], [name='primitive_shape']",
    geometryUnit: "[data-create-field='geometry_unit'], [name='geometry_unit']",
    geometryWidth: "[data-create-field='geometry_width'], [name='geometry_width']",
    geometryHeight: "[data-create-field='geometry_height'], [name='geometry_height']",
    geometryDepth: "[data-create-field='geometry_depth'], [name='geometry_depth']",
    editorCellsX: "[data-create-field='editor_cells_x'], [name='editor_cells_x']",
    editorCellsY: "[data-create-field='editor_cells_y'], [name='editor_cells_y']",
    editorCellsZ: "[data-create-field='editor_cells_z'], [name='editor_cells_z']",

    previewPlaceholder: "[data-vp-create-preview], [data-create-preview-placeholder='true']",
    previewStage: "[data-vp-preview-stage], [data-create-preview-stage='true']",
    previewCube: "[data-vp-preview-primitive], [data-create-preview-cube='true']",
    previewShape: "[data-vp-preview-shape], [data-create-preview-shape='true']",
    previewObjectKind: "[data-vp-preview-object-kind], [data-create-preview-object-kind='true']",
    previewDimensions: "[data-vp-preview-dimensions], [data-create-preview-dimensions='true']",
    previewCells: "[data-vp-preview-cells], [data-create-preview-cells='true']",

    geometryVisibleSummary: "[data-vp-geometry-visible-summary], [data-create-geometry-visible-summary='true']",
    geometryCellsSummary: "[data-vp-geometry-cells-summary], [data-create-geometry-cells-summary='true']",

    variantCountLabel: "[data-vp-variant-count-label]",
    variableCountLabel: "[data-vp-variable-count-label]",

    themeToggle: "[data-create-theme-toggle='true']",
    themeLabel: "[data-create-theme-label='true']",

    contextJson: "[data-create-context-json='true'], #vp-create-context-json",
    optionsJson: "[data-create-options-json='true'], #vp-create-options-json",
    healthJson: "[data-create-health-json='true'], #vp-create-health-json",
    uiStateJson: "[data-create-ui-state-json='true'], #vp-create-ui-state-json",
    wizardJson: "[data-create-wizard-json='true'], #vp-create-wizard-json"
  };

  var STATE_CLASSES = {
    loading: "is-loading",
    ok: "is-ok",
    warning: "is-warning",
    error: "is-error",
    invalid: "is-invalid",
    valid: "is-valid",
    updated: "is-updated",
    copied: "is-copied",
    cleared: "is-cleared",
    active: "is-active",
    hidden: "is-hidden",
    complete: "is-complete",
    locked: "is-locked",
    running: "is-running",
    disabled: "is-disabled"
  };

  var PREVIEW_SHAPE_CLASSES = [
    "vp-create-preview-cube--block",
    "vp-create-preview-cube--box",
    "vp-create-preview-cube--cuboid",
    "vp-create-preview-cube--rectangular_prism",
    "vp-create-preview-cube--cube",
    "vp-create-preview-cube--wall",
    "vp-create-preview-cube--wall_block",
    "vp-create-preview-cube--slab",
    "vp-create-preview-cube--plate",
    "vp-create-preview-cube--cylinder",
    "vp-create-preview-cube--pipe",
    "vp-create-preview-cube--sphere"
  ];

  var DEFAULT_STEPS = [
    {
      index: 1,
      key: "identity",
      label: "Grunddaten",
      short_label: "Daten",
      hint: "Name und Beschreibung des neuen Library-Bausteins festlegen.",
      target: "identity"
    },
    {
      index: 2,
      key: "taxonomy",
      label: "Taxonomie",
      short_label: "Taxonomie",
      hint: "Fachliche Einordnung auswählen.",
      target: "taxonomy"
    },
    {
      index: 3,
      key: "object",
      label: "Objekt",
      short_label: "Objekt",
      hint: "Objektklasse und Varianten festlegen.",
      target: "object-variants"
    },
    {
      index: 4,
      key: "geometry",
      label: "Geometrie",
      short_label: "Geometrie",
      hint: "Form, Maße und Editor-Raster definieren.",
      target: "geometry"
    },
    {
      index: 5,
      key: "technical",
      label: "Technik",
      short_label: "Technik",
      hint: "Optionale technische Kennwerte ergänzen.",
      target: "technical"
    },
    {
      index: 6,
      key: "create",
      label: "Erzeugen",
      short_label: "Erzeugen",
      hint: "Draft, Validierung, Package-Plan, Download oder Save ausführen.",
      target: "actions"
    }
  ];

  var state = {
    initialized: false,
    coreReady: false,
    domReady: false,

    version: CORE_VERSION,
    apiPrefix: DEFAULT_API_PREFIX,
    themeStorageKey: DEFAULT_THEME_STORAGE_KEY,

    context: {},
    options: {},
    health: {},
    uiState: {},
    wizard: {},

    steps: clone(DEFAULT_STEPS),
    currentStep: 1,
    stepCount: DEFAULT_STEPS.length,
    maxReachedStep: 1,
    allowDirectStepClick: true,
    lockFutureSteps: false,

    pending: false,
    lastResult: null,
    lastAction: "",
    lastError: null,

    variantIndex: 1,
    variableIndex: 1,

    theme: "system",
    previewUpdateTimer: null,

    locks: {},
    modules: {},
    moduleOrder: [],
    bindings: {},
    diagnostics: [],
    navigationTrace: []
  };

  function nowIso() {
    try {
      return new Date().toISOString();
    } catch (error) {
      return "";
    }
  }

  function log(message, payload) {
    try {
      if (window.console && typeof window.console.log === "function") {
        if (typeof payload !== "undefined") {
          window.console.log("[VPLIB Create Core] " + message, payload);
        } else {
          window.console.log("[VPLIB Create Core] " + message);
        }
      }
    } catch (error) {
      /* no-op */
    }
  }

  function info(message, payload) {
    try {
      if (window.console && typeof window.console.info === "function") {
        if (typeof payload !== "undefined") {
          window.console.info("[VPLIB Create Core] " + message, payload);
        } else {
          window.console.info("[VPLIB Create Core] " + message);
        }
      }
    } catch (error) {
      /* no-op */
    }
  }

  function warn(message, error) {
    try {
      if (window.console && typeof window.console.warn === "function") {
        if (typeof error !== "undefined") {
          window.console.warn("[VPLIB Create Core] " + message, error);
        } else {
          window.console.warn("[VPLIB Create Core] " + message);
        }
      }
    } catch (consoleError) {
      /* no-op */
    }

    pushDiagnostic("warning", message, error);
  }

  function error(message, err) {
    try {
      if (window.console && typeof window.console.error === "function") {
        if (typeof err !== "undefined") {
          window.console.error("[VPLIB Create Core] " + message, err);
        } else {
          window.console.error("[VPLIB Create Core] " + message);
        }
      }
    } catch (consoleError) {
      /* no-op */
    }

    pushDiagnostic("error", message, err);
  }

  function pushDiagnostic(level, message, err) {
    try {
      state.diagnostics.push({
        level: level || "info",
        message: String(message || ""),
        error: err && err.message ? String(err.message) : err ? String(err) : "",
        timestamp: nowIso()
      });

      if (state.diagnostics.length > 100) {
        state.diagnostics = state.diagnostics.slice(state.diagnostics.length - 100);
      }
    } catch (diagnosticError) {
      /* no-op */
    }
  }

  function onReady(callback) {
    try {
      if (typeof callback !== "function") {
        return;
      }

      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
          try {
            state.domReady = true;
            callback();
          } catch (callbackError) {
            error("DOM-ready callback failed.", callbackError);
          }
        }, { once: true });
      } else {
        state.domReady = true;
        callback();
      }
    } catch (err) {
      error("DOM-ready binding failed.", err);
    }
  }

  function refreshContext() {
    try {
      var page = qs(SELECTORS.page);
      var app = qs(SELECTORS.app);
      var form = qs(SELECTORS.form);

      state.context = resolveContextBundle("context");
      state.options = resolveContextBundle("options");
      state.health = resolveContextBundle("health");
      state.uiState = resolveContextBundle("uiState");
      state.wizard = resolveContextBundle("wizard");

      state.apiPrefix = resolveApiPrefix(page, app, form, state.context);
      state.themeStorageKey = getNested(
        state.context,
        ["theme", "storage_key"],
        getNested(state.context, ["theme", "storageKey"], DEFAULT_THEME_STORAGE_KEY)
      );

      refreshWizardConfig(app, form);

      state.coreReady = true;

      safeSetAttribute(document.documentElement, "data-vp-create-core-ready", "true");
      safeSetAttribute(document.documentElement, "data-vp-create-core-version", CORE_VERSION);

      dispatch("vectoplan:create:core-context-refreshed", {
        apiPrefix: state.apiPrefix,
        stepCount: state.stepCount,
        currentStep: state.currentStep
      });

      return snapshot();
    } catch (err) {
      state.coreReady = false;
      state.lastError = err;
      error("Context refresh failed.", err);
      return snapshot();
    }
  }

  function refreshWizardConfig(app, form) {
    try {
      var stepsFromContext = getNested(state.context, ["wizard", "steps"], null);
      var stepsFromWizard = state.wizard && Array.isArray(state.wizard.steps) ? state.wizard.steps : null;
      var steps = Array.isArray(stepsFromWizard) && stepsFromWizard.length ? stepsFromWizard : stepsFromContext;

      if (Array.isArray(steps) && steps.length) {
        state.steps = steps.map(normalizeStep).filter(Boolean);
      }

      if (!Array.isArray(state.steps) || !state.steps.length) {
        state.steps = clone(DEFAULT_STEPS);
      }

      state.stepCount = state.steps.length || DEFAULT_STEPS.length;

      var initialStep = getNested(state.uiState, ["current_step"], null) ||
        getNested(state.uiState, ["currentStep"], null) ||
        getNested(state.wizard, ["current_step"], null) ||
        getNested(state.wizard, ["currentStep"], null) ||
        getNested(state.context, ["wizard", "current_step"], null) ||
        getNested(state.context, ["wizard", "currentStep"], null) ||
        getDataInt(qs(SELECTORS.stepsRoot), "data-vp-current-step", 1);

      state.currentStep = clampStep(initialStep || state.currentStep || 1);
      state.maxReachedStep = Math.max(clampStep(state.maxReachedStep || 1), state.currentStep);

      state.allowDirectStepClick = toBoolean(
        getNested(state.context, ["wizard", "allow_direct_step_click"], getNested(state.context, ["wizard", "allowDirectStepClick"], true)),
        true
      );

      state.lockFutureSteps = toBoolean(
        getNested(state.context, ["wizard", "lock_future_steps"], getNested(state.context, ["wizard", "lockFutureSteps"], false)),
        false
      );

      if (app) {
        safeSetAttribute(app, "data-vp-current-step", String(state.currentStep));
        safeSetAttribute(app, "data-vp-step-count", String(state.stepCount));
      }

      if (form) {
        safeSetAttribute(form, "data-vp-current-step", String(state.currentStep));
        safeSetAttribute(form, "data-vp-step-count", String(state.stepCount));
      }
    } catch (err) {
      error("Wizard config refresh failed.", err);
    }
  }

  function resolveContextBundle(name) {
    try {
      if (window.VectoplanCreateContext && typeof window.VectoplanCreateContext === "object") {
        if (name === "context" && window.VectoplanCreateContext.context) {
          return cloneObject(window.VectoplanCreateContext.context);
        }

        if (name === "options" && window.VectoplanCreateContext.options) {
          return cloneObject(window.VectoplanCreateContext.options);
        }

        if (name === "health" && window.VectoplanCreateContext.health) {
          return cloneObject(window.VectoplanCreateContext.health);
        }

        if (name === "uiState" && window.VectoplanCreateContext.uiState) {
          return cloneObject(window.VectoplanCreateContext.uiState);
        }

        if (name === "wizard" && window.VectoplanCreateContext.wizard) {
          return cloneObject(window.VectoplanCreateContext.wizard);
        }
      }

      if (name === "context") {
        return readJsonScript(SELECTORS.contextJson, {});
      }

      if (name === "options") {
        return readJsonScript(SELECTORS.optionsJson, {});
      }

      if (name === "health") {
        return readJsonScript(SELECTORS.healthJson, {});
      }

      if (name === "uiState") {
        return readJsonScript(SELECTORS.uiStateJson, {});
      }

      if (name === "wizard") {
        return readJsonScript(SELECTORS.wizardJson, {});
      }

      return {};
    } catch (err) {
      warn("Context bundle resolution failed: " + name, err);
      return {};
    }
  }

  function resolveApiPrefix(page, app, form, context) {
    try {
      var fromContext = context && (context.api_prefix || context.apiPrefix) || "";
      var fromForm = form ? form.getAttribute("data-create-api-prefix") || "" : "";
      var fromApp = app ? app.getAttribute("data-create-api-prefix") || "" : "";
      var fromPage = page ? page.getAttribute("data-create-api-prefix") || "" : "";

      return trimTrailingSlash(fromContext || fromForm || fromApp || fromPage || DEFAULT_API_PREFIX);
    } catch (err) {
      warn("API prefix resolution failed.", err);
      return DEFAULT_API_PREFIX;
    }
  }

  function normalizeStep(step, index) {
    try {
      if (!step || typeof step !== "object") {
        return null;
      }

      var fallbackIndex = typeof index === "number" ? index + 1 : 1;
      var stepIndex = parseInt(step.index || fallbackIndex, 10);

      if (!Number.isFinite(stepIndex) || stepIndex < 1) {
        stepIndex = fallbackIndex;
      }

      return {
        index: stepIndex,
        key: step.key || "step-" + stepIndex,
        label: step.label || "Schritt " + stepIndex,
        short_label: step.short_label || step.shortLabel || step.label || String(stepIndex),
        description: step.description || "",
        hint: step.hint || step.description || "",
        target: step.target || step.key || "step-" + stepIndex
      };
    } catch (err) {
      warn("Step normalization failed.", err);
      return null;
    }
  }

  function clampStep(value) {
    try {
      var parsed = parseInt(value, 10);

      if (!Number.isFinite(parsed)) {
        parsed = 1;
      }

      if (parsed < 1) {
        return 1;
      }

      if (parsed > state.stepCount) {
        return state.stepCount;
      }

      return parsed;
    } catch (err) {
      return 1;
    }
  }

  function getStepMeta(stepIndex) {
    try {
      var parsed = parseInt(stepIndex, 10);

      for (var index = 0; index < state.steps.length; index += 1) {
        if (parseInt(state.steps[index].index, 10) === parsed) {
          return state.steps[index];
        }
      }

      return {
        index: parsed,
        key: "step-" + parsed,
        label: "Schritt " + parsed,
        short_label: String(parsed),
        hint: ""
      };
    } catch (err) {
      return {
        index: stepIndex,
        key: "step-" + stepIndex,
        label: "Schritt " + stepIndex,
        short_label: String(stepIndex || ""),
        hint: ""
      };
    }
  }

  function traceNavigation(entry) {
    try {
      var payload = Object.assign({
        timestamp: nowIso()
      }, entry || {});

      state.navigationTrace.push(payload);

      if (state.navigationTrace.length > 50) {
        state.navigationTrace = state.navigationTrace.slice(state.navigationTrace.length - 50);
      }

      dispatch("vectoplan:create:navigation-traced", payload);
    } catch (err) {
      warn("Navigation trace failed.", err);
    }
  }

  function acquireLock(name, ttlMs) {
    try {
      var key = String(name || "default");
      var now = Date.now();
      var ttl = parseInt(ttlMs || DEFAULT_LOCK_TIMEOUT_MS, 10);

      if (!Number.isFinite(ttl) || ttl < 50) {
        ttl = DEFAULT_LOCK_TIMEOUT_MS;
      }

      var existing = state.locks[key];

      if (existing && existing.expiresAt && existing.expiresAt > now) {
        return false;
      }

      state.locks[key] = {
        acquiredAt: now,
        expiresAt: now + ttl
      };

      return true;
    } catch (err) {
      warn("Lock acquisition failed.", err);
      return true;
    }
  }

  function releaseLock(name) {
    try {
      var key = String(name || "default");

      if (state.locks[key]) {
        delete state.locks[key];
      }
    } catch (err) {
      warn("Lock release failed.", err);
    }
  }

  function isLocked(name) {
    try {
      var key = String(name || "default");
      var lock = state.locks[key];

      if (!lock) {
        return false;
      }

      if (lock.expiresAt && lock.expiresAt <= Date.now()) {
        delete state.locks[key];
        return false;
      }

      return true;
    } catch (err) {
      return false;
    }
  }

  function withLock(name, callback, ttlMs) {
    try {
      if (typeof callback !== "function") {
        return undefined;
      }

      if (!acquireLock(name, ttlMs)) {
        return undefined;
      }

      try {
        return callback();
      } finally {
        releaseLock(name);
      }
    } catch (err) {
      releaseLock(name);
      error("Locked operation failed: " + name, err);
      return undefined;
    }
  }

  function setPending(value) {
    try {
      state.pending = !!value;
      safeSetAttribute(document.documentElement, "data-vp-create-pending", state.pending ? "true" : "false");
      dispatch("vectoplan:create:pending-changed", {
        pending: state.pending
      });
    } catch (err) {
      warn("Set pending failed.", err);
    }
  }

  function setStatus(message, stateName) {
    try {
      var statusNode = qs(SELECTORS.status);

      if (!statusNode) {
        return;
      }

      statusNode.textContent = message || "";

      statusNode.classList.remove(
        STATE_CLASSES.loading,
        STATE_CLASSES.ok,
        STATE_CLASSES.warning,
        STATE_CLASSES.error
      );

      if (stateName === "loading" || stateName === "running") {
        statusNode.classList.add(STATE_CLASSES.loading);
      } else if (stateName === "ok") {
        statusNode.classList.add(STATE_CLASSES.ok);
      } else if (stateName === "warning") {
        statusNode.classList.add(STATE_CLASSES.warning);
      } else if (stateName === "error") {
        statusNode.classList.add(STATE_CLASSES.error);
      }

      safeSetAttribute(statusNode, "data-vp-status-state", stateName || "idle");
    } catch (err) {
      warn("Set status failed.", err);
    }
  }

  function registerModule(name, moduleApi) {
    try {
      var key = String(name || "").trim();

      if (!key) {
        warn("Module registration skipped because name is empty.");
        return false;
      }

      if (state.modules[key]) {
        warn("Module already registered; replacing module: " + key);
      } else {
        state.moduleOrder.push(key);
      }

      state.modules[key] = moduleApi || {};

      dispatch("vectoplan:create:module-registered", {
        name: key,
        moduleNames: state.moduleOrder.slice()
      });

      return true;
    } catch (err) {
      error("Module registration failed.", err);
      return false;
    }
  }

  function getModule(name) {
    try {
      return state.modules[String(name || "")] || null;
    } catch (err) {
      return null;
    }
  }

  function hasModule(name) {
    try {
      return !!getModule(name);
    } catch (err) {
      return false;
    }
  }

  function bindOnce(key, binder) {
    try {
      var safeKey = String(key || "").trim();

      if (!safeKey || typeof binder !== "function") {
        return false;
      }

      if (state.bindings[safeKey]) {
        return false;
      }

      state.bindings[safeKey] = true;
      binder();

      return true;
    } catch (err) {
      error("bindOnce failed: " + key, err);
      return false;
    }
  }

  function dispatch(eventName, detail, options) {
    try {
      var eventOptions = options || {};
      var event = new CustomEvent(eventName, {
        bubbles: eventOptions.bubbles !== false,
        cancelable: !!eventOptions.cancelable,
        detail: detail || {}
      });

      var target = eventOptions.target || document;
      target.dispatchEvent(event);

      return event;
    } catch (err) {
      warn("Event dispatch failed: " + eventName, err);
      return null;
    }
  }

  function dispatchNativeEvent(node, eventName) {
    try {
      if (!node) {
        return;
      }

      node.dispatchEvent(new Event(eventName, {
        bubbles: true,
        cancelable: false
      }));
    } catch (err) {
      warn("Native event dispatch failed: " + eventName, err);
    }
  }

  function qs(selector, root) {
    try {
      var scope = root || document;
      return scope.querySelector(selector);
    } catch (err) {
      warn("querySelector failed: " + selector, err);
      return null;
    }
  }

  function qsa(selector, root) {
    try {
      var scope = root || document;
      return Array.prototype.slice.call(scope.querySelectorAll(selector));
    } catch (err) {
      warn("querySelectorAll failed: " + selector, err);
      return [];
    }
  }

  function closest(node, selector) {
    try {
      if (!node || typeof node.closest !== "function") {
        return null;
      }

      return node.closest(selector);
    } catch (err) {
      return null;
    }
  }

  function contains(root, node) {
    try {
      return !!(root && node && root.contains(node));
    } catch (err) {
      return false;
    }
  }

  function setText(selectorOrNode, value, root) {
    try {
      var node = typeof selectorOrNode === "string" ? qs(selectorOrNode, root) : selectorOrNode;

      if (node) {
        node.textContent = typeof value === "undefined" || value === null ? "" : String(value);
      }
    } catch (err) {
      warn("Set text failed.", err);
    }
  }

  function setAllText(selector, value, root) {
    try {
      qsa(selector, root).forEach(function (node) {
        node.textContent = typeof value === "undefined" || value === null ? "" : String(value);
      });
    } catch (err) {
      warn("Set all text failed: " + selector, err);
    }
  }

  function safeSetAttribute(node, name, value) {
    try {
      if (node && name) {
        node.setAttribute(name, typeof value === "undefined" || value === null ? "" : String(value));
      }
    } catch (err) {
      /* no-op */
    }
  }

  function safeRemoveAttribute(node, name) {
    try {
      if (node && name) {
        node.removeAttribute(name);
      }
    } catch (err) {
      /* no-op */
    }
  }

  function toggleClass(node, className, enabled) {
    try {
      if (node && className) {
        node.classList.toggle(className, !!enabled);
      }
    } catch (err) {
      warn("Toggle class failed: " + className, err);
    }
  }

  function addClass(node, className) {
    try {
      if (node && className) {
        node.classList.add(className);
      }
    } catch (err) {
      warn("Add class failed: " + className, err);
    }
  }

  function removeClass(node, className) {
    try {
      if (node && className) {
        node.classList.remove(className);
      }
    } catch (err) {
      warn("Remove class failed: " + className, err);
    }
  }

  function readJsonScript(selector, fallback) {
    try {
      var node = qs(selector);

      if (!node) {
        return fallback;
      }

      var text = node.textContent || "";

      if (!text.trim()) {
        return fallback;
      }

      return JSON.parse(text);
    } catch (err) {
      warn("Invalid JSON script: " + selector, err);
      return fallback;
    }
  }

  function getNested(object, path, fallback) {
    try {
      var current = object;

      for (var i = 0; i < path.length; i += 1) {
        if (!current || typeof current !== "object" || !(path[i] in current)) {
          return fallback;
        }

        current = current[path[i]];
      }

      return current;
    } catch (err) {
      return fallback;
    }
  }

  function setNested(object, path, value) {
    try {
      if (!object || typeof object !== "object" || !Array.isArray(path) || !path.length) {
        return object;
      }

      var current = object;

      for (var i = 0; i < path.length - 1; i += 1) {
        var key = path[i];

        if (!current[key] || typeof current[key] !== "object") {
          current[key] = {};
        }

        current = current[key];
      }

      current[path[path.length - 1]] = value;

      return object;
    } catch (err) {
      warn("setNested failed.", err);
      return object;
    }
  }

  function getDataInt(node, attribute, fallback) {
    try {
      if (!node) {
        return fallback;
      }

      var parsed = parseInt(node.getAttribute(attribute) || "", 10);

      return Number.isFinite(parsed) ? parsed : fallback;
    } catch (err) {
      return fallback;
    }
  }

  function getFieldValue(form, name) {
    try {
      if (!form || !name) {
        return "";
      }

      var field = form.elements ? form.elements[name] : null;

      if (!field) {
        field = qs("[name='" + cssEscape(name) + "']", form);
      }

      if (!field) {
        return "";
      }

      if (window.RadioNodeList && field instanceof RadioNodeList) {
        return field.value || "";
      }

      return typeof field.value !== "undefined" ? String(field.value) : "";
    } catch (err) {
      return "";
    }
  }

  function setFieldValue(form, name, value) {
    try {
      if (!form || !name) {
        return false;
      }

      var field = form.elements ? form.elements[name] : null;

      if (!field) {
        field = qs("[name='" + cssEscape(name) + "']", form);
      }

      if (!field || typeof field.value === "undefined") {
        return false;
      }

      field.value = typeof value === "undefined" || value === null ? "" : String(value);
      dispatchNativeEvent(field, "input");
      dispatchNativeEvent(field, "change");

      return true;
    } catch (err) {
      warn("setFieldValue failed: " + name, err);
      return false;
    }
  }

  function ensureHiddenField(form, name, value) {
    try {
      if (!form || !name) {
        return null;
      }

      var field = qs("input[type='hidden'][name='" + cssEscape(name) + "']", form);

      if (!field) {
        field = document.createElement("input");
        field.type = "hidden";
        field.name = name;
        form.appendChild(field);
      }

      if (typeof value !== "undefined") {
        field.value = value === null ? "" : String(value);
      }

      return field;
    } catch (err) {
      warn("ensureHiddenField failed: " + name, err);
      return null;
    }
  }

  function trimTrailingSlash(value) {
    try {
      return String(value || "").replace(/\/+$/, "") || DEFAULT_API_PREFIX;
    } catch (err) {
      return DEFAULT_API_PREFIX;
    }
  }

  function slugify(value) {
    try {
      var text = String(value || "")
        .trim()
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/ä/g, "ae")
        .replace(/ö/g, "oe")
        .replace(/ü/g, "ue")
        .replace(/ß/g, "ss")
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/_+/g, "_")
        .replace(/^_+|_+$/g, "");

      return text || "";
    } catch (err) {
      return "";
    }
  }

  function normalizeToken(value, fallback) {
    try {
      var text = String(value || "")
        .trim()
        .toLowerCase()
        .replace(/[-\s]+/g, "_")
        .replace(/[^a-z0-9_]/g, "");

      return text || fallback || "";
    } catch (err) {
      return fallback || "";
    }
  }

  function normalizeTheme(value) {
    try {
      var text = String(value || "").trim().toLowerCase();

      if (text === "dark" || text === "light" || text === "system") {
        return text;
      }

      return "system";
    } catch (err) {
      return "system";
    }
  }

  function normalizeDecimalDisplay(value) {
    try {
      var text = String(value || "").replace(",", ".").trim();
      var number = Number(text);

      if (!Number.isFinite(number) || number <= 0) {
        return "1.00";
      }

      return number.toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1");
    } catch (err) {
      return "1.00";
    }
  }

  function normalizeIntDisplay(value) {
    try {
      var number = parseInt(String(value || "").trim(), 10);

      if (!Number.isFinite(number) || number < 1) {
        return "1";
      }

      return String(number);
    } catch (err) {
      return "1";
    }
  }

  function normalizeOptionText(value) {
    try {
      return String(value || "")
        .replace(/\s+·\s+deaktiviert\s*$/i, "")
        .replace(/\s+/g, " ")
        .trim();
    } catch (err) {
      return "";
    }
  }

  function selectedOptionLabel(select, value) {
    try {
      if (!select) {
        return "";
      }

      var selected = select.options[select.selectedIndex];

      if (selected && selected.value === value) {
        return normalizeOptionText(selected.textContent);
      }

      var options = Array.prototype.slice.call(select.options);
      var match = options.find(function (option) {
        return option.value === value;
      });

      return match ? normalizeOptionText(match.textContent) : "";
    } catch (err) {
      return "";
    }
  }

  function toBoolean(value, fallback) {
    try {
      if (typeof value === "boolean") {
        return value;
      }

      if (typeof value === "number") {
        return value !== 0;
      }

      var text = String(value || "").trim().toLowerCase();

      if (["true", "1", "yes", "ja", "on", "enabled", "active"].indexOf(text) !== -1) {
        return true;
      }

      if (["false", "0", "no", "nein", "off", "disabled", "inactive"].indexOf(text) !== -1) {
        return false;
      }

      return !!fallback;
    } catch (err) {
      return !!fallback;
    }
  }

  function toNumber(value, fallback) {
    try {
      var number = Number(String(value || "").replace(",", "."));

      return Number.isFinite(number) ? number : fallback;
    } catch (err) {
      return fallback;
    }
  }

  function toInteger(value, fallback) {
    try {
      var number = parseInt(String(value || "").trim(), 10);

      return Number.isFinite(number) ? number : fallback;
    } catch (err) {
      return fallback;
    }
  }

  function compactArray(value) {
    try {
      if (!Array.isArray(value)) {
        return [];
      }

      return value.filter(function (item) {
        return item !== null && typeof item !== "undefined" && String(item).trim() !== "";
      });
    } catch (err) {
      return [];
    }
  }

  function uniqueArray(value) {
    try {
      var seen = {};
      var result = [];

      compactArray(value).forEach(function (item) {
        var key = String(item);

        if (!seen[key]) {
          seen[key] = true;
          result.push(item);
        }
      });

      return result;
    } catch (err) {
      return compactArray(value);
    }
  }

  function clone(value) {
    try {
      if (typeof structuredClone === "function") {
        return structuredClone(value);
      }

      return JSON.parse(JSON.stringify(value));
    } catch (err) {
      if (Array.isArray(value)) {
        return value.slice();
      }

      if (value && typeof value === "object") {
        return Object.assign({}, value);
      }

      return value;
    }
  }

  function cloneObject(value) {
    try {
      var cloned = clone(value);

      if (cloned && typeof cloned === "object" && !Array.isArray(cloned)) {
        return cloned;
      }

      return {};
    } catch (err) {
      return {};
    }
  }

  function safeJsonParse(value, fallback) {
    try {
      if (typeof value === "object" && value !== null) {
        return value;
      }

      var text = String(value || "");

      if (!text.trim()) {
        return fallback;
      }

      return JSON.parse(text);
    } catch (err) {
      return fallback;
    }
  }

  function safeJsonStringify(value, fallback) {
    try {
      return JSON.stringify(value);
    } catch (err) {
      return typeof fallback === "string" ? fallback : "{}";
    }
  }

  function stringifyJson(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (err) {
      return String(value);
    }
  }

  function cssEscape(value) {
    try {
      if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(String(value));
      }

      return String(value).replace(/["\\]/g, "\\$&");
    } catch (err) {
      return String(value || "").replace(/["\\]/g, "\\$&");
    }
  }

  function htmlToFragment(html) {
    try {
      var template = document.createElement("template");
      template.innerHTML = String(html || "").trim();
      return template.content;
    } catch (err) {
      return document.createDocumentFragment();
    }
  }

  function getTemplateHtml(template) {
    try {
      if (!template) {
        return "";
      }

      if ("innerHTML" in template && template.innerHTML) {
        return template.innerHTML;
      }

      if (template.content) {
        var wrapper = document.createElement("div");
        wrapper.appendChild(template.content.cloneNode(true));
        return wrapper.innerHTML;
      }

      return template.textContent || "";
    } catch (err) {
      return "";
    }
  }

  function focusFirstInput(root) {
    try {
      if (!root) {
        return false;
      }

      var firstInput = qs("input:not([type='hidden']):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex='-1'])", root);

      if (firstInput && typeof firstInput.focus === "function") {
        firstInput.focus({ preventScroll: true });
        return true;
      }

      return false;
    } catch (err) {
      try {
        var fallbackInput = root ? qs("input, select, textarea, button", root) : null;

        if (fallbackInput) {
          fallbackInput.focus();
          return true;
        }
      } catch (fallbackError) {
        /* no-op */
      }

      return false;
    }
  }

  function safeLocalStorageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (err) {
      return "";
    }
  }

  function safeLocalStorageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
      return true;
    } catch (err) {
      return false;
    }
  }

  function safeLocalStorageRemove(key) {
    try {
      window.localStorage.removeItem(key);
      return true;
    } catch (err) {
      return false;
    }
  }

  function copyText(text) {
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        return navigator.clipboard.writeText(text);
      }

      return new Promise(function (resolve, reject) {
        try {
          var textarea = document.createElement("textarea");
          textarea.value = text;
          textarea.setAttribute("readonly", "readonly");
          textarea.style.position = "fixed";
          textarea.style.left = "-9999px";
          document.body.appendChild(textarea);
          textarea.select();
          document.execCommand("copy");
          textarea.remove();
          resolve();
        } catch (err) {
          reject(err);
        }
      });
    } catch (err) {
      return Promise.reject(err);
    }
  }

  function flashUpdated(node, className, timeoutMs) {
    try {
      if (!node) {
        return;
      }

      var safeClass = className || STATE_CLASSES.updated;
      var timeout = parseInt(timeoutMs || 380, 10);

      node.classList.remove(safeClass);
      void node.offsetWidth;
      node.classList.add(safeClass);

      window.setTimeout(function () {
        try {
          node.classList.remove(safeClass);
        } catch (err) {
          /* no-op */
        }
      }, Number.isFinite(timeout) ? timeout : 380);
    } catch (err) {
      warn("Flash updated failed.", err);
    }
  }

  function actionLabel(action) {
    var labels = {
      draft: "Draft",
      validate: "Validierung",
      "package-plan": "Package-Plan",
      package_plan: "Package-Plan",
      download: "Download",
      save: "Speichern"
    };

    return labels[action] || action || "Aktion";
  }

  function isWriteEnabled() {
    try {
      if (state.context && typeof state.context.write_enabled !== "undefined") {
        return Boolean(state.context.write_enabled);
      }

      if (state.context && typeof state.context.writeEnabled !== "undefined") {
        return Boolean(state.context.writeEnabled);
      }

      var app = qs(SELECTORS.app);
      var page = qs(SELECTORS.page);

      if (app && app.getAttribute("data-create-write-enabled") === "true") {
        return true;
      }

      if (page && page.getAttribute("data-create-write-enabled") === "true") {
        return true;
      }

      return false;
    } catch (err) {
      return false;
    }
  }

  function resolveRouteUrl(action, fallbackPath) {
    try {
      var routes = state.context.routes || {};
      var normalizedAction = action === "package-plan" ? "package_plan" : action;
      var candidate = routes[normalizedAction] || routes[action] || "";

      if (!candidate && normalizedAction === "package_plan") {
        candidate = routes.packagePlan || "";
      }

      if (!candidate && action === "download") {
        candidate = routes.download || "";
      }

      if (!candidate && action === "save") {
        candidate = routes.save || "";
      }

      if (!candidate && action === "draft") {
        candidate = routes.draft || "";
      }

      if (!candidate && action === "validate") {
        candidate = routes.validate || "";
      }

      if (!candidate) {
        candidate = state.apiPrefix + (fallbackPath || "");
      }

      if (/^https?:\/\//i.test(candidate)) {
        return candidate;
      }

      if (candidate.charAt(0) === "/") {
        return candidate;
      }

      return state.apiPrefix + "/" + candidate.replace(/^\/+/, "");
    } catch (err) {
      return state.apiPrefix + (fallbackPath || "");
    }
  }

  function normalizeIssues(value) {
    try {
      if (!value) {
        return [];
      }

      if (Array.isArray(value)) {
        return value.filter(Boolean);
      }

      if (typeof value === "object") {
        return [value];
      }

      return [
        {
          severity: "error",
          code: "issue",
          message: String(value)
        }
      ];
    } catch (err) {
      return [];
    }
  }

  function normalizeIssueFieldName(fieldName) {
    var mapping = {
      "geometry.width": "geometry_width",
      "geometry.height": "geometry_height",
      "geometry.depth": "geometry_depth",
      "geometry.unit": "geometry_unit",
      "dimensions.width": "geometry_width",
      "dimensions.height": "geometry_height",
      "dimensions.depth": "geometry_depth",
      "dimensions.unit": "geometry_unit",
      "editor_block.cells.x": "editor_cells_x",
      "editor_block.cells.y": "editor_cells_y",
      "editor_block.cells.z": "editor_cells_z",
      "default_variant_id": "variants",
      "documents": "family_name",
      "draft": "family_name",
      "path": "family_name",
      "target_dir": "family_name",
      "write_enabled": "save"
    };

    return mapping[fieldName] || fieldName;
  }

  function snapshot() {
    try {
      return {
        version: CORE_VERSION,
        initialized: state.initialized,
        coreReady: state.coreReady,
        domReady: state.domReady,
        apiPrefix: state.apiPrefix,
        writeEnabled: isWriteEnabled(),
        pending: state.pending,
        theme: state.theme,
        lastAction: state.lastAction,
        lastResult: clone(state.lastResult),
        lastError: state.lastError && state.lastError.message ? state.lastError.message : state.lastError ? String(state.lastError) : "",
        wizard: {
          currentStep: state.currentStep,
          stepCount: state.stepCount,
          maxReachedStep: state.maxReachedStep,
          allowDirectStepClick: state.allowDirectStepClick,
          lockFutureSteps: state.lockFutureSteps,
          steps: clone(state.steps)
        },
        modules: state.moduleOrder.slice(),
        locks: Object.keys(state.locks || {}),
        diagnostics: clone(state.diagnostics),
        navigationTrace: clone(state.navigationTrace)
      };
    } catch (err) {
      return {
        version: CORE_VERSION,
        snapshot_error: String(err && err.message ? err.message : err)
      };
    }
  }

  function bootstrapCore() {
    try {
      refreshContext();
      state.initialized = true;
      safeSetAttribute(document.documentElement, "data-vp-create-core-initialized", "true");

      dispatch("vectoplan:create:core-ready", snapshot());

      return true;
    } catch (err) {
      state.initialized = false;
      state.lastError = err;
      error("Core bootstrap failed.", err);
      return false;
    }
  }

  var api = {
    version: CORE_VERSION,

    constants: {
      GLOBAL_NAME: GLOBAL_NAME,
      DEFAULT_API_PREFIX: DEFAULT_API_PREFIX,
      DEFAULT_THEME_STORAGE_KEY: DEFAULT_THEME_STORAGE_KEY,
      DEFAULT_LOCK_TIMEOUT_MS: DEFAULT_LOCK_TIMEOUT_MS
    },

    selectors: SELECTORS,
    classes: STATE_CLASSES,
    previewShapeClasses: PREVIEW_SHAPE_CLASSES,
    defaultSteps: DEFAULT_STEPS,
    state: state,

    onReady: onReady,
    bootstrap: bootstrapCore,
    refreshContext: refreshContext,
    refreshWizardConfig: refreshWizardConfig,
    snapshot: snapshot,

    log: log,
    info: info,
    warn: warn,
    error: error,
    pushDiagnostic: pushDiagnostic,

    registerModule: registerModule,
    getModule: getModule,
    hasModule: hasModule,
    bindOnce: bindOnce,

    acquireLock: acquireLock,
    releaseLock: releaseLock,
    isLocked: isLocked,
    withLock: withLock,
    setPending: setPending,

    dispatch: dispatch,
    dispatchNativeEvent: dispatchNativeEvent,
    traceNavigation: traceNavigation,

    qs: qs,
    qsa: qsa,
    closest: closest,
    contains: contains,
    setText: setText,
    setAllText: setAllText,
    safeSetAttribute: safeSetAttribute,
    safeRemoveAttribute: safeRemoveAttribute,
    toggleClass: toggleClass,
    addClass: addClass,
    removeClass: removeClass,

    resolveContextBundle: resolveContextBundle,
    resolveApiPrefix: resolveApiPrefix,
    resolveRouteUrl: resolveRouteUrl,
    readJsonScript: readJsonScript,

    normalizeStep: normalizeStep,
    clampStep: clampStep,
    getStepMeta: getStepMeta,

    getNested: getNested,
    setNested: setNested,
    getDataInt: getDataInt,
    getFieldValue: getFieldValue,
    setFieldValue: setFieldValue,
    ensureHiddenField: ensureHiddenField,

    trimTrailingSlash: trimTrailingSlash,
    slugify: slugify,
    normalizeToken: normalizeToken,
    normalizeTheme: normalizeTheme,
    normalizeDecimalDisplay: normalizeDecimalDisplay,
    normalizeIntDisplay: normalizeIntDisplay,
    normalizeOptionText: normalizeOptionText,
    selectedOptionLabel: selectedOptionLabel,
    toBoolean: toBoolean,
    toNumber: toNumber,
    toInteger: toInteger,
    compactArray: compactArray,
    uniqueArray: uniqueArray,

    clone: clone,
    cloneObject: cloneObject,
    safeJsonParse: safeJsonParse,
    safeJsonStringify: safeJsonStringify,
    stringifyJson: stringifyJson,
    cssEscape: cssEscape,
    htmlToFragment: htmlToFragment,
    getTemplateHtml: getTemplateHtml,
    focusFirstInput: focusFirstInput,

    safeLocalStorageGet: safeLocalStorageGet,
    safeLocalStorageSet: safeLocalStorageSet,
    safeLocalStorageRemove: safeLocalStorageRemove,
    copyText: copyText,
    flashUpdated: flashUpdated,

    setStatus: setStatus,
    actionLabel: actionLabel,
    isWriteEnabled: isWriteEnabled,
    normalizeIssues: normalizeIssues,
    normalizeIssueFieldName: normalizeIssueFieldName
  };

  window[GLOBAL_NAME] = api;

  onReady(function () {
    bootstrapCore();
  });
})();