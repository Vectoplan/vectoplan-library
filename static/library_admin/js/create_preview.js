/* services/vectoplan-library/static/library_admin/js/create_preview.js */

/* -----------------------------------------------------------------------------
  VECTOPLAN Library · VPLIB Create Preview Runtime

  Zweck:
  - Eigenständige Preview-/Kontext-Schicht für /create.
  - Entlastet die bisher zu große create.js.
  - Steuert Taxonomie-Filterung, Taxonomiepfad, Object-Kind-Regeln,
    Geometrie-Zusammenfassungen und CSS-/HTML-Preview.
  - Synchronisiert Domain, Kategorie, Subkategorie und Objektart in den
    Variant Workspace, ohne Wizard-Schritte automatisch weiterzuschalten.
  - Löst keine Navigation aus.
  - Erzeugt keine VPLIB-Dateien im Browser.

  Abhängigkeit:
  - Muss nach create_core.js geladen werden.
  - Erwartet window.VectoplanCreateCore.
  - Nutzt optional:
    - window.VectoplanCreateVariantProfiles
    - window.VectoplanCreateVariantState
    - window.VectoplanCreatePreviewRenderer

  Öffentliche API:
  - window.VectoplanCreatePreview.initialize()
  - window.VectoplanCreatePreview.refresh()
  - window.VectoplanCreatePreview.update()
  - window.VectoplanCreatePreview.updatePreview()
  - window.VectoplanCreatePreview.applyTaxonomyFiltering()
  - window.VectoplanCreatePreview.applyObjectKindRules()
  - window.VectoplanCreatePreview.updateTaxonomyPath()
  - window.VectoplanCreatePreview.getContext()
  - window.VectoplanCreatePreview.getState()
----------------------------------------------------------------------------- */

(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreatePreview";
  var MODULE_NAME = "preview";
  var PREVIEW_VERSION = "0.4.0";
  var CORE_NAME = "VectoplanCreateCore";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 80;
  var PREVIEW_DEBOUNCE_MS = 60;

  var EXTRA_SELECTORS = {
    taxonomyPathSubcategory: "[data-vp-taxonomy-path-subcategory]",
    taxonomyPathFull: "[data-vp-taxonomy-path-full]",
    taxonomyPathCanonical: "[data-vp-taxonomy-path-canonical]",
    taxonomyPathLabel: "[data-vp-taxonomy-path-label]",

    variantWorkspace: "[data-vp-variant-workspace], [data-create-variant-workspace='true']",
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
    hiddenVariantProfileId: "input[name='variant_profile_id']"
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
    catalog_object: "Katalogobjekt",
    adaptive_system: "Adaptives System"
  };

  var OBJECT_KIND_HINTS = {
    cell_block: "Ein einzelner Raster- oder Blockbaustein. Das Editor-Raster wird auf 1 × 1 × 1 fixiert.",
    adaptive_system: "Ein kontextabhängiges System. Rasterbedarf 1 × 1 × 1; dynamische Regeln bleiben deklarativ vorbereitet.",
    multi_cell_module: "Ein Modul, das mehrere Rasterzellen belegen kann.",
    catalog_object: "Ein freies Objekt wie Möbel, Armatur, Gerät oder Ausstattung."
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

        fallbackWarn("Core runtime missing; preview runtime not initialized.");
        return;
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

      core = coreRuntime || window[CORE_NAME];

      if (!core) {
        fallbackWarn("Cannot initialize preview without create_core.js.");
        return api;
      }

      selectors = core.selectors || {};
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

      core.safeSetAttribute(document.documentElement, "data-vp-create-preview-ready", "true");
      core.safeSetAttribute(document.documentElement, "data-vp-create-preview-version", PREVIEW_VERSION);

      core.dispatch("vectoplan:create:preview-ready", getState());

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

      if (core && typeof core.bindOnce === "function") {
        core.bindOnce("create-preview-taxonomy-filtering", bindTaxonomyFiltering);
        core.bindOnce("create-preview-object-kind-rules", bindObjectKindRules);
        core.bindOnce("create-preview-form-updates", bindPreviewUpdates);
        core.bindOnce("create-preview-context-events", bindContextEvents);
      } else {
        bindTaxonomyFiltering();
        bindObjectKindRules();
        bindPreviewUpdates();
        bindContextEvents();
      }
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

      var domainSelect = core.qs(selectors.domainSelect, form);
      var categorySelect = core.qs(selectors.categorySelect, form);
      var subcategorySelect = core.qs(selectors.subcategorySelect, form);

      [domainSelect, categorySelect, subcategorySelect].forEach(function (select) {
        if (!select) {
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

      var objectKindSelect = core.qs(selectors.objectKindSelect, form);

      if (!objectKindSelect) {
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
    } catch (error) {
      safeError("Object kind binding failed.", error);
    }
  }

  function bindPreviewUpdates() {
    try {
      var form = resolveForm();

      if (!form) {
        return;
      }

      var previewSelector = [
        selectors.objectKindSelect,
        selectors.primitiveShapeSelect,
        selectors.geometryUnit,
        selectors.geometryWidth,
        selectors.geometryHeight,
        selectors.geometryDepth,
        selectors.editorCellsX,
        selectors.editorCellsY,
        selectors.editorCellsZ,
        EXTRA_SELECTORS.familyName,
        EXTRA_SELECTORS.familySlug,
        "[data-create-preview-source]"
      ].join(",");

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

          if (target.matches(selectors.variableRow + " input, " + selectors.variableRow + " select, " + selectors.variableRow + " textarea")) {
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
            if (target.matches(selectors.objectKindSelect)) {
              applyObjectKindRules(form, {
                source: "preview-change-object-kind",
                animate: false
              });
            }

            if (
              target.matches(selectors.domainSelect) ||
              target.matches(selectors.categorySelect) ||
              target.matches(selectors.subcategorySelect)
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

          if (target.matches(selectors.variableRow + " input, " + selectors.variableRow + " select, " + selectors.variableRow + " textarea")) {
            updateVariableCount(form);
          }
        } catch (changeError) {
          safeWarn("Preview change update failed.", changeError);
        }
      });
    } catch (error) {
      safeError("Preview update binding failed.", error);
    }
  }

  function bindContextEvents() {
    try {
      document.addEventListener("vectoplan:create:payload-ready", function () {
        try {
          syncContextToVariantWorkspace({
            source: "payload-ready"
          });
        } catch (error) {
          safeWarn("Payload-ready context sync failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-state-ready", function () {
        try {
          syncContextToVariantWorkspace({
            source: "variant-state-ready"
          });
        } catch (error) {
          safeWarn("Variant-state-ready context sync failed.", error);
        }
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
      var domainSelect = core.qs(selectors.domainSelect, safeForm);
      var categorySelect = core.qs(selectors.categorySelect, safeForm);
      var subcategorySelect = core.qs(selectors.subcategorySelect, safeForm);

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

      core.dispatch("vectoplan:create:taxonomy-changed", {
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

      var options = Array.prototype.slice.call(select.options || []);

      options.forEach(function (option) {
        try {
          if (!option.value) {
            return;
          }

          var optionValue = option.getAttribute("data-" + dataKey) || "";

          if (!expectedValue || !optionValue || optionValue === expectedValue) {
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
        core.dispatchNativeEvent(select, "change");
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
      var familyName = core.getFieldValue(safeForm, "family_name") || core.getFieldValue(safeForm, "family_slug") || "family_slug";
      var familySlug = core.slugify(core.getFieldValue(safeForm, "family_slug") || familyName) || "family_slug";
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

      core.setText(selectors.taxonomyPathDomain, context.domain);
      core.setText(selectors.taxonomyPathCategory, context.category);
      core.setText(EXTRA_SELECTORS.taxonomyPathSubcategory, context.subcategory);
      core.setText(selectors.taxonomyPathFamily, familySlug);

      core.setText(selectors.taxonomyLegacyPath, canonicalPath);
      core.setText(EXTRA_SELECTORS.taxonomyPathFull, canonicalPath);
      core.setText(EXTRA_SELECTORS.taxonomyPathCanonical, canonicalPath);
      core.setText(EXTRA_SELECTORS.taxonomyPathLabel, visibleLabel);
      core.setText(EXTRA_SELECTORS.previewPath, canonicalPath);
      core.setText(EXTRA_SELECTORS.previewTaxonomy, visibleLabel);
      core.setText(EXTRA_SELECTORS.previewFamily, familyName || familySlug);

      localState.lastTaxonomyPath = canonicalPath;

      core.dispatch("vectoplan:create:taxonomy-path-updated", {
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
      var fromContext = core.getNested(core.state.context, ["source_root"], "") ||
        core.getNested(core.state.context, ["sourceRoot"], "") ||
        core.getNested(core.state.context, ["library", "source_root"], "") ||
        core.getNested(core.state.context, ["library", "sourceRoot"], "");

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
      var objectKindSelect = core.qs(selectors.objectKindSelect, safeForm);
      var cellsX = core.qs(selectors.editorCellsX, safeForm);
      var cellsY = core.qs(selectors.editorCellsY, safeForm);
      var cellsZ = core.qs(selectors.editorCellsZ, safeForm);

      if (!objectKindSelect) {
        return false;
      }

      var objectKind = core.normalizeToken(objectKindSelect.value || "cell_block", "cell_block");
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
          safeWarn("Object kind cell input update skipped.", inputError);
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

      core.dispatch("vectoplan:create:object-kind-changed", {
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
      var note = core.qs(selectors.objectKindNote);
      var labelNode = core.qs(selectors.objectKindNoteLabel);
      var textNode = core.qs(selectors.objectKindNoteText);

      if (!note || !labelNode || !textNode) {
        return false;
      }

      var label = core.selectedOptionLabel(core.qs(selectors.objectKindSelect, form), objectKind) || objectKindLabelFallback(objectKind);
      var hint = OBJECT_KIND_HINTS[objectKind] || "Objektart für dieses Library-Element.";

      note.setAttribute("data-create-object-kind-note-value", objectKind || "");
      note.setAttribute("data-create-object-kind-locks-cells", locked ? "true" : "false");
      labelNode.textContent = label;
      textNode.textContent = hint;

      return true;
    } catch (error) {
      safeWarn("Object kind note update failed.", error);
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
      var placeholder = core.qs(selectors.previewPlaceholder);

      if (!safeForm) {
        return false;
      }

      if (window.VectoplanCreatePreviewRenderer && typeof window.VectoplanCreatePreviewRenderer.update === "function") {
        try {
          window.VectoplanCreatePreviewRenderer.update({
            form: safeForm,
            context: getContext(safeForm),
            source: safeOptions.source || "preview-runtime"
          });

          updateGeometrySummariesFromForm(safeForm);
          updatePreviewTextFromForm(safeForm);

          if (placeholder && safeOptions.animate) {
            core.flashUpdated(placeholder);
          }

          return true;
        } catch (rendererError) {
          safeWarn("External preview renderer failed; using fallback preview.", rendererError);
        }
      }

      if (!placeholder) {
        updateGeometrySummariesFromForm(safeForm);
        return false;
      }

      var context = getContext(safeForm);
      var objectKind = context.object_kind;
      var shape = core.normalizeToken(core.getFieldValue(safeForm, "primitive_shape") || "block", "block");
      var width = core.normalizeDecimalDisplay(core.getFieldValue(safeForm, "geometry_width") || "1.00");
      var height = core.normalizeDecimalDisplay(core.getFieldValue(safeForm, "geometry_height") || "1.00");
      var depth = core.normalizeDecimalDisplay(core.getFieldValue(safeForm, "geometry_depth") || "1.00");
      var unit = core.getFieldValue(safeForm, "geometry_unit") || "m";
      var cellsX = core.normalizeIntDisplay(core.getFieldValue(safeForm, "editor_cells_x") || "1");
      var cellsY = core.normalizeIntDisplay(core.getFieldValue(safeForm, "editor_cells_y") || "1");
      var cellsZ = core.normalizeIntDisplay(core.getFieldValue(safeForm, "editor_cells_z") || "1");

      var shapeSelect = core.qs(selectors.primitiveShapeSelect, safeForm);
      var objectKindSelect = core.qs(selectors.objectKindSelect, safeForm);

      var shapeLabel = core.selectedOptionLabel(shapeSelect, shape) || shapeLabelFallback(shape);
      var objectKindLabel = core.selectedOptionLabel(objectKindSelect, objectKind) || objectKindLabelFallback(objectKind);

      var dimensionsText = width + " × " + height + " × " + depth + " " + unit;
      var cellsText = cellsX + " × " + cellsY + " × " + cellsZ;

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

      setPreviewCssVariables(placeholder, {
        width: width,
        height: height,
        depth: depth,
        cellsX: cellsX,
        cellsY: cellsY,
        cellsZ: cellsZ
      });

      core.setText(selectors.previewShape, shapeLabel);
      core.setText(selectors.previewObjectKind, objectKindLabel);
      core.setText(selectors.previewDimensions, dimensionsText);
      core.setText(selectors.previewCells, cellsText);

      updatePreviewTextFromForm(safeForm);
      updatePreviewCube(shape, safeOptions.animate);
      updateGeometrySummaries(width, height, depth, unit, cellsX, cellsY, cellsZ);

      if (safeOptions.animate) {
        core.flashUpdated(placeholder);
      }

      localState.updateCount += 1;
      localState.lastContext = context;
      localState.lastPreview = {
        objectKind: objectKind,
        shape: shape,
        shapeLabel: shapeLabel,
        objectKindLabel: objectKindLabel,
        dimensionsText: dimensionsText,
        cellsText: cellsText,
        timestamp: timestamp()
      };

      core.dispatch("vectoplan:create:preview-updated", {
        context: context,
        preview: localState.lastPreview,
        source: safeOptions.source || "api"
      });

      return true;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Preview update failed.", error);
      return false;
    }
  }

  function updatePreviewTextFromForm(form) {
    try {
      var safeForm = resolveForm(form);
      var context = getContext(safeForm);
      var familyName = core.getFieldValue(safeForm, "family_name") || "Unbenannte Family";
      var familySlug = core.slugify(core.getFieldValue(safeForm, "family_slug") || familyName) || "family_slug";
      var taxonomyText = context.domain + " / " + context.category + " / " + context.subcategory;
      var path = getSourceRoot() + "/" + context.domain + "/" + context.category + "/" + context.subcategory + "/" + familySlug;

      core.setText(EXTRA_SELECTORS.previewFamily, familyName);
      core.setText(EXTRA_SELECTORS.previewTaxonomy, taxonomyText);
      core.setText(EXTRA_SELECTORS.previewPath, path);
    } catch (error) {
      safeWarn("Preview text from form failed.", error);
    }
  }

  function updateGeometrySummariesFromForm(form) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm) {
        return false;
      }

      updateGeometrySummaries(
        core.normalizeDecimalDisplay(core.getFieldValue(safeForm, "geometry_width") || "1.00"),
        core.normalizeDecimalDisplay(core.getFieldValue(safeForm, "geometry_height") || "1.00"),
        core.normalizeDecimalDisplay(core.getFieldValue(safeForm, "geometry_depth") || "1.00"),
        core.getFieldValue(safeForm, "geometry_unit") || "m",
        core.normalizeIntDisplay(core.getFieldValue(safeForm, "editor_cells_x") || "1"),
        core.normalizeIntDisplay(core.getFieldValue(safeForm, "editor_cells_y") || "1"),
        core.normalizeIntDisplay(core.getFieldValue(safeForm, "editor_cells_z") || "1")
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

      core.setText(selectors.geometryVisibleSummary, visibleText);
      core.setText(selectors.geometryCellsSummary, cellsText);

      return true;
    } catch (error) {
      safeWarn("Geometry summary update failed.", error);
      return false;
    }
  }

  function updatePreviewCube(shape, animate) {
    try {
      var cube = core.qs(selectors.previewCube);

      if (!cube) {
        return false;
      }

      var shapeClasses = core.previewShapeClasses || [];

      shapeClasses.forEach(function (className) {
        cube.classList.remove(className);
      });

      var normalized = normalizePreviewShape(shape);

      cube.classList.add("vp-create-preview-cube--" + normalized);
      cube.setAttribute("data-create-preview-cube-shape", normalized);
      cube.setAttribute("data-vp-preview-cube-shape", normalized);

      if (animate) {
        core.flashUpdated(cube);
      }

      return true;
    } catch (error) {
      safeWarn("Preview cube update failed.", error);
      return false;
    }
  }

  function setPreviewCssVariables(node, values) {
    try {
      if (!node || !values) {
        return false;
      }

      var width = Math.max(0.1, core.toNumber(values.width, 1));
      var height = Math.max(0.1, core.toNumber(values.height, 1));
      var depth = Math.max(0.1, core.toNumber(values.depth, 1));
      var maxDimension = Math.max(width, height, depth, 1);

      node.style.setProperty("--vp-preview-width-ratio", String(width / maxDimension));
      node.style.setProperty("--vp-preview-height-ratio", String(height / maxDimension));
      node.style.setProperty("--vp-preview-depth-ratio", String(depth / maxDimension));
      node.style.setProperty("--vp-preview-cells-x", String(core.toInteger(values.cellsX, 1)));
      node.style.setProperty("--vp-preview-cells-y", String(core.toInteger(values.cellsY, 1)));
      node.style.setProperty("--vp-preview-cells-z", String(core.toInteger(values.cellsZ, 1)));

      return true;
    } catch (error) {
      safeWarn("Preview CSS variable update failed.", error);
      return false;
    }
  }

  function normalizePreviewShape(shape) {
    try {
      var value = core.normalizeToken(shape || "block", "block");

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
      var normalized = core.normalizeToken(objectKind, "cell_block");
      return OBJECT_KIND_LABELS[normalized] || normalized || "Objektart";
    } catch (error) {
      return "Objektart";
    }
  }

  function syncContextToVariantWorkspace(options) {
    try {
      var form = resolveForm();
      var context = getContext(form);
      var workspaceNodes = core.qsa(EXTRA_SELECTORS.variantWorkspace);
      var drawerNodes = core.qsa(EXTRA_SELECTORS.variantDrawer);

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

      core.dispatch("vectoplan:create:context-synced", {
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

      core.dispatch("vectoplan:create:variant-profile-context-changed", {
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
      var domain = core.getFieldValue(safeForm, "domain") ||
        core.getNested(core.state.uiState, ["defaults", "domain"], "hochbau");

      var category = core.getFieldValue(safeForm, "category") ||
        core.getNested(core.state.uiState, ["defaults", "category"], "bloecke");

      var subcategory = core.getFieldValue(safeForm, "subcategory") ||
        core.getNested(core.state.uiState, ["defaults", "subcategory"], "basis");

      var objectKind = core.getFieldValue(safeForm, "object_kind") ||
        core.getNested(core.state.uiState, ["defaults", "object_kind"], "cell_block");

      var familyProfileId = core.getFieldValue(safeForm, "family_profile_id") ||
        readWorkspaceAttribute("data-vp-current-family-profile-id") ||
        "";

      var variantProfileId = core.getFieldValue(safeForm, "variant_profile_id") ||
        readWorkspaceAttribute("data-vp-current-variant-profile-id") ||
        "";

      return {
        domain: core.normalizeToken(domain, "hochbau"),
        category: core.normalizeToken(category, "bloecke"),
        subcategory: core.normalizeToken(subcategory, "basis"),
        object_kind: core.normalizeToken(objectKind, "cell_block"),
        objectKind: core.normalizeToken(objectKind, "cell_block"),
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
      var workspace = core.qs(EXTRA_SELECTORS.variantWorkspace);

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
      var label = core.qs(selectors.variantCountLabel);
      var count = 0;

      if (window.VectoplanCreateVariantState && typeof window.VectoplanCreateVariantState.getVariants === "function") {
        var variants = window.VectoplanCreateVariantState.getVariants();
        count = Array.isArray(variants) ? variants.length : 0;
      }

      if (!count && safeForm) {
        count = core.qsa(selectors.variantRow, safeForm).length;
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
      var label = core.qs(selectors.variableCountLabel);
      var rows = safeForm ? core.qsa(selectors.variableRow, safeForm) : [];
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
      var fields = core.qsa("input, select, textarea", row);

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
        ? core.qs(selectors.form)
        : document.querySelector("[data-vp-create-form], [data-create-form='true'], #vp-create-form");
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
        lastContext: core && typeof core.clone === "function" ? core.clone(localState.lastContext) : localState.lastContext,
        lastPreview: core && typeof core.clone === "function" ? core.clone(localState.lastPreview) : localState.lastPreview,
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
          window.console.warn("[VPLIB Create Preview] " + message, error);
        } else {
          window.console.warn("[VPLIB Create Preview] " + message);
        }
      }
    } catch (consoleError) {
      /* no-op */
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

    syncContextToVariantWorkspace: syncContextToVariantWorkspace,
    scheduleVariantProfileResolve: scheduleVariantProfileResolve,
    getContext: getContext,

    updateVariantCount: updateVariantCount,
    updateVariableCount: updateVariableCount,

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