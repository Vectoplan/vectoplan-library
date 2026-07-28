/* services/vectoplan-library/static/js/vplib/create/create_core.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateCore";
  var CORE_VERSION = "0.8.0";
  var DEFAULT_API_PREFIX = "/api/v1/vplib/create";
  var DEFAULT_DEFINITIONS_API_PREFIX = "/api/v1/vplib/definitions";
  var DEFAULT_TAXONOMY_API_PREFIX = "/api/v1/vplib/taxonomy";
  var DEFAULT_FILES_API_PREFIX = "/api/v1/vplib/files";
  var DEFAULT_THEME_STORAGE_KEY = "vectoplan.create.theme";
  var DEFAULT_LOCK_TIMEOUT_MS = 60000;
  var DEFAULT_ASYNC_LOCK_TIMEOUT_MS = 120000;
  var DEFAULT_CORE_READINESS_TIMEOUT_MS = 20000;
  var DEFAULT_CORE_READINESS_POLL_MS = 50;
  var DEFAULT_STARTER_OBJECT_KIND = "cell_block";
  var DEFAULT_STARTER_FAMILY_PROFILE_ID = "simple_cell_block";
  var DEFAULT_STARTER_VARIANT_PROFILE_ID = "simple_cell_block.v1";

  var CORE_STATUS_CREATED = "created";
  var CORE_STATUS_INITIALIZED = "initialized";
  var CORE_STATUS_LOADING = "loading";
  var CORE_STATUS_READY = "ready";
  var CORE_STATUS_BLOCKED = "blocked";
  var CORE_STATUS_UNAVAILABLE = "unavailable";

  var CRITICAL_ACTIONS = {
    validate: true,
    package_plan: true,
    "package-plan": true,
    download: true,
    save: true,
    publish_bundle: true,
    publishBundle: true,
    publish_prepare: true,
    publishPrepare: true,
    "publish-prepare": true
  };

  var existingRuntime = window[GLOBAL_NAME] || null;

  if (existingRuntime && existingRuntime.version === CORE_VERSION && existingRuntime.state) {
    try {
      existingRuntime.refreshContext();

      if (typeof existingRuntime.ensureReady === "function") {
        Promise.resolve(existingRuntime.ensureReady({
          source: "duplicate_script_load",
          rejectOnError: false
        })).catch(function (existingReadinessError) {
          if (typeof existingRuntime.warn === "function") {
            existingRuntime.warn(
              "Existing Create Core readiness refresh failed.",
              existingReadinessError
            );
          }
        });
      }

      existingRuntime.log("create_core.js already initialized; refreshed existing runtime.", {
        existingVersion: existingRuntime.version,
        incomingVersion: CORE_VERSION,
        ready: typeof existingRuntime.isOperational === "function"
          ? existingRuntime.isOperational()
          : !!existingRuntime.state.coreReady
      });
    } catch (existingError) {
      /* no-op */
    }

    return;
  }

  var SELECTORS = {
    page: "[data-create-page='true'], [data-vp-create-page='true']",
    app: "[data-vp-create-app]",
    form: "[data-vp-create-form], [data-create-form='true'], #vp-create-form, form[data-create-form]",

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

    section: "[data-vp-create-section], [data-create-section]",
    identitySection: "[data-vp-create-section='identity'], [data-create-section='identity']",
    taxonomySection: "[data-vp-create-section='taxonomy'], [data-create-section='taxonomy']",
    variablesSection: "[data-vp-create-section='object-variants'], [data-vp-create-section='variables'], [data-vp-create-section-alias='variables'], [data-create-section='object-variants'], [data-create-section='variables']",
    geometrySection: "[data-vp-create-section='geometry'], [data-create-section='geometry']",
    technicalSection: "[data-vp-create-section='technical'], [data-create-section='technical']",
    actionSection: "[data-vp-create-section='actions'], [data-create-actions-card='true'], [data-vp-actions-root='true']",

    actionButton: "[data-create-action]",
    status: "[data-vp-action-status], [data-create-action-status='true']",

    resultSection: "[data-vp-actions-result], [data-create-result-section='true']",
    resultOutput: "[data-vp-actions-result-output], [data-create-result-output='true'], [data-create-output='true']",
    resultCode: "[data-vp-actions-result-code]",
    resultSummary: "[data-vp-actions-result-summary], [data-create-result-summary='true']",
    resultCopy: "[data-vp-actions-result-copy], [data-create-copy-result='true'], [data-create-result-copy='true']",
    resultClear: "[data-vp-actions-result-clear], [data-create-clear-result='true'], [data-create-result-clear='true']",
    resultLastAction: "[data-create-result-last-action='true'], [data-vp-result-last-action]",
    resultStatus: "[data-create-result-status='true'], [data-vp-result-status]",
    resultHttpStatus: "[data-create-result-http-status='true'], [data-vp-result-http-status]",
    resultErrorCount: "[data-create-result-error-count='true'], [data-vp-result-error-count]",
    resultWarningCount: "[data-create-result-warning-count='true'], [data-vp-result-warning-count]",

    addVariant: "[data-create-add-variant='true'], [data-vp-add-definition-variant='true']",
    addVariable: "[data-create-add-variable='true'], [data-vp-add-variable]",
    removeRow: "[data-create-remove-row='true']",
    clearVariable: "[data-create-clear-variable='true']",

    variantWorkspace: "[data-vp-variant-workspace-root='true'], [data-vp-variant-workspace='true']",
    variantTable: "[data-create-variant-table='true'], [data-vp-variant-table-root='true'], [data-vp-variant-table='true']",
    variantRow: "[data-vp-variant-row='true'], [data-create-variant-row='true']",
    variantTemplate: "[data-vp-variant-row-template='true'], [data-create-variant-row-template='true']",
    variantDrawer: "[data-vp-variant-drawer-root='true'], [data-vp-variant-drawer='true']",

    variableTable: "[data-create-variable-table='true'], [data-vp-variable-table]",
    variableRow: "[data-create-variable-row='true'], [data-vp-variable-row]",
    variableTemplate: "[data-create-variable-row-template='true']",

    domainSelect: "[data-create-taxonomy-select='domain'], [name='domain'], [data-vp-taxonomy-domain]",
    categorySelect: "[data-create-taxonomy-select='category'], [name='category'], [data-vp-taxonomy-category]",
    subcategorySelect: "[data-create-taxonomy-select='subcategory'], [name='subcategory'], [data-vp-taxonomy-subcategory]",
    taxonomyPathDomain: "[data-vp-taxonomy-path-domain]",
    taxonomyPathCategory: "[data-vp-taxonomy-path-category]",
    taxonomyPathFamily: "[data-vp-taxonomy-path-family]",
    taxonomyLegacyPath: "[data-create-taxonomy-path-value='true'], [name='taxonomy_path']",

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

    uploadZone: "[data-vp-upload-zone], [data-create-upload-zone], [data-vp-upload]",
    uploadInput: "[data-vp-upload-input], input[type='file'][data-vp-upload-kind], input[type='file'][name='geometry_model_files'], input[type='file'][name='texture_files'], input[type='file'][name='technical_document_files'], input[type='file'][name^='variant_document_files']",
    uploadMetadata: "[data-vp-upload-metadata], [name='geometry_model_uploads_json'], [name='texture_uploads_json'], [name='technical_document_uploads_json'], [name='variant_document_uploads_json'], [name^='variant_document_uploads[']",
    geometryUpload: "[data-vp-geometry-upload], [data-vp-upload-kind='geometry_model']",
    technicalUpload: "[data-vp-technical-upload], [data-vp-upload-kind='technical_documents']",
    variantDocumentUpload: "[data-vp-field-document-list-upload='true'], [data-vp-upload-kind='variant_documents']",

    previewPlaceholder: "[data-vp-create-preview], [data-create-preview-placeholder='true']",
    previewStage: "[data-vp-preview-stage], [data-create-preview-stage='true']",
    previewPrimitive: "[data-vp-preview-primitive], [data-create-preview-cube='true']",
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

    contextJson: "[data-vp-create-context-json], [data-create-context-json='true'], #vp-create-context-json",
    generatorContextJson: "[data-generator-context-json='true'], [data-vp-create-context-json='generator-context'], #vp-generator-context-json",
    optionsJson: "[data-vp-create-options-json], [data-create-options-json='true'], #vp-create-options-json",
    healthJson: "[data-vp-create-health-json], [data-create-health-json='true'], #vp-create-health-json",
    uiStateJson: "[data-vp-create-ui-state-json], [data-create-ui-state-json='true'], #vp-create-ui-state-json",
    wizardJson: "[data-vp-create-wizard-json], [data-create-wizard-json='true'], #vp-create-wizard-json",
    uploadsJson: "[data-vp-create-context-json='uploads'], [data-create-upload-json='true'], [data-vp-create-upload-config-json], [data-create-upload-config-json='true'], #vp-create-upload-json, #vp-create-upload-config-json",
    payloadContractJson: "[data-create-payload-contract-json='true'], [data-vp-create-context-json='payload-contract'], #vp-create-payload-contract-json",
    definitionsJson: "[data-vp-create-definitions-json], [data-create-definitions-json='true'], #vp-create-definitions-json"
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

  var DEFAULT_ROUTES = {
    index: "/",
    health: "/health",
    routes: "/routes",
    selftest: "/selftest",
    options: "/options",
    context: "/context",
    create_context: "/create-context",
    createContext: "/create-context",
    definitions_current: "/definitions/current",
    definitionsCurrent: "/definitions/current",
    draft: "/draft",
    persistent_draft: "/drafts",
    persistentDraft: "/drafts",
    drafts: "/drafts",
    validate: "/validate",
    package_plan: "/package-plan",
    packagePlan: "/package-plan",
    "package-plan": "/package-plan",
    publish_bundle: "/publish-bundle",
    publishBundle: "/publish-bundle",
    publish_prepare: "/publish-bundle",
    publishPrepare: "/publish-bundle",
    "publish-prepare": "/publish-bundle",
    download: "/download",
    save: "/save",
    cache_clear: "/cache/clear",
    cacheClear: "/cache/clear"
  };

  var DEFAULT_STEPS = [
    {
      index: 1,
      key: "identity",
      label: "Grunddaten",
      short_label: "Daten",
      shortLabel: "Daten",
      hint: "Name und Beschreibung des neuen Library-Bausteins festlegen.",
      target: "identity"
    },
    {
      index: 2,
      key: "taxonomy",
      label: "Taxonomie",
      short_label: "Taxonomie",
      shortLabel: "Taxonomie",
      hint: "Fachliche Einordnung auswählen.",
      target: "taxonomy"
    },
    {
      index: 3,
      key: "variables",
      alias: "object",
      aliases: ["object", "object-variants", "variables"],
      label: "Variablen",
      short_label: "Variablen",
      shortLabel: "Variablen",
      hint: "Variablen, Varianten und Unterlagen definieren.",
      target: "object-variants"
    },
    {
      index: 4,
      key: "geometry",
      label: "Geometrie",
      short_label: "Geometrie",
      shortLabel: "Geometrie",
      hint: "Form, Maße, Editor-Raster und optionales 3D-Modell definieren.",
      target: "geometry"
    },
    {
      index: 5,
      key: "technical",
      label: "Technik",
      short_label: "Technik",
      shortLabel: "Technik",
      hint: "Optionale technische Kennwerte und Unterlagen ergänzen.",
      target: "technical"
    },
    {
      index: 6,
      key: "actions",
      alias: "create",
      label: "Erzeugen",
      short_label: "Erzeugen",
      shortLabel: "Erzeugen",
      hint: "Draft, Validierung, Package-Plan, Download oder Save ausführen.",
      target: "actions"
    }
  ];

  var previousState = existingRuntime && existingRuntime.state ? existingRuntime.state : {};

  var state = {
    initialized: false,
    coreReady: false,
    contextReady: false,
    domReady: false,
    status: CORE_STATUS_CREATED,
    operational: false,
    variantProfilesReady: false,
    readinessPromise: null,
    readinessResult: null,
    readinessGeneration: 0,
    bootstrapPromise: null,
    bootstrapGeneration: 0,
    dependencyEventsBound: false,
    lastReadySignature: "",
    lockSequence: 0,

    version: CORE_VERSION,
    apiPrefix: DEFAULT_API_PREFIX,
    definitionsApiPrefix: DEFAULT_DEFINITIONS_API_PREFIX,
    taxonomyApiPrefix: DEFAULT_TAXONOMY_API_PREFIX,
    filesApiPrefix: DEFAULT_FILES_API_PREFIX,
    themeStorageKey: DEFAULT_THEME_STORAGE_KEY,

    context: {},
    generatorContext: {},
    options: {},
    health: {},
    uiState: {},
    wizard: {},
    uploads: {},
    payloadContract: {},
    definitions: {},
    routes: cloneObject(DEFAULT_ROUTES),

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
    lastFailure: null,
    dependencies: previousState.dependencies && typeof previousState.dependencies === "object"
      ? cloneObject(previousState.dependencies)
      : {
        context: {
          ready: false,
          status: CORE_STATUS_CREATED,
          error: null
        },
        definitions: {
          ready: false,
          status: CORE_STATUS_CREATED,
          error: null
        },
        variantProfiles: {
          ready: false,
          status: CORE_STATUS_CREATED,
          error: null,
          result: null
        }
      },

    variantIndex: 1,
    variableIndex: 1,

    theme: "dark",
    previewUpdateTimer: null,

    locks: previousState.locks && typeof previousState.locks === "object" ? previousState.locks : {},
    modules: previousState.modules && typeof previousState.modules === "object" ? previousState.modules : {},
    moduleOrder: Array.isArray(previousState.moduleOrder) ? previousState.moduleOrder.slice() : [],
    bindings: previousState.bindings && typeof previousState.bindings === "object" ? previousState.bindings : {},
    diagnostics: Array.isArray(previousState.diagnostics) ? previousState.diagnostics.slice(-100) : [],
    navigationTrace: Array.isArray(previousState.navigationTrace) ? previousState.navigationTrace.slice(-50) : []
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
    } catch (logError) {
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
    } catch (infoError) {
      /* no-op */
    }
  }

  function warn(message, err) {
    try {
      if (window.console && typeof window.console.warn === "function") {
        if (typeof err !== "undefined") {
          window.console.warn("[VPLIB Create Core] " + message, err);
        } else {
          window.console.warn("[VPLIB Create Core] " + message);
        }
      }
    } catch (consoleError) {
      /* no-op */
    }

    pushDiagnostic("warning", message, err);
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


  function createCoreError(code, message, details, cause) {
    var coreError;

    try {
      coreError = new Error(String(message || code || "Create Core error."));
    } catch (constructionError) {
      coreError = {
        name: "Error",
        message: String(message || code || "Create Core error.")
      };
    }

    try {
      coreError.name = "VectoplanCreateCoreError";
      coreError.code = String(code || "create_core_error");
      coreError.component = GLOBAL_NAME;
      coreError.componentVersion = CORE_VERSION;
      coreError.__vp_create_core_error = true;

      if (details && typeof details === "object") {
        coreError.details = cloneObject(details);

        if (details.status !== undefined && details.status !== null) {
          coreError.status = details.status;
        }

        if (details.action) {
          coreError.action = String(details.action);
        }

        if (details.dependency) {
          coreError.dependency = String(details.dependency);
        }
      }

      if (cause !== undefined && cause !== null) {
        try {
          coreError.cause = cause;
        } catch (causeError) {
          /* no-op */
        }
      }
    } catch (enrichmentError) {
      /* Preserve the Error even if enrichment fails. */
    }

    return coreError;
  }

  function ensureCoreError(err, fallbackCode, fallbackMessage, details) {
    try {
      if (err && err.__vp_create_core_error === true && err.message) {
        return err;
      }

      if (err instanceof Error) {
        if (!err.code) {
          err.code = fallbackCode || err.name || "create_core_error";
        }

        if (!err.component) {
          err.component = GLOBAL_NAME;
        }

        err.__vp_create_core_error = true;

        if (details && typeof details === "object" && !err.details) {
          err.details = cloneObject(details);
        }

        return err;
      }

      var source = err && err.error && typeof err.error === "object"
        ? err.error
        : (err || {});

      var code = source.code ||
        source.error_code ||
        source.status ||
        source.name ||
        fallbackCode ||
        "create_core_error";

      var message = source.message ||
        source.detail ||
        source.description ||
        fallbackMessage ||
        (typeof err === "string" ? err : "") ||
        "Create Core error.";

      return createCoreError(code, message, Object.assign({}, details || {}, {
        status: source.status || null,
        payload: source.payload || source.raw || source.response || null
      }), err);
    } catch (normalizationError) {
      return createCoreError(
        fallbackCode || "create_core_error",
        fallbackMessage || "Create Core error could not be normalized.",
        details || {},
        err
      );
    }
  }

  function normalizeCoreError(err) {
    try {
      var normalized = ensureCoreError(
        err,
        "create_core_error",
        "Create Core error."
      );

      return {
        code: normalized.code || normalized.name || "create_core_error",
        message: normalized.message || "Create Core error.",
        name: normalized.name || "Error",
        status: normalized.status || null,
        action: normalized.action || null,
        dependency: normalized.dependency || null,
        details: normalized.details || null,
        component: normalized.component || GLOBAL_NAME
      };
    } catch (normalizationError) {
      return {
        code: "create_core_error",
        message: "Create Core error could not be normalized.",
        name: "Error",
        status: null,
        action: null,
        dependency: null,
        details: null,
        component: GLOBAL_NAME
      };
    }
  }

  function buildCoreFailure(kind, err, extra) {
    try {
      var normalizedError = normalizeCoreError(err);
      var code = String(normalizedError.code || "").toLowerCase();
      var status = CORE_STATUS_BLOCKED;

      if (
        code.indexOf("unavailable") !== -1 ||
        code.indexOf("timeout") !== -1 ||
        code.indexOf("missing_api") !== -1
      ) {
        status = CORE_STATUS_UNAVAILABLE;
      }

      var payload = Object.assign({
        ok: false,
        ready: false,
        healthy: false,
        operational: false,
        status: status,
        kind: kind || "core",
        component: GLOBAL_NAME,
        version: CORE_VERSION,
        error: normalizedError
      }, extra || {});

      payload.ok = false;
      payload.ready = false;
      payload.operational = false;
      payload.error = normalizedError;
      payload.status = payload.status || status;

      return payload;
    } catch (buildError) {
      return {
        ok: false,
        ready: false,
        healthy: false,
        operational: false,
        status: CORE_STATUS_UNAVAILABLE,
        kind: kind || "core",
        component: GLOBAL_NAME,
        version: CORE_VERSION,
        error: {
          code: "core_failure_result_error",
          message: "Create Core failure result could not be created."
        }
      };
    }
  }

  function shouldReject(options) {
    try {
      return !!(options && options.rejectOnError === true);
    } catch (err) {
      return false;
    }
  }

  function setCoreStatus(status, err, details) {
    try {
      var nextStatus = String(status || CORE_STATUS_CREATED).trim().toLowerCase() || CORE_STATUS_CREATED;
      var normalizedError = err ? normalizeCoreError(err) : null;

      state.status = nextStatus;
      state.coreReady = nextStatus === CORE_STATUS_READY;
      state.operational = state.coreReady;
      state.lastError = err || null;
      state.lastFailure = normalizedError;

      safeSetAttribute(
        document.documentElement,
        "data-vp-create-core-initialized",
        state.initialized ? "true" : "false"
      );
      safeSetAttribute(
        document.documentElement,
        "data-vp-create-core-context-ready",
        state.contextReady ? "true" : "false"
      );
      safeSetAttribute(
        document.documentElement,
        "data-vp-create-core-ready",
        state.coreReady ? "true" : "false"
      );
      safeSetAttribute(
        document.documentElement,
        "data-vp-create-core-operational",
        state.operational ? "true" : "false"
      );
      safeSetAttribute(
        document.documentElement,
        "data-vp-create-core-status",
        nextStatus
      );
      safeSetAttribute(
        document.documentElement,
        "data-vp-create-core-version",
        CORE_VERSION
      );
      safeSetAttribute(
        document.documentElement,
        "data-vp-create-variant-profiles-ready",
        state.variantProfilesReady ? "true" : "false"
      );

      dispatch("vectoplan:create:core-status-changed", {
        component: GLOBAL_NAME,
        version: CORE_VERSION,
        initialized: state.initialized,
        contextReady: state.contextReady,
        ready: state.coreReady,
        operational: state.operational,
        status: nextStatus,
        error: normalizedError,
        details: details || null,
        dependencies: cloneObject(state.dependencies)
      });

      return nextStatus;
    } catch (statusError) {
      state.status = String(status || CORE_STATUS_CREATED);
      state.coreReady = state.status === CORE_STATUS_READY;
      state.operational = state.coreReady;
      state.lastError = err || null;
      return state.status;
    }
  }

  function getVariantProfilesApi() {
    try {
      var api = window.VectoplanCreateVariantProfiles;

      if (!api || typeof api !== "object") {
        return null;
      }

      return api;
    } catch (err) {
      return null;
    }
  }

  function getVariantProfilesReadiness() {
    try {
      var profileApi = getVariantProfilesApi();

      if (!profileApi) {
        return {
          ok: false,
          ready: false,
          operational: false,
          status: CORE_STATUS_UNAVAILABLE,
          error: {
            code: "variant_profiles_api_missing",
            message: "VectoplanCreateVariantProfiles is not available."
          }
        };
      }

      if (typeof profileApi.getReadiness === "function") {
        var readiness = profileApi.getReadiness();

        if (readiness && typeof readiness === "object") {
          return readiness;
        }
      }

      if (typeof profileApi.getState === "function") {
        var profileState = profileApi.getState();

        if (profileState && typeof profileState === "object") {
          return {
            ok: profileState.ready === true || profileState.operational === true,
            ready: profileState.ready === true || profileState.operational === true,
            operational: profileState.ready === true || profileState.operational === true,
            status: profileState.status || (
              profileState.ready === true || profileState.operational === true
                ? CORE_STATUS_READY
                : CORE_STATUS_INITIALIZED
            ),
            state: profileState
          };
        }
      }

      var operational = typeof profileApi.isOperational === "function"
        ? profileApi.isOperational() === true
        : false;

      return {
        ok: operational,
        ready: operational,
        operational: operational,
        status: operational ? CORE_STATUS_READY : CORE_STATUS_INITIALIZED
      };
    } catch (err) {
      return buildCoreFailure("variant_profiles_readiness", err, {
        dependency: "variant_profiles"
      });
    }
  }

  function waitForVariantProfilesApi(options) {
    var config = options || {};
    var timeoutMs = parseInt(
      config.timeoutMs !== undefined
        ? config.timeoutMs
        : DEFAULT_CORE_READINESS_TIMEOUT_MS,
      10
    );
    var pollMs = parseInt(
      config.pollMs !== undefined
        ? config.pollMs
        : DEFAULT_CORE_READINESS_POLL_MS,
      10
    );

    if (!Number.isFinite(timeoutMs) || timeoutMs < 100) {
      timeoutMs = DEFAULT_CORE_READINESS_TIMEOUT_MS;
    }

    if (!Number.isFinite(pollMs) || pollMs < 10) {
      pollMs = DEFAULT_CORE_READINESS_POLL_MS;
    }

    return new Promise(function (resolve, reject) {
      var startedAt = Date.now();
      var settled = false;
      var timer = null;

      function cleanup() {
        try {
          if (timer !== null) {
            window.clearTimeout(timer);
            timer = null;
          }

          document.removeEventListener(
            "vectoplan:create:variant-profiles-initialized",
            handleCandidateEvent
          );
          document.removeEventListener(
            "vectoplan:create:variant-profiles-ready",
            handleCandidateEvent
          );
        } catch (cleanupError) {
          /* no-op */
        }
      }

      function finishResolve(api) {
        if (settled) {
          return;
        }

        settled = true;
        cleanup();
        resolve(api);
      }

      function finishReject(err) {
        if (settled) {
          return;
        }

        settled = true;
        cleanup();
        reject(err);
      }

      function check() {
        var api = getVariantProfilesApi();

        if (api) {
          finishResolve(api);
          return;
        }

        if (Date.now() - startedAt >= timeoutMs) {
          finishReject(createCoreError(
            "variant_profiles_api_timeout",
            "VectoplanCreateVariantProfiles was not available within " + String(timeoutMs) + " ms.",
            {
              dependency: "variant_profiles",
              timeoutMs: timeoutMs
            }
          ));
          return;
        }

        timer = window.setTimeout(check, pollMs);
      }

      function handleCandidateEvent() {
        check();
      }

      try {
        document.addEventListener(
          "vectoplan:create:variant-profiles-initialized",
          handleCandidateEvent
        );
        document.addEventListener(
          "vectoplan:create:variant-profiles-ready",
          handleCandidateEvent
        );
      } catch (eventError) {
        /* Polling remains available. */
      }

      check();
    });
  }

  function validateVariantProfilesReadiness(result, profileApi) {
    try {
      var readiness = result && typeof result === "object"
        ? result
        : getVariantProfilesReadiness();
      var apiOperational = profileApi && typeof profileApi.isOperational === "function"
        ? profileApi.isOperational() === true
        : false;
      var ready = readiness.ready === true ||
        readiness.operational === true ||
        (
          readiness.ok === true &&
          (
            apiOperational ||
            String(readiness.status || "").toLowerCase() === CORE_STATUS_READY
          )
        );

      if (!ready) {
        return buildCoreFailure(
          "variant_profiles_readiness",
          createCoreError(
            "variant_profiles_not_ready",
            "Variant Profiles are initialized but not operational.",
            {
              dependency: "variant_profiles",
              readiness: readiness
            }
          ),
          {
            dependency: "variant_profiles",
            result: readiness
          }
        );
      }

      var variantProfileId = String(
        readiness.variant_profile_id ||
        readiness.variantProfileId ||
        getNested(readiness, ["bundle", "variant_profile_id"], "") ||
        getNested(readiness, ["bundle", "variantProfileId"], "") ||
        ""
      ).trim();

      return {
        ok: true,
        ready: true,
        healthy: true,
        operational: true,
        status: CORE_STATUS_READY,
        dependency: "variant_profiles",
        variant_profile_id: variantProfileId,
        family_profile_id: String(
          readiness.family_profile_id ||
          readiness.familyProfileId ||
          getNested(readiness, ["bundle", "family_profile_id"], "") ||
          getNested(readiness, ["bundle", "familyProfileId"], "") ||
          ""
        ).trim(),
        object_kind: String(
          readiness.object_kind ||
          readiness.objectKind ||
          getNested(readiness, ["bundle", "context", "object_kind"], "") ||
          DEFAULT_STARTER_OBJECT_KIND
        ).trim(),
        result: readiness
      };
    } catch (err) {
      return buildCoreFailure("variant_profiles_readiness", err, {
        dependency: "variant_profiles",
        result: result || null
      });
    }
  }

  function evaluateCriticalDependencies() {
    try {
      var contextReady = state.contextReady === true;
      var definitionsAreReady = definitionsReady();
      var variantReadiness = getVariantProfilesReadiness();
      var variantProfilesAreReady = variantReadiness.ready === true ||
        variantReadiness.operational === true;
      var errors = [];

      if (!contextReady) {
        errors.push({
          code: "core_context_not_ready",
          message: "Create Core context is not ready."
        });
      }

      if (!variantProfilesAreReady) {
        errors.push({
          code: "variant_profiles_not_ready",
          message: "Variant Profiles are not ready.",
          readiness: variantReadiness
        });
      }

      return {
        ok: errors.length === 0,
        ready: errors.length === 0,
        operational: errors.length === 0,
        status: errors.length === 0 ? CORE_STATUS_READY : CORE_STATUS_BLOCKED,
        contextReady: contextReady,
        definitionsReady: definitionsAreReady,
        variantProfilesReady: variantProfilesAreReady,
        variantProfiles: variantReadiness,
        errors: errors
      };
    } catch (err) {
      return buildCoreFailure("critical_dependencies", err);
    }
  }

  function ensureCoreReady(options) {
    var config = options || {};

    try {
      if (
        state.coreReady === true &&
        state.readinessResult &&
        config.force !== true &&
        config.forceReload !== true
      ) {
        return Promise.resolve(state.readinessResult);
      }

      if (
        state.readinessPromise &&
        config.force !== true &&
        config.forceReload !== true
      ) {
        return state.readinessPromise;
      }

      state.readinessGeneration += 1;
      var generation = state.readinessGeneration;

      if (config.refreshContext !== false) {
        refreshContext();
      }

      setCoreStatus(CORE_STATUS_LOADING, null, {
        source: config.source || "ensure_core_ready"
      });

      var readinessPromise = waitForVariantProfilesApi(config)
        .then(function (profileApi) {
          var readinessMethod = null;

          if (typeof profileApi.whenReady === "function") {
            readinessMethod = profileApi.whenReady;
          } else if (typeof profileApi.waitUntilReady === "function") {
            readinessMethod = profileApi.waitUntilReady;
          } else if (typeof profileApi.runReadinessCheck === "function") {
            readinessMethod = profileApi.runReadinessCheck;
          }

          if (!readinessMethod) {
            var immediateReadiness = getVariantProfilesReadiness();

            if (
              immediateReadiness.ready === true ||
              immediateReadiness.operational === true
            ) {
              return {
                profileApi: profileApi,
                readiness: immediateReadiness
              };
            }

            throw createCoreError(
              "variant_profiles_readiness_api_missing",
              "Variant Profiles API does not expose whenReady(), waitUntilReady() or runReadinessCheck().",
              {
                dependency: "variant_profiles"
              }
            );
          }

          return Promise.resolve(readinessMethod.call(profileApi, {
            source: config.source || "create_core",
            force: config.force === true || config.forceReload === true,
            rejectOnError: false,
            context: config.context || null
          })).then(function (readiness) {
            return {
              profileApi: profileApi,
              readiness: readiness
            };
          });
        })
        .then(function (resolved) {
          var validated = validateVariantProfilesReadiness(
            resolved.readiness,
            resolved.profileApi
          );

          if (!validated.ok || !validated.ready) {
            throw createCoreError(
              "variant_profiles_not_ready",
              getNested(
                validated,
                ["error", "message"],
                "Variant Profiles are not ready."
              ),
              {
                dependency: "variant_profiles",
                readiness: validated
              }
            );
          }

          var dependencySummary = evaluateCriticalDependencies();

          if (!dependencySummary.ok && dependencySummary.contextReady !== true) {
            throw createCoreError(
              "core_context_not_ready",
              "Create Core context is not ready.",
              {
                dependency: "context",
                dependencies: dependencySummary
              }
            );
          }

          var result = {
            ok: true,
            ready: true,
            healthy: true,
            operational: true,
            status: CORE_STATUS_READY,
            component: GLOBAL_NAME,
            version: CORE_VERSION,
            source: config.source || "ensure_core_ready",
            contextReady: state.contextReady,
            definitionsReady: definitionsReady(),
            variantProfilesReady: true,
            variantProfiles: validated,
            dependencies: dependencySummary,
            starter: {
              object_kind: validated.object_kind || DEFAULT_STARTER_OBJECT_KIND,
              family_profile_id: validated.family_profile_id || DEFAULT_STARTER_FAMILY_PROFILE_ID,
              variant_profile_id: validated.variant_profile_id || DEFAULT_STARTER_VARIANT_PROFILE_ID
            }
          };

          if (generation === state.readinessGeneration) {
            state.variantProfilesReady = true;
            state.dependencies.context = {
              ready: state.contextReady,
              status: state.contextReady ? CORE_STATUS_READY : CORE_STATUS_BLOCKED,
              error: null
            };
            state.dependencies.definitions = {
              ready: definitionsReady(),
              status: definitionsReady() ? CORE_STATUS_READY : CORE_STATUS_INITIALIZED,
              error: null
            };
            state.dependencies.variantProfiles = {
              ready: true,
              status: CORE_STATUS_READY,
              error: null,
              result: clone(validated)
            };
            state.readinessResult = result;
            state.lastError = null;
            state.lastFailure = null;

            setCoreStatus(CORE_STATUS_READY, null, result);

            var readySignature = safeJsonStringify({
              version: CORE_VERSION,
              variant_profile_id: result.starter.variant_profile_id,
              family_profile_id: result.starter.family_profile_id,
              object_kind: result.starter.object_kind
            }, "");

            if (readySignature !== state.lastReadySignature) {
              state.lastReadySignature = readySignature;

              info("Create Core operational.", {
                version: CORE_VERSION,
                variant_profile_id: result.starter.variant_profile_id,
                family_profile_id: result.starter.family_profile_id,
                object_kind: result.starter.object_kind
              });

              dispatch("vectoplan:create:core-ready", snapshot());
              dispatch("vectoplan:create:core-operational", result);
            }
          }

          return result;
        })
        .catch(function (err) {
          var normalized = ensureCoreError(
            err,
            "core_readiness_failed",
            "Create Core could not become operational."
          );
          var failed = buildCoreFailure("core_readiness", normalized, {
            source: config.source || "ensure_core_ready",
            dependencies: evaluateCriticalDependencies()
          });

          if (generation === state.readinessGeneration) {
            state.variantProfilesReady = false;
            state.dependencies.variantProfiles = {
              ready: false,
              status: failed.status,
              error: failed.error,
              result: failed
            };
            state.readinessResult = failed;
            state.lastError = normalized;
            state.lastFailure = failed;

            setCoreStatus(
              failed.status === CORE_STATUS_UNAVAILABLE
                ? CORE_STATUS_UNAVAILABLE
                : CORE_STATUS_BLOCKED,
              normalized,
              failed
            );

            dispatch("vectoplan:create:core-blocked", failed);
          }

          if (shouldReject(config)) {
            throw normalized;
          }

          return failed;
        });

      state.readinessPromise = readinessPromise.then(function (result) {
        if (generation === state.readinessGeneration) {
          state.readinessPromise = null;
        }

        return result;
      }, function (err) {
        if (generation === state.readinessGeneration) {
          state.readinessPromise = null;
        }

        throw ensureCoreError(
          err,
          "core_readiness_failed",
          "Create Core could not become operational."
        );
      });

      return state.readinessPromise;
    } catch (err) {
      var setupError = ensureCoreError(
        err,
        "core_readiness_setup_failed",
        "Create Core readiness could not be prepared."
      );
      var setupFailure = buildCoreFailure("core_readiness", setupError, {
        source: config.source || "ensure_core_ready"
      });

      state.readinessResult = setupFailure;
      state.lastError = setupError;
      state.lastFailure = setupFailure;
      setCoreStatus(CORE_STATUS_UNAVAILABLE, setupError, setupFailure);

      if (shouldReject(config)) {
        return Promise.reject(setupError);
      }

      return Promise.resolve(setupFailure);
    }
  }

  function whenReady(options) {
    return ensureCoreReady(options || {});
  }

  function isOperational() {
    return state.coreReady === true && state.operational === true;
  }

  function actionRequiresCoreReady(action) {
    try {
      var normalized = normalizeRouteAction(action);
      var dashed = dashRouteAction(normalized);
      var camel = camelRouteAction(normalized);

      return CRITICAL_ACTIONS[normalized] === true ||
        CRITICAL_ACTIONS[dashed] === true ||
        CRITICAL_ACTIONS[camel] === true;
    } catch (err) {
      return false;
    }
  }

  function ensureActionReady(action, options) {
    var config = options || {};
    var normalizedAction = normalizeRouteAction(action);

    try {
      if (!actionRequiresCoreReady(normalizedAction)) {
        return Promise.resolve({
          ok: true,
          ready: true,
          operational: state.operational,
          status: state.status,
          action: normalizedAction,
          bypassed: true,
          reason: "action_does_not_require_core_readiness"
        });
      }

      return ensureCoreReady({
        source: config.source || "action:" + normalizedAction,
        force: config.force === true,
        forceReload: config.forceReload === true,
        rejectOnError: false,
        timeoutMs: config.timeoutMs,
        context: config.context || null
      }).then(function (readiness) {
        if (readiness && readiness.ready === true && readiness.ok === true) {
          return Object.assign({}, readiness, {
            action: normalizedAction,
            actionReady: true
          });
        }

        var blockedError = createCoreError(
          "action_blocked_core_not_ready",
          actionLabel(normalizedAction) + " cannot start because Create Core is not ready.",
          {
            action: normalizedAction,
            readiness: readiness
          }
        );
        var blocked = buildCoreFailure("action_readiness", blockedError, {
          action: normalizedAction,
          actionReady: false,
          readiness: readiness
        });

        dispatch("vectoplan:create:action-blocked", blocked);

        if (shouldReject(config)) {
          throw blockedError;
        }

        return blocked;
      });
    } catch (err) {
      var failed = buildCoreFailure("action_readiness", err, {
        action: normalizedAction,
        actionReady: false
      });

      dispatch("vectoplan:create:action-blocked", failed);

      if (shouldReject(config)) {
        return Promise.reject(ensureCoreError(
          err,
          "action_readiness_failed",
          actionLabel(normalizedAction) + " readiness failed.",
          {
            action: normalizedAction
          }
        ));
      }

      return Promise.resolve(failed);
    }
  }

  function runWhenReady(action, callback, options) {
    var config = options || {};
    var normalizedAction = normalizeRouteAction(action);

    if (typeof callback !== "function") {
      return Promise.resolve(buildCoreFailure(
        "action_callback",
        createCoreError(
          "action_callback_missing",
          "No callback was supplied for " + actionLabel(normalizedAction) + ".",
          {
            action: normalizedAction
          }
        ),
        {
          action: normalizedAction
        }
      ));
    }

    return ensureActionReady(normalizedAction, config)
      .then(function (readiness) {
        if (!readiness || readiness.ok !== true || readiness.ready !== true) {
          return readiness;
        }

        try {
          return Promise.resolve(callback(readiness));
        } catch (callbackError) {
          throw ensureCoreError(
            callbackError,
            "action_callback_failed",
            actionLabel(normalizedAction) + " failed.",
            {
              action: normalizedAction
            }
          );
        }
      })
      .catch(function (err) {
        var failed = buildCoreFailure("action", err, {
          action: normalizedAction
        });

        if (shouldReject(config)) {
          throw ensureCoreError(
            err,
            "action_failed",
            actionLabel(normalizedAction) + " failed.",
            {
              action: normalizedAction
            }
          );
        }

        return failed;
      });
  }

  function bindDependencyEvents() {
    try {
      if (state.dependencyEventsBound) {
        return false;
      }

      document.addEventListener(
        "vectoplan:create:variant-profiles-status-changed",
        function (event) {
          try {
            var detail = event && event.detail ? event.detail : {};
            var ready = detail.ready === true || detail.operational === true;

            state.variantProfilesReady = ready;
            state.dependencies.variantProfiles = {
              ready: ready,
              status: detail.status || (
                ready ? CORE_STATUS_READY : CORE_STATUS_INITIALIZED
              ),
              error: detail.error || null,
              result: clone(detail)
            };

            safeSetAttribute(
              document.documentElement,
              "data-vp-create-variant-profiles-ready",
              ready ? "true" : "false"
            );

            if (ready) {
              ensureCoreReady({
                source: "variant_profiles_status_changed",
                rejectOnError: false
              }).catch(function (readinessError) {
                warn(
                  "Create Core readiness after Variant Profiles status change failed.",
                  readinessError
                );
              });
            } else if (state.coreReady) {
              setCoreStatus(
                CORE_STATUS_BLOCKED,
                createCoreError(
                  "variant_profiles_lost_readiness",
                  "Variant Profiles are no longer operational.",
                  {
                    dependency: "variant_profiles",
                    detail: detail
                  }
                ),
                detail
              );
            }
          } catch (eventError) {
            warn("Variant Profiles status event handling failed.", eventError);
          }
        }
      );

      document.addEventListener(
        "vectoplan:create:variant-profiles-ready",
        function () {
          ensureCoreReady({
            source: "variant_profiles_ready_event",
            rejectOnError: false
          }).catch(function (readinessError) {
            warn(
              "Create Core readiness after Variant Profiles ready event failed.",
              readinessError
            );
          });
        }
      );

      document.addEventListener(
        "vectoplan:create:definitions-ready",
        function (event) {
          try {
            var detail = event && event.detail ? event.detail : {};

            if (detail.definitions && typeof detail.definitions === "object") {
              state.definitions = cloneObject(detail.definitions);
            }

            state.dependencies.definitions = {
              ready: definitionsReady(),
              status: definitionsReady()
                ? CORE_STATUS_READY
                : CORE_STATUS_INITIALIZED,
              error: null
            };

            safeSetAttribute(
              document.documentElement,
              "data-vp-create-definitions-ready",
              definitionsReady() ? "true" : "false"
            );
          } catch (definitionsEventError) {
            warn("Definitions-ready event handling failed.", definitionsEventError);
          }
        }
      );

      state.dependencyEventsBound = true;
      return true;
    } catch (err) {
      warn("Create Core dependency event binding failed.", err);
      return false;
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
      state.generatorContext = resolveContextBundle("generatorContext");
      state.options = resolveContextBundle("options");
      state.health = resolveContextBundle("health");
      state.uiState = resolveContextBundle("uiState");
      state.wizard = resolveContextBundle("wizard");
      state.uploads = resolveContextBundle("uploads");
      state.payloadContract = resolveContextBundle("payloadContract");
      state.definitions = resolveContextBundle("definitions");
      state.routes = resolveRoutesBundle(page, app, form, state.context);

      state.apiPrefix = resolveApiPrefix(page, app, form, state.context);
      state.definitionsApiPrefix = resolveApiPrefixValue(
        "definitions",
        DEFAULT_DEFINITIONS_API_PREFIX,
        state.context,
        page,
        app,
        form
      );
      state.taxonomyApiPrefix = resolveApiPrefixValue(
        "taxonomy",
        DEFAULT_TAXONOMY_API_PREFIX,
        state.context,
        page,
        app,
        form
      );
      state.filesApiPrefix = resolveApiPrefixValue(
        "files",
        DEFAULT_FILES_API_PREFIX,
        state.context,
        page,
        app,
        form
      );

      state.themeStorageKey = getNested(
        state.context,
        ["theme", "storage_key"],
        getNested(state.context, ["theme", "storageKey"], DEFAULT_THEME_STORAGE_KEY)
      );

      state.theme = normalizeTheme(
        getNested(state.uiState, ["theme"], "") ||
        getNested(state.context, ["theme", "current"], "") ||
        getNested(state.context, ["theme", "default"], "") ||
        getPageTheme(page, app) ||
        safeLocalStorageGet(state.themeStorageKey) ||
        "dark"
      );

      refreshWizardConfig(app, form);

      state.contextReady = true;
      state.dependencies.context = {
        ready: true,
        status: CORE_STATUS_READY,
        error: null
      };
      state.dependencies.definitions = {
        ready: definitionsReady(),
        status: definitionsReady()
          ? CORE_STATUS_READY
          : CORE_STATUS_INITIALIZED,
        error: null
      };

      safeSetAttribute(
        document.documentElement,
        "data-vp-create-core-context-ready",
        "true"
      );
      safeSetAttribute(
        document.documentElement,
        "data-vp-create-core-ready",
        state.coreReady ? "true" : "false"
      );
      safeSetAttribute(
        document.documentElement,
        "data-vp-create-core-operational",
        state.operational ? "true" : "false"
      );
      safeSetAttribute(document.documentElement, "data-vp-create-core-version", CORE_VERSION);
      safeSetAttribute(document.documentElement, "data-vp-create-theme", state.theme);
      safeSetAttribute(document.documentElement, "data-vp-create-generator-context-ready", hasGeneratorContext() ? "true" : "false");
      safeSetAttribute(document.documentElement, "data-vp-create-definitions-ready", definitionsReady() ? "true" : "false");

      dispatch("vectoplan:create:core-context-refreshed", {
        apiPrefix: state.apiPrefix,
        definitionsApiPrefix: state.definitionsApiPrefix,
        taxonomyApiPrefix: state.taxonomyApiPrefix,
        filesApiPrefix: state.filesApiPrefix,
        routes: cloneObject(state.routes),
        stepCount: state.stepCount,
        currentStep: state.currentStep,
        theme: state.theme,
        writeEnabled: isWriteEnabled(),
        initialized: state.initialized,
        contextReady: state.contextReady,
        coreReady: state.coreReady,
        operational: state.operational,
        status: state.status,
        generatorContextReady: hasGeneratorContext(),
        definitionsReady: definitionsReady(),
        variantProfilesReady: state.variantProfilesReady
      });

      return snapshot();
    } catch (err) {
      state.contextReady = false;
      state.coreReady = false;
      state.operational = false;
      state.dependencies.context = {
        ready: false,
        status: CORE_STATUS_UNAVAILABLE,
        error: normalizeCoreError(err)
      };
      state.lastError = err;
      setCoreStatus(CORE_STATUS_UNAVAILABLE, err, {
        source: "refresh_context"
      });
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
      var contextObject = window.VectoplanCreateContext && typeof window.VectoplanCreateContext === "object"
        ? window.VectoplanCreateContext
        : null;

      var generatorObject = window.VectoplanGeneratorContext && typeof window.VectoplanGeneratorContext === "object"
        ? window.VectoplanGeneratorContext
        : null;

      if (name === "generatorContext") {
        if (generatorObject) {
          return cloneObject(generatorObject);
        }

        if (contextObject && contextObject.generatorContext) {
          return cloneObject(contextObject.generatorContext);
        }

        if (contextObject && contextObject.generator_context) {
          return cloneObject(contextObject.generator_context);
        }

        return readJsonScript(SELECTORS.generatorContextJson, {});
      }

      if (name === "payloadContract") {
        if (window.VectoplanCreatePayloadContract) {
          return cloneObject(window.VectoplanCreatePayloadContract);
        }

        if (contextObject && contextObject.payloadContract) {
          return cloneObject(contextObject.payloadContract);
        }

        if (contextObject && contextObject.payload_contract) {
          return cloneObject(contextObject.payload_contract);
        }

        return readJsonScript(SELECTORS.payloadContractJson, {});
      }

      if (contextObject) {
        if (name === "context" && contextObject.context) {
          return cloneObject(contextObject.context);
        }

        if (name === "context") {
          return cloneObject(contextObject);
        }

        if (name === "options" && contextObject.options) {
          return cloneObject(contextObject.options);
        }

        if (name === "health" && contextObject.health) {
          return cloneObject(contextObject.health);
        }

        if (name === "uiState" && contextObject.uiState) {
          return cloneObject(contextObject.uiState);
        }

        if (name === "uiState" && contextObject.ui_state) {
          return cloneObject(contextObject.ui_state);
        }

        if (name === "wizard" && contextObject.wizard) {
          return cloneObject(contextObject.wizard);
        }

        if (name === "uploads" && contextObject.uploadConfig) {
          return cloneObject(contextObject.uploadConfig);
        }

        if (name === "uploads" && contextObject.uploads) {
          return cloneObject(contextObject.uploads);
        }

        if (name === "definitions" && contextObject.definitionsApi) {
          return cloneObject(contextObject.definitionsApi);
        }

        if (name === "definitions" && contextObject.definitions) {
          return cloneObject(contextObject.definitions);
        }
      }

      if (name === "uploads" && window.VectoplanCreateUploadConfig) {
        return cloneObject(window.VectoplanCreateUploadConfig);
      }

      if (name === "definitions" && window.VectoplanCreateDefinitions) {
        return cloneObject(window.VectoplanCreateDefinitions);
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

      if (name === "uploads") {
        return readJsonScript(SELECTORS.uploadsJson, {});
      }

      if (name === "definitions") {
        return readJsonScript(SELECTORS.definitionsJson, {});
      }

      return {};
    } catch (err) {
      warn("Context bundle resolution failed: " + name, err);
      return {};
    }
  }

  function resolveRoutesBundle(page, app, form, context) {
    try {
      var routes = cloneObject(DEFAULT_ROUTES);
      var contextRoutes = context && context.routes && typeof context.routes === "object" ? context.routes : {};
      var createRoutes = window.VectoplanCreateRoutes && typeof window.VectoplanCreateRoutes === "object" ? window.VectoplanCreateRoutes : {};

      routes = Object.assign(routes, cloneObject(contextRoutes), cloneObject(createRoutes));

      [
        "health",
        "options",
        "context",
        "create_context",
        "definitions_current",
        "draft",
        "persistent_draft",
        "validate",
        "package_plan",
        "publish_bundle",
        "download",
        "save",
        "cache_clear"
      ].forEach(function (key) {
        try {
          var dataName = "data-vp-route-" + key.replace(/_/g, "-");
          var dataNameLegacy = "data-create-route-" + key.replace(/_/g, "-");
          var value = "";

          [form, app, page].some(function (node) {
            if (!node) {
              return false;
            }

            value = node.getAttribute(dataName) || node.getAttribute(dataNameLegacy) || "";
            return !!value;
          });

          if (value) {
            routes[key] = value;
          }
        } catch (routeError) {
          warn("Route data attribute read skipped: " + key, routeError);
        }
      });

      routes.packagePlan = routes.packagePlan || routes.package_plan;
      routes["package-plan"] = routes["package-plan"] || routes.package_plan;
      routes.createContext = routes.createContext || routes.create_context;
      routes.definitionsCurrent = routes.definitionsCurrent || routes.definitions_current;
      routes.persistentDraft = routes.persistentDraft || routes.persistent_draft;
      routes.publishBundle = routes.publishBundle || routes.publish_bundle;
      routes.publishPrepare = routes.publishPrepare || routes.publish_prepare || routes.publish_bundle;
      routes["publish-prepare"] = routes["publish-prepare"] || routes.publish_prepare || routes.publish_bundle;
      routes.cacheClear = routes.cacheClear || routes.cache_clear;

      return routes;
    } catch (err) {
      warn("Routes bundle resolution failed.", err);
      return cloneObject(DEFAULT_ROUTES);
    }
  }

  function resolveApiPrefix(page, app, form, context) {
    try {
      var fromContext = context && (context.api_prefix || context.apiPrefix) || "";
      var fromWindow = window.VectoplanCreateApiPrefix || "";
      var fromForm = form ? form.getAttribute("data-create-api-prefix") || form.getAttribute("data-vp-api-prefix") || "" : "";
      var fromApp = app ? app.getAttribute("data-create-api-prefix") || app.getAttribute("data-vp-api-prefix") || "" : "";
      var fromPage = page ? page.getAttribute("data-create-api-prefix") || page.getAttribute("data-vp-api-prefix") || "" : "";

      return trimTrailingSlash(fromContext || fromWindow || fromForm || fromApp || fromPage || DEFAULT_API_PREFIX);
    } catch (err) {
      warn("API prefix resolution failed.", err);
      return DEFAULT_API_PREFIX;
    }
  }

  function resolveApiPrefixValue(kind, fallback, context, page, app, form) {
    try {
      var snake = kind + "_api_prefix";
      var camel = kind + "ApiPrefix";
      var windowName = "Vectoplan" + capitalize(kind) + "ApiPrefix";
      var fromContext = context && (context[snake] || context[camel]) || "";
      var fromWindow = window[windowName] || "";
      var attr = "data-vp-" + kind + "-api-prefix";
      var fromForm = form ? form.getAttribute(attr) || "" : "";
      var fromApp = app ? app.getAttribute(attr) || "" : "";
      var fromPage = page ? page.getAttribute(attr) || "" : "";

      return trimTrailingSlash(fromContext || fromWindow || fromForm || fromApp || fromPage || fallback);
    } catch (err) {
      return fallback;
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

      var key = step.key || "step-" + stepIndex;
      var target = step.target || step.panel || key || "step-" + stepIndex;

      if (stepIndex === 3 && (key === "object" || key === "variables" || target === "object-variants" || target === "variables")) {
        return {
          index: stepIndex,
          key: "variables",
          alias: step.alias || "object",
          aliases: step.aliases || ["object", "object-variants", "variables"],
          label: step.label && step.label !== "Objekt" ? step.label : "Variablen",
          short_label: step.short_label && step.short_label !== "Objekt" ? step.short_label : "Variablen",
          shortLabel: step.shortLabel && step.shortLabel !== "Objekt" ? step.shortLabel : "Variablen",
          description: step.description || "",
          hint: step.hint || step.description || "Variablen, Varianten und Unterlagen definieren.",
          target: "object-variants"
        };
      }

      if (stepIndex === 6 && (key === "create" || key === "actions" || target === "actions")) {
        return {
          index: stepIndex,
          key: "actions",
          alias: step.alias || "create",
          label: step.label || "Erzeugen",
          short_label: step.short_label || step.shortLabel || "Erzeugen",
          shortLabel: step.shortLabel || step.short_label || "Erzeugen",
          description: step.description || "",
          hint: step.hint || step.description || "Draft, Validierung, Package-Plan, Download oder Save ausführen.",
          target: "actions"
        };
      }

      return {
        index: stepIndex,
        key: key,
        alias: step.alias || "",
        aliases: step.aliases || [],
        label: step.label || "Schritt " + stepIndex,
        short_label: step.short_label || step.shortLabel || step.label || String(stepIndex),
        shortLabel: step.shortLabel || step.short_label || step.label || String(stepIndex),
        description: step.description || "",
        hint: step.hint || step.description || "",
        target: target
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
        shortLabel: String(parsed),
        hint: "",
        target: "step-" + parsed
      };
    } catch (err) {
      return {
        index: stepIndex,
        key: "step-" + stepIndex,
        label: "Schritt " + stepIndex,
        short_label: String(stepIndex || ""),
        shortLabel: String(stepIndex || ""),
        hint: "",
        target: "step-" + stepIndex
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

      state.lockSequence += 1;
      var token = key + ":" + String(now) + ":" + String(state.lockSequence);

      state.locks[key] = {
        token: token,
        acquiredAt: now,
        expiresAt: now + ttl,
        ttlMs: ttl
      };

      return true;
    } catch (err) {
      warn("Lock acquisition failed.", err);
      return false;
    }
  }

  function refreshLock(name, token, ttlMs) {
    try {
      var key = String(name || "default");
      var lock = state.locks[key];

      if (!lock) {
        return false;
      }

      if (token && lock.token && lock.token !== token) {
        return false;
      }

      var ttl = parseInt(ttlMs || lock.ttlMs || DEFAULT_ASYNC_LOCK_TIMEOUT_MS, 10);

      if (!Number.isFinite(ttl) || ttl < 50) {
        ttl = DEFAULT_ASYNC_LOCK_TIMEOUT_MS;
      }

      lock.ttlMs = ttl;
      lock.expiresAt = Date.now() + ttl;

      return true;
    } catch (err) {
      warn("Lock refresh failed.", err);
      return false;
    }
  }

  function releaseLock(name, token) {
    try {
      var key = String(name || "default");
      var lock = state.locks[key];

      if (!lock) {
        return false;
      }

      if (token && lock.token && lock.token !== token) {
        return false;
      }

      delete state.locks[key];
      return true;
    } catch (err) {
      warn("Lock release failed.", err);
      return false;
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
    var key = String(name || "default");
    var token = null;

    try {
      if (typeof callback !== "function") {
        return undefined;
      }

      if (!acquireLock(key, ttlMs)) {
        return undefined;
      }

      token = state.locks[key] ? state.locks[key].token : null;

      var result;

      try {
        result = callback();
      } catch (callbackError) {
        releaseLock(key, token);
        throw callbackError;
      }

      if (result && typeof result.then === "function") {
        refreshLock(
          key,
          token,
          Math.max(
            parseInt(ttlMs || 0, 10) || 0,
            DEFAULT_ASYNC_LOCK_TIMEOUT_MS
          )
        );

        return Promise.resolve(result).then(function (value) {
          releaseLock(key, token);
          return value;
        }, function (err) {
          releaseLock(key, token);
          throw err;
        });
      }

      releaseLock(key, token);
      return result;
    } catch (err) {
      releaseLock(key, token);
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
      var nodes = qsa(SELECTORS.status);

      nodes.forEach(function (statusNode) {
        try {
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
        } catch (nodeError) {
          warn("Set status node failed.", nodeError);
        }
      });

      dispatch("vectoplan:create:core-status-changed", {
        message: message || "",
        state: stateName || "idle"
      });
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
      if (!selector) {
        return null;
      }

      var scope = root || document;
      return scope.querySelector(selector);
    } catch (err) {
      warn("querySelector failed: " + selector, err);
      return null;
    }
  }

  function qsa(selector, root) {
    try {
      if (!selector) {
        return [];
      }

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

      return !!node;
    } catch (err) {
      warn("Set text failed.", err);
      return false;
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
        return true;
      }

      return false;
    } catch (err) {
      return false;
    }
  }

  function safeRemoveAttribute(node, name) {
    try {
      if (node && name) {
        node.removeAttribute(name);
        return true;
      }

      return false;
    } catch (err) {
      return false;
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

      if (field.length && !field.nodeType && typeof field.value === "undefined") {
        return field[0] && typeof field[0].value !== "undefined" ? String(field[0].value) : "";
      }

      return typeof field.value !== "undefined" ? String(field.value) : "";
    } catch (err) {
      return "";
    }
  }

  function setFieldValue(form, name, value, options) {
    try {
      if (!form || !name) {
        return false;
      }

      var safeOptions = options || {};
      var field = form.elements ? form.elements[name] : null;

      if (!field) {
        field = qs("[name='" + cssEscape(name) + "']", form);
      }

      if (!field || typeof field.value === "undefined") {
        return false;
      }

      var next = typeof value === "undefined" || value === null ? "" : String(value);

      if (field.value === next && safeOptions.force !== true) {
        return false;
      }

      field.value = next;

      if (safeOptions.emitNativeEvents !== false) {
        dispatchNativeEvent(field, "input");
        dispatchNativeEvent(field, "change");
      }

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
        field.setAttribute("data-vp-created-by", GLOBAL_NAME);
        form.appendChild(field);
      }

      if (typeof value !== "undefined" && field.value === "") {
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
        .replace(/ä/g, "ae")
        .replace(/ö/g, "oe")
        .replace(/ü/g, "ue")
        .replace(/ß/g, "ss")
        .replace(/[-\s]+/g, "_")
        .replace(/[^a-z0-9_./[\]-]/g, "")
        .replace(/_{2,}/g, "_")
        .replace(/^_+|_+$/g, "");

      return text || fallback || "";
    } catch (err) {
      return fallback || "";
    }
  }

  function normalizeTheme(value) {
    try {
      var text = String(value || "").trim().toLowerCase();

      if (text === "dark" || text === "light" || text === "system" || text === "black") {
        return text === "black" ? "dark" : text;
      }

      return "dark";
    } catch (err) {
      return "dark";
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

      if (["true", "1", "yes", "ja", "on", "enabled", "active", "ok", "healthy", "ready", "partial", "default", "selected"].indexOf(text) !== -1) {
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
          textarea.style.top = "0";
          document.body.appendChild(textarea);
          textarea.focus();
          textarea.select();

          var ok = document.execCommand("copy");
          textarea.remove();

          if (ok) {
            resolve();
          } else {
            reject(new Error("execCommand copy failed"));
          }
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
      save: "Speichern",
      "persist-draft": "Draft speichern",
      persistent_draft: "Draft speichern",
      persistentDraft: "Draft speichern",
      "publish-prepare": "Publish vorbereiten",
      publish_prepare: "Publish vorbereiten",
      publishBundle: "Publish vorbereiten"
    };

    return labels[action] || action || "Aktion";
  }

  function getPageTheme(page, app) {
    try {
      var fromApp = app ? app.getAttribute("data-vp-theme") || app.getAttribute("data-create-theme") || "" : "";
      var fromPage = page ? page.getAttribute("data-vp-theme") || page.getAttribute("data-create-theme") || "" : "";

      return fromApp || fromPage || "";
    } catch (err) {
      return "";
    }
  }

  function isWriteEnabled() {
    try {
      if (state.context && typeof state.context.write_enabled !== "undefined") {
        return toBoolean(state.context.write_enabled, false);
      }

      if (state.context && typeof state.context.writeEnabled !== "undefined") {
        return toBoolean(state.context.writeEnabled, false);
      }

      if (state.options && typeof state.options.write_enabled !== "undefined") {
        return toBoolean(state.options.write_enabled, false);
      }

      if (state.options && state.options.write && typeof state.options.write.enabled !== "undefined") {
        return toBoolean(state.options.write.enabled, false);
      }

      var actionSection = qs(SELECTORS.actionSection);
      var app = qs(SELECTORS.app);
      var page = qs(SELECTORS.page);

      if (actionSection && actionSection.getAttribute("data-create-write-enabled") === "true") {
        return true;
      }

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
      var routes = state.routes || {};
      var normalizedAction = normalizeRouteAction(action);
      var dashAction = dashRouteAction(normalizedAction);
      var camelAction = camelRouteAction(normalizedAction);
      var candidate = routes[normalizedAction] || routes[dashAction] || routes[camelAction] || "";

      if (candidate && typeof candidate === "object") {
        candidate = candidate.url || candidate.path || candidate.href || "";
      }

      if (!candidate) {
        candidate = DEFAULT_ROUTES[normalizedAction] || DEFAULT_ROUTES[dashAction] || DEFAULT_ROUTES[camelAction] || fallbackPath || "";
      }

      if (/^https?:\/\//i.test(candidate)) {
        return candidate;
      }

      if (candidate.charAt(0) === "/") {
        if (candidate.indexOf(state.apiPrefix + "/") === 0 || candidate === state.apiPrefix) {
          return candidate;
        }

        if (candidate.indexOf(DEFAULT_API_PREFIX + "/") === 0 || candidate === DEFAULT_API_PREFIX) {
          return candidate;
        }

        return trimTrailingSlash(state.apiPrefix) + candidate;
      }

      return trimTrailingSlash(state.apiPrefix) + "/" + String(candidate || "").replace(/^\/+/, "");
    } catch (err) {
      return trimTrailingSlash(state.apiPrefix || DEFAULT_API_PREFIX) + (fallbackPath || "");
    }
  }

  function normalizeRouteAction(action) {
    var value = String(action || "").replace(/-/g, "_");

    if (value === "package_plan") {
      return "package_plan";
    }

    if (value === "persist_draft" || value === "persistent_draft") {
      return "persistent_draft";
    }

    if (value === "publish_prepare" || value === "publish_bundle") {
      return "publish_bundle";
    }

    if (value === "create_context") {
      return "create_context";
    }

    return value;
  }

  function dashRouteAction(action) {
    return String(action || "").replace(/_/g, "-");
  }

  function camelRouteAction(action) {
    var normalized = String(action || "");
    var mapping = {
      package_plan: "packagePlan",
      create_context: "createContext",
      definitions_current: "definitionsCurrent",
      persistent_draft: "persistentDraft",
      publish_bundle: "publishBundle",
      publish_prepare: "publishPrepare",
      cache_clear: "cacheClear"
    };

    return mapping[normalized] || normalized;
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
      "identity.name": "family_name",
      "family.name": "family_name",
      "identity.description": "family_description",
      "family.description": "family_description",
      "taxonomy.domain": "domain",
      "taxonomy.category": "category",
      "taxonomy.subcategory": "subcategory",
      "taxonomy.path": "taxonomy_path",
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
      "profiles.family": "family_profile_id",
      "profiles.variant": "variant_profile_id",
      "variant.family_profile_id": "family_profile_id",
      "variant.variant_profile_id": "variant_profile_id",
      "payload.definition_variants_json": "definition_variants_json",
      "uploads.geometry_model": "geometry_model_uploads_json",
      "uploads.technical_documents": "technical_document_uploads_json",
      "uploads.variant_documents": "variant_document_uploads_json",
      "default_variant_id": "variants",
      "documents": "family_name",
      "draft": "family_name",
      "path": "family_name",
      "target_dir": "family_name",
      "write_enabled": "save"
    };

    try {
      var key = String(fieldName || "").trim();
      return mapping[key] || key;
    } catch (err) {
      return fieldName;
    }
  }

  function hasGeneratorContext() {
    try {
      return !!(state.generatorContext && Object.keys(state.generatorContext).length);
    } catch (err) {
      return false;
    }
  }

  function definitionsReady() {
    try {
      var profileApi = getVariantProfilesApi();

      if (profileApi) {
        if (
          typeof profileApi.getCacheSnapshot === "function"
        ) {
          var cacheSnapshot = profileApi.getCacheSnapshot();

          if (
            cacheSnapshot &&
            cacheSnapshot.definitionsLoaded === true
          ) {
            return true;
          }
        }

        if (typeof profileApi.getState === "function") {
          var profileState = profileApi.getState();

          if (
            profileState &&
            profileState.cache &&
            profileState.cache.definitionsLoaded === true
          ) {
            return true;
          }
        }
      }

      if (!state.definitions || typeof state.definitions !== "object") {
        return false;
      }

      if (state.definitions.ready === true || state.definitions.ok === true) {
        return true;
      }

      var counts = state.definitions.counts ||
        state.definitions.definitionCounts ||
        getNested(state.definitions, ["snapshot", "counts"], {}) ||
        {};

      if (
        counts.object_kinds ||
        counts.objectKinds ||
        counts.variant_profiles ||
        counts.variantProfiles
      ) {
        return true;
      }

      var datasets = state.definitions.datasets || {};

      return !!(
        (Array.isArray(datasets.object_kinds) && datasets.object_kinds.length) ||
        (Array.isArray(datasets.variant_profiles) && datasets.variant_profiles.length) ||
        (Array.isArray(state.definitions.object_kinds) && state.definitions.object_kinds.length) ||
        (Array.isArray(state.definitions.variant_profiles) && state.definitions.variant_profiles.length)
      );
    } catch (err) {
      return false;
    }
  }

  function snapshot() {
    try {
      return {
        version: CORE_VERSION,
        initialized: state.initialized,
        coreReady: state.coreReady,
        contextReady: state.contextReady,
        operational: state.operational,
        ready: state.coreReady,
        status: state.status,
        domReady: state.domReady,
        apiPrefix: state.apiPrefix,
        definitionsApiPrefix: state.definitionsApiPrefix,
        taxonomyApiPrefix: state.taxonomyApiPrefix,
        filesApiPrefix: state.filesApiPrefix,
        routes: cloneObject(state.routes),
        writeEnabled: isWriteEnabled(),
        pending: state.pending,
        theme: state.theme,
        generatorContextReady: hasGeneratorContext(),
        definitionsReady: definitionsReady(),
        variantProfilesReady: state.variantProfilesReady,
        readiness: clone(state.readinessResult),
        dependencies: cloneObject(state.dependencies),
        lastAction: state.lastAction,
        lastResult: clone(state.lastResult),
        lastError: state.lastError && state.lastError.message ? state.lastError.message : state.lastError ? String(state.lastError) : "",
        lastFailure: clone(state.lastFailure),
        wizard: {
          currentStep: state.currentStep,
          stepCount: state.stepCount,
          maxReachedStep: state.maxReachedStep,
          allowDirectStepClick: state.allowDirectStepClick,
          lockFutureSteps: state.lockFutureSteps,
          steps: clone(state.steps)
        },
        uploads: cloneObject(state.uploads),
        payloadContract: cloneObject(state.payloadContract),
        definitions: cloneObject(state.definitions),
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

  function bootstrapCore(options) {
    var config = options || {};

    try {
      state.bootstrapGeneration += 1;
      var generation = state.bootstrapGeneration;

      refreshContext();
      bindDependencyEvents();

      state.initialized = true;
      safeSetAttribute(
        document.documentElement,
        "data-vp-create-core-initialized",
        "true"
      );

      setCoreStatus(CORE_STATUS_INITIALIZED, null, {
        source: config.source || "bootstrap"
      });

      dispatch("vectoplan:create:core-initialized", snapshot());

      state.bootstrapPromise = ensureCoreReady({
        source: config.source || "bootstrap",
        force: config.force === true,
        rejectOnError: false,
        timeoutMs: config.timeoutMs,
        refreshContext: false
      }).then(function (readiness) {
        if (generation === state.bootstrapGeneration) {
          state.bootstrapPromise = null;
        }

        return readiness;
      }).catch(function (err) {
        if (generation === state.bootstrapGeneration) {
          state.bootstrapPromise = null;
        }

        var failed = buildCoreFailure("bootstrap", err, {
          source: config.source || "bootstrap"
        });

        state.lastError = err;
        state.lastFailure = failed;
        setCoreStatus(CORE_STATUS_UNAVAILABLE, err, failed);
        error("Core bootstrap readiness failed.", err);

        return failed;
      });

      return true;
    } catch (err) {
      state.initialized = false;
      state.contextReady = false;
      state.coreReady = false;
      state.operational = false;
      state.lastError = err;
      state.lastFailure = buildCoreFailure("bootstrap", err, {
        source: config.source || "bootstrap"
      });
      setCoreStatus(CORE_STATUS_UNAVAILABLE, err, state.lastFailure);
      error("Core bootstrap failed.", err);
      return false;
    }
  }

  function bootstrapCoreAsync(options) {
    var config = options || {};
    var started = bootstrapCore(config);

    if (!started) {
      return Promise.resolve(
        state.lastFailure ||
        buildCoreFailure(
          "bootstrap",
          createCoreError(
            "core_bootstrap_failed",
            "Create Core bootstrap failed."
          )
        )
      );
    }

    return state.bootstrapPromise ||
      state.readinessPromise ||
      ensureCoreReady({
        source: config.source || "bootstrap_async",
        rejectOnError: false,
        timeoutMs: config.timeoutMs
      });
  }

  function capitalize(value) {
    try {
      var text = String(value || "");
      return text.charAt(0).toUpperCase() + text.slice(1);
    } catch (err) {
      return "";
    }
  }

  var api = {
    version: CORE_VERSION,

    constants: {
      GLOBAL_NAME: GLOBAL_NAME,
      DEFAULT_API_PREFIX: DEFAULT_API_PREFIX,
      DEFAULT_DEFINITIONS_API_PREFIX: DEFAULT_DEFINITIONS_API_PREFIX,
      DEFAULT_TAXONOMY_API_PREFIX: DEFAULT_TAXONOMY_API_PREFIX,
      DEFAULT_FILES_API_PREFIX: DEFAULT_FILES_API_PREFIX,
      DEFAULT_THEME_STORAGE_KEY: DEFAULT_THEME_STORAGE_KEY,
      DEFAULT_LOCK_TIMEOUT_MS: DEFAULT_LOCK_TIMEOUT_MS,
      DEFAULT_ASYNC_LOCK_TIMEOUT_MS: DEFAULT_ASYNC_LOCK_TIMEOUT_MS,
      DEFAULT_CORE_READINESS_TIMEOUT_MS: DEFAULT_CORE_READINESS_TIMEOUT_MS,
      DEFAULT_CORE_READINESS_POLL_MS: DEFAULT_CORE_READINESS_POLL_MS,
      DEFAULT_STARTER_OBJECT_KIND: DEFAULT_STARTER_OBJECT_KIND,
      DEFAULT_STARTER_FAMILY_PROFILE_ID: DEFAULT_STARTER_FAMILY_PROFILE_ID,
      DEFAULT_STARTER_VARIANT_PROFILE_ID: DEFAULT_STARTER_VARIANT_PROFILE_ID,
      CRITICAL_ACTIONS: cloneObject(CRITICAL_ACTIONS)
    },

    selectors: SELECTORS,
    classes: STATE_CLASSES,
    previewShapeClasses: PREVIEW_SHAPE_CLASSES,
    defaultSteps: DEFAULT_STEPS,
    defaultRoutes: DEFAULT_ROUTES,
    state: state,

    onReady: onReady,
    bootstrap: bootstrapCore,
    bootstrapAsync: bootstrapCoreAsync,
    refreshContext: refreshContext,
    refreshWizardConfig: refreshWizardConfig,
    snapshot: snapshot,
    ensureReady: ensureCoreReady,
    whenReady: whenReady,
    waitUntilReady: whenReady,
    isOperational: isOperational,
    evaluateCriticalDependencies: evaluateCriticalDependencies,
    getVariantProfilesApi: getVariantProfilesApi,
    getVariantProfilesReadiness: getVariantProfilesReadiness,
    ensureActionReady: ensureActionReady,
    runWhenReady: runWhenReady,
    actionRequiresCoreReady: actionRequiresCoreReady,

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
    refreshLock: refreshLock,
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
    normalizeIssueFieldName: normalizeIssueFieldName,

    hasGeneratorContext: hasGeneratorContext,
    definitionsReady: definitionsReady,

    createError: createCoreError,
    ensureError: ensureCoreError,
    normalizeError: normalizeCoreError,
    buildFailureResult: buildCoreFailure,
    setCoreStatus: setCoreStatus,
    bindDependencyEvents: bindDependencyEvents
  };

  window[GLOBAL_NAME] = api;

  onReady(function () {
    bootstrapCore({
      source: "dom_ready",
      rejectOnError: false
    });
  });
})();