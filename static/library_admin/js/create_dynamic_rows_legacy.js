/* services/vectoplan-library/static/library_admin/js/create_dynamic_rows_legacy.js */

/* -----------------------------------------------------------------------------
  VECTOPLAN Library · VPLIB Create Dynamic Rows Legacy Runtime

  Zweck:
  - Legacy-Kompatibilität für dynamische Tabellenzeilen im /create Wizard.
  - Entlastet die bisher zu große create.js.
  - Verwaltet alte Varianten- und Kennwert-Tabellen, falls sie noch im Template
    vorhanden sind.
  - Kollidiert nicht mit der neuen definition-managed Variant Runtime.
  - Delegiert Variantenanlage bevorzugt an den neuen Variant Drawer.
  - Hält alte data-create-* Hooks weiter lauffähig.
  - Erzeugt keine VPLIB-Dateien im Browser.

  Wichtig:
  - Neue Varianten sollen fachlich über:
      window.VectoplanCreateVariantDrawer
      window.VectoplanCreateVariantState
    laufen.
  - Diese Datei bleibt als robuste Brücke für alte Tabellen, Fallbacks und
    technische Kennwert-Zeilen erhalten.

  Abhängigkeit:
  - Muss nach create_core.js geladen werden.
  - Sollte nach create_preview.js geladen werden, falls Count-/Preview-Updates
    darüber laufen sollen.
  - Erwartet window.VectoplanCreateCore.
  - Nutzt optional:
    - window.VectoplanCreateVariantDrawer
    - window.VectoplanCreateVariantState
    - window.VectoplanCreatePreview
    - window.VectoplanCreatePayload

  Öffentliche API:
  - window.VectoplanCreateDynamicRowsLegacy.initialize()
  - window.VectoplanCreateDynamicRowsLegacy.addVariantRow()
  - window.VectoplanCreateDynamicRowsLegacy.addVariableRow()
  - window.VectoplanCreateDynamicRowsLegacy.removeDynamicRow(buttonOrRow)
  - window.VectoplanCreateDynamicRowsLegacy.clearVariableRow(buttonOrRow)
  - window.VectoplanCreateDynamicRowsLegacy.reindexAll()
  - window.VectoplanCreateDynamicRowsLegacy.refreshAutoSlugs()
  - window.VectoplanCreateDynamicRowsLegacy.updateCounts()
  - window.VectoplanCreateDynamicRowsLegacy.getState()
----------------------------------------------------------------------------- */

