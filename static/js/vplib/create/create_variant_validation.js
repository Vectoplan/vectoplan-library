/* services/vectoplan-library/static/js/vplib/create/create_variant_validation.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateVariantValidation";
  var COMPONENT_NAME = "VECTOPLAN Create Variant Validation";
  var COMPONENT_VERSION = "0.7.0";
  var READY_ATTR = "data-vp-create-variant-validation-ready";

  var DRAWER_SELECTOR = "[data-vp-variant-drawer-root='true'], [data-vp-variant-drawer='true'], .vp-create-variant-drawer";
  var FIELD_SELECTOR = "[data-vp-variant-field='true']";
  var CONTROL_SELECTOR = [
    "[data-vp-field-input='true']",
    "[data-vp-field-control-input='true']",
    "[data-vp-definition-value-key]",
    "[name^='definition_values[']"
  ].join(",");

  var VALIDATE_ENDPOINT = "/api/v1/vplib/definitions/validate-variant";

  if (window[GLOBAL_NAME] && window[GLOBAL_NAME].__version === COMPONENT_VERSION) {
    try {
      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-validation-version", COMPONENT_VERSION);
    } catch (alreadyReadyError) {
      /* no-op */
    }

    return;
  }

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
        return selector ? (root || document).querySelector(selector) : null;
      } catch (error) {
        return null;
      }
    },

    qsa: function (selector, root) {
      try {
        return selector ? Array.prototype.slice.call((root || document).querySelectorAll(selector)) : [];
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

        if (value === null || value === undefined || value === "") {
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
          return node.checked;
        }

        if ("value" in node) {
          return node.value;
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

        if (node.type === "checkbox") {
          node.checked = !!value;
          node.value = node.checked ? "true" : "false";
        } else {
          node.value = value === null || value === undefined ? "" : String(value);
        }

        if (dispatchEvents) {
          fallbackUtils.dispatchNative(node, "input", {
            source: COMPONENT_NAME
          });
          fallbackUtils.dispatchNative(node, "change", {
            source: COMPONENT_NAME
          });
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

        node.textContent = value === null || value === undefined ? "" : String(value);
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
          } else if (key === "attrs" && value && typeof value === "object") {
            Object.keys(value).forEach(function (attrKey) {
              if (value[attrKey] !== null && value[attrKey] !== undefined) {
                node.setAttribute(attrKey, String(value[attrKey]));
              }
            });
          } else if (key === "hidden") {
            node.hidden = !!value;
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
        return isNaN(parsed) ? (fallback === undefined ? 0 : fallback) : parsed;
      } catch (error) {
        return fallback === undefined ? 0 : fallback;
      }
    },

    floatValue: function (value, fallback) {
      try {
        var parsed = parseFloat(String(value || "").replace(",", "."));
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

    dispatchNative: function (node, eventName, options) {
      try {
        if (!node) {
          return false;
        }

        if (node.setAttribute) {
          node.setAttribute("data-vp-programmatic-event", String(eventName));
          node.setAttribute("data-vp-programmatic-event-source", options && options.source ? options.source : COMPONENT_NAME);
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
          object_kinds: fallbackUtils.toArrayOrObjectValues(defs.object_kinds || defs.objectKinds),
          family_profiles: fallbackUtils.toArrayOrObjectValues(defs.family_profiles || defs.familyProfiles),
          variant_profiles: fallbackUtils.toArrayOrObjectValues(defs.variant_profiles || defs.variantProfiles),
          variables: fallbackUtils.toArrayOrObjectValues(defs.variables),
          units: fallbackUtils.toArrayOrObjectValues(defs.units),
          materials: fallbackUtils.toArrayOrObjectValues(defs.materials || defs.material_classes || defs.materialClasses),
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
          materialsById: fallbackUtils.indexBy(defs.materials, "id"),
          documentTypesById: fallbackUtils.indexBy(defs.document_types, "id")
        };
      } catch (error) {
        return {
          variantProfilesById: {},
          variablesByKey: {},
          variablesById: {},
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

        if (type === "document_list" || type === "documents" || type === "array") {
          if (Array.isArray(value)) {
            return value;
          }

          return fallbackUtils.safeJsonParse(value, []);
        }

        if (type === "object") {
          if (value && typeof value === "object") {
            return value;
          }

          return fallbackUtils.safeJsonParse(value, {});
        }

        return value === null || value === undefined ? "" : value;
      } catch (error) {
        return value;
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

  var runtime = {
    initialized: false,
    globalEventsBound: false,
    validationSeq: 0,
    validationInProgress: false,
    suppressedValidationCount: 0,
    lastProfile: null,
    lastValues: {},
    lastResult: null,
    lastValidatedAt: 0,
    lastValidationRequestId: "",
    lastValidationSignature: "",
    cache: {
      definitions: null,
      maps: null
    },
    options: {
      backendValidation: true,
      backendValidationMode: "after_local_valid",
      validateOnChange: false,
      validateOnOpen: false,
      showWarnings: true,
      warnUnknownFields: true,
      failOnMissingProfile: true
    }
  };

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
      warn("Could not read validation definitions.", error);
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
      warn("Could not build validation definition maps.", error);
      return U().buildDefinitionMaps({});
    }
  }

  function getVariable(fieldKey) {
    try {
      var maps = getMaps();

      return maps.variablesByKey[fieldKey] || maps.variablesById && maps.variablesById[fieldKey] || null;
    } catch (error) {
      return null;
    }
  }

  function getVariantProfile(profileId) {
    try {
      if (!profileId) {
        return null;
      }

      var profile = getMaps().variantProfilesById[profileId];

      if (profile) {
        return profile;
      }

      if (
        window.VectoplanCreateVariantProfiles &&
        typeof window.VectoplanCreateVariantProfiles.getVariantProfileLocal === "function"
      ) {
        var local = window.VectoplanCreateVariantProfiles.getVariantProfileLocal(profileId);

        if (local && local.ok) {
          return local.variant_profile || local.variantProfile || local.profile || null;
        }
      }

      return null;
    } catch (error) {
      return null;
    }
  }

  function getRequiredFields(profile) {
    try {
      return U().toArray(profile && (profile.required_fields || profile.requiredFields));
    } catch (error) {
      return [];
    }
  }

  function getProfileFields(profile) {
    try {
      if (U().getProfileFieldKeys) {
        return U().getProfileFieldKeys(profile);
      }

      var fields = [];
      var seen = {};

      function add(field) {
        var fieldKey = "";

        if (typeof field === "string") {
          fieldKey = field;
        } else if (field && typeof field === "object") {
          fieldKey = field.key || field.field_key || field.fieldKey || field.variable_key || field.variableKey || field.id || "";
        }

        if (fieldKey && !seen[fieldKey]) {
          seen[fieldKey] = true;
          fields.push(fieldKey);
        }
      }

      U().toArray(profile && profile.sections).forEach(function (section) {
        U().toArray(section && section.fields).forEach(add);
      });

      U().toArray(profile && (profile.required_fields || profile.requiredFields)).forEach(add);
      U().toArray(profile && (profile.optional_fields || profile.optionalFields)).forEach(add);
      U().toArray(profile && (profile.all_fields || profile.allFields)).forEach(add);

      return fields;
    } catch (error) {
      return [];
    }
  }

  function isRequired(profile, fieldKey, variable) {
    try {
      if (getRequiredFields(profile).indexOf(fieldKey) !== -1) {
        return true;
      }

      if (variable && U().bool(variable.required_default || variable.requiredDefault || variable.required, false)) {
        return true;
      }

      return false;
    } catch (error) {
      return false;
    }
  }

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

        var inside = U().qs(DRAWER_SELECTOR, root);

        if (inside) {
          return inside;
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

      return {
        drawer: drawer,
        valuesJsonField: U().qs("[data-vp-variant-drawer-values-json-field='true']", drawer),
        variantIdField: U().qs("[data-vp-variant-drawer-variant-id-field='true']", drawer),
        profileIdField: U().qs("[data-vp-variant-drawer-profile-id-field='true']", drawer),
        familyProfileIdField: U().qs("[data-vp-variant-drawer-family-profile-id-field='true']", drawer),
        validationRoot: U().qs("[data-vp-variant-drawer-validation='true']", drawer),
        validationList: U().qs("[data-vp-variant-drawer-validation-list='true']", drawer),
        validationCount: U().qs("[data-vp-variant-drawer-validation-count='true']", drawer),
        validationTitle: U().qs("[data-vp-variant-drawer-validation-title='true']", drawer),
        statusPill: U().qs("[data-vp-variant-drawer-status-pill='true']", drawer),
        statusText: U().qs("[data-vp-variant-drawer-status-text='true']", drawer),
        applyButton: U().qs("[data-vp-variant-drawer-apply='true']", drawer),
        validateButton: U().qs("[data-vp-variant-drawer-validate='true']", drawer)
      };
    } catch (error) {
      warn("Could not cache validation drawer.", error);

      return {
        drawer: root || null
      };
    }
  }

  function readDrawerValues(root) {
    try {
      var cache = cacheDrawer(root);

      if (
        window.VectoplanCreateVariantFieldRenderer &&
        typeof window.VectoplanCreateVariantFieldRenderer.collectValues === "function"
      ) {
        var collected = window.VectoplanCreateVariantFieldRenderer.collectValues(cache.drawer);

        if (collected && typeof collected === "object") {
          return collected;
        }
      }

      if (cache.valuesJsonField && cache.valuesJsonField.value) {
        return U().valuesFromJson(cache.valuesJsonField.value);
      }

      var values = {};

      U().qsa(CONTROL_SELECTOR, cache.drawer).forEach(function (control) {
        var fieldKey = U().attr(control, "data-vp-field-key", "") ||
          U().attr(control, "data-vp-definition-value-key", "") ||
          keyFromDefinitionValueName(control.getAttribute("name") || "");

        if (!fieldKey) {
          return;
        }

        if (control.type === "checkbox") {
          values[fieldKey] = !!control.checked;
        } else if (control.getAttribute("data-vp-document-list-json") === "true") {
          values[fieldKey] = U().safeJsonParse(control.value || "[]", []);
        } else {
          values[fieldKey] = control.value;
        }
      });

      return values;
    } catch (error) {
      warn("Could not read drawer values for validation.", error);
      return {};
    }
  }

  function readDrawerProfile(root) {
    try {
      var cache = cacheDrawer(root);
      var profileId = U().getValue(cache.profileIdField, "") ||
        U().attr(cache.drawer, "data-vp-current-variant-profile-id", "");

      if (!profileId && runtime.lastProfile && runtime.lastProfile.id) {
        return runtime.lastProfile;
      }

      return getVariantProfile(profileId);
    } catch (error) {
      return runtime.lastProfile || null;
    }
  }

  function readDrawerContext(root) {
    try {
      var cache = cacheDrawer(root);

      return {
        domain: U().attr(cache.drawer, "data-vp-current-domain", ""),
        category: U().attr(cache.drawer, "data-vp-current-category", ""),
        subcategory: U().attr(cache.drawer, "data-vp-current-subcategory", ""),
        object_kind: U().attr(cache.drawer, "data-vp-current-object-kind", "cell_block"),
        family_profile_id: U().getValue(cache.familyProfileIdField, "") ||
          U().attr(cache.drawer, "data-vp-current-family-profile-id", ""),
        variant_profile_id: U().getValue(cache.profileIdField, "") ||
          U().attr(cache.drawer, "data-vp-current-variant-profile-id", "")
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

  function buildVariantFromDrawer(root) {
    try {
      if (
        window.VectoplanCreateVariantDrawer &&
        typeof window.VectoplanCreateVariantDrawer.buildVariantFromDrawer === "function"
      ) {
        var fromDrawer = window.VectoplanCreateVariantDrawer.buildVariantFromDrawer();

        if (fromDrawer) {
          return fromDrawer;
        }
      }

      var cache = cacheDrawer(root);
      var values = readDrawerValues(cache.drawer);
      var profile = readDrawerProfile(cache.drawer);
      var context = readDrawerContext(cache.drawer);

      var variantId = values["variant.variant_id"] ||
        U().getValue(cache.variantIdField, "") ||
        "";

      var label = values["variant.label"] || "Neue Variante";

      return {
        variant_id: variantId,
        variantId: variantId,
        slug: variantId,
        label: label,
        name: label,
        description: values["variant.description"] || "",
        is_default: variantId === "default",
        isDefault: variantId === "default",
        kind: variantId === "default" ? "standard" : "profile",
        family_profile_id: context.family_profile_id || "",
        familyProfileId: context.family_profile_id || "",
        variant_profile_id: context.variant_profile_id || (profile ? profile.id || profile.profile_id || "" : ""),
        variantProfileId: context.variant_profile_id || (profile ? profile.id || profile.profile_id || "" : ""),
        definition_managed: true,
        definitionManaged: true,
        definition_values: values,
        definitionValues: values,
        definition_values_json: U().valuesToJson(values),
        definitionValuesJson: U().valuesToJson(values),
        definition_summary: ""
      };
    } catch (error) {
      warn("Could not build variant from drawer for validation.", error);
      return null;
    }
  }

  function normalizeVariantInput(input) {
    try {
      var source = input || {};

      if (source.variant) {
        source = source.variant;
      }

      var values = {};

      if (source.definition_values && typeof source.definition_values === "object") {
        values = U().deepClone(source.definition_values, {});
      } else if (source.definitionValues && typeof source.definitionValues === "object") {
        values = U().deepClone(source.definitionValues, {});
      } else if (source.values && typeof source.values === "object") {
        values = U().deepClone(source.values, {});
      } else if (source.definition_values_json) {
        values = U().valuesFromJson(source.definition_values_json);
      } else if (source.definitionValuesJson) {
        values = U().valuesFromJson(source.definitionValuesJson);
      } else if (source.valuesJson) {
        values = U().valuesFromJson(source.valuesJson);
      } else if (source.values_json) {
        values = U().valuesFromJson(source.values_json);
      }

      if (source.variant_id || source.variantId || source.slug) {
        values["variant.variant_id"] = source.variant_id || source.variantId || source.slug;
      }

      if (source.label || source.name) {
        values["variant.label"] = source.label || source.name;
      }

      if (source.description) {
        values["variant.description"] = source.description;
      }

      return {
        variant_id: source.variant_id || source.variantId || source.slug || values["variant.variant_id"] || "",
        variantId: source.variant_id || source.variantId || source.slug || values["variant.variant_id"] || "",
        label: source.label || source.name || values["variant.label"] || "",
        name: source.label || source.name || values["variant.label"] || "",
        description: source.description || values["variant.description"] || "",
        family_profile_id: source.family_profile_id || source.familyProfileId || "",
        familyProfileId: source.family_profile_id || source.familyProfileId || "",
        variant_profile_id: source.variant_profile_id || source.variantProfileId || source.profile_id || "",
        variantProfileId: source.variant_profile_id || source.variantProfileId || source.profile_id || "",
        definition_values: values,
        definitionValues: values,
        definition_values_json: U().valuesToJson(values),
        definitionValuesJson: U().valuesToJson(values),
        raw: input || {}
      };
    } catch (error) {
      return {
        variant_id: "",
        variantId: "",
        label: "",
        name: "",
        description: "",
        family_profile_id: "",
        familyProfileId: "",
        variant_profile_id: "",
        variantProfileId: "",
        definition_values: {},
        definitionValues: {},
        definition_values_json: "{}",
        definitionValuesJson: "{}",
        raw: input || {}
      };
    }
  }

  function isEmpty(value) {
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

  function valueType(variable) {
    try {
      return U().lower(variable && (variable.value_type || variable.valueType || variable.data_type || variable.dataType || variable.type || "string"));
    } catch (error) {
      return "string";
    }
  }

  function widgetType(variable) {
    try {
      return U().lower(variable && (variable.widget || variable.ui && variable.ui.widget || ""));
    } catch (error) {
      return "";
    }
  }

  function getOptionValues(variable) {
    try {
      var options = variable && (
        variable.options ||
        variable.enum ||
        variable.enum_values ||
        variable.enumValues ||
        variable.allowed_values ||
        variable.allowedValues
      );

      return U().toArray(options).map(function (option) {
        return U().optionValue(option);
      });
    } catch (error) {
      return [];
    }
  }

  function labelForField(fieldKey, variable) {
    try {
      return variable && (variable.label || variable.name) ? variable.label || variable.name : fieldKey || "Feld";
    } catch (error) {
      return fieldKey || "Feld";
    }
  }

  function makeIssue(level, code, fieldKey, variable, message, extra) {
    try {
      return U().safeMerge({
        level: level || "error",
        severity: level || "error",
        code: code || "invalid",
        field_key: fieldKey || "",
        fieldKey: fieldKey || "",
        label: labelForField(fieldKey, variable),
        message: message || "Ungültiger Wert."
      }, extra || {});
    } catch (error) {
      return {
        level: level || "error",
        severity: level || "error",
        code: code || "invalid",
        field_key: fieldKey || "",
        fieldKey: fieldKey || "",
        label: fieldKey || "Feld",
        message: message || "Ungültiger Wert."
      };
    }
  }

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

  function validateRequired(fieldKey, value, variable, required) {
    try {
      if (!required) {
        return null;
      }

      if (isEmpty(value)) {
        return makeIssue(
          "error",
          "required",
          fieldKey,
          variable,
          "Pflichtfeld ist nicht ausgefüllt."
        );
      }

      return null;
    } catch (error) {
      return makeIssue("error", "required_check_failed", fieldKey, variable, "Pflichtfeld konnte nicht geprüft werden.");
    }
  }

  function validateType(fieldKey, value, variable) {
    try {
      if (!variable || isEmpty(value)) {
        return null;
      }

      var type = valueType(variable);
      var widget = widgetType(variable);

      if (type === "number" || type === "money" || type === "float" || type === "decimal" || widget === "number" || widget === "money") {
        var number = U().floatValue(value, null);

        if (number === null || isNaN(number)) {
          return makeIssue("error", "invalid_number", fieldKey, variable, "Wert muss eine Zahl sein.");
        }
      }

      if (type === "integer" || type === "int" || widget === "integer") {
        var integer = U().intValue(value, null);

        if (integer === null || isNaN(integer) || String(value).indexOf(".") !== -1 || String(value).indexOf(",") !== -1) {
          return makeIssue("error", "invalid_integer", fieldKey, variable, "Wert muss eine ganze Zahl sein.");
        }
      }

      if (type === "boolean" || type === "bool" || widget === "checkbox") {
        if (typeof value !== "boolean" && ["true", "false", "1", "0", "yes", "no", "ja", "nein", "on", "off"].indexOf(String(value).toLowerCase()) === -1) {
          return makeIssue("error", "invalid_boolean", fieldKey, variable, "Wert muss Ja oder Nein sein.");
        }
      }

      if (type === "url" || widget === "url") {
        var text = U().trim(value);

        if (text && !/^https?:\/\/.+/i.test(text)) {
          return makeIssue("warning", "invalid_url_hint", fieldKey, variable, "URL sollte mit http:// oder https:// beginnen.");
        }
      }

      if (type === "date" || widget === "date") {
        var dateText = U().trim(value);

        if (dateText && isNaN(Date.parse(dateText))) {
          return makeIssue("error", "invalid_date", fieldKey, variable, "Wert muss ein gültiges Datum sein.");
        }
      }

      if (type === "document_list" || type === "documents" || widget === "document_list") {
        if (!Array.isArray(value)) {
          return makeIssue("error", "invalid_document_list", fieldKey, variable, "Wert muss eine Dokumentliste sein.");
        }
      }

      if (type === "object" && value && typeof value !== "object") {
        return makeIssue("error", "invalid_object", fieldKey, variable, "Wert muss ein Objekt sein.");
      }

      return null;
    } catch (error) {
      return makeIssue("error", "type_check_failed", fieldKey, variable, "Datentyp konnte nicht geprüft werden.");
    }
  }

  function validateValidationRules(fieldKey, value, variable) {
    try {
      if (!variable || isEmpty(value)) {
        return [];
      }

      var issues = [];
      var rules = variable.validation || variable.rules || {};
      var type = valueType(variable);

      var min = firstDefined(rules.min, rules.minimum, variable.min, variable.minimum);
      var max = firstDefined(rules.max, rules.maximum, variable.max, variable.maximum);
      var minLength = firstDefined(rules.min_length, rules.minLength, variable.min_length, variable.minLength);
      var maxLength = firstDefined(rules.max_length, rules.maxLength, variable.max_length, variable.maxLength);
      var pattern = firstDefined(rules.pattern, variable.pattern);

      if ((type === "number" || type === "integer" || type === "int" || type === "money" || type === "float" || type === "decimal") && !isEmpty(value)) {
        var number = type === "integer" || type === "int" ? U().intValue(value, null) : U().floatValue(value, null);

        if (number !== null && !isNaN(number)) {
          if (min !== undefined && min !== null && min !== "" && number < Number(min)) {
            issues.push(makeIssue("error", "min", fieldKey, variable, "Wert darf nicht kleiner als " + String(min) + " sein.", {
              min: min,
              value: number
            }));
          }

          if (max !== undefined && max !== null && max !== "" && number > Number(max)) {
            issues.push(makeIssue("error", "max", fieldKey, variable, "Wert darf nicht größer als " + String(max) + " sein.", {
              max: max,
              value: number
            }));
          }
        }
      }

      if ((type === "string" || type === "text" || type === "url" || type === "date" || !type) && typeof value === "string") {
        if (minLength !== undefined && minLength !== null && minLength !== "" && value.length < Number(minLength)) {
          issues.push(makeIssue("error", "min_length", fieldKey, variable, "Text ist zu kurz.", {
            min_length: minLength,
            value_length: value.length
          }));
        }

        if (maxLength !== undefined && maxLength !== null && maxLength !== "" && value.length > Number(maxLength)) {
          issues.push(makeIssue("error", "max_length", fieldKey, variable, "Text ist zu lang.", {
            max_length: maxLength,
            value_length: value.length
          }));
        }

        if (pattern) {
          try {
            var regex = new RegExp(pattern);

            if (!regex.test(value)) {
              issues.push(makeIssue("error", "pattern", fieldKey, variable, "Wert entspricht nicht dem erwarteten Format.", {
                pattern: pattern
              }));
            }
          } catch (patternError) {
            issues.push(makeIssue("warning", "invalid_pattern_rule", fieldKey, variable, "Validierungsmuster ist ungültig.", {
              pattern: pattern
            }));
          }
        }
      }

      return issues;
    } catch (error) {
      return [makeIssue("error", "rule_check_failed", fieldKey, variable, "Validierungsregeln konnten nicht geprüft werden.")];
    }
  }

  function validateEnum(fieldKey, value, variable) {
    try {
      if (!variable || isEmpty(value)) {
        return null;
      }

      var type = valueType(variable);
      var widget = widgetType(variable);

      if (type !== "enum" && type !== "select" && widget !== "select") {
        return null;
      }

      var optionValues = getOptionValues(variable);

      if (!optionValues.length) {
        return null;
      }

      if (optionValues.indexOf(String(value)) === -1) {
        return makeIssue("error", "invalid_option", fieldKey, variable, "Wert ist keine erlaubte Option.", {
          allowed_values: optionValues,
          value: value
        });
      }

      return null;
    } catch (error) {
      return makeIssue("error", "enum_check_failed", fieldKey, variable, "Option konnte nicht geprüft werden.");
    }
  }

  function validateField(fieldKey, value, variable, required) {
    try {
      var issues = [];
      var normalized = normalizeValue(value, variable);
      var requiredIssue = validateRequired(fieldKey, normalized, variable, required);

      if (requiredIssue) {
        issues.push(requiredIssue);
        return issues;
      }

      var typeIssue = validateType(fieldKey, normalized, variable);
      if (typeIssue) {
        issues.push(typeIssue);
      }

      var enumIssue = validateEnum(fieldKey, normalized, variable);
      if (enumIssue) {
        issues.push(enumIssue);
      }

      issues = issues.concat(validateValidationRules(fieldKey, normalized, variable));

      return issues;
    } catch (error) {
      return [
        makeIssue("error", "field_validation_failed", fieldKey, variable, "Feld konnte nicht validiert werden.")
      ];
    }
  }

  function localValidateValues(values, profile, options) {
    try {
      var config = U().safeMerge(runtime.options, options || {});
      var sourceValues = values && typeof values === "object" ? values : {};
      var sourceProfile = profile || null;
      var errors = [];
      var warnings = [];
      var fields = [];

      if (!sourceProfile) {
        var issue = makeIssue(
          config.failOnMissingProfile === false ? "warning" : "error",
          "profile_missing",
          "",
          null,
          "Kein Variant Profile für die Validierung vorhanden."
        );

        if (issue.level === "warning") {
          warnings.push(issue);
        } else {
          errors.push(issue);
        }
      }

      if (sourceProfile) {
        fields = getProfileFields(sourceProfile);
      }

      if (fields.indexOf("variant.variant_id") === -1) {
        fields.unshift("variant.variant_id");
      }

      if (fields.indexOf("variant.label") === -1) {
        fields.unshift("variant.label");
      }

      fields.forEach(function (fieldKey) {
        var variable = getVariable(fieldKey);
        var required = isRequired(sourceProfile, fieldKey, variable);
        var value = sourceValues[fieldKey];

        if (fieldKey === "variant.variant_id") {
          required = true;
        }

        if (fieldKey === "variant.label") {
          required = true;
        }

        var fieldIssues = validateField(fieldKey, value, variable, required);

        fieldIssues.forEach(function (issue) {
          if (issue.level === "warning") {
            warnings.push(issue);
          } else {
            errors.push(issue);
          }
        });

        if (!variable && config.warnUnknownFields !== false) {
          warnings.push(makeIssue(
            "warning",
            "variable_definition_missing",
            fieldKey,
            null,
            "Für dieses Feld fehlt eine Variable Definition."
          ));
        }
      });

      Object.keys(sourceValues).forEach(function (fieldKey) {
        if (fields.indexOf(fieldKey) !== -1) {
          return;
        }

        var variable = getVariable(fieldKey);

        if (!variable && config.warnUnknownFields !== false) {
          warnings.push(makeIssue(
            "warning",
            "unprofiled_field",
            fieldKey,
            null,
            "Dieses Feld ist nicht Teil des aktuellen Variant Profiles."
          ));
        } else if (variable) {
          validateField(fieldKey, sourceValues[fieldKey], variable, false).forEach(function (issue) {
            if (issue.level === "warning") {
              warnings.push(issue);
            } else {
              errors.push(issue);
            }
          });
        }
      });

      return buildValidationResult(errors.length === 0, errors, warnings, sourceValues, sourceProfile, "local");
    } catch (error) {
      return buildValidationResult(false, [
        makeIssue("error", "local_validation_failed", "", null, "Lokale Validierung ist fehlgeschlagen.", {
          error: normalizeError(error)
        })
      ], [], values || {}, profile || null, "local");
    }
  }

  function localValidateVariant(variant, options) {
    try {
      var source = normalizeVariantInput(variant || {});
      var profile = null;

      if (options && options.profile) {
        profile = options.profile;
      }

      if (!profile && source.variant_profile_id) {
        profile = getVariantProfile(source.variant_profile_id);
      }

      if (!profile && runtime.lastProfile) {
        profile = runtime.lastProfile;
      }

      return localValidateValues(source.definition_values, profile, options || {});
    } catch (error) {
      return buildValidationResult(false, [
        makeIssue("error", "local_variant_validation_failed", "", null, "Variante konnte lokal nicht validiert werden.", {
          error: normalizeError(error)
        })
      ], [], {}, null, "local");
    }
  }

  function buildValidationResult(ok, errors, warnings, values, profile, source) {
    try {
      var errorList = U().toArray(errors);
      var warningList = U().toArray(warnings);

      return {
        ok: !!ok && errorList.length === 0,
        valid: !!ok && errorList.length === 0,
        source: source || "local",
        errors: errorList,
        warnings: warningList,
        issue_count: errorList.length + warningList.length,
        issueCount: errorList.length + warningList.length,
        error_count: errorList.length,
        errorCount: errorList.length,
        warning_count: warningList.length,
        warningCount: warningList.length,
        values: values || {},
        profile: profile || null,
        profile_id: profile ? profile.id || profile.profile_id || "" : "",
        profileId: profile ? profile.id || profile.profile_id || "" : "",
        timestamp: U().nowIso ? U().nowIso() : new Date().toISOString()
      };
    } catch (error) {
      return {
        ok: false,
        valid: false,
        source: source || "local",
        errors: [
          makeIssue("error", "validation_result_build_failed", "", null, "Validierungsergebnis konnte nicht aufgebaut werden.")
        ],
        warnings: [],
        issue_count: 1,
        issueCount: 1,
        error_count: 1,
        errorCount: 1,
        warning_count: 0,
        warningCount: 0,
        values: values || {},
        profile: profile || null,
        profile_id: profile ? profile.id || profile.profile_id || "" : "",
        profileId: profile ? profile.id || profile.profile_id || "" : "",
        timestamp: ""
      };
    }
  }

  function getValidateEndpoint() {
    try {
      var context = window.VectoplanCreateContext || {};
      var definitionsApi = context.definitionsApi || context.definitions_api || {};
      var endpoints = definitionsApi.endpoints || definitionsApi.routes || {};

      return endpoints.validateVariant ||
        endpoints.validate_variant ||
        definitionsApi.validateVariant ||
        definitionsApi.validate_variant ||
        context.definitions_validate_variant ||
        context.definitionsValidateVariant ||
        VALIDATE_ENDPOINT;
    } catch (error) {
      return VALIDATE_ENDPOINT;
    }
  }

  function canFetch() {
    try {
      return typeof window.fetch === "function";
    } catch (error) {
      return false;
    }
  }

  function backendValidateVariant(variant, profile, options) {
    try {
      var config = options || {};

      if (!canFetch()) {
        return Promise.resolve(buildValidationResult(true, [], [
          makeIssue("warning", "fetch_unavailable", "", null, "Backend-Validierung übersprungen, weil Fetch nicht verfügbar ist.")
        ], variant.definition_values || {}, profile || null, "backend_skipped"));
      }

      var source = normalizeVariantInput(variant || {});
      var profileId = source.variant_profile_id || (profile ? profile.id || profile.profile_id || "" : "") || "";
      var context = config.context || readDrawerContext();

      var body = {
        profile_id: profileId,
        variant_profile_id: profileId,
        family_profile_id: source.family_profile_id || context.family_profile_id || "",
        values: source.definition_values || {},
        variant: {
          variant_id: source.variant_id || source.definition_values["variant.variant_id"] || "",
          label: source.label || source.definition_values["variant.label"] || "",
          description: source.description || source.definition_values["variant.description"] || "",
          variant_profile_id: profileId,
          family_profile_id: source.family_profile_id || context.family_profile_id || "",
          definition_values: source.definition_values || {}
        },
        context: context
      };

      return window.fetch(getValidateEndpoint(), {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json"
        },
        body: U().safeJsonStringify(body, "{}")
      }).then(function (response) {
        return response.text().then(function (text) {
          var json = U().safeJsonParse(text, null);

          if (!response.ok) {
            throw {
              code: "http_" + String(response.status),
              message: "Backend-Validierung HTTP " + String(response.status),
              status: response.status,
              payload: json
            };
          }

          if (!json || typeof json !== "object") {
            throw {
              code: "invalid_json",
              message: "Backend-Validierung lieferte kein gültiges JSON."
            };
          }

          return normalizeBackendValidationResult(json, source.definition_values || {}, profile || null);
        });
      }).catch(function (error) {
        return buildValidationResult(true, [], [
          makeIssue("warning", "backend_validation_failed", "", null, "Backend-Validierung konnte nicht ausgeführt werden.", {
            error: normalizeError(error)
          })
        ], source.definition_values || {}, profile || null, "backend_failed_soft");
      });
    } catch (error) {
      return Promise.resolve(buildValidationResult(true, [], [
        makeIssue("warning", "backend_validation_error", "", null, "Backend-Validierung konnte nicht vorbereitet werden.", {
          error: normalizeError(error)
        })
      ], variant && variant.definition_values ? variant.definition_values : {}, profile || null, "backend_failed_soft"));
    }
  }

  function normalizeBackendValidationResult(payload, values, profile) {
    try {
      var data = payload && payload.data && typeof payload.data === "object"
        ? payload.data
        : payload || {};

      var errors = data.errors ||
        data.validation_errors ||
        data.validationErrors ||
        data.field_errors ||
        data.fieldErrors ||
        [];

      var warnings = data.warnings ||
        data.validation_warnings ||
        data.validationWarnings ||
        [];

      if (data.error && !errors.length) {
        errors.push(data.error);
      }

      errors = U().toArray(errors).map(normalizeIssue);
      warnings = U().toArray(warnings).map(function (item) {
        var issue = normalizeIssue(item);
        issue.level = "warning";
        issue.severity = "warning";
        return issue;
      });

      var ok = data.ok !== undefined
        ? !!data.ok
        : data.valid !== undefined
          ? !!data.valid
          : errors.length === 0;

      return buildValidationResult(ok, errors, warnings, values || data.values || {}, profile || null, "backend");
    } catch (error) {
      return buildValidationResult(false, [
        makeIssue("error", "backend_result_normalization_failed", "", null, "Backend-Ergebnis konnte nicht verarbeitet werden.", {
          error: normalizeError(error)
        })
      ], [], values || {}, profile || null, "backend");
    }
  }

  function normalizeIssue(item) {
    try {
      if (!item || typeof item !== "object") {
        return makeIssue("error", "invalid", "", null, String(item || "Ungültiger Wert."));
      }

      var fieldKey = item.field_key || item.fieldKey || item.key || item.path || "";
      var variable = fieldKey ? getVariable(fieldKey) : null;

      return makeIssue(
        item.level || item.severity || "error",
        item.code || item.type || "invalid",
        fieldKey,
        variable,
        item.message || item.detail || "Ungültiger Wert.",
        item
      );
    } catch (error) {
      return makeIssue("error", "invalid_issue", "", null, "Validierungshinweis konnte nicht verarbeitet werden.");
    }
  }

  function shouldRunBackend(localResult, options) {
    try {
      var config = U().safeMerge(runtime.options, options || {});

      if (!config.backendValidation) {
        return false;
      }

      if (config.backendValidationMode === "always") {
        return true;
      }

      if (config.backendValidationMode === "never") {
        return false;
      }

      return !!localResult.ok;
    } catch (error) {
      return false;
    }
  }

  function mergeValidationResults(localResult, backendResult) {
    try {
      if (!backendResult) {
        return localResult;
      }

      var errors = []
        .concat(U().toArray(localResult.errors))
        .concat(U().toArray(backendResult.errors));

      var warnings = []
        .concat(U().toArray(localResult.warnings))
        .concat(U().toArray(backendResult.warnings));

      return buildValidationResult(
        errors.length === 0,
        errors,
        warnings,
        backendResult.values || localResult.values || {},
        backendResult.profile || localResult.profile || null,
        backendResult.source === "backend" ? "local+backend" : "local+backend_soft"
      );
    } catch (error) {
      return localResult;
    }
  }

  function validationSignature(variant, profile, options) {
    try {
      return U().safeJsonStringify({
        variant: variant || {},
        profile: profile ? profile.id || profile.profile_id || "" : "",
        mode: options && options.source ? options.source : ""
      }, "");
    } catch (error) {
      return String(Date.now());
    }
  }

  function validateVariant(input, options) {
    try {
      var config = options || {};
      var requestId = "validation_" + String(++runtime.validationSeq);
      var variant = normalizeVariantInput(input || {});
      var profile = config.profile || null;

      if (!profile && variant.variant_profile_id) {
        profile = getVariantProfile(variant.variant_profile_id);
      }

      if (!profile && runtime.lastProfile) {
        profile = runtime.lastProfile;
      }

      var signature = validationSignature(variant, profile, config);

      if (runtime.validationInProgress && config.force !== true) {
        runtime.suppressedValidationCount += 1;

        if (runtime.lastResult) {
          return Promise.resolve(runtime.lastResult);
        }
      }

      runtime.validationInProgress = true;
      runtime.lastValidationRequestId = requestId;
      runtime.lastValidationSignature = signature;

      U().dispatchDocument("vectoplan:create:variant-validation-started", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        request_id: requestId,
        requestId: requestId,
        variant: variant,
        profile: profile,
        __vp_variant_validation_event: true
      }, {
        silent: true
      });

      var localResult = localValidateVariant(variant, U().safeMerge(config, {
        profile: profile
      }));

      if (!shouldRunBackend(localResult, config)) {
        return Promise.resolve(finishValidation(localResult, requestId, config));
      }

      return backendValidateVariant(variant, profile, config)
        .then(function (backendResult) {
          return finishValidation(mergeValidationResults(localResult, backendResult), requestId, config);
        })
        .catch(function (error) {
          var softResult = mergeValidationResults(localResult, buildValidationResult(true, [], [
            makeIssue("warning", "backend_validation_failed", "", null, "Backend-Validierung konnte nicht ausgeführt werden.", {
              error: normalizeError(error)
            })
          ], variant.definition_values || {}, profile || null, "backend_failed_soft"));

          return finishValidation(softResult, requestId, config);
        });
    } catch (error) {
      runtime.validationInProgress = false;

      var failed = buildValidationResult(false, [
        makeIssue("error", "validation_failed", "", null, "Validierung ist fehlgeschlagen.", {
          error: normalizeError(error)
        })
      ], [], {}, null, "client");

      return Promise.resolve(finishValidation(failed, "", options || {}));
    }
  }

  function validateValues(values, profile, options) {
    try {
      var variant = {
        variant_id: values && values["variant.variant_id"] ? values["variant.variant_id"] : "",
        label: values && values["variant.label"] ? values["variant.label"] : "",
        variant_profile_id: profile ? profile.id || profile.profile_id || "" : "",
        definition_values: values || {}
      };

      return validateVariant(variant, U().safeMerge(options || {}, {
        profile: profile
      }));
    } catch (error) {
      return Promise.resolve(buildValidationResult(false, [
        makeIssue("error", "validate_values_failed", "", null, "Werte konnten nicht validiert werden.")
      ], [], values || {}, profile || null, "client"));
    }
  }

  function validateDrawer(input) {
    try {
      var config = input || {};
      var root = config.root ? config.root : null;
      var cache = cacheDrawer(root);
      var variant = config.variant ? config.variant : buildVariantFromDrawer(cache.drawer);
      var profile = config.profile ? config.profile : readDrawerProfile(cache.drawer);

      return validateVariant(variant, U().safeMerge(config, {
        profile: profile,
        context: config.context || readDrawerContext(cache.drawer),
        render: true,
        root: cache.drawer
      }));
    } catch (error) {
      return Promise.resolve(finishValidation(buildValidationResult(false, [
        makeIssue("error", "validate_drawer_failed", "", null, "Drawer konnte nicht validiert werden.", {
          error: normalizeError(error)
        })
      ], [], {}, null, "client"), "", {
        render: true
      }));
    }
  }

  function finishValidation(result, requestId, options) {
    try {
      var config = options || {};
      var finalResult = result || buildValidationResult(false, [], [], {}, null, "client");

      runtime.validationInProgress = false;
      runtime.lastResult = finalResult;
      runtime.lastValidatedAt = Date.now();
      runtime.lastValues = finalResult.values || runtime.lastValues || {};
      runtime.lastProfile = finalResult.profile || runtime.lastProfile || null;

      if (config.render !== false) {
        renderValidationResult(finalResult, config.root || null);
      }

      U().dispatchDocument("vectoplan:create:variant-validation-finished", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        request_id: requestId || runtime.lastValidationRequestId,
        requestId: requestId || runtime.lastValidationRequestId,
        ok: !!finalResult.ok,
        valid: !!finalResult.valid,
        errors: finalResult.errors || [],
        warnings: finalResult.warnings || [],
        result: finalResult,
        profile: finalResult.profile || null,
        values: finalResult.values || {},
        __vp_variant_validation_event: true
      }, {
        silent: true
      });

      return finalResult;
    } catch (error) {
      runtime.validationInProgress = false;
      warn("Could not finish validation.", error);
      return result;
    }
  }

  function clearValidationUI(root) {
    try {
      var cache = cacheDrawer(root);

      U().qsa("[data-vp-field-error='true']", cache.drawer || document).forEach(function (node) {
        node.textContent = "";
        U().setHidden(node, true);
      });

      U().qsa(FIELD_SELECTOR, cache.drawer || document).forEach(function (node) {
        node.classList.remove("vp-create-variant-field--invalid");
        node.classList.remove("vp-create-variant-field--warning");
        U().setAttr(node, "data-vp-field-validation-state", "");
      });

      if (cache.validationList) {
        U().empty(cache.validationList);
      }

      if (cache.validationRoot) {
        U().setHidden(cache.validationRoot, true);
        U().setAttr(cache.validationRoot, "data-vp-variant-drawer-validation-state", "idle");
      }

      if (cache.validationCount) {
        cache.validationCount.textContent = "0 Hinweise";
      }

      U().dispatchDocument("vectoplan:create:variant-validation-cleared", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        __vp_variant_validation_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not clear validation UI.", error);
      return false;
    }
  }

  function renderIssueList(cache, result) {
    try {
      var issues = []
        .concat(U().toArray(result.errors))
        .concat(runtime.options.showWarnings ? U().toArray(result.warnings) : []);

      if (!cache.validationRoot || !cache.validationList) {
        return false;
      }

      U().empty(cache.validationList);

      issues.forEach(function (issue) {
        var item = U().createElement("li", {
          class: "vp-create-variant-drawer__validation-item vp-create-variant-drawer__validation-item--" + (issue.level || "error"),
          attrs: {
            "data-vp-validation-item": "true",
            "data-vp-validation-field-key": issue.field_key || "",
            "data-vp-validation-level": issue.level || "error"
          }
        }, [
          U().createElement("strong", {
            text: issue.label || issue.field_key || "Feld",
            attrs: {
              "data-vp-validation-label": "true"
            }
          }),
          U().createElement("span", {
            text: issue.message || "Ungültiger Wert.",
            attrs: {
              "data-vp-validation-message": "true"
            }
          })
        ]);

        cache.validationList.appendChild(item);
      });

      U().setHidden(cache.validationRoot, issues.length === 0);

      if (cache.validationCount) {
        cache.validationCount.textContent = issues.length === 1 ? "1 Hinweis" : String(issues.length) + " Hinweise";
      }

      if (cache.validationTitle) {
        cache.validationTitle.textContent = result.ok ? "Prüfung erfolgreich" : "Prüfung";
      }

      return true;
    } catch (error) {
      warn("Could not render validation issue list.", error);
      return false;
    }
  }

  function renderFieldIssues(root, result) {
    try {
      var drawer = getDrawer(root);
      var issues = []
        .concat(U().toArray(result.errors))
        .concat(runtime.options.showWarnings ? U().toArray(result.warnings) : []);

      issues.forEach(function (issue) {
        try {
          var fieldKey = issue.field_key || issue.fieldKey || "";

          if (!fieldKey) {
            return;
          }

          var field = U().qs("[data-vp-field-key='" + cssEscape(fieldKey) + "']", drawer);

          if (!field) {
            return;
          }

          var isWarning = issue.level === "warning";
          field.classList.add(isWarning ? "vp-create-variant-field--warning" : "vp-create-variant-field--invalid");
          U().setAttr(field, "data-vp-field-validation-state", isWarning ? "warning" : "invalid");

          var errorNode = U().qs("[data-vp-field-error='true']", field);

          if (errorNode) {
            errorNode.textContent = issue.message || "Ungültiger Wert.";
            U().setHidden(errorNode, false);
          }

          U().dispatchDocument("vectoplan:create:variant-field-validation-updated", {
            component: COMPONENT_NAME,
            version: COMPONENT_VERSION,
            field_key: fieldKey,
            fieldKey: fieldKey,
            issue: issue,
            __vp_variant_validation_event: true
          }, {
            silent: true
          });
        } catch (issueError) {
          warn("Could not render field issue.", issueError);
        }
      });

      return true;
    } catch (error) {
      warn("Could not render field validation issues.", error);
      return false;
    }
  }

  function setStatusFromResult(cache, result) {
    try {
      var statusState = result.ok ? "valid" : "invalid";
      var message = "";

      if (result.ok) {
        message = result.warning_count > 0
          ? "Variante ist gültig, enthält aber Hinweise."
          : "Variante ist gültig.";
      } else {
        message = result.error_count === 1
          ? "Variante enthält 1 Fehler."
          : "Variante enthält " + String(result.error_count) + " Fehler.";
      }

      if (cache.statusPill) {
        cache.statusPill.className = "vp-create-variant-drawer__status-pill vp-create-variant-drawer__status-pill--" + statusState;
        cache.statusPill.textContent = result.ok ? "Gültig" : "Ungültig";
      }

      if (cache.statusText) {
        cache.statusText.textContent = message;
      }

      if (cache.validationRoot) {
        U().setAttr(cache.validationRoot, "data-vp-variant-drawer-validation-state", statusState);
      }
    } catch (error) {
      warn("Could not set validation status.", error);
    }
  }

  function renderValidationResult(result, root) {
    try {
      var cache = cacheDrawer(root);

      clearValidationUI(cache.drawer);

      renderIssueList(cache, result);
      renderFieldIssues(cache.drawer, result);
      setStatusFromResult(cache, result);

      return true;
    } catch (error) {
      warn("Could not render validation result.", error);
      return false;
    }
  }

  function markValidationStale(root) {
    try {
      var cache = cacheDrawer(root);

      if (cache.validationRoot) {
        U().setAttr(cache.validationRoot, "data-vp-variant-drawer-validation-state", "stale");
      }

      if (cache.statusPill) {
        cache.statusPill.className = "vp-create-variant-drawer__status-pill vp-create-variant-drawer__status-pill--idle";
        cache.statusPill.textContent = "Bereit";
      }

      if (cache.statusText) {
        cache.statusText.textContent = "Werte wurden geändert. Prüfung ist nicht mehr aktuell.";
      }
    } catch (error) {
      warn("Could not mark validation stale.", error);
    }
  }

  function bindGlobalEvents() {
    try {
      if (runtime.globalEventsBound) {
        return;
      }

      document.addEventListener("vectoplan:create:variant-values-changed", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail.__vp_variant_validation_event) {
            return;
          }

          runtime.lastValues = detail.values || runtime.lastValues || {};

          markValidationStale(detail.drawerId ? document.getElementById(detail.drawerId) : null);

          if (runtime.options.validateOnChange) {
            validateDrawer({
              source: "values_changed"
            });
          }
        } catch (error) {
          warn("Values changed validation listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-fields-rendered", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          runtime.lastProfile = detail.profile || runtime.lastProfile;
          runtime.lastValues = detail.values || runtime.lastValues || {};

          clearValidationUI(detail.drawerId ? document.getElementById(detail.drawerId) : null);
        } catch (error) {
          warn("Fields rendered validation listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-profile-resolved", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          runtime.lastProfile = detail.variant_profile || detail.variantProfile || detail.profile || runtime.lastProfile;
        } catch (error) {
          warn("Profile resolved validation listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-drawer-opened", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var payload = detail.payload || detail.session || detail || {};

          clearValidationUI();

          if (payload.values || payload.definition_values || payload.definitionValues) {
            runtime.lastValues = payload.values || payload.definition_values || payload.definitionValues;
          } else if (payload.valuesJson || payload.definition_values_json || payload.definitionValuesJson) {
            runtime.lastValues = U().valuesFromJson(payload.valuesJson || payload.definition_values_json || payload.definitionValuesJson);
          }

          if (runtime.options.validateOnOpen) {
            validateDrawer({
              source: "drawer_opened"
            });
          }
        } catch (error) {
          warn("Drawer opened validation listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-drawer-validate-requested", function (event) {
        try {
          if (
            window.VectoplanCreateVariantDrawer &&
            typeof window.VectoplanCreateVariantDrawer.validateDrawer === "function"
          ) {
            return;
          }

          validateDrawer({
            source: "validate_requested",
            detail: event && event.detail ? event.detail : {}
          });
        } catch (error) {
          warn("Validate requested fallback listener failed.", error);
        }
      });

      runtime.globalEventsBound = true;
    } catch (error) {
      warn("Could not bind validation global events.", error);
    }
  }

  function normalizeError(error) {
    try {
      if (!error) {
        return {
          level: "error",
          code: "unknown_error",
          message: "Unbekannter Fehler."
        };
      }

      if (error.error && typeof error.error === "object") {
        return normalizeError(error.error);
      }

      return {
        level: "error",
        code: error.code || error.status || "error",
        message: error.message || String(error),
        status: error.status || null,
        payload: error.payload || null
      };
    } catch (normalizationError) {
      return {
        level: "error",
        code: "error",
        message: "Fehler konnte nicht normalisiert werden."
      };
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

      return String(value || "").replace(/["\\]/g, "\\$&");
    } catch (error) {
      return String(value || "").replace(/["\\]/g, "\\$&");
    }
  }

  function getRuntimeSnapshot() {
    try {
      return {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        initialized: runtime.initialized,
        validationInProgress: runtime.validationInProgress,
        suppressedValidationCount: runtime.suppressedValidationCount,
        backendValidation: runtime.options.backendValidation,
        backendValidationMode: runtime.options.backendValidationMode,
        validateOnChange: runtime.options.validateOnChange,
        validateOnOpen: runtime.options.validateOnOpen,
        lastResult: runtime.lastResult ? {
          ok: runtime.lastResult.ok,
          error_count: runtime.lastResult.error_count,
          warning_count: runtime.lastResult.warning_count,
          source: runtime.lastResult.source
        } : null,
        lastProfileId: runtime.lastProfile ? runtime.lastProfile.id || runtime.lastProfile.profile_id || "" : "",
        lastValueCount: runtime.lastValues ? Object.keys(runtime.lastValues).length : 0,
        hasDefinitions: !!runtime.cache.definitions
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

      runtime.initialized = true;

      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-validation-version", COMPONENT_VERSION);

      U().dispatchDocument("vectoplan:create:variant-validation-ready", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        snapshot: getRuntimeSnapshot(),
        __vp_variant_validation_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not initialize variant validation.", error);
      return false;
    }
  }

  var api = {
    __name: COMPONENT_NAME,
    __version: COMPONENT_VERSION,

    initialize: initialize,

    validateVariant: validateVariant,
    validateValues: validateValues,
    validateDrawer: validateDrawer,

    localValidateVariant: localValidateVariant,
    localValidateValues: localValidateValues,
    backendValidateVariant: backendValidateVariant,

    validateField: validateField,
    validateRequired: validateRequired,
    validateType: validateType,
    validateValidationRules: validateValidationRules,
    validateEnum: validateEnum,

    renderValidationResult: renderValidationResult,
    clearValidationUI: clearValidationUI,
    markValidationStale: markValidationStale,

    buildVariantFromDrawer: buildVariantFromDrawer,
    normalizeVariantInput: normalizeVariantInput,

    getDefinitions: getDefinitions,
    getMaps: getMaps,
    getVariable: getVariable,
    getVariantProfile: getVariantProfile,

    getLastResult: function () {
      return U().deepClone(runtime.lastResult, null);
    },

    getRuntimeSnapshot: getRuntimeSnapshot,

    setOptions: function (options) {
      runtime.options = U().safeMerge(runtime.options, options || {});
      return U().deepClone(runtime.options, {});
    }
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
    warn("Could not bootstrap variant validation.", bootstrapError);
  }
})();