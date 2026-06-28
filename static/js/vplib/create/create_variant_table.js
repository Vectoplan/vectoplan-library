/* services/vectoplan-library/static/js/vplib/create/create_variant_table.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateVariantTable";
  var COMPONENT_NAME = "VECTOPLAN Create Variant Table";
  var COMPONENT_VERSION = "0.7.0";
  var READY_ATTR = "data-vp-create-variant-table-controller-ready";

  var TABLE_SELECTOR = "[data-vp-variant-table-root='true'], [data-vp-variant-table='true'], [data-create-variant-table='true']";
  var TABLE_BODY_SELECTOR = "[data-vp-variant-table-body='true']";
  var WORKSPACE_SELECTOR = "[data-vp-variant-workspace-root='true'], [data-vp-variant-workspace='true'], .vp-create-variant-workspace";
  var TABLE_SLOT_SELECTOR = "[data-vp-variant-table-slot='true'], .vp-create-variant-workspace__table-slot";
  var DRAWER_SLOT_SELECTOR = "[data-vp-variant-drawer-slot='true'], .vp-create-variant-workspace__drawer-slot";
  var DRAWER_SELECTOR = "[data-vp-variant-drawer-root='true'], [data-vp-variant-drawer='true'], .vp-create-variant-drawer";
  var ROW_SELECTOR = "[data-vp-variant-row='true'], [data-create-variant-row='true']";
  var JSON_FIELD_SELECTOR = "[data-vp-definition-variants-json='true'], [name='definition_variants_json']";
  var DEFAULT_FIELD_SELECTOR = "[data-vp-default-variant-id-field='true'], [data-vp-definition-variants-default-id='true'], [name='default_variant_id']";
  var COUNT_LABEL_SELECTOR = "[data-vp-variant-count-label='true'], [data-vp-variant-count-label]";

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

        var text = value === null || value === undefined ? "" : String(value);

        if (node.textContent === text) {
          return false;
        }

        node.textContent = text;
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
        var changed = node.hidden !== nextHidden;

        node.hidden = nextHidden;

        if (nextHidden) {
          node.setAttribute("hidden", "");
          node.setAttribute("aria-hidden", "true");
        } else {
          node.removeAttribute("hidden");
          node.removeAttribute("aria-hidden");
        }

        return changed;
      } catch (error) {
        return false;
      }
    },

    setDisabled: function (node, disabled, reason) {
      try {
        if (!node) {
          return false;
        }

        var nextDisabled = !!disabled;
        var changed = node.disabled !== nextDisabled;

        node.disabled = nextDisabled;

        if (nextDisabled) {
          node.setAttribute("aria-disabled", "true");

          if (reason) {
            node.setAttribute("data-vp-disabled-reason", String(reason));
          }
        } else {
          node.removeAttribute("aria-disabled");
          node.removeAttribute("data-vp-disabled-reason");
        }

        return changed;
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

        if (["true", "1", "yes", "ja", "on", "ok", "default", "selected", "enabled", "active"].indexOf(text) !== -1) {
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

    trim: function (value) {
      try {
        return String(value || "").trim();
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

    dispatch: function (node, eventName, detail, options) {
      try {
        if (!node) {
          return null;
        }

        var event = new CustomEvent(eventName, {
          bubbles: !(options && options.bubbles === false),
          cancelable: !!(options && options.cancelable),
          detail: detail || {}
        });

        node.dispatchEvent(event);
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

    valuesFromJson: function (value) {
      var parsed = fallbackUtils.safeJsonParse(value, {});
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    },

    valuesToJson: function (value) {
      return fallbackUtils.safeJsonStringify(value || {}, "{}", 0);
    },

    normalizeVariant: function (raw) {
      try {
        var source = raw || {};
        var values = {};

        if (source.definition_values && typeof source.definition_values === "object") {
          values = fallbackUtils.deepClone(source.definition_values, {});
        } else if (source.definitionValues && typeof source.definitionValues === "object") {
          values = fallbackUtils.deepClone(source.definitionValues, {});
        } else if (source.definition_values_json) {
          values = fallbackUtils.valuesFromJson(source.definition_values_json);
        } else if (source.definitionValuesJson) {
          values = fallbackUtils.valuesFromJson(source.definitionValuesJson);
        } else if (source.values && typeof source.values === "object") {
          values = fallbackUtils.deepClone(source.values, {});
        } else if (source.valuesJson) {
          values = fallbackUtils.valuesFromJson(source.valuesJson);
        }

        var id = source.variant_id || source.variantId || source.slug || source.id || values["variant.variant_id"] || "";
        var label = source.label || source.name || values["variant.label"] || "";
        var isDefault = fallbackUtils.bool(source.is_default || source.isDefault || source.default, false) || id === "default";

        if (!id) {
          id = isDefault ? "default" : "variant";
        }

        if (!label) {
          label = isDefault ? "Standard" : "Neue Variante";
        }

        values["variant.variant_id"] = id;
        values["variant.label"] = label;

        return {
          variant_id: id,
          variantId: id,
          label: label,
          name: label,
          slug: source.slug || id,
          kind: source.kind || source.variant_kind || (isDefault ? "standard" : "profile"),
          description: source.description || values["variant.description"] || "",
          is_default: isDefault,
          isDefault: isDefault,
          family_profile_id: source.family_profile_id || source.familyProfileId || "",
          familyProfileId: source.family_profile_id || source.familyProfileId || "",
          variant_profile_id: source.variant_profile_id || source.variantProfileId || source.profile_id || "",
          variantProfileId: source.variant_profile_id || source.variantProfileId || source.profile_id || "",
          definition_managed: fallbackUtils.bool(source.definition_managed || source.definitionManaged, !!Object.keys(values).length),
          definitionManaged: fallbackUtils.bool(source.definition_managed || source.definitionManaged, !!Object.keys(values).length),
          definition_values: values,
          definitionValues: values,
          definition_values_json: fallbackUtils.valuesToJson(values),
          definitionValuesJson: fallbackUtils.valuesToJson(values),
          additional_field_keys: normalizeAdditionalFieldKeys(source.additional_field_keys || source.additionalFieldKeys || source.additional_fields || source.additionalFields || []),
          additionalFieldKeys: normalizeAdditionalFieldKeys(source.additional_field_keys || source.additionalFieldKeys || source.additional_fields || source.additionalFields || []),
          definition_summary: source.definition_summary || source.definitionSummary || source.summary || "",
          definitionSummary: source.definition_summary || source.definitionSummary || source.summary || ""
        };
      } catch (error) {
        return {
          variant_id: "variant",
          variantId: "variant",
          label: "Neue Variante",
          name: "Neue Variante",
          slug: "variant",
          kind: "profile",
          description: "",
          is_default: false,
          isDefault: false,
          family_profile_id: "",
          familyProfileId: "",
          variant_profile_id: "",
          variantProfileId: "",
          definition_managed: false,
          definitionManaged: false,
          definition_values: {},
          definitionValues: {},
          definition_values_json: "{}",
          definitionValuesJson: "{}",
          additional_field_keys: [],
          additionalFieldKeys: [],
          definition_summary: "",
          definitionSummary: ""
        };
      }
    },

    normalizeVariants: function (variants) {
      try {
        var list = fallbackUtils.toArray(variants).map(function (variant, index) {
          var normalized = fallbackUtils.normalizeVariant(variant);

          if (index === 0 || normalized.variant_id === "default" || normalized.is_default) {
            normalized.variant_id = "default";
            normalized.variantId = "default";
            normalized.slug = "default";
            normalized.is_default = true;
            normalized.isDefault = true;
            normalized.kind = "standard";

            if (!normalized.label || normalized.label === "Neue Variante") {
              normalized.label = "Standard";
              normalized.name = "Standard";
            }

            normalized.definition_values["variant.variant_id"] = "default";
            normalized.definition_values["variant.label"] = normalized.label;
            normalized.definitionValues = normalized.definition_values;
            normalized.definition_values_json = fallbackUtils.valuesToJson(normalized.definition_values);
            normalized.definitionValuesJson = normalized.definition_values_json;
          } else {
            normalized.is_default = false;
            normalized.isDefault = false;
          }

          normalized.additional_field_keys = normalizeAdditionalFieldKeys(normalized.additional_field_keys || normalized.additionalFieldKeys || []);
          normalized.additionalFieldKeys = normalized.additional_field_keys.slice();

          return normalized;
        });

        if (!list.length) {
          list.push(fallbackUtils.normalizeVariant({
            variant_id: "default",
            label: "Standard",
            is_default: true,
            kind: "standard",
            definition_summary: "Standardvariante"
          }));
        }

        return list;
      } catch (error) {
        return [];
      }
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

  var previousApi = window[GLOBAL_NAME] || null;

  var runtime = {
    initialized: false,
    globalEventsBound: false,
    renderScheduled: false,
    pendingRenderAfterEditorClose: false,
    rendering: false,
    editorMode: "closed",
    cache: null,
    lastRevision: null,
    lastRenderAt: 0,
    lastClickAt: 0,
    lastJsonFieldValue: "",
    lastMetaSignature: "",
    lastRenderSignature: "",
    suppressedRenderCount: 0,
    suppressedSyncCount: 0,
    suppressedEditorRenderCount: 0,
    options: {
      autoRender: true,
      autoRenderWhileEditorOpen: false,
      preserveFocus: true,
      emitNativeEvents: false
    }
  };

  function getTable(root) {
    try {
      if (root && root.nodeType === 1) {
        if (root.matches && root.matches(TABLE_SELECTOR)) {
          return root;
        }

        var found = U().qs(TABLE_SELECTOR, root);

        if (found) {
          return found;
        }

        var closest = root.closest ? root.closest(TABLE_SELECTOR) : null;

        if (closest) {
          return closest;
        }
      }

      return U().qs(TABLE_SELECTOR);
    } catch (error) {
      return null;
    }
  }

  function getWorkspace(root) {
    try {
      if (root && root.nodeType === 1) {
        if (root.matches && root.matches(WORKSPACE_SELECTOR)) {
          return root;
        }

        var closest = root.closest ? root.closest(WORKSPACE_SELECTOR) : null;

        if (closest) {
          return closest;
        }

        var inside = U().qs(WORKSPACE_SELECTOR, root);

        if (inside) {
          return inside;
        }
      }

      return U().qs(WORKSPACE_SELECTOR);
    } catch (error) {
      return null;
    }
  }

  function getTableSlot(workspace, table) {
    try {
      if (workspace) {
        var slot = U().qs(TABLE_SLOT_SELECTOR, workspace);

        if (slot) {
          return slot;
        }
      }

      if (table) {
        var parentSlot = U().closest(table, TABLE_SLOT_SELECTOR);

        if (parentSlot) {
          return parentSlot;
        }
      }

      return table || null;
    } catch (error) {
      return table || null;
    }
  }

  function getDrawerSlot(workspace) {
    try {
      if (workspace) {
        var slot = U().qs(DRAWER_SLOT_SELECTOR, workspace);

        if (slot) {
          return slot;
        }
      }

      return U().qs(DRAWER_SLOT_SELECTOR);
    } catch (error) {
      return null;
    }
  }

  function getDrawer(workspace) {
    try {
      if (workspace) {
        var drawer = U().qs(DRAWER_SELECTOR, workspace);

        if (drawer) {
          return drawer;
        }
      }

      return U().qs(DRAWER_SELECTOR);
    } catch (error) {
      return null;
    }
  }

  function cacheDom(root) {
    try {
      var table = getTable(root);
      var workspace = getWorkspace(table || root);
      var body = table ? U().qs(TABLE_BODY_SELECTOR, table) : null;
      var tableSlot = getTableSlot(workspace, table);
      var drawerSlot = getDrawerSlot(workspace);
      var drawer = getDrawer(workspace);

      if (!body && table) {
        body = table;
      }

      var cache = {
        workspace: workspace,
        table: table,
        tableSlot: tableSlot,
        drawerSlot: drawerSlot,
        drawer: drawer,
        body: body,
        rows: table ? U().qsa(ROW_SELECTOR, table) : [],
        empty: table ? U().qs("[data-vp-variant-table-empty='true']", table) : null,
        template: table ? U().qs("[data-vp-variant-row-template='true']", table) : null,
        countLabel: workspace
          ? U().qs(COUNT_LABEL_SELECTOR, workspace)
          : U().qs(COUNT_LABEL_SELECTOR),
        jsonField: workspace
          ? U().qs(JSON_FIELD_SELECTOR, workspace)
          : U().qs(JSON_FIELD_SELECTOR),
        defaultField: workspace
          ? U().qs(DEFAULT_FIELD_SELECTOR, workspace)
          : U().qs(DEFAULT_FIELD_SELECTOR)
      };

      runtime.cache = cache;
      return cache;
    } catch (error) {
      warn("Could not cache variant table DOM.", error);

      runtime.cache = {
        workspace: null,
        table: null,
        tableSlot: null,
        drawerSlot: null,
        drawer: null,
        body: null,
        rows: [],
        empty: null,
        template: null,
        countLabel: null,
        jsonField: null,
        defaultField: null
      };

      return runtime.cache;
    }
  }

  function markEditorNode(node, mode, source) {
    try {
      if (!node) {
        return false;
      }

      U().setAttr(node, "data-vp-variant-editor-state", mode);
      U().setAttr(node, "data-vp-variant-editor-mode", mode);
      U().setAttr(node, "data-vp-variant-editor-state-source", source || COMPONENT_NAME);

      if (node.classList) {
        node.classList.toggle("is-variant-editor-open", mode === "open");
        node.classList.toggle("is-variant-editor-closed", mode !== "open");
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function setEditorMode(mode, options) {
    try {
      var config = options || {};
      var nextMode = mode === "open" ? "open" : "closed";
      var changed = runtime.editorMode !== nextMode;
      var cache = runtime.cache || cacheDom(config.root || null);

      runtime.editorMode = nextMode;

      markEditorNode(cache.workspace, nextMode, config.source || "table_editor_mode");
      markEditorNode(cache.table, nextMode, config.source || "table_editor_mode");
      markEditorNode(cache.tableSlot, nextMode, config.source || "table_editor_mode");
      markEditorNode(cache.drawerSlot, nextMode, config.source || "table_editor_mode");
      markEditorNode(cache.drawer, nextMode, config.source || "table_editor_mode");

      try {
        document.documentElement.setAttribute("data-vp-variant-editor-state", nextMode);
      } catch (htmlError) {
        /* no-op */
      }

      if (nextMode === "open") {
        if (cache.tableSlot && cache.drawer && !cache.tableSlot.contains(cache.drawer)) {
          U().setHidden(cache.tableSlot, true);
        } else if (cache.table && cache.drawer && !cache.table.contains(cache.drawer)) {
          U().setHidden(cache.table, true);
        }

        if (cache.drawerSlot) {
          U().setHidden(cache.drawerSlot, false);
        }

        if (cache.drawer) {
          cache.drawer.hidden = false;
          cache.drawer.removeAttribute("hidden");
          cache.drawer.setAttribute("aria-hidden", "false");
        }
      } else {
        if (cache.tableSlot) {
          U().setHidden(cache.tableSlot, false);
        } else if (cache.table) {
          U().setHidden(cache.table, false);
        }

        if (cache.drawerSlot && config.keepDrawerSlotVisible !== true) {
          if (!cache.drawer || U().attr(cache.drawer, "data-vp-variant-drawer-state", "") !== "open") {
            U().setHidden(cache.drawerSlot, true);
          }
        }
      }

      if (changed || config.forceEvent === true) {
        U().dispatchDocument("vectoplan:create:variant-table-editor-mode-changed", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          mode: nextMode,
          editorMode: nextMode,
          open: nextMode === "open",
          source: config.source || "table_editor_mode",
          __vp_variant_table_event: true
        }, {
          silent: true
        });
      }

      if (nextMode === "closed" && (runtime.pendingRenderAfterEditorClose || config.renderAfterClose === true)) {
        runtime.pendingRenderAfterEditorClose = false;

        window.setTimeout(function () {
          renderFromState({
            source: config.source || "editor_closed",
            force: true,
            emitNativeEvents: false
          });
        }, 40);
      }

      return nextMode;
    } catch (error) {
      warn("Could not set variant table editor mode.", error);
      return runtime.editorMode || "closed";
    }
  }

  function isEditorOpen() {
    try {
      return runtime.editorMode === "open" ||
        (runtime.cache && runtime.cache.workspace && U().attr(runtime.cache.workspace, "data-vp-variant-editor-state", "") === "open") ||
        document.documentElement.getAttribute("data-vp-variant-editor-state") === "open";
    } catch (error) {
      return runtime.editorMode === "open";
    }
  }

  function shouldRenderVisibleTable(options) {
    try {
      var config = options || {};

      if (config.force === true) {
        return true;
      }

      if (!isEditorOpen()) {
        return true;
      }

      if (runtime.options.autoRenderWhileEditorOpen === true || config.renderWhileEditorOpen === true) {
        return true;
      }

      runtime.suppressedEditorRenderCount += 1;
      runtime.pendingRenderAfterEditorClose = true;
      return false;
    } catch (error) {
      return true;
    }
  }

  function getStateApi() {
    try {
      return window.VectoplanCreateVariantState || null;
    } catch (error) {
      return null;
    }
  }

  function getDrawerApi() {
    try {
      return window.VectoplanCreateVariantDrawer || null;
    } catch (error) {
      return null;
    }
  }

  function getSummaryApi() {
    try {
      return window.VectoplanCreateVariantSummary || null;
    } catch (error) {
      return null;
    }
  }

  function readRowsPayload(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();

      return U().qsa(ROW_SELECTOR, c.table || document).map(function (row) {
        return payloadFromRow(row);
      });
    } catch (error) {
      warn("Could not read rows payload.", error);
      return [];
    }
  }

  function readJsonPayload(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();

      if (!c.jsonField || !c.jsonField.value) {
        return [];
      }

      var parsed = U().safeJsonParse(c.jsonField.value, []);

      if (Array.isArray(parsed)) {
        return parsed;
      }

      if (parsed && Array.isArray(parsed.variants)) {
        return parsed.variants;
      }

      if (parsed && Array.isArray(parsed.items)) {
        return parsed.items;
      }

      if (parsed && Array.isArray(parsed.definition_variants)) {
        return parsed.definition_variants;
      }

      if (parsed && Array.isArray(parsed.definitionVariants)) {
        return parsed.definitionVariants;
      }

      return [];
    } catch (error) {
      return [];
    }
  }

  function getVariants(options) {
    try {
      var config = options || {};
      var state = getStateApi();

      if (state && typeof state.getVariants === "function" && config.fromDom !== true) {
        var stateVariants = state.getVariants();

        if (stateVariants && stateVariants.length) {
          return U().normalizeVariants(stateVariants);
        }
      }

      var cache = runtime.cache || cacheDom();
      var jsonVariants = readJsonPayload(cache);

      if (jsonVariants.length) {
        return U().normalizeVariants(jsonVariants);
      }

      var rowVariants = readRowsPayload(cache);

      if (rowVariants.length) {
        return U().normalizeVariants(rowVariants);
      }

      return U().normalizeVariants([]);
    } catch (error) {
      warn("Could not get variants for table.", error);
      return U().normalizeVariants([]);
    }
  }

  function getStateRevision() {
    try {
      var state = getStateApi();

      if (state && typeof state.getState === "function") {
        var snapshot = state.getState();
        return snapshot && snapshot.revision !== undefined ? snapshot.revision : null;
      }

      return null;
    } catch (error) {
      return null;
    }
  }

  function normalizeAdditionalFieldKeys(value) {
    try {
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

  function normalizeVariant(raw, index) {
    try {
      var normalized = U().normalizeVariant(raw || {});

      if (index === 0 || normalized.variant_id === "default" || normalized.is_default) {
        normalized.variant_id = "default";
        normalized.variantId = "default";
        normalized.slug = "default";
        normalized.is_default = true;
        normalized.isDefault = true;
        normalized.kind = "standard";

        if (!normalized.label || normalized.label === "Neue Variante") {
          normalized.label = "Standard";
          normalized.name = "Standard";
        }
      } else {
        normalized.is_default = false;
        normalized.isDefault = false;
      }

      if (!normalized.definition_values || typeof normalized.definition_values !== "object") {
        normalized.definition_values = U().valuesFromJson(normalized.definition_values_json);
      }

      normalized.definition_values["variant.variant_id"] = normalized.variant_id;
      normalized.definition_values["variant.label"] = normalized.label;
      normalized.definition_values_json = U().valuesToJson(normalized.definition_values);
      normalized.definitionValues = normalized.definition_values;
      normalized.definitionValuesJson = normalized.definition_values_json;

      normalized.additional_field_keys = normalizeAdditionalFieldKeys(
        normalized.additional_field_keys ||
        normalized.additionalFieldKeys ||
        normalized.additional_fields ||
        normalized.additionalFields ||
        []
      );
      normalized.additionalFieldKeys = normalized.additional_field_keys.slice();

      return normalized;
    } catch (error) {
      return U().normalizeVariant(raw || {});
    }
  }

  function fieldValue(root, selector, fallback) {
    try {
      return U().getValue(U().qs(selector, root), fallback || "");
    } catch (error) {
      return fallback || "";
    }
  }

  function payloadFromRow(row) {
    try {
      if (!row || row.nodeType !== 1) {
        return {};
      }

      var variantId = U().attr(row, "data-vp-variant-id", "") ||
        U().attr(row, "data-vp-definition-variant-id", "") ||
        fieldValue(row, "[data-vp-variant-slug]", "");

      var label = U().attr(row, "data-vp-variant-label", "") ||
        fieldValue(row, "[data-vp-variant-name]", "") ||
        fieldValue(row, "[data-vp-variant-row-display-name='true']", "");

      var profileId = U().attr(row, "data-vp-variant-profile-id", "") ||
        U().attr(row, "data-vp-definition-variant-profile-id", "") ||
        fieldValue(row, "[data-vp-row-variant-profile-id]", "");

      var valuesJson = fieldValue(row, "[data-vp-row-definition-values-json]", "");
      var additionalKeysJson = fieldValue(row, "[data-vp-row-additional-field-keys-json]", "[]");
      var summary = fieldValue(row, "[data-vp-row-definition-summary-input]", "") ||
        fieldValue(row, "[data-vp-row-definition-summary='true']", "");

      return {
        row: row,
        rowIndex: U().intValue(U().attr(row, "data-row-index", U().attr(row, "data-vp-variant-index", "")), 0),
        variant_id: variantId,
        variantId: variantId,
        label: label,
        name: label,
        slug: variantId,
        kind: U().attr(row, "data-vp-variant-kind", "") || fieldValue(row, "[data-vp-row-variant-kind]", "profile"),
        description: fieldValue(row, "[data-vp-row-variant-description]", ""),
        is_default: U().bool(U().attr(row, "data-vp-is-default", ""), false) ||
          U().bool(fieldValue(row, "[data-vp-row-is-default]", ""), false) ||
          variantId === "default",
        isDefault: U().bool(U().attr(row, "data-vp-is-default", ""), false) ||
          U().bool(fieldValue(row, "[data-vp-row-is-default]", ""), false) ||
          variantId === "default",
        family_profile_id: U().attr(row, "data-vp-family-profile-id", ""),
        familyProfileId: U().attr(row, "data-vp-family-profile-id", ""),
        variant_profile_id: profileId,
        variantProfileId: profileId,
        definition_managed: U().bool(U().attr(row, "data-vp-definition-managed", ""), false) ||
          U().bool(fieldValue(row, "[data-vp-row-definition-managed]", ""), false),
        definitionManaged: U().bool(U().attr(row, "data-vp-definition-managed", ""), false) ||
          U().bool(fieldValue(row, "[data-vp-row-definition-managed]", ""), false),
        definition_values_json: valuesJson,
        definitionValuesJson: valuesJson,
        definition_values: U().valuesFromJson(valuesJson),
        definitionValues: U().valuesFromJson(valuesJson),
        additional_field_keys: normalizeAdditionalFieldKeys(additionalKeysJson),
        additionalFieldKeys: normalizeAdditionalFieldKeys(additionalKeysJson),
        definition_summary: summary,
        definitionSummary: summary
      };
    } catch (error) {
      warn("Could not read row payload.", error);
      return {};
    }
  }

  function getProfileLabel(profileId) {
    try {
      if (!profileId) {
        return "auto";
      }

      if (
        window.VectoplanCreateVariantProfiles &&
        typeof window.VectoplanCreateVariantProfiles.getVariantProfileLocal === "function"
      ) {
        var local = window.VectoplanCreateVariantProfiles.getVariantProfileLocal(profileId);

        if (local && local.ok && local.variant_profile && local.variant_profile.label) {
          return local.variant_profile.label;
        }
      }

      return profileId;
    } catch (error) {
      return profileId || "auto";
    }
  }

  function getSummary(variant) {
    try {
      if (variant.definition_summary) {
        return variant.definition_summary;
      }

      if (getSummaryApi() && typeof getSummaryApi().buildSummary === "function") {
        var summary = getSummaryApi().buildSummary(variant.definition_values || {}, {
          id: variant.variant_profile_id || "",
          summary_fields: []
        });

        if (summary) {
          return summary;
        }
      }

      var values = variant.definition_values || {};
      var parts = [];

      [
        "dimensions.thickness_mm",
        "dimensions.width_mm",
        "dimensions.height_mm",
        "dimensions.depth_mm",
        "dimensions.length_mm",
        "material.type",
        "manufacturer.name",
        "product.designation",
        "concrete.strength_class",
        "thermal.u_value",
        "physics.u_value",
        "commercial.price_per_piece",
        "commercial.price_per_m2",
        "commercial.price_per_m3"
      ].forEach(function (key) {
        var value = values[key];

        if (value === null || value === undefined || value === "") {
          return;
        }

        parts.push(String(value));
      });

      if (parts.length) {
        return parts.join(" · ");
      }

      return variant.is_default ? "Standardvariante" : "Noch keine Kurzwerte";
    } catch (error) {
      return variant && variant.is_default ? "Standardvariante" : "Noch keine Kurzwerte";
    }
  }

  function getVariantDisplayName(variant) {
    try {
      return variant.label || variant.name || (variant.is_default ? "Standard" : "Neue Variante");
    } catch (error) {
      return "Neue Variante";
    }
  }

  function getVariantId(variant) {
    try {
      return variant.variant_id || variant.slug || "variant";
    } catch (error) {
      return "variant";
    }
  }

  function createHiddenInput(index, name, value, hooks) {
    try {
      return U().createElement("input", {
        type: "hidden",
        value: value === null || value === undefined ? "" : value,
        attrs: U().safeMerge({
          name: "variants[" + String(index) + "][" + name + "]"
        }, hooks || {})
      });
    } catch (error) {
      return document.createElement("input");
    }
  }

  function createHiddenFields(variant, index) {
    try {
      var hidden = U().createElement("div", {
        class: "vp-create-variant-row__hidden",
        hidden: true,
        attrs: {
          "data-vp-variant-row-hidden-fields": "true"
        }
      });

      hidden.appendChild(createHiddenInput(index, "is_default", variant.is_default ? "true" : "false", {
        "data-create-field": "variant_is_default",
        "data-vp-row-is-default": "true"
      }));

      hidden.appendChild(createHiddenInput(index, "name", getVariantDisplayName(variant), {
        "data-create-field": "variant_name",
        "data-vp-variant-name": "true"
      }));

      hidden.appendChild(createHiddenInput(index, "slug", getVariantId(variant), {
        "data-create-field": "variant_slug",
        "data-vp-variant-slug": "true"
      }));

      hidden.appendChild(createHiddenInput(index, "kind", variant.kind || (variant.is_default ? "standard" : "profile"), {
        "data-create-field": "variant_kind",
        "data-vp-row-variant-kind": "true"
      }));

      hidden.appendChild(createHiddenInput(index, "description", variant.description || "", {
        "data-create-field": "variant_description",
        "data-vp-row-variant-description": "true"
      }));

      hidden.appendChild(createHiddenInput(index, "family_profile_id", variant.family_profile_id || "", {
        "data-create-field": "family_profile_id",
        "data-vp-row-family-profile-id": "true"
      }));

      hidden.appendChild(createHiddenInput(index, "variant_profile_id", variant.variant_profile_id || "", {
        "data-create-field": "variant_profile_id",
        "data-vp-row-variant-profile-id": "true"
      }));

      hidden.appendChild(createHiddenInput(index, "definition_values_json", variant.definition_values_json || U().valuesToJson(variant.definition_values || {}), {
        "data-vp-row-definition-values-json": "true"
      }));

      hidden.appendChild(createHiddenInput(index, "additional_field_keys_json", U().safeJsonStringify(normalizeAdditionalFieldKeys(variant.additional_field_keys || variant.additionalFieldKeys || []), "[]"), {
        "data-vp-row-additional-field-keys-json": "true"
      }));

      hidden.appendChild(createHiddenInput(index, "definition_summary", getSummary(variant), {
        "data-vp-row-definition-summary-input": "true"
      }));

      hidden.appendChild(createHiddenInput(index, "definition_managed", variant.definition_managed ? "true" : "", {
        "data-vp-row-definition-managed": "true"
      }));

      return hidden;
    } catch (error) {
      warn("Could not create hidden fields.", error);
      return U().createElement("div", {
        hidden: true
      });
    }
  }

  function createCell(className, children) {
    try {
      return U().createElement("div", {
        class: "vp-create-variant-row__cell " + className,
        attrs: {
          role: "cell"
        }
      }, children || []);
    } catch (error) {
      return document.createElement("div");
    }
  }

  function createDefaultCell(variant) {
    try {
      return createCell("vp-create-variant-row__cell--default", [
        U().createElement("span", {
          class: "vp-create-variant-default-pill" + (variant.is_default ? " vp-create-variant-default-pill--active" : ""),
          text: variant.is_default ? "Default" : "Nein",
          attrs: {
            "data-vp-default-label": "true"
          }
        })
      ]);
    } catch (error) {
      return createCell("vp-create-variant-row__cell--default", []);
    }
  }

  function createVariantCell(variant) {
    try {
      var titleWrap = U().createElement("div", {
        class: "vp-create-variant-row__title-wrap"
      }, [
        U().createElement("strong", {
          class: "vp-create-variant-row__title",
          text: getVariantDisplayName(variant),
          attrs: {
            "data-vp-variant-row-display-name": "true"
          }
        })
      ]);

      var children = [titleWrap];

      if (variant.description) {
        children.push(U().createElement("p", {
          class: "vp-create-variant-row__description",
          text: variant.description,
          attrs: {
            "data-vp-variant-row-display-description": "true"
          }
        }));
      }

      return createCell("vp-create-variant-row__cell--variant", children);
    } catch (error) {
      return createCell("vp-create-variant-row__cell--variant", []);
    }
  }

  function createProfileCell(variant) {
    try {
      var children = [
        U().createElement("span", {
          class: "vp-create-definition-profile-pill",
          text: variant.variant_profile_id ? getProfileLabel(variant.variant_profile_id) : "auto",
          attrs: {
            "data-vp-row-profile-pill": "true",
            "data-vp-row-profile-id": variant.variant_profile_id || ""
          }
        })
      ];

      if (variant.definition_managed || variant.variant_profile_id) {
        children.push(U().createElement("span", {
          class: "vp-create-variant-managed-pill",
          text: "Definitionsprofil",
          attrs: {
            "data-vp-row-managed-pill": "true"
          }
        }));
      }

      return createCell("vp-create-variant-row__cell--profile", children);
    } catch (error) {
      return createCell("vp-create-variant-row__cell--profile", []);
    }
  }

  function createSummaryCell(variant) {
    try {
      var additionalKeys = normalizeAdditionalFieldKeys(variant.additional_field_keys || variant.additionalFieldKeys || []);
      var children = [
        U().createElement("div", {
          class: "vp-create-definition-summary",
          text: getSummary(variant),
          attrs: {
            "data-vp-row-definition-summary": "true"
          }
        })
      ];

      if (additionalKeys.length) {
        children.push(U().createElement("span", {
          class: "vp-create-definition-summary__additional-count",
          text: additionalKeys.length === 1 ? "1 Zusatzfeld" : String(additionalKeys.length) + " Zusatzfelder",
          attrs: {
            "data-vp-row-additional-field-count": String(additionalKeys.length)
          }
        }));
      }

      return createCell("vp-create-variant-row__cell--summary", children);
    } catch (error) {
      return createCell("vp-create-variant-row__cell--summary", []);
    }
  }

  function createActionsCell(variant) {
    try {
      var actions = U().createElement("div", {
        class: "vp-create-row-action vp-create-row-action--definition"
      });

      actions.appendChild(U().createElement("button", {
        class: "vp-create-button vp-create-button--ghost",
        type: "button",
        text: "Bearbeiten",
        attrs: {
          "data-vp-edit-definition-variant": "true",
          "data-vp-variant-action": "edit",
          "aria-label": "Variante bearbeiten: " + getVariantDisplayName(variant)
        }
      }));

      if (variant.is_default || variant.variant_id === "default") {
        actions.appendChild(U().createElement("button", {
          class: "vp-create-button vp-create-button--ghost",
          type: "button",
          text: "Fix",
          disabled: true,
          attrs: {
            "data-create-static-disabled": "true",
            "data-vp-variant-action": "locked",
            "aria-disabled": "true",
            title: "Die Default-Variante kann nicht entfernt werden."
          }
        }));
      } else {
        actions.appendChild(U().createElement("button", {
          class: "vp-create-button vp-create-button--ghost",
          type: "button",
          text: "Entfernen",
          attrs: {
            "data-vp-remove-definition-variant": "true",
            "data-vp-variant-action": "remove",
            "aria-label": "Variante entfernen: " + getVariantDisplayName(variant)
          }
        }));
      }

      return createCell("vp-create-variant-row__cell--actions", [
        actions
      ]);
    } catch (error) {
      return createCell("vp-create-variant-row__cell--actions", []);
    }
  }

  function createRow(variant, index) {
    try {
      var normalized = normalizeVariant(variant, index);
      var additionalKeys = normalizeAdditionalFieldKeys(normalized.additional_field_keys || normalized.additionalFieldKeys || []);
      var rowClass = [
        "vp-create-variant-row",
        "vp-create-variant-row--definition",
        "vp-create-variant-row--readonly"
      ];

      if (normalized.is_default) {
        rowClass.push("vp-create-variant-row--default");
      }

      if (normalized.definition_managed || normalized.variant_profile_id) {
        rowClass.push("vp-create-variant-row--managed");
      }

      if (additionalKeys.length) {
        rowClass.push("vp-create-variant-row--has-additional-fields");
      }

      var row = U().createElement("div", {
        class: rowClass.join(" "),
        attrs: {
          role: "row",
          "data-vp-variant-row": "true",
          "data-create-variant-row": "true",
          "data-vp-variant-row-readonly": "true",
          "data-row-index": String(index),
          "data-vp-variant-index": String(index),
          "data-vp-variant-id": normalized.variant_id,
          "data-vp-definition-variant-id": normalized.variant_id,
          "data-vp-variant-label": normalized.label,
          "data-vp-variant-kind": normalized.kind || "",
          "data-vp-variant-profile-id": normalized.variant_profile_id || "",
          "data-vp-definition-variant-profile-id": normalized.variant_profile_id || "",
          "data-vp-family-profile-id": normalized.family_profile_id || "",
          "data-vp-definition-managed": normalized.definition_managed ? "true" : "false",
          "data-vp-is-default": normalized.is_default ? "true" : "false",
          "data-vp-additional-field-count": String(additionalKeys.length)
        }
      });

      row.appendChild(createDefaultCell(normalized));
      row.appendChild(createVariantCell(normalized));
      row.appendChild(createProfileCell(normalized));
      row.appendChild(createSummaryCell(normalized));
      row.appendChild(createActionsCell(normalized));
      row.appendChild(createHiddenFields(normalized, index));

      return row;
    } catch (error) {
      warn("Could not create variant row.", error);
      return U().createElement("div", {
        class: "vp-create-variant-row vp-create-variant-row--error",
        text: "Variante konnte nicht gerendert werden."
      });
    }
  }

  function renderSignature(variants) {
    try {
      return U().safeJsonStringify(U().toArray(variants).map(function (variant) {
        return {
          id: variant.variant_id || variant.variantId || variant.slug || "",
          label: variant.label || variant.name || "",
          profile: variant.variant_profile_id || variant.variantProfileId || "",
          default: !!variant.is_default,
          summary: variant.definition_summary || variant.definitionSummary || "",
          values: variant.definition_values || variant.definitionValues || {},
          additional: variant.additional_field_keys || variant.additionalFieldKeys || []
        };
      }), "[]");
    } catch (error) {
      return String(Date.now());
    }
  }

  function preserveFocusBeforeRender(cache) {
    try {
      if (!runtime.options.preserveFocus) {
        return null;
      }

      var active = document.activeElement;

      if (!active || !cache.table || !cache.table.contains(active)) {
        return null;
      }

      var row = U().closest(active, ROW_SELECTOR);

      return {
        variantId: row ? U().attr(row, "data-vp-variant-id", "") : "",
        action: U().attr(active, "data-vp-variant-action", "") ||
          U().attr(active, "data-vp-variant-footer-action", "") ||
          "",
        text: active.textContent || ""
      };
    } catch (error) {
      return null;
    }
  }

  function restoreFocusAfterRender(cache, focusState) {
    try {
      if (!focusState || !cache.table || isEditorOpen()) {
        return;
      }

      var selector = "";

      if (focusState.variantId) {
        selector = "[data-vp-variant-id='" + cssEscape(focusState.variantId) + "'] ";
      }

      if (focusState.action) {
        selector += "[data-vp-variant-action='" + cssEscape(focusState.action) + "']";
      }

      if (!selector.trim()) {
        return;
      }

      var target = U().qs(selector, cache.table);

      if (target && typeof target.focus === "function") {
        window.setTimeout(function () {
          try {
            target.focus();
          } catch (focusError) {
            /* no-op */
          }
        }, 0);
      }
    } catch (error) {
      /* no-op */
    }
  }

  function render(variants, options) {
    try {
      var config = options || {};
      var cache = cacheDom(config.root || null);
      var normalizedVariants = U().normalizeVariants(variants || getVariants());

      updateTableMeta(cache, normalizedVariants, {
        source: config.source || "render_meta_before_visibility",
        emitNativeEvents: config.emitNativeEvents === true
      });

      if (!shouldRenderVisibleTable(config)) {
        return true;
      }

      if (!cache.table || !cache.body) {
        return false;
      }

      if (runtime.rendering && config.force !== true) {
        scheduleRender(variants, config);
        return false;
      }

      var signature = renderSignature(normalizedVariants);

      if (config.force !== true && signature === runtime.lastRenderSignature && runtime.lastRevision === getStateRevision()) {
        runtime.suppressedRenderCount += 1;
        updateTableMeta(cache, normalizedVariants, {
          source: config.source || "render_noop",
          emitNativeEvents: false
        });
        return true;
      }

      runtime.rendering = true;

      var focusState = preserveFocusBeforeRender(cache);

      U().dispatchDocument("vectoplan:create:variant-table-render-started", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        source: config.source || "render",
        count: normalizedVariants.length,
        variants: normalizedVariants,
        __vp_variant_table_event: true
      }, {
        silent: true
      });

      U().empty(cache.body);

      normalizedVariants.forEach(function (variant, index) {
        cache.body.appendChild(createRow(variant, index));
      });

      updateTableMeta(cache, normalizedVariants, {
        source: config.source || "render",
        emitNativeEvents: config.emitNativeEvents === true
      });
      updateEmptyState(cache, normalizedVariants);
      bindTableEvents(cache.table);
      restoreFocusAfterRender(cache, focusState);

      runtime.lastRevision = getStateRevision();
      runtime.lastRenderAt = Date.now();
      runtime.lastRenderSignature = signature;
      runtime.rendering = false;

      U().dispatchDocument("vectoplan:create:variant-table-rendered", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        source: config.source || "render",
        count: normalizedVariants.length,
        variants: normalizedVariants,
        tableId: U().attr(cache.table, "id", ""),
        __vp_variant_table_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      runtime.rendering = false;
      warn("Could not render variant table.", error);

      U().dispatchDocument("vectoplan:create:variant-table-render-failed", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        error: normalizeError(error),
        __vp_variant_table_event: true
      }, {
        silent: true
      });

      return false;
    }
  }

  function scheduleRender(variants, options) {
    try {
      var config = options || {};

      if (isEditorOpen() && runtime.options.autoRenderWhileEditorOpen !== true && config.force !== true && config.renderWhileEditorOpen !== true) {
        runtime.pendingRenderAfterEditorClose = true;
        runtime.suppressedEditorRenderCount += 1;
        syncJsonField(runtime.cache || cacheDom(), variants || getVariants(), {
          source: config.source || "scheduled_render_suppressed_editor_open",
          emitNativeEvents: false
        });
        return;
      }

      if (runtime.renderScheduled) {
        runtime.suppressedRenderCount += 1;
        return;
      }

      runtime.renderScheduled = true;

      window.setTimeout(function () {
        try {
          runtime.renderScheduled = false;
          render(variants || getVariants(), config);
        } catch (error) {
          runtime.renderScheduled = false;
          warn("Scheduled render failed.", error);
        }
      }, 40);
    } catch (error) {
      runtime.renderScheduled = false;
      warn("Could not schedule variant table render.", error);
    }
  }

  function renderFromState(options) {
    try {
      return render(getVariants(), options || {});
    } catch (error) {
      warn("Could not render variant table from state.", error);
      return false;
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

  function updateTableMeta(cache, variants, options) {
    try {
      var config = options || {};
      var c = cache || runtime.cache || cacheDom();
      var list = U().toArray(variants);
      var count = list.length;
      var defaultVariant = list.filter(function (variant) {
        return variant.is_default || variant.variant_id === "default";
      })[0] || list[0] || null;
      var defaultId = defaultVariant ? defaultVariant.variant_id : "default";
      var firstProfile = list.filter(function (variant) {
        return !!variant.variant_profile_id;
      })[0];
      var changed = false;

      if (c.table) {
        changed = setAttrIfChanged(c.table, "data-vp-variant-count", String(count)) || changed;
        changed = setAttrIfChanged(c.table, "data-vp-default-variant-id", defaultId) || changed;

        if (firstProfile && firstProfile.variant_profile_id) {
          changed = setAttrIfChanged(c.table, "data-vp-variant-profile-id", firstProfile.variant_profile_id) || changed;
        }

        if (firstProfile && firstProfile.family_profile_id) {
          changed = setAttrIfChanged(c.table, "data-vp-family-profile-id", firstProfile.family_profile_id) || changed;
        }
      }

      if (c.workspace) {
        changed = setAttrIfChanged(c.workspace, "data-vp-variant-count", String(count)) || changed;
        changed = setAttrIfChanged(c.workspace, "data-vp-default-variant-id", defaultId) || changed;
      }

      if (c.defaultField) {
        changed = U().setValue(c.defaultField, defaultId, false) || changed;
      }

      if (c.countLabel) {
        changed = setTextIfChanged(c.countLabel, count === 1 ? "1 Variante" : String(count) + " Varianten") || changed;
      }

      changed = syncJsonField(c, list, {
        source: config.source || "table_meta",
        emitNativeEvents: config.emitNativeEvents === true
      }) || changed;

      return changed;
    } catch (error) {
      warn("Could not update table meta.", error);
      return false;
    }
  }

  function updateEmptyState(cache, variants) {
    try {
      if (!cache.empty) {
        return true;
      }

      var count = U().toArray(variants).length;
      U().setHidden(cache.empty, count > 0);

      return true;
    } catch (error) {
      warn("Could not update table empty state.", error);
      return false;
    }
  }

  function syncJsonField(cache, variants, options) {
    try {
      var config = options || {};

      if (!cache || !cache.jsonField) {
        return false;
      }

      var normalized = U().normalizeVariants(U().toArray(variants));
      var json = U().safeJsonStringify(normalized, "[]");

      if (cache.jsonField.value === json && runtime.lastJsonFieldValue === json) {
        return false;
      }

      cache.jsonField.value = json;
      runtime.lastJsonFieldValue = json;

      U().setAttr(cache.jsonField, "data-vp-last-table-sync", String(Date.now()));
      U().setAttr(cache.jsonField, "data-vp-last-table-sync-source", config.source || "variant_table");
      U().setAttr(cache.jsonField, "data-vp-programmatic-event-source", COMPONENT_NAME);

      if (config.emitNativeEvents === true) {
        U().dispatchNative(cache.jsonField, "input", {
          source: COMPONENT_NAME,
          silent: true
        });
        U().dispatchNative(cache.jsonField, "change", {
          source: COMPONENT_NAME,
          silent: true
        });
      }

      return true;
    } catch (error) {
      warn("Could not sync definition_variants_json from table.", error);
      return false;
    }
  }

  function requestEdit(row) {
    try {
      if (!row) {
        return false;
      }

      var payload = payloadFromRow(row);

      setEditorMode("open", {
        source: "table_request_edit",
        forceEvent: true
      });

      if (getDrawerApi() && typeof getDrawerApi().open === "function") {
        Promise.resolve(getDrawerApi().open(payload)).catch(function (error) {
          warn("Drawer open from table edit failed.", error);

          setEditorMode("closed", {
            source: "table_request_edit_failed",
            forceEvent: true,
            renderAfterClose: true
          });
        });
        return true;
      }

      U().dispatchDocument("vectoplan:create:variant-edit-requested", U().safeMerge(payload, {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        source: "variant_table",
        __vp_variant_table_event: true
      }), {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not request variant edit.", error);
      return false;
    }
  }

  function requestRemove(row) {
    try {
      if (!row) {
        return false;
      }

      var payload = payloadFromRow(row);

      if (payload.is_default || payload.variant_id === "default") {
        U().dispatchDocument("vectoplan:create:variant-remove-blocked", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          source: "variant_table",
          reason: "default_variant_locked",
          variant: payload,
          __vp_variant_table_event: true
        }, {
          silent: true
        });

        return false;
      }

      if (getStateApi() && typeof getStateApi().removeVariant === "function") {
        getStateApi().removeVariant(payload.variant_id || payload.rowIndex, {
          source: "table_remove",
          emitNativeEvents: false
        });
        return true;
      }

      U().dispatchDocument("vectoplan:create:variant-state-remove-requested", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        source: "variant_table",
        variant_id: payload.variant_id,
        variantId: payload.variant_id,
        rowIndex: payload.rowIndex,
        variant: payload,
        __vp_variant_table_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not request variant remove.", error);
      return false;
    }
  }

  function bindTableEvents(table) {
    try {
      var root = table || (runtime.cache && runtime.cache.table);

      if (!root || U().attr(root, "data-vp-variant-table-controller-events-bound", "") === "true") {
        return false;
      }

      root.addEventListener("click", function (event) {
        try {
          if (event.defaultPrevented) {
            return;
          }

          var target = event.target;

          if (!target || !target.closest) {
            return;
          }

          var now = Date.now();

          if (now - runtime.lastClickAt < 80) {
            return;
          }

          var editButton = target.closest("[data-vp-edit-definition-variant='true']");

          if (editButton && root.contains(editButton)) {
            event.preventDefault();
            runtime.lastClickAt = now;
            requestEdit(editButton.closest(ROW_SELECTOR));
            return;
          }

          var removeButton = target.closest("[data-vp-remove-definition-variant='true'], [data-create-remove-row='true']");

          if (removeButton && root.contains(removeButton)) {
            event.preventDefault();
            runtime.lastClickAt = now;
            requestRemove(removeButton.closest(ROW_SELECTOR));
          }
        } catch (error) {
          warn("Table click handling failed.", error);
        }
      });

      U().setAttr(root, "data-vp-variant-table-controller-events-bound", "true");
      return true;
    } catch (error) {
      warn("Could not bind table events.", error);
      return false;
    }
  }

  function syncAndMaybeRender(detail, fallbackSource) {
    try {
      var source = detail && detail.source ? detail.source : fallbackSource;
      var variants = detail && detail.variants ? detail.variants : getVariants();

      if (isEditorOpen() && runtime.options.autoRenderWhileEditorOpen !== true) {
        runtime.pendingRenderAfterEditorClose = true;
        runtime.suppressedEditorRenderCount += 1;
        syncJsonField(runtime.cache || cacheDom(), variants, {
          source: source || "editor_open_sync",
          emitNativeEvents: false
        });
        return;
      }

      scheduleRender(variants, {
        source: source || fallbackSource
      });
    } catch (error) {
      warn("Could not sync/render table.", error);
    }
  }

  function bindGlobalEvents() {
    try {
      if (runtime.globalEventsBound) {
        return;
      }

      document.addEventListener("vectoplan:create:variant-state-ready", function (event) {
        var detail = event && event.detail ? event.detail : {};
        renderFromState({
          source: detail.source || "state_ready"
        });
      });

      document.addEventListener("vectoplan:create:variant-state-changed", function (event) {
        try {
          if (!runtime.options.autoRender) {
            return;
          }

          var detail = event && event.detail ? event.detail : {};
          var revision = detail.revision;

          if (revision !== undefined && revision !== null && revision === runtime.lastRevision) {
            return;
          }

          syncAndMaybeRender(detail, "state_changed");
        } catch (error) {
          warn("State changed render listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-state-synced", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          syncJsonField(runtime.cache || cacheDom(), detail.variants || getVariants(), {
            source: detail.source || "state_synced",
            emitNativeEvents: false
          });
        } catch (error) {
          warn("State synced table listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-added", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          syncAndMaybeRender(detail, "variant_added");
        } catch (error) {
          warn("Variant added render listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-updated", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          syncAndMaybeRender(detail, "variant_updated");
        } catch (error) {
          warn("Variant updated render listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-removed", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          syncAndMaybeRender(detail, "variant_removed");
        } catch (error) {
          warn("Variant removed render listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-workspace-ready", function () {
        cacheDom();
        bindTableEvents(runtime.cache.table);
        renderFromState({
          source: "workspace_ready"
        });
      });

      document.addEventListener("vectoplan:create:variant-profile-resolved", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var cache = runtime.cache || cacheDom();

          if (cache.table) {
            if (detail.variant_profile_id || detail.variantProfileId) {
              setAttrIfChanged(cache.table, "data-vp-variant-profile-id", detail.variant_profile_id || detail.variantProfileId);
            }

            if (detail.family_profile_id || detail.familyProfileId) {
              setAttrIfChanged(cache.table, "data-vp-family-profile-id", detail.family_profile_id || detail.familyProfileId);
            }
          }
        } catch (error) {
          warn("Profile resolved table listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-editor-mode-changed", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          setEditorMode(detail.mode || detail.editorMode || (detail.open ? "open" : "closed"), {
            source: detail.source || "external_editor_mode_changed",
            forceEvent: false,
            renderAfterClose: detail.open === false || detail.mode === "closed"
          });
        } catch (error) {
          warn("Editor mode listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-editor-opened", function () {
        setEditorMode("open", {
          source: "variant_editor_opened",
          forceEvent: false
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-opened", function () {
        setEditorMode("open", {
          source: "variant_drawer_opened",
          forceEvent: false
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-session-started", function () {
        setEditorMode("open", {
          source: "drawer_session_started",
          forceEvent: false
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-session-prepared", function () {
        setEditorMode("open", {
          source: "drawer_session_prepared",
          forceEvent: false
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-apply-finished", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          setEditorMode("closed", {
            source: "drawer_apply_finished",
            forceEvent: false,
            renderAfterClose: true
          });

          window.setTimeout(function () {
            renderFromState({
              source: detail.source || "drawer_apply_finished",
              force: true,
              emitNativeEvents: false
            });
          }, 60);
        } catch (error) {
          warn("Drawer apply finished table listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-drawer-apply-failed", function () {
        setEditorMode("open", {
          source: "drawer_apply_failed",
          forceEvent: false
        });
      });

      document.addEventListener("vectoplan:create:variant-editor-closed", function () {
        setEditorMode("closed", {
          source: "variant_editor_closed",
          forceEvent: false,
          renderAfterClose: true
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-closed", function () {
        setEditorMode("closed", {
          source: "variant_drawer_closed",
          forceEvent: false,
          renderAfterClose: true
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-reset", function () {
        setEditorMode("closed", {
          source: "drawer_reset",
          forceEvent: false,
          renderAfterClose: true
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-cancel-requested", function () {
        setEditorMode("closed", {
          source: "drawer_cancel_requested",
          forceEvent: false,
          renderAfterClose: true
        });
      });

      document.addEventListener("vectoplan:create:variant-empty-state-close-requested", function () {
        setEditorMode("closed", {
          source: "empty_state_close_requested",
          forceEvent: false,
          renderAfterClose: true
        });
      });

      runtime.globalEventsBound = true;
    } catch (error) {
      warn("Could not bind table global events.", error);
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
      var cache = runtime.cache || cacheDom();

      return {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        initialized: runtime.initialized,
        rendering: runtime.rendering,
        renderScheduled: runtime.renderScheduled,
        editorMode: runtime.editorMode,
        pendingRenderAfterEditorClose: runtime.pendingRenderAfterEditorClose,
        autoRender: runtime.options.autoRender,
        autoRenderWhileEditorOpen: runtime.options.autoRenderWhileEditorOpen,
        emitNativeEvents: runtime.options.emitNativeEvents,
        lastRevision: runtime.lastRevision,
        lastJsonFieldLength: runtime.lastJsonFieldValue ? runtime.lastJsonFieldValue.length : 0,
        suppressedRenderCount: runtime.suppressedRenderCount,
        suppressedSyncCount: runtime.suppressedSyncCount,
        suppressedEditorRenderCount: runtime.suppressedEditorRenderCount,
        hasWorkspace: !!cache.workspace,
        hasTableSlot: !!cache.tableSlot,
        hasDrawerSlot: !!cache.drawerSlot,
        hasTable: !!cache.table,
        hasBody: !!cache.body,
        rowCount: cache.table ? U().qsa(ROW_SELECTOR, cache.table).length : 0,
        stateAvailable: !!getStateApi(),
        drawerAvailable: !!getDrawerApi(),
        previousApiPresent: !!previousApi
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

      var cache = cacheDom(config.root || null);

      bindTableEvents(cache.table);
      bindGlobalEvents();

      runtime.initialized = true;

      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-table-controller-version", COMPONENT_VERSION);

      setEditorMode(runtime.editorMode || "closed", {
        source: config.source || "initialize",
        forceEvent: false,
        keepDrawerSlotVisible: false
      });

      if (config.render !== false) {
        renderFromState({
          source: config.source || "initialize",
          emitNativeEvents: config.emitNativeEvents === true
        });
      }

      U().dispatchDocument("vectoplan:create:variant-table-controller-ready", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        source: config.source || "initialize",
        snapshot: getRuntimeSnapshot(),
        __vp_variant_table_event: true
      }, {
        silent: true
      });

      return true;
    } catch (error) {
      warn("Could not initialize variant table controller.", error);
      return false;
    }
  }

  var api = U().safeMerge(previousApi || {}, {
    __name: COMPONENT_NAME,
    __version: COMPONENT_VERSION,
    __controllerVersion: COMPONENT_VERSION,

    initialize: initialize,

    cacheDom: cacheDom,
    render: render,
    renderFromState: renderFromState,
    scheduleRender: scheduleRender,
    refresh: function () {
      return renderFromState({
        source: "api_refresh",
        force: true,
        emitNativeEvents: false
      });
    },

    setEditorMode: setEditorMode,
    isEditorOpen: isEditorOpen,

    getVariants: getVariants,
    getRows: function (table) {
      try {
        return U().qsa(ROW_SELECTOR, table || (runtime.cache && runtime.cache.table) || document);
      } catch (error) {
        return [];
      }
    },
    getPayloads: function () {
      return readRowsPayload(runtime.cache || cacheDom());
    },
    getRowPayload: payloadFromRow,
    payloadFromRow: payloadFromRow,

    requestEdit: requestEdit,
    requestRemove: requestRemove,

    createRow: createRow,
    bindTableEvents: bindTableEvents,

    getRuntimeSnapshot: getRuntimeSnapshot,

    setAutoRender: function (enabled) {
      runtime.options.autoRender = !!enabled;
    },

    setAutoRenderWhileEditorOpen: function (enabled) {
      runtime.options.autoRenderWhileEditorOpen = !!enabled;
    },

    setEmitNativeEvents: function (enabled) {
      runtime.options.emitNativeEvents = !!enabled;
    }
  });

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
    warn("Could not bootstrap variant table controller.", bootstrapError);
  }
})();