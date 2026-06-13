/* services/vectoplan-library/static/library_admin/js/create_theme.js */

/* -----------------------------------------------------------------------------
  VECTOPLAN Library · VPLIB Create Theme Runtime

  Zweck:
  - Eigenständige Theme-Schicht für /create.
  - Entlastet die bisher zu große create.js.
  - Verwaltet light/dark/system Theme-Modus.
  - Hält bestehende data-create-theme-* Hooks stabil.
  - Speichert Nutzerauswahl robust in localStorage.
  - Reagiert bei system-Modus auf prefers-color-scheme Änderungen.
  - Setzt kompatible Attribute für bestehendes und zukünftiges CSS.
  - Löst keine Wizard-Navigation aus.
  - Erzeugt keine VPLIB-Dateien im Browser.

  Abhängigkeit:
  - Muss nach create_core.js geladen werden.
  - Erwartet window.VectoplanCreateCore.

  Öffentliche API:
  - window.VectoplanCreateTheme.initialize()
  - window.VectoplanCreateTheme.setTheme("light" | "dark" | "system", options)
  - window.VectoplanCreateTheme.cycleTheme()
  - window.VectoplanCreateTheme.getTheme()
  - window.VectoplanCreateTheme.getEffectiveTheme()
  - window.VectoplanCreateTheme.updateControls()
  - window.VectoplanCreateTheme.getState()
----------------------------------------------------------------------------- */

