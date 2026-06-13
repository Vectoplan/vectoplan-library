// services/vectoplan-library/static/library_admin/js/create_variant_field_renderer.js
/* -----------------------------------------------------------------------------
 * VECTOPLAN Library · Create Wizard · Variant Field Renderer
 *
 * Zweck:
 * - Rendert Variant-Drawer-Felder dynamisch aus Backend-Definitionsdaten.
 * - Nutzt Variant Profiles, Sections und Variables als Source of Truth.
 * - Rendert keine fachlich hart kodierten Felder.
 * - Unterstützt systemverwaltete Felder wie `variant.variant_id`.
 * - Schreibt aktuelle Drawer-Werte in `variant_drawer_values_json`.
 * - Dispatcht Werteänderungen an Drawer, Summary, Validation und State.
 *
 * Architekturregel:
 * - Backend definiert, welche Felder existieren.
 * - Frontend rendert nur die gelieferten Definitionen.
 * - `variant.variant_id` wird nicht als normales Eingabefeld gerendert.
 * - Feldwerte werden als flache Dot-Key-Werte geführt:
 *     {
 *       "variant.label": "Standard",
 *       "dimensions.width_mm": 1000,
 *       "material.type": "concrete"
 *     }
 *
 * UI-Ziel dieser Fassung:
 * - Kompatibel mit der Clean-Shell `_variant_drawer_shell.html`.
 * - Section Navigation bleibt als technischer Hook erhalten, wird im Clean-Modus
 *   aber nicht sichtbar gerendert.
 * - Sections werden im Clean-Modus untereinander angezeigt, nicht als Tabs
 *   gegeneinander versteckt.
 * - Clean-Shell-Sections bekommen explizite Flat-Hooks:
 *     data-vp-clean-section-layout="flat"
 *     data-vp-section-display="flat"
 *     data-vp-section-visible="true"
 * - Profilabschnitte bleiben semantisch erhalten, wirken aber wie eine
 *   zusammenhängende Formularfläche.
 * - Legacy-Additional-Fields werden im Clean-Modus nicht zusätzlich gerendert.
 * - Der Optional-Fields-Bereich wird nicht geleert, versteckt oder gemountet.
 * - Zusätzliche Backend-Variablen bleiben Aufgabe von:
 *     create_variant_optional_fields.js
 * - Hidden JSON-Felder werden möglichst still synchronisiert, um Event-Loops zu
 *   vermeiden.
 *
 * Diese Datei:
 * - resolved keine Profile selbst, nutzt aber Profile Events und optional
 *   window.VectoplanCreateVariantProfiles
 * - validiert nicht final, kann aber einfache HTML-Constraints setzen
 * - erzeugt keine Varianten im State
 * - erzeugt keine VPLIB-Packages
 *
 * Global:
 * - window.VectoplanCreateVariantFieldRenderer
 *
 * Benötigt, falls vorhanden:
 * - window.VectoplanCreateVariantUtils
 * - window.VectoplanCreateVariantProfiles
 * - window.VectoplanCreateVariantState
 * - window.VectoplanCreateDefinitions
 * - window.VectoplanCreateVariantOptionalFields
 *
 * Events:
 * - dispatch: vectoplan:create:variant-field-renderer-ready
 * - dispatch: vectoplan:create:variant-fields-render-started
 * - dispatch: vectoplan:create:variant-fields-rendered
 * - dispatch: vectoplan:create:variant-fields-cleared
 * - dispatch: vectoplan:create:variant-values-changed
 * - dispatch: vectoplan:create:variant-field-changed
 * - dispatch: vectoplan:create:variant-field-render-failed
 *
 * - listen: vectoplan:create:variant-profile-resolved
 * - listen: vectoplan:create:variant-profile-loaded
 * - listen: vectoplan:create:variant-empty-values-ready
 * - listen: vectoplan:create:variant-drawer-opened
 * - listen: vectoplan:create:variant-drawer-session-started
 * - listen: vectoplan:create:variant-drawer-session-prepared
 * - listen: vectoplan:create:definitions-ready
 * - listen: vectoplan:create:variant-definitions-retry-requested
 * -------------------------------------------------------------------------- */

