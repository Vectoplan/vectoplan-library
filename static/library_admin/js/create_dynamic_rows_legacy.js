/* services/vectoplan-library/static/library_admin/js/create_dynamic_rows_legacy.js */

/* -----------------------------------------------------------------------------
  VECTOPLAN Library · VPLIB Create Dynamic Rows Legacy Runtime

  Zweck:
  - Legacy-Kompatibilität für dynamische Tabellenzeilen im /create Wizard.
  - Entlastet create.js.
  - Verwaltet alte Varianten- und Kennwert-Tabellen, falls sie noch im Template
    vorhanden sind.
  - Kollidiert nicht mit der neuen definition-managed Variant Runtime.
  - Delegiert Variantenanlage bevorzugt an den neuen Variablen-/Variant-Drawer.
  - Hält alte data-create-* Hooks weiter lauffähig.
  - Erzeugt keine VPLIB-Dateien im Browser.
  - Verarbeitet keine Upload-Dateien und erzeugt keine Objekt-URLs.

  Wichtig:
  - Neue Varianten sollen fachlich über:
      window.VectoplanCreateVariantDrawer
      window.VectoplanCreateVariantDrawerShell
      window.VectoplanCreateVariantWorkspace
      window.VectoplanCreateVariantState
    laufen.
  - Diese Datei bleibt als robuste Brücke für alte Tabellen, Fallbacks und
    technische Kennwert-Zeilen erhalten.
  - Definition-managed Tabellen werden standardmäßig nicht reindexiert oder
    mutiert, außer sie erlauben Legacy-Reindex explizit.

  Abhängigkeit:
  - Sollte nach create_core.js geladen werden.
  - Sollte nach create_preview.js geladen werden, falls Count-/Preview-Updates
    darüber laufen sollen.
  - Erwartet bevorzugt window.VectoplanCreateCore.
  - Nutzt optional:
    - window.VectoplanCreateVariantDrawer
    - window.VectoplanCreateVariantDrawerShell
    - window.VectoplanCreateVariantWorkspace
    - window.VectoplanCreateVariantState
    - window.VectoplanCreateVariantTable
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
  var LEGACY_VERSION = "0.6.0";
  var CORE_NAME = "VectoplanCreateCore";
  var PREVIEW_NAME = "VectoplanCreatePreview";
  var PAYLOAD_NAME = "VectoplanCreatePayload";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 80;

  var LEGACY_VARIANT_SOURCE = "legacy_row";
  var LEGACY_VARIABLE_SOURCE = "legacy_variable_row";

  var FALLBACK_SELECTORS = {
    form: "[data-vp-create-form], [data-create-form='true'], #vp-create-form, form[data-create-form]",

    addVariant: [
      "[data-create-add-variant='true']",
      "[data-vp-add-definition-variant='true']",
      "[data-vp-add-variant='true']"
    ].join(","),

    addVariable: [
      "[data-create-add-variable='true']",
      "[data-vp-add-variable]"
    ].join(","),

    removeRow: "[data-create-remove-row='true']",
    clearVariable: "[data-create-clear-variable='true']",

    variantTable: [
      "[data-create-variant-table='true']",
      "[data-vp-legacy-variant-table='true']"
    ].join(","),

    variantRow: [
      "[data-create-variant-row='true']",
      "[data-vp-legacy-variant-row='true']"
    ].join(","),

    variantTemplate: [
      "[data-create-variant-row-template='true']",
      "[data-vp-legacy-variant-row-template='true']"
    ].join(","),

    variableTable: [
      "[data-create-variable-table='true']",
      "[data-vp-variable-table]"
    ].join(","),

    variableRow: [
      "[data-create-variable-row='true']",
      "[data-vp-variable-row]"
    ].join(","),

    variableTemplate: "[data-create-variable-row-template='true']",

    variantCountLabel: "[data-vp-variant-count-label]",
    variableCountLabel: "[data-vp-variable-count-label]"
  };

  var DEFINITION_MANAGED_SELECTOR = [
    "[data-vp-definition-managed-variants='true']",
    "[data-vp-variant-workspace-root='true']",
    "[data-vp-variant-workspace='true']",
    "[data-vp-variant-table-root='true']",
    "[data-vp-variant-drawer-root='true']",
    "[data-vp-variant-drawer='true']"
  ].join(",");

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
    delegatedVariantEventCount: 0,
    fallbackVariantRowCount: 0,
    fallbackVariableRowCount: 0,
    skippedManagedVariantMutationCount: 0,
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

        fallbackWarn("Core runtime missing; initializing dynamic rows legacy with fallback core.");
        maybeCore = buildFallbackCore();
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

      core = coreRuntime || window[CORE_NAME] || buildFallbackCore();

      if (!core) {
        fallbackWarn("Cannot initialize dynamic rows legacy runtime.");
        return api;
      }

      selectors = Object.assign({}, FALLBACK_SELECTORS, core.selectors || {});
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

      safeSetAttribute(document.documentElement, "data-vp-create-dynamic-rows-legacy-ready", "true");
      safeSetAttribute(document.documentElement, "data-vp-create-dynamic-rows-legacy-version", LEGACY_VERSION);

      safeDispatch("vectoplan:create:dynamic-rows-legacy-ready", getState());

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

      bindOnce("create-dynamic-rows-legacy-click", bindClickControls);
      bindOnce("create-dynamic-rows-legacy-input", bindInputControls);
      bindOnce("create-dynamic-rows-legacy-state-events", bindStateEvents);
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

          var addVariantButton = target.closest(selectorFor("addVariant"));

          if (addVariantButton && form.contains(addVariantButton)) {
            if (!shouldHandleAddVariantButton(addVariantButton, form)) {
              return;
            }

            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            if (typeof event.stopImmediatePropagation === "function") {
              event.stopImmediatePropagation();
            }

            addVariantRow(form, {
              source: "button",
              button: addVariantButton
            });
            return;
          }

          var addVariableButton = target.closest(selectorFor("addVariable"));

          if (addVariableButton && form.contains(addVariableButton)) {
            if (!shouldHandleAddVariableButton(addVariableButton, form)) {
              return;
            }

            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            if (typeof event.stopImmediatePropagation === "function") {
              event.stopImmediatePropagation();
            }

            addVariableRow(form, {
              source: "button",
              button: addVariableButton
            });
            return;
          }

          var removeButton = target.closest(selectorFor("removeRow"));

          if (removeButton && form.contains(removeButton)) {
            var removableRow = resolveDynamicRow(removeButton);

            if (!removableRow) {
              return;
            }

            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            if (typeof event.stopImmediatePropagation === "function") {
              event.stopImmediatePropagation();
            }

            removeDynamicRow(removeButton, {
              source: "button"
            });
            return;
          }

          var clearVariableButton = target.closest(selectorFor("clearVariable"));

          if (clearVariableButton && form.contains(clearVariableButton)) {
            var variableRow = resolveVariableRow(clearVariableButton);

            if (!variableRow) {
              return;
            }

            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            if (typeof event.stopImmediatePropagation === "function") {
              event.stopImmediatePropagation();
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

          if (target.matches && target.matches("[name*='variants']") && !isDefinitionManagedArea(target)) {
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

          if (target.matches && target.matches(selectorFor("variableRow") + " input, " + selectorFor("variableRow") + " select, " + selectorFor("variableRow") + " textarea")) {
            updateCounts(form);
            syncPayload(form, {
              source: "variable-input"
            });
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

          if (target.matches && target.matches("[name*='variants']") && !isDefinitionManagedArea(target)) {
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

          if (target.matches && target.matches(selectorFor("variableRow") + " input, " + selectorFor("variableRow") + " select, " + selectorFor("variableRow") + " textarea")) {
            updateCounts(form);
            syncPayload(form, {
              source: "variable-change"
            });
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
      [
        "vectoplan:create:variant-state-changed",
        "vectoplan:create:variant-state-synced",
        "vectoplan:create:variant-added",
        "vectoplan:create:variant-updated",
        "vectoplan:create:variant-removed",
        "vectoplan:create:variant-table-refreshed"
      ].forEach(function (eventName) {
        document.addEventListener(eventName, function () {
          try {
            updateCounts(resolveForm());
            syncPayload(resolveForm(), {
              source: eventName
            });
          } catch (error) {
            safeWarn("Variant state event handling failed: " + eventName, error);
          }
        });
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

      document.addEventListener("vectoplan:create:wizard-ui-updated", function () {
        try {
          updateCounts(resolveForm());
        } catch (error) {
          safeWarn("Wizard UI update handling failed.", error);
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
          source: safeOptions.source || "legacy-add-button",
          button: safeOptions.button || null
        });

        if (delegated) {
          localState.delegatedVariantDrawerCount += 1;
          setStatus("Varianteneditor geöffnet.", "ok");
          return null;
        }

        if (dispatchVariantAddRequest(safeOptions)) {
          localState.delegatedVariantEventCount += 1;
          setStatus("Varianteneditor angefordert.", "ok");
          return null;
        }

        localState.skippedManagedVariantMutationCount += 1;
        setStatus("Varianteneditor nicht bereit.", "warning");
        return null;
      }

      var table = getLegacyVariantTable(safeForm);
      var template = getLegacyVariantTemplate(safeForm, table);

      if (!table) {
        setStatus("Legacy-Variantentabelle fehlt.", "error");
        return null;
      }

      var index = getNextRowIndex(safeForm, selectorFor("variantRow"));
      setCoreIndex("variantIndex", index + 1);

      var row = createRowFromTemplate(template, index, "variant");

      if (!row) {
        row = createFallbackVariantRow(index);
      }

      if (!row) {
        setStatus("Varianten-Zeile konnte nicht erzeugt werden.", "error");
        return null;
      }

      row.setAttribute("data-row-index", String(index));
      row.setAttribute("data-vp-row-source", LEGACY_VARIANT_SOURCE);
      row.setAttribute("data-vp-row-created-at", timestamp());

      table.appendChild(row);

      reindexRows(table, "variants", selectorFor("variantRow"));
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

      focusFirstInput(row);
      setStatus("Variante hinzugefügt.", "ok");

      safeDispatch("vectoplan:create:legacy-variant-row-added", {
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

      var table = getVariableTable(safeForm, safeOptions.button || null);
      var template = getVariableTemplate(safeForm, table, safeOptions.button || null);

      if (!table) {
        setStatus("Kennwert-Tabelle fehlt.", "error");
        return null;
      }

      var index = getNextRowIndex(safeForm, selectorFor("variableRow"));
      setCoreIndex("variableIndex", index + 1);

      var row = createRowFromTemplate(template, index, "variable");

      if (!row) {
        row = createFallbackVariableRow(index);
      }

      if (!row) {
        setStatus("Kennwert-Zeile konnte nicht erzeugt werden.", "error");
        return null;
      }

      row.setAttribute("data-row-index", String(index));
      row.setAttribute("data-vp-row-source", LEGACY_VARIABLE_SOURCE);
      row.setAttribute("data-vp-row-created-at", timestamp());

      table.appendChild(row);

      reindexRows(table, "variables", selectorFor("variableRow"));
      updateCounts(safeForm);
      syncPayload(safeForm, {
        source: safeOptions.source || "add-variable-row"
      });

      localState.fallbackVariableRowCount += 1;

      focusFirstInput(row);
      setStatus("Kennwert hinzugefügt.", "ok");

      safeDispatch("vectoplan:create:legacy-variable-row-added", {
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

      if (isDefinitionManagedArea(row)) {
        localState.skippedManagedVariantMutationCount += 1;
        safeDispatch("vectoplan:create:legacy-row-remove-blocked", {
          reason: "definition_managed",
          row: row
        });
        return false;
      }

      var table = row.parentElement;
      var isVariant = matches(row, selectorFor("variantRow"));
      var isVariable = matches(row, selectorFor("variableRow"));
      var form = resolveForm();

      if (isVariant && isDefaultVariantRow(row)) {
        setStatus("Die Default-Variante bleibt fix.", "warning");

        safeDispatch("vectoplan:create:legacy-row-remove-blocked", {
          reason: "default_variant",
          row: row
        });

        return false;
      }

      if (isVariable && countRows(table, selectorFor("variableRow")) <= 1) {
        return clearVariableRow(row, {
          source: safeOptions.source || "remove-last-variable-as-clear"
        });
      }

      var rowIndex = parseInt(row.getAttribute("data-row-index") || "-1", 10);

      row.remove();
      localState.removeCount += 1;
      localState.lastAction = "removeDynamicRow";

      if (table && isVariant) {
        reindexRows(table, "variants", selectorFor("variantRow"));
      }

      if (table && isVariable) {
        reindexRows(table, "variables", selectorFor("variableRow"));
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

      safeDispatch("vectoplan:create:legacy-row-removed", {
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

      var fields = qsa("input, select, textarea", row);

      fields.forEach(function (input) {
        try {
          if (input.type === "hidden") {
            return;
          }

          if (input.tagName && input.tagName.toLowerCase() === "select") {
            input.selectedIndex = 0;
          } else if (input.type === "checkbox" || input.type === "radio") {
            input.checked = false;
          } else if (input.type === "file") {
            input.value = "";
          } else {
            input.value = "";
          }

          dispatchNativeEvent(input, "input");
          dispatchNativeEvent(input, "change");
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

      safeDispatch("vectoplan:create:legacy-variable-row-cleared", {
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

      getLegacyVariantTables(safeForm).forEach(function (variantTable) {
        reindexRows(variantTable, "variants", selectorFor("variantRow"));
      });

      getVariableTables(safeForm).forEach(function (variableTable) {
        reindexRows(variableTable, "variables", selectorFor("variableRow"));
      });

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

      safeDispatch("vectoplan:create:legacy-rows-reindexed", {
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

      if (prefix === "variants" && isDefinitionManagedArea(table) && table.getAttribute("data-vp-allow-legacy-reindex") !== "true") {
        localState.skippedManagedVariantMutationCount += 1;
        return false;
      }

      var rows = qsa(rowSelector, table).filter(function (row) {
        return prefix !== "variants" || !isDefinitionManagedArea(row) || row.getAttribute("data-vp-allow-legacy-reindex") === "true";
      });

      rows.forEach(function (row, index) {
        try {
          row.setAttribute("data-row-index", String(index));

          var fields = qsa("[name]", row);

          fields.forEach(function (field) {
            try {
              if (field.getAttribute("data-vp-no-legacy-reindex") === "true") {
                return;
              }

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
      if (!row || (isDefinitionManagedArea(row) && row.getAttribute("data-vp-allow-legacy-reindex") !== "true")) {
        return false;
      }

      var checkbox = qs("[data-create-field='variant_is_default'], [name$='[is_default]']", row);
      var label = qs("[data-vp-default-label]", row);
      var removeButton = qs(selectorFor("removeRow"), row);
      var staticButton = qs("[data-create-static-disabled='true']", row);
      var slugInput = qs("[data-create-field='variant_slug'], [data-create-field='variant_id'], [name$='[slug]'], [name$='[variant_id]']", row);
      var nameInput = qs("[data-create-field='variant_name'], [name$='[name]']", row);

      row.setAttribute("data-row-index", String(index));

      if (checkbox) {
        if (index === 0 || checkbox.hasAttribute("data-create-default-locked")) {
          if (checkbox.type === "checkbox" || checkbox.type === "radio") {
            checkbox.checked = true;
          }

          checkbox.value = "true";
          checkbox.setAttribute("data-create-default-locked", "true");
          checkbox.setAttribute("aria-readonly", "true");
        } else {
          checkbox.value = checkbox.checked ? "true" : "false";
        }
      }

      if (label) {
        label.textContent = checkbox && (checkbox.checked || checkbox.value === "true") ? "Default" : "Nein";
      }

      if (slugInput) {
        if (index === 0) {
          slugInput.value = "default";
          slugInput.setAttribute("readonly", "readonly");
          slugInput.setAttribute("aria-readonly", "true");
        } else if (!slugInput.value || slugInput.getAttribute("data-create-auto-slug") === "true") {
          slugInput.value = slugify(nameInput && nameInput.value ? nameInput.value : "variant_" + (index + 1));
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

      var clearButton = qs(selectorFor("clearVariable"), row);
      var removeButton = qs(selectorFor("removeRow"), row);

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

      var rows = qsa(selectorFor("variantRow"), safeForm).filter(function (row) {
        return !isDefinitionManagedArea(row) || row.getAttribute("data-vp-allow-legacy-reindex") === "true";
      });

      rows.forEach(function (row, index) {
        try {
          var nameInput = qs("[data-create-field='variant_name'], [name$='[name]']", row);
          var slugInput = qs("[data-create-field='variant_slug'], [data-create-field='variant_id'], [name$='[slug]'], [name$='[variant_id]']", row);

          if (!slugInput) {
            return;
          }

          if (index === 0) {
            slugInput.value = "default";
            return;
          }

          if (slugInput.getAttribute("data-create-auto-slug") === "true" || !slugInput.value) {
            var value = nameInput ? nameInput.value : "";
            slugInput.value = slugify(value || "variant_" + (index + 1));
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
      var label = qs(selectorFor("variantCountLabel"));
      var count = 0;

      if (window.VectoplanCreateVariantState && typeof window.VectoplanCreateVariantState.getVariants === "function") {
        var variants = window.VectoplanCreateVariantState.getVariants();
        count = Array.isArray(variants) ? variants.length : 0;
      }

      if (!count && window.VectoplanCreateVariantTable && typeof window.VectoplanCreateVariantTable.getRows === "function") {
        count = window.VectoplanCreateVariantTable.getRows().length || 0;
      }

      if (!count && safeForm) {
        count = qsa(selectorFor("variantRow"), safeForm).filter(function (row) {
          return row.getAttribute("data-vp-variant-row-template") !== "true" &&
            row.getAttribute("data-vp-row-template") !== "true";
        }).length;
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
        if (!field || field.type === "hidden") {
          return false;
        }

        if (field.type === "checkbox" || field.type === "radio") {
          return !!field.checked;
        }

        if (field.type === "file") {
          return !!(field.files && field.files.length);
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

      var button = safeOptions.button || null;

      if (button && button.getAttribute("data-vp-force-legacy") === "true") {
        return false;
      }

      if (button && button.getAttribute("data-create-force-legacy") === "true") {
        return false;
      }

      if (hasDefinitionManagedWorkspace(form)) {
        return true;
      }

      if (window.VectoplanCreateVariantDrawer && typeof window.VectoplanCreateVariantDrawer.open === "function") {
        return true;
      }

      if (window.VectoplanCreateVariantDrawerShell && typeof window.VectoplanCreateVariantDrawerShell.open === "function") {
        return true;
      }

      if (window.VectoplanCreateVariantState && typeof window.VectoplanCreateVariantState.getState === "function") {
        return true;
      }

      if (button && (
        button.getAttribute("data-vp-use-variant-runtime") === "true" ||
        button.getAttribute("data-create-use-variant-runtime") === "true"
      )) {
        return true;
      }

      return false;
    } catch (error) {
      safeWarn("Variant creation delegation check failed.", error);
      return false;
    }
  }

  function openVariantDrawer(options) {
    try {
      var context = getVariantContext();
      var source = options && options.source ? options.source : "legacy-dynamic-rows";

      if (window.VectoplanCreateVariantDrawer && typeof window.VectoplanCreateVariantDrawer.open === "function") {
        window.VectoplanCreateVariantDrawer.open({
          mode: "create",
          source: source,
          context: context
        });
        return true;
      }

      if (window.VectoplanCreateVariantDrawerShell && typeof window.VectoplanCreateVariantDrawerShell.open === "function") {
        window.VectoplanCreateVariantDrawerShell.open({
          mode: "create",
          source: source,
          context: context
        });
        return true;
      }

      if (window.VectoplanCreateDefinitionsRuntime && typeof window.VectoplanCreateDefinitionsRuntime.openVariantDrawer === "function") {
        window.VectoplanCreateDefinitionsRuntime.openVariantDrawer({
          mode: "create",
          source: source,
          context: context
        });
        return true;
      }

      if (window.VectoplanCreateVariantWorkspace && typeof window.VectoplanCreateVariantWorkspace.openEditor === "function") {
        window.VectoplanCreateVariantWorkspace.openEditor("legacy_add_variant");
        dispatchVariantAddRequest(options);
        return true;
      }

      return false;
    } catch (error) {
      safeWarn("Open variant drawer failed.", error);
      return false;
    }
  }

  function dispatchVariantAddRequest(options) {
    try {
      var context = getVariantContext();
      var event = safeDispatch("vectoplan:create:variant-add-requested", {
        mode: "create",
        source: options && options.source ? options.source : "legacy-dynamic-rows",
        context: context
      }, {
        cancelable: true
      });

      safeDispatch("vectoplan:create:variant-drawer-open-requested", {
        mode: "create",
        source: options && options.source ? options.source : "legacy-dynamic-rows",
        context: context
      });

      return !!event;
    } catch (error) {
      safeWarn("Variant add request dispatch failed.", error);
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
        domain: normalizeToken(getFieldValue(form, "domain"), "hochbau"),
        category: normalizeToken(getFieldValue(form, "category"), "bloecke"),
        subcategory: normalizeToken(getFieldValue(form, "subcategory"), "basis"),
        object_kind: normalizeToken(getFieldValue(form, "object_kind"), "cell_block"),
        objectKind: normalizeToken(getFieldValue(form, "object_kind"), "cell_block"),
        family_profile_id: getFieldValue(form, "family_profile_id") || "",
        familyProfileId: getFieldValue(form, "family_profile_id") || "",
        variant_profile_id: getFieldValue(form, "variant_profile_id") || "",
        variantProfileId: getFieldValue(form, "variant_profile_id") || ""
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
      var safeForm = form || resolveForm();
      var source = options && options.source ? options.source : "dynamic-rows-legacy";

      if (payloadRuntime && typeof payloadRuntime.syncVariantRuntimeToForm === "function") {
        payloadRuntime.syncVariantRuntimeToForm(safeForm, {
          source: source
        });
      }

      if (payloadRuntime && typeof payloadRuntime.syncUploadsRuntimeToForm === "function") {
        payloadRuntime.syncUploadsRuntimeToForm(safeForm, {
          source: source
        });
      }

      return !!payloadRuntime;
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

  function shouldHandleAddVariantButton(button, form) {
    try {
      if (!button || !form || !form.contains(button)) {
        return false;
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function shouldHandleAddVariableButton(button, form) {
    try {
      if (!button || !form || !form.contains(button)) {
        return false;
      }

      if (isDefinitionManagedArea(button)) {
        return false;
      }

      var scope = button.closest("[data-create-variables-section='true'], [data-vp-variable-editor], [data-vp-create-section='technical'], [data-create-section='technical']") || form;
      var table = qs(selectorFor("variableTable"), scope);

      return !!table;
    } catch (error) {
      return false;
    }
  }

  function getLegacyVariantTables(form) {
    try {
      return qsa(selectorFor("variantTable"), form || document).filter(function (table) {
        return !isDefinitionManagedArea(table) || table.getAttribute("data-vp-allow-legacy-reindex") === "true";
      });
    } catch (error) {
      return [];
    }
  }

  function getLegacyVariantTable(form) {
    try {
      return getLegacyVariantTables(form)[0] || null;
    } catch (error) {
      return null;
    }
  }

  function getLegacyVariantTemplate(form, table) {
    try {
      var scope = table ? table.parentElement || form : form;
      var template = qs(selectorFor("variantTemplate"), scope) || qs(selectorFor("variantTemplate"), form);

      if (template && isDefinitionManagedArea(template) && template.getAttribute("data-vp-allow-legacy-reindex") !== "true") {
        return null;
      }

      return template;
    } catch (error) {
      return null;
    }
  }

  function getVariableTables(form) {
    try {
      return qsa(selectorFor("variableTable"), form || document).filter(function (table) {
        return !isDefinitionManagedArea(table);
      });
    } catch (error) {
      return [];
    }
  }

  function getVariableTable(form, button) {
    try {
      var scope = button
        ? button.closest("[data-create-variables-section='true'], [data-vp-variable-editor], [data-vp-create-section='technical'], [data-create-section='technical']")
        : null;

      if (scope) {
        var scopedTable = qs(selectorFor("variableTable"), scope);

        if (scopedTable) {
          return scopedTable;
        }
      }

      return getVariableTables(form)[0] || null;
    } catch (error) {
      return null;
    }
  }

  function getVariableTemplate(form, table, button) {
    try {
      var scope = button
        ? button.closest("[data-create-variables-section='true'], [data-vp-variable-editor], [data-vp-create-section='technical'], [data-create-section='technical']")
        : null;

      return qs(selectorFor("variableTemplate"), scope || table && table.parentElement || form) ||
        qs(selectorFor("variableTemplate"), form);
    } catch (error) {
      return null;
    }
  }

  function createRowFromTemplate(template, index, type) {
    try {
      if (!template) {
        return null;
      }

      var html = getTemplateHtml(template);

      if (!html) {
        return null;
      }

      html = html.split("__index__").join(String(index));

      var fragment = htmlToFragment(html);
      var selector = type === "variant" ? selectorFor("variantRow") : selectorFor("variableRow");
      var row = qs(selector, fragment) || fragment.firstElementChild;

      return row || null;
    } catch (error) {
      safeWarn("Create row from template failed.", error);
      return null;
    }
  }

  function createFallbackVariantRow(index) {
    try {
      var row = document.createElement("div");
      var isDefault = index === 0;
      row.className = "vp-create-variant-row";
      row.setAttribute("data-create-variant-row", "true");
      row.setAttribute("data-vp-legacy-variant-row", "true");
      row.setAttribute("data-row-index", String(index));

      row.innerHTML = [
        '<label class="vp-create-field vp-create-field--compact">',
        '<span class="vp-create-sr-only">Variant Name</span>',
        '<input class="vp-create-input" name="variants[' + index + '][name]" type="text" value="' + (isDefault ? "Standard" : "") + '" placeholder="Variante" data-create-field="variant_name" autocomplete="off" />',
        '</label>',
        '<label class="vp-create-field vp-create-field--compact">',
        '<span class="vp-create-sr-only">Variant ID</span>',
        '<input class="vp-create-input vp-create-input--mono" name="variants[' + index + '][slug]" type="text" value="' + (isDefault ? "default" : "") + '" placeholder="variant_' + (index + 1) + '" data-create-field="variant_slug" autocomplete="off" ' + (isDefault ? 'readonly aria-readonly="true"' : 'data-create-auto-slug="true"') + ' />',
        '</label>',
        '<input type="hidden" name="variants[' + index + '][is_default]" value="' + (isDefault ? "true" : "false") + '" data-create-field="variant_is_default" />',
        '<div class="vp-create-row-action">',
        isDefault
          ? '<button class="vp-create-button vp-create-button--ghost" type="button" disabled aria-disabled="true" data-create-static-disabled="true">Fix</button>'
          : '<button class="vp-create-button vp-create-button--ghost" type="button" data-create-remove-row="true">Entfernen</button>',
        '</div>'
      ].join("");

      return row;
    } catch (error) {
      return null;
    }
  }

  function createFallbackVariableRow(index) {
    try {
      var row = document.createElement("div");
      row.className = "vp-create-variable-row";
      row.setAttribute("data-create-variable-row", "true");
      row.setAttribute("data-vp-variable-row", "");
      row.setAttribute("data-row-index", String(index));
      row.setAttribute("role", "row");

      row.innerHTML = [
        '<label class="vp-create-field vp-create-field--compact">',
        '<span class="vp-create-sr-only">Kennwert-Key</span>',
        '<input class="vp-create-input vp-create-input--mono" name="variables[' + index + '][key]" type="text" placeholder="extensions.custom.value" data-create-field="variable_key" data-vp-variable-key autocomplete="off" spellcheck="false" />',
        '</label>',
        '<label class="vp-create-field vp-create-field--compact">',
        '<span class="vp-create-sr-only">Wert</span>',
        '<input class="vp-create-input" name="variables[' + index + '][value]" type="text" placeholder="Wert" data-create-field="variable_value" data-vp-variable-value autocomplete="off" />',
        '</label>',
        '<label class="vp-create-field vp-create-field--compact">',
        '<span class="vp-create-sr-only">Einheit</span>',
        '<input class="vp-create-input vp-create-input--mono" name="variables[' + index + '][unit]" type="text" placeholder="optional" list="create-technical-unit-suggestions" data-create-field="variable_unit" data-vp-variable-unit autocomplete="off" spellcheck="false" />',
        '</label>',
        '<label class="vp-create-field vp-create-field--compact">',
        '<span class="vp-create-sr-only">Beschreibung</span>',
        '<input class="vp-create-input" name="variables[' + index + '][description]" type="text" placeholder="Beschreibung" data-create-field="variable_description" data-vp-variable-description autocomplete="off" />',
        '</label>',
        '<div class="vp-create-row-action">',
        index === 0
          ? '<button class="vp-create-button vp-create-button--ghost" type="button" data-create-clear-variable="true">Leeren</button>'
          : '<button class="vp-create-button vp-create-button--ghost" type="button" data-create-remove-row="true">Entfernen</button>',
        '</div>'
      ].join("");

      return row;
    } catch (error) {
      return null;
    }
  }

  function hasDefinitionManagedWorkspace(form) {
    try {
      return !!qs(DEFINITION_MANAGED_SELECTOR, form || document);
    } catch (error) {
      return false;
    }
  }

  function isDefinitionManagedArea(node) {
    try {
      if (!node || !node.closest) {
        return false;
      }

      return !!node.closest(DEFINITION_MANAGED_SELECTOR);
    } catch (error) {
      return false;
    }
  }

  function resolveDynamicRow(buttonOrRow) {
    try {
      if (!buttonOrRow) {
        return null;
      }

      if (matches(buttonOrRow, selectorFor("variantRow")) || matches(buttonOrRow, selectorFor("variableRow"))) {
        return buttonOrRow;
      }

      if (buttonOrRow.closest) {
        return buttonOrRow.closest(selectorFor("variantRow") + ", " + selectorFor("variableRow"));
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

      if (matches(buttonOrRow, selectorFor("variableRow"))) {
        return buttonOrRow;
      }

      if (buttonOrRow.closest) {
        return buttonOrRow.closest(selectorFor("variableRow"));
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

      var checkbox = qs("[data-create-field='variant_is_default'], [name$='[is_default]']", row);

      if (checkbox && (checkbox.checked || checkbox.value === "true") && checkbox.hasAttribute("data-create-default-locked")) {
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
      var rows = safeForm ? qsa(rowSelector, safeForm) : [];
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

  function countRows(root, rowSelector) {
    try {
      return root ? qsa(rowSelector, root).length : 0;
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
        ? core.qs(selectorFor("form"))
        : document.querySelector(FALLBACK_SELECTORS.form);
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
        delegatedVariantEventCount: localState.delegatedVariantEventCount,
        fallbackVariantRowCount: localState.fallbackVariantRowCount,
        fallbackVariableRowCount: localState.fallbackVariableRowCount,
        skippedManagedVariantMutationCount: localState.skippedManagedVariantMutationCount,
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

  function matches(node, selector) {
    try {
      return !!(node && node.matches && selector && node.matches(selector));
    } catch (error) {
      return false;
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

  function safeDispatch(eventName, detail, options) {
    try {
      if (core && typeof core.dispatch === "function") {
        return core.dispatch(eventName, detail || {}, options || {});
      }

      var event = new CustomEvent(eventName, {
        bubbles: !(options && options.bubbles === false),
        cancelable: !!(options && options.cancelable),
        detail: detail || {}
      });

      document.dispatchEvent(event);
      return event;
    } catch (error) {
      fallbackWarn("Dispatch failed: " + eventName, error);
      return null;
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

  function getTemplateHtml(template) {
    try {
      if (core && typeof core.getTemplateHtml === "function") {
        return core.getTemplateHtml(template);
      }

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
    } catch (error) {
      return "";
    }
  }

  function htmlToFragment(html) {
    try {
      if (core && typeof core.htmlToFragment === "function") {
        return core.htmlToFragment(html);
      }

      var template = document.createElement("template");
      template.innerHTML = String(html || "").trim();
      return template.content;
    } catch (error) {
      return document.createDocumentFragment();
    }
  }

  function focusFirstInput(root) {
    try {
      if (core && typeof core.focusFirstInput === "function") {
        return core.focusFirstInput(root);
      }

      var input = qs("input:not([type='hidden']):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])", root);

      if (input && typeof input.focus === "function") {
        input.focus({ preventScroll: true });
        return true;
      }

      return false;
    } catch (error) {
      return false;
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

  function setCoreIndex(key, value) {
    try {
      if (core && core.state) {
        core.state[key] = Math.max(parseInt(core.state[key] || "1", 10) || 1, parseInt(value || "1", 10) || 1);
      }
    } catch (error) {
      /* no-op */
    }
  }

  function buildFallbackCore() {
    try {
      return {
        selectors: FALLBACK_SELECTORS,
        classes: {},
        state: {
          variantIndex: 1,
          variableIndex: 1
        },
        qs: function (selector, root) {
          return (root || document).querySelector(selector);
        },
        qsa: function (selector, root) {
          return Array.prototype.slice.call((root || document).querySelectorAll(selector));
        },
        safeSetAttribute: safeSetAttribute,
        dispatch: safeDispatch,
        dispatchNativeEvent: dispatchNativeEvent,
        bindOnce: bindOnce,
        registerModule: function () {},
        refreshContext: function () {},
        getFieldValue: getFieldValue,
        normalizeToken: normalizeToken,
        slugify: slugify,
        getTemplateHtml: getTemplateHtml,
        htmlToFragment: htmlToFragment,
        focusFirstInput: focusFirstInput,
        cssEscape: cssEscape,
        setStatus: function () {},
        warn: fallbackWarn,
        error: fallbackWarn
      };
    } catch (error) {
      return null;
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
    dispatchVariantAddRequest: dispatchVariantAddRequest,

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