(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateDynamicRowsLegacy";
  var MODULE_NAME = "dynamicRowsLegacy";
  var LEGACY_VERSION = "0.4.0";
  var CORE_NAME = "VectoplanCreateCore";
  var PREVIEW_NAME = "VectoplanCreatePreview";
  var PAYLOAD_NAME = "VectoplanCreatePayload";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 80;

  var LEGACY_VARIANT_SOURCE = "legacy_row";
  var LEGACY_VARIABLE_SOURCE = "legacy_variable_row";

  var core = null;
  var selectors = null;
  var classes = null;
  var initialized = false;
  var bindingDone = false;

  var localState = {
    version: LEGACY_VERSION,
    initialized: false,
    bindingDone: false,
    addVariantCount: 0,
    addVariableCount: 0,
    removeCount: 0,
    clearCount: 0,
    reindexCount: 0,
    autoSlugCount: 0,
    delegatedVariantDrawerCount: 0,
    fallbackVariantRowCount: 0,
    lastAction: "",
    lastError: null
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

        fallbackWarn("Core runtime missing; dynamic rows legacy runtime not initialized.");
        return;
      }

      initialize(maybeCore);
    } catch (error) {
      fallbackWarn("Dynamic rows legacy boot failed.", error);
    }
  }

  function initialize(coreRuntime) {
    try {
      if (initialized) {
        return api;
      }

      core = coreRuntime || window[CORE_NAME];

      if (!core) {
        fallbackWarn("Cannot initialize dynamic rows legacy without create_core.js.");
        return api;
      }

      selectors = core.selectors || {};
      classes = core.classes || {};

      if (typeof core.refreshContext === "function") {
        core.refreshContext();
      }

      bindControls();
      reindexAll(resolveForm(), {
        source: "legacy-init",
        silent: true
      });
      updateCounts(resolveForm());

      initialized = true;
      localState.initialized = true;

      if (typeof core.registerModule === "function") {
        core.registerModule(MODULE_NAME, api);
      }

      core.safeSetAttribute(document.documentElement, "data-vp-create-dynamic-rows-legacy-ready", "true");
      core.safeSetAttribute(document.documentElement, "data-vp-create-dynamic-rows-legacy-version", LEGACY_VERSION);

      core.dispatch("vectoplan:create:dynamic-rows-legacy-ready", getState());

      return api;
    } catch (error) {
      localState.initialized = false;
      localState.lastError = normalizeError(error);
      safeError("Dynamic rows legacy initialization failed.", error);
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
        core.bindOnce("create-dynamic-rows-legacy-click", bindClickControls);
        core.bindOnce("create-dynamic-rows-legacy-input", bindInputControls);
        core.bindOnce("create-dynamic-rows-legacy-state-events", bindStateEvents);
      } else {
        bindClickControls();
        bindInputControls();
        bindStateEvents();
      }
    } catch (error) {
      safeError("Dynamic rows legacy control binding failed.", error);
    }
  }

  function bindClickControls() {
    try {
      document.addEventListener("click", function (event) {
        try {
          var target = event && event.target ? event.target : null;

          if (!target || !target.closest) {
            return;
          }

          var form = resolveForm();

          if (!form) {
            return;
          }

          var addVariantButton = target.closest(selectors.addVariant);

          if (addVariantButton && form.contains(addVariantButton)) {
            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            addVariantRow(form, {
              source: "button"
            });
            return;
          }

          var addVariableButton = target.closest(selectors.addVariable);

          if (addVariableButton && form.contains(addVariableButton)) {
            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            addVariableRow(form, {
              source: "button"
            });
            return;
          }

          var removeButton = target.closest(selectors.removeRow);

          if (removeButton && form.contains(removeButton)) {
            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            removeDynamicRow(removeButton, {
              source: "button"
            });
            return;
          }

          var clearVariableButton = target.closest(selectors.clearVariable);

          if (clearVariableButton && form.contains(clearVariableButton)) {
            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            clearVariableRow(clearVariableButton, {
              source: "button"
            });
          }
        } catch (clickError) {
          safeWarn("Dynamic row click handling failed.", clickError);
        }
      }, true);
    } catch (error) {
      safeError("Dynamic row click binding failed.", error);
    }
  }

  function bindInputControls() {
    try {
      document.addEventListener("input", function (event) {
        try {
          var target = event && event.target ? event.target : null;
          var form = resolveForm();

          if (!target || !form || !form.contains(target)) {
            return;
          }

          if (target.matches && target.matches("[name*='variants']")) {
            refreshAutoSlugs(form, {
              source: "variant-input",
              silent: true
            });
            updateCounts(form);
            syncPayload(form, {
              source: "variant-input"
            });
            return;
          }

          if (target.matches && target.matches("[name='family_name'], [name='family_slug']")) {
            refreshAutoSlugs(form, {
              source: "family-input",
              silent: true
            });
            updatePreview({
              source: "family-input",
              animate: false
            });
            return;
          }

          if (target.matches && target.matches(selectors.variableRow + " input, " + selectors.variableRow + " select, " + selectors.variableRow + " textarea")) {
            updateCounts(form);
          }
        } catch (inputError) {
          safeWarn("Dynamic row input handling failed.", inputError);
        }
      }, true);

      document.addEventListener("change", function (event) {
        try {
          var target = event && event.target ? event.target : null;
          var form = resolveForm();

          if (!target || !form || !form.contains(target)) {
            return;
          }

          if (target.matches && target.matches("[name*='variants']")) {
            refreshAutoSlugs(form, {
              source: "variant-change",
              silent: true
            });
            updateCounts(form);
            syncPayload(form, {
              source: "variant-change"
            });
            updatePreview({
              source: "variant-change",
              animate: true
            });
            return;
          }

          if (target.matches && target.matches(selectors.variableRow + " input, " + selectors.variableRow + " select, " + selectors.variableRow + " textarea")) {
            updateCounts(form);
          }
        } catch (changeError) {
          safeWarn("Dynamic row change handling failed.", changeError);
        }
      }, true);
    } catch (error) {
      safeError("Dynamic row input binding failed.", error);
    }
  }

  function bindStateEvents() {
    try {
      document.addEventListener("vectoplan:create:variant-state-changed", function () {
        try {
          updateCounts(resolveForm());
          syncPayload(resolveForm(), {
            source: "variant-state-changed"
          });
        } catch (error) {
          safeWarn("Variant state changed handling failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:payload-ready", function () {
        try {
          syncPayload(resolveForm(), {
            source: "payload-ready"
          });
        } catch (error) {
          safeWarn("Payload ready handling failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:preview-ready", function () {
        try {
          updateCounts(resolveForm());
        } catch (error) {
          safeWarn("Preview ready handling failed.", error);
        }
      });
    } catch (error) {
      safeWarn("Dynamic row state event binding failed.", error);
    }
  }

  function addVariantRow(form, options) {
    try {
      ensureCore();

      var safeForm = resolveForm(form);
      var safeOptions = options || {};

      if (!safeForm) {
        throw new Error("Create form not found.");
      }

      localState.addVariantCount += 1;
      localState.lastAction = "addVariantRow";

      if (shouldDelegateVariantCreation(safeForm, safeOptions)) {
        var delegated = openVariantDrawer({
          source: safeOptions.source || "legacy-add-button"
        });

        if (delegated) {
          localState.delegatedVariantDrawerCount += 1;
          setStatus("Varianten-Drawer geöffnet.", "ok");
          return null;
        }
      }

      var table = core.qs(selectors.variantTable, safeForm);
      var template = core.qs(selectors.variantTemplate, safeForm);

      if (!table || !template) {
        setStatus("Varianten-Template fehlt.", "error");
        return null;
      }

      var index = getNextRowIndex(safeForm, selectors.variantRow);
      core.state.variantIndex = Math.max(core.state.variantIndex || 1, index + 1);

      var html = core.getTemplateHtml(template).replace(/__index__/g, String(index));
      var fragment = core.htmlToFragment(html);
      var row = core.qs(selectors.variantRow, fragment) || fragment.firstElementChild;

      if (!row) {
        setStatus("Varianten-Zeile konnte nicht erzeugt werden.", "error");
        return null;
      }

      row.setAttribute("data-row-index", String(index));
      row.setAttribute("data-vp-row-source", LEGACY_VARIANT_SOURCE);
      row.setAttribute("data-vp-row-created-at", timestamp());

      table.appendChild(row);

      reindexRows(table, "variants", selectors.variantRow);
      refreshAutoSlugs(safeForm, {
        source: "add-variant-row",
        silent: true
      });
      updateCounts(safeForm);
      syncPayload(safeForm, {
        source: "add-variant-row"
      });
      updatePreview({
        source: "add-variant-row",
        animate: true
      });

      localState.fallbackVariantRowCount += 1;

      core.focusFirstInput(row);
      setStatus("Variante hinzugefügt.", "ok");

      core.dispatch("vectoplan:create:legacy-variant-row-added", {
        rowIndex: index,
        row: row
      });

      return row;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Add variant row failed.", error);
      setStatus("Variante konnte nicht hinzugefügt werden.", "error");
      return null;
    }
  }

  function addVariableRow(form, options) {
    try {
      ensureCore();

      var safeForm = resolveForm(form);
      var safeOptions = options || {};

      if (!safeForm) {
        throw new Error("Create form not found.");
      }

      localState.addVariableCount += 1;
      localState.lastAction = "addVariableRow";

      var table = core.qs(selectors.variableTable, safeForm);
      var template = core.qs(selectors.variableTemplate, safeForm);

      if (!table || !template) {
        setStatus("Kennwert-Template fehlt.", "error");
        return null;
      }

      var index = getNextRowIndex(safeForm, selectors.variableRow);
      core.state.variableIndex = Math.max(core.state.variableIndex || 1, index + 1);

      var html = core.getTemplateHtml(template).replace(/__index__/g, String(index));
      var fragment = core.htmlToFragment(html);
      var row = core.qs(selectors.variableRow, fragment) || fragment.firstElementChild;

      if (!row) {
        setStatus("Kennwert-Zeile konnte nicht erzeugt werden.", "error");
        return null;
      }

      row.setAttribute("data-row-index", String(index));
      row.setAttribute("data-vp-row-source", LEGACY_VARIABLE_SOURCE);
      row.setAttribute("data-vp-row-created-at", timestamp());

      table.appendChild(row);

      reindexRows(table, "variables", selectors.variableRow);
      updateCounts(safeForm);
      syncPayload(safeForm, {
        source: safeOptions.source || "add-variable-row"
      });

      core.focusFirstInput(row);
      setStatus("Kennwert hinzugefügt.", "ok");

      core.dispatch("vectoplan:create:legacy-variable-row-added", {
        rowIndex: index,
        row: row
      });

      return row;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Add variable row failed.", error);
      setStatus("Kennwert konnte nicht hinzugefügt werden.", "error");
      return null;
    }
  }

  function removeDynamicRow(buttonOrRow, options) {
    try {
      ensureCore();

      var safeOptions = options || {};
      var row = resolveDynamicRow(buttonOrRow);

      if (!row) {
        return false;
      }

      var table = row.parentElement;
      var isVariant = row.matches(selectors.variantRow);
      var isVariable = row.matches(selectors.variableRow);
      var form = resolveForm();

      if (isVariant && isDefaultVariantRow(row)) {
        setStatus("Die Default-Variante bleibt fix.", "warning");

        core.dispatch("vectoplan:create:legacy-row-remove-blocked", {
          reason: "default_variant",
          row: row
        });

        return false;
      }

      var rowIndex = parseInt(row.getAttribute("data-row-index") || "-1", 10);

      row.remove();
      localState.removeCount += 1;
      localState.lastAction = "removeDynamicRow";

      if (table && isVariant) {
        reindexRows(table, "variants", selectors.variantRow);
      }

      if (table && isVariable) {
        reindexRows(table, "variables", selectors.variableRow);
      }

      refreshAutoSlugs(form, {
        source: safeOptions.source || "remove-row",
        silent: true
      });
      updateCounts(form);
      syncPayload(form, {
        source: safeOptions.source || "remove-row"
      });
      updatePreview({
        source: safeOptions.source || "remove-row",
        animate: true
      });

      setStatus("Zeile entfernt.", "ok");

      core.dispatch("vectoplan:create:legacy-row-removed", {
        rowIndex: rowIndex,
        rowType: isVariant ? "variant" : isVariable ? "variable" : "unknown"
      });

      return true;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Remove dynamic row failed.", error);
      setStatus("Zeile konnte nicht entfernt werden.", "error");
      return false;
    }
  }

  function clearVariableRow(buttonOrRow, options) {
    try {
      ensureCore();

      var row = resolveVariableRow(buttonOrRow);

      if (!row) {
        return false;
      }

      var fields = core.qsa("input, select, textarea", row);

      fields.forEach(function (input) {
        try {
          if (input.type === "hidden") {
            return;
          }

          if (input.tagName && input.tagName.toLowerCase() === "select") {
            input.selectedIndex = 0;
          } else if (input.type === "checkbox" || input.type === "radio") {
            input.checked = false;
          } else {
            input.value = "";
          }

          core.dispatchNativeEvent(input, "input");
          core.dispatchNativeEvent(input, "change");
        } catch (fieldError) {
          safeWarn("Variable row field clear skipped.", fieldError);
        }
      });

      localState.clearCount += 1;
      localState.lastAction = "clearVariableRow";

      updateCounts(resolveForm());
      syncPayload(resolveForm(), {
        source: options && options.source ? options.source : "clear-variable-row"
      });

      setStatus("Kennwert geleert.", "ok");

      core.dispatch("vectoplan:create:legacy-variable-row-cleared", {
        row: row,
        rowIndex: parseInt(row.getAttribute("data-row-index") || "-1", 10)
      });

      return true;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Clear variable row failed.", error);
      setStatus("Kennwert konnte nicht geleert werden.", "error");
      return false;
    }
  }

  function reindexAll(form, options) {
    try {
      ensureCore();

      var safeForm = resolveForm(form);

      if (!safeForm) {
        return false;
      }

      var variantTable = core.qs(selectors.variantTable, safeForm);
      var variableTable = core.qs(selectors.variableTable, safeForm);

      if (variantTable) {
        reindexRows(variantTable, "variants", selectors.variantRow);
      }

      if (variableTable) {
        reindexRows(variableTable, "variables", selectors.variableRow);
      }

      refreshAutoSlugs(safeForm, {
        source: options && options.source ? options.source : "reindex-all",
        silent: true
      });
      updateCounts(safeForm);

      localState.reindexCount += 1;
      localState.lastAction = "reindexAll";

      if (!options || !options.silent) {
        setStatus("Zeilen neu indexiert.", "ok");
      }

      core.dispatch("vectoplan:create:legacy-rows-reindexed", {
        source: options && options.source ? options.source : "api"
      });

      return true;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Reindex all dynamic rows failed.", error);
      return false;
    }
  }

  function reindexRows(table, prefix, rowSelector) {
    try {
      if (!table || !prefix || !rowSelector) {
        return false;
      }

      var rows = core.qsa(rowSelector, table);

      rows.forEach(function (row, index) {
        try {
          row.setAttribute("data-row-index", String(index));

          var fields = core.qsa("[name]", row);

          fields.forEach(function (field) {
            try {
              var oldName = field.getAttribute("name") || "";
              var escapedPrefix = prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
              var newName = oldName.replace(new RegExp("^" + escapedPrefix + "\\[\\d+\\]"), prefix + "[" + index + "]");

              field.setAttribute("name", newName);
            } catch (fieldError) {
              safeWarn("Field reindex skipped.", fieldError);
            }
          });

          if (prefix === "variants") {
            normalizeVariantRow(row, index);
          }

          if (prefix === "variables") {
            normalizeVariableRow(row, index);
          }
        } catch (rowError) {
          safeWarn("Row reindex skipped.", rowError);
        }
      });

      return true;
    } catch (error) {
      safeWarn("Reindex rows failed.", error);
      return false;
    }
  }

  function normalizeVariantRow(row, index) {
    try {
      if (!row) {
        return false;
      }

      var checkbox = core.qs("[data-create-field='variant_is_default']", row);
      var label = core.qs("[data-vp-default-label]", row);
      var removeButton = core.qs(selectors.removeRow, row);
      var staticButton = core.qs("[data-create-static-disabled='true']", row);
      var slugInput = core.qs("[data-create-field='variant_slug'], [data-create-field='variant_id']", row);
      var nameInput = core.qs("[data-create-field='variant_name']", row);

      row.setAttribute("data-row-index", String(index));

      if (checkbox) {
        if (index === 0 || checkbox.hasAttribute("data-create-default-locked")) {
          checkbox.checked = true;
          checkbox.value = "true";
          checkbox.setAttribute("data-create-default-locked", "true");
          checkbox.setAttribute("aria-readonly", "true");
        } else {
          checkbox.value = checkbox.checked ? "true" : "false";
        }
      }

      if (label) {
        label.textContent = checkbox && checkbox.checked ? "Default" : "Nein";
      }

      if (slugInput) {
        if (index === 0) {
          slugInput.value = "default";
          slugInput.setAttribute("readonly", "readonly");
          slugInput.setAttribute("aria-readonly", "true");
        } else if (!slugInput.value || slugInput.getAttribute("data-create-auto-slug") === "true") {
          slugInput.value = core.slugify(nameInput && nameInput.value ? nameInput.value : "variant_" + (index + 1));
          slugInput.setAttribute("data-create-auto-slug", "true");
        }
      }

      if (index === 0) {
        if (removeButton) {
          removeButton.disabled = true;
          removeButton.setAttribute("aria-disabled", "true");
          removeButton.setAttribute("data-create-static-disabled", "true");
          removeButton.removeAttribute("data-create-remove-row");
          removeButton.textContent = "Fix";
        }

        if (staticButton) {
          staticButton.disabled = true;
          staticButton.setAttribute("aria-disabled", "true");
          staticButton.textContent = "Fix";
        }

        row.setAttribute("data-vp-default-variant-row", "true");
      } else {
        row.removeAttribute("data-vp-default-variant-row");
      }

      return true;
    } catch (error) {
      safeWarn("Normalize variant row failed.", error);
      return false;
    }
  }

  function normalizeVariableRow(row, index) {
    try {
      if (!row) {
        return false;
      }

      var clearButton = core.qs(selectors.clearVariable, row);
      var removeButton = core.qs(selectors.removeRow, row);

      row.setAttribute("data-row-index", String(index));

      if (index === 0 && removeButton && !clearButton) {
        removeButton.setAttribute("data-create-clear-variable", "true");
        removeButton.removeAttribute("data-create-remove-row");
        removeButton.textContent = "Leeren";
      }

      if (index > 0 && clearButton && !removeButton) {
        clearButton.setAttribute("data-create-remove-row", "true");
        clearButton.removeAttribute("data-create-clear-variable");
        clearButton.textContent = "Entfernen";
      }

      return true;
    } catch (error) {
      safeWarn("Normalize variable row failed.", error);
      return false;
    }
  }

  function refreshAutoSlugs(form, options) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm) {
        return false;
      }

      var rows = core.qsa(selectors.variantRow, safeForm);

      rows.forEach(function (row, index) {
        try {
          var nameInput = core.qs("[data-create-field='variant_name']", row);
          var slugInput = core.qs("[data-create-field='variant_slug'], [data-create-field='variant_id']", row);

          if (!slugInput) {
            return;
          }

          if (index === 0) {
            slugInput.value = "default";
            return;
          }

          if (slugInput.getAttribute("data-create-auto-slug") === "true" || !slugInput.value) {
            var value = nameInput ? nameInput.value : "";
            slugInput.value = core.slugify(value || "variant_" + (index + 1));
            slugInput.setAttribute("data-create-auto-slug", "true");
          }
        } catch (rowError) {
          safeWarn("Auto slug row skipped.", rowError);
        }
      });

      localState.autoSlugCount += 1;

      if (!options || !options.silent) {
        setStatus("Varianten-Slugs aktualisiert.", "ok");
      }

      return true;
    } catch (error) {
      safeWarn("Refresh auto slugs failed.", error);
      return false;
    }
  }

  function updateCounts(form) {
    try {
      var safeForm = resolveForm(form);
      var variantCount = updateVariantCount(safeForm);
      var variableCount = updateVariableCount(safeForm);

      return {
        variants: variantCount,
        variables: variableCount
      };
    } catch (error) {
      safeWarn("Update counts failed.", error);

      return {
        variants: 0,
        variables: {
          count: 0,
          filled: 0
        }
      };
    }
  }

  function updateVariantCount(form) {
    try {
      var previewRuntime = window[PREVIEW_NAME];

      if (previewRuntime && typeof previewRuntime.updateVariantCount === "function") {
        return previewRuntime.updateVariantCount(form || resolveForm());
      }

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
      var previewRuntime = window[PREVIEW_NAME];

      if (previewRuntime && typeof previewRuntime.updateVariableCount === "function") {
        return previewRuntime.updateVariableCount(form || resolveForm());
      }

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
        if (!field || field.type === "hidden") {
          return false;
        }

        if (field.type === "checkbox" || field.type === "radio") {
          return !!field.checked;
        }

        return field.value && String(field.value).trim() !== "";
      });
    } catch (error) {
      return false;
    }
  }

  function shouldDelegateVariantCreation(form, options) {
    try {
      var safeOptions = options || {};

      if (safeOptions.forceLegacy === true) {
        return false;
      }

      if (safeOptions.forceDrawer === true) {
        return true;
      }

      var drawerRuntime = window.VectoplanCreateVariantDrawer;
      var stateRuntime = window.VectoplanCreateVariantState;
      var workspace = document.querySelector("[data-vp-variant-workspace], [data-create-variant-workspace='true']");

      if (!drawerRuntime || typeof drawerRuntime.open !== "function") {
        return false;
      }

      if (workspace) {
        return true;
      }

      if (stateRuntime && typeof stateRuntime.getState === "function") {
        return true;
      }

      var buttonPrefersRuntime = false;

      try {
        var buttons = core.qsa(selectors.addVariant, form);
        buttonPrefersRuntime = buttons.some(function (button) {
          return button.getAttribute("data-vp-use-variant-runtime") === "true" ||
            button.getAttribute("data-create-use-variant-runtime") === "true";
        });
      } catch (buttonError) {
        buttonPrefersRuntime = false;
      }

      return buttonPrefersRuntime;
    } catch (error) {
      safeWarn("Variant creation delegation check failed.", error);
      return false;
    }
  }

  function openVariantDrawer(options) {
    try {
      var drawerRuntime = window.VectoplanCreateVariantDrawer;

      if (!drawerRuntime || typeof drawerRuntime.open !== "function") {
        return false;
      }

      drawerRuntime.open({
        mode: "create",
        source: options && options.source ? options.source : "legacy-dynamic-rows",
        context: getVariantContext()
      });

      return true;
    } catch (error) {
      safeWarn("Open variant drawer failed.", error);
      return false;
    }
  }

  function getVariantContext() {
    try {
      var previewRuntime = window[PREVIEW_NAME];

      if (previewRuntime && typeof previewRuntime.getContext === "function") {
        return previewRuntime.getContext(resolveForm());
      }

      var form = resolveForm();

      return {
        domain: core.normalizeToken(core.getFieldValue(form, "domain"), "hochbau"),
        category: core.normalizeToken(core.getFieldValue(form, "category"), "bloecke"),
        subcategory: core.normalizeToken(core.getFieldValue(form, "subcategory"), "basis"),
        object_kind: core.normalizeToken(core.getFieldValue(form, "object_kind"), "cell_block"),
        objectKind: core.normalizeToken(core.getFieldValue(form, "object_kind"), "cell_block"),
        family_profile_id: core.getFieldValue(form, "family_profile_id") || "",
        familyProfileId: core.getFieldValue(form, "family_profile_id") || "",
        variant_profile_id: core.getFieldValue(form, "variant_profile_id") || "",
        variantProfileId: core.getFieldValue(form, "variant_profile_id") || ""
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

  function syncPayload(form, options) {
    try {
      var payloadRuntime = window[PAYLOAD_NAME];

      if (payloadRuntime && typeof payloadRuntime.syncVariantRuntimeToForm === "function") {
        payloadRuntime.syncVariantRuntimeToForm(form || resolveForm(), {
          source: options && options.source ? options.source : "dynamic-rows-legacy"
        });
        return true;
      }

      return false;
    } catch (error) {
      safeWarn("Payload sync from dynamic rows failed.", error);
      return false;
    }
  }

  function updatePreview(options) {
    try {
      var previewRuntime = window[PREVIEW_NAME];

      if (previewRuntime && typeof previewRuntime.updatePreview === "function") {
        previewRuntime.updatePreview(resolveForm(), options || {});
        return true;
      }

      if (previewRuntime && typeof previewRuntime.refresh === "function") {
        previewRuntime.refresh(options || {});
        return true;
      }

      return false;
    } catch (error) {
      safeWarn("Preview update from dynamic rows failed.", error);
      return false;
    }
  }

  function resolveDynamicRow(buttonOrRow) {
    try {
      if (!buttonOrRow) {
        return null;
      }

      if (buttonOrRow.matches && (buttonOrRow.matches(selectors.variantRow) || buttonOrRow.matches(selectors.variableRow))) {
        return buttonOrRow;
      }

      if (buttonOrRow.closest) {
        return buttonOrRow.closest(selectors.variantRow + ", " + selectors.variableRow);
      }

      return null;
    } catch (error) {
      return null;
    }
  }

  function resolveVariableRow(buttonOrRow) {
    try {
      if (!buttonOrRow) {
        return null;
      }

      if (buttonOrRow.matches && buttonOrRow.matches(selectors.variableRow)) {
        return buttonOrRow;
      }

      if (buttonOrRow.closest) {
        return buttonOrRow.closest(selectors.variableRow);
      }

      return null;
    } catch (error) {
      return null;
    }
  }

  function isDefaultVariantRow(row) {
    try {
      if (!row) {
        return false;
      }

      var index = parseInt(row.getAttribute("data-row-index") || "0", 10);

      if (index === 0) {
        return true;
      }

      if (row.getAttribute("data-vp-default-variant-row") === "true") {
        return true;
      }

      var checkbox = core.qs("[data-create-field='variant_is_default']", row);

      if (checkbox && checkbox.checked && checkbox.hasAttribute("data-create-default-locked")) {
        return true;
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function getNextRowIndex(form, rowSelector) {
    try {
      var safeForm = resolveForm(form);
      var rows = safeForm ? core.qsa(rowSelector, safeForm) : [];
      var max = -1;

      rows.forEach(function (row) {
        var index = parseInt(row.getAttribute("data-row-index") || "-1", 10);

        if (Number.isFinite(index) && index > max) {
          max = index;
        }
      });

      return max + 1;
    } catch (error) {
      return 0;
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

  function setStatus(message, stateName) {
    try {
      if (core && typeof core.setStatus === "function") {
        core.setStatus(message, stateName);
      }
    } catch (error) {
      safeWarn("Set status failed.", error);
    }
  }

  function getState() {
    try {
      return {
        version: LEGACY_VERSION,
        initialized: initialized,
        bindingDone: bindingDone,
        addVariantCount: localState.addVariantCount,
        addVariableCount: localState.addVariableCount,
        removeCount: localState.removeCount,
        clearCount: localState.clearCount,
        reindexCount: localState.reindexCount,
        autoSlugCount: localState.autoSlugCount,
        delegatedVariantDrawerCount: localState.delegatedVariantDrawerCount,
        fallbackVariantRowCount: localState.fallbackVariantRowCount,
        lastAction: localState.lastAction,
        lastError: localState.lastError
      };
    } catch (error) {
      return {
        version: LEGACY_VERSION,
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
          window.console.warn("[VPLIB Create Dynamic Rows Legacy] " + message, error);
        } else {
          window.console.warn("[VPLIB Create Dynamic Rows Legacy] " + message);
        }
      }
    } catch (consoleError) {
      /* no-op */
    }
  }

  var api = {
    version: LEGACY_VERSION,

    initialize: initialize,

    addVariantRow: addVariantRow,
    addVariableRow: addVariableRow,
    removeDynamicRow: removeDynamicRow,
    clearVariableRow: clearVariableRow,

    reindexAll: reindexAll,
    reindexRows: reindexRows,
    refreshAutoSlugs: refreshAutoSlugs,

    updateCounts: updateCounts,
    updateVariantCount: updateVariantCount,
    updateVariableCount: updateVariableCount,

    shouldDelegateVariantCreation: shouldDelegateVariantCreation,
    openVariantDrawer: openVariantDrawer,

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