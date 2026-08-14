/* Manufacturer product variants and distribution coverage for /create. */
(function () {
  "use strict";

  var ROOT_SELECTOR = "[data-vp-manufacturer-product-root='true']";
  var state = {
    root: null,
    form: null,
    sourceRef: "",
    mode: "",
    canCreate: false,
    locations: [],
    pending: false
  };

  function clean(value) {
    return value === null || value === undefined ? "" : String(value).trim();
  }

  function field(name) {
    return state.root ? state.root.querySelector("[data-vp-manufacturer-field='" + name + "']") : null;
  }

  function rootField(selector) {
    return state.form ? state.form.querySelector(selector) : null;
  }

  function value(name) {
    var node = field(name);
    return node ? clean(node.value) : "";
  }

  function numberOrNull(raw) {
    if (clean(raw) === "") {
      return null;
    }
    var parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function setStatus(message, kind) {
    var node = state.root && state.root.querySelector("[data-vp-manufacturer-product-status]");
    if (node) {
      node.textContent = message;
      node.setAttribute("data-status", kind || "idle");
    }
  }

  function setPermissionLabel(message, allowed) {
    var node = state.root && state.root.querySelector("[data-vp-manufacturer-permission-status]");
    if (!node) {
      return;
    }
    node.textContent = message;
    node.classList.toggle("vp-create-status-pill--ok", allowed === true);
    node.classList.toggle("vp-create-status-pill--warning", allowed === false);
    node.classList.toggle("vp-create-status-pill--muted", allowed === null);
  }

  function updateSourceState() {
    var source = rootField("[data-vp-source-library-item-ref]");
    var mode = rootField("[data-vp-source-mode]");
    state.sourceRef = source ? clean(source.value) : "";
    state.mode = mode ? clean(mode.value) : "";

    var active = state.mode === "existing" && !!state.sourceRef;
    state.root.hidden = !active;
    Array.prototype.slice.call(state.root.querySelectorAll("[data-vp-manufacturer-required]")).forEach(function (node) {
      node.required = active;
    });
    Array.prototype.slice.call(state.root.querySelectorAll("[data-vp-distribution-row] [data-vp-location-field='name'], [data-vp-distribution-row] [data-vp-location-field='postal_code'], [data-vp-distribution-row] [data-vp-location-field='city'], [data-vp-distribution-row] [data-vp-location-field='country_code'], [data-vp-distribution-row] [data-vp-location-field='radius_km']")).forEach(function (node) {
      node.required = active;
    });

    if (!active) {
      state.canCreate = false;
      setPermissionLabel(state.mode === "new" ? "Nach VPLIB-Speicherung verfügbar" : "Familie auswählen", null);
      setStatus("Produktvarianten werden nach Auswahl einer bestehenden Familie separat gespeichert.", "idle");
    }
    updateButton();
  }

  function updateButton() {
    var button = state.root && state.root.querySelector("[data-vp-save-manufacturer-product]");
    if (button) {
      button.disabled = state.pending || state.mode !== "existing" || !state.sourceRef || !state.canCreate;
      button.setAttribute("aria-busy", state.pending ? "true" : "false");
    }
  }

  function rowData(row) {
    function rowValue(key) {
      var node = row.querySelector("[data-vp-location-field='" + key + "']");
      return node ? clean(node.value) : "";
    }
    return {
      name: rowValue("name"),
      channel: rowValue("channel") || "factory",
      address: rowValue("address"),
      postal_code: rowValue("postal_code"),
      city: rowValue("city"),
      country_code: (rowValue("country_code") || "DE").toUpperCase(),
      radius_km: numberOrNull(rowValue("radius_km")),
      latitude: numberOrNull(rowValue("latitude")),
      longitude: numberOrNull(rowValue("longitude"))
    };
  }

  function collectLocations() {
    return Array.prototype.slice.call(state.root.querySelectorAll("[data-vp-distribution-row]")).map(rowData);
  }

  function productPayload() {
    return {
      family_ref: state.sourceRef,
      source_vplib_uid: clean((rootField("[data-vp-source-vplib-uid]") || {}).value),
      base_variant_id: value("manufacturer_base_variant_id") || "default",
      manufacturer_org_id: value("manufacturer_org_id"),
      brand: value("manufacturer_brand"),
      product_name: value("manufacturer_product_name"),
      sku: value("manufacturer_sku"),
      gtin: value("manufacturer_gtin"),
      status: "submitted",
      locations: collectLocations()
    };
  }

  function syncJson() {
    var product = productPayload();
    var productNode = state.root.querySelector("[data-vp-manufacturer-product-json]");
    var locationsNode = state.root.querySelector("[data-vp-distribution-locations-json]");
    if (productNode) {
      productNode.value = JSON.stringify(product);
    }
    if (locationsNode) {
      locationsNode.value = JSON.stringify(product.locations);
    }
    return product;
  }

  function markRows() {
    Array.prototype.slice.call(state.root.querySelectorAll("[data-vp-distribution-row]")).forEach(function (row, index) {
      var label = row.querySelector("[data-vp-distribution-row-label]");
      if (label) {
        label.textContent = "Standort " + (index + 1);
      }
      var remove = row.querySelector("[data-vp-remove-distribution-location]");
      if (remove) {
        remove.disabled = state.root.querySelectorAll("[data-vp-distribution-row]").length <= 1;
      }
    });
  }

  function addLocation(initial) {
    var template = state.root.querySelector("[data-vp-distribution-row-template]");
    var rows = state.root.querySelector("[data-vp-distribution-rows]");
    if (!template || !rows) {
      return null;
    }
    var fragment = template.content.cloneNode(true);
    var row = fragment.querySelector("[data-vp-distribution-row]");
    var data = initial || {};
    Object.keys(data).forEach(function (key) {
      var node = row.querySelector("[data-vp-location-field='" + key + "']");
      if (node && data[key] !== null && data[key] !== undefined) {
        node.value = data[key];
      }
    });
    row.addEventListener("input", syncJson);
    row.addEventListener("change", syncJson);
    var remove = row.querySelector("[data-vp-remove-distribution-location]");
    if (remove) {
      remove.addEventListener("click", function () {
        row.remove();
        markRows();
        syncJson();
      });
    }
    rows.appendChild(fragment);
    markRows();
    updateSourceState();
    syncJson();
    return row;
  }

  function variantsFromRuntime() {
    try {
      if (window.VectoplanCreateVariantState && typeof window.VectoplanCreateVariantState.getVariants === "function") {
        return window.VectoplanCreateVariantState.getVariants() || [];
      }
    } catch (error) {
      /* no-op */
    }
    var hidden = rootField("[data-vp-definition-variants-json]");
    try {
      return JSON.parse(hidden && hidden.value ? hidden.value : "[]");
    } catch (error) {
      return [];
    }
  }

  function refreshBaseVariants() {
    var select = state.root.querySelector("[data-vp-manufacturer-base-variant]");
    if (!select) {
      return;
    }
    var current = clean(select.value) || "default";
    var variants = variantsFromRuntime();
    select.textContent = "";
    (variants.length ? variants : [{ variant_id: "default", label: "Standard" }]).forEach(function (variant, index) {
      var option = document.createElement("option");
      option.value = clean(variant.variant_id || variant.variantId || variant.id || (index === 0 ? "default" : "variant-" + (index + 1)));
      option.textContent = clean(variant.label || variant.name || option.value || "Variante");
      select.appendChild(option);
    });
    if (Array.prototype.some.call(select.options, function (option) { return option.value === current; })) {
      select.value = current;
    }
    syncJson();
  }

  function validateProduct(payload) {
    var invalid = [];
    Array.prototype.slice.call(state.root.querySelectorAll("[required]")).forEach(function (node) {
      var valid = node.type === "checkbox" ? node.checked : !!clean(node.value);
      node.classList.toggle("is-invalid", !valid);
      if (!valid) {
        node.setAttribute("aria-invalid", "true");
        invalid.push(node);
      } else {
        node.removeAttribute("aria-invalid");
      }
    });
    if (!payload.locations.length) {
      return { valid: false, message: "Mindestens ein Vertriebsstandort ist erforderlich." };
    }
    if (invalid.length) {
      invalid[0].focus();
      return { valid: false, message: "Bitte fülle alle Pflichtfelder der Produktvariante und des Standorts aus." };
    }
    return { valid: true };
  }

  function saveProduct() {
    if (state.pending) {
      return;
    }
    var payload = syncJson();
    var validation = validateProduct(payload);
    if (!validation.valid) {
      setStatus(validation.message, "error");
      return;
    }
    var url = state.root.getAttribute("data-vp-manufacturer-products-url");
    state.pending = true;
    updateButton();
    setStatus("Produktvariante wird eingereicht …", "loading");
    window.fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok || body.ok === false) {
          throw new Error(clean(body.message || (body.error && body.error.message)) || "Speichern fehlgeschlagen");
        }
        return body;
      });
    }).then(function (result) {
      setStatus("Produktvariante wurde separat in der Datenbank gespeichert und zur Freigabe eingereicht.", "success");
      document.dispatchEvent(new CustomEvent("vectoplan:create:manufacturer-product-saved", { detail: result }));
    }).catch(function (error) {
      setStatus("Produktvariante konnte nicht gespeichert werden: " + clean(error.message), "error");
    }).finally(function () {
      state.pending = false;
      updateButton();
    });
  }

  function applyPermissions(detail) {
    var data = detail && detail.capabilities ? detail : (detail && detail.data ? detail.data : detail || {});
    var capabilities = data.capabilities || {};
    var identity = data.identity || {};
    state.canCreate = capabilities.product_variant_create !== false;
    if (identity.organization_id && !value("manufacturer_org_id")) {
      field("manufacturer_org_id").value = identity.organization_id;
    }
    setPermissionLabel(state.canCreate ? "Produktvarianten erlaubt" : "Keine Einreichberechtigung", state.canCreate);
    updateButton();
    syncJson();
  }

  function bind() {
    state.root.addEventListener("input", syncJson);
    state.root.addEventListener("change", syncJson);
    var add = state.root.querySelector("[data-vp-add-distribution-location]");
    var save = state.root.querySelector("[data-vp-save-manufacturer-product]");
    if (add) { add.addEventListener("click", function () { addLocation({ country_code: "DE", radius_km: 100 }); }); }
    if (save) { save.addEventListener("click", saveProduct); }

    document.addEventListener("vectoplan:create:library-source-mode-changed", updateSourceState);
    document.addEventListener("vectoplan:create:library-source-selected", function (event) {
      updateSourceState();
      applyPermissions((event.detail || {}).permissions || {});
    });
    document.addEventListener("vectoplan:create:library-permissions-loaded", function (event) {
      applyPermissions(event.detail || {});
    });
    ["vectoplan:create:variant-state-changed", "vectoplan:create:variant-state-synced", "vectoplan:create:variant-added", "vectoplan:create:variant-updated", "vectoplan:create:variant-removed"].forEach(function (name) {
      document.addEventListener(name, refreshBaseVariants);
    });
  }

  function initialize() {
    state.root = document.querySelector(ROOT_SELECTOR);
    if (!state.root || state.root.getAttribute("data-vp-manufacturer-product-ready") === "true") {
      return;
    }
    state.form = state.root.closest("form") || document.querySelector("[data-vp-create-form]");
    bind();
    addLocation({ country_code: "DE", radius_km: 100, channel: "factory" });
    refreshBaseVariants();
    updateSourceState();
    state.root.setAttribute("data-vp-manufacturer-product-ready", "true");
    window.VectoplanCreateManufacturerProducts = {
      getPayload: productPayload,
      save: saveProduct,
      addLocation: addLocation,
      refreshVariants: refreshBaseVariants
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
