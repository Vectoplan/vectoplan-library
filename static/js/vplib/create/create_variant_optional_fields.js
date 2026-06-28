/* services/vectoplan-library/static/js/vplib/create/create_variant_optional_fields.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateVariantOptionalFields";
  var COMPONENT_NAME = "VPLIB Create Variant Optional Fields";
  var VERSION = "0.7.0";
  var READY_ATTR = "data-vp-create-variant-optional-fields";

  var SELECTORS = {
    drawerRoot: [
      "[data-vp-variant-drawer]",
      "[data-vp-variant-drawer-root]",
      ".vp-create-variant-drawer",
      ".vp-variant-drawer"
    ].join(","),

    drawerBody: [
      "[data-vp-variant-drawer-body]",
      "[data-vp-drawer-body]",
      ".vp-create-variant-drawer__body",
      ".vp-variant-drawer__body"
    ].join(","),

    drawerFields: [
      "[data-vp-variant-drawer-fields='true']",
      "[data-vp-variant-drawer-fields]",
      "[data-vp-variant-fields-root]",
      "[data-vp-variant-drawer-fields-root]",
      "[data-vp-fields-root]",
      ".vp-create-variant-drawer__fields",
      ".vp-create-variant-fields",
      ".vp-variant-fields"
    ].join(","),

    drawerSections: [
      "[data-vp-variant-drawer-sections='true']",
      "[data-vp-variant-drawer-sections]",
      ".vp-create-variant-drawer__sections"
    ].join(","),

    profileFieldsRoot: [
      "[data-vp-variant-drawer-sections='true']",
      "[data-vp-variant-drawer-sections]",
      "[data-vp-variant-fields-root]",
      "[data-vp-variant-drawer-fields-root]",
      "[data-vp-fields-root]",
      ".vp-create-variant-drawer__sections",
      ".vp-create-variant-fields",
      ".vp-variant-fields"
    ].join(","),

    summaryRoot: [
      "[data-vp-variant-summary]",
      "[data-vp-variant-drawer-summary]",
      ".vp-create-variant-summary",
      ".vp-variant-summary",
      ".vp-create-variant-drawer__summary"
    ].join(","),

    optionalRoot: [
      "[data-vp-variant-optional-fields-root='true']",
      "[data-vp-variant-optional-fields='true']",
      "[data-vp-variant-drawer-optional-fields='true']",
      ".vp-create-variant-optional-fields",
      ".vp-variant-optional-fields"
    ].join(","),

    optionalSlot: [
      "[data-vp-variant-optional-fields-slot]",
      "[data-vp-variant-drawer-additional-fields='true']"
    ].join(","),

    availableRoot: [
      "[data-vp-variant-optional-fields-available='true']",
      "[data-vp-variant-optional-fields-catalog='true']",
      "[data-vp-variant-optional-available='true']"
    ].join(","),

    availableColumns: [
      "[data-vp-variant-optional-fields-available-columns='true']",
      ".vp-create-variant-optional-fields__available-columns"
    ].join(","),

    availableList: [
      "[data-vp-variant-optional-fields-available-list='true']",
      "[data-vp-variant-optional-results]",
      "[data-vp-variant-optional-results='true']"
    ].join(","),

    selectedRoot: [
      "[data-vp-variant-optional-fields-selected='true']",
      "[data-vp-variant-optional-selected]",
      "[data-vp-variant-optional-selected='true']"
    ].join(","),

    selectedRows: [
      "[data-vp-variant-optional-fields-selected-rows='true']",
      "[data-vp-variant-optional-fields-selected-list='true']"
    ].join(","),

    selectedEmpty: [
      "[data-vp-variant-optional-fields-selected-empty='true']",
      "[data-vp-variant-optional-empty]",
      "[data-vp-variant-optional-empty='true']"
    ].join(","),

    availableCountNode: [
      "[data-vp-variant-optional-fields-available-count='true']",
      "[data-vp-variant-optional-count]",
      "[data-vp-variant-optional-count='true']"
    ].join(","),

    selectedCountNode: [
      "[data-vp-variant-optional-fields-selected-count='true']",
      "[data-vp-variant-optional-selected-count]",
      "[data-vp-variant-optional-selected-count='true']"
    ].join(","),

    statusNode: [
      "[data-vp-variant-optional-fields-status='true']",
      "[data-vp-variant-optional-status]",
      "[data-vp-variant-optional-status='true']"
    ].join(","),

    legacyTools: [
      "[data-vp-variant-optional-search]",
      "[data-vp-variant-optional-group]",
      "[data-vp-variant-optional-clear-search]",
      "[data-vp-variant-optional-refresh]",
      ".vp-variant-optional-fields__tools",
      ".vp-create-variant-optional-fields__tools"
    ].join(","),

    searchInput: "[data-vp-variant-optional-search]",
    groupSelect: "[data-vp-variant-optional-group]",

    addButton: [
      "[data-vp-variant-optional-add]",
      "[data-vp-add-additional-field]"
    ].join(","),

    removeButton: [
      "[data-vp-variant-optional-remove]",
      "[data-vp-remove-additional-field]",
      "[data-vp-optional-row-remove]"
    ].join(","),

    refreshButton: "[data-vp-variant-optional-refresh]",
    clearSearchButton: "[data-vp-variant-optional-clear-search]",

    valueControl: [
      "[data-vp-variant-optional-control]",
      "[data-vp-definition-value-key][data-vp-variable-key]",
      ".vp-create-variant-optional-fields__row-control input",
      ".vp-create-variant-optional-fields__row-control select",
      ".vp-create-variant-optional-fields__row-control textarea"
    ].join(","),

    valuesJson: [
      "input[name='variant_drawer_values_json']",
      "textarea[name='variant_drawer_values_json']",
      "input[name='definition_values_json']",
      "textarea[name='definition_values_json']",
      "[data-vp-variant-drawer-values-json]",
      "[data-vp-variant-drawer-values-json-field='true']"
    ].join(","),

    additionalKeysJson: [
      "input[name='variant_drawer_additional_field_keys_json']",
      "textarea[name='variant_drawer_additional_field_keys_json']",
      "input[name='additional_field_keys_json']",
      "textarea[name='additional_field_keys_json']",
      "[data-vp-variant-drawer-additional-field-keys-json-field='true']",
      "[data-vp-variant-drawer-additional-field-keys-json='true']",
      "[data-vp-variant-additional-field-keys-json]",
      "[data-vp-row-additional-field-keys-json]"
    ].join(","),

    form: "[data-vp-create-form], [data-create-form='true'], #vp-create-form"
  };

  var CLASS_NAMES = {
    root: "vp-create-variant-optional-fields",
    rootLegacy: "vp-variant-optional-fields",
    rootReady: "is-ready",
    rootEmpty: "is-empty",
    rootHasResults: "has-results",
    rootHasSelected: "has-selected",

    header: "vp-create-variant-optional-fields__header",
    title: "vp-create-variant-optional-fields__title",
    subtitle: "vp-create-variant-optional-fields__subtitle",
    status: "vp-create-variant-optional-fields__status",

    available: "vp-create-variant-optional-fields__available",
    availableHeader: "vp-create-variant-optional-fields__available-header",
    availableTitle: "vp-create-variant-optional-fields__available-title",
    availableCount: "vp-create-variant-optional-fields__available-count",
    availableColumns: "vp-create-variant-optional-fields__available-columns",
    availableList: "vp-create-variant-optional-fields__available-list",

    resultButton: "vp-create-variant-optional-fields__variable",
    availableRow: "vp-create-variant-optional-fields__available-row",
    availableName: "vp-create-variant-optional-fields__available-name",
    availableDescription: "vp-create-variant-optional-fields__available-description",
    availableType: "vp-create-variant-optional-fields__available-type",
    availableKey: "vp-create-variant-optional-fields__available-key",

    resultTitle: "vp-create-variant-optional-fields__variable-title",
    resultMeta: "vp-create-variant-optional-fields__variable-meta",

    selected: "vp-create-variant-optional-fields__selected",
    selectedHeader: "vp-create-variant-optional-fields__selected-header",
    selectedRows: "vp-create-variant-optional-fields__selected-rows",
    selectedEmpty: "vp-create-variant-optional-fields__selected-empty",

    row: "vp-create-variant-optional-fields__row",
    rowVariable: "vp-create-variant-optional-fields__row-variable",
    rowLabel: "vp-create-variant-optional-fields__row-label",
    rowMeta: "vp-create-variant-optional-fields__row-meta",
    rowControl: "vp-create-variant-optional-fields__row-control",
    rowRemove: "vp-create-variant-optional-fields__row-remove",
    rowUnit: "vp-create-variant-optional-fields__row-unit",

    empty: "vp-create-variant-optional-fields__empty",
    isHidden: "is-hidden"
  };

  var SYSTEM_KEYS = {
    "variant.variant_id": true,
    "variant.variantId": true,
    "variant.id": true,
    "variant_id": true,
    "variantId": true,
    "variant.id_slug": true,
    "family_id": true,
    "package_id": true,
    "id": true
  };

  var CORE_VALUE_KEYS = {
    "variant.variant_id": true,
    "variant.label": true,
    "variant.description": true
  };

  var state = {
    initialized: false,
    eventsBound: false,
    refreshInProgress: false,
    syncInProgress: false,
    suppressedRefreshCount: 0,
    suppressedSyncCount: 0,

    root: null,
    drawerRoot: null,
    drawerFieldsRoot: null,
    profileFieldsRoot: null,

    availableRoot: null,
    availableColumns: null,
    availableList: null,
    selectedRoot: null,
    selectedRows: null,
    selectedEmpty: null,
    statusNode: null,
    availableCountNode: null,
    selectedCountNode: null,

    valuesJsonField: null,
    additionalKeysJsonField: null,

    variables: [],
    variablesByKey: {},
    unitsById: {},
    activeProfile: null,
    activeProfileId: "",
    activeContext: {},
    profileFieldKeys: [],
    additionalFieldKeys: [],
    definitionValues: {},

    searchText: "",
    groupFilter: "",
    pendingScrollKey: "",

    lastRefreshReason: "",
    lastError: null,
    renderCount: 0,
    syncCount: 0,
    loadCount: 0
  };

  if (window[GLOBAL_NAME] && window[GLOBAL_NAME].version === VERSION) {
    try {
      document.documentElement.setAttribute(READY_ATTR, "ready");
      document.documentElement.setAttribute("data-vp-create-variant-optional-fields-version", VERSION);
    } catch (alreadyReadyError) {
      /* no-op */
    }

    return;
  }

  function utils() {
    return window.VectoplanCreateVariantUtils || null;
  }

  function initialize() {
    try {
      if (state.initialized) {
        return getRuntimeSnapshot();
      }

      bindEvents();
      refresh({
        reason: "initialize",
        soft: true,
        silent: true
      });

      state.initialized = true;

      safeSetAttribute(document.documentElement, READY_ATTR, "ready");
      safeSetAttribute(document.documentElement, "data-vp-create-variant-optional-fields-version", VERSION);

      dispatchDocument("vectoplan:create:variant-optional-fields-ready", {
        component: COMPONENT_NAME,
        version: VERSION,
        snapshot: getRuntimeSnapshot()
      });

      return getRuntimeSnapshot();
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("initialize failed", error);
      return getRuntimeSnapshot();
    }
  }

  function bindEvents() {
    try {
      if (state.eventsBound) {
        return;
      }

      state.eventsBound = true;

      document.addEventListener("click", onDocumentClick, true);
      document.addEventListener("input", onDocumentInput, true);
      document.addEventListener("change", onDocumentChange, true);

      document.addEventListener("vectoplan:create:variant-drawer-session-started", function (event) {
        var detail = event && event.detail ? event.detail : {};
        loadVariant(extractVariantFromDetail(detail) || detail.session || detail.payload || {}, {
          reason: "drawer-session-started",
          soft: true,
          silent: true
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-session-prepared", function (event) {
        var detail = event && event.detail ? event.detail : {};
        loadVariant(extractVariantFromDetail(detail) || detail.session || detail.payload || {}, {
          reason: "drawer-session-prepared",
          soft: true,
          silent: true
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-opened", function (event) {
        refresh({
          reason: "drawer-opened",
          detail: event && event.detail ? event.detail : {},
          soft: true,
          silent: true
        });
      });

      document.addEventListener("vectoplan:create:variant-editor-opened", function (event) {
        refresh({
          reason: "variant-editor-opened",
          detail: event && event.detail ? event.detail : {},
          soft: true,
          silent: true
        });
      });

      document.addEventListener("vectoplan:create:variant-fields-rendered", function (event) {
        refresh({
          reason: "variant-fields-rendered",
          detail: event && event.detail ? event.detail : {},
          soft: true,
          silent: true
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-reset", function () {
        resetRuntimeState({
          keepDom: true
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-validate-started", function () {
        syncToDrawerValues({
          reason: "validate-started",
          silent: true
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-apply-started", function () {
        syncToDrawerValues({
          reason: "apply-started",
          silent: true
        });
      });

      document.addEventListener("vectoplan:create:variant-profile-context-changed", function (event) {
        refresh({
          reason: "profile-context-changed",
          detail: event && event.detail ? event.detail : {},
          soft: true,
          silent: true
        });
      });

      document.addEventListener("vectoplan:create:variant-profile-resolved", function (event) {
        refresh({
          reason: "profile-resolved",
          detail: event && event.detail ? event.detail : {},
          soft: true,
          silent: true
        });
      });
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("bindEvents failed", error);
    }
  }

  function onDocumentClick(event) {
    try {
      var target = event && event.target ? event.target : null;

      if (!target || !target.closest) {
        return;
      }

      var addButton = target.closest(SELECTORS.addButton);

      if (addButton && containsRoot(addButton)) {
        event.preventDefault();
        event.stopPropagation();

        if (typeof event.stopImmediatePropagation === "function") {
          event.stopImmediatePropagation();
        }

        var key = addButton.getAttribute("data-vp-variant-optional-add") ||
          addButton.getAttribute("data-vp-add-additional-field") ||
          addButton.getAttribute("data-vp-variable-key") ||
          "";

        if (key) {
          addField(key, {
            reason: "variable-click",
            scrollIntoView: true,
            focus: true
          });
        }

        return;
      }

      var removeButton = target.closest(SELECTORS.removeButton);

      if (removeButton && containsRoot(removeButton)) {
        event.preventDefault();
        event.stopPropagation();

        if (typeof event.stopImmediatePropagation === "function") {
          event.stopImmediatePropagation();
        }

        var removeKey = removeButton.getAttribute("data-vp-variant-optional-remove") ||
          removeButton.getAttribute("data-vp-remove-additional-field") ||
          removeButton.getAttribute("data-vp-optional-row-remove") ||
          removeButton.getAttribute("data-vp-variable-key") ||
          "";

        if (removeKey) {
          removeField(removeKey, {
            reason: "remove-click"
          });
        }

        return;
      }

      var refreshButton = target.closest(SELECTORS.refreshButton);

      if (refreshButton && containsRoot(refreshButton)) {
        event.preventDefault();
        event.stopPropagation();

        refresh({
          reason: "manual-refresh"
        });

        return;
      }

      var clearSearchButton = target.closest(SELECTORS.clearSearchButton);

      if (clearSearchButton && containsRoot(clearSearchButton)) {
        event.preventDefault();
        event.stopPropagation();

        state.searchText = "";
        state.groupFilter = "";

        renderAvailableVariables();
      }
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("onDocumentClick failed", error);
    }
  }

  function onDocumentInput(event) {
    try {
      var target = event && event.target ? event.target : null;

      if (!target || !target.matches) {
        return;
      }

      if (target.matches(SELECTORS.searchInput) && containsRoot(target)) {
        state.searchText = "";
        renderAvailableVariables();
        return;
      }

      if (target.matches(SELECTORS.valueControl) && containsRoot(target)) {
        syncToDrawerValues({
          reason: "optional-field-input"
        });
      }
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("onDocumentInput failed", error);
    }
  }

  function onDocumentChange(event) {
    try {
      var target = event && event.target ? event.target : null;

      if (!target || !target.matches) {
        return;
      }

      if (target.matches(SELECTORS.groupSelect) && containsRoot(target)) {
        state.groupFilter = "";
        renderAvailableVariables();
        return;
      }

      if (target.matches(SELECTORS.valueControl) && containsRoot(target)) {
        syncToDrawerValues({
          reason: "optional-field-change"
        });
      }
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("onDocumentChange failed", error);
    }
  }

  function refresh(options) {
    try {
      var safeOptions = options || {};

      if (state.refreshInProgress && safeOptions.force !== true) {
        state.suppressedRefreshCount += 1;
        return getRuntimeSnapshot();
      }

      state.refreshInProgress = true;
      state.lastRefreshReason = safeOptions.reason || "refresh";
      state.searchText = "";
      state.groupFilter = "";

      ensureDom();
      loadDefinitions();
      resolveContext(safeOptions.detail || {});
      resolveActiveProfile(safeOptions.detail || {});
      resolveProfileFieldKeys();
      readDrawerValues(safeOptions.detail || {});
      readAdditionalKeys(safeOptions.detail || {});
      inferAdditionalKeysFromValues();

      render();

      syncToDrawerValues({
        reason: state.lastRefreshReason,
        silent: safeOptions.silent !== false
      });

      if (!safeOptions.silent) {
        dispatchDocument("vectoplan:create:variant-optional-fields-refreshed", {
          component: COMPONENT_NAME,
          version: VERSION,
          snapshot: getRuntimeSnapshot(),
          reason: state.lastRefreshReason
        });
      }

      state.refreshInProgress = false;
      return getRuntimeSnapshot();
    } catch (error) {
      state.refreshInProgress = false;
      state.lastError = normalizeError(error);
      warn("refresh failed", error);

      if (!options || !options.soft) {
        renderError(error);
      }

      return getRuntimeSnapshot();
    }
  }

  function loadVariant(variant, options) {
    try {
      var safeOptions = options || {};
      var source = variant || {};

      state.loadCount += 1;
      state.lastRefreshReason = safeOptions.reason || "load-variant";
      state.searchText = "";
      state.groupFilter = "";

      ensureDom();
      loadDefinitions();

      state.definitionValues = extractDefinitionValues(source);
      state.additionalFieldKeys = normalizeAdditionalKeys(extractAdditionalKeys(source));

      resolveContext({
        session: source,
        variant: source
      });
      resolveActiveProfile({
        session: source,
        variant: source
      });
      resolveProfileFieldKeys();

      state.additionalFieldKeys = filterAdditionalKeys(state.additionalFieldKeys);
      inferAdditionalKeysFromValues();

      render();

      syncToDrawerValues({
        reason: state.lastRefreshReason,
        silent: safeOptions.silent !== false
      });

      if (!safeOptions.silent) {
        dispatchDocument("vectoplan:create:variant-optional-fields-loaded", {
          component: COMPONENT_NAME,
          version: VERSION,
          variant: source,
          snapshot: getRuntimeSnapshot()
        });
      }

      return getRuntimeSnapshot();
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("loadVariant failed", error);
      return getRuntimeSnapshot();
    }
  }

  function restoreFromVariant(variant, options) {
    return loadVariant(variant, safeMerge({
      reason: "restore-from-variant"
    }, options || {}));
  }

  function setValues(values, options) {
    try {
      var safeOptions = options || {};

      ensureDom();
      loadDefinitions();

      state.definitionValues = safeMerge(state.definitionValues || {}, values || {});
      inferAdditionalKeysFromValues();

      renderSelectedFields();

      syncToDrawerValues({
        reason: safeOptions.reason || "set-values",
        silent: safeOptions.silent !== false
      });

      return cloneObject(state.definitionValues);
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("setValues failed", error);
      return cloneObject(state.definitionValues);
    }
  }

  function ensureDom() {
    try {
      state.drawerRoot = query(SELECTORS.drawerRoot) || document;
      state.drawerFieldsRoot = query(SELECTORS.drawerFields, state.drawerRoot);
      state.profileFieldsRoot = query(SELECTORS.profileFieldsRoot, state.drawerRoot) || state.drawerFieldsRoot;
      state.root = query(SELECTORS.optionalRoot, state.drawerRoot);

      if (!state.root) {
        state.root = createRoot();
        mountRoot(state.root);
      }

      normalizeRootDom(state.root);

      state.availableRoot = query(SELECTORS.availableRoot, state.root);
      state.availableColumns = query(SELECTORS.availableColumns, state.root);
      state.availableList = query(SELECTORS.availableList, state.root);
      state.selectedRoot = query(SELECTORS.selectedRoot, state.root);
      state.selectedRows = query(SELECTORS.selectedRows, state.root);
      state.selectedEmpty = query(SELECTORS.selectedEmpty, state.root);
      state.statusNode = query(SELECTORS.statusNode, state.root);
      state.availableCountNode = query(SELECTORS.availableCountNode, state.root);
      state.selectedCountNode = query(SELECTORS.selectedCountNode, state.root);

      state.valuesJsonField = query(SELECTORS.valuesJson, state.drawerRoot) || query(SELECTORS.valuesJson);
      state.additionalKeysJsonField = query(SELECTORS.additionalKeysJson, state.drawerRoot) || query(SELECTORS.additionalKeysJson, state.root);

      if (!state.additionalKeysJsonField) {
        state.additionalKeysJsonField = document.createElement("input");
        state.additionalKeysJsonField.type = "hidden";
        state.additionalKeysJsonField.name = "variant_drawer_additional_field_keys_json";
        state.additionalKeysJsonField.setAttribute("data-vp-variant-drawer-additional-field-keys-json-field", "true");
        state.additionalKeysJsonField.setAttribute("data-vp-variant-additional-field-keys-json", "true");
        state.root.appendChild(state.additionalKeysJsonField);
      }

      if (!state.valuesJsonField) {
        state.valuesJsonField = document.createElement("textarea");
        state.valuesJsonField.name = "variant_drawer_values_json";
        state.valuesJsonField.hidden = true;
        state.valuesJsonField.setAttribute("data-vp-variant-drawer-values-json", "true");
        state.root.appendChild(state.valuesJsonField);
      }

      return state.root;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("ensureDom failed", error);
      return null;
    }
  }

  function normalizeRootDom(root) {
    try {
      if (!root) {
        return;
      }

      root.classList.add(CLASS_NAMES.root);
      root.classList.add(CLASS_NAMES.rootReady);
      root.setAttribute("data-vp-variant-optional-fields", "true");
      root.setAttribute("data-vp-variant-optional-fields-root", "true");
      root.setAttribute("data-vp-variant-optional-fields-version", VERSION);
      root.setAttribute("data-vp-optional-ui-mode", "list-no-search");
      root.setAttribute("data-vp-optional-available-layout", "table-list");
      root.setAttribute("aria-label", root.getAttribute("aria-label") || "Weitere technische Angaben");

      queryAll(SELECTORS.legacyTools, root).forEach(function (node) {
        try {
          node.hidden = true;
          node.setAttribute("aria-hidden", "true");
          node.setAttribute("data-vp-legacy-control-hidden", "true");
        } catch (error) {
          /* no-op */
        }
      });

      ensureChildStructure(root);
    } catch (error) {
      warn("normalizeRootDom failed", error);
    }
  }

  function ensureChildStructure(root) {
    try {
      var available = query(SELECTORS.availableRoot, root);

      if (!available) {
        available = document.createElement("div");
        available.className = CLASS_NAMES.available;
        available.setAttribute("data-vp-variant-optional-fields-available", "true");
        available.setAttribute("data-vp-variant-optional-fields-catalog", "true");

        available.innerHTML = [
          '<div class="' + CLASS_NAMES.availableHeader + '" data-vp-variant-optional-fields-available-header="true">',
          '  <strong data-vp-variant-optional-fields-available-title="true">Verfügbare Variablen</strong>',
          '  <span data-vp-variant-optional-fields-available-count="true">Wird geladen.</span>',
          '</div>',
          '<div class="' + CLASS_NAMES.availableColumns + '" data-vp-variant-optional-fields-available-columns="true" aria-hidden="true">',
          '  <span>Bezeichnung</span>',
          '  <span>Beschreibung</span>',
          '  <span>Art</span>',
          '</div>',
          '<div class="' + CLASS_NAMES.availableList + '" data-vp-variant-optional-fields-available-list="true" role="listbox" aria-label="Verfügbare Backend-Variablen"></div>'
        ].join("");

        root.appendChild(available);
      } else {
        ensureAvailableColumns(available);

        var availableList = query(SELECTORS.availableList, available);

        if (!availableList) {
          availableList = document.createElement("div");
          availableList.className = CLASS_NAMES.availableList;
          availableList.setAttribute("data-vp-variant-optional-fields-available-list", "true");
          available.appendChild(availableList);
        }

        availableList.setAttribute("role", "listbox");
        availableList.setAttribute("aria-label", "Verfügbare Backend-Variablen");
      }

      var selected = query(SELECTORS.selectedRoot, root);

      if (!selected) {
        selected = document.createElement("div");
        selected.className = CLASS_NAMES.selected;
        selected.setAttribute("data-vp-variant-optional-fields-selected", "true");

        selected.innerHTML = [
          '<div class="' + CLASS_NAMES.selectedHeader + '">',
          '  <strong>Gewählte Zusatzfelder</strong>',
          '  <span data-vp-variant-optional-fields-selected-count="true">0</span>',
          '</div>',
          '<div class="' + CLASS_NAMES.selectedEmpty + '" data-vp-variant-optional-fields-selected-empty="true">',
          '  Noch keine zusätzlichen Variablen gewählt.',
          '</div>',
          '<div class="' + CLASS_NAMES.selectedRows + '" data-vp-variant-optional-fields-selected-rows="true" data-vp-variant-optional-fields-selected-list="true"></div>'
        ].join("");

        root.appendChild(selected);
      }

      var selectedRows = query(SELECTORS.selectedRows, root);

      if (!selectedRows && selected) {
        selectedRows = document.createElement("div");
        selectedRows.className = CLASS_NAMES.selectedRows;
        selectedRows.setAttribute("data-vp-variant-optional-fields-selected-rows", "true");
        selectedRows.setAttribute("data-vp-variant-optional-fields-selected-list", "true");
        selected.appendChild(selectedRows);
      }
    } catch (error) {
      warn("ensureChildStructure failed", error);
    }
  }

  function ensureAvailableColumns(availableRoot) {
    try {
      if (!availableRoot) {
        return null;
      }

      var columns = query(SELECTORS.availableColumns, availableRoot);

      if (columns) {
        return columns;
      }

      columns = document.createElement("div");
      columns.className = CLASS_NAMES.availableColumns;
      columns.setAttribute("data-vp-variant-optional-fields-available-columns", "true");
      columns.setAttribute("aria-hidden", "true");

      ["Bezeichnung", "Beschreibung", "Art"].forEach(function (label) {
        var span = document.createElement("span");
        span.textContent = label;
        columns.appendChild(span);
      });

      var list = query(SELECTORS.availableList, availableRoot);

      if (list && list.parentNode === availableRoot) {
        availableRoot.insertBefore(columns, list);
      } else {
        availableRoot.appendChild(columns);
      }

      return columns;
    } catch (error) {
      warn("ensureAvailableColumns failed", error);
      return null;
    }
  }

  function createRoot() {
    var root = document.createElement("section");

    root.className = CLASS_NAMES.root;
    root.setAttribute("data-vp-variant-optional-fields", "true");
    root.setAttribute("data-vp-variant-optional-fields-root", "true");
    root.setAttribute("data-vp-variant-drawer-optional-fields", "true");
    root.setAttribute("data-vp-variant-optional-fields-version", VERSION);
    root.setAttribute("data-vp-optional-ui-mode", "list-no-search");
    root.setAttribute("data-vp-optional-available-layout", "table-list");
    root.setAttribute("aria-label", "Weitere technische Angaben");

    root.innerHTML = [
      '<header class="' + CLASS_NAMES.header + '">',
      '  <div>',
      '    <h4 class="' + CLASS_NAMES.title + '">Weitere technische Angaben</h4>',
      '    <p class="' + CLASS_NAMES.subtitle + '">',
      '      Zusätzliche Variablen aus dem Backend-Katalog auswählen, z. B. U-Wert, Brandschutz oder Rohdichte.',
      '    </p>',
      '  </div>',
      '  <span class="' + CLASS_NAMES.status + '" data-vp-variant-optional-fields-status="true" data-vp-variant-optional-fields-count-label="true" aria-live="polite">',
      '    Keine Zusatzfelder aktiv.',
      '  </span>',
      '</header>',
      '<div class="' + CLASS_NAMES.available + '" data-vp-variant-optional-fields-available="true" data-vp-variant-optional-fields-catalog="true">',
      '  <div class="' + CLASS_NAMES.availableHeader + '" data-vp-variant-optional-fields-available-header="true">',
      '    <strong data-vp-variant-optional-fields-available-title="true">Verfügbare Variablen</strong>',
      '    <span data-vp-variant-optional-fields-available-count="true">Wird geladen.</span>',
      '  </div>',
      '  <div class="' + CLASS_NAMES.availableColumns + '" data-vp-variant-optional-fields-available-columns="true" aria-hidden="true">',
      '    <span>Bezeichnung</span>',
      '    <span>Beschreibung</span>',
      '    <span>Art</span>',
      '  </div>',
      '  <div class="' + CLASS_NAMES.availableList + '" data-vp-variant-optional-fields-available-list="true" role="listbox" aria-label="Verfügbare Backend-Variablen"></div>',
      '</div>',
      '<div class="' + CLASS_NAMES.selected + '" data-vp-variant-optional-fields-selected="true">',
      '  <div class="' + CLASS_NAMES.selectedHeader + '">',
      '    <strong>Gewählte Zusatzfelder</strong>',
      '    <span data-vp-variant-optional-fields-selected-count="true">0</span>',
      '  </div>',
      '  <div class="' + CLASS_NAMES.selectedEmpty + '" data-vp-variant-optional-fields-selected-empty="true">',
      '    Noch keine zusätzlichen Variablen gewählt.',
      '  </div>',
      '  <div class="' + CLASS_NAMES.selectedRows + '" data-vp-variant-optional-fields-selected-rows="true" data-vp-variant-optional-fields-selected-list="true"></div>',
      '</div>',
      '<input type="hidden" name="variant_drawer_additional_field_keys_json" data-vp-variant-drawer-additional-field-keys-json-field="true" data-vp-variant-additional-field-keys-json="true" value="[]" />'
    ].join("");

    return root;
  }

  function mountRoot(root) {
    try {
      var slot = query(SELECTORS.optionalSlot, state.drawerRoot);

      if (slot) {
        slot.appendChild(root);
        return true;
      }

      var sectionsRoot = query(SELECTORS.drawerSections, state.drawerRoot);

      if (sectionsRoot && sectionsRoot.parentNode) {
        sectionsRoot.parentNode.insertBefore(root, sectionsRoot.nextSibling);
        return true;
      }

      var fieldsRoot = query(SELECTORS.drawerFields, state.drawerRoot);

      if (fieldsRoot) {
        fieldsRoot.appendChild(root);
        return true;
      }

      var profileRoot = query(SELECTORS.profileFieldsRoot, state.drawerRoot);

      if (profileRoot && profileRoot.parentNode) {
        profileRoot.parentNode.insertBefore(root, profileRoot.nextSibling);
        return true;
      }

      var summaryRoot = query(SELECTORS.summaryRoot, state.drawerRoot);

      if (summaryRoot && summaryRoot.parentNode) {
        summaryRoot.parentNode.insertBefore(root, summaryRoot);
        return true;
      }

      var drawerBody = query(SELECTORS.drawerBody, state.drawerRoot);

      if (drawerBody) {
        drawerBody.appendChild(root);
        return true;
      }

      if (state.drawerRoot && state.drawerRoot !== document && state.drawerRoot.appendChild) {
        state.drawerRoot.appendChild(root);
        return true;
      }

      return false;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("mountRoot failed", error);
      return false;
    }
  }

  function loadDefinitions() {
    try {
      var variables = [];
      var units = [];
      var maps = getDefinitionMaps();
      var definitionsSources = getDefinitionSources();

      definitionsSources.forEach(function (source) {
        var normalized = normalizeDefinitions(source);

        variables = variables.concat(normalized.variables || []);
        units = units.concat(normalized.units || []);
      });

      if (!variables.length && maps.variablesByKey) {
        variables = Object.keys(maps.variablesByKey).map(function (key) {
          return maps.variablesByKey[key];
        });
      }

      if (!variables.length && maps.variables_by_key) {
        variables = Object.keys(maps.variables_by_key).map(function (key) {
          return maps.variables_by_key[key];
        });
      }

      state.variablesByKey = {};
      state.variables = uniqueVariables(variables).filter(function (variable) {
        var key = getVariableKey(variable);

        if (!key) {
          return false;
        }

        state.variablesByKey[key] = variable;
        return true;
      });

      state.unitsById = {};

      uniqueUnits(units).forEach(function (unit) {
        var unitId = getUnitId(unit);

        if (unitId) {
          state.unitsById[unitId] = unit;
        }
      });

      if (maps.unitsById) {
        Object.keys(maps.unitsById).forEach(function (key) {
          if (!state.unitsById[key]) {
            state.unitsById[key] = maps.unitsById[key];
          }
        });
      }

      if (maps.units_by_id) {
        Object.keys(maps.units_by_id).forEach(function (key) {
          if (!state.unitsById[key]) {
            state.unitsById[key] = maps.units_by_id[key];
          }
        });
      }

      return state.variables;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("loadDefinitions failed", error);
      state.variables = [];
      state.variablesByKey = {};
      state.unitsById = {};
      return [];
    }
  }

  function getDefinitionSources() {
    var sources = [];

    try {
      if (
        window.VectoplanCreateVariantProfiles &&
        typeof window.VectoplanCreateVariantProfiles.getDefinitionsSync === "function"
      ) {
        sources.push(window.VectoplanCreateVariantProfiles.getDefinitionsSync());
      }
    } catch (error) {
      /* no-op */
    }

    try {
      if (window.VectoplanCreateDefinitions) {
        sources.push(window.VectoplanCreateDefinitions);
      }

      if (window.VectoplanCreateDefinitionCatalogs) {
        sources.push(window.VectoplanCreateDefinitionCatalogs);
      }

      if (window.VectoplanCreateContext && window.VectoplanCreateContext.definitions) {
        sources.push(window.VectoplanCreateContext.definitions);
      }

      if (window.VectoplanCreateContext && window.VectoplanCreateContext.definitionCatalogs) {
        sources.push(window.VectoplanCreateContext.definitionCatalogs);
      }

      if (window.VectoplanCreateContext && window.VectoplanCreateContext.definition_catalogs) {
        sources.push(window.VectoplanCreateContext.definition_catalogs);
      }

      if (window.VectoplanCreateContext && window.VectoplanCreateContext.options && window.VectoplanCreateContext.options.definitions) {
        sources.push(window.VectoplanCreateContext.options.definitions);
      }
    } catch (error) {
      /* no-op */
    }

    return sources;
  }

  function normalizeDefinitions(raw) {
    try {
      if (utils() && typeof utils().normalizeDefinitions === "function") {
        var normalized = utils().normalizeDefinitions(raw || {});

        return {
          variables: normalized.variables || normalized.variable_definitions || [],
          units: normalized.units || [],
          variant_profiles: normalized.variant_profiles || normalized.variantProfiles || [],
          family_profiles: normalized.family_profiles || normalized.familyProfiles || []
        };
      }

      var source = raw || {};
      var defs = source;

      if (source.data && typeof source.data === "object") {
        defs = source.data;
      }

      if (defs.definitions && typeof defs.definitions === "object") {
        defs = defs.definitions;
      }

      if (defs.definition_catalogs && typeof defs.definition_catalogs === "object") {
        defs = defs.definition_catalogs;
      }

      return {
        variables: toArrayOrObjectValues(defs.variables),
        units: toArrayOrObjectValues(defs.units),
        variant_profiles: toArrayOrObjectValues(defs.variant_profiles || defs.variantProfiles),
        family_profiles: toArrayOrObjectValues(defs.family_profiles || defs.familyProfiles)
      };
    } catch (error) {
      return {
        variables: [],
        units: [],
        variant_profiles: [],
        family_profiles: []
      };
    }
  }

  function resolveContext(detail) {
    try {
      var context = {};
      var drawerSession = getDrawerSession();
      var source = extractVariantFromDetail(detail) || detail.session || detail.payload || drawerSession || {};

      if (window.VectoplanCreateVariantProfiles && typeof window.VectoplanCreateVariantProfiles.getCurrentContext === "function") {
        context = window.VectoplanCreateVariantProfiles.getCurrentContext() || {};
      }

      var drawer = state.drawerRoot && state.drawerRoot !== document ? state.drawerRoot : query(SELECTORS.drawerRoot);
      var form = query(SELECTORS.form);

      state.activeContext = {
        domain: normalizeToken(context.domain || source.domain || readValue(form, "domain") || getAttr(drawer, "data-vp-current-domain") || "hochbau", "hochbau"),
        category: normalizeToken(context.category || source.category || readValue(form, "category") || getAttr(drawer, "data-vp-current-category") || "bloecke", "bloecke"),
        subcategory: normalizeToken(context.subcategory || source.subcategory || readValue(form, "subcategory") || getAttr(drawer, "data-vp-current-subcategory") || "basis", "basis"),
        object_kind: normalizeToken(context.object_kind || context.objectKind || source.object_kind || source.objectKind || readValue(form, "object_kind") || getAttr(drawer, "data-vp-current-object-kind") || "cell_block", "cell_block"),
        family_profile_id: String(context.family_profile_id || context.familyProfileId || source.family_profile_id || source.familyProfileId || readValue(form, "family_profile_id") || getAttr(drawer, "data-vp-current-family-profile-id") || "").trim(),
        variant_profile_id: String(context.variant_profile_id || context.variantProfileId || source.variant_profile_id || source.variantProfileId || source.profile_id || readValue(form, "variant_profile_id") || getAttr(drawer, "data-vp-current-variant-profile-id") || "").trim()
      };

      state.activeContext.taxonomy_path = [state.activeContext.domain, state.activeContext.category, state.activeContext.subcategory].filter(Boolean).join("/");

      return state.activeContext;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("resolveContext failed", error);

      state.activeContext = {
        domain: "hochbau",
        category: "bloecke",
        subcategory: "basis",
        taxonomy_path: "hochbau/bloecke/basis",
        object_kind: "cell_block",
        family_profile_id: "",
        variant_profile_id: ""
      };

      return state.activeContext;
    }
  }

  function resolveActiveProfile(detail) {
    try {
      var profile = null;
      var drawerSession = getDrawerSession();
      var source = extractVariantFromDetail(detail) || detail.session || detail.payload || drawerSession || {};
      var profileId = state.activeContext.variant_profile_id || source.variant_profile_id || source.variantProfileId || "";

      profile = source.variant_profile || source.variantProfile || source.profile || null;

      if (!profile && drawerSession) {
        profile = drawerSession.variant_profile || drawerSession.variantProfile || drawerSession.profile || null;
      }

      if (!profile && window.VectoplanCreateVariantProfiles) {
        if (typeof window.VectoplanCreateVariantProfiles.getVariantProfileLocal === "function" && profileId) {
          var localProfile = window.VectoplanCreateVariantProfiles.getVariantProfileLocal(profileId);

          if (localProfile && localProfile.ok) {
            profile = localProfile.variant_profile || localProfile.variantProfile || localProfile.profile || null;
          }
        }

        if (!profile && typeof window.VectoplanCreateVariantProfiles.getCacheSnapshot === "function") {
          var cache = window.VectoplanCreateVariantProfiles.getCacheSnapshot();

          if (cache && cache.lastResolved) {
            profile = cache.lastResolved.variant_profile || cache.lastResolved.variantProfile || cache.lastResolved.profile || null;
          }

          if (!profile && cache && cache.currentProfile) {
            profile = cache.currentProfile;
          }

          if (!profile && cache && cache.resolvedProfile) {
            profile = cache.resolvedProfile;
          }

          if (!profile && cache && cache.currentBundle && cache.currentBundle.profile) {
            profile = cache.currentBundle.profile;
          }
        }

        if (!profile && typeof window.VectoplanCreateVariantProfiles.getDefinitionMaps === "function" && profileId) {
          var maps = window.VectoplanCreateVariantProfiles.getDefinitionMaps();

          if (maps && maps.variantProfilesById) {
            profile = maps.variantProfilesById[profileId] || null;
          }
        }
      }

      if (!profile && profileId) {
        profile = findProfileInDefinitions(profileId);
      }

      state.activeProfile = profile || null;
      state.activeProfileId = getProfileId(profile) || profileId || "";

      return state.activeProfile;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("resolveActiveProfile failed", error);
      state.activeProfile = null;
      state.activeProfileId = "";
      return null;
    }
  }

  function resolveProfileFieldKeys() {
    try {
      var keys = [];

      keys = keys.concat(extractProfileFieldKeys(state.activeProfile));
      keys = keys.concat(readRenderedProfileFieldKeys());

      state.profileFieldKeys = uniqueStrings(keys).filter(Boolean);

      return state.profileFieldKeys;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("resolveProfileFieldKeys failed", error);
      state.profileFieldKeys = readRenderedProfileFieldKeys();
      return state.profileFieldKeys;
    }
  }

  function readDrawerValues(detail) {
    try {
      var values = {};
      var session = getDrawerSession();
      var variant = extractVariantFromDetail(detail) || extractVariantFromSession(session) || session || {};

      values = mergeObjects(values, extractDefinitionValues(variant));
      values = mergeObjects(values, extractDefinitionValues(session));

      if (state.valuesJsonField && state.valuesJsonField.value) {
        values = mergeObjects(values, safeJsonParse(state.valuesJsonField.value, {}));
      }

      state.definitionValues = values;

      return state.definitionValues;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("readDrawerValues failed", error);
      state.definitionValues = {};
      return {};
    }
  }

  function readAdditionalKeys(detail) {
    try {
      var keys = [];
      var session = getDrawerSession();
      var variant = extractVariantFromDetail(detail) || extractVariantFromSession(session) || session || {};

      keys = keys.concat(extractAdditionalKeys(variant));
      keys = keys.concat(extractAdditionalKeys(session));

      if (state.additionalKeysJsonField && state.additionalKeysJsonField.value) {
        keys = keys.concat(parseKeyList(state.additionalKeysJsonField.value));
      }

      state.additionalFieldKeys = filterAdditionalKeys(keys);

      return state.additionalFieldKeys;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("readAdditionalKeys failed", error);
      state.additionalFieldKeys = [];
      return [];
    }
  }

  function inferAdditionalKeysFromValues() {
    try {
      Object.keys(state.definitionValues || {}).forEach(function (key) {
        if (!key || isSystemKey(key) || isCoreValueKey(key) || containsString(state.profileFieldKeys, key)) {
          return;
        }

        ensureVariableForKey(key);

        if (!containsString(state.additionalFieldKeys, key) && !!state.variablesByKey[key]) {
          state.additionalFieldKeys.push(key);
        }
      });

      state.additionalFieldKeys = filterAdditionalKeys(state.additionalFieldKeys);

      return state.additionalFieldKeys;
    } catch (error) {
      warn("inferAdditionalKeysFromValues failed", error);
      return state.additionalFieldKeys;
    }
  }

  function filterAdditionalKeys(keys) {
    try {
      return uniqueStrings(parseKeyList(keys)).filter(function (key) {
        if (!key || isSystemKey(key) || isCoreValueKey(key) || containsString(state.profileFieldKeys, key)) {
          return false;
        }

        ensureVariableForKey(key);

        return !!state.variablesByKey[key];
      });
    } catch (error) {
      return [];
    }
  }

  function normalizeAdditionalKeys(keys) {
    return uniqueStrings(parseKeyList(keys)).filter(Boolean);
  }

  function render() {
    try {
      ensureDom();

      renderAvailableVariables();
      renderSelectedFields();
      updateCountsAndStatus();

      state.renderCount += 1;

      dispatchDocument("vectoplan:create:variant-optional-fields-rendered", {
        component: COMPONENT_NAME,
        version: VERSION,
        snapshot: getRuntimeSnapshot()
      });
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("render failed", error);
      renderError(error);
    }
  }

  function renderAvailableVariables() {
    try {
      if (!state.availableList) {
        return;
      }

      var variables = getAvailableVariables({
        ignoreSearch: true,
        ignoreGroup: true
      });

      state.availableList.innerHTML = "";
      state.availableList.setAttribute("role", "listbox");
      state.availableList.setAttribute("aria-label", "Verfügbare Backend-Variablen");

      if (state.availableRoot) {
        state.availableRoot.setAttribute("data-vp-available-variable-count", String(variables.length));
        state.availableRoot.setAttribute("data-vp-available-layout", "table-list");
        ensureAvailableColumns(state.availableRoot);
      }

      if (!variables.length) {
        var empty = document.createElement("p");
        empty.className = CLASS_NAMES.empty;
        empty.textContent = state.variables.length
          ? "Keine weiteren kompatiblen Variablen verfügbar."
          : "Keine Variablen aus dem Backend-Katalog verfügbar.";
        state.availableList.appendChild(empty);
      } else {
        var fragment = document.createDocumentFragment();

        variables.forEach(function (variable) {
          fragment.appendChild(createVariableResultButton(variable));
        });

        state.availableList.appendChild(fragment);
      }

      setNodeText(state.availableCountNode, "Verfügbare Variablen: " + String(variables.length));
      updateText(SELECTORS.availableCountNode, "Verfügbare Variablen: " + String(variables.length), state.root);

      if (state.root) {
        state.root.classList.toggle(CLASS_NAMES.rootHasResults, variables.length > 0);
      }
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("renderAvailableVariables failed", error);
    }
  }

  function createVariableResultButton(variable) {
    var key = getVariableKey(variable);
    var label = getVariableLabel(variable);
    var group = getVariableGroup(variable);
    var description = getVariableDescription(variable);
    var typeLabel = getVariableTypeLabel(variable);
    var unitLabel = getVariableUnitLabel(variable);
    var readableGroup = groupLabel(group);

    var button = document.createElement("button");
    button.type = "button";
    button.className = [
      CLASS_NAMES.resultButton,
      CLASS_NAMES.availableRow
    ].join(" ");
    button.setAttribute("data-vp-variant-optional-add", key);
    button.setAttribute("data-vp-add-additional-field", key);
    button.setAttribute("data-vp-variable-key", key);
    button.setAttribute("data-vp-variable-group", group);
    button.setAttribute("data-vp-variable-type", typeLabel);
    button.setAttribute("data-vp-variable-unit", unitLabel);
    button.setAttribute("role", "option");
    button.setAttribute("aria-label", "Variable hinzufügen: " + label + ". " + description + ". Art: " + typeLabel + ".");
    button.title = label + " · " + key;

    var nameCell = document.createElement("span");
    nameCell.className = [
      CLASS_NAMES.resultTitle,
      CLASS_NAMES.availableName
    ].join(" ");
    nameCell.setAttribute("data-vp-optional-available-name", "true");
    nameCell.textContent = label;

    var descriptionCell = document.createElement("span");
    descriptionCell.className = CLASS_NAMES.availableDescription;
    descriptionCell.setAttribute("data-vp-optional-available-description", "true");
    descriptionCell.textContent = description || [key, readableGroup, unitLabel].filter(Boolean).join(" · ");

    var typeCell = document.createElement("span");
    typeCell.className = CLASS_NAMES.availableType;
    typeCell.setAttribute("data-vp-optional-available-type", "true");
    typeCell.textContent = typeLabel || "string";

    var keyMeta = document.createElement("small");
    keyMeta.className = [
      CLASS_NAMES.resultMeta,
      CLASS_NAMES.availableKey
    ].join(" ");
    keyMeta.setAttribute("data-vp-optional-available-key", "true");
    keyMeta.textContent = [key, readableGroup, unitLabel].filter(Boolean).join(" · ");

    nameCell.appendChild(keyMeta);

    button.appendChild(nameCell);
    button.appendChild(descriptionCell);
    button.appendChild(typeCell);

    return button;
  }

  function renderSelectedFields() {
    try {
      if (!state.selectedRows) {
        return;
      }

      state.selectedRows.innerHTML = "";

      state.additionalFieldKeys.forEach(function (key) {
        ensureVariableForKey(key);

        var variable = state.variablesByKey[key];

        if (!variable) {
          return;
        }

        state.selectedRows.appendChild(createSelectedFieldNode(variable));
      });

      updateCountsAndStatus();

      if (state.pendingScrollKey) {
        scrollToSelectedField(state.pendingScrollKey);
        state.pendingScrollKey = "";
      }
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("renderSelectedFields failed", error);
    }
  }

  function createSelectedFieldNode(variable) {
    try {
      return createSelectedRowNode(variable);
    } catch (error) {
      warn("createSelectedFieldNode fallback used", error);
      return createSelectedRowNode(variable);
    }
  }

  function createSelectedRowNode(variable) {
    var key = getVariableKey(variable);
    var value = getValueForKey(key);
    var group = getVariableGroup(variable);
    var unitLabel = getVariableUnitLabel(variable);
    var typeLabel = getVariableTypeLabel(variable);
    var description = getVariableDescription(variable);

    var row = document.createElement("div");
    row.className = CLASS_NAMES.row;
    row.setAttribute("data-vp-variant-optional-field", key);
    row.setAttribute("data-vp-variant-optional-field-key", key);
    row.setAttribute("data-vp-variant-optional-fields-row", "true");
    row.setAttribute("data-vp-variable-key", key);
    row.setAttribute("data-vp-field-key", key);
    row.setAttribute("data-vp-variable-type", typeLabel);

    var variableCell = document.createElement("div");
    variableCell.className = CLASS_NAMES.rowVariable;

    var label = document.createElement("strong");
    label.className = CLASS_NAMES.rowLabel;
    label.setAttribute("data-vp-optional-row-label", "true");
    label.textContent = getVariableLabel(variable);

    var meta = document.createElement("span");
    meta.className = CLASS_NAMES.rowMeta;
    meta.setAttribute("data-vp-optional-row-meta", "true");
    meta.textContent = [key, groupLabel(group), typeLabel, unitLabel].filter(Boolean).join(" · ");

    if (description && description !== key) {
      meta.title = description;
    }

    variableCell.appendChild(label);
    variableCell.appendChild(meta);

    var controlCell = document.createElement("div");
    controlCell.className = CLASS_NAMES.rowControl;
    controlCell.setAttribute("data-vp-optional-row-control", "true");

    var control = createControl(variable, value);
    controlCell.appendChild(control);

    if (unitLabel && shouldRenderUnitBesideControl(variable)) {
      var unit = document.createElement("span");
      unit.className = CLASS_NAMES.rowUnit;
      unit.textContent = unitLabel;
      controlCell.appendChild(unit);
    }

    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "vp-create-button vp-create-button--ghost " + CLASS_NAMES.rowRemove;
    remove.setAttribute("data-vp-variant-optional-remove", key);
    remove.setAttribute("data-vp-remove-additional-field", key);
    remove.setAttribute("data-vp-optional-row-remove", key);
    remove.setAttribute("data-vp-variable-key", key);
    remove.textContent = "Entfernen";

    row.appendChild(variableCell);
    row.appendChild(controlCell);
    row.appendChild(remove);

    return row;
  }

  function createControl(variable, value) {
    var key = getVariableKey(variable);
    var widget = getVariableWidget(variable);
    var options = getVariableOptions(variable);
    var control;

    if (options.length) {
      control = document.createElement("select");

      var empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "Bitte wählen";
      control.appendChild(empty);

      options.forEach(function (option) {
        var item = normalizeOption(option);
        var node = document.createElement("option");

        node.value = item.value;
        node.textContent = item.label;

        if (String(value) === String(item.value)) {
          node.selected = true;
        }

        control.appendChild(node);
      });
    } else if (widget === "textarea" || widget === "document_list") {
      control = document.createElement("textarea");
      control.rows = widget === "document_list" ? 3 : 2;
      control.value = value === null || typeof value === "undefined" ? "" : valueToControlString(value);
    } else if (widget === "checkbox" || getVariableType(variable) === "boolean" || getVariableType(variable) === "bool") {
      control = document.createElement("input");
      control.type = "checkbox";
      control.checked = value === true || String(value).toLowerCase() === "true" || String(value) === "1";
    } else {
      control = document.createElement("input");

      if (widget === "date") {
        control.type = "date";
      } else if (widget === "url") {
        control.type = "url";
      } else if (widget === "number" || widget === "integer" || widget === "money" || isNumberVariable(variable)) {
        control.type = "number";
        control.step = getVariableStep(variable);
      } else {
        control.type = "text";
      }

      control.value = value === null || typeof value === "undefined" ? "" : valueToControlString(value);
    }

    control.className = "vp-create-variant-optional-fields__input";
    control.name = "definition_values[" + key + "]";
    control.setAttribute("data-vp-variant-optional-control", "true");
    control.setAttribute("data-vp-definition-value-key", key);
    control.setAttribute("data-vp-variable-key", key);
    control.setAttribute("data-variable-key", key);
    control.setAttribute("data-vp-field-key", key);
    control.setAttribute("data-vp-field-value-type", getVariableType(variable));
    control.setAttribute("data-vp-field-widget", widget);
    control.setAttribute("autocomplete", "off");

    applyValidationAttributes(control, variable);

    return control;
  }

  function valueToControlString(value) {
    try {
      if (Array.isArray(value) || value && typeof value === "object") {
        return JSON.stringify(value, null, 2);
      }

      return String(value);
    } catch (error) {
      return String(value || "");
    }
  }

  function shouldRenderUnitBesideControl(variable) {
    try {
      var widget = getVariableWidget(variable);

      return widget !== "checkbox" && widget !== "textarea" && widget !== "document_list";
    } catch (error) {
      return true;
    }
  }

  function applyValidationAttributes(control, variable) {
    try {
      var rules = variable.validation || variable.rules || {};
      var min = firstDefined(rules.min, rules.minimum, variable.min, variable.minimum);
      var max = firstDefined(rules.max, rules.maximum, variable.max, variable.maximum);
      var step = firstDefined(rules.step, variable.step);
      var pattern = firstDefined(rules.pattern, variable.pattern);
      var placeholder = firstDefined(variable.placeholder, variable.ui && variable.ui.placeholder, "");

      if (min !== null && typeof min !== "undefined" && control.type === "number") {
        control.min = String(min);
      }

      if (max !== null && typeof max !== "undefined" && control.type === "number") {
        control.max = String(max);
      }

      if (step !== null && typeof step !== "undefined" && control.type === "number") {
        control.step = String(step);
      }

      if (pattern && control.tagName.toLowerCase() === "input" && control.type !== "number") {
        control.pattern = String(pattern);
      }

      if (placeholder && control.tagName.toLowerCase() !== "select") {
        control.placeholder = String(placeholder);
      }
    } catch (error) {
      warn("applyValidationAttributes failed", error);
    }
  }

  function scrollToSelectedField(key) {
    try {
      if (!key || !state.root) {
        return false;
      }

      var node = query("[data-vp-variant-optional-field-key='" + cssEscape(key) + "'], [data-vp-variant-optional-field='" + cssEscape(key) + "']", state.root);

      if (!node) {
        return false;
      }

      window.setTimeout(function () {
        try {
          node.scrollIntoView({
            behavior: "smooth",
            block: "nearest",
            inline: "nearest"
          });

          var control = query("input, select, textarea, button", node);

          if (control && typeof control.focus === "function") {
            control.focus({
              preventScroll: true
            });
          }
        } catch (scrollError) {
          try {
            node.scrollIntoView();
          } catch (fallbackScrollError) {
            /* no-op */
          }
        }
      }, 40);

      return true;
    } catch (error) {
      return false;
    }
  }

  function addField(key, options) {
    try {
      var safeOptions = options || {};
      var normalizedKey = String(key || "").trim();

      ensureDom();
      loadDefinitions();

      if (!normalizedKey) {
        setStatus("Keine Variable angegeben.", "warning");
        return false;
      }

      ensureVariableForKey(normalizedKey);

      if (!state.variablesByKey[normalizedKey]) {
        setStatus("Variable nicht gefunden.", "warning");
        return false;
      }

      if (isSystemKey(normalizedKey)) {
        setStatus("Systemvariable kann nicht manuell hinzugefügt werden.", "warning");
        return false;
      }

      if (containsString(state.profileFieldKeys, normalizedKey)) {
        setStatus("Variable ist bereits Teil des Profils.", "warning");
        return false;
      }

      if (!containsString(state.additionalFieldKeys, normalizedKey)) {
        state.additionalFieldKeys.push(normalizedKey);
      }

      if (!Object.prototype.hasOwnProperty.call(state.definitionValues, normalizedKey)) {
        state.definitionValues[normalizedKey] = defaultValueForVariable(state.variablesByKey[normalizedKey]);
      }

      state.additionalFieldKeys = filterAdditionalKeys(state.additionalFieldKeys);
      state.pendingScrollKey = safeOptions.scrollIntoView === false ? "" : normalizedKey;

      renderAvailableVariables();
      renderSelectedFields();

      syncToDrawerValues({
        reason: safeOptions.reason || "add-field"
      });

      setStatus("Variable hinzugefügt: " + getVariableLabel(state.variablesByKey[normalizedKey]), "ok");

      dispatchDocument("vectoplan:create:variant-optional-field-added", {
        component: COMPONENT_NAME,
        version: VERSION,
        key: normalizedKey,
        variable: state.variablesByKey[normalizedKey],
        snapshot: getRuntimeSnapshot()
      });

      return true;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("addField failed", error);
      setStatus("Variable konnte nicht hinzugefügt werden.", "error");
      return false;
    }
  }

  function removeField(key, options) {
    try {
      var normalizedKey = String(key || "").trim();
      var safeOptions = options || {};

      state.additionalFieldKeys = state.additionalFieldKeys.filter(function (item) {
        return item !== normalizedKey;
      });

      if (state.definitionValues && Object.prototype.hasOwnProperty.call(state.definitionValues, normalizedKey)) {
        delete state.definitionValues[normalizedKey];
      }

      renderAvailableVariables();
      renderSelectedFields();

      syncToDrawerValues({
        reason: safeOptions.reason || "remove-field",
        removeMissingValues: true
      });

      setStatus("Variable entfernt.", "ok");

      dispatchDocument("vectoplan:create:variant-optional-field-removed", {
        component: COMPONENT_NAME,
        version: VERSION,
        key: normalizedKey,
        snapshot: getRuntimeSnapshot()
      });

      return true;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("removeField failed", error);
      setStatus("Variable konnte nicht entfernt werden.", "error");
      return false;
    }
  }

  function collectValues() {
    try {
      var values = {};

      if (!state.root) {
        return values;
      }

      queryAll(SELECTORS.valueControl, state.root).forEach(function (control) {
        var key = control.getAttribute("data-vp-definition-value-key") ||
          control.getAttribute("data-vp-variable-key") ||
          control.getAttribute("data-vp-field-key") ||
          "";

        if (!key) {
          return;
        }

        values[key] = readControlValue(control, state.variablesByKey[key]);
      });

      return values;
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("collectValues failed", error);
      return {};
    }
  }

  function syncToDrawerValues(options) {
    try {
      var safeOptions = options || {};

      if (state.syncInProgress && safeOptions.force !== true) {
        state.suppressedSyncCount += 1;
        return {
          values: state.definitionValues || {},
          additional_field_keys: state.additionalFieldKeys.slice(),
          additionalFieldKeys: state.additionalFieldKeys.slice()
        };
      }

      state.syncInProgress = true;

      var optionalValues = collectValues();
      var currentValues = {};

      if (state.valuesJsonField && state.valuesJsonField.value) {
        currentValues = safeJsonParse(state.valuesJsonField.value, {});
      }

      currentValues = mergeObjects(currentValues, state.definitionValues || {});
      currentValues = mergeObjects(currentValues, optionalValues);

      if (safeOptions.removeMissingValues) {
        Object.keys(currentValues).forEach(function (key) {
          if (
            !isCoreValueKey(key) &&
            !isSystemKey(key) &&
            !containsString(state.profileFieldKeys, key) &&
            !containsString(state.additionalFieldKeys, key)
          ) {
            delete currentValues[key];
          }
        });
      }

      state.definitionValues = currentValues;

      writeFieldValueSilently(state.valuesJsonField, stringifyJson(currentValues));
      writeFieldValueSilently(state.additionalKeysJsonField, stringifyJson(state.additionalFieldKeys));

      state.syncCount += 1;

      if (!safeOptions.silent) {
        dispatchDocument("vectoplan:create:variant-optional-fields-synced", {
          component: COMPONENT_NAME,
          version: VERSION,
          values: cloneObject(currentValues),
          additionalFieldKeys: state.additionalFieldKeys.slice(),
          additional_field_keys: state.additionalFieldKeys.slice(),
          snapshot: getRuntimeSnapshot()
        });

        dispatchDocument("vectoplan:create:variant-values-changed", {
          component: COMPONENT_NAME,
          version: VERSION,
          source: "variant_optional_fields",
          values: cloneObject(currentValues),
          additionalFieldKeys: state.additionalFieldKeys.slice(),
          additional_field_keys: state.additionalFieldKeys.slice()
        });
      }

      state.syncInProgress = false;

      return {
        values: currentValues,
        additional_field_keys: state.additionalFieldKeys.slice(),
        additionalFieldKeys: state.additionalFieldKeys.slice()
      };
    } catch (error) {
      state.syncInProgress = false;
      state.lastError = normalizeError(error);
      warn("syncToDrawerValues failed", error);

      return {
        values: state.definitionValues || {},
        additional_field_keys: state.additionalFieldKeys.slice(),
        additionalFieldKeys: state.additionalFieldKeys.slice()
      };
    }
  }

  function writeFieldValueSilently(field, value) {
    try {
      if (!field) {
        return false;
      }

      var next = value === null || typeof value === "undefined" ? "" : String(value);

      if (field.value === next) {
        return false;
      }

      field.value = next;
      field.setAttribute("data-vp-last-optional-sync", String(Date.now()));
      field.setAttribute("data-vp-programmatic-event-source", COMPONENT_NAME);

      return true;
    } catch (error) {
      return false;
    }
  }

  function getAvailableVariables(options) {
    try {
      var safeOptions = options || {};
      var queryText = safeOptions.ignoreSearch ? "" : normalizeSearch(state.searchText);
      var group = safeOptions.ignoreGroup ? "" : state.groupFilter;

      return state.variables.filter(function (variable) {
        var key = getVariableKey(variable);

        if (!key) {
          return false;
        }

        if (isSystemVariable(variable)) {
          return false;
        }

        if (containsString(state.profileFieldKeys, key)) {
          return false;
        }

        if (containsString(state.additionalFieldKeys, key)) {
          return false;
        }

        if (!isCompatibleVariable(variable)) {
          return false;
        }

        if (group && getVariableGroup(variable) !== group) {
          return false;
        }

        if (queryText && !matchesVariableSearch(variable, queryText)) {
          return false;
        }

        return true;
      }).sort(compareVariables);
    } catch (error) {
      warn("getAvailableVariables failed", error);
      return [];
    }
  }

  function isCompatibleVariable(variable) {
    try {
      var compatibility = variable.compatibility || variable.context || {};
      var context = state.activeContext || {};

      if (!matchesCompatibilityList(compatibility.object_kinds || compatibility.objectKinds || variable.object_kinds || variable.objectKinds, context.object_kind)) {
        return false;
      }

      if (!matchesCompatibilityList(compatibility.domains || variable.domains, context.domain)) {
        return false;
      }

      if (!matchesCompatibilityList(compatibility.categories || variable.categories, context.category)) {
        return false;
      }

      if (!matchesCompatibilityList(compatibility.subcategories || variable.subcategories, context.subcategory)) {
        return false;
      }

      if (!matchesCompatibilityList(compatibility.family_profiles || compatibility.familyProfiles || variable.family_profiles || variable.familyProfiles, context.family_profile_id)) {
        return false;
      }

      if (!matchesCompatibilityList(compatibility.variant_profiles || compatibility.variantProfiles || variable.variant_profiles || variable.variantProfiles, context.variant_profile_id)) {
        return false;
      }

      return true;
    } catch (error) {
      return true;
    }
  }

  function matchesCompatibilityList(list, value) {
    try {
      if (!list || (Array.isArray(list) && !list.length)) {
        return true;
      }

      var values = Array.isArray(list) ? list : String(list).split(",");
      var normalizedValue = normalizeToken(value, "");

      if (!normalizedValue) {
        return true;
      }

      return values.some(function (item) {
        var normalizedItem = normalizeToken(item, "");

        return !normalizedItem || normalizedItem === "*" || normalizedItem === "any" || normalizedItem === normalizedValue;
      });
    } catch (error) {
      return true;
    }
  }

  function matchesVariableSearch(variable, queryText) {
    try {
      var haystack = [
        getVariableKey(variable),
        getVariableLabel(variable),
        getVariableDescription(variable),
        variable.help_text || variable.helpText || "",
        getVariableGroup(variable),
        getVariableTypeLabel(variable),
        getVariableUnitLabel(variable)
      ].join(" ").toLowerCase();

      return normalizeSearch(haystack).indexOf(queryText) !== -1;
    } catch (error) {
      return false;
    }
  }

  function updateCountsAndStatus() {
    try {
      var availableCount = getAvailableVariables({
        ignoreSearch: true,
        ignoreGroup: true
      }).length;
      var selectedCount = state.additionalFieldKeys.length;

      setNodeText(state.availableCountNode, "Verfügbare Variablen: " + String(availableCount));
      setNodeText(state.selectedCountNode, String(selectedCount));

      if (state.selectedEmpty) {
        state.selectedEmpty.hidden = selectedCount > 0;
      }

      if (state.root) {
        state.root.classList.toggle(CLASS_NAMES.rootEmpty, selectedCount === 0);
        state.root.classList.toggle(CLASS_NAMES.rootHasSelected, selectedCount > 0);
      }

      setStatus(selectedCount
        ? selectedCount + " Zusatzfeld" + (selectedCount === 1 ? "" : "er") + " aktiv."
        : "Keine Zusatzfelder aktiv.",
      selectedCount ? "ok" : "info");
    } catch (error) {
      warn("updateCountsAndStatus failed", error);
    }
  }

  function setStatus(message, level) {
    try {
      var node = state.statusNode || query(SELECTORS.statusNode, state.root);

      if (!node) {
        return;
      }

      node.textContent = message || "";
      node.setAttribute("data-vp-status-level", level || "info");
    } catch (error) {
      /* no-op */
    }
  }

  function renderError(error) {
    try {
      ensureDom();

      if (!state.availableList) {
        return;
      }

      state.availableList.innerHTML = "";

      var node = document.createElement("p");
      node.className = CLASS_NAMES.empty;
      node.textContent = "Optionale Variablen konnten nicht geladen werden: " + (error && error.message ? error.message : String(error));

      state.availableList.appendChild(node);
      setStatus("Fehler beim Laden optionaler Variablen.", "error");
    } catch (renderErrorObject) {
      warn("renderError failed", renderErrorObject);
    }
  }

  function getAdditionalFieldKeys() {
    return state.additionalFieldKeys.slice();
  }

  function getSelectedFieldKeys() {
    return getAdditionalFieldKeys();
  }

  function setAdditionalFieldKeys(keys, options) {
    try {
      var safeOptions = options || {};

      ensureDom();
      loadDefinitions();
      resolveProfileFieldKeys();

      state.additionalFieldKeys = filterAdditionalKeys(keys);

      state.additionalFieldKeys.forEach(function (key) {
        if (!Object.prototype.hasOwnProperty.call(state.definitionValues, key)) {
          state.definitionValues[key] = defaultValueForVariable(state.variablesByKey[key]);
        }
      });

      renderAvailableVariables();
      renderSelectedFields();

      syncToDrawerValues({
        reason: safeOptions.reason || "set-additional-field-keys",
        silent: safeOptions.silent !== false
      });

      return state.additionalFieldKeys.slice();
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("setAdditionalFieldKeys failed", error);
      return state.additionalFieldKeys.slice();
    }
  }

  function resetRuntimeState(options) {
    try {
      var keepDom = options && options.keepDom;

      state.activeProfile = null;
      state.activeProfileId = "";
      state.activeContext = {};
      state.profileFieldKeys = [];
      state.additionalFieldKeys = [];
      state.definitionValues = {};
      state.searchText = "";
      state.groupFilter = "";
      state.pendingScrollKey = "";

      if (!keepDom && state.root) {
        state.root.remove();
        state.root = null;
      } else if (state.root) {
        render();
        syncToDrawerValues({
          reason: "reset",
          silent: true,
          removeMissingValues: true
        });
      }
    } catch (error) {
      state.lastError = normalizeError(error);
      warn("resetRuntimeState failed", error);
    }
  }

  function getRuntimeSnapshot() {
    return {
      version: VERSION,
      initialized: state.initialized,
      hasRoot: !!state.root,
      hasAvailableColumns: !!state.availableColumns,
      variableCount: state.variables.length,
      availableCount: getAvailableVariables({
        ignoreSearch: true,
        ignoreGroup: true
      }).length,
      selectedCount: state.additionalFieldKeys.length,
      activeProfileId: state.activeProfileId,
      activeContext: cloneObject(state.activeContext),
      profileFieldKeys: state.profileFieldKeys.slice(),
      additionalFieldKeys: state.additionalFieldKeys.slice(),
      additional_field_keys: state.additionalFieldKeys.slice(),
      definitionValues: cloneObject(state.definitionValues),
      searchText: "",
      groupFilter: "",
      uiMode: "list-no-search",
      availableLayout: "table-list",
      lastRefreshReason: state.lastRefreshReason,
      lastError: state.lastError,
      renderCount: state.renderCount,
      syncCount: state.syncCount,
      loadCount: state.loadCount,
      suppressedRefreshCount: state.suppressedRefreshCount,
      suppressedSyncCount: state.suppressedSyncCount
    };
  }

  function extractProfileFieldKeys(profile) {
    var keys = [];

    try {
      if (!profile || typeof profile !== "object") {
        return keys;
      }

      keys = keys.concat(parseKeyList(profile.required_fields || profile.requiredFields));
      keys = keys.concat(parseKeyList(profile.optional_fields || profile.optionalFields));
      keys = keys.concat(parseKeyList(profile.summary_fields || profile.summaryFields));
      keys = keys.concat(parseKeyList(profile.fields));
      keys = keys.concat(parseKeyList(profile.all_fields || profile.allFields));

      if (profile.default_values || profile.defaultValues) {
        keys = keys.concat(Object.keys(profile.default_values || profile.defaultValues || {}));
      }

      var sections = profile.sections || profile.field_sections || profile.fieldSections || [];

      if (Array.isArray(sections)) {
        sections.forEach(function (section) {
          keys = keys.concat(extractSectionFieldKeys(section));
        });
      }

      return uniqueStrings(keys);
    } catch (error) {
      warn("extractProfileFieldKeys failed", error);
      return uniqueStrings(keys);
    }
  }

  function extractSectionFieldKeys(section) {
    var keys = [];

    try {
      if (!section || typeof section !== "object") {
        return keys;
      }

      var fields = section.fields || section.field_keys || section.fieldKeys || [];

      if (Array.isArray(fields)) {
        fields.forEach(function (field) {
          if (typeof field === "string") {
            keys.push(field);
          } else if (field && typeof field === "object") {
            keys.push(field.key || field.field_key || field.fieldKey || field.variable_key || field.variableKey || field.id || "");
          }
        });
      }

      return keys.filter(Boolean);
    } catch (error) {
      return keys;
    }
  }

  function readRenderedProfileFieldKeys() {
    var keys = [];

    try {
      var root = state.profileFieldsRoot || state.drawerRoot || document;

      queryAll("[data-vp-variable-key], [data-variable-key], [data-vp-field-key], [data-field-key], [name^='definition_values[']", root).forEach(function (node) {
        if (state.root && state.root.contains(node)) {
          return;
        }

        var key = node.getAttribute("data-vp-variable-key") ||
          node.getAttribute("data-variable-key") ||
          node.getAttribute("data-vp-field-key") ||
          node.getAttribute("data-field-key") ||
          keyFromDefinitionValueName(node.getAttribute("name") || "");

        if (key) {
          keys.push(key);
        }
      });

      return uniqueStrings(keys);
    } catch (error) {
      warn("readRenderedProfileFieldKeys failed", error);
      return [];
    }
  }

  function findProfileInDefinitions(profileId) {
    try {
      var profiles = [];
      var sources = getDefinitionSources();

      sources.forEach(function (source) {
        var normalized = normalizeDefinitions(source);
        profiles = profiles.concat(normalized.variant_profiles || []);
      });

      for (var index = 0; index < profiles.length; index += 1) {
        if (getProfileId(profiles[index]) === profileId) {
          return profiles[index];
        }
      }

      return null;
    } catch (error) {
      return null;
    }
  }

  function getDrawerSession() {
    try {
      if (window.VectoplanCreateVariantDrawer && typeof window.VectoplanCreateVariantDrawer.getActiveSession === "function") {
        return window.VectoplanCreateVariantDrawer.getActiveSession() || {};
      }

      return {};
    } catch (error) {
      return {};
    }
  }

  function extractVariantFromDetail(detail) {
    try {
      if (!detail || typeof detail !== "object") {
        return null;
      }

      return detail.variant || detail.currentVariant || detail.session || detail.payload || detail.data || null;
    } catch (error) {
      return null;
    }
  }

  function extractVariantFromSession(session) {
    try {
      if (!session || typeof session !== "object") {
        return null;
      }

      return session.variant || session.currentVariant || session.payload || session.data || session;
    } catch (error) {
      return null;
    }
  }

  function extractDefinitionValues(source) {
    try {
      if (!source || typeof source !== "object") {
        return {};
      }

      var candidate = source.definition_values ||
        source.definitionValues ||
        source.values ||
        source.definition_values_json ||
        source.definitionValuesJson ||
        source.values_json ||
        source.valuesJson ||
        {};

      if (typeof candidate === "string") {
        return safeJsonParse(candidate, {});
      }

      if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
        return cloneObject(candidate);
      }

      return {};
    } catch (error) {
      return {};
    }
  }

  function extractAdditionalKeys(source) {
    try {
      if (!source || typeof source !== "object") {
        return [];
      }

      return parseKeyList(
        source.additional_field_keys ||
        source.additionalFieldKeys ||
        source.additional_fields ||
        source.additionalFields ||
        source.additional_field_keys_json ||
        source.additionalFieldKeysJson ||
        []
      );
    } catch (error) {
      return [];
    }
  }

  function readControlValue(control, variable) {
    try {
      if (!control) {
        return "";
      }

      if (control.type === "checkbox") {
        return !!control.checked;
      }

      var raw = typeof control.value !== "undefined" ? control.value : "";

      if (raw === "") {
        return "";
      }

      if (getVariableType(variable) === "integer" || getVariableType(variable) === "int") {
        var integer = parseInt(String(raw), 10);

        return Number.isFinite(integer) ? integer : raw;
      }

      if (isNumberVariable(variable)) {
        var number = Number(String(raw).replace(",", "."));

        return Number.isFinite(number) ? number : raw;
      }

      if (getVariableType(variable) === "object") {
        return safeJsonParse(raw, raw);
      }

      if (getVariableType(variable) === "array" || getVariableType(variable) === "document_list") {
        return safeJsonParse(raw, raw);
      }

      return raw;
    } catch (error) {
      return "";
    }
  }

  function getValueForKey(key) {
    try {
      if (state.definitionValues && Object.prototype.hasOwnProperty.call(state.definitionValues, key)) {
        return state.definitionValues[key];
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function ensureVariableForKey(key) {
    try {
      var normalizedKey = String(key || "").trim();

      if (!normalizedKey || state.variablesByKey[normalizedKey]) {
        return state.variablesByKey[normalizedKey] || null;
      }

      if (!Object.prototype.hasOwnProperty.call(state.definitionValues || {}, normalizedKey)) {
        return null;
      }

      var value = state.definitionValues[normalizedKey];
      var synthetic = {
        key: normalizedKey,
        label: humanize(normalizedKey.split(".").pop() || normalizedKey),
        group: normalizedKey.indexOf(".") !== -1 ? normalizedKey.split(".")[0] : "weitere",
        description: "Zusätzlicher Wert aus vorhandenen Variant-Daten.",
        value_type: typeof value === "number" ? "number" : typeof value === "boolean" ? "boolean" : Array.isArray(value) ? "array" : "string",
        widget: typeof value === "boolean" ? "checkbox" : typeof value === "number" ? "number" : "input",
        synthetic: true
      };

      state.variablesByKey[normalizedKey] = synthetic;
      state.variables.push(synthetic);

      return synthetic;
    } catch (error) {
      return null;
    }
  }

  function defaultValueForVariable(variable) {
    try {
      if (!variable) {
        return "";
      }

      if (Object.prototype.hasOwnProperty.call(variable, "default_value")) {
        return cloneAny(variable.default_value);
      }

      if (Object.prototype.hasOwnProperty.call(variable, "defaultValue")) {
        return cloneAny(variable.defaultValue);
      }

      var type = getVariableType(variable);
      var widget = getVariableWidget(variable);

      if (type === "boolean" || type === "bool" || widget === "checkbox") {
        return false;
      }

      if (type === "number" || type === "integer" || type === "int" || type === "float" || type === "decimal" || widget === "number" || widget === "money") {
        return "";
      }

      if (type === "array" || type === "document_list" || widget === "document_list") {
        return [];
      }

      if (type === "object") {
        return {};
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function isSystemVariable(variable) {
    try {
      var key = getVariableKey(variable);

      if (isSystemKey(key)) {
        return true;
      }

      if (variable.system_managed === true || variable.systemManaged === true || variable.editable === false) {
        return true;
      }

      if (variable.hidden === true) {
        return true;
      }

      var ui = variable.ui || {};

      if (ui.hidden === true || ui.visible === false || ui.expose_in_optional_picker === false || ui.exposeInOptionalPicker === false) {
        return true;
      }

      if (utils() && typeof utils().shouldHideVariableInDrawer === "function") {
        return !!utils().shouldHideVariableInDrawer(variable);
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function isSystemKey(key) {
    return !!SYSTEM_KEYS[String(key || "").trim()];
  }

  function isCoreValueKey(key) {
    return !!CORE_VALUE_KEYS[String(key || "").trim()];
  }

  function getVariableKey(variable) {
    try {
      if (!variable || typeof variable !== "object") {
        return "";
      }

      return String(
        variable.key ||
        variable.variable_key ||
        variable.variableKey ||
        variable.path ||
        variable.id ||
        variable.name ||
        ""
      ).trim();
    } catch (error) {
      return "";
    }
  }

  function getVariableLabel(variable) {
    try {
      var key = getVariableKey(variable);

      return String(
        variable.label ||
        variable.display_label ||
        variable.displayLabel ||
        variable.title ||
        variable.name ||
        humanize(key)
      ).trim();
    } catch (error) {
      return "Variable";
    }
  }

  function getVariableDescription(variable) {
    try {
      if (!variable || typeof variable !== "object") {
        return "";
      }

      var ui = variable.ui || {};
      var metadata = variable.metadata || {};

      var description = variable.description ||
        variable.help_text ||
        variable.helpText ||
        variable.short_description ||
        variable.shortDescription ||
        ui.description ||
        ui.help_text ||
        ui.helpText ||
        metadata.description ||
        metadata.help_text ||
        metadata.helpText ||
        "";

      if (description) {
        return String(description).trim();
      }

      var key = getVariableKey(variable);
      var group = groupLabel(getVariableGroup(variable));
      var unitLabel = getVariableUnitLabel(variable);

      return [key, group, unitLabel].filter(Boolean).join(" · ");
    } catch (error) {
      return "";
    }
  }

  function getVariableGroup(variable) {
    try {
      var key = getVariableKey(variable);
      var group = variable.group ||
        variable.category ||
        variable.section ||
        variable.namespace ||
        variable.domain ||
        "";

      if (!group && key.indexOf(".") !== -1) {
        group = key.split(".")[0];
      }

      return normalizeToken(group || "weitere", "weitere");
    } catch (error) {
      return "weitere";
    }
  }

  function groupLabel(group) {
    var labels = {
      physics: "Bauphysik",
      physical: "Physisch",
      fire: "Brandschutz",
      acoustics: "Akustik",
      acoustic: "Akustik",
      density: "Dichte",
      material: "Material",
      dimensions: "Geometrie",
      geometry: "Geometrie",
      structure: "Tragwerk",
      structural: "Tragwerk",
      commercial: "Kalkulation",
      calculation: "Kalkulation",
      price: "Preis",
      manufacturer: "Hersteller",
      documents: "Dokumente",
      document: "Dokumente",
      sustainability: "Nachhaltigkeit",
      energy: "Energie",
      thermal: "Wärmeschutz",
      routing: "Routing",
      context: "Kontext",
      variant: "Variante",
      concrete: "Concrete",
      connection: "Connection",
      dynamic: "Dynamic",
      exposure: "Exposure",
      flow: "Flow",
      module: "Module",
      product: "Product",
      reinforcement: "Reinforcement",
      render: "Render",
      road: "Road",
      sanitary: "Sanitary",
      surface: "Surface",
      usage: "Usage",
      wall_masonry: "Wall masonry",
      weitere: "Weitere"
    };

    return labels[group] || humanize(group);
  }

  function getVariableType(variable) {
    try {
      return normalizeToken(
        variable.value_type ||
        variable.valueType ||
        variable.data_type ||
        variable.dataType ||
        variable.type ||
        "string",
        "string"
      );
    } catch (error) {
      return "string";
    }
  }

  function getVariableTypeLabel(variable) {
    try {
      var type = getVariableType(variable);
      var widget = getVariableWidget(variable);
      var options = getVariableOptions(variable);

      if (options.length) {
        if (type === "enum" || type === "select") {
          return "enum/select";
        }

        if (type === "string") {
          return "string/select";
        }

        return type + "/select";
      }

      if (type === "boolean" || type === "bool" || widget === "checkbox") {
        return "boolean/checkbox";
      }

      if (type === "integer" || type === "int") {
        return "integer/number";
      }

      if (type === "number" || type === "float" || type === "decimal") {
        return "number";
      }

      if (type === "money" || widget === "money") {
        return "money";
      }

      if (type === "document_list" || widget === "document_list") {
        return "document_list";
      }

      if (widget && widget !== type && widget !== "input") {
        return type + "/" + widget;
      }

      return type || "string";
    } catch (error) {
      return "string";
    }
  }

  function getVariableWidget(variable) {
    try {
      var ui = variable.ui || {};
      var widget = variable.widget || ui.widget || "";

      if (widget) {
        return normalizeToken(widget, "input");
      }

      var type = getVariableType(variable);

      if (type === "boolean" || type === "bool") {
        return "checkbox";
      }

      if (type === "number" || type === "float" || type === "decimal") {
        return "number";
      }

      if (type === "integer" || type === "int") {
        return "integer";
      }

      if (type === "date") {
        return "date";
      }

      if (type === "url") {
        return "url";
      }

      if (type === "text" || type === "long_text" || type === "markdown") {
        return "textarea";
      }

      if (type === "document_list") {
        return "document_list";
      }

      return "input";
    } catch (error) {
      return "input";
    }
  }

  function getVariableOptions(variable) {
    try {
      var options = variable.options ||
        variable.enum ||
        variable.enum_values ||
        variable.enumValues ||
        variable.allowed_values ||
        variable.allowedValues ||
        [];

      return Array.isArray(options) ? options : [];
    } catch (error) {
      return [];
    }
  }

  function normalizeOption(option) {
    try {
      if (option && typeof option === "object") {
        return {
          value: String(option.value || option.id || option.key || option.label || ""),
          label: String(option.label || option.name || option.value || option.id || option.key || "")
        };
      }

      return {
        value: String(option),
        label: String(option)
      };
    } catch (error) {
      return {
        value: "",
        label: ""
      };
    }
  }

  function getVariableUnitLabel(variable) {
    try {
      var unitId = variable.unit_id || variable.unitId || variable.unit || variable.default_unit || variable.defaultUnit || "";

      if (!unitId) {
        return "";
      }

      var unit = state.unitsById[unitId] || state.unitsById[String(unitId)] || null;

      if (!unit) {
        return String(unitId);
      }

      return String(unit.symbol || unit.label || unit.name || unit.id || unitId);
    } catch (error) {
      return "";
    }
  }

  function getUnitId(unit) {
    try {
      return String(unit.id || unit.key || unit.unit_id || unit.unitId || unit.symbol || "").trim();
    } catch (error) {
      return "";
    }
  }

  function getProfileId(profile) {
    try {
      if (!profile || typeof profile !== "object") {
        return "";
      }

      return String(profile.profile_id || profile.profileId || profile.id || profile.key || "").trim();
    } catch (error) {
      return "";
    }
  }

  function isNumberVariable(variable) {
    var type = getVariableType(variable);
    var widget = getVariableWidget(variable);

    return type === "number" ||
      type === "float" ||
      type === "decimal" ||
      type === "integer" ||
      type === "int" ||
      widget === "number" ||
      widget === "integer" ||
      widget === "money";
  }

  function getVariableStep(variable) {
    var type = getVariableType(variable);
    var step = firstDefined(variable.step, variable.increment, variable.validation && variable.validation.step);

    if (step !== null && typeof step !== "undefined" && step !== "") {
      return String(step);
    }

    if (type === "integer" || type === "int") {
      return "1";
    }

    return "any";
  }

  function getDefinitionMaps() {
    try {
      if (window.VectoplanCreateDefinitionMaps && typeof window.VectoplanCreateDefinitionMaps === "object") {
        return window.VectoplanCreateDefinitionMaps;
      }

      if (window.VectoplanCreateVariantProfiles && typeof window.VectoplanCreateVariantProfiles.getDefinitionMaps === "function") {
        return window.VectoplanCreateVariantProfiles.getDefinitionMaps();
      }

      if (utils() && typeof utils().buildDefinitionMaps === "function") {
        return utils().buildDefinitionMaps(window.VectoplanCreateDefinitions || {});
      }

      return {};
    } catch (error) {
      return {};
    }
  }

  function toArrayOrObjectValues(value) {
    try {
      if (!value) {
        return [];
      }

      if (Array.isArray(value)) {
        return value.slice();
      }

      if (typeof value === "object") {
        return Object.keys(value).map(function (key) {
          return value[key];
        });
      }

      return [];
    } catch (error) {
      return [];
    }
  }

  function uniqueVariables(variables) {
    var seen = {};
    var result = [];

    try {
      variables.forEach(function (variable) {
        var key = getVariableKey(variable);

        if (!key || seen[key]) {
          return;
        }

        seen[key] = true;
        result.push(variable);
      });

      return result;
    } catch (error) {
      return result;
    }
  }

  function uniqueUnits(units) {
    var seen = {};
    var result = [];

    try {
      units.forEach(function (unit) {
        var id = getUnitId(unit);

        if (!id || seen[id]) {
          return;
        }

        seen[id] = true;
        result.push(unit);
      });

      return result;
    } catch (error) {
      return result;
    }
  }

  function query(selector, root) {
    try {
      return (root || document).querySelector(selector);
    } catch (error) {
      return null;
    }
  }

  function queryAll(selector, root) {
    try {
      return Array.prototype.slice.call((root || document).querySelectorAll(selector));
    } catch (error) {
      return [];
    }
  }

  function containsRoot(node) {
    try {
      return !!(state.root && node && state.root.contains(node));
    } catch (error) {
      return false;
    }
  }

  function updateText(selector, value, root) {
    try {
      var node = query(selector, root || document);

      if (node) {
        node.textContent = value;
      }
    } catch (error) {
      /* no-op */
    }
  }

  function setNodeText(node, value) {
    try {
      if (node) {
        node.textContent = value === null || typeof value === "undefined" ? "" : String(value);
      }
    } catch (error) {
      /* no-op */
    }
  }

  function readValue(form, name) {
    try {
      if (!form || !name) {
        return "";
      }

      var field = form.elements ? form.elements[name] : null;

      if (!field) {
        field = query("[name='" + cssEscape(name) + "']", form);
      }

      return field && typeof field.value !== "undefined" ? String(field.value) : "";
    } catch (error) {
      return "";
    }
  }

  function getAttr(node, name) {
    try {
      return node && name ? node.getAttribute(name) || "" : "";
    } catch (error) {
      return "";
    }
  }

  function keyFromDefinitionValueName(name) {
    try {
      var match = String(name || "").match(/^definition_values\[(.+)]$/);
      return match && match[1] ? match[1] : "";
    } catch (error) {
      return "";
    }
  }

  function parseKeyList(value) {
    try {
      if (!value) {
        return [];
      }

      if (Array.isArray(value)) {
        return value.map(String);
      }

      if (typeof value === "string") {
        var text = value.trim();

        if (!text) {
          return [];
        }

        if (text.charAt(0) === "[" || text.charAt(0) === "{") {
          var parsed = safeJsonParse(text, []);

          if (Array.isArray(parsed)) {
            return parsed.map(String);
          }

          if (parsed && Array.isArray(parsed.keys)) {
            return parsed.keys.map(String);
          }
        }

        return text.split(",").map(function (item) {
          return item.trim();
        });
      }

      return [];
    } catch (error) {
      return [];
    }
  }

  function normalizeSearch(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  function normalizeToken(value, fallback) {
    try {
      if (utils() && typeof utils().normalizeId === "function") {
        return utils().normalizeId(value || fallback || "");
      }

      return String(value || fallback || "")
        .trim()
        .toLowerCase()
        .replace(/[-\s]+/g, "_")
        .replace(/[^a-z0-9_]/g, "") || fallback || "";
    } catch (error) {
      return fallback || "";
    }
  }

  function humanize(value) {
    return String(value || "")
      .replace(/[._-]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/^./, function (char) {
        return char.toUpperCase();
      });
  }

  function compareVariables(a, b) {
    var ga = groupLabel(getVariableGroup(a));
    var gb = groupLabel(getVariableGroup(b));

    if (ga !== gb) {
      return compareText(ga, gb);
    }

    return compareText(getVariableLabel(a), getVariableLabel(b));
  }

  function compareText(a, b) {
    return String(a || "").localeCompare(String(b || ""), "de", {
      sensitivity: "base"
    });
  }

  function containsString(list, value) {
    return Array.isArray(list) && list.indexOf(value) !== -1;
  }

  function uniqueStrings(values) {
    var seen = {};
    var result = [];

    (Array.isArray(values) ? values : []).forEach(function (value) {
      var text = String(value || "").trim();

      if (!text || seen[text]) {
        return;
      }

      seen[text] = true;
      result.push(text);
    });

    return result;
  }

  function safeMerge() {
    var result = {};

    Array.prototype.slice.call(arguments).forEach(function (object) {
      if (!object || typeof object !== "object") {
        return;
      }

      Object.keys(object).forEach(function (key) {
        result[key] = object[key];
      });
    });

    return result;
  }

  function mergeObjects(base, extra) {
    var result = cloneObject(base);

    try {
      Object.keys(extra || {}).forEach(function (key) {
        result[key] = extra[key];
      });
    } catch (error) {
      /* no-op */
    }

    return result;
  }

  function cloneObject(value) {
    try {
      return JSON.parse(JSON.stringify(value || {}));
    } catch (error) {
      return {};
    }
  }

  function cloneAny(value) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      return value;
    }
  }

  function safeJsonParse(value, fallback) {
    try {
      if (value && typeof value === "object") {
        return value;
      }

      var text = String(value || "");

      if (!text.trim()) {
        return fallback;
      }

      return JSON.parse(text);
    } catch (error) {
      return fallback;
    }
  }

  function stringifyJson(value) {
    try {
      return JSON.stringify(value || (Array.isArray(value) ? [] : {}), null, 2);
    } catch (error) {
      return Array.isArray(value) ? "[]" : "{}";
    }
  }

  function firstDefined() {
    for (var index = 0; index < arguments.length; index += 1) {
      if (arguments[index] !== null && typeof arguments[index] !== "undefined") {
        return arguments[index];
      }
    }

    return null;
  }

  function cssEscape(value) {
    try {
      if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(String(value));
      }

      return String(value).replace(/["\\]/g, "\\$&");
    } catch (error) {
      return String(value || "").replace(/["\\]/g, "\\$&");
    }
  }

  function safeSetAttribute(node, name, value) {
    try {
      if (node) {
        node.setAttribute(name, String(value));
      }
    } catch (error) {
      /* no-op */
    }
  }

  function dispatchDocument(name, detail) {
    try {
      if (utils() && typeof utils().dispatchDocument === "function") {
        utils().dispatchDocument(name, detail || {}, {
          silent: true
        });
        return;
      }

      document.dispatchEvent(new CustomEvent(name, {
        bubbles: true,
        cancelable: false,
        detail: detail || {}
      }));
    } catch (error) {
      /* no-op */
    }
  }

  function normalizeError(error) {
    return {
      message: String(error && error.message ? error.message : error),
      stack: error && error.stack ? String(error.stack) : "",
      timestamp: new Date().toISOString()
    };
  }

  function warn(message, error) {
    try {
      if (utils() && typeof utils().warn === "function") {
        utils().warn("[" + COMPONENT_NAME + "] " + message, error || "");
        return;
      }

      if (window.console && typeof window.console.warn === "function") {
        window.console.warn("[" + COMPONENT_NAME + "] " + message, error || "");
      }
    } catch (consoleError) {
      /* no-op */
    }
  }

  var api = {
    version: VERSION,
    __version: VERSION,

    initialize: initialize,
    refresh: refresh,
    render: render,

    loadVariant: loadVariant,
    restoreFromVariant: restoreFromVariant,
    setValues: setValues,

    addField: addField,
    removeField: removeField,

    collectValues: collectValues,
    syncToDrawerValues: syncToDrawerValues,

    getAdditionalFieldKeys: getAdditionalFieldKeys,
    getSelectedFieldKeys: getSelectedFieldKeys,
    setAdditionalFieldKeys: setAdditionalFieldKeys,

    getAvailableVariables: getAvailableVariables,
    getRuntimeSnapshot: getRuntimeSnapshot
  };

  window[GLOBAL_NAME] = api;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, {
      once: true
    });
  } else {
    initialize();
  }
})();