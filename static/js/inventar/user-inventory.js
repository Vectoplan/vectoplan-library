// static/js/inventar/user-inventory.js
(function () {
  "use strict";

  var MODULE_NAME = "VectoplanUserInventory";
  var MODULE_VERSION = "1.5.0";

  var DEFAULT_USER_ID = 1;
  var DEFAULT_INVENTORY_KEY = "default";
  var DEFAULT_SLOT_COUNT = 9;
  var MIN_SLOT_INDEX = 1;
  var MAX_SLOT_INDEX = 9;

  var DEFAULT_API_URL = "/api/v1/vplib/inventar_user";
  var DEFAULT_SELECT_URL = "/api/v1/vplib/inventar_user/select-slot";

  var CACHE_NAMESPACE = "vectoplan.userInventory.v1";
  var CACHE_TTL_MS = 120000;
  var SAVE_DEBOUNCE_MS = 140;
  var STATUS_HIDE_DELAY_MS = 1200;
  var WHEEL_THROTTLE_MS = 120;
  var CACHE_WRITE_DEBOUNCE_MS = 180;
  var SELECTION_LABEL_HIDE_DELAY_MS = 1500;
  var CREATIVE_DRAG_MIME = "application/x-vectoplan-vplib-item+json";
  var CREATIVE_POINTER_DRAG_START = "vectoplan:creative-pointer-drag-start";
  var CREATIVE_POINTER_DRAG_MOVE = "vectoplan:creative-pointer-drag-move";
  var CREATIVE_POINTER_DRAG_END = "vectoplan:creative-pointer-drag-end";

  var SELECTORS = {
    root: "[data-user-inventory-root]",
    fallbackRoot: "#vp-user-inventory-root, #vp-creative-inventory-root, .vp-user-inventory-root",
    hotbar: "[data-user-inventory-hotbar]",
    slots: "[data-user-inventory-slots]",
    slot: "[data-slot-index]",
    status: "[data-user-inventory-status]",
    creativeCard: "[data-creative-item-card], [data-creative-card], .vp-creative-card",
    createEmbedRoot: "[data-create-embed-root]"
  };

  var CLASSES = {
    active: "vp-user-slot--active",
    selected: "vp-user-slot--selected",
    empty: "vp-user-slot--empty",
    filled: "vp-user-slot--filled",
    saving: "vp-user-slot--saving",
    error: "vp-user-slot--error",
    locked: "vp-user-slot--locked",
    pinned: "vp-user-slot--pinned",
    dropTarget: "vp-user-slot--drop-target",
    selectionAnnounced: "vp-user-slot--selection-announced",

    statusLoading: "vp-user-inventory-status--loading",
    statusSaving: "vp-user-inventory-status--saving",
    statusReady: "vp-user-inventory-status--ready",
    statusError: "vp-user-inventory-status--error"
  };

  var EVENTS = {
    selectSlot: "vectoplan:user-inventory-select-slot",
    setSlot: "vectoplan:user-inventory-set-slot",
    clearSlot: "vectoplan:user-inventory-clear-slot",
    reload: "vectoplan:user-inventory-reload",
    requestState: "vectoplan:user-inventory-request-state",
    creativeItemPick: "vectoplan:creative-item-pick",
    createEmbedOpen: "vectoplan:create-embed-open",
    createEmbedClose: "vectoplan:create-embed-close"
  };

  var memoryCache = Object.create(null);

  var state = {
    initialized: false,
    eventsBound: false,
    loading: false,
    saving: false,
    loadedFromApi: false,
    lastError: null,

    userId: DEFAULT_USER_ID,
    inventoryKey: DEFAULT_INVENTORY_KEY,
    slotCount: DEFAULT_SLOT_COUNT,
    activeSlotIndex: MIN_SLOT_INDEX,
    lastSelectedSlotIndex: MIN_SLOT_INDEX,

    apiUrl: DEFAULT_API_URL,
    selectUrl: DEFAULT_SELECT_URL,

    cacheEnabled: true,
    wheelNavigationEnabled: true,
    keyboardNavigationEnabled: true,
    cardSelectionEnabled: false,
    suspendDuringCreateEmbed: true,

    wheelNavigationScope: "document",

    wheelLockedUntil: 0,
    pendingSaveTimer: null,
    pendingCacheTimer: null,
    selectionLabelTimer: null,
    statusTimer: null,
    activeDragItem: null,

    slots: [],

    elements: {
      root: null,
      hotbar: null,
      slots: null,
      status: null,
      slotElements: [],
      creativeCards: []
    }
  };

  function init() {
    try {
      if (state.initialized) {
        refreshElements();
        ensureSlotElements();
        bindSlotClickEvents();
        bindSlotDropEvents();
        render();
        return true;
      }

      var root = findRootElement();

      if (!root) {
        warn("User inventory root not found.");
        return false;
      }

      state.elements.root = root;

      refreshElements();
      readConfiguration(root);
      ensureSlotElements();
      readInitialDomState();
      bindEvents();

      var cached = readCache();

      if (cached) {
        applyInventoryPayload(cached, {
          source: "cache",
          persist: false,
          render: true,
          preserveExistingSlots: true
        });
      } else {
        render();
      }

      state.initialized = true;
      dispatch("ready");

      loadInventory();

      return true;
    } catch (err) {
      state.lastError = err;
      setStatus("User-Inventar konnte nicht initialisiert werden.", "error");
      error("Initialization failed.", err);
      dispatch("error", {
        operation: "init",
        error: stringifyError(err)
      });
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
      state.elements.hotbar = root.querySelector(SELECTORS.hotbar) || document.querySelector(SELECTORS.hotbar);
      state.elements.slots = root.querySelector(SELECTORS.slots) || document.querySelector(SELECTORS.slots);
      state.elements.status = root.querySelector(SELECTORS.status) || document.querySelector(SELECTORS.status);
      state.elements.slotElements = state.elements.slots
        ? toArray(state.elements.slots.querySelectorAll(SELECTORS.slot))
        : [];
      state.elements.creativeCards = toArray(document.querySelectorAll(SELECTORS.creativeCard));

      return true;
    } catch (err) {
      state.lastError = err;
      error("Element refresh failed.", err);
      return false;
    }
  }

  function findRootElement() {
    try {
      return (
        document.querySelector(SELECTORS.root) ||
        document.querySelector(SELECTORS.fallbackRoot)
      );
    } catch (err) {
      error("Root lookup failed.", err);
      return null;
    }
  }

  function readConfiguration(root) {
    try {
      var script = document.currentScript;
      var element = root || state.elements.root;

      state.userId = normalizeUserId(
        readFirstDefined(
          element && element.dataset ? element.dataset.userId : null,
          script ? script.getAttribute("data-user-id") : null,
          DEFAULT_USER_ID
        )
      );

      state.inventoryKey = normalizeInventoryKey(
        readFirstDefined(
          element && element.dataset ? element.dataset.inventoryKey : null,
          script ? script.getAttribute("data-inventory-key") : null,
          DEFAULT_INVENTORY_KEY
        )
      );

      state.slotCount = clampInteger(
        readFirstDefined(
          element && element.dataset ? element.dataset.slotCount : null,
          DEFAULT_SLOT_COUNT
        ),
        MIN_SLOT_INDEX,
        MAX_SLOT_INDEX,
        DEFAULT_SLOT_COUNT
      );

      state.activeSlotIndex = normalizeSlotIndex(
        readFirstDefined(
          element && element.dataset ? element.dataset.activeSlotIndex : null,
          MIN_SLOT_INDEX
        )
      );

      state.lastSelectedSlotIndex = normalizeSlotIndex(
        readFirstDefined(
          element && element.dataset ? element.dataset.lastSelectedSlotIndex : null,
          state.activeSlotIndex
        )
      );

      state.apiUrl = sanitizeSameOriginUrl(
        readFirstDefined(
          element && element.dataset ? element.dataset.userInventoryApiUrl : null,
          script ? script.getAttribute("data-user-inventory-api-url") : null,
          DEFAULT_API_URL
        ),
        DEFAULT_API_URL
      );

      state.selectUrl = sanitizeSameOriginUrl(
        readFirstDefined(
          element && element.dataset ? element.dataset.userInventorySelectUrl : null,
          script ? script.getAttribute("data-user-inventory-select-url") : null,
          DEFAULT_SELECT_URL
        ),
        DEFAULT_SELECT_URL
      );

      state.cacheEnabled = normalizeBoolean(
        element && element.dataset ? element.dataset.cacheEnabled : null,
        true
      );

      state.wheelNavigationEnabled = normalizeBoolean(
        element && element.dataset ? element.dataset.wheelNavigationEnabled : null,
        true
      );

      state.keyboardNavigationEnabled = normalizeBoolean(
        element && element.dataset ? element.dataset.keyboardNavigationEnabled : null,
        true
      );

      state.cardSelectionEnabled = normalizeBoolean(
        element && element.dataset ? element.dataset.cardSelectionEnabled : null,
        false
      );

      state.suspendDuringCreateEmbed = normalizeBoolean(
        element && element.dataset ? element.dataset.suspendDuringCreateEmbed : null,
        true
      );

      state.wheelNavigationScope = normalizeWheelScope(
        readFirstDefined(
          element && element.dataset ? element.dataset.wheelNavigationScope : null,
          "document"
        )
      );

      syncRootDataset();
    } catch (err) {
      warn("Configuration read failed. Defaults are used.", err);
    }
  }

  function readInitialDomState() {
    try {
      var slots = [];

      refreshElements();

      state.elements.slotElements.forEach(function (element) {
        slots.push(readSlotFromElement(element));
      });

      if (slots.length) {
        state.slots = normalizeSlots(slots);
      } else {
        state.slots = createEmptySlots(state.activeSlotIndex);
      }

      var selected = state.slots.filter(function (slot) {
        return Boolean(slot.selected);
      })[0];

      if (selected) {
        state.activeSlotIndex = normalizeSlotIndex(selected.slot_index);
        state.lastSelectedSlotIndex = state.activeSlotIndex;
      } else {
        state.slots = normalizeSlots(state.slots).map(function (slot) {
          slot.selected = normalizeSlotIndex(slot.slot_index) === state.activeSlotIndex;
          return slot;
        });
      }
    } catch (err) {
      warn("Initial DOM state read failed.", err);
      state.slots = createEmptySlots(state.activeSlotIndex);
    }
  }

  function readSlotFromElement(element) {
    try {
      var slotIndex = normalizeSlotIndex(getAttribute(element, "data-slot-index"));
      var label = cleanString(getAttribute(element, "data-slot-label")) || readSlotLabelFromElement(element);
      var quantity = normalizeQuantity(getAttribute(element, "data-slot-quantity"), 0);
      var empty = normalizeBoolean(getAttribute(element, "data-slot-empty"), true);

      return {
        id: cleanString(getAttribute(element, "data-id")) || null,
        state_id: cleanString(getAttribute(element, "data-state-id")) || null,
        user_id: state.userId,
        inventory_key: state.inventoryKey,
        slot_index: slotIndex,
        slot_key: cleanString(getAttribute(element, "data-slot-key")) || slotKey(slotIndex),

        item_db_id: cleanString(getAttribute(element, "data-item-db-id")),
        vplib_uid: cleanString(getAttribute(element, "data-vplib-uid")),
        family_id: cleanString(getAttribute(element, "data-family-id")),
        package_id: cleanString(getAttribute(element, "data-package-id")),
        variant_id: cleanString(getAttribute(element, "data-variant-id")),

        label: label,
        description: cleanString(getAttribute(element, "data-slot-description")) || cleanString(getAttribute(element, "title")),
        object_kind: cleanString(getAttribute(element, "data-object-kind")),

        domain: cleanString(getAttribute(element, "data-domain")),
        category: cleanString(getAttribute(element, "data-category")),
        subcategory: cleanString(getAttribute(element, "data-subcategory")),
        taxonomy_path: cleanString(getAttribute(element, "data-taxonomy-path")),

        quantity: quantity,
        empty: empty,
        selected: normalizeBoolean(getAttribute(element, "data-slot-selected"), false),
        active: normalizeBoolean(getAttribute(element, "data-slot-active"), true),
        locked: normalizeBoolean(getAttribute(element, "data-slot-locked"), false),
        pinned: normalizeBoolean(getAttribute(element, "data-slot-pinned"), false),

        source: cleanString(getAttribute(element, "data-source")) || "user",
        scope: cleanString(getAttribute(element, "data-scope")) || "editor",
        mode: cleanString(getAttribute(element, "data-mode")) || "creative",

        icon: {},
        preview: {},
        assets: [],
        variant: {},
        placement: {},
        payload: {},
        meta: {},
        metadata: {}
      };
    } catch (err) {
      return createEmptySlot(MIN_SLOT_INDEX, false);
    }
  }

  function ensureSlotElements() {
    try {
      refreshElements();

      if (!state.elements.slots) {
        warn("Slot container not found.");
        state.elements.slotElements = [];
        return;
      }

      var existing = toArray(state.elements.slots.querySelectorAll(SELECTORS.slot));
      var byIndex = Object.create(null);

      existing.forEach(function (element) {
        var index = normalizeSlotIndex(element.getAttribute("data-slot-index"));
        byIndex[index] = element;
      });

      for (var slotIndex = MIN_SLOT_INDEX; slotIndex <= state.slotCount; slotIndex += 1) {
        if (!byIndex[slotIndex]) {
          byIndex[slotIndex] = createSlotElement(slotIndex);
          state.elements.slots.appendChild(byIndex[slotIndex]);
        }
      }

      state.elements.slotElements = [];

      for (var index = MIN_SLOT_INDEX; index <= state.slotCount; index += 1) {
        if (byIndex[index]) {
          state.elements.slotElements.push(byIndex[index]);
        }
      }
    } catch (err) {
      error("Could not ensure slot elements.", err);
      state.elements.slotElements = [];
    }
  }

  function createSlotElement(slotIndex) {
    var article = document.createElement("article");

    article.id = "vp-user-slot-" + slotIndex;
    article.className = "vp-user-slot vp-user-slot--empty";
    article.setAttribute("role", "option");
    article.setAttribute("tabindex", "-1");
    article.setAttribute("aria-selected", "false");
    article.setAttribute("aria-label", "Inventar Slot " + slotIndex + ", leer");
    article.setAttribute("data-slot-index", String(slotIndex));
    article.setAttribute("data-slot-key", slotKey(slotIndex));
    article.setAttribute("data-slot-empty", "true");
    article.setAttribute("data-slot-selected", "false");
    article.setAttribute("data-slot-quantity", "0");
    article.setAttribute("data-slot-label", "");
    article.setAttribute("data-item-db-id", "");
    article.setAttribute("data-family-id", "");
    article.setAttribute("data-vplib-uid", "");
    article.setAttribute("data-package-id", "");
    article.setAttribute("data-variant-id", "");
    article.setAttribute("data-object-kind", "");
    article.setAttribute("data-domain", "");
    article.setAttribute("data-category", "");
    article.setAttribute("data-subcategory", "");
    article.setAttribute("data-taxonomy-path", "");
    article.setAttribute("data-source", "user");
    article.setAttribute("data-scope", "editor");
    article.setAttribute("data-mode", "creative");
    article.setAttribute("data-slot-locked", "false");
    article.setAttribute("data-slot-pinned", "false");

    var indexElement = document.createElement("div");
    indexElement.className = "vp-user-slot__index";
    indexElement.setAttribute("aria-hidden", "true");
    indexElement.textContent = String(slotIndex);

    var content = document.createElement("div");
    content.className = "vp-user-slot__content";

    var placeholder = document.createElement("span");
    placeholder.className = "vp-user-slot__placeholder";
    placeholder.textContent = "Leer";

    content.appendChild(placeholder);
    article.appendChild(indexElement);
    article.appendChild(content);

    return article;
  }

  function bindEvents() {
    bindSlotClickEvents();
    bindSlotDropEvents();

    if (state.eventsBound) {
      return;
    }

    state.eventsBound = true;

    bindWheelEvents();
    bindKeyboardEvents();
    bindExternalEvents();
    bindCreativeCardEvents();
    bindCreateEmbedEvents();
  }

  function bindSlotClickEvents() {
    try {
      refreshElements();

      state.elements.slotElements.forEach(function (element) {
        if (!element || element.getAttribute("data-user-inventory-click-bound") === "true") {
          return;
        }

        element.setAttribute("data-user-inventory-click-bound", "true");

        element.addEventListener("click", function (event) {
          try {
            event.preventDefault();

            if (isSlotLocked(element)) {
              setStatus("Dieser Slot ist gesperrt.", "error");
              dispatch("selection-blocked", {
                source: "click",
                slot_index: normalizeSlotIndex(element.getAttribute("data-slot-index")),
                reason: "slot-locked"
              });
              return;
            }

            selectSlot(element.getAttribute("data-slot-index"), {
              source: "click",
              persist: true,
              focus: true,
              immediate: true,
              forceDispatch: true
            });
          } catch (err) {
            state.lastError = err;
            error("Slot click handling failed.", err);
          }
        });
      });
    } catch (err) {
      error("Could not bind slot click events.", err);
    }
  }

  function clearDropTargets() {
    try {
      state.elements.slotElements.forEach(function (element) {
        element.classList.remove(CLASSES.dropTarget);
        element.removeAttribute("data-drop-target");
      });
    } catch (err) {
      // visual cleanup is best effort
    }
  }

  function readCreativeDragPayload(dataTransfer) {
    var raw = "";
    try {
      if (dataTransfer) {
        raw = dataTransfer.getData(CREATIVE_DRAG_MIME) || dataTransfer.getData("text/plain") || "";
      }
      if (raw) {
        var parsed = JSON.parse(raw);
        if (hasMeaningfulItemData(parsed)) return parsed;
      }
    } catch (err) {
      // The editor relay below is the cross-frame fallback.
    }
    return state.activeDragItem && hasMeaningfulItemData(state.activeDragItem)
      ? state.activeDragItem
      : null;
  }

  function bindSlotDropEvents() {
    try {
      refreshElements();
      state.elements.slotElements.forEach(function (element) {
        if (!element || element.getAttribute("data-user-inventory-drop-bound") === "true") return;
        element.setAttribute("data-user-inventory-drop-bound", "true");

        element.addEventListener("dragenter", function (event) {
          if (isSlotLocked(element) || !readCreativeDragPayload(event.dataTransfer)) return;
          event.preventDefault();
          element.classList.add(CLASSES.dropTarget);
          element.setAttribute("data-drop-target", "true");
        });

        element.addEventListener("dragover", function (event) {
          if (isSlotLocked(element) || !readCreativeDragPayload(event.dataTransfer)) return;
          event.preventDefault();
          if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
          clearDropTargets();
          element.classList.add(CLASSES.dropTarget);
          element.setAttribute("data-drop-target", "true");
        });

        element.addEventListener("dragleave", function (event) {
          if (event.relatedTarget && element.contains(event.relatedTarget)) return;
          element.classList.remove(CLASSES.dropTarget);
          element.removeAttribute("data-drop-target");
        });

        element.addEventListener("drop", function (event) {
          event.preventDefault();
          var item = readCreativeDragPayload(event.dataTransfer);
          var slotIndex = normalizeSlotIndex(element.getAttribute("data-slot-index"));
          clearDropTargets();
          state.activeDragItem = null;
          if (!item || isSlotLocked(element)) return;
          void setSlotItem(slotIndex, item, {
            select: true,
            persist: true,
            source: "creative-drag-drop"
          });
        });
      });

      document.addEventListener("dragend", clearDropTargets, { once: false });
    } catch (err) {
      error("Could not bind slot drop events.", err);
    }
  }
  function bindWheelEvents() {
    if (!state.wheelNavigationEnabled) {
      return;
    }

    try {
      document.addEventListener(
        "wheel",
        function (event) {
          try {
            handleWheel(event);
          } catch (err) {
            state.lastError = err;
            error("Wheel handling failed.", err);
          }
        },
        { passive: false }
      );
    } catch (err) {
      error("Could not bind wheel event.", err);
    }
  }

  function bindKeyboardEvents() {
    try {
      document.addEventListener("keydown", function (event) {
        try {
          handleKeydown(event);
        } catch (err) {
          state.lastError = err;
          error("Keyboard handling failed.", err);
        }
      });
    } catch (err) {
      error("Could not bind keyboard event.", err);
    }
  }

  function bindExternalEvents() {
  try {
    window.addEventListener("message", function (event) {
      try {
        if (!window.parent || event.source !== window.parent) {
          return;
        }

        var expectedOrigin = "";
        try {
          if (document.referrer) {
            expectedOrigin = new URL(document.referrer).origin;
          }
        } catch (originError) {
          expectedOrigin = "";
        }
        if (expectedOrigin && event.origin !== expectedOrigin) {
          return;
        }

        var message = event && event.data ? event.data : {};
        var detail = message.detail || {};

        if (
          message.source === "vectoplan-editor" &&
          (
            message.type === CREATIVE_POINTER_DRAG_START
            || message.type === CREATIVE_POINTER_DRAG_MOVE
            || message.type === CREATIVE_POINTER_DRAG_END
          )
        ) {
          var pointerItem = normalizeItemPayload(detail.item || detail.payload);
          var pointer = detail.pointer && typeof detail.pointer === "object" ? detail.pointer : {};
          var pointerX = Number(pointer.clientX);
          var pointerY = Number(pointer.clientY);
          var pointerInside = pointer.inside !== false && Number.isFinite(pointerX) && Number.isFinite(pointerY);
          var pointerTarget = pointerInside ? document.elementFromPoint(pointerX, pointerY) : null;
          var pointerSlot = pointerTarget && pointerTarget.closest ? pointerTarget.closest(SELECTORS.slot) : null;

          clearDropTargets();
          if (message.type !== CREATIVE_POINTER_DRAG_END) {
            state.activeDragItem = pointerItem;
            if (pointerSlot && !isSlotLocked(pointerSlot)) {
              pointerSlot.classList.add(CLASSES.dropTarget);
              pointerSlot.setAttribute("data-drop-target", "true");
            }
            return;
          }

          state.activeDragItem = null;
          if (detail.drop !== false && pointerItem && pointerSlot && !isSlotLocked(pointerSlot)) {
            var pointerSlotIndex = normalizeSlotIndex(pointerSlot.getAttribute("data-slot-index"));
            void setSlotItem(pointerSlotIndex, pointerItem, {
              select: true,
              persist: true,
              source: "creative-pointer-drag-drop"
            });
          }
          return;
        }

        if (
          message.source === "vectoplan-editor" &&
          (message.type === "vectoplan:creative-drag-start" || message.type === "vectoplan:creative-drag-end")
        ) {
          state.activeDragItem = message.type === "vectoplan:creative-drag-start"
            ? normalizeItemPayload(detail.item || detail.payload)
            : null;
          if (!state.activeDragItem) clearDropTargets();
          return;
        }

        if (
          message.source === "vectoplan-editor"
          && message.type === EVENTS.requestState
        ) {
          dispatch("state", {
            source: detail.source || "editor-host"
          });
          return;
        }

        if (
          message.type !== EVENTS.selectSlot ||
          message.source !== "vectoplan-editor"
        ) {
          return;
        }

        selectSlot(detail.slot_index || detail.slotIndex, {
          source: detail.source || "editor-host",
          persist: detail.persist !== false,
          focus: detail.focus === true,
          immediate: detail.immediate === true,
          forceDispatch: detail.forceDispatch !== false
        });      } catch (err) {
        error("Editor host select-slot message failed.", err);
      }
    });
  } catch (err) {
    // Cross-origin host integration is optional.
  }

    try {
      document.addEventListener(EVENTS.selectSlot, function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          selectSlot(detail.slot_index || detail.slotIndex, {
            source: detail.source || "external-event",
            persist: detail.persist !== false,
            focus: detail.focus === true,
            immediate: detail.immediate === true
          });
        } catch (err) {
          error("External select-slot event failed.", err);
        }
      });
    } catch (err) {
      // non-critical
    }

    try {
      document.addEventListener(EVENTS.setSlot, function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};
          var slotIndex = detail.slot_index || detail.slotIndex || state.activeSlotIndex;
          var item = detail.item || detail.payload || detail;

          setSlotItem(slotIndex, item, {
            select: detail.select !== false,
            persist: detail.persist !== false,
            source: detail.source || "external-event"
          });
        } catch (err) {
          error("External set-slot event failed.", err);
        }
      });
    } catch (err) {
      // non-critical
    }

    try {
      document.addEventListener(EVENTS.clearSlot, function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          clearSlotItem(detail.slot_index || detail.slotIndex || state.activeSlotIndex, {
            select: detail.select !== false,
            persist: detail.persist !== false,
            source: detail.source || "external-event"
          });
        } catch (err) {
          error("External clear-slot event failed.", err);
        }
      });
    } catch (err) {
      // non-critical
    }

    try {
      document.addEventListener(EVENTS.reload, function () {
        reload();
      });
    } catch (err) {
      // non-critical
    }

    try {
      document.addEventListener(EVENTS.requestState, function () {
        dispatch("state", {
          source: "request-state"
        });
      });
    } catch (err) {
      // non-critical
    }

    try {
      document.addEventListener(EVENTS.creativeItemPick, function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail.item || detail.payload) {
            setSlotItem(detail.slot_index || detail.slotIndex || state.activeSlotIndex, detail.item || detail.payload, {
              select: detail.select !== false,
              persist: detail.persist !== false,
              source: detail.source || "creative-item-pick"
            });
          }
        } catch (err) {
          error("Creative item pick handling failed.", err);
        }
      });
    } catch (err) {
      // non-critical
    }
  }

  function bindCreativeCardEvents() {
    if (!state.cardSelectionEnabled) {
      return;
    }

    try {
      document.addEventListener("click", function (event) {
        try {
          var card = closest(event.target, SELECTORS.creativeCard);

          if (!card) {
            return;
          }

          if (normalizeBoolean(card.getAttribute("data-disabled"), false)) {
            return;
          }

          setSlotItem(state.activeSlotIndex, itemPayloadFromCreativeCard(card), {
            select: true,
            persist: true,
            source: "creative-card-click"
          });
        } catch (err) {
          error("Creative card click failed.", err);
        }
      });
    } catch (err) {
      error("Could not bind creative card events.", err);
    }
  }

  function bindCreateEmbedEvents() {
    try {
      document.addEventListener(EVENTS.createEmbedOpen, function () {
        syncRootDataset();
      });

      document.addEventListener(EVENTS.createEmbedClose, function () {
        syncRootDataset();
      });
    } catch (err) {
      // non-critical
    }
  }

  function handleWheel(event) {
    if (!state.initialized || !state.wheelNavigationEnabled) {
      return;
    }

    if (state.suspendDuringCreateEmbed && isCreateEmbedActive()) {
      return;
    }

    if (shouldIgnoreInputEvent(event)) {
      return;
    }

    if (state.wheelNavigationScope === "hotbar" && !eventWithinHotbar(event)) {
      return;
    }

    var delta = event.deltaY || event.deltaX || 0;

    if (!delta) {
      return;
    }

    var now = Date.now();

    if (now < state.wheelLockedUntil) {
      tryPreventDefault(event);
      return;
    }

    state.wheelLockedUntil = now + WHEEL_THROTTLE_MS;
    tryPreventDefault(event);

    if (delta > 0) {
      nextSlot({
        source: "wheel",
        persist: true,
        focus: false,
        immediate: false
      });
    } else {
      previousSlot({
        source: "wheel",
        persist: true,
        focus: false,
        immediate: false
      });
    }
  }

  function postCreativeInventoryHostMessage(type) {
    if (!window.parent || window.parent === window) {
      return;
    }

    var targetOrigin = "*";

    try {
      if (document.referrer) {
        targetOrigin = new URL(document.referrer).origin;
      }
    } catch (originError) {
      targetOrigin = "*";
    }

    window.parent.postMessage({
      type: type,
      source: "vectoplan-library-inventory",
      version: MODULE_VERSION
    }, targetOrigin);
  }

  function handleKeydown(event) {
    if (event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }


    var key = event.key;
    var normalizedKey = cleanString(key).toLowerCase();
    var isCreativePage = document.body.classList.contains("vp-creative-inventar-page");
    var eventTarget = event.target;
    var targetTagName = eventTarget && eventTarget.tagName
      ? cleanString(eventTarget.tagName).toUpperCase()
      : "";
    if ((eventTarget && eventTarget.isContentEditable) || ["INPUT", "TEXTAREA", "SELECT"].indexOf(targetTagName) >= 0) {
      return;
    }

    var togglesCreativeInventory = normalizedKey === "tab"
      || event.code === "Tab"
      || normalizedKey === "i"
      || event.code === "KeyI";

    if (togglesCreativeInventory && !event.repeat) {
      tryPreventDefault(event);
      if (typeof event.stopImmediatePropagation === "function") event.stopImmediatePropagation();
      postCreativeInventoryHostMessage(
        isCreativePage
          ? "vectoplan:creative-inventory-close"
          : "vectoplan:creative-inventory-toggle"
      );
      return;
    }

    if (normalizedKey === "escape" && isCreativePage) {
      tryPreventDefault(event);
      postCreativeInventoryHostMessage("vectoplan:creative-inventory-close");
      return;
    }


    if (shouldIgnoreInputEvent(event)) {
      return;
    }
    if (!state.initialized || !state.keyboardNavigationEnabled) {
      return;
    }

    if (state.suspendDuringCreateEmbed && isCreateEmbedActive()) {
      return;
    }

    if (/^[1-9]$/.test(key)) {
      tryPreventDefault(event);
      selectSlot(parseInt(key, 10), {
        source: "keyboard-number",
        persist: true,
        focus: true,
        immediate: true,
        forceDispatch: true
      });
      return;
    }

    if (key === "ArrowRight" || key === "PageDown") {
      tryPreventDefault(event);
      nextSlot({
        source: "keyboard-next",
        persist: true,
        focus: true,
        immediate: true
      });
      return;
    }

    if (key === "ArrowLeft" || key === "PageUp") {
      tryPreventDefault(event);
      previousSlot({
        source: "keyboard-previous",
        persist: true,
        focus: true,
        immediate: true
      });
      return;
    }

    if (key === "Home") {
      tryPreventDefault(event);
      selectSlot(MIN_SLOT_INDEX, {
        source: "keyboard-home",
        persist: true,
        focus: true,
        immediate: true
      });
      return;
    }

    if (key === "End") {
      tryPreventDefault(event);
      selectSlot(state.slotCount, {
        source: "keyboard-end",
        persist: true,
        focus: true,
        immediate: true
      });
    }
  }

  function shouldIgnoreInputEvent(event) {
    try {
      var target = event.target;

      if (!target) {
        return false;
      }

      var tagName = String(target.tagName || "").toLowerCase();

      if (tagName === "input" || tagName === "textarea" || tagName === "select" || tagName === "button") {
        return true;
      }

      if (target.isContentEditable) {
        return true;
      }

      if (typeof target.closest === "function") {
        if (target.closest("input, textarea, select, button, [contenteditable='true']")) {
          return true;
        }
      }

      return false;
    } catch (err) {
      return false;
    }
  }

  function eventWithinHotbar(event) {
    try {
      return Boolean(
        event &&
        event.target &&
        state.elements.hotbar &&
        state.elements.hotbar.contains(event.target)
      );
    } catch (err) {
      return false;
    }
  }

  function isCreateEmbedActive() {
    try {
      var root = state.elements.root;

      if (root && root.dataset && root.dataset.createEmbedActive === "true") {
        return true;
      }

      var createRoot = root && root.closest
        ? root.closest(SELECTORS.createEmbedRoot)
        : document.querySelector(SELECTORS.createEmbedRoot);

      return Boolean(createRoot && createRoot.dataset && createRoot.dataset.createEmbedActive === "true");
    } catch (err) {
      return false;
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

  function loadInventory() {
    if (!state.apiUrl) {
      return Promise.resolve(false);
    }

    if (typeof window.fetch !== "function") {
      setStatus("Fetch API nicht verfügbar. Lokaler Inventar-Cache wird verwendet.", "error");
      return Promise.resolve(false);
    }

    state.loading = true;
    state.lastError = null;
    syncRootDataset();
    setStatus("User-Inventar wird geladen ...", "loading");

    var url = appendQuery(state.apiUrl, {
      user_id: state.userId,
      inventory_key: state.inventoryKey
    });

    return requestJson(url, {
      method: "GET",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "X-VECTOPLAN-User-Inventory": MODULE_VERSION
      },
      cache: "no-store"
    })
      .then(function (result) {
        if (!result.response.ok || result.payload.ok === false) {
          throw new Error(extractMessage(result.payload) || ("Inventar-API Fehler: HTTP " + result.response.status));
        }

        applyInventoryPayload(result.payload, {
          source: "api",
          persist: false,
          render: true,
          preserveExistingSlots: true
        });

        state.loadedFromApi = true;
        state.loading = false;
        state.lastError = null;

        writeCache(inventoryPayloadForCache());
        setStatus("", "ready");
        syncRootDataset();
        dispatch("load", { source: "api" });

        return true;
      })
      .catch(function (err) {
        state.loading = false;
        state.lastError = err;

        var cached = readCache();

        if (cached) {
          applyInventoryPayload(cached, {
            source: "cache-after-api-error",
            persist: false,
            render: true,
            preserveExistingSlots: true
          });
          setStatus("Inventar-API nicht erreichbar. Cache wird verwendet.", "error");
        } else {
          setStatus("User-Inventar konnte nicht geladen werden.", "error");
        }

        syncRootDataset();

        error("Inventory load failed.", err);
        dispatch("error", {
          operation: "load",
          error: stringifyError(err)
        });

        return false;
      });
  }

  function selectSlot(slotIndex, options) {
    var selectionStartedAtMs = performance.now();
    var selectionStartedAtEpochMs = Date.now();
    var normalizedOptions = options || {};
    var normalizedSlotIndex = normalizeSlotIndex(slotIndex);
    var targetSlot = getSlot(normalizedSlotIndex);
    var selectionChanged = normalizedSlotIndex !== state.activeSlotIndex;
    var shouldDispatchSelection = selectionChanged || normalizedOptions.forceDispatch === true;

    if (targetSlot.locked) {
      setStatus("Dieser Slot ist gesperrt.", "error");
      dispatch("selection-blocked", {
        source: normalizedOptions.source || "unknown",
        slot_index: normalizedSlotIndex,
        reason: "slot-locked"
      });
      return targetSlot;
    }

    state.activeSlotIndex = normalizedSlotIndex;
    state.lastSelectedSlotIndex = normalizedSlotIndex;

    // Slots are normalized when the inventory payload is loaded. Re-running
    // the full normalizer here cloned large nested VPLIB payload/metadata
    // objects several times per wheel tick. Keep selection as a shallow
    // nine-slot update instead.
    var selectionStateStartedAtMs = performance.now();
    state.slots = (Array.isArray(state.slots) ? state.slots : normalizeSlots(state.slots))
      .map(function (slot) {
        var selected = normalizeSlotIndex(slot.slot_index) === normalizedSlotIndex;
        return slot.selected === selected
          ? slot
          : Object.assign({}, slot, { selected: selected });
      });
    var selectionStateDurationMs = performance.now() - selectionStateStartedAtMs;

    var selectionRenderStartedAtMs = performance.now();
    renderSelectionState(selectionChanged && normalizedOptions.announce !== false);
    var selectionRenderDurationMs = performance.now() - selectionRenderStartedAtMs;

    if (normalizedOptions.focus) {
      focusSlot(normalizedSlotIndex);
    }

    if (shouldDispatchSelection) {
      dispatch("selection-change", {
        source: normalizedOptions.source || "unknown",
        slot_index: normalizedSlotIndex,
        slot: compactSelectionSlot(getSlot(normalizedSlotIndex)),
        selection_started_at_epoch_ms: selectionStartedAtEpochMs,
        selection_before_dispatch_ms: performance.now() - selectionStartedAtMs,
        selection_state_ms: selectionStateDurationMs,
        selection_render_ms: selectionRenderDurationMs
      });
    }

    if (selectionChanged && normalizedOptions.persist !== false) {
      if (normalizedOptions.immediate) {
        persistSelection(normalizedSlotIndex);
      } else {
        schedulePersistSelection(normalizedSlotIndex);
      }
    }

    return getSlot(normalizedSlotIndex);
  }

  function nextSlot(options) {
    var next = state.activeSlotIndex + 1;

    if (next > state.slotCount) {
      next = MIN_SLOT_INDEX;
    }

    return selectSlot(next, options || {});
  }

  function previousSlot(options) {
    var previous = state.activeSlotIndex - 1;

    if (previous < MIN_SLOT_INDEX) {
      previous = state.slotCount;
    }

    return selectSlot(previous, options || {});
  }

  function schedulePersistSelection(slotIndex) {
    try {
      if (state.pendingSaveTimer) {
        window.clearTimeout(state.pendingSaveTimer);
      }

      state.pendingSaveTimer = window.setTimeout(function () {
        state.pendingSaveTimer = null;
        persistSelection(slotIndex);
      }, SAVE_DEBOUNCE_MS);
    } catch (err) {
      persistSelection(slotIndex);
    }
  }

  function scheduleCacheWrite() {
    try {
      if (state.pendingCacheTimer) {
        window.clearTimeout(state.pendingCacheTimer);
      }

      state.pendingCacheTimer = window.setTimeout(function () {
        state.pendingCacheTimer = null;
        writeCache(inventoryPayloadForCache());
      }, CACHE_WRITE_DEBOUNCE_MS);
    } catch (err) {
      // Cache is optional. Selection must stay instant when browser storage is
      // unavailable or temporarily blocked.
    }
  }

  function persistSelection(slotIndex) {
    var normalizedSlotIndex = normalizeSlotIndex(slotIndex);

    if (typeof window.fetch !== "function") {
      return Promise.resolve(false);
    }

    state.saving = true;
    syncRootDataset();

    return requestJson(state.selectUrl || DEFAULT_SELECT_URL, {
      method: "PATCH",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-VECTOPLAN-User-Inventory": MODULE_VERSION
      },
      cache: "no-store",
      body: JSON.stringify({
        user_id: state.userId,
        inventory_key: state.inventoryKey,
        slot_index: normalizedSlotIndex
      })
    })
      .then(function (result) {
        if (!result.response.ok || result.payload.ok === false) {
          throw new Error(extractMessage(result.payload) || ("Slot-Auswahl konnte nicht gespeichert werden: HTTP " + result.response.status));
        }

        applyInventoryPayload(result.payload, {
          source: "select-api",
          persist: false,
          render: false,
          preserveExistingSlots: true
        });

        state.saving = false;
        setStatus("", "ready");
        syncRootDataset();

        dispatch("selection-persisted", {
          operation: "select-slot",
          slot_index: normalizedSlotIndex
        });

        return true;
      })
      .catch(function (err) {
        state.saving = false;
        state.lastError = err;
        setSlotError(normalizedSlotIndex, true);
        setStatus("Slot-Auswahl konnte nicht gespeichert werden.", "error");
        syncRootDataset();

        window.setTimeout(function () {
          setSlotError(normalizedSlotIndex, false);
        }, STATUS_HIDE_DELAY_MS);

        error("Selection persist failed.", err);
        dispatch("error", {
          operation: "select-slot",
          slot_index: normalizedSlotIndex,
          error: stringifyError(err)
        });

        return false;
      });
  }

  function setSlotItem(slotIndex, itemPayload, options) {
    var normalizedSlotIndex = normalizeSlotIndex(slotIndex);
    var normalizedOptions = options || {};
    var item = normalizeItemPayload(itemPayload);

    if (getSlot(normalizedSlotIndex).locked) {
      setStatus("Dieser Slot ist gesperrt.", "error");
      dispatch("selection-blocked", {
        source: normalizedOptions.source || "set-slot",
        slot_index: normalizedSlotIndex,
        reason: "slot-locked"
      });
      return Promise.resolve(false);
    }

    updateLocalSlot(normalizedSlotIndex, item, {
      selected: normalizedOptions.select !== false
    });

    if (normalizedOptions.select !== false) {
      selectSlot(normalizedSlotIndex, {
        source: normalizedOptions.source || "set-slot-local",
        persist: false,
        focus: false,
        forceDispatch: true
      });
    } else {
      render();
    }

    writeCache(inventoryPayloadForCache());

    if (normalizedOptions.persist === false || typeof window.fetch !== "function") {
      return Promise.resolve(false);
    }

    state.saving = true;
    syncRootDataset();
    setSlotSaving(normalizedSlotIndex, true);
    setStatus("Slot " + normalizedSlotIndex + " wird aktualisiert ...", "saving");

    return requestJson(joinUrl(state.apiUrl, "/slots/" + normalizedSlotIndex), {
      method: "PUT",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-VECTOPLAN-User-Inventory": MODULE_VERSION
      },
      cache: "no-store",
      body: JSON.stringify({
        user_id: state.userId,
        inventory_key: state.inventoryKey,
        item: item,
        select: normalizedOptions.select !== false
      })
    })
      .then(function (result) {
        if (!result.response.ok || result.payload.ok === false) {
          throw new Error(extractMessage(result.payload) || "Slot konnte nicht gespeichert werden.");
        }

        applyInventoryPayload(result.payload, {
          source: "set-slot-api",
          persist: false,
          render: true,
          preserveExistingSlots: true
        });

        state.saving = false;
        setSlotSaving(normalizedSlotIndex, false);
        setStatus("", "ready");
        writeCache(inventoryPayloadForCache());
        syncRootDataset();

        dispatch("save", {
          operation: "set-slot",
          slot_index: normalizedSlotIndex
        });

        return true;
      })
      .catch(function (err) {
        state.saving = false;
        state.lastError = err;
        setSlotSaving(normalizedSlotIndex, false);
        setSlotError(normalizedSlotIndex, true);
        setStatus("Slot konnte nicht gespeichert werden.", "error");
        syncRootDataset();

        window.setTimeout(function () {
          setSlotError(normalizedSlotIndex, false);
        }, STATUS_HIDE_DELAY_MS);

        error("Set slot failed.", err);
        dispatch("error", {
          operation: "set-slot",
          slot_index: normalizedSlotIndex,
          error: stringifyError(err)
        });

        return false;
      });
  }

  function clearSlotItem(slotIndex, options) {
    var normalizedSlotIndex = normalizeSlotIndex(slotIndex);
    var normalizedOptions = options || {};

    if (getSlot(normalizedSlotIndex).locked) {
      setStatus("Dieser Slot ist gesperrt.", "error");
      dispatch("selection-blocked", {
        source: normalizedOptions.source || "clear-slot",
        slot_index: normalizedSlotIndex,
        reason: "slot-locked"
      });
      return Promise.resolve(false);
    }

    updateLocalSlot(normalizedSlotIndex, {}, {
      selected: normalizedOptions.select !== false,
      clear: true
    });

    if (normalizedOptions.select !== false) {
      selectSlot(normalizedSlotIndex, {
        source: normalizedOptions.source || "clear-slot-local",
        persist: false,
        focus: false
      });
    } else {
      render();
    }

    writeCache(inventoryPayloadForCache());

    if (normalizedOptions.persist === false || typeof window.fetch !== "function") {
      return Promise.resolve(false);
    }

    state.saving = true;
    syncRootDataset();
    setSlotSaving(normalizedSlotIndex, true);
    setStatus("Slot " + normalizedSlotIndex + " wird geleert ...", "saving");

    return requestJson(joinUrl(state.apiUrl, "/slots/" + normalizedSlotIndex), {
      method: "DELETE",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-VECTOPLAN-User-Inventory": MODULE_VERSION
      },
      cache: "no-store",
      body: JSON.stringify({
        user_id: state.userId,
        inventory_key: state.inventoryKey,
        select: normalizedOptions.select !== false
      })
    })
      .then(function (result) {
        if (!result.response.ok || result.payload.ok === false) {
          throw new Error(extractMessage(result.payload) || "Slot konnte nicht geleert werden.");
        }

        applyInventoryPayload(result.payload, {
          source: "clear-slot-api",
          persist: false,
          render: true,
          preserveExistingSlots: true
        });

        state.saving = false;
        setSlotSaving(normalizedSlotIndex, false);
        setStatus("", "ready");
        writeCache(inventoryPayloadForCache());
        syncRootDataset();

        dispatch("save", {
          operation: "clear-slot",
          slot_index: normalizedSlotIndex
        });

        return true;
      })
      .catch(function (err) {
        state.saving = false;
        state.lastError = err;
        setSlotSaving(normalizedSlotIndex, false);
        setSlotError(normalizedSlotIndex, true);
        setStatus("Slot konnte nicht geleert werden.", "error");
        syncRootDataset();

        window.setTimeout(function () {
          setSlotError(normalizedSlotIndex, false);
        }, STATUS_HIDE_DELAY_MS);

        error("Clear slot failed.", err);
        dispatch("error", {
          operation: "clear-slot",
          slot_index: normalizedSlotIndex,
          error: stringifyError(err)
        });

        return false;
      });
  }

  function updateLocalSlot(slotIndex, item, options) {
    var normalizedSlotIndex = normalizeSlotIndex(slotIndex);
    var normalizedOptions = options || {};
    var normalizedItem = normalizeItemPayload(item);

    state.slots = normalizeSlots(state.slots).map(function (slot) {
      if (normalizeSlotIndex(slot.slot_index) !== normalizedSlotIndex) {
        if (normalizedOptions.selected) {
          slot.selected = false;
        }

        return slot;
      }

      if (normalizedOptions.clear || !hasMeaningfulItemData(normalizedItem)) {
        return createEmptySlot(normalizedSlotIndex, Boolean(normalizedOptions.selected));
      }

      return {
        id: slot.id || null,
        state_id: slot.state_id || null,
        user_id: state.userId,
        inventory_key: state.inventoryKey,
        slot_index: normalizedSlotIndex,
        slot_key: slotKey(normalizedSlotIndex),

        item_db_id: normalizedItem.item_db_id || normalizedItem.id || null,
        vplib_uid: normalizedItem.vplib_uid || "",
        family_id: normalizedItem.family_id || "",
        package_id: normalizedItem.package_id || "",
        variant_id: normalizedItem.variant_id || "",

        label: normalizedItem.label || normalizedItem.name || normalizedItem.title || "Item",
        description: normalizedItem.description || normalizedItem.text || "",
        object_kind: normalizedItem.object_kind || normalizedItem.kind || "",
        icon_kind: normalizedItem.icon_kind || normalizedItem.iconKind || "",

        domain: normalizedItem.domain || "",
        category: normalizedItem.category || "",
        subcategory: normalizedItem.subcategory || "",
        taxonomy_path: normalizedItem.taxonomy_path || "",

        quantity: normalizeQuantity(normalizedItem.quantity, 1),
        empty: false,
        selected: Boolean(normalizedOptions.selected),
        active: true,
        locked: normalizeBoolean(normalizedItem.locked, false),
        pinned: normalizeBoolean(normalizedItem.pinned, false),

        source: cleanString(normalizedItem.source) || "user",
        scope: cleanString(normalizedItem.scope) || "editor",
        mode: cleanString(normalizedItem.mode) || "creative",

        icon: normalizeIcon(normalizedItem.icon || normalizedItem.icon_text || normalizedItem.iconText),
        preview: normalizeObject(normalizedItem.preview),
        assets: normalizeAssets(normalizedItem.assets),
        variant: normalizeObject(normalizedItem.variant),
        placement: normalizeObject(normalizedItem.placement),
        payload: normalizedItem,
        meta: normalizeObject(normalizedItem.meta),
        metadata: normalizeObject(normalizedItem.metadata)
      };
    });
  }

  function applyInventoryPayload(payload, options) {
    var normalizedOptions = options || {};
    var data = unwrapInventoryPayload(payload);
    var hasSlots = payloadHasSlots(data);

    state.userId = normalizeUserId(data.user_id || data.userId || state.userId);
    state.inventoryKey = normalizeInventoryKey(data.inventory_key || data.inventoryKey || state.inventoryKey);
    state.activeSlotIndex = normalizeSlotIndex(data.active_slot_index || data.activeSlotIndex || data.last_selected_slot_index || data.lastSelectedSlotIndex || state.activeSlotIndex);
    state.lastSelectedSlotIndex = normalizeSlotIndex(data.last_selected_slot_index || data.lastSelectedSlotIndex || state.activeSlotIndex);

    if (hasSlots) {
      state.slots = normalizeSlots(data.slots);
    } else if (normalizedOptions.preserveExistingSlots !== false) {
      state.slots = normalizeSlots(state.slots);
    } else {
      state.slots = createEmptySlots(state.activeSlotIndex);
    }

    state.slots = state.slots.map(function (slot) {
      slot.selected = normalizeSlotIndex(slot.slot_index) === state.activeSlotIndex;
      return slot;
    });

    if (normalizedOptions.render !== false) {
      render();
    }

    if (normalizedOptions.persist) {
      writeCache(inventoryPayloadForCache());
    }
  }

  function unwrapInventoryPayload(payload) {
    var raw = normalizeObject(payload);

    if (raw.data && typeof raw.data === "object") {
      return normalizeObject(raw.data);
    }

    if (raw.payload && typeof raw.payload === "object") {
      return normalizeObject(raw.payload);
    }

    if (raw.result && typeof raw.result === "object") {
      return normalizeObject(raw.result);
    }

    return raw;
  }

  function payloadHasSlots(data) {
    try {
      return Boolean(data && Object.prototype.hasOwnProperty.call(data, "slots"));
    } catch (err) {
      return false;
    }
  }

  function render() {
    try {
      syncRootDataset();
      ensureSlotElements();

      var slotsByIndex = Object.create(null);

      normalizeSlots(state.slots).forEach(function (slot) {
        slotsByIndex[normalizeSlotIndex(slot.slot_index)] = slot;
      });

      state.elements.slotElements.forEach(function (element) {
        var slotIndex = normalizeSlotIndex(element.getAttribute("data-slot-index"));
        var slot = slotsByIndex[slotIndex] || createEmptySlot(slotIndex, slotIndex === state.activeSlotIndex);

        renderSlotElement(element, slot);
      });
    } catch (err) {
      state.lastError = err;
      error("Render failed.", err);
    }
  }

  /**
   * Selection changes are the hottest inventory path. Rebuilding all nine
   * slot contents here recreated every cube face and texture preloader for a
   * single mouse-wheel notch. Keep the existing DOM and only update the
   * selection attributes/classes that actually changed.
   */
  function renderSelectionState(announceSelection) {
    try {
      syncRootDataset();

      var selectedElement = null;

      state.elements.slotElements.forEach(function (element) {
        var slotIndex = normalizeSlotIndex(element.getAttribute("data-slot-index"));
        var selected = slotIndex === state.activeSlotIndex;

        element.classList.toggle(CLASSES.active, selected);
        element.classList.toggle(CLASSES.selected, selected);
        element.classList.remove(CLASSES.selectionAnnounced);
        element.setAttribute("tabindex", selected ? "0" : "-1");
        element.setAttribute("aria-selected", selected ? "true" : "false");
        element.setAttribute("data-slot-selected", selected ? "true" : "false");

        if (selected) {
          selectedElement = element;
        }
      });

      if (state.selectionLabelTimer) {
        window.clearTimeout(state.selectionLabelTimer);
        state.selectionLabelTimer = null;
      }

      if (
        announceSelection
        && selectedElement
        && selectedElement.getAttribute("data-slot-empty") !== "true"
      ) {
        selectedElement.classList.add(CLASSES.selectionAnnounced);
        state.selectionLabelTimer = window.setTimeout(function () {
          state.selectionLabelTimer = null;
          if (selectedElement && selectedElement.classList) {
            selectedElement.classList.remove(CLASSES.selectionAnnounced);
          }
        }, SELECTION_LABEL_HIDE_DELAY_MS);
      }
    } catch (err) {
      state.lastError = err;
      error("Selection render failed.", err);
    }
  }

  function worldEditToolIdFromSlot(slotValue) {
    var slot = normalizeObject(slotValue);
    var payload = normalizeObject(slot.payload);
    var metadata = normalizeObject(slot.metadata || payload.metadata);
    var placement = normalizeObject(slot.placement || payload.placement);
    var objectKind = cleanString(readFirstDefined(
      slot.object_kind,
      slot.objectKind,
      payload.object_kind,
      payload.objectKind
    )).toLowerCase().replace(/-/g, "_");
    var domain = cleanString(readFirstDefined(slot.domain, payload.domain)).toLowerCase().replace(/_/g, "-");
    var familyId = cleanString(readFirstDefined(slot.family_id, slot.familyId, payload.family_id, payload.familyId)).toLowerCase();
    var vplibUid = cleanString(readFirstDefined(slot.vplib_uid, slot.vplibUid, payload.vplib_uid, payload.vplibUid)).toLowerCase();
    var packageId = cleanString(readFirstDefined(slot.package_id, slot.packageId, payload.package_id, payload.packageId)).toLowerCase();
    var isWorldEdit = objectKind === "world_edit_tool"
      || domain === "world-edit"
      || familyId.indexOf("world-edit.") === 0
      || vplibUid.indexOf("vectoplan.world-edit.") === 0
      || packageId === "vectoplan.world-edit";
    if (!isWorldEdit) return "";

    var candidates = [
      slot.world_edit_tool,
      slot.worldEditTool,
      payload.world_edit_tool,
      payload.worldEditTool,
      metadata.world_edit_tool,
      metadata.worldEditTool,
      placement.world_edit_tool,
      placement.worldEditTool,
      placement.toolId,
      slot.variant_id,
      slot.variantId,
      payload.variant_id,
      payload.variantId,
      familyId,
      vplibUid
    ];
    var knownTools = ["selection", "room", "paint", "sculpt", "parcel", "parcel-grid", "ruler-laser", "copy-transform"];
    for (var index = 0; index < candidates.length; index += 1) {
      var candidate = cleanString(candidates[index]).toLowerCase().replace(/_/g, "-");
      ["vectoplan.world-edit.", "world-edit.", "world-edit-"].some(function (prefix) {
        if (candidate.indexOf(prefix) !== 0) return false;
        candidate = candidate.slice(prefix.length);
        return true;
      });
      if (knownTools.indexOf(candidate) >= 0) return candidate;
    }
    return "";
  }

  function renderSlotElement(element, slot) {
    try {
      var slotIndex = normalizeSlotIndex(slot.slot_index);
      var selected = slotIndex === state.activeSlotIndex;
      var empty = inferSlotEmpty(slot);
      var locked = normalizeBoolean(slot.locked, false);
      var pinned = normalizeBoolean(slot.pinned, false);
      var worldEditToolId = worldEditToolIdFromSlot(slot);

      element.classList.toggle(CLASSES.active, selected);
      element.classList.toggle(CLASSES.selected, selected);
      element.classList.toggle(CLASSES.empty, empty);
      element.classList.toggle(CLASSES.filled, !empty);
      element.classList.toggle(CLASSES.locked, locked);
      element.classList.toggle(CLASSES.pinned, pinned);
      element.classList.toggle("vp-user-slot--editor-tool", Boolean(worldEditToolId));

      element.setAttribute("role", "option");
      element.setAttribute("tabindex", selected ? "0" : "-1");
      element.setAttribute("aria-selected", selected ? "true" : "false");
      element.setAttribute("data-slot-selected", selected ? "true" : "false");
      element.setAttribute("data-slot-empty", empty ? "true" : "false");
      element.setAttribute("data-slot-key", slot.slot_key || slotKey(slotIndex));
      element.setAttribute("data-slot-label", slot.label || "");
      element.setAttribute("data-slot-quantity", String(normalizeQuantity(slot.quantity, 0)));
      element.setAttribute("data-item-db-id", slot.item_db_id || "");
      element.setAttribute("data-family-id", slot.family_id || "");
      element.setAttribute("data-vplib-uid", slot.vplib_uid || "");
      element.setAttribute("data-package-id", slot.package_id || "");
      element.setAttribute("data-variant-id", slot.variant_id || "");
      element.setAttribute("data-object-kind", slot.object_kind || "");
      element.setAttribute("data-domain", slot.domain || "");
      element.setAttribute("data-category", slot.category || "");
      element.setAttribute("data-subcategory", slot.subcategory || "");
      element.setAttribute("data-taxonomy-path", slot.taxonomy_path || "");
      element.setAttribute("data-source", slot.source || "user");
      element.setAttribute("data-scope", slot.scope || "editor");
      element.setAttribute("data-mode", slot.mode || "creative");
      element.setAttribute("data-slot-locked", locked ? "true" : "false");
      element.setAttribute("data-slot-pinned", pinned ? "true" : "false");
      if (worldEditToolId) {
        element.setAttribute("data-world-edit-tool-id", worldEditToolId);
      } else {
        element.removeAttribute("data-world-edit-tool-id");
      }

      if (slot.description) {
        element.setAttribute("title", slot.description);
      } else {
        element.removeAttribute("title");
      }

      element.setAttribute(
        "aria-label",
        buildSlotAriaLabel(slot, {
          selected: selected,
          empty: empty,
          locked: locked,
          pinned: pinned
        })
      );

      renderSlotContent(element, slot, {
        selected: selected,
        empty: empty
      });
    } catch (err) {
      error("Slot render failed.", err);
    }
  }

  function renderSlotContent(element, slot, meta) {
    var content = element.querySelector(".vp-user-slot__content");

    if (!content) {
      content = document.createElement("div");
      content.className = "vp-user-slot__content";
      element.appendChild(content);
    }

    clearElement(content);

    if (meta.empty) {
      var placeholder = document.createElement("span");
      placeholder.className = "vp-user-slot__placeholder";
      placeholder.textContent = "Leer";
      content.appendChild(placeholder);
      removeQuantityElement(element);
      return;
    }

    var icon = document.createElement("span");
    icon.className = "vp-user-slot__icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = itemIconText(slot);

    var worldEditToolId = worldEditToolIdFromSlot(slot);
    var previewUrl = slotPreviewUrl(slot);
    var previewColor = slotPreviewColor(slot);
    var iconSystem = window.VectoplanLibraryIcons;
    var libraryIconKind = iconSystem && typeof iconSystem.kind === "function"
      ? iconSystem.kind(slot)
      : "block";
    element.setAttribute("data-library-icon-kind", libraryIconKind);
    if (worldEditToolId) {
      element.setAttribute("data-has-texture", "false");
      if (iconSystem && typeof iconSystem.createTool === "function") {
        icon.hidden = true;
        content.appendChild(iconSystem.createTool(worldEditToolId, {
          className: "vp-user-slot__tool-icon"
        }));
      } else {
        icon.hidden = false;
        content.appendChild(icon);
      }
    } else if (libraryIconKind !== "block" && iconSystem && typeof iconSystem.create === "function") {
      element.setAttribute("data-has-texture", "false");
      icon.hidden = true;
      content.appendChild(iconSystem.create(slot, {
        className: "vp-user-slot__library-icon"
      }));
    } else if (previewUrl) {
      var cube = createTextureCube(previewUrl, "vp-user-slot__cube", previewColor);
      var preloader = new Image();
      element.setAttribute("data-has-texture", "loading");
      icon.classList.add("vp-user-slot__icon--fallback");
      icon.hidden = true;
      preloader.onload = function () {
        element.setAttribute("data-has-texture", "true");
        cube.classList.add("is-loaded");
      };
      preloader.onerror = function () {
        element.setAttribute("data-has-texture", "false");
        toArray(cube.querySelectorAll(".vp-inventory-cube__face")).forEach(function (face) {
          face.style.backgroundImage = "none";
        });
      };
      preloader.src = previewUrl;
      content.appendChild(cube);
    } else {
      element.setAttribute("data-has-texture", "false");
      icon.hidden = true;
      content.appendChild(
        iconSystem && typeof iconSystem.create === "function"
          ? iconSystem.create(slot, { className: "vp-user-slot__library-icon" })
          : createTextureCube("", "vp-user-slot__cube", previewColor)
      );
    }

    var label = document.createElement("span");
    label.className = "vp-user-slot__label";
    label.textContent = slot.label || slot.family_id || slot.vplib_uid || "Item";

    content.appendChild(label);

    renderQuantityElement(element, slot);
  }

  function createTextureCube(textureUrl, extraClassName, fallbackColor) {
    var cube = document.createElement("span");
    cube.className = "vp-inventory-cube " + (extraClassName || "");
    cube.setAttribute("aria-hidden", "true");

    ["front", "right", "top"].forEach(function (faceName) {
      var face = document.createElement("span");
      face.className = "vp-inventory-cube__face vp-inventory-cube__face--" + faceName;
      face.style.backgroundColor = fallbackColor || "#8ea2b5";
      if (textureUrl) {
        face.style.backgroundImage = "url(\"" + textureUrl.replace(/[\"\\]/g, "\\$&") + "\")";
      }
      cube.appendChild(face);
    });

    return cube;
  }

  function safePreviewUrl(value) {
    var raw = cleanString(value);
    if (!raw) return "";
    try {
      var parsed = new URL(raw, window.location.href);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      return parsed.href;
    } catch (err) {
      return "";
    }
  }

  function firstPreviewUrlFromAssets(value) {
    var candidates = [];
    if (Array.isArray(value)) {
      candidates = value;
    } else if (value && typeof value === "object") {
      candidates = [value].concat(Array.isArray(value.items) ? value.items : []);
    }

    for (var index = 0; index < candidates.length; index += 1) {
      var asset = normalizeObject(candidates[index]);
      var payload = normalizeObject(asset.payload);
      var url = safePreviewUrl(readFirstDefined(
        asset.previewUrl,
        asset.preview_url,
        asset.textureUrl,
        asset.texture_url,
        asset.iconUrl,
        asset.icon_url,
        asset.uri,
        asset.url,
        payload.previewUrl,
        payload.textureUrl,
        payload.uri,
        payload.url
      ));
      if (url) return url;
    }
    return "";
  }

  function slotPreviewUrl(slot) {
    var payload = normalizeObject(slot.payload);
    var metadata = normalizeObject(slot.metadata);
    var placement = normalizeObject(slot.placement);
    var appearance = normalizeObject(readFirstDefined(
      slot.appearance,
      payload.appearance,
      metadata.appearance,
      placement.appearance
    ));
    var icon = normalizeIcon(slot.icon);
    var preview = normalizeObject(slot.preview);
    var payloadIcon = normalizeIcon(payload.icon);
    var payloadPreview = normalizeObject(payload.preview);
    var direct = safePreviewUrl(readFirstDefined(
      preview.url,
      preview.src,
      icon.url,
      icon.src,
      icon.value,
      slot.previewUrl,
      slot.preview_url,
      slot.iconUrl,
      slot.icon_url,
      payloadPreview.url,
      payloadPreview.src,
      payloadIcon.url,
      payloadIcon.src,
      payload.previewUrl,
      payload.preview_url,
      payload.iconUrl,
      payload.icon_url,
      appearance.textureUrl,
      appearance.texture_url
    ));
    return direct
      || firstPreviewUrlFromAssets(slot.assets)
      || firstPreviewUrlFromAssets(payload.assets);
  }

  function slotPreviewColor(slot) {
    var payload = normalizeObject(slot.payload);
    var icon = normalizeIcon(slot.icon);
    var payloadIcon = normalizeIcon(payload.icon);
    var appearance = normalizeObject(payload.appearance || normalizeObject(slot.metadata).appearance);
    var candidate = cleanString(readFirstDefined(
      icon.color,
      payloadIcon.color,
      slot.color,
      payload.color,
      appearance.color
    ));
    if (candidate && (!window.CSS || !window.CSS.supports || window.CSS.supports("color", candidate))) {
      return candidate;
    }

    var identity = cleanString(slot.label || slot.family_id || slot.vplib_uid || "block").toLowerCase();
    if (identity.indexOf("terrain") >= 0 || identity.indexOf("grass") >= 0) return "#78a986";
    var hash = 0;
    for (var index = 0; index < identity.length; index += 1) {
      hash = ((hash << 5) - hash + identity.charCodeAt(index)) | 0;
    }
    return "hsl(" + Math.abs(hash % 360) + " 30% 58%)";
  }

  function renderQuantityElement(element, slot) {
    removeQuantityElement(element);

    var quantity = normalizeQuantity(slot.quantity, 0);

    if (quantity <= 1) {
      return;
    }

    var quantityElement = document.createElement("span");
    quantityElement.className = "vp-user-slot__quantity";
    quantityElement.setAttribute("aria-label", "Anzahl " + quantity);
    quantityElement.textContent = String(quantity);
    element.appendChild(quantityElement);
  }

  function removeQuantityElement(element) {
    try {
      var existing = element.querySelector(".vp-user-slot__quantity");

      if (existing && existing.parentNode) {
        existing.parentNode.removeChild(existing);
      }
    } catch (err) {
      // ignore
    }
  }

  function itemIconText(slot) {
    var icon = normalizeIcon(slot.icon);
    var worldEditToolId = worldEditToolIdFromSlot(slot);
    var worldEditIcons = {
      selection: "\u2317",
      room: "R",
      paint: "\u270e",
      sculpt: "\u2248",
      parcel: "\u2316",
      "parcel-grid": "\u22d5",
      "ruler-laser": "\u2194",
      "copy-transform": "\u27f3"
    };
    if (worldEditIcons[worldEditToolId]) return worldEditIcons[worldEditToolId];

    var candidates = [
      icon.text,
      icon.label,
      slot.object_kind,
      slot.label,
      slot.family_id,
      slot.vplib_uid
    ];

    for (var index = 0; index < candidates.length; index += 1) {
      var value = cleanString(candidates[index]);

      if (value) {
        return value.replace(/[^a-zA-Z0-9]/g, "").slice(0, 2).toUpperCase() || "IT";
      }
    }

    return "IT";
  }

  function buildSlotAriaLabel(slot, meta) {
    var parts = [
      "Inventar Slot " + normalizeSlotIndex(slot.slot_index)
    ];

    if (meta.empty) {
      parts.push("leer");
    } else {
      parts.push(slot.label || slot.family_id || slot.vplib_uid || "belegt");
    }

    if (meta.selected) {
      parts.push("ausgewählt");
    }

    if (meta.locked) {
      parts.push("gesperrt");
    }

    if (meta.pinned) {
      parts.push("fixiert");
    }

    return parts.join(", ");
  }

  function setSlotSaving(slotIndex, saving) {
    updateSlotClass(slotIndex, CLASSES.saving, saving);
  }

  function setSlotError(slotIndex, hasError) {
    updateSlotClass(slotIndex, CLASSES.error, hasError);
  }

  function updateSlotClass(slotIndex, className, enabled) {
    try {
      var element = getSlotElement(slotIndex);

      if (!element) {
        return;
      }

      element.classList.toggle(className, Boolean(enabled));
    } catch (err) {
      // non-critical
    }
  }

  function focusSlot(slotIndex) {
    try {
      var element = getSlotElement(slotIndex);

      if (element && typeof element.focus === "function") {
        element.focus({ preventScroll: true });
      }
    } catch (err) {
      try {
        getSlotElement(slotIndex).focus();
      } catch (focusError) {
        // ignore
      }
    }
  }

  function getSlotElement(slotIndex) {
    var normalizedSlotIndex = normalizeSlotIndex(slotIndex);

    for (var index = 0; index < state.elements.slotElements.length; index += 1) {
      var element = state.elements.slotElements[index];

      if (normalizeSlotIndex(element.getAttribute("data-slot-index")) === normalizedSlotIndex) {
        return element;
      }
    }

    return null;
  }

  function getSlot(slotIndex) {
    var normalizedSlotIndex = normalizeSlotIndex(slotIndex);
    var slots = Array.isArray(state.slots)
      ? state.slots
      : Object.keys(state.slots || {}).map(function (key) {
          return state.slots[key];
        });

    for (var index = 0; index < slots.length; index += 1) {
      if (
        slots[index]
        && normalizeSlotIndex(
          slots[index].slot_index
          || slots[index].slotIndex
          || slots[index].index
          || slots[index].slot
        ) === normalizedSlotIndex
      ) {
        return slots[index];
      }
    }

    return createEmptySlot(normalizedSlotIndex, normalizedSlotIndex === state.activeSlotIndex);
  }

  function normalizeSlots(value) {
    var byIndex = Object.create(null);
    var list = [];

    if (Array.isArray(value)) {
      list = value;
    } else if (value && typeof value === "object") {
      Object.keys(value).forEach(function (key) {
        list.push(value[key]);
      });
    }

    list.forEach(function (candidate) {
      var slot = normalizeSlot(candidate);
      byIndex[slot.slot_index] = slot;
    });

    for (var slotIndex = MIN_SLOT_INDEX; slotIndex <= state.slotCount; slotIndex += 1) {
      if (!byIndex[slotIndex]) {
        byIndex[slotIndex] = createEmptySlot(slotIndex, slotIndex === state.activeSlotIndex);
      }
    }

    var result = [];

    for (var index = MIN_SLOT_INDEX; index <= state.slotCount; index += 1) {
      result.push(byIndex[index]);
    }

    return result;
  }

  function normalizeSlot(value) {
    var raw = normalizeObject(value);
    var slotIndex = normalizeSlotIndex(raw.slot_index || raw.slotIndex || raw.index || raw.slot);

    return {
      id: raw.id || null,
      state_id: raw.state_id || raw.stateId || null,
      user_id: normalizeUserId(raw.user_id || raw.userId || state.userId),
      inventory_key: normalizeInventoryKey(raw.inventory_key || raw.inventoryKey || state.inventoryKey),
      slot_index: slotIndex,
      slot_key: raw.slot_key || raw.slotKey || slotKey(slotIndex),

      item_db_id: raw.item_db_id || raw.itemDbId || raw.item_id || raw.itemId || null,
      vplib_uid: cleanString(raw.vplib_uid || raw.vplibUid || raw.uid),
      family_id: cleanString(raw.family_id || raw.familyId || raw.family),
      package_id: cleanString(raw.package_id || raw.packageId || raw.package),
      variant_id: cleanString(raw.variant_id || raw.variantId),

      label: cleanString(raw.label || raw.name || raw.title),
      description: cleanString(raw.description || raw.text),
      object_kind: cleanString(raw.object_kind || raw.objectKind || raw.kind),
      icon_kind: cleanString(raw.icon_kind || raw.iconKind || normalizeObject(raw.payload).icon_kind),

      domain: cleanString(raw.domain),
      category: cleanString(raw.category),
      subcategory: cleanString(raw.subcategory),
      taxonomy_path: cleanString(raw.taxonomy_path || raw.taxonomyPath),

      quantity: normalizeQuantity(raw.quantity, 0),
      empty: inferSlotEmpty(raw),
      selected: normalizeBoolean(raw.selected, false),
      active: normalizeBoolean(raw.active, true),
      locked: normalizeBoolean(raw.locked, false),
      pinned: normalizeBoolean(raw.pinned, false),

      source: cleanString(raw.source) || "user",
      scope: cleanString(raw.scope) || "editor",
      mode: cleanString(raw.mode) || "creative",

      icon: normalizeIcon(raw.icon || raw.icon_text || raw.iconText),
      preview: normalizeObject(raw.preview),
      assets: normalizeAssets(raw.assets),
      variant: normalizeObject(raw.variant),
      placement: normalizeObject(raw.placement),
      payload: normalizeObject(raw.payload),
      meta: normalizeObject(raw.meta),
      metadata: normalizeObject(raw.metadata)
    };
  }

  function createEmptySlots(activeSlotIndex) {
    var result = [];

    for (var slotIndex = MIN_SLOT_INDEX; slotIndex <= state.slotCount; slotIndex += 1) {
      result.push(createEmptySlot(slotIndex, slotIndex === normalizeSlotIndex(activeSlotIndex)));
    }

    return result;
  }

  function createEmptySlot(slotIndex, selected) {
    var normalizedSlotIndex = normalizeSlotIndex(slotIndex);

    return {
      id: null,
      state_id: null,
      user_id: state.userId,
      inventory_key: state.inventoryKey,
      slot_index: normalizedSlotIndex,
      slot_key: slotKey(normalizedSlotIndex),
      item_db_id: null,
      vplib_uid: "",
      family_id: "",
      package_id: "",
      variant_id: "",
      label: "",
      description: "",
      object_kind: "",
      icon_kind: "",
      domain: "",
      category: "",
      subcategory: "",
      taxonomy_path: "",
      quantity: 0,
      empty: true,
      selected: Boolean(selected),
      active: true,
      locked: false,
      pinned: false,
      source: "user",
      scope: "editor",
      mode: "creative",
      icon: {},
      preview: {},
      assets: [],
      variant: {},
      placement: {},
      payload: {},
      meta: {},
      metadata: {}
    };
  }

  function normalizeItemPayload(value) {
    try {
      if (value && value.nodeType === 1) {
        return itemPayloadFromElement(value);
      }

      return normalizeObject(value);
    } catch (err) {
      return {};
    }
  }

  function itemPayloadFromCreativeCard(card) {
    return itemPayloadFromElement(card);
  }

  function itemPayloadFromElement(element) {
    try {
      if (!element || !element.dataset) {
        return {};
      }

      return {
        id: cleanString(element.dataset.itemId || element.dataset.id),
        item_db_id: cleanString(element.dataset.itemDbId),
        vplib_uid: cleanString(element.dataset.vplibUid),
        family_id: cleanString(element.dataset.familyId),
        package_id: cleanString(element.dataset.packageId),
        variant_id: cleanString(element.dataset.variantId),
        label: cleanString(element.dataset.itemLabel || element.dataset.itemTitle || element.getAttribute("aria-label")),
        title: cleanString(element.dataset.itemTitle),
        description: cleanString(element.dataset.itemDescription),
        object_kind: cleanString(element.dataset.objectKind),
        icon_kind: cleanString(element.dataset.iconKind),
        domain: cleanString(element.dataset.domain),
        category: cleanString(element.dataset.category),
        subcategory: cleanString(element.dataset.subcategory),
        taxonomy_path: cleanString(element.dataset.taxonomyPath),
        quantity: normalizeQuantity(element.dataset.itemQuantity, 1),
        source: cleanString(element.dataset.source) || "creative",
        scope: cleanString(element.dataset.scope) || "editor",
        mode: cleanString(element.dataset.mode) || "creative",
        locked: normalizeBoolean(element.dataset.locked, false),
        pinned: normalizeBoolean(element.dataset.pinned, false),
        icon: {
          text: readElementIconText(element)
        },
        preview: {},
        assets: [],
        meta: {},
        metadata: {}
      };
    } catch (err) {
      return {};
    }
  }

  function readElementIconText(element) {
    try {
      var icon = element.querySelector(".vp-creative-card__icon, [data-creative-card-icon]");

      if (icon) {
        return cleanString(icon.textContent);
      }

      return "";
    } catch (err) {
      return "";
    }
  }

  function hasMeaningfulItemData(value) {
    var item = normalizeObject(value);

    return Boolean(
      item.item_db_id ||
      item.itemDbId ||
      item.id ||
      item.vplib_uid ||
      item.vplibUid ||
      item.family_id ||
      item.familyId ||
      item.package_id ||
      item.packageId ||
      item.variant_id ||
      item.variantId ||
      item.label ||
      item.name ||
      item.title ||
      item.object_kind ||
      item.objectKind
    );
  }

  function inferSlotEmpty(slot) {
    var raw = normalizeObject(slot);

    if (raw.empty === true || raw.empty === "true" || raw.empty === "1") {
      return true;
    }

    if (raw.empty === false || raw.empty === "false" || raw.empty === "0") {
      return false;
    }

    return !(
      raw.item_db_id ||
      raw.itemDbId ||
      raw.vplib_uid ||
      raw.vplibUid ||
      raw.family_id ||
      raw.familyId ||
      raw.package_id ||
      raw.packageId ||
      raw.variant_id ||
      raw.variantId ||
      raw.label ||
      raw.name ||
      raw.title ||
      raw.object_kind ||
      raw.objectKind
    );
  }

  function inventoryPayloadForCache() {
    return {
      schema_version: MODULE_VERSION,
      cached_at: Date.now(),
      user_id: state.userId,
      inventory_key: state.inventoryKey,
      active_slot_index: state.activeSlotIndex,
      last_selected_slot_index: state.lastSelectedSlotIndex,
      slot_count: state.slotCount,
      slots: normalizeSlots(state.slots)
    };
  }

  function cacheKey() {
    return [
      CACHE_NAMESPACE,
      state.userId,
      state.inventoryKey
    ].join(":");
  }

  function readCache() {
    if (!state.cacheEnabled) {
      return null;
    }

    var key = cacheKey();

    try {
      if (memoryCache[key] && !isCacheExpired(memoryCache[key])) {
        return memoryCache[key];
      }
    } catch (err) {
      // ignore
    }

    try {
      var raw = window.localStorage.getItem(key);

      if (!raw) {
        return null;
      }

      var parsed = JSON.parse(raw);

      if (isCacheExpired(parsed)) {
        window.localStorage.removeItem(key);
        return null;
      }

      memoryCache[key] = parsed;
      return parsed;
    } catch (err) {
      return null;
    }
  }

  function writeCache(payload) {
    if (!state.cacheEnabled) {
      return false;
    }

    var key = cacheKey();
    var normalizedPayload = normalizeObject(payload);
    normalizedPayload.cached_at = Date.now();

    try {
      memoryCache[key] = normalizedPayload;
    } catch (err) {
      // ignore
    }

    try {
      window.localStorage.setItem(key, JSON.stringify(normalizedPayload));
      return true;
    } catch (err) {
      return false;
    }
  }

  function clearCache() {
    var key = cacheKey();

    try {
      delete memoryCache[key];
    } catch (err) {
      // ignore
    }

    try {
      window.localStorage.removeItem(key);
    } catch (err) {
      // ignore
    }

    return true;
  }

  function isCacheExpired(payload) {
    try {
      var cachedAt = parseInt(payload.cached_at, 10);

      if (!cachedAt) {
        return true;
      }

      return Date.now() - cachedAt > CACHE_TTL_MS;
    } catch (err) {
      return true;
    }
  }

  function syncRootDataset() {
    try {
      var root = state.elements.root;

      if (!root || !root.dataset) {
        return;
      }

      root.dataset.userId = String(state.userId);
      root.dataset.inventoryKey = state.inventoryKey;
      root.dataset.slotCount = String(state.slotCount);
      root.dataset.activeSlotIndex = String(state.activeSlotIndex);
      root.dataset.lastSelectedSlotIndex = String(state.lastSelectedSlotIndex);
      root.dataset.loadedFromApi = state.loadedFromApi ? "true" : "false";
      root.dataset.loading = state.loading ? "true" : "false";
      root.dataset.saving = state.saving ? "true" : "false";
      root.dataset.cacheEnabled = state.cacheEnabled ? "true" : "false";
      root.dataset.wheelNavigationEnabled = state.wheelNavigationEnabled ? "true" : "false";
      root.dataset.keyboardNavigationEnabled = state.keyboardNavigationEnabled ? "true" : "false";
    } catch (err) {
      // non-critical
    }
  }

  function setStatus(message, mode) {
    try {
      var status = state.elements.status;

      if (!status) {
        return;
      }

      if (state.statusTimer) {
        window.clearTimeout(state.statusTimer);
        state.statusTimer = null;
      }

      var text = cleanString(message);
      var normalizedMode = cleanString(mode) || "ready";

      status.classList.remove(CLASSES.statusLoading);
      status.classList.remove(CLASSES.statusSaving);
      status.classList.remove(CLASSES.statusReady);
      status.classList.remove(CLASSES.statusError);

      if (normalizedMode === "loading") {
        status.classList.add(CLASSES.statusLoading);
      } else if (normalizedMode === "saving") {
        status.classList.add(CLASSES.statusSaving);
      } else if (normalizedMode === "error") {
        status.classList.add(CLASSES.statusError);
      } else {
        status.classList.add(CLASSES.statusReady);
      }

      if (!text || normalizedMode === "ready") {
        status.hidden = true;
        status.textContent = "";
        return;
      }

      status.hidden = false;
      status.textContent = text;

      if (normalizedMode !== "loading" && normalizedMode !== "saving") {
        state.statusTimer = window.setTimeout(function () {
          status.hidden = true;
          status.textContent = "";
        }, STATUS_HIDE_DELAY_MS);
      }
    } catch (err) {
      // non-critical
    }
  }

  function dispatch(type, detail) {
    try {
      var compactSelectionEvent = type === "selection-change" || type === "selection-persisted";
      var selectedSlot = getSlot(state.activeSlotIndex);
      var payload = {
        type: type,
        module: MODULE_NAME,
        version: MODULE_VERSION,
        user_id: state.userId,
        inventory_key: state.inventoryKey,
        active_slot_index: state.activeSlotIndex,
        last_selected_slot_index: state.lastSelectedSlotIndex,
        // Selection events cross an iframe boundary. Sending the full slot
        // structured-cloned the complete VPLIB payload (metadata, previews and
        // placement data) twice per wheel tick. Keep the public scalar identity
        // fields while leaving the canonical full object in local state.
        selected_slot: compactSelectionEvent
          ? compactSelectionSlot(selectedSlot)
          : selectedSlot,
        slots: compactSelectionEvent ? [] : normalizeSlots(state.slots),
        loading: state.loading,
        saving: state.saving,
        loaded_from_api: state.loadedFromApi
      };

      if (detail && typeof detail === "object") {
        Object.keys(detail).forEach(function (key) {
          payload[key] = compactSelectionEvent && key === "slot"
            ? compactSelectionSlot(detail[key])
            : detail[key];
        });
      }

      document.dispatchEvent(
        new CustomEvent("vectoplan:user-inventory-" + type, {
          bubbles: true,
          detail: payload
        })
      );
      if (window.parent && window.parent !== window) {
        var targetOrigin = "*";

        try {
          if (document.referrer) {
            targetOrigin = new URL(document.referrer).origin;
          }
        } catch (originError) {
          targetOrigin = "*";
        }

        window.parent.postMessage({
          type: "vectoplan:user-inventory-" + type,
          source: "vectoplan-library-user-inventory",
          version: MODULE_VERSION,
          detail: payload
        }, targetOrigin);
      }
    } catch (err) {
      // non-critical
    }
  }

  /**
   * Return only scalar slot identity/presentation fields for frequent
   * selection events. This intentionally excludes raw payload, metadata,
   * preview, asset and placement trees because the parent editor only needs
   * the active index and those trees can be several hundred kilobytes.
   */
  function compactSelectionSlot(slot) {
    var source = slot && typeof slot === "object" ? slot : {};
    var result = {};
    var scalarKeys = [
      "slot_index", "slotIndex", "slot", "index", "slot_key",
      "item_db_id", "item_id", "id", "uid", "vplib_uid",
      "family_id", "package_id", "variant_id", "revision_id",
      "runtime_block_type_id", "runtimeBlockTypeId", "block_type_id",
      "blockTypeId", "label", "name", "title", "object_kind",
      "domain", "category", "subcategory", "taxonomy_path", "material",
      "texture_url", "preview_url", "color", "empty", "selected",
      "locked", "pinned"
    ];

    scalarKeys.forEach(function (key) {
      var value = source[key];
      if (
        value === null
        || typeof value === "string"
        || typeof value === "number"
        || typeof value === "boolean"
      ) {
        result[key] = value;
      }
    });

    var worldEditToolId = worldEditToolIdFromSlot(source);
    if (worldEditToolId) {
      result.world_edit_tool = worldEditToolId;
      result.worldEditTool = worldEditToolId;
    }

    if (!Object.prototype.hasOwnProperty.call(result, "slot_index")) {
      result.slot_index = normalizeSlotIndex(
        source.slot_index || source.slotIndex || source.slot || source.index
      );
    }

    return result;
  }

  function getState() {
    return {
      initialized: state.initialized,
      loading: state.loading,
      saving: state.saving,
      loadedFromApi: state.loadedFromApi,
      lastError: state.lastError ? stringifyError(state.lastError) : null,
      userId: state.userId,
      inventoryKey: state.inventoryKey,
      slotCount: state.slotCount,
      activeSlotIndex: state.activeSlotIndex,
      lastSelectedSlotIndex: state.lastSelectedSlotIndex,
      apiUrl: state.apiUrl,
      selectUrl: state.selectUrl,
      cacheEnabled: state.cacheEnabled,
      wheelNavigationEnabled: state.wheelNavigationEnabled,
      keyboardNavigationEnabled: state.keyboardNavigationEnabled,
      cardSelectionEnabled: state.cardSelectionEnabled,
      suspendDuringCreateEmbed: state.suspendDuringCreateEmbed,
      wheelNavigationScope: state.wheelNavigationScope,
      slots: normalizeSlots(state.slots),
      selectedSlot: getSlot(state.activeSlotIndex),
      hasRoot: Boolean(state.elements.root),
      hasHotbar: Boolean(state.elements.hotbar),
      hasSlotsContainer: Boolean(state.elements.slots),
      slotElements: state.elements.slotElements.length
    };
  }

  function reload() {
    clearCache();
    return loadInventory();
  }

  function requestJson(url, options) {
    return fetch(url, options || {})
      .then(function (response) {
        return response.text().then(function (text) {
          var payload = {};

          if (text) {
            try {
              payload = JSON.parse(text);
            } catch (err) {
              payload = {
                ok: false,
                message: "Antwort konnte nicht als JSON gelesen werden.",
                raw: text
              };
            }
          } else {
            payload = {
              ok: response.ok
            };
          }

          return {
            response: response,
            payload: payload
          };
        });
      });
  }

  function appendQuery(url, params) {
    try {
      var parsed = new URL(url, window.location.href);

      Object.keys(params || {}).forEach(function (key) {
        parsed.searchParams.set(key, params[key]);
      });

      return parsed.pathname + parsed.search + parsed.hash;
    } catch (err) {
      return url;
    }
  }

  function joinUrl(baseUrl, suffix) {
    try {
      var base = cleanString(baseUrl) || DEFAULT_API_URL;
      var cleanSuffix = cleanString(suffix);
      var parsed = new URL(base, window.location.href);

      parsed.pathname = parsed.pathname.replace(/\/+$/, "") + "/" + cleanSuffix.replace(/^\/+/, "");
      parsed.search = "";
      parsed.hash = "";

      return parsed.pathname + parsed.search + parsed.hash;
    } catch (err) {
      var fallbackBase = cleanString(baseUrl) || DEFAULT_API_URL;
      var fallbackSuffix = cleanString(suffix);

      return fallbackBase.replace(/\/+$/, "") + "/" + fallbackSuffix.replace(/^\/+/, "");
    }
  }

  function sanitizeSameOriginUrl(value, fallback) {
    try {
      var safeFallback = cleanString(fallback) || DEFAULT_API_URL;
      var raw = cleanString(value) || safeFallback;
      var parsed = new URL(raw, window.location.href);

      if (parsed.origin !== window.location.origin) {
        return safeFallback;
      }

      return parsed.pathname + parsed.search + parsed.hash;
    } catch (err) {
      return cleanString(fallback) || DEFAULT_API_URL;
    }
  }

  function normalizeUserId(value) {
    return Math.max(1, normalizeInteger(value, DEFAULT_USER_ID));
  }

  function normalizeInventoryKey(value) {
    var text = cleanString(value) || DEFAULT_INVENTORY_KEY;
    return text.slice(0, 120);
  }

  function normalizeSlotIndex(value) {
    return clampInteger(value, MIN_SLOT_INDEX, state.slotCount || MAX_SLOT_INDEX, MIN_SLOT_INDEX);
  }

  function normalizeQuantity(value, fallback) {
    return Math.max(0, normalizeInteger(value, fallback));
  }

  function normalizeInteger(value, fallback) {
    var number = parseInt(value, 10);

    if (!Number.isFinite(number)) {
      return fallback;
    }

    return number;
  }

  function clampInteger(value, minimum, maximum, fallback) {
    var number = normalizeInteger(value, fallback);

    if (number < minimum) {
      return minimum;
    }

    if (number > maximum) {
      return maximum;
    }

    return number;
  }

  function normalizeBoolean(value, fallback) {
    if (typeof value === "boolean") {
      return value;
    }

    if (value === null || value === undefined) {
      return Boolean(fallback);
    }

    var text = cleanString(value).toLowerCase();

    if (text === "1" || text === "true" || text === "yes" || text === "ja" || text === "on" || text === "selected") {
      return true;
    }

    if (text === "0" || text === "false" || text === "no" || text === "nein" || text === "off") {
      return false;
    }

    return Boolean(fallback);
  }

  function normalizeObject(value) {
    if (!value || typeof value !== "object") {
      return {};
    }

    if (Array.isArray(value)) {
      return {};
    }

    var result = {};

    Object.keys(value).forEach(function (key) {
      result[key] = value[key];
    });

    return result;
  }

  function normalizeArray(value) {
    if (Array.isArray(value)) {
      return value.slice();
    }

    return [];
  }

  function normalizeAssets(value) {
    if (Array.isArray(value)) {
      return value.slice();
    }

    if (value && typeof value === "object") {
      return normalizeObject(value);
    }

    return [];
  }

  function normalizeIcon(value) {
    try {
      if (!value) {
        return {};
      }

      if (typeof value === "string") {
        return {
          text: cleanString(value)
        };
      }

      if (typeof value === "object" && !Array.isArray(value)) {
        return normalizeObject(value);
      }

      return {};
    } catch (err) {
      return {};
    }
  }

  function normalizeWheelScope(value) {
    var text = cleanString(value).toLowerCase();

    if (text === "hotbar" || text === "document") {
      return text;
    }

    return "document";
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

  function readFirstDefined() {
    for (var index = 0; index < arguments.length; index += 1) {
      var value = arguments[index];

      if (value !== null && value !== undefined && value !== "") {
        return value;
      }
    }

    return "";
  }

  function readSlotLabelFromElement(element) {
    try {
      var labelElement = element.querySelector(".vp-user-slot__label");
      var placeholderElement = element.querySelector(".vp-user-slot__placeholder");

      if (labelElement) {
        return cleanString(labelElement.textContent);
      }

      if (placeholderElement && cleanString(placeholderElement.textContent).toLowerCase() !== "leer") {
        return cleanString(placeholderElement.textContent);
      }

      return "";
    } catch (err) {
      return "";
    }
  }

  function slotKey(slotIndex) {
    return "user-slot-" + normalizeSlotIndex(slotIndex);
  }

  function clearElement(element) {
    try {
      while (element.firstChild) {
        element.removeChild(element.firstChild);
      }
    } catch (err) {
      try {
        element.innerHTML = "";
      } catch (innerErr) {
        // ignore
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

  function getAttribute(element, name) {
    try {
      if (!element || typeof element.getAttribute !== "function") {
        return "";
      }

      return element.getAttribute(name);
    } catch (err) {
      return "";
    }
  }

  function isSlotLocked(element) {
    try {
      return normalizeBoolean(element.getAttribute("data-slot-locked"), false);
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

  function extractMessage(payload) {
    try {
      var errors = payload && payload.errors;

      if (Array.isArray(errors) && errors.length) {
        return cleanString(errors[0].message || errors[0].code);
      }

      return cleanString(payload.message || payload.status);
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

  function setWheelNavigationEnabled(value) {
    state.wheelNavigationEnabled = Boolean(value);
    syncRootDataset();
    return state.wheelNavigationEnabled;
  }

  function setKeyboardNavigationEnabled(value) {
    state.keyboardNavigationEnabled = Boolean(value);
    syncRootDataset();
    return state.keyboardNavigationEnabled;
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
    reload: reload,
    loadInventory: loadInventory,
    selectSlot: selectSlot,
    nextSlot: nextSlot,
    previousSlot: previousSlot,
    setSlotItem: setSlotItem,
    clearSlotItem: clearSlotItem,
    clearSlot: clearSlotItem,
    clearCache: clearCache,
    refreshElements: refreshElements,
    render: render,
    setWheelNavigationEnabled: setWheelNavigationEnabled,
    setKeyboardNavigationEnabled: setKeyboardNavigationEnabled,
    getState: getState
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
