/* services/vectoplan-library/static/library_admin/js/create_preview.js */

/* -----------------------------------------------------------------------------
  VECTOPLAN Library · VPLIB Create Preview Runtime

  Zweck:
  - Eigenständige Preview-/Kontext-Schicht für /create.
  - Entlastet create.js.
  - Steuert Taxonomie-Filterung, Taxonomiepfad, technische Kontextregeln,
    Geometrie-Zusammenfassungen und Context-Sync.
  - Hält die rechte Preview bewusst leer: keine sichtbaren Preview-Texte,
    keine Statusmeldungen, keine Metriken, keine Placeholder-Kopien.
  - Synchronisiert Domain, Kategorie, Unterkategorie und technische Objektart in
    den Variant Workspace, ohne Wizard-Schritte automatisch weiterzuschalten.
  - Löst keine Navigation aus.
  - Erzeugt keine VPLIB-Dateien im Browser.
  - Liest keine Upload-Dateien und erzeugt keine Objekt-URLs.

  Abhängigkeit:
  - Sollte nach create_core.js geladen werden.
  - Erwartet bevorzugt window.VectoplanCreateCore.
  - Nutzt optional:
    - window.VectoplanCreateVariantProfiles
    - window.VectoplanCreateVariantState
    - window.VectoplanCreatePreviewRenderer, aber nur bei explizit aktiviertem
      data-vp-preview-render-enabled="true"

  Öffentliche API:
  - window.VectoplanCreatePreview.initialize()
  - window.VectoplanCreatePreview.refresh()
  - window.VectoplanCreatePreview.update()
  - window.VectoplanCreatePreview.updatePreview()
  - window.VectoplanCreatePreview.applyTaxonomyFiltering()
  - window.VectoplanCreatePreview.applyObjectKindRules()
  - window.VectoplanCreatePreview.updateTaxonomyPath()
  - window.VectoplanCreatePreview.clearVisiblePreviewText()
  - window.VectoplanCreatePreview.getContext()
  - window.VectoplanCreatePreview.getState()
----------------------------------------------------------------------------- */

