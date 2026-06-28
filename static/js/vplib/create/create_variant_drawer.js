// services/vectoplan-library/static/js/vplib/create/create_variant_drawer.js
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateVariantDrawer";
  var COMPONENT_NAME = "VECTOPLAN Create Variant Drawer";
  var COMPONENT_VERSION = "0.7.0";
  var READY_ATTR = "data-vp-create-variant-drawer-ready";

  var DRAWER_SELECTOR = "[data-vp-variant-drawer-root='true'], [data-vp-variant-drawer='true'], .vp-create-variant-drawer";
  var WORKSPACE_SELECTOR = "[data-vp-variant-workspace-root='true'], [data-vp-variant-workspace='true'], .vp-create-variant-workspace";
  var TABLE_SELECTOR = "[data-vp-variant-table-root='true'], [data-vp-variant-table='true'], [data-create-variant-table='true']";
  var ROW_SELECTOR = "[data-vp-variant-row='true'], [data-create-variant-row='true']";

  var OBJECT_VARIANTS_SECTION_SELECTOR = [
    "[data-vp-create-section='object-variants']",
    "[data-create-section='object-variants']",
    ".vp-create-section--object-variants"
  ].join(",");

  var OBJECT_VARIANTS_TOP_SELECTOR = [
    "[data-vp-object-variants-top='true']",
    "[data-vp-object-kind-area='true']",
    ".vp-create-object-variants__top"
  ].join(",");

  var CONTROL_SELECTOR = [
    "[data-vp-field-input='true']",
    "[data-vp-field-control-input='true']",
    "[data-vp-definition-value-key]",
    "[name^='definition_values[']"
  ].join(",");

  var TABLE_SLOT_SELECTOR = [
    "[data-vp-variant-table-slot='true']",
    ".vp-create-variant-workspace__table-slot"
  ].join(",");

  var DRAWER_SLOT_SELECTOR = [
    "[data-vp-variant-drawer-slot='true']",
    ".vp-create-variant-workspace__drawer-slot"
  ].join(",");

  var SECTION_NAV_SELECTOR = [
    "[data-vp-variant-drawer-section-nav='true']",
    "[data-vp-section-nav='true']",
    ".vp-create-variant-drawer__section-nav"
  ].join(",");

  var SECTION_NAV_ITEM_SELECTOR = [
    "[data-vp-variant-drawer-section-nav-item='true']",
    "[data-vp-section-nav-item='true']",
    "[data-vp-section-target]",
    "[data-vp-section-key]",
    "[data-section-target]",
    "[data-section-key]",
    "[aria-controls]",
    ".vp-create-variant-drawer__section-nav-item"
  ].join(",");

  var SECTION_SELECTOR = [
    "[data-vp-variant-drawer-section='true']",
    "[data-vp-section='true']",
    "[data-vp-section-id]",
    "[data-vp-section-key]",
    ".vp-create-variant-drawer__section"
  ].join(",");

  if (window[GLOBAL_NAME] && window[GLOBAL_NAME].__version === COMPONENT_VERSION) {
    try {
      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-drawer-version", COMPONENT_VERSION);
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

    qs: function (selector, root) {
      try {
        if (!selector) {
          return null;
        }

        return (root || document).querySelector(selector);
      } catch (error) {
        return null;
      }
    },

    qsa: function (selector, root) {
      try {
        if (!selector) {
          return [];
        }

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
          if (node.hasAttribute(name)) {
            node.removeAttribute(name);
            return true;
          }

          return false;
        }

        if (node.getAttribute(name) === String(value)) {
          return false;
        }

        node.setAttribute(name, String(value));
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

        var changed = false;

        if (node.type === "checkbox") {
          var nextChecked = !!value;
          var nextCheckboxValue = nextChecked ? "true" : "false";

          if (node.checked !== nextChecked) {
            node.checked = nextChecked;
            changed = true;
          }

          if (node.value !== nextCheckboxValue) {
            node.value = nextCheckboxValue;
            changed = true;
          }
        } else {
          var nextValue = value === null || value === undefined ? "" : String(value);

          if (node.value !== nextValue) {
            node.value = nextValue;
            changed = true;
          }
        }

        if (changed && dispatchEvents) {
          fallbackUtils.dispatchNative(node, "input", {
            source: COMPONENT_NAME
          });
          fallbackUtils.dispatchNative(node, "change", {
            source: COMPONENT_NAME
          });
        }

        return changed;
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

        var next = !!hidden;
        var changed = node.hidden !== next;

        node.hidden = next;

        if (next) {
          if (!node.hasAttribute("hidden")) {
            node.setAttribute("hidden", "");
            changed = true;
          }

          if (node.getAttribute("aria-hidden") !== "true") {
            node.setAttribute("aria-hidden", "true");
            changed = true;
          }
        } else {
          if (node.hasAttribute("hidden")) {
            node.removeAttribute("hidden");
            changed = true;
          }

          if (node.hasAttribute("aria-hidden")) {
            node.removeAttribute("aria-hidden");
            changed = true;
          }
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

        var changed = node.disabled !== !!disabled;

        node.disabled = !!disabled;

        if (disabled) {
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

    bool: function (value, fallback) {
      try {
        if (typeof value === "boolean") {
          return value;
        }

        var text = String(value === null || value === undefined ? "" : value).trim().toLowerCase();

        if (["true", "1", "yes", "ja", "on", "ok", "enabled", "active", "ready"].indexOf(text) !== -1) {
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
          if (item) {
            existing[String(item)] = true;
          }
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
        var explicit = config.explicitId || config.explicit_id || "";

        if (explicit) {
          return fallbackUtils.ensureUniqueId(explicit, config.existingIds || []);
        }

        var profile = config.variantProfileId || config.variant_profile_id || "variant";
        var label = config.label || "";
        var base = profile
          ? fallbackUtils.slugify(String(profile).replace(/\./g, "_"), "variant")
          : fallbackUtils.slugify(label, "variant");

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
      return fallbackUtils.safeJsonStringify(value || {}, "{}", 0);
    },

    buildSummary: function (values, profile) {
      try {
        var parts = [];
        var fields = fallbackUtils.toArray(profile && profile.summary_fields);

        fields.forEach(function (fieldKey) {
          var value = values[fieldKey];

          if (value === null || value === undefined || value === "" || fieldKey === "variant.label") {
            return;
          }

          parts.push(String(fieldKey) + ": " + String(value));
        });

        return parts.join(" · ");
      } catch (error) {
        return "";
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

  var runtime = {
    initialized: false,
    globalEventsBound: false,
    active: null,
    cache: null,
    editorMode: "closed",
    activeSectionId: "",
    lastOpenAt: 0,
    lastApplyAt: 0,
    lastValidateAt: 0,
    lastCloseAt: 0,
    lastSectionAt: 0,
    sessionSeq: 0
  };

  function shellApi() {
    return window.VectoplanCreateVariantDrawerShell || null;
  }

  function profilesApi() {
    return window.VectoplanCreateVariantProfiles || null;
  }

  function fieldRendererApi() {
    return window.VectoplanCreateVariantFieldRenderer || null;
  }

  function stateApi() {
    return window.VectoplanCreateVariantState || null;
  }

  function validationApi() {
    return window.VectoplanCreateVariantValidation || null;
  }

  function summaryApi() {
    return window.VectoplanCreateVariantSummary || null;
  }

  function optionalFieldsApi() {
    return window.VectoplanCreateVariantOptionalFields || null;
  }

  function getDrawer(root) {
    try {
      if (root && root.nodeType === 1) {
        if (root.matches && root.matches(DRAWER_SELECTOR)) {
          return root;
        }

        var closestDrawer = root.closest ? root.closest(DRAWER_SELECTOR) : null;

        if (closestDrawer) {
          return closestDrawer;
        }
      }

      return U().qs(DRAWER_SELECTOR);
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

        var closestWorkspace = root.closest ? root.closest(WORKSPACE_SELECTOR) : null;

        if (closestWorkspace) {
          return closestWorkspace;
        }
      }

      return U().qs(WORKSPACE_SELECTOR);
    } catch (error) {
      return null;
    }
  }

  function getObjectVariantsSection(root) {
    try {
      if (root && root.nodeType === 1) {
        if (root.matches && root.matches(OBJECT_VARIANTS_SECTION_SELECTOR)) {
          return root;
        }

        var closestSection = root.closest ? root.closest(OBJECT_VARIANTS_SECTION_SELECTOR) : null;

        if (closestSection) {
          return closestSection;
        }

        var innerSection = U().qs(OBJECT_VARIANTS_SECTION_SELECTOR, root);

        if (innerSection) {
          return innerSection;
        }
      }

      return U().qs(OBJECT_VARIANTS_SECTION_SELECTOR);
    } catch (error) {
      return null;
    }
  }

  function getTable(root) {
    try {
      if (root && root.nodeType === 1) {
        if (root.matches && root.matches(TABLE_SELECTOR)) {
          return root;
        }

        var tableInside = U().qs(TABLE_SELECTOR, root);

        if (tableInside) {
          return tableInside;
        }
      }

      return U().qs(TABLE_SELECTOR);
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

      if (table && table.parentElement) {
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

  function getDrawerSlot(workspace, drawer) {
    try {
      if (workspace) {
        var slot = U().qs(DRAWER_SLOT_SELECTOR, workspace);

        if (slot) {
          return slot;
        }
      }

      if (drawer && drawer.parentElement) {
        var parentSlot = U().closest(drawer, DRAWER_SLOT_SELECTOR);

        if (parentSlot) {
          return parentSlot;
        }
      }

      return drawer || null;
    } catch (error) {
      return drawer || null;
    }
  }

  function cacheDom(root) {
    try {
      var drawer = getDrawer(root);
      var workspace = getWorkspace(drawer || root);
      var objectVariantsSection = getObjectVariantsSection(workspace || drawer || root);
      var table = getTable(workspace || objectVariantsSection || root);
      var tableSlot = getTableSlot(workspace, table);
      var drawerSlot = getDrawerSlot(workspace, drawer);

      var cache = {
        drawer: drawer,
        workspace: workspace,
        objectVariantsSection: objectVariantsSection,
        objectVariantsTop: U().qs(OBJECT_VARIANTS_TOP_SELECTOR, objectVariantsSection),
        objectKindArea: U().qs("[data-vp-object-kind-area='true']", objectVariantsSection),
        objectVariantsBody: U().qs("[data-vp-object-variants-body='true']", objectVariantsSection),
        objectVariantsWorkspaceSlot: U().qs("[data-vp-object-variants-workspace-slot='true']", objectVariantsSection),
        table: table,
        tableSlot: tableSlot,
        drawerSlot: drawerSlot,

        form: U().qs("[data-vp-variant-drawer-form='true']", drawer),
        panel: U().qs("[data-vp-variant-drawer-panel='true']", drawer),
        body: U().qs(".vp-create-variant-drawer__body, [data-vp-variant-drawer-body='true']", drawer),

        modeField: U().qs("[data-vp-variant-drawer-mode-field='true']", drawer),
        rowIndexField: U().qs("[data-vp-variant-drawer-row-index-field='true']", drawer),
        variantIdField: U().qs("[data-vp-variant-drawer-variant-id-field='true']", drawer),
        profileIdField: U().qs("[data-vp-variant-drawer-profile-id-field='true']", drawer),
        familyProfileIdField: U().qs("[data-vp-variant-drawer-family-profile-id-field='true']", drawer),
        valuesJsonField: U().qs("[data-vp-variant-drawer-values-json-field='true']", drawer),
        originalValuesJsonField: U().qs("[data-vp-variant-drawer-original-values-json-field='true']", drawer),
        additionalKeysJsonField: U().qs("[data-vp-variant-drawer-additional-field-keys-json-field='true'], [data-vp-variant-drawer-additional-field-keys-json='true'], [data-vp-variant-additional-field-keys-json]", drawer),
        originalAdditionalKeysJsonField: U().qs("[data-vp-variant-drawer-original-additional-field-keys-json-field='true']", drawer),

        title: U().qs("[data-vp-variant-drawer-title='true']", drawer),
        subtitle: U().qs("[data-vp-variant-drawer-subtitle='true']", drawer),
        kicker: U().qs("[data-vp-variant-drawer-kicker='true']", drawer),

        statusPill: U().qs("[data-vp-variant-drawer-status-pill='true']", drawer),
        statusText: U().qs("[data-vp-variant-drawer-status-text='true']", drawer),

        fieldsRoot: U().qs("[data-vp-variant-drawer-fields='true']", drawer),
        sectionsRoot: U().qs("[data-vp-variant-drawer-sections='true']", drawer),
        sectionNav: U().qs(SECTION_NAV_SELECTOR, drawer),
        sectionButtons: U().qsa(SECTION_NAV_ITEM_SELECTOR, drawer),
        sections: U().qsa(SECTION_SELECTOR, drawer),

        validationRoot: U().qs("[data-vp-variant-drawer-validation='true']", drawer),
        validationList: U().qs("[data-vp-variant-drawer-validation-list='true']", drawer),
        validationCount: U().qs("[data-vp-variant-drawer-validation-count='true']", drawer),

        summaryName: U().qs("[data-vp-variant-drawer-summary-name='true']", drawer),
        summaryId: U().qs("[data-vp-variant-drawer-summary-id='true']", drawer),
        summaryProfile: U().qs("[data-vp-variant-drawer-summary-profile='true']", drawer),
        summaryStatus: U().qs("[data-vp-variant-drawer-summary-status='true']", drawer),
        summaryValues: U().qs("[data-vp-variant-drawer-summary-values='true']", drawer),

        dirtyState: U().qs("[data-vp-variant-drawer-dirty-state='true']", drawer),

        cancelButton: U().qs("[data-vp-variant-drawer-cancel='true']", drawer),
        validateButton: U().qs("[data-vp-variant-drawer-validate='true']", drawer),
        applyButton: U().qs("[data-vp-variant-drawer-apply='true']", drawer)
      };

      runtime.cache = cache;
      return cache;
    } catch (error) {
      warn("Could not cache variant drawer DOM.", error);

      runtime.cache = {
        drawer: null,
        workspace: null,
        objectVariantsSection: null,
        objectVariantsTop: null,
        objectKindArea: null,
        table: null,
        tableSlot: null,
        drawerSlot: null,
        sectionButtons: [],
        sections: []
      };

      return runtime.cache;
    }
  }

  function isCleanShell(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();
      var drawer = c && c.drawer ? c.drawer : null;

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

  function shouldRevealAllSections(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();

      if (isCleanShell(c)) {
        return true;
      }

      if (!c.sectionNav || c.sectionNav.hidden || U().attr(c.sectionNav, "hidden", "") !== "") {
        return true;
      }

      var buttons = c.sectionButtons && c.sectionButtons.length
        ? c.sectionButtons
        : U().qsa(SECTION_NAV_ITEM_SELECTOR, c.sectionNav || c.drawer);

      return !buttons.length;
    } catch (error) {
      return true;
    }
  }

  function setNodeHidden(node, hidden) {
    try {
      if (!node) {
        return false;
      }

      return U().setHidden(node, !!hidden);
    } catch (error) {
      return false;
    }
  }

  function setManagedEditorHidden(node, hidden, source) {
    try {
      if (!node) {
        return false;
      }

      if (hidden) {
        node.setAttribute("data-vp-hidden-by-variant-editor", "true");
        node.setAttribute("data-vp-hidden-reason", source || COMPONENT_NAME);
        node.setAttribute("aria-hidden", "true");
        node.hidden = true;
        node.setAttribute("hidden", "");
        return true;
      }

      if (node.getAttribute("data-vp-hidden-by-variant-editor") === "true") {
        node.removeAttribute("data-vp-hidden-by-variant-editor");
        node.removeAttribute("data-vp-hidden-reason");
        node.removeAttribute("aria-hidden");
        node.hidden = false;
        node.removeAttribute("hidden");
        return true;
      }

      return false;
    } catch (error) {
      return false;
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

  function applyEditorStateToObjectVariants(cache, mode, source) {
    try {
      var c = cache || runtime.cache || cacheDom();
      var isOpen = mode === "open";

      markEditorNode(c.objectVariantsSection, mode, source);
      markEditorNode(c.objectVariantsBody, mode, source);
      markEditorNode(c.objectVariantsWorkspaceSlot, mode, source);

      if (c.objectVariantsSection) {
        U().setAttr(c.objectVariantsSection, "data-vp-object-variants-editor-state", mode);
        U().setAttr(c.objectVariantsSection, "data-vp-object-kind-area-hidden", isOpen ? "true" : "false");
      }

      if (c.objectVariantsWorkspaceSlot) {
        U().setAttr(c.objectVariantsWorkspaceSlot, "data-vp-object-kind-area-hidden", isOpen ? "true" : "false");
      }

      setManagedEditorHidden(c.objectVariantsTop, isOpen, source);
      setManagedEditorHidden(c.objectKindArea, isOpen, source);

      return true;
    } catch (error) {
      warn("Could not apply editor state to object variants section.", error);
      return false;
    }
  }

  function setActionButtonLabels(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();

      if (c.applyButton) {
        c.applyButton.textContent = "Variante speichern";
        c.applyButton.setAttribute("aria-label", "Variante speichern");
        c.applyButton.setAttribute("data-vp-action-label", "Variante speichern");
      }

      if (c.cancelButton) {
        c.cancelButton.textContent = "Abbrechen";
        c.cancelButton.setAttribute("aria-label", "Bearbeitung abbrechen");
        c.cancelButton.setAttribute("data-vp-action-label", "Abbrechen");
      }

      if (c.validateButton) {
        c.validateButton.textContent = "Prüfen";
        c.validateButton.setAttribute("aria-label", "Variante prüfen");
        c.validateButton.setAttribute("data-vp-action-label", "Prüfen");
      }

      return true;
    } catch (error) {
      warn("Could not set drawer action button labels.", error);
      return false;
    }
  }

  function setEditorMode(mode, options) {
    try {
      var config = options || {};
      var nextMode = mode === "open" ? "open" : "closed";
      var cache = runtime.cache || cacheDom(config.root || null);
      var changed = runtime.editorMode !== nextMode;

      runtime.editorMode = nextMode;

      markEditorNode(cache.workspace, nextMode, config.source || "set_editor_mode");
      markEditorNode(cache.drawer, nextMode, config.source || "set_editor_mode");
      markEditorNode(cache.drawerSlot, nextMode, config.source || "set_editor_mode");
      markEditorNode(cache.tableSlot, nextMode, config.source || "set_editor_mode");
      markEditorNode(cache.table, nextMode, config.source || "set_editor_mode");
      applyEditorStateToObjectVariants(cache, nextMode, config.source || "set_editor_mode");

      try {
        document.documentElement.setAttribute("data-vp-variant-editor-state", nextMode);
        document.documentElement.setAttribute("data-vp-object-variants-editor-state", nextMode);
      } catch (htmlError) {
        /* no-op */
      }

      if (cache.tableSlot && cache.drawer && cache.tableSlot !== cache.drawerSlot && !cache.tableSlot.contains(cache.drawer)) {
        setNodeHidden(cache.tableSlot, nextMode === "open");
      } else if (cache.table && cache.drawer && !cache.table.contains(cache.drawer)) {
        setNodeHidden(cache.table, nextMode === "open");
      }

      if (cache.drawerSlot) {
        setNodeHidden(cache.drawerSlot, false);
      }

      if (cache.drawer) {
        if (nextMode === "open") {
          cache.drawer.hidden = false;
          cache.drawer.removeAttribute("hidden");
          cache.drawer.setAttribute("aria-hidden", "false");
          cache.drawer.setAttribute("data-vp-variant-drawer-state", "open");
        } else if (config.keepDrawerVisible !== true) {
          cache.drawer.setAttribute("data-vp-variant-drawer-state", "closed");
          cache.drawer.setAttribute("aria-hidden", "true");
          cache.drawer.hidden = true;
        }
      }

      if (changed || config.forceEvent === true) {
        U().dispatchDocument("vectoplan:create:variant-editor-mode-changed", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          mode: nextMode,
          editorMode: nextMode,
          open: nextMode === "open",
          source: config.source || "set_editor_mode",
          session: getActiveSession()
        });

        U().dispatchDocument("vectoplan:create:object-variants-editor-state-changed", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          state: nextMode,
          editorState: nextMode,
          open: nextMode === "open",
          source: config.source || "set_editor_mode",
          session: getActiveSession()
        });
      }

      return nextMode;
    } catch (error) {
      warn("Could not set variant editor mode.", error);
      return runtime.editorMode || "closed";
    }
  }

  function openEditorMode(source) {
    var mode = setEditorMode("open", {
      source: source || "open_editor",
      forceEvent: true
    });

    U().dispatchDocument("vectoplan:create:variant-editor-opened", {
      component: COMPONENT_NAME,
      version: COMPONENT_VERSION,
      source: source || "open_editor",
      session: getActiveSession()
    });

    return mode;
  }

  function closeEditorMode(source) {
    var mode = setEditorMode("closed", {
      source: source || "close_editor",
      forceEvent: true
    });

    U().dispatchDocument("vectoplan:create:variant-editor-closed", {
      component: COMPONENT_NAME,
      version: COMPONENT_VERSION,
      source: source || "close_editor",
      session: getActiveSession()
    });

    return mode;
  }

  function normalizeSectionId(value, fallback) {
    try {
      var raw = U().trim(value || fallback || "");

      if (!raw) {
        return "";
      }

      if (raw.charAt(0) === "#") {
        raw = raw.slice(1);
      }

      if (U().normalizeId) {
        return U().normalizeId(raw, "section");
      }

      return raw
        .toLowerCase()
        .replace(/[^a-z0-9_.-]+/g, "_")
        .replace(/^_+|_+$/g, "");
    } catch (error) {
      return fallback || "";
    }
  }

  function getSectionIdFromSection(section, index) {
    try {
      var raw = U().attr(section, "data-vp-section-id", "") ||
        U().attr(section, "data-vp-section-key", "") ||
        U().attr(section, "data-vp-field-section-id", "") ||
        U().attr(section, "data-vp-field-section-key", "") ||
        U().attr(section, "data-section-id", "") ||
        U().attr(section, "data-section-key", "") ||
        U().attr(section, "id", "");

      var normalized = normalizeSectionId(raw, "");

      if (!normalized) {
        var title = U().qs(".vp-create-variant-drawer__section-header h4, h4, h3, [data-vp-section-title]", section);
        normalized = normalizeSectionId(title ? title.textContent : "", "");
      }

      if (!normalized) {
        normalized = "section_" + String(index + 1);
      }

      return normalized;
    } catch (error) {
      return "section_" + String(index + 1);
    }
  }

  function getSectionIdFromButton(button, index) {
    try {
      var raw = U().attr(button, "data-vp-section-target", "") ||
        U().attr(button, "data-vp-section-id", "") ||
        U().attr(button, "data-vp-section-key", "") ||
        U().attr(button, "data-section-target", "") ||
        U().attr(button, "data-section-id", "") ||
        U().attr(button, "data-section-key", "") ||
        U().attr(button, "aria-controls", "") ||
        U().attr(button, "href", "");

      var normalized = normalizeSectionId(raw, "");

      if (!normalized) {
        normalized = normalizeSectionId(button.textContent || "", "");
      }

      if (!normalized) {
        normalized = "section_" + String(index + 1);
      }

      return normalized;
    } catch (error) {
      return "section_" + String(index + 1);
    }
  }

  function ensureSectionStructure(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();
      var sections = U().qsa(SECTION_SELECTOR, c.sectionsRoot || c.fieldsRoot || c.drawer);
      var buttons = U().qsa(SECTION_NAV_ITEM_SELECTOR, c.sectionNav || c.drawer);

      c.sections = sections;
      c.sectionButtons = buttons;

      sections.forEach(function (section, index) {
        var id = getSectionIdFromSection(section, index);

        U().setAttr(section, "data-vp-section-id", id);
        U().setAttr(section, "data-vp-section-index", String(index));
        U().setAttr(section, "data-vp-variant-drawer-section", "true");

        if (!section.id) {
          section.id = "vp-variant-section-" + id;
        }
      });

      buttons.forEach(function (button, index) {
        var buttonId = getSectionIdFromButton(button, index);
        var matchingSection = findSectionById(c, buttonId) || sections[index] || null;
        var finalId = matchingSection ? getSectionIdFromSection(matchingSection, index) : buttonId;

        U().setAttr(button, "data-vp-section-target", finalId);
        U().setAttr(button, "data-vp-section-index", String(index));
        U().setAttr(button, "data-vp-variant-drawer-section-nav-item", "true");
        U().setAttr(button, "role", "tab");

        if (matchingSection && matchingSection.id) {
          U().setAttr(button, "aria-controls", matchingSection.id);
        }
      });

      if (c.sectionNav && !shouldRevealAllSections(c)) {
        U().setAttr(c.sectionNav, "role", "tablist");
        U().setAttr(c.sectionNav, "data-vp-variant-drawer-section-nav", "true");
      }

      return {
        sections: sections,
        buttons: buttons
      };
    } catch (error) {
      warn("Could not ensure section structure.", error);

      return {
        sections: [],
        buttons: []
      };
    }
  }

  function findSectionById(cache, sectionId) {
    try {
      var c = cache || runtime.cache || cacheDom();
      var wanted = normalizeSectionId(sectionId, "");

      if (!wanted) {
        return null;
      }

      var sections = c.sections && c.sections.length ? c.sections : U().qsa(SECTION_SELECTOR, c.sectionsRoot || c.fieldsRoot || c.drawer);

      for (var index = 0; index < sections.length; index += 1) {
        var current = getSectionIdFromSection(sections[index], index);

        if (current === wanted || sections[index].id === wanted) {
          return sections[index];
        }
      }

      return null;
    } catch (error) {
      return null;
    }
  }

  function getFirstSectionId(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();
      var sections = c.sections && c.sections.length ? c.sections : U().qsa(SECTION_SELECTOR, c.sectionsRoot || c.fieldsRoot || c.drawer);

      if (!sections.length) {
        return "";
      }

      return getSectionIdFromSection(sections[0], 0);
    } catch (error) {
      return "";
    }
  }

  function getActiveSectionIdFromDom(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();
      var sections = c.sections && c.sections.length ? c.sections : U().qsa(SECTION_SELECTOR, c.sectionsRoot || c.fieldsRoot || c.drawer);
      var buttons = c.sectionButtons && c.sectionButtons.length ? c.sectionButtons : U().qsa(SECTION_NAV_ITEM_SELECTOR, c.sectionNav || c.drawer);

      for (var sectionIndex = 0; sectionIndex < sections.length; sectionIndex += 1) {
        var section = sections[sectionIndex];

        if (U().attr(section, "data-vp-section-active", "") === "true" || section.classList.contains("is-active")) {
          return getSectionIdFromSection(section, sectionIndex);
        }
      }

      for (var buttonIndex = 0; buttonIndex < buttons.length; buttonIndex += 1) {
        var button = buttons[buttonIndex];

        if (U().attr(button, "data-vp-section-active", "") === "true" || button.classList.contains("is-active")) {
          return getSectionIdFromButton(button, buttonIndex);
        }
      }

      return U().attr(c.drawer, "data-vp-active-section", "") || "";
    } catch (error) {
      return "";
    }
  }

  function getActiveSectionId(cache) {
    try {
      if (runtime.activeSectionId) {
        return runtime.activeSectionId;
      }

      return getActiveSectionIdFromDom(cache) || getFirstSectionId(cache);
    } catch (error) {
      return "";
    }
  }

  function setSectionNodeActive(section, active, options) {
    try {
      if (!section) {
        return false;
      }

      var config = options || {};
      var revealAll = !!config.revealAll;
      var isActive = !!active;

      U().setAttr(section, "data-vp-section-active", isActive ? "true" : "false");
      section.classList.toggle("is-active", isActive);

      if (revealAll) {
        section.hidden = false;
        section.removeAttribute("hidden");
        U().setAttr(section, "aria-hidden", "false");

        if (!section.getAttribute("tabindex")) {
          section.setAttribute("tabindex", "-1");
        }

        return true;
      }

      section.hidden = !isActive;
      U().setAttr(section, "aria-hidden", isActive ? "false" : "true");

      if (isActive) {
        section.removeAttribute("hidden");

        if (!section.getAttribute("tabindex")) {
          section.setAttribute("tabindex", "-1");
        }
      } else {
        section.setAttribute("hidden", "");
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function setButtonNodeActive(button, active) {
    try {
      if (!button) {
        return false;
      }

      var isActive = !!active;

      U().setAttr(button, "data-vp-section-active", isActive ? "true" : "false");
      button.classList.toggle("is-active", isActive);
      U().setAttr(button, "aria-selected", isActive ? "true" : "false");
      U().setAttr(button, "tabindex", isActive ? "0" : "-1");

      return true;
    } catch (error) {
      return false;
    }
  }

  function activateSection(sectionId, options) {
    try {
      var config = options || {};
      var cache = runtime.cache || cacheDom(config.root || null);
      var structure = ensureSectionStructure(cache);
      var sections = structure.sections;
      var buttons = structure.buttons;
      var revealAll = shouldRevealAllSections(cache);

      if (!sections.length) {
        return "";
      }

      var wanted = normalizeSectionId(sectionId, "") || getActiveSectionId(cache) || getFirstSectionId(cache);
      var matchingSection = findSectionById(cache, wanted);

      if (!matchingSection) {
        wanted = getFirstSectionId(cache);
        matchingSection = findSectionById(cache, wanted);
      }

      if (!wanted || !matchingSection) {
        return "";
      }

      runtime.activeSectionId = wanted;

      if (cache.drawer) {
        U().setAttr(cache.drawer, "data-vp-active-section", wanted);
      }

      if (cache.sectionsRoot) {
        U().setAttr(cache.sectionsRoot, "data-vp-active-section", wanted);
      }

      sections.forEach(function (section, index) {
        var currentId = getSectionIdFromSection(section, index);
        setSectionNodeActive(section, currentId === wanted, {
          revealAll: revealAll
        });
      });

      buttons.forEach(function (button, index) {
        var currentId = getSectionIdFromButton(button, index);
        var matching = currentId === wanted;

        if (!matching && sections[index]) {
          matching = getSectionIdFromSection(sections[index], index) === wanted;
        }

        setButtonNodeActive(button, matching);
      });

      if (cache.fieldsRoot && config.resetScroll !== false && !revealAll) {
        try {
          cache.fieldsRoot.scrollTop = 0;
        } catch (scrollError) {
          /* no-op */
        }
      }

      if (config.focus === true && matchingSection && typeof matchingSection.focus === "function") {
        window.setTimeout(function () {
          try {
            matchingSection.focus({
              preventScroll: true
            });
          } catch (focusError) {
            /* no-op */
          }
        }, 0);
      }

      if (config.dispatchEvent !== false) {
        U().dispatchDocument("vectoplan:create:variant-drawer-section-changed", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          section_id: wanted,
          sectionId: wanted,
          revealAll: revealAll,
          source: config.source || "activate_section",
          session: getActiveSession()
        });
      }

      return wanted;
    } catch (error) {
      warn("Could not activate drawer section.", error);
      return "";
    }
  }

  function activateSectionFromButton(button, options) {
    try {
      var cache = runtime.cache || cacheDom(button || null);
      var structure = ensureSectionStructure(cache);
      var buttons = structure.buttons;
      var index = buttons.indexOf ? buttons.indexOf(button) : U().toArray(buttons).indexOf(button);
      var sectionId = getSectionIdFromButton(button, Math.max(0, index));

      if (!sectionId && structure.sections[index]) {
        sectionId = getSectionIdFromSection(structure.sections[index], index);
      }

      return activateSection(sectionId, U().safeMerge(options || {}, {
        source: "section_nav_click",
        focus: false
      }));
    } catch (error) {
      warn("Could not activate section from button.", error);
      return "";
    }
  }

  function ensureInitialSection(options) {
    try {
      var config = options || {};
      var cache = runtime.cache || cacheDom(config.root || null);

      ensureSectionStructure(cache);

      var current = config.sectionId ||
        runtime.activeSectionId ||
        U().attr(cache.drawer, "data-vp-active-section", "") ||
        getFirstSectionId(cache);

      if (!current) {
        return "";
      }

      return activateSection(current, U().safeMerge(config, {
        source: config.source || "ensure_initial_section",
        resetScroll: config.resetScroll !== false,
        dispatchEvent: config.dispatchEvent === true
      }));
    } catch (error) {
      warn("Could not ensure initial drawer section.", error);
      return "";
    }
  }

  function readContext(cache) {
    try {
      var c = cache || runtime.cache || cacheDom();

      var context = {
        domain: U().attr(c.drawer, "data-vp-current-domain", "") ||
          U().attr(c.workspace, "data-vp-current-domain", "") ||
          U().attr(c.objectVariantsSection, "data-vp-current-domain", ""),

        category: U().attr(c.drawer, "data-vp-current-category", "") ||
          U().attr(c.workspace, "data-vp-current-category", "") ||
          U().attr(c.objectVariantsSection, "data-vp-current-category", ""),

        subcategory: U().attr(c.drawer, "data-vp-current-subcategory", "") ||
          U().attr(c.workspace, "data-vp-current-subcategory", "") ||
          U().attr(c.objectVariantsSection, "data-vp-current-subcategory", ""),

        object_kind: U().attr(c.drawer, "data-vp-current-object-kind", "") ||
          U().attr(c.workspace, "data-vp-current-object-kind", "") ||
          U().attr(c.objectVariantsSection, "data-vp-current-object-kind", "cell_block"),

        family_profile_id: U().getValue(c.familyProfileIdField, "") ||
          U().attr(c.drawer, "data-vp-current-family-profile-id", "") ||
          U().attr(c.workspace, "data-vp-current-family-profile-id", "") ||
          U().attr(c.objectVariantsSection, "data-vp-current-family-profile-id", "") ||
          U().attr(c.table, "data-vp-family-profile-id", ""),

        variant_profile_id: U().getValue(c.profileIdField, "") ||
          U().attr(c.drawer, "data-vp-current-variant-profile-id", "") ||
          U().attr(c.workspace, "data-vp-current-variant-profile-id", "") ||
          U().attr(c.objectVariantsSection, "data-vp-current-variant-profile-id", "") ||
          U().attr(c.table, "data-vp-variant-profile-id", "")
      };

      context.taxonomy_path = [context.domain, context.category, context.subcategory].filter(Boolean).join("/");
      context.taxonomyPath = context.taxonomy_path;

      if (profilesApi() && typeof profilesApi().normalizeContext === "function") {
        return profilesApi().normalizeContext(context);
      }

      return context;
    } catch (error) {
      warn("Could not read drawer context.", error);

      return {
        domain: "",
        category: "",
        subcategory: "",
        taxonomy_path: "",
        taxonomyPath: "",
        object_kind: "cell_block",
        family_profile_id: "",
        variant_profile_id: ""
      };
    }
  }

  function getExistingVariantIds() {
    try {
      if (stateApi() && typeof stateApi().getVariants === "function") {
        return U().toArray(stateApi().getVariants()).map(function (variant) {
          return variant.variant_id || variant.slug || "";
        }).filter(Boolean);
      }

      return U().qsa(ROW_SELECTOR).map(function (row) {
        return U().attr(row, "data-vp-variant-id", "") ||
          U().attr(row, "data-vp-definition-variant-id", "");
      }).filter(Boolean);
    } catch (error) {
      return [];
    }
  }

  function getVariantFromState(target) {
    try {
      if (!stateApi() || typeof stateApi().getVariant !== "function") {
        return null;
      }

      return stateApi().getVariant(target);
    } catch (error) {
      return null;
    }
  }

  function normalizeMode(value, fallback) {
    try {
      var mode = U().lower(value || fallback || "");

      if (mode === "edit" || mode === "update") {
        return "edit";
      }

      return "create";
    } catch (error) {
      return "create";
    }
  }

  function valuesFromAny(payload) {
    try {
      var source = payload || {};

      if (source.definition_values && typeof source.definition_values === "object") {
        return U().deepClone(source.definition_values, {});
      }

      if (source.definitionValues && typeof source.definitionValues === "object") {
        return U().deepClone(source.definitionValues, {});
      }

      if (source.values && typeof source.values === "object") {
        return U().deepClone(source.values, {});
      }

      if (source.definition_values_json) {
        return U().valuesFromJson(source.definition_values_json);
      }

      if (source.definitionValuesJson) {
        return U().valuesFromJson(source.definitionValuesJson);
      }

      if (source.valuesJson) {
        return U().valuesFromJson(source.valuesJson);
      }

      if (source.values_json) {
        return U().valuesFromJson(source.values_json);
      }

      return {};
    } catch (error) {
      return {};
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

  function normalizePayload(payload) {
    try {
      var source = payload || {};
      var row = source.row || null;
      var rowPayload = {};

      if (row && row.nodeType === 1) {
        rowPayload = payloadFromRow(row);
      }

      var merged = U().safeMerge(rowPayload, source);
      var rowIndex = merged.rowIndex;

      if (rowIndex === undefined || rowIndex === null || rowIndex === "") {
        rowIndex = merged.row_index;
      }

      if (rowIndex === undefined || rowIndex === null || rowIndex === "") {
        rowIndex = "";
      }

      var variantId = merged.variant_id ||
        merged.variantId ||
        merged.slug ||
        merged.id ||
        "";

      var existingVariant = null;

      if (variantId) {
        existingVariant = getVariantFromState(variantId);
      }

      if (!existingVariant && rowIndex !== "") {
        existingVariant = getVariantFromState(U().intValue(rowIndex, -1));
      }

      if (existingVariant) {
        merged = U().safeMerge(existingVariant, merged);
      }

      var values = valuesFromAny(merged);

      if (!values["variant.variant_id"] && variantId) {
        values["variant.variant_id"] = variantId;
      }

      var label = merged.label ||
        merged.name ||
        merged.variant_label ||
        merged.variantLabel ||
        values["variant.label"] ||
        "";

      if (!values["variant.label"] && label) {
        values["variant.label"] = label;
      }

      var description = merged.description ||
        values["variant.description"] ||
        "";

      if (!values["variant.description"] && description) {
        values["variant.description"] = description;
      }

      var additionalKeys = normalizeAdditionalFieldKeys(
        merged.additional_field_keys ||
        merged.additionalFieldKeys ||
        merged.additional_fields ||
        merged.additionalFields ||
        merged.additional_field_keys_json ||
        merged.additionalFieldKeysJson ||
        []
      );

      var mode = normalizeMode(merged.mode || merged.drawerMode, variantId || rowIndex !== "" ? "edit" : "create");

      return {
        session_id: "drawer_session_" + String(++runtime.sessionSeq),
        mode: mode,
        rowIndex: rowIndex,
        variant_id: variantId,
        label: label,
        description: description,
        kind: merged.kind || merged.variant_kind || (variantId === "default" ? "standard" : "profile"),
        is_default: U().bool(merged.is_default || merged.isDefault || merged.default, false) || variantId === "default",
        family_profile_id: merged.family_profile_id || merged.familyProfileId || "",
        variant_profile_id: merged.variant_profile_id || merged.variantProfileId || merged.profile_id || "",
        definition_values: values,
        definition_values_json: U().valuesToJson(values),
        additional_field_keys: additionalKeys,
        additionalFieldKeys: additionalKeys.slice(),
        definition_summary: merged.definition_summary || merged.definitionSummary || merged.summary || "",
        raw: source,
        started_at: U().nowIso ? U().nowIso() : new Date().toISOString()
      };
    } catch (error) {
      warn("Could not normalize drawer payload.", error);

      return {
        session_id: "drawer_session_" + String(++runtime.sessionSeq),
        mode: "create",
        rowIndex: "",
        variant_id: "",
        label: "",
        description: "",
        kind: "profile",
        is_default: false,
        family_profile_id: "",
        variant_profile_id: "",
        definition_values: {},
        definition_values_json: "{}",
        additional_field_keys: [],
        additionalFieldKeys: [],
        definition_summary: "",
        raw: payload || {},
        started_at: U().nowIso ? U().nowIso() : ""
      };
    }
  }

  function payloadFromRow(row) {
    try {
      if (!row || row.nodeType !== 1) {
        return {};
      }

      function field(selector, fallback) {
        var node = U().qs(selector, row);
        return U().getValue(node, fallback || "");
      }

      var additionalKeysJson = field("[data-vp-row-additional-field-keys-json]", "[]");

      return {
        row: row,
        rowIndex: U().intValue(U().attr(row, "data-row-index", U().attr(row, "data-vp-variant-index", "")), ""),
        variant_id: U().attr(row, "data-vp-variant-id", "") ||
          U().attr(row, "data-vp-definition-variant-id", "") ||
          field("[data-vp-variant-slug]", ""),
        label: U().attr(row, "data-vp-variant-label", "") ||
          field("[data-vp-variant-name]", ""),
        kind: U().attr(row, "data-vp-variant-kind", "") ||
          field("[data-vp-row-variant-kind]", "profile"),
        description: field("[data-vp-row-variant-description]", ""),
        variant_profile_id: U().attr(row, "data-vp-variant-profile-id", "") ||
          U().attr(row, "data-vp-definition-variant-profile-id", "") ||
          field("[data-vp-row-variant-profile-id]", ""),
        definition_values_json: field("[data-vp-row-definition-values-json]", ""),
        additional_field_keys: normalizeAdditionalFieldKeys(additionalKeysJson),
        definition_summary: field("[data-vp-row-definition-summary-input]", "") ||
          (U().qs("[data-vp-row-definition-summary='true']", row) || {}).textContent ||
          "",
        definition_managed: U().bool(U().attr(row, "data-vp-definition-managed", ""), false) ||
          U().bool(field("[data-vp-row-definition-managed]", ""), false),
        is_default: U().bool(U().attr(row, "data-vp-is-default", ""), false) ||
          U().bool(field("[data-vp-row-is-default]", ""), false)
      };
    } catch (error) {
      warn("Could not read payload from row.", error);
      return {};
    }
  }

  function setStatus(state, message) {
    try {
      var cache = runtime.cache || cacheDom();

      if (shellApi() && typeof shellApi().setStatus === "function") {
        shellApi().setStatus(state || "idle", message || "", cache.drawer);
      }

      if (cache.drawer) {
        U().setAttr(cache.drawer, "data-vp-variant-drawer-status-state", state || "idle");
      }

      if (cache.statusPill) {
        cache.statusPill.className = "vp-create-variant-drawer__status-pill vp-create-variant-drawer__status-pill--" + String(state || "idle");
        cache.statusPill.textContent = state === "busy"
          ? "Lädt"
          : state === "error"
            ? "Fehler"
            : state === "valid"
              ? "Gültig"
              : state === "warning"
                ? "Hinweis"
                : "Bereit";
      }

      if (cache.statusText && message) {
        cache.statusText.textContent = message;
      }
    } catch (error) {
      warn("Could not set drawer status.", error);
    }
  }

  function setBusy(busy, message) {
    try {
      var cache = runtime.cache || cacheDom();
      var isBusy = !!busy;

      if (shellApi() && typeof shellApi().setBusy === "function") {
        shellApi().setBusy(isBusy, message || "", cache.drawer);
      }

      if (cache.drawer) {
        U().setAttr(cache.drawer, "data-vp-variant-drawer-busy", isBusy ? "true" : "false");
      }

      U().setDisabled(cache.applyButton, isBusy, isBusy ? "busy" : "");
      U().setDisabled(cache.validateButton, isBusy, isBusy ? "busy" : "");

      if (message) {
        setStatus(isBusy ? "busy" : "idle", message);
      }
    } catch (error) {
      warn("Could not set drawer busy state.", error);
    }
  }

  function setDirty(dirty) {
    try {
      var cache = runtime.cache || cacheDom();
      var isDirty = !!dirty;

      if (shellApi() && typeof shellApi().setDirty === "function") {
        shellApi().setDirty(isDirty, cache.drawer);
      }

      if (cache.drawer) {
        U().setAttr(cache.drawer, "data-vp-variant-drawer-dirty", isDirty ? "true" : "false");
      }

      if (cache.dirtyState) {
        U().setAttr(cache.dirtyState, "data-vp-dirty", isDirty ? "true" : "false");
        cache.dirtyState.textContent = isDirty ? "Ungespeicherte Änderungen" : "Keine ungespeicherten Änderungen";
      }
    } catch (error) {
      warn("Could not set drawer dirty state.", error);
    }
  }

  function setValidationResult(result) {
    try {
      var cache = runtime.cache || cacheDom();
      var payload = result || {};
      var errors = U().toArray(payload.errors);
      var warnings = U().toArray(payload.warnings);
      var items = errors.length ? errors : warnings;
      var state = errors.length ? "invalid" : (warnings.length ? "warning" : "valid");

      clearFieldErrors(cache.drawer);

      if (errors.length || warnings.length) {
        applyFieldErrors(cache.drawer, items);
      }

      if (shellApi() && typeof shellApi().setValidation === "function") {
        shellApi().setValidation(items, state, cache.drawer);
      }

      if (cache.validationRoot) {
        U().setHidden(cache.validationRoot, !items.length);
        U().setAttr(cache.validationRoot, "data-vp-variant-drawer-validation-state", state);
      }

      if (cache.validationCount) {
        cache.validationCount.textContent = items.length === 1 ? "1 Hinweis" : String(items.length) + " Hinweise";
      }

      if (cache.validationList) {
        cache.validationList.innerHTML = "";

        items.forEach(function (item) {
          var li = document.createElement("li");
          li.className = "vp-create-variant-drawer__validation-item";
          U().setAttr(li, "data-vp-validation-item", "true");

          if (item.field_key || item.fieldKey) {
            U().setAttr(li, "data-vp-validation-field-key", item.field_key || item.fieldKey);
          }

          var strong = document.createElement("strong");
          strong.textContent = item.label || item.field_key || item.fieldKey || "Feld";

          var span = document.createElement("span");
          span.textContent = item.message || "Ungültiger Wert.";

          li.appendChild(strong);
          li.appendChild(span);
          cache.validationList.appendChild(li);
        });
      }

      setStatus(state, state === "valid" ? "Variante ist gültig." : "Variante enthält Hinweise oder Fehler.");
    } catch (error) {
      warn("Could not set validation result.", error);
    }
  }

  function clearFieldErrors(root) {
    try {
      U().qsa("[data-vp-field-error='true']", root || document).forEach(function (node) {
        node.textContent = "";
        U().setHidden(node, true);
      });

      U().qsa("[data-vp-variant-field='true']", root || document).forEach(function (node) {
        node.classList.remove("vp-create-variant-field--invalid");
        node.classList.remove("vp-create-variant-field--warning");
      });
    } catch (error) {
      warn("Could not clear field errors.", error);
    }
  }

  function applyFieldErrors(root, items) {
    try {
      U().toArray(items).forEach(function (item) {
        var key = item.field_key || item.fieldKey || "";

        if (!key) {
          return;
        }

        var field = U().qs("[data-vp-field-key='" + cssEscape(key) + "']", root || document);

        if (!field) {
          return;
        }

        field.classList.add(item.level === "warning" ? "vp-create-variant-field--warning" : "vp-create-variant-field--invalid");

        var errorNode = U().qs("[data-vp-field-error='true']", field);

        if (errorNode) {
          errorNode.textContent = item.message || "Ungültiger Wert.";
          U().setHidden(errorNode, false);
        }
      });
    } catch (error) {
      warn("Could not apply field errors.", error);
    }
  }

  function setHiddenValue(field, value) {
    try {
      return U().setValue(field, value, false);
    } catch (error) {
      return false;
    }
  }

  function applySessionToShell(session) {
    try {
      var cache = runtime.cache || cacheDom();

      if (!cache.drawer) {
        return false;
      }

      U().setAttr(cache.drawer, "data-vp-variant-drawer-mode", session.mode);
      U().setAttr(cache.drawer, "data-vp-current-family-profile-id", session.family_profile_id || "");
      U().setAttr(cache.drawer, "data-vp-current-variant-profile-id", session.variant_profile_id || "");

      setHiddenValue(cache.modeField, session.mode);
      setHiddenValue(cache.rowIndexField, session.rowIndex);
      setHiddenValue(cache.variantIdField, session.variant_id || "");
      setHiddenValue(cache.profileIdField, session.variant_profile_id || "");
      setHiddenValue(cache.familyProfileIdField, session.family_profile_id || "");
      setHiddenValue(cache.valuesJsonField, U().valuesToJson(session.definition_values || {}));
      setHiddenValue(cache.originalValuesJsonField, U().valuesToJson(session.definition_values || {}));
      setHiddenValue(cache.additionalKeysJsonField, U().safeJsonStringify(session.additional_field_keys || [], "[]", 0));
      setHiddenValue(cache.originalAdditionalKeysJsonField, U().safeJsonStringify(session.additional_field_keys || [], "[]", 0));

      if (cache.title) {
        cache.title.textContent = session.mode === "edit" ? "Variante bearbeiten" : "Neue Variante";
      }

      if (cache.kicker) {
        cache.kicker.textContent = session.mode === "edit" ? "Bearbeitung" : "Neue Variante";
      }

      if (cache.summaryName) {
        cache.summaryName.textContent = session.label || (session.mode === "edit" ? "Bestehende Variante" : "Neue Variante");
      }

      if (cache.summaryId) {
        cache.summaryId.textContent = session.variant_id || "wird automatisch vergeben";
      }

      if (cache.summaryProfile) {
        cache.summaryProfile.textContent = session.variant_profile_id || "auto";
      }

      if (cache.summaryStatus) {
        cache.summaryStatus.textContent = session.mode === "edit" ? "Bearbeitung" : "Entwurf";
      }

      setActionButtonLabels(cache);

      return true;
    } catch (error) {
      warn("Could not apply session to shell.", error);
      return false;
    }
  }

  function restoreOptionalFields(session, options) {
    try {
      var api = optionalFieldsApi();
      var config = options || {};

      if (!api || !session) {
        return false;
      }

      var keys = normalizeAdditionalFieldKeys(session.additional_field_keys || session.additionalFieldKeys || []);
      var values = session.definition_values || {};

      if (typeof api.loadVariant === "function") {
        api.loadVariant(session, {
          reason: config.reason || "drawer_restore_optional_fields",
          silent: true
        });
        return true;
      }

      if (typeof api.restoreFromVariant === "function") {
        api.restoreFromVariant(session, {
          reason: config.reason || "drawer_restore_optional_fields",
          silent: true
        });
        return true;
      }

      if (typeof api.setAdditionalFieldKeys === "function") {
        api.setAdditionalFieldKeys(keys, {
          reason: config.reason || "drawer_restore_optional_fields",
          silent: true
        });
      }

      if (typeof api.setValues === "function") {
        api.setValues(values, {
          reason: config.reason || "drawer_restore_optional_values",
          silent: true
        });
      }

      if (typeof api.refresh === "function") {
        api.refresh({
          reason: config.reason || "drawer_restore_optional_fields",
          detail: {
            variant: session,
            additional_field_keys: keys,
            values: values
          },
          soft: true,
          silent: true
        });
      }

      return true;
    } catch (error) {
      warn("Could not restore optional fields.", error);
      return false;
    }
  }

  function collectOptionalValues(baseValues) {
    try {
      var api = optionalFieldsApi();
      var values = U().safeMerge({}, baseValues || {});

      if (!api) {
        return values;
      }

      if (typeof api.syncToDrawerValues === "function") {
        api.syncToDrawerValues({
          reason: "drawer_collect",
          silent: true
        });
      }

      if (typeof api.collectValues === "function") {
        values = U().safeMerge(values, api.collectValues() || {});
      }

      return values;
    } catch (error) {
      warn("Could not collect optional field values.", error);
      return baseValues || {};
    }
  }

  function collectOptionalFieldKeys(session) {
    try {
      var api = optionalFieldsApi();

      if (api && typeof api.getAdditionalFieldKeys === "function") {
        return normalizeAdditionalFieldKeys(api.getAdditionalFieldKeys());
      }

      if (api && typeof api.getSelectedFieldKeys === "function") {
        return normalizeAdditionalFieldKeys(api.getSelectedFieldKeys());
      }

      var keysFromDom = [];

      U().qsa("[data-vp-variant-optional-field], [data-vp-variant-optional-field-key], [data-vp-optional-field-key], [data-vp-field-optional='true']").forEach(function (node) {
        var key = U().attr(node, "data-vp-field-key", "") ||
          U().attr(node, "data-vp-optional-field-key", "") ||
          U().attr(node, "data-vp-variant-optional-field-key", "") ||
          U().attr(node, "data-vp-variant-optional-field", "");

        if (key) {
          keysFromDom.push(key);
        }
      });

      if (keysFromDom.length) {
        return normalizeAdditionalFieldKeys(keysFromDom);
      }

      return normalizeAdditionalFieldKeys(session && (session.additional_field_keys || session.additionalFieldKeys || []));
    } catch (error) {
      return normalizeAdditionalFieldKeys(session && session.additional_field_keys || []);
    }
  }

  function open(payload, options) {
    try {
      var now = Date.now();

      if (now - runtime.lastOpenAt < 80) {
        return Promise.resolve(runtime.active);
      }

      runtime.lastOpenAt = now;

      var config = options || {};
      var cache = cacheDom(config.root || null);

      if (!cache.drawer) {
        var errorPayload = {
          code: "drawer_not_found",
          message: "Variant Drawer wurde nicht gefunden."
        };

        U().dispatchDocument("vectoplan:create:variant-drawer-session-failed", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          error: errorPayload
        });

        return Promise.reject(errorPayload);
      }

      var session = normalizePayload(payload || {});

      runtime.active = session;
      runtime.activeSectionId = "";

      applySessionToShell(session);
      openEditorMode("drawer_open");
      ensureInitialSection({
        source: "open_before_prepare",
        resetScroll: true,
        dispatchEvent: false
      });

      if (shellApi() && typeof shellApi().open === "function") {
        shellApi().open({
          mode: session.mode,
          rowIndex: session.rowIndex,
          variantId: session.variant_id,
          variant_id: session.variant_id,
          label: session.label,
          name: session.label,
          variantProfileId: session.variant_profile_id,
          variant_profile_id: session.variant_profile_id,
          familyProfileId: session.family_profile_id,
          family_profile_id: session.family_profile_id,
          valuesJson: U().valuesToJson(session.definition_values),
          definition_values_json: U().valuesToJson(session.definition_values),
          additional_field_keys: session.additional_field_keys || [],
          additionalFieldKeys: session.additional_field_keys || [],
          additionalFieldKeysJson: U().safeJsonStringify(session.additional_field_keys || [], "[]", 0),
          summary: session.definition_summary
        }, cache.drawer);
      } else {
        openFallback(cache.drawer);
      }

      setActionButtonLabels(cache);
      setBusy(true, "Variantenprofil wird vorbereitet.");

      U().dispatchDocument("vectoplan:create:variant-drawer-session-started", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        session: getActiveSession()
      });

      return prepareSession(session, config)
        .then(function (prepared) {
          runtime.active = prepared;

          applySessionToShell(prepared);
          restoreOptionalFields(prepared, {
            reason: "session_prepared"
          });

          window.setTimeout(function () {
            cacheDom();
            setActionButtonLabels();
            ensureInitialSection({
              source: "session_prepared",
              resetScroll: true,
              dispatchEvent: true
            });
          }, 0);

          setBusy(false);
          setDirty(false);
          setStatus("idle", "Variante bereit.");

          U().dispatchDocument("vectoplan:create:variant-drawer-session-prepared", {
            component: COMPONENT_NAME,
            version: COMPONENT_VERSION,
            session: getActiveSession()
          });

          return prepared;
        })
        .catch(function (error) {
          setBusy(false);
          setStatus("error", "Variante konnte nicht vorbereitet werden.");

          U().dispatchDocument("vectoplan:create:variant-drawer-session-failed", {
            component: COMPONENT_NAME,
            version: COMPONENT_VERSION,
            session: getActiveSession(),
            error: normalizeError(error)
          });

          throw error;
        });
    } catch (error) {
      warn("Could not open variant drawer.", error);
      return Promise.reject(error);
    }
  }

  function openFallback(drawer) {
    try {
      if (!drawer) {
        return false;
      }

      drawer.hidden = false;
      drawer.removeAttribute("hidden");
      drawer.setAttribute("aria-hidden", "false");
      drawer.setAttribute("data-vp-variant-drawer-state", "open");

      try {
        document.body.classList.add("vp-create-variant-drawer-open");
      } catch (bodyError) {
        /* no-op */
      }

      U().dispatchDocument("vectoplan:create:variant-drawer-opened", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        drawerId: U().attr(drawer, "id", ""),
        payload: getActiveSession()
      });

      var panel = U().qs("[data-vp-variant-drawer-panel='true']", drawer);

      window.setTimeout(function () {
        try {
          if (panel && typeof panel.focus === "function") {
            panel.focus();
          }
        } catch (focusError) {
          /* no-op */
        }
      }, 20);

      return true;
    } catch (error) {
      warn("Could not open drawer fallback.", error);
      return false;
    }
  }

  function close(reason) {
    try {
      var now = Date.now();

      if (now - runtime.lastCloseAt < 80) {
        return true;
      }

      runtime.lastCloseAt = now;

      var cache = runtime.cache || cacheDom();

      if (shellApi() && typeof shellApi().close === "function") {
        shellApi().close(reason || "api", cache.drawer);
      } else {
        closeFallback(cache.drawer, reason || "api");
      }

      setBusy(false);
      setDirty(false);
      closeEditorMode(reason || "drawer_close");

      runtime.active = null;
      runtime.activeSectionId = "";

      return true;
    } catch (error) {
      warn("Could not close variant drawer.", error);
      return false;
    }
  }

  function closeFallback(drawer, reason) {
    try {
      if (!drawer) {
        return false;
      }

      drawer.setAttribute("data-vp-variant-drawer-state", "closed");
      drawer.setAttribute("aria-hidden", "true");
      drawer.hidden = true;

      try {
        document.body.classList.remove("vp-create-variant-drawer-open");
      } catch (bodyError) {
        /* no-op */
      }

      U().dispatchDocument("vectoplan:create:variant-drawer-closed", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        drawerId: U().attr(drawer, "id", ""),
        reason: reason || "close"
      });

      return true;
    } catch (error) {
      warn("Could not close drawer fallback.", error);
      return false;
    }
  }

  function reset(reason) {
    try {
      runtime.active = null;
      runtime.activeSectionId = "";

      var cache = runtime.cache || cacheDom();

      setHiddenValue(cache.modeField, "create");
      setHiddenValue(cache.rowIndexField, "");
      setHiddenValue(cache.variantIdField, "");
      setHiddenValue(cache.valuesJsonField, "{}");
      setHiddenValue(cache.originalValuesJsonField, "{}");
      setHiddenValue(cache.additionalKeysJsonField, "[]");
      setHiddenValue(cache.originalAdditionalKeysJsonField, "[]");

      setDirty(false);
      clearFieldErrors(cache.drawer);
      closeEditorMode(reason || "reset");

      U().dispatchDocument("vectoplan:create:variant-drawer-reset", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        reason: reason || "manual"
      });

      return true;
    } catch (error) {
      warn("Could not reset variant drawer.", error);
      return false;
    }
  }

  function prepareSession(session, options) {
    try {
      var config = options || {};
      var cache = runtime.cache || cacheDom();
      var context = U().safeMerge(readContext(cache), {
        family_profile_id: session.family_profile_id || "",
        variant_profile_id: session.variant_profile_id || ""
      });

      if (profilesApi() && typeof profilesApi().getResolvedProfileBundle === "function") {
        return Promise.resolve(profilesApi().getResolvedProfileBundle(context, {
          force: !!config.force,
          source: "drawer_prepare"
        })).then(function (bundle) {
          return applyBundleToSession(session, bundle, config);
        });
      }

      return Promise.resolve(applyBundleToSession(session, localBundleFallback(context), config));
    } catch (error) {
      return Promise.reject(error);
    }
  }

  function localBundleFallback(context) {
    try {
      var profile = null;

      if (profilesApi() && typeof profilesApi().getVariantProfileLocal === "function") {
        var localProfileId = context.variant_profile_id || "";
        var localResult = localProfileId ? profilesApi().getVariantProfileLocal(localProfileId) : null;

        if (localResult && localResult.ok) {
          profile = localResult.variant_profile || localResult.profile;
        }
      }

      return {
        ok: !!profile,
        source: "drawer_local_fallback",
        context: context,
        family_profile_id: context.family_profile_id || "",
        variant_profile_id: profile ? profile.id : context.variant_profile_id || "",
        variant_profile: profile,
        profile: profile,
        empty_values: profile && profile.default_values ? U().deepClone(profile.default_values, {}) : {}
      };
    } catch (error) {
      return {
        ok: false,
        source: "drawer_local_fallback",
        context: context,
        error: normalizeError(error)
      };
    }
  }

  function applyBundleToSession(session, bundle, options) {
    try {
      var config = options || {};
      var resolved = bundle || {};
      var profile = resolved.variant_profile || resolved.profile || null;
      var emptyValues = resolved.empty_values || resolved.emptyValues || {};
      var values = U().safeMerge(emptyValues, session.definition_values || {});

      if (profile && profile.default_values) {
        values = U().safeMerge(profile.default_values, values);
      }

      if (!values["variant.label"]) {
        values["variant.label"] = session.label || (session.variant_id === "default" ? "Standard" : "Neue Variante");
      }

      if (session.variant_id) {
        values["variant.variant_id"] = session.variant_id;
      }

      if (session.description) {
        values["variant.description"] = session.description;
      }

      var additionalKeys = normalizeAdditionalFieldKeys(session.additional_field_keys || session.additionalFieldKeys || []);

      var prepared = U().safeMerge(session, {
        family_profile_id: resolved.family_profile_id || session.family_profile_id || "",
        variant_profile_id: resolved.variant_profile_id || (profile ? profile.id : "") || session.variant_profile_id || "",
        variant_profile: profile,
        profile: profile,
        definition_values: values,
        definition_values_json: U().valuesToJson(values),
        additional_field_keys: additionalKeys,
        additionalFieldKeys: additionalKeys.slice(),
        bundle: resolved,
        prepared_at: U().nowIso ? U().nowIso() : new Date().toISOString()
      });

      if (fieldRendererApi() && typeof fieldRendererApi().renderProfile === "function" && profile) {
        fieldRendererApi().renderProfile({
          profile: profile,
          values: values,
          context: U().safeMerge(readContext(), {
            family_profile_id: prepared.family_profile_id,
            variant_profile_id: prepared.variant_profile_id
          }),
          source: "drawer_prepare"
        }, config.root || null);
      }

      updateProfileDom(prepared);

      window.setTimeout(function () {
        cacheDom();
        setActionButtonLabels();
        ensureInitialSection({
          source: "bundle_applied",
          resetScroll: true,
          dispatchEvent: false
        });

        restoreOptionalFields(prepared, {
          reason: "bundle_applied"
        });
      }, 0);

      return prepared;
    } catch (error) {
      warn("Could not apply profile bundle to session.", error);
      throw error;
    }
  }

  function updateProfileDom(session) {
    try {
      var cache = runtime.cache || cacheDom();

      U().setAttr(cache.drawer, "data-vp-current-family-profile-id", session.family_profile_id || "");
      U().setAttr(cache.drawer, "data-vp-current-variant-profile-id", session.variant_profile_id || "");
      setHiddenValue(cache.familyProfileIdField, session.family_profile_id || "");
      setHiddenValue(cache.profileIdField, session.variant_profile_id || "");
      setHiddenValue(cache.valuesJsonField, U().valuesToJson(session.definition_values || {}));
      setHiddenValue(cache.additionalKeysJsonField, U().safeJsonStringify(session.additional_field_keys || [], "[]", 0));

      if (cache.summaryProfile) {
        cache.summaryProfile.textContent = session.variant_profile_id || "auto";
      }

      if (cache.summaryName) {
        cache.summaryName.textContent = session.definition_values["variant.label"] || session.label || "Neue Variante";
      }

      if (cache.summaryId) {
        cache.summaryId.textContent = session.variant_id || session.definition_values["variant.variant_id"] || "wird automatisch vergeben";
      }

      setActionButtonLabels(cache);
    } catch (error) {
      warn("Could not update profile DOM.", error);
    }
  }

  function collectValues() {
    try {
      var cache = runtime.cache || cacheDom();

      var values = {};

      if (fieldRendererApi() && typeof fieldRendererApi().collectValues === "function") {
        values = fieldRendererApi().collectValues(cache.drawer) || {};
      } else {
        U().qsa(CONTROL_SELECTOR, cache.drawer).forEach(function (control) {
          if (!control || control.type === "hidden") {
            return;
          }

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
      }

      values = collectOptionalValues(values);

      return values || {};
    } catch (error) {
      warn("Could not collect drawer values.", error);
      return {};
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

  function syncCollectedValues(values) {
    try {
      var cache = runtime.cache || cacheDom();
      var nextValues = values || collectValues();

      if (fieldRendererApi() && typeof fieldRendererApi().syncValuesJson === "function") {
        fieldRendererApi().syncValuesJson(cache.drawer, nextValues);
      } else {
        setHiddenValue(cache.valuesJsonField, U().valuesToJson(nextValues));
      }

      return nextValues;
    } catch (error) {
      warn("Could not sync collected values.", error);
      return values || {};
    }
  }

  function buildVariantFromDrawer() {
    try {
      var cache = runtime.cache || cacheDom();
      var session = runtime.active || normalizePayload({});
      var values = collectValues();

      values = U().safeMerge(session.definition_values || {}, values || {});

      var label = values["variant.label"] ||
        session.label ||
        (session.variant_id === "default" ? "Standard" : "Neue Variante");

      var description = values["variant.description"] ||
        session.description ||
        "";

      var existingIds = getExistingVariantIds();
      var variantId = session.variant_id || values["variant.variant_id"] || "";

      if (session.mode === "edit" && session.variant_id) {
        variantId = session.variant_id;
      } else if (session.is_default || variantId === "default") {
        variantId = "default";
      } else if (!variantId || variantId === "default") {
        variantId = U().buildVariantId({
          label: label,
          variantProfileId: session.variant_profile_id || U().getValue(cache.profileIdField, ""),
          existingIds: existingIds,
          index: existingIds.length + 1
        });
      } else if (session.mode !== "edit") {
        variantId = U().ensureUniqueId(variantId, existingIds);
      }

      values["variant.variant_id"] = variantId;
      values["variant.label"] = label;

      if (description) {
        values["variant.description"] = description;
      }

      var profile = session.variant_profile || session.profile || null;
      var summary = "";

      if (summaryApi() && typeof summaryApi().buildSummary === "function") {
        summary = summaryApi().buildSummary(values, profile);
      } else if (U().buildSummary) {
        summary = U().buildSummary(values, profile || {});
      }

      if (!summary) {
        summary = session.definition_summary || "Noch keine Kurzwerte";
      }

      var additionalFieldKeys = collectOptionalFieldKeys(session);

      setHiddenValue(cache.valuesJsonField, U().valuesToJson(values));
      setHiddenValue(cache.additionalKeysJsonField, U().safeJsonStringify(additionalFieldKeys, "[]", 0));

      var variant = {
        variant_id: variantId,
        variantId: variantId,
        label: label,
        name: label,
        slug: variantId,
        kind: variantId === "default" ? "standard" : "profile",
        description: description,
        is_default: variantId === "default",
        isDefault: variantId === "default",
        family_profile_id: session.family_profile_id || U().getValue(cache.familyProfileIdField, ""),
        familyProfileId: session.family_profile_id || U().getValue(cache.familyProfileIdField, ""),
        variant_profile_id: session.variant_profile_id || U().getValue(cache.profileIdField, ""),
        variantProfileId: session.variant_profile_id || U().getValue(cache.profileIdField, ""),
        definition_managed: true,
        definitionManaged: true,
        definition_values: values,
        definitionValues: values,
        definition_values_json: U().valuesToJson(values),
        definitionValuesJson: U().valuesToJson(values),
        additional_field_keys: additionalFieldKeys,
        additionalFieldKeys: additionalFieldKeys.slice(),
        definition_summary: summary,
        definitionSummary: summary
      };

      return variant;
    } catch (error) {
      warn("Could not build variant from drawer.", error);
      return null;
    }
  }

  function validateDrawer(options) {
    try {
      var config = options || {};
      var now = Date.now();

      if (now - runtime.lastValidateAt < 80 && !config.force) {
        return Promise.resolve({
          ok: true,
          skipped: true,
          reason: "deduped"
        });
      }

      runtime.lastValidateAt = now;

      var variant = buildVariantFromDrawer();

      U().dispatchDocument("vectoplan:create:variant-validation-started", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        variant: variant,
        session: getActiveSession()
      });

      U().dispatchDocument("vectoplan:create:variant-drawer-validate-started", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        variant: variant,
        session: getActiveSession()
      });

      if (validationApi() && typeof validationApi().validateDrawer === "function") {
        return Promise.resolve(validationApi().validateDrawer({
          variant: variant,
          session: getActiveSession(),
          profile: runtime.active ? runtime.active.variant_profile || runtime.active.profile : null
        })).then(function (result) {
          return finishValidation(result, variant);
        }).catch(function (error) {
          return finishValidation({
            ok: false,
            errors: [normalizeError(error)]
          }, variant);
        });
      }

      return Promise.resolve(finishValidation(localValidateVariant(variant), variant));
    } catch (error) {
      warn("Could not validate drawer.", error);

      return Promise.resolve(finishValidation({
        ok: false,
        errors: [normalizeError(error)]
      }, null));
    }
  }

  function localValidateVariant(variant) {
    try {
      var errors = [];
      var warnings = [];
      var profile = runtime.active ? runtime.active.variant_profile || runtime.active.profile : null;
      var values = variant && variant.definition_values ? variant.definition_values : {};

      if (!variant) {
        errors.push({
          code: "variant_missing",
          field_key: "",
          label: "Variante",
          message: "Variante konnte nicht aus dem Drawer gelesen werden."
        });

        return {
          ok: false,
          errors: errors,
          warnings: warnings
        };
      }

      if (!values["variant.label"]) {
        errors.push({
          code: "required",
          field_key: "variant.label",
          label: "Variantenname",
          message: "Der Variantenname ist erforderlich."
        });
      }

      if (!variant.variant_id) {
        errors.push({
          code: "required",
          field_key: "variant.variant_id",
          label: "Variant-ID",
          message: "Die Variant-ID konnte nicht automatisch erzeugt werden."
        });
      }

      if (profile && profile.required_fields) {
        U().toArray(profile.required_fields).forEach(function (fieldKey) {
          if (fieldKey === "variant.variant_id") {
            return;
          }

          var value = values[fieldKey];

          if (value === null || value === undefined || value === "") {
            errors.push({
              code: "required",
              field_key: fieldKey,
              label: fieldKey,
              message: "Pflichtfeld ist nicht ausgefüllt."
            });
          }
        });
      }

      return {
        ok: errors.length === 0,
        errors: errors,
        warnings: warnings
      };
    } catch (error) {
      return {
        ok: false,
        errors: [normalizeError(error)],
        warnings: []
      };
    }
  }

  function finishValidation(result, variant) {
    try {
      var payload = result || {};
      var errors = U().toArray(payload.errors);
      var warnings = U().toArray(payload.warnings);
      var ok = payload.ok !== undefined ? !!payload.ok : errors.length === 0;

      var finalResult = U().safeMerge(payload, {
        ok: ok,
        errors: errors,
        warnings: warnings,
        variant: variant || null
      });

      setValidationResult(finalResult);

      U().dispatchDocument("vectoplan:create:variant-validation-finished", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        ok: ok,
        errors: errors,
        warnings: warnings,
        variant: variant || null,
        session: getActiveSession()
      });

      U().dispatchDocument("vectoplan:create:variant-drawer-validate-finished", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        ok: ok,
        errors: errors,
        warnings: warnings,
        variant: variant || null,
        session: getActiveSession()
      });

      return finalResult;
    } catch (error) {
      warn("Could not finish validation.", error);

      return {
        ok: false,
        errors: [normalizeError(error)],
        warnings: [],
        variant: variant || null
      };
    }
  }

  function applyDrawer(options) {
    try {
      var now = Date.now();

      if (now - runtime.lastApplyAt < 120) {
        return Promise.resolve({
          ok: false,
          skipped: true,
          reason: "deduped"
        });
      }

      runtime.lastApplyAt = now;

      var config = options || {};

      setBusy(true, "Variante wird gespeichert.");

      U().dispatchDocument("vectoplan:create:variant-drawer-apply-started", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        session: getActiveSession()
      });

      return validateDrawer({
        force: true
      }).then(function (validationResult) {
        if (!validationResult.ok && config.allowInvalid !== true) {
          setBusy(false);
          setStatus("invalid", "Variante enthält Fehler.");

          U().dispatchDocument("vectoplan:create:variant-drawer-apply-failed", {
            component: COMPONENT_NAME,
            version: COMPONENT_VERSION,
            reason: "validation_failed",
            validation: validationResult,
            session: getActiveSession()
          });

          return {
            ok: false,
            reason: "validation_failed",
            validation: validationResult
          };
        }

        var variant = validationResult.variant || buildVariantFromDrawer();

        if (!variant) {
          throw {
            code: "variant_build_failed",
            message: "Variante konnte nicht erzeugt werden."
          };
        }

        var resultVariant = null;

        if (stateApi()) {
          if (runtime.active && runtime.active.mode === "edit") {
            var target = runtime.active.variant_id || runtime.active.rowIndex;
            resultVariant = stateApi().updateVariant(target, variant, {
              upsert: true,
              source: "drawer_apply",
              emitNativeEvents: false
            });
          } else {
            resultVariant = stateApi().addVariant(variant, {
              source: "drawer_apply",
              emitNativeEvents: false
            });
          }
        } else {
          U().dispatchDocument(runtime.active && runtime.active.mode === "edit" ? "vectoplan:create:variant-updated" : "vectoplan:create:variant-added", {
            component: COMPONENT_NAME,
            version: COMPONENT_VERSION,
            variant: variant,
            variants: [variant]
          });

          resultVariant = variant;
        }

        setBusy(false);
        setDirty(false);
        setStatus("valid", runtime.active && runtime.active.mode === "edit" ? "Variante wurde aktualisiert." : "Variante wurde gespeichert.");

        U().dispatchDocument("vectoplan:create:variant-drawer-apply-finished", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          ok: true,
          mode: runtime.active ? runtime.active.mode : "",
          variant: resultVariant || variant,
          session: getActiveSession()
        });

        close("applied");

        return {
          ok: true,
          variant: resultVariant || variant
        };
      }).catch(function (error) {
        setBusy(false);
        setStatus("error", "Variante konnte nicht gespeichert werden.");

        U().dispatchDocument("vectoplan:create:variant-drawer-apply-failed", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          error: normalizeError(error),
          session: getActiveSession()
        });

        throw error;
      });
    } catch (error) {
      warn("Could not apply variant drawer.", error);
      setBusy(false);

      return Promise.reject(error);
    }
  }

  function handleSectionNavClick(event, target) {
    try {
      var now = Date.now();

      if (now - runtime.lastSectionAt < 40) {
        return true;
      }

      runtime.lastSectionAt = now;

      if (event) {
        event.preventDefault();
        event.stopPropagation();

        if (typeof event.stopImmediatePropagation === "function") {
          event.stopImmediatePropagation();
        }
      }

      activateSectionFromButton(target, {
        source: "section_nav_click",
        resetScroll: true,
        dispatchEvent: true
      });

      return true;
    } catch (error) {
      warn("Section nav click handling failed.", error);
      return false;
    }
  }

  function handleAddClick() {
    try {
      var cache = runtime.cache || cacheDom();

      if (cache.drawer && U().attr(cache.drawer, "data-vp-variant-drawer-state", "") === "open") {
        return;
      }

      var now = Date.now();

      if (now - runtime.lastOpenAt < 120) {
        return;
      }

      open({
        mode: "create"
      }).catch(function (error) {
        warn("Add click open failed.", error);
      });
    } catch (error) {
      warn("Add click handling failed.", error);
    }
  }

  function handleEditClick(target) {
    try {
      var row = U().closest(target, ROW_SELECTOR);

      if (!row) {
        return;
      }

      open(payloadFromRow(row)).catch(function (error) {
        warn("Edit click open failed.", error);
      });
    } catch (error) {
      warn("Edit click handling failed.", error);
    }
  }

  function bindGlobalEvents() {
    try {
      if (runtime.globalEventsBound) {
        return;
      }

      document.addEventListener("click", function (event) {
        try {
          var target = event.target;

          if (!target || !target.closest) {
            return;
          }

          var sectionButton = target.closest(SECTION_NAV_ITEM_SELECTOR);

          if (sectionButton && U().closest(sectionButton, DRAWER_SELECTOR)) {
            handleSectionNavClick(event, sectionButton);
            return;
          }

          var addButton = target.closest("[data-vp-add-variant='true'], [data-create-add-variant='true']");
          if (addButton) {
            window.setTimeout(function () {
              handleAddClick(addButton);
            }, 0);
            return;
          }

          var editButton = target.closest("[data-vp-edit-definition-variant='true']");
          if (editButton) {
            window.setTimeout(function () {
              handleEditClick(editButton);
            }, 0);
          }
        } catch (error) {
          warn("Global click handling failed.", error);
        }
      }, true);

      document.addEventListener("keydown", function (event) {
        try {
          var target = event.target;

          if (!target || !target.closest) {
            return;
          }

          var sectionButton = target.closest(SECTION_NAV_ITEM_SELECTOR);

          if (!sectionButton || !U().closest(sectionButton, DRAWER_SELECTOR)) {
            return;
          }

          if (event.key === "Enter" || event.key === " ") {
            handleSectionNavClick(event, sectionButton);
            return;
          }

          if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
            return;
          }

          var cache = runtime.cache || cacheDom(sectionButton);

          if (shouldRevealAllSections(cache)) {
            return;
          }

          var buttons = ensureSectionStructure(cache).buttons;

          if (!buttons.length) {
            return;
          }

          event.preventDefault();

          var index = buttons.indexOf ? buttons.indexOf(sectionButton) : U().toArray(buttons).indexOf(sectionButton);
          var nextIndex = index;

          if (event.key === "ArrowDown" || event.key === "ArrowRight") {
            nextIndex = index + 1;
          } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
            nextIndex = index - 1;
          }

          if (nextIndex < 0) {
            nextIndex = buttons.length - 1;
          }

          if (nextIndex >= buttons.length) {
            nextIndex = 0;
          }

          var nextButton = buttons[nextIndex];

          if (nextButton) {
            activateSectionFromButton(nextButton, {
              source: "section_nav_keyboard",
              resetScroll: true,
              dispatchEvent: true
            });

            if (typeof nextButton.focus === "function") {
              nextButton.focus();
            }
          }
        } catch (error) {
          warn("Section nav keyboard handling failed.", error);
        }
      }, true);

      document.addEventListener("vectoplan:create:variant-add-requested", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail && detail.handledByVariantDrawer) {
            return;
          }

          open({
            mode: "create"
          }).catch(function (error) {
            warn("Variant add request failed.", error);
          });
        } catch (error) {
          warn("Variant add request listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-edit-requested", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          open(detail).catch(function (error) {
            warn("Variant edit request failed.", error);
          });
        } catch (error) {
          warn("Variant edit request listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-drawer-validate-requested", function () {
        validateDrawer({
          force: true
        }).catch(function (error) {
          warn("Validate request failed.", error);
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-apply-requested", function () {
        applyDrawer().catch(function (error) {
          warn("Apply request failed.", error);
        });
      });

      document.addEventListener("vectoplan:create:variant-drawer-cancel-requested", function () {
        close("cancel_requested");
      });

      document.addEventListener("vectoplan:create:variant-empty-state-close-requested", function () {
        close("empty_state_close_requested");
      });

      document.addEventListener("vectoplan:create:variant-values-changed", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (runtime.active) {
            runtime.active.definition_values = U().safeMerge(runtime.active.definition_values || {}, detail.values || {});
            runtime.active.definition_values_json = U().valuesToJson(runtime.active.definition_values);

            if (detail.additional_field_keys || detail.additionalFieldKeys) {
              runtime.active.additional_field_keys = normalizeAdditionalFieldKeys(detail.additional_field_keys || detail.additionalFieldKeys || []);
              runtime.active.additionalFieldKeys = runtime.active.additional_field_keys.slice();
            }
          }

          setDirty(true);
        } catch (error) {
          warn("Values changed listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-fields-rendered", function () {
        try {
          window.setTimeout(function () {
            cacheDom();
            setActionButtonLabels();
            ensureInitialSection({
              source: "fields_rendered",
              resetScroll: true,
              dispatchEvent: false
            });

            if (runtime.active) {
              restoreOptionalFields(runtime.active, {
                reason: "fields_rendered"
              });
            }
          }, 0);
        } catch (error) {
          warn("Fields rendered section setup failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-profile-resolution-failed", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          setStatus("error", detail && detail.error && detail.error.message ? detail.error.message : "Profilauflösung fehlgeschlagen.");
        } catch (error) {
          warn("Profile resolution failed listener failed.", error);
        }
      });

      runtime.globalEventsBound = true;
    } catch (error) {
      warn("Could not bind variant drawer global events.", error);
    }
  }

  function getActiveSession() {
    try {
      return U().deepClone(runtime.active, null);
    } catch (error) {
      return runtime.active;
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
      var cache = runtime.cache || cacheDom();

      return {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        initialized: runtime.initialized,
        editorMode: runtime.editorMode,
        cleanShell: isCleanShell(cache),
        revealAllSections: shouldRevealAllSections(cache),
        hasActiveSession: !!runtime.active,
        activeSectionId: runtime.activeSectionId,
        activeSession: runtime.active ? {
          session_id: runtime.active.session_id,
          mode: runtime.active.mode,
          variant_id: runtime.active.variant_id,
          variant_profile_id: runtime.active.variant_profile_id,
          family_profile_id: runtime.active.family_profile_id,
          additional_field_keys: runtime.active.additional_field_keys || []
        } : null,
        hasDrawer: !!(cache && cache.drawer),
        hasWorkspace: !!(cache && cache.workspace),
        hasObjectVariantsSection: !!(cache && cache.objectVariantsSection),
        hasObjectVariantsTop: !!(cache && cache.objectVariantsTop),
        objectKindAreaHidden: !!(cache && cache.objectVariantsTop && cache.objectVariantsTop.hidden),
        hasTableSlot: !!(cache && cache.tableSlot),
        hasDrawerSlot: !!(cache && cache.drawerSlot),
        sectionCount: cache && cache.sections ? cache.sections.length : 0,
        sectionButtonCount: cache && cache.sectionButtons ? cache.sectionButtons.length : 0,
        modules: {
          shell: !!shellApi(),
          profiles: !!profilesApi(),
          fieldRenderer: !!fieldRendererApi(),
          state: !!stateApi(),
          validation: !!validationApi(),
          summary: !!summaryApi(),
          optionalFields: !!optionalFieldsApi()
        }
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

      cacheDom(config.root || null);
      bindGlobalEvents();
      setActionButtonLabels();

      ensureInitialSection({
        source: "initialize",
        resetScroll: false,
        dispatchEvent: false
      });

      setEditorMode(runtime.editorMode || "closed", {
        source: "initialize",
        forceEvent: false
      });

      runtime.initialized = true;

      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-drawer-version", COMPONENT_VERSION);

      U().dispatchDocument("vectoplan:create:variant-drawer-ready", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        snapshot: getRuntimeSnapshot()
      });

      return true;
    } catch (error) {
      warn("Could not initialize variant drawer.", error);
      return false;
    }
  }

  var api = {
    __name: COMPONENT_NAME,
    __version: COMPONENT_VERSION,

    initialize: initialize,

    open: open,
    close: close,
    reset: reset,

    setEditorMode: setEditorMode,
    openEditorMode: openEditorMode,
    closeEditorMode: closeEditorMode,

    prepareSession: prepareSession,
    collectValues: collectValues,
    syncCollectedValues: syncCollectedValues,
    buildVariantFromDrawer: buildVariantFromDrawer,

    activateSection: activateSection,
    activateSectionFromButton: activateSectionFromButton,
    ensureInitialSection: ensureInitialSection,
    getActiveSectionId: function () {
      return runtime.activeSectionId || getActiveSectionId(runtime.cache || cacheDom());
    },

    validateDrawer: validateDrawer,
    applyDrawer: applyDrawer,

    getActiveSession: getActiveSession,
    getRuntimeSnapshot: getRuntimeSnapshot,

    cacheDom: cacheDom,
    readContext: readContext
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
    warn("Could not bootstrap variant drawer.", bootstrapError);
  }
})();