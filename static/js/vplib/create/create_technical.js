/* VPLIB Create · Step 5: exact per-variant technical/CAD values. */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateTechnical";
  var VERSION = "1.0.0";
  var ROOT_SELECTOR = "[data-vp-technical-controller='catalog']";
  var QUICK_KEYS = [
    "dimensions.width_mm",
    "dimensions.height_mm",
    "dimensions.depth_mm",
    "dimensions.thickness_mm",
    "dimensions.length_mm"
  ];
  var SYSTEM_KEYS = {
    "variant.variant_id": true,
    "variant.label": true,
    "variant.description": true,
    "material.type": true,
    "technical.units": true
  };
  var GROUP_LABELS = {
    acoustic: "Akustik",
    commercial: "Kaufmännisch",
    concrete: "Beton",
    connection: "Anschluss",
    context: "Kontext",
    dimensions: "Reale Abmessungen",
    dynamic: "Dynamik",
    exposure: "Exposition",
    fire: "Brandschutz",
    flow: "Durchfluss",
    manufacturer: "Hersteller",
    material: "Material",
    module: "Modul",
    product: "Produkt",
    reinforcement: "Bewehrung",
    render: "Darstellung",
    road: "Straße",
    sanitary: "Sanitär",
    structural: "Tragwerk",
    surface: "Oberfläche",
    thermal: "Wärmeschutz",
    usage: "Nutzung",
    wall_masonry: "Mauerwerk"
  };

  var state = {
    root: null,
    variables: [],
    variablesByKey: {},
    units: [],
    materials: [],
    currentVariantId: "default",
    renderKeys: [],
    syncing: false,
    initialized: false
  };

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

  function clean(value) {
    return value === null || typeof value === "undefined" ? "" : String(value).trim();
  }

  function clone(value, fallback) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      return fallback;
    }
  }

  function parseJson(value, fallback) {
    try {
      var parsed = JSON.parse(value || "");
      return parsed === null || typeof parsed === "undefined" ? fallback : parsed;
    } catch (error) {
      return fallback;
    }
  }

  function catalogData() {
    var script = query("#vp-create-definitions-json");
    var parsed = script ? parseJson(script.textContent, {}) : {};
    var context = window.VectoplanCreateContext || {};
    var catalogs = context.definitionCatalogs || context.definition_catalogs || {};

    return {
      variables: parsed.variables || catalogs.variables || [],
      units: parsed.units || catalogs.units || [],
      materials: parsed.materials || catalogs.materials || []
    };
  }

  function variableKey(variable) {
    return clean(variable && (variable.key || variable.variable_key || variable.id));
  }

  function variableLabel(variable) {
    return clean(variable && (variable.label || variable.title || variableKey(variable))) || variableKey(variable);
  }

  function variableGroup(variable) {
    return clean(variable && variable.group) || "other";
  }

  function variableType(variable) {
    return clean(variable && (variable.value_type || variable.valueType || variable.type)) || "string";
  }

  function variableWidget(variable) {
    return clean(variable && variable.widget) || "input";
  }

  function variableOptions(variable) {
    var options = variable && (variable.options || variable.values || variable.enum_values);
    return Array.isArray(options) ? options : [];
  }

  function optionValue(option) {
    if (option && typeof option === "object") {
      return clean(option.value !== undefined ? option.value : (option.id !== undefined ? option.id : option.key));
    }
    return clean(option);
  }

  function optionLabel(option) {
    if (option && typeof option === "object") {
      return clean(option.label || option.title || optionValue(option));
    }
    return clean(option);
  }

  function unitId(unit) {
    return clean(unit && (unit.id || unit.value || unit.key));
  }

  function unitLabel(unit) {
    var symbol = clean(unit && unit.symbol);
    var label = clean(unit && (unit.label || unit.title || unitId(unit)));
    return symbol && symbol !== label ? label + " (" + symbol + ")" : label;
  }

  function materialId(material) {
    return clean(material && (material.id || material.value || material.key));
  }

  function materialLabel(material) {
    return clean(material && (material.label || material.title || materialId(material)));
  }

  function isTechnicalVariable(variable) {
    var key = variableKey(variable);
    if (!key || SYSTEM_KEYS[key]) {
      return false;
    }
    if (variableGroup(variable) === "variant" || variableGroup(variable) === "documents") {
      return false;
    }
    if (variableWidget(variable) === "document_list") {
      return false;
    }
    return variable.active !== false && variable.enabled !== false;
  }

  function sortVariables(left, right) {
    var groupCompare = (GROUP_LABELS[variableGroup(left)] || variableGroup(left))
      .localeCompare(GROUP_LABELS[variableGroup(right)] || variableGroup(right), "de");
    if (groupCompare) {
      return groupCompare;
    }
    return variableLabel(left).localeCompare(variableLabel(right), "de");
  }

  function getVariantApi() {
    return window.VectoplanCreateVariantState || null;
  }

  function readVariants() {
    var api = getVariantApi();
    if (api && typeof api.getVariants === "function") {
      var apiVariants = api.getVariants();
      if (Array.isArray(apiVariants) && apiVariants.length) {
        return apiVariants;
      }
    }

    var field = query("[name='definition_variants_json']");
    var parsed = field ? parseJson(field.value, []) : [];
    return Array.isArray(parsed) ? parsed : [];
  }

  function findVariant(variantId) {
    var variants = readVariants();
    var id = clean(variantId);
    return variants.find(function (variant) {
      return clean(variant.variant_id || variant.variantId || variant.id) === id;
    }) || variants[0] || null;
  }

  function variantId(variant) {
    return clean(variant && (variant.variant_id || variant.variantId || variant.id)) || "default";
  }

  function variantLabel(variant) {
    return clean(variant && (variant.label || variant.name)) || variantId(variant);
  }

  function variantValues(variant) {
    if (!variant) {
      return {};
    }
    if (variant.definition_values && typeof variant.definition_values === "object") {
      return clone(variant.definition_values, {});
    }
    if (variant.definitionValues && typeof variant.definitionValues === "object") {
      return clone(variant.definitionValues, {});
    }
    return parseJson(variant.definition_values_json || variant.definitionValuesJson, {});
  }

  function selectedVariant() {
    return findVariant(state.currentVariantId);
  }

  function dispatch(name, detail) {
    try {
      document.dispatchEvent(new CustomEvent(name, {detail: detail || {}, bubbles: false}));
    } catch (error) {
      /* no-op */
    }
  }

  function writeVariantsFallback(variants) {
    var field = query("[name='definition_variants_json']");
    if (!field) {
      return;
    }
    field.value = JSON.stringify(variants);
    field.dispatchEvent(new Event("input", {bubbles: true}));
    field.dispatchEvent(new Event("change", {bubbles: true}));
  }

  function persistVariant(variant, values, additionalKeys) {
    var id = variantId(variant);
    var api = getVariantApi();
    var nextKeys = Array.from(new Set((additionalKeys || []).filter(Boolean)));
    state.syncing = true;

    if (api && typeof api.updateVariant === "function") {
      api.updateVariant(id, {
        definition_values: values,
        additional_field_keys: nextKeys,
        definition_managed: true
      }, {
        source: "technical_cad",
        forceEvent: true
      });
    } else {
      var variants = readVariants();
      variants.forEach(function (item) {
        if (variantId(item) !== id) {
          return;
        }
        item.definition_values = values;
        item.definitionValues = values;
        item.definition_values_json = JSON.stringify(values);
        item.additional_field_keys = nextKeys;
        item.additionalFieldKeys = nextKeys.slice();
      });
      writeVariantsFallback(variants);
    }

    state.syncing = false;
    renderPayloadFields();
    dispatch("vectoplan:create:technical-values-changed", {
      source: "technical_cad",
      variantId: id,
      values: clone(values, {})
    });
  }

  function additionalKeysFor(variant, values) {
    var existing = variant && (variant.additional_field_keys || variant.additionalFieldKeys);
    var keys = Array.isArray(existing) ? existing.slice() : [];
    Object.keys(values || {}).forEach(function (key) {
      if (isTechnicalVariable(state.variablesByKey[key])) {
        keys.push(key);
      }
    });
    return Array.from(new Set(keys.filter(function (key) {
      return !!state.variablesByKey[key] && isTechnicalVariable(state.variablesByKey[key]);
    })));
  }

  function setValue(key, rawValue) {
    var variant = selectedVariant();
    var variable = state.variablesByKey[key];
    if (!variant || !variable) {
      return;
    }

    var values = variantValues(variant);
    var value = normalizeTypedValue(rawValue, variable);
    var units = values["technical.units"];
    if (!units || typeof units !== "object" || Array.isArray(units)) {
      units = {};
    }
    if (!clean(units[key])) {
      units[key] = clean(variable.unit || variable.unit_id);
    }
    values["technical.units"] = units;
    values[key] = value;
    persistVariant(variant, values, additionalKeysFor(variant, values));
  }

  function setUnit(key, unit) {
    var variant = selectedVariant();
    if (!variant || !state.variablesByKey[key]) {
      return;
    }
    var values = variantValues(variant);
    var units = values["technical.units"];
    if (!units || typeof units !== "object" || Array.isArray(units)) {
      units = {};
    }
    units[key] = clean(unit);
    values["technical.units"] = units;
    persistVariant(variant, values, additionalKeysFor(variant, values));
  }

  function setMaterial(material) {
    var variant = selectedVariant();
    if (!variant) {
      return;
    }
    var values = variantValues(variant);
    values["material.type"] = clean(material);
    persistVariant(variant, values, additionalKeysFor(variant, values));
  }

  function removeValue(key) {
    var variant = selectedVariant();
    if (!variant || QUICK_KEYS.indexOf(key) !== -1) {
      return;
    }
    var values = variantValues(variant);
    values[key] = null;
    var units = values["technical.units"];
    if (units && typeof units === "object") {
      delete units[key];
      values["technical.units"] = units;
    }
    state.renderKeys = state.renderKeys.filter(function (item) { return item !== key; });
    persistVariant(variant, values, additionalKeysFor(variant, values).filter(function (item) {
      return item !== key;
    }));
    renderVariant();
  }

  function normalizeTypedValue(value, variable) {
    var type = variableType(variable);
    if (type === "number" || type === "integer" || type === "money") {
      if (clean(value) === "") {
        return null;
      }
      var numberValue = Number(String(value).replace(",", "."));
      if (!Number.isFinite(numberValue)) {
        return null;
      }
      return type === "integer" ? Math.round(numberValue) : numberValue;
    }
    if (type === "boolean" || type === "bool") {
      if (clean(value) === "") {
        return null;
      }
      return value === true || value === "true" || value === "1";
    }
    return clean(value);
  }

  function populateVariantSelect() {
    var select = query("[data-vp-technical-variant-select]", state.root);
    var summary = query("[data-vp-technical-variant-summary]", state.root);
    var variants = readVariants();
    if (!select) {
      return;
    }

    if (!variants.length) {
      variants = [{variant_id: "default", label: "Standard", definition_values: {}}];
    }
    if (!variants.some(function (variant) { return variantId(variant) === state.currentVariantId; })) {
      state.currentVariantId = variantId(variants[0]);
    }

    select.innerHTML = "";
    variants.forEach(function (variant) {
      var option = document.createElement("option");
      option.value = variantId(variant);
      option.textContent = variantLabel(variant) + (variant.is_default || variant.isDefault ? " · Standard" : "");
      option.selected = option.value === state.currentVariantId;
      select.appendChild(option);
    });
    if (summary) {
      summary.textContent = variants.length + (variants.length === 1 ? " Variante" : " Varianten");
    }
  }

  function populateMaterialSelect() {
    var select = query("[data-vp-technical-material-select]", state.root);
    if (!select || select.options.length > 1) {
      return;
    }
    state.materials.forEach(function (material) {
      var option = document.createElement("option");
      option.value = materialId(material);
      option.textContent = materialLabel(material);
      select.appendChild(option);
    });
  }

  function populateAddSelect() {
    var select = query("[data-vp-technical-add-select]", state.root);
    if (!select) {
      return;
    }
    var selected = {};
    state.renderKeys.forEach(function (key) { selected[key] = true; });
    select.innerHTML = "";
    var empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "Kennwert auswählen";
    select.appendChild(empty);

    var groups = {};
    state.variables.filter(isTechnicalVariable).sort(sortVariables).forEach(function (variable) {
      var key = variableKey(variable);
      if (selected[key]) {
        return;
      }
      var group = variableGroup(variable);
      if (!groups[group]) {
        groups[group] = document.createElement("optgroup");
        groups[group].label = GROUP_LABELS[group] || group;
        select.appendChild(groups[group]);
      }
      var option = document.createElement("option");
      option.value = key;
      option.textContent = variableLabel(variable);
      groups[group].appendChild(option);
    });
  }

  function appendVariableOptions(select, selectedKey) {
    var groups = {};
    state.variables.filter(isTechnicalVariable).sort(sortVariables).forEach(function (variable) {
      var group = variableGroup(variable);
      if (!groups[group]) {
        groups[group] = document.createElement("optgroup");
        groups[group].label = GROUP_LABELS[group] || group;
        select.appendChild(groups[group]);
      }
      var option = document.createElement("option");
      option.value = variableKey(variable);
      option.textContent = variableLabel(variable);
      option.selected = option.value === selectedKey;
      groups[group].appendChild(option);
    });
  }

  function appendUnitOptions(select, selectedUnit) {
    var blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "Ohne Einheit";
    select.appendChild(blank);
    state.units.forEach(function (unit) {
      var option = document.createElement("option");
      option.value = unitId(unit);
      option.textContent = unitLabel(unit);
      option.selected = option.value === selectedUnit;
      select.appendChild(option);
    });
  }

  function createValueControl(variable, value) {
    var control;
    var options = variableOptions(variable);
    var type = variableType(variable);
    var widget = variableWidget(variable);

    if (options.length) {
      control = document.createElement("select");
      var blank = document.createElement("option");
      blank.value = "";
      blank.textContent = "Bitte auswählen";
      control.appendChild(blank);
      options.forEach(function (item) {
        var option = document.createElement("option");
        option.value = optionValue(item);
        option.textContent = optionLabel(item);
        option.selected = String(value === null || value === undefined ? "" : value) === option.value;
        control.appendChild(option);
      });
    } else if (type === "boolean" || type === "bool" || widget === "checkbox") {
      control = document.createElement("select");
      [["", "Nicht festgelegt"], ["true", "Ja"], ["false", "Nein"]].forEach(function (pair) {
        var option = document.createElement("option");
        option.value = pair[0];
        option.textContent = pair[1];
        option.selected = String(value === null || value === undefined ? "" : value) === pair[0];
        control.appendChild(option);
      });
    } else if (widget === "textarea" || type === "text") {
      control = document.createElement("textarea");
      control.rows = 2;
      control.value = value === null || value === undefined ? "" : String(value);
    } else {
      control = document.createElement("input");
      control.type = (type === "number" || type === "integer" || type === "money" || widget === "number")
        ? "number"
        : (widget === "date" ? "date" : (widget === "url" ? "url" : "text"));
      if (control.type === "number") {
        control.step = type === "integer" ? "1" : "any";
        control.min = variable.validation && variable.validation.min !== undefined
          ? String(variable.validation.min)
          : "0";
      }
      control.value = value === null || value === undefined ? "" : String(value);
    }

    control.className = control.tagName === "SELECT" ? "vp-create-select" : "vp-create-input";
    control.setAttribute("data-vp-technical-value", "true");
    control.setAttribute("aria-label", "Wert: " + variableLabel(variable));
    return control;
  }

  function createRow(key, values) {
    var variable = state.variablesByKey[key];
    if (!variable) {
      return null;
    }
    var units = values["technical.units"] && typeof values["technical.units"] === "object"
      ? values["technical.units"]
      : {};
    var selectedUnit = clean(units[key] || variable.unit || variable.unit_id);

    var row = document.createElement("div");
    row.className = "vp-create-technical-cad__row";
    row.setAttribute("role", "row");
    row.setAttribute("data-vp-technical-row", "true");
    row.setAttribute("data-vp-technical-key", key);

    var keySelect = document.createElement("select");
    keySelect.className = "vp-create-select";
    keySelect.setAttribute("data-vp-technical-key-select", "true");
    keySelect.setAttribute("aria-label", "Kennwert auswählen");
    appendVariableOptions(keySelect, key);
    if (QUICK_KEYS.indexOf(key) !== -1) {
      keySelect.disabled = true;
      keySelect.title = "Fester Basiskennwert";
    }

    var valueControl = createValueControl(variable, values[key]);

    var unitSelect = document.createElement("select");
    unitSelect.className = "vp-create-select";
    unitSelect.setAttribute("data-vp-technical-unit", "true");
    unitSelect.setAttribute("aria-label", "Einheit für " + variableLabel(variable));
    appendUnitOptions(unitSelect, selectedUnit);

    var description = document.createElement("div");
    description.className = "vp-create-technical-cad__description";
    description.textContent = clean(variable.description) || "Keine Beschreibung hinterlegt.";
    description.title = variableKey(variable);

    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "vp-create-button vp-create-button--ghost";
    remove.setAttribute("data-vp-technical-remove", "true");
    remove.textContent = QUICK_KEYS.indexOf(key) !== -1 ? "Basiswert" : "Entfernen";
    remove.disabled = QUICK_KEYS.indexOf(key) !== -1;

    row.appendChild(keySelect);
    row.appendChild(valueControl);
    row.appendChild(unitSelect);
    row.appendChild(description);
    row.appendChild(remove);
    return row;
  }

  function computeRenderKeys(variant, values) {
    var keys = QUICK_KEYS.slice();
    var additional = additionalKeysFor(variant, values);
    additional.forEach(function (key) {
      if (
        keys.indexOf(key) === -1
        && values[key] !== null
        && values[key] !== undefined
        && values[key] !== ""
      ) {
        keys.push(key);
      }
    });
    state.renderKeys.forEach(function (key) {
      if (keys.indexOf(key) === -1 && state.variablesByKey[key]) {
        keys.push(key);
      }
    });
    return keys.filter(function (key) { return !!state.variablesByKey[key]; });
  }

  function renderRows(variant, values) {
    var rows = query("[data-vp-technical-rows]", state.root);
    var empty = query("[data-vp-technical-empty]", state.root);
    var count = query("[data-vp-technical-value-count]", state.root);
    if (!rows) {
      return;
    }
    state.renderKeys = computeRenderKeys(variant, values);
    rows.innerHTML = "";
    state.renderKeys.forEach(function (key) {
      var row = createRow(key, values);
      if (row) {
        rows.appendChild(row);
      }
    });
    if (empty) {
      empty.hidden = state.renderKeys.length > 0;
    }
    if (count) {
      count.textContent = state.renderKeys.length + (state.renderKeys.length === 1 ? " Kennwert" : " Kennwerte");
    }
    populateAddSelect();
  }

  function renderMaterial(variant, values) {
    var select = query("[data-vp-technical-material-select]", state.root);
    var description = query("[data-vp-technical-material-description]", state.root);
    var value = clean(values["material.type"]);
    if (select) {
      select.value = value;
      if (select.value !== value && value) {
        var custom = document.createElement("option");
        custom.value = value;
        custom.textContent = value;
        custom.selected = true;
        select.appendChild(custom);
      }
    }
    var material = state.materials.find(function (item) { return materialId(item) === value; });
    if (description) {
      description.textContent = material
        ? clean(material.description)
        : "Material aus dem zentralen Katalog auswählen.";
    }
  }

  function renderVariant() {
    populateVariantSelect();
    var variant = selectedVariant();
    var values = variantValues(variant);
    renderMaterial(variant, values);
    renderRows(variant, values);
    renderPayloadFields();
    updateStatus();
  }

  function renderPayloadFields() {
    var container = query("[data-vp-technical-payload-fields]", state.root);
    if (!container) {
      return;
    }
    container.innerHTML = "";
    var index = 0;
    readVariants().forEach(function (variant) {
      var values = variantValues(variant);
      var units = values["technical.units"] && typeof values["technical.units"] === "object"
        ? values["technical.units"]
        : {};
      Object.keys(values).forEach(function (key) {
        var variable = state.variablesByKey[key];
        if (!isTechnicalVariable(variable) || values[key] === null || values[key] === "") {
          return;
        }
        var fields = {
          key: key,
          value: values[key],
          unit: clean(units[key] || variable.unit || variable.unit_id),
          description: clean(variable.description),
          value_type: variableType(variable),
          scope: "variant",
          variant_id: variantId(variant)
        };
        Object.keys(fields).forEach(function (fieldName) {
          var input = document.createElement("input");
          input.type = "hidden";
          input.name = "variables[" + index + "][" + fieldName + "]";
          input.value = fields[fieldName] === null || fields[fieldName] === undefined
            ? ""
            : String(fields[fieldName]);
          container.appendChild(input);
        });
        index += 1;
      });
    });
    container.setAttribute("data-vp-technical-payload-count", String(index));
  }

  function updateStatus() {
    var status = query("[data-vp-technical-status]", state.root);
    if (!status) {
      return;
    }
    status.textContent = state.variables.length + " Kennwerte · " + state.units.length + " Einheiten";
    status.setAttribute("data-vp-technical-status", "ready");
    state.root.setAttribute("data-vp-technical-ready", "true");
  }

  function onChange(event) {
    var target = event.target;
    if (!target || !state.root.contains(target)) {
      return;
    }
    if (target.matches("[data-vp-technical-variant-select]")) {
      state.currentVariantId = clean(target.value) || "default";
      state.renderKeys = [];
      renderVariant();
      return;
    }
    if (target.matches("[data-vp-technical-material-select]")) {
      setMaterial(target.value);
      renderMaterial(selectedVariant(), variantValues(selectedVariant()));
      return;
    }
    var row = target.closest("[data-vp-technical-row='true']");
    if (!row) {
      return;
    }
    var key = clean(row.getAttribute("data-vp-technical-key"));
    if (target.matches("[data-vp-technical-value]")) {
      setValue(key, target.type === "checkbox" ? target.checked : target.value);
    } else if (target.matches("[data-vp-technical-unit]")) {
      setUnit(key, target.value);
    } else if (target.matches("[data-vp-technical-key-select]")) {
      var nextKey = clean(target.value);
      if (nextKey && nextKey !== key) {
        removeValue(key);
        if (state.renderKeys.indexOf(nextKey) === -1) {
          state.renderKeys.push(nextKey);
        }
        renderVariant();
      }
    }
  }

  function onClick(event) {
    var target = event.target;
    if (!target || !state.root.contains(target)) {
      return;
    }
    var add = target.closest("[data-vp-technical-add-button]");
    if (add) {
      event.preventDefault();
      var select = query("[data-vp-technical-add-select]", state.root);
      var key = select ? clean(select.value) : "";
      if (key && state.renderKeys.indexOf(key) === -1) {
        state.renderKeys.push(key);
        renderVariant();
        var added = query("[data-vp-technical-row='true'][data-vp-technical-key='" + cssEscape(key) + "']", state.root);
        if (added) {
          added.scrollIntoView({block: "nearest"});
          var control = query("[data-vp-technical-value]", added);
          if (control) {
            control.focus();
          }
        }
      }
      return;
    }
    var remove = target.closest("[data-vp-technical-remove]");
    if (remove) {
      event.preventDefault();
      var row = remove.closest("[data-vp-technical-row='true']");
      if (row) {
        removeValue(clean(row.getAttribute("data-vp-technical-key")));
      }
    }
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(value);
    }
    return String(value).replace(/["\\]/g, "\\$&");
  }

  function bindEvents() {
    state.root.addEventListener("change", onChange);
    state.root.addEventListener("input", function (event) {
      if (event.target && event.target.matches("[data-vp-technical-value]")) {
        onChange(event);
      }
    });
    state.root.addEventListener("click", onClick);
    [
      "vectoplan:create:variant-state-synced",
      "vectoplan:create:variant-state-changed",
      "vectoplan:create:variant-added",
      "vectoplan:create:variant-removed"
    ].forEach(function (eventName) {
      document.addEventListener(eventName, function (event) {
        if (state.syncing || (event.detail && event.detail.source === "technical_cad")) {
          return;
        }
        window.setTimeout(renderVariant, 0);
      });
    });
  }

  function initialize() {
    state.root = query(ROOT_SELECTOR);
    if (!state.root || state.initialized) {
      return false;
    }
    var catalogs = catalogData();
    state.variables = (Array.isArray(catalogs.variables) ? catalogs.variables : [])
      .filter(function (variable) { return !!variableKey(variable); });
    state.variables.forEach(function (variable) {
      state.variablesByKey[variableKey(variable)] = variable;
    });
    state.units = Array.isArray(catalogs.units) ? catalogs.units : [];
    state.materials = Array.isArray(catalogs.materials) ? catalogs.materials : [];
    populateMaterialSelect();
    bindEvents();
    state.initialized = true;
    renderVariant();
    document.documentElement.setAttribute("data-vp-create-technical-ready", "true");
    dispatch("vectoplan:create:technical-ready", {
      component: GLOBAL_NAME,
      version: VERSION,
      variableCount: state.variables.length,
      unitCount: state.units.length,
      materialCount: state.materials.length
    });
    return true;
  }

  window[GLOBAL_NAME] = {
    version: VERSION,
    initialize: initialize,
    render: renderVariant,
    getState: function () {
      return {
        currentVariantId: state.currentVariantId,
        variableCount: state.variables.length,
        unitCount: state.units.length,
        materialCount: state.materials.length,
        renderKeys: state.renderKeys.slice()
      };
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, {once: true});
  } else {
    initialize();
  }
})();
