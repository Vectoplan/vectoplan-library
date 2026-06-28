/* services/vectoplan-library/static/js/vplib/create/create_variant_profiles.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateVariantProfiles";
  var COMPONENT_NAME = "VECTOPLAN Create Variant Profiles";
  var COMPONENT_VERSION = "0.7.0";
  var READY_ATTR = "data-vp-create-variant-profiles-ready";

  var WORKSPACE_SELECTOR = "[data-vp-variant-workspace-root='true'], [data-vp-variant-workspace='true']";
  var DRAWER_SELECTOR = "[data-vp-variant-drawer-root='true'], [data-vp-variant-drawer='true']";
  var TABLE_SELECTOR = "[data-vp-variant-table-root='true'], [data-vp-variant-table='true']";

  var FIELD_SELECTORS = {
    domain: [
      "[name='domain']",
      "[name='taxonomy[domain]']",
      "[data-vp-taxonomy-domain]",
      "[data-create-taxonomy-domain]"
    ],
    category: [
      "[name='category']",
      "[name='taxonomy[category]']",
      "[data-vp-taxonomy-category]",
      "[data-create-taxonomy-category]"
    ],
    subcategory: [
      "[name='subcategory']",
      "[name='taxonomy[subcategory]']",
      "[data-vp-taxonomy-subcategory]",
      "[data-create-taxonomy-subcategory]"
    ],
    objectKind: [
      "[name='object_kind']",
      "[name='object_class']",
      "[data-create-object-kind='true']",
      "[data-vp-object-kind]"
    ],
    familyProfileId: [
      "[name='family_profile_id']",
      "[data-vp-family-profile-id-field='true']",
      "[data-vp-variant-drawer-family-profile-id-field='true']"
    ],
    variantProfileId: [
      "[name='variant_profile_id']",
      "[data-vp-variant-profile-id-field='true']",
      "[data-vp-variant-drawer-profile-id-field='true']"
    ]
  };

  if (window[GLOBAL_NAME] && window[GLOBAL_NAME].__version === COMPONENT_VERSION) {
    try {
      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-profiles-version", COMPONENT_VERSION);
    } catch (alreadyReadyError) {
      /* no-op */
    }
    return;
  }

  var runtime = {
    initialized: false,
    globalEventsBound: false,
    resolveInProgress: false,
    activeResolvePromise: null,
    activeResolveKey: "",
    applyInProgress: false,
    autoResolveTimer: null,
    cache: {
      definitions: null,
      definitionMaps: null,
      endpoints: null,
      familyResolve: {},
      variantResolve: {},
      variantProfiles: {},
      emptyValues: {},
      requests: {}
    },
    lastContext: null,
    lastContextKey: "",
    lastResolved: null,
    lastResolvedSignature: "",
    lastBundle: null,
    lastBundleSignature: "",
    lastProfilePayload: null,
    lastAppliedSignature: "",
    lastFamilyDispatchSignature: "",
    lastVariantDispatchSignature: "",
    lastProfileLoadedSignature: "",
    lastEmptyValuesSignature: "",
    suppressedApplyCount: 0,
    suppressedResolveCount: 0,
    suppressedDispatchCount: 0,
    options: {
      emitNativeEvents: false,
      preferLocal: true,
      autoResolve: true,
      fetchDefinitions: true
    }
  };

  function getUtils() {
    if (window.VectoplanCreateVariantUtils && window.VectoplanCreateVariantUtils.__version) {
      return window.VectoplanCreateVariantUtils;
    }

    return fallbackUtils;
  }

  function U() {
    return getUtils();
  }

  function warn(message, error) {
    try {
      U().warn(message, error);
    } catch (warnError) {
      try {
        if (window.console && typeof window.console.warn === "function") {
          window.console.warn("[" + COMPONENT_NAME + "] " + String(message || ""), error || "");
        }
      } catch (consoleError) {
        /* no-op */
      }
    }
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

        if (typeof value === "object" && typeof value.length === "number" && typeof value !== "string") {
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
            var item = value[key];

            if (item && typeof item === "object") {
              if (!item.id && !item.key && !item.value) {
                item.id = key;
              }
            }

            return item;
          });
        }

        return fallbackUtils.toArray(value);
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
          node.setAttribute("data-vp-last-profile-sync", String(Date.now()));
        }

        if (dispatchEvents) {
          fallbackUtils.dispatchNative(node, "input", {
            source: COMPONENT_NAME,
            silent: true
          });
          fallbackUtils.dispatchNative(node, "change", {
            source: COMPONENT_NAME,
            silent: true
          });
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

        if ("value" in node) {
          return node.value || fallback || "";
        }

        return node.textContent || fallback || "";
      } catch (error) {
        return fallback || "";
      }
    },

    bool: function (value, fallback) {
      try {
        if (typeof value === "boolean") {
          return value;
        }

        var text = String(value === null || value === undefined ? "" : value).trim().toLowerCase();

        if (["true", "1", "yes", "ja", "on", "ok", "healthy", "ready", "partial", "enabled", "active"].indexOf(text) !== -1) {
          return true;
        }

        if (["false", "0", "no", "nein", "off", "disabled", "inactive", ""].indexOf(text) !== -1) {
          return false;
        }

        return !!fallback;
      } catch (error) {
        return !!fallback;
      }
    },

    lower: function (value) {
      try {
        return String(value || "").trim().toLowerCase();
      } catch (error) {
        return "";
      }
    },

    trim: function (value) {
      try {
        return String(value || "").trim();
      } catch (error) {
        return "";
      }
    },

    normalizeObjectKind: function (value) {
      try {
        return String(value || "")
          .trim()
          .toLowerCase()
          .replace(/[-\s]+/g, "_")
          .replace(/[^a-z0-9_]/g, "");
      } catch (error) {
        return "";
      }
    },

    normalizeProfileId: function (value) {
      try {
        return String(value || "")
          .trim()
          .replace(/\s+/g, "")
          .replace(/-/g, "_");
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

    safeJsonStringify: function (value, fallback) {
      try {
        return JSON.stringify(value);
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

        var source = options && options.source ? options.source : COMPONENT_NAME;

        if (node.setAttribute) {
          node.setAttribute("data-vp-programmatic-event", String(eventName));
          node.setAttribute("data-vp-programmatic-event-source", source);
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

    normalizeDefinitions: normalizeDefinitions,
    buildDefinitionMaps: buildDefinitionMaps,
    indexBy: indexBy,
    nowIso: function () {
      try {
        return new Date().toISOString();
      } catch (error) {
        return "";
      }
    }
  };

  function isPlainObject(value) {
    return !!value && typeof value === "object" && !Array.isArray(value);
  }

  function pathGet(source, path, fallbackValue) {
    try {
      var current = source || {};
      var parts = String(path || "").split(".");

      for (var index = 0; index < parts.length; index += 1) {
        if (!current || typeof current !== "object") {
          return fallbackValue;
        }

        current = current[parts[index]];

        if (current === null || current === undefined) {
          return fallbackValue;
        }
      }

      return current;
    } catch (error) {
      return fallbackValue;
    }
  }

  function firstNonEmpty() {
    try {
      for (var index = 0; index < arguments.length; index += 1) {
        var value = arguments[index];

        if (value === null || value === undefined) {
          continue;
        }

        if (typeof value === "string" && !value.trim()) {
          continue;
        }

        if (Array.isArray(value) && !value.length) {
          continue;
        }

        if (isPlainObject(value) && !Object.keys(value).length) {
          continue;
        }

        return value;
      }

      return null;
    } catch (error) {
      return null;
    }
  }

  function toArrayOrObjectValues(value) {
    return U().toArrayOrObjectValues ? U().toArrayOrObjectValues(value) : fallbackUtils.toArrayOrObjectValues(value);
  }

  function indexBy(items, keyName) {
    try {
      var output = {};
      var key = keyName || "id";

      toArrayOrObjectValues(items).forEach(function (item) {
        if (!item || typeof item !== "object") {
          return;
        }

        var keys = [
          item[key],
          item.id,
          item.key,
          item.value,
          item.name,
          item.profile_id,
          item.profileId,
          item.variant_profile_id,
          item.variantProfileId,
          item.family_profile_id,
          item.familyProfileId,
          item.variable_key,
          item.variableKey,
          item.document_type_id,
          item.documentTypeId
        ];

        keys.forEach(function (candidate) {
          var text = candidate === null || candidate === undefined ? "" : String(candidate).trim();
          if (!text) {
            return;
          }

          output[text] = item;

          var normalized = U().normalizeProfileId ? U().normalizeProfileId(text) : text.replace(/-/g, "_");
          if (normalized) {
            output[normalized] = item;
          }
        });
      });

      return output;
    } catch (error) {
      return {};
    }
  }

  function normalizeDefinitions(raw) {
    try {
      var source = raw || {};
      var sources = [];

      function add(value) {
        if (value && typeof value === "object") {
          sources.push(value);
        }
      }

      add(source);
      add(source.data);
      add(source.payload);
      add(source.options);
      add(source.catalogs);
      add(source.definition_catalogs);
      add(source.definitionCatalogs);
      add(source.records);
      add(source.definitions);

      if (source.definitions && typeof source.definitions === "object") {
        add(source.definitions.data);
        add(source.definitions.payload);
        add(source.definitions.options);
        add(source.definitions.catalogs);
        add(source.definitions.records);
        add(source.definitions.definitions);
      }

      var generator = window.VectoplanGeneratorContext || {};
      var context = window.VectoplanCreateContext || {};
      var generatorFromContext = context.generatorContext || context.generator_context || {};
      var generatorData = generator.data || generator.payload || generator.generator_data || generator.generatorData || generator;
      var generatorContextData = generatorFromContext.data || generatorFromContext.payload || generatorFromContext.generator_data || generatorFromContext.generatorData || generatorFromContext;
      var generatorDefinitions = generatorData.definition_context || generatorData.definitions || {};
      var contextDefinitions = generatorContextData.definition_context || generatorContextData.definitions || {};

      add(generatorDefinitions);
      add(generatorDefinitions.records);
      add(generatorDefinitions.definitions);
      add(generatorDefinitions.options);
      add(contextDefinitions);
      add(contextDefinitions.records);
      add(contextDefinitions.definitions);
      add(contextDefinitions.options);

      function firstCollection(names) {
        for (var sourceIndex = 0; sourceIndex < sources.length; sourceIndex += 1) {
          var candidateSource = sources[sourceIndex];

          if (!candidateSource || typeof candidateSource !== "object") {
            continue;
          }

          for (var nameIndex = 0; nameIndex < names.length; nameIndex += 1) {
            var value = candidateSource[names[nameIndex]];
            var array = toArrayOrObjectValues(value);

            if (array.length) {
              return array;
            }
          }
        }

        return [];
      }

      return {
        raw: source,
        object_kinds: firstCollection(["object_kinds", "objectKinds"]),
        family_profiles: firstCollection(["family_profiles", "familyProfiles"]),
        variant_profiles: firstCollection(["variant_profiles", "variantProfiles"]),
        variables: firstCollection(["variables"]),
        units: firstCollection(["units"]),
        materials: firstCollection(["materials", "material_classes", "materialClasses"]),
        document_types: firstCollection(["document_types", "documentTypes"]),
        profile_bindings: firstCollection(["profile_bindings", "profileBindings"])
      };
    } catch (error) {
      return {
        raw: raw || {},
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
  }

  function buildDefinitionMaps(defs) {
    try {
      var normalized = normalizeDefinitions(defs);

      var mapsFromWindow = window.VectoplanCreateDefinitionMaps || {};
      var built = {
        objectKindsById: indexBy(normalized.object_kinds, "id"),
        familyProfilesById: indexBy(normalized.family_profiles, "id"),
        variantProfilesById: indexBy(normalized.variant_profiles, "id"),
        variablesByKey: indexBy(normalized.variables, "key"),
        unitsById: indexBy(normalized.units, "id"),
        materialsById: indexBy(normalized.materials, "id"),
        documentTypesById: indexBy(normalized.document_types, "id"),
        profileBindingsById: indexBy(normalized.profile_bindings, "id")
      };

      return U().safeMerge ? U().safeMerge(built, mapsFromWindow) : Object.assign(built, mapsFromWindow);
    } catch (error) {
      return {
        objectKindsById: {},
        familyProfilesById: {},
        variantProfilesById: {},
        variablesByKey: {},
        unitsById: {},
        materialsById: {},
        documentTypesById: {},
        profileBindingsById: {}
      };
    }
  }

  function getDefaultEndpoints() {
    return {
      options: "/api/v1/vplib/definitions/options",
      payload: "/api/v1/vplib/definitions/payload",
      resolveFamilyProfile: "/api/v1/vplib/definitions/resolve-family-profile",
      resolveVariantProfile: "/api/v1/vplib/definitions/resolve-variant-profile",
      variantProfileBase: "/api/v1/vplib/definitions/variant-profiles/",
      emptyValuesBase: "/api/v1/vplib/definitions/empty-variant-values/",
      validateVariant: "/api/v1/vplib/definitions/validate-variant"
    };
  }

  function readEndpointFromContext(key, fallback) {
    try {
      var context = window.VectoplanCreateContext || {};
      var definitionsWindow = window.VectoplanCreateDefinitions || {};
      var definitionsApi = context.definitionsApi ||
        context.definitions_api ||
        window.VectoplanCreateDefinitions ||
        {};

      var definitions = context.definitions || {};
      var routes = context.routes || {};
      var endpointCandidates = [
        pathGet(definitionsApi, key, null),
        pathGet(definitionsApi, "routes." + key, null),
        pathGet(definitionsApi, "endpoints." + key, null),
        pathGet(definitionsWindow, key, null),
        pathGet(definitionsWindow, "routes." + key, null),
        pathGet(definitionsWindow, "endpoints." + key, null),
        pathGet(definitions, key, null),
        pathGet(definitions, "routes." + key, null),
        pathGet(definitions, "endpoints." + key, null)
      ];

      var routeKeyAliases = {
        options: ["definitions_options", "definitionsOptions"],
        payload: ["definitions_payload", "definitionsPayload"],
        resolveFamilyProfile: ["definitions_resolve_family_profile", "definitionsResolveFamilyProfile"],
        resolveVariantProfile: ["definitions_resolve_variant_profile", "definitionsResolveVariantProfile"],
        variantProfileBase: ["definitions_variant_profile_base", "definitionsVariantProfileBase"],
        emptyValuesBase: ["definitions_empty_variant_values_base", "definitionsEmptyVariantValuesBase"],
        validateVariant: ["definitions_validate_variant", "definitionsValidateVariant"]
      };

      (routeKeyAliases[key] || []).forEach(function (alias) {
        endpointCandidates.push(routes[alias]);
      });

      for (var index = 0; index < endpointCandidates.length; index += 1) {
        if (endpointCandidates[index]) {
          return endpointCandidates[index];
        }
      }

      return fallback;
    } catch (error) {
      return fallback;
    }
  }

  function getEndpoints(options) {
    try {
      var config = options || {};

      if (runtime.cache.endpoints && config.force !== true && config.forceReload !== true) {
        return runtime.cache.endpoints;
      }

      var defaults = getDefaultEndpoints();

      runtime.cache.endpoints = {
        options: readEndpointFromContext("options", defaults.options),
        payload: readEndpointFromContext("payload", defaults.payload),
        resolveFamilyProfile: readEndpointFromContext("resolveFamilyProfile", readEndpointFromContext("resolve_family_profile", defaults.resolveFamilyProfile)),
        resolveVariantProfile: readEndpointFromContext("resolveVariantProfile", readEndpointFromContext("resolve_variant_profile", defaults.resolveVariantProfile)),
        variantProfileBase: readEndpointFromContext("variantProfileBase", readEndpointFromContext("variant_profile_base", defaults.variantProfileBase)),
        emptyValuesBase: readEndpointFromContext("emptyValuesBase", readEndpointFromContext("empty_values_base", defaults.emptyValuesBase)),
        validateVariant: readEndpointFromContext("validateVariant", readEndpointFromContext("validate_variant", defaults.validateVariant))
      };

      return runtime.cache.endpoints;
    } catch (error) {
      warn("Could not read definitions endpoints.", error);
      return getDefaultEndpoints();
    }
  }

  function buildQuery(params) {
    try {
      var pairs = [];

      Object.keys(params || {}).forEach(function (key) {
        var value = params[key];

        if (value === null || value === undefined || value === "") {
          return;
        }

        pairs.push(encodeURIComponent(key) + "=" + encodeURIComponent(String(value)));
      });

      return pairs.length ? "?" + pairs.join("&") : "";
    } catch (error) {
      return "";
    }
  }

  function joinUrl(base, suffix) {
    try {
      var left = String(base || "");
      var right = String(suffix || "");

      if (!right) {
        return left;
      }

      if (left.slice(-1) !== "/") {
        left += "/";
      }

      return left + encodeURIComponent(right);
    } catch (error) {
      return String(base || "");
    }
  }

  function canFetch() {
    try {
      return typeof window.fetch === "function";
    } catch (error) {
      return false;
    }
  }

  function responseOk(payload) {
    try {
      if (!payload || typeof payload !== "object") {
        return false;
      }

      if (payload.ok === true || payload.healthy === true || payload.ready === true) {
        return true;
      }

      var status = String(payload.status || "").toLowerCase();

      return ["ok", "healthy", "ready", "success", "partial", "valid", "created"].indexOf(status) !== -1;
    } catch (error) {
      return false;
    }
  }

  function unwrapResponse(payload) {
    try {
      var source = payload || {};

      if (source.data && typeof source.data === "object") {
        return source.data;
      }

      if (source.payload && typeof source.payload === "object") {
        return source.payload;
      }

      if (source.result && typeof source.result === "object") {
        return source.result;
      }

      return source;
    } catch (error) {
      return payload || {};
    }
  }

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
        code: error.code || error.status || error.name || "error",
        message: error.message || String(error),
        status: error.status || null,
        payload: error.payload || error.raw || null
      };
    } catch (normalizationError) {
      return {
        code: "error",
        message: "Fehler konnte nicht normalisiert werden."
      };
    }
  }

  function requestJson(url, options) {
    try {
      var config = options || {};
      var method = (config.method || "GET").toUpperCase();
      var body = config.body || null;
      var cacheKey = method + " " + url + (body ? " " + U().safeJsonStringify(body, "") : "");

      if (config.useRequestCache !== false && runtime.cache.requests[cacheKey]) {
        return runtime.cache.requests[cacheKey];
      }

      if (!canFetch()) {
        return Promise.reject({
          code: "fetch_unavailable",
          message: "Fetch API ist nicht verfügbar."
        });
      }

      var fetchOptions = {
        method: method,
        headers: {
          "Accept": "application/json"
        },
        credentials: "same-origin"
      };

      if (method !== "GET" && body) {
        fetchOptions.headers["Content-Type"] = "application/json";
        fetchOptions.body = U().safeJsonStringify(body, "{}");
      }

      var promise = window.fetch(url, fetchOptions)
        .then(function (response) {
          return response.text().then(function (text) {
            var json = U().safeJsonParse(text, null);

            if (!response.ok) {
              throw {
                code: "http_" + String(response.status),
                message: "HTTP " + String(response.status),
                status: response.status,
                payload: json,
                url: url
              };
            }

            if (!json || typeof json !== "object") {
              throw {
                code: "invalid_json",
                message: "Antwort ist kein gültiges JSON.",
                url: url
              };
            }

            return json;
          });
        });

      if (config.useRequestCache !== false) {
        runtime.cache.requests[cacheKey] = promise.catch(function (error) {
          delete runtime.cache.requests[cacheKey];
          throw error;
        });
      }

      return promise;
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function readDefinitionsFromWindow() {
    try {
      var candidates = [];

      if (window.VectoplanCreateDefinitions) {
        candidates.push(window.VectoplanCreateDefinitions);
      }

      if (window.VectoplanCreateDefinitionsOptions) {
        candidates.push({
          options: window.VectoplanCreateDefinitionsOptions
        });
      }

      if (window.VectoplanCreateDefinitionCatalogs) {
        candidates.push({
          catalogs: window.VectoplanCreateDefinitionCatalogs
        });
      }

      if (window.VectoplanCreateContext && window.VectoplanCreateContext.definitions) {
        candidates.push(window.VectoplanCreateContext.definitions);
      }

      if (window.VectoplanCreateContext && window.VectoplanCreateContext.definitionsApi) {
        candidates.push(window.VectoplanCreateContext.definitionsApi);
      }

      if (window.VectoplanCreateContext && window.VectoplanCreateContext.definitionCatalogs) {
        candidates.push(window.VectoplanCreateContext.definitionCatalogs);
      }

      if (window.VectoplanCreateContext && window.VectoplanCreateContext.definition_catalogs) {
        candidates.push(window.VectoplanCreateContext.definition_catalogs);
      }

      if (window.VectoplanCreateContext && window.VectoplanCreateContext.options && window.VectoplanCreateContext.options.definitions) {
        candidates.push(window.VectoplanCreateContext.options.definitions);
      }

      if (window.VectoplanGeneratorContext) {
        candidates.push(window.VectoplanGeneratorContext);
      }

      if (window.VectoplanCreateContext && window.VectoplanCreateContext.generatorContext) {
        candidates.push(window.VectoplanCreateContext.generatorContext);
      }

      if (window.VectoplanCreateContext && window.VectoplanCreateContext.generator_context) {
        candidates.push(window.VectoplanCreateContext.generator_context);
      }

      for (var index = 0; index < candidates.length; index += 1) {
        var normalized = normalizeDefinitions(candidates[index]);

        if (hasDefinitionData(normalized)) {
          return normalized;
        }
      }

      return normalizeDefinitions({});
    } catch (error) {
      warn("Could not read definitions from window.", error);
      return normalizeDefinitions({});
    }
  }

  function hasDefinitionData(definitions) {
    try {
      var defs = definitions || getDefinitionsSync();

      return !!(
        defs.variant_profiles.length ||
        defs.variables.length ||
        defs.family_profiles.length ||
        defs.profile_bindings.length ||
        defs.object_kinds.length
      );
    } catch (error) {
      return false;
    }
  }

  function getDefinitionsSync(options) {
    try {
      var config = options || {};

      if (runtime.cache.definitions && config.force !== true && config.forceReload !== true) {
        return runtime.cache.definitions;
      }

      runtime.cache.definitions = readDefinitionsFromWindow();
      runtime.cache.definitionMaps = buildDefinitionMaps(runtime.cache.definitions);

      return runtime.cache.definitions;
    } catch (error) {
      warn("Could not get definitions sync.", error);
      return normalizeDefinitions({});
    }
  }

  function getDefinitionMaps(options) {
    try {
      var config = options || {};

      if (runtime.cache.definitionMaps && config.force !== true && config.forceReload !== true) {
        return runtime.cache.definitionMaps;
      }

      runtime.cache.definitionMaps = buildDefinitionMaps(getDefinitionsSync(config));
      return runtime.cache.definitionMaps;
    } catch (error) {
      warn("Could not build definition maps.", error);
      return buildDefinitionMaps({});
    }
  }

  function fetchDefinitions(options) {
    try {
      var config = options || {};

      if (hasDefinitionData(getDefinitionsSync()) && config.force !== true && config.forceReload !== true) {
        return Promise.resolve(getDefinitionsSync());
      }

      if (config.localOnly === true || !canFetch() || runtime.options.fetchDefinitions === false) {
        var localOnly = getDefinitionsSync();
        if (hasDefinitionData(localOnly)) {
          return Promise.resolve(localOnly);
        }

        return Promise.reject({
          code: "definitions_not_loaded",
          message: "Keine Definitionsdaten im Fensterkontext gefunden."
        });
      }

      var endpoints = getEndpoints();

      return requestJson(endpoints.options, {
        method: "GET",
        useRequestCache: config.useRequestCache !== false
      }).then(function (payload) {
        var data = unwrapResponse(payload);
        var definitions = normalizeDefinitions(data);

        if (!hasDefinitionData(definitions)) {
          definitions = normalizeDefinitions(payload);
        }

        if (!hasDefinitionData(definitions)) {
          throw {
            code: "definitions_empty",
            message: "Definitionsantwort enthält keine nutzbaren Definitionsdaten.",
            payload: payload
          };
        }

        runtime.cache.definitions = definitions;
        runtime.cache.definitionMaps = buildDefinitionMaps(definitions);

        U().dispatchDocument("vectoplan:create:definitions-ready", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          definitions: definitions,
          maps: runtime.cache.definitionMaps,
          __vp_variant_profiles_event: true
        }, {
          silent: true
        });

        return definitions;
      }).catch(function (error) {
        U().dispatchDocument("vectoplan:create:definitions-unavailable", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          error: normalizeError(error),
          definitions: getDefinitionsSync(),
          __vp_variant_profiles_event: true
        }, {
          silent: true
        });

        if (hasDefinitionData(getDefinitionsSync())) {
          return getDefinitionsSync();
        }

        throw error;
      });
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function firstValue(selectors, root) {
    try {
      var list = U().toArray(selectors);

      for (var index = 0; index < list.length; index += 1) {
        var node = U().qs(list[index], root || document);

        if (!node) {
          continue;
        }

        var value = U().getValue ? U().getValue(node, "") : (node.value || node.textContent || "");

        if (value) {
          return value;
        }
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function readContextFromDom(root) {
    try {
      var workspace = root && root.matches && root.matches(WORKSPACE_SELECTOR)
        ? root
        : U().qs(WORKSPACE_SELECTOR, root || document);

      var drawer = root && root.matches && root.matches(DRAWER_SELECTOR)
        ? root
        : U().qs(DRAWER_SELECTOR, root || document);

      var table = root && root.matches && root.matches(TABLE_SELECTOR)
        ? root
        : U().qs(TABLE_SELECTOR, root || document);

      var contextRoot = workspace || drawer || table || root || document;
      var createContext = window.VectoplanCreateContext || {};
      var defaults = createContext.uiState && createContext.uiState.defaults
        ? createContext.uiState.defaults
        : createContext.defaults || {};

      var context = {
        domain: firstValue(FIELD_SELECTORS.domain, document) ||
          U().attr(contextRoot, "data-vp-current-domain", "") ||
          defaults.domain ||
          "",

        category: firstValue(FIELD_SELECTORS.category, document) ||
          U().attr(contextRoot, "data-vp-current-category", "") ||
          defaults.category ||
          "",

        subcategory: firstValue(FIELD_SELECTORS.subcategory, document) ||
          U().attr(contextRoot, "data-vp-current-subcategory", "") ||
          defaults.subcategory ||
          "",

        object_kind: firstValue(FIELD_SELECTORS.objectKind, document) ||
          U().attr(contextRoot, "data-vp-current-object-kind", "") ||
          defaults.object_kind ||
          defaults.objectKind ||
          "cell_block",

        family_profile_id: firstValue(FIELD_SELECTORS.familyProfileId, document) ||
          U().attr(contextRoot, "data-vp-current-family-profile-id", "") ||
          U().attr(table, "data-vp-family-profile-id", "") ||
          defaults.family_profile_id ||
          defaults.familyProfileId ||
          "",

        variant_profile_id: firstValue(FIELD_SELECTORS.variantProfileId, document) ||
          U().attr(contextRoot, "data-vp-current-variant-profile-id", "") ||
          U().attr(table, "data-vp-variant-profile-id", "") ||
          defaults.variant_profile_id ||
          defaults.variantProfileId ||
          ""
      };

      return normalizeContext(context);
    } catch (error) {
      warn("Could not read profile context from DOM.", error);
      return normalizeContext({});
    }
  }

  function readContextFromState() {
    try {
      if (
        window.VectoplanCreateVariantState &&
        typeof window.VectoplanCreateVariantState.getContext === "function"
      ) {
        return normalizeContext(window.VectoplanCreateVariantState.getContext());
      }

      return normalizeContext({});
    } catch (error) {
      return normalizeContext({});
    }
  }

  function normalizeContext(context) {
    try {
      var raw = context || {};
      var taxonomyPath = raw.taxonomy_path || raw.taxonomyPath || "";

      return {
        domain: U().trim(raw.domain || raw.taxonomy_domain || raw.taxonomyDomain || ""),
        category: U().trim(raw.category || raw.taxonomy_category || raw.taxonomyCategory || ""),
        subcategory: U().trim(raw.subcategory || raw.taxonomy_subcategory || raw.taxonomySubcategory || ""),
        taxonomy_path: U().trim(taxonomyPath),
        taxonomyPath: U().trim(taxonomyPath),
        object_kind: U().normalizeObjectKind(raw.object_kind || raw.objectKind || raw.object_class || "cell_block"),
        objectKind: U().normalizeObjectKind(raw.object_kind || raw.objectKind || raw.object_class || "cell_block"),
        family_profile_id: U().normalizeProfileId(raw.family_profile_id || raw.familyProfileId || ""),
        familyProfileId: U().normalizeProfileId(raw.family_profile_id || raw.familyProfileId || ""),
        variant_profile_id: U().normalizeProfileId(raw.variant_profile_id || raw.variantProfileId || ""),
        variantProfileId: U().normalizeProfileId(raw.variant_profile_id || raw.variantProfileId || "")
      };
    } catch (error) {
      return {
        domain: "",
        category: "",
        subcategory: "",
        taxonomy_path: "",
        taxonomyPath: "",
        object_kind: "cell_block",
        objectKind: "cell_block",
        family_profile_id: "",
        familyProfileId: "",
        variant_profile_id: "",
        variantProfileId: ""
      };
    }
  }

  function getCurrentContext(options) {
    try {
      var config = options || {};
      var domContext = readContextFromDom(config.root || null);
      var stateContext = readContextFromState();

      var context = U().safeMerge(stateContext, domContext, config.context || {});
      context = normalizeContext(context);

      runtime.lastContext = context;
      runtime.lastContextKey = contextKey(context, "current");

      return context;
    } catch (error) {
      warn("Could not get current profile context.", error);
      return normalizeContext({});
    }
  }

  function collectContext(options) {
    return getCurrentContext(options || {});
  }

  function contextKey(context, suffix) {
    try {
      var ctx = normalizeContext(context || {});

      return [
        ctx.domain,
        ctx.category,
        ctx.subcategory,
        ctx.object_kind,
        ctx.family_profile_id,
        ctx.variant_profile_id,
        suffix || ""
      ].join("|");
    } catch (error) {
      return String(Math.random());
    }
  }

  function profileKey(profileId) {
    try {
      return U().normalizeProfileId(profileId || "");
    } catch (error) {
      return "";
    }
  }

  function valueMatches(ruleValue, contextValue) {
    try {
      if (ruleValue === null || ruleValue === undefined || ruleValue === "" || ruleValue === "*" || ruleValue === "any") {
        return true;
      }

      if (Array.isArray(ruleValue)) {
        if (!ruleValue.length) {
          return true;
        }

        return ruleValue.map(String).indexOf(String(contextValue || "")) !== -1;
      }

      return String(ruleValue) === String(contextValue || "");
    } catch (error) {
      return false;
    }
  }

  function listContainsAny(list, value) {
    try {
      var arr = U().toArray(list);

      if (!arr.length) {
        return true;
      }

      if (!value) {
        return false;
      }

      return arr.map(String).indexOf(String(value || "")) !== -1;
    } catch (error) {
      return false;
    }
  }

  function bindingMatches(binding, context, mode) {
    try {
      var ctx = normalizeContext(context || {});
      var item = binding || {};

      if (item.active === false || item.enabled === false) {
        return false;
      }

      if (!valueMatches(item.domain || item.taxonomy_domain || item.taxonomyDomain, ctx.domain)) {
        return false;
      }

      if (!valueMatches(item.category || item.taxonomy_category || item.taxonomyCategory, ctx.category)) {
        return false;
      }

      if (!valueMatches(item.subcategory || item.taxonomy_subcategory || item.taxonomySubcategory, ctx.subcategory)) {
        return false;
      }

      if (!valueMatches(item.object_kind || item.objectKind || item.object_class, ctx.object_kind)) {
        return false;
      }

      if (mode === "variant" && ctx.family_profile_id) {
        var bindingFamily = profileKey(item.family_profile_id || item.familyProfileId || "");

        if (bindingFamily && bindingFamily !== ctx.family_profile_id) {
          return false;
        }
      }

      if (item.use_only_if_family_profile_selected === true && !ctx.family_profile_id) {
        return false;
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function bindingScore(binding, context) {
    try {
      var ctx = normalizeContext(context || {});
      var item = binding || {};
      var score = 0;

      if ((item.domain || item.taxonomy_domain || item.taxonomyDomain) && valueMatches(item.domain || item.taxonomy_domain || item.taxonomyDomain, ctx.domain)) {
        score += 10;
      }

      if ((item.category || item.taxonomy_category || item.taxonomyCategory) && valueMatches(item.category || item.taxonomy_category || item.taxonomyCategory, ctx.category)) {
        score += 20;
      }

      if ((item.subcategory || item.taxonomy_subcategory || item.taxonomySubcategory) && valueMatches(item.subcategory || item.taxonomy_subcategory || item.taxonomySubcategory, ctx.subcategory)) {
        score += 30;
      }

      if ((item.object_kind || item.objectKind || item.object_class) && valueMatches(item.object_kind || item.objectKind || item.object_class, ctx.object_kind)) {
        score += 40;
      }

      if ((item.family_profile_id || item.familyProfileId) && ctx.family_profile_id && profileKey(item.family_profile_id || item.familyProfileId) === ctx.family_profile_id) {
        score += 50;
      }

      score += parseInt(item.priority || 0, 10) || 0;
      score -= (parseInt(item.sort_order || 0, 10) || 0) / 10000;

      return score;
    } catch (error) {
      return 0;
    }
  }

  function sortBindings(bindings, context) {
    try {
      return U().toArray(bindings).sort(function (a, b) {
        var diff = bindingScore(b, context) - bindingScore(a, context);

        if (diff !== 0) {
          return diff;
        }

        var sortA = parseInt(a.sort_order || 0, 10) || 0;
        var sortB = parseInt(b.sort_order || 0, 10) || 0;

        if (sortA !== sortB) {
          return sortA - sortB;
        }

        return String(a.id || "").localeCompare(String(b.id || ""));
      });
    } catch (error) {
      return U().toArray(bindings);
    }
  }

  function familyProfileMatches(profile, context) {
    try {
      var ctx = normalizeContext(context || {});
      var item = profile || {};

      if (item.active === false || item.enabled === false) {
        return false;
      }

      if (!listContainsAny(item.object_kinds || item.objectKinds, ctx.object_kind)) {
        return false;
      }

      if (ctx.domain && !listContainsAny(item.taxonomy_domains || item.domains, ctx.domain)) {
        return false;
      }

      if (ctx.category && !listContainsAny(item.taxonomy_categories || item.categories, ctx.category)) {
        return false;
      }

      if (ctx.subcategory && !listContainsAny(item.taxonomy_subcategories || item.subcategories, ctx.subcategory)) {
        return false;
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function familyProfileScore(profile, context) {
    try {
      var ctx = normalizeContext(context || {});
      var item = profile || {};
      var score = 0;

      if (listContainsAny(item.object_kinds || item.objectKinds, ctx.object_kind)) {
        score += 20;
      }

      if (ctx.domain && listContainsAny(item.taxonomy_domains || item.domains, ctx.domain)) {
        score += 10;
      }

      if (ctx.category && listContainsAny(item.taxonomy_categories || item.categories, ctx.category)) {
        score += 20;
      }

      if (ctx.subcategory && listContainsAny(item.taxonomy_subcategories || item.subcategories, ctx.subcategory)) {
        score += 30;
      }

      score += parseInt(item.priority || 0, 10) || 0;
      score -= (parseInt(item.sort_order || 0, 10) || 0) / 10000;

      return score;
    } catch (error) {
      return 0;
    }
  }

  function resolveFamilyProfileLocal(context) {
    try {
      var ctx = normalizeContext(context || {});
      var defs = getDefinitionsSync();
      var maps = getDefinitionMaps();

      if (ctx.family_profile_id && maps.familyProfilesById[ctx.family_profile_id]) {
        return {
          ok: true,
          source: "local_explicit",
          family_profile_id: ctx.family_profile_id,
          familyProfileId: ctx.family_profile_id,
          family_profile: maps.familyProfilesById[ctx.family_profile_id],
          familyProfile: maps.familyProfilesById[ctx.family_profile_id],
          context: ctx
        };
      }

      var matchingBindings = sortBindings(defs.profile_bindings.filter(function (binding) {
        return bindingMatches(binding, ctx, "family") && (binding.family_profile_id || binding.familyProfileId);
      }), ctx);

      if (matchingBindings.length) {
        var binding = matchingBindings[0];
        var familyId = profileKey(binding.family_profile_id || binding.familyProfileId || "");

        if (familyId && maps.familyProfilesById[familyId]) {
          return {
            ok: true,
            source: "local_binding",
            family_profile_id: familyId,
            familyProfileId: familyId,
            family_profile: maps.familyProfilesById[familyId],
            familyProfile: maps.familyProfilesById[familyId],
            binding: binding,
            context: ctx
          };
        }
      }

      var matchingProfiles = defs.family_profiles
        .filter(function (profile) {
          return familyProfileMatches(profile, ctx);
        })
        .sort(function (a, b) {
          return familyProfileScore(b, ctx) - familyProfileScore(a, ctx);
        });

      if (matchingProfiles.length) {
        return {
          ok: true,
          source: "local_family_profile_match",
          family_profile_id: profileKey(matchingProfiles[0].id || matchingProfiles[0].key),
          familyProfileId: profileKey(matchingProfiles[0].id || matchingProfiles[0].key),
          family_profile: matchingProfiles[0],
          familyProfile: matchingProfiles[0],
          context: ctx
        };
      }

      return {
        ok: false,
        source: "local",
        error: {
          code: "family_profile_not_found",
          message: "Kein Family Profile im lokalen Definitionskatalog gefunden."
        },
        context: ctx
      };
    } catch (error) {
      return {
        ok: false,
        source: "local",
        error: normalizeError(error),
        context: normalizeContext(context || {})
      };
    }
  }

  function resolveVariantProfileLocal(context) {
    try {
      var ctx = normalizeContext(context || {});
      var defs = getDefinitionsSync();
      var maps = getDefinitionMaps();

      if (ctx.variant_profile_id && maps.variantProfilesById[ctx.variant_profile_id]) {
        return {
          ok: true,
          source: "local_explicit",
          family_profile_id: ctx.family_profile_id,
          familyProfileId: ctx.family_profile_id,
          variant_profile_id: ctx.variant_profile_id,
          variantProfileId: ctx.variant_profile_id,
          variant_profile: maps.variantProfilesById[ctx.variant_profile_id],
          variantProfile: maps.variantProfilesById[ctx.variant_profile_id],
          profile: maps.variantProfilesById[ctx.variant_profile_id],
          context: ctx
        };
      }

      var familyResult = resolveFamilyProfileLocal(ctx);
      var familyProfileId = profileKey(ctx.family_profile_id || familyResult.family_profile_id || "");

      if (familyProfileId) {
        ctx.family_profile_id = familyProfileId;
        ctx.familyProfileId = familyProfileId;
      }

      var matchingBindings = sortBindings(defs.profile_bindings.filter(function (binding) {
        return bindingMatches(binding, ctx, "variant") && (binding.variant_profile_id || binding.variantProfileId);
      }), ctx);

      if (matchingBindings.length) {
        var binding = matchingBindings[0];
        var variantId = profileKey(binding.variant_profile_id || binding.variantProfileId || "");

        if (variantId && maps.variantProfilesById[variantId]) {
          return {
            ok: true,
            source: "local_binding",
            family_profile_id: familyProfileId,
            familyProfileId: familyProfileId,
            family_profile: familyProfileId ? maps.familyProfilesById[familyProfileId] : null,
            familyProfile: familyProfileId ? maps.familyProfilesById[familyProfileId] : null,
            variant_profile_id: variantId,
            variantProfileId: variantId,
            variant_profile: maps.variantProfilesById[variantId],
            variantProfile: maps.variantProfilesById[variantId],
            profile: maps.variantProfilesById[variantId],
            binding: binding,
            context: ctx
          };
        }
      }

      if (familyProfileId && maps.familyProfilesById[familyProfileId]) {
        var familyProfile = maps.familyProfilesById[familyProfileId];
        var defaultVariantProfileId = profileKey(
          familyProfile.default_variant_profile_id ||
          familyProfile.defaultVariantProfileId ||
          familyProfile.variant_profile_id ||
          familyProfile.variantProfileId ||
          ""
        );

        if (defaultVariantProfileId && maps.variantProfilesById[defaultVariantProfileId]) {
          return {
            ok: true,
            source: "local_family_default",
            family_profile_id: familyProfileId,
            familyProfileId: familyProfileId,
            family_profile: familyProfile,
            familyProfile: familyProfile,
            variant_profile_id: defaultVariantProfileId,
            variantProfileId: defaultVariantProfileId,
            variant_profile: maps.variantProfilesById[defaultVariantProfileId],
            variantProfile: maps.variantProfilesById[defaultVariantProfileId],
            profile: maps.variantProfilesById[defaultVariantProfileId],
            context: ctx
          };
        }
      }

      var matchingVariantProfiles = defs.variant_profiles.filter(function (profile) {
        if (!profile || profile.active === false || profile.enabled === false) {
          return false;
        }

        if (ctx.object_kind && !listContainsAny(profile.object_kinds || profile.objectKinds, ctx.object_kind)) {
          return false;
        }

        if (familyProfileId && !listContainsAny(profile.family_profiles || profile.familyProfiles, familyProfileId)) {
          return false;
        }

        return true;
      });

      if (matchingVariantProfiles.length) {
        matchingVariantProfiles.sort(function (a, b) {
          var sortA = parseInt(a.sort_order || 0, 10) || 0;
          var sortB = parseInt(b.sort_order || 0, 10) || 0;
          return sortA - sortB;
        });

        var matchedId = profileKey(matchingVariantProfiles[0].id || matchingVariantProfiles[0].key);

        return {
          ok: true,
          source: "local_variant_profile_match",
          family_profile_id: familyProfileId,
          familyProfileId: familyProfileId,
          family_profile: familyProfileId ? maps.familyProfilesById[familyProfileId] : null,
          familyProfile: familyProfileId ? maps.familyProfilesById[familyProfileId] : null,
          variant_profile_id: matchedId,
          variantProfileId: matchedId,
          variant_profile: matchingVariantProfiles[0],
          variantProfile: matchingVariantProfiles[0],
          profile: matchingVariantProfiles[0],
          context: ctx
        };
      }

      return {
        ok: false,
        source: "local",
        family_profile_id: familyProfileId,
        familyProfileId: familyProfileId,
        error: {
          code: "variant_profile_not_found",
          message: "Kein Variant Profile im lokalen Definitionskatalog gefunden."
        },
        context: ctx
      };
    } catch (error) {
      return {
        ok: false,
        source: "local",
        error: normalizeError(error),
        context: normalizeContext(context || {})
      };
    }
  }

  function normalizeFamilyResult(payload, context, source) {
    try {
      var data = unwrapResponse(payload || {});
      var ctx = normalizeContext(context || data.context || {});
      var familyProfileId = profileKey(
        data.family_profile_id ||
        data.familyProfileId ||
        data.profile_id ||
        data.profileId ||
        ""
      );

      var familyProfile = data.family_profile ||
        data.familyProfile ||
        data.profile ||
        null;

      if (!familyProfileId && familyProfile && familyProfile.id) {
        familyProfileId = profileKey(familyProfile.id);
      }

      if (!familyProfile && familyProfileId) {
        familyProfile = getDefinitionMaps().familyProfilesById[familyProfileId] || null;
      }

      return {
        ok: responseOk(payload) || !!familyProfileId,
        source: source || data.source || "unknown",
        family_profile_id: familyProfileId,
        familyProfileId: familyProfileId,
        family_profile: familyProfile,
        familyProfile: familyProfile,
        context: ctx,
        raw: payload
      };
    } catch (error) {
      return {
        ok: false,
        source: source || "unknown",
        error: normalizeError(error),
        context: normalizeContext(context || {}),
        raw: payload
      };
    }
  }

  function normalizeVariantResult(payload, context, source) {
    try {
      var data = unwrapResponse(payload || {});
      var ctx = normalizeContext(context || data.context || {});

      var familyProfileId = profileKey(
        data.family_profile_id ||
        data.familyProfileId ||
        ctx.family_profile_id ||
        ""
      );

      var variantProfileId = profileKey(
        data.variant_profile_id ||
        data.variantProfileId ||
        data.profile_id ||
        data.profileId ||
        ctx.variant_profile_id ||
        ""
      );

      var familyProfile = data.family_profile ||
        data.familyProfile ||
        null;

      var variantProfile = data.variant_profile ||
        data.variantProfile ||
        data.profile ||
        null;

      if (!familyProfile && familyProfileId) {
        familyProfile = getDefinitionMaps().familyProfilesById[familyProfileId] || null;
      }

      if (!variantProfile && variantProfileId) {
        variantProfile = getDefinitionMaps().variantProfilesById[variantProfileId] || null;
      }

      if (!variantProfileId && variantProfile && variantProfile.id) {
        variantProfileId = profileKey(variantProfile.id);
      }

      if (!familyProfileId && variantProfile && variantProfile.family_profiles && variantProfile.family_profiles.length === 1) {
        familyProfileId = profileKey(variantProfile.family_profiles[0]);
      }

      return {
        ok: responseOk(payload) || !!variantProfileId,
        source: source || data.source || "unknown",
        family_profile_id: familyProfileId,
        familyProfileId: familyProfileId,
        family_profile: familyProfile,
        familyProfile: familyProfile,
        variant_profile_id: variantProfileId,
        variantProfileId: variantProfileId,
        variant_profile: variantProfile,
        variantProfile: variantProfile,
        profile: variantProfile,
        binding: data.binding || null,
        context: normalizeContext(U().safeMerge(ctx, {
          family_profile_id: familyProfileId,
          variant_profile_id: variantProfileId
        })),
        raw: payload
      };
    } catch (error) {
      return {
        ok: false,
        source: source || "unknown",
        error: normalizeError(error),
        context: normalizeContext(context || {}),
        raw: payload
      };
    }
  }

  function normalizeProfilePayload(payload, profileId, source) {
    try {
      var id = profileKey(profileId);
      var data = unwrapResponse(payload || {});
      var profile = data.variant_profile || data.variantProfile || data.profile || data;

      if (data.data && data.data.profile) {
        profile = data.data.profile;
      }

      if (!profile || !profile.id) {
        var maps = getDefinitionMaps();
        profile = maps.variantProfilesById[id] || null;
      }

      if (!profile) {
        return {
          ok: false,
          source: source || "unknown",
          profile_id: id,
          variant_profile_id: id,
          error: {
            code: "variant_profile_not_found",
            message: "Variant Profile wurde nicht gefunden."
          },
          raw: payload
        };
      }

      return {
        ok: true,
        source: source || data.source || "unknown",
        profile_id: profileKey(profile.id || id),
        variant_profile_id: profileKey(profile.id || id),
        variantProfileId: profileKey(profile.id || id),
        variant_profile: profile,
        variantProfile: profile,
        profile: profile,
        raw: payload
      };
    } catch (error) {
      return {
        ok: false,
        source: source || "unknown",
        profile_id: profileId,
        variant_profile_id: profileId,
        error: normalizeError(error),
        raw: payload
      };
    }
  }

  function normalizeEmptyValuesPayload(payload, profileId, context, source) {
    try {
      var id = profileKey(profileId);
      var data = unwrapResponse(payload || {});
      var values = data.values ||
        data.empty_values ||
        data.emptyValues ||
        data.default_values ||
        data.defaultValues ||
        data.defaults ||
        {};

      if (!values || typeof values !== "object" || Array.isArray(values)) {
        values = {};
      }

      return {
        ok: responseOk(payload) || true,
        source: source || data.source || "unknown",
        profile_id: id,
        variant_profile_id: id,
        variantProfileId: id,
        values: values,
        context: normalizeContext(context || {}),
        raw: payload
      };
    } catch (error) {
      return {
        ok: false,
        source: source || "unknown",
        profile_id: profileId,
        variant_profile_id: profileId,
        values: {},
        error: normalizeError(error),
        context: normalizeContext(context || {}),
        raw: payload
      };
    }
  }

  function resolveFamilyProfileBackend(context, options) {
    try {
      var ctx = normalizeContext(context || {});
      var config = options || {};
      var endpoints = getEndpoints();

      if (config.method === "POST") {
        return requestJson(endpoints.resolveFamilyProfile, {
          method: "POST",
          body: ctx,
          useRequestCache: config.useRequestCache !== false
        }).then(function (payload) {
          return normalizeFamilyResult(payload, ctx, "backend_post");
        });
      }

      return requestJson(endpoints.resolveFamilyProfile + buildQuery(ctx), {
        method: "GET",
        useRequestCache: config.useRequestCache !== false
      }).then(function (payload) {
        return normalizeFamilyResult(payload, ctx, "backend_get");
      });
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function resolveVariantProfileBackend(context, options) {
    try {
      var ctx = normalizeContext(context || {});
      var config = options || {};
      var endpoints = getEndpoints();

      if (config.method === "POST") {
        return requestJson(endpoints.resolveVariantProfile, {
          method: "POST",
          body: ctx,
          useRequestCache: config.useRequestCache !== false
        }).then(function (payload) {
          return normalizeVariantResult(payload, ctx, "backend_post");
        });
      }

      return requestJson(endpoints.resolveVariantProfile + buildQuery(ctx), {
        method: "GET",
        useRequestCache: config.useRequestCache !== false
      }).then(function (payload) {
        return normalizeVariantResult(payload, ctx, "backend_get");
      });
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function getVariantProfileBackend(profileId, options) {
    try {
      var id = profileKey(profileId);
      var config = options || {};
      var endpoints = getEndpoints();

      if (!id) {
        return Promise.reject({
          code: "missing_profile_id",
          message: "Keine Variant Profile ID angegeben."
        });
      }

      return requestJson(joinUrl(endpoints.variantProfileBase, id), {
        method: "GET",
        useRequestCache: config.useRequestCache !== false
      }).then(function (payload) {
        return normalizeProfilePayload(payload, id, "backend");
      });
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function getEmptyValuesBackend(profileId, context, options) {
    try {
      var id = profileKey(profileId);
      var ctx = normalizeContext(context || {});
      var config = options || {};
      var endpoints = getEndpoints();

      if (!id) {
        return Promise.reject({
          code: "missing_profile_id",
          message: "Keine Variant Profile ID für Empty Values angegeben."
        });
      }

      if (config.method === "POST") {
        return requestJson(joinUrl(endpoints.emptyValuesBase, id), {
          method: "POST",
          body: ctx,
          useRequestCache: config.useRequestCache !== false
        }).then(function (payload) {
          return normalizeEmptyValuesPayload(payload, id, ctx, "backend_post");
        });
      }

      return requestJson(joinUrl(endpoints.emptyValuesBase, id) + buildQuery(ctx), {
        method: "GET",
        useRequestCache: config.useRequestCache !== false
      }).then(function (payload) {
        return normalizeEmptyValuesPayload(payload, id, ctx, "backend_get");
      });
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function getVariantProfileLocal(profileId) {
    try {
      var id = profileKey(profileId);
      var maps = getDefinitionMaps();
      var profile = maps.variantProfilesById[id] || null;

      if (!profile) {
        return {
          ok: false,
          source: "local",
          profile_id: id,
          variant_profile_id: id,
          error: {
            code: "variant_profile_not_found",
            message: "Variant Profile wurde lokal nicht gefunden."
          }
        };
      }

      return {
        ok: true,
        source: "local",
        profile_id: id,
        variant_profile_id: id,
        variantProfileId: id,
        variant_profile: profile,
        variantProfile: profile,
        profile: profile
      };
    } catch (error) {
      return {
        ok: false,
        source: "local",
        profile_id: profileId,
        variant_profile_id: profileId,
        error: normalizeError(error)
      };
    }
  }

  function getProfileFieldKeys(profile) {
    try {
      var item = profile || {};
      var fieldKeys = [];

      function addKey(value) {
        var key = "";

        if (typeof value === "string") {
          key = value;
        } else if (value && typeof value === "object") {
          key = value.key || value.id || value.name || value.variable_key || value.variableKey || "";
        }

        key = String(key || "").trim();

        if (key && fieldKeys.indexOf(key) === -1) {
          fieldKeys.push(key);
        }
      }

      U().toArray(item.sections).forEach(function (section) {
        U().toArray(section.fields).forEach(addKey);
      });

      U().toArray(item.fields).forEach(addKey);
      U().toArray(item.required_fields || item.requiredFields).forEach(addKey);
      U().toArray(item.optional_fields || item.optionalFields).forEach(addKey);

      return fieldKeys;
    } catch (error) {
      return [];
    }
  }

  function defaultValueForVariable(variable) {
    try {
      if (!variable || typeof variable !== "object") {
        return null;
      }

      if (Object.prototype.hasOwnProperty.call(variable, "default_value")) {
        return U().deepClone(variable.default_value, null);
      }

      if (Object.prototype.hasOwnProperty.call(variable, "defaultValue")) {
        return U().deepClone(variable.defaultValue, null);
      }

      var type = variable.value_type || variable.valueType || variable.type || "string";

      if (type === "boolean") {
        return false;
      }

      if (type === "number" || type === "integer" || type === "money" || type === "float") {
        return null;
      }

      if (type === "document_list" || type === "document" || type === "documents" || type === "array" || type === "multi_enum") {
        return [];
      }

      if (type === "object") {
        return {};
      }

      return "";
    } catch (error) {
      return null;
    }
  }

  function getEmptyValuesLocal(profileId, context) {
    try {
      var id = profileKey(profileId);
      var profileResult = getVariantProfileLocal(id);

      if (!profileResult.ok) {
        return {
          ok: false,
          source: "local",
          profile_id: id,
          variant_profile_id: id,
          values: {},
          error: profileResult.error,
          context: normalizeContext(context || {})
        };
      }

      var defs = getDefinitionsSync();
      var maps = getDefinitionMaps();
      var profile = profileResult.variant_profile;
      var values = {};

      getProfileFieldKeys(profile).forEach(function (key) {
        var variable = maps.variablesByKey[key] || null;
        values[key] = defaultValueForVariable(variable);
      });

      if (profile.default_values && typeof profile.default_values === "object") {
        Object.keys(profile.default_values).forEach(function (key) {
          values[key] = U().deepClone(profile.default_values[key], profile.default_values[key]);
        });
      }

      if (profile.defaultValues && typeof profile.defaultValues === "object") {
        Object.keys(profile.defaultValues).forEach(function (key) {
          values[key] = U().deepClone(profile.defaultValues[key], profile.defaultValues[key]);
        });
      }

      if (!values["variant.variant_id"]) {
        values["variant.variant_id"] = "default";
      }

      if (!values["variant.label"]) {
        values["variant.label"] = "Standard";
      }

      return {
        ok: true,
        source: "local",
        profile_id: id,
        variant_profile_id: id,
        variantProfileId: id,
        values: values,
        definitions: defs,
        context: normalizeContext(context || {})
      };
    } catch (error) {
      return {
        ok: false,
        source: "local",
        profile_id: profileId,
        variant_profile_id: profileId,
        values: {},
        error: normalizeError(error),
        context: normalizeContext(context || {})
      };
    }
  }

  function shouldPreferLocal(options) {
    try {
      var config = options || {};

      if (config.localOnly === true) {
        return true;
      }

      if (config.preferLocal === false) {
        return false;
      }

      if (runtime.options.preferLocal === false) {
        return false;
      }

      return true;
    } catch (error) {
      return true;
    }
  }

  function resolveFamilyProfile(context, options) {
    try {
      var ctx = normalizeContext(context || getCurrentContext());
      var config = options || {};
      var key = contextKey(ctx, "family");

      if (runtime.cache.familyResolve[key] && config.force !== true && config.forceReload !== true) {
        return Promise.resolve(runtime.cache.familyResolve[key]);
      }

      var localFirst = resolveFamilyProfileLocal(ctx);

      if ((config.localOnly === true || shouldPreferLocal(config) || !canFetch()) && localFirst.ok) {
        runtime.cache.familyResolve[key] = localFirst;
        dispatchFamilyResolved(localFirst);
        return Promise.resolve(localFirst);
      }

      if (config.localOnly === true || !canFetch()) {
        runtime.cache.familyResolve[key] = localFirst;
        dispatchFamilyResolved(localFirst);
        return Promise.resolve(localFirst);
      }

      return resolveFamilyProfileBackend(ctx, config)
        .then(function (result) {
          if (!result.ok) {
            throw result;
          }

          runtime.cache.familyResolve[key] = result;
          dispatchFamilyResolved(result);
          return result;
        })
        .catch(function (error) {
          var local = localFirst.ok ? localFirst : resolveFamilyProfileLocal(ctx);

          if (local.ok) {
            local.backend_error = normalizeError(error);
            runtime.cache.familyResolve[key] = local;
            dispatchFamilyResolved(local);
            return local;
          }

          var failed = {
            ok: false,
            source: "backend_then_local_failed",
            context: ctx,
            error: normalizeError(error),
            local_error: local.error || null
          };

          dispatchResolutionFailed("family", failed);
          return failed;
        });
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function resolveVariantProfile(context, options) {
    try {
      var ctx = normalizeContext(context || getCurrentContext());
      var config = options || {};
      var key = contextKey(ctx, "variant");

      if (runtime.cache.variantResolve[key] && config.force !== true && config.forceReload !== true) {
        return Promise.resolve(runtime.cache.variantResolve[key]);
      }

      var localFirst = resolveVariantProfileLocal(ctx);

      if ((config.localOnly === true || shouldPreferLocal(config) || !canFetch()) && localFirst.ok) {
        runtime.cache.variantResolve[key] = localFirst;
        applyResolvedProfile(localFirst);
        dispatchVariantResolved(localFirst);
        return Promise.resolve(localFirst);
      }

      if (config.localOnly === true || !canFetch()) {
        runtime.cache.variantResolve[key] = localFirst;

        if (localFirst.ok) {
          applyResolvedProfile(localFirst);
          dispatchVariantResolved(localFirst);
        } else {
          dispatchResolutionFailed("variant", localFirst);
        }

        return Promise.resolve(localFirst);
      }

      return resolveVariantProfileBackend(ctx, config)
        .then(function (result) {
          if (!result.ok) {
            throw result;
          }

          runtime.cache.variantResolve[key] = result;
          applyResolvedProfile(result);
          dispatchVariantResolved(result);
          return result;
        })
        .catch(function (error) {
          var local = localFirst.ok ? localFirst : resolveVariantProfileLocal(ctx);

          if (local.ok) {
            local.backend_error = normalizeError(error);
            runtime.cache.variantResolve[key] = local;
            applyResolvedProfile(local);
            dispatchVariantResolved(local);
            return local;
          }

          var failed = {
            ok: false,
            source: "backend_then_local_failed",
            context: ctx,
            error: normalizeError(error),
            local_error: local.error || null
          };

          dispatchResolutionFailed("variant", failed);
          return failed;
        });
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function getVariantProfile(profileId, options) {
    try {
      var id = profileKey(profileId);
      var config = options || {};

      if (!id) {
        return Promise.resolve({
          ok: false,
          source: "client",
          error: {
            code: "missing_profile_id",
            message: "Keine Variant Profile ID angegeben."
          }
        });
      }

      if (runtime.cache.variantProfiles[id] && config.force !== true && config.forceReload !== true) {
        return Promise.resolve(runtime.cache.variantProfiles[id]);
      }

      var localFirst = getVariantProfileLocal(id);

      if ((config.localOnly === true || shouldPreferLocal(config) || !canFetch()) && localFirst.ok) {
        runtime.cache.variantProfiles[id] = localFirst;
        dispatchVariantProfileLoaded(localFirst);
        return Promise.resolve(localFirst);
      }

      if (config.localOnly === true || !canFetch()) {
        runtime.cache.variantProfiles[id] = localFirst;

        if (localFirst.ok) {
          dispatchVariantProfileLoaded(localFirst);
        }

        return Promise.resolve(localFirst);
      }

      return getVariantProfileBackend(id, config)
        .then(function (result) {
          if (!result.ok) {
            throw result;
          }

          runtime.cache.variantProfiles[id] = result;
          dispatchVariantProfileLoaded(result);
          return result;
        })
        .catch(function (error) {
          var local = localFirst.ok ? localFirst : getVariantProfileLocal(id);

          if (local.ok) {
            local.backend_error = normalizeError(error);
            runtime.cache.variantProfiles[id] = local;
            dispatchVariantProfileLoaded(local);
            return local;
          }

          var failed = {
            ok: false,
            source: "backend_then_local_failed",
            profile_id: id,
            error: normalizeError(error),
            local_error: local.error || null
          };

          dispatchResolutionFailed("profile", failed);
          return failed;
        });
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function getEmptyVariantValues(profileId, context, options) {
    try {
      var id = profileKey(profileId);
      var ctx = normalizeContext(context || getCurrentContext());
      var config = options || {};
      var key = id + "|" + contextKey(ctx, "empty");

      if (!id) {
        return Promise.resolve({
          ok: false,
          source: "client",
          values: {},
          error: {
            code: "missing_profile_id",
            message: "Keine Variant Profile ID für Empty Values angegeben."
          }
        });
      }

      if (runtime.cache.emptyValues[key] && config.force !== true && config.forceReload !== true) {
        return Promise.resolve(runtime.cache.emptyValues[key]);
      }

      var localFirst = getEmptyValuesLocal(id, ctx);

      if ((config.localOnly === true || shouldPreferLocal(config) || !canFetch()) && localFirst.ok) {
        runtime.cache.emptyValues[key] = localFirst;
        dispatchEmptyValuesReady(localFirst);
        return Promise.resolve(localFirst);
      }

      if (config.localOnly === true || !canFetch()) {
        runtime.cache.emptyValues[key] = localFirst;

        if (localFirst.ok) {
          dispatchEmptyValuesReady(localFirst);
        }

        return Promise.resolve(localFirst);
      }

      return getEmptyValuesBackend(id, ctx, config)
        .then(function (result) {
          if (!result.ok) {
            throw result;
          }

          runtime.cache.emptyValues[key] = result;
          dispatchEmptyValuesReady(result);
          return result;
        })
        .catch(function (error) {
          var local = localFirst.ok ? localFirst : getEmptyValuesLocal(id, ctx);

          if (local.ok) {
            local.backend_error = normalizeError(error);
            runtime.cache.emptyValues[key] = local;
            dispatchEmptyValuesReady(local);
            return local;
          }

          var failed = {
            ok: false,
            source: "backend_then_local_failed",
            profile_id: id,
            values: {},
            error: normalizeError(error),
            local_error: local.error || null,
            context: ctx
          };

          dispatchResolutionFailed("empty_values", failed);
          return failed;
        });
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function resolveCurrentProfile(options) {
    try {
      var config = options || {};
      var context = normalizeContext(config.context || getCurrentContext(config));
      var key = contextKey(context, "resolve_current");

      if (runtime.activeResolvePromise && runtime.activeResolveKey === key && config.force !== true && config.forceReload !== true) {
        runtime.suppressedResolveCount += 1;
        return runtime.activeResolvePromise;
      }

      if (runtime.lastResolved && runtime.lastContextKey === key && config.force !== true && config.forceReload !== true) {
        return Promise.resolve(runtime.lastResolved);
      }

      runtime.resolveInProgress = true;
      runtime.lastContextKey = key;
      runtime.activeResolveKey = key;

      runtime.activeResolvePromise = fetchDefinitions(config)
        .catch(function () {
          return getDefinitionsSync();
        })
        .then(function () {
          return resolveFamilyProfile(context, config);
        })
        .then(function (familyResult) {
          var nextContext = normalizeContext(U().safeMerge(context, {
            family_profile_id: familyResult.family_profile_id || context.family_profile_id
          }));

          return resolveVariantProfile(nextContext, config);
        })
        .then(function (variantResult) {
          if (!variantResult.ok) {
            runtime.resolveInProgress = false;
            runtime.activeResolvePromise = null;
            return variantResult;
          }

          return getVariantProfile(variantResult.variant_profile_id, config)
            .then(function (profileResult) {
              var result = U().safeMerge(variantResult, {
                profile_payload: profileResult,
                variant_profile: profileResult.variant_profile || variantResult.variant_profile,
                variantProfile: profileResult.variant_profile || variantResult.variant_profile,
                profile: profileResult.variant_profile || variantResult.variant_profile
              });

              runtime.resolveInProgress = false;
              runtime.activeResolvePromise = null;
              runtime.lastResolved = result;
              runtime.lastResolvedSignature = resolvedSignature(result);
              runtime.lastProfilePayload = profileResult;

              applyResolvedProfile(result);
              dispatchVariantResolved(result);

              return result;
            });
        })
        .catch(function (error) {
          runtime.resolveInProgress = false;
          runtime.activeResolvePromise = null;
          dispatchResolutionFailed("current", {
            ok: false,
            source: config.source || "resolve_current",
            error: normalizeError(error),
            context: context
          });
          throw error;
        });

      return runtime.activeResolvePromise;
    } catch (error) {
      runtime.resolveInProgress = false;
      runtime.activeResolvePromise = null;
      return Promise.reject(error);
    }
  }

  function getResolvedProfileBundle(context, options) {
    try {
      var config = options || {};
      var ctx = normalizeContext(context || getCurrentContext(config));

      return resolveCurrentProfile(U().safeMerge(config, {
        context: ctx
      })).then(function (resolved) {
        if (!resolved.ok) {
          return resolved;
        }

        return getEmptyVariantValues(resolved.variant_profile_id, resolved.context || ctx, config)
          .then(function (emptyValues) {
            var bundle = U().safeMerge(resolved, {
              empty_values: emptyValues.values || {},
              emptyValues: emptyValues.values || {},
              empty_values_payload: emptyValues,
              emptyValuesPayload: emptyValues
            });

            runtime.lastBundle = bundle;
            runtime.lastBundleSignature = resolvedSignature(bundle) + "::" + U().safeJsonStringify(emptyValues.values || {}, "{}");

            return bundle;
          });
      });
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function getResolvedProfileBundleSync() {
    try {
      return runtime.lastBundle || runtime.lastResolved || null;
    } catch (error) {
      return null;
    }
  }

  function getCurrentProfilePayload() {
    try {
      return runtime.lastProfilePayload || {
        ok: !!(runtime.lastResolved && runtime.lastResolved.variant_profile_id),
        source: "sync_cache",
        profile_id: runtime.lastResolved ? runtime.lastResolved.variant_profile_id : "",
        variant_profile_id: runtime.lastResolved ? runtime.lastResolved.variant_profile_id : "",
        variant_profile: runtime.lastResolved ? runtime.lastResolved.variant_profile || runtime.lastResolved.profile || null : null,
        profile: runtime.lastResolved ? runtime.lastResolved.variant_profile || runtime.lastResolved.profile || null : null
      };
    } catch (error) {
      return {};
    }
  }

  function setAttrIfChanged(node, name, value) {
    try {
      if (!node || !name) {
        return false;
      }

      var next = value === null || value === undefined ? "" : String(value);

      if (U().attr(node, name, "") === next) {
        return false;
      }

      U().setAttr(node, name, next);
      return true;
    } catch (error) {
      return false;
    }
  }

  function setTextIfChanged(node, value) {
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
  }

  function setFieldNodeValue(field, value, options) {
    try {
      var config = options || {};

      if (!field) {
        return false;
      }

      var next = value === null || value === undefined ? "" : String(value);

      if (field.value === next) {
        return false;
      }

      field.value = next;
      U().setAttr(field, "data-vp-last-profile-sync", String(Date.now()));
      U().setAttr(field, "data-vp-last-profile-sync-source", config.source || COMPONENT_NAME);
      U().setAttr(field, "data-vp-programmatic-event-source", COMPONENT_NAME);

      if (config.emitNativeEvents === true) {
        U().dispatchNative(field, "input", {
          source: COMPONENT_NAME,
          silent: true
        });
        U().dispatchNative(field, "change", {
          source: COMPONENT_NAME,
          silent: true
        });
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function setFieldValue(selectorList, value, options) {
    try {
      var selectors = U().toArray(selectorList);
      var changed = false;
      var config = options || {};

      selectors.forEach(function (selector) {
        U().qsa(selector).forEach(function (field) {
          try {
            changed = setFieldNodeValue(field, value || "", config) || changed;
          } catch (fieldError) {
            warn("Could not set profile field value.", fieldError);
          }
        });
      });

      return changed;
    } catch (error) {
      warn("Could not set fields by selector.", error);
      return false;
    }
  }

  function resolvedSignature(result) {
    try {
      var source = result || {};
      var context = normalizeContext(source.context || {});

      return [
        source.family_profile_id || "",
        source.variant_profile_id || "",
        source.variant_profile && source.variant_profile.id ? source.variant_profile.id : "",
        context.domain || "",
        context.category || "",
        context.subcategory || "",
        context.object_kind || ""
      ].join("::");
    } catch (error) {
      return "";
    }
  }

  function updateProfileAttrs(result, options) {
    try {
      var config = options || {};
      var familyProfileId = profileKey(result.family_profile_id || result.familyProfileId || "");
      var variantProfileId = profileKey(result.variant_profile_id || result.variantProfileId || "");
      var changed = false;

      U().qsa(WORKSPACE_SELECTOR).forEach(function (workspace) {
        changed = setAttrIfChanged(workspace, "data-vp-current-family-profile-id", familyProfileId) || changed;
        changed = setAttrIfChanged(workspace, "data-vp-current-variant-profile-id", variantProfileId) || changed;
      });

      U().qsa(TABLE_SELECTOR).forEach(function (table) {
        changed = setAttrIfChanged(table, "data-vp-family-profile-id", familyProfileId) || changed;
        changed = setAttrIfChanged(table, "data-vp-variant-profile-id", variantProfileId) || changed;
      });

      U().qsa(DRAWER_SELECTOR).forEach(function (drawer) {
        changed = setAttrIfChanged(drawer, "data-vp-current-family-profile-id", familyProfileId) || changed;
        changed = setAttrIfChanged(drawer, "data-vp-current-variant-profile-id", variantProfileId) || changed;

        var familyField = U().qs("[data-vp-variant-drawer-family-profile-id-field='true']", drawer);
        var profileField = U().qs("[data-vp-variant-drawer-profile-id-field='true']", drawer);
        var profilePill = U().qs("[data-vp-variant-drawer-profile-pill='true']", drawer);
        var summaryProfile = U().qs("[data-vp-variant-drawer-summary-profile='true']", drawer);
        var technicalFamily = U().qs("[data-vp-variant-drawer-technical-family-profile='true']", drawer);
        var technicalVariant = U().qs("[data-vp-variant-drawer-technical-variant-profile='true']", drawer);

        changed = setFieldNodeValue(familyField, familyProfileId, {
          source: config.source || "profile_apply",
          emitNativeEvents: config.emitNativeEvents === true
        }) || changed;

        changed = setFieldNodeValue(profileField, variantProfileId, {
          source: config.source || "profile_apply",
          emitNativeEvents: config.emitNativeEvents === true
        }) || changed;

        if (profilePill) {
          changed = setTextIfChanged(profilePill, "Profil: " + (variantProfileId || "auto")) || changed;
        }

        if (summaryProfile) {
          changed = setTextIfChanged(summaryProfile, variantProfileId || "auto") || changed;
        }

        if (technicalFamily) {
          changed = setTextIfChanged(technicalFamily, familyProfileId || "auto") || changed;
        }

        if (technicalVariant) {
          changed = setTextIfChanged(technicalVariant, variantProfileId || "auto") || changed;
        }
      });

      changed = setFieldValue(FIELD_SELECTORS.familyProfileId, familyProfileId, {
        source: config.source || "profile_apply",
        emitNativeEvents: config.emitNativeEvents === true
      }) || changed;

      changed = setFieldValue(FIELD_SELECTORS.variantProfileId, variantProfileId, {
        source: config.source || "profile_apply",
        emitNativeEvents: config.emitNativeEvents === true
      }) || changed;

      if (
        window.VectoplanCreateVariantState &&
        typeof window.VectoplanCreateVariantState.setContext === "function"
      ) {
        window.VectoplanCreateVariantState.setContext({
          family_profile_id: familyProfileId,
          familyProfileId: familyProfileId,
          variant_profile_id: variantProfileId,
          variantProfileId: variantProfileId
        }, {
          source: config.source || "profile_apply",
          emitNativeEvents: false,
          forceEvent: false
        });
      }

      return changed;
    } catch (error) {
      warn("Could not update profile DOM attributes.", error);
      return false;
    }
  }

  function applyResolvedProfile(result, options) {
    try {
      var config = options || {};

      if (!result || !result.ok) {
        return false;
      }

      var signature = resolvedSignature(result);

      if (signature && signature === runtime.lastAppliedSignature && config.force !== true) {
        runtime.suppressedApplyCount += 1;
        runtime.lastResolved = result;
        return false;
      }

      runtime.applyInProgress = true;
      runtime.lastResolved = result;
      runtime.lastAppliedSignature = signature;

      updateProfileAttrs(result, {
        source: config.source || result.source || "profile_apply",
        emitNativeEvents: config.emitNativeEvents === true
      });

      runtime.applyInProgress = false;

      return true;
    } catch (error) {
      runtime.applyInProgress = false;
      warn("Could not apply resolved profile.", error);
      return false;
    }
  }

  function dispatchFamilyResolved(result) {
    try {
      var signature = [
        result && result.family_profile_id ? result.family_profile_id : "",
        contextKey(result && result.context ? result.context : {}, "family_dispatch")
      ].join("::");

      if (signature === runtime.lastFamilyDispatchSignature) {
        runtime.suppressedDispatchCount += 1;
        return false;
      }

      runtime.lastFamilyDispatchSignature = signature;

      U().dispatchDocument("vectoplan:create:variant-family-profile-resolved", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        ok: !!result.ok,
        source: result.source || "",
        family_profile_id: result.family_profile_id || "",
        familyProfileId: result.family_profile_id || "",
        family_profile: result.family_profile || null,
        familyProfile: result.family_profile || null,
        context: result.context || {},
        raw: result.raw || null,
        __vp_variant_profiles_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not dispatch family profile resolved event.", error);
      return false;
    }
  }

  function dispatchVariantResolved(result) {
    try {
      var signature = resolvedSignature(result);

      if (signature && signature === runtime.lastVariantDispatchSignature) {
        runtime.suppressedDispatchCount += 1;
        return false;
      }

      runtime.lastVariantDispatchSignature = signature;

      U().dispatchDocument("vectoplan:create:variant-profile-resolved", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        ok: !!result.ok,
        source: result.source || "",
        family_profile_id: result.family_profile_id || "",
        familyProfileId: result.family_profile_id || "",
        family_profile: result.family_profile || null,
        familyProfile: result.family_profile || null,
        variant_profile_id: result.variant_profile_id || "",
        variantProfileId: result.variant_profile_id || "",
        variant_profile: result.variant_profile || result.profile || null,
        variantProfile: result.variant_profile || result.profile || null,
        profile: result.variant_profile || result.profile || null,
        profilePayload: result.profile_payload || null,
        binding: result.binding || null,
        context: result.context || {},
        raw: result.raw || null,
        __vp_variant_profiles_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not dispatch variant profile resolved event.", error);
      return false;
    }
  }

  function dispatchVariantProfileLoaded(result) {
    try {
      var signature = [
        result && (result.variant_profile_id || result.profile_id) ? result.variant_profile_id || result.profile_id : "",
        result && result.source ? result.source : ""
      ].join("::");

      if (signature === runtime.lastProfileLoadedSignature) {
        runtime.suppressedDispatchCount += 1;
        return false;
      }

      runtime.lastProfileLoadedSignature = signature;

      U().dispatchDocument("vectoplan:create:variant-profile-loaded", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        ok: !!result.ok,
        source: result.source || "",
        profile_id: result.profile_id || result.variant_profile_id || "",
        variant_profile_id: result.variant_profile_id || result.profile_id || "",
        variantProfileId: result.variant_profile_id || result.profile_id || "",
        variant_profile: result.variant_profile || result.profile || null,
        variantProfile: result.variant_profile || result.profile || null,
        profile: result.variant_profile || result.profile || null,
        raw: result.raw || null,
        __vp_variant_profiles_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not dispatch variant profile loaded event.", error);
      return false;
    }
  }

  function dispatchEmptyValuesReady(result) {
    try {
      var signature = [
        result && (result.variant_profile_id || result.profile_id) ? result.variant_profile_id || result.profile_id : "",
        contextKey(result && result.context ? result.context : {}, "empty_values")
      ].join("::");

      if (signature === runtime.lastEmptyValuesSignature) {
        runtime.suppressedDispatchCount += 1;
        return false;
      }

      runtime.lastEmptyValuesSignature = signature;

      U().dispatchDocument("vectoplan:create:variant-empty-values-ready", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        ok: !!result.ok,
        source: result.source || "",
        profile_id: result.profile_id || result.variant_profile_id || "",
        variant_profile_id: result.variant_profile_id || result.profile_id || "",
        variantProfileId: result.variant_profile_id || result.profile_id || "",
        values: result.values || {},
        context: result.context || {},
        raw: result.raw || null,
        __vp_variant_profiles_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not dispatch empty values ready event.", error);
      return false;
    }
  }

  function dispatchResolutionFailed(kind, result) {
    try {
      U().dispatchDocument("vectoplan:create:variant-profile-resolution-failed", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        kind: kind || "variant",
        ok: false,
        source: result && result.source ? result.source : "",
        error: result && result.error ? result.error : normalizeError(result),
        local_error: result && result.local_error ? result.local_error : null,
        context: result && result.context ? result.context : getCurrentContext(),
        raw: result || null,
        __vp_variant_profiles_event: true
      }, {
        silent: true
      });
    } catch (error) {
      warn("Could not dispatch resolution failed event.", error);
    }
  }

  function scheduleResolve(reason, delay) {
    try {
      window.clearTimeout(runtime.autoResolveTimer);

      runtime.autoResolveTimer = window.setTimeout(function () {
        try {
          resolveCurrentProfile({
            source: reason || "scheduled"
          }).catch(function (error) {
            warn("Scheduled profile resolve failed.", error);
          });
        } catch (error) {
          warn("Scheduled profile resolve failed.", error);
        }
      }, typeof delay === "number" ? delay : 120);

      return true;
    } catch (error) {
      warn("Could not schedule profile resolve.", error);
      return false;
    }
  }

  function isProgrammaticEventTarget(target) {
    try {
      if (!target) {
        return false;
      }

      if (target.getAttribute && target.getAttribute("data-vp-programmatic-event")) {
        return true;
      }

      if (target.getAttribute && target.getAttribute("data-vp-programmatic-event-source")) {
        return true;
      }

      if (target.__vpProgrammaticEvent) {
        return true;
      }

      if (target.getAttribute && target.getAttribute("data-vp-last-profile-sync")) {
        var timestamp = parseInt(target.getAttribute("data-vp-last-profile-sync") || "0", 10);

        if (timestamp && Date.now() - timestamp < 160) {
          return true;
        }
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function handleContextFieldChange(event) {
    try {
      var target = event && event.target ? event.target : null;

      if (!target || !target.matches) {
        return;
      }

      if (isProgrammaticEventTarget(target)) {
        return;
      }

      var selectors = []
        .concat(FIELD_SELECTORS.domain)
        .concat(FIELD_SELECTORS.category)
        .concat(FIELD_SELECTORS.subcategory)
        .concat(FIELD_SELECTORS.objectKind)
        .concat(FIELD_SELECTORS.familyProfileId)
        .concat(FIELD_SELECTORS.variantProfileId)
        .join(",");

      if (!target.matches(selectors)) {
        return;
      }

      scheduleResolve("context_field_change", 160);
    } catch (error) {
      warn("Could not handle context field change.", error);
    }
  }

  function bindGlobalEvents() {
    try {
      if (runtime.globalEventsBound) {
        return;
      }

      document.addEventListener("change", handleContextFieldChange);
      document.addEventListener("input", handleContextFieldChange);

      document.addEventListener("vectoplan:create:context-ready", function () {
        clearCache({
          keepDefinitions: false
        });
        getDefinitionsSync({
          force: true
        });
        scheduleResolve("context_ready", 90);
      });

      document.addEventListener("vectoplan:create:definitions-ready", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail.__vp_variant_profiles_event) {
            return;
          }

          runtime.cache.definitions = normalizeDefinitions(detail.definitions || detail || {});
          runtime.cache.definitionMaps = buildDefinitionMaps(runtime.cache.definitions);
          scheduleResolve("definitions_ready", 80);
        } catch (error) {
          warn("Definitions-ready handling failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-workspace-ready", function () {
        scheduleResolve("workspace_ready", 80);
      });

      document.addEventListener("vectoplan:create:variant-drawer-opened", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var payload = detail.payload || detail || {};

          if (payload.variantProfileId || payload.variant_profile_id) {
            getVariantProfile(payload.variantProfileId || payload.variant_profile_id);
            return;
          }

          scheduleResolve("drawer_opened", 60);
        } catch (error) {
          warn("Drawer opened resolve failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-definitions-retry-requested", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          clearCache({
            keepDefinitions: false
          });

          fetchDefinitions({
            force: true,
            source: "retry_requested"
          }).then(function () {
            return resolveCurrentProfile({
              force: true,
              context: detail.context || getCurrentContext(),
              source: "retry_requested"
            });
          }).catch(function (error) {
            dispatchResolutionFailed("retry", {
              ok: false,
              source: "retry_requested",
              error: normalizeError(error),
              context: detail.context || getCurrentContext()
            });
          });
        } catch (error) {
          warn("Definitions retry failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-profile-resolve-requested", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          resolveCurrentProfile({
            force: !!detail.force,
            context: detail.context || getCurrentContext(),
            source: detail.source || "resolve_requested"
          }).catch(function (error) {
            warn("Explicit profile resolve request failed.", error);
          });
        } catch (error) {
          warn("Explicit profile resolve request failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:context-synced", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail.__vp_variant_profiles_event) {
            return;
          }

          scheduleResolve(detail.source || "context_synced", 140);
        } catch (error) {
          warn("Context synced resolve failed.", error);
        }
      });

      runtime.globalEventsBound = true;
    } catch (error) {
      warn("Could not bind profile global events.", error);
    }
  }

  function clearCache(options) {
    try {
      var config = options || {};
      var definitions = runtime.cache.definitions;
      var maps = runtime.cache.definitionMaps;
      var endpoints = runtime.cache.endpoints;

      runtime.cache = {
        definitions: config.keepDefinitions === true ? definitions : null,
        definitionMaps: config.keepDefinitions === true ? maps : null,
        endpoints: config.keepEndpoints === false ? null : endpoints,
        familyResolve: {},
        variantResolve: {},
        variantProfiles: {},
        emptyValues: {},
        requests: {}
      };

      runtime.lastResolved = null;
      runtime.lastBundle = null;
      runtime.lastProfilePayload = null;
      runtime.lastContextKey = "";
      runtime.lastResolvedSignature = "";
      runtime.lastBundleSignature = "";
      runtime.lastAppliedSignature = "";
      runtime.lastFamilyDispatchSignature = "";
      runtime.lastVariantDispatchSignature = "";
      runtime.lastProfileLoadedSignature = "";
      runtime.lastEmptyValuesSignature = "";
      runtime.activeResolvePromise = null;
      runtime.activeResolveKey = "";

      U().dispatchDocument("vectoplan:create:variant-profile-cache-cleared", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        keepDefinitions: !!config.keepDefinitions,
        __vp_variant_profiles_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not clear profile cache.", error);
      return false;
    }
  }

  function getCacheSnapshot() {
    try {
      return {
        definitionsLoaded: !!runtime.cache.definitions,
        definitionCounts: runtime.cache.definitions ? {
          object_kinds: runtime.cache.definitions.object_kinds.length,
          family_profiles: runtime.cache.definitions.family_profiles.length,
          variant_profiles: runtime.cache.definitions.variant_profiles.length,
          variables: runtime.cache.definitions.variables.length,
          units: runtime.cache.definitions.units.length,
          materials: runtime.cache.definitions.materials.length,
          document_types: runtime.cache.definitions.document_types.length,
          profile_bindings: runtime.cache.definitions.profile_bindings.length
        } : null,
        cacheSizes: {
          familyResolve: Object.keys(runtime.cache.familyResolve || {}).length,
          variantResolve: Object.keys(runtime.cache.variantResolve || {}).length,
          variantProfiles: Object.keys(runtime.cache.variantProfiles || {}).length,
          emptyValues: Object.keys(runtime.cache.emptyValues || {}).length,
          requests: Object.keys(runtime.cache.requests || {}).length
        },
        resolving: runtime.resolveInProgress,
        applying: runtime.applyInProgress,
        lastContext: runtime.lastContext,
        lastContextKey: runtime.lastContextKey,
        lastResolved: runtime.lastResolved,
        currentBundle: runtime.lastBundle,
        resolvedProfileBundle: runtime.lastBundle,
        currentProfilePayload: runtime.lastProfilePayload,
        lastResolvedSignature: runtime.lastResolvedSignature,
        lastBundleSignature: runtime.lastBundleSignature,
        lastAppliedSignature: runtime.lastAppliedSignature,
        suppressedApplyCount: runtime.suppressedApplyCount,
        suppressedResolveCount: runtime.suppressedResolveCount,
        suppressedDispatchCount: runtime.suppressedDispatchCount
      };
    } catch (error) {
      return {};
    }
  }

  function getGeneratorContext() {
    try {
      return window.VectoplanGeneratorContext ||
        (window.VectoplanCreateContext && (window.VectoplanCreateContext.generatorContext || window.VectoplanCreateContext.generator_context)) ||
        {};
    } catch (error) {
      return {};
    }
  }

  function getPayloadContract() {
    try {
      return window.VectoplanCreatePayloadContract ||
        (window.VectoplanCreateContext && (window.VectoplanCreateContext.payloadContract || window.VectoplanCreateContext.payload_contract)) ||
        {};
    } catch (error) {
      return {};
    }
  }

  function getState() {
    return {
      component: COMPONENT_NAME,
      version: COMPONENT_VERSION,
      initialized: runtime.initialized,
      ready: runtime.initialized,
      cache: getCacheSnapshot(),
      endpoints: getEndpoints(),
      context: getCurrentContext(),
      generatorContext: getGeneratorContext(),
      payloadContract: getPayloadContract(),
      options: U().deepClone(runtime.options, {})
    };
  }

  function initialize(options) {
    try {
      var config = options || {};

      if (runtime.initialized && config.force !== true && config.reinitialize !== true) {
        return true;
      }

      runtime.options = U().safeMerge(runtime.options, config || {});

      getDefinitionsSync({
        force: !!config.force
      });

      bindGlobalEvents();

      runtime.initialized = true;

      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-profiles-version", COMPONENT_VERSION);

      U().dispatchDocument("vectoplan:create:variant-profiles-ready", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        definitions: getDefinitionsSync(),
        cache: getCacheSnapshot(),
        endpoints: getEndpoints(),
        generatorContext: getGeneratorContext(),
        payloadContract: getPayloadContract(),
        __vp_variant_profiles_event: true
      }, {
        silent: true
      });

      if (hasDefinitionData(getDefinitionsSync())) {
        U().dispatchDocument("vectoplan:create:definitions-ready", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          definitions: getDefinitionsSync(),
          maps: getDefinitionMaps(),
          __vp_variant_profiles_event: true
        }, {
          silent: true
        });

        if (config.autoResolve !== false && runtime.options.autoResolve !== false) {
          scheduleResolve("profiles_initialized", 100);
        }
      } else {
        U().dispatchDocument("vectoplan:create:definitions-unavailable", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          error: {
            code: "definitions_not_loaded",
            message: "Keine Definitionsdaten im Fensterkontext gefunden."
          },
          __vp_variant_profiles_event: true
        }, {
          silent: true
        });

        if (config.fetchDefinitions !== false && runtime.options.fetchDefinitions !== false) {
          fetchDefinitions({
            source: "initialize_fetch"
          }).then(function () {
            if (config.autoResolve !== false && runtime.options.autoResolve !== false) {
              scheduleResolve("definitions_fetched", 80);
            }
          }).catch(function (error) {
            warn("Initial definitions fetch failed.", error);
          });
        }
      }

      return true;
    } catch (error) {
      warn("Could not initialize variant profiles.", error);
      return false;
    }
  }

  var api = {
    __name: COMPONENT_NAME,
    __version: COMPONENT_VERSION,
    version: COMPONENT_VERSION,

    initialize: initialize,
    getState: getState,

    getEndpoints: getEndpoints,
    getDefinitionsSync: getDefinitionsSync,
    fetchDefinitions: fetchDefinitions,
    getDefinitionMaps: getDefinitionMaps,
    hasDefinitionData: hasDefinitionData,
    readDefinitionsFromWindow: readDefinitionsFromWindow,
    normalizeDefinitions: normalizeDefinitions,
    buildDefinitionMaps: buildDefinitionMaps,

    getGeneratorContext: getGeneratorContext,
    getPayloadContract: getPayloadContract,

    getCurrentContext: getCurrentContext,
    collectContext: collectContext,
    readContextFromDom: readContextFromDom,
    readContextFromState: readContextFromState,
    normalizeContext: normalizeContext,

    resolveFamilyProfile: resolveFamilyProfile,
    resolveVariantProfile: resolveVariantProfile,
    resolveCurrentProfile: resolveCurrentProfile,
    getVariantProfile: getVariantProfile,
    getEmptyVariantValues: getEmptyVariantValues,
    getResolvedProfileBundle: getResolvedProfileBundle,
    getResolvedProfileBundleSync: getResolvedProfileBundleSync,
    getCurrentProfilePayload: getCurrentProfilePayload,

    resolveFamilyProfileLocal: resolveFamilyProfileLocal,
    resolveVariantProfileLocal: resolveVariantProfileLocal,
    getVariantProfileLocal: getVariantProfileLocal,
    getEmptyValuesLocal: getEmptyValuesLocal,

    applyResolvedProfile: applyResolvedProfile,
    updateProfileAttrs: updateProfileAttrs,
    clearCache: clearCache,
    getCacheSnapshot: getCacheSnapshot,

    scheduleResolve: scheduleResolve
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
    warn("Could not bootstrap variant profiles.", bootstrapError);
  }
})();