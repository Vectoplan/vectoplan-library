/* Creative-Library selection for the first /create wizard step. */
(function () {
  "use strict";

  var ROOT_SELECTOR = "[data-vp-library-source-root='true']";
  var state = {
    root: null,
    form: null,
    mode: "",
    items: [],
    selected: null,
    permissions: null,
    ready: false
  };

  function text(value) {
    return value === null || value === undefined ? "" : String(value).trim();
  }

  function first() {
    for (var index = 0; index < arguments.length; index += 1) {
      var value = arguments[index];
      if (value !== null && value !== undefined && text(value)) {
        return value;
      }
    }
    return "";
  }

  function mapping(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function list(value) {
    return Array.isArray(value) ? value : [];
  }

  function emit(name, detail) {
    try {
      document.dispatchEvent(new CustomEvent(name, {
        bubbles: true,
        detail: detail || {}
      }));
    } catch (error) {
      /* no-op */
    }
  }

  function setStatus(message, kind) {
    var notice = state.root && state.root.querySelector("[data-vp-library-source-notice]");
    var pill = state.root && state.root.querySelector("[data-vp-library-source-status-pill]");

    if (notice) {
      notice.textContent = message;
      notice.setAttribute("data-status", kind || "idle");
    }
    if (pill) {
      pill.textContent = kind === "ready" ? "Start bereit" : kind === "warning" ? "Fallback" : kind === "error" ? "Prüfen" : "Auswahl offen";
      pill.classList.toggle("vp-create-status-pill--ok", kind === "ready");
      pill.classList.toggle("vp-create-status-pill--warning", kind === "warning");
      pill.classList.toggle("vp-create-status-pill--danger", kind === "error");
    }
  }

  function setHiddenValue(selector, value) {
    var field = state.root && state.root.querySelector(selector);
    if (field) {
      field.value = text(value);
    }
  }

  function itemRef(item) {
    return text(first(item.id, item.family_db_id, item.item_id, item.vplib_uid, item.family_id, item.package_id));
  }

  function itemPayload(item) {
    var source = mapping(item);
    var currentRevision = mapping(first(source.current_revision, source.latest_revision, source.revision));
    var payload = mapping(first(currentRevision.payload, currentRevision.resolved_payload, source.payload));
    return Object.assign({}, payload, currentRevision, source);
  }

  function itemLabel(item) {
    var data = itemPayload(item);
    return text(first(data.label, data.title, data.name, data.family_name, data.family_id, "Library-Baustein"));
  }

  function itemDescription(item) {
    var data = itemPayload(item);
    return text(first(data.description, mapping(data.family).description, "Veröffentlichte technische Familie"));
  }

  function itemTaxonomy(item) {
    var data = itemPayload(item);
    var classification = mapping(first(data.classification, data.classification_json));
    var parts = [
      first(data.domain, classification.domain),
      first(data.category, classification.category),
      first(data.subcategory, classification.subcategory)
    ].map(text).filter(Boolean);
    return parts.join(" / ");
  }

  function itemCategory(item) {
    var data = itemPayload(item);
    var classification = mapping(first(data.classification, data.classification_json));
    return text(first(data.category, classification.category));
  }

  function extractItems(payload) {
    var root = mapping(payload);
    var data = mapping(root.data);
    var candidates = [
      root.items,
      root.blocks,
      root.families,
      root.results,
      data.items,
      data.blocks,
      data.families,
      data.results,
      mapping(root.payload).items
    ];

    for (var index = 0; index < candidates.length; index += 1) {
      if (Array.isArray(candidates[index])) {
        return candidates[index];
      }
    }
    return [];
  }

  function fetchJson(url, options) {
    var controller = typeof window.AbortController === "function" ? new window.AbortController() : null;
    var timeout = controller ? window.setTimeout(function () { controller.abort(); }, 15000) : null;
    var requestOptions = Object.assign({
      credentials: "same-origin",
      headers: { "Accept": "application/json" }
    }, options || {});
    if (controller && !requestOptions.signal) {
      requestOptions.signal = controller.signal;
    }
    return window.fetch(url, requestOptions).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok || payload.ok === false) {
          throw new Error(first(payload.message, mapping(payload.error).message, "Abruf fehlgeschlagen"));
        }
        return payload;
      });
    }).finally(function () {
      if (timeout) {
        window.clearTimeout(timeout);
      }
    });
  }

  function modeInputs() {
    return Array.prototype.slice.call(state.root.querySelectorAll("[data-vp-library-mode]"));
  }

  function updateModeCards() {
    modeInputs().forEach(function (input) {
      var card = input.closest(".vp-create-library-source__mode-card");
      if (card) {
        card.classList.toggle("is-selected", input.checked);
      }
    });
  }

  function selectMode(mode) {
    state.mode = mode === "existing" ? "existing" : mode === "new" ? "new" : "";
    var browser = state.root.querySelector("[data-vp-library-browser]");

    setHiddenValue("[data-vp-source-mode]", state.mode);
    state.root.setAttribute("data-vp-library-source-mode", state.mode || "unset");
    updateModeCards();

    if (browser) {
      browser.hidden = state.mode !== "existing";
    }

    Array.prototype.slice.call(state.root.querySelectorAll("[data-vp-library-item-input]")).forEach(function (input) {
      input.disabled = state.mode !== "existing";
      input.required = state.mode === "existing";
    });

    if (state.mode === "new") {
      state.selected = null;
      setHiddenValue("[data-vp-source-library-item-ref]", "");
      setHiddenValue("[data-vp-source-vplib-uid]", "");
      setHiddenValue("[data-vp-source-revision-id]", "");
      var selection = state.root.querySelector("[data-vp-library-selection]");
      if (selection) {
        selection.hidden = true;
      }
      setStatus("Neue VPLIB: Alle folgenden Schritte stehen zur vollständigen Bearbeitung bereit.", "ready");
    } else if (state.mode === "existing" && state.selected) {
      setStatus("Bestehender Baustein ausgewählt. Mit Weiter werden die Daten als Grundlage übernommen.", "ready");
    } else if (state.mode === "existing") {
      setStatus("Wähle einen Baustein aus der Creative Library aus.", "idle");
    } else {
      setStatus("Wähle zuerst, ob du einen bestehenden Baustein verwendest oder eine neue VPLIB erstellst.", "idle");
    }

    emit("vectoplan:create:library-source-mode-changed", { mode: state.mode });
  }

  function categoryOptions() {
    var select = state.root.querySelector("[data-vp-library-category]");
    if (!select) {
      return;
    }
    while (select.options.length > 1) {
      select.remove(1);
    }
    var categories = {};
    state.items.forEach(function (item) {
      var category = itemCategory(item);
      if (category) {
        categories[category] = true;
      }
    });
    Object.keys(categories).sort().forEach(function (category) {
      var option = document.createElement("option");
      option.value = category;
      option.textContent = category.replace(/[_-]+/g, " ");
      select.appendChild(option);
    });
  }

  function updateExistingAvailability(options) {
    var settings = options || {};
    var existing = state.root.querySelector("[data-vp-library-mode='existing']");
    var next = state.root.querySelector("[data-vp-library-mode='new']");
    var label = state.root.querySelector("[data-vp-library-existing-availability]");
    var card = existing && existing.closest(".vp-create-library-source__mode-card");
    var available = state.items.length > 0 && !settings.failed;

    if (label) {
      if (settings.failed) {
        label.textContent = "Creative Library derzeit nicht erreichbar";
      } else {
        label.textContent = state.items.length === 1
          ? "1 veröffentlichter Baustein"
          : state.items.length + " veröffentlichte Bausteine";
      }
    }
    if (existing) {
      existing.disabled = !available;
      existing.required = available;
      if (!available) {
        existing.checked = false;
      }
    }
    if (card) {
      card.classList.toggle("is-unavailable", !available);
      card.setAttribute("aria-disabled", available ? "false" : "true");
    }

    if (!available && next) {
      next.checked = true;
      selectMode("new");
    }
  }

  function libraryCard(item) {
    var label = itemLabel(item);
    var description = itemDescription(item);
    var taxonomy = itemTaxonomy(item);
    var ref = itemRef(item);
    var wrapper = document.createElement("label");
    var input = document.createElement("input");
    var mark = document.createElement("span");
    var copy = document.createElement("span");
    var title = document.createElement("strong");
    var meta = document.createElement("span");
    var body = document.createElement("span");
    var badge = document.createElement("span");

    wrapper.className = "vp-create-library-card";
    wrapper.setAttribute("data-vp-library-card", ref);
    wrapper.setAttribute("data-search", [label, description, taxonomy].join(" ").toLowerCase());
    wrapper.setAttribute("data-category", itemCategory(item).toLowerCase());

    input.type = "radio";
    input.name = "selected_library_item";
    input.value = ref;
    input.disabled = state.mode !== "existing";
    input.required = state.mode === "existing";
    input.setAttribute("data-vp-library-item-input", "true");
    input.addEventListener("change", function () {
      if (input.checked) {
        selectItem(item, wrapper);
      }
    });

    mark.className = "vp-create-library-card__mark";
    mark.textContent = label.slice(0, 2).toUpperCase();
    copy.className = "vp-create-library-card__copy";
    title.textContent = label;
    meta.className = "vp-create-library-card__meta";
    meta.textContent = taxonomy || "Creative Library";
    body.className = "vp-create-library-card__description";
    body.textContent = description;
    badge.className = "vp-create-library-card__badge";
    badge.textContent = "Auswählen";

    copy.appendChild(title);
    copy.appendChild(meta);
    copy.appendChild(body);
    wrapper.appendChild(input);
    wrapper.appendChild(mark);
    wrapper.appendChild(copy);
    wrapper.appendChild(badge);
    return wrapper;
  }

  function renderItems() {
    var grid = state.root.querySelector("[data-vp-library-grid]");
    var count = state.root.querySelector("[data-vp-library-count]");
    if (!grid) {
      return;
    }
    grid.textContent = "";
    if (!state.items.length) {
      var empty = document.createElement("div");
      empty.className = "vp-create-library-source__empty";
      empty.innerHTML = "<strong>Noch keine veröffentlichten Bausteine gefunden.</strong><span>Du kannst stattdessen eine neue VPLIB erstellen.</span>";
      grid.appendChild(empty);
    } else {
      state.items.forEach(function (item) { grid.appendChild(libraryCard(item)); });
    }
    if (count) {
      count.textContent = state.items.length + (state.items.length === 1 ? " Baustein" : " Bausteine");
    }
    applyFilters();
  }

  function applyFilters() {
    var search = text((state.root.querySelector("[data-vp-library-search]") || {}).value).toLowerCase();
    var category = text((state.root.querySelector("[data-vp-library-category]") || {}).value).toLowerCase();
    var visible = 0;
    Array.prototype.slice.call(state.root.querySelectorAll("[data-vp-library-card]")).forEach(function (card) {
      var matchesSearch = !search || text(card.getAttribute("data-search")).indexOf(search) >= 0;
      var matchesCategory = !category || text(card.getAttribute("data-category")) === category;
      card.hidden = !(matchesSearch && matchesCategory);
      if (!card.hidden) {
        visible += 1;
      }
    });
    state.root.setAttribute("data-vp-library-visible-count", String(visible));
  }

  function field(name) {
    if (!state.form || !name) {
      return null;
    }
    try {
      return state.form.elements.namedItem(name) || state.form.querySelector("[name='" + name.replace(/'/g, "\\'") + "']");
    } catch (error) {
      return null;
    }
  }

  function writeField(names, value) {
    var next = text(value);
    if (!next) {
      return false;
    }
    for (var index = 0; index < names.length; index += 1) {
      var target = field(names[index]);
      if (target && !target.disabled) {
        target.value = next;
        target.dispatchEvent(new Event("input", { bubbles: true }));
        target.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }
    }
    return false;
  }

  function prefillFromItem(item) {
    var data = itemPayload(item);
    var family = mapping(first(data.family, data.identity, data.family_payload));
    var classification = mapping(first(data.classification, data.classification_json, data.taxonomy));
    var manifest = mapping(first(data.manifest, data.manifest_json));
    var variants = list(first(data.variants, mapping(data.current_revision).variants));

    writeField(["name", "family_name", "title"], first(data.name, data.label, data.title, family.name, family.label));
    writeField(["description", "family_description"], first(data.description, family.description));
    writeField(["domain"], first(data.domain, classification.domain));
    writeField(["category"], first(data.category, classification.category));
    writeField(["subcategory"], first(data.subcategory, classification.subcategory));
    writeField(["object_kind", "object_class"], first(data.object_kind, classification.object_kind));
    writeField(["family_profile_id"], first(data.family_profile_id, family.family_profile_id));
    writeField(["variant_profile_id"], first(data.variant_profile_id, family.variant_profile_id));
    writeField(["vplib_uid"], first(data.vplib_uid, manifest.vplib_uid));
    writeField(["family_id"], first(data.family_id, manifest.family_id));
    writeField(["package_id"], first(data.package_id, manifest.package_id));

    if (variants.length) {
      var variantsField = field("definition_variants_json");
      if (variantsField) {
        variantsField.value = JSON.stringify(variants);
        variantsField.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    emit("vectoplan:create:library-source-prefilled", { item: item, payload: data });
  }

  function updateSelection(item) {
    var selection = state.root.querySelector("[data-vp-library-selection]");
    if (!selection) {
      return;
    }
    selection.hidden = false;
    var name = selection.querySelector("[data-vp-library-selection-name]");
    var path = selection.querySelector("[data-vp-library-selection-path]");
    if (name) { name.textContent = itemLabel(item); }
    if (path) { path.textContent = itemTaxonomy(item) || text(first(item.family_id, item.vplib_uid)); }
  }

  function loadPermissions(item) {
    var url = state.root.getAttribute("data-vp-library-permissions-url");
    var permissionNode = state.root.querySelector("[data-vp-library-permission]");
    if (!url || !itemRef(item)) {
      return Promise.resolve(null);
    }
    return fetchJson(url + "?family_ref=" + encodeURIComponent(itemRef(item))).then(function (payload) {
      state.permissions = mapping(first(payload.data, payload));
      var capabilities = mapping(state.permissions.capabilities);
      var canVariant = capabilities.product_variant_create !== false;
      if (permissionNode) {
        permissionNode.textContent = canVariant ? "Produktvarianten erlaubt" : "Nur lesbar";
        permissionNode.classList.toggle("vp-create-status-pill--ok", canVariant);
        permissionNode.classList.toggle("vp-create-status-pill--warning", !canVariant);
      }
      state.root.setAttribute("data-vp-can-create-product-variant", canVariant ? "true" : "false");
      emit("vectoplan:create:library-permissions-loaded", state.permissions);
      return state.permissions;
    }).catch(function () {
      if (permissionNode) {
        permissionNode.textContent = "Rechte werden beim Speichern geprüft";
        permissionNode.classList.add("vp-create-status-pill--warning");
      }
      return null;
    });
  }

  function hydrateDetail(item) {
    var template = state.root.getAttribute("data-vp-library-detail-url");
    if (!template) {
      return Promise.resolve(item);
    }
    var url = template.replace("__item_ref__", encodeURIComponent(itemRef(item)));
    return fetchJson(url).then(function (payload) {
      var data = mapping(first(mapping(payload).data, payload));
      return mapping(first(data.item, data.block, data.family, data.result, data));
    }).catch(function () { return item; });
  }

  function selectItem(item, card) {
    state.selected = item;
    Array.prototype.slice.call(state.root.querySelectorAll("[data-vp-library-card]")).forEach(function (candidate) {
      candidate.classList.toggle("is-selected", candidate === card);
    });
    setHiddenValue("[data-vp-source-library-item-ref]", itemRef(item));
    setHiddenValue("[data-vp-source-vplib-uid]", first(item.vplib_uid, itemPayload(item).vplib_uid));
    setHiddenValue("[data-vp-source-revision-id]", first(item.current_revision_id, item.revision_id, mapping(item.current_revision).id));
    updateSelection(item);
    setStatus("Baustein wird als bearbeitbare Grundlage geladen …", "idle");

    Promise.all([hydrateDetail(item), loadPermissions(item)]).then(function (results) {
      state.selected = results[0] || item;
      prefillFromItem(state.selected);
      updateSelection(state.selected);
      setStatus("Bestehender Baustein ausgewählt. Du kannst jetzt mit Weiter fortfahren.", "ready");
      emit("vectoplan:create:library-source-selected", {
        item: state.selected,
        permissions: state.permissions,
        ref: itemRef(state.selected)
      });
    });
  }

  function loadLibrary() {
    var url = state.root.getAttribute("data-vp-library-list-url");
    if (!url) {
      return Promise.resolve([]);
    }
    state.root.setAttribute("data-vp-library-load-state", "loading");
    return fetchJson(url).then(function (payload) {
      state.items = extractItems(payload);
      categoryOptions();
      renderItems();
      updateExistingAvailability();
      state.root.setAttribute("data-vp-library-load-state", "ready");
      return state.items;
    }).catch(function (error) {
      state.items = [];
      renderItems();
      updateExistingAvailability({ failed: true });
      state.root.setAttribute("data-vp-library-load-state", "error");
      setStatus("Creative Library konnte nicht geladen werden. Du kannst ohne Einschränkung eine neue VPLIB beginnen.", "warning");
      return [];
    });
  }

  function bind() {
    modeInputs().forEach(function (input) {
      input.addEventListener("change", function () {
        if (input.checked) {
          selectMode(input.value);
        }
      });
    });
    var search = state.root.querySelector("[data-vp-library-search]");
    var category = state.root.querySelector("[data-vp-library-category]");
    if (search) { search.addEventListener("input", applyFilters); }
    if (category) { category.addEventListener("change", applyFilters); }
  }

  function initialize() {
    state.root = document.querySelector(ROOT_SELECTOR);
    if (!state.root || state.root.getAttribute("data-vp-library-source-ready") === "true") {
      return;
    }
    state.form = state.root.closest("form") || document.querySelector("[data-vp-create-form]");
    bind();
    loadLibrary();
    state.ready = true;
    state.root.setAttribute("data-vp-library-source-ready", "true");
    window.VectoplanCreateLibrarySource = {
      getState: function () { return state; },
      selectMode: selectMode,
      reload: loadLibrary,
      getSelectedItem: function () { return state.selected; }
    };
    emit("vectoplan:create:library-source-ready", { root: state.root });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
