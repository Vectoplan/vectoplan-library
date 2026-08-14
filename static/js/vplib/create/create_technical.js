/* VPLIB Create · Step 7: exact per-variant CAD dimensions. */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateTechnical";
  var VERSION = "3.0.0";
  var ROOT_SELECTOR = "[data-vp-technical-controller='dimensions']";
  var DIMENSION_FIELDS = [
    {
      key: "dimensions.width_mm",
      label: "Breite",
      description: "Tatsächliche Außenbreite für CAD, Mengen und Platzierung.",
      unit: "mm",
      required: true
    },
    {
      key: "dimensions.height_mm",
      label: "Höhe",
      description: "Tatsächliche Außenhöhe des Bauteils oder Objekts.",
      unit: "mm",
      required: true
    },
    {
      key: "dimensions.depth_mm",
      label: "Tiefe",
      description: "Tatsächliche Außentiefe des Bauteils oder Objekts.",
      unit: "mm",
      required: true
    },
    {
      key: "dimensions.thickness_mm",
      label: "Dicke / Stärke",
      description: "Optionale reale Material- oder Bauteildicke.",
      unit: "mm",
      required: false
    },
    {
      key: "dimensions.length_mm",
      label: "Länge",
      description: "Optionale reale Länge für längsorientierte Bauteile.",
      unit: "mm",
      required: false
    }
  ];
  var DIMENSION_KEYS = DIMENSION_FIELDS.map(function (field) { return field.key; });
  var PATTERN_FIELDS = [
    {
      key: "cad.cut_pattern_id",
      label: "Schnittschraffur",
      description: "Vektor-Schraffur für geschnittene Bauteilflächen.",
      valueType: "string",
      defaultValue: "solid"
    },
    {
      key: "cad.surface_pattern_id",
      label: "Oberflächenmuster",
      description: "Vektor-Muster für ungeschnittene Oberflächen.",
      valueType: "string",
      defaultValue: "none"
    },
    {
      key: "cad.pattern_scale",
      label: "Mustermaßstab",
      description: "Skalierungsfaktor für Schnitt- und Oberflächenmuster.",
      valueType: "number",
      defaultValue: 1
    },
    {
      key: "cad.pattern_rotation_deg",
      label: "Musterdrehung",
      description: "Drehwinkel des Musters in Grad relativ zum Bauteil.",
      valueType: "number",
      defaultValue: 0
    },
    {
      key: "cad.pattern_foreground_color",
      label: "Muster-Vordergrundfarbe",
      description: "Vordergrundfarbe der CAD-Schraffur als Hex-Farbwert.",
      valueType: "string",
      defaultValue: "#202020"
    },
    {
      key: "cad.pattern_background_color",
      label: "Muster-Hintergrundfarbe",
      description: "Hintergrundfarbe der CAD-Schraffur als Hex-Farbwert.",
      valueType: "string",
      defaultValue: "#FFFFFF"
    }
  ];
  var PATTERN_KEYS = PATTERN_FIELDS.map(function (field) { return field.key; });
  var MANAGED_KEYS = DIMENSION_KEYS.concat(PATTERN_KEYS);

  var state = {
    root: null,
    units: [],
    currentVariantId: "default",
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

  function unitCatalog() {
    var script = query("#vp-create-definitions-json");
    var parsed = script ? parseJson(script.textContent, {}) : {};
    var context = window.VectoplanCreateContext || {};
    var catalogs = context.definitionCatalogs || context.definition_catalogs || {};
    var units = parsed.units || catalogs.units || [];
    return Array.isArray(units) ? units : [];
  }

  function unitId(unit) {
    return clean(unit && (unit.id || unit.value || unit.key));
  }

  function unitLabel(unit) {
    var symbol = clean(unit && unit.symbol);
    var label = clean(unit && (unit.label || unit.title || unitId(unit)));
    return symbol && symbol !== label ? label + " (" + symbol + ")" : label;
  }

  function isLengthUnit(unit) {
    var quantity = clean(unit && (unit.quantity_kind || unit.quantityKind)).toLowerCase();
    var id = unitId(unit).toLowerCase();
    return unit && unit.active !== false && (quantity === "length" || ["mm", "cm", "dm", "m", "in", "ft"].indexOf(id) !== -1);
  }

  function lengthUnits() {
    var units = state.units.filter(isLengthUnit);
    if (units.length) {
      return units;
    }
    return [
      {id: "mm", label: "Millimeter", symbol: "mm"},
      {id: "cm", label: "Zentimeter", symbol: "cm"},
      {id: "m", label: "Meter", symbol: "m"}
    ];
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

  function variantId(variant) {
    return clean(variant && (variant.variant_id || variant.variantId || variant.id)) || "default";
  }

  function variantLabel(variant) {
    return clean(variant && (variant.label || variant.name)) || variantId(variant);
  }

  function findVariant(id) {
    var variants = readVariants();
    var normalized = clean(id);
    return variants.find(function (variant) {
      return variantId(variant) === normalized;
    }) || variants[0] || null;
  }

  function selectedVariant() {
    return findVariant(state.currentVariantId);
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

  function existingAdditionalKeys(variant) {
    var source = variant && (variant.additional_field_keys || variant.additionalFieldKeys || variant.additional_field_keys_json);
    var keys = Array.isArray(source) ? source.slice() : parseJson(source, []);
    if (!Array.isArray(keys)) {
      keys = [];
    }
    return Array.from(new Set(keys.map(clean).filter(function (key) {
      return key && MANAGED_KEYS.indexOf(key) === -1;
    })));
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

  function persistVariant(variant, values) {
    if (!variant) {
      return;
    }
    var id = variantId(variant);
    var additionalKeys = existingAdditionalKeys(variant);
    var api = getVariantApi();
    state.syncing = true;

    if (api && typeof api.updateVariant === "function") {
      api.updateVariant(id, {
        definition_values: values,
        additional_field_keys: additionalKeys,
        definition_managed: true
      }, {
        source: "technical_dimensions",
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
        item.additional_field_keys = additionalKeys;
        item.additionalFieldKeys = additionalKeys.slice();
      });
      writeVariantsFallback(variants);
    }

    state.syncing = false;
    renderPayloadFields();
    dispatch("vectoplan:create:technical-dimensions-changed", {
      source: "technical_dimensions",
      variantId: id,
      values: clone(values, {})
    });
    dispatch("vectoplan:create:technical-patterns-changed", {
      source: "technical_dimensions",
      variantId: id,
      values: clone(values, {})
    });
  }

  function numberValue(rawValue) {
    if (clean(rawValue) === "") {
      return null;
    }
    var value = Number(String(rawValue).replace(",", "."));
    return Number.isFinite(value) && value >= 0 ? value : null;
  }

  function setValue(key, rawValue) {
    var variant = selectedVariant();
    if (!variant || DIMENSION_KEYS.indexOf(key) === -1) {
      return;
    }
    var values = variantValues(variant);
    values[key] = numberValue(rawValue);
    var units = values["technical.units"];
    if (!units || typeof units !== "object" || Array.isArray(units)) {
      units = {};
    }
    if (!clean(units[key])) {
      units[key] = "mm";
    }
    values["technical.units"] = units;
    persistVariant(variant, values);
  }

  function setUnit(key, unit) {
    var variant = selectedVariant();
    if (!variant || DIMENSION_KEYS.indexOf(key) === -1) {
      return;
    }
    var values = variantValues(variant);
    var units = values["technical.units"];
    if (!units || typeof units !== "object" || Array.isArray(units)) {
      units = {};
    }
    units[key] = clean(unit) || "mm";
    values["technical.units"] = units;
    persistVariant(variant, values);
  }

  function patternField(key) {
    return PATTERN_FIELDS.find(function (field) { return field.key === key; }) || null;
  }

  function patternValue(field, rawValue) {
    if (!field) {
      return null;
    }
    if (field.valueType === "number") {
      var parsed = Number(String(rawValue).replace(",", "."));
      return Number.isFinite(parsed) ? parsed : field.defaultValue;
    }
    return clean(rawValue) || field.defaultValue;
  }

  function setPatternValue(key, rawValue) {
    var variant = selectedVariant();
    var field = patternField(key);
    if (!variant || !field) {
      return;
    }
    var values = variantValues(variant);
    values[key] = patternValue(field, rawValue);
    persistVariant(variant, values);
  }

  function populateVariantSelect() {
    var select = query("[data-vp-technical-variant-select]", state.root);
    var summary = query("[data-vp-technical-variant-summary]", state.root);
    var variants = readVariants();
    if (!select) {
      return;
    }
    if (!variants.length) {
      variants = [{variant_id: "default", label: "Standard", is_default: true, definition_values: {}}];
    }
    if (!variants.some(function (variant) { return variantId(variant) === state.currentVariantId; })) {
      state.currentVariantId = variantId(variants[0]);
    }
    select.innerHTML = "";
    variants.forEach(function (variant) {
      var option = document.createElement("option");
      option.value = variantId(variant);
      option.textContent = variantLabel(variant) + (variant.is_default || variant.isDefault ? " · Default" : "");
      option.selected = option.value === state.currentVariantId;
      select.appendChild(option);
    });
    if (summary) {
      summary.textContent = variants.length + (variants.length === 1 ? " Variante" : " Varianten");
    }
  }

  function appendUnitOptions(select, selectedUnit) {
    var selectedFound = false;
    select.innerHTML = "";
    lengthUnits().forEach(function (unit) {
      var option = document.createElement("option");
      option.value = unitId(unit);
      option.textContent = unitLabel(unit);
      option.selected = option.value === selectedUnit;
      selectedFound = selectedFound || option.selected;
      select.appendChild(option);
    });
    if (selectedUnit && !selectedFound) {
      var custom = document.createElement("option");
      custom.value = selectedUnit;
      custom.textContent = selectedUnit;
      custom.selected = true;
      select.appendChild(custom);
    }
  }

  function createDimensionRow(field, values) {
    var units = values["technical.units"] && typeof values["technical.units"] === "object"
      ? values["technical.units"]
      : {};
    var selectedUnit = clean(units[field.key]) || field.unit;
    var row = document.createElement("div");
    row.className = "vp-create-technical-cad__row vp-create-technical-cad__row--dimension";
    row.setAttribute("role", "row");
    row.setAttribute("data-vp-technical-row", "true");
    row.setAttribute("data-vp-technical-dimension-key", field.key);

    var label = document.createElement("div");
    label.className = "vp-create-technical-cad__dimension-label";
    var title = document.createElement("strong");
    title.textContent = field.label;
    if (field.required) {
      var required = document.createElement("span");
      required.className = "vp-create-required";
      required.textContent = " *";
      title.appendChild(required);
    }
    var key = document.createElement("small");
    key.textContent = field.key;
    label.appendChild(title);
    label.appendChild(key);

    var input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.step = "any";
    input.className = "vp-create-input";
    input.value = values[field.key] === null || typeof values[field.key] === "undefined"
      ? ""
      : String(values[field.key]);
    input.placeholder = field.required ? "z. B. 1000" : "optional";
    input.setAttribute("data-vp-technical-dimension-value", field.key);
    input.setAttribute("aria-label", field.label + " als reales CAD-Maß");

    var unitSelect = document.createElement("select");
    unitSelect.className = "vp-create-select";
    unitSelect.setAttribute("data-vp-technical-dimension-unit", field.key);
    unitSelect.setAttribute("aria-label", "Einheit für " + field.label);
    appendUnitOptions(unitSelect, selectedUnit);

    var description = document.createElement("div");
    description.className = "vp-create-technical-cad__description";
    description.textContent = field.description;

    row.appendChild(label);
    row.appendChild(input);
    row.appendChild(unitSelect);
    row.appendChild(description);
    return row;
  }

  function renderRows(values) {
    var rows = query("[data-vp-technical-rows]", state.root);
    var count = query("[data-vp-technical-dimension-count]", state.root);
    if (!rows) {
      return;
    }
    rows.innerHTML = "";
    DIMENSION_FIELDS.forEach(function (field) {
      rows.appendChild(createDimensionRow(field, values));
    });
    if (count) {
      count.textContent = DIMENSION_FIELDS.length + " Maßangaben";
    }
  }

  function renderPatternControls(values) {
    PATTERN_FIELDS.forEach(function (field) {
      var input = query("[data-vp-technical-pattern-value='" + field.key + "']", state.root);
      if (!input) {
        return;
      }
      var value = values[field.key];
      if (value === null || typeof value === "undefined" || value === "") {
        value = field.defaultValue;
      }
      input.value = String(value);
    });
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
      DIMENSION_FIELDS.forEach(function (field) {
        var value = values[field.key];
        if (value === null || typeof value === "undefined" || value === "") {
          return;
        }
        var fields = {
          key: field.key,
          value: value,
          unit: clean(units[field.key]) || field.unit,
          description: field.description,
          value_type: "number",
          scope: "variant",
          variant_id: variantId(variant)
        };
        Object.keys(fields).forEach(function (fieldName) {
          var input = document.createElement("input");
          input.type = "hidden";
          input.name = "variables[" + index + "][" + fieldName + "]";
          input.value = String(fields[fieldName]);
          container.appendChild(input);
        });
        index += 1;
      });
      PATTERN_FIELDS.forEach(function (field) {
        var value = values[field.key];
        if (value === null || typeof value === "undefined" || value === "") {
          value = field.defaultValue;
        }
        var fields = {
          key: field.key,
          value: value,
          unit: field.key === "cad.pattern_rotation_deg" ? "deg" : "",
          description: field.description,
          value_type: field.valueType,
          scope: "variant",
          variant_id: variantId(variant)
        };
        Object.keys(fields).forEach(function (fieldName) {
          var input = document.createElement("input");
          input.type = "hidden";
          input.name = "variables[" + index + "][" + fieldName + "]";
          input.value = String(fields[fieldName]);
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
    status.textContent = DIMENSION_FIELDS.length + " CAD-Maße · " + PATTERN_FIELDS.length + " Musterwerte";
    status.setAttribute("data-vp-technical-status", "ready");
    state.root.setAttribute("data-vp-technical-ready", "true");
  }

  function renderVariant() {
    populateVariantSelect();
    var values = variantValues(selectedVariant());
    renderRows(values);
    renderPatternControls(values);
    renderPayloadFields();
    updateStatus();
  }

  function onChange(event) {
    var target = event.target;
    if (!target || !state.root.contains(target)) {
      return;
    }
    if (target.matches("[data-vp-technical-variant-select]")) {
      state.currentVariantId = clean(target.value) || "default";
      renderVariant();
      return;
    }
    var valueKey = clean(target.getAttribute("data-vp-technical-dimension-value"));
    if (valueKey) {
      setValue(valueKey, target.value);
      return;
    }
    var unitKey = clean(target.getAttribute("data-vp-technical-dimension-unit"));
    if (unitKey) {
      setUnit(unitKey, target.value);
      return;
    }
    var patternKey = clean(target.getAttribute("data-vp-technical-pattern-value"));
    if (patternKey) {
      setPatternValue(patternKey, target.value);
    }
  }

  function bindEvents() {
    state.root.addEventListener("change", onChange);
    state.root.addEventListener("input", function (event) {
      if (event.target && event.target.matches("[data-vp-technical-dimension-value], [data-vp-technical-pattern-value]")) {
        onChange(event);
      }
    });
    [
      "vectoplan:create:variant-state-synced",
      "vectoplan:create:variant-state-changed",
      "vectoplan:create:variant-added",
      "vectoplan:create:variant-removed",
      "vectoplan:create:variant-applied"
    ].forEach(function (eventName) {
      document.addEventListener(eventName, function (event) {
        if (state.syncing || (event.detail && event.detail.source === "technical_dimensions")) {
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
    state.units = unitCatalog();
    bindEvents();
    state.initialized = true;
    renderVariant();
    document.documentElement.setAttribute("data-vp-create-technical-ready", "true");
    dispatch("vectoplan:create:technical-ready", {
      component: GLOBAL_NAME,
      version: VERSION,
      dimensionCount: DIMENSION_FIELDS.length,
      patternFieldCount: PATTERN_FIELDS.length,
      unitCount: lengthUnits().length
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
        dimensionCount: DIMENSION_FIELDS.length,
        dimensionKeys: DIMENSION_KEYS.slice(),
        patternFieldCount: PATTERN_FIELDS.length,
        patternKeys: PATTERN_KEYS.slice(),
        unitCount: lengthUnits().length
      };
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, {once: true});
  } else {
    initialize();
  }
})();
