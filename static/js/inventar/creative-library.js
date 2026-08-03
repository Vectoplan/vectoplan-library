// static/js/inventar/creative-library.js
(function () {
  "use strict";

  var MODULE_NAME = "VectoplanCreativeLibrary";
  var MODULE_VERSION = "1.0.0";
  var DRAG_MIME = "application/x-vectoplan-vplib-item+json";
  var REQUEST_TIMEOUT_MS = 12000;
  var SELECTORS = {
    grid: "[data-creative-library-grid]",
    search: "[data-creative-search]",
    empty: "[data-creative-empty]",
    status: "[data-taxonomy-status]",
    card: "[data-creative-item-card]"
  };

  var state = {
    initialized: false,
    loading: false,
    items: [],
    query: "",
    errors: []
  };

  function clean(value) {
    try { return String(value == null ? "" : value).trim(); } catch (error) { return ""; }
  }

  function record(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function first() {
    for (var index = 0; index < arguments.length; index += 1) {
      var value = clean(arguments[index]);
      if (value) return value;
    }
    return "";
  }

  function booleanValue(value, fallback) {
    if (typeof value === "boolean") return value;
    var normalized = clean(value).toLowerCase();
    if (["true", "1", "yes", "on", "enabled", "published", "active"].indexOf(normalized) >= 0) return true;
    if (["false", "0", "no", "off", "disabled", "deleted", "invalid"].indexOf(normalized) >= 0) return false;
    return fallback;
  }

  function unwrapItems(payload) {
    var root = record(payload);
    var candidates = [
      root.items,
      record(root.data).items,
      record(root.payload).items,
      record(root.result).items,
      record(record(root.payload).data).items,
      record(record(root.data).payload).items
    ];
    for (var index = 0; index < candidates.length; index += 1) {
      if (Array.isArray(candidates[index])) return candidates[index];
    }
    return [];
  }

  function nestedValue(source, keys) {
    var value = source;
    for (var index = 0; index < keys.length; index += 1) {
      value = record(value)[keys[index]];
    }
    return value;
  }

  function normalizeVariant(value) {
    var raw = record(value);
    var variantId = first(raw.variant_id, raw.variantId, raw.id_in_family, raw.slug);
    if (!variantId) return null;

    var status = first(raw.publication_status, raw.status).toLowerCase();
    var enabled = booleanValue(raw.enabled, booleanValue(raw.active, true));
    var visible = booleanValue(raw.visible, true);
    var published = !status || ["published", "ready", "active", "ok"].indexOf(status) >= 0;
    if (!enabled || !visible || !published) return null;

    return {
      variant_id: variantId,
      label: first(raw.label, raw.name, variantId),
      description: first(raw.description),
      is_default: booleanValue(raw.is_default, false),
      definition_values: record(raw.definition_values || raw.definitionValues),
      metadata: record(raw.metadata),
      revision_hash: first(raw.revision_hash)
    };
  }

  function normalizeVariants(raw) {
    var values = Array.isArray(raw.variants) ? raw.variants : [];
    return values.map(normalizeVariant).filter(Boolean);
  }

  function selectedVariant(variants, variantId) {
    var selected = null;
    variants.some(function (variant) {
      if (variant.variant_id !== variantId) return false;
      selected = variant;
      return true;
    });
    if (selected) return selected;
    return variants.filter(function (variant) { return variant.is_default; })[0] || variants[0] || null;
  }

  function variantMetadata(baseMetadata, variant, variants) {
    return Object.assign({}, record(baseMetadata), {
      selected_variant_id: variant ? variant.variant_id : "default",
      definition_values: variant ? record(variant.definition_values) : {},
      available_variants: variants.map(function (entry) {
        return {
          variant_id: entry.variant_id,
          label: entry.label,
          definition_values: record(entry.definition_values)
        };
      })
    });
  }

  function normalizeItem(value) {
    var wrapper = record(value);
    var raw = record(wrapper.item && typeof wrapper.item === "object" ? wrapper.item : wrapper);
    var payload = record(raw.payload);
    var metadata = record(raw.metadata || payload.metadata);
    var placement = record(
      raw.placement ||
      payload.placement ||
      nestedValue(raw, ["variant", "placement"]) ||
      nestedValue(payload, ["variant", "placement"])
    );
    var command = record(raw.placementCommand || raw.placement_command || placement.command);
    var vplibUid = first(raw.vplib_uid, raw.vplibUid, raw.uid, payload.vplib_uid, payload.vplibUid);
    var familyId = first(raw.family_id, raw.familyId, payload.family_id, payload.familyId);
    var itemDbId = first(raw.item_db_id, raw.itemDbId, raw.family_db_id, raw.id, wrapper.item_db_id, wrapper.id);
    var packageId = first(raw.package_id, raw.packageId, payload.package_id, payload.packageId);
    var variants = normalizeVariants(raw);
    var requestedVariantId = first(raw.variant_id, raw.variantId, raw.default_variant_id, payload.variant_id, payload.variantId, "default");
    var activeVariant = selectedVariant(variants, requestedVariantId);
    var variantId = activeVariant ? activeVariant.variant_id : requestedVariantId;
    var runtimeBlockTypeId = first(
      raw.runtimeBlockTypeId,
      raw.runtime_block_type_id,
      raw.blockTypeId,
      raw.block_type_id,
      placement.runtimeBlockTypeId,
      placement.runtime_block_type_id,
      placement.blockTypeId,
      placement.block_type_id,
      command.runtimeBlockTypeId,
      command.blockTypeId,
      payload.runtimeBlockTypeId,
      payload.runtime_block_type_id,
      metadata.runtimeBlockTypeId,
      metadata.runtime_block_type_id,
      familyId,
      vplibUid ? "vplib:" + vplibUid + ":" + variantId : ""
    );
    var status = first(raw.publication_status, raw.status, wrapper.status).toLowerCase();
    var label = first(raw.label, raw.name, raw.title, payload.label, payload.name, familyId, vplibUid);
    var objectKind = first(raw.object_kind, raw.objectKind, raw.kind, payload.object_kind, payload.objectKind, "block");
    var enabled = booleanValue(raw.enabled, true) && booleanValue(raw.active, true);
    var visible = booleanValue(raw.visible, true) && !booleanValue(raw.is_deleted, false);
    var published = !status || ["published", "ready", "active", "ok"].indexOf(status) >= 0;
    var placeable = booleanValue(placement.placeable, booleanValue(raw.placeable, true));

    if (!enabled || !visible || !published || !placeable || !runtimeBlockTypeId || !(vplibUid || familyId || itemDbId) || !label) {
      return null;
    }

    var icon = record(raw.icon || payload.icon);
    var preview = record(raw.preview || payload.preview);
    var description = first(raw.description, raw.text, payload.description);
    var domain = first(raw.domain, payload.domain, "all").toLowerCase();
    var category = first(raw.category, payload.category, "all").toLowerCase();
    var subcategory = first(raw.subcategory, payload.subcategory, "all").toLowerCase();
    var taxonomyPath = first(raw.taxonomy_path, raw.taxonomyPath, payload.taxonomy_path, [domain, category, subcategory].join("/"));
    var iconText = first(icon.text, icon.label, raw.icon_text, label).replace(/[^\p{L}\p{N}]/gu, "").slice(0, 2).toUpperCase() || "VP";
    var previewUrl = first(preview.url, preview.src, raw.preview_url, raw.banner_url);
    var color = first(icon.color, raw.color, payload.color);

    return {
      id: itemDbId,
      item_db_id: itemDbId,
      vplib_uid: vplibUid,
      family_id: familyId,
      package_id: packageId,
      variant_id: variantId,
      runtimeBlockTypeId: runtimeBlockTypeId,
      blockTypeId: runtimeBlockTypeId,
      label: label,
      title: label,
      description: description,
      object_kind: objectKind,
      domain: domain,
      category: category,
      subcategory: subcategory,
      taxonomy_path: taxonomyPath,
      quantity: Number(raw.quantity || 1) || 1,
      source: first(raw.source, raw.source_scope, "creative-library"),
      scope: first(raw.scope, "editor"),
      mode: "creative",
      icon: { text: iconText, color: color },
      preview: previewUrl ? { url: previewUrl } : {},
      placement: {
        kind: first(placement.kind, command.kind, "SetBlock"),
        runtimeBlockTypeId: runtimeBlockTypeId,
        blockTypeId: runtimeBlockTypeId,
        placeable: true
      },
      revision_hash: first(raw.revision_hash, raw.current_revision_hash),
      variants: variants,
      selected_variant: activeVariant,
      metadata: variantMetadata(metadata, activeVariant, variants)
    };
  }

  function expandItemVariants(value) {
    var wrapper = record(value);
    var raw = record(wrapper.item && typeof wrapper.item === "object" ? wrapper.item : wrapper);
    var variants = Array.isArray(raw.variants) ? raw.variants : [];
    if (!variants.length) return [value];

    var familyLabel = first(raw.label, raw.name, raw.title, raw.family_id, raw.vplib_uid);
    return variants.map(function (variantValue) {
      var variant = record(variantValue);
      var merged = Object.assign({}, raw);
      var variantId = first(variant.variant_id, variant.variantId, variant.id_in_family, variant.slug, "default");
      var variantLabel = first(variant.label, variant.name, variantId);

      merged.variant = variant;
      merged.variant_id = variantId;
      merged.label = variantLabel ? familyLabel + " - " + variantLabel : familyLabel;
      merged.description = first(variant.description, raw.description, raw.text);
      merged.enabled = booleanValue(raw.enabled, true) && booleanValue(variant.enabled, true);
      merged.visible = booleanValue(raw.visible, true) && booleanValue(variant.visible, true);
      merged.status = first(variant.publication_status, variant.status, raw.publication_status, raw.status);
      merged.publication_status = merged.status;
      merged.payload = Object.assign(
        {},
        record(raw.payload),
        record(variant.payload),
        record(variant.resolved_payload)
      );
      merged.metadata = Object.assign(
        {},
        record(raw.metadata),
        record(variant.metadata),
        { definition_values: record(variant.definition_values) }
      );
      return merged;
    });
  }

  function uniqueItems(values) {
    var result = [];
    var seen = Object.create(null);
    values.forEach(function (value) {
      var item = normalizeItem(value);
      if (!item) return;
      var key = item.vplib_uid || item.family_id || item.item_db_id;
      if (seen[key]) return;
      seen[key] = true;
      result.push(item);
    });
    return result.sort(function (left, right) { return left.label.localeCompare(right.label, "de"); });
  }

  function safePreviewUrl(value) {
    var url = clean(value);
    if (!url) return "";
    try {
      var parsed = new URL(url, window.location.href);
      if (["http:", "https:"].indexOf(parsed.protocol) < 0) return "";
      return parsed.href;
    } catch (error) {
      return "";
    }
  }

  function itemPayload(item) {
    return {
      id: item.id,
      item_db_id: item.item_db_id,
      vplib_uid: item.vplib_uid,
      family_id: item.family_id,
      package_id: item.package_id,
      variant_id: item.variant_id,
      runtimeBlockTypeId: item.runtimeBlockTypeId,
      blockTypeId: item.blockTypeId,
      label: item.label,
      title: item.title,
      description: item.description,
      object_kind: item.object_kind,
      domain: item.domain,
      category: item.category,
      subcategory: item.subcategory,
      taxonomy_path: item.taxonomy_path,
      quantity: item.quantity,
      source: item.source,
      scope: item.scope,
      mode: item.mode,
      icon: item.icon,
      preview: item.preview,
      placement: item.placement,
      variant: item.selected_variant,
      variants: item.variants,
      metadata: item.metadata
    };
  }

  function postDragMessage(type, item) {
    if (!window.parent || window.parent === window) return;
    var targetOrigin = "*";
    try { if (document.referrer) targetOrigin = new URL(document.referrer).origin; } catch (error) { targetOrigin = "*"; }
    window.parent.postMessage({
      type: type,
      source: "vectoplan-library-creative-inventory",
      version: MODULE_VERSION,
      detail: item ? { item: itemPayload(item) } : {}
    }, targetOrigin);
  }

  function createCard(item) {
    var card = document.createElement("article");
    card.className = "vp-creative-card vp-creative-card--real-item";
    card.setAttribute("role", "listitem");
    card.setAttribute("tabindex", "0");
    card.setAttribute("draggable", "true");
    card.setAttribute("aria-label", item.label + ", in einen Inventar-Slot ziehen");
    card.setAttribute("title", item.label + " in einen Slot ziehen");
    card.dataset.creativeItemCard = "true";
    card.dataset.creativeCard = "true";
    card.dataset.itemId = item.id;
    card.dataset.itemDbId = item.item_db_id;
    card.dataset.vplibUid = item.vplib_uid;
    card.dataset.familyId = item.family_id;
    card.dataset.packageId = item.package_id;
    card.dataset.variantId = item.variant_id;
    card.dataset.definitionValues = JSON.stringify(item.selected_variant ? item.selected_variant.definition_values : {});
    card.dataset.runtimeBlockTypeId = item.runtimeBlockTypeId;
    card.dataset.blockTypeId = item.blockTypeId;
    card.dataset.domain = item.domain;
    card.dataset.category = item.category;
    card.dataset.subcategory = item.subcategory;
    card.dataset.taxonomyPath = item.taxonomy_path;
    card.dataset.objectKind = item.object_kind;
    card.dataset.itemTitle = item.title;
    card.dataset.itemLabel = item.label;
    card.dataset.itemDescription = item.description;
    card.dataset.itemQuantity = String(item.quantity);
    card.dataset.source = item.source;
    card.dataset.scope = item.scope;
    card.dataset.mode = item.mode;
    card.dataset.selectable = "true";
    card.dataset.draggable = "true";
    card.dataset.disabled = "false";
    card.dataset.searchText = [item.label, item.description, item.vplib_uid, item.family_id, item.package_id, item.domain, item.category, item.subcategory, item.variants.map(function (variant) { return variant.label; }).join(" ")].join(" ").toLowerCase();

    var preview = document.createElement("div");
    preview.className = "vp-creative-card__preview vp-creative-card__banner";
    preview.setAttribute("aria-hidden", "true");
    var previewUrl = safePreviewUrl(item.preview.url);
    if (previewUrl) {
      var image = document.createElement("img");
      image.className = "vp-creative-card__preview-image vp-creative-card__banner-image";
      image.src = previewUrl;
      image.alt = "";
      image.loading = "lazy";
      image.decoding = "async";
      preview.appendChild(image);
    }
    var icon = document.createElement("span");
    icon.className = "vp-creative-card__icon";
    icon.dataset.creativeCardIcon = "true";
    icon.textContent = item.icon.text;
    if (/^#[0-9a-f]{3,8}$/i.test(item.icon.color)) icon.style.backgroundColor = item.icon.color;
    preview.appendChild(icon);

    var content = document.createElement("div");
    content.className = "vp-creative-card__content";
    var title = document.createElement("h2");
    title.className = "vp-creative-card__title";
    title.textContent = item.label;
    content.appendChild(title);
    if (item.description) {
      var description = document.createElement("p");
      description.className = "vp-creative-card__text";
      description.textContent = item.description;
      content.appendChild(description);
    }
    if (item.variants.length > 1) {
      var variantControl = document.createElement("label");
      variantControl.className = "vp-creative-card__variant-control";
      var variantLabel = document.createElement("span");
      variantLabel.className = "vp-creative-card__variant-label";
      variantLabel.textContent = "Dicke";
      var variantSelect = document.createElement("select");
      variantSelect.className = "vp-creative-card__variant-select";
      variantSelect.setAttribute("aria-label", "Dicke f?r " + item.label + " w?hlen");
      variantSelect.draggable = false;
      item.variants.forEach(function (variant) {
        var option = document.createElement("option");
        option.value = variant.variant_id;
        option.textContent = variant.label;
        option.selected = variant.variant_id === item.variant_id;
        variantSelect.appendChild(option);
      });
      variantSelect.addEventListener("change", function () {
        var activeVariant = selectedVariant(item.variants, variantSelect.value);
        if (!activeVariant) return;
        item.variant_id = activeVariant.variant_id;
        item.selected_variant = activeVariant;
        item.metadata = variantMetadata(item.metadata, activeVariant, item.variants);
        card.dataset.variantId = activeVariant.variant_id;
        card.dataset.definitionValues = JSON.stringify(activeVariant.definition_values);
      });
      ["pointerdown", "mousedown", "click", "dragstart"].forEach(function (eventName) {
        variantSelect.addEventListener(eventName, function (event) { event.stopPropagation(); });
      });
      variantControl.appendChild(variantLabel);
      variantControl.appendChild(variantSelect);
      content.appendChild(variantControl);
    }
    var hint = document.createElement("span");
    hint.className = "vp-creative-card__drag-hint";
    hint.textContent = "Ziehen und auf Slot 1–9 ablegen";
    content.appendChild(hint);
    card.appendChild(preview);
    card.appendChild(content);

    card.addEventListener("dragstart", function (event) {
      var payload = itemPayload(item);
      card.classList.add("vp-creative-card--dragging");
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "copy";
        event.dataTransfer.setData(DRAG_MIME, JSON.stringify(payload));
        event.dataTransfer.setData("text/plain", JSON.stringify(payload));
      }
      postDragMessage("vectoplan:creative-drag-start", item);
    });
    card.addEventListener("dragend", function () {
      card.classList.remove("vp-creative-card--dragging");
      postDragMessage("vectoplan:creative-drag-end", null);
    });
    return card;
  }

  function refreshTaxonomy() {
    try {
      var taxonomy = window.VectoplanTaxonomyNavigation;
      if (taxonomy) {
        taxonomy.refreshElements();
        taxonomy.applyCreativeCardFilter();
      }
    } catch (error) { state.errors.push(String(error)); }
  }

  function updateEmptyState() {
    var grid = document.querySelector(SELECTORS.grid);
    var empty = document.querySelector(SELECTORS.empty);
    if (!grid || !empty) return;
    var cards = Array.prototype.slice.call(grid.querySelectorAll(SELECTORS.card));
    var visible = cards.filter(function (card) {
      return !card.hidden && !card.classList.contains("vp-creative-card--hidden-by-taxonomy") && !card.classList.contains("vp-creative-card--hidden-by-search");
    }).length;
    empty.hidden = visible > 0 || state.loading;
    grid.hidden = visible === 0;
  }

  function applySearch() {
    var grid = document.querySelector(SELECTORS.grid);
    if (!grid) return;
    var normalized = clean(state.query).toLocaleLowerCase("de");
    Array.prototype.forEach.call(grid.querySelectorAll(SELECTORS.card), function (card) {
      var haystack = clean(card.dataset.searchText || card.textContent).toLocaleLowerCase("de");
      card.classList.toggle("vp-creative-card--hidden-by-search", Boolean(normalized && haystack.indexOf(normalized) < 0));
    });
    updateEmptyState();
  }

  function setLoadingStatus(message) {
    var status = document.querySelector(SELECTORS.status);
    if (!status) return;
    status.hidden = !message;
    status.textContent = message || "";
  }

  function render(items) {
    var grid = document.querySelector(SELECTORS.grid);
    if (!grid) return;
    while (grid.firstChild) grid.removeChild(grid.firstChild);
    var fragment = document.createDocumentFragment();
    items.forEach(function (item) { fragment.appendChild(createCard(item)); });
    grid.appendChild(fragment);
    state.items = items;
    refreshTaxonomy();
    applySearch();
    setLoadingStatus("");
    updateEmptyState();
    document.dispatchEvent(new CustomEvent("vectoplan:creative-library-ready", { detail: { itemCount: items.length } }));
  }

  function requestItems(url) {
    if (!url || typeof window.fetch !== "function") return Promise.resolve([]);
    var controller = typeof window.AbortController === "function" ? new window.AbortController() : null;
    var timeoutId = window.setTimeout(function () {
      if (controller) controller.abort();
    }, REQUEST_TIMEOUT_MS);
    var options = { credentials: "same-origin", cache: "no-store", headers: { "Accept": "application/json" } };
    if (controller) options.signal = controller.signal;
    return window.fetch(url, options)
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status + " für " + url);
        return response.json();
      })
      .then(unwrapItems)
      .then(function (items) {
        window.clearTimeout(timeoutId);
        return items;
      }, function (error) {
        window.clearTimeout(timeoutId);
        throw error;
      });
  }

  function load() {
    var grid = document.querySelector(SELECTORS.grid);
    if (!grid) return Promise.resolve([]);
    state.loading = true;
    setLoadingStatus("Veröffentlichte VPLIB-Objekte werden geladen …");
    updateEmptyState();
    var urls = [clean(grid.dataset.creativeItemsUrl), clean(grid.dataset.publishedItemsUrl)].filter(Boolean);
    return Promise.allSettled(urls.map(requestItems)).then(function (results) {
      var rawItems = [];
      results.forEach(function (result) {
        if (result.status === "fulfilled") rawItems = rawItems.concat(result.value);
        else state.errors.push(String(result.reason));
      });
      state.loading = false;
      var items = uniqueItems(rawItems);
      render(items);
      return items;
    }).catch(function (error) {
      state.loading = false;
      state.errors.push(String(error));
      render([]);
      return [];
    });
  }

  function bindInventoryToggleKeys() {
    document.addEventListener("keydown", function (event) {
      if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;

      var target = event.target;
      var targetTag = target && target.tagName ? clean(target.tagName).toUpperCase() : "";
      if ((target && target.isContentEditable) || ["INPUT", "TEXTAREA", "SELECT"].indexOf(targetTag) >= 0) {
        return;
      }

      var normalizedKey = clean(event.key).toLowerCase();
      var togglesCreativeInventory = normalizedKey === "tab"
        || event.code === "Tab"
        || normalizedKey === "i"
        || event.code === "KeyI";
      if (!togglesCreativeInventory) return;

      event.preventDefault();
      event.stopImmediatePropagation();
      postDragMessage("vectoplan:creative-inventory-close", null);
    }, true);
  }

  function bindSearch() {
    var input = document.querySelector(SELECTORS.search);
    if (!input) return;
    input.addEventListener("input", function () { state.query = input.value; applySearch(); });
    document.addEventListener("keydown", function (event) {
      if ((event.key === "f" || event.key === "F") && !event.ctrlKey && !event.metaKey && !event.altKey && document.activeElement !== input) {
        var tag = document.activeElement && document.activeElement.tagName ? document.activeElement.tagName : "";
        if (["INPUT", "TEXTAREA", "SELECT"].indexOf(tag) < 0) {
          event.preventDefault();
          input.focus({ preventScroll: true });
        }
      }
    });
  }

  function init() {
    if (state.initialized) return;
    state.initialized = true;
    bindInventoryToggleKeys();
    bindSearch();
    document.addEventListener("vectoplan:taxonomy-filter-applied", function () { applySearch(); });
    void load();
  }

  window[MODULE_NAME] = { init: init, load: load, applySearch: applySearch, getState: function () { return state; } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
