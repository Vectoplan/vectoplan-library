/* services/vectoplan-library/static/js/vplib/create/create_variant_profiles.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateVariantProfiles";
  var COMPONENT_NAME = "VECTOPLAN Create Variant Profiles";
  var COMPONENT_VERSION = "0.9.0";
  var READY_ATTR = "data-vp-create-variant-profiles-ready";
  var INITIALIZED_ATTR = "data-vp-create-variant-profiles-initialized";
  var STATUS_ATTR = "data-vp-create-variant-profiles-status";
  var OPERATIONAL_ATTR = "data-vp-create-variant-profiles-operational";

  var DEFAULT_REQUEST_TIMEOUT_MS = 15000;
  var DEFAULT_REQUEST_CACHE_TTL_MS = 30000;
  var DEFAULT_STARTER_OBJECT_KIND = "cell_block";
  var DEFAULT_STARTER_FAMILY_PROFILE_ID = "simple_cell_block";
  var DEFAULT_STARTER_VARIANT_PROFILE_ID = "simple_cell_block.v1";
  var REQUIRED_STARTER_DEFAULT_KEYS = [
    "variant.variant_id",
    "variant.label",
    "dimensions.width_mm",
    "dimensions.height_mm",
    "dimensions.depth_mm"
  ];

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
      var existingApi = window[GLOBAL_NAME];
      var existingOperational = typeof existingApi.isOperational === "function"
        ? !!existingApi.isOperational()
        : true;
      var existingState = typeof existingApi.getState === "function"
        ? existingApi.getState()
        : {};

      document.documentElement.setAttribute(INITIALIZED_ATTR, "true");
      document.documentElement.setAttribute(READY_ATTR, existingOperational ? "true" : "false");
      document.documentElement.setAttribute(OPERATIONAL_ATTR, existingOperational ? "true" : "false");
      document.documentElement.setAttribute(STATUS_ATTR, existingState.status || (existingOperational ? "ready" : "initialized"));
      document.documentElement.setAttribute("data-vp-create-variant-profiles-version", COMPONENT_VERSION);
    } catch (alreadyReadyError) {
      /* no-op */
    }
    return;
  }

  var runtime = {
    initialized: false,
    operational: false,
    status: "created",
    globalEventsBound: false,
    resolveInProgress: false,
    resolveGeneration: 0,
    activeResolvePromise: null,
    activeResolveKey: "",
    applyInProgress: false,
    autoResolveTimer: null,
    readinessPromise: null,
    readinessGeneration: 0,
    readinessResult: null,
    lastError: null,
    requestSequence: 0,
    cache: {
      definitions: null,
      definitionMaps: null,
      definitionSourceSignature: "",
      endpointContextSignature: "",
      endpoints: null,
      familyResolve: {},
      variantResolve: {},
      variantProfiles: {},
      emptyValues: {},
      requests: {},
      requestMeta: {}
    },
    diagnostics: {
      definitionConflicts: [],
      definitionConflictKeys: {},
      invalidEndpointCandidates: [],
      invalidEndpointKeys: {},
      lastEndpointRefreshAt: 0,
      lastDefinitionsBuildAt: 0
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
      preferLocal: false,
      autoResolve: true,
      fetchDefinitions: true,
      rejectOnError: false,
      requestTimeoutMs: DEFAULT_REQUEST_TIMEOUT_MS,
      requestCacheTtlMs: DEFAULT_REQUEST_CACHE_TTL_MS,
      requestCacheMaxEntries: 64,
      warnOnDefinitionConflicts: false,
      maxDefinitionDiagnostics: 100,
      maxEndpointDiagnostics: 50,
      allowCrossOriginDefinitionEndpoints: false,
      starterObjectKind: DEFAULT_STARTER_OBJECT_KIND,
      starterFamilyProfileId: DEFAULT_STARTER_FAMILY_PROFILE_ID,
      starterVariantProfileId: DEFAULT_STARTER_VARIANT_PROFILE_ID
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

            if (item && typeof item === "object" && !Array.isArray(item)) {
              var cloned = {};

              Object.keys(item).forEach(function (itemKey) {
                cloned[itemKey] = item[itemKey];
              });

              if (!cloned.id && !cloned.key && !cloned.value) {
                cloned.id = key;
              }

              return cloned;
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


  function hasOwn(source, key) {
    try {
      return !!source && Object.prototype.hasOwnProperty.call(source, key);
    } catch (error) {
      return false;
    }
  }

  function normalizeLookupKey(value) {
    try {
      if (value === null || value === undefined || typeof value === "object" || typeof value === "function") {
        return "";
      }

      var text = String(value).trim();

      if (!text || text === "[object Object]") {
        return "";
      }

      return U().normalizeProfileId
        ? U().normalizeProfileId(text).toLowerCase()
        : text.replace(/-/g, "_").toLowerCase();
    } catch (error) {
      return "";
    }
  }

  function stableSerializableValue(value, depth, seen) {
    try {
      var currentDepth = depth || 0;

      if (currentDepth > 20) {
        return "[max-depth]";
      }

      if (value === null || value === undefined || typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
        return value;
      }

      if (typeof value === "function") {
        return "[function]";
      }

      if (typeof value !== "object") {
        return String(value);
      }

      var visited = seen || [];

      if (visited.indexOf(value) !== -1) {
        return "[circular]";
      }

      visited.push(value);

      if (Array.isArray(value)) {
        return value.map(function (item) {
          return stableSerializableValue(item, currentDepth + 1, visited.slice());
        });
      }

      var output = {};
      Object.keys(value).sort().forEach(function (key) {
        if (
          key === "raw" ||
          key === "_raw" ||
          key === "loaded_at" ||
          key === "loadedAt" ||
          key === "updated_at" ||
          key === "updatedAt" ||
          key === "created_at" ||
          key === "createdAt" ||
          key === "timestamp"
        ) {
          return;
        }

        output[key] = stableSerializableValue(value[key], currentDepth + 1, visited.slice());
      });

      return output;
    } catch (error) {
      return String(value);
    }
  }

  function stableStringify(value) {
    try {
      return JSON.stringify(stableSerializableValue(value, 0, []));
    } catch (error) {
      return "";
    }
  }

  function definitionCompletenessScore(item) {
    try {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return 0;
      }

      var score = 0;

      Object.keys(item).forEach(function (key) {
        var value = item[key];

        if (value === null || value === undefined || value === "") {
          return;
        }

        score += 1;

        if (Array.isArray(value)) {
          score += Math.min(value.length, 20);
        } else if (typeof value === "object") {
          score += Math.min(Object.keys(value).length, 20);
        }
      });

      if (item.resolved === true) {
        score += 100;
      }

      if (item.source === "database" || item.definition_source === "database") {
        score += 20;
      }

      return score;
    } catch (error) {
      return 0;
    }
  }

  function mergeDefinitionItems(left, right) {
    try {
      var first = left && typeof left === "object" && !Array.isArray(left) ? left : {};
      var second = right && typeof right === "object" && !Array.isArray(right) ? right : {};
      var preferSecond = definitionCompletenessScore(second) > definitionCompletenessScore(first);
      var primary = preferSecond ? second : first;
      var secondary = preferSecond ? first : second;
      var merged = {};

      Object.keys(secondary).forEach(function (key) {
        merged[key] = secondary[key];
      });

      Object.keys(primary).forEach(function (key) {
        var value = primary[key];

        if (
          value &&
          typeof value === "object" &&
          !Array.isArray(value) &&
          merged[key] &&
          typeof merged[key] === "object" &&
          !Array.isArray(merged[key])
        ) {
          merged[key] = U().safeMerge(merged[key], value);
        } else if (value !== undefined) {
          merged[key] = value;
        }
      });

      return merged;
    } catch (error) {
      return right || left || {};
    }
  }

  function definitionTypeSpec(typeName) {
    var specs = {
      object_kinds: {
        primary: ["id", "object_kind", "objectKind", "key", "value"],
        lookups: ["key", "value", "slug", "name"]
      },
      family_profiles: {
        primary: ["id", "family_profile_id", "familyProfileId", "profile_id", "profileId", "key"],
        lookups: ["key", "value", "definition_key", "definitionKey"]
      },
      variant_profiles: {
        primary: ["id", "variant_profile_id", "variantProfileId", "profile_id", "profileId", "key", "definition_key", "definitionKey"],
        lookups: ["key", "value", "definition_key", "definitionKey"]
      },
      variables: {
        primary: ["key", "variable_key", "variableKey", "id", "definition_key", "definitionKey"],
        lookups: ["id", "definition_key", "definitionKey", "name"]
      },
      units: {
        primary: ["id", "unit_id", "unitId", "key", "value", "symbol"],
        lookups: ["key", "value", "symbol", "name"]
      },
      materials: {
        primary: ["id", "material_id", "materialId", "key", "value", "material_class", "materialClass"],
        lookups: ["key", "value", "material_class", "materialClass", "name"]
      },
      document_types: {
        primary: ["id", "document_type_id", "documentTypeId", "key", "value"],
        lookups: ["key", "value", "name"]
      },
      profile_bindings: {
        primary: ["id", "binding_id", "bindingId", "key"],
        lookups: ["key"]
      }
    };

    return specs[typeName] || {
      primary: ["id", "key", "value"],
      lookups: ["key", "value"]
    };
  }

  function firstDefinitionIdentity(item, spec) {
    try {
      var fields = spec && spec.primary ? spec.primary : ["id", "key", "value"];

      for (var index = 0; index < fields.length; index += 1) {
        var key = normalizeLookupKey(item && item[fields[index]]);

        if (key) {
          return key;
        }
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function recordDefinitionConflict(typeName, key, existing, incoming, kind) {
    try {
      var existingId = firstDefinitionIdentity(existing, definitionTypeSpec(typeName));
      var incomingId = firstDefinitionIdentity(incoming, definitionTypeSpec(typeName));
      var diagnosticKey = [
        typeName || "definition",
        kind || "lookup",
        key || "",
        existingId || "",
        incomingId || ""
      ].join("|");

      if (runtime.diagnostics.definitionConflictKeys[diagnosticKey]) {
        return;
      }

      runtime.diagnostics.definitionConflictKeys[diagnosticKey] = true;

      var diagnostic = {
        type: typeName || "definition",
        key: key || "",
        kind: kind || "lookup",
        existing_id: existingId,
        incoming_id: incomingId
      };

      runtime.diagnostics.definitionConflicts.push(diagnostic);

      var limit = parseInt(runtime.options.maxDefinitionDiagnostics, 10);

      if (!Number.isFinite(limit) || limit < 1) {
        limit = 100;
      }

      if (runtime.diagnostics.definitionConflicts.length > limit) {
        runtime.diagnostics.definitionConflicts.splice(0, runtime.diagnostics.definitionConflicts.length - limit);
      }

      if (runtime.options.warnOnDefinitionConflicts === true) {
        warn(
          "Echte Definitionsschlüssel-Kollision für '" + String(key || "") + "' (" + String(typeName || "definition") + ", " + String(kind || "lookup") + ").",
          diagnostic
        );
      }
    } catch (error) {
      /* Diagnostics must never block definition loading. */
    }
  }

  function dedupeDefinitionCollection(items, typeName) {
    try {
      var spec = definitionTypeSpec(typeName);
      var byIdentity = {};
      var anonymousByFingerprint = {};
      var order = [];

      toArrayOrObjectValues(items).forEach(function (item) {
        if (!item || typeof item !== "object" || Array.isArray(item)) {
          return;
        }

        var identity = firstDefinitionIdentity(item, spec);
        var fingerprint = stableStringify(item);
        var storageKey = identity ? "id:" + identity : "fp:" + fingerprint;

        if (!identity && anonymousByFingerprint[fingerprint]) {
          return;
        }

        if (!byIdentity[storageKey]) {
          byIdentity[storageKey] = U().deepClone(item, item);
          order.push(storageKey);

          if (!identity) {
            anonymousByFingerprint[fingerprint] = true;
          }

          return;
        }

        byIdentity[storageKey] = mergeDefinitionItems(byIdentity[storageKey], item);
      });

      return order.map(function (storageKey) {
        return byIdentity[storageKey];
      });
    } catch (error) {
      warn("Definitionssammlung konnte nicht dedupliziert werden.", error);
      return toArrayOrObjectValues(items);
    }
  }

  function buildDefinitionIndex(items, typeName) {
    try {
      var output = {};
      var ownership = {};
      var spec = definitionTypeSpec(typeName);
      var normalizedItems = dedupeDefinitionCollection(items, typeName);

      function register(rawKey, item, kind) {
        var key = normalizeLookupKey(rawKey);

        if (!key) {
          return;
        }

        var incomingId = firstDefinitionIdentity(item, spec);
        var existing = output[key];
        var existingId = ownership[key] || (existing ? firstDefinitionIdentity(existing, spec) : "");

        if (!existing) {
          output[key] = item;
          ownership[key] = incomingId;
          return;
        }

        if (existingId && incomingId && existingId === incomingId) {
          output[key] = mergeDefinitionItems(existing, item);
          ownership[key] = existingId;
          return;
        }

        if (stableStringify(existing) === stableStringify(item)) {
          return;
        }

        recordDefinitionConflict(typeName, key, existing, item, kind);

        if (kind === "canonical") {
          var existingScore = definitionCompletenessScore(existing);
          var incomingScore = definitionCompletenessScore(item);

          if (incomingScore > existingScore || (incomingScore === existingScore && incomingId && existingId && incomingId < existingId)) {
            output[key] = item;
            ownership[key] = incomingId;
          }
        }
      }

      normalizedItems.forEach(function (item) {
        var primaryId = firstDefinitionIdentity(item, spec);

        if (primaryId) {
          register(primaryId, item, "canonical");
        }

        (spec.lookups || []).forEach(function (fieldName) {
          if (hasOwn(item, fieldName)) {
            register(item[fieldName], item, "lookup");
          }
        });
      });

      normalizedItems.forEach(function (item) {
        U().toArray(item.aliases || item.alias || []).forEach(function (alias) {
          register(alias, item, "alias");
        });
      });

      return output;
    } catch (error) {
      warn("Definitionsindex konnte nicht aufgebaut werden.", error);
      return {};
    }
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
      var key = String(keyName || "id");
      var typeName = key === "key" ? "variables" : "generic";
      return buildDefinitionIndex(items, typeName);
    } catch (error) {
      warn("Definitionsindex konnte nicht aufgebaut werden.", error);
      return {};
    }
  }

  function normalizeDefinitions(raw) {
    try {
      var source = raw || {};
      var sources = [];
      var seenSources = [];
      var nestedKeys = [
        "data",
        "payload",
        "options",
        "catalogs",
        "definition_catalogs",
        "definitionCatalogs",
        "records",
        "definitions",
        "definition_context",
        "definitionContext"
      ];

      function add(value) {
        if (!value || typeof value !== "object" || Array.isArray(value)) {
          return;
        }

        if (seenSources.indexOf(value) !== -1) {
          return;
        }

        seenSources.push(value);
        sources.push(value);

        if (sources.length > 160) {
          return;
        }

        nestedKeys.forEach(function (key) {
          if (value[key] && typeof value[key] === "object" && !Array.isArray(value[key])) {
            add(value[key]);
          }
        });
      }

      add(source);

      var generator = window.VectoplanGeneratorContext || {};
      var context = window.VectoplanCreateContext || {};
      add(generator);
      add(context.definitions);
      add(context.definitionCatalogs);
      add(context.definition_catalogs);
      add(context.generatorContext);
      add(context.generator_context);
      add(context.options && context.options.definitions);

      function collectCollection(names, typeName) {
        var collected = [];

        sources.forEach(function (candidateSource) {
          if (!candidateSource || typeof candidateSource !== "object") {
            return;
          }

          names.forEach(function (name) {
            if (!hasOwn(candidateSource, name)) {
              return;
            }

            toArrayOrObjectValues(candidateSource[name]).forEach(function (item) {
              if (item && typeof item === "object" && !Array.isArray(item)) {
                collected.push(item);
              }
            });
          });
        });

        return dedupeDefinitionCollection(collected, typeName);
      }

      var normalized = {
        raw: source,
        object_kinds: collectCollection(["object_kinds", "objectKinds"], "object_kinds"),
        family_profiles: collectCollection(["family_profiles", "familyProfiles"], "family_profiles"),
        variant_profiles: collectCollection(["variant_profiles", "variantProfiles"], "variant_profiles"),
        variables: collectCollection(["variables"], "variables"),
        units: collectCollection(["units"], "units"),
        materials: collectCollection(["materials", "material_classes", "materialClasses"], "materials"),
        document_types: collectCollection(["document_types", "documentTypes"], "document_types"),
        profile_bindings: collectCollection(["profile_bindings", "profileBindings"], "profile_bindings")
      };

      runtime.diagnostics.lastDefinitionsBuildAt = Date.now();

      return normalized;
    } catch (error) {
      warn("Definitionsdaten konnten nicht normalisiert werden.", error);
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

  function definitionCollectionSignature(definitions) {
    try {
      var source = definitions || {};
      var parts = [];

      [
        ["object_kinds", "object_kinds"],
        ["family_profiles", "family_profiles"],
        ["variant_profiles", "variant_profiles"],
        ["variables", "variables"],
        ["units", "units"],
        ["materials", "materials"],
        ["document_types", "document_types"],
        ["profile_bindings", "profile_bindings"]
      ].forEach(function (entry) {
        var typeName = entry[0];
        var collectionName = entry[1];
        var spec = definitionTypeSpec(typeName);
        var ids = U().toArray(source[collectionName]).map(function (item) {
          return firstDefinitionIdentity(item, spec) || stableStringify(item);
        }).sort();

        parts.push(typeName + ":" + ids.join(","));
      });

      return parts.join("|");
    } catch (error) {
      return "";
    }
  }

  function buildDefinitionMaps(defs) {
    try {
      var normalized = normalizeDefinitions(defs);
      var built = {
        objectKindsById: buildDefinitionIndex(normalized.object_kinds, "object_kinds"),
        familyProfilesById: buildDefinitionIndex(normalized.family_profiles, "family_profiles"),
        variantProfilesById: buildDefinitionIndex(normalized.variant_profiles, "variant_profiles"),
        variablesByKey: buildDefinitionIndex(normalized.variables, "variables"),
        unitsById: buildDefinitionIndex(normalized.units, "units"),
        materialsById: buildDefinitionIndex(normalized.materials, "materials"),
        documentTypesById: buildDefinitionIndex(normalized.document_types, "document_types"),
        profileBindingsById: buildDefinitionIndex(normalized.profile_bindings, "profile_bindings")
      };
      var mapsFromWindow = window.VectoplanCreateDefinitionMaps || {};

      Object.keys(built).forEach(function (mapName) {
        var externalMap = mapsFromWindow[mapName];

        if (!externalMap || typeof externalMap !== "object" || Array.isArray(externalMap)) {
          return;
        }

        Object.keys(externalMap).forEach(function (rawKey) {
          var key = normalizeLookupKey(rawKey);
          var incoming = externalMap[rawKey];

          if (!key || !incoming || typeof incoming !== "object") {
            return;
          }

          if (!built[mapName][key]) {
            built[mapName][key] = incoming;
            return;
          }

          if (stableStringify(built[mapName][key]) === stableStringify(incoming)) {
            return;
          }

          recordDefinitionConflict(mapName, key, built[mapName][key], incoming, "external_map");
        });
      });

      runtime.cache.definitionSourceSignature = definitionCollectionSignature(normalized);

      return built;
    } catch (error) {
      warn("Definitionskarten konnten nicht aufgebaut werden.", error);
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

  function recordInvalidEndpointCandidate(key, value, source) {
    try {
      if (value === null || value === undefined || value === "") {
        return;
      }

      var fingerprint = [
        key || "",
        source || "",
        typeof value,
        stableStringify(value).slice(0, 500)
      ].join("|");

      if (runtime.diagnostics.invalidEndpointKeys[fingerprint]) {
        return;
      }

      runtime.diagnostics.invalidEndpointKeys[fingerprint] = true;
      runtime.diagnostics.invalidEndpointCandidates.push({
        key: key || "",
        source: source || "",
        value_type: typeof value,
        value_preview: typeof value === "string"
          ? value.slice(0, 240)
          : stableStringify(value).slice(0, 240)
      });

      var limit = parseInt(runtime.options.maxEndpointDiagnostics, 10);

      if (!Number.isFinite(limit) || limit < 1) {
        limit = 50;
      }

      if (runtime.diagnostics.invalidEndpointCandidates.length > limit) {
        runtime.diagnostics.invalidEndpointCandidates.splice(
          0,
          runtime.diagnostics.invalidEndpointCandidates.length - limit
        );
      }
    } catch (error) {
      /* Endpoint diagnostics must never block initialization. */
    }
  }

  function normalizeEndpointCandidate(value, key, source, depth) {
    try {
      var currentDepth = depth || 0;

      if (currentDepth > 3 || value === null || value === undefined || typeof value === "function") {
        return "";
      }

      if (typeof window.URL === "function" && value instanceof window.URL) {
        value = value.href;
      }

      if (typeof value === "object") {
        if (Array.isArray(value)) {
          return "";
        }

        var objectFields = [
          key,
          "url",
          "href",
          "path",
          "endpoint",
          "route",
          "base",
          "baseUrl",
          "base_url"
        ];

        for (var fieldIndex = 0; fieldIndex < objectFields.length; fieldIndex += 1) {
          var fieldName = objectFields[fieldIndex];

          if (!fieldName || !hasOwn(value, fieldName)) {
            continue;
          }

          var nested = normalizeEndpointCandidate(
            value[fieldName],
            key,
            source + "." + fieldName,
            currentDepth + 1
          );

          if (nested) {
            return nested;
          }
        }

        return "";
      }

      var text = String(value).trim();

      if (
        !text ||
        text === "[object Object]" ||
        text.indexOf("[object Object]") !== -1 ||
        /[\u0000-\u001f]/.test(text)
      ) {
        return "";
      }

      if (/^(javascript|data|vbscript|file):/i.test(text)) {
        return "";
      }

      if (/^https?:\/\//i.test(text)) {
        try {
          var absolute = new window.URL(text, window.location && window.location.href ? window.location.href : undefined);
          var currentOrigin = window.location && window.location.origin ? window.location.origin : "";

          if (
            runtime.options.allowCrossOriginDefinitionEndpoints !== true &&
            currentOrigin &&
            absolute.origin !== currentOrigin
          ) {
            return "";
          }

          return absolute.origin === currentOrigin
            ? absolute.pathname + absolute.search + absolute.hash
            : absolute.href;
        } catch (absoluteUrlError) {
          return "";
        }
      }

      if (text.charAt(0) === "/" || text.indexOf("./") === 0 || text.indexOf("../") === 0) {
        return text;
      }

      if (/^[a-z0-9_.~-]+(?:\/[a-z0-9_.~%-]+)*(?:\?[^#\s]*)?(?:#[^\s]*)?$/i.test(text)) {
        return "/" + text.replace(/^\/+/, "");
      }

      return "";
    } catch (error) {
      recordInvalidEndpointCandidate(key, value, source);
      return "";
    }
  }

  function endpointContextSignature() {
    try {
      var context = window.VectoplanCreateContext || {};
      var definitionsWindow = window.VectoplanCreateDefinitions || {};

      return stableStringify({
        definitionsApi: context.definitionsApi || null,
        definitions_api: context.definitions_api || null,
        contextDefinitionsRoutes: pathGet(context, "definitions.routes", null),
        contextDefinitionsEndpoints: pathGet(context, "definitions.endpoints", null),
        routes: context.routes || null,
        definitionsWindowRoutes: definitionsWindow.routes || null,
        definitionsWindowEndpoints: definitionsWindow.endpoints || null
      });
    } catch (error) {
      return "";
    }
  }

  function readEndpointFromContext(key, fallback) {
    try {
      var context = window.VectoplanCreateContext || {};
      var definitionsWindow = window.VectoplanCreateDefinitions || {};
      var definitionsApi = context.definitionsApi || context.definitions_api || {};
      var definitions = context.definitions || {};
      var routes = context.routes || {};
      var endpointCandidates = [
        { value: pathGet(definitionsApi, key, null), source: "definitionsApi." + key },
        { value: pathGet(definitionsApi, "routes." + key, null), source: "definitionsApi.routes." + key },
        { value: pathGet(definitionsApi, "endpoints." + key, null), source: "definitionsApi.endpoints." + key },
        { value: pathGet(definitionsWindow, key, null), source: "definitionsWindow." + key },
        { value: pathGet(definitionsWindow, "routes." + key, null), source: "definitionsWindow.routes." + key },
        { value: pathGet(definitionsWindow, "endpoints." + key, null), source: "definitionsWindow.endpoints." + key },
        { value: pathGet(definitions, key, null), source: "definitions." + key },
        { value: pathGet(definitions, "routes." + key, null), source: "definitions.routes." + key },
        { value: pathGet(definitions, "endpoints." + key, null), source: "definitions.endpoints." + key }
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
        endpointCandidates.push({
          value: routes[alias],
          source: "routes." + alias
        });
      });

      for (var index = 0; index < endpointCandidates.length; index += 1) {
        var candidate = endpointCandidates[index];
        var normalized = normalizeEndpointCandidate(candidate.value, key, candidate.source, 0);

        if (normalized) {
          return normalized;
        }

        if (candidate.value !== null && candidate.value !== undefined && candidate.value !== "") {
          recordInvalidEndpointCandidate(key, candidate.value, candidate.source);
        }
      }

      return normalizeEndpointCandidate(fallback, key, "fallback", 0) || "";
    } catch (error) {
      return normalizeEndpointCandidate(fallback, key, "fallback_error", 0) || "";
    }
  }

  function getEndpoints(options) {
    try {
      var config = options || {};
      var signature = endpointContextSignature();
      var shouldRefresh = config.force === true ||
        config.forceReload === true ||
        !runtime.cache.endpoints ||
        runtime.cache.endpointContextSignature !== signature;

      if (!shouldRefresh) {
        return runtime.cache.endpoints;
      }

      var defaults = getDefaultEndpoints();
      var endpoints = {
        options: readEndpointFromContext("options", defaults.options),
        payload: readEndpointFromContext("payload", defaults.payload),
        resolveFamilyProfile: readEndpointFromContext(
          "resolveFamilyProfile",
          readEndpointFromContext("resolve_family_profile", defaults.resolveFamilyProfile)
        ),
        resolveVariantProfile: readEndpointFromContext(
          "resolveVariantProfile",
          readEndpointFromContext("resolve_variant_profile", defaults.resolveVariantProfile)
        ),
        variantProfileBase: readEndpointFromContext(
          "variantProfileBase",
          readEndpointFromContext("variant_profile_base", defaults.variantProfileBase)
        ),
        emptyValuesBase: readEndpointFromContext(
          "emptyValuesBase",
          readEndpointFromContext("empty_values_base", defaults.emptyValuesBase)
        ),
        validateVariant: readEndpointFromContext(
          "validateVariant",
          readEndpointFromContext("validate_variant", defaults.validateVariant)
        )
      };

      Object.keys(defaults).forEach(function (endpointKey) {
        endpoints[endpointKey] = normalizeEndpointCandidate(
          endpoints[endpointKey],
          endpointKey,
          "resolved",
          0
        ) || defaults[endpointKey];
      });

      runtime.cache.endpoints = endpoints;
      runtime.cache.endpointContextSignature = signature;
      runtime.diagnostics.lastEndpointRefreshAt = Date.now();

      return endpoints;
    } catch (error) {
      warn("Could not read definitions endpoints.", error);
      runtime.cache.endpoints = getDefaultEndpoints();
      runtime.cache.endpointContextSignature = "";
      return runtime.cache.endpoints;
    }
  }

  function buildQuery(params) {
    try {
      var pairs = [];

      Object.keys(params || {}).sort().forEach(function (key) {
        var value = params[key];

        if (
          value === null ||
          value === undefined ||
          value === "" ||
          typeof value === "object" ||
          typeof value === "function"
        ) {
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
      var left = normalizeEndpointCandidate(base, "base", "joinUrl", 0);
      var right = suffix === null || suffix === undefined || typeof suffix === "object"
        ? ""
        : String(suffix).trim();

      if (!left) {
        return "";
      }

      if (!right) {
        return left;
      }

      if (left.slice(-1) !== "/") {
        left += "/";
      }

      return left + encodeURIComponent(right);
    } catch (error) {
      return normalizeEndpointCandidate(base, "base", "joinUrl_error", 0);
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

  function createComponentError(code, message, details, cause) {
    var error;

    try {
      error = new Error(String(message || code || "Unbekannter Fehler."));
    } catch (constructionError) {
      error = {
        name: "Error",
        message: String(message || code || "Unbekannter Fehler.")
      };
    }

    try {
      error.name = "VectoplanCreateVariantProfilesError";
      error.code = String(code || "variant_profiles_error");
      error.component = COMPONENT_NAME;
      error.componentVersion = COMPONENT_VERSION;
      error.__vp_variant_profiles_error = true;

      if (details && typeof details === "object") {
        error.details = U().deepClone ? U().deepClone(details, details) : details;

        if (details.status !== undefined && details.status !== null) {
          error.status = details.status;
        }

        if (details.url) {
          error.url = String(details.url);
        }

        if (details.method) {
          error.method = String(details.method);
        }

        if (details.payload !== undefined) {
          error.payload = details.payload;
        }
      }

      if (cause !== undefined && cause !== null) {
        try {
          error.cause = cause;
        } catch (causeError) {
          /* no-op */
        }
      }
    } catch (enrichmentError) {
      /* Preserve the Error even if enrichment fails. */
    }

    return error;
  }

  function ensureComponentError(error, fallbackCode, fallbackMessage, details) {
    try {
      if (error && error.__vp_variant_profiles_error === true && error.message) {
        return error;
      }

      if (error instanceof Error) {
        if (!error.code) {
          error.code = fallbackCode || error.name || "variant_profiles_error";
        }

        if (!error.component) {
          error.component = COMPONENT_NAME;
        }

        error.__vp_variant_profiles_error = true;

        if (details && typeof details === "object" && !error.details) {
          error.details = details;
        }

        return error;
      }

      var source = error && error.error && typeof error.error === "object"
        ? error.error
        : (error || {});

      var code = source.code ||
        source.error_code ||
        source.status ||
        source.name ||
        fallbackCode ||
        "variant_profiles_error";

      var message = source.message ||
        source.detail ||
        source.description ||
        fallbackMessage ||
        (typeof error === "string" ? error : "") ||
        "Unbekannter Fehler.";

      var mergedDetails = U().safeMerge ? U().safeMerge(
        details || {},
        {
          status: source.status || null,
          url: source.url || null,
          method: source.method || null,
          payload: source.payload || source.raw || source.response || null
        }
      ) : (details || {});

      return createComponentError(code, message, mergedDetails, error);
    } catch (normalizationError) {
      return createComponentError(
        fallbackCode || "variant_profiles_error",
        fallbackMessage || "Fehler konnte nicht normalisiert werden.",
        details || {},
        error
      );
    }
  }

  function normalizeError(error) {
    try {
      var normalized = ensureComponentError(
        error,
        "variant_profiles_error",
        "Unbekannter Fehler."
      );

      return {
        code: normalized.code || normalized.name || "variant_profiles_error",
        message: normalized.message || "Unbekannter Fehler.",
        name: normalized.name || "Error",
        status: normalized.status || null,
        url: normalized.url || null,
        method: normalized.method || null,
        payload: normalized.payload || null,
        details: normalized.details || null,
        component: normalized.component || COMPONENT_NAME
      };
    } catch (normalizationError) {
      return {
        code: "variant_profiles_error",
        message: "Fehler konnte nicht normalisiert werden.",
        name: "Error",
        status: null,
        url: null,
        method: null,
        payload: null,
        details: null,
        component: COMPONENT_NAME
      };
    }
  }

  function failureStatusFromError(error) {
    try {
      var normalized = normalizeError(error);
      var code = String(normalized.code || "").toLowerCase();
      var status = parseInt(normalized.status || 0, 10) || 0;

      if (status === 404 || code.indexOf("not_found") !== -1 || code.indexOf("http_404") !== -1) {
        return "not_found";
      }

      if (status === 400 || status === 422 || code.indexOf("invalid") !== -1 || code.indexOf("missing") !== -1) {
        return "invalid_request";
      }

      if (status === 408 || status === 504 || code.indexOf("timeout") !== -1 || code.indexOf("abort") !== -1) {
        return "timeout";
      }

      if (status === 503 || code.indexOf("unavailable") !== -1 || code.indexOf("network") !== -1) {
        return "unavailable";
      }

      return "error";
    } catch (statusError) {
      return "error";
    }
  }

  function buildFailureResult(kind, error, extra) {
    try {
      var normalizedError = normalizeError(error);
      var payload = U().safeMerge ? U().safeMerge(
        {
          ok: false,
          ready: false,
          healthy: false,
          status: failureStatusFromError(error),
          kind: kind || "variant_profile",
          source: "client",
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          error: normalizedError
        },
        extra || {}
      ) : (extra || {});

      payload.ok = false;
      payload.ready = false;
      payload.error = normalizedError;
      payload.status = payload.status || failureStatusFromError(error);
      payload.component = payload.component || COMPONENT_NAME;
      payload.version = payload.version || COMPONENT_VERSION;

      return payload;
    } catch (buildError) {
      return {
        ok: false,
        ready: false,
        healthy: false,
        status: "error",
        kind: kind || "variant_profile",
        source: "client",
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        error: {
          code: "failure_result_error",
          message: "Fehlerergebnis konnte nicht erstellt werden."
        }
      };
    }
  }

  function shouldReject(options) {
    try {
      var config = options || {};

      if (config.rejectOnError === true) {
        return true;
      }

      if (config.rejectOnError === false) {
        return false;
      }

      return runtime.options.rejectOnError === true;
    } catch (error) {
      return false;
    }
  }

  function settleFailure(kind, error, extra, options) {
    var normalizedError = ensureComponentError(
      error,
      String(kind || "variant_profile") + "_error",
      "Variant-Profile-Aktion ist fehlgeschlagen."
    );

    if (shouldReject(options)) {
      return Promise.reject(normalizedError);
    }

    return Promise.resolve(buildFailureResult(kind, normalizedError, extra));
  }

  function setRuntimeStatus(status, error, details) {
    try {
      var nextStatus = String(status || "unknown").trim().toLowerCase() || "unknown";
      var normalizedError = error ? normalizeError(error) : null;

      runtime.status = nextStatus;
      runtime.operational = nextStatus === "ready";
      runtime.lastError = normalizedError;

      document.documentElement.setAttribute(INITIALIZED_ATTR, runtime.initialized ? "true" : "false");
      document.documentElement.setAttribute(READY_ATTR, runtime.operational ? "true" : "false");
      document.documentElement.setAttribute(OPERATIONAL_ATTR, runtime.operational ? "true" : "false");
      document.documentElement.setAttribute(STATUS_ATTR, nextStatus);
      document.documentElement.setAttribute("data-vp-create-variant-profiles-version", COMPONENT_VERSION);

      U().dispatchDocument("vectoplan:create:variant-profiles-status-changed", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        initialized: runtime.initialized,
        operational: runtime.operational,
        ready: runtime.operational,
        status: nextStatus,
        error: normalizedError,
        details: details || null,
        __vp_variant_profiles_event: true
      }, {
        silent: true
      });

      return nextStatus;
    } catch (statusError) {
      runtime.status = String(status || "unknown");
      runtime.operational = runtime.status === "ready";
      runtime.lastError = error ? normalizeError(error) : null;
      return runtime.status;
    }
  }

  function pruneRequestCache(maxEntries) {
    try {
      var limit = parseInt(maxEntries, 10);

      if (!Number.isFinite(limit) || limit < 1) {
        limit = 64;
      }

      var now = Date.now();
      var meta = runtime.cache.requestMeta || {};
      var keys = Object.keys(meta);

      keys.forEach(function (key) {
        var item = meta[key] || {};

        if (item.inFlight !== true && item.expiresAt && item.expiresAt <= now) {
          delete runtime.cache.requests[key];
          delete runtime.cache.requestMeta[key];
        }
      });

      keys = Object.keys(runtime.cache.requestMeta || {});

      if (keys.length <= limit) {
        return;
      }

      keys.sort(function (left, right) {
        var leftMeta = runtime.cache.requestMeta[left] || {};
        var rightMeta = runtime.cache.requestMeta[right] || {};
        var leftTime = leftMeta.settledAt || leftMeta.startedAt || 0;
        var rightTime = rightMeta.settledAt || rightMeta.startedAt || 0;
        return leftTime - rightTime;
      });

      while (keys.length > limit) {
        var removableKey = keys.shift();
        var removableMeta = runtime.cache.requestMeta[removableKey] || {};

        if (removableMeta.inFlight === true) {
          keys.push(removableKey);

          if (keys.every(function (candidate) {
            return (runtime.cache.requestMeta[candidate] || {}).inFlight === true;
          })) {
            break;
          }

          continue;
        }

        delete runtime.cache.requests[removableKey];
        delete runtime.cache.requestMeta[removableKey];
      }
    } catch (error) {
      /* Cache pruning must never block a request. */
    }
  }

  function requestJson(url, options) {
    var config = options || {};
    var rawUrl = url;
    var requestUrl = normalizeEndpointCandidate(url, "request", "requestJson", 0);
    var method = String(config.method || "GET").toUpperCase();
    var body = config.body === undefined ? null : config.body;
    var bodyText = body === null ? "" : U().safeJsonStringify(body, "");
    var cacheKey = method + " " + requestUrl + (bodyText ? " " + bodyText : "");
    var timeoutMs = parseInt(
      config.timeoutMs !== undefined ? config.timeoutMs : runtime.options.requestTimeoutMs,
      10
    );
    var cacheTtlMs = parseInt(
      config.cacheTtlMs !== undefined ? config.cacheTtlMs : runtime.options.requestCacheTtlMs,
      10
    );
    var useRequestCache = config.useRequestCache !== false;
    var now = Date.now();

    try {
      if (useRequestCache) {
        pruneRequestCache(
          config.requestCacheMaxEntries !== undefined
            ? config.requestCacheMaxEntries
            : runtime.options.requestCacheMaxEntries
        );
      }
      if (!requestUrl) {
        return Promise.reject(createComponentError(
          "invalid_url",
          "Für den Definitionsrequest wurde keine gültige URL angegeben.",
          {
            method: method,
            url: typeof rawUrl === "string" ? rawUrl : "",
            receivedType: typeof rawUrl
          }
        ));
      }

      if (useRequestCache && runtime.cache.requests[cacheKey]) {
        var existingMeta = runtime.cache.requestMeta[cacheKey] || {};
        var existingIsFresh = existingMeta.inFlight === true ||
          !existingMeta.expiresAt ||
          existingMeta.expiresAt > now;

        if (existingIsFresh) {
          return runtime.cache.requests[cacheKey];
        }

        delete runtime.cache.requests[cacheKey];
        delete runtime.cache.requestMeta[cacheKey];
      }

      if (!canFetch()) {
        return Promise.reject(createComponentError(
          "fetch_unavailable",
          "Fetch API ist nicht verfügbar.",
          {
            method: method,
            url: requestUrl
          }
        ));
      }

      if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
        timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS;
      }

      if (!Number.isFinite(cacheTtlMs) || cacheTtlMs < 0) {
        cacheTtlMs = DEFAULT_REQUEST_CACHE_TTL_MS;
      }

      runtime.requestSequence += 1;
      var requestId = COMPONENT_NAME + ":" + String(runtime.requestSequence);
      var controller = typeof window.AbortController === "function"
        ? new window.AbortController()
        : null;
      var externalSignal = config.signal || null;
      var timeoutId = null;
      var externalAbortHandler = null;

      if (controller && externalSignal && typeof externalSignal.addEventListener === "function") {
        externalAbortHandler = function () {
          try {
            controller.abort(externalSignal.reason || "external_abort");
          } catch (abortError) {
            controller.abort();
          }
        };

        if (externalSignal.aborted) {
          externalAbortHandler();
        } else {
          externalSignal.addEventListener("abort", externalAbortHandler, {
            once: true
          });
        }
      }

      if (controller && timeoutMs > 0) {
        timeoutId = window.setTimeout(function () {
          try {
            controller.abort("timeout");
          } catch (abortError) {
            try {
              controller.abort();
            } catch (ignoredAbortError) {
              /* no-op */
            }
          }
        }, timeoutMs);
      }

      var fetchOptions = {
        method: method,
        headers: {
          "Accept": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-Vectoplan-Component": COMPONENT_NAME,
          "X-Vectoplan-Component-Version": COMPONENT_VERSION,
          "X-Vectoplan-Request-Id": requestId
        },
        credentials: "same-origin",
        cache: config.browserCache || "no-store"
      };

      if (controller) {
        fetchOptions.signal = controller.signal;
      } else if (externalSignal) {
        fetchOptions.signal = externalSignal;
      }

      if (config.headers && typeof config.headers === "object") {
        Object.keys(config.headers).forEach(function (headerName) {
          fetchOptions.headers[headerName] = config.headers[headerName];
        });
      }

      if (method !== "GET" && method !== "HEAD" && body !== null) {
        fetchOptions.headers["Content-Type"] = "application/json";
        fetchOptions.body = bodyText || "{}";
      }

      if (useRequestCache) {
        runtime.cache.requestMeta[cacheKey] = {
          requestId: requestId,
          method: method,
          url: String(requestUrl),
          startedAt: now,
          inFlight: true,
          expiresAt: 0
        };
      }

      var cleanup = function () {
        try {
          if (timeoutId !== null) {
            window.clearTimeout(timeoutId);
            timeoutId = null;
          }

          if (
            externalSignal &&
            externalAbortHandler &&
            typeof externalSignal.removeEventListener === "function"
          ) {
            externalSignal.removeEventListener("abort", externalAbortHandler);
          }
        } catch (cleanupError) {
          /* no-op */
        }
      };

      var promise = window.fetch(requestUrl, fetchOptions)
        .then(function (response) {
          return response.text()
            .catch(function (readError) {
              throw createComponentError(
                "response_read_failed",
                "Die Serverantwort konnte nicht gelesen werden.",
                {
                  status: response.status,
                  method: method,
                  url: requestUrl,
                  requestId: requestId
                },
                readError
              );
            })
            .then(function (responseText) {
              var json = U().safeJsonParse(responseText, null);
              var responseDetails = {
                status: response.status,
                method: method,
                url: requestUrl,
                requestId: requestId,
                payload: json,
                responseText: responseText
              };

              if (!response.ok) {
                var serverError = json && json.error && typeof json.error === "object"
                  ? json.error
                  : {};

                throw createComponentError(
                  serverError.code || "http_" + String(response.status),
                  serverError.message ||
                    (json && json.message) ||
                    "HTTP " + String(response.status) + " beim Laden der Definitionsdaten.",
                  responseDetails
                );
              }

              if (!json || typeof json !== "object" || Array.isArray(json)) {
                throw createComponentError(
                  "invalid_json",
                  "Antwort ist kein gültiges JSON-Objekt.",
                  responseDetails
                );
              }

              return json;
            });
        })
        .catch(function (error) {
          var isAbort = error && (
            error.name === "AbortError" ||
            error.code === "ABORT_ERR" ||
            String(error.message || "").toLowerCase().indexOf("abort") !== -1
          );

          if (isAbort) {
            throw createComponentError(
              "request_timeout",
              "Definitionsrequest wurde nach " + String(timeoutMs) + " ms abgebrochen.",
              {
                method: method,
                url: requestUrl,
                requestId: requestId,
                timeoutMs: timeoutMs
              },
              error
            );
          }

          throw ensureComponentError(
            error,
            "definitions_request_failed",
            "Definitionsrequest ist fehlgeschlagen.",
            {
              method: method,
              url: requestUrl,
              requestId: requestId
            }
          );
        })
        .then(function (payload) {
          cleanup();

          if (useRequestCache) {
            runtime.cache.requestMeta[cacheKey] = {
              requestId: requestId,
              method: method,
              url: String(requestUrl),
              startedAt: now,
              settledAt: Date.now(),
              inFlight: false,
              expiresAt: Date.now() + cacheTtlMs,
              ok: true
            };
          }

          return payload;
        }, function (error) {
          cleanup();
          delete runtime.cache.requests[cacheKey];
          delete runtime.cache.requestMeta[cacheKey];
          throw ensureComponentError(
            error,
            "definitions_request_failed",
            "Definitionsrequest ist fehlgeschlagen.",
            {
              method: method,
              url: requestUrl,
              requestId: requestId
            }
          );
        });

      if (useRequestCache) {
        runtime.cache.requests[cacheKey] = promise;
      }

      return promise;
    } catch (error) {
      return Promise.reject(ensureComponentError(
        error,
        "definitions_request_setup_failed",
        "Definitionsrequest konnte nicht vorbereitet werden.",
        {
          method: method,
          url: requestUrl
        }
      ));
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

      if (
        hasDefinitionData(getDefinitionsSync()) &&
        (config.localOnly === true || shouldPreferLocal(config)) &&
        config.force !== true &&
        config.forceReload !== true
      ) {
        return Promise.resolve(getDefinitionsSync());
      }

      if (config.localOnly === true || !canFetch() || runtime.options.fetchDefinitions === false) {
        var localOnly = getDefinitionsSync();
        if (hasDefinitionData(localOnly)) {
          return Promise.resolve(localOnly);
        }

        return Promise.reject(createComponentError(
          "definitions_not_loaded",
          "Keine Definitionsdaten im Fensterkontext gefunden."
        ));
      }

      var endpoints = getEndpoints();

      return requestJson(endpoints.options, {
        method: "GET",
        useRequestCache: shouldUseRequestCache(config)
      }).then(function (payload) {
        var data = unwrapResponse(payload);
        var definitions = normalizeDefinitions(data);

        if (!hasDefinitionData(definitions)) {
          definitions = normalizeDefinitions(payload);
        }

        if (!hasDefinitionData(definitions)) {
          throw createComponentError(
            "definitions_empty",
            "Definitionsantwort enthält keine nutzbaren Definitionsdaten.",
            {
              payload: payload,
              url: endpoints.options
            }
          );
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

        throw ensureComponentError(
          error,
          "definitions_load_failed",
          "Definitionsdaten konnten nicht geladen werden."
        );
      });
    } catch (error) {
      return Promise.reject(ensureComponentError(
        error,
        "variant_profiles_async_error",
        "Asynchrone Variant-Profile-Aktion ist fehlgeschlagen."
      ));
    }
  }

  function fetchDefinitionsPublic(options) {
    var config = options || {};

    try {
      return fetchDefinitions(config).catch(function (error) {
        var failed = buildFailureResult("definitions", error, {
          source: config.source || "fetch_definitions",
          definitions: getDefinitionsSync()
        });

        runtime.lastError = failed.error;

        U().dispatchDocument("vectoplan:create:definitions-unavailable", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          error: failed.error,
          definitions: getDefinitionsSync(),
          failure: failed,
          __vp_variant_profiles_event: true
        }, {
          silent: true
        });

        if (shouldReject(config)) {
          throw ensureComponentError(
            error,
            "definitions_load_failed",
            "Definitionsdaten konnten nicht geladen werden."
          );
        }

        return failed;
      });
    } catch (error) {
      return settleFailure("definitions", error, {
        source: config.source || "fetch_definitions",
        definitions: getDefinitionsSync()
      }, config);
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

      var explicitFamilyProfile = ctx.family_profile_id
        ? (
          maps.familyProfilesById[ctx.family_profile_id] ||
          maps.familyProfilesById[String(ctx.family_profile_id).toLowerCase()] ||
          null
        )
        : null;

      if (explicitFamilyProfile) {
        var canonicalFamilyProfileId = profileKey(
          explicitFamilyProfile.id ||
          explicitFamilyProfile.family_profile_id ||
          explicitFamilyProfile.familyProfileId ||
          ctx.family_profile_id
        );

        return {
          ok: true,
          ready: true,
          healthy: true,
          status: "resolved",
          source: "local_explicit",
          requested_family_profile_id: ctx.family_profile_id,
          family_profile_id: canonicalFamilyProfileId,
          familyProfileId: canonicalFamilyProfileId,
          family_profile: explicitFamilyProfile,
          familyProfile: explicitFamilyProfile,
          context: normalizeContext(U().safeMerge(ctx, {
            family_profile_id: canonicalFamilyProfileId,
            familyProfileId: canonicalFamilyProfileId
          }))
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

      var explicitVariantProfile = ctx.variant_profile_id
        ? (
          maps.variantProfilesById[ctx.variant_profile_id] ||
          maps.variantProfilesById[String(ctx.variant_profile_id).toLowerCase()] ||
          null
        )
        : null;

      if (explicitVariantProfile) {
        var canonicalVariantProfileId = profileKey(
          explicitVariantProfile.id ||
          explicitVariantProfile.variant_profile_id ||
          explicitVariantProfile.variantProfileId ||
          ctx.variant_profile_id
        );

        return {
          ok: true,
          ready: true,
          healthy: true,
          status: "resolved",
          source: "local_explicit",
          family_profile_id: ctx.family_profile_id,
          familyProfileId: ctx.family_profile_id,
          variant_profile_id: canonicalVariantProfileId,
          variantProfileId: canonicalVariantProfileId,
          requested_variant_profile_id: ctx.variant_profile_id,
          variant_profile: explicitVariantProfile,
          variantProfile: explicitVariantProfile,
          profile: explicitVariantProfile,
          context: normalizeContext(U().safeMerge(ctx, {
            variant_profile_id: canonicalVariantProfileId,
            variantProfileId: canonicalVariantProfileId
          }))
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
        source: data.source || source || "unknown",
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
        source: data.source || source || "unknown",
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
      var requestedId = profileKey(profileId);
      var data = unwrapResponse(payload || {});
      var profile = firstNonEmpty(
        data.item,
        data.variant_profile,
        data.variantProfile,
        data.profile,
        pathGet(data, "data.item", null),
        pathGet(data, "data.variant_profile", null),
        pathGet(data, "data.variantProfile", null),
        pathGet(data, "result.item", null),
        pathGet(data, "result.variant_profile", null),
        pathGet(data, "payload.item", null)
      );

      if (
        profile &&
        typeof profile === "object" &&
        !Array.isArray(profile) &&
        profile.item &&
        typeof profile.item === "object"
      ) {
        profile = profile.item;
      }

      var resolvedId = profileKey(
        profile && (
          profile.id ||
          profile.variant_profile_id ||
          profile.variantProfileId ||
          profile.profile_id ||
          profile.profileId ||
          profile.definition_key ||
          profile.key
        ) ||
        data.variant_profile_id ||
        data.variantProfileId ||
        data.profile_id ||
        data.profileId ||
        requestedId
      );

      if ((!profile || typeof profile !== "object" || Array.isArray(profile)) && resolvedId) {
        profile = getDefinitionMaps().variantProfilesById[resolvedId] || null;
      }

      if (
        profile &&
        typeof profile === "object" &&
        !Array.isArray(profile) &&
        !resolvedId
      ) {
        resolvedId = profileKey(
          profile.id ||
          profile.variant_profile_id ||
          profile.variantProfileId ||
          profile.profile_id ||
          profile.profileId ||
          profile.definition_key ||
          profile.key ||
          requestedId
        );
      }

      if (!profile || typeof profile !== "object" || Array.isArray(profile) || !resolvedId) {
        return buildFailureResult(
          "profile",
          createComponentError(
            "variant_profile_not_found",
            "Variant Profile '" + String(requestedId || profileId || "") + "' wurde nicht gefunden.",
            {
              profileId: requestedId || profileId || "",
              payload: payload
            }
          ),
          {
            source: data.source || source || "unknown",
            profile_id: requestedId,
            variant_profile_id: requestedId,
            variantProfileId: requestedId,
            raw: payload
          }
        );
      }

      var normalizedProfile = U().deepClone(profile, profile);

      if (!normalizedProfile.id) {
        normalizedProfile.id = resolvedId;
      }

      return {
        ok: true,
        ready: true,
        healthy: true,
        status: "ok",
        source: data.source || data.definition_source || source || "unknown",
        profile_id: resolvedId,
        variant_profile_id: resolvedId,
        variantProfileId: resolvedId,
        requested_profile_id: requestedId,
        variant_profile: normalizedProfile,
        variantProfile: normalizedProfile,
        profile: normalizedProfile,
        resolved: data.resolved === true || normalizedProfile.resolved === true,
        raw: payload
      };
    } catch (error) {
      return buildFailureResult("profile", error, {
        source: source || "unknown",
        profile_id: profileKey(profileId),
        variant_profile_id: profileKey(profileId),
        variantProfileId: profileKey(profileId),
        raw: payload
      });
    }
  }

  function normalizeEmptyValuesPayload(payload, profileId, context, source) {
    try {
      var id = profileKey(profileId);
      var data = unwrapResponse(payload || {});
      var values = firstNonEmpty(
        data.values,
        data.empty_values,
        data.emptyValues,
        data.default_values,
        data.defaultValues,
        data.defaults,
        data.item && data.item.values,
        data.item && data.item.default_values,
        pathGet(data, "data.values", null),
        pathGet(data, "result.values", null)
      );

      if (!values || typeof values !== "object" || Array.isArray(values)) {
        values = {};
      }

      var explicitFailure = payload && payload.ok === false;
      var accepted = !explicitFailure && (
        responseOk(payload) ||
        Object.keys(values).length > 0 ||
        (payload && !Object.prototype.hasOwnProperty.call(payload, "ok"))
      );

      if (!accepted) {
        return buildFailureResult(
          "empty_values",
          createComponentError(
            "empty_values_unavailable",
            "Defaultwerte für Variant Profile '" + String(id || profileId || "") + "' konnten nicht geladen werden.",
            {
              profileId: id || profileId || "",
              payload: payload
            }
          ),
          {
            source: data.source || source || "unknown",
            profile_id: id,
            variant_profile_id: id,
            variantProfileId: id,
            values: {},
            context: normalizeContext(context || {}),
            raw: payload
          }
        );
      }

      return {
        ok: true,
        ready: true,
        healthy: true,
        status: "ok",
        source: data.source || source || "unknown",
        profile_id: id,
        variant_profile_id: id,
        variantProfileId: id,
        values: U().deepClone(values, values),
        context: normalizeContext(context || {}),
        raw: payload
      };
    } catch (error) {
      return buildFailureResult("empty_values", error, {
        source: source || "unknown",
        profile_id: profileKey(profileId),
        variant_profile_id: profileKey(profileId),
        variantProfileId: profileKey(profileId),
        values: {},
        context: normalizeContext(context || {}),
        raw: payload
      });
    }
  }

  function shouldUseRequestCache(options) {
    try {
      var config = options || {};

      return config.useRequestCache !== false &&
        config.force !== true &&
        config.forceReload !== true;
    } catch (error) {
      return true;
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
          useRequestCache: shouldUseRequestCache(config)
        }).then(function (payload) {
          return normalizeFamilyResult(payload, ctx, "backend_post");
        });
      }

      return requestJson(endpoints.resolveFamilyProfile + buildQuery(ctx), {
        method: "GET",
        useRequestCache: shouldUseRequestCache(config)
      }).then(function (payload) {
        return normalizeFamilyResult(payload, ctx, "backend_get");
      });
    } catch (error) {
      return Promise.reject(ensureComponentError(
        error,
        "variant_profiles_async_error",
        "Asynchrone Variant-Profile-Aktion ist fehlgeschlagen."
      ));
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
          useRequestCache: shouldUseRequestCache(config)
        }).then(function (payload) {
          return normalizeVariantResult(payload, ctx, "backend_post");
        });
      }

      return requestJson(endpoints.resolveVariantProfile + buildQuery(ctx), {
        method: "GET",
        useRequestCache: shouldUseRequestCache(config)
      }).then(function (payload) {
        return normalizeVariantResult(payload, ctx, "backend_get");
      });
    } catch (error) {
      return Promise.reject(ensureComponentError(
        error,
        "variant_profiles_async_error",
        "Asynchrone Variant-Profile-Aktion ist fehlgeschlagen."
      ));
    }
  }

  function getVariantProfileBackend(profileId, options) {
    try {
      var id = profileKey(profileId);
      var config = options || {};
      var endpoints = getEndpoints();

      if (!id) {
        return Promise.reject(createComponentError(
          "missing_profile_id",
          "Keine Variant Profile ID angegeben."
        ));
      }

      var profileUrl = joinUrl(endpoints.variantProfileBase, id) + buildQuery({
        resolved: config.resolved === false ? 0 : 1
      });

      return requestJson(profileUrl, {
        method: "GET",
        useRequestCache: shouldUseRequestCache(config),
        timeoutMs: config.timeoutMs
      }).then(function (payload) {
        return normalizeProfilePayload(payload, id, "backend");
      });
    } catch (error) {
      return Promise.reject(ensureComponentError(
        error,
        "variant_profiles_async_error",
        "Asynchrone Variant-Profile-Aktion ist fehlgeschlagen."
      ));
    }
  }

  function getEmptyValuesBackend(profileId, context, options) {
    try {
      var id = profileKey(profileId);
      var ctx = normalizeContext(context || {});
      var config = options || {};
      var endpoints = getEndpoints();

      if (!id) {
        return Promise.reject(createComponentError(
          "missing_profile_id",
          "Keine Variant Profile ID für Empty Values angegeben."
        ));
      }

      if (config.method === "POST") {
        return requestJson(joinUrl(endpoints.emptyValuesBase, id), {
          method: "POST",
          body: ctx,
          useRequestCache: shouldUseRequestCache(config)
        }).then(function (payload) {
          return normalizeEmptyValuesPayload(payload, id, ctx, "backend_post");
        });
      }

      return requestJson(joinUrl(endpoints.emptyValuesBase, id) + buildQuery(ctx), {
        method: "GET",
        useRequestCache: shouldUseRequestCache(config)
      }).then(function (payload) {
        return normalizeEmptyValuesPayload(payload, id, ctx, "backend_get");
      });
    } catch (error) {
      return Promise.reject(ensureComponentError(
        error,
        "variant_profiles_async_error",
        "Asynchrone Variant-Profile-Aktion ist fehlgeschlagen."
      ));
    }
  }

  function getVariantProfileLocal(profileId) {
    try {
      var requestedId = profileKey(profileId);
      var maps = getDefinitionMaps();
      var profile = maps.variantProfilesById[requestedId] ||
        maps.variantProfilesById[String(requestedId).toLowerCase()] ||
        null;

      if (!profile) {
        return buildFailureResult(
          "profile",
          createComponentError(
            "variant_profile_not_found",
            "Variant Profile '" + String(requestedId || profileId || "") + "' wurde lokal nicht gefunden.",
            {
              profileId: requestedId || profileId || ""
            }
          ),
          {
            source: "local",
            profile_id: requestedId,
            variant_profile_id: requestedId,
            variantProfileId: requestedId
          }
        );
      }

      var canonicalId = profileKey(
        profile.id ||
        profile.variant_profile_id ||
        profile.variantProfileId ||
        profile.profile_id ||
        profile.profileId ||
        requestedId
      );

      return {
        ok: true,
        ready: true,
        healthy: true,
        status: "ok",
        source: "local",
        requested_profile_id: requestedId,
        profile_id: canonicalId,
        variant_profile_id: canonicalId,
        variantProfileId: canonicalId,
        variant_profile: profile,
        variantProfile: profile,
        profile: profile
      };
    } catch (error) {
      return buildFailureResult("profile", error, {
        source: "local",
        profile_id: profileKey(profileId),
        variant_profile_id: profileKey(profileId),
        variantProfileId: profileKey(profileId)
      });
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
      var canonicalId = profileKey(
        profileResult.variant_profile_id ||
        profileResult.profile_id ||
        (profile && profile.id) ||
        id
      );
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
        profile_id: canonicalId,
        variant_profile_id: canonicalId,
        variantProfileId: canonicalId,
        requested_profile_id: id,
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
    var ctx = normalizeContext(context || getCurrentContext());
    var config = options || {};
    var key = contextKey(ctx, "family");

    try {
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
        if (localFirst.ok) {
          runtime.cache.familyResolve[key] = localFirst;
          dispatchFamilyResolved(localFirst);
          return Promise.resolve(localFirst);
        }

        dispatchResolutionFailed("family", localFirst);
        return Promise.resolve(localFirst);
      }

      return resolveFamilyProfileBackend(ctx, config)
        .then(function (result) {
          if (!result || !result.ok) {
            throw ensureComponentError(
              result && result.error ? result.error : result,
              "family_profile_not_found",
              "Family Profile konnte nicht aufgelöst werden.",
              {
                context: ctx
              }
            );
          }

          runtime.cache.familyResolve[key] = result;
          dispatchFamilyResolved(result);
          return result;
        })
        .catch(function (error) {
          var local = localFirst.ok ? U().deepClone(localFirst, localFirst) : resolveFamilyProfileLocal(ctx);

          if (local.ok) {
            local.backend_error = normalizeError(error);
            local.source = local.source || "local_fallback";
            runtime.cache.familyResolve[key] = local;
            dispatchFamilyResolved(local);
            return local;
          }

          var failed = buildFailureResult("family", error, {
            source: "backend_then_local_failed",
            context: ctx,
            local_error: local.error || null
          });

          dispatchResolutionFailed("family", failed);

          if (shouldReject(config)) {
            throw ensureComponentError(
              error,
              "family_profile_resolution_failed",
              "Family Profile konnte nicht aufgelöst werden.",
              {
                context: ctx,
                local_error: local.error || null
              }
            );
          }

          return failed;
        });
    } catch (error) {
      return settleFailure("family", error, {
        source: "client",
        context: ctx
      }, config);
    }
  }

  function resolveVariantProfile(context, options) {
    var ctx = normalizeContext(context || getCurrentContext());
    var config = options || {};
    var key = contextKey(ctx, "variant");

    try {
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
        if (localFirst.ok) {
          runtime.cache.variantResolve[key] = localFirst;
          applyResolvedProfile(localFirst);
          dispatchVariantResolved(localFirst);
        } else {
          dispatchResolutionFailed("variant", localFirst);
        }

        return Promise.resolve(localFirst);
      }

      return resolveVariantProfileBackend(ctx, config)
        .then(function (result) {
          if (!result || !result.ok) {
            throw ensureComponentError(
              result && result.error ? result.error : result,
              "variant_profile_not_found",
              "Variant Profile konnte nicht aufgelöst werden.",
              {
                context: ctx
              }
            );
          }

          runtime.cache.variantResolve[key] = result;
          applyResolvedProfile(result);
          dispatchVariantResolved(result);
          return result;
        })
        .catch(function (error) {
          var local = localFirst.ok ? U().deepClone(localFirst, localFirst) : resolveVariantProfileLocal(ctx);

          if (local.ok) {
            local.backend_error = normalizeError(error);
            local.source = local.source || "local_fallback";
            runtime.cache.variantResolve[key] = local;
            applyResolvedProfile(local);
            dispatchVariantResolved(local);
            return local;
          }

          var failed = buildFailureResult("variant", error, {
            source: "backend_then_local_failed",
            context: ctx,
            local_error: local.error || null
          });

          dispatchResolutionFailed("variant", failed);

          if (shouldReject(config)) {
            throw ensureComponentError(
              error,
              "variant_profile_resolution_failed",
              "Variant Profile konnte nicht aufgelöst werden.",
              {
                context: ctx,
                local_error: local.error || null
              }
            );
          }

          return failed;
        });
    } catch (error) {
      return settleFailure("variant", error, {
        source: "client",
        context: ctx
      }, config);
    }
  }

  function getVariantProfile(profileId, options) {
    var id = profileKey(profileId);
    var config = options || {};

    try {
      if (!id) {
        return settleFailure(
          "profile",
          createComponentError(
            "missing_profile_id",
            "Keine Variant Profile ID angegeben."
          ),
          {
            source: "client",
            profile_id: "",
            variant_profile_id: ""
          },
          config
        );
      }

      if (
        runtime.cache.variantProfiles[id] &&
        runtime.cache.variantProfiles[id].ok === true &&
        config.force !== true &&
        config.forceReload !== true
      ) {
        return Promise.resolve(runtime.cache.variantProfiles[id]);
      }

      var localFirst = getVariantProfileLocal(id);

      if ((config.localOnly === true || shouldPreferLocal(config) || !canFetch()) && localFirst.ok) {
        runtime.cache.variantProfiles[id] = localFirst;
        if (localFirst.variant_profile_id) {
          runtime.cache.variantProfiles[localFirst.variant_profile_id] = localFirst;
        }
        dispatchVariantProfileLoaded(localFirst);
        return Promise.resolve(localFirst);
      }

      if (config.localOnly === true || !canFetch()) {
        if (localFirst.ok) {
          runtime.cache.variantProfiles[id] = localFirst;
          if (localFirst.variant_profile_id) {
            runtime.cache.variantProfiles[localFirst.variant_profile_id] = localFirst;
          }
          dispatchVariantProfileLoaded(localFirst);
        } else {
          dispatchResolutionFailed("profile", localFirst);
        }

        return Promise.resolve(localFirst);
      }

      return getVariantProfileBackend(id, config)
        .then(function (result) {
          if (!result || !result.ok || !result.variant_profile) {
            throw ensureComponentError(
              result && result.error ? result.error : result,
              "variant_profile_not_found",
              "Variant Profile '" + String(id) + "' konnte nicht geladen werden.",
              {
                profileId: id
              }
            );
          }

          runtime.cache.variantProfiles[id] = result;

          if (result.variant_profile_id && result.variant_profile_id !== id) {
            runtime.cache.variantProfiles[result.variant_profile_id] = result;
          }

          dispatchVariantProfileLoaded(result);
          return result;
        })
        .catch(function (error) {
          var local = localFirst.ok ? U().deepClone(localFirst, localFirst) : getVariantProfileLocal(id);

          if (local.ok) {
            local.backend_error = normalizeError(error);
            local.source = local.source || "local_fallback";
            runtime.cache.variantProfiles[id] = local;
            if (local.variant_profile_id) {
              runtime.cache.variantProfiles[local.variant_profile_id] = local;
            }
            dispatchVariantProfileLoaded(local);
            return local;
          }

          var failed = buildFailureResult("profile", error, {
            source: "backend_then_local_failed",
            profile_id: id,
            variant_profile_id: id,
            variantProfileId: id,
            local_error: local.error || null
          });

          dispatchResolutionFailed("profile", failed);

          if (shouldReject(config)) {
            throw ensureComponentError(
              error,
              "variant_profile_load_failed",
              "Variant Profile '" + String(id) + "' konnte nicht geladen werden.",
              {
                profileId: id,
                local_error: local.error || null
              }
            );
          }

          return failed;
        });
    } catch (error) {
      return settleFailure("profile", error, {
        source: "client",
        profile_id: id,
        variant_profile_id: id,
        variantProfileId: id
      }, config);
    }
  }

  function getEmptyVariantValues(profileId, context, options) {
    var id = profileKey(profileId);
    var ctx = normalizeContext(context || getCurrentContext());
    var config = options || {};
    var key = id + "|" + contextKey(ctx, "empty");

    try {
      if (!id) {
        return settleFailure(
          "empty_values",
          createComponentError(
            "missing_profile_id",
            "Keine Variant Profile ID für Empty Values angegeben."
          ),
          {
            source: "client",
            profile_id: "",
            variant_profile_id: "",
            values: {},
            context: ctx
          },
          config
        );
      }

      if (
        runtime.cache.emptyValues[key] &&
        runtime.cache.emptyValues[key].ok === true &&
        config.force !== true &&
        config.forceReload !== true
      ) {
        return Promise.resolve(runtime.cache.emptyValues[key]);
      }

      var localFirst = getEmptyValuesLocal(id, ctx);

      if ((config.localOnly === true || shouldPreferLocal(config) || !canFetch()) && localFirst.ok) {
        runtime.cache.emptyValues[key] = localFirst;
        dispatchEmptyValuesReady(localFirst);
        return Promise.resolve(localFirst);
      }

      if (config.localOnly === true || !canFetch()) {
        if (localFirst.ok) {
          runtime.cache.emptyValues[key] = localFirst;
          dispatchEmptyValuesReady(localFirst);
        } else {
          dispatchResolutionFailed("empty_values", localFirst);
        }

        return Promise.resolve(localFirst);
      }

      return getEmptyValuesBackend(id, ctx, config)
        .then(function (result) {
          if (!result || !result.ok) {
            throw ensureComponentError(
              result && result.error ? result.error : result,
              "empty_values_unavailable",
              "Defaultwerte für Variant Profile '" + String(id) + "' konnten nicht geladen werden.",
              {
                profileId: id,
                context: ctx
              }
            );
          }

          runtime.cache.emptyValues[key] = result;
          dispatchEmptyValuesReady(result);
          return result;
        })
        .catch(function (error) {
          var local = localFirst.ok ? U().deepClone(localFirst, localFirst) : getEmptyValuesLocal(id, ctx);

          if (local.ok) {
            local.backend_error = normalizeError(error);
            local.source = local.source || "local_fallback";
            runtime.cache.emptyValues[key] = local;
            dispatchEmptyValuesReady(local);
            return local;
          }

          var failed = buildFailureResult("empty_values", error, {
            source: "backend_then_local_failed",
            profile_id: id,
            variant_profile_id: id,
            variantProfileId: id,
            values: {},
            local_error: local.error || null,
            context: ctx
          });

          dispatchResolutionFailed("empty_values", failed);

          if (shouldReject(config)) {
            throw ensureComponentError(
              error,
              "empty_values_load_failed",
              "Defaultwerte für Variant Profile '" + String(id) + "' konnten nicht geladen werden.",
              {
                profileId: id,
                context: ctx,
                local_error: local.error || null
              }
            );
          }

          return failed;
        });
    } catch (error) {
      return settleFailure("empty_values", error, {
        source: "client",
        profile_id: id,
        variant_profile_id: id,
        variantProfileId: id,
        values: {},
        context: ctx
      }, config);
    }
  }

  function resolveCurrentProfile(options) {
    var config = options || {};
    var context = normalizeContext(config.context || getCurrentContext(config));
    var key = contextKey(context, "resolve_current");

    try {
      if (
        runtime.activeResolvePromise &&
        runtime.activeResolveKey === key &&
        config.force !== true &&
        config.forceReload !== true
      ) {
        runtime.suppressedResolveCount += 1;
        return runtime.activeResolvePromise;
      }

      if (
        runtime.lastResolved &&
        runtime.lastResolved.ok === true &&
        runtime.lastContextKey === key &&
        config.force !== true &&
        config.forceReload !== true
      ) {
        return Promise.resolve(runtime.lastResolved);
      }

      runtime.resolveGeneration += 1;
      var generation = runtime.resolveGeneration;
      runtime.resolveInProgress = true;
      runtime.lastContextKey = key;
      runtime.activeResolveKey = key;

      var chain = fetchDefinitions(config)
        .catch(function (definitionsError) {
          var localDefinitions = getDefinitionsSync();

          if (hasDefinitionData(localDefinitions)) {
            return localDefinitions;
          }

          throw ensureComponentError(
            definitionsError,
            "definitions_not_loaded",
            "Definitionsdaten konnten weder vom Backend noch lokal geladen werden.",
            {
              context: context
            }
          );
        })
        .then(function () {
          return resolveFamilyProfile(context, U().safeMerge(config, {
            rejectOnError: false
          }));
        })
        .then(function (familyResult) {
          if (!familyResult || !familyResult.ok) {
            throw ensureComponentError(
              familyResult && familyResult.error ? familyResult.error : familyResult,
              "family_profile_resolution_failed",
              "Family Profile konnte nicht aufgelöst werden.",
              {
                context: context,
                result: familyResult
              }
            );
          }

          var nextContext = normalizeContext(U().safeMerge(context, {
            family_profile_id: familyResult.family_profile_id || context.family_profile_id,
            familyProfileId: familyResult.family_profile_id || context.family_profile_id
          }));

          return resolveVariantProfile(nextContext, U().safeMerge(config, {
            rejectOnError: false
          })).then(function (variantResult) {
            return {
              familyResult: familyResult,
              variantResult: variantResult,
              context: nextContext
            };
          });
        })
        .then(function (resolution) {
          var variantResult = resolution.variantResult;

          if (!variantResult || !variantResult.ok || !variantResult.variant_profile_id) {
            throw ensureComponentError(
              variantResult && variantResult.error ? variantResult.error : variantResult,
              "variant_profile_resolution_failed",
              "Variant Profile konnte nicht aufgelöst werden.",
              {
                context: resolution.context,
                result: variantResult
              }
            );
          }

          return getVariantProfile(
            variantResult.variant_profile_id,
            U().safeMerge(config, {
              rejectOnError: false
            })
          ).then(function (profileResult) {
            return {
              familyResult: resolution.familyResult,
              variantResult: variantResult,
              profileResult: profileResult,
              context: resolution.context
            };
          });
        })
        .then(function (resolution) {
          var profileResult = resolution.profileResult;

          if (!profileResult || !profileResult.ok || !profileResult.variant_profile) {
            throw ensureComponentError(
              profileResult && profileResult.error ? profileResult.error : profileResult,
              "variant_profile_load_failed",
              "Das aufgelöste Variant Profile konnte nicht geladen werden.",
              {
                context: resolution.context,
                result: profileResult
              }
            );
          }

          var familyResult = resolution.familyResult;
          var variantResult = resolution.variantResult;
          var resolvedContext = normalizeContext(U().safeMerge(
            resolution.context,
            {
              family_profile_id: variantResult.family_profile_id ||
                familyResult.family_profile_id ||
                resolution.context.family_profile_id,
              variant_profile_id: profileResult.variant_profile_id ||
                variantResult.variant_profile_id
            }
          ));

          var result = U().safeMerge(variantResult, {
            ok: true,
            ready: true,
            healthy: true,
            status: "resolved",
            family_profile_id: resolvedContext.family_profile_id,
            familyProfileId: resolvedContext.family_profile_id,
            family_profile: variantResult.family_profile ||
              familyResult.family_profile ||
              null,
            familyProfile: variantResult.family_profile ||
              familyResult.family_profile ||
              null,
            variant_profile_id: profileResult.variant_profile_id,
            variantProfileId: profileResult.variant_profile_id,
            profile_payload: profileResult,
            profilePayload: profileResult,
            variant_profile: profileResult.variant_profile,
            variantProfile: profileResult.variant_profile,
            profile: profileResult.variant_profile,
            context: resolvedContext
          });

          if (generation === runtime.resolveGeneration) {
            runtime.lastResolved = result;
            runtime.lastResolvedSignature = resolvedSignature(result);
            runtime.lastProfilePayload = profileResult;
            runtime.lastContext = resolvedContext;
            runtime.lastError = null;

            applyResolvedProfile(result, {
              source: config.source || result.source || "resolve_current",
              force: config.force === true,
              emitNativeEvents: config.emitNativeEvents === true
            });
            dispatchVariantResolved(result);
          }

          return result;
        })
        .catch(function (error) {
          var failed = buildFailureResult("current", error, {
            source: config.source || "resolve_current",
            context: context
          });

          runtime.lastError = failed.error;
          dispatchResolutionFailed("current", failed);

          if (shouldReject(config)) {
            throw ensureComponentError(
              error,
              "current_profile_resolution_failed",
              "Aktuelles Variant Profile konnte nicht vollständig aufgelöst werden.",
              {
                context: context
              }
            );
          }

          return failed;
        });

      runtime.activeResolvePromise = chain.then(function (result) {
        if (generation === runtime.resolveGeneration) {
          runtime.resolveInProgress = false;
          runtime.activeResolvePromise = null;
          runtime.activeResolveKey = "";
        }

        return result;
      }, function (error) {
        if (generation === runtime.resolveGeneration) {
          runtime.resolveInProgress = false;
          runtime.activeResolvePromise = null;
          runtime.activeResolveKey = "";
        }

        throw ensureComponentError(
          error,
          "current_profile_resolution_failed",
          "Aktuelles Variant Profile konnte nicht vollständig aufgelöst werden.",
          {
            context: context
          }
        );
      });

      return runtime.activeResolvePromise;
    } catch (error) {
      runtime.resolveInProgress = false;
      runtime.activeResolvePromise = null;
      runtime.activeResolveKey = "";

      return settleFailure("current", error, {
        source: config.source || "resolve_current",
        context: context
      }, config);
    }
  }

  function getResolvedProfileBundle(context, options) {
    var config = options || {};
    var ctx = normalizeContext(context || getCurrentContext(config));

    try {
      return resolveCurrentProfile(U().safeMerge(config, {
        context: ctx,
        rejectOnError: false
      })).then(function (resolved) {
        if (!resolved || !resolved.ok) {
          return resolved || buildFailureResult(
            "bundle",
            createComponentError(
              "profile_bundle_resolution_failed",
              "Variant-Profile-Bundle konnte nicht aufgelöst werden."
            ),
            {
              context: ctx
            }
          );
        }

        return getEmptyVariantValues(
          resolved.variant_profile_id,
          resolved.context || ctx,
          U().safeMerge(config, {
            rejectOnError: false
          })
        ).then(function (emptyValues) {
          if (!emptyValues || !emptyValues.ok) {
            return buildFailureResult(
              "bundle",
              emptyValues && emptyValues.error ? emptyValues.error : emptyValues,
              {
                source: "profile_resolved_empty_values_failed",
                context: resolved.context || ctx,
                family_profile_id: resolved.family_profile_id,
                variant_profile_id: resolved.variant_profile_id,
                profile: resolved.variant_profile || resolved.profile || null,
                empty_values_payload: emptyValues || null
              }
            );
          }

          var bundle = U().safeMerge(resolved, {
            ok: true,
            ready: true,
            healthy: true,
            status: "ready",
            empty_values: emptyValues.values || {},
            emptyValues: emptyValues.values || {},
            empty_values_payload: emptyValues,
            emptyValuesPayload: emptyValues
          });

          runtime.lastBundle = bundle;
          runtime.lastBundleSignature = resolvedSignature(bundle) + "::" +
            U().safeJsonStringify(emptyValues.values || {}, "{}");

          return bundle;
        });
      }).catch(function (error) {
        return buildFailureResult("bundle", error, {
          source: config.source || "get_resolved_profile_bundle",
          context: ctx
        });
      });
    } catch (error) {
      return settleFailure("bundle", error, {
        source: config.source || "get_resolved_profile_bundle",
        context: ctx
      }, config);
    }
  }

  function profileDefaults(profile, emptyValues) {
    try {
      var item = profile || {};
      var values = {};

      [
        item.default_values,
        item.defaultValues,
        emptyValues
      ].forEach(function (source) {
        if (!source || typeof source !== "object" || Array.isArray(source)) {
          return;
        }

        Object.keys(source).forEach(function (key) {
          values[key] = U().deepClone(source[key], source[key]);
        });
      });

      return values;
    } catch (error) {
      return {};
    }
  }

  function validateCreatorProfileBundle(bundle, options) {
    try {
      var config = options || {};
      var result = bundle || {};
      var profile = result.variant_profile || result.variantProfile || result.profile || {};
      var context = normalizeContext(result.context || config.context || {});
      var familyProfileId = profileKey(
        result.family_profile_id ||
        result.familyProfileId ||
        context.family_profile_id ||
        config.familyProfileId ||
        ""
      );
      var variantProfileId = profileKey(
        result.variant_profile_id ||
        result.variantProfileId ||
        profile.id ||
        context.variant_profile_id ||
        config.variantProfileId ||
        ""
      );
      var objectKind = U().normalizeObjectKind(
        context.object_kind ||
        config.objectKind ||
        DEFAULT_STARTER_OBJECT_KIND
      );
      var defaults = profileDefaults(
        profile,
        result.empty_values || result.emptyValues || {}
      );
      var requiredFields = U().toArray(
        profile.required_fields ||
        profile.requiredFields ||
        []
      ).map(function (key) {
        return String(key || "").trim();
      }).filter(Boolean);
      var errors = [];
      var warnings = [];

      if (!result.ok) {
        errors.push({
          code: "bundle_not_ok",
          message: "Das Variant-Profile-Bundle ist nicht erfolgreich aufgelöst.",
          error: result.error || null
        });
      }

      if (!variantProfileId) {
        errors.push({
          code: "variant_profile_id_missing",
          message: "Die Variant Profile ID fehlt."
        });
      }

      if (!profile || typeof profile !== "object" || Array.isArray(profile) || !Object.keys(profile).length) {
        errors.push({
          code: "variant_profile_payload_missing",
          message: "Der Variant-Profile-Payload fehlt."
        });
      }

      requiredFields.forEach(function (fieldKey) {
        if (!Object.prototype.hasOwnProperty.call(defaults, fieldKey)) {
          warnings.push({
            code: "required_default_missing",
            field: fieldKey,
            message: "Für das Pflichtfeld '" + fieldKey + "' ist kein Defaultwert vorhanden."
          });
        }
      });

      var starterRequested = objectKind === DEFAULT_STARTER_OBJECT_KIND &&
        (!familyProfileId || familyProfileId === DEFAULT_STARTER_FAMILY_PROFILE_ID) &&
        (!variantProfileId || variantProfileId === DEFAULT_STARTER_VARIANT_PROFILE_ID);

      if (starterRequested) {
        if (familyProfileId !== DEFAULT_STARTER_FAMILY_PROFILE_ID) {
          errors.push({
            code: "starter_family_profile_mismatch",
            expected: DEFAULT_STARTER_FAMILY_PROFILE_ID,
            actual: familyProfileId,
            message: "Für den Starter-Block wurde ein unerwartetes Family Profile aufgelöst."
          });
        }

        if (variantProfileId !== DEFAULT_STARTER_VARIANT_PROFILE_ID) {
          errors.push({
            code: "starter_variant_profile_mismatch",
            expected: DEFAULT_STARTER_VARIANT_PROFILE_ID,
            actual: variantProfileId,
            message: "Für den Starter-Block wurde ein unerwartetes Variant Profile aufgelöst."
          });
        }

        REQUIRED_STARTER_DEFAULT_KEYS.forEach(function (fieldKey) {
          if (!Object.prototype.hasOwnProperty.call(defaults, fieldKey)) {
            errors.push({
              code: "starter_default_missing",
              field: fieldKey,
              message: "Der Starter-Defaultwert '" + fieldKey + "' fehlt."
            });
          }
        });

        [
          "dimensions.width_mm",
          "dimensions.height_mm",
          "dimensions.depth_mm"
        ].forEach(function (fieldKey) {
          var value = Number(defaults[fieldKey]);

          if (!Number.isFinite(value) || value <= 0) {
            errors.push({
              code: "starter_dimension_invalid",
              field: fieldKey,
              value: defaults[fieldKey],
              message: "Die Starter-Abmessung '" + fieldKey + "' muss größer als 0 sein."
            });
          }
        });
      }

      var ready = errors.length === 0;

      return {
        ok: ready,
        ready: ready,
        healthy: ready,
        status: ready ? "ready" : "blocked",
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        object_kind: objectKind,
        family_profile_id: familyProfileId,
        variant_profile_id: variantProfileId,
        starter_requested: starterRequested,
        starter_compatible: starterRequested && ready,
        profile: profile,
        defaults: defaults,
        required_fields: requiredFields,
        errors: errors,
        warnings: warnings,
        bundle: result
      };
    } catch (error) {
      return buildFailureResult("readiness_validation", error, {
        source: "validate_creator_profile_bundle",
        bundle: bundle || null
      });
    }
  }

  function buildStarterContext(context, options) {
    try {
      var config = options || {};
      var current = normalizeContext(context || getCurrentContext(config));
      var objectKind = U().normalizeObjectKind(
        current.object_kind ||
        config.objectKind ||
        runtime.options.starterObjectKind ||
        DEFAULT_STARTER_OBJECT_KIND
      );
      var useStarterDefaults = objectKind === DEFAULT_STARTER_OBJECT_KIND;
      var familyProfileId = current.family_profile_id ||
        config.familyProfileId ||
        (useStarterDefaults
          ? runtime.options.starterFamilyProfileId || DEFAULT_STARTER_FAMILY_PROFILE_ID
          : "");
      var variantProfileId = current.variant_profile_id ||
        config.variantProfileId ||
        (useStarterDefaults
          ? runtime.options.starterVariantProfileId || DEFAULT_STARTER_VARIANT_PROFILE_ID
          : "");

      return normalizeContext(U().safeMerge(current, {
        object_kind: objectKind,
        objectKind: objectKind,
        family_profile_id: familyProfileId,
        familyProfileId: familyProfileId,
        variant_profile_id: variantProfileId,
        variantProfileId: variantProfileId
      }));
    } catch (error) {
      return normalizeContext({
        object_kind: DEFAULT_STARTER_OBJECT_KIND,
        family_profile_id: DEFAULT_STARTER_FAMILY_PROFILE_ID,
        variant_profile_id: DEFAULT_STARTER_VARIANT_PROFILE_ID
      });
    }
  }

  function runReadinessCheck(options) {
    var config = options || {};

    try {
      if (
        runtime.readinessPromise &&
        config.force !== true &&
        config.forceReload !== true
      ) {
        return runtime.readinessPromise;
      }

      if (
        runtime.operational &&
        runtime.readinessResult &&
        config.force !== true &&
        config.forceReload !== true
      ) {
        return Promise.resolve(runtime.readinessResult);
      }

      runtime.readinessGeneration += 1;
      var generation = runtime.readinessGeneration;
      var context = buildStarterContext(config.context, config);

      setRuntimeStatus("loading", null, {
        context: context,
        generation: generation
      });

      var readinessPromise = fetchDefinitions(U().safeMerge(config, {
        rejectOnError: true
      }))
        .then(function () {
          return getResolvedProfileBundle(context, U().safeMerge(config, {
            context: context,
            preferLocal: config.preferLocal === true,
            rejectOnError: false
          }));
        })
        .then(function (bundle) {
          var readiness = validateCreatorProfileBundle(bundle, {
            context: context,
            familyProfileId: context.family_profile_id,
            variantProfileId: context.variant_profile_id,
            objectKind: context.object_kind
          });

          if (generation !== runtime.readinessGeneration) {
            return runtime.readinessResult || readiness;
          }

          runtime.readinessResult = readiness;

          if (readiness.ready) {
            setRuntimeStatus("ready", null, readiness);

            U().dispatchDocument("vectoplan:create:variant-profiles-ready", {
              component: COMPONENT_NAME,
              version: COMPONENT_VERSION,
              ready: true,
              operational: true,
              status: "ready",
              readiness: readiness,
              bundle: readiness.bundle,
              definitions: getDefinitionsSync(),
              cache: getCacheSnapshot(),
              endpoints: getEndpoints(),
              generatorContext: getGeneratorContext(),
              payloadContract: getPayloadContract(),
              __vp_variant_profiles_event: true
            }, {
              silent: true
            });
          } else {
            var readinessError = createComponentError(
              "creator_profile_not_ready",
              "Das Variant Profile für den Creator ist noch nicht vollständig bereit.",
              {
                readiness: readiness,
                context: context
              }
            );

            setRuntimeStatus("blocked", readinessError, readiness);
            dispatchResolutionFailed("readiness", buildFailureResult(
              "readiness",
              readinessError,
              {
                source: "readiness_check",
                context: context,
                readiness: readiness
              }
            ));
          }

          return readiness;
        })
        .catch(function (error) {
          var failed = buildFailureResult("readiness", error, {
            source: "readiness_check",
            context: context
          });

          if (generation === runtime.readinessGeneration) {
            runtime.readinessResult = failed;
            setRuntimeStatus("unavailable", error, failed);
            dispatchResolutionFailed("readiness", failed);
          }

          if (shouldReject(config)) {
            throw ensureComponentError(
              error,
              "creator_readiness_failed",
              "Die Variant-Profile-Bereitschaft konnte nicht hergestellt werden.",
              {
                context: context
              }
            );
          }

          return failed;
        });

      runtime.readinessPromise = readinessPromise.then(function (result) {
        if (generation === runtime.readinessGeneration) {
          runtime.readinessPromise = null;
        }

        return result;
      }, function (error) {
        if (generation === runtime.readinessGeneration) {
          runtime.readinessPromise = null;
        }

        throw ensureComponentError(
          error,
          "creator_readiness_failed",
          "Die Variant-Profile-Bereitschaft konnte nicht hergestellt werden."
        );
      });

      return runtime.readinessPromise;
    } catch (error) {
      setRuntimeStatus("unavailable", error, null);
      return settleFailure("readiness", error, {
        source: "readiness_check",
        context: buildStarterContext(config.context, config)
      }, config);
    }
  }

  function whenReady(options) {
    try {
      if (runtime.operational && runtime.readinessResult) {
        return Promise.resolve(runtime.readinessResult);
      }

      return runReadinessCheck(options || {});
    } catch (error) {
      return settleFailure("readiness", error, {
        source: "when_ready"
      }, options || {});
    }
  }

  function ensureProfileReady(profileId, context, options) {
    try {
      var config = options || {};
      var id = profileKey(
        profileId ||
        config.variantProfileId ||
        runtime.options.starterVariantProfileId ||
        DEFAULT_STARTER_VARIANT_PROFILE_ID
      );
      var ctx = buildStarterContext(context, U().safeMerge(config, {
        variantProfileId: id
      }));

      ctx.variant_profile_id = id;
      ctx.variantProfileId = id;

      return getResolvedProfileBundle(ctx, U().safeMerge(config, {
        context: ctx,
        rejectOnError: false
      })).then(function (bundle) {
        var readiness = validateCreatorProfileBundle(bundle, {
          context: ctx,
          familyProfileId: ctx.family_profile_id,
          variantProfileId: id,
          objectKind: ctx.object_kind
        });

        if (!readiness.ready) {
          dispatchResolutionFailed("profile_readiness", readiness);
        }

        return readiness;
      }).catch(function (error) {
        return buildFailureResult("profile_readiness", error, {
          source: "ensure_profile_ready",
          context: ctx,
          variant_profile_id: id
        });
      });
    } catch (error) {
      return settleFailure("profile_readiness", error, {
        source: "ensure_profile_ready",
        context: normalizeContext(context || {}),
        variant_profile_id: profileKey(profileId)
      }, options || {});
    }
  }

  function isOperational() {
    return runtime.operational === true;
  }

  function getReadiness() {
    try {
      return runtime.readinessResult || {
        ok: runtime.operational,
        ready: runtime.operational,
        healthy: runtime.operational,
        status: runtime.status,
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        error: runtime.lastError
      };
    } catch (error) {
      return {
        ok: false,
        ready: false,
        healthy: false,
        status: "error",
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        error: normalizeError(error)
      };
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

  function handleOwnedUnhandledRejection(event) {
    try {
      var reason = event && event.reason ? event.reason : null;
      var owned = !!(
        reason &&
        (
          reason.__vp_variant_profiles_error === true ||
          reason.component === COMPONENT_NAME ||
          reason.name === "VectoplanCreateVariantProfilesError"
        )
      );

      if (!owned) {
        return;
      }

      var normalized = normalizeError(reason);
      runtime.lastError = normalized;

      warn("Unhandled Variant-Profile-Promise wurde kontrolliert abgefangen.", reason);

      dispatchResolutionFailed("unhandled_promise", {
        ok: false,
        source: "window_unhandledrejection",
        error: normalized,
        context: getCurrentContext(),
        raw: reason
      });

      if (event && typeof event.preventDefault === "function") {
        event.preventDefault();
      }
    } catch (error) {
      warn("Unhandled-Rejection-Handler ist fehlgeschlagen.", error);
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
        runReadinessCheck({
          force: true,
          source: "context_ready",
          rejectOnError: false
        }).catch(function (error) {
          warn("Readiness-Prüfung nach Context-Ready ist fehlgeschlagen.", error);
        });
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
            getVariantProfile(
              payload.variantProfileId || payload.variant_profile_id,
              {
                source: "drawer_opened",
                rejectOnError: false
              }
            ).catch(function (error) {
              warn("Drawer Variant Profile konnte nicht geladen werden.", error);
            });
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
              source: "retry_requested",
              rejectOnError: false
            });
          }).then(function () {
            return runReadinessCheck({
              force: true,
              context: detail.context || getCurrentContext(),
              source: "retry_requested",
              rejectOnError: false
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

      if (window && typeof window.addEventListener === "function") {
        window.addEventListener("unhandledrejection", handleOwnedUnhandledRejection);
      }

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
      var definitionSourceSignature = runtime.cache.definitionSourceSignature;
      var endpoints = runtime.cache.endpoints;
      var endpointContextSignatureValue = runtime.cache.endpointContextSignature;

      runtime.cache = {
        definitions: config.keepDefinitions === true ? definitions : null,
        definitionMaps: config.keepDefinitions === true ? maps : null,
        definitionSourceSignature: config.keepDefinitions === true ? definitionSourceSignature : "",
        endpoints: config.keepEndpoints === true ? endpoints : null,
        endpointContextSignature: config.keepEndpoints === true ? endpointContextSignatureValue : "",
        familyResolve: {},
        variantResolve: {},
        variantProfiles: {},
        emptyValues: {},
        requests: {},
        requestMeta: {}
      };

      if (config.keepDiagnostics !== true) {
        runtime.diagnostics.definitionConflicts = [];
        runtime.diagnostics.definitionConflictKeys = {};
        runtime.diagnostics.invalidEndpointCandidates = [];
        runtime.diagnostics.invalidEndpointKeys = {};
      }

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
      runtime.resolveInProgress = false;
      runtime.readinessPromise = null;
      runtime.readinessResult = null;
      runtime.operational = false;
      runtime.lastError = null;

      if (runtime.initialized) {
        setRuntimeStatus("initialized", null, {
          cacheCleared: true
        });
      }

      U().dispatchDocument("vectoplan:create:variant-profile-cache-cleared", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        keepDefinitions: !!config.keepDefinitions,
        keepEndpoints: !!config.keepEndpoints,
        keepDiagnostics: !!config.keepDiagnostics,
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

  function getDiagnostics() {
    try {
      return {
        definitionConflicts: U().deepClone(runtime.diagnostics.definitionConflicts, []),
        invalidEndpointCandidates: U().deepClone(runtime.diagnostics.invalidEndpointCandidates, []),
        lastEndpointRefreshAt: runtime.diagnostics.lastEndpointRefreshAt || 0,
        lastDefinitionsBuildAt: runtime.diagnostics.lastDefinitionsBuildAt || 0,
        definitionSourceSignature: runtime.cache.definitionSourceSignature || "",
        endpointContextSignature: runtime.cache.endpointContextSignature || ""
      };
    } catch (error) {
      return {
        definitionConflicts: [],
        invalidEndpointCandidates: [],
        lastEndpointRefreshAt: 0,
        lastDefinitionsBuildAt: 0,
        definitionSourceSignature: "",
        endpointContextSignature: ""
      };
    }
  }

  function getCacheSnapshot() {
    try {
      return {
        definitionsLoaded: !!runtime.cache.definitions,
        definitionSourceSignature: runtime.cache.definitionSourceSignature || "",
        endpointContextSignature: runtime.cache.endpointContextSignature || "",
        diagnostics: {
          definitionConflictCount: runtime.diagnostics.definitionConflicts.length,
          invalidEndpointCandidateCount: runtime.diagnostics.invalidEndpointCandidates.length,
          lastEndpointRefreshAt: runtime.diagnostics.lastEndpointRefreshAt || 0,
          lastDefinitionsBuildAt: runtime.diagnostics.lastDefinitionsBuildAt || 0
        },
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
          requests: Object.keys(runtime.cache.requests || {}).length,
          requestMeta: Object.keys(runtime.cache.requestMeta || {}).length
        },
        status: runtime.status,
        operational: runtime.operational,
        ready: runtime.operational,
        lastError: runtime.lastError,
        readiness: runtime.readinessResult,
        readinessInProgress: !!runtime.readinessPromise,
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
      operational: runtime.operational,
      ready: runtime.operational,
      status: runtime.status,
      lastError: runtime.lastError,
      readiness: getReadiness(),
      cache: getCacheSnapshot(),
      endpoints: getEndpoints(),
      context: getCurrentContext(),
      generatorContext: getGeneratorContext(),
      payloadContract: getPayloadContract(),
      options: U().deepClone(runtime.options, {})
    };
  }

  function initialize(options) {
    var config = options || {};

    try {
      if (runtime.initialized && config.force !== true && config.reinitialize !== true) {
        if (!runtime.operational && !runtime.readinessPromise) {
          runReadinessCheck({
            source: config.source || "initialize_existing",
            rejectOnError: false
          }).catch(function (error) {
            warn("Readiness-Prüfung der bestehenden Runtime ist fehlgeschlagen.", error);
          });
        }

        return true;
      }

      runtime.options = U().safeMerge(runtime.options, config || {});

      getDefinitionsSync({
        force: !!config.force
      });

      bindGlobalEvents();

      runtime.initialized = true;
      setRuntimeStatus("initialized", null, {
        source: config.source || "initialize"
      });

      document.documentElement.setAttribute(INITIALIZED_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-profiles-version", COMPONENT_VERSION);

      U().dispatchDocument("vectoplan:create:variant-profiles-initialized", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        initialized: true,
        ready: false,
        operational: false,
        status: runtime.status,
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
      } else {
        U().dispatchDocument("vectoplan:create:definitions-loading", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          status: "loading",
          __vp_variant_profiles_event: true
        }, {
          silent: true
        });
      }

      runReadinessCheck({
        force: !!config.force,
        source: config.source || "initialize_readiness",
        context: config.context || null,
        preferLocal: config.preferLocal === true,
        rejectOnError: false
      }).then(function (readiness) {
        if (
          readiness &&
          readiness.ready &&
          config.autoResolve !== false &&
          runtime.options.autoResolve !== false
        ) {
          scheduleResolve("profiles_ready", 40);
        }

        return readiness;
      }).catch(function (error) {
        warn("Initiale Variant-Profile-Bereitschaft ist fehlgeschlagen.", error);
      });

      return true;
    } catch (error) {
      runtime.initialized = false;
      setRuntimeStatus("unavailable", error, {
        source: config.source || "initialize"
      });

      warn("Could not initialize variant profiles.", error);

      U().dispatchDocument("vectoplan:create:variant-profiles-initialization-failed", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        initialized: false,
        ready: false,
        operational: false,
        status: "unavailable",
        error: normalizeError(error),
        __vp_variant_profiles_event: true
      }, {
        silent: true
      });

      return false;
    }
  }

  var api = {
    __name: COMPONENT_NAME,
    __version: COMPONENT_VERSION,
    version: COMPONENT_VERSION,

    initialize: initialize,
    getState: getState,
    isOperational: isOperational,
    getReadiness: getReadiness,
    whenReady: whenReady,
    waitUntilReady: whenReady,
    runReadinessCheck: runReadinessCheck,
    ensureProfileReady: ensureProfileReady,
    validateCreatorProfileBundle: validateCreatorProfileBundle,

    getEndpoints: getEndpoints,
    getDefinitionsSync: getDefinitionsSync,
    fetchDefinitions: fetchDefinitionsPublic,
    fetchDefinitionsSafe: fetchDefinitionsPublic,
    fetchDefinitionsStrict: fetchDefinitions,
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
    getDiagnostics: getDiagnostics,

    scheduleResolve: scheduleResolve,

    normalizeError: normalizeError,
    createError: createComponentError,
    ensureError: ensureComponentError,
    buildFailureResult: buildFailureResult
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