(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateVariantFieldRenderer";
  var COMPONENT_NAME = "VECTOPLAN Create Variant Field Renderer";
  var COMPONENT_VERSION = "0.3.0";
  var READY_ATTR = "data-vp-create-variant-field-renderer-ready";

  var DRAWER_SELECTOR = "[data-vp-variant-drawer-root='true'], [data-vp-variant-drawer='true']";
  var FIELD_SELECTOR = "[data-vp-variant-field='true']";

  var CONTROL_SELECTOR = [
    "[data-vp-field-input='true']",
    "[data-vp-field-control-input='true']",
    "[data-vp-definition-value-key]",
    "[name^='definition_values[']"
  ].join(",");

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

    toArrayOrObjectValues: function (value) {
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

        if (value === null || value === undefined) {
          node.removeAttribute(name);
        } else {
          node.setAttribute(name, String(value));
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

        var nextValue = value === null || value === undefined ? "" : String(value);

        if (node.type === "checkbox") {
          var nextChecked = !!value;

          if (node.checked === nextChecked && node.value === (nextChecked ? "true" : "false")) {
            return false;
          }

          node.checked = nextChecked;
          node.value = nextChecked ? "true" : "false";
        } else {
          if (node.value === nextValue) {
            return false;
          }

          node.value = nextValue;
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

    setHidden: function (node, hidden) {
      try {
        if (!node) {
          return false;
        }

        node.hidden = !!hidden;

        if (hidden) {
          node.setAttribute("hidden", "");
          node.setAttribute("aria-hidden", "true");
        } else {
          node.removeAttribute("hidden");
          node.setAttribute("aria-hidden", "false");
        }

        return true;
      } catch (error) {
        return false;
      }
    },

    setDisabled: function (node, disabled) {
      try {
        if (!node) {
          return false;
        }

        node.disabled = !!disabled;

        if (disabled) {
          node.setAttribute("aria-disabled", "true");
        } else {
          node.removeAttribute("aria-disabled");
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
              if (value[attrKey] === null || value[attrKey] === undefined) {
                return;
              }

              node.setAttribute(attrKey, String(value[attrKey]));
            });
          } else if (key === "hidden") {
            node.hidden = !!value;

            if (value) {
              node.setAttribute("hidden", "");
            }
          } else if (key === "disabled") {
            node.disabled = !!value;
          } else if (key in node) {
            try {
              node[key] = value;
            } catch (innerError) {
              node.setAttribute(key, String(value));
            }
          } else if (value !== null && value !== undefined) {
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
        var parsed = parseFloat(String(value).replace(",", "."));
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

    slugify: function (value, fallback) {
      try {
        var slug = String(value || "")
          .trim()
          .toLowerCase()
          .replace(/ä/g, "ae")
          .replace(/ö/g, "oe")
          .replace(/ü/g, "ue")
          .replace(/ß/g, "ss")
          .replace(/[^a-z0-9]+/g, "_")
          .replace(/^_+|_+$/g, "")
          .replace(/_{2,}/g, "_");

        if (!slug) {
          slug = fallback || "field";
        }

        if (!/^[a-z]/.test(slug)) {
          slug = "v_" + slug;
        }

        return slug;
      } catch (error) {
        return fallback || "field";
      }
    },

    normalizeFieldKey: function (value) {
      try {
        return String(value || "").trim().replace(/\s+/g, "").replace(/[^a-zA-Z0-9_.-]/g, "");
      } catch (error) {
        return "";
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
          object_kinds: fallbackUtils.toArrayOrObjectValues(defs.object_kinds || defs.objectKinds),
          family_profiles: fallbackUtils.toArrayOrObjectValues(defs.family_profiles || defs.familyProfiles),
          variant_profiles: fallbackUtils.toArrayOrObjectValues(defs.variant_profiles || defs.variantProfiles),
          variables: fallbackUtils.toArrayOrObjectValues(defs.variables),
          units: fallbackUtils.toArrayOrObjectValues(defs.units),
          materials: fallbackUtils.toArrayOrObjectValues(defs.materials),
          document_types: fallbackUtils.toArrayOrObjectValues(defs.document_types || defs.documentTypes),
          profile_bindings: fallbackUtils.toArrayOrObjectValues(defs.profile_bindings || defs.profileBindings)
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
          variablesById: fallbackUtils.indexBy(defs.variables, "id"),
          unitsById: fallbackUtils.indexBy(defs.units, "id"),
          unitsBySymbol: fallbackUtils.indexBy(defs.units, "symbol"),
          materialsById: fallbackUtils.indexBy(defs.materials, "id"),
          documentTypesById: fallbackUtils.indexBy(defs.document_types, "id")
        };
      } catch (error) {
        return {
          variantProfilesById: {},
          variablesByKey: {},
          variablesById: {},
          unitsById: {},
          unitsBySymbol: {},
          materialsById: {},
          documentTypesById: {}
        };
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

        node.dispatchEvent(new Event(eventName, {
          bubbles: true,
          cancelable: false
        }));

        return true;
      } catch (error) {
        return false;
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

    getProfileFieldKeys: function (profile) {
      try {
        var seen = {};
        var keys = [];

        fallbackUtils.toArray(profile && profile.sections).forEach(function (section) {
          fallbackUtils.toArray(section && section.fields).forEach(function (field) {
            var fieldKey = typeof field === "string"
              ? field
              : field && (field.key || field.field_key || field.variable_key || field.id);

            fieldKey = fallbackUtils.normalizeFieldKey(fieldKey);

            if (fieldKey && !seen[fieldKey]) {
              seen[fieldKey] = true;
              keys.push(fieldKey);
            }
          });
        });

        fallbackUtils.toArray(profile && profile.required_fields).forEach(function (fieldKey) {
          fieldKey = fallbackUtils.normalizeFieldKey(fieldKey);

          if (fieldKey && !seen[fieldKey]) {
            seen[fieldKey] = true;
            keys.push(fieldKey);
          }
        });

        fallbackUtils.toArray(profile && profile.optional_fields).forEach(function (fieldKey) {
          fieldKey = fallbackUtils.normalizeFieldKey(fieldKey);

          if (fieldKey && !seen[fieldKey]) {
            seen[fieldKey] = true;
            keys.push(fieldKey);
          }
        });

        return keys;
      } catch (error) {
        return [];
      }
    },

    getSectionFieldKeys: function (profile) {
      try {
        var seen = {};
        var keys = [];

        fallbackUtils.toArray(profile && profile.sections).forEach(function (section) {
          fallbackUtils.toArray(section && section.fields).forEach(function (field) {
            var fieldKey = typeof field === "string"
              ? field
              : field && (field.key || field.field_key || field.variable_key || field.id);

            fieldKey = fallbackUtils.normalizeFieldKey(fieldKey);

            if (fieldKey && !seen[fieldKey]) {
              seen[fieldKey] = true;
              keys.push(fieldKey);
            }
          });
        });

        return keys;
      } catch (error) {
        return [];
      }
    },

    getAdditionalFieldKeys: function (profile) {
      try {
        var sectionKeys = {};
        var output = [];

        fallbackUtils.getSectionFieldKeys(profile).forEach(function (fieldKey) {
          sectionKeys[fieldKey] = true;
        });

        fallbackUtils.getProfileFieldKeys(profile).forEach(function (fieldKey) {
          if (!sectionKeys[fieldKey]) {
            output.push(fieldKey);
          }
        });

        return output;
      } catch (error) {
        return [];
      }
    },

    isFieldRequired: function (profile, fieldKey) {
      try {
        return fallbackUtils.toArray(profile && profile.required_fields).indexOf(fieldKey) !== -1;
      } catch (error) {
        return false;
      }
    },

    shouldHideVariableInDrawer: function (variable) {
      try {
        if (!variable) {
          return false;
        }

        var key = variable.key || variable.variable_key || variable.id || "";

        if (key === "variant.variant_id" || key === "variant_id" || key === "id") {
          return true;
        }

        var metadata = variable.metadata || {};
        var ui = variable.ui || {};

        return fallbackUtils.bool(metadata.hide_in_create_drawer, false) ||
          fallbackUtils.bool(metadata.system_managed, false) ||
          fallbackUtils.bool(variable.system_managed || variable.systemManaged, false) ||
          ui.hidden === true ||
          ui.visible === false;
      } catch (error) {
        return false;
      }
    },

    normalizeValueForVariable: function (value, variable) {
      try {
        var type = variable && (variable.value_type || variable.valueType || variable.type) ? String(variable.value_type || variable.valueType || variable.type) : "";

        if (type === "boolean" || type === "bool") {
          return fallbackUtils.bool(value, false);
        }

        if (type === "integer" || type === "int") {
          if (value === "" || value === null || value === undefined) {
            return null;
          }

          return fallbackUtils.intValue(value, null);
        }

        if (type === "number" || type === "money" || type === "float" || type === "decimal") {
          if (value === "" || value === null || value === undefined) {
            return null;
          }

          return fallbackUtils.floatValue(value, null);
        }

        if (type === "document_list" || type === "array") {
          if (Array.isArray(value)) {
            return value;
          }

          return fallbackUtils.safeJsonParse(value, []);
        }

        if (type === "object") {
          if (value && typeof value === "object") {
            return value;
          }

          return fallbackUtils.safeJsonParse(value, value);
        }

        return value === null || value === undefined ? "" : value;
      } catch (error) {
        return value;
      }
    },

    defaultValueForVariable: function (variable) {
      try {
        if (!variable) {
          return null;
        }

        if (Object.prototype.hasOwnProperty.call(variable, "default_value")) {
          return fallbackUtils.deepClone(variable.default_value, variable.default_value);
        }

        if (Object.prototype.hasOwnProperty.call(variable, "defaultValue")) {
          return fallbackUtils.deepClone(variable.defaultValue, variable.defaultValue);
        }

        var type = variable.value_type || variable.valueType || variable.type || "string";

        if (type === "boolean" || type === "bool") {
          return false;
        }

        if (type === "number" || type === "integer" || type === "int" || type === "money" || type === "float" || type === "decimal") {
          return null;
        }

        if (type === "document_list" || type === "array") {
          return [];
        }

        if (type === "object") {
          return {};
        }

        return "";
      } catch (error) {
        return null;
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
    lastProfile: null,
    lastValues: {},
    lastDefinitions: null,
    lastBundle: null,
    cache: {
      drawers: [],
      definitions: null,
      maps: null
    }
  };

  /* ---------------------------------------------------------------------------
   * Definitions / maps
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

      if (!definitions && window.VectoplanCreateDefinitionCatalogs) {
        definitions = window.VectoplanCreateDefinitionCatalogs;
      }

      if (!definitions && window.VectoplanCreateContext && window.VectoplanCreateContext.definitions) {
        definitions = window.VectoplanCreateContext.definitions;
      }

      if (!definitions && window.VectoplanCreateContext && window.VectoplanCreateContext.definitionCatalogs) {
        definitions = window.VectoplanCreateContext.definitionCatalogs;
      }

      if (!definitions && window.VectoplanCreateContext && window.VectoplanCreateContext.definition_catalogs) {
        definitions = window.VectoplanCreateContext.definition_catalogs;
      }

      runtime.cache.definitions = U().normalizeDefinitions(definitions || {});
      runtime.cache.maps = U().buildDefinitionMaps(runtime.cache.definitions);

      return runtime.cache.definitions;
    } catch (error) {
      warn("Could not get renderer definitions.", error);
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
      warn("Could not build renderer maps.", error);
      return U().buildDefinitionMaps({});
    }
  }

  function getProfileById(profileId) {
    try {
      if (!profileId) {
        return null;
      }

      return getMaps().variantProfilesById[profileId] || null;
    } catch (error) {
      return null;
    }
  }

  function getVariable(fieldKey) {
    try {
      var key = U().normalizeFieldKey(fieldKey);
      var maps = getMaps();

      return maps.variablesByKey[key] || maps.variablesById[key] || null;
    } catch (error) {
      return null;
    }
  }

  function getUnit(unitId) {
    try {
      if (!unitId) {
        return null;
      }

      var maps = getMaps();

      return maps.unitsById[unitId] || maps.unitsBySymbol[unitId] || null;
    } catch (error) {
      return null;
    }
  }

  function getMaterialOptions(context) {
    try {
      var defs = getDefinitions();
      var materials = U().toArray(defs.materials);

      if (U().filterCompatibleMaterials) {
        return U().filterCompatibleMaterials(
          materials,
          context && context.family_profile_id ? context.family_profile_id : "",
          context && context.variant_profile_id ? context.variant_profile_id : ""
        );
      }

      return materials.filter(function (item) {
        return item && item.active !== false;
      });
    } catch (error) {
      return [];
    }
  }

  /* ---------------------------------------------------------------------------
   * Drawer cache / context
   * ------------------------------------------------------------------------ */

  function getDrawer(root) {
    try {
      if (root && root.nodeType === 1) {
        if (root.matches && root.matches(DRAWER_SELECTOR)) {
          return root;
        }

        var closest = root.closest ? root.closest(DRAWER_SELECTOR) : null;

        if (closest) {
          return closest;
        }
      }

      return U().qs(DRAWER_SELECTOR);
    } catch (error) {
      return null;
    }
  }

  function cacheDrawer(root) {
    try {
      var drawer = getDrawer(root);

      var optionalRoot = U().qs([
        "[data-vp-variant-optional-fields-root='true']",
        "[data-vp-variant-drawer-optional-fields='true']",
        "[data-vp-variant-drawer-additional-fields='true']"
      ].join(","), drawer);

      return {
        drawer: drawer,
        form: U().qs("[data-vp-variant-drawer-form='true']", drawer),
        fieldsRoot: U().qs("[data-vp-variant-drawer-fields='true']", drawer),
        fieldsHeader: U().qs("[data-vp-variant-drawer-fields-header='true']", drawer),
        fieldsEmpty: U().qs("[data-vp-variant-drawer-fields-empty='true']", drawer),
        sectionsRoot: U().qs("[data-vp-variant-drawer-sections='true']", drawer),

        optionalRoot: optionalRoot,

        legacyAdditionalRoot: U().qs("[data-vp-variant-drawer-profile-additional-fields='true'], [data-vp-variant-drawer-legacy-additional-fields='true']", drawer),
        legacyAdditionalGrid: U().qs("[data-vp-variant-drawer-additional-fields-grid='true']", drawer),

        sectionNav: U().qs("[data-vp-variant-drawer-section-nav='true']", drawer),
        sectionNavEmpty: U().qs("[data-vp-variant-drawer-section-nav-empty='true']", drawer),

        valuesJsonField: U().qs("[data-vp-variant-drawer-values-json-field='true']", drawer),
        originalValuesJsonField: U().qs("[data-vp-variant-drawer-original-values-json-field='true']", drawer),
        additionalKeysJsonField: U().qs("[data-vp-variant-drawer-additional-field-keys-json-field='true'], [data-vp-variant-drawer-additional-field-keys-json='true']", drawer),
        profileIdField: U().qs("[data-vp-variant-drawer-profile-id-field='true']", drawer),
        familyProfileIdField: U().qs("[data-vp-variant-drawer-family-profile-id-field='true']", drawer),
        variantIdField: U().qs("[data-vp-variant-drawer-variant-id-field='true']", drawer),

        title: U().qs("[data-vp-variant-drawer-title='true']", drawer),
        subtitle: U().qs("[data-vp-variant-drawer-subtitle='true']", drawer),
        statusText: U().qs("[data-vp-variant-drawer-status-text='true']", drawer),
        statusPill: U().qs("[data-vp-variant-drawer-status-pill='true']", drawer),

        summaryName: U().qs("[data-vp-variant-drawer-summary-name='true']", drawer),
        summaryId: U().qs("[data-vp-variant-drawer-summary-id='true']", drawer),
        summaryProfile: U().qs("[data-vp-variant-drawer-summary-profile='true']", drawer),
        dirtyState: U().qs("[data-vp-variant-drawer-dirty-state='true']", drawer)
      };
    } catch (error) {
      warn("Could not cache field renderer drawer.", error);

      return {
        drawer: root || null
      };
    }
  }

  function isCleanShell(cache) {
    try {
      var c = cache || cacheDrawer();
      var drawer = c.drawer;

      if (!drawer) {
        return false;
      }

      return drawer.classList.contains("vp-create-variant-drawer--shell-clean") ||
        U().attr(drawer, "data-vp-variant-drawer-shell", "") === "clean" ||
        U().attr(drawer, "data-vp-variant-drawer-layout", "") === "embedded";
    } catch (error) {
      return false;
    }
  }

  function applyCleanLayoutAttributes(cache, clean) {
    try {
      var c = cache || cacheDrawer();
      var isClean = clean === undefined ? isCleanShell(c) : !!clean;
      var sectionDisplay = isClean ? "flat" : "card";
      var navigationMode = isClean ? "hidden" : "nav";

      [
        c.drawer,
        c.fieldsRoot,
        c.sectionsRoot
      ].forEach(function (node) {
        if (!node) {
          return;
        }

        U().setAttr(node, "data-vp-clean-section-layout", isClean ? "flat" : "card");
        U().setAttr(node, "data-vp-section-display", sectionDisplay);
        U().setAttr(node, "data-vp-section-navigation-mode", navigationMode);
        U().setAttr(node, "data-vp-sections-render-mode", isClean ? "flat-all-visible" : "section-nav");

        if (node.classList) {
          node.classList.toggle("is-clean-section-layout", isClean);
          node.classList.toggle("is-card-section-layout", !isClean);
        }
      });

      if (c.sectionsRoot) {
        U().setAttr(c.sectionsRoot, "data-vp-clean-sections-root", isClean ? "true" : "false");
        U().setAttr(c.sectionsRoot, "data-vp-all-sections-visible", isClean ? "true" : "false");
      }

      U().qsa("[data-vp-variant-drawer-section='true']", c.sectionsRoot || c.drawer).forEach(function (section) {
        markSectionLayout(section, {
          cleanShell: isClean
        });
      });

      if (c.sectionNav && isClean) {
        U().setHidden(c.sectionNav, true);
      }

      return true;
    } catch (error) {
      warn("Could not apply clean section layout attributes.", error);
      return false;
    }
  }

  function markSectionLayout(sectionNode, options) {
    try {
      if (!sectionNode) {
        return false;
      }

      var config = options || {};
      var clean = !!config.cleanShell;

      U().setAttr(sectionNode, "data-vp-section-display", clean ? "flat" : "card");
      U().setAttr(sectionNode, "data-vp-clean-section-layout", clean ? "flat" : "card");
      U().setAttr(sectionNode, "data-vp-section-visible", "true");

      if (clean) {
        sectionNode.hidden = false;
        sectionNode.removeAttribute("hidden");
        sectionNode.setAttribute("aria-hidden", "false");
      }

      if (sectionNode.classList) {
        sectionNode.classList.toggle("vp-create-variant-drawer__section--flat", clean);
        sectionNode.classList.toggle("vp-create-variant-drawer__section--card", !clean);
        sectionNode.classList.toggle("is-flat-section", clean);
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function readDrawerContext(cache) {
    try {
      var c = cache || cacheDrawer();

      return {
        domain: U().attr(c.drawer, "data-vp-current-domain", ""),
        category: U().attr(c.drawer, "data-vp-current-category", ""),
        subcategory: U().attr(c.drawer, "data-vp-current-subcategory", ""),
        object_kind: U().attr(c.drawer, "data-vp-current-object-kind", "cell_block"),
        family_profile_id: U().attr(c.drawer, "data-vp-current-family-profile-id", "") || getNodeValue(c.familyProfileIdField, ""),
        variant_profile_id: U().attr(c.drawer, "data-vp-current-variant-profile-id", "") || getNodeValue(c.profileIdField, "")
      };
    } catch (error) {
      return {
        domain: "",
        category: "",
        subcategory: "",
        object_kind: "cell_block",
        family_profile_id: "",
        variant_profile_id: ""
      };
    }
  }

  function getNodeValue(node, fallback) {
    try {
      if (!node) {
        return fallback || "";
      }

      return "value" in node ? node.value || fallback || "" : node.textContent || fallback || "";
    } catch (error) {
      return fallback || "";
    }
  }

  /* ---------------------------------------------------------------------------
   * Field metadata
   * ------------------------------------------------------------------------ */

  function getFieldId(fieldKey) {
    try {
      return "vp-field-" + U().slugify(String(fieldKey || "").replace(/\./g, "_"), "field");
    } catch (error) {
      return "vp-field";
    }
  }

  function getVariableKey(variable) {
    try {
      return U().normalizeFieldKey(
        variable && (
          variable.key ||
          variable.variable_key ||
          variable.variableKey ||
          variable.path ||
          variable.id ||
          variable.name ||
          ""
        )
      );
    } catch (error) {
      return "";
    }
  }

  function getVariableLabel(variable, fallbackKey) {
    try {
      return String(
        variable && (
          variable.label ||
          variable.display_label ||
          variable.displayLabel ||
          variable.title ||
          variable.name
        ) ||
        fallbackKey ||
        "Feld"
      );
    } catch (error) {
      return fallbackKey || "Feld";
    }
  }

  function getWidget(variable) {
    try {
      if (!variable) {
        return "input";
      }

      var ui = variable.ui || {};
      var widget = variable.widget || ui.widget || "";

      if (widget) {
        return U().lower(widget);
      }

      var type = getValueType(variable);

      if (type === "boolean" || type === "bool") {
        return "checkbox";
      }

      if (type === "enum" || type === "select") {
        return "select";
      }

      if (type === "number" || type === "integer" || type === "int" || type === "float" || type === "decimal") {
        return "number";
      }

      if (type === "money") {
        return "money";
      }

      if (type === "date") {
        return "date";
      }

      if (type === "url") {
        return "url";
      }

      if (type === "text" || type === "long_text" || type === "textarea" || type === "markdown") {
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

  function getValueType(variable) {
    try {
      if (!variable) {
        return "string";
      }

      return U().lower(
        variable.value_type ||
        variable.valueType ||
        variable.data_type ||
        variable.dataType ||
        variable.type ||
        "string"
      );
    } catch (error) {
      return "string";
    }
  }

  function getUnitId(variable) {
    try {
      if (!variable) {
        return "";
      }

      return String(
        variable.unit ||
        variable.unit_id ||
        variable.unitId ||
        variable.default_unit ||
        variable.defaultUnit ||
        ""
      ).trim();
    } catch (error) {
      return "";
    }
  }

  function getUnitSymbol(variable) {
    try {
      var unitId = getUnitId(variable);

      if (!unitId) {
        return "";
      }

      var unit = getUnit(unitId);

      if (!unit) {
        return unitId;
      }

      return unit.symbol || unit.label || unit.name || unit.id || unitId;
    } catch (error) {
      return "";
    }
  }

  function getFieldValue(values, fieldKey, variable) {
    try {
      if (values && Object.prototype.hasOwnProperty.call(values, fieldKey)) {
        return values[fieldKey];
      }

      if (variable) {
        return U().defaultValueForVariable(variable);
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function isRequired(profile, fieldKey) {
    try {
      return U().isFieldRequired
        ? U().isFieldRequired(profile, fieldKey)
        : U().toArray(profile && profile.required_fields).indexOf(fieldKey) !== -1;
    } catch (error) {
      return false;
    }
  }

  function shouldHideField(variable) {
    try {
      if (!variable) {
        return false;
      }

      if (U().shouldHideVariableInDrawer) {
        return U().shouldHideVariableInDrawer(variable);
      }

      return getVariableKey(variable) === "variant.variant_id";
    } catch (error) {
      return false;
    }
  }

  function getOptionsForVariable(variable, context) {
    try {
      if (!variable) {
        return [];
      }

      if (getVariableKey(variable) === "material.type" && variable.metadata && variable.metadata.references_dataset === "materials") {
        var materials = getMaterialOptions(context);

        if (materials.length) {
          return materials.map(function (material) {
            return {
              id: material.id,
              value: material.id,
              label: material.label || material.id,
              description: material.description || ""
            };
          });
        }
      }

      var options = variable.options ||
        variable.enum ||
        variable.enum_values ||
        variable.enumValues ||
        variable.allowed_values ||
        variable.allowedValues ||
        [];

      return U().toArray(options);
    } catch (error) {
      return [];
    }
  }

  /* ---------------------------------------------------------------------------
   * Clear / status
   * ------------------------------------------------------------------------ */

  function setStatus(cache, state, message) {
    try {
      var c = cache || cacheDrawer();

      if (c.drawer) {
        U().setAttr(c.drawer, "data-vp-variant-fields-state", state || "idle");
      }

      if (c.statusPill) {
        c.statusPill.className = "vp-create-variant-drawer__status-pill vp-create-variant-drawer__status-pill--" + String(state || "idle");
        c.statusPill.textContent = state === "rendering"
          ? "Rendert"
          : state === "ready"
            ? "Bereit"
            : state === "error"
              ? "Fehler"
              : "Bereit";
      }

      if (c.statusText && message) {
        c.statusText.textContent = message;
      }
    } catch (error) {
      warn("Could not set renderer status.", error);
    }
  }

  function clearFields(root, options) {
    try {
      var c = cacheDrawer(root);
      var config = options || {};

      U().empty(c.sectionsRoot);
      U().empty(c.legacyAdditionalGrid);
      U().empty(c.sectionNav);

      if (c.legacyAdditionalRoot) {
        U().setHidden(c.legacyAdditionalRoot, true);
      }

      applyCleanLayoutAttributes(c, isCleanShell(c));

      if (c.sectionNav) {
        U().setHidden(c.sectionNav, isCleanShell(c));
      }

      if (c.fieldsEmpty) {
        U().setHidden(c.fieldsEmpty, false);
      }

      if (c.fieldsRoot) {
        U().setAttr(c.fieldsRoot, "data-vp-variant-drawer-fields-state", "empty");
      }

      if (c.sectionNavEmpty && c.sectionNav && !isCleanShell(c)) {
        c.sectionNav.appendChild(c.sectionNavEmpty);
        U().setHidden(c.sectionNavEmpty, false);
      }

      if (c.valuesJsonField && config.clearValues !== false) {
        setFieldValueSilently(c.valuesJsonField, "{}");
      }

      runtime.lastProfile = null;
      runtime.lastValues = {};

      U().dispatchDocument("vectoplan:create:variant-fields-cleared", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        reason: config.reason || "manual"
      });

      return true;
    } catch (error) {
      warn("Could not clear variant fields.", error);
      return false;
    }
  }

  function setFieldValueSilently(field, value) {
    try {
      if (!field) {
        return false;
      }

      var nextValue = value === null || value === undefined ? "" : String(value);

      if (field.value === nextValue) {
        return false;
      }

      field.value = nextValue;
      field.setAttribute("data-vp-programmatic-event-source", COMPONENT_NAME);
      field.setAttribute("data-vp-last-field-renderer-sync", String(Date.now()));
      return true;
    } catch (error) {
      return false;
    }
  }

  /* ---------------------------------------------------------------------------
   * Value collection / sync
   * ------------------------------------------------------------------------ */

  function normalizeValue(value, variable) {
    try {
      if (U().normalizeValueForVariable) {
        return U().normalizeValueForVariable(value, variable);
      }

      return value;
    } catch (error) {
      return value;
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

  function collectValues(root) {
    try {
      var c = cacheDrawer(root);
      var values = {};

      U().qsa(CONTROL_SELECTOR, c.drawer).forEach(function (control) {
        try {
          if (!control || control.disabled) {
            return;
          }

          var fieldKey = U().attr(control, "data-vp-field-key", "") ||
            U().attr(control, "data-vp-definition-value-key", "") ||
            keyFromDefinitionValueName(control.getAttribute("name") || "");

          var variable = getVariable(fieldKey);

          if (!fieldKey) {
            return;
          }

          var value;

          if (control.type === "checkbox") {
            value = !!control.checked;
          } else if (control.getAttribute("data-vp-document-list-json") === "true") {
            value = U().safeJsonParse(control.value || "[]", []);
          } else {
            value = control.value;
          }

          values[fieldKey] = normalizeValue(value, variable);
        } catch (fieldError) {
          warn("Could not collect field value.", fieldError);
        }
      });

      if (!values["variant.variant_id"] && c.variantIdField && c.variantIdField.value) {
        values["variant.variant_id"] = c.variantIdField.value;
      }

      runtime.lastValues = values;

      return values;
    } catch (error) {
      warn("Could not collect drawer values.", error);
      return {};
    }
  }

  function syncValuesJson(root, values, options) {
    try {
      var c = cacheDrawer(root);
      var config = options || {};
      var nextValues = values || collectValues(c.drawer);

      if (c.valuesJsonField) {
        if (config.emitNativeEvents === true) {
          U().setValue(c.valuesJsonField, U().valuesToJson(nextValues), true);
        } else {
          setFieldValueSilently(c.valuesJsonField, U().valuesToJson(nextValues));
        }
      }

      return nextValues;
    } catch (error) {
      warn("Could not sync drawer values JSON.", error);
      return values || {};
    }
  }

  function setDirty(root, dirty) {
    try {
      var c = cacheDrawer(root);
      var isDirty = !!dirty;

      if (c.drawer) {
        U().setAttr(c.drawer, "data-vp-variant-drawer-dirty", isDirty ? "true" : "false");
      }

      if (c.dirtyState) {
        U().setAttr(c.dirtyState, "data-vp-dirty", isDirty ? "true" : "false");
        c.dirtyState.textContent = isDirty ? "Ungespeicherte Änderungen" : "Keine ungespeicherten Änderungen";
      }
    } catch (error) {
      warn("Could not set drawer dirty state.", error);
    }
  }

  function dispatchValuesChanged(root, fieldKey, value, values, variable) {
    try {
      var c = cacheDrawer(root);
      var detail = {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        field_key: fieldKey || "",
        fieldKey: fieldKey || "",
        value: value,
        values: values || collectValues(c.drawer),
        variable: variable || (fieldKey ? getVariable(fieldKey) : null),
        profile: runtime.lastProfile,
        drawerId: c.drawer ? U().attr(c.drawer, "id", "") : ""
      };

      U().dispatchDocument("vectoplan:create:variant-values-changed", detail);

      if (fieldKey) {
        U().dispatchDocument("vectoplan:create:variant-field-changed", detail);
      }
    } catch (error) {
      warn("Could not dispatch values changed.", error);
    }
  }

  function handleInputChange(event) {
    try {
      var target = event && event.target ? event.target : null;

      if (!target || !target.matches || !target.matches(CONTROL_SELECTOR)) {
        return;
      }

      if (target.getAttribute("data-vp-programmatic-event-source") === COMPONENT_NAME) {
        return;
      }

      var fieldKey = U().attr(target, "data-vp-field-key", "") ||
        U().attr(target, "data-vp-definition-value-key", "") ||
        keyFromDefinitionValueName(target.getAttribute("name") || "");

      var variable = getVariable(fieldKey);
      var drawer = U().closest(target, DRAWER_SELECTOR);
      var value = target.type === "checkbox" ? !!target.checked : target.value;

      if (target.getAttribute("data-vp-document-list-json") === "true") {
        value = U().safeJsonParse(target.value || "[]", []);
      }

      var normalized = normalizeValue(value, variable);
      var values = collectValues(drawer);

      values[fieldKey] = normalized;
      syncValuesJson(drawer, values, {
        emitNativeEvents: false
      });
      setDirty(drawer, true);
      updateSystemSummaryFields(drawer, values);

      dispatchValuesChanged(drawer, fieldKey, normalized, values, variable);
    } catch (error) {
      warn("Field input/change handling failed.", error);
    }
  }

  function updateSystemSummaryFields(root, values) {
    try {
      var c = cacheDrawer(root);
      var name = values && values["variant.label"] ? values["variant.label"] : "";
      var id = values && values["variant.variant_id"] ? values["variant.variant_id"] : "";

      if (c.summaryName && name) {
        c.summaryName.textContent = name;
      }

      if (c.summaryId && id) {
        c.summaryId.textContent = id;
      }
    } catch (error) {
      warn("Could not update system summary fields.", error);
    }
  }

  /* ---------------------------------------------------------------------------
   * Field renderers
   * ------------------------------------------------------------------------ */

  function applyValidationAttributes(input, variable, required) {
    try {
      var validation = variable && variable.validation && typeof variable.validation === "object"
        ? variable.validation
        : {};

      if (required) {
        input.required = true;
        U().setAttr(input, "aria-required", "true");
      }

      if (validation.min !== undefined && validation.min !== null) {
        U().setAttr(input, "min", validation.min);
      }

      if (validation.minimum !== undefined && validation.minimum !== null) {
        U().setAttr(input, "min", validation.minimum);
      }

      if (validation.max !== undefined && validation.max !== null) {
        U().setAttr(input, "max", validation.max);
      }

      if (validation.maximum !== undefined && validation.maximum !== null) {
        U().setAttr(input, "max", validation.maximum);
      }

      if (validation.step !== undefined && validation.step !== null) {
        U().setAttr(input, "step", validation.step);
      }

      if (validation.min_length !== undefined && validation.min_length !== null) {
        U().setAttr(input, "minlength", validation.min_length);
      }

      if (validation.minLength !== undefined && validation.minLength !== null) {
        U().setAttr(input, "minlength", validation.minLength);
      }

      if (validation.max_length !== undefined && validation.max_length !== null) {
        U().setAttr(input, "maxlength", validation.max_length);
      }

      if (validation.maxLength !== undefined && validation.maxLength !== null) {
        U().setAttr(input, "maxlength", validation.maxLength);
      }

      if (validation.pattern) {
        U().setAttr(input, "pattern", validation.pattern);
      }

      if (variable && variable.placeholder && input.tagName && input.tagName.toLowerCase() !== "select") {
        U().setAttr(input, "placeholder", variable.placeholder);
      }

      if (variable && variable.ui && variable.ui.placeholder && input.tagName && input.tagName.toLowerCase() !== "select") {
        U().setAttr(input, "placeholder", variable.ui.placeholder);
      }
    } catch (error) {
      warn("Could not apply validation attributes.", error);
    }
  }

  function createBaseInput(fieldKey, variable, value, required, type) {
    try {
      var input = U().createElement("input", {
        class: "vp-create-input vp-create-variant-field__input",
        type: type || "text",
        value: value === null || value === undefined ? "" : value,
        id: getFieldId(fieldKey),
        attrs: {
          name: "definition_values[" + fieldKey + "]",
          "data-vp-field-input": "true",
          "data-vp-field-control-input": "true",
          "data-vp-definition-value-key": fieldKey,
          "data-vp-field-key": fieldKey,
          "data-vp-variable-key": fieldKey,
          "data-variable-key": fieldKey,
          "data-vp-field-widget": getWidget(variable),
          "data-vp-field-value-type": getValueType(variable),
          autocomplete: "off"
        }
      });

      applyValidationAttributes(input, variable, required);

      return input;
    } catch (error) {
      warn("Could not create base input.", error);
      return document.createElement("input");
    }
  }

  function renderTextInput(fieldKey, variable, value, required) {
    return createBaseInput(fieldKey, variable, value, required, "text");
  }

  function renderUrlInput(fieldKey, variable, value, required) {
    return createBaseInput(fieldKey, variable, value, required, "url");
  }

  function renderDateInput(fieldKey, variable, value, required) {
    return createBaseInput(fieldKey, variable, value, required, "date");
  }

  function renderNumberInput(fieldKey, variable, value, required) {
    try {
      var input = createBaseInput(fieldKey, variable, value, required, "number");

      if (!input.getAttribute("step")) {
        var type = getValueType(variable);
        U().setAttr(input, "step", type === "integer" || type === "int" ? "1" : "any");
      }

      return input;
    } catch (error) {
      warn("Could not create number input.", error);
      return createBaseInput(fieldKey, variable, value, required, "number");
    }
  }

  function renderMoneyInput(fieldKey, variable, value, required) {
    try {
      var wrapper = U().createElement("div", {
        class: "vp-create-variant-field__money"
      });

      var input = createBaseInput(fieldKey, variable, value, required, "number");
      var unit = getUnitSymbol(variable);

      if (!input.getAttribute("step")) {
        U().setAttr(input, "step", "0.01");
      }

      wrapper.appendChild(input);

      if (unit) {
        wrapper.appendChild(U().createElement("span", {
          class: "vp-create-variant-field__unit",
          text: unit,
          attrs: {
            "data-vp-field-unit": getUnitId(variable)
          }
        }));
      }

      return wrapper;
    } catch (error) {
      warn("Could not create money input.", error);
      return renderNumberInput(fieldKey, variable, value, required);
    }
  }

  function renderTextarea(fieldKey, variable, value, required) {
    try {
      var textareaValue = value;

      if (Array.isArray(value) || value && typeof value === "object") {
        textareaValue = U().safeJsonStringify(value, "", 2);
      }

      var textarea = U().createElement("textarea", {
        class: "vp-create-textarea vp-create-variant-field__textarea",
        id: getFieldId(fieldKey),
        text: textareaValue === null || textareaValue === undefined ? "" : textareaValue,
        attrs: {
          name: "definition_values[" + fieldKey + "]",
          "data-vp-field-input": "true",
          "data-vp-field-control-input": "true",
          "data-vp-definition-value-key": fieldKey,
          "data-vp-field-key": fieldKey,
          "data-vp-variable-key": fieldKey,
          "data-variable-key": fieldKey,
          "data-vp-field-widget": getWidget(variable),
          "data-vp-field-value-type": getValueType(variable),
          rows: "4",
          autocomplete: "off"
        }
      });

      applyValidationAttributes(textarea, variable, required);

      return textarea;
    } catch (error) {
      warn("Could not create textarea.", error);
      return document.createElement("textarea");
    }
  }

  function renderCheckbox(fieldKey, variable, value, required) {
    try {
      var checkboxId = getFieldId(fieldKey);

      var input = U().createElement("input", {
        class: "vp-create-checkbox vp-create-variant-field__checkbox-input",
        type: "checkbox",
        checked: U().bool(value, false),
        id: checkboxId,
        value: "true",
        attrs: {
          name: "definition_values[" + fieldKey + "]",
          "data-vp-field-input": "true",
          "data-vp-field-control-input": "true",
          "data-vp-definition-value-key": fieldKey,
          "data-vp-field-key": fieldKey,
          "data-vp-variable-key": fieldKey,
          "data-variable-key": fieldKey,
          "data-vp-field-widget": getWidget(variable),
          "data-vp-field-value-type": getValueType(variable)
        }
      });

      applyValidationAttributes(input, variable, required);

      var label = U().createElement("label", {
        class: "vp-create-variant-field__checkbox",
        attrs: {
          for: checkboxId
        }
      }, [
        input,
        U().createElement("span", {
          class: "vp-create-variant-field__checkbox-label",
          text: "Aktiv"
        })
      ]);

      return label;
    } catch (error) {
      warn("Could not create checkbox.", error);
      return createBaseInput(fieldKey, variable, value, required, "checkbox");
    }
  }

  function renderSelect(fieldKey, variable, value, required, context) {
    try {
      var select = U().createElement("select", {
        class: "vp-create-select vp-create-variant-field__select",
        id: getFieldId(fieldKey),
        attrs: {
          name: "definition_values[" + fieldKey + "]",
          "data-vp-field-input": "true",
          "data-vp-field-control-input": "true",
          "data-vp-definition-value-key": fieldKey,
          "data-vp-field-key": fieldKey,
          "data-vp-variable-key": fieldKey,
          "data-variable-key": fieldKey,
          "data-vp-field-widget": getWidget(variable),
          "data-vp-field-value-type": getValueType(variable),
          autocomplete: "off"
        }
      });

      applyValidationAttributes(select, variable, required);

      var options = getOptionsForVariable(variable, context);

      if (!required) {
        select.appendChild(U().createElement("option", {
          value: "",
          text: "Nicht angegeben"
        }));
      }

      options.forEach(function (option) {
        try {
          var optionValue = U().optionValue(option);
          var optionLabel = U().optionLabel(option);

          var optionNode = U().createElement("option", {
            value: optionValue,
            text: optionLabel || optionValue
          });

          if (String(optionValue) === String(value || "")) {
            optionNode.selected = true;
          }

          if (option && option.description) {
            U().setAttr(optionNode, "title", option.description);
          }

          select.appendChild(optionNode);
        } catch (optionError) {
          warn("Could not render select option.", optionError);
        }
      });

      return select;
    } catch (error) {
      warn("Could not create select.", error);
      return renderTextInput(fieldKey, variable, value, required);
    }
  }

  function normalizeDocumentList(value) {
    try {
      if (Array.isArray(value)) {
        return value;
      }

      var parsed = U().safeJsonParse(value, []);

      if (Array.isArray(parsed)) {
        return parsed;
      }

      return [];
    } catch (error) {
      return [];
    }
  }

  function createDocumentRow(fieldKey, item, index) {
    try {
      var source = item || {};
      var row = U().createElement("div", {
        class: "vp-create-variant-document-row",
        attrs: {
          "data-vp-document-row": "true",
          "data-vp-document-row-index": String(index)
        }
      });

      var labelInput = U().createElement("input", {
        class: "vp-create-input vp-create-variant-document-row__label",
        type: "text",
        value: source.label || source.name || "",
        attrs: {
          placeholder: "Bezeichnung",
          "data-vp-document-field": "label",
          autocomplete: "off"
        }
      });

      var typeInput = U().createElement("input", {
        class: "vp-create-input vp-create-variant-document-row__type",
        type: "text",
        value: source.type || source.document_type || "",
        attrs: {
          placeholder: "Typ",
          "data-vp-document-field": "type",
          autocomplete: "off"
        }
      });

      var urlInput = U().createElement("input", {
        class: "vp-create-input vp-create-variant-document-row__url",
        type: "url",
        value: source.url || source.href || source.reference || "",
        attrs: {
          placeholder: "URL oder Referenz",
          "data-vp-document-field": "url",
          autocomplete: "off"
        }
      });

      var removeButton = U().createElement("button", {
        class: "vp-create-button vp-create-button--ghost vp-create-variant-document-row__remove",
        type: "button",
        text: "Entfernen",
        attrs: {
          "data-vp-document-remove": "true"
        }
      });

      row.appendChild(labelInput);
      row.appendChild(typeInput);
      row.appendChild(urlInput);
      row.appendChild(removeButton);

      return row;
    } catch (error) {
      warn("Could not create document row.", error);
      return U().createElement("div");
    }
  }

  function syncDocumentList(container) {
    try {
      var hidden = U().qs("[data-vp-document-list-json='true']", container);
      var rows = U().qsa("[data-vp-document-row='true']", container);
      var list = [];

      rows.forEach(function (row) {
        try {
          var item = {};

          U().qsa("[data-vp-document-field]", row).forEach(function (field) {
            var key = U().attr(field, "data-vp-document-field", "");
            item[key] = field.value || "";
          });

          if (item.label || item.type || item.url) {
            list.push(item);
          }
        } catch (rowError) {
          warn("Could not collect document row.", rowError);
        }
      });

      if (hidden) {
        hidden.value = U().safeJsonStringify(list, "[]");
        U().dispatchNative(hidden, "input");
        U().dispatchNative(hidden, "change");
      }

      return list;
    } catch (error) {
      warn("Could not sync document list.", error);
      return [];
    }
  }

  function renderDocumentList(fieldKey, variable, value, required) {
    try {
      var list = normalizeDocumentList(value);
      var container = U().createElement("div", {
        class: "vp-create-variant-document-list",
        attrs: {
          "data-vp-document-list": "true",
          "data-vp-field-key": fieldKey
        }
      });

      var rows = U().createElement("div", {
        class: "vp-create-variant-document-list__rows",
        attrs: {
          "data-vp-document-list-rows": "true"
        }
      });

      var hidden = U().createElement("input", {
        type: "hidden",
        value: U().safeJsonStringify(list, "[]"),
        attrs: {
          name: "definition_values[" + fieldKey + "]",
          "data-vp-field-input": "true",
          "data-vp-field-control-input": "true",
          "data-vp-definition-value-key": fieldKey,
          "data-vp-document-list-json": "true",
          "data-vp-field-key": fieldKey,
          "data-vp-variable-key": fieldKey,
          "data-variable-key": fieldKey,
          "data-vp-field-widget": getWidget(variable),
          "data-vp-field-value-type": getValueType(variable)
        }
      });

      list.forEach(function (item, index) {
        rows.appendChild(createDocumentRow(fieldKey, item, index));
      });

      if (!list.length) {
        rows.appendChild(createDocumentRow(fieldKey, {}, 0));
      }

      var addButton = U().createElement("button", {
        class: "vp-create-button vp-create-button--secondary vp-create-variant-document-list__add",
        type: "button",
        text: "Dokument hinzufügen",
        attrs: {
          "data-vp-document-add": "true"
        }
      });

      container.appendChild(hidden);
      container.appendChild(rows);
      container.appendChild(addButton);

      container.addEventListener("click", function (event) {
        try {
          var target = event.target;

          if (!target || !target.closest) {
            return;
          }

          if (target.closest("[data-vp-document-add='true']")) {
            event.preventDefault();
            rows.appendChild(createDocumentRow(fieldKey, {}, U().qsa("[data-vp-document-row='true']", rows).length));
            syncDocumentList(container);
            return;
          }

          if (target.closest("[data-vp-document-remove='true']")) {
            event.preventDefault();

            var row = target.closest("[data-vp-document-row='true']");
            if (row) {
              row.remove();
            }

            if (!U().qsa("[data-vp-document-row='true']", rows).length) {
              rows.appendChild(createDocumentRow(fieldKey, {}, 0));
            }

            syncDocumentList(container);
          }
        } catch (clickError) {
          warn("Document list click handling failed.", clickError);
        }
      });

      container.addEventListener("input", function () {
        syncDocumentList(container);
      });

      container.addEventListener("change", function () {
        syncDocumentList(container);
      });

      return container;
    } catch (error) {
      warn("Could not create document list.", error);
      return renderTextarea(fieldKey, variable, U().safeJsonStringify(value || [], "[]", 2), required);
    }
  }

  function renderControl(fieldKey, variable, value, required, context) {
    try {
      var widget = getWidget(variable);
      var type = getValueType(variable);
      var options = getOptionsForVariable(variable, context);

      if (widget === "textarea" || type === "text" || type === "long_text" || type === "markdown") {
        return renderTextarea(fieldKey, variable, value, required);
      }

      if (widget === "select" || type === "enum" || options.length) {
        return renderSelect(fieldKey, variable, value, required, context);
      }

      if (widget === "checkbox" || type === "boolean" || type === "bool") {
        return renderCheckbox(fieldKey, variable, value, required);
      }

      if (widget === "number" || type === "number" || type === "integer" || type === "int" || type === "float" || type === "decimal") {
        return renderNumberInput(fieldKey, variable, value, required);
      }

      if (widget === "money" || type === "money") {
        return renderMoneyInput(fieldKey, variable, value, required);
      }

      if (widget === "date" || type === "date") {
        return renderDateInput(fieldKey, variable, value, required);
      }

      if (widget === "url" || type === "url") {
        return renderUrlInput(fieldKey, variable, value, required);
      }

      if (widget === "document_list" || type === "document_list") {
        return renderDocumentList(fieldKey, variable, value, required);
      }

      return renderTextInput(fieldKey, variable, value, required);
    } catch (error) {
      warn("Could not render field control.", error);
      return renderTextInput(fieldKey, variable, value, required);
    }
  }

  function createFieldNode(fieldKeyOrConfig, profile, values, context) {
    try {
      if (fieldKeyOrConfig && typeof fieldKeyOrConfig === "object" && !Array.isArray(fieldKeyOrConfig)) {
        return createFieldNodeFromConfig(fieldKeyOrConfig);
      }

      return createProfileFieldNode(fieldKeyOrConfig, profile, values, context);
    } catch (error) {
      warn("Could not create field node.", error);
      return createMissingVariableField(String(fieldKeyOrConfig || ""));
    }
  }

  function createFieldNodeFromConfig(config) {
    try {
      var source = config || {};
      var variable = source.variable || source.definition || null;
      var key = U().normalizeFieldKey(source.key || source.fieldKey || source.field_key || getVariableKey(variable));

      if (!variable && key) {
        variable = getVariable(key);
      }

      if (!variable && key) {
        variable = {
          key: key,
          label: key,
          value_type: source.value_type || source.valueType || "string",
          widget: source.widget || "input"
        };
      }

      var profile = source.profile || runtime.lastProfile || {};
      var values = {};
      values[key] = source.value;

      return createProfileFieldNode(key, profile, values, source.context || readDrawerContext());
    } catch (error) {
      warn("Could not create field node from config.", error);
      return createMissingVariableField("");
    }
  }

  function createProfileFieldNode(fieldKey, profile, values, context) {
    try {
      var key = U().normalizeFieldKey(fieldKey);
      var variable = getVariable(key);

      if (!variable) {
        return createMissingVariableField(key);
      }

      if (shouldHideField(variable)) {
        return createHiddenSystemField(key, variable, getFieldValue(values, key, variable));
      }

      var required = isRequired(profile, key) || U().bool(variable.required_default || variable.requiredDefault || variable.required, false);
      var value = getFieldValue(values, key, variable);
      var widget = getWidget(variable);
      var type = getValueType(variable);
      var unitSymbol = getUnitSymbol(variable);

      var field = U().createElement("div", {
        class: "vp-create-variant-field vp-create-variant-field--" + widget + (required ? " vp-create-variant-field--required" : ""),
        attrs: {
          "data-vp-variant-field": "true",
          "data-vp-field-key": key,
          "data-vp-variable-key": key,
          "data-variable-key": key,
          "data-vp-field-widget": widget,
          "data-vp-field-value-type": type,
          "data-vp-field-required": required ? "true" : "false"
        }
      });

      var label = U().createElement("label", {
        class: "vp-create-variant-field__label",
        attrs: {
          for: getFieldId(key)
        }
      }, [
        U().createElement("span", {
          text: getVariableLabel(variable, key),
          attrs: {
            "data-vp-field-label": "true"
          }
        })
      ]);

      if (required) {
        label.appendChild(U().createElement("span", {
          class: "vp-create-variant-field__required",
          text: "*",
          attrs: {
            "data-vp-field-required-marker": "true",
            "aria-hidden": "true"
          }
        }));
      }

      if (unitSymbol) {
        label.appendChild(U().createElement("span", {
          class: "vp-create-variant-field__unit-label",
          text: unitSymbol,
          attrs: {
            "data-vp-field-unit": getUnitId(variable)
          }
        }));
      }

      var controlWrapper = U().createElement("div", {
        class: "vp-create-variant-field__control",
        attrs: {
          "data-vp-field-control": "true"
        }
      });

      controlWrapper.appendChild(renderControl(key, variable, value, required, context));

      field.appendChild(label);
      field.appendChild(controlWrapper);

      if (variable.description || variable.help_text || variable.helpText) {
        field.appendChild(U().createElement("p", {
          class: "vp-create-variant-field__description",
          text: variable.description || variable.help_text || variable.helpText,
          attrs: {
            "data-vp-field-description": "true"
          }
        }));
      }

      field.appendChild(U().createElement("p", {
        class: "vp-create-variant-field__error",
        attrs: {
          "data-vp-field-error": "true",
          "aria-live": "polite",
          hidden: "hidden"
        }
      }));

      return field;
    } catch (error) {
      warn("Could not create field node for " + fieldKey + ".", error);
      return createMissingVariableField(fieldKey);
    }
  }

  function createMissingVariableField(fieldKey) {
    try {
      return U().createElement("div", {
        class: "vp-create-variant-field vp-create-variant-field--missing",
        attrs: {
          "data-vp-variant-field": "true",
          "data-vp-field-key": fieldKey,
          "data-vp-field-missing": "true"
        }
      }, [
        U().createElement("strong", {
          text: fieldKey || "Unbekanntes Feld"
        }),
        U().createElement("p", {
          text: "Für diesen Field-Key existiert keine Variable Definition."
        })
      ]);
    } catch (error) {
      return document.createElement("div");
    }
  }

  function createHiddenSystemField(fieldKey, variable, value) {
    try {
      var input = U().createElement("input", {
        type: "hidden",
        value: value === null || value === undefined ? "" : value,
        attrs: {
          name: "definition_values[" + fieldKey + "]",
          "data-vp-field-input": "true",
          "data-vp-field-control-input": "true",
          "data-vp-definition-value-key": fieldKey,
          "data-vp-field-system-managed": "true",
          "data-vp-field-hidden-in-drawer": "true",
          "data-vp-field-key": fieldKey,
          "data-vp-variable-key": fieldKey,
          "data-variable-key": fieldKey,
          "data-vp-field-widget": getWidget(variable),
          "data-vp-field-value-type": getValueType(variable)
        }
      });

      return U().createElement("div", {
        class: "vp-create-variant-field vp-create-variant-field--system-hidden",
        hidden: true,
        attrs: {
          "data-vp-variant-field": "true",
          "data-vp-field-key": fieldKey,
          "data-vp-variable-key": fieldKey,
          "data-variable-key": fieldKey,
          "data-vp-field-system-managed": "true",
          "data-vp-field-hidden-in-drawer": "true"
        }
      }, [
        input
      ]);
    } catch (error) {
      return document.createElement("div");
    }
  }

  /* ---------------------------------------------------------------------------
   * Section renderers
   * ------------------------------------------------------------------------ */

  function getSectionColumns(section) {
    try {
      var columns = section && section.ui ? U().intValue(section.ui.columns, 1) : 1;

      if (columns < 1) {
        columns = 1;
      }

      if (columns > 4) {
        columns = 4;
      }

      return columns;
    } catch (error) {
      return 1;
    }
  }

  function normalizeSectionId(section, index) {
    try {
      var raw = section && (section.id || section.key || section.section_id || section.label) || "section_" + String(index + 1);
      return U().slugify(raw, "section_" + String(index + 1));
    } catch (error) {
      return "section_" + String(index + 1);
    }
  }

  function extractFieldKey(field) {
    try {
      return typeof field === "string"
        ? field
        : field && (field.key || field.field_key || field.variable_key || field.id);
    } catch (error) {
      return "";
    }
  }

  function normalizeRenderableSections(profile) {
    try {
      var sections = [];

      U().toArray(profile && profile.sections).forEach(function (section, index) {
        var fields = U().toArray(section && section.fields).map(extractFieldKey).filter(Boolean);

        if (!fields.length) {
          return;
        }

        sections.push(U().safeMerge(section, {
          id: section.id || section.key || "section_" + String(index + 1),
          label: section.label || section.title || "Abschnitt " + String(index + 1),
          fields: fields
        }));
      });

      if (sections.length) {
        return sections;
      }

      var fallbackKeys = [];

      if (U().getProfileFieldKeys) {
        fallbackKeys = U().getProfileFieldKeys(profile);
      }

      fallbackKeys = fallbackKeys.concat(U().toArray(profile && profile.required_fields));
      fallbackKeys = fallbackKeys.concat(U().toArray(profile && profile.optional_fields));
      fallbackKeys = fallbackKeys.filter(Boolean);

      var seen = {};
      fallbackKeys = fallbackKeys.filter(function (fieldKey) {
        if (seen[fieldKey]) {
          return false;
        }

        seen[fieldKey] = true;
        return true;
      });

      if (!fallbackKeys.length) {
        return [];
      }

      return [{
        id: "profile_fields",
        key: "profile_fields",
        label: "Profilfelder",
        title: "Profilfelder",
        description: "Felder aus dem Backend-Definitionsprofil.",
        fields: fallbackKeys,
        ui: {
          columns: 2
        }
      }];
    } catch (error) {
      warn("Could not normalize renderable sections.", error);
      return U().toArray(profile && profile.sections);
    }
  }

  function createSectionNode(section, profile, values, context, index, options) {
    try {
      var config = options || {};
      var clean = !!config.cleanShell;
      var sectionId = normalizeSectionId(section, index || 0);
      var columns = getSectionColumns(section);

      var sectionClass = [
        "vp-create-variant-drawer__section",
        "vp-create-variant-drawer__section--" + sectionId
      ];

      if (clean) {
        sectionClass.push("vp-create-variant-drawer__section--flat");
        sectionClass.push("is-flat-section");
      } else {
        sectionClass.push("vp-create-variant-drawer__section--card");
      }

      var sectionNode = U().createElement("section", {
        class: sectionClass.join(" "),
        attrs: {
          "data-vp-variant-drawer-section": "true",
          "data-vp-section-id": sectionId,
          "data-vp-section-index": String(index || 0),
          "data-vp-section-required": section.required ? "true" : "false",
          "data-vp-section-display": clean ? "flat" : "card",
          "data-vp-clean-section-layout": clean ? "flat" : "card",
          "data-vp-section-visible": "true",
          "aria-hidden": "false"
        }
      });

      var header = U().createElement("header", {
        class: "vp-create-variant-drawer__section-header"
      }, [
        U().createElement("h4", {
          text: section.label || section.title || sectionId,
          attrs: {
            "data-vp-section-label": "true"
          }
        })
      ]);

      if (section.description) {
        header.appendChild(U().createElement("p", {
          text: section.description,
          attrs: {
            "data-vp-section-description": "true"
          }
        }));
      }

      var grid = U().createElement("div", {
        class: "vp-create-variant-drawer__section-grid vp-create-variant-drawer__section-grid--cols-" + String(columns),
        attrs: {
          "data-vp-section-fields": "true",
          "data-vp-section-columns": String(columns),
          "data-vp-section-display": clean ? "flat" : "card"
        }
      });

      U().toArray(section.fields).forEach(function (field) {
        var fieldKey = extractFieldKey(field);

        if (fieldKey) {
          grid.appendChild(createProfileFieldNode(fieldKey, profile, values, context));
        }
      });

      sectionNode.appendChild(header);
      sectionNode.appendChild(grid);

      markSectionLayout(sectionNode, {
        cleanShell: clean
      });

      return sectionNode;
    } catch (error) {
      warn("Could not create section node.", error);
      return U().createElement("section");
    }
  }

  function createSectionNavItem(section, index) {
    try {
      var sectionId = normalizeSectionId(section, index || 0);

      return U().createElement("button", {
        class: "vp-create-variant-drawer__section-nav-item",
        type: "button",
        attrs: {
          "data-vp-variant-drawer-section-nav-item": "true",
          "data-vp-section-target": sectionId
        }
      }, [
        U().createElement("span", {
          text: section.label || section.title || sectionId,
          attrs: {
            "data-vp-section-nav-label": "true"
          }
        }),
        U().createElement("span", {
          class: "vp-create-variant-drawer__section-nav-state",
          attrs: {
            "data-vp-section-nav-state": "true"
          }
        })
      ]);
    } catch (error) {
      return U().createElement("button", {
        type: "button",
        text: "Abschnitt"
      });
    }
  }

  function renderSectionNav(cache, profile) {
    try {
      if (!cache.sectionNav) {
        return false;
      }

      U().empty(cache.sectionNav);

      if (isCleanShell(cache)) {
        U().setHidden(cache.sectionNav, true);
        return true;
      }

      var sections = normalizeRenderableSections(profile);

      if (!sections.length) {
        if (cache.sectionNavEmpty) {
          cache.sectionNav.appendChild(cache.sectionNavEmpty);
          U().setHidden(cache.sectionNavEmpty, false);
        }

        return true;
      }

      sections.forEach(function (section, index) {
        cache.sectionNav.appendChild(createSectionNavItem(section, index));
      });

      U().setHidden(cache.sectionNavEmpty, true);
      U().setHidden(cache.sectionNav, false);

      return true;
    } catch (error) {
      warn("Could not render section navigation.", error);
      return false;
    }
  }

  function renderLegacyAdditionalFields(cache, profile, values, context) {
    try {
      if (isCleanShell(cache)) {
        U().empty(cache.legacyAdditionalGrid);

        if (cache.legacyAdditionalRoot) {
          U().setHidden(cache.legacyAdditionalRoot, true);
        }

        return true;
      }

      var additionalKeys = U().getAdditionalFieldKeys
        ? U().getAdditionalFieldKeys(profile)
        : [];

      if (!cache.legacyAdditionalRoot || !cache.legacyAdditionalGrid) {
        return false;
      }

      U().empty(cache.legacyAdditionalGrid);

      if (!additionalKeys.length) {
        U().setHidden(cache.legacyAdditionalRoot, true);
        return true;
      }

      additionalKeys.forEach(function (fieldKey) {
        cache.legacyAdditionalGrid.appendChild(createProfileFieldNode(fieldKey, profile, values, context));
      });

      U().setHidden(cache.legacyAdditionalRoot, false);

      return true;
    } catch (error) {
      warn("Could not render legacy additional fields.", error);
      return false;
    }
  }

  function refreshOptionalFields(profile, values, context, source) {
    try {
      var optionalApi = window.VectoplanCreateVariantOptionalFields;

      if (!optionalApi || typeof optionalApi.refresh !== "function") {
        return false;
      }

      optionalApi.refresh({
        reason: source || "field_renderer",
        detail: {
          profile: profile,
          values: values,
          context: context
        },
        soft: true,
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not refresh optional fields runtime.", error);
      return false;
    }
  }

  /* ---------------------------------------------------------------------------
   * Render entrypoints
   * ------------------------------------------------------------------------ */

  function normalizeRenderInput(input) {
    try {
      var source = input || {};
      var profile = source.profile || source.variant_profile || source.variantProfile || null;
      var values = source.values || source.empty_values || source.emptyValues || {};

      if (!profile && source.variant_profile_id) {
        profile = getProfileById(source.variant_profile_id);
      }

      if (!profile && source.variantProfileId) {
        profile = getProfileById(source.variantProfileId);
      }

      if (!profile && source.profile_id) {
        profile = getProfileById(source.profile_id);
      }

      if (!values || typeof values !== "object" || Array.isArray(values)) {
        values = {};
      }

      if (source.current_values && typeof source.current_values === "object") {
        values = U().safeMerge(values, source.current_values);
      }

      if (source.definition_values && typeof source.definition_values === "object") {
        values = U().safeMerge(values, source.definition_values);
      }

      if (source.definitionValues && typeof source.definitionValues === "object") {
        values = U().safeMerge(values, source.definitionValues);
      }

      if (source.definition_values_json) {
        values = U().safeMerge(values, U().valuesFromJson(source.definition_values_json));
      }

      if (source.definitionValuesJson) {
        values = U().safeMerge(values, U().valuesFromJson(source.definitionValuesJson));
      }

      return {
        profile: profile,
        values: values,
        context: source.context || readDrawerContext(),
        source: source.source || "manual",
        raw: source
      };
    } catch (error) {
      return {
        profile: null,
        values: {},
        context: readDrawerContext(),
        source: "normalization_failed",
        raw: input || {}
      };
    }
  }

  function renderProfile(input, root) {
    try {
      var cache = cacheDrawer(root);
      var normalized = normalizeRenderInput(input);

      if (!cache.drawer || !cache.sectionsRoot) {
        throw {
          code: "drawer_not_found",
          message: "Variant Drawer wurde nicht gefunden."
        };
      }

      if (!normalized.profile) {
        throw {
          code: "profile_missing",
          message: "Kein Variant Profile für Rendering vorhanden."
        };
      }

      var profile = normalized.profile;
      var values = U().safeMerge(profile.default_values || profile.defaultValues || {}, normalized.values || {});
      var context = U().safeMerge(normalized.context || {}, {
        variant_profile_id: profile.id || normalized.context.variant_profile_id || ""
      });
      var cleanShell = isCleanShell(cache);
      var sections = normalizeRenderableSections(profile);

      runtime.lastProfile = profile;
      runtime.lastValues = values;
      runtime.lastBundle = normalized;

      U().dispatchDocument("vectoplan:create:variant-fields-render-started", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        profile: profile,
        values: values,
        context: context,
        cleanShell: cleanShell,
        source: normalized.source
      });

      setStatus(cache, "rendering", "Variant-Felder werden aufgebaut.");

      U().empty(cache.sectionsRoot);
      U().empty(cache.legacyAdditionalGrid);
      U().empty(cache.sectionNav);

      applyCleanLayoutAttributes(cache, cleanShell);

      sections.forEach(function (section, index) {
        cache.sectionsRoot.appendChild(createSectionNode(section, profile, values, context, index, {
          cleanShell: cleanShell
        }));
      });

      applyCleanLayoutAttributes(cache, cleanShell);
      renderLegacyAdditionalFields(cache, profile, values, context);
      renderSectionNav(cache, profile);

      if (cache.fieldsEmpty) {
        U().setHidden(cache.fieldsEmpty, true);
      }

      if (cache.fieldsRoot) {
        U().setAttr(cache.fieldsRoot, "data-vp-variant-drawer-fields-state", "ready");
        U().setAttr(cache.fieldsRoot, "data-vp-rendered-section-count", String(sections.length));
      }

      if (cache.drawer) {
        U().setAttr(cache.drawer, "data-vp-current-variant-profile-id", profile.id || "");
        U().setAttr(cache.drawer, "data-vp-rendered-section-count", String(sections.length));
      }

      if (cache.profileIdField) {
        setFieldValueSilently(cache.profileIdField, profile.id || "");
      }

      if (cache.valuesJsonField) {
        setFieldValueSilently(cache.valuesJsonField, U().valuesToJson(values));
      }

      if (cache.originalValuesJsonField && !cache.originalValuesJsonField.value) {
        setFieldValueSilently(cache.originalValuesJsonField, U().valuesToJson(values));
      }

      if (cache.title && profile.ui && profile.ui.drawer && profile.ui.drawer.title && !cleanShell) {
        cache.title.textContent = profile.ui.drawer.title;
      } else if (cache.title && profile.label && !cleanShell) {
        cache.title.textContent = profile.label;
      }

      if (cache.subtitle && profile.ui && profile.ui.drawer && profile.ui.drawer.subtitle && !cleanShell) {
        cache.subtitle.textContent = profile.ui.drawer.subtitle;
      } else if (cache.subtitle && profile.description && !cleanShell) {
        cache.subtitle.textContent = profile.description;
      }

      if (cache.summaryProfile) {
        cache.summaryProfile.textContent = profile.id || "auto";
      }

      updateSystemSummaryFields(cache.drawer, values);
      bindFieldEvents(cache.drawer);
      refreshOptionalFields(profile, values, context, normalized.source);

      setStatus(cache, "ready", "Variant-Felder bereit.");

      U().dispatchDocument("vectoplan:create:variant-fields-rendered", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        profile: profile,
        values: values,
        context: context,
        drawerId: cache.drawer ? U().attr(cache.drawer, "id", "") : "",
        cleanShell: cleanShell,
        sectionLayout: cleanShell ? "flat" : "card",
        sectionCount: sections.length,
        source: normalized.source
      });

      return {
        ok: true,
        profile: profile,
        values: values,
        context: context,
        cleanShell: cleanShell,
        sectionLayout: cleanShell ? "flat" : "card",
        sectionCount: sections.length
      };
    } catch (error) {
      warn("Could not render variant profile.", error);

      U().dispatchDocument("vectoplan:create:variant-field-render-failed", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        error: normalizeError(error),
        input: input || {}
      });

      var failedCache = cacheDrawer(root);
      setStatus(failedCache, "error", "Variant-Felder konnten nicht gerendert werden.");

      return {
        ok: false,
        error: normalizeError(error)
      };
    }
  }

  function renderResolvedProfile(result, root) {
    try {
      var source = result || {};
      var profile = source.variant_profile ||
        source.variantProfile ||
        source.profile ||
        null;

      var values = source.values ||
        source.empty_values ||
        source.emptyValues ||
        source.definition_values ||
        source.definitionValues ||
        {};

      if (!profile && source.variant_profile_id) {
        profile = getProfileById(source.variant_profile_id);
      }

      if (!profile && source.variantProfileId) {
        profile = getProfileById(source.variantProfileId);
      }

      if (
        (!values || !Object.keys(values).length) &&
        (source.variant_profile_id || source.variantProfileId) &&
        window.VectoplanCreateVariantProfiles &&
        typeof window.VectoplanCreateVariantProfiles.getEmptyVariantValues === "function"
      ) {
        window.VectoplanCreateVariantProfiles
          .getEmptyVariantValues(source.variant_profile_id || source.variantProfileId, source.context || readDrawerContext())
          .then(function (emptyResult) {
            renderProfile({
              profile: profile || getProfileById(source.variant_profile_id || source.variantProfileId),
              values: emptyResult.values || {},
              context: source.context || emptyResult.context || readDrawerContext(),
              source: "empty_values_after_resolve"
            }, root);
          })
          .catch(function (error) {
            warn("Could not fetch empty values after profile resolve.", error);

            renderProfile({
              profile: profile,
              values: values,
              context: source.context || readDrawerContext(),
              source: "resolve_without_empty_values"
            }, root);
          });

        return {
          ok: true,
          async: true
        };
      }

      return renderProfile({
        profile: profile,
        values: values,
        context: source.context || readDrawerContext(),
        source: source.source || "resolved_profile"
      }, root);
    } catch (error) {
      warn("Could not render resolved profile.", error);
      return {
        ok: false,
        error: normalizeError(error)
      };
    }
  }

  function renderCurrentProfile(options) {
    try {
      var config = options || {};

      if (
        window.VectoplanCreateVariantProfiles &&
        typeof window.VectoplanCreateVariantProfiles.getResolvedProfileBundle === "function"
      ) {
        return window.VectoplanCreateVariantProfiles
          .getResolvedProfileBundle(config.context || null, config)
          .then(function (bundle) {
            renderProfile({
              profile: bundle.variant_profile || bundle.profile,
              values: U().safeMerge(bundle.empty_values || {}, config.values || {}),
              context: bundle.context || config.context || readDrawerContext(),
              source: "resolved_bundle"
            }, config.root || null);

            return bundle;
          });
      }

      var context = readDrawerContext();
      var profile = getProfileById(context.variant_profile_id);

      return Promise.resolve(renderProfile({
        profile: profile,
        values: config.values || {},
        context: context,
        source: "local_current"
      }, config.root || null));
    } catch (error) {
      return Promise.reject(error);
    }
  }

  /* ---------------------------------------------------------------------------
   * Event binding
   * ------------------------------------------------------------------------ */

  function bindFieldEvents(root) {
    try {
      var drawer = getDrawer(root);

      if (!drawer || drawer.getAttribute("data-vp-variant-field-events-bound") === "true") {
        return;
      }

      drawer.addEventListener("input", handleInputChange);
      drawer.addEventListener("change", handleInputChange);

      drawer.addEventListener("click", function (event) {
        try {
          var target = event.target;

          if (!target || !target.closest) {
            return;
          }

          var navItem = target.closest("[data-vp-variant-drawer-section-nav-item='true']");

          if (!navItem || !drawer.contains(navItem)) {
            return;
          }

          if (isCleanShell(cacheDrawer(drawer))) {
            return;
          }

          event.preventDefault();

          var sectionId = U().attr(navItem, "data-vp-section-target", "");
          var section = U().qs("[data-vp-section-id='" + cssEscape(sectionId) + "']", drawer);

          if (section && typeof section.scrollIntoView === "function") {
            section.scrollIntoView({
              behavior: "smooth",
              block: "start"
            });
          }
        } catch (clickError) {
          warn("Section nav click failed.", clickError);
        }
      });

      U().setAttr(drawer, "data-vp-variant-field-events-bound", "true");
    } catch (error) {
      warn("Could not bind field events.", error);
    }
  }

  function extractValuesFromDetail(detail) {
    try {
      var source = detail || {};
      var payload = source.payload || source.session || source.variant || source.currentVariant || source;

      if (payload.valuesJson || payload.definition_values_json || payload.definitionValuesJson) {
        return U().valuesFromJson(payload.valuesJson || payload.definition_values_json || payload.definitionValuesJson);
      }

      if (payload.values && typeof payload.values === "object") {
        return payload.values;
      }

      if (payload.definition_values && typeof payload.definition_values === "object") {
        return payload.definition_values;
      }

      if (payload.definitionValues && typeof payload.definitionValues === "object") {
        return payload.definitionValues;
      }

      return {};
    } catch (error) {
      return {};
    }
  }

  function bindGlobalEvents() {
    try {
      if (runtime.globalEventsBound) {
        return;
      }

      document.addEventListener("vectoplan:create:variant-profile-resolved", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          renderResolvedProfile(detail);
        } catch (error) {
          warn("Profile resolved render listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-profile-loaded", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          renderResolvedProfile(detail);
        } catch (error) {
          warn("Profile loaded render listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-empty-values-ready", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var profile = detail.profile || getProfileById(detail.variant_profile_id || detail.variantProfileId || detail.profile_id);

          if (!profile) {
            return;
          }

          renderProfile({
            profile: profile,
            values: detail.values || {},
            context: detail.context || readDrawerContext(),
            source: "empty_values_ready"
          });
        } catch (error) {
          warn("Empty values render listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-drawer-opened", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var payload = detail.payload || detail.session || detail || {};
          var values = extractValuesFromDetail(detail);
          var profileId = payload.variantProfileId || payload.variant_profile_id || payload.profile_id || "";

          if (profileId) {
            var profile = getProfileById(profileId);

            if (profile) {
              renderProfile({
                profile: profile,
                values: values,
                context: readDrawerContext(),
                source: "drawer_opened_with_profile"
              });
              return;
            }
          }

          renderCurrentProfile({
            values: values,
            source: "drawer_opened"
          }).catch(function (error) {
            warn("Render current profile after drawer open failed.", error);
          });
        } catch (error) {
          warn("Drawer opened render listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-drawer-session-started", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var session = detail.session || detail.payload || {};
          var profileId = session.variant_profile_id || session.variantProfileId || "";
          var profile = profileId ? getProfileById(profileId) : null;

          if (profile) {
            renderProfile({
              profile: profile,
              values: session.definition_values || session.definitionValues || {},
              context: readDrawerContext(),
              source: "drawer_session_started"
            });
          }
        } catch (error) {
          warn("Drawer session started render listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-drawer-session-prepared", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var session = detail.session || detail.payload || {};
          var profile = session.variant_profile || session.variantProfile || session.profile || getProfileById(session.variant_profile_id || session.variantProfileId || "");

          if (profile) {
            renderProfile({
              profile: profile,
              values: session.definition_values || session.definitionValues || {},
              context: readDrawerContext(),
              source: "drawer_session_prepared"
            });
          }
        } catch (error) {
          warn("Drawer session prepared render listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:definitions-ready", function () {
        try {
          getDefinitions({
            force: true
          });
        } catch (error) {
          warn("Definitions ready cache refresh failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-definitions-retry-requested", function () {
        try {
          clearFields(null, {
            reason: "definitions_retry",
            clearValues: false
          });
        } catch (error) {
          warn("Definitions retry clear failed.", error);
        }
      });

      runtime.globalEventsBound = true;
    } catch (error) {
      warn("Could not bind field renderer global events.", error);
    }
  }

  /* ---------------------------------------------------------------------------
   * Error normalization
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

  function cssEscape(value) {
    try {
      if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(String(value));
      }

      return String(value || "").replace(/["\\]/g, "\\$&");
    } catch (error) {
      return String(value || "").replace(/["\\]/g, "\\$&");
    }
  }

  /* ---------------------------------------------------------------------------
   * Diagnostics / initialization
   * ------------------------------------------------------------------------ */

  function getRuntimeSnapshot() {
    try {
      var drawer = getDrawer();
      var cache = drawer ? cacheDrawer(drawer) : null;

      return {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        initialized: runtime.initialized,
        hasLastProfile: !!runtime.lastProfile,
        lastProfileId: runtime.lastProfile ? runtime.lastProfile.id : "",
        valueCount: runtime.lastValues ? Object.keys(runtime.lastValues).length : 0,
        cleanShell: cache ? isCleanShell(cache) : false,
        sectionLayout: cache && isCleanShell(cache) ? "flat" : "card",
        renderedSectionCount: cache && cache.sectionsRoot ? U().qsa("[data-vp-variant-drawer-section='true']", cache.sectionsRoot).length : 0,
        definitions: runtime.cache.definitions ? {
          variant_profiles: runtime.cache.definitions.variant_profiles.length,
          variables: runtime.cache.definitions.variables.length,
          units: runtime.cache.definitions.units.length,
          materials: runtime.cache.definitions.materials.length
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

      getDefinitions({
        force: !!config.force
      });

      bindGlobalEvents();

      U().qsa(DRAWER_SELECTOR).forEach(function (drawer) {
        bindFieldEvents(drawer);
        applyCleanLayoutAttributes(cacheDrawer(drawer), isCleanShell(cacheDrawer(drawer)));
      });

      runtime.initialized = true;

      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-field-renderer-version", COMPONENT_VERSION);

      U().dispatchDocument("vectoplan:create:variant-field-renderer-ready", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        snapshot: getRuntimeSnapshot()
      });

      return true;
    } catch (error) {
      warn("Could not initialize field renderer.", error);
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

    renderProfile: renderProfile,
    renderResolvedProfile: renderResolvedProfile,
    renderCurrentProfile: renderCurrentProfile,
    clearFields: clearFields,

    collectValues: collectValues,
    syncValuesJson: syncValuesJson,

    getDefinitions: getDefinitions,
    getMaps: getMaps,
    getProfileById: getProfileById,
    getVariable: getVariable,
    getUnit: getUnit,

    createFieldNode: createFieldNode,
    renderControl: renderControl,

    applyCleanLayoutAttributes: applyCleanLayoutAttributes,
    normalizeRenderableSections: normalizeRenderableSections,

    getRuntimeSnapshot: getRuntimeSnapshot
  };

  try {
    window[GLOBAL_NAME] = api;

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        initialize({
          source: "dom_content_loaded"
        });
      }, {
        once: true
      });
    } else {
      initialize({
        source: "immediate"
      });
    }
  } catch (bootstrapError) {
    warn("Could not bootstrap field renderer.", bootstrapError);
  }
})();