(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreatePreview";
  var MODULE_NAME = "preview";
  var PREVIEW_VERSION = "0.6.0";
  var CORE_NAME = "VectoplanCreateCore";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 80;
  var PREVIEW_DEBOUNCE_MS = 60;

  var EXTRA_SELECTORS = {
    taxonomyPathSubcategory: "[data-vp-taxonomy-path-subcategory]",
    taxonomyPathFull: "[data-vp-taxonomy-path-full]",
    taxonomyPathCanonical: "[data-vp-taxonomy-path-canonical]",
    taxonomyPathLabel: "[data-vp-taxonomy-path-label]",

    variantWorkspace: "[data-vp-variant-workspace], [data-vp-variant-workspace-root='true'], [data-create-variant-workspace='true']",
    variantDrawer: "[data-vp-variant-drawer], [data-vp-variant-drawer-root], .vp-create-variant-drawer",

    familyName: "[name='family_name'], [data-create-field='family_name']",
    familySlug: "[name='family_slug'], [data-create-field='family_slug']",

    previewFamily: "[data-vp-preview-family], [data-create-preview-family='true']",
    previewTaxonomy: "[data-vp-preview-taxonomy], [data-create-preview-taxonomy='true']",
    previewPath: "[data-vp-preview-path], [data-create-preview-path='true']",

    contextDomainTargets: "[data-vp-current-domain]",
    contextCategoryTargets: "[data-vp-current-category]",
    contextSubcategoryTargets: "[data-vp-current-subcategory]",
    contextObjectKindTargets: "[data-vp-current-object-kind]",

    hiddenFamilyProfileId: "input[name='family_profile_id']",
    hiddenVariantProfileId: "input[name='variant_profile_id']",

    uploadCountLabels: "[data-vp-upload-count-label]",
    geometryUploadSummary: "[data-vp-geometry-upload-summary]",

    previewRoot: "[data-vp-create-preview], [data-create-preview-placeholder='true']",
    previewClearText: [
      "[data-vp-preview-family]",
      "[data-create-preview-family='true']",
      "[data-vp-preview-taxonomy]",
      "[data-create-preview-taxonomy='true']",
      "[data-vp-preview-path]",
      "[data-create-preview-path='true']",
      "[data-vp-preview-shape]",
      "[data-create-preview-shape='true']",
      "[data-vp-preview-object-kind]",
      "[data-create-preview-object-kind='true']",
      "[data-vp-preview-dimensions]",
      "[data-create-preview-dimensions='true']",
      "[data-vp-preview-cells]",
      "[data-create-preview-cells='true']",
      "[data-vp-preview-status]",
      "[data-create-preview-status='true']",
      "[data-vp-preview-metric]",
      "[data-vp-preview-label]",
      "[data-vp-preview-copy]",
      "[data-vp-preview-placeholder-text]",
      "[data-create-preview-placeholder-text='true']"
    ].join(",")
  };

  var FALLBACK_SELECTORS = {
    form: "[data-vp-create-form], [data-create-form='true'], #vp-create-form, form[data-create-form]",
    domainSelect: "[data-create-taxonomy-select='domain'], [name='domain'], [data-vp-taxonomy-domain]",
    categorySelect: "[data-create-taxonomy-select='category'], [name='category'], [data-vp-taxonomy-category]",
    subcategorySelect: "[data-create-taxonomy-select='subcategory'], [name='subcategory'], [data-vp-taxonomy-subcategory]",
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
    previewCube: "[data-vp-preview-primitive], [data-create-preview-cube='true']",
    previewShape: "[data-vp-preview-shape], [data-create-preview-shape='true']",
    previewObjectKind: "[data-vp-preview-object-kind], [data-create-preview-object-kind='true']",
    previewDimensions: "[data-vp-preview-dimensions], [data-create-preview-dimensions='true']",
    previewCells: "[data-vp-preview-cells], [data-create-preview-cells='true']",
    geometryVisibleSummary: "[data-vp-geometry-visible-summary], [data-create-geometry-visible-summary='true']",
    geometryCellsSummary: "[data-vp-geometry-cells-summary], [data-create-geometry-cells-summary='true']",
    variantRow: "[data-vp-variant-row='true'], [data-create-variant-row='true']",
    variableRow: "[data-create-variable-row='true'], [data-vp-variable-row]",
    variantCountLabel: "[data-vp-variant-count-label]",
    variableCountLabel: "[data-vp-variable-count-label]"
  };

  var OBJECT_KIND_CELL_LOCKED = {
    cell_block: true,
    adaptive_system: true
  };

  var SHAPE_LABELS = {
    block: "Block / Quader",
    box: "Block / Quader",
    cuboid: "Block / Quader",
    rectangular_prism: "Block / Quader",
    cube: "Würfel",
    wall: "Wandkörper",
    wall_block: "Wandkörper",
    slab: "Platte",
    plate: "Platte",
    cylinder: "Zylinder",
    pipe: "Rohr",
    sphere: "Kugel"
  };

  var OBJECT_KIND_LABELS = {
    cell_block: "Raster-Bauteil",
    multi_cell_module: "Mehrblock-Modul",
    catalog_object: "Katalogelement",
    adaptive_system: "Adaptives System"
  };

  var OBJECT_KIND_HINTS = {
    cell_block: "Rasterbedarf wird technisch auf 1 × 1 × 1 fixiert.",
    adaptive_system: "Rasterbedarf 1 × 1 × 1; dynamische Regeln bleiben deklarativ vorbereitet.",
    multi_cell_module: "Mehrere Rasterzellen möglich.",
    catalog_object: "Freies Katalogelement."
  };

  var core = null;
  var selectors = null;
  var classes = null;
  var initialized = false;
  var bindingDone = false;

  var localState = {
    version: PREVIEW_VERSION,
    initialized: false,
    bindingDone: false,
    updateCount: 0,
    taxonomyUpdateCount: 0,
    objectKindUpdateCount: 0,
    contextSyncCount: 0,
    previewClearCount: 0,
    lastContext: null,
    lastPreview: null,
    lastTaxonomyPath: "",
    lastError: null,
    previewUpdateTimer: null
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

        fallbackWarn("Core runtime missing; initializing preview with fallback core.");
        maybeCore = buildFallbackCore();
      }

      initialize(maybeCore);
    } catch (error) {
      fallbackWarn("Preview boot failed.", error);
    }
  }

  function initialize(coreRuntime) {
    try {
      if (initialized) {
        return api;
      }

      core = coreRuntime || window[CORE_NAME] || buildFallbackCore();

      if (!core) {
        fallbackWarn("Cannot initialize preview runtime.");
        return api;
      }

      selectors = Object.assign({}, FALLBACK_SELECTORS, core.selectors || {});
      classes = core.classes || {};

      if (typeof core.refreshContext === "function") {
        core.refreshContext();
      }

      bindControls();
      refresh({
        animate: false,
        source: "preview-init"
      });

      initialized = true;
      localState.initialized = true;

      if (typeof core.registerModule === "function") {
        core.registerModule(MODULE_NAME, api);
      }

      safeSetAttribute(document.documentElement, "data-vp-create-preview-ready", "true");
      safeSetAttribute(document.documentElement, "data-vp-create-preview-version", PREVIEW_VERSION);

      safeDispatch("vectoplan:create:preview-ready", getState());

      return api;
    } catch (error) {
      localState.initialized = false;
      localState.lastError = normalizeError(error);
      safeError("Preview initialization failed.", error);
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

      bindOnce("create-preview-taxonomy-filtering", bindTaxonomyFiltering);
      bindOnce("create-preview-object-kind-rules", bindObjectKindRules);
      bindOnce("create-preview-form-updates", bindPreviewUpdates);
      bindOnce("create-preview-context-events", bindContextEvents);
    } catch (error) {
      safeError("Preview control binding failed.", error);
    }
  }

  function bindTaxonomyFiltering() {
    try {
      var form = resolveForm();

      if (!form) {
        return;
      }

      var domainSelect = qs(selectorFor("domainSelect"), form);
      var categorySelect = qs(selectorFor("categorySelect"), form);
      var subcategorySelect = qs(selectorFor("subcategorySelect"), form);

      [domainSelect, categorySelect, subcategorySelect].forEach(function (select) {
        if (!select || select.getAttribute("data-vp-preview-taxonomy-bound") === "true") {
          return;
        }

        select.addEventListener("change", function () {
          try {
            applyTaxonomyFiltering(form, {
              source: "taxonomy-change",
              animate: true
            });
          } catch (error) {
            safeWarn("Taxonomy change handling failed.", error);
          }
        });

        select.addEventListener("input", function () {
          try {
            applyTaxonomyFiltering(form, {
              source: "taxonomy-input",
              animate: true
            });
          } catch (error) {
            safeWarn("Taxonomy input handling failed.", error);
          }
        });

        select.setAttribute("data-vp-preview-taxonomy-bound", "true");
      });
    } catch (error) {
      safeError("Taxonomy filtering binding failed.", error);
    }
  }

  function bindObjectKindRules() {
    try {
      var form = resolveForm();

      if (!form) {
        return;
      }

      var objectKindSelect = qs(selectorFor("objectKindSelect"), form);

      if (!objectKindSelect || objectKindSelect.getAttribute("data-vp-preview-object-kind-bound") === "true") {
        return;
      }

      objectKindSelect.addEventListener("change", function () {
        try {
          applyObjectKindRules(form, {
            source: "object-kind-change",
            animate: true
          });
        } catch (error) {
          safeWarn("Object kind change handling failed.", error);
        }
      });

      objectKindSelect.addEventListener("input", function () {
        try {
          applyObjectKindRules(form, {
            source: "object-kind-input",
            animate: true
          });
        } catch (error) {
          safeWarn("Object kind input handling failed.", error);
        }
      });

      objectKindSelect.setAttribute("data-vp-preview-object-kind-bound", "true");
    } catch (error) {
      safeError("Object kind binding failed.", error);
    }
  }

  function bindPreviewUpdates() {
    try {
      var form = resolveForm();

      if (!form || form.getAttribute("data-vp-preview-form-bound") === "true") {
        return;
      }

      var previewSelector = [
        selectorFor("objectKindSelect"),
        selectorFor("primitiveShapeSelect"),
        selectorFor("geometryUnit"),
        selectorFor("geometryWidth"),
        selectorFor("geometryHeight"),
        selectorFor("geometryDepth"),
        selectorFor("editorCellsX"),
        selectorFor("editorCellsY"),
        selectorFor("editorCellsZ"),
        EXTRA_SELECTORS.familyName,
        EXTRA_SELECTORS.familySlug,
        "[data-create-preview-source]",
        "[data-vp-upload-input]"
      ].filter(Boolean).join(",");

      form.addEventListener("input", function (event) {
        try {
          var target = event && event.target ? event.target : null;

          if (!target || !target.matches) {
            return;
          }

          if (target.matches(previewSelector)) {
            if (target.matches(EXTRA_SELECTORS.familyName) || target.matches(EXTRA_SELECTORS.familySlug)) {
              updateTaxonomyPath(form, {
                source: "family-input"
              });
            }

            schedulePreviewUpdate(form, {
              source: "form-input",
              animate: true
            });
          }

          if (target.matches("[name*='variants']")) {
            updateVariantCount(form);
          }

          if (target.matches(selectorFor("variableRow") + " input, " + selectorFor("variableRow") + " select, " + selectorFor("variableRow") + " textarea")) {
            updateVariableCount(form);
          }
        } catch (inputError) {
          safeWarn("Preview input update failed.", inputError);
        }
      });

      form.addEventListener("change", function (event) {
        try {
          var target = event && event.target ? event.target : null;

          if (!target || !target.matches) {
            return;
          }

          if (target.matches(previewSelector)) {
            if (target.matches(selectorFor("objectKindSelect"))) {
              applyObjectKindRules(form, {
                source: "preview-change-object-kind",
                animate: false
              });
            }

            if (
              target.matches(selectorFor("domainSelect")) ||
              target.matches(selectorFor("categorySelect")) ||
              target.matches(selectorFor("subcategorySelect"))
            ) {
              applyTaxonomyFiltering(form, {
                source: "preview-change-taxonomy",
                animate: false
              });
            }

            updatePreview(form, {
              source: "form-change",
              animate: true
            });
          }

          if (target.matches("[name*='variants']")) {
            updateVariantCount(form);
          }

          if (target.matches(selectorFor("variableRow") + " input, " + selectorFor("variableRow") + " select, " + selectorFor("variableRow") + " textarea")) {
            updateVariableCount(form);
          }
        } catch (changeError) {
          safeWarn("Preview change update failed.", changeError);
        }
      });

      form.setAttribute("data-vp-preview-form-bound", "true");
    } catch (error) {
      safeError("Preview update binding failed.", error);
    }
  }

  function bindContextEvents() {
    try {
      [
        "vectoplan:create:payload-ready",
        "vectoplan:create:payload-collected",
        "vectoplan:create:variant-state-ready",
        "vectoplan:create:variant-state-changed",
        "vectoplan:create:variant-state-synced",
        "vectoplan:create:uploads-runtime-ready",
        "vectoplan:create:upload-changed",
        "vectoplan:create:upload-cleared"
      ].forEach(function (eventName) {
        document.addEventListener(eventName, function () {
          try {
            syncContextToVariantWorkspace({
              source: eventName
            });
          } catch (error) {
            safeWarn("Context sync event failed: " + eventName, error);
          }
        });
      });

      document.addEventListener("vectoplan:create:wizard-ui-updated", function () {
        try {
          updatePreview(resolveForm(), {
            source: "wizard-ui-updated",
            animate: false
          });
        } catch (error) {
          safeWarn("Wizard preview refresh failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:core-context-refreshed", function () {
        try {
          refresh({
            source: "core-context-refreshed",
            animate: false
          });
        } catch (error) {
          safeWarn("Core context refresh preview failed.", error);
        }
      });
    } catch (error) {
      safeWarn("Context event binding failed.", error);
    }
  }

  function refresh(options) {
    try {
      ensureCore();

      var form = resolveForm();
      var safeOptions = options || {};

      applyTaxonomyFiltering(form, {
        source: safeOptions.source || "refresh",
        animate: !!safeOptions.animate
      });

      applyObjectKindRules(form, {
        source: safeOptions.source || "refresh",
        animate: !!safeOptions.animate
      });

      updateTaxonomyPath(form, {
        source: safeOptions.source || "refresh"
      });

      updateVariantCount(form);
      updateVariableCount(form);
      updateUploadSummaries(form);

      updatePreview(form, {
        source: safeOptions.source || "refresh",
        animate: !!safeOptions.animate
      });

      return getState();
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Preview refresh failed.", error);
      return getState();
    }
  }

  function applyTaxonomyFiltering(form, options) {
    try {
      ensureCore();

      var safeForm = resolveForm(form);

      if (!safeForm) {
        return false;
      }

      var safeOptions = options || {};
      var domainSelect = qs(selectorFor("domainSelect"), safeForm);
      var categorySelect = qs(selectorFor("categorySelect"), safeForm);
      var subcategorySelect = qs(selectorFor("subcategorySelect"), safeForm);

      var selectedDomain = domainSelect ? domainSelect.value : "";
      var selectedCategory = categorySelect ? categorySelect.value : "";

      if (categorySelect) {
        filterOptionsByData(categorySelect, "domain", selectedDomain);
        ensureEnabledSelection(categorySelect);
        selectedCategory = categorySelect.value;
      }

      if (subcategorySelect) {
        filterOptionsByData(subcategorySelect, "domain", selectedDomain);
        filterOptionsByData(subcategorySelect, "category", selectedCategory);
        ensureEnabledSelection(subcategorySelect);
      }

      updateTaxonomyPath(safeForm, {
        source: safeOptions.source || "taxonomy-filter"
      });

      syncContextToVariantWorkspace({
        source: safeOptions.source || "taxonomy-filter"
      });

      scheduleVariantProfileResolve({
        source: safeOptions.source || "taxonomy-filter"
      });

      localState.taxonomyUpdateCount += 1;

      safeDispatch("vectoplan:create:taxonomy-changed", {
        context: getContext(safeForm),
        source: safeOptions.source || "taxonomy-filter"
      });

      if (safeOptions.animate) {
        updatePreview(safeForm, {
          source: safeOptions.source || "taxonomy-filter",
          animate: true
        });
      }

      return true;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Apply taxonomy filtering failed.", error);
      return false;
    }
  }

  function filterOptionsByData(select, dataKey, expectedValue) {
    try {
      if (!select) {
        return false;
      }

      var normalizedExpected = String(expectedValue || "").trim();
      var options = Array.prototype.slice.call(select.options || []);

      options.forEach(function (option) {
        try {
          if (!option.value) {
            return;
          }

          var optionValue = option.getAttribute("data-" + dataKey) ||
            option.getAttribute("data-vp-parent-" + dataKey) ||
            option.getAttribute("data-" + dataKey + "-slug") ||
            "";

          if (!normalizedExpected || !optionValue || optionValue === normalizedExpected) {
            option.hidden = false;
            option.disabled = false;
          } else {
            option.hidden = true;
            option.disabled = true;
          }
        } catch (optionError) {
          safeWarn("Taxonomy option filter skipped.", optionError);
        }
      });

      return true;
    } catch (error) {
      safeWarn("Filter options failed.", error);
      return false;
    }
  }

  function ensureEnabledSelection(select) {
    try {
      if (!select) {
        return false;
      }

      var selected = select.options[select.selectedIndex];

      if (selected && !selected.disabled && !selected.hidden) {
        return true;
      }

      var options = Array.prototype.slice.call(select.options || []);
      var firstEnabled = options.find(function (option) {
        return option.value && !option.disabled && !option.hidden;
      });

      if (firstEnabled) {
        select.value = firstEnabled.value;
        dispatchNativeEvent(select, "change");
        return true;
      }

      select.value = "";
      return false;
    } catch (error) {
      safeWarn("Ensure enabled selection failed.", error);
      return false;
    }
  }

  function updateTaxonomyPath(form, options) {
    try {
      var safeForm = resolveForm(form);
      var context = getContext(safeForm);
      var familyName = getFieldValue(safeForm, "family_name") || getFieldValue(safeForm, "family_slug") || "family_slug";
      var familySlug = slugify(getFieldValue(safeForm, "family_slug") || familyName) || "family_slug";
      var sourceRoot = getSourceRoot();

      var canonicalPath = sourceRoot + "/" +
        context.domain + "/" +
        context.category + "/" +
        context.subcategory + "/" +
        familySlug;

      var legacyPath = sourceRoot + "/" +
        context.domain + "/" +
        context.category + "/" +
        familySlug;

      var visibleLabel = context.domain + " / " + context.category + " / " + context.subcategory + " / " + familySlug;

      setText(selectorFor("taxonomyPathDomain"), context.domain);
      setText(selectorFor("taxonomyPathCategory"), context.category);
      setText(EXTRA_SELECTORS.taxonomyPathSubcategory, context.subcategory);
      setText(selectorFor("taxonomyPathFamily"), familySlug);

      setText(selectorFor("taxonomyLegacyPath"), canonicalPath);
      setText(EXTRA_SELECTORS.taxonomyPathFull, canonicalPath);
      setText(EXTRA_SELECTORS.taxonomyPathCanonical, canonicalPath);
      setText(EXTRA_SELECTORS.taxonomyPathLabel, visibleLabel);

      localState.lastTaxonomyPath = canonicalPath;

      safeDispatch("vectoplan:create:taxonomy-path-updated", {
        source: options && options.source ? options.source : "api",
        context: context,
        familySlug: familySlug,
        canonicalPath: canonicalPath,
        legacyPath: legacyPath,
        visibleLabel: visibleLabel
      });

      return canonicalPath;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeWarn("Update taxonomy path failed.", error);
      return "";
    }
  }

  function getSourceRoot() {
    try {
      var coreState = core && core.state ? core.state : {};
      var fromContext = getNested(coreState.context, ["source_root"], "") ||
        getNested(coreState.context, ["sourceRoot"], "") ||
        getNested(coreState.context, ["library", "source_root"], "") ||
        getNested(coreState.context, ["library", "sourceRoot"], "");

      return String(fromContext || "src/library/source").replace(/\/+$/, "");
    } catch (error) {
      return "src/library/source";
    }
  }

  function applyObjectKindRules(form, options) {
    try {
      ensureCore();

      var safeForm = resolveForm(form);

      if (!safeForm) {
        return false;
      }

      var safeOptions = options || {};
      var objectKindSelect = qs(selectorFor("objectKindSelect"), safeForm);
      var cellsX = qs(selectorFor("editorCellsX"), safeForm);
      var cellsY = qs(selectorFor("editorCellsY"), safeForm);
      var cellsZ = qs(selectorFor("editorCellsZ"), safeForm);

      if (!objectKindSelect) {
        return false;
      }

      var objectKind = normalizeToken(objectKindSelect.value || "cell_block", "cell_block");
      var locked = !!OBJECT_KIND_CELL_LOCKED[objectKind];

      [cellsX, cellsY, cellsZ].forEach(function (input) {
        try {
          if (!input) {
            return;
          }

          if (locked) {
            input.value = "1";
            input.setAttribute("readonly", "readonly");
            input.setAttribute("aria-readonly", "true");
            input.setAttribute("data-create-locked", "true");
            input.setAttribute("data-create-grid-locked", "true");
          } else {
            input.removeAttribute("readonly");
            input.removeAttribute("aria-readonly");
            input.setAttribute("data-create-locked", "false");
            input.removeAttribute("data-create-grid-locked");
          }
        } catch (inputError) {
          safeWarn("Technical context cell input update skipped.", inputError);
        }
      });

      updateObjectKindNote(safeForm, objectKind, locked);
      syncContextToVariantWorkspace({
        source: safeOptions.source || "object-kind-rules"
      });

      scheduleVariantProfileResolve({
        source: safeOptions.source || "object-kind-rules"
      });

      localState.objectKindUpdateCount += 1;

      safeDispatch("vectoplan:create:object-kind-changed", {
        context: getContext(safeForm),
        objectKind: objectKind,
        lockedCells: locked,
        source: safeOptions.source || "object-kind-rules"
      });

      updatePreview(safeForm, {
        source: safeOptions.source || "object-kind-rules",
        animate: !!safeOptions.animate
      });

      return true;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Apply object kind rules failed.", error);
      return false;
    }
  }

  function updateObjectKindNote(form, objectKind, locked) {
    try {
      var note = qs(selectorFor("objectKindNote"));
      var labelNode = qs(selectorFor("objectKindNoteLabel"));
      var textNode = qs(selectorFor("objectKindNoteText"));

      if (!note) {
        return false;
      }

      if (note.getAttribute("data-vp-show-object-kind-note") !== "true") {
        note.hidden = true;
        note.setAttribute("aria-hidden", "true");
        return true;
      }

      if (!labelNode || !textNode) {
        return false;
      }

      var label = selectedOptionLabel(qs(selectorFor("objectKindSelect"), form), objectKind) || objectKindLabelFallback(objectKind);
      var hint = OBJECT_KIND_HINTS[objectKind] || "Technischer Kontext für dieses Library-Element.";

      note.hidden = false;
      note.setAttribute("aria-hidden", "false");
      note.setAttribute("data-create-object-kind-note-value", objectKind || "");
      note.setAttribute("data-create-object-kind-locks-cells", locked ? "true" : "false");
      labelNode.textContent = label;
      textNode.textContent = hint;

      return true;
    } catch (error) {
      safeWarn("Technical context note update failed.", error);
      return false;
    }
  }

  function schedulePreviewUpdate(form, options) {
    try {
      if (localState.previewUpdateTimer) {
        window.clearTimeout(localState.previewUpdateTimer);
      }

      localState.previewUpdateTimer = window.setTimeout(function () {
        try {
          updatePreview(form, options || {});
        } catch (error) {
          safeWarn("Scheduled preview update failed.", error);
        }
      }, PREVIEW_DEBOUNCE_MS);
    } catch (error) {
      safeWarn("Schedule preview update failed.", error);
    }
  }

  function updatePreview(form, options) {
    try {
      ensureCore();

      var safeForm = resolveForm(form);
      var safeOptions = options || {};
      var placeholder = qs(selectorFor("previewPlaceholder")) || qs(EXTRA_SELECTORS.previewRoot);

      if (!safeForm) {
        clearVisiblePreviewText(placeholder || document);
        return false;
      }

      var context = getContext(safeForm);
      var objectKind = context.object_kind;
      var shape = normalizeToken(getFieldValue(safeForm, "primitive_shape") || "block", "block");
      var width = normalizeDecimalDisplay(getFieldValue(safeForm, "geometry_width") || "1.00");
      var height = normalizeDecimalDisplay(getFieldValue(safeForm, "geometry_height") || "1.00");
      var depth = normalizeDecimalDisplay(getFieldValue(safeForm, "geometry_depth") || "1.00");
      var unit = getFieldValue(safeForm, "geometry_unit") || "m";
      var cellsX = normalizeIntDisplay(getFieldValue(safeForm, "editor_cells_x") || "1");
      var cellsY = normalizeIntDisplay(getFieldValue(safeForm, "editor_cells_y") || "1");
      var cellsZ = normalizeIntDisplay(getFieldValue(safeForm, "editor_cells_z") || "1");

      updateGeometrySummaries(width, height, depth, unit, cellsX, cellsY, cellsZ);
      updateUploadSummaries(safeForm);

      if (placeholder) {
        placeholder.setAttribute("data-vp-preview-mode", "empty-dev");
        placeholder.setAttribute("data-create-preview-primitive-shape", shape);
        placeholder.setAttribute("data-create-preview-object-kind-value", objectKind);
        placeholder.setAttribute("data-create-preview-unit-value", unit);
        placeholder.setAttribute("data-create-preview-width-value", width);
        placeholder.setAttribute("data-create-preview-height-value", height);
        placeholder.setAttribute("data-create-preview-depth-value", depth);
        placeholder.setAttribute("data-create-preview-cells-x-value", cellsX);
        placeholder.setAttribute("data-create-preview-cells-y-value", cellsY);
        placeholder.setAttribute("data-create-preview-cells-z-value", cellsZ);
        placeholder.setAttribute("data-vp-preview-domain", context.domain);
        placeholder.setAttribute("data-vp-preview-category", context.category);
        placeholder.setAttribute("data-vp-preview-subcategory", context.subcategory);
        placeholder.setAttribute("data-vp-preview-empty", "true");

        setPreviewCssVariables(placeholder, {
          width: width,
          height: height,
          depth: depth,
          cellsX: cellsX,
          cellsY: cellsY,
          cellsZ: cellsZ
        });

        clearVisiblePreviewText(placeholder);
      } else {
        clearVisiblePreviewText(document);
      }

      if (isVisualPreviewEnabled(placeholder)) {
        updateVisualPreview(safeForm, placeholder, {
          context: context,
          objectKind: objectKind,
          shape: shape,
          width: width,
          height: height,
          depth: depth,
          unit: unit,
          cellsX: cellsX,
          cellsY: cellsY,
          cellsZ: cellsZ,
          source: safeOptions.source || "api",
          animate: !!safeOptions.animate
        });
      }

      localState.updateCount += 1;
      localState.lastContext = context;
      localState.lastPreview = {
        mode: "empty-dev",
        objectKind: objectKind,
        shape: shape,
        dimensionsText: width + " × " + height + " × " + depth + " " + unit,
        cellsText: cellsX + " × " + cellsY + " × " + cellsZ,
        visualEnabled: isVisualPreviewEnabled(placeholder),
        timestamp: timestamp()
      };

      safeDispatch("vectoplan:create:preview-updated", {
        context: context,
        preview: localState.lastPreview,
        source: safeOptions.source || "api"
      });

      return true;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Preview update failed.", error);
      clearVisiblePreviewText();
      return false;
    }
  }

  function updateVisualPreview(form, placeholder, data) {
    try {
      var safeForm = resolveForm(form);
      var safeData = data || {};
      var shapeSelect = qs(selectorFor("primitiveShapeSelect"), safeForm);
      var objectKindSelect = qs(selectorFor("objectKindSelect"), safeForm);
      var shapeLabel = selectedOptionLabel(shapeSelect, safeData.shape) || shapeLabelFallback(safeData.shape);
      var objectKindLabel = selectedOptionLabel(objectKindSelect, safeData.objectKind) || objectKindLabelFallback(safeData.objectKind);
      var dimensionsText = safeData.width + " × " + safeData.height + " × " + safeData.depth + " " + safeData.unit;
      var cellsText = safeData.cellsX + " × " + safeData.cellsY + " × " + safeData.cellsZ;

      if (window.VectoplanCreatePreviewRenderer && typeof window.VectoplanCreatePreviewRenderer.update === "function") {
        window.VectoplanCreatePreviewRenderer.update({
          form: safeForm,
          context: safeData.context || getContext(safeForm),
          source: safeData.source || "preview-runtime"
        });
      }

      setTextInRoot(placeholder, selectorFor("previewShape"), shapeLabel);
      setTextInRoot(placeholder, selectorFor("previewObjectKind"), objectKindLabel);
      setTextInRoot(placeholder, selectorFor("previewDimensions"), dimensionsText);
      setTextInRoot(placeholder, selectorFor("previewCells"), cellsText);

      updatePreviewCube(safeData.shape, safeData.animate);

      if (safeData.animate && placeholder && typeof flashUpdated === "function") {
        flashUpdated(placeholder);
      }

      return true;
    } catch (error) {
      safeWarn("Visual preview update failed.", error);
      clearVisiblePreviewText(placeholder);
      return false;
    }
  }

  function isVisualPreviewEnabled(placeholder) {
    try {
      if (!placeholder) {
        return false;
      }

      return toBoolean(
        placeholder.getAttribute("data-vp-preview-render-enabled") ||
        placeholder.getAttribute("data-create-preview-render-enabled") ||
        "",
        false
      );
    } catch (error) {
      return false;
    }
  }

  function clearVisiblePreviewText(root) {
    try {
      var scope = root || qs(selectorFor("previewPlaceholder")) || qs(EXTRA_SELECTORS.previewRoot) || document;
      var nodes = qsa(EXTRA_SELECTORS.previewClearText, scope);

      nodes.forEach(function (node) {
        try {
          node.textContent = "";
          node.setAttribute("data-vp-preview-text-cleared", "true");
        } catch (nodeError) {
          safeWarn("Preview text clear skipped.", nodeError);
        }
      });

      if (scope && scope.nodeType === 1) {
        scope.setAttribute("data-vp-preview-visible-text-cleared", "true");
      }

      localState.previewClearCount += 1;

      return true;
    } catch (error) {
      safeWarn("Preview text cleanup failed.", error);
      return false;
    }
  }

  function updatePreviewTextFromForm(form) {
    try {
      var placeholder = qs(selectorFor("previewPlaceholder")) || qs(EXTRA_SELECTORS.previewRoot);

      if (!isVisualPreviewEnabled(placeholder)) {
        clearVisiblePreviewText(placeholder);
        return false;
      }

      var safeForm = resolveForm(form);
      var context = getContext(safeForm);
      var familyName = getFieldValue(safeForm, "family_name") || "Unbenannte Family";
      var familySlug = slugify(getFieldValue(safeForm, "family_slug") || familyName) || "family_slug";
      var taxonomyText = context.domain + " / " + context.category + " / " + context.subcategory;
      var path = getSourceRoot() + "/" + context.domain + "/" + context.category + "/" + context.subcategory + "/" + familySlug;

      setTextInRoot(placeholder, EXTRA_SELECTORS.previewFamily, familyName);
      setTextInRoot(placeholder, EXTRA_SELECTORS.previewTaxonomy, taxonomyText);
      setTextInRoot(placeholder, EXTRA_SELECTORS.previewPath, path);

      return true;
    } catch (error) {
      safeWarn("Preview text from form failed.", error);
      return false;
    }
  }

  function updateGeometrySummariesFromForm(form) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm) {
        return false;
      }

      updateGeometrySummaries(
        normalizeDecimalDisplay(getFieldValue(safeForm, "geometry_width") || "1.00"),
        normalizeDecimalDisplay(getFieldValue(safeForm, "geometry_height") || "1.00"),
        normalizeDecimalDisplay(getFieldValue(safeForm, "geometry_depth") || "1.00"),
        getFieldValue(safeForm, "geometry_unit") || "m",
        normalizeIntDisplay(getFieldValue(safeForm, "editor_cells_x") || "1"),
        normalizeIntDisplay(getFieldValue(safeForm, "editor_cells_y") || "1"),
        normalizeIntDisplay(getFieldValue(safeForm, "editor_cells_z") || "1")
      );

      return true;
    } catch (error) {
      safeWarn("Geometry summary from form failed.", error);
      return false;
    }
  }

  function updateGeometrySummaries(width, height, depth, unit, cellsX, cellsY, cellsZ) {
    try {
      var visibleText = width + " × " + height + " × " + depth + " " + unit;
      var cellsText = cellsX + " × " + cellsY + " × " + cellsZ + " Blöcke";

      setText(selectorFor("geometryVisibleSummary"), visibleText);
      setText(selectorFor("geometryCellsSummary"), cellsText);

      return true;
    } catch (error) {
      safeWarn("Geometry summary update failed.", error);
      return false;
    }
  }

  function updateUploadSummaries(form) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm) {
        return false;
      }

      var geometryPayload = readUploadPayload(safeForm, "geometry_model_uploads_json");
      var geometryCount = geometryPayload && geometryPayload.count ? parseInt(geometryPayload.count, 10) || 0 : countFileInputFiles(safeForm, "geometry_model_files");

      setText(EXTRA_SELECTORS.geometryUploadSummary, geometryCount === 1 ? "1 Datei" : geometryCount + " Dateien");

      return true;
    } catch (error) {
      safeWarn("Upload summary update failed.", error);
      return false;
    }
  }

  function updatePreviewCube(shape, animate) {
    try {
      var placeholder = qs(selectorFor("previewPlaceholder")) || qs(EXTRA_SELECTORS.previewRoot);

      if (!isVisualPreviewEnabled(placeholder)) {
        return clearPreviewCubeClasses();
      }

      var cube = qs(selectorFor("previewCube"), placeholder || document);

      if (!cube) {
        return false;
      }

      var shapeClasses = core && core.previewShapeClasses ? core.previewShapeClasses : [];

      shapeClasses.forEach(function (className) {
        cube.classList.remove(className);
      });

      var normalized = normalizePreviewShape(shape);

      cube.classList.add("vp-create-preview-cube--" + normalized);
      cube.setAttribute("data-create-preview-cube-shape", normalized);
      cube.setAttribute("data-vp-preview-cube-shape", normalized);

      if (animate) {
        flashUpdated(cube);
      }

      return true;
    } catch (error) {
      safeWarn("Preview cube update failed.", error);
      return false;
    }
  }

  function clearPreviewCubeClasses() {
    try {
      var placeholder = qs(selectorFor("previewPlaceholder")) || qs(EXTRA_SELECTORS.previewRoot);
      var cube = placeholder ? qs(selectorFor("previewCube"), placeholder) : null;

      if (!cube) {
        return false;
      }

      var shapeClasses = core && core.previewShapeClasses ? core.previewShapeClasses : [];

      shapeClasses.forEach(function (className) {
        cube.classList.remove(className);
      });

      cube.removeAttribute("data-create-preview-cube-shape");
      cube.removeAttribute("data-vp-preview-cube-shape");

      return true;
    } catch (error) {
      return false;
    }
  }

  function setPreviewCssVariables(node, values) {
    try {
      if (!node || !values) {
        return false;
      }

      var width = Math.max(0.1, toNumber(values.width, 1));
      var height = Math.max(0.1, toNumber(values.height, 1));
      var depth = Math.max(0.1, toNumber(values.depth, 1));
      var maxDimension = Math.max(width, height, depth, 1);

      node.style.setProperty("--vp-preview-width-ratio", String(width / maxDimension));
      node.style.setProperty("--vp-preview-height-ratio", String(height / maxDimension));
      node.style.setProperty("--vp-preview-depth-ratio", String(depth / maxDimension));
      node.style.setProperty("--vp-preview-cells-x", String(toInteger(values.cellsX, 1)));
      node.style.setProperty("--vp-preview-cells-y", String(toInteger(values.cellsY, 1)));
      node.style.setProperty("--vp-preview-cells-z", String(toInteger(values.cellsZ, 1)));

      return true;
    } catch (error) {
      safeWarn("Preview CSS variable update failed.", error);
      return false;
    }
  }

  function normalizePreviewShape(shape) {
    try {
      var value = normalizeToken(shape || "block", "block");

      if (
        value === "block" ||
        value === "box" ||
        value === "cuboid" ||
        value === "rectangular_prism" ||
        value === "cube" ||
        value === "wall" ||
        value === "wall_block" ||
        value === "slab" ||
        value === "plate" ||
        value === "cylinder" ||
        value === "pipe" ||
        value === "sphere"
      ) {
        return value;
      }

      return "block";
    } catch (error) {
      return "block";
    }
  }

  function shapeLabelFallback(shape) {
    try {
      var normalized = normalizePreviewShape(shape);
      return SHAPE_LABELS[normalized] || shape || "Form";
    } catch (error) {
      return "Form";
    }
  }

  function objectKindLabelFallback(objectKind) {
    try {
      var normalized = normalizeToken(objectKind, "cell_block");
      return OBJECT_KIND_LABELS[normalized] || normalized || "Technischer Kontext";
    } catch (error) {
      return "Technischer Kontext";
    }
  }

  function syncContextToVariantWorkspace(options) {
    try {
      var form = resolveForm();
      var context = getContext(form);
      var workspaceNodes = qsa(EXTRA_SELECTORS.variantWorkspace);
      var drawerNodes = qsa(EXTRA_SELECTORS.variantDrawer);

      workspaceNodes.concat(drawerNodes).forEach(function (node) {
        try {
          node.setAttribute("data-vp-current-domain", context.domain);
          node.setAttribute("data-vp-current-category", context.category);
          node.setAttribute("data-vp-current-subcategory", context.subcategory);
          node.setAttribute("data-vp-current-object-kind", context.object_kind);

          if (context.family_profile_id) {
            node.setAttribute("data-vp-current-family-profile-id", context.family_profile_id);
          }

          if (context.variant_profile_id) {
            node.setAttribute("data-vp-current-variant-profile-id", context.variant_profile_id);
          }
        } catch (nodeError) {
          safeWarn("Context node sync skipped.", nodeError);
        }
      });

      localState.contextSyncCount += 1;
      localState.lastContext = context;

      safeDispatch("vectoplan:create:context-synced", {
        context: context,
        source: options && options.source ? options.source : "api"
      });

      return context;
    } catch (error) {
      safeWarn("Context to Variant Workspace sync failed.", error);
      return getContext(resolveForm());
    }
  }

  function scheduleVariantProfileResolve(options) {
    try {
      var runtime = window.VectoplanCreateVariantProfiles;
      var context = getContext(resolveForm());

      safeDispatch("vectoplan:create:variant-profile-context-changed", {
        context: context,
        source: options && options.source ? options.source : "api"
      });

      if (!runtime) {
        return false;
      }

      if (typeof runtime.scheduleResolve === "function") {
        runtime.scheduleResolve({
          source: options && options.source ? options.source : "preview-context"
        });
        return true;
      }

      if (typeof runtime.resolveCurrentProfile === "function") {
        window.setTimeout(function () {
          try {
            runtime.resolveCurrentProfile({
              force: true,
              source: options && options.source ? options.source : "preview-context"
            });
          } catch (resolveError) {
            safeWarn("Variant profile resolve failed.", resolveError);
          }
        }, 0);

        return true;
      }

      return false;
    } catch (error) {
      safeWarn("Schedule variant profile resolve failed.", error);
      return false;
    }
  }

  function getContext(form) {
    try {
      var safeForm = resolveForm(form);
      var coreState = core && core.state ? core.state : {};
      var domain = getFieldValue(safeForm, "domain") ||
        getNested(coreState.uiState, ["defaults", "domain"], "hochbau");

      var category = getFieldValue(safeForm, "category") ||
        getNested(coreState.uiState, ["defaults", "category"], "bloecke");

      var subcategory = getFieldValue(safeForm, "subcategory") ||
        getNested(coreState.uiState, ["defaults", "subcategory"], "basis");

      var objectKind = getFieldValue(safeForm, "object_kind") ||
        getNested(coreState.uiState, ["defaults", "object_kind"], "cell_block");

      var familyProfileId = getFieldValue(safeForm, "family_profile_id") ||
        readWorkspaceAttribute("data-vp-current-family-profile-id") ||
        "";

      var variantProfileId = getFieldValue(safeForm, "variant_profile_id") ||
        readWorkspaceAttribute("data-vp-current-variant-profile-id") ||
        "";

      return {
        domain: normalizeToken(domain, "hochbau"),
        category: normalizeToken(category, "bloecke"),
        subcategory: normalizeToken(subcategory, "basis"),
        object_kind: normalizeToken(objectKind, "cell_block"),
        objectKind: normalizeToken(objectKind, "cell_block"),
        family_profile_id: String(familyProfileId || "").trim(),
        familyProfileId: String(familyProfileId || "").trim(),
        variant_profile_id: String(variantProfileId || "").trim(),
        variantProfileId: String(variantProfileId || "").trim()
      };
    } catch (error) {
      return {
        domain: "hochbau",
        category: "bloecke",
        subcategory: "basis",
        object_kind: "cell_block",
        objectKind: "cell_block",
        family_profile_id: "",
        familyProfileId: "",
        variant_profile_id: "",
        variantProfileId: ""
      };
    }
  }

  function readWorkspaceAttribute(attributeName) {
    try {
      var workspace = qs(EXTRA_SELECTORS.variantWorkspace);

      if (!workspace || !attributeName) {
        return "";
      }

      return workspace.getAttribute(attributeName) || "";
    } catch (error) {
      return "";
    }
  }

  function updateVariantCount(form) {
    try {
      var safeForm = resolveForm(form);
      var label = qs(selectorFor("variantCountLabel"));
      var count = 0;

      if (window.VectoplanCreateVariantState && typeof window.VectoplanCreateVariantState.getVariants === "function") {
        var variants = window.VectoplanCreateVariantState.getVariants();
        count = Array.isArray(variants) ? variants.length : 0;
      }

      if (!count && safeForm) {
        count = qsa(selectorFor("variantRow"), safeForm).length;
      }

      if (label) {
        label.textContent = count === 1 ? "1 Variante" : count + " Varianten";
      }

      return count;
    } catch (error) {
      safeWarn("Variant count update failed.", error);
      return 0;
    }
  }

  function updateVariableCount(form) {
    try {
      var safeForm = resolveForm(form);
      var label = qs(selectorFor("variableCountLabel"));
      var rows = safeForm ? qsa(selectorFor("variableRow"), safeForm) : [];
      var filled = rows.filter(rowHasAnyInputValue).length;
      var count = rows.length;

      if (label) {
        label.textContent = count === 1
          ? (filled === 1 ? "1 Zeile · befüllt" : "1 Zeile")
          : filled + " / " + count + " befüllt";
      }

      return {
        count: count,
        filled: filled
      };
    } catch (error) {
      safeWarn("Variable count update failed.", error);
      return {
        count: 0,
        filled: 0
      };
    }
  }

  function rowHasAnyInputValue(row) {
    try {
      var fields = qsa("input, select, textarea", row);

      return fields.some(function (field) {
        return field.value && String(field.value).trim() !== "";
      });
    } catch (error) {
      return false;
    }
  }

  function resolveForm(form) {
    try {
      if (form && form.nodeType === 1) {
        return form;
      }

      return core && typeof core.qs === "function"
        ? core.qs(selectorFor("form"))
        : document.querySelector(FALLBACK_SELECTORS.form);
    } catch (error) {
      return null;
    }
  }

  function getState() {
    try {
      return {
        version: PREVIEW_VERSION,
        initialized: initialized,
        bindingDone: bindingDone,
        updateCount: localState.updateCount,
        taxonomyUpdateCount: localState.taxonomyUpdateCount,
        objectKindUpdateCount: localState.objectKindUpdateCount,
        contextSyncCount: localState.contextSyncCount,
        previewClearCount: localState.previewClearCount,
        lastContext: clone(localState.lastContext),
        lastPreview: clone(localState.lastPreview),
        lastTaxonomyPath: localState.lastTaxonomyPath,
        lastError: localState.lastError
      };
    } catch (error) {
      return {
        version: PREVIEW_VERSION,
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
        selectors = Object.assign({}, FALLBACK_SELECTORS, core.selectors || {});
      }

      if (!classes) {
        classes = core.classes || {};
      }

      return core;
    } catch (error) {
      throw error;
    }
  }

  function selectorFor(key) {
    try {
      if (!selectors) {
        selectors = Object.assign({}, FALLBACK_SELECTORS, core && core.selectors ? core.selectors : {});
      }

      return selectors[key] || FALLBACK_SELECTORS[key] || "";
    } catch (error) {
      return FALLBACK_SELECTORS[key] || "";
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

  function setText(selector, value, root) {
    try {
      if (core && typeof core.setText === "function") {
        core.setText(selector, value, root);
        return true;
      }

      var node = qs(selector, root);

      if (node) {
        node.textContent = value === null || typeof value === "undefined" ? "" : String(value);
      }

      return !!node;
    } catch (error) {
      return false;
    }
  }

  function setTextInRoot(root, selector, value) {
    try {
      if (!root || !selector) {
        return false;
      }

      var node = qs(selector, root);

      if (node) {
        node.textContent = value === null || typeof value === "undefined" ? "" : String(value);
        return true;
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function getFieldValue(form, name) {
    try {
      if (core && typeof core.getFieldValue === "function") {
        return core.getFieldValue(form, name);
      }

      if (!form || !name) {
        return "";
      }

      var field = form.elements ? form.elements[name] : null;

      if (!field || field.nodeType !== 1) {
        field = qs("[name='" + cssEscape(name) + "']", form);
      }

      return field && typeof field.value !== "undefined" ? String(field.value || "") : "";
    } catch (error) {
      return "";
    }
  }

  function dispatchNativeEvent(node, eventName) {
    try {
      if (core && typeof core.dispatchNativeEvent === "function") {
        core.dispatchNativeEvent(node, eventName);
        return;
      }

      if (node) {
        node.dispatchEvent(new Event(eventName, {
          bubbles: true,
          cancelable: false
        }));
      }
    } catch (error) {
      /* no-op */
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

  function selectedOptionLabel(select, value) {
    try {
      if (core && typeof core.selectedOptionLabel === "function") {
        return core.selectedOptionLabel(select, value);
      }

      if (!select) {
        return "";
      }

      var selected = select.options[select.selectedIndex];

      if (selected && selected.value === value) {
        return normalizeOptionText(selected.textContent);
      }

      var options = Array.prototype.slice.call(select.options || []);
      var match = options.find(function (option) {
        return option.value === value;
      });

      return match ? normalizeOptionText(match.textContent) : "";
    } catch (error) {
      return "";
    }
  }

  function normalizeOptionText(value) {
    try {
      if (core && typeof core.normalizeOptionText === "function") {
        return core.normalizeOptionText(value);
      }

      return String(value || "")
        .replace(/\s+·\s+deaktiviert\s*$/i, "")
        .replace(/\s+/g, " ")
        .trim();
    } catch (error) {
      return "";
    }
  }

  function normalizeToken(value, fallback) {
    try {
      if (core && typeof core.normalizeToken === "function") {
        return core.normalizeToken(value, fallback);
      }

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
    } catch (error) {
      return fallback || "";
    }
  }

  function slugify(value) {
    try {
      if (core && typeof core.slugify === "function") {
        return core.slugify(value);
      }

      return normalizeToken(value, "");
    } catch (error) {
      return "";
    }
  }

  function normalizeDecimalDisplay(value) {
    try {
      if (core && typeof core.normalizeDecimalDisplay === "function") {
        return core.normalizeDecimalDisplay(value);
      }

      var text = String(value || "").replace(",", ".").trim();
      var number = Number(text);

      if (!Number.isFinite(number) || number <= 0) {
        return "1.00";
      }

      return number.toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1");
    } catch (error) {
      return "1.00";
    }
  }

  function normalizeIntDisplay(value) {
    try {
      if (core && typeof core.normalizeIntDisplay === "function") {
        return core.normalizeIntDisplay(value);
      }

      var number = parseInt(String(value || "").trim(), 10);

      if (!Number.isFinite(number) || number < 1) {
        return "1";
      }

      return String(number);
    } catch (error) {
      return "1";
    }
  }

  function toNumber(value, fallback) {
    try {
      if (core && typeof core.toNumber === "function") {
        return core.toNumber(value, fallback);
      }

      var number = Number(String(value || "").replace(",", "."));

      return Number.isFinite(number) ? number : fallback;
    } catch (error) {
      return fallback;
    }
  }

  function toInteger(value, fallback) {
    try {
      if (core && typeof core.toInteger === "function") {
        return core.toInteger(value, fallback);
      }

      var number = parseInt(String(value || "").trim(), 10);

      return Number.isFinite(number) ? number : fallback;
    } catch (error) {
      return fallback;
    }
  }

  function toBoolean(value, fallback) {
    try {
      if (core && typeof core.toBoolean === "function") {
        return core.toBoolean(value, fallback);
      }

      if (value === true || value === false) {
        return value;
      }

      var text = String(value || "").trim().toLowerCase();

      if (["true", "1", "yes", "ja", "on", "enabled", "active"].indexOf(text) >= 0) {
        return true;
      }

      if (["false", "0", "no", "nein", "off", "disabled", "inactive"].indexOf(text) >= 0) {
        return false;
      }

      return !!fallback;
    } catch (error) {
      return !!fallback;
    }
  }

  function getNested(object, path, fallback) {
    try {
      if (core && typeof core.getNested === "function") {
        return core.getNested(object, path, fallback);
      }

      var cursor = object;

      for (var index = 0; index < path.length; index += 1) {
        if (!cursor || typeof cursor !== "object" || !(path[index] in cursor)) {
          return fallback;
        }

        cursor = cursor[path[index]];
      }

      return cursor === undefined || cursor === null ? fallback : cursor;
    } catch (error) {
      return fallback;
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

  function flashUpdated(node) {
    try {
      if (core && typeof core.flashUpdated === "function") {
        core.flashUpdated(node);
        return;
      }

      if (!node) {
        return;
      }

      node.classList.remove("is-updated");
      void node.offsetWidth;
      node.classList.add("is-updated");

      window.setTimeout(function () {
        try {
          node.classList.remove("is-updated");
        } catch (error) {
          /* no-op */
        }
      }, 380);
    } catch (error) {
      /* no-op */
    }
  }

  function readUploadPayload(form, fieldName) {
    try {
      var field = form && form.elements ? form.elements[fieldName] : null;

      if (!field || field.nodeType !== 1) {
        field = qs("[name='" + cssEscape(fieldName) + "']", form);
      }

      if (!field || typeof field.value === "undefined" || !String(field.value || "").trim()) {
        return {};
      }

      return JSON.parse(field.value);
    } catch (error) {
      return {};
    }
  }

  function countFileInputFiles(form, fieldName) {
    try {
      var field = form && form.elements ? form.elements[fieldName] : null;

      if (!field || field.nodeType !== 1) {
        field = qs("input[type='file'][name='" + cssEscape(fieldName) + "']", form);
      }

      return field && field.files ? field.files.length : 0;
    } catch (error) {
      return 0;
    }
  }

  function safeSetAttribute(node, name, value) {
    try {
      if (core && typeof core.safeSetAttribute === "function") {
        core.safeSetAttribute(node, name, value);
        return true;
      }

      if (node && name) {
        node.setAttribute(name, value === undefined || value === null ? "" : String(value));
        return true;
      }

      return false;
    } catch (error) {
      return false;
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
          window.console.warn("[VPLIB Create Preview] " + message, error);
        } else {
          window.console.warn("[VPLIB Create Preview] " + message);
        }
      }
    } catch (consoleError) {
      /* no-op */
    }
  }

  function buildFallbackCore() {
    try {
      return {
        selectors: FALLBACK_SELECTORS,
        classes: {},
        state: {
          context: {},
          uiState: {
            defaults: {}
          }
        },
        previewShapeClasses: [
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
        ],
        qs: function (selector, root) {
          return (root || document).querySelector(selector);
        },
        qsa: function (selector, root) {
          return Array.prototype.slice.call((root || document).querySelectorAll(selector));
        },
        setText: setText,
        getFieldValue: getFieldValue,
        getNested: getNested,
        slugify: slugify,
        normalizeToken: normalizeToken,
        normalizeDecimalDisplay: normalizeDecimalDisplay,
        normalizeIntDisplay: normalizeIntDisplay,
        toNumber: toNumber,
        toInteger: toInteger,
        toBoolean: toBoolean,
        selectedOptionLabel: selectedOptionLabel,
        dispatchNativeEvent: dispatchNativeEvent,
        dispatch: safeDispatch,
        registerModule: function () {},
        bindOnce: bindOnce,
        refreshContext: function () {},
        safeSetAttribute: safeSetAttribute,
        clone: clone,
        cssEscape: cssEscape,
        flashUpdated: flashUpdated,
        warn: fallbackWarn,
        error: fallbackWarn
      };
    } catch (error) {
      return null;
    }
  }

  var api = {
    version: PREVIEW_VERSION,

    initialize: initialize,
    refresh: refresh,
    update: updatePreview,
    updatePreview: updatePreview,

    applyTaxonomyFiltering: applyTaxonomyFiltering,
    filterOptionsByData: filterOptionsByData,
    ensureEnabledSelection: ensureEnabledSelection,
    updateTaxonomyPath: updateTaxonomyPath,

    applyObjectKindRules: applyObjectKindRules,
    updateObjectKindNote: updateObjectKindNote,

    schedulePreviewUpdate: schedulePreviewUpdate,
    updateGeometrySummariesFromForm: updateGeometrySummariesFromForm,
    updateGeometrySummaries: updateGeometrySummaries,
    updatePreviewCube: updatePreviewCube,
    clearVisiblePreviewText: clearVisiblePreviewText,

    syncContextToVariantWorkspace: syncContextToVariantWorkspace,
    scheduleVariantProfileResolve: scheduleVariantProfileResolve,
    getContext: getContext,

    updateVariantCount: updateVariantCount,
    updateVariableCount: updateVariableCount,
    updateUploadSummaries: updateUploadSummaries,

    normalizePreviewShape: normalizePreviewShape,
    shapeLabelFallback: shapeLabelFallback,
    objectKindLabelFallback: objectKindLabelFallback,

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