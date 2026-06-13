/* services/vectoplan-library/static/library_admin/js/create_variant_summary.js */
/* -----------------------------------------------------------------------------
 * VECTOPLAN Library · Create Wizard · Variant Summary
 *
 * Zweck:
 * - Zentrale Summary-/Kurzwerte-Schicht für definition-managed Varianten.
 * - Baut kompakte Kurzwerte aus:
 *     - Variant Profile `summary_fields`
 *     - Variant Profile `ui.cards.title_field`
 *     - Variant Profile `ui.cards.subtitle_fields`
 *     - Variant Profile `ui.cards.badge_fields`
 *     - Variable Definitions
 *     - Unit Definitions
 *     - Material-/Optionskatalogen
 * - Aktualisiert Drawer-Summary live.
 * - Liefert kompakte Summary-Strings für Variantenliste und Hidden Fields.
 *
 * Architekturregel:
 * - Diese Datei entscheidet nicht, welche Felder fachlich existieren.
 * - Sie liest nur Profile, Variables, Units und Values.
 * - Sie validiert keine Werte.
 * - Sie schreibt keine Varianten in den State.
 * - Sie erzeugt keine VPLIB-Packages.
 *
 * Wichtiger Fix in dieser Fassung:
 * - updateRowSummary() schreibt Hidden Summary Inputs still.
 * - Keine nativen input/change Events mehr bei Summary-Sync.
 * - Summary-Updates sind idempotent.
 * - updateTableSummaries() besitzt Reentrancy-/Schedule-Schutz.
 * - Summary-Events werden markiert und nicht als User-Input behandelt.
 *
 * Global:
 * - window.VectoplanCreateVariantSummary
 *
 * Benötigt, falls vorhanden:
 * - window.VectoplanCreateVariantUtils
 * - window.VectoplanCreateVariantProfiles
 * - window.VectoplanCreateVariantState
 * - window.VectoplanCreateVariantFieldRenderer
 * - window.VectoplanCreateDefinitions
 *
 * Events:
 * - dispatch: vectoplan:create:variant-summary-ready
 * - dispatch: vectoplan:create:variant-summary-built
 * - dispatch: vectoplan:create:variant-drawer-summary-updated
 * - dispatch: vectoplan:create:variant-table-summary-updated
 *
 * - listen: vectoplan:create:variant-values-changed
 * - listen: vectoplan:create:variant-fields-rendered
 * - listen: vectoplan:create:variant-profile-resolved
 * - listen: vectoplan:create:variant-profile-loaded
 * - listen: vectoplan:create:variant-drawer-opened
 * - listen: vectoplan:create:variant-added
 * - listen: vectoplan:create:variant-updated
 * - listen: vectoplan:create:variant-state-changed
 * -------------------------------------------------------------------------- */

