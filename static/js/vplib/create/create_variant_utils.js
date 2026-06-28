/* services/vectoplan-library/static/js/vplib/create/create_variant_utils.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateVariantUtils";
  var COMPONENT_NAME = "VECTOPLAN Create Variant Utils";
  var COMPONENT_VERSION = "0.7.0";
  var READY_ATTR = "data-vp-create-variant-utils-ready";

  if (window[GLOBAL_NAME] && window[GLOBAL_NAME].__version === COMPONENT_VERSION) {
    try {
      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-utils-version", COMPONENT_VERSION);
    } catch (alreadyReadyError) {
      /* no-op */
    }

    return;
  }

  var EVENT_GUARD = {
    customStack: [],
    customDepthByName: {},
    nativeNodeLock: typeof WeakMap !== "undefined" ? new WeakMap() : null,
    nativeFallbackLock: {},
    suppressedCustomCount: 0,
    suppressedNativeCount: 0,
    dispatchedCustomCount: 0,
    dispatchedNativeCount: 0,
    maxCustomDepth: 24,
    nativeCooldownMs: 8,
    debugNativeEvents: false,
    debugCustomEvents: false
  };

  var RECURSIVE_CUSTOM_EVENTS = {
    "vectoplan:create:variant-state-synced": true,
    "vectoplan:create:variant-state-changed": true,
    "vectoplan:create:variant-table-synced": true,
    "vectoplan:create:variant-table-rendered": true,
    "vectoplan:create:definition-variants-synced": true,
    "vectoplan:create:definitions-variants-synced": true,
    "vectoplan:create:payload-variants-synced": true,
    "vectoplan:create:payload-uploads-synced": true,
    "vectoplan:create:upload-changed": true,
    "vectoplan:create:upload-cleared": true,
    "vectoplan:create:uploads-synced": true,
    "vectoplan:create:context-synced": true
  };

  var SYNC_NATIVE_EVENTS = {
    input: true,
    change: true
  };

  var SYSTEM_VARIANT_KEYS = {
    "variant.variant_id": true,
    "variant.variantId": true,
    "variant.id": true,
    "variant_id": true,
    "variantId": true,
    "id": true
  };

  var DOCUMENT_VALUE_TYPES = {
    document: true,
    documents: true,
    document_list: true,
    documentList: true,
    file: true,
    file_list: true,
    fileList: true
  };

  function log(level, message, payload) {
    try {
      var consoleRef = window.console;

      if (!consoleRef) {
        return;
      }

      var method = consoleRef[level];

      if (typeof method !== "function") {
        method = consoleRef.log;
      }

      if (typeof method === "function") {
        if (payload !== undefined && payload !== null && payload !== "") {
          method.call(consoleRef, "[" + COMPONENT_NAME + "] " + String(message || ""), payload);
        } else {
          method.call(consoleRef, "[" + COMPONENT_NAME + "] " + String(message || ""));
        }
      }
    } catch (error) {
      /* no-op */
    }
  }

  function warn(message, payload) {
    log("warn", message, payload);
  }

  function info(message, payload) {
    log("info", message, payload);
  }

  function debug(message, payload) {
    try {
      if (window.console && typeof window.console.debug === "function") {
        window.console.debug("[" + COMPONENT_NAME + "] " + String(message || ""), payload || "");
        return;
      }

      log("log", message, payload);
    } catch (error) {
      /* no-op */
    }
  }

  function error(message, payload) {
    log("error", message, payload);
  }

  function isDebugEnabled(kind) {
    try {
      var root = document.documentElement;
      var globalDebug = root.getAttribute("data-vp-create-debug") === "true";
      var nativeDebug = root.getAttribute("data-vp-create-debug-native-events") === "true";
      var customDebug = root.getAttribute("data-vp-create-debug-custom-events") === "true";

      if (kind === "native") {
        return EVENT_GUARD.debugNativeEvents || globalDebug || nativeDebug;
      }

      if (kind === "custom") {
        return EVENT_GUARD.debugCustomEvents || globalDebug || customDebug;
      }

      return globalDebug;
    } catch (eventDebugError) {
      return false;
    }
  }

  function isNil(value) {
    return value === null || value === undefined;
  }

  function isString(value) {
    return typeof value === "string" || value instanceof String;
  }

  function isNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  function isBoolean(value) {
    return typeof value === "boolean";
  }

  function isFunction(value) {
    return typeof value === "function";
  }

  function isArray(value) {
    try {
      return Array.isArray(value);
    } catch (error) {
      return Object.prototype.toString.call(value) === "[object Array]";
    }
  }

  function isObject(value) {
    return !!value && typeof value === "object" && !isArray(value);
  }

  function isPlainObject(value) {
    try {
      if (!value || Object.prototype.toString.call(value) !== "[object Object]") {
        return false;
      }

      var proto = Object.getPrototypeOf(value);
      return proto === Object.prototype || proto === null;
    } catch (error) {
      return isObject(value);
    }
  }

  function isElement(value) {
    try {
      return !!value && value.nodeType === 1;
    } catch (error) {
      return false;
    }
  }

  function hasOwn(object, key) {
    try {
      return Object.prototype.hasOwnProperty.call(object, key);
    } catch (error) {
      return false;
    }
  }

  function toString(value, fallback) {
    try {
      if (isNil(value)) {
        return fallback || "";
      }

      return String(value);
    } catch (error) {
      return fallback || "";
    }
  }

  function trim(value) {
    try {
      return toString(value).trim();
    } catch (error) {
      return "";
    }
  }

  function lower(value) {
    try {
      return trim(value).toLowerCase();
    } catch (error) {
      return "";
    }
  }

  function upper(value) {
    try {
      return trim(value).toUpperCase();
    } catch (error) {
      return "";
    }
  }

  function bool(value, fallback) {
    try {
      if (isBoolean(value)) {
        return value;
      }

      if (isNumber(value)) {
        return value !== 0;
      }

      var text = lower(value);

      if (["true", "1", "yes", "ja", "y", "on", "ok", "enabled", "active", "selected", "default", "ready"].indexOf(text) !== -1) {
        return true;
      }

      if (["false", "0", "no", "nein", "n", "off", "disabled", "inactive", ""].indexOf(text) !== -1) {
        return false;
      }

      return !!fallback;
    } catch (error) {
      return !!fallback;
    }
  }

  function intValue(value, fallback) {
    try {
      if (value === "" || isNil(value)) {
        return isNil(fallback) ? 0 : fallback;
      }

      var parsed = parseInt(value, 10);

      if (isNaN(parsed)) {
        return isNil(fallback) ? 0 : fallback;
      }

      return parsed;
    } catch (error) {
      return isNil(fallback) ? 0 : fallback;
    }
  }

  function floatValue(value, fallback) {
    try {
      if (value === "" || isNil(value)) {
        return isNil(fallback) ? 0 : fallback;
      }

      var parsed = parseFloat(String(value).replace(",", "."));

      if (isNaN(parsed)) {
        return isNil(fallback) ? 0 : fallback;
      }

      return parsed;
    } catch (error) {
      return isNil(fallback) ? 0 : fallback;
    }
  }

  function clamp(value, min, max) {
    try {
      var number = floatValue(value, 0);

      if (isNumber(min) && number < min) {
        return min;
      }

      if (isNumber(max) && number > max) {
        return max;
      }

      return number;
    } catch (error) {
      return value;
    }
  }

  function toArray(value) {
    try {
      if (!value) {
        return [];
      }

      if (isArray(value)) {
        return value.slice();
      }

      if (typeof value.length === "number" && !isString(value) && !isFunction(value)) {
        return Array.prototype.slice.call(value);
      }

      return [value];
    } catch (error) {
      return [];
    }
  }

  function objectValues(value) {
    try {
      if (!isObject(value)) {
        return [];
      }

      return Object.keys(value).map(function (key) {
        return value[key];
      });
    } catch (error) {
      return [];
    }
  }

  function toArrayOrObjectValues(value) {
    try {
      if (isArray(value)) {
        return value.slice();
      }

      if (isPlainObject(value)) {
        return objectValues(value);
      }

      return toArray(value);
    } catch (error) {
      return [];
    }
  }

  function uniqueArray(values) {
    try {
      var seen = {};
      var result = [];

      toArray(values).forEach(function (item) {
        var key = toString(item);

        if (!key || seen[key]) {
          return;
        }

        seen[key] = true;
        result.push(item);
      });

      return result;
    } catch (error) {
      return [];
    }
  }

  function compactArray(values) {
    try {
      return toArray(values).filter(function (item) {
        return !isNil(item) && trim(item) !== "";
      });
    } catch (error) {
      return [];
    }
  }

  function safeJsonParse(value, fallback) {
    try {
      if (isNil(value)) {
        return isNil(fallback) ? null : fallback;
      }

      if (isObject(value) || isArray(value)) {
        return value;
      }

      var text = trim(value);

      if (!text) {
        return isNil(fallback) ? null : fallback;
      }

      return JSON.parse(text);
    } catch (error) {
      return isNil(fallback) ? null : fallback;
    }
  }

  function safeJsonStringify(value, fallback, spacing) {
    try {
      return JSON.stringify(value, null, isNil(spacing) ? 0 : spacing);
    } catch (error) {
      return isNil(fallback) ? "" : fallback;
    }
  }

  function deepClone(value, fallback) {
    try {
      if (isNil(value)) {
        return isNil(fallback) ? value : fallback;
      }

      if (typeof structuredClone === "function") {
        return structuredClone(value);
      }

      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      if (!isNil(fallback)) {
        return fallback;
      }

      if (isArray(value)) {
        return value.slice();
      }

      if (isPlainObject(value)) {
        return shallowClone(value);
      }

      return value;
    }
  }

  function shallowClone(value) {
    try {
      if (isArray(value)) {
        return value.slice();
      }

      if (!isObject(value)) {
        return value;
      }

      var output = {};
      Object.keys(value).forEach(function (key) {
        output[key] = value[key];
      });

      return output;
    } catch (error) {
      return {};
    }
  }

  function safeMerge() {
    try {
      var output = {};

      Array.prototype.slice.call(arguments).forEach(function (object) {
        if (!isObject(object)) {
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
  }

  function deepMerge() {
    try {
      var output = {};

      Array.prototype.slice.call(arguments).forEach(function (object) {
        if (!isObject(object)) {
          return;
        }

        Object.keys(object).forEach(function (key) {
          var value = object[key];

          if (isPlainObject(value) && isPlainObject(output[key])) {
            output[key] = deepMerge(output[key], value);
          } else if (isArray(value)) {
            output[key] = value.slice();
          } else if (isPlainObject(value)) {
            output[key] = deepMerge(value);
          } else {
            output[key] = value;
          }
        });
      });

      return output;
    } catch (error) {
      return {};
    }
  }

  function qs(selector, root) {
    try {
      if (!selector) {
        return null;
      }

      return (root || document).querySelector(selector);
    } catch (error) {
      return null;
    }
  }

  function qsa(selector, root) {
    try {
      if (!selector) {
        return [];
      }

      return toArray((root || document).querySelectorAll(selector));
    } catch (error) {
      return [];
    }
  }

  function closest(node, selector) {
    try {
      if (!node || !selector || !node.closest) {
        return null;
      }

      return node.closest(selector);
    } catch (error) {
      return null;
    }
  }

  function contains(root, node) {
    try {
      return !!root && !!node && root.contains(node);
    } catch (error) {
      return false;
    }
  }

  function attr(node, name, fallback) {
    try {
      if (!node || !name) {
        return fallback || "";
      }

      var value = node.getAttribute(name);

      if (isNil(value)) {
        return fallback || "";
      }

      return value;
    } catch (error) {
      return fallback || "";
    }
  }

  function setAttr(node, name, value) {
    try {
      if (!node || !name) {
        return false;
      }

      var current = node.getAttribute(name);
      var next = isNil(value) ? null : String(value);

      if (current === next) {
        return false;
      }

      if (isNil(value)) {
        node.removeAttribute(name);
      } else {
        node.setAttribute(name, next);
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function boolAttr(node, name, fallback) {
    try {
      return bool(attr(node, name, fallback ? "true" : "false"), fallback);
    } catch (error) {
      return !!fallback;
    }
  }

  function dataset(node, key, fallback) {
    try {
      if (!node || !key) {
        return fallback || "";
      }

      if (node.dataset && !isNil(node.dataset[key])) {
        return node.dataset[key];
      }

      var attrName = "data-" + key.replace(/[A-Z]/g, function (letter) {
        return "-" + letter.toLowerCase();
      });

      return attr(node, attrName, fallback);
    } catch (error) {
      return fallback || "";
    }
  }

  function setDataset(node, key, value) {
    try {
      if (!node || !key) {
        return false;
      }

      if (node.dataset) {
        var next = isNil(value) ? "" : String(value);

        if (node.dataset[key] === next) {
          return false;
        }

        node.dataset[key] = next;
        return true;
      }

      var attrName = "data-" + key.replace(/[A-Z]/g, function (letter) {
        return "-" + letter.toLowerCase();
      });

      return setAttr(node, attrName, value);
    } catch (error) {
      return false;
    }
  }

  function setText(node, value) {
    try {
      if (!node) {
        return false;
      }

      var next = isNil(value) ? "" : String(value);

      if (node.textContent === next) {
        return false;
      }

      node.textContent = next;
      return true;
    } catch (error) {
      return false;
    }
  }

  function setHtml(node, value) {
    try {
      if (!node) {
        return false;
      }

      var next = isNil(value) ? "" : String(value);

      if (node.innerHTML === next) {
        return false;
      }

      node.innerHTML = next;
      return true;
    } catch (error) {
      return false;
    }
  }

  function setValue(node, value, dispatchEvents) {
    try {
      if (!node) {
        return false;
      }

      var changed = false;

      if (node.type === "checkbox") {
        var nextChecked = bool(value, false);
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
        var nextValue = isNil(value) ? "" : String(value);

        if (node.value !== nextValue) {
          node.value = nextValue;
          changed = true;
        }
      }

      if (changed && dispatchEvents) {
        var options = dispatchEvents === true ? { source: "setValue" } : dispatchEvents;
        dispatchNative(node, "input", options || { source: "setValue" });
        dispatchNative(node, "change", options || { source: "setValue" });
      }

      return changed;
    } catch (error) {
      return false;
    }
  }

  function getValue(node, fallback) {
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
  }

  function setHidden(node, hidden) {
    try {
      if (!node) {
        return false;
      }

      var next = !!hidden;
      var changed = node.hidden !== next;

      node.hidden = next;

      if (next) {
        changed = setAttr(node, "hidden", "") || changed;
        changed = setAttr(node, "aria-hidden", "true") || changed;
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
  }

  function setDisabled(node, disabled, reason) {
    try {
      if (!node) {
        return false;
      }

      var next = !!disabled;
      var changed = node.disabled !== next;

      node.disabled = next;

      if (next) {
        changed = setAttr(node, "aria-disabled", "true") || changed;

        if (reason) {
          changed = setAttr(node, "data-vp-disabled-reason", reason) || changed;
        }
      } else {
        if (node.hasAttribute("aria-disabled")) {
          node.removeAttribute("aria-disabled");
          changed = true;
        }

        if (node.hasAttribute("data-vp-disabled-reason")) {
          node.removeAttribute("data-vp-disabled-reason");
          changed = true;
        }
      }

      return changed;
    } catch (error) {
      return false;
    }
  }

  function addClass(node, className) {
    try {
      if (node && className && !node.classList.contains(className)) {
        node.classList.add(className);
        return true;
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function removeClass(node, className) {
    try {
      if (node && className && node.classList.contains(className)) {
        node.classList.remove(className);
        return true;
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function toggleClass(node, className, force) {
    try {
      if (node && className) {
        var before = node.classList.contains(className);
        node.classList.toggle(className, !!force);
        return before !== node.classList.contains(className);
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function empty(node) {
    try {
      if (!node) {
        return false;
      }

      var changed = !!node.firstChild;

      while (node.firstChild) {
        node.removeChild(node.firstChild);
      }

      return changed;
    } catch (error) {
      return false;
    }
  }

  function createElement(tagName, attributes, children) {
    try {
      var node = document.createElement(tagName || "div");

      if (isObject(attributes)) {
        Object.keys(attributes).forEach(function (key) {
          var value = attributes[key];

          if (key === "class") {
            node.className = String(value || "");
          } else if (key === "text") {
            node.textContent = String(value || "");
          } else if (key === "html") {
            node.innerHTML = String(value || "");
          } else if (key === "dataset" && isObject(value)) {
            Object.keys(value).forEach(function (dataKey) {
              setDataset(node, dataKey, value[dataKey]);
            });
          } else if (key === "attrs" && isObject(value)) {
            Object.keys(value).forEach(function (attrKey) {
              setAttr(node, attrKey, value[attrKey]);
            });
          } else if (key === "hidden") {
            setHidden(node, !!value);
          } else if (key === "disabled") {
            setDisabled(node, !!value);
          } else if (key in node) {
            try {
              node[key] = value;
            } catch (innerError) {
              setAttr(node, key, value);
            }
          } else {
            setAttr(node, key, value);
          }
        });
      }

      toArray(children).forEach(function (child) {
        try {
          if (isNil(child)) {
            return;
          }

          if (typeof child === "string") {
            node.appendChild(document.createTextNode(child));
          } else {
            node.appendChild(child);
          }
        } catch (childError) {
          warn("Could not append child.", childError);
        }
      });

      return node;
    } catch (error) {
      warn("Could not create element.", error);
      return document.createElement("div");
    }
  }

  function htmlToElement(html) {
    try {
      var template = document.createElement("template");
      template.innerHTML = String(html || "").trim();
      return template.content.firstElementChild;
    } catch (error) {
      return null;
    }
  }

  function templateHtml(template) {
    try {
      if (!template) {
        return "";
      }

      if ("innerHTML" in template && template.innerHTML) {
        return template.innerHTML;
      }

      if ("content" in template && template.content) {
        var wrapper = document.createElement("div");
        wrapper.appendChild(template.content.cloneNode(true));
        return wrapper.innerHTML;
      }

      return template.textContent || "";
    } catch (error) {
      return "";
    }
  }

  function renderTemplate(template, replacements) {
    try {
      var html = templateHtml(template);
      var map = replacements || {};

      Object.keys(map).forEach(function (key) {
        var token = "__" + key + "__";
        html = html.split(token).join(escapeAttr(map[key]));
      });

      return htmlToElement(html);
    } catch (error) {
      warn("Could not render template.", error);
      return null;
    }
  }

  function cache(root, selectorMap) {
    try {
      var output = {
        root: root || document
      };

      if (!isObject(selectorMap)) {
        return output;
      }

      Object.keys(selectorMap).forEach(function (key) {
        var selector = selectorMap[key];

        if (isArray(selector)) {
          output[key] = qsa(selector[0], root);
        } else {
          output[key] = qs(selector, root);
        }
      });

      return output;
    } catch (error) {
      warn("Could not build DOM cache.", error);
      return {
        root: root || document
      };
    }
  }

  function eventGuardKey(node, eventName) {
    try {
      var nodeKey = "document";

      if (node && node !== document) {
        if (!node.__vpVariantUtilsEventUid) {
          node.__vpVariantUtilsEventUid = uid("event_node");
        }

        nodeKey = node.__vpVariantUtilsEventUid;
      }

      return nodeKey + "::" + String(eventName || "");
    } catch (error) {
      return "unknown::" + String(eventName || "");
    }
  }

  function isRecursiveCustomEvent(eventName) {
    try {
      return !!RECURSIVE_CUSTOM_EVENTS[String(eventName || "")];
    } catch (error) {
      return false;
    }
  }

  function isCustomEventActive(eventName) {
    try {
      var name = String(eventName || "");

      if (!name) {
        return false;
      }

      return intValue(EVENT_GUARD.customDepthByName[name], 0) > 0;
    } catch (error) {
      return false;
    }
  }

  function pushCustomEvent(eventName) {
    try {
      var name = String(eventName || "");

      EVENT_GUARD.customStack.push(name);
      EVENT_GUARD.customDepthByName[name] = intValue(EVENT_GUARD.customDepthByName[name], 0) + 1;
    } catch (error) {
      /* no-op */
    }
  }

  function popCustomEvent(eventName) {
    try {
      var name = String(eventName || "");
      var last = EVENT_GUARD.customStack[EVENT_GUARD.customStack.length - 1];

      if (last === name) {
        EVENT_GUARD.customStack.pop();
      } else {
        var index = EVENT_GUARD.customStack.lastIndexOf(name);

        if (index !== -1) {
          EVENT_GUARD.customStack.splice(index, 1);
        }
      }

      EVENT_GUARD.customDepthByName[name] = Math.max(0, intValue(EVENT_GUARD.customDepthByName[name], 0) - 1);

      if (EVENT_GUARD.customDepthByName[name] <= 0) {
        delete EVENT_GUARD.customDepthByName[name];
      }
    } catch (error) {
      /* no-op */
    }
  }

  function getNativeLock(node) {
    try {
      if (!node) {
        return {};
      }

      if (EVENT_GUARD.nativeNodeLock) {
        return EVENT_GUARD.nativeNodeLock.get(node) || {};
      }

      return EVENT_GUARD.nativeFallbackLock[eventGuardKey(node, "__lock")] || {};
    } catch (error) {
      return {};
    }
  }

  function setNativeLock(node, lock) {
    try {
      if (!node) {
        return;
      }

      if (EVENT_GUARD.nativeNodeLock) {
        if (lock && Object.keys(lock).length) {
          EVENT_GUARD.nativeNodeLock.set(node, lock);
        } else {
          EVENT_GUARD.nativeNodeLock.delete(node);
        }

        return;
      }

      var key = eventGuardKey(node, "__lock");

      if (lock && Object.keys(lock).length) {
        EVENT_GUARD.nativeFallbackLock[key] = lock;
      } else {
        delete EVENT_GUARD.nativeFallbackLock[key];
      }
    } catch (error) {
      /* no-op */
    }
  }

  function markNativeActive(node, eventName) {
    try {
      if (!node || !eventName) {
        return;
      }

      var safeEventName = String(eventName || "");
      var lock = getNativeLock(node);

      lock[safeEventName] = true;
      setNativeLock(node, lock);

      window.setTimeout(function () {
        try {
          var current = getNativeLock(node);
          delete current[safeEventName];
          setNativeLock(node, current);
        } catch (cleanupError) {
          /* no-op */
        }
      }, EVENT_GUARD.nativeCooldownMs);
    } catch (error) {
      /* no-op */
    }
  }

  function isNativeActive(node, eventName) {
    try {
      if (!node || !eventName) {
        return false;
      }

      var lock = getNativeLock(node);
      return !!lock[String(eventName || "")];
    } catch (error) {
      return false;
    }
  }

  function markProgrammaticEvent(node, eventName, source) {
    try {
      if (!node || !node.setAttribute) {
        return;
      }

      node.setAttribute("data-vp-programmatic-event", String(eventName || ""));
      node.setAttribute("data-vp-programmatic-event-source", String(source || "variant-utils"));
      node.__vpProgrammaticEvent = {
        eventName: String(eventName || ""),
        source: String(source || "variant-utils"),
        timestamp: Date.now()
      };

      window.setTimeout(function () {
        try {
          if (node.getAttribute("data-vp-programmatic-event") === String(eventName || "")) {
            node.removeAttribute("data-vp-programmatic-event");
            node.removeAttribute("data-vp-programmatic-event-source");
          }

          if (node.__vpProgrammaticEvent && node.__vpProgrammaticEvent.eventName === String(eventName || "")) {
            delete node.__vpProgrammaticEvent;
          }
        } catch (cleanupError) {
          /* no-op */
        }
      }, 0);
    } catch (error) {
      /* no-op */
    }
  }

  function isProgrammaticEventTarget(node) {
    try {
      if (!node) {
        return false;
      }

      if (node.getAttribute && node.getAttribute("data-vp-programmatic-event")) {
        return true;
      }

      if (node.__vpProgrammaticEvent) {
        return true;
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function shouldSuppressCustomDispatch(eventName) {
    try {
      if (!eventName) {
        return false;
      }

      if (EVENT_GUARD.customStack.length > EVENT_GUARD.maxCustomDepth) {
        return true;
      }

      if (isRecursiveCustomEvent(eventName) && isCustomEventActive(eventName)) {
        return true;
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function dispatch(node, eventName, detail, options) {
    try {
      if (!node || !eventName) {
        return null;
      }

      var safeEventName = String(eventName || "");
      var config = options || {};

      if (shouldSuppressCustomDispatch(safeEventName)) {
        EVENT_GUARD.suppressedCustomCount += 1;

        if (isDebugEnabled("custom") && !config.silent) {
          debug("Suppressed recursive custom event: " + safeEventName, {
            eventName: safeEventName,
            stack: EVENT_GUARD.customStack.slice(),
            suppressedCustomCount: EVENT_GUARD.suppressedCustomCount
          });
        }

        return {
          type: safeEventName,
          detail: detail || {},
          defaultPrevented: false,
          suppressed: true
        };
      }

      var safeDetail = isObject(detail) ? detail : {};
      var event = new CustomEvent(safeEventName, {
        bubbles: config.bubbles !== false,
        cancelable: !!config.cancelable,
        detail: safeMerge(safeDetail, {
          __vp_dispatch_source: safeDetail.__vp_dispatch_source || config.source || "variant-utils",
          __vp_dispatch_timestamp: nowIso()
        })
      });

      pushCustomEvent(safeEventName);

      try {
        node.dispatchEvent(event);
        EVENT_GUARD.dispatchedCustomCount += 1;
      } finally {
        popCustomEvent(safeEventName);
      }

      return event;
    } catch (dispatchError) {
      warn("Could not dispatch custom event: " + eventName, dispatchError);
      return null;
    }
  }

  function dispatchDocument(eventName, detail, options) {
    return dispatch(document, eventName, detail, options);
  }

  function dispatchNative(node, eventName, options) {
    try {
      if (!node || !eventName) {
        return false;
      }

      var safeEventName = String(eventName || "");
      var config = options || {};
      var source = config.source || "variant-utils";

      if (SYNC_NATIVE_EVENTS[safeEventName] && isNativeActive(node, safeEventName)) {
        EVENT_GUARD.suppressedNativeCount += 1;

        if (isDebugEnabled("native") && !config.silent) {
          debug("Suppressed recursive native event: " + safeEventName, {
            node: node,
            eventName: safeEventName,
            source: source,
            suppressedNativeCount: EVENT_GUARD.suppressedNativeCount
          });
        }

        return false;
      }

      if (SYNC_NATIVE_EVENTS[safeEventName]) {
        markNativeActive(node, safeEventName);
        markProgrammaticEvent(node, safeEventName, source);
      }

      try {
        node.dispatchEvent(new Event(safeEventName, {
          bubbles: true,
          cancelable: false
        }));

        EVENT_GUARD.dispatchedNativeCount += 1;
        return true;
      } catch (modernError) {
        try {
          var event = document.createEvent("Event");
          event.initEvent(safeEventName, true, false);
          node.dispatchEvent(event);
          EVENT_GUARD.dispatchedNativeCount += 1;
          return true;
        } catch (legacyError) {
          return false;
        }
      }
    } catch (nativeError) {
      return false;
    }
  }

  function on(node, eventName, handler, options) {
    try {
      if (!node || !eventName || !isFunction(handler)) {
        return function () {};
      }

      node.addEventListener(eventName, handler, options || false);

      return function () {
        try {
          node.removeEventListener(eventName, handler, options || false);
        } catch (error) {
          /* no-op */
        }
      };
    } catch (bindError) {
      warn("Could not bind event: " + eventName, bindError);
      return function () {};
    }
  }

  function once(node, eventName, handler) {
    try {
      return on(node, eventName, handler, {
        once: true
      });
    } catch (error) {
      return function () {};
    }
  }

  function delegate(root, eventName, selector, handler) {
    try {
      if (!root || !eventName || !selector || !isFunction(handler)) {
        return function () {};
      }

      return on(root, eventName, function (event) {
        try {
          var target = event.target && event.target.closest ? event.target.closest(selector) : null;

          if (!target || !root.contains(target)) {
            return;
          }

          handler.call(target, event, target);
        } catch (delegateError) {
          warn("Delegated event failed: " + eventName + " / " + selector, delegateError);
        }
      });
    } catch (error) {
      warn("Could not bind delegated event.", error);
      return function () {};
    }
  }

  function debounce(fn, wait) {
    var timeout = null;

    return function () {
      var context = this;
      var args = arguments;

      try {
        window.clearTimeout(timeout);
        timeout = window.setTimeout(function () {
          try {
            fn.apply(context, args);
          } catch (error) {
            warn("Debounced function failed.", error);
          }
        }, intValue(wait, 0));
      } catch (error) {
        warn("Debounce failed.", error);
      }
    };
  }

  function throttle(fn, wait) {
    var locked = false;
    var lastArgs = null;
    var lastContext = null;
    var delay = intValue(wait, 0);

    function run() {
      try {
        if (lastArgs) {
          var args = lastArgs;
          var context = lastContext;

          lastArgs = null;
          lastContext = null;

          fn.apply(context, args);

          window.setTimeout(run, delay);
        } else {
          locked = false;
        }
      } catch (error) {
        locked = false;
        warn("Throttled function failed.", error);
      }
    }

    return function () {
      try {
        if (locked) {
          lastArgs = arguments;
          lastContext = this;
          return;
        }

        locked = true;
        fn.apply(this, arguments);
        window.setTimeout(run, delay);
      } catch (error) {
        locked = false;
        warn("Throttle failed.", error);
      }
    };
  }

  function transliterate(value) {
    try {
      return toString(value)
        .replace(/Ä/g, "Ae")
        .replace(/Ö/g, "Oe")
        .replace(/Ü/g, "Ue")
        .replace(/ä/g, "ae")
        .replace(/ö/g, "oe")
        .replace(/ü/g, "ue")
        .replace(/ß/g, "ss");
    } catch (error) {
      return toString(value);
    }
  }

  function stripDiacritics(value) {
    try {
      return transliterate(value)
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "");
    } catch (error) {
      return transliterate(value);
    }
  }

  function slugify(value, fallback) {
    try {
      var slug = stripDiacritics(value)
        .toLowerCase()
        .replace(/&/g, " und ")
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
  }

  function normalizeId(value, fallback) {
    try {
      var id = slugify(value, fallback || "id");
      return id.replace(/_+/g, "_");
    } catch (error) {
      return fallback || "id";
    }
  }

  function normalizeProfileId(value) {
    try {
      return trim(value).replace(/\s+/g, "").replace(/-/g, "_");
    } catch (error) {
      return "";
    }
  }

  function normalizeObjectKind(value) {
    try {
      return lower(value).replace(/[-\s]+/g, "_").replace(/[^a-z0-9_]/g, "");
    } catch (error) {
      return "";
    }
  }

  function normalizeFieldKey(value) {
    try {
      return trim(value).replace(/\s+/g, "").replace(/[^a-zA-Z0-9_.-]/g, "");
    } catch (error) {
      return "";
    }
  }

  function ensureUniqueId(base, existingIds, options) {
    try {
      var config = options || {};
      var id = normalizeId(base, config.fallback || "variant");
      var existing = {};
      var start = intValue(config.start, 1);
      var separator = config.separator || "_";

      toArray(existingIds).forEach(function (item) {
        var key = normalizeId(item, "");
        if (key) {
          existing[key] = true;
        }
      });

      if (!existing[id]) {
        return id;
      }

      var index = start;
      var candidate = id + separator + String(index);

      while (existing[candidate]) {
        index += 1;
        candidate = id + separator + String(index);
      }

      return candidate;
    } catch (error) {
      return normalizeId(base, "variant");
    }
  }

  function profileSlug(profileId) {
    try {
      var clean = normalizeProfileId(profileId || "variant");
      return slugify(clean.replace(/\./g, "_"), "variant");
    } catch (error) {
      return "variant";
    }
  }

  function buildVariantId(options) {
    try {
      var config = options || {};
      var existingIds = config.existingIds || config.existing_ids || [];
      var explicit = config.explicitId || config.explicit_id || "";
      var label = config.label || config.name || "";
      var profileId = config.variantProfileId || config.variant_profile_id || "";
      var index = intValue(config.index, 1);

      if (explicit) {
        return ensureUniqueId(explicit, existingIds, {
          fallback: "variant",
          start: 1
        });
      }

      if (config.isDefault || config.is_default || label === "Standard" || label === "default") {
        if (toArray(existingIds).indexOf("default") === -1 || config.allowDefault) {
          return "default";
        }
      }

      var base = "";

      if (config.strategy === "label" && label) {
        base = label;
      } else if (profileId) {
        base = profileSlug(profileId);
      } else if (label) {
        base = label;
      } else {
        base = "variant";
      }

      return ensureUniqueId(base + "_" + String(index), existingIds, {
        fallback: "variant",
        start: 1
      });
    } catch (error) {
      return "variant_1";
    }
  }

  function uid(prefix) {
    try {
      var base = prefix || "vp";
      var random = Math.random().toString(36).slice(2, 10);
      var time = Date.now().toString(36);
      return normalizeId(base + "_" + time + "_" + random, "vp_id");
    } catch (error) {
      return "vp_id_" + String(Math.floor(Math.random() * 1000000));
    }
  }

  function escapeHtml(value) {
    try {
      return toString(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    } catch (error) {
      return "";
    }
  }

  function escapeAttr(value) {
    return escapeHtml(value);
  }

  function unescapeHtml(value) {
    try {
      var textarea = document.createElement("textarea");
      textarea.innerHTML = toString(value);
      return textarea.value;
    } catch (error) {
      return toString(value);
    }
  }

  function splitKey(path) {
    try {
      return compactArray(toString(path).split("."));
    } catch (error) {
      return [];
    }
  }

  function getByPath(object, path, fallback) {
    try {
      var parts = splitKey(path);
      var current = object;

      for (var index = 0; index < parts.length; index += 1) {
        if (isNil(current)) {
          return fallback;
        }

        current = current[parts[index]];
      }

      return isNil(current) ? fallback : current;
    } catch (error) {
      return fallback;
    }
  }

  function setByPath(object, path, value) {
    try {
      var parts = splitKey(path);

      if (!parts.length) {
        return object;
      }

      var target = object || {};
      var current = target;

      parts.forEach(function (part, index) {
        if (index === parts.length - 1) {
          current[part] = value;
          return;
        }

        if (!isObject(current[part])) {
          current[part] = {};
        }

        current = current[part];
      });

      return target;
    } catch (error) {
      return object || {};
    }
  }

  function deleteByPath(object, path) {
    try {
      var parts = splitKey(path);

      if (!parts.length || !object) {
        return object;
      }

      var current = object;

      for (var index = 0; index < parts.length - 1; index += 1) {
        current = current[parts[index]];

        if (!isObject(current)) {
          return object;
        }
      }

      delete current[parts[parts.length - 1]];
      return object;
    } catch (error) {
      return object;
    }
  }

  function flattenObject(object, prefix, output) {
    try {
      var result = output || {};
      var base = prefix || "";

      if (!isObject(object)) {
        return result;
      }

      Object.keys(object).forEach(function (key) {
        var value = object[key];
        var nextKey = base ? base + "." + key : key;

        if (isPlainObject(value)) {
          flattenObject(value, nextKey, result);
        } else {
          result[nextKey] = value;
        }
      });

      return result;
    } catch (error) {
      return output || {};
    }
  }

  function unflattenObject(flat) {
    try {
      var output = {};

      if (!isObject(flat)) {
        return output;
      }

      Object.keys(flat).forEach(function (key) {
        setByPath(output, key, flat[key]);
      });

      return output;
    } catch (error) {
      return {};
    }
  }

  function getId(item) {
    try {
      if (!item) {
        return "";
      }

      return item.id || item.key || item.value || item.name || "";
    } catch (error) {
      return "";
    }
  }

  function getLabel(item, fallback) {
    try {
      if (!item) {
        return fallback || "";
      }

      return item.label || item.name || item.title || item.value || item.id || item.key || fallback || "";
    } catch (error) {
      return fallback || "";
    }
  }

  function indexBy(items, keyName) {
    try {
      var output = {};
      var key = keyName || "id";

      toArray(items).forEach(function (item) {
        try {
          if (!item) {
            return;
          }

          var id = item[key] || item.id || item.key || item.value || item.name;

          if (!id) {
            return;
          }

          output[String(id)] = item;
        } catch (itemError) {
          warn("Could not index item.", itemError);
        }
      });

      return output;
    } catch (error) {
      return {};
    }
  }

  function findById(items, id) {
    try {
      var needle = toString(id);

      if (!needle) {
        return null;
      }

      return toArray(items).filter(function (item) {
        return toString(getId(item)) === needle;
      })[0] || null;
    } catch (error) {
      return null;
    }
  }

  function findByKey(items, key) {
    try {
      var needle = toString(key);

      if (!needle) {
        return null;
      }

      return toArray(items).filter(function (item) {
        return toString(item && item.key) === needle;
      })[0] || null;
    } catch (error) {
      return null;
    }
  }

  function normalizeDefinitions(raw) {
    try {
      var source = raw || {};
      var defs = source;

      if (source.data && isObject(source.data)) {
        defs = source.data;
      }

      if (defs.definitions && isObject(defs.definitions)) {
        defs = defs.definitions;
      }

      if (defs.definition_catalogs && isObject(defs.definition_catalogs)) {
        defs = defs.definition_catalogs;
      }

      if (defs.catalogs && isObject(defs.catalogs)) {
        defs = safeMerge(defs, defs.catalogs);
      }

      return {
        object_kinds: toArrayOrObjectValues(defs.object_kinds || defs.objectKinds),
        family_profiles: toArrayOrObjectValues(defs.family_profiles || defs.familyProfiles),
        variant_profiles: toArrayOrObjectValues(defs.variant_profiles || defs.variantProfiles),
        variables: toArrayOrObjectValues(defs.variables),
        units: toArrayOrObjectValues(defs.units),
        materials: toArrayOrObjectValues(defs.materials || defs.material_classes || defs.materialClasses),
        document_types: toArrayOrObjectValues(defs.document_types || defs.documentTypes),
        profile_bindings: toArrayOrObjectValues(defs.profile_bindings || defs.profileBindings)
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
  }

  function buildDefinitionMaps(definitions) {
    try {
      var defs = normalizeDefinitions(definitions);

      return {
        objectKindsById: indexBy(defs.object_kinds, "id"),
        familyProfilesById: indexBy(defs.family_profiles, "id"),
        variantProfilesById: indexBy(defs.variant_profiles, "id"),
        variablesByKey: indexBy(defs.variables, "key"),
        unitsById: indexBy(defs.units, "id"),
        materialsById: indexBy(defs.materials, "id"),
        documentTypesById: indexBy(defs.document_types, "id"),
        profileBindingsById: indexBy(defs.profile_bindings, "id")
      };
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

  function getVariable(definitions, key) {
    try {
      var defs = normalizeDefinitions(definitions);
      var maps = buildDefinitionMaps(defs);
      return maps.variablesByKey[key] || findByKey(defs.variables, key);
    } catch (error) {
      return null;
    }
  }

  function getUnit(definitions, unitId) {
    try {
      var maps = buildDefinitionMaps(definitions);
      return maps.unitsById[unitId] || null;
    } catch (error) {
      return null;
    }
  }

  function getVariantProfile(definitions, profileId) {
    try {
      var id = normalizeProfileId(profileId);
      var maps = buildDefinitionMaps(definitions);
      return maps.variantProfilesById[id] || null;
    } catch (error) {
      return null;
    }
  }

  function getFamilyProfile(definitions, profileId) {
    try {
      var id = normalizeProfileId(profileId);
      var maps = buildDefinitionMaps(definitions);
      return maps.familyProfilesById[id] || null;
    } catch (error) {
      return null;
    }
  }

  function getProfileFieldKeys(profile) {
    try {
      var keys = [];
      var seen = {};

      function add(key) {
        key = normalizeFieldKey(key);

        if (key && !seen[key]) {
          seen[key] = true;
          keys.push(key);
        }
      }

      toArray(profile && profile.sections).forEach(function (section) {
        toArray(section && section.fields).forEach(function (field) {
          if (isString(field)) {
            add(field);
          } else if (isObject(field)) {
            add(field.key || field.field_key || field.fieldKey || field.variable_key || field.variableKey || field.id || "");
          }
        });
      });

      toArray(profile && profile.all_fields).forEach(add);
      toArray(profile && profile.allFields).forEach(add);
      toArray(profile && profile.required_fields).forEach(add);
      toArray(profile && profile.requiredFields).forEach(add);
      toArray(profile && profile.optional_fields).forEach(add);
      toArray(profile && profile.optionalFields).forEach(add);

      return keys;
    } catch (error) {
      return [];
    }
  }

  function getSectionFieldKeys(profile) {
    try {
      var keys = [];
      var seen = {};

      function add(key) {
        key = normalizeFieldKey(key);

        if (key && !seen[key]) {
          seen[key] = true;
          keys.push(key);
        }
      }

      toArray(profile && profile.sections).forEach(function (section) {
        toArray(section && section.fields).forEach(function (field) {
          if (isString(field)) {
            add(field);
          } else if (isObject(field)) {
            add(field.key || field.field_key || field.fieldKey || field.variable_key || field.variableKey || field.id || "");
          }
        });
      });

      return keys;
    } catch (error) {
      return [];
    }
  }

  function getAdditionalFieldKeys(profile) {
    try {
      var sectionKeys = {};
      var output = [];

      getSectionFieldKeys(profile).forEach(function (key) {
        sectionKeys[key] = true;
      });

      getProfileFieldKeys(profile).forEach(function (key) {
        if (!sectionKeys[key]) {
          output.push(key);
        }
      });

      return output;
    } catch (error) {
      return [];
    }
  }

  function isFieldRequired(profile, fieldKey) {
    try {
      return toArray(profile && profile.required_fields).indexOf(fieldKey) !== -1 ||
        toArray(profile && profile.requiredFields).indexOf(fieldKey) !== -1;
    } catch (error) {
      return false;
    }
  }

  function isSystemManagedVariable(variable) {
    try {
      if (!variable) {
        return false;
      }

      var key = variable.key || variable.id || "";

      if (SYSTEM_VARIANT_KEYS[key]) {
        return true;
      }

      if (variable.system_managed === true || variable.systemManaged === true || variable.editable === false) {
        return true;
      }

      var metadata = variable.metadata || {};
      var ui = variable.ui || {};

      return bool(metadata.system_managed, false) ||
        bool(metadata.systemManaged, false) ||
        bool(metadata.hide_in_create_drawer, false) ||
        bool(metadata.hideInCreateDrawer, false) ||
        ui.hidden === true ||
        ui.visible === false;
    } catch (error) {
      return false;
    }
  }

  function shouldHideVariableInDrawer(variable) {
    try {
      if (!variable) {
        return false;
      }

      var key = variable.key || variable.id || "";

      if (SYSTEM_VARIANT_KEYS[key]) {
        return true;
      }

      if (variable.system_managed === true || variable.systemManaged === true || variable.editable === false) {
        return true;
      }

      var metadata = variable.metadata || {};
      var ui = variable.ui || {};

      return bool(metadata.hide_in_create_drawer, false) ||
        bool(metadata.hideInCreateDrawer, false) ||
        ui.hidden === true ||
        ui.visible === false ||
        ui.expose_in_optional_picker === false ||
        ui.exposeInOptionalPicker === false;
    } catch (error) {
      return false;
    }
  }

  function optionLabel(option) {
    return getLabel(option, "");
  }

  function optionValue(option) {
    try {
      if (!isObject(option)) {
        return toString(option);
      }

      return toString(option.value || option.id || option.key || option.label);
    } catch (error) {
      return "";
    }
  }

  function filterCompatibleMaterials(materials, familyProfileId, variantProfileId) {
    try {
      var familyId = normalizeProfileId(familyProfileId);
      var variantId = normalizeProfileId(variantProfileId);

      return toArray(materials).filter(function (material) {
        try {
          if (!material || material.active === false) {
            return false;
          }

          var compatibleFamilies = toArray(material.compatible_family_profiles || material.compatibleFamilyProfiles);
          var compatibleVariants = toArray(material.compatible_variant_profiles || material.compatibleVariantProfiles);

          if (!familyId && !variantId) {
            return true;
          }

          if (familyId && compatibleFamilies.indexOf(familyId) !== -1) {
            return true;
          }

          if (variantId && compatibleVariants.indexOf(variantId) !== -1) {
            return true;
          }

          if (!compatibleFamilies.length && !compatibleVariants.length) {
            return true;
          }

          return false;
        } catch (itemError) {
          return false;
        }
      });
    } catch (error) {
      return [];
    }
  }

  function valueType(variable) {
    try {
      return lower(variable && (variable.value_type || variable.valueType || variable.type) ? variable.value_type || variable.valueType || variable.type : "string");
    } catch (error) {
      return "string";
    }
  }

  function defaultValueForVariable(variable) {
    try {
      if (!variable) {
        return null;
      }

      if (hasOwn(variable, "default_value")) {
        return deepClone(variable.default_value);
      }

      if (hasOwn(variable, "defaultValue")) {
        return deepClone(variable.defaultValue);
      }

      var type = valueType(variable);

      if (type === "boolean") {
        return false;
      }

      if (type === "number" || type === "integer" || type === "money") {
        return null;
      }

      if (DOCUMENT_VALUE_TYPES[type] || type === "array" || type === "multi_enum" || type === "multi-enum") {
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

  function normalizeValueForVariable(value, variable) {
    try {
      var type = valueType(variable);

      if (!type) {
        return value;
      }

      if (type === "boolean") {
        return bool(value, false);
      }

      if (type === "integer") {
        if (value === "" || isNil(value)) {
          return null;
        }

        return intValue(value, 0);
      }

      if (type === "number" || type === "money") {
        if (value === "" || isNil(value)) {
          return null;
        }

        return floatValue(value, null);
      }

      if (DOCUMENT_VALUE_TYPES[type] || type === "array" || type === "multi_enum" || type === "multi-enum") {
        if (isArray(value)) {
          return value;
        }

        var parsedArray = safeJsonParse(value, null);

        if (isArray(parsedArray)) {
          return parsedArray;
        }

        return [];
      }

      if (type === "object") {
        if (isObject(value)) {
          return value;
        }

        return safeJsonParse(value, {});
      }

      if (type === "enum") {
        return toString(value);
      }

      return isNil(value) ? "" : value;
    } catch (error) {
      return value;
    }
  }

  function buildEmptyValues(profile, definitions) {
    try {
      var defs = normalizeDefinitions(definitions);
      var maps = buildDefinitionMaps(defs);
      var values = {};

      getProfileFieldKeys(profile).forEach(function (fieldKey) {
        var variable = maps.variablesByKey[fieldKey] || null;
        values[fieldKey] = defaultValueForVariable(variable);
      });

      if (profile && isObject(profile.default_values)) {
        Object.keys(profile.default_values).forEach(function (key) {
          values[key] = deepClone(profile.default_values[key]);
        });
      }

      if (profile && isObject(profile.defaultValues)) {
        Object.keys(profile.defaultValues).forEach(function (key) {
          values[key] = deepClone(profile.defaultValues[key]);
        });
      }

      return values;
    } catch (error) {
      return {};
    }
  }

  function mergeValues(defaults, current) {
    try {
      return safeMerge(defaults || {}, current || {});
    } catch (error) {
      return current || defaults || {};
    }
  }

  function valuesFromJson(value) {
    try {
      var parsed = safeJsonParse(value, {});

      if (isObject(parsed)) {
        return parsed;
      }

      return {};
    } catch (error) {
      return {};
    }
  }

  function valuesToJson(values) {
    return safeJsonStringify(values || {}, "{}", 0);
  }

  function getVariantLabelFromValues(values, fallback) {
    try {
      return values && values["variant.label"] ? String(values["variant.label"]) : (fallback || "Neue Variante");
    } catch (error) {
      return fallback || "Neue Variante";
    }
  }

  function getVariantDescriptionFromValues(values, fallback) {
    try {
      return values && values["variant.description"] ? String(values["variant.description"]) : (fallback || "");
    } catch (error) {
      return fallback || "";
    }
  }

  function normalizeAdditionalFieldKeys(value) {
    try {
      var raw = value;

      if (isString(raw)) {
        var parsed = safeJsonParse(raw, null);

        if (isArray(parsed)) {
          raw = parsed;
        } else {
          raw = raw.split(",");
        }
      }

      return uniqueArray(toArray(raw).map(function (item) {
        return trim(item);
      }).filter(Boolean));
    } catch (error) {
      return [];
    }
  }

  function normalizeVariant(raw, options) {
    try {
      var config = options || {};
      var variant = raw || {};
      var values = {};

      if (isString(variant.definition_values_json)) {
        values = valuesFromJson(variant.definition_values_json);
      } else if (isString(variant.definitionValuesJson)) {
        values = valuesFromJson(variant.definitionValuesJson);
      } else if (isString(variant.values_json)) {
        values = valuesFromJson(variant.values_json);
      } else if (isString(variant.valuesJson)) {
        values = valuesFromJson(variant.valuesJson);
      } else if (isObject(variant.definition_values)) {
        values = deepClone(variant.definition_values, {});
      } else if (isObject(variant.definitionValues)) {
        values = deepClone(variant.definitionValues, {});
      } else if (isObject(variant.values)) {
        values = deepClone(variant.values, {});
      }

      var id = variant.variant_id || variant.variantId || variant.slug || variant.id || variant.key || values["variant.variant_id"] || "";
      var label = variant.label || variant.name || values["variant.label"] || "";
      var description = variant.description || values["variant.description"] || "";
      var profileId = variant.variant_profile_id || variant.variantProfileId || variant.profile_id || config.variantProfileId || config.variant_profile_id || "";
      var familyProfileId = variant.family_profile_id || variant.familyProfileId || config.familyProfileId || config.family_profile_id || "";
      var isDefault = bool(variant.is_default || variant.isDefault || variant.default, false) || id === "default";

      var additionalFieldKeys = normalizeAdditionalFieldKeys(
        variant.additional_field_keys ||
        variant.additionalFieldKeys ||
        variant.additional_fields ||
        variant.additionalFields ||
        []
      );

      if (!label) {
        label = isDefault ? "Standard" : "Neue Variante";
      }

      if (!id) {
        id = buildVariantId({
          label: label,
          variantProfileId: profileId,
          existingIds: config.existingIds || [],
          index: config.index || 1,
          isDefault: isDefault
        });
      }

      values["variant.variant_id"] = id;
      values["variant.label"] = label;

      if (description) {
        values["variant.description"] = description;
      }

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
        variant_profile_id: profileId,
        variantProfileId: profileId,
        family_profile_id: familyProfileId,
        familyProfileId: familyProfileId,
        definition_managed: bool(variant.definition_managed || variant.definitionManaged, !!profileId || !!Object.keys(values).length),
        definitionManaged: bool(variant.definition_managed || variant.definitionManaged, !!profileId || !!Object.keys(values).length),
        definition_values: values,
        definitionValues: values,
        definition_values_json: valuesToJson(values),
        definitionValuesJson: valuesToJson(values),
        additional_field_keys: additionalFieldKeys,
        additionalFieldKeys: additionalFieldKeys.slice(),
        definition_summary: variant.definition_summary || variant.definitionSummary || variant.summary || "",
        definitionSummary: variant.definition_summary || variant.definitionSummary || variant.summary || "",
        validation: variant.validation || null,
        raw: variant
      };
    } catch (error) {
      warn("Could not normalize variant.", error);

      return {
        variant_id: "variant_1",
        variantId: "variant_1",
        label: "Neue Variante",
        name: "Neue Variante",
        slug: "variant_1",
        kind: "profile",
        description: "",
        is_default: false,
        isDefault: false,
        variant_profile_id: "",
        variantProfileId: "",
        family_profile_id: "",
        familyProfileId: "",
        definition_managed: false,
        definitionManaged: false,
        definition_values: {},
        definitionValues: {},
        definition_values_json: "{}",
        definitionValuesJson: "{}",
        additional_field_keys: [],
        additionalFieldKeys: [],
        definition_summary: "",
        definitionSummary: "",
        raw: raw || {}
      };
    }
  }

  function normalizeVariants(rawVariants, options) {
    try {
      var config = options || {};
      var existingIds = [];
      var output = [];

      toArray(rawVariants).forEach(function (raw, index) {
        var variant = normalizeVariant(raw, safeMerge(config, {
          index: index + 1,
          existingIds: existingIds
        }));

        variant.is_default = index === 0 || variant.variant_id === "default" || variant.is_default;
        variant.isDefault = variant.is_default;

        if (index === 0) {
          variant.variant_id = "default";
          variant.variantId = "default";
          variant.slug = "default";
          variant.definition_values["variant.variant_id"] = "default";
          variant.definitionValues = variant.definition_values;

          if (!variant.label || variant.label === "Neue Variante") {
            variant.label = "Standard";
            variant.name = "Standard";
            variant.definition_values["variant.label"] = "Standard";
          }

          variant.definition_values_json = valuesToJson(variant.definition_values);
          variant.definitionValuesJson = variant.definition_values_json;
        } else if (variant.variant_id === "default") {
          variant.variant_id = ensureUniqueId("variant_" + (index + 1), existingIds, {
            fallback: "variant",
            start: 1
          });
          variant.variantId = variant.variant_id;
          variant.slug = variant.variant_id;
          variant.definition_values["variant.variant_id"] = variant.variant_id;
          variant.definitionValues = variant.definition_values;
          variant.definition_values_json = valuesToJson(variant.definition_values);
          variant.definitionValuesJson = variant.definition_values_json;
          variant.is_default = false;
          variant.isDefault = false;
        }

        existingIds.push(variant.variant_id);
        output.push(variant);
      });

      if (!output.length) {
        output.push(normalizeVariant({
          variant_id: "default",
          label: "Standard",
          name: "Standard",
          slug: "default",
          kind: "standard",
          is_default: true
        }, config));
      }

      return output;
    } catch (error) {
      return [normalizeVariant({
        variant_id: "default",
        label: "Standard",
        is_default: true
      }, options || {})];
    }
  }

  function formatUnit(unit) {
    try {
      if (!unit) {
        return "";
      }

      if (isString(unit)) {
        return unit;
      }

      return unit.symbol || unit.label || unit.id || "";
    } catch (error) {
      return "";
    }
  }

  function formatValue(value, variable, definitions) {
    try {
      if (isNil(value) || value === "") {
        return "";
      }

      var type = valueType(variable);

      if (type === "boolean") {
        return bool(value, false) ? "Ja" : "Nein";
      }

      if (type === "money" || type === "number" || type === "integer") {
        var unit = variable && (variable.unit || variable.unit_id || variable.unitId) ? getUnit(definitions, variable.unit || variable.unit_id || variable.unitId) : null;
        var symbol = formatUnit(unit || (variable && (variable.unit || variable.unit_id || variable.unitId)));
        return String(value) + (symbol ? " " + symbol : "");
      }

      if (type === "enum" && variable && variable.options) {
        var matched = toArray(variable.options).filter(function (option) {
          return optionValue(option) === String(value);
        })[0];

        if (matched) {
          return optionLabel(matched);
        }
      }

      if (DOCUMENT_VALUE_TYPES[type]) {
        var list = isArray(value) ? value : safeJsonParse(value, []);
        return list.length === 1 ? "1 Dokument" : String(list.length) + " Dokumente";
      }

      if (type === "object") {
        return safeJsonStringify(value, "{}", 0);
      }

      return String(value);
    } catch (error) {
      return toString(value);
    }
  }

  function buildSummary(values, profile, definitions) {
    try {
      var defs = normalizeDefinitions(definitions);
      var maps = buildDefinitionMaps(defs);
      var fields = toArray(profile && profile.summary_fields || profile && profile.summaryFields);
      var parts = [];

      fields.forEach(function (fieldKey) {
        try {
          var value = values[fieldKey];

          if (isNil(value) || value === "") {
            return;
          }

          var variable = maps.variablesByKey[fieldKey] || null;
          var label = variable ? variable.label : fieldKey;
          var formatted = formatValue(value, variable, defs);

          if (!formatted) {
            return;
          }

          if (fieldKey === "variant.label") {
            return;
          }

          parts.push(label + ": " + formatted);
        } catch (fieldError) {
          warn("Could not build summary part.", fieldError);
        }
      });

      return parts.join(" · ");
    } catch (error) {
      return "";
    }
  }

  function resolveCreateContext() {
    try {
      return window.VectoplanCreateContext || {};
    } catch (error) {
      return {};
    }
  }

  function resolveGeneratorContext() {
    try {
      var context = resolveCreateContext();
      return window.VectoplanGeneratorContext ||
        context.generatorContext ||
        context.generator_context ||
        {};
    } catch (error) {
      return {};
    }
  }

  function resolvePayloadContract() {
    try {
      var context = resolveCreateContext();
      return window.VectoplanCreatePayloadContract ||
        context.payloadContract ||
        context.payload_contract ||
        {};
    } catch (error) {
      return {};
    }
  }

  function nowIso() {
    try {
      return new Date().toISOString();
    } catch (error) {
      return "";
    }
  }

  function markReady() {
    try {
      document.documentElement.setAttribute(READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-variant-utils-version", COMPONENT_VERSION);
    } catch (error) {
      /* no-op */
    }
  }

  function setDebugNativeEvents(enabled) {
    EVENT_GUARD.debugNativeEvents = !!enabled;
    return EVENT_GUARD.debugNativeEvents;
  }

  function setDebugCustomEvents(enabled) {
    EVENT_GUARD.debugCustomEvents = !!enabled;
    return EVENT_GUARD.debugCustomEvents;
  }

  function getRuntimeSnapshot() {
    try {
      return {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        ready: true,
        timestamp: nowIso(),
        eventGuard: {
          customStack: EVENT_GUARD.customStack.slice(),
          customDepthByName: shallowClone(EVENT_GUARD.customDepthByName),
          suppressedCustomCount: EVENT_GUARD.suppressedCustomCount,
          suppressedNativeCount: EVENT_GUARD.suppressedNativeCount,
          dispatchedCustomCount: EVENT_GUARD.dispatchedCustomCount,
          dispatchedNativeCount: EVENT_GUARD.dispatchedNativeCount,
          nativeCooldownMs: EVENT_GUARD.nativeCooldownMs,
          debugNativeEvents: EVENT_GUARD.debugNativeEvents,
          debugCustomEvents: EVENT_GUARD.debugCustomEvents
        },
        globals: {
          hasCreateContext: !!window.VectoplanCreateContext,
          hasGeneratorContext: !!window.VectoplanGeneratorContext,
          hasCreateDefinitions: !!window.VectoplanCreateDefinitions,
          hasDefinitionsRuntime: !!window.VectoplanCreateDefinitionsRuntime,
          hasVariantWorkspace: !!window.VectoplanCreateVariantWorkspace,
          hasVariantTable: !!window.VectoplanCreateVariantTable,
          hasVariantDrawerShell: !!window.VectoplanCreateVariantDrawerShell,
          hasUploadsRuntime: !!window.VectoplanCreateUploads,
          hasPayloadRuntime: !!window.VectoplanCreatePayload
        }
      };
    } catch (error) {
      return {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        ready: true
      };
    }
  }

  var api = {
    __name: COMPONENT_NAME,
    __version: COMPONENT_VERSION,
    version: COMPONENT_VERSION,

    log: log,
    warn: warn,
    info: info,
    debug: debug,
    error: error,

    isNil: isNil,
    isString: isString,
    isNumber: isNumber,
    isBoolean: isBoolean,
    isFunction: isFunction,
    isArray: isArray,
    isObject: isObject,
    isPlainObject: isPlainObject,
    isElement: isElement,
    hasOwn: hasOwn,

    toString: toString,
    trim: trim,
    lower: lower,
    upper: upper,
    bool: bool,
    intValue: intValue,
    floatValue: floatValue,
    clamp: clamp,
    toArray: toArray,
    objectValues: objectValues,
    toArrayOrObjectValues: toArrayOrObjectValues,
    uniqueArray: uniqueArray,
    compactArray: compactArray,

    safeJsonParse: safeJsonParse,
    safeJsonStringify: safeJsonStringify,
    deepClone: deepClone,
    shallowClone: shallowClone,
    safeMerge: safeMerge,
    deepMerge: deepMerge,

    qs: qs,
    qsa: qsa,
    closest: closest,
    contains: contains,
    attr: attr,
    setAttr: setAttr,
    boolAttr: boolAttr,
    dataset: dataset,
    setDataset: setDataset,
    setText: setText,
    setHtml: setHtml,
    getValue: getValue,
    setValue: setValue,
    setHidden: setHidden,
    setDisabled: setDisabled,
    addClass: addClass,
    removeClass: removeClass,
    toggleClass: toggleClass,
    empty: empty,
    createElement: createElement,
    htmlToElement: htmlToElement,
    templateHtml: templateHtml,
    renderTemplate: renderTemplate,
    cache: cache,

    dispatch: dispatch,
    dispatchDocument: dispatchDocument,
    dispatchNative: dispatchNative,
    markProgrammaticEvent: markProgrammaticEvent,
    isProgrammaticEventTarget: isProgrammaticEventTarget,
    on: on,
    once: once,
    delegate: delegate,
    debounce: debounce,
    throttle: throttle,

    transliterate: transliterate,
    stripDiacritics: stripDiacritics,
    slugify: slugify,
    normalizeId: normalizeId,
    normalizeProfileId: normalizeProfileId,
    normalizeObjectKind: normalizeObjectKind,
    normalizeFieldKey: normalizeFieldKey,
    ensureUniqueId: ensureUniqueId,
    profileSlug: profileSlug,
    buildVariantId: buildVariantId,
    uid: uid,

    escapeHtml: escapeHtml,
    escapeAttr: escapeAttr,
    unescapeHtml: unescapeHtml,

    splitKey: splitKey,
    getByPath: getByPath,
    setByPath: setByPath,
    deleteByPath: deleteByPath,
    flattenObject: flattenObject,
    unflattenObject: unflattenObject,

    getId: getId,
    getLabel: getLabel,
    indexBy: indexBy,
    findById: findById,
    findByKey: findByKey,
    normalizeDefinitions: normalizeDefinitions,
    buildDefinitionMaps: buildDefinitionMaps,
    getVariable: getVariable,
    getUnit: getUnit,
    getVariantProfile: getVariantProfile,
    getFamilyProfile: getFamilyProfile,
    getProfileFieldKeys: getProfileFieldKeys,
    getSectionFieldKeys: getSectionFieldKeys,
    getAdditionalFieldKeys: getAdditionalFieldKeys,
    isFieldRequired: isFieldRequired,
    isSystemManagedVariable: isSystemManagedVariable,
    shouldHideVariableInDrawer: shouldHideVariableInDrawer,
    optionLabel: optionLabel,
    optionValue: optionValue,
    filterCompatibleMaterials: filterCompatibleMaterials,

    defaultValueForVariable: defaultValueForVariable,
    normalizeValueForVariable: normalizeValueForVariable,
    buildEmptyValues: buildEmptyValues,
    mergeValues: mergeValues,
    valuesFromJson: valuesFromJson,
    valuesToJson: valuesToJson,
    getVariantLabelFromValues: getVariantLabelFromValues,
    getVariantDescriptionFromValues: getVariantDescriptionFromValues,
    normalizeAdditionalFieldKeys: normalizeAdditionalFieldKeys,

    normalizeVariant: normalizeVariant,
    normalizeVariants: normalizeVariants,

    formatUnit: formatUnit,
    formatValue: formatValue,
    buildSummary: buildSummary,

    resolveCreateContext: resolveCreateContext,
    resolveGeneratorContext: resolveGeneratorContext,
    resolvePayloadContract: resolvePayloadContract,

    nowIso: nowIso,
    setDebugNativeEvents: setDebugNativeEvents,
    setDebugCustomEvents: setDebugCustomEvents,
    getRuntimeSnapshot: getRuntimeSnapshot
  };

  try {
    window[GLOBAL_NAME] = api;
    markReady();

    dispatchDocument("vectoplan:create:variant-utils-ready", {
      component: COMPONENT_NAME,
      version: COMPONENT_VERSION,
      api: GLOBAL_NAME,
      snapshot: getRuntimeSnapshot()
    }, {
      silent: true
    });
  } catch (bootstrapError) {
    warn("Could not expose variant utils.", bootstrapError);
  }
})();