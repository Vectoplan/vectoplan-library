/* services/vectoplan-library/static/js/vplib/create/create_theme.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateTheme";
  var MODULE_NAME = "theme";
  var THEME_VERSION = "0.7.0";
  var CORE_NAME = "VectoplanCreateCore";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 80;

  var THEMES = {
    light: "light",
    dark: "dark",
    system: "system"
  };

  var THEME_LABELS = {
    light: "Hell",
    dark: "Dunkel",
    system: "System"
  };

  var THEME_TITLES = {
    light: "Darstellung: Hell",
    dark: "Darstellung: Dunkel",
    system: "Darstellung: System"
  };

  var THEME_NEXT = {
    system: "dark",
    dark: "light",
    light: "system"
  };

  var THEME_META_COLORS = {
    light: "#f8fafc",
    dark: "#020617"
  };

  var DEFAULT_SELECTORS = {
    themeToggle: "[data-create-theme-toggle='true'], [data-vp-theme-toggle]",
    themeLabel: "[data-create-theme-label='true'], [data-vp-theme-label]",
    themeValue: "[data-vp-theme-value]",
    themeEffectiveValue: "[data-vp-theme-effective-value]",
    themeIcon: "[data-vp-theme-icon]",
    themeOption: "[data-vp-theme-option]",
    themeSelect: "[data-vp-theme-select], [data-create-theme-select='true']",
    themeScope: "[data-vp-create-app], [data-create-page='true'], [data-vp-create-page='true'], [data-vp-create-form], [data-create-form='true']"
  };

  var core = null;
  var selectors = null;
  var initialized = false;
  var bindingDone = false;
  var mediaQuery = null;
  var mediaQueryHandler = null;

  var localState = {
    version: THEME_VERSION,
    initialized: false,
    bindingDone: false,
    theme: "dark",
    effectiveTheme: "dark",
    storageKey: "vectoplan.create.theme",
    source: "initial",
    changeCount: 0,
    applyCount: 0,
    suppressedEventCount: 0,
    systemChangeCount: 0,
    lastChange: null,
    lastApply: null,
    lastError: null,
    mediaQuerySupported: false,
    degradedCore: false
  };

  function boot(attempt) {
    try {
      var safeAttempt = typeof attempt === "number" ? attempt : 0;
      var maybeCore = window[CORE_NAME];

      if (!maybeCore || !maybeCore.selectors || !maybeCore.state) {
        if (safeAttempt < BOOT_MAX_ATTEMPTS) {
          window.setTimeout(function () {
            boot(safeAttempt + 1);
          }, BOOT_RETRY_MS);
          return;
        }

        fallbackWarn("Core runtime missing; initializing theme with defensive fallback core.");
        maybeCore = buildFallbackCore();
        localState.degradedCore = true;
      }

      initialize(maybeCore);
    } catch (error) {
      fallbackWarn("Theme boot failed.", error);
    }
  }

  function initialize(coreRuntime) {
    try {
      if (initialized) {
        return api;
      }

      core = coreRuntime || window[CORE_NAME] || buildFallbackCore();

      if (!core) {
        fallbackWarn("Cannot initialize theme runtime.");
        return api;
      }

      selectors = Object.assign({}, DEFAULT_SELECTORS, core.selectors || {});
      localState.storageKey = resolveStorageKey();

      bindControls();
      bindSystemThemeListener();

      setTheme(resolveInitialTheme(), {
        persist: false,
        source: "initialize",
        forceApply: true,
        forceEvent: false
      });

      initialized = true;
      localState.initialized = true;

      if (typeof core.registerModule === "function") {
        core.registerModule(MODULE_NAME, api);
      }

      safeSetAttribute(document.documentElement, "data-theme-ready", "true");
      safeSetAttribute(document.documentElement, "data-vp-create-theme-ready", "true");
      safeSetAttribute(document.documentElement, "data-vp-create-theme-version", THEME_VERSION);

      dispatch("vectoplan:create:theme-ready", getState());

      return api;
    } catch (error) {
      localState.initialized = false;
      localState.lastError = normalizeError(error);
      safeError("Theme initialization failed.", error);
      return api;
    }
  }

  function bindControls() {
    try {
      if (bindingDone) {
        return;
      }

      bindingDone = true;
      localState.bindingDone = true;

      bindOnce("create-theme-click", bindThemeClicks);
      bindOnce("create-theme-select", bindThemeSelects);
      bindOnce("create-theme-core-events", bindCoreEvents);
      bindOnce("create-theme-keyboard", bindThemeKeyboard);
    } catch (error) {
      safeError("Theme control binding failed.", error);
    }
  }

  function bindThemeClicks() {
    try {
      document.addEventListener("click", function (event) {
        try {
          var target = event && event.target ? event.target : null;

          if (!target || !target.closest) {
            return;
          }

          var option = target.closest(selectorFor("themeOption"));

          if (option) {
            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            setTheme(
              option.getAttribute("data-vp-theme-option") ||
              option.getAttribute("data-theme") ||
              option.getAttribute("data-value") ||
              "",
              {
                persist: true,
                source: "theme-option"
              }
            );

            return;
          }

          var toggle = target.closest(selectorFor("themeToggle"));

          if (!toggle) {
            return;
          }

          event.preventDefault();

          if (typeof event.stopPropagation === "function") {
            event.stopPropagation();
          }

          cycleTheme({
            source: "theme-toggle"
          });
        } catch (clickError) {
          safeWarn("Theme click handling failed.", clickError);
        }
      }, true);
    } catch (error) {
      safeError("Theme click binding failed.", error);
    }
  }

  function bindThemeSelects() {
    try {
      document.addEventListener("change", function (event) {
        try {
          var target = event && event.target ? event.target : null;

          if (!target || !target.matches || !target.matches(selectorFor("themeSelect"))) {
            return;
          }

          setTheme(target.value, {
            persist: true,
            source: "theme-select"
          });
        } catch (changeError) {
          safeWarn("Theme select handling failed.", changeError);
        }
      }, true);
    } catch (error) {
      safeError("Theme select binding failed.", error);
    }
  }

  function bindThemeKeyboard() {
    try {
      document.addEventListener("keydown", function (event) {
        try {
          var target = event && event.target ? event.target : null;

          if (!target || !target.closest) {
            return;
          }

          var option = target.closest(selectorFor("themeOption"));

          if (!option || (event.key !== "Enter" && event.key !== " ")) {
            return;
          }

          event.preventDefault();

          setTheme(
            option.getAttribute("data-vp-theme-option") ||
            option.getAttribute("data-theme") ||
            option.getAttribute("data-value") ||
            "",
            {
              persist: true,
              source: "theme-option-keyboard"
            }
          );
        } catch (keyboardError) {
          safeWarn("Theme keyboard handling failed.", keyboardError);
        }
      }, true);
    } catch (error) {
      safeWarn("Theme keyboard binding failed.", error);
    }
  }

  function bindCoreEvents() {
    try {
      document.addEventListener("vectoplan:create:core-context-refreshed", function () {
        try {
          localState.storageKey = resolveStorageKey();

          if (!localState.theme) {
            setTheme(resolveInitialTheme(), {
              persist: false,
              source: "core-context-refreshed",
              forceApply: true
            });
            return;
          }

          applyThemeAttributes(localState.theme, {
            source: "core-context-refreshed",
            forceEvent: false
          });
          updateControls();
        } catch (error) {
          safeWarn("Theme context refresh handling failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:theme-refresh-requested", function () {
        try {
          applyThemeAttributes(localState.theme || resolveInitialTheme(), {
            source: "theme-refresh-requested",
            forceEvent: true
          });
          updateControls();
        } catch (error) {
          safeWarn("Theme refresh request failed.", error);
        }
      });
    } catch (error) {
      safeWarn("Theme core event binding failed.", error);
    }
  }

  function bindSystemThemeListener() {
    try {
      if (!window.matchMedia) {
        localState.mediaQuerySupported = false;
        return false;
      }

      mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
      localState.mediaQuerySupported = true;

      mediaQueryHandler = function () {
        try {
          if (localState.theme !== THEMES.system) {
            return;
          }

          localState.systemChangeCount += 1;

          applyThemeAttributes(THEMES.system, {
            source: "system-media-change",
            forceEvent: true
          });
          updateControls();

          dispatch("vectoplan:create:theme-system-changed", getState());
        } catch (error) {
          safeWarn("System theme change handling failed.", error);
        }
      };

      if (typeof mediaQuery.addEventListener === "function") {
        mediaQuery.addEventListener("change", mediaQueryHandler);
      } else if (typeof mediaQuery.addListener === "function") {
        mediaQuery.addListener(mediaQueryHandler);
      }

      return true;
    } catch (error) {
      safeWarn("System theme listener binding failed.", error);
      localState.mediaQuerySupported = false;
      return false;
    }
  }

  function unbindSystemThemeListener() {
    try {
      if (!mediaQuery || !mediaQueryHandler) {
        return false;
      }

      if (typeof mediaQuery.removeEventListener === "function") {
        mediaQuery.removeEventListener("change", mediaQueryHandler);
      } else if (typeof mediaQuery.removeListener === "function") {
        mediaQuery.removeListener(mediaQueryHandler);
      }

      mediaQueryHandler = null;
      return true;
    } catch (error) {
      safeWarn("System theme listener unbinding failed.", error);
      return false;
    }
  }

  function resolveInitialTheme() {
    try {
      var storageKey = resolveStorageKey();
      var fromStorage = safeLocalStorageGet(storageKey);
      var root = document.documentElement;

      var fromHtml = root.getAttribute("data-theme") ||
        root.getAttribute("data-vp-theme") ||
        root.getAttribute("data-vp-theme-mode") ||
        root.getAttribute("data-vp-create-theme") ||
        "";

      var context = core && core.state ? core.state.context || {} : {};
      var uiState = core && core.state ? core.state.uiState || {} : {};

      var fromContext = getNested(context, ["theme", "default"], "") ||
        getNested(context, ["theme", "mode"], "") ||
        getNested(context, ["theme", "current"], "") ||
        getNested(context, ["theme_default"], "") ||
        getNested(context, ["themeDefault"], "");

      var fromUiState = getNested(uiState, ["theme"], "") ||
        getNested(uiState, ["appearance"], "");

      return normalizeTheme(fromStorage || fromUiState || fromContext || fromHtml || THEMES.dark);
    } catch (error) {
      return THEMES.dark;
    }
  }

  function resolveStorageKey() {
    try {
      var root = document.documentElement;
      var fromDom = root.getAttribute("data-create-theme-storage-key") ||
        root.getAttribute("data-vp-create-theme-storage-key") ||
        "";

      var fromState = core && core.state ? core.state.themeStorageKey : "";
      var fromContext = core && core.state
        ? getNested(core.state.context, ["theme", "storage_key"], "") ||
          getNested(core.state.context, ["theme", "storageKey"], "")
        : "";

      return String(fromDom || fromContext || fromState || "vectoplan.create.theme").trim() || "vectoplan.create.theme";
    } catch (error) {
      return "vectoplan.create.theme";
    }
  }

  function setTheme(theme, options) {
    try {
      ensureCore();

      var normalized = normalizeTheme(theme);
      var safeOptions = options || {};
      var previousTheme = localState.theme;
      var previousEffective = localState.effectiveTheme;
      var effective = resolveEffectiveTheme(normalized);
      var persist = safeOptions.persist === true;
      var changed = previousTheme !== normalized || previousEffective !== effective || safeOptions.forceApply === true;

      localState.theme = normalized;
      localState.effectiveTheme = effective;
      localState.source = safeOptions.source || "api";

      if (changed) {
        localState.changeCount += 1;
      }

      localState.lastChange = {
        theme: normalized,
        effectiveTheme: effective,
        previousTheme: previousTheme || "",
        previousEffectiveTheme: previousEffective || "",
        changed: changed,
        persisted: persist,
        source: localState.source,
        timestamp: timestamp()
      };

      if (core && core.state) {
        core.state.theme = normalized;
      }

      applyThemeAttributes(normalized, safeOptions);

      if (persist) {
        safeLocalStorageSet(resolveStorageKey(), normalized);
      }

      updateControls();

      if (changed || safeOptions.forceEvent === true) {
        dispatch("vectoplan:create:theme-changed", getState());
      } else {
        localState.suppressedEventCount += 1;
      }

      return normalized;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Set theme failed.", error);
      return localState.theme || THEMES.dark;
    }
  }

  function cycleTheme(options) {
    try {
      var current = normalizeTheme(localState.theme || getTheme());
      var next = THEME_NEXT[current] || THEMES.dark;

      return setTheme(next, {
        persist: true,
        source: options && options.source ? options.source : "cycle"
      });
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Theme cycle failed.", error);
      return localState.theme || THEMES.dark;
    }
  }

  function resetTheme(options) {
    try {
      var storageKey = resolveStorageKey();
      safeLocalStorageRemove(storageKey);

      return setTheme(THEMES.dark, {
        persist: false,
        source: options && options.source ? options.source : "reset",
        forceApply: true,
        forceEvent: true
      });
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Reset theme failed.", error);
      return localState.theme || THEMES.dark;
    }
  }

  function applyThemeAttributes(theme, options) {
    try {
      var safeOptions = options || {};
      var normalized = normalizeTheme(theme);
      var effective = resolveEffectiveTheme(normalized);
      var root = document.documentElement;
      var body = document.body;

      localState.effectiveTheme = effective;
      localState.applyCount += 1;
      localState.lastApply = {
        theme: normalized,
        effectiveTheme: effective,
        source: safeOptions.source || "api",
        timestamp: timestamp()
      };

      root.setAttribute("data-theme", normalized);
      root.setAttribute("data-vp-theme", normalized);
      root.setAttribute("data-vp-theme-mode", normalized);
      root.setAttribute("data-vp-theme-effective", effective);
      root.setAttribute("data-vp-effective-theme", effective);
      root.setAttribute("data-vp-color-scheme", effective);
      root.setAttribute("data-vp-create-theme", normalized);
      root.setAttribute("data-vp-create-theme-mode", normalized);
      root.setAttribute("data-vp-create-theme-effective", effective);
      root.setAttribute("data-vp-create-color-scheme", effective);
      root.setAttribute("data-vp-create-style", effective === THEMES.dark ? "black" : "light");

      root.style.colorScheme = effective === THEMES.dark ? "dark" : "light";

      if (body) {
        body.setAttribute("data-theme", normalized);
        body.setAttribute("data-vp-theme", normalized);
        body.setAttribute("data-vp-theme-mode", normalized);
        body.setAttribute("data-vp-theme-effective", effective);
        body.setAttribute("data-vp-color-scheme", effective);
        body.setAttribute("data-vp-create-theme", normalized);
        body.setAttribute("data-vp-create-theme-effective", effective);
      }

      queryAll(selectorFor("themeScope")).forEach(function (node) {
        try {
          node.setAttribute("data-theme", normalized);
          node.setAttribute("data-vp-theme", normalized);
          node.setAttribute("data-vp-theme-effective", effective);
          node.setAttribute("data-vp-create-theme", normalized);
          node.setAttribute("data-vp-create-theme-effective", effective);
        } catch (nodeError) {
          safeWarn("Theme scope update skipped.", nodeError);
        }
      });

      updateThemeMetaColor(effective);

      if (safeOptions.forceEvent === true) {
        dispatch("vectoplan:create:theme-applied", {
          theme: normalized,
          effectiveTheme: effective,
          source: safeOptions.source || "api"
        });
      }

      return true;
    } catch (error) {
      safeWarn("Apply theme attributes failed.", error);
      return false;
    }
  }

  function updateThemeMetaColor(effectiveTheme) {
    try {
      var effective = effectiveTheme === THEMES.light ? THEMES.light : THEMES.dark;
      var color = THEME_META_COLORS[effective] || THEME_META_COLORS.dark;
      var meta = document.querySelector("meta[name='theme-color']");

      if (!meta) {
        meta = document.createElement("meta");
        meta.setAttribute("name", "theme-color");
        document.head.appendChild(meta);
      }

      meta.setAttribute("content", color);
      return true;
    } catch (error) {
      safeWarn("Theme meta color update failed.", error);
      return false;
    }
  }

  function updateControls() {
    try {
      var theme = normalizeTheme(localState.theme || THEMES.dark);
      var effective = resolveEffectiveTheme(theme);
      var label = THEME_LABELS[theme] || THEME_LABELS.dark;
      var title = THEME_TITLES[theme] || THEME_TITLES.dark;

      queryAll(selectorFor("themeToggle")).forEach(function (toggle) {
        try {
          toggle.setAttribute("aria-pressed", theme === THEMES.system ? "false" : "true");
          toggle.setAttribute("data-create-theme-current", theme);
          toggle.setAttribute("data-vp-theme-current", theme);
          toggle.setAttribute("data-vp-theme-effective", effective);
          toggle.setAttribute("title", title);
          toggle.setAttribute("aria-label", title);
        } catch (error) {
          safeWarn("Theme toggle update skipped.", error);
        }
      });

      queryAll(selectorFor("themeLabel")).forEach(function (node) {
        node.textContent = label;
      });

      queryAll(selectorFor("themeValue")).forEach(function (node) {
        node.textContent = theme;
      });

      queryAll(selectorFor("themeEffectiveValue")).forEach(function (node) {
        node.textContent = effective;
      });

      queryAll(selectorFor("themeIcon")).forEach(function (node) {
        try {
          node.setAttribute("data-vp-theme-icon-current", theme);
          node.setAttribute("data-vp-theme-icon-effective", effective);
          node.textContent = iconForTheme(theme, effective);
        } catch (error) {
          safeWarn("Theme icon update skipped.", error);
        }
      });

      queryAll(selectorFor("themeOption")).forEach(function (node) {
        try {
          var optionTheme = normalizeTheme(
            node.getAttribute("data-vp-theme-option") ||
            node.getAttribute("data-theme") ||
            node.getAttribute("data-value") ||
            ""
          );
          var active = optionTheme === theme;

          node.classList.toggle("is-active", active);
          node.setAttribute("aria-selected", active ? "true" : "false");
          node.setAttribute("aria-pressed", active ? "true" : "false");
          node.setAttribute("data-vp-theme-option-active", active ? "true" : "false");
        } catch (error) {
          safeWarn("Theme option update skipped.", error);
        }
      });

      queryAll(selectorFor("themeSelect")).forEach(function (select) {
        try {
          select.value = theme;
        } catch (error) {
          safeWarn("Theme select update skipped.", error);
        }
      });

      return true;
    } catch (error) {
      safeWarn("Theme controls update failed.", error);
      return false;
    }
  }

  function iconForTheme(theme, effectiveTheme) {
    try {
      if (theme === THEMES.system) {
        return "◐";
      }

      if (effectiveTheme === THEMES.dark) {
        return "●";
      }

      return "○";
    } catch (error) {
      return "●";
    }
  }

  function getTheme() {
    try {
      return normalizeTheme(localState.theme || (core && core.state ? core.state.theme : "") || THEMES.dark);
    } catch (error) {
      return THEMES.dark;
    }
  }

  function getEffectiveTheme() {
    try {
      return resolveEffectiveTheme(getTheme());
    } catch (error) {
      return THEMES.dark;
    }
  }

  function resolveEffectiveTheme(theme) {
    try {
      var normalized = normalizeTheme(theme);

      if (normalized === THEMES.dark || normalized === THEMES.light) {
        return normalized;
      }

      if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
        return THEMES.dark;
      }

      if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
        return THEMES.light;
      }

      return THEMES.dark;
    } catch (error) {
      return THEMES.dark;
    }
  }

  function normalizeTheme(value) {
    try {
      if (core && typeof core.normalizeTheme === "function") {
        var coreTheme = core.normalizeTheme(value);

        if (coreTheme === "black") {
          return THEMES.dark;
        }

        if (coreTheme === THEMES.dark || coreTheme === THEMES.light || coreTheme === THEMES.system) {
          return coreTheme;
        }
      }

      var text = String(value || "").trim().toLowerCase();

      if (text === "black" || text === "night" || text === "dunkel") {
        return THEMES.dark;
      }

      if (text === "hell") {
        return THEMES.light;
      }

      if (text === THEMES.dark || text === THEMES.light || text === THEMES.system) {
        return text;
      }

      return THEMES.dark;
    } catch (error) {
      return THEMES.dark;
    }
  }

  function queryAll(selector) {
    try {
      if (!selector) {
        return [];
      }

      if (core && typeof core.qsa === "function") {
        return core.qsa(selector);
      }

      return Array.prototype.slice.call(document.querySelectorAll(selector));
    } catch (error) {
      return [];
    }
  }

  function selectorFor(key) {
    try {
      if (!selectors) {
        selectors = Object.assign({}, DEFAULT_SELECTORS, core && core.selectors ? core.selectors : {});
      }

      return selectors[key] || DEFAULT_SELECTORS[key] || "";
    } catch (error) {
      return DEFAULT_SELECTORS[key] || "";
    }
  }

  function getState() {
    try {
      return {
        version: THEME_VERSION,
        initialized: initialized,
        bindingDone: bindingDone,
        theme: getTheme(),
        effectiveTheme: getEffectiveTheme(),
        storageKey: resolveStorageKey(),
        source: localState.source,
        changeCount: localState.changeCount,
        applyCount: localState.applyCount,
        suppressedEventCount: localState.suppressedEventCount,
        systemChangeCount: localState.systemChangeCount,
        lastChange: localState.lastChange,
        lastApply: localState.lastApply,
        lastError: localState.lastError,
        mediaQuerySupported: !!window.matchMedia,
        degradedCore: localState.degradedCore
      };
    } catch (error) {
      return {
        version: THEME_VERSION,
        initialized: initialized,
        state_error: String(error && error.message ? error.message : error)
      };
    }
  }

  function normalizeError(error) {
    try {
      return {
        message: String(error && error.message ? error.message : error),
        stack: error && error.stack ? String(error.stack) : "",
        timestamp: timestamp()
      };
    } catch (normalizationError) {
      return {
        message: "Unknown error",
        timestamp: timestamp()
      };
    }
  }

  function timestamp() {
    try {
      return new Date().toISOString();
    } catch (error) {
      return "";
    }
  }

  function ensureCore() {
    try {
      if (!core) {
        core = window[CORE_NAME] || buildFallbackCore();
      }

      if (!core) {
        throw new Error("VectoplanCreateCore is not available.");
      }

      if (!selectors) {
        selectors = Object.assign({}, DEFAULT_SELECTORS, core.selectors || {});
      }

      return core;
    } catch (error) {
      throw error;
    }
  }

  function getNested(object, path, fallback) {
    try {
      if (core && typeof core.getNested === "function") {
        return core.getNested(object, path, fallback);
      }

      var cursor = object;

      for (var index = 0; index < path.length; index += 1) {
        if (!cursor || typeof cursor !== "object" || !(path[index] in cursor)) {
          return fallback;
        }

        cursor = cursor[path[index]];
      }

      return cursor === undefined || cursor === null ? fallback : cursor;
    } catch (error) {
      return fallback;
    }
  }

  function safeLocalStorageGet(key) {
    try {
      if (core && typeof core.safeLocalStorageGet === "function") {
        return core.safeLocalStorageGet(key);
      }

      return window.localStorage.getItem(key);
    } catch (error) {
      return "";
    }
  }

  function safeLocalStorageSet(key, value) {
    try {
      if (core && typeof core.safeLocalStorageSet === "function") {
        return core.safeLocalStorageSet(key, value);
      }

      window.localStorage.setItem(key, value);
      return true;
    } catch (error) {
      return false;
    }
  }

  function safeLocalStorageRemove(key) {
    try {
      if (core && typeof core.safeLocalStorageRemove === "function") {
        return core.safeLocalStorageRemove(key);
      }

      window.localStorage.removeItem(key);
      return true;
    } catch (error) {
      return false;
    }
  }

  function safeSetAttribute(node, name, value) {
    try {
      if (!node || !name) {
        return false;
      }

      if (core && typeof core.safeSetAttribute === "function") {
        core.safeSetAttribute(node, name, value);
        return true;
      }

      node.setAttribute(name, value === undefined || value === null ? "" : String(value));
      return true;
    } catch (error) {
      return false;
    }
  }

  function dispatch(eventName, detail) {
    try {
      if (core && typeof core.dispatch === "function") {
        core.dispatch(eventName, detail || {});
        return true;
      }

      document.dispatchEvent(new CustomEvent(eventName, {
        bubbles: true,
        cancelable: false,
        detail: detail || {}
      }));

      return true;
    } catch (error) {
      fallbackWarn("Dispatch failed: " + eventName, error);
      return false;
    }
  }

  function bindOnce(key, callback) {
    try {
      if (core && typeof core.bindOnce === "function") {
        core.bindOnce(key, callback);
        return;
      }

      var attr = "data-vp-" + String(key || "bind-once").replace(/[^a-z0-9_-]/gi, "-");

      if (document.documentElement.getAttribute(attr) === "true") {
        return;
      }

      document.documentElement.setAttribute(attr, "true");

      if (typeof callback === "function") {
        callback();
      }
    } catch (error) {
      safeWarn("bindOnce failed: " + key, error);
    }
  }

  function safeWarn(message, error) {
    try {
      if (core && typeof core.warn === "function") {
        core.warn(message, error);
        return;
      }
    } catch (coreError) {
      /* fallback below */
    }

    fallbackWarn(message, error);
  }

  function safeError(message, error) {
    try {
      if (core && typeof core.error === "function") {
        core.error(message, error);
        return;
      }
    } catch (coreError) {
      /* fallback below */
    }

    fallbackWarn(message, error);
  }

  function fallbackWarn(message, error) {
    try {
      if (window.console && typeof window.console.warn === "function") {
        if (typeof error !== "undefined") {
          window.console.warn("[VPLIB Create Theme] " + message, error);
        } else {
          window.console.warn("[VPLIB Create Theme] " + message);
        }
      }
    } catch (consoleError) {
      /* no-op */
    }
  }

  function buildFallbackCore() {
    try {
      return {
        selectors: DEFAULT_SELECTORS,
        state: {
          theme: "dark",
          themeStorageKey: "vectoplan.create.theme",
          context: {},
          uiState: {}
        },
        qsa: function (selector, root) {
          return Array.prototype.slice.call((root || document).querySelectorAll(selector));
        },
        safeSetAttribute: safeSetAttribute,
        dispatch: dispatch,
        bindOnce: bindOnce,
        registerModule: function () {},
        normalizeTheme: function (value) {
          var text = String(value || "").trim().toLowerCase();

          if (text === "light" || text === "system") {
            return text;
          }

          return "dark";
        },
        getNested: getNested,
        safeLocalStorageGet: safeLocalStorageGet,
        safeLocalStorageSet: safeLocalStorageSet,
        safeLocalStorageRemove: safeLocalStorageRemove,
        warn: fallbackWarn,
        error: fallbackWarn
      };
    } catch (error) {
      return null;
    }
  }

  var api = {
    version: THEME_VERSION,

    initialize: initialize,
    destroy: unbindSystemThemeListener,

    setTheme: setTheme,
    cycleTheme: cycleTheme,
    resetTheme: resetTheme,

    getTheme: getTheme,
    getEffectiveTheme: getEffectiveTheme,
    resolveEffectiveTheme: resolveEffectiveTheme,
    normalizeTheme: normalizeTheme,

    applyThemeAttributes: applyThemeAttributes,
    updateControls: updateControls,
    updateThemeMetaColor: updateThemeMetaColor,

    getState: getState
  };

  window[GLOBAL_NAME] = api;

  try {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        boot(0);
      }, { once: true });
    } else {
      boot(0);
    }
  } catch (error) {
    fallbackWarn("Theme runtime scheduling failed.", error);
  }
})();