(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateVariantSummary";
  var COMPONENT_NAME = "VECTOPLAN Create Variant Summary";
  var COMPONENT_VERSION = "0.1.1";
  var READY_ATTR = "data-vp-create-variant-summary-ready";

  var DRAWER_SELECTOR = "[data-vp-variant-drawer-root='true'], [data-vp-variant-drawer='true']";
  var TABLE_SELECTOR = "[data-vp-variant-table-root='true'], [data-vp-variant-table='true'], [data-create-variant-table='true']";
  var ROW_SELECTOR = "[data-vp-variant-row='true'], [data-create-variant-row='true']";

  if (window[GLOBAL_NAME] && window[GLOBAL_NAME].__version) {
    try {
      document.documentElement.setAttribute(READY_ATTR, "true");
    } catch (alreadyReadyError) {
      /* no-op */
    }

    return;
  }

  /* ---------------------------------------------------------------------------
   * Utils / fallback
   * ------------------------------------------------------------------------ */

  function getUtils() {
    if (window.VectoplanCreateVariantUtils && window.VectoplanCreateVariantUtils.__version) {
      return window.VectoplanCreateVariantUtils;
    }

    return fallbackUtils;
  }

  var fallbackUtils = {
    warn: function (message, error) {
      try {
        if (window.console && typeof window.console.warn === "function") {
          window.console.warn("[" + COMPONENT_NAME + "] " + String(message || ""), error || "");
        }
      } catch (consoleError) {
        /* no-op */
      }
    },

    info: function (message, payload) {
      try {
        if (window.console && typeof window.console.info === "function") {
          window.console.info("[" + COMPONENT_NAME + "] " + String(message || ""), payload || "");
        }
      } catch (consoleError) {
        /* no-op */
      }
    },

    toArray: function (value) {
      try {
        if (!value) {
          return [];
        }

        if (Array.isArray(value)) {
          return value.slice();
        }

        if (typeof value.length === "number" && typeof value !== "string") {
          return Array.prototype.slice.call(value);
        }

        return [value];
      } catch (error) {
        return [];
      }
    },

    qs: function (selector, root) {
      try {
        return (root || document).querySelector(selector);
      } catch (error) {
        return null;
      }
    },

    qsa: function (selector, root) {
      try {
        return Array.prototype.slice.call((root || document).querySelectorAll(selector));
      } catch (error) {
        return [];
      }
    },

    closest: function (node, selector) {
      try {
        return node && node.closest ? node.closest(selector) : null;
      } catch (error) {
        return null;
      }
    },

    attr: function (node, name, fallback) {
      try {
        var value = node ? node.getAttribute(name) : null;
        return value === null || value === undefined ? (fallback || "") : value;
      } catch (error) {
        return fallback || "";
      }
    },

    setAttr: function (node, name, value) {
      try {
        if (!node || !name) {
          return false;
        }

        var next = value === null || value === undefined ? "" : String(value);

        if (node.getAttribute(name) === next) {
          return false;
        }

        if (value === null || value === undefined) {
          node.removeAttribute(name);
        } else {
          node.setAttribute(name, next);
        }

        return true;
      } catch (error) {
        return false;
      }
    },

    getValue: function (node, fallback) {
      try {
        if (!node) {
          return fallback || "";
        }

        if (node.type === "checkbox") {
          return node.checked ? "true" : "false";
        }

        if ("value" in node) {
          return node.value || fallback || "";
        }

        return node.textContent || fallback || "";
      } catch (error) {
        return fallback || "";
      }
    },

    setValue: function (node, value, dispatchEvents) {
      try {
        if (!node) {
          return false;
        }

        var next = value === null || value === undefined ? "" : String(value);

        if (node.value === next) {
          return false;
        }

        node.value = next;

        if (node.setAttribute) {
          node.setAttribute("data-vp-programmatic-event-source", COMPONENT_NAME);
          node.setAttribute("data-vp-last-summary-sync", String(Date.now()));
        }

        if (dispatchEvents) {
          fallbackUtils.dispatchNative(node, "input");
          fallbackUtils.dispatchNative(node, "change");
        }

        return true;
      } catch (error) {
        return false;
      }
    },

    setText: function (node, value) {
      try {
        if (!node) {
          return false;
        }

        var next = value === null || value === undefined ? "" : String(value);

        if (node.textContent === next) {
          return false;
        }

        node.textContent = next;
        return true;
      } catch (error) {
        return false;
      }
    },

    setHidden: function (node, hidden) {
      try {
        if (!node) {
          return false;
        }

        var nextHidden = !!hidden;

        if (node.hidden === nextHidden) {
          return false;
        }

        node.hidden = nextHidden;

        if (nextHidden) {
          node.setAttribute("hidden", "");
          node.setAttribute("aria-hidden", "true");
        } else {
          node.removeAttribute("hidden");
          node.removeAttribute("aria-hidden");
        }

        return true;
      } catch (error) {
        return false;
      }
    },

    empty: function (node) {
      try {
        if (!node) {
          return false;
        }

        while (node.firstChild) {
          node.removeChild(node.firstChild);
        }

        return true;
      } catch (error) {
        return false;
      }
    },

    createElement: function (tagName, attributes, children) {
      try {
        var node = document.createElement(tagName || "div");
        var attrs = attributes || {};

        Object.keys(attrs).forEach(function (key) {
          var value = attrs[key];

          if (key === "class") {
            node.className = String(value || "");
          } else if (key === "text") {
            node.textContent = String(value || "");
          } else if (key === "html") {
            node.innerHTML = String(value || "");
          } else if (key === "dataset" && value && typeof value === "object") {
            Object.keys(value).forEach(function (dataKey) {
              node.dataset[dataKey] = String(value[dataKey] || "");
            });
          } else if (key === "attrs" && value && typeof value === "object") {
            Object.keys(value).forEach(function (attrKey) {
              node.setAttribute(attrKey, String(value[attrKey]));
            });
          } else if (key in node) {
            try {
              node[key] = value;
            } catch (innerError) {
              node.setAttribute(key, String(value));
            }
          } else {
            node.setAttribute(key, String(value));
          }
        });

        fallbackUtils.toArray(children).forEach(function (child) {
          if (child === null || child === undefined) {
            return;
          }

          if (typeof child === "string") {
            node.appendChild(document.createTextNode(child));
          } else {
            node.appendChild(child);
          }
        });

        return node;
      } catch (error) {
        return document.createElement("div");
      }
    },

    bool: function (value, fallback) {
      try {
        if (typeof value === "boolean") {
          return value;
        }

        var text = String(value === null || value === undefined ? "" : value).trim().toLowerCase();

        if (["true", "1", "yes", "ja", "on", "ok"].indexOf(text) !== -1) {
          return true;
        }

        if (["false", "0", "no", "nein", "off", ""].indexOf(text) !== -1) {
          return false;
        }

        return !!fallback;
      } catch (error) {
        return !!fallback;
      }
    },

    intValue: function (value, fallback) {
      try {
        var parsed = parseInt(value, 10);
        return isNaN(parsed) ? (fallback || 0) : parsed;
      } catch (error) {
        return fallback || 0;
      }
    },

    floatValue: function (value, fallback) {
      try {
        var parsed = parseFloat(value);
        return isNaN(parsed) ? (fallback === undefined ? null : fallback) : parsed;
      } catch (error) {
        return fallback === undefined ? null : fallback;
      }
    },

    trim: function (value) {
      try {
        return String(value || "").trim();
      } catch (error) {
        return "";
      }
    },

    lower: function (value) {
      try {
        return String(value || "").trim().toLowerCase();
      } catch (error) {
        return "";
      }
    },

    safeJsonParse: function (value, fallback) {
      try {
        if (value && typeof value === "object") {
          return value;
        }

        var text = String(value || "").trim();

        if (!text) {
          return fallback;
        }

        return JSON.parse(text);
      } catch (error) {
        return fallback;
      }
    },

    safeJsonStringify: function (value, fallback, spacing) {
      try {
        return JSON.stringify(value, null, spacing || 0);
      } catch (error) {
        return fallback || "";
      }
    },

    deepClone: function (value, fallback) {
      try {
        return JSON.parse(JSON.stringify(value));
      } catch (error) {
        return fallback === undefined ? value : fallback;
      }
    },

    safeMerge: function () {
      try {
        var output = {};
        var args = Array.prototype.slice.call(arguments);

        args.forEach(function (object) {
          if (!object || typeof object !== "object") {
            return;
          }

          Object.keys(object).forEach(function (key) {
            output[key] = object[key];
          });
        });

        return output;
      } catch (error) {
        return {};
      }
    },

    dispatchDocument: function (eventName, detail, options) {
      try {
        var event = new CustomEvent(eventName, {
          bubbles: !(options && options.bubbles === false),
          cancelable: !!(options && options.cancelable),
          detail: detail || {}
        });

        document.dispatchEvent(event);
        return event;
      } catch (error) {
        return null;
      }
    },

    dispatchNative: function (node, eventName) {
      try {
        if (!node) {
          return false;
        }

        if (node.setAttribute) {
          node.setAttribute("data-vp-programmatic-event", String(eventName));
          node.setAttribute("data-vp-programmatic-event-source", COMPONENT_NAME);
        }

        node.dispatchEvent(new Event(eventName, {
          bubbles: true,
          cancelable: false
        }));

        window.setTimeout(function () {
          try {
            if (node && node.getAttribute && node.getAttribute("data-vp-programmatic-event") === String(eventName)) {
              node.removeAttribute("data-vp-programmatic-event");
              node.removeAttribute("data-vp-programmatic-event-source");
            }
          } catch (cleanupError) {
            /* no-op */
          }
        }, 0);

        return true;
      } catch (error) {
        return false;
      }
    },

    normalizeDefinitions: function (raw) {
      try {
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
          object_kinds: fallbackUtils.toArray(defs.object_kinds || defs.objectKinds),
          family_profiles: fallbackUtils.toArray(defs.family_profiles || defs.familyProfiles),
          variant_profiles: fallbackUtils.toArray(defs.variant_profiles || defs.variantProfiles),
          variables: fallbackUtils.toArray(defs.variables),
          units: fallbackUtils.toArray(defs.units),
          materials: fallbackUtils.toArray(defs.materials),
          document_types: fallbackUtils.toArray(defs.document_types || defs.documentTypes),
          profile_bindings: fallbackUtils.toArray(defs.profile_bindings || defs.profileBindings)
        };
      } catch (error) {
        return {
          object_kinds: [],
          family_profiles: [],
          variant_profiles: [],
          variables: [],
          units: [],
          materials: [],
          document_types: [],
          profile_bindings: []
        };
      }
    },

    indexBy: function (items, keyName) {
      try {
        var output = {};
        var key = keyName || "id";

        fallbackUtils.toArray(items).forEach(function (item) {
          var id = item && (item[key] || item.id || item.key || item.value || item.name);

          if (id) {
            output[String(id)] = item;
          }
        });

        return output;
      } catch (error) {
        return {};
      }
    },

    buildDefinitionMaps: function (definitions) {
      try {
        var defs = fallbackUtils.normalizeDefinitions(definitions);

        return {
          variantProfilesById: fallbackUtils.indexBy(defs.variant_profiles, "id"),
          variablesByKey: fallbackUtils.indexBy(defs.variables, "key"),
          unitsById: fallbackUtils.indexBy(defs.units, "id"),
          materialsById: fallbackUtils.indexBy(defs.materials, "id"),
          documentTypesById: fallbackUtils.indexBy(defs.document_types, "id")
        };
      } catch (error) {
        return {
          variantProfilesById: {},
          variablesByKey: {},
          unitsById: {},
          materialsById: {},
          documentTypesById: {}
        };
      }
    },

    optionValue: function (option) {
      try {
        if (!option || typeof option !== "object") {
          return String(option || "");
        }

        return String(option.value || option.id || option.key || option.label || "");
      } catch (error) {
        return "";
      }
    },

    optionLabel: function (option) {
      try {
        if (!option || typeof option !== "object") {
          return String(option || "");
        }

        return String(option.label || option.name || option.title || option.value || option.id || "");
      } catch (error) {
        return "";
      }
    },

    formatValue: function (value, variable, definitions) {
      try {
        if (value === null || value === undefined || value === "") {
          return "";
        }

        var type = variable && variable.value_type ? variable.value_type : "";

        if (type === "boolean") {
          return fallbackUtils.bool(value, false) ? "Ja" : "Nein";
        }

        if (type === "enum" && variable && variable.options) {
          var match = fallbackUtils.toArray(variable.options).filter(function (option) {
            return fallbackUtils.optionValue(option) === String(value);
          })[0];

          if (match) {
            return fallbackUtils.optionLabel(match);
          }
        }

        return String(value);
      } catch (error) {
        return String(value || "");
      }
    },

    valuesFromJson: function (value) {
      var parsed = fallbackUtils.safeJsonParse(value, {});
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    },

    valuesToJson: function (value) {
      return fallbackUtils.safeJsonStringify(value || {}, "{}", 0);
    },

    nowIso: function () {
      try {
        return new Date().toISOString();
      } catch (error) {
        return "";
      }
    }
  };

  function U() {
    return getUtils();
  }

  function warn(message, error) {
    U().warn(message, error);
  }

  /* ---------------------------------------------------------------------------
   * Runtime
   * ------------------------------------------------------------------------ */

  var runtime = {
    initialized: false,
    globalEventsBound: false,
    tableSummaryInProgress: false,
    tableSummaryScheduled: false,
    suppressedTableSummaryCount: 0,
    lastProfile: null,
    lastValues: {},
    lastPayload: null,
    lastTableSignature: "",
    lastDrawerSignature: "",
    cache: {
      definitions: null,
      maps: null
    },
    options: {
      maxSummaryParts: 7,
      maxBadgeParts: 5,
      maxPartLength: 80,
      separator: " · ",
      emitNativeEvents: false
    }
  };

  /* ---------------------------------------------------------------------------
   * Definitions
   * ------------------------------------------------------------------------ */

  function getDefinitions(options) {
    try {
      var config = options || {};

      if (runtime.cache.definitions && config.force !== true && config.forceReload !== true) {
        return runtime.cache.definitions;
      }

      var definitions = null;

      if (
        window.VectoplanCreateVariantProfiles &&
        typeof window.VectoplanCreateVariantProfiles.getDefinitionsSync === "function"
      ) {
        definitions = window.VectoplanCreateVariantProfiles.getDefinitionsSync();
      }

      if (!definitions && window.VectoplanCreateDefinitions) {
        definitions = window.VectoplanCreateDefinitions;
      }

      if (!definitions && window.VectoplanCreateContext && window.VectoplanCreateContext.definitions) {
        definitions = window.VectoplanCreateContext.definitions;
      }

      runtime.cache.definitions = U().normalizeDefinitions(definitions || {});
      runtime.cache.maps = U().buildDefinitionMaps(runtime.cache.definitions);

      return runtime.cache.definitions;
    } catch (error) {
      warn("Could not read summary definitions.", error);
      return U().normalizeDefinitions({});
    }
  }

  function getMaps(options) {
    try {
      var config = options || {};

      if (runtime.cache.maps && config.force !== true && config.forceReload !== true) {
        return runtime.cache.maps;
      }

      runtime.cache.maps = U().buildDefinitionMaps(getDefinitions(config));
      return runtime.cache.maps;
    } catch (error) {
      warn("Could not build summary definition maps.", error);
      return U().buildDefinitionMaps({});
    }
  }

  function getVariable(fieldKey) {
    try {
      return getMaps().variablesByKey[fieldKey] || null;
    } catch (error) {
      return null;
    }
  }

  function getUnit(unitId) {
    try {
      return getMaps().unitsById[unitId] || null;
    } catch (error) {
      return null;
    }
  }

  function getMaterial(materialId) {
    try {
      return getMaps().materialsById[materialId] || null;
    } catch (error) {
      return null;
    }
  }

  function getVariantProfile(profileId) {
    try {
      if (!profileId) {
        return null;
      }

      return getMaps().variantProfilesById[profileId] || null;
    } catch (error) {
      return null;
    }
  }

  /* ---------------------------------------------------------------------------
   * Value access
   * ------------------------------------------------------------------------ */

  function isEmptyValue(value) {
    try {
      if (value === null || value === undefined || value === "") {
        return true;
      }

      if (Array.isArray(value) && value.length === 0) {
        return true;
      }

      return false;
    } catch (error) {
      return true;
    }
  }

  function getValue(values, fieldKey) {
    try {
      if (!values || typeof values !== "object") {
        return undefined;
      }

      if (Object.prototype.hasOwnProperty.call(values, fieldKey)) {
        return values[fieldKey];
      }

      return undefined;
    } catch (error) {
      return undefined;
    }
  }

  function truncateText(value, maxLength) {
    try {
      var text = String(value === null || value === undefined ? "" : value);
      var limit = U().intValue(maxLength, runtime.options.maxPartLength);

      if (text.length <= limit) {
        return text;
      }

      return text.slice(0, Math.max(0, limit - 1)) + "…";
    } catch (error) {
      return String(value || "");
    }
  }

  function unitSymbol(variable) {
    try {
      if (!variable || !variable.unit) {
        return "";
      }

      var unit = getUnit(variable.unit);

      if (!unit) {
        return variable.unit;
      }

      return unit.symbol || unit.label || unit.id || variable.unit;
    } catch (error) {
      return "";
    }
  }

  function optionLabel(variable, value) {
    try {
      if (!variable) {
        return "";
      }

      var options = U().toArray(variable.options);
      var textValue = String(value);

      var matched = options.filter(function (option) {
        return U().optionValue(option) === textValue;
      })[0];

      if (matched) {
        return U().optionLabel(matched);
      }

      if (variable.key === "material.type") {
        var material = getMaterial(value);

        if (material) {
          return material.label || material.id || value;
        }
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function formatDocumentList(value) {
    try {
      var list = Array.isArray(value) ? value : U().safeJsonParse(value, []);

      if (!Array.isArray(list)) {
        list = [];
      }

      if (list.length === 0) {
        return "";
      }

      if (list.length === 1) {
        var first = list[0];

        if (first && typeof first === "object" && (first.label || first.name || first.type)) {
          return first.label || first.name || first.type;
        }

        return "1 Dokument";
      }

      return String(list.length) + " Dokumente";
    } catch (error) {
      return "";
    }
  }

  function formatBoolean(value) {
    try {
      return U().bool(value, false) ? "Ja" : "Nein";
    } catch (error) {
      return "";
    }
  }

  function formatNumber(value, variable) {
    try {
      if (value === null || value === undefined || value === "") {
        return "";
      }

      var unit = unitSymbol(variable);
      var text = String(value);

      return unit ? text + " " + unit : text;
    } catch (error) {
      return String(value || "");
    }
  }

  function formatValue(value, variable, options) {
    try {
      if (isEmptyValue(value)) {
        return "";
      }

      var config = options || {};
      var type = variable && variable.value_type ? variable.value_type : "";
      var widget = variable && variable.widget ? variable.widget : "";

      if (type === "boolean" || widget === "checkbox") {
        return formatBoolean(value);
      }

      if (type === "number" || type === "integer" || type === "money" || widget === "number" || widget === "money") {
        return formatNumber(value, variable);
      }

      if (type === "document_list" || widget === "document_list") {
        return formatDocumentList(value);
      }

      if (type === "enum" || widget === "select") {
        return optionLabel(variable, value) || String(value);
      }

      if (variable && variable.key === "material.type") {
        return optionLabel(variable, value) || String(value);
      }

      return truncateText(value, config.maxPartLength || runtime.options.maxPartLength);
    } catch (error) {
      return String(value || "");
    }
  }

  function labelForField(fieldKey, variable) {
    try {
      if (variable && variable.label) {
        return variable.label;
      }

      return fieldKey || "Feld";
    } catch (error) {
      return fieldKey || "Feld";
    }
  }

  function makePart(fieldKey, values, options) {
    try {
      var variable = getVariable(fieldKey);
      var value = getValue(values, fieldKey);

      if (isEmptyValue(value)) {
        return null;
      }

      var formatted = formatValue(value, variable, options);

      if (!formatted) {
        return null;
      }

      return {
        field_key: fieldKey,
        fieldKey: fieldKey,
        label: labelForField(fieldKey, variable),
        value: value,
        formatted: formatted,
        text: formatted,
        variable: variable
      };
    } catch (error) {
      return null;
    }
  }

  function makeLabeledPart(fieldKey, values, options) {
    try {
      var part = makePart(fieldKey, values, options);

      if (!part) {
        return null;
      }

      if (fieldKey === "variant.label") {
        part.text = part.formatted;
      } else {
        part.text = part.label + ": " + part.formatted;
      }

      return part;
    } catch (error) {
      return null;
    }
  }

  /* ---------------------------------------------------------------------------
   * Profile fields
   * ------------------------------------------------------------------------ */

  function getCardConfig(profile) {
    try {
      var ui = profile && profile.ui ? profile.ui : {};
      var cards = ui.cards || {};

      return {
        title_field: cards.title_field || "variant.label",
        subtitle_fields: U().toArray(cards.subtitle_fields),
        badge_fields: U().toArray(cards.badge_fields)
      };
    } catch (error) {
      return {
        title_field: "variant.label",
        subtitle_fields: [],
        badge_fields: []
      };
    }
  }

  function getSummaryFields(profile) {
    try {
      var fields = U().toArray(profile && profile.summary_fields);

      if (fields.length) {
        return fields;
      }

      var card = getCardConfig(profile);

      return []
        .concat([card.title_field])
        .concat(card.subtitle_fields)
        .concat(card.badge_fields)
        .filter(Boolean);
    } catch (error) {
      return [];
    }
  }

  function fallbackSummaryFields(values) {
    try {
      var priority = [
        "variant.label",
        "product.designation",
        "manufacturer.name",
        "dimensions.thickness_mm",
        "dimensions.width_mm",
        "dimensions.height_mm",
        "dimensions.depth_mm",
        "dimensions.length_mm",
        "material.type",
        "material.subtype",
        "concrete.strength_class",
        "structural.compressive_strength",
        "thermal.u_value",
        "physics.u_value",
        "thermal.lambda_value",
        "physics.lambda_value",
        "fire.fire_resistance_class",
        "acoustic.sound_reduction_db",
        "acoustics.sound_reduction",
        "connection.type",
        "surface.finish",
        "commercial.price_per_piece",
        "commercial.price_per_m2",
        "commercial.price_per_m3"
      ];

      var result = [];

      priority.forEach(function (fieldKey) {
        if (!isEmptyValue(getValue(values, fieldKey))) {
          result.push(fieldKey);
        }
      });

      if (result.length) {
        return result;
      }

      Object.keys(values || {}).forEach(function (key) {
        if (result.length >= runtime.options.maxSummaryParts) {
          return;
        }

        if (!isEmptyValue(values[key])) {
          result.push(key);
        }
      });

      return result;
    } catch (error) {
      return [];
    }
  }

  /* ---------------------------------------------------------------------------
   * Summary build
   * ------------------------------------------------------------------------ */

  function buildSummaryPayload(values, profile, options) {
    try {
      var config = U().safeMerge(runtime.options, options || {});
      var sourceValues = values && typeof values === "object" ? values : {};
      var sourceProfile = profile || null;

      if (!sourceProfile && sourceValues.variant_profile_id) {
        sourceProfile = getVariantProfile(sourceValues.variant_profile_id);
      }

      var card = getCardConfig(sourceProfile || {});
      var titleField = card.title_field || "variant.label";
      var titlePart = makePart(titleField, sourceValues, config);
      var title = titlePart ? titlePart.formatted : "";

      if (!title) {
        title = sourceValues["variant.label"] || sourceValues.label || sourceValues.name || "Neue Variante";
      }

      var subtitleParts = [];
      card.subtitle_fields.forEach(function (fieldKey) {
        var part = makePart(fieldKey, sourceValues, config);

        if (part) {
          subtitleParts.push(part);
        }
      });

      var badgeParts = [];
      card.badge_fields.forEach(function (fieldKey) {
        if (badgeParts.length >= config.maxBadgeParts) {
          return;
        }

        var part = makePart(fieldKey, sourceValues, config);

        if (part) {
          badgeParts.push(part);
        }
      });

      var summaryFields = getSummaryFields(sourceProfile);

      if (!summaryFields.length) {
        summaryFields = fallbackSummaryFields(sourceValues);
      }

      var summaryParts = [];
      var seen = {};

      summaryFields.forEach(function (fieldKey) {
        if (summaryParts.length >= config.maxSummaryParts) {
          return;
        }

        if (!fieldKey || seen[fieldKey]) {
          return;
        }

        seen[fieldKey] = true;

        if (fieldKey === "variant.label") {
          return;
        }

        var part = makeLabeledPart(fieldKey, sourceValues, config);

        if (part) {
          summaryParts.push(part);
        }
      });

      if (!summaryParts.length) {
        fallbackSummaryFields(sourceValues).forEach(function (fieldKey) {
          if (summaryParts.length >= config.maxSummaryParts) {
            return;
          }

          if (!fieldKey || seen[fieldKey] || fieldKey === "variant.label") {
            return;
          }

          seen[fieldKey] = true;

          var part = makeLabeledPart(fieldKey, sourceValues, config);

          if (part) {
            summaryParts.push(part);
          }
        });
      }

      var subtitle = subtitleParts.map(function (part) {
        return part.formatted;
      }).join(config.separator);

      var text = summaryParts.map(function (part) {
        return part.text;
      }).join(config.separator);

      if (!text && subtitle) {
        text = subtitle;
      }

      if (!text && title && title !== "Neue Variante") {
        text = title;
      }

      if (!text) {
        text = "Noch keine Kurzwerte";
      }

      return {
        ok: true,
        title: title,
        subtitle: subtitle,
        text: text,
        summary: text,
        summary_text: text,
        parts: summaryParts,
        subtitles: subtitleParts,
        badges: badgeParts,
        title_field: titleField,
        summary_fields: summaryFields,
        profile_id: sourceProfile ? sourceProfile.id || "" : "",
        values: sourceValues,
        profile: sourceProfile || null
      };
    } catch (error) {
      warn("Could not build summary payload.", error);

      return {
        ok: false,
        title: "Neue Variante",
        subtitle: "",
        text: "Noch keine Kurzwerte",
        summary: "Noch keine Kurzwerte",
        summary_text: "Noch keine Kurzwerte",
        parts: [],
        subtitles: [],
        badges: [],
        error: normalizeError(error),
        values: values || {},
        profile: profile || null
      };
    }
  }

  function buildSummary(values, profile, options) {
    try {
      var config = options || {};
      var payload = buildSummaryPayload(values || {}, profile || null, config);

      if (config.dispatchEvent === true) {
        U().dispatchDocument("vectoplan:create:variant-summary-built", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          payload: payload,
          text: payload.text,
          __vp_variant_summary_event: true
        }, {
          silent: true
        });
      }

      if (config.returnObject === true || config.asObject === true) {
        return payload;
      }

      return payload.text;
    } catch (error) {
      warn("Could not build summary.", error);
      return "Noch keine Kurzwerte";
    }
  }

  /* ---------------------------------------------------------------------------
   * DOM rendering: Drawer summary
   * ------------------------------------------------------------------------ */

  function cacheDrawer(root) {
    try {
      var drawer = root && root.nodeType === 1
        ? (root.matches && root.matches(DRAWER_SELECTOR) ? root : U().closest(root, DRAWER_SELECTOR) || U().qs(DRAWER_SELECTOR, root))
        : U().qs(DRAWER_SELECTOR);

      return {
        drawer: drawer,
        valuesJsonField: U().qs("[data-vp-variant-drawer-values-json-field='true']", drawer),
        variantIdField: U().qs("[data-vp-variant-drawer-variant-id-field='true']", drawer),
        profileIdField: U().qs("[data-vp-variant-drawer-profile-id-field='true']", drawer),
        summaryName: U().qs("[data-vp-variant-drawer-summary-name='true']", drawer),
        summaryId: U().qs("[data-vp-variant-drawer-summary-id='true']", drawer),
        summaryProfile: U().qs("[data-vp-variant-drawer-summary-profile='true']", drawer),
        summaryStatus: U().qs("[data-vp-variant-drawer-summary-status='true']", drawer),
        summaryValues: U().qs("[data-vp-variant-drawer-summary-values='true']", drawer),
        title: U().qs("[data-vp-variant-drawer-title='true']", drawer)
      };
    } catch (error) {
      warn("Could not cache drawer summary nodes.", error);

      return {
        drawer: null
      };
    }
  }

  function readDrawerValues(cache) {
    try {
      var c = cache || cacheDrawer();

      if (c.valuesJsonField && c.valuesJsonField.value) {
        return U().valuesFromJson(c.valuesJsonField.value);
      }

      if (
        window.VectoplanCreateVariantFieldRenderer &&
        typeof window.VectoplanCreateVariantFieldRenderer.collectValues === "function"
      ) {
        return window.VectoplanCreateVariantFieldRenderer.collectValues(c.drawer);
      }

      return {};
    } catch (error) {
      return {};
    }
  }

  function readDrawerProfile(cache, explicitProfile) {
    try {
      if (explicitProfile) {
        return explicitProfile;
      }

      var c = cache || cacheDrawer();
      var profileId = U().getValue(c.profileIdField, "") ||
        U().attr(c.drawer, "data-vp-current-variant-profile-id", "");

      return getVariantProfile(profileId);
    } catch (error) {
      return null;
    }
  }

  function createChip(part, modifier) {
    try {
      return U().createElement("span", {
        class: "vp-create-variant-summary-chip" + (modifier ? " " + modifier : ""),
        text: part.formatted || part.text || "",
        attrs: {
          "data-vp-summary-chip": "true",
          "data-vp-summary-field-key": part.field_key || "",
          title: part.label ? part.label + ": " + part.formatted : part.formatted
        }
      });
    } catch (error) {
      return U().createElement("span");
    }
  }

  function renderSummaryValues(container, payload) {
    try {
      if (!container) {
        return false;
      }

      U().empty(container);

      if (payload.badges && payload.badges.length) {
        var badgeWrap = U().createElement("div", {
          class: "vp-create-variant-drawer__summary-badges",
          attrs: {
            "data-vp-summary-badges": "true"
          }
        });

        payload.badges.forEach(function (part) {
          badgeWrap.appendChild(createChip(part, "vp-create-variant-summary-chip--badge"));
        });

        container.appendChild(badgeWrap);
      }

      if (payload.parts && payload.parts.length) {
        var list = U().createElement("dl", {
          class: "vp-create-variant-drawer__summary-values-list",
          attrs: {
            "data-vp-summary-values-list": "true"
          }
        });

        payload.parts.forEach(function (part) {
          var item = U().createElement("div", {
            class: "vp-create-variant-drawer__summary-values-item",
            attrs: {
              "data-vp-summary-value-item": "true",
              "data-vp-summary-field-key": part.field_key || ""
            }
          }, [
            U().createElement("dt", {
              text: part.label || part.field_key || "Feld"
            }),
            U().createElement("dd", {
              text: part.formatted || ""
            })
          ]);

          list.appendChild(item);
        });

        container.appendChild(list);
      }

      if ((!payload.parts || !payload.parts.length) && (!payload.badges || !payload.badges.length)) {
        container.appendChild(U().createElement("span", {
          class: "vp-create-variant-drawer__summary-placeholder",
          text: payload.text || "Noch keine Kurzwerte"
        }));
      }

      return true;
    } catch (error) {
      warn("Could not render drawer summary values.", error);
      return false;
    }
  }

  function drawerSignature(values, profile) {
    try {
      return U().safeJsonStringify({
        values: values || {},
        profile: profile ? profile.id || profile.profile_id || "" : ""
      }, "{}");
    } catch (error) {
      return String(Date.now());
    }
  }

  function updateDrawerSummary(values, profile, root, options) {
    try {
      var config = options || {};
      var cache = cacheDrawer(root);
      var sourceValues = values || readDrawerValues(cache);
      var sourceProfile = profile || readDrawerProfile(cache);
      var signature = drawerSignature(sourceValues, sourceProfile);

      if (config.force !== true && signature === runtime.lastDrawerSignature) {
        return runtime.lastPayload || buildSummaryPayload(sourceValues, sourceProfile, config);
      }

      var payload = buildSummaryPayload(sourceValues, sourceProfile, config);

      if (cache.summaryName) {
        U().setText(cache.summaryName, payload.title || "Neue Variante");
      }

      if (cache.summaryId) {
        var id = sourceValues["variant.variant_id"] ||
          U().getValue(cache.variantIdField, "") ||
          "wird automatisch vergeben";

        U().setText(cache.summaryId, id);
      }

      if (cache.summaryProfile) {
        U().setText(cache.summaryProfile, payload.profile_id ||
          U().getValue(cache.profileIdField, "") ||
          "auto");
      }

      if (cache.summaryStatus) {
        U().setText(cache.summaryStatus, "Entwurf");
      }

      renderSummaryValues(cache.summaryValues, payload);

      runtime.lastPayload = payload;
      runtime.lastValues = sourceValues;
      runtime.lastProfile = sourceProfile;
      runtime.lastDrawerSignature = signature;

      if (config.dispatchEvent !== false) {
        U().dispatchDocument("vectoplan:create:variant-drawer-summary-updated", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          payload: payload,
          values: sourceValues,
          profile: sourceProfile,
          drawerId: cache.drawer ? U().attr(cache.drawer, "id", "") : "",
          __vp_variant_summary_event: true
        }, {
          silent: true
        });
      }

      return payload;
    } catch (error) {
      warn("Could not update drawer summary.", error);

      return buildSummaryPayload({}, null, {});
    }
  }

  /* ---------------------------------------------------------------------------
   * DOM rendering: Table summaries
   * ------------------------------------------------------------------------ */

  function getRowValues(row) {
    try {
      var json = U().getValue(U().qs("[data-vp-row-definition-values-json]", row), "") ||
        U().attr(row, "data-vp-definition-values-json", "");

      var values = U().valuesFromJson(json);

      if (!values["variant.label"]) {
        var label = U().attr(row, "data-vp-variant-label", "") ||
          U().getValue(U().qs("[data-vp-variant-name]", row), "");

        if (label) {
          values["variant.label"] = label;
        }
      }

      if (!values["variant.variant_id"]) {
        var id = U().attr(row, "data-vp-variant-id", "") ||
          U().attr(row, "data-vp-definition-variant-id", "") ||
          U().getValue(U().qs("[data-vp-variant-slug]", row), "");

        if (id) {
          values["variant.variant_id"] = id;
        }
      }

      return values;
    } catch (error) {
      return {};
    }
  }

  function getRowProfile(row) {
    try {
      var profileId = U().attr(row, "data-vp-variant-profile-id", "") ||
        U().attr(row, "data-vp-definition-variant-profile-id", "") ||
        U().getValue(U().qs("[data-vp-row-variant-profile-id]", row), "");

      return getVariantProfile(profileId);
    } catch (error) {
      return null;
    }
  }

  function setHiddenSummaryValue(summaryInput, summaryText) {
    try {
      if (!summaryInput) {
        return false;
      }

      var next = summaryText === null || summaryText === undefined ? "" : String(summaryText);

      if (summaryInput.value === next) {
        return false;
      }

      summaryInput.value = next;
      U().setAttr(summaryInput, "data-vp-last-summary-sync", String(Date.now()));
      U().setAttr(summaryInput, "data-vp-last-summary-sync-source", COMPONENT_NAME);
      U().setAttr(summaryInput, "data-vp-programmatic-event-source", COMPONENT_NAME);

      return true;
    } catch (error) {
      return false;
    }
  }

  function updateRowSummary(row) {
    try {
      if (!row) {
        return null;
      }

      var values = getRowValues(row);
      var profile = getRowProfile(row);
      var payload = buildSummaryPayload(values, profile, {
        dispatchEvent: false
      });
      var summaryText = payload.text || "Noch keine Kurzwerte";

      var summaryNode = U().qs("[data-vp-row-definition-summary='true']", row);
      var summaryInput = U().qs("[data-vp-row-definition-summary-input]", row);

      if (summaryNode) {
        U().setText(summaryNode, summaryText);
      }

      setHiddenSummaryValue(summaryInput, summaryText);

      return payload;
    } catch (error) {
      warn("Could not update row summary.", error);
      return null;
    }
  }

  function tableSignature(table) {
    try {
      var parts = U().qsa(ROW_SELECTOR, table || document).map(function (row) {
        return [
          U().attr(row, "data-vp-variant-id", ""),
          U().attr(row, "data-vp-variant-profile-id", ""),
          U().getValue(U().qs("[data-vp-row-definition-values-json]", row), ""),
          U().getValue(U().qs("[data-vp-row-definition-summary-input]", row), "")
        ].join("::");
      });

      return parts.join("||");
    } catch (error) {
      return "";
    }
  }

  function updateTableSummaries(root, options) {
    try {
      var config = options || {};
      var table = root && root.nodeType === 1
        ? (root.matches && root.matches(TABLE_SELECTOR) ? root : U().qs(TABLE_SELECTOR, root) || U().closest(root, TABLE_SELECTOR))
        : U().qs(TABLE_SELECTOR);

      if (!table) {
        return [];
      }

      if (runtime.tableSummaryInProgress) {
        runtime.suppressedTableSummaryCount += 1;
        return [];
      }

      var beforeSignature = tableSignature(table);

      if (config.force !== true && beforeSignature && beforeSignature === runtime.lastTableSignature) {
        return [];
      }

      runtime.tableSummaryInProgress = true;

      var payloads = [];

      U().qsa(ROW_SELECTOR, table).forEach(function (row) {
        var payload = updateRowSummary(row);

        if (payload) {
          payloads.push(payload);
        }
      });

      runtime.tableSummaryInProgress = false;
      runtime.lastTableSignature = tableSignature(table);

      if (config.dispatchEvent !== false) {
        U().dispatchDocument("vectoplan:create:variant-table-summary-updated", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          count: payloads.length,
          payloads: payloads,
          __vp_variant_summary_event: true
        }, {
          silent: true
        });
      }

      return payloads;
    } catch (error) {
      runtime.tableSummaryInProgress = false;
      warn("Could not update table summaries.", error);
      return [];
    }
  }

  function scheduleTableSummaries(root, options) {
    try {
      if (runtime.tableSummaryScheduled) {
        runtime.suppressedTableSummaryCount += 1;
        return false;
      }

      runtime.tableSummaryScheduled = true;

      window.setTimeout(function () {
        try {
          runtime.tableSummaryScheduled = false;
          updateTableSummaries(root, options || {});
        } catch (error) {
          runtime.tableSummaryScheduled = false;
          warn("Scheduled table summaries failed.", error);
        }
      }, 50);

      return true;
    } catch (error) {
      runtime.tableSummaryScheduled = false;
      warn("Could not schedule table summaries.", error);
      return false;
    }
  }

  /* ---------------------------------------------------------------------------
   * Variant helpers
   * ------------------------------------------------------------------------ */

  function updateVariantSummaryPayload(variant, profile) {
    try {
      var source = variant || {};
      var values = source.definition_values && typeof source.definition_values === "object"
        ? source.definition_values
        : U().valuesFromJson(source.definition_values_json || "{}");

      if (!values["variant.label"] && (source.label || source.name)) {
        values["variant.label"] = source.label || source.name;
      }

      if (!values["variant.variant_id"] && (source.variant_id || source.slug)) {
        values["variant.variant_id"] = source.variant_id || source.slug;
      }

      var sourceProfile = profile || getVariantProfile(source.variant_profile_id || "");
      var payload = buildSummaryPayload(values, sourceProfile, {
        dispatchEvent: false
      });

      source.definition_summary = payload.text;
      source.definition_values = values;
      source.definition_values_json = U().valuesToJson(values);

      return {
        variant: source,
        summary: payload.text,
        payload: payload
      };
    } catch (error) {
      warn("Could not update variant summary payload.", error);

      return {
        variant: variant,
        summary: "Noch keine Kurzwerte",
        payload: buildSummaryPayload({}, null, {})
      };
    }
  }

  /* ---------------------------------------------------------------------------
   * Event binding
   * ------------------------------------------------------------------------ */

  function bindGlobalEvents() {
    try {
      if (runtime.globalEventsBound) {
        return;
      }

      document.addEventListener("vectoplan:create:variant-values-changed", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          updateDrawerSummary(detail.values || {}, detail.profile || runtime.lastProfile || null, null, {
            source: "values_changed"
          });
        } catch (error) {
          warn("Values changed summary listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-fields-rendered", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          updateDrawerSummary(detail.values || {}, detail.profile || runtime.lastProfile || null, {
            source: "fields_rendered"
          });
        } catch (error) {
          warn("Fields rendered summary listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-profile-resolved", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var profile = detail.variant_profile || detail.variantProfile || detail.profile || null;

          runtime.lastProfile = profile || runtime.lastProfile;

          updateDrawerSummary(runtime.lastValues || {}, runtime.lastProfile, null, {
            source: "profile_resolved"
          });
          scheduleTableSummaries(null, {
            source: "profile_resolved"
          });
        } catch (error) {
          warn("Profile resolved summary listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-profile-loaded", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var profile = detail.variant_profile || detail.variantProfile || detail.profile || null;

          runtime.lastProfile = profile || runtime.lastProfile;
          updateDrawerSummary(runtime.lastValues || {}, runtime.lastProfile, null, {
            source: "profile_loaded"
          });
        } catch (error) {
          warn("Profile loaded summary listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-drawer-opened", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var payload = detail.payload || detail || {};
          var values = {};

          if (payload.definition_values && typeof payload.definition_values === "object") {
            values = payload.definition_values;
          } else if (payload.values && typeof payload.values === "object") {
            values = payload.values;
          } else if (payload.definition_values_json || payload.valuesJson || payload.values_json) {
            values = U().valuesFromJson(payload.definition_values_json || payload.valuesJson || payload.values_json);
          }

          runtime.lastValues = values;
          updateDrawerSummary(values, runtime.lastProfile || null, null, {
            source: "drawer_opened",
            force: true
          });
        } catch (error) {
          warn("Drawer opened summary listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-added", function () {
        try {
          scheduleTableSummaries(null, {
            source: "variant_added",
            force: true
          });
        } catch (error) {
          warn("Variant added summary listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-updated", function () {
        try {
          scheduleTableSummaries(null, {
            source: "variant_updated",
            force: true
          });
        } catch (error) {
          warn("Variant updated summary listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-state-changed", function () {
        try {
          scheduleTableSummaries(null, {
            source: "state_changed"
          });
        } catch (error) {
          warn("State changed summary listener failed.", error);
        }
      });

      runtime.globalEventsBound = true;
    } catch (error) {
      warn("Could not bind summary global events.", error);
    }
  }

  /* ---------------------------------------------------------------------------
   * Diagnostics / init
   * ------------------------------------------------------------------------ */

  function normalizeError(error) {
    try {
      if (!error) {
        return {
          code: "unknown_error",
          message: "Unbekannter Fehler."
        };
      }

      if (error.error && typeof error.error === "object") {
        return normalizeError(error.error);
      }

      return {
        code: error.code || error.status || "error",
        message: error.message || String(error),
        status: error.status || null,
        payload: error.payload || null
      };
    } catch (normalizationError) {
      return {
        code: "error",
        message: "Fehler konnte nicht normalisiert werden."
      };
    }
  }

  function getRuntimeSnapshot() {
    try {
      return {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        initialized: runtime.initialized,
        hasLastProfile: !!runtime.lastProfile,
        lastProfileId: runtime.lastProfile ? runtime.lastProfile.id || "" : "",
        lastValueCount: runtime.lastValues ? Object.keys(runtime.lastValues).length : 0,
        hasDefinitions: !!runtime.cache.definitions,
        tableSummaryInProgress: runtime.tableSummaryInProgress,
        tableSummaryScheduled: runtime.tableSummaryScheduled,
        suppressedTableSummaryCount: runtime.suppressedTableSummaryCount,
        lastTableSignatureLength: runtime.lastTableSignature ? runtime.lastTableSignature.length : 0,
        lastDrawerSignatureLength: runtime.lastDrawerSignature ? runtime.lastDrawerSignature.length : 0,
        counts: runtime.cache.definitions ? {
          variables: runtime.cache.definitions.variables.length,
          units: runtime.cache.definitions.units.length,
          materials: runtime.cache.definitions.materials.length,
          variant_profiles: runtime.cache.definitions.variant_profiles.length
        } : null
      };
    } catch (error) {
      return {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION
      };
    }
  }

  function initialize(options) {
    try {
      var config = options || {};

      runtime.options = U().safeMerge(runtime.options, config);

      getDefinitions({
        force: !!config.force
      });

      bindGlobalEvents();
      updateTableSummaries(null, {
        source: config.source || "initialize",
        dispatchEvent: false,
        force: true
      });

      runtime.initialized = true;

      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-summary-version", COMPONENT_VERSION);

      U().dispatchDocument("vectoplan:create:variant-summary-ready", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        snapshot: getRuntimeSnapshot(),
        __vp_variant_summary_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not initialize variant summary.", error);
      return false;
    }
  }

  /* ---------------------------------------------------------------------------
   * Public API
   * ------------------------------------------------------------------------ */

  var api = {
    __name: COMPONENT_NAME,
    __version: COMPONENT_VERSION,

    initialize: initialize,

    buildSummary: buildSummary,
    buildSummaryPayload: buildSummaryPayload,
    updateDrawerSummary: updateDrawerSummary,
    updateTableSummaries: updateTableSummaries,
    scheduleTableSummaries: scheduleTableSummaries,
    updateRowSummary: updateRowSummary,
    updateVariantSummaryPayload: updateVariantSummaryPayload,

    formatValue: formatValue,
    makePart: makePart,
    makeLabeledPart: makeLabeledPart,

    getDefinitions: getDefinitions,
    getMaps: getMaps,
    getVariable: getVariable,
    getUnit: getUnit,
    getVariantProfile: getVariantProfile,

    getRuntimeSnapshot: getRuntimeSnapshot
  };

  try {
    window[GLOBAL_NAME] = api;

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        initialize({
          source: "dom_content_loaded",
          emitNativeEvents: false
        });
      }, {
        once: true
      });
    } else {
      initialize({
        source: "immediate",
        emitNativeEvents: false
      });
    }
  } catch (bootstrapError) {
    warn("Could not bootstrap variant summary.", bootstrapError);
  }
})();