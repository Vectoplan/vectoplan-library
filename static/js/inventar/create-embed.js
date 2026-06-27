// static/js/inventar/create-embed.js
(function () {
  "use strict";

  var MODULE_NAME = "VectoplanCreateEmbed";
  var MODULE_VERSION = "1.2.0";

  var DEFAULT_CREATE_URL = "/create";

  var SELECTORS = {
    root: "[data-create-embed-root]",
    fallbackRoot: ".vp-creative-layout",

    toggle: "[data-create-embed-toggle]",
    toggleLabel: "[data-create-embed-toggle-label]",

    panel: "[data-create-embed-panel]",
    frame: "[data-create-embed-frame]",

    libraryArea: "[data-create-embed-library-area]",
    filterArea: "[data-create-embed-filter-area]",
    subfilterArea: "[data-create-embed-subfilter-area]",
    hotbarArea: "[data-create-embed-hotbar-area]",

    taxonomyStatus: "[data-taxonomy-status]",
    taxonomyTabs: "[data-taxonomy-tabs]",
    taxonomyFilters: "[data-taxonomy-filters]",
    taxonomySubfilters: "[data-taxonomy-subfilters]",

    taxonomyControl: [
      "[data-taxonomy-domain]",
      "[data-taxonomy-category]",
      "[data-taxonomy-subcategory]",
      ".vp-creative-tab",
      ".vp-creative-filter",
      ".vp-creative-subfilter"
    ].join(", ")
  };

  var CLASSES = {
    rootActive: "vp-create-embed-is-active",
    rootTaxonomyLocked: "vp-create-embed-taxonomy-is-locked",

    toggleActive: "vp-creative-create-button--active",

    panelLoading: "vp-create-embed-panel--loading",
    panelReady: "vp-create-embed-panel--ready",
    panelError: "vp-create-embed-panel--error",

    taxonomyControlLocked: "vp-creative-taxonomy-control--locked"
  };

  var EVENTS = {
    taxonomySelectionChange: "vectoplan:taxonomy-selection-change",
    publicPrefix: "vectoplan:create-embed-"
  };

  var MESSAGE_TYPES = {
    close: {
      "vectoplan:create-close": true,
      "vectoplan:create:close": true,
      "vectoplan:createEmbed:close": true,
      "create-close": true,
      "create:close": true
    },
    reload: {
      "vectoplan:create-reload": true,
      "vectoplan:create:reload": true,
      "vectoplan:createEmbed:reload": true,
      "create-reload": true,
      "create:reload": true
    },
    ready: {
      "vectoplan:create-ready": true,
      "vectoplan:create:ready": true,
      "vectoplan:createEmbed:ready": true,
      "create-ready": true,
      "create:ready": true
    }
  };

  var state = {
    initialized: false,
    eventsBound: false,

    active: false,
    loading: false,
    loaded: false,
    error: null,

    createUrl: DEFAULT_CREATE_URL,
    statusDisabled: false,

    lockTaxonomyDuringCreate: true,
    closeOnTaxonomyClick: false,

    lastFocusedElement: null,
    previousHiddenState: [],
    previousTaxonomyState: [],

    elements: {
      root: null,
      toggle: null,
      toggleLabel: null,
      panel: null,
      frame: null,
      status: null,

      libraryAreas: [],
      filterAreas: [],
      subfilterAreas: [],
      hotbarAreas: [],

      taxonomyStatus: null,
      taxonomyTabs: null,
      taxonomyFilters: null,
      taxonomySubfilters: null,
      taxonomyControls: []
    }
  };

  function init() {
    try {
      if (state.initialized) {
        refreshElements();
        return true;
      }

      var root = findRootElement();

      if (!root) {
        return false;
      }

      state.elements.root = root;

      refreshElements();
      readConfiguration(root);

      if (!state.elements.toggle || !state.elements.panel) {
        warn("Create embed toggle or panel is missing.", {
          hasToggle: Boolean(state.elements.toggle),
          hasPanel: Boolean(state.elements.panel)
        });
        return false;
      }

      if (!state.statusDisabled) {
        state.elements.status = findOrCreateStatusElement(state.elements.panel);
      }

      bindEvents();
      applyInactiveMode({ restore: false, initial: true });

      state.initialized = true;
      dispatchEvent("ready");

      return true;
    } catch (err) {
      state.error = err;
      error("Initialization failed.", err);
      dispatchEvent("error", { error: stringifyError(err), operation: "init" });
      return false;
    }
  }

  function refreshElements() {
    try {
      var root = state.elements.root || findRootElement();

      if (!root) {
        return false;
      }

      state.elements.root = root;

      state.elements.toggle =
        root.querySelector(SELECTORS.toggle) ||
        document.querySelector(SELECTORS.toggle);

      state.elements.toggleLabel = state.elements.toggle
        ? state.elements.toggle.querySelector(SELECTORS.toggleLabel)
        : null;

      state.elements.panel =
        root.querySelector(SELECTORS.panel) ||
        document.querySelector(SELECTORS.panel);

      state.elements.frame =
        root.querySelector(SELECTORS.frame) ||
        document.querySelector(SELECTORS.frame);

      state.elements.taxonomyStatus = root.querySelector(SELECTORS.taxonomyStatus);
      state.elements.taxonomyTabs = root.querySelector(SELECTORS.taxonomyTabs);
      state.elements.taxonomyFilters = root.querySelector(SELECTORS.taxonomyFilters);
      state.elements.taxonomySubfilters = root.querySelector(SELECTORS.taxonomySubfilters);

      state.elements.libraryAreas = toArray(root.querySelectorAll(SELECTORS.libraryArea));
      state.elements.filterAreas = toArray(root.querySelectorAll(SELECTORS.filterArea));
      state.elements.subfilterAreas = toArray(root.querySelectorAll(SELECTORS.subfilterArea));
      state.elements.hotbarAreas = toArray(root.querySelectorAll(SELECTORS.hotbarArea));

      state.elements.taxonomyControls = collectTaxonomyControls(root);

      return true;
    } catch (err) {
      state.error = err;
      error("Could not refresh create embed elements.", err);
      return false;
    }
  }

  function readConfiguration(root) {
    try {
      var element = root || state.elements.root;

      state.statusDisabled = readBooleanDataset(element, "createEmbedStatusDisabled", false);

      state.lockTaxonomyDuringCreate = readBooleanDataset(
        element,
        "createEmbedLockTaxonomy",
        true
      );

      state.closeOnTaxonomyClick = readBooleanDataset(
        element,
        "createEmbedCloseOnTaxonomyClick",
        false
      );

      state.createUrl = resolveCreateUrl(element);

      syncRootConfigurationDataset();
    } catch (err) {
      warn("Configuration read failed. Defaults are used.", err);
      state.statusDisabled = false;
      state.lockTaxonomyDuringCreate = true;
      state.closeOnTaxonomyClick = false;
      state.createUrl = DEFAULT_CREATE_URL;
    }
  }

  function syncRootConfigurationDataset() {
    try {
      var root = state.elements.root;

      if (!root || !root.dataset) {
        return;
      }

      if (!("createEmbedActive" in root.dataset)) {
        root.dataset.createEmbedActive = state.active ? "true" : "false";
      }

      root.dataset.createEmbedLockTaxonomy = state.lockTaxonomyDuringCreate ? "true" : "false";
      root.dataset.createEmbedCloseOnTaxonomyClick = state.closeOnTaxonomyClick ? "true" : "false";

      if (!("taxonomyLocked" in root.dataset)) {
        root.dataset.taxonomyLocked = "false";
      }
    } catch (err) {
      // non-critical
    }
  }

  function bindEvents() {
    if (state.eventsBound) {
      return;
    }

    state.eventsBound = true;

    try {
      if (state.elements.toggle) {
        state.elements.toggle.addEventListener("click", function (event) {
          try {
            tryPreventDefault(event);
            toggle();
          } catch (err) {
            state.error = err;
            error("Toggle click failed.", err);
            dispatchEvent("error", { error: stringifyError(err), operation: "toggle-click" });
          }
        });
      }
    } catch (err) {
      state.error = err;
      error("Could not bind toggle event.", err);
    }

    try {
      if (state.elements.frame) {
        state.elements.frame.addEventListener("load", function () {
          markFrameLoaded();
        });
      }
    } catch (err) {
      state.error = err;
      error("Could not bind iframe load event.", err);
    }

    try {
      document.addEventListener("keydown", function (event) {
        try {
          handleDocumentKeydown(event);
        } catch (err) {
          state.error = err;
          error("Document keydown failed.", err);
          dispatchEvent("error", { error: stringifyError(err), operation: "document-keydown" });
        }
      });
    } catch (err) {
      state.error = err;
      error("Could not bind document keydown event.", err);
    }

    try {
      document.addEventListener(
        "click",
        function (event) {
          try {
            handleTaxonomyPointerInteraction(event);
          } catch (err) {
            state.error = err;
            error("Taxonomy click guard failed.", err);
          }
        },
        true
      );
    } catch (err) {
      state.error = err;
      error("Could not bind taxonomy click guard.", err);
    }

    try {
      document.addEventListener(
        "keydown",
        function (event) {
          try {
            handleTaxonomyKeyboardInteraction(event);
          } catch (err) {
            state.error = err;
            error("Taxonomy keyboard guard failed.", err);
          }
        },
        true
      );
    } catch (err) {
      state.error = err;
      error("Could not bind taxonomy keyboard guard.", err);
    }

    try {
      document.addEventListener(
        "focusin",
        function (event) {
          try {
            handleTaxonomyFocus(event);
          } catch (err) {
            state.error = err;
            error("Taxonomy focus guard failed.", err);
          }
        },
        true
      );
    } catch (err) {
      state.error = err;
      error("Could not bind taxonomy focus guard.", err);
    }

    try {
      document.addEventListener(EVENTS.taxonomySelectionChange, function () {
        try {
          refreshElements();

          if (state.active) {
            applyActiveMode({ keepFocus: true, fromTaxonomyChange: true });
          }
        } catch (err) {
          state.error = err;
          error("Taxonomy selection event failed.", err);
        }
      });
    } catch (err) {
      state.error = err;
      error("Could not bind taxonomy selection event.", err);
    }

    try {
      window.addEventListener("message", function (event) {
        try {
          handleFrameMessage(event);
        } catch (err) {
          state.error = err;
          error("Frame message handling failed.", err);
        }
      });
    } catch (err) {
      state.error = err;
      error("Could not bind frame message event.", err);
    }
  }

  function findRootElement() {
    try {
      return (
        document.querySelector(SELECTORS.root) ||
        document.querySelector(SELECTORS.fallbackRoot)
      );
    } catch (err) {
      state.error = err;
      error("Could not find create embed root.", err);
      return null;
    }
  }

  function collectTaxonomyControls(root) {
    try {
      if (!root) {
        return [];
      }

      return toArray(root.querySelectorAll(SELECTORS.taxonomyControl)).filter(function (element) {
        return !isCreateEmbedToggle(element);
      });
    } catch (err) {
      error("Could not collect taxonomy controls.", err);
      return [];
    }
  }

  function findOrCreateStatusElement(panel) {
    try {
      if (state.statusDisabled || !panel) {
        return null;
      }

      var existing =
        panel.querySelector("[data-create-embed-status]") ||
        panel.querySelector(".vp-create-embed-panel__status");

      if (existing) {
        return existing;
      }

      var status = document.createElement("div");
      status.className = "vp-create-embed-panel__status";
      status.setAttribute("data-create-embed-status", "true");
      status.setAttribute("aria-live", "polite");
      status.hidden = true;

      var header = panel.querySelector(".vp-create-embed-panel__header");

      if (header && header.parentNode) {
        header.parentNode.insertBefore(status, header.nextSibling);
      } else if (panel.firstChild) {
        panel.insertBefore(status, panel.firstChild);
      } else {
        panel.appendChild(status);
      }

      return status;
    } catch (err) {
      error("Could not create create-embed status element.", err);
      return null;
    }
  }

  function resolveCreateUrl(root) {
    try {
      var script = document.currentScript;
      var scriptUrl = script ? cleanString(script.getAttribute("data-create-url")) : "";
      var toggleUrl = state.elements.toggle ? cleanString(state.elements.toggle.getAttribute("data-create-url")) : "";
      var rootUrl = root ? cleanString(root.getAttribute("data-create-url")) : "";
      var frameUrl = state.elements.frame
        ? cleanString(state.elements.frame.getAttribute("data-src") || state.elements.frame.getAttribute("src"))
        : "";

      return sanitizeSameOriginUrl(scriptUrl || toggleUrl || rootUrl || frameUrl || DEFAULT_CREATE_URL);
    } catch (err) {
      warn("Could not resolve create URL. Falling back to default.", err);
      return DEFAULT_CREATE_URL;
    }
  }

  function sanitizeSameOriginUrl(value) {
    try {
      var raw = cleanString(value) || DEFAULT_CREATE_URL;
      var url = new URL(raw, window.location.href);

      if (url.origin !== window.location.origin) {
        warn("External create URL blocked. Falling back to /create.", {
          requested: raw,
          origin: url.origin
        });
        return DEFAULT_CREATE_URL;
      }

      return url.pathname + url.search + url.hash;
    } catch (err) {
      warn("Invalid create URL. Falling back to /create.", err);
      return DEFAULT_CREATE_URL;
    }
  }

  function open() {
    try {
      if (!state.initialized && !state.elements.root) {
        init();
      }

      refreshElements();

      if (!state.elements.root || !state.elements.panel) {
        return false;
      }

      if (state.active) {
        return true;
      }

      state.lastFocusedElement = safeActiveElement();
      state.active = true;
      state.error = null;

      captureHiddenState();
      ensureFrameSource();
      applyActiveMode({ keepFocus: false });
      dispatchEvent("open");

      return true;
    } catch (err) {
      state.error = err;
      setStatus("Create konnte nicht geöffnet werden.", "error");
      applyPanelState("error");
      error("Open failed.", err);
      dispatchEvent("error", { error: stringifyError(err), operation: "open" });
      return false;
    }
  }

  function close() {
    try {
      refreshElements();

      if (!state.elements.root || !state.elements.panel) {
        return false;
      }

      if (!state.active) {
        return true;
      }

      state.active = false;
      state.error = null;

      applyInactiveMode({ restore: true });
      restoreFocus();
      dispatchEvent("close");

      return true;
    } catch (err) {
      state.error = err;
      error("Close failed.", err);
      dispatchEvent("error", { error: stringifyError(err), operation: "close" });
      return false;
    }
  }

  function toggle() {
    try {
      if (state.active) {
        return close();
      }

      return open();
    } catch (err) {
      state.error = err;
      error("Toggle failed.", err);
      dispatchEvent("error", { error: stringifyError(err), operation: "toggle" });
      return false;
    }
  }

  function applyActiveMode(options) {
    try {
      refreshElements();

      var keepFocus = Boolean(options && options.keepFocus);
      var root = state.elements.root;

      if (!root || !state.elements.panel) {
        return;
      }

      root.dataset.createEmbedActive = "true";
      root.classList.add(CLASSES.rootActive);

      state.elements.panel.hidden = false;
      state.elements.panel.setAttribute("aria-hidden", "false");

      hideElements(state.elements.filterAreas);
      hideElements(state.elements.subfilterAreas);
      hideElements(state.elements.libraryAreas);
      hideElements(state.elements.hotbarAreas);

      if (state.elements.taxonomyStatus) {
        state.elements.taxonomyStatus.hidden = true;
        state.elements.taxonomyStatus.setAttribute("aria-hidden", "true");
      }

      setTaxonomyLocked(true, {
        silent: Boolean(options && options.fromTaxonomyChange)
      });

      setToggleActive(true);
      syncPanelContext();

      if (!state.loaded) {
        state.loading = true;
        applyPanelState("loading");
        setStatus("Create wird geladen ...", "loading");
      } else {
        state.loading = false;
        applyPanelState("ready");
        setStatus("", "ready");
      }

      if (!keepFocus) {
        focusPanel();
      }
    } catch (err) {
      state.error = err;
      error("Could not apply active mode.", err);
      dispatchEvent("error", { error: stringifyError(err), operation: "apply-active-mode" });
    }
  }

  function applyInactiveMode(options) {
    try {
      refreshElements();

      var shouldRestore = Boolean(options && options.restore);
      var isInitial = Boolean(options && options.initial);
      var root = state.elements.root;

      if (!root || !state.elements.panel) {
        return;
      }

      root.dataset.createEmbedActive = "false";
      root.classList.remove(CLASSES.rootActive);

      setTaxonomyLocked(false, {
        silent: isInitial
      });

      state.elements.panel.hidden = true;
      state.elements.panel.setAttribute("aria-hidden", "true");

      if (shouldRestore) {
        restoreHiddenState();
      } else {
        showElements(state.elements.filterAreas);
        restoreSubfilterDefaultVisibility();
        showElements(state.elements.libraryAreas);
        showElements(state.elements.hotbarAreas);
      }

      setToggleActive(false);
      applyPanelState("");
      setStatus("", "ready");
      syncPanelContext();
    } catch (err) {
      state.error = err;
      error("Could not apply inactive mode.", err);
      dispatchEvent("error", { error: stringifyError(err), operation: "apply-inactive-mode" });
    }
  }

  function ensureFrameSource() {
    try {
      var frame = state.elements.frame;

      if (!frame) {
        state.loaded = false;
        state.loading = false;
        setStatus("Create-Frame fehlt im Template.", "error");
        applyPanelState("error");
        return;
      }

      var currentSrc = cleanString(frame.getAttribute("src"));
      var currentUrl = currentSrc ? sanitizeSameOriginUrl(currentSrc) : "";
      var targetUrl = state.createUrl || DEFAULT_CREATE_URL;

      if (!currentSrc || currentSrc === "about:blank" || currentUrl !== targetUrl) {
        frame.setAttribute("src", targetUrl);
        frame.dataset.src = targetUrl;
        frame.dataset.loaded = "false";
        state.loaded = false;
        state.loading = true;
        return;
      }

      state.loaded = frame.dataset.loaded === "true";
      state.loading = !state.loaded;
    } catch (err) {
      state.error = err;
      setStatus("Create-Frame konnte nicht geladen werden.", "error");
      applyPanelState("error");
      error("Could not ensure frame source.", err);
      dispatchEvent("error", { error: stringifyError(err), operation: "ensure-frame-source" });
    }
  }

  function markFrameLoaded() {
    try {
      var frame = state.elements.frame;

      if (frame) {
        frame.dataset.loaded = "true";
      }

      state.loaded = true;
      state.loading = false;
      state.error = null;

      if (state.active) {
        applyPanelState("ready");
        setStatus("", "ready");
      }

      dispatchEvent("frame-load");
    } catch (err) {
      state.error = err;
      error("Could not mark frame as loaded.", err);
      dispatchEvent("error", { error: stringifyError(err), operation: "mark-frame-loaded" });
    }
  }

  function reloadFrame() {
    try {
      refreshElements();

      var frame = state.elements.frame;

      if (!frame) {
        return false;
      }

      state.loaded = false;
      state.loading = true;
      state.error = null;

      frame.dataset.loaded = "false";

      applyPanelState("loading");
      setStatus("Create wird neu geladen ...", "loading");

      frame.setAttribute("src", state.createUrl || DEFAULT_CREATE_URL);

      dispatchEvent("reload");

      return true;
    } catch (err) {
      state.error = err;
      error("Could not reload frame.", err);
      dispatchEvent("error", { error: stringifyError(err), operation: "reload-frame" });
      return false;
    }
  }

  function setCreateUrl(value) {
    try {
      var nextUrl = sanitizeSameOriginUrl(value || DEFAULT_CREATE_URL);

      state.createUrl = nextUrl;
      state.loaded = false;

      if (state.elements.root) {
        state.elements.root.dataset.createUrl = nextUrl;
      }

      if (state.elements.toggle) {
        state.elements.toggle.setAttribute("data-create-url", nextUrl);
      }

      if (state.elements.frame) {
        state.elements.frame.dataset.src = nextUrl;
        state.elements.frame.dataset.loaded = "false";
      }

      dispatchEvent("url-change", { createUrl: nextUrl });

      return nextUrl;
    } catch (err) {
      state.error = err;
      error("Could not set create URL.", err);
      dispatchEvent("error", { error: stringifyError(err), operation: "set-create-url" });
      return state.createUrl;
    }
  }

  function setToggleActive(isActive) {
    try {
      var toggleButton = state.elements.toggle;

      if (!toggleButton) {
        return;
      }

      var openLabel = cleanString(toggleButton.getAttribute("data-open-label")) || "Neues Element hinzufügen";
      var closeLabel = cleanString(toggleButton.getAttribute("data-close-label")) || "Creative Library anzeigen";
      var label = isActive ? closeLabel : openLabel;

      toggleButton.classList.toggle(CLASSES.toggleActive, Boolean(isActive));
      toggleButton.setAttribute("aria-expanded", isActive ? "true" : "false");
      toggleButton.setAttribute("data-create-embed-toggle-active", isActive ? "true" : "false");

      if (state.elements.toggleLabel) {
        state.elements.toggleLabel.textContent = label;
      } else {
        toggleButton.textContent = label;
      }
    } catch (err) {
      error("Could not update toggle state.", err);
    }
  }

  function syncPanelContext() {
    try {
      var panel = state.elements.panel;
      var root = state.elements.root;

      if (!panel || !root || !root.dataset) {
        return;
      }

      panel.dataset.selectedDomain = root.dataset.selectedDomain || "all";
      panel.dataset.selectedCategory = root.dataset.selectedCategory || "all";
      panel.dataset.selectedSubcategory = root.dataset.selectedSubcategory || "all";
      panel.dataset.createUrl = state.createUrl || DEFAULT_CREATE_URL;
      panel.dataset.taxonomyLocked = root.dataset.taxonomyLocked || "false";
    } catch (err) {
      // non-critical
    }
  }

  function setTaxonomyLocked(locked, options) {
    try {
      var shouldLock = Boolean(locked) && state.lockTaxonomyDuringCreate;
      var root = state.elements.root;
      var silent = Boolean(options && options.silent);

      if (!root) {
        return false;
      }

      if (shouldLock) {
        captureTaxonomyState();
        applyTaxonomyControlLock();
      } else {
        restoreTaxonomyControlState();
      }

      root.dataset.taxonomyLocked = shouldLock ? "true" : "false";
      root.classList.toggle(CLASSES.rootTaxonomyLocked, shouldLock);

      syncPanelContext();

      if (!silent) {
        dispatchEvent("taxonomy-lock-change", {
          taxonomyLocked: shouldLock
        });
      }

      return true;
    } catch (err) {
      state.error = err;
      error("Could not update taxonomy lock.", err);
      dispatchEvent("error", { error: stringifyError(err), operation: "set-taxonomy-locked" });
      return false;
    }
  }

  function captureTaxonomyState() {
    try {
      refreshElements();

      var controls = state.elements.taxonomyControls || [];

      state.previousTaxonomyState = [];

      controls.forEach(function (element) {
        try {
          if (!element) {
            return;
          }

          state.previousTaxonomyState.push({
            element: element,
            tabindex: element.hasAttribute("tabindex") ? element.getAttribute("tabindex") : null,
            ariaDisabled: element.hasAttribute("aria-disabled") ? element.getAttribute("aria-disabled") : null,
            dataLocked: element.hasAttribute("data-create-embed-taxonomy-locked")
              ? element.getAttribute("data-create-embed-taxonomy-locked")
              : null,
            classLocked: element.classList.contains(CLASSES.taxonomyControlLocked)
          });
        } catch (err) {
          // ignore single element capture failure
        }
      });
    } catch (err) {
      state.previousTaxonomyState = [];
    }
  }

  function applyTaxonomyControlLock() {
    try {
      refreshElements();

      var controls = state.elements.taxonomyControls || [];

      controls.forEach(function (element) {
        try {
          if (!element || isCreateEmbedToggle(element)) {
            return;
          }

          element.classList.add(CLASSES.taxonomyControlLocked);
          element.setAttribute("aria-disabled", "true");
          element.setAttribute("data-create-embed-taxonomy-locked", "true");
          element.setAttribute("tabindex", "-1");
        } catch (err) {
          // ignore single element lock failure
        }
      });
    } catch (err) {
      error("Could not apply taxonomy control lock.", err);
    }
  }

  function restoreTaxonomyControlState() {
    try {
      var restored = [];

      state.previousTaxonomyState.forEach(function (entry) {
        try {
          if (!entry || !entry.element || !documentContains(entry.element)) {
            return;
          }

          restored.push(entry.element);

          if (entry.classLocked) {
            entry.element.classList.add(CLASSES.taxonomyControlLocked);
          } else {
            entry.element.classList.remove(CLASSES.taxonomyControlLocked);
          }

          if (entry.tabindex === null) {
            entry.element.removeAttribute("tabindex");
          } else {
            entry.element.setAttribute("tabindex", entry.tabindex);
          }

          if (entry.ariaDisabled === null) {
            entry.element.removeAttribute("aria-disabled");
          } else {
            entry.element.setAttribute("aria-disabled", entry.ariaDisabled);
          }

          if (entry.dataLocked === null) {
            entry.element.removeAttribute("data-create-embed-taxonomy-locked");
          } else {
            entry.element.setAttribute("data-create-embed-taxonomy-locked", entry.dataLocked);
          }
        } catch (err) {
          // ignore single element restore failure
        }
      });

      cleanupCurrentTaxonomyControls(restored);

      state.previousTaxonomyState = [];
    } catch (err) {
      cleanupCurrentTaxonomyControls([]);
      state.previousTaxonomyState = [];
    }
  }

  function cleanupCurrentTaxonomyControls(restoredElements) {
    try {
      refreshElements();

      var restored = restoredElements || [];
      var controls = state.elements.taxonomyControls || [];

      controls.forEach(function (element) {
        try {
          if (!element || restored.indexOf(element) !== -1) {
            return;
          }

          element.classList.remove(CLASSES.taxonomyControlLocked);

          if (element.getAttribute("data-create-embed-taxonomy-locked") === "true") {
            element.removeAttribute("data-create-embed-taxonomy-locked");
          }

          if (element.getAttribute("aria-disabled") === "true") {
            element.removeAttribute("aria-disabled");
          }

          if (element.getAttribute("tabindex") === "-1") {
            element.removeAttribute("tabindex");
          }
        } catch (err) {
          // ignore single element cleanup failure
        }
      });
    } catch (err) {
      // non-critical
    }
  }

  function shouldBlockTaxonomyInteraction(event) {
    try {
      if (!state.active || !state.lockTaxonomyDuringCreate) {
        return false;
      }

      if (!event || !event.target) {
        return false;
      }

      var control = findTaxonomyControlFromEvent(event);

      if (!control) {
        return false;
      }

      if (isCreateEmbedToggle(control)) {
        return false;
      }

      return true;
    } catch (err) {
      return false;
    }
  }

  function handleTaxonomyPointerInteraction(event) {
    if (!shouldBlockTaxonomyInteraction(event)) {
      return;
    }

    var control = findTaxonomyControlFromEvent(event);

    blockTaxonomyEvent(event, control, "pointer");

    if (state.closeOnTaxonomyClick) {
      close();
    }
  }

  function handleTaxonomyKeyboardInteraction(event) {
    try {
      if (!shouldBlockTaxonomyInteraction(event)) {
        return;
      }

      var key = event.key;

      if (
        key !== "Enter" &&
        key !== " " &&
        key !== "Spacebar" &&
        key !== "ArrowLeft" &&
        key !== "ArrowRight" &&
        key !== "ArrowUp" &&
        key !== "ArrowDown" &&
        key !== "Home" &&
        key !== "End"
      ) {
        return;
      }

      var control = findTaxonomyControlFromEvent(event);

      blockTaxonomyEvent(event, control, "keyboard");
    } catch (err) {
      error("Could not handle taxonomy keyboard interaction.", err);
    }
  }

  function handleTaxonomyFocus(event) {
    try {
      if (!state.active || !state.lockTaxonomyDuringCreate) {
        return;
      }

      var control = findTaxonomyControlFromEvent(event);

      if (!control || isCreateEmbedToggle(control)) {
        return;
      }

      if (state.elements.toggle && typeof state.elements.toggle.focus === "function") {
        state.elements.toggle.focus({ preventScroll: true });
        return;
      }

      focusPanel();
    } catch (err) {
      // non-critical
    }
  }

  function blockTaxonomyEvent(event, control, source) {
    try {
      safeStopEvent(event);

      if (state.elements.root) {
        state.elements.root.dataset.lastBlockedTaxonomyInteraction = String(Date.now());
      }

      dispatchEvent("taxonomy-blocked", {
        taxonomyLocked: true,
        source: source || "unknown",
        controlType: getTaxonomyControlType(control),
        controlValue: getTaxonomyControlValue(control)
      });
    } catch (err) {
      error("Could not block taxonomy event.", err);
    }
  }

  function findTaxonomyControlFromEvent(event) {
    try {
      var target = event && event.target ? event.target : null;

      if (!target) {
        return null;
      }

      return closest(target, SELECTORS.taxonomyControl);
    } catch (err) {
      return null;
    }
  }

  function getTaxonomyControlType(control) {
    try {
      if (!control) {
        return "";
      }

      if (control.hasAttribute("data-taxonomy-domain")) {
        return "domain";
      }

      if (control.hasAttribute("data-taxonomy-category")) {
        return "category";
      }

      if (control.hasAttribute("data-taxonomy-subcategory")) {
        return "subcategory";
      }

      if (control.classList.contains("vp-creative-tab")) {
        return "domain";
      }

      if (control.classList.contains("vp-creative-filter")) {
        return "category";
      }

      if (control.classList.contains("vp-creative-subfilter")) {
        return "subcategory";
      }

      return "unknown";
    } catch (err) {
      return "unknown";
    }
  }

  function getTaxonomyControlValue(control) {
    try {
      if (!control) {
        return "";
      }

      return (
        cleanString(control.getAttribute("data-taxonomy-domain")) ||
        cleanString(control.getAttribute("data-taxonomy-category")) ||
        cleanString(control.getAttribute("data-taxonomy-subcategory")) ||
        cleanString(control.textContent)
      );
    } catch (err) {
      return "";
    }
  }

  function handleDocumentKeydown(event) {
    try {
      if (!state.active) {
        return;
      }

      if (event.key === "Escape") {
        tryPreventDefault(event);
        close();
      }
    } catch (err) {
      state.error = err;
      error("Could not handle document keydown.", err);
    }
  }

  function handleFrameMessage(event) {
    try {
      if (!event || event.origin !== window.location.origin) {
        return;
      }

      var data = normalizeMessageData(event.data);
      var type = cleanString(data.type || data.event || data.name);

      if (!type) {
        return;
      }

      if (MESSAGE_TYPES.close[type]) {
        close();
        return;
      }

      if (MESSAGE_TYPES.reload[type]) {
        reloadFrame();
        return;
      }

      if (MESSAGE_TYPES.ready[type]) {
        markFrameLoaded();
        return;
      }

      if (type === "vectoplan:create-url" || type === "vectoplan:create:set-url") {
        if (data.url) {
          setCreateUrl(data.url);
        }
      }
    } catch (err) {
      error("Could not handle frame message.", err);
    }
  }

  function normalizeMessageData(value) {
    try {
      if (!value) {
        return {};
      }

      if (typeof value === "object") {
        return value;
      }

      if (typeof value === "string") {
        try {
          var parsed = JSON.parse(value);
          return parsed && typeof parsed === "object" ? parsed : { type: value };
        } catch (err) {
          return { type: value };
        }
      }

      return {};
    } catch (err) {
      return {};
    }
  }

  function applyPanelState(mode) {
    try {
      var panel = state.elements.panel;

      if (!panel) {
        return;
      }

      panel.classList.remove(CLASSES.panelLoading);
      panel.classList.remove(CLASSES.panelReady);
      panel.classList.remove(CLASSES.panelError);

      if (mode === "loading") {
        panel.classList.add(CLASSES.panelLoading);
      } else if (mode === "ready") {
        panel.classList.add(CLASSES.panelReady);
      } else if (mode === "error") {
        panel.classList.add(CLASSES.panelError);
      }
    } catch (err) {
      // non-critical
    }
  }

  function setStatus(message, mode) {
    try {
      if (state.statusDisabled) {
        return;
      }

      var status = state.elements.status;

      if (!status) {
        return;
      }

      var text = cleanString(message);
      var cleanMode = cleanString(mode) || "info";

      status.className = "vp-create-embed-panel__status vp-create-embed-panel__status--" + cleanMode;

      if (!text) {
        status.hidden = true;
        status.textContent = "";
        return;
      }

      status.hidden = false;
      status.textContent = text;
    } catch (err) {
      // non-critical
    }
  }

  function captureHiddenState() {
    try {
      state.previousHiddenState = [];

      var elements = []
        .concat(state.elements.filterAreas)
        .concat(state.elements.subfilterAreas)
        .concat(state.elements.libraryAreas)
        .concat(state.elements.hotbarAreas);

      elements.forEach(function (element) {
        if (!element) {
          return;
        }

        state.previousHiddenState.push({
          element: element,
          hidden: Boolean(element.hidden),
          ariaHidden: element.hasAttribute("aria-hidden") ? element.getAttribute("aria-hidden") : null,
          role: getElementRole(element)
        });
      });
    } catch (err) {
      state.previousHiddenState = [];
    }
  }

  function restoreHiddenState() {
    try {
      if (!state.previousHiddenState.length) {
        showElements(state.elements.filterAreas);
        restoreSubfilterDefaultVisibility();
        showElements(state.elements.libraryAreas);
        showElements(state.elements.hotbarAreas);
        return;
      }

      state.previousHiddenState.forEach(function (entry) {
        try {
          if (!entry || !entry.element) {
            return;
          }

          if (entry.role === "subfilter") {
            entry.element.hidden = shouldSubfilterBeHidden(entry.element, entry.hidden);
          } else {
            entry.element.hidden = Boolean(entry.hidden);
          }

          restoreAriaHidden(entry.element, entry.ariaHidden);
        } catch (err) {
          // ignore single element restore failure
        }
      });

      state.previousHiddenState = [];
    } catch (err) {
      showElements(state.elements.filterAreas);
      restoreSubfilterDefaultVisibility();
      showElements(state.elements.libraryAreas);
      showElements(state.elements.hotbarAreas);
    }
  }

  function restoreSubfilterDefaultVisibility() {
    try {
      state.elements.subfilterAreas.forEach(function (element) {
        element.hidden = shouldSubfilterBeHidden(element, element.hidden);

        if (element.hidden) {
          element.setAttribute("aria-hidden", "true");
        } else {
          element.removeAttribute("aria-hidden");
        }
      });
    } catch (err) {
      hideElements(state.elements.subfilterAreas);
    }
  }

  function shouldSubfilterBeHidden(element, fallbackHidden) {
    try {
      var root = state.elements.root;
      var selectedDomain = root && root.dataset ? cleanString(root.dataset.selectedDomain) : "all";
      var selectedCategory = root && root.dataset ? cleanString(root.dataset.selectedCategory) : "all";

      if (!selectedDomain || selectedDomain === "all" || selectedDomain === "world_edit") {
        return true;
      }

      if (!selectedCategory || selectedCategory === "all") {
        return true;
      }

      if (!element || !element.children || element.children.length === 0) {
        return true;
      }

      return false;
    } catch (err) {
      return Boolean(fallbackHidden);
    }
  }

  function getElementRole(element) {
    try {
      if (state.elements.subfilterAreas.indexOf(element) !== -1) {
        return "subfilter";
      }

      if (state.elements.filterAreas.indexOf(element) !== -1) {
        return "filter";
      }

      if (state.elements.libraryAreas.indexOf(element) !== -1) {
        return "library";
      }

      if (state.elements.hotbarAreas.indexOf(element) !== -1) {
        return "hotbar";
      }

      return "unknown";
    } catch (err) {
      return "unknown";
    }
  }

  function hideElements(elements) {
    try {
      elements.forEach(function (element) {
        if (element) {
          element.hidden = true;
          element.setAttribute("aria-hidden", "true");
        }
      });
    } catch (err) {
      // non-critical
    }
  }

  function showElements(elements) {
    try {
      elements.forEach(function (element) {
        if (element) {
          element.hidden = false;
          element.removeAttribute("aria-hidden");
        }
      });
    } catch (err) {
      // non-critical
    }
  }

  function restoreAriaHidden(element, previousValue) {
    try {
      if (!element) {
        return;
      }

      if (previousValue === null || previousValue === undefined) {
        element.removeAttribute("aria-hidden");
        return;
      }

      element.setAttribute("aria-hidden", previousValue);
    } catch (err) {
      // non-critical
    }
  }

  function focusPanel() {
    try {
      var panel = state.elements.panel;

      if (!panel) {
        return;
      }

      if (!panel.hasAttribute("tabindex")) {
        panel.setAttribute("tabindex", "-1");
      }

      panel.focus({ preventScroll: true });
    } catch (err) {
      try {
        state.elements.panel.focus();
      } catch (focusError) {
        // ignore
      }
    }
  }

  function restoreFocus() {
    try {
      var element = state.lastFocusedElement;

      if (element && typeof element.focus === "function" && documentContains(element)) {
        element.focus({ preventScroll: true });
      }

      state.lastFocusedElement = null;
    } catch (err) {
      state.lastFocusedElement = null;
    }
  }

  function safeActiveElement() {
    try {
      return document.activeElement || null;
    } catch (err) {
      return null;
    }
  }

  function dispatchEvent(type, extraDetail) {
    try {
      var rootDataset = state.elements.root && state.elements.root.dataset
        ? state.elements.root.dataset
        : {};

      var detail = {
        type: type,
        active: state.active,
        loading: state.loading,
        loaded: state.loaded,
        createUrl: state.createUrl,
        selectedDomain: rootDataset.selectedDomain || "all",
        selectedCategory: rootDataset.selectedCategory || "all",
        selectedSubcategory: rootDataset.selectedSubcategory || "all",
        taxonomyLocked: rootDataset.taxonomyLocked === "true",
        lockTaxonomyDuringCreate: state.lockTaxonomyDuringCreate,
        closeOnTaxonomyClick: state.closeOnTaxonomyClick,
        module: MODULE_NAME,
        version: MODULE_VERSION
      };

      if (extraDetail && typeof extraDetail === "object") {
        Object.keys(extraDetail).forEach(function (key) {
          detail[key] = extraDetail[key];
        });
      }

      document.dispatchEvent(
        new CustomEvent(EVENTS.publicPrefix + type, {
          bubbles: true,
          detail: detail
        })
      );
    } catch (err) {
      // non-critical
    }
  }

  function readBooleanDataset(element, key, fallback) {
    try {
      if (!element || !element.dataset || !(key in element.dataset)) {
        return fallback;
      }

      var value = cleanString(element.dataset[key]).toLowerCase();

      if (value === "1" || value === "true" || value === "yes" || value === "ja" || value === "on") {
        return true;
      }

      if (value === "0" || value === "false" || value === "no" || value === "nein" || value === "off") {
        return false;
      }

      return fallback;
    } catch (err) {
      return fallback;
    }
  }

  function setLockTaxonomyDuringCreate(value) {
    try {
      state.lockTaxonomyDuringCreate = Boolean(value);

      if (state.elements.root && state.elements.root.dataset) {
        state.elements.root.dataset.createEmbedLockTaxonomy = state.lockTaxonomyDuringCreate ? "true" : "false";
      }

      if (state.active) {
        setTaxonomyLocked(state.lockTaxonomyDuringCreate);
      }

      return state.lockTaxonomyDuringCreate;
    } catch (err) {
      state.error = err;
      error("Could not set taxonomy lock preference.", err);
      return state.lockTaxonomyDuringCreate;
    }
  }

  function setCloseOnTaxonomyClick(value) {
    try {
      state.closeOnTaxonomyClick = Boolean(value);

      if (state.elements.root && state.elements.root.dataset) {
        state.elements.root.dataset.createEmbedCloseOnTaxonomyClick = state.closeOnTaxonomyClick ? "true" : "false";
      }

      return state.closeOnTaxonomyClick;
    } catch (err) {
      state.error = err;
      error("Could not set taxonomy close preference.", err);
      return state.closeOnTaxonomyClick;
    }
  }

  function getState() {
    return {
      initialized: state.initialized,
      active: state.active,
      loading: state.loading,
      loaded: state.loaded,
      error: state.error ? stringifyError(state.error) : null,
      createUrl: state.createUrl,
      statusDisabled: state.statusDisabled,
      lockTaxonomyDuringCreate: state.lockTaxonomyDuringCreate,
      closeOnTaxonomyClick: state.closeOnTaxonomyClick,
      taxonomyLocked: Boolean(
        state.elements.root &&
        state.elements.root.dataset &&
        state.elements.root.dataset.taxonomyLocked === "true"
      ),
      hasRoot: Boolean(state.elements.root),
      hasToggle: Boolean(state.elements.toggle),
      hasPanel: Boolean(state.elements.panel),
      hasFrame: Boolean(state.elements.frame),
      hiddenAreas: {
        filters: state.elements.filterAreas.length,
        subfilters: state.elements.subfilterAreas.length,
        library: state.elements.libraryAreas.length,
        hotbar: state.elements.hotbarAreas.length
      },
      taxonomy: {
        hasTabs: Boolean(state.elements.taxonomyTabs),
        hasFilters: Boolean(state.elements.taxonomyFilters),
        hasSubfilters: Boolean(state.elements.taxonomySubfilters),
        controls: state.elements.taxonomyControls.length,
        previousControls: state.previousTaxonomyState.length
      },
      module: MODULE_NAME,
      version: MODULE_VERSION
    };
  }

  function isCreateEmbedToggle(element) {
    try {
      if (!element) {
        return false;
      }

      if (element === state.elements.toggle) {
        return true;
      }

      return Boolean(closest(element, SELECTORS.toggle));
    } catch (err) {
      return false;
    }
  }

  function closest(element, selector) {
    try {
      if (!element || !selector) {
        return null;
      }

      if (typeof element.closest === "function") {
        return element.closest(selector);
      }

      var current = element;

      while (current && current !== document) {
        if (matches(current, selector)) {
          return current;
        }

        current = current.parentNode;
      }

      return null;
    } catch (err) {
      return null;
    }
  }

  function matches(element, selector) {
    try {
      if (!element || element.nodeType !== 1) {
        return false;
      }

      var fn =
        element.matches ||
        element.msMatchesSelector ||
        element.webkitMatchesSelector ||
        element.mozMatchesSelector;

      if (typeof fn !== "function") {
        return false;
      }

      return fn.call(element, selector);
    } catch (err) {
      return false;
    }
  }

  function safeStopEvent(event) {
    tryPreventDefault(event);

    try {
      if (event && typeof event.stopPropagation === "function") {
        event.stopPropagation();
      }
    } catch (err) {
      // ignore
    }

    try {
      if (event && typeof event.stopImmediatePropagation === "function") {
        event.stopImmediatePropagation();
      }
    } catch (err) {
      // ignore
    }
  }

  function tryPreventDefault(event) {
    try {
      if (event && typeof event.preventDefault === "function") {
        event.preventDefault();
      }
    } catch (err) {
      // ignore
    }
  }

  function documentContains(element) {
    try {
      return Boolean(element && document.documentElement && document.documentElement.contains(element));
    } catch (err) {
      try {
        return Boolean(element && document.body && document.body.contains(element));
      } catch (fallbackError) {
        return false;
      }
    }
  }

  function toArray(value) {
    try {
      return Array.prototype.slice.call(value || []);
    } catch (err) {
      return [];
    }
  }

  function cleanString(value) {
    try {
      if (value === null || value === undefined) {
        return "";
      }

      return String(value).trim();
    } catch (err) {
      return "";
    }
  }

  function stringifyError(err) {
    try {
      if (!err) {
        return "";
      }

      return String(err.message || err);
    } catch (stringifyFailure) {
      return "Unknown error";
    }
  }

  function warn(message, extra) {
    try {
      if (window.console && typeof window.console.warn === "function") {
        window.console.warn("[" + MODULE_NAME + "] " + message, extra || "");
      }
    } catch (err) {
      // ignore
    }
  }

  function error(message, err) {
    try {
      if (window.console && typeof window.console.error === "function") {
        window.console.error("[" + MODULE_NAME + "] " + message, err || "");
      }
    } catch (consoleError) {
      // ignore
    }
  }

  window[MODULE_NAME] = {
    init: init,
    open: open,
    close: close,
    toggle: toggle,
    reloadFrame: reloadFrame,
    setCreateUrl: setCreateUrl,
    setTaxonomyLocked: setTaxonomyLocked,
    setLockTaxonomyDuringCreate: setLockTaxonomyDuringCreate,
    setCloseOnTaxonomyClick: setCloseOnTaxonomyClick,
    refreshElements: refreshElements,
    getState: getState
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();