(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateTheme";
  var MODULE_NAME = "theme";
  var THEME_VERSION = "0.4.0";
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

  var EXTRA_SELECTORS = {
    themeToggle: "[data-create-theme-toggle='true'], [data-vp-theme-toggle]",
    themeLabel: "[data-create-theme-label='true'], [data-vp-theme-label]",
    themeValue: "[data-vp-theme-value]",
    themeEffectiveValue: "[data-vp-theme-effective-value]",
    themeIcon: "[data-vp-theme-icon]",
    themeOption: "[data-vp-theme-option]",
    themeSelect: "[data-vp-theme-select], [data-create-theme-select='true']"
  };

  var core = null;
  var selectors = null;
  var initialized = false;
  var bindingDone = false;
  var mediaQuery = null;

  var localState = {
    version: THEME_VERSION,
    initialized: false,
    bindingDone: false,
    theme: "system",
    effectiveTheme: "light",
    storageKey: "",
    source: "initial",
    changeCount: 0,
    systemChangeCount: 0,
    lastChange: null,
    lastError: null
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

        fallbackWarn("Core runtime missing; theme runtime not initialized.");
        return;
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

      core = coreRuntime || window[CORE_NAME];

      if (!core) {
        fallbackWarn("Cannot initialize theme without create_core.js.");
        return api;
      }

      selectors = core.selectors || {};
      localState.storageKey = resolveStorageKey();

      bindControls();
      bindSystemThemeListener();

      var initialTheme = resolveInitialTheme();
      setTheme(initialTheme, {
        persist: false,
        source: "initialize"
      });

      initialized = true;
      localState.initialized = true;

      if (typeof core.registerModule === "function") {
        core.registerModule(MODULE_NAME, api);
      }

      core.safeSetAttribute(document.documentElement, "data-theme-ready", "true");
      core.safeSetAttribute(document.documentElement, "data-vp-create-theme-ready", "true");
      core.safeSetAttribute(document.documentElement, "data-vp-create-theme-version", THEME_VERSION);

      core.dispatch("vectoplan:create:theme-ready", getState());

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

      if (core && typeof core.bindOnce === "function") {
        core.bindOnce("create-theme-click", bindThemeClicks);
        core.bindOnce("create-theme-select", bindThemeSelects);
        core.bindOnce("create-theme-core-events", bindCoreEvents);
      } else {
        bindThemeClicks();
        bindThemeSelects();
        bindCoreEvents();
      }
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

          var option = target.closest(EXTRA_SELECTORS.themeOption);

          if (option) {
            event.preventDefault();

            if (typeof event.stopPropagation === "function") {
              event.stopPropagation();
            }

            var explicitTheme = normalizeTheme(
              option.getAttribute("data-vp-theme-option") ||
              option.getAttribute("data-theme") ||
              option.getAttribute("data-value") ||
              ""
            );

            setTheme(explicitTheme, {
              persist: true,
              source: "theme-option"
            });
            return;
          }

          var toggle = target.closest(EXTRA_SELECTORS.themeToggle);

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

          if (!target || !target.matches || !target.matches(EXTRA_SELECTORS.themeSelect)) {
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

  function bindCoreEvents() {
    try {
      document.addEventListener("vectoplan:create:core-context-refreshed", function () {
        try {
          localState.storageKey = resolveStorageKey();

          if (!localState.theme) {
            setTheme(resolveInitialTheme(), {
              persist: false,
              source: "core-context-refreshed"
            });
          } else {
            applyThemeAttributes(localState.theme, {
              source: "core-context-refreshed"
            });
            updateControls();
          }
        } catch (error) {
          safeWarn("Theme context refresh handling failed.", error);
        }
      });
    } catch (error) {
      safeWarn("Theme core event binding failed.", error);
    }
  }

  function bindSystemThemeListener() {
    try {
      if (!window.matchMedia) {
        return false;
      }

      mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

      var handler = function () {
        try {
          if (localState.theme !== THEMES.system) {
            return;
          }

          localState.systemChangeCount += 1;
          applyThemeAttributes(THEMES.system, {
            source: "system-media-change"
          });
          updateControls();

          core.dispatch("vectoplan:create:theme-system-changed", getState());
        } catch (error) {
          safeWarn("System theme change handling failed.", error);
        }
      };

      if (typeof mediaQuery.addEventListener === "function") {
        mediaQuery.addEventListener("change", handler);
      } else if (typeof mediaQuery.addListener === "function") {
        mediaQuery.addListener(handler);
      }

      return true;
    } catch (error) {
      safeWarn("System theme listener binding failed.", error);
      return false;
    }
  }

  function resolveInitialTheme() {
    try {
      var fromStorage = core.safeLocalStorageGet(resolveStorageKey());
      var fromHtml = document.documentElement.getAttribute("data-theme") ||
        document.documentElement.getAttribute("data-vp-theme") ||
        "";
      var fromContext = core.getNested(core.state.context, ["theme", "default"], "") ||
        core.getNested(core.state.context, ["theme", "mode"], "") ||
        core.getNested(core.state.context, ["theme_default"], "") ||
        core.getNested(core.state.context, ["themeDefault"], "");
      var fromUiState = core.getNested(core.state.uiState, ["theme"], "") ||
        core.getNested(core.state.uiState, ["appearance"], "");

      return normalizeTheme(fromStorage || fromUiState || fromContext || fromHtml || THEMES.system);
    } catch (error) {
      return THEMES.system;
    }
  }

  function resolveStorageKey() {
    try {
      var fromState = core && core.state ? core.state.themeStorageKey : "";
      var fromContext = core && core.state
        ? core.getNested(core.state.context, ["theme", "storage_key"], "") ||
          core.getNested(core.state.context, ["theme", "storageKey"], "")
        : "";

      return String(fromContext || fromState || "vectoplan.create.theme").trim() || "vectoplan.create.theme";
    } catch (error) {
      return "vectoplan.create.theme";
    }
  }

  function setTheme(theme, options) {
    try {
      ensureCore();

      var normalized = normalizeTheme(theme);
      var safeOptions = options || {};
      var persist = !!safeOptions.persist;

      localState.theme = normalized;
      localState.effectiveTheme = resolveEffectiveTheme(normalized);
      localState.source = safeOptions.source || "api";
      localState.changeCount += 1;
      localState.lastChange = {
        theme: normalized,
        effectiveTheme: localState.effectiveTheme,
        persisted: persist,
        source: localState.source,
        timestamp: timestamp()
      };

      core.state.theme = normalized;

      applyThemeAttributes(normalized, safeOptions);

      if (persist) {
        core.safeLocalStorageSet(resolveStorageKey(), normalized);
      }

      updateControls();

      core.dispatch("vectoplan:create:theme-changed", getState());

      return normalized;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Set theme failed.", error);
      return localState.theme || THEMES.system;
    }
  }

  function cycleTheme(options) {
    try {
      var current = normalizeTheme(localState.theme || getTheme());
      var next = THEME_NEXT[current] || THEMES.system;

      return setTheme(next, {
        persist: true,
        source: options && options.source ? options.source : "cycle"
      });
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Theme cycle failed.", error);
      return localState.theme || THEMES.system;
    }
  }

  function applyThemeAttributes(theme, options) {
    try {
      var normalized = normalizeTheme(theme);
      var effective = resolveEffectiveTheme(normalized);
      var root = document.documentElement;
      var body = document.body;

      localState.effectiveTheme = effective;

      root.setAttribute("data-theme", normalized);
      root.setAttribute("data-vp-theme", normalized);
      root.setAttribute("data-vp-theme-mode", normalized);
      root.setAttribute("data-vp-theme-effective", effective);
      root.setAttribute("data-vp-effective-theme", effective);
      root.setAttribute("data-vp-color-scheme", effective);

      root.style.colorScheme = effective === THEMES.dark ? "dark" : "light";

      if (body) {
        body.setAttribute("data-theme", normalized);
        body.setAttribute("data-vp-theme", normalized);
        body.setAttribute("data-vp-theme-effective", effective);
      }

      updateThemeMetaColor(effective);

      core.dispatch("vectoplan:create:theme-applied", {
        theme: normalized,
        effectiveTheme: effective,
        source: options && options.source ? options.source : "api"
      });

      return true;
    } catch (error) {
      safeWarn("Apply theme attributes failed.", error);
      return false;
    }
  }

  function updateThemeMetaColor(effectiveTheme) {
    try {
      var color = effectiveTheme === THEMES.dark ? "#0f172a" : "#f8fafc";
      var meta = document.querySelector("meta[name='theme-color']");

      if (!meta) {
        meta = document.createElement("meta");
        meta.setAttribute("name", "theme-color");
        document.head.appendChild(meta);
      }

      meta.setAttribute("content", color);
    } catch (error) {
      safeWarn("Theme meta color update failed.", error);
    }
  }

  function updateControls() {
    try {
      var theme = normalizeTheme(localState.theme || THEMES.system);
      var effective = resolveEffectiveTheme(theme);
      var label = THEME_LABELS[theme] || THEME_LABELS.system;
      var title = THEME_TITLES[theme] || THEME_TITLES.system;

      var toggles = queryAll(EXTRA_SELECTORS.themeToggle);
      var labels = queryAll(EXTRA_SELECTORS.themeLabel);
      var values = queryAll(EXTRA_SELECTORS.themeValue);
      var effectiveValues = queryAll(EXTRA_SELECTORS.themeEffectiveValue);
      var icons = queryAll(EXTRA_SELECTORS.themeIcon);
      var options = queryAll(EXTRA_SELECTORS.themeOption);
      var selects = queryAll(EXTRA_SELECTORS.themeSelect);

      toggles.forEach(function (toggle) {
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

      labels.forEach(function (node) {
        node.textContent = label;
      });

      values.forEach(function (node) {
        node.textContent = theme;
      });

      effectiveValues.forEach(function (node) {
        node.textContent = effective;
      });

      icons.forEach(function (node) {
        try {
          node.setAttribute("data-vp-theme-icon-current", theme);
          node.setAttribute("data-vp-theme-icon-effective", effective);
          node.textContent = iconForTheme(theme, effective);
        } catch (error) {
          safeWarn("Theme icon update skipped.", error);
        }
      });

      options.forEach(function (node) {
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
        } catch (error) {
          safeWarn("Theme option update skipped.", error);
        }
      });

      selects.forEach(function (select) {
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
      return "◐";
    }
  }

  function getTheme() {
    try {
      return normalizeTheme(localState.theme || core.state.theme || THEMES.system);
    } catch (error) {
      return THEMES.system;
    }
  }

  function getEffectiveTheme() {
    try {
      return resolveEffectiveTheme(getTheme());
    } catch (error) {
      return THEMES.light;
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

      return THEMES.light;
    } catch (error) {
      return THEMES.light;
    }
  }

  function normalizeTheme(value) {
    try {
      if (core && typeof core.normalizeTheme === "function") {
        return core.normalizeTheme(value);
      }

      var text = String(value || "").trim().toLowerCase();

      if (text === THEMES.dark || text === THEMES.light || text === THEMES.system) {
        return text;
      }

      return THEMES.system;
    } catch (error) {
      return THEMES.system;
    }
  }

  function resetTheme(options) {
    try {
      var storageKey = resolveStorageKey();
      core.safeLocalStorageRemove(storageKey);

      return setTheme(THEMES.system, {
        persist: false,
        source: options && options.source ? options.source : "reset"
      });
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Reset theme failed.", error);
      return localState.theme || THEMES.system;
    }
  }

  function queryAll(selector) {
    try {
      if (core && typeof core.qsa === "function") {
        return core.qsa(selector);
      }

      return Array.prototype.slice.call(document.querySelectorAll(selector));
    } catch (error) {
      return [];
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
        systemChangeCount: localState.systemChangeCount,
        lastChange: localState.lastChange,
        lastError: localState.lastError,
        mediaQuerySupported: !!window.matchMedia
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
        core = window[CORE_NAME];
      }

      if (!core) {
        throw new Error("VectoplanCreateCore is not available.");
      }

      if (!selectors) {
        selectors = core.selectors || {};
      }

      return core;
    } catch (error) {
      throw error;
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

  var api = {
    version: THEME_VERSION,

    initialize: initialize,

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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      boot(0);
    }, { once: true });
  } else {
    boot(0);
  }
})();