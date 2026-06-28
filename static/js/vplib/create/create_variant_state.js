/* services/vectoplan-library/static/js/vplib/create/create_variant_state.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateVariantState";
  var COMPONENT_NAME = "VECTOPLAN Create Variant State";
  var COMPONENT_VERSION = "0.7.0";
  var READY_ATTR = "data-vp-create-variant-state-ready";

  var WORKSPACE_SELECTOR = "[data-vp-variant-workspace-root='true'], [data-vp-variant-workspace='true']";
  var TABLE_SELECTOR = "[data-vp-variant-table-root='true'], [data-vp-variant-table='true'], [data-create-variant-table='true']";
  var ROW_SELECTOR = "[data-vp-variant-row='true'], [data-create-variant-row='true']";
  var JSON_FIELD_SELECTOR = "[data-vp-definition-variants-json='true'], [name='definition_variants_json']";
  var DEFAULT_ID_FIELD_SELECTOR = "[data-vp-definition-variants-default-id='true'], [name='default_variant_id'], [name='definition_variants_default_variant_id']";
  var COUNT_LABEL_SELECTOR = "[data-vp-variant-count-label='true'], [data-vp-variant-count-label]";

  if (window[GLOBAL_NAME] && window[GLOBAL_NAME].__version === COMPONENT_VERSION) {
    try {
      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-state-version", COMPONENT_VERSION);
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

        var next = value === null || value === undefined ? null : String(value);

        if (next === null) {
          if (node.hasAttribute(name)) {
            node.removeAttribute(name);
            return true;
          }

          return false;
        }

        if (node.getAttribute(name) === next) {
          return false;
        }

        node.setAttribute(name, next);
        return true;
      } catch (error) {
        return false;
      }
    },

    bool: function (value, fallback) {
      try {
        if (typeof value === "boolean") {
          return value;
        }

        var text = String(value === null || value === undefined ? "" : value).trim().toLowerCase();

        if (["true", "1", "yes", "ja", "on", "ok", "enabled", "active", "default", "selected"].indexOf(text) !== -1) {
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

    intValue: function (value, fallback) {
      try {
        var parsed = parseInt(value, 10);
        return isNaN(parsed) ? (fallback || 0) : parsed;
      } catch (error) {
        return fallback || 0;
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
        if (!node || !eventName) {
          return false;
        }

        var source = options && options.source ? options.source : COMPONENT_NAME;

        if (node.setAttribute) {
          node.setAttribute("data-vp-programmatic-event", String(eventName));
          node.setAttribute("data-vp-programmatic-event-source", String(source));
          node.__vpProgrammaticEvent = {
            eventName: String(eventName),
            source: String(source),
            timestamp: Date.now()
          };
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

            if (node && node.__vpProgrammaticEvent && node.__vpProgrammaticEvent.eventName === String(eventName)) {
              delete node.__vpProgrammaticEvent;
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
          slug = fallback || "variant";
        }

        if (!/^[a-z]/.test(slug)) {
          slug = "v_" + slug;
        }

        return slug;
      } catch (error) {
        return fallback || "variant";
      }
    },

    ensureUniqueId: function (base, existingIds) {
      try {
        var id = fallbackUtils.slugify(base || "variant", "variant");
        var existing = {};
        var index = 1;

        fallbackUtils.toArray(existingIds).forEach(function (item) {
          existing[String(item)] = true;
        });

        if (!existing[id]) {
          return id;
        }

        while (existing[id + "_" + String(index)]) {
          index += 1;
        }

        return id + "_" + String(index);
      } catch (error) {
        return "variant_" + String(Math.floor(Math.random() * 100000));
      }
    },

    buildVariantId: function (options) {
      try {
        var config = options || {};
        var profile = config.variantProfileId || config.variant_profile_id || config.label || "variant";
        var base = fallbackUtils.slugify(String(profile).replace(/\./g, "_"), "variant");
        var index = config.index || 1;
        return fallbackUtils.ensureUniqueId(base + "_" + String(index), config.existingIds || []);
      } catch (error) {
        return "variant_1";
      }
    },

    valuesFromJson: function (value) {
      var parsed = fallbackUtils.safeJsonParse(value, {});
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    },

    valuesToJson: function (value) {
      return fallbackUtils.safeJsonStringify(value || {}, "{}");
    },

    normalizeAdditionalFieldKeys: function (value) {
      try {
        var raw = value;

        if (typeof raw === "string") {
          var parsed = fallbackUtils.safeJsonParse(raw, null);

          if (Array.isArray(parsed)) {
            raw = parsed;
          } else {
            raw = raw.split(",");
          }
        }

        return fallbackUtils.toArray(raw).map(function (item) {
          return String(item || "").trim();
        }).filter(function (item, index, array) {
          return item && array.indexOf(item) === index;
        });
      } catch (error) {
        return [];
      }
    },

    normalizeVariant: function (raw, options) {
      var variant = raw || {};
      var config = options || {};
      var values = {};

      if (variant.definition_values_json) {
        values = fallbackUtils.valuesFromJson(variant.definition_values_json);
      } else if (variant.definitionValuesJson) {
        values = fallbackUtils.valuesFromJson(variant.definitionValuesJson);
      } else if (variant.values_json) {
        values = fallbackUtils.valuesFromJson(variant.values_json);
      } else if (variant.definition_values && typeof variant.definition_values === "object") {
        values = fallbackUtils.deepClone(variant.definition_values, {});
      } else if (variant.definitionValues && typeof variant.definitionValues === "object") {
        values = fallbackUtils.deepClone(variant.definitionValues, {});
      } else if (variant.values && typeof variant.values === "object") {
        values = fallbackUtils.deepClone(variant.values, {});
      }

      var id = variant.variant_id || variant.variantId || variant.slug || variant.id || values["variant.variant_id"] || "";
      var label = variant.label || variant.name || values["variant.label"] || "";
      var description = variant.description || values["variant.description"] || "";
      var isDefault = fallbackUtils.bool(variant.is_default || variant.isDefault || variant.default, false) || id === "default";

      if (!id) {
        id = isDefault ? "default" : fallbackUtils.buildVariantId({
          label: label,
          variantProfileId: variant.variant_profile_id || variant.variantProfileId || config.variantProfileId || "",
          existingIds: config.existingIds || [],
          index: config.index || 1
        });
      }

      if (!label) {
        label = isDefault ? "Standard" : "Neue Variante";
      }

      values["variant.variant_id"] = id;
      values["variant.label"] = label;

      if (description) {
        values["variant.description"] = description;
      }

      var additionalFieldKeys = fallbackUtils.normalizeAdditionalFieldKeys(
        variant.additional_field_keys ||
        variant.additionalFieldKeys ||
        variant.additional_fields ||
        variant.additionalFields ||
        []
      );

      return {
        variant_id: id,
        variantId: id,
        label: label,
        name: label,
        slug: id,
        kind: variant.kind || variant.variant_kind || variant.type || (isDefault ? "standard" : "profile"),
        description: description,
        is_default: isDefault,
        isDefault: isDefault,
        variant_profile_id: variant.variant_profile_id || variant.variantProfileId || config.variantProfileId || "",
        variantProfileId: variant.variant_profile_id || variant.variantProfileId || config.variantProfileId || "",
        family_profile_id: variant.family_profile_id || variant.familyProfileId || config.familyProfileId || "",
        familyProfileId: variant.family_profile_id || variant.familyProfileId || config.familyProfileId || "",
        definition_managed: fallbackUtils.bool(variant.definition_managed || variant.definitionManaged, !!Object.keys(values).length),
        definitionManaged: fallbackUtils.bool(variant.definition_managed || variant.definitionManaged, !!Object.keys(values).length),
        definition_values: values,
        definitionValues: values,
        definition_values_json: fallbackUtils.valuesToJson(values),
        definitionValuesJson: fallbackUtils.valuesToJson(values),
        additional_field_keys: additionalFieldKeys,
        additionalFieldKeys: additionalFieldKeys.slice(),
        definition_summary: variant.definition_summary || variant.definitionSummary || variant.summary || "",
        definitionSummary: variant.definition_summary || variant.definitionSummary || variant.summary || "",
        validation: variant.validation || null,
        raw: variant
      };
    },

    normalizeVariants: function (rawVariants, options) {
      var existing = [];
      var output = [];

      fallbackUtils.toArray(rawVariants).forEach(function (item, index) {
        var normalized = fallbackUtils.normalizeVariant(item, fallbackUtils.safeMerge(options || {}, {
          index: index + 1,
          existingIds: existing
        }));

        if (index === 0) {
          normalized.variant_id = "default";
          normalized.variantId = "default";
          normalized.slug = "default";
          normalized.is_default = true;
          normalized.isDefault = true;
          normalized.kind = "standard";
          normalized.definition_values["variant.variant_id"] = "default";

          if (!normalized.label || normalized.label === "Neue Variante") {
            normalized.label = "Standard";
            normalized.name = "Standard";
            normalized.definition_values["variant.label"] = "Standard";
          }

          normalized.definition_values_json = fallbackUtils.valuesToJson(normalized.definition_values);
          normalized.definitionValuesJson = normalized.definition_values_json;
        }

        existing.push(normalized.variant_id);
        output.push(normalized);
      });

      if (!output.length) {
        output.push(fallbackUtils.normalizeVariant({
          variant_id: "default",
          label: "Standard",
          is_default: true,
          kind: "standard"
        }, options || {}));
      }

      return output;
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
    subscribers: [],
    cache: null,
    syncInProgress: false,
    notifyInProgress: false,
    suppressedSyncCount: 0,
    suppressedNotifyCount: 0,
    lastPayloadJson: "",
    lastDefaultVariantId: "",
    lastCount: -1,
    lastContextSignature: "",
    lastSyncedRevision: -1,
    lastSyncSignature: "",
    lastSyncSnapshot: null,
    state: createEmptyState()
  };

  function createEmptyState() {
    return {
      component: COMPONENT_NAME,
      version: COMPONENT_VERSION,
      ready: false,
      revision: 0,
      source: "initial",
      created_at: "",
      updated_at: "",
      context: {
        workspace_id: "",
        table_id: "",
        domain: "",
        category: "",
        subcategory: "",
        taxonomy_path: "",
        object_kind: "cell_block",
        family_profile_id: "",
        variant_profile_id: "",
        default_variant_id: "default"
      },
      sync_meta: {
        last_synced_at: "",
        last_payload_json_length: 0,
        suppressed_sync_count: 0,
        suppressed_notify_count: 0
      },
      variants: []
    };
  }

  function getFormRoot(explicitRoot) {
    try {
      if (explicitRoot && explicitRoot.nodeType === 1 && explicitRoot.tagName && explicitRoot.tagName.toLowerCase() === "form") {
        return explicitRoot;
      }

      if (explicitRoot && explicitRoot.closest) {
        var form = explicitRoot.closest("form");

        if (form) {
          return form;
        }
      }

      return U().qs("[data-vp-create-form], [data-create-form='true'], #vp-create-form, form[data-create-form]");
    } catch (error) {
      return null;
    }
  }

  function getWorkspaceRoot(explicitRoot) {
    try {
      if (explicitRoot && explicitRoot.nodeType === 1) {
        if (explicitRoot.matches && explicitRoot.matches(WORKSPACE_SELECTOR)) {
          return explicitRoot;
        }

        var closest = explicitRoot.closest ? explicitRoot.closest(WORKSPACE_SELECTOR) : null;

        if (closest) {
          return closest;
        }

        var nested = U().qs(WORKSPACE_SELECTOR, explicitRoot);

        if (nested) {
          return nested;
        }
      }

      return U().qs(WORKSPACE_SELECTOR);
    } catch (error) {
      return null;
    }
  }

  function getTableRoot(root) {
    try {
      if (root) {
        if (root.matches && root.matches(TABLE_SELECTOR)) {
          return root;
        }

        var table = U().qs(TABLE_SELECTOR, root);

        if (table) {
          return table;
        }
      }

      return U().qs(TABLE_SELECTOR);
    } catch (error) {
      return null;
    }
  }

  function ensureHiddenField(form, name, defaultValue, attrName) {
    try {
      if (!form || !name) {
        return null;
      }

      var field = form.elements ? form.elements[name] : null;

      if (!field || field.nodeType !== 1) {
        field = U().qs("[name='" + cssEscape(name) + "']", form);
      }

      if (!field) {
        field = document.createElement("input");
        field.type = "hidden";
        field.name = name;
        field.value = defaultValue || "";
        field.setAttribute("data-vp-created-by", GLOBAL_NAME);

        if (attrName) {
          field.setAttribute(attrName, "true");
        }

        form.appendChild(field);
      }

      if (field.value === "" && defaultValue !== undefined && defaultValue !== null) {
        field.value = String(defaultValue);
      }

      return field;
    } catch (error) {
      warn("Could not ensure hidden field: " + name, error);
      return null;
    }
  }

  function cacheDom(explicitRoot) {
    try {
      var workspace = getWorkspaceRoot(explicitRoot);
      var table = getTableRoot(workspace || explicitRoot);
      var form = getFormRoot(workspace || table || explicitRoot);
      var rows = table ? U().qsa(ROW_SELECTOR, table).filter(isUsableRow) : [];

      var jsonField = workspace
        ? U().qs(JSON_FIELD_SELECTOR, workspace)
        : null;

      if (!jsonField && form) {
        jsonField = U().qs(JSON_FIELD_SELECTOR, form) ||
          ensureHiddenField(form, "definition_variants_json", "[]", "data-vp-definition-variants-json");
      }

      if (!jsonField) {
        jsonField = U().qs(JSON_FIELD_SELECTOR);
      }

      var defaultIdField = workspace
        ? U().qs(DEFAULT_ID_FIELD_SELECTOR, workspace)
        : null;

      if (!defaultIdField && form) {
        defaultIdField = U().qs(DEFAULT_ID_FIELD_SELECTOR, form) ||
          ensureHiddenField(form, "default_variant_id", "default", "data-vp-definition-variants-default-id");
      }

      if (!defaultIdField) {
        defaultIdField = U().qs(DEFAULT_ID_FIELD_SELECTOR);
      }

      var cache = {
        form: form,
        workspace: workspace,
        table: table,
        tableBody: table ? U().qs("[data-vp-variant-table-body='true'], tbody", table) : null,
        rows: rows,
        jsonField: jsonField,
        defaultIdField: defaultIdField,
        countLabel: workspace
          ? U().qs(COUNT_LABEL_SELECTOR, workspace)
          : U().qs(COUNT_LABEL_SELECTOR)
      };

      runtime.cache = cache;
      return cache;
    } catch (error) {
      warn("Could not cache variant state DOM.", error);

      runtime.cache = {
        form: null,
        workspace: null,
        table: null,
        tableBody: null,
        rows: [],
        jsonField: null,
        defaultIdField: null,
        countLabel: null
      };

      return runtime.cache;
    }
  }

  function isUsableRow(row) {
    try {
      if (!row) {
        return false;
      }

      if (U().attr(row, "data-vp-variant-row-template", "") === "true") {
        return false;
      }

      if (U().attr(row, "data-vp-row-template", "") === "true") {
        return false;
      }

      if (U().attr(row, "data-create-variant-row-template", "") === "true") {
        return false;
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function readContext(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();
      var workspace = c.workspace;
      var table = c.table;
      var form = c.form;
      var domain = U().attr(workspace, "data-vp-current-domain", "") || getFieldByName(form, "domain", "");
      var category = U().attr(workspace, "data-vp-current-category", "") || getFieldByName(form, "category", "");
      var subcategory = U().attr(workspace, "data-vp-current-subcategory", "") || getFieldByName(form, "subcategory", "");

      return {
        workspace_id: U().attr(workspace, "id", ""),
        table_id: U().attr(table, "id", ""),
        domain: domain,
        category: category,
        subcategory: subcategory,
        taxonomy_path: [domain, category, subcategory].filter(Boolean).join("/"),
        object_kind: U().attr(workspace, "data-vp-current-object-kind", "cell_block") || getFieldByName(form, "object_kind", "cell_block") || "cell_block",
        family_profile_id: U().attr(workspace, "data-vp-current-family-profile-id", "") || U().attr(table, "data-vp-family-profile-id", "") || getFieldByName(form, "family_profile_id", ""),
        variant_profile_id: U().attr(workspace, "data-vp-current-variant-profile-id", "") || U().attr(table, "data-vp-variant-profile-id", "") || getFieldByName(form, "variant_profile_id", ""),
        default_variant_id: U().attr(workspace, "data-vp-default-variant-id", "default") || U().attr(table, "data-vp-default-variant-id", "default") || getFieldByName(form, "default_variant_id", "default") || "default"
      };
    } catch (error) {
      warn("Could not read variant context.", error);

      return {
        workspace_id: "",
        table_id: "",
        domain: "",
        category: "",
        subcategory: "",
        taxonomy_path: "",
        object_kind: "cell_block",
        family_profile_id: "",
        variant_profile_id: "",
        default_variant_id: "default"
      };
    }
  }

  function getFieldByName(form, name, fallback) {
    try {
      if (!form || !name) {
        return fallback || "";
      }

      var field = form.elements ? form.elements[name] : null;

      if (!field || field.nodeType !== 1) {
        field = U().qs("[name='" + cssEscape(name) + "']", form);
      }

      if (!field || typeof field.value === "undefined") {
        return fallback || "";
      }

      return field.value || fallback || "";
    } catch (error) {
      return fallback || "";
    }
  }

  function getFieldValue(root, selectors, fallback) {
    try {
      var selectorList = U().toArray(selectors);
      var node = null;

      for (var index = 0; index < selectorList.length; index += 1) {
        node = U().qs(selectorList[index], root);

        if (node) {
          break;
        }
      }

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
  }

  function readRows(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();
      var rows = c.rows && c.rows.length ? c.rows : U().qsa(ROW_SELECTOR, c.table || document).filter(isUsableRow);

      return rows.map(function (row, index) {
        var variantId = U().attr(row, "data-vp-variant-id", "") ||
          U().attr(row, "data-vp-definition-variant-id", "") ||
          getFieldValue(row, [
            "[data-vp-variant-slug]",
            "[data-vp-row-variant-id]",
            "[data-vp-row-variant-slug]",
            "[name$='[variant_id]']",
            "[name$='[slug]']"
          ], "");

        var label = U().attr(row, "data-vp-variant-label", "") ||
          getFieldValue(row, [
            "[data-vp-variant-name]",
            "[data-vp-variant-row-display-name='true']",
            "[data-vp-row-display-name]",
            "[name$='[name]']",
            "[name$='[label]']"
          ], "");

        var profileId = U().attr(row, "data-vp-variant-profile-id", "") ||
          U().attr(row, "data-vp-definition-variant-profile-id", "") ||
          getFieldValue(row, [
            "[data-vp-row-variant-profile-id]",
            "[name$='[variant_profile_id]']"
          ], "");

        var valuesJson = getFieldValue(row, [
          "[data-vp-row-definition-values-json]",
          "[name$='[definition_values_json]']"
        ], "");

        var summary = getFieldValue(row, [
          "[data-vp-row-definition-summary-input]",
          "[data-vp-row-definition-summary='true']",
          "[name$='[definition_summary]']"
        ], "");

        var additionalFieldKeys = getFieldValue(row, [
          "[data-vp-row-additional-field-keys]",
          "[name$='[additional_field_keys]']"
        ], "");

        var isDefault = U().bool(U().attr(row, "data-vp-is-default", ""), false) ||
          getFieldValue(row, [
            "[data-vp-row-is-default]",
            "[name$='[is_default]']"
          ], "") === "true" ||
          index === 0;

        return {
          variant_id: variantId || (index === 0 ? "default" : "variant_" + String(index + 1)),
          variantId: variantId || (index === 0 ? "default" : "variant_" + String(index + 1)),
          label: label || (index === 0 ? "Standard" : "Neue Variante"),
          name: label || (index === 0 ? "Standard" : "Neue Variante"),
          slug: variantId || (index === 0 ? "default" : "variant_" + String(index + 1)),
          kind: getFieldValue(row, [
            "[data-vp-row-variant-kind]",
            "[name$='[kind]']"
          ], index === 0 ? "standard" : "profile"),
          description: getFieldValue(row, [
            "[data-vp-row-variant-description]",
            "[name$='[description]']"
          ], ""),
          is_default: isDefault,
          isDefault: isDefault,
          variant_profile_id: profileId,
          variantProfileId: profileId,
          family_profile_id: U().attr(row, "data-vp-family-profile-id", ""),
          familyProfileId: U().attr(row, "data-vp-family-profile-id", ""),
          definition_values_json: valuesJson,
          definitionValuesJson: valuesJson,
          definition_values: U().valuesFromJson(valuesJson),
          definitionValues: U().valuesFromJson(valuesJson),
          definition_summary: summary || (index === 0 ? "Standardvariante" : ""),
          definitionSummary: summary || (index === 0 ? "Standardvariante" : ""),
          definition_managed: U().bool(U().attr(row, "data-vp-definition-managed", ""), false) ||
            getFieldValue(row, [
              "[data-vp-row-definition-managed]",
              "[name$='[definition_managed]']"
            ], "") === "true",
          additional_field_keys: normalizeAdditionalFieldKeys(additionalFieldKeys),
          additionalFieldKeys: normalizeAdditionalFieldKeys(additionalFieldKeys)
        };
      });
    } catch (error) {
      warn("Could not read variant rows.", error);
      return [];
    }
  }

  function readDefinitionVariantsJson(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();
      var field = c.jsonField;

      if (!field || !field.value) {
        return [];
      }

      var parsed = U().safeJsonParse(field.value, []);

      if (Array.isArray(parsed)) {
        return parsed;
      }

      if (parsed && Array.isArray(parsed.items)) {
        return parsed.items;
      }

      if (parsed && Array.isArray(parsed.variants)) {
        return parsed.variants;
      }

      if (parsed && Array.isArray(parsed.definition_variants)) {
        return parsed.definition_variants;
      }

      if (parsed && Array.isArray(parsed.definitionVariants)) {
        return parsed.definitionVariants;
      }

      return [];
    } catch (error) {
      warn("Could not read definition_variants_json.", error);
      return [];
    }
  }

  function readInitialVariants(cache) {
    try {
      var fromJson = readDefinitionVariantsJson(cache);

      if (fromJson && fromJson.length) {
        return fromJson;
      }

      var fromRows = readRows(cache);

      if (fromRows && fromRows.length) {
        return fromRows;
      }

      return [];
    } catch (error) {
      warn("Could not read initial variants.", error);
      return [];
    }
  }

  function getExistingIds(exceptVariantId) {
    try {
      return runtime.state.variants
        .map(function (variant) {
          return variant.variant_id;
        })
        .filter(function (id) {
          return id && id !== exceptVariantId;
        });
    } catch (error) {
      return [];
    }
  }

  function normalizeAdditionalFieldKeys(value) {
    try {
      if (U().normalizeAdditionalFieldKeys) {
        return U().normalizeAdditionalFieldKeys(value);
      }

      var raw = value;

      if (typeof raw === "string") {
        var parsed = U().safeJsonParse(raw, null);

        if (Array.isArray(parsed)) {
          raw = parsed;
        } else {
          raw = raw.split(",");
        }
      }

      return U().toArray(raw).map(function (item) {
        return String(item || "").trim();
      }).filter(function (item, index, array) {
        return item && array.indexOf(item) === index;
      });
    } catch (error) {
      return [];
    }
  }

  function normalizeVariant(raw, options) {
    try {
      var context = runtime.state.context || {};
      var rawId = raw && (raw.variant_id || raw.variantId || raw.slug || raw.id);
      var config = U().safeMerge({
        familyProfileId: context.family_profile_id,
        family_profile_id: context.family_profile_id,
        variantProfileId: context.variant_profile_id,
        variant_profile_id: context.variant_profile_id,
        existingIds: getExistingIds(rawId),
        index: runtime.state.variants.length + 1
      }, options || {});

      var variant = U().normalizeVariant(raw || {}, config);

      if (!variant.variant_profile_id && context.variant_profile_id) {
        variant.variant_profile_id = context.variant_profile_id;
        variant.variantProfileId = context.variant_profile_id;
      }

      if (!variant.family_profile_id && context.family_profile_id) {
        variant.family_profile_id = context.family_profile_id;
        variant.familyProfileId = context.family_profile_id;
      }

      if (!variant.definition_values || typeof variant.definition_values !== "object") {
        variant.definition_values = U().valuesFromJson(variant.definition_values_json);
      }

      variant.definition_values["variant.variant_id"] = variant.variant_id;
      variant.definition_values["variant.label"] = variant.label;

      if (variant.description) {
        variant.definition_values["variant.description"] = variant.description;
      }

      variant.definitionValues = variant.definition_values;
      variant.additional_field_keys = normalizeAdditionalFieldKeys(
        variant.additional_field_keys ||
        variant.additionalFieldKeys ||
        raw && raw.additional_field_keys ||
        raw && raw.additionalFieldKeys ||
        raw && raw.additional_fields ||
        raw && raw.additionalFields ||
        []
      );
      variant.additionalFieldKeys = variant.additional_field_keys.slice();

      variant.definition_values_json = U().valuesToJson(variant.definition_values);
      variant.definitionValuesJson = variant.definition_values_json;

      return variant;
    } catch (error) {
      warn("Could not normalize variant.", error);

      return U().normalizeVariant({
        variant_id: "variant_1",
        label: "Neue Variante"
      }, options || {});
    }
  }

  function normalizeVariants(rawVariants, context) {
    try {
      var options = {
        familyProfileId: context && context.family_profile_id ? context.family_profile_id : "",
        family_profile_id: context && context.family_profile_id ? context.family_profile_id : "",
        variantProfileId: context && context.variant_profile_id ? context.variant_profile_id : "",
        variant_profile_id: context && context.variant_profile_id ? context.variant_profile_id : ""
      };

      var variants = U().normalizeVariants(rawVariants || [], options);

      return ensureDefaultVariant(variants);
    } catch (error) {
      warn("Could not normalize variants.", error);

      return ensureDefaultVariant([]);
    }
  }

  function ensureDefaultVariant(variants) {
    try {
      var list = U().toArray(variants);
      var output = [];
      var defaultSeen = false;

      if (!list.length) {
        list.push({
          variant_id: "default",
          label: "Standard",
          name: "Standard",
          slug: "default",
          kind: "standard",
          is_default: true,
          isDefault: true,
          definition_values: {
            "variant.variant_id": "default",
            "variant.label": "Standard"
          },
          additional_field_keys: [],
          additionalFieldKeys: [],
          definition_summary: "Standardvariante"
        });
      }

      list.forEach(function (variant, index) {
        var normalized = U().deepClone(variant, {});

        if (index === 0 || normalized.variant_id === "default" || normalized.is_default === true || normalized.isDefault === true) {
          if (!defaultSeen) {
            normalized.variant_id = "default";
            normalized.variantId = "default";
            normalized.slug = "default";
            normalized.is_default = true;
            normalized.isDefault = true;
            normalized.kind = "standard";
            normalized.label = normalized.label || normalized.name || "Standard";
            normalized.name = normalized.label;

            if (!normalized.definition_values || typeof normalized.definition_values !== "object") {
              normalized.definition_values = U().valuesFromJson(normalized.definition_values_json);
            }

            normalized.definition_values["variant.variant_id"] = "default";
            normalized.definition_values["variant.label"] = normalized.label || "Standard";

            defaultSeen = true;
          } else {
            normalized.is_default = false;
            normalized.isDefault = false;

            if (normalized.variant_id === "default") {
              normalized.variant_id = U().ensureUniqueId("variant", output.map(function (item) {
                return item.variant_id;
              }));
              normalized.variantId = normalized.variant_id;
              normalized.slug = normalized.variant_id;
            }
          }
        } else {
          normalized.is_default = false;
          normalized.isDefault = false;
        }

        if (!normalized.variant_id) {
          normalized.variant_id = U().ensureUniqueId("variant_" + String(index + 1), output.map(function (item) {
            return item.variant_id;
          }));
          normalized.variantId = normalized.variant_id;
          normalized.slug = normalized.variant_id;
        }

        if (!normalized.variantId) {
          normalized.variantId = normalized.variant_id;
        }

        if (!normalized.slug) {
          normalized.slug = normalized.variant_id;
        }

        if (!normalized.label) {
          normalized.label = normalized.variant_id === "default" ? "Standard" : "Neue Variante";
        }

        if (!normalized.name) {
          normalized.name = normalized.label;
        }

        if (!normalized.definition_values || typeof normalized.definition_values !== "object") {
          normalized.definition_values = U().valuesFromJson(normalized.definition_values_json);
        }

        normalized.definition_values["variant.variant_id"] = normalized.variant_id;
        normalized.definition_values["variant.label"] = normalized.label;

        if (normalized.description) {
          normalized.definition_values["variant.description"] = normalized.description;
        }

        normalized.definitionValues = normalized.definition_values;
        normalized.additional_field_keys = normalizeAdditionalFieldKeys(
          normalized.additional_field_keys ||
          normalized.additionalFieldKeys ||
          normalized.additional_fields ||
          normalized.additionalFields ||
          []
        );
        normalized.additionalFieldKeys = normalized.additional_field_keys.slice();

        normalized.definition_values_json = U().valuesToJson(normalized.definition_values);
        normalized.definitionValuesJson = normalized.definition_values_json;

        output.push(normalized);
      });

      if (!defaultSeen && output.length) {
        output[0].variant_id = "default";
        output[0].variantId = "default";
        output[0].slug = "default";
        output[0].is_default = true;
        output[0].isDefault = true;
        output[0].kind = "standard";
        output[0].label = output[0].label || "Standard";
        output[0].name = output[0].label;

        if (!output[0].definition_values || typeof output[0].definition_values !== "object") {
          output[0].definition_values = {};
        }

        output[0].definition_values["variant.variant_id"] = "default";
        output[0].definition_values["variant.label"] = output[0].label;
        output[0].definitionValues = output[0].definition_values;
        output[0].additional_field_keys = normalizeAdditionalFieldKeys(output[0].additional_field_keys || output[0].additionalFieldKeys || []);
        output[0].additionalFieldKeys = output[0].additional_field_keys.slice();
        output[0].definition_values_json = U().valuesToJson(output[0].definition_values);
        output[0].definitionValuesJson = output[0].definition_values_json;
      }

      return output;
    } catch (error) {
      warn("Could not ensure default variant.", error);

      return [{
        variant_id: "default",
        variantId: "default",
        label: "Standard",
        name: "Standard",
        slug: "default",
        kind: "standard",
        is_default: true,
        isDefault: true,
        variant_profile_id: "",
        variantProfileId: "",
        family_profile_id: "",
        familyProfileId: "",
        definition_managed: false,
        definitionManaged: false,
        definition_values: {
          "variant.variant_id": "default",
          "variant.label": "Standard"
        },
        definitionValues: {
          "variant.variant_id": "default",
          "variant.label": "Standard"
        },
        definition_values_json: "{\"variant.variant_id\":\"default\",\"variant.label\":\"Standard\"}",
        definitionValuesJson: "{\"variant.variant_id\":\"default\",\"variant.label\":\"Standard\"}",
        additional_field_keys: [],
        additionalFieldKeys: [],
        definition_summary: "Standardvariante",
        definitionSummary: "Standardvariante"
      }];
    }
  }

  function serializeVariant(variant) {
    try {
      var copy = U().deepClone(variant || {}, {});
      var values = copy.definition_values && typeof copy.definition_values === "object"
        ? copy.definition_values
        : U().valuesFromJson(copy.definition_values_json);

      var additionalFieldKeys = normalizeAdditionalFieldKeys(
        copy.additional_field_keys ||
        copy.additionalFieldKeys ||
        copy.additional_fields ||
        copy.additionalFields ||
        []
      );

      values["variant.variant_id"] = copy.variant_id || copy.slug || "variant";
      values["variant.label"] = copy.label || copy.name || "Neue Variante";

      if (copy.description) {
        values["variant.description"] = copy.description;
      }

      return {
        variant_id: copy.variant_id || copy.slug || values["variant.variant_id"],
        variantId: copy.variant_id || copy.slug || values["variant.variant_id"],
        label: copy.label || copy.name || values["variant.label"],
        name: copy.label || copy.name || values["variant.label"],
        slug: copy.slug || copy.variant_id || values["variant.variant_id"],
        kind: copy.kind || (copy.is_default ? "standard" : "profile"),
        description: copy.description || values["variant.description"] || "",
        is_default: !!copy.is_default,
        isDefault: !!copy.is_default,
        variant_profile_id: copy.variant_profile_id || "",
        variantProfileId: copy.variant_profile_id || "",
        family_profile_id: copy.family_profile_id || "",
        familyProfileId: copy.family_profile_id || "",
        definition_managed: !!copy.definition_managed,
        definitionManaged: !!copy.definition_managed,
        definition_values: values,
        definitionValues: values,
        definition_values_json: U().valuesToJson(values),
        definitionValuesJson: U().valuesToJson(values),
        additional_field_keys: additionalFieldKeys,
        additionalFieldKeys: additionalFieldKeys.slice(),
        definition_summary: copy.definition_summary || "",
        definitionSummary: copy.definition_summary || "",
        validation: copy.validation || null
      };
    } catch (error) {
      warn("Could not serialize variant.", error);
      return {};
    }
  }

  function serializeVariants(variants) {
    try {
      return U().toArray(variants).map(serializeVariant).filter(function (variant) {
        return !!variant.variant_id;
      });
    } catch (error) {
      return [];
    }
  }

  function getPayload() {
    try {
      return serializeVariants(runtime.state.variants);
    } catch (error) {
      warn("Could not build variant payload.", error);
      return [];
    }
  }

  function getPayloadJson() {
    try {
      return U().safeJsonStringify(getPayload(), "[]", 0);
    } catch (error) {
      return "[]";
    }
  }

  function bumpRevision(source) {
    try {
      runtime.state.revision += 1;
      runtime.state.source = source || "mutation";
      runtime.state.updated_at = U().nowIso ? U().nowIso() : new Date().toISOString();
    } catch (error) {
      /* no-op */
    }
  }

  function setContext(context, options) {
    try {
      var config = options || {};
      var current = runtime.state.context || {};
      var next = U().safeMerge(current, context || {});

      if (!next.taxonomy_path) {
        next.taxonomy_path = [next.domain, next.category, next.subcategory].filter(Boolean).join("/");
      }

      var currentSignature = contextSignature(current);
      var nextSignature = contextSignature(next);

      if (currentSignature === nextSignature) {
        return current;
      }

      runtime.state.context = next;

      if (config.sync !== false) {
        bumpRevision(config.source || "context");
        sync({
          source: config.source || "context",
          emitNativeEvents: config.emitNativeEvents === true,
          forceEvent: config.forceEvent === true
        });
        notify("context", {
          context: next
        }, {
          source: config.source || "context",
          forceEvent: config.forceEvent === true
        });
      }

      return next;
    } catch (error) {
      warn("Could not set variant context.", error);
      return runtime.state.context;
    }
  }

  function setVariants(variants, options) {
    try {
      var config = options || {};
      var normalized = normalizeVariants(variants || [], runtime.state.context || {});
      var previousSignature = variantsSignature(runtime.state.variants);
      var nextSignature = variantsSignature(normalized);

      if (previousSignature === nextSignature && config.force !== true) {
        sync({
          source: config.source || "set_variants_noop",
          emitNativeEvents: false,
          forceEvent: false
        });
        return runtime.state.variants;
      }

      runtime.state.variants = normalized;

      bumpRevision(config.source || "set_variants");

      if (config.sync !== false) {
        sync({
          source: config.source || "set_variants",
          emitNativeEvents: config.emitNativeEvents === true,
          forceEvent: config.forceEvent === true
        });
      }

      notify("set_variants", {
        variants: getPayload()
      }, {
        source: config.source || "set_variants",
        forceEvent: config.forceEvent === true
      });

      return runtime.state.variants;
    } catch (error) {
      warn("Could not set variants.", error);
      return runtime.state.variants;
    }
  }

  function findVariantIndex(target) {
    try {
      if (typeof target === "number") {
        return target >= 0 && target < runtime.state.variants.length ? target : -1;
      }

      if (target && typeof target === "object") {
        if (target.rowIndex !== undefined && target.rowIndex !== null && target.rowIndex !== "") {
          var byRow = U().intValue(target.rowIndex, -1);

          if (byRow >= 0 && byRow < runtime.state.variants.length) {
            return byRow;
          }
        }

        target = target.variant_id || target.variantId || target.slug || target.id;
      }

      var id = String(target || "");

      if (!id) {
        return -1;
      }

      for (var index = 0; index < runtime.state.variants.length; index += 1) {
        var variant = runtime.state.variants[index];

        if (variant.variant_id === id || variant.variantId === id || variant.slug === id || variant.id === id) {
          return index;
        }
      }

      return -1;
    } catch (error) {
      return -1;
    }
  }

  function getVariant(target) {
    try {
      var index = findVariantIndex(target);

      if (index < 0) {
        return null;
      }

      return runtime.state.variants[index] || null;
    } catch (error) {
      return null;
    }
  }

  function getDefaultVariant() {
    try {
      return runtime.state.variants.filter(function (variant) {
        return !!variant.is_default || variant.variant_id === "default";
      })[0] || runtime.state.variants[0] || null;
    } catch (error) {
      return null;
    }
  }

  function addVariant(raw, options) {
    try {
      var config = options || {};
      var existingIds = runtime.state.variants.map(function (variant) {
        return variant.variant_id;
      });

      var variant = normalizeVariant(raw || {}, {
        existingIds: existingIds,
        index: runtime.state.variants.length + 1,
        familyProfileId: runtime.state.context.family_profile_id,
        family_profile_id: runtime.state.context.family_profile_id,
        variantProfileId: runtime.state.context.variant_profile_id,
        variant_profile_id: runtime.state.context.variant_profile_id
      });

      if (!runtime.state.variants.length) {
        variant.variant_id = "default";
        variant.variantId = "default";
        variant.slug = "default";
        variant.is_default = true;
        variant.isDefault = true;
        variant.kind = "standard";
      } else {
        variant.is_default = false;
        variant.isDefault = false;

        if (!variant.variant_id || existingIds.indexOf(variant.variant_id) !== -1) {
          variant.variant_id = U().buildVariantId({
            label: variant.label,
            variantProfileId: variant.variant_profile_id || runtime.state.context.variant_profile_id,
            existingIds: existingIds,
            index: runtime.state.variants.length + 1
          });
          variant.variantId = variant.variant_id;
          variant.slug = variant.variant_id;
        }
      }

      variant.definition_values["variant.variant_id"] = variant.variant_id;
      variant.definition_values["variant.label"] = variant.label;
      variant.definitionValues = variant.definition_values;
      variant.definition_values_json = U().valuesToJson(variant.definition_values);
      variant.definitionValuesJson = variant.definition_values_json;
      variant.additional_field_keys = normalizeAdditionalFieldKeys(variant.additional_field_keys || variant.additionalFieldKeys || []);
      variant.additionalFieldKeys = variant.additional_field_keys.slice();

      runtime.state.variants.push(variant);
      runtime.state.variants = ensureDefaultVariant(runtime.state.variants);

      bumpRevision(config.source || "add_variant");
      sync({
        source: config.source || "add_variant",
        emitNativeEvents: config.emitNativeEvents === true,
        forceEvent: config.forceEvent === true
      });

      var payload = serializeVariant(variant);

      notify("add_variant", {
        variant: payload,
        variants: getPayload()
      }, {
        source: config.source || "add_variant",
        forceEvent: config.forceEvent === true
      });

      U().dispatchDocument("vectoplan:create:variant-added", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        source: config.source || "add_variant",
        variant: payload,
        variants: getPayload(),
        state: getState(),
        __vp_variant_state_event: true
      }, {
        silent: true
      });

      return variant;
    } catch (error) {
      warn("Could not add variant.", error);
      return null;
    }
  }

  function updateVariant(target, patch, options) {
    try {
      var config = options || {};
      var index = findVariantIndex(target);

      if (index < 0) {
        if (config.upsert !== false) {
          return addVariant(patch || target || {}, U().safeMerge(config, {
            source: config.source || "upsert_add"
          }));
        }

        return null;
      }

      var current = U().deepClone(runtime.state.variants[index], {});
      var update = patch || {};

      if (update.definition_values_json && !update.definition_values) {
        update.definition_values = U().valuesFromJson(update.definition_values_json);
      }

      if (update.definitionValuesJson && !update.definition_values) {
        update.definition_values = U().valuesFromJson(update.definitionValuesJson);
      }

      if (update.definitionValues && !update.definition_values) {
        update.definition_values = update.definitionValues;
      }

      var mergedValues = U().safeMerge(
        current.definition_values || {},
        update.definition_values || update.values || {}
      );

      var next = U().safeMerge(current, update);

      next.definition_values = mergedValues;

      if (update.label || update.name) {
        next.label = update.label || update.name;
        next.name = next.label;
        next.definition_values["variant.label"] = next.label;
      }

      if (update.description !== undefined) {
        next.description = update.description || "";
        next.definition_values["variant.description"] = next.description;
      }

      if (index === 0 || current.variant_id === "default") {
        next.variant_id = "default";
        next.variantId = "default";
        next.slug = "default";
        next.is_default = true;
        next.isDefault = true;
        next.kind = "standard";
      } else if (update.variant_id && config.allowIdChange === true) {
        next.variant_id = U().ensureUniqueId(update.variant_id, getExistingIds(current.variant_id));
        next.variantId = next.variant_id;
        next.slug = next.variant_id;
      } else {
        next.variant_id = current.variant_id;
        next.variantId = current.variant_id;
        next.slug = current.slug || current.variant_id;
      }

      next.definition_values["variant.variant_id"] = next.variant_id;
      next.definition_values["variant.label"] = next.label || "Neue Variante";

      next.additional_field_keys = normalizeAdditionalFieldKeys(
        update.additional_field_keys ||
        update.additionalFieldKeys ||
        next.additional_field_keys ||
        next.additionalFieldKeys ||
        []
      );
      next.additionalFieldKeys = next.additional_field_keys.slice();
      next.definition_values_json = U().valuesToJson(next.definition_values);
      next.definitionValuesJson = next.definition_values_json;

      runtime.state.variants[index] = normalizeVariant(next, {
        existingIds: getExistingIds(next.variant_id),
        index: index + 1,
        familyProfileId: runtime.state.context.family_profile_id,
        family_profile_id: runtime.state.context.family_profile_id,
        variantProfileId: runtime.state.context.variant_profile_id,
        variant_profile_id: runtime.state.context.variant_profile_id
      });

      runtime.state.variants = ensureDefaultVariant(runtime.state.variants);

      bumpRevision(config.source || "update_variant");
      sync({
        source: config.source || "update_variant",
        emitNativeEvents: config.emitNativeEvents === true,
        forceEvent: config.forceEvent === true
      });

      var payload = serializeVariant(runtime.state.variants[index]);

      notify("update_variant", {
        variant: payload,
        variants: getPayload()
      }, {
        source: config.source || "update_variant",
        forceEvent: config.forceEvent === true
      });

      U().dispatchDocument("vectoplan:create:variant-updated", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        source: config.source || "update_variant",
        variant: payload,
        variants: getPayload(),
        state: getState(),
        __vp_variant_state_event: true
      }, {
        silent: true
      });

      return runtime.state.variants[index];
    } catch (error) {
      warn("Could not update variant.", error);
      return null;
    }
  }

  function upsertVariant(raw, options) {
    try {
      var data = raw || {};
      var index = findVariantIndex(data);

      if (index >= 0) {
        return updateVariant(index, data, U().safeMerge(options || {}, {
          upsert: false,
          source: options && options.source ? options.source : "upsert_update"
        }));
      }

      return addVariant(data, U().safeMerge(options || {}, {
        source: options && options.source ? options.source : "upsert_add"
      }));
    } catch (error) {
      warn("Could not upsert variant.", error);
      return null;
    }
  }

  function removeVariant(target, options) {
    try {
      var config = options || {};
      var index = findVariantIndex(target);

      if (index < 0) {
        return false;
      }

      var variant = runtime.state.variants[index];

      if (!variant) {
        return false;
      }

      if (index === 0 || variant.is_default || variant.variant_id === "default") {
        U().dispatchDocument("vectoplan:create:variant-remove-blocked", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          reason: "default_variant_locked",
          variant: serializeVariant(variant),
          state: getState(),
          __vp_variant_state_event: true
        }, {
          silent: true
        });

        return false;
      }

      runtime.state.variants.splice(index, 1);
      runtime.state.variants = ensureDefaultVariant(runtime.state.variants);

      bumpRevision(config.source || "remove_variant");
      sync({
        source: config.source || "remove_variant",
        emitNativeEvents: config.emitNativeEvents === true,
        forceEvent: config.forceEvent === true
      });

      notify("remove_variant", {
        variant: serializeVariant(variant),
        variants: getPayload()
      }, {
        source: config.source || "remove_variant",
        forceEvent: config.forceEvent === true
      });

      U().dispatchDocument("vectoplan:create:variant-removed", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        source: config.source || "remove_variant",
        variant: serializeVariant(variant),
        variants: getPayload(),
        state: getState(),
        __vp_variant_state_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not remove variant.", error);
      return false;
    }
  }

  function replaceVariantValues(target, values, options) {
    try {
      var index = findVariantIndex(target);

      if (index < 0) {
        return null;
      }

      return updateVariant(index, {
        definition_values: values || {}
      }, options || {});
    } catch (error) {
      warn("Could not replace variant values.", error);
      return null;
    }
  }

  function patchVariantValues(target, values, options) {
    try {
      var variant = getVariant(target);

      if (!variant) {
        return null;
      }

      var merged = U().safeMerge(variant.definition_values || {}, values || {});

      return updateVariant(target, {
        definition_values: merged
      }, options || {});
    } catch (error) {
      warn("Could not patch variant values.", error);
      return null;
    }
  }

  function setDefaultVariant(target, options) {
    try {
      var config = options || {};

      if (config.allowDefaultSwitch !== true) {
        U().dispatchDocument("vectoplan:create:variant-default-switch-blocked", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          reason: "default_variant_fixed",
          target: target,
          state: getState(),
          __vp_variant_state_event: true
        }, {
          silent: true
        });

        return false;
      }

      var index = findVariantIndex(target);

      if (index < 0) {
        return false;
      }

      runtime.state.variants.forEach(function (variant, variantIndex) {
        variant.is_default = variantIndex === index;
        variant.isDefault = variantIndex === index;
      });

      runtime.state.variants[index].variant_id = "default";
      runtime.state.variants[index].variantId = "default";
      runtime.state.variants[index].slug = "default";
      runtime.state.variants[index].kind = "standard";
      runtime.state.variants[index].definition_values["variant.variant_id"] = "default";
      runtime.state.variants[index].definition_values_json = U().valuesToJson(runtime.state.variants[index].definition_values);
      runtime.state.variants[index].definitionValuesJson = runtime.state.variants[index].definition_values_json;

      runtime.state.variants = ensureDefaultVariant(runtime.state.variants);

      bumpRevision("set_default_variant");
      sync({
        source: "set_default_variant",
        emitNativeEvents: config.emitNativeEvents === true,
        forceEvent: config.forceEvent === true
      });

      notify("set_default_variant", {
        variant: serializeVariant(runtime.state.variants[index]),
        variants: getPayload()
      }, {
        source: "set_default_variant",
        forceEvent: config.forceEvent === true
      });

      return true;
    } catch (error) {
      warn("Could not set default variant.", error);
      return false;
    }
  }

  function contextSignature(context) {
    try {
      var source = context || {};

      return [
        source.workspace_id || "",
        source.table_id || "",
        source.domain || "",
        source.category || "",
        source.subcategory || "",
        source.taxonomy_path || "",
        source.object_kind || "",
        source.family_profile_id || "",
        source.variant_profile_id || "",
        source.default_variant_id || ""
      ].join("::");
    } catch (error) {
      return "";
    }
  }

  function variantsSignature(variants) {
    try {
      return U().safeJsonStringify(serializeVariants(variants || []), "[]", 0);
    } catch (error) {
      return String(Date.now());
    }
  }

  function syncSignature(payloadJson, contextSignatureValue, count, defaultId) {
    return [
      payloadJson || "",
      contextSignatureValue || "",
      String(count || 0),
      defaultId || ""
    ].join("::::");
  }

  function syncJsonField(cache, options) {
    try {
      var config = options || {};
      var c = cache || runtime.cache || cacheDom();
      var field = c.jsonField;

      if (!field) {
        return false;
      }

      var json = getPayloadJson();

      if (field.value === json && runtime.lastPayloadJson === json) {
        return false;
      }

      field.value = json;
      runtime.lastPayloadJson = json;

      U().setAttr(field, "data-vp-last-state-sync", Date.now());
      U().setAttr(field, "data-vp-last-state-sync-source", config.source || "variant_state");
      U().setAttr(field, "data-vp-state-sync-version", COMPONENT_VERSION);

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
      warn("Could not sync definition_variants_json.", error);
      return false;
    }
  }

  function syncDefaultIdField(cache, options) {
    try {
      var config = options || {};
      var c = cache || runtime.cache || cacheDom();
      var field = c.defaultIdField;
      var defaultVariant = getDefaultVariant();
      var defaultId = defaultVariant ? defaultVariant.variant_id : "default";
      var changed = runtime.state.context.default_variant_id !== defaultId;

      runtime.state.context.default_variant_id = defaultId;

      if (field && field.value !== defaultId) {
        field.value = defaultId;
        changed = true;

        U().setAttr(field, "data-vp-last-state-sync", Date.now());
        U().setAttr(field, "data-vp-last-state-sync-source", config.source || "variant_state");

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
      }

      if (runtime.lastDefaultVariantId !== defaultId) {
        changed = true;
        runtime.lastDefaultVariantId = defaultId;
      }

      if (c.workspace && U().attr(c.workspace, "data-vp-default-variant-id", "") !== defaultId) {
        U().setAttr(c.workspace, "data-vp-default-variant-id", defaultId);
        changed = true;
      }

      if (c.table && U().attr(c.table, "data-vp-default-variant-id", "") !== defaultId) {
        U().setAttr(c.table, "data-vp-default-variant-id", defaultId);
        changed = true;
      }

      return changed;
    } catch (error) {
      warn("Could not sync default variant id.", error);
      return false;
    }
  }

  function syncCounts(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();
      var count = runtime.state.variants.length;
      var changed = runtime.lastCount !== count;

      runtime.lastCount = count;

      if (c.workspace && U().attr(c.workspace, "data-vp-variant-count", "") !== String(count)) {
        U().setAttr(c.workspace, "data-vp-variant-count", count);
        changed = true;
      }

      if (c.table && U().attr(c.table, "data-vp-variant-count", "") !== String(count)) {
        U().setAttr(c.table, "data-vp-variant-count", count);
        changed = true;
      }

      if (c.countLabel) {
        var labelText = count === 1 ? "1 Variante" : String(count) + " Varianten";

        if (c.countLabel.textContent !== labelText) {
          c.countLabel.textContent = labelText;
          changed = true;
        }
      }

      return changed;
    } catch (error) {
      warn("Could not sync variant count.", error);
      return false;
    }
  }

  function syncContextAttrs(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();
      var context = runtime.state.context || {};
      var signature = contextSignature(context);
      var changed = runtime.lastContextSignature !== signature;

      runtime.lastContextSignature = signature;

      if (c.workspace) {
        [
          ["data-vp-current-domain", context.domain || ""],
          ["data-vp-current-category", context.category || ""],
          ["data-vp-current-subcategory", context.subcategory || ""],
          ["data-vp-current-taxonomy-path", context.taxonomy_path || ""],
          ["data-vp-current-family-profile-id", context.family_profile_id || ""],
          ["data-vp-current-variant-profile-id", context.variant_profile_id || ""],
          ["data-vp-current-object-kind", context.object_kind || "cell_block"]
        ].forEach(function (item) {
          if (U().attr(c.workspace, item[0], "") !== item[1]) {
            U().setAttr(c.workspace, item[0], item[1]);
            changed = true;
          }
        });
      }

      if (c.table) {
        [
          ["data-vp-family-profile-id", context.family_profile_id || ""],
          ["data-vp-variant-profile-id", context.variant_profile_id || ""]
        ].forEach(function (item) {
          if (U().attr(c.table, item[0], "") !== item[1]) {
            U().setAttr(c.table, item[0], item[1]);
            changed = true;
          }
        });
      }

      return changed;
    } catch (error) {
      warn("Could not sync context attributes.", error);
      return false;
    }
  }

  function sync(options) {
    try {
      var config = options || {};

      if (runtime.syncInProgress) {
        runtime.suppressedSyncCount += 1;
        runtime.state.sync_meta.suppressed_sync_count = runtime.suppressedSyncCount;
        return false;
      }

      runtime.syncInProgress = true;

      var cache = cacheDom(config.root || null);
      var payloadJsonBefore = runtime.lastPayloadJson || "";
      var changedJson = syncJsonField(cache, config);
      var changedDefault = syncDefaultIdField(cache, config);
      var changedCount = syncCounts(cache);
      var changedContext = syncContextAttrs(cache);
      var payloadJson = runtime.lastPayloadJson || getPayloadJson();
      var contextSig = runtime.lastContextSignature || contextSignature(runtime.state.context);
      var defaultId = runtime.lastDefaultVariantId || "default";
      var signature = syncSignature(payloadJson, contextSig, runtime.state.variants.length, defaultId);
      var changed = !!(changedJson || changedDefault || changedCount || changedContext || payloadJsonBefore !== payloadJson || runtime.lastSyncSignature !== signature);
      var shouldDispatch = config.forceEvent === true ||
        changed ||
        runtime.lastSyncedRevision !== runtime.state.revision;

      runtime.lastSyncSignature = signature;
      runtime.state.sync_meta.last_synced_at = U().nowIso ? U().nowIso() : "";
      runtime.state.sync_meta.last_payload_json_length = payloadJson ? payloadJson.length : 0;
      runtime.state.sync_meta.suppressed_sync_count = runtime.suppressedSyncCount;
      runtime.state.sync_meta.suppressed_notify_count = runtime.suppressedNotifyCount;

      if (shouldDispatch && config.dispatchEvent !== false) {
        runtime.lastSyncedRevision = runtime.state.revision;
        runtime.lastSyncSnapshot = {
          revision: runtime.state.revision,
          changedJson: changedJson,
          changedDefault: changedDefault,
          changedCount: changedCount,
          changedContext: changedContext,
          source: config.source || "sync"
        };

        U().dispatchDocument("vectoplan:create:variant-state-synced", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          source: config.source || "sync",
          state: getState(),
          variants: getPayload(),
          json: getPayloadJson(),
          changed: changed,
          changedJson: changedJson,
          changedDefault: changedDefault,
          changedCount: changedCount,
          changedContext: changedContext,
          __vp_variant_state_event: true
        }, {
          silent: true
        });
      }

      runtime.syncInProgress = false;
      return true;
    } catch (error) {
      runtime.syncInProgress = false;
      warn("Could not sync variant state.", error);
      return false;
    }
  }

  function getState() {
    try {
      return U().deepClone(runtime.state, {});
    } catch (error) {
      return runtime.state;
    }
  }

  function notify(action, detail, options) {
    try {
      var config = options || {};

      if (runtime.notifyInProgress) {
        runtime.suppressedNotifyCount += 1;
        runtime.state.sync_meta.suppressed_notify_count = runtime.suppressedNotifyCount;
        return false;
      }

      runtime.notifyInProgress = true;

      var payload = U().safeMerge({
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        action: action || "change",
        revision: runtime.state.revision,
        source: config.source || action || "change",
        state: getState(),
        __vp_variant_state_event: true
      }, detail || {});

      runtime.subscribers.forEach(function (subscriber) {
        try {
          subscriber(payload);
        } catch (subscriberError) {
          warn("Variant state subscriber failed.", subscriberError);
        }
      });

      if (config.dispatchEvent !== false) {
        U().dispatchDocument("vectoplan:create:variant-state-changed", payload, {
          silent: true
        });
      }

      runtime.notifyInProgress = false;
      return true;
    } catch (error) {
      runtime.notifyInProgress = false;
      warn("Could not notify state subscribers.", error);
      return false;
    }
  }

  function subscribe(handler) {
    try {
      if (typeof handler !== "function") {
        return function () {};
      }

      runtime.subscribers.push(handler);

      return function unsubscribe() {
        try {
          runtime.subscribers = runtime.subscribers.filter(function (subscriber) {
            return subscriber !== handler;
          });
        } catch (error) {
          /* no-op */
        }
      };
    } catch (error) {
      warn("Could not subscribe to variant state.", error);
      return function () {};
    }
  }

  function initialize(explicitRoot, options) {
    try {
      var config = options || {};
      var cache = cacheDom(explicitRoot || null);
      var context = readContext(cache);

      if (runtime.initialized && config.force !== true && config.reinitialize !== true) {
        runtime.cache = cache;
        setContext(context, {
          source: config.source || "initialize_existing",
          emitNativeEvents: false,
          forceEvent: false
        });
        sync({
          root: explicitRoot || null,
          source: config.source || "initialize_existing",
          emitNativeEvents: false,
          forceEvent: false
        });
        return getState();
      }

      var initialVariants = readInitialVariants(cache);
      var variants = normalizeVariants(initialVariants, context);

      runtime.state = createEmptyState();
      runtime.state.ready = true;
      runtime.state.created_at = U().nowIso ? U().nowIso() : new Date().toISOString();
      runtime.state.updated_at = runtime.state.created_at;
      runtime.state.source = config.source || "dom";
      runtime.state.context = context;
      runtime.state.variants = variants;
      runtime.initialized = true;

      sync({
        root: explicitRoot || null,
        source: config.source || "initialize",
        emitNativeEvents: config.emitNativeEvents === true,
        forceEvent: config.forceEvent === true
      });

      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-state-version", COMPONENT_VERSION);

      U().dispatchDocument("vectoplan:create:variant-state-ready", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        source: config.source || "initialize",
        state: getState(),
        variants: getPayload(),
        json: getPayloadJson(),
        __vp_variant_state_event: true
      }, {
        silent: true
      });

      notify("ready", {
        variants: getPayload()
      }, {
        source: config.source || "initialize"
      });

      return getState();
    } catch (error) {
      warn("Could not initialize variant state.", error);

      runtime.state = createEmptyState();
      runtime.state.ready = false;
      runtime.state.source = "initialization_failed";
      runtime.state.updated_at = U().nowIso ? U().nowIso() : "";

      return getState();
    }
  }

  function reload(options) {
    try {
      return initialize(null, U().safeMerge(options || {}, {
        source: "reload",
        force: true
      }));
    } catch (error) {
      warn("Could not reload variant state.", error);
      return getState();
    }
  }

  function extractVariantFromEvent(detail) {
    try {
      var payload = detail || {};

      if (payload.variant) {
        return payload.variant;
      }

      if (payload.payload && payload.payload.variant) {
        return payload.payload.variant;
      }

      if (payload.payload) {
        return payload.payload;
      }

      return payload;
    } catch (error) {
      return {};
    }
  }

  function bindGlobalEvents() {
    try {
      if (runtime.globalEventsBound) {
        return;
      }

      document.addEventListener("vectoplan:create:variant-state-upsert-requested", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail.__vp_variant_state_event) {
            return;
          }

          var variant = extractVariantFromEvent(detail);

          upsertVariant(variant, {
            source: detail.source || "event_upsert",
            forceEvent: detail.forceEvent === true
          });
        } catch (error) {
          warn("Upsert event failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-state-remove-requested", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail.__vp_variant_state_event) {
            return;
          }

          var target = detail.variant_id || detail.variantId || detail.slug || detail.id || detail.rowIndex || detail;

          removeVariant(target, {
            source: detail.source || "event_remove",
            forceEvent: detail.forceEvent === true
          });
        } catch (error) {
          warn("Remove event failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-remove-requested", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail.__vp_variant_state_event) {
            return;
          }

          var target = detail.variant_id || detail.variantId || detail.slug || detail.id || detail.rowIndex || detail;

          removeVariant(target, {
            source: detail.source || "table_remove_request",
            forceEvent: detail.forceEvent === true
          });
        } catch (error) {
          warn("Table remove request failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-profile-resolved", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var familyProfileId = detail.family_profile_id || detail.familyProfileId || "";
          var variantProfileId = detail.variant_profile_id || detail.variantProfileId || "";

          if (!familyProfileId && detail.profilePayload && detail.profilePayload.family_profile_id) {
            familyProfileId = detail.profilePayload.family_profile_id;
          }

          if (!variantProfileId && detail.profilePayload && detail.profilePayload.variant_profile_id) {
            variantProfileId = detail.profilePayload.variant_profile_id;
          }

          if (familyProfileId || variantProfileId) {
            setContext({
              family_profile_id: familyProfileId || runtime.state.context.family_profile_id,
              variant_profile_id: variantProfileId || runtime.state.context.variant_profile_id
            }, {
              source: detail.source || "profile_resolved",
              emitNativeEvents: false,
              forceEvent: false
            });
          }
        } catch (error) {
          warn("Profile resolved context update failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:context-synced", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var context = detail.context || {};

          if (!context || detail.__vp_variant_state_event) {
            return;
          }

          setContext({
            domain: context.domain || runtime.state.context.domain,
            category: context.category || runtime.state.context.category,
            subcategory: context.subcategory || runtime.state.context.subcategory,
            taxonomy_path: context.taxonomy_path || context.taxonomyPath || runtime.state.context.taxonomy_path,
            object_kind: context.object_kind || context.objectKind || runtime.state.context.object_kind,
            family_profile_id: context.family_profile_id || context.familyProfileId || runtime.state.context.family_profile_id,
            variant_profile_id: context.variant_profile_id || context.variantProfileId || runtime.state.context.variant_profile_id
          }, {
            source: detail.source || "context_synced",
            emitNativeEvents: false,
            forceEvent: false
          });
        } catch (error) {
          warn("Context synced update failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-workspace-ready", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var root = detail && detail.context && detail.context.id
            ? document.getElementById(detail.context.id)
            : null;

          initialize(root, {
            source: "workspace_ready",
            emitNativeEvents: false
          });
        } catch (error) {
          warn("Workspace ready initialization failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-table-ready", function () {
        try {
          sync({
            source: "variant_table_ready",
            emitNativeEvents: false,
            forceEvent: false
          });
        } catch (error) {
          warn("Table ready sync failed.", error);
        }
      });

      runtime.globalEventsBound = true;
    } catch (error) {
      warn("Could not bind variant state global events.", error);
    }
  }

  function cssEscape(value) {
    try {
      if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(String(value || ""));
      }

      return String(value || "").replace(/["\\]/g, "\\$&");
    } catch (error) {
      return String(value || "");
    }
  }

  var api = {
    __name: COMPONENT_NAME,
    __version: COMPONENT_VERSION,
    version: COMPONENT_VERSION,

    initialize: initialize,
    reload: reload,
    sync: sync,

    getState: getState,
    getContext: function () {
      return U().deepClone(runtime.state.context, {});
    },
    setContext: setContext,

    getVariants: function () {
      return U().deepClone(runtime.state.variants, []);
    },
    getVariant: function (target) {
      return U().deepClone(getVariant(target), null);
    },
    getDefaultVariant: function () {
      return U().deepClone(getDefaultVariant(), null);
    },

    setVariants: setVariants,
    addVariant: addVariant,
    updateVariant: updateVariant,
    upsertVariant: upsertVariant,
    removeVariant: removeVariant,
    setDefaultVariant: setDefaultVariant,

    replaceVariantValues: replaceVariantValues,
    patchVariantValues: patchVariantValues,

    findVariantIndex: findVariantIndex,

    getPayload: getPayload,
    getPayloadJson: getPayloadJson,
    serializeVariant: serializeVariant,
    serializeVariants: serializeVariants,

    readRows: function () {
      return readRows(runtime.cache || cacheDom());
    },
    readDefinitionVariantsJson: function () {
      return readDefinitionVariantsJson(runtime.cache || cacheDom());
    },

    subscribe: subscribe
  };

  try {
    window[GLOBAL_NAME] = api;
    bindGlobalEvents();

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        initialize(null, {
          source: "dom_content_loaded",
          emitNativeEvents: false
        });
      }, {
        once: true
      });
    } else {
      initialize(null, {
        source: "immediate",
        emitNativeEvents: false
      });
    }
  } catch (bootstrapError) {
    warn("Could not bootstrap variant state.", bootstrapError);
  }
})();