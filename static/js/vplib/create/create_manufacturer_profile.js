(function () {
  "use strict";

  var VERSION = "2.0.0";
  var ROOT_SELECTOR = "[data-vp-manufacturer-profile-root='true']";

  function text(value) { return value === null || value === undefined ? "" : String(value).trim(); }
  function parseJson(value, fallback) {
    try { var parsed = JSON.parse(String(value || "")); return parsed === null ? fallback : parsed; }
    catch (error) { return fallback; }
  }
  function numberOrNull(value) {
    var parsed = Number(String(value === undefined ? "" : value).replace(",", "."));
    return Number.isFinite(parsed) ? parsed : null;
  }
  function unique(values) { return values.filter(function (value, index, list) { return value && list.indexOf(value) === index; }); }

  function boot() {
    var root = document.querySelector(ROOT_SELECTOR);
    if (!root || root.dataset.vpManufacturerProfileReady === "true") { return; }
    var form = root.closest("form");
    var api = root.dataset.vpManufacturerApi;
    var geocodeApi = root.dataset.vpManufacturerGeocodeApi;
    var list = root.querySelector("[data-vp-manufacturer-list]");
    var registryStatus = root.querySelector("[data-vp-manufacturer-registry-status]");
    var search = root.querySelector("[data-vp-manufacturer-search]");
    var profileField = root.querySelector("[data-vp-manufacturer-profile-json]");
    var locationsField = root.querySelector("[data-vp-manufacturer-locations-json]");
    var organizationIdField = root.querySelector('[data-vp-manufacturer-profile-field="organization_id"]');
    var locationRows = root.querySelector("[data-vp-manufacturer-location-rows]");
    var locationTemplate = root.querySelector("template[data-vp-manufacturer-location-template]");
    var summary = root.querySelector("[data-vp-manufacturer-profile-summary]");
    var saveStatus = root.querySelector("[data-vp-manufacturer-save-status]");
    var transferPanel = root.querySelector("[data-vp-manufacturer-transfer-panel]");
    var newManufacturerButton = root.querySelector("[data-vp-manufacturer-new]");
    var selectedManufacturer = null;
    var platformAdmin = false;
    var includeAll = false;
    var registryItems = [];
    var registryTimer = 0;

    function familyRef() {
      var field = form && form.querySelector('[name="source_library_item_ref"]');
      if (field && text(field.value)) { return text(field.value); }
      var uid = form && form.querySelector('[name="vplib_uid"]');
      var family = form && form.querySelector('[name="family_id"]');
      return text((uid && uid.value) || (family && family.value));
    }

    function organizationValue(key) {
      var field = root.querySelector('[data-vp-manufacturer-profile-field="' + key + '"]');
      return text(field && field.value);
    }
    function setOrganizationValue(key, value) {
      var field = root.querySelector('[data-vp-manufacturer-profile-field="' + key + '"]');
      if (field) { field.value = value === null || value === undefined ? "" : String(value); }
    }
    function rowField(row, key) { return row.querySelector('[data-vp-manufacturer-location-field="' + key + '"]'); }
    function rowValue(row, key) { var field = rowField(row, key); return text(field && field.value); }
    function setRowValue(row, key, value) { var field = rowField(row, key); if (field) { field.value = value === null || value === undefined ? "" : String(value); } }

    function currentVariants() {
      var field = document.querySelector("[data-vp-definition-variants-json='true'], [name='definition_variants_json']");
      var values = parseJson(field && field.value, []);
      if (!Array.isArray(values) || !values.length) { values = [{ variant_id: "default", label: "Standard" }]; }
      return values.map(function (variant, index) {
        var id = text(variant.variant_id || variant.variantId || variant.id || (index ? "variant_" + (index + 1) : "default"));
        return { id: id, label: text(variant.label || variant.name || id) };
      }).filter(function (item) { return item.id; });
    }

    function collectAssignment(row) {
      var all = row.querySelector("[data-vp-manufacturer-all-variants]");
      var ids = Array.prototype.map.call(row.querySelectorAll("[data-vp-manufacturer-variant-id]:checked"), function (field) { return text(field.value); });
      return { applies_to_all_variants: !!(all && all.checked), variant_ids: unique(ids) };
    }
    function renderAssignment(row, assignment) {
      var container = row.querySelector("[data-vp-manufacturer-variant-options]");
      var all = row.querySelector("[data-vp-manufacturer-all-variants]");
      if (!container || !all) { return; }
      var selected = Array.isArray(assignment && assignment.variant_ids) ? assignment.variant_ids.map(text) : [];
      var appliesAll = assignment && typeof assignment.applies_to_all_variants === "boolean" ? assignment.applies_to_all_variants : !selected.length;
      container.replaceChildren();
      currentVariants().forEach(function (variant) {
        var label = document.createElement("label");
        var input = document.createElement("input");
        input.type = "checkbox";
        input.value = variant.id;
        input.checked = appliesAll || selected.indexOf(variant.id) >= 0;
        input.disabled = appliesAll;
        input.setAttribute("data-vp-manufacturer-variant-id", "true");
        label.append(input, document.createTextNode(" " + variant.label));
        container.appendChild(label);
      });
      all.checked = appliesAll;
    }

    function coverageMode(row) {
      var selected = row.querySelector("[data-vp-manufacturer-coverage-mode]:checked");
      return selected ? selected.value : "radius";
    }
    function applyCoverageMode(row) {
      var mode = coverageMode(row);
      var radius = row.querySelector("[data-vp-manufacturer-radius-field]");
      var states = row.querySelector("[data-vp-manufacturer-state-fields]");
      if (radius) { radius.hidden = mode !== "radius"; }
      if (states) { states.hidden = mode !== "territories"; }
    }

    function collectLocations() {
      return Array.prototype.map.call(locationRows.querySelectorAll("[data-vp-manufacturer-location-row]"), function (row, index) {
        var assignment = collectAssignment(row);
        var mode = coverageMode(row);
        var states = Array.prototype.map.call(row.querySelectorAll("[data-vp-manufacturer-state]:checked"), function (field) { return field.value; });
        return {
          location_id: row.dataset.vpManufacturerLocationId || "location_" + (index + 1),
          name: rowValue(row, "name"),
          roles: Array.prototype.map.call(row.querySelectorAll("[data-vp-manufacturer-location-role]:checked"), function (field) { return field.value; }),
          address: rowValue(row, "address"),
          formatted_address: rowValue(row, "formatted_address"),
          mapbox_feature_id: rowValue(row, "mapbox_feature_id"),
          country_code: rowValue(row, "country_code") || "DE",
          latitude: numberOrNull(rowValue(row, "latitude")),
          longitude: numberOrNull(rowValue(row, "longitude")),
          coverage_mode: mode,
          radius_km: mode === "radius" ? numberOrNull(rowValue(row, "radius_km")) : null,
          delivery_radius_km: mode === "radius" ? numberOrNull(rowValue(row, "radius_km")) : null,
          territory_codes: mode === "country" ? ["DE"] : states,
          applies_to_all_variants: assignment.applies_to_all_variants,
          variant_ids: assignment.variant_ids
        };
      });
    }

    function buildProfile() {
      var locations = collectLocations();
      return {
        schema_version: "vplib.manufacturer.v2",
        enforced: true,
        scope: "manufacturer",
        manufacturer_bound: true,
        organization: {
          organization_id: organizationValue("organization_id"),
          name: organizationValue("name"),
          brand: organizationValue("brand"),
          website: organizationValue("website"),
          country_code: (organizationValue("country_code") || "DE").toUpperCase(),
          owner_subject: selectedManufacturer && selectedManufacturer.owner_subject || "",
          platform_admin_retains_access: true
        },
        availability: {
          storage: "platform_database_with_package_snapshot",
          coverage_mode: "locations",
          location_count: locations.length,
          territory_count: 0,
          locations: locations,
          territories: []
        }
      };
    }

    function sync(reason) {
      var profile = buildProfile();
      profileField.value = JSON.stringify(profile);
      locationsField.value = JSON.stringify(profile.availability.locations);
      summary.textContent = profile.organization.name ? profile.organization.name + " · " + profile.availability.location_count + " Standorte" : "Hersteller auswählen";
      root.dispatchEvent(new CustomEvent("vectoplan:create:manufacturer-profile-changed", {
        bubbles: true,
        detail: { version: VERSION, reason: reason || "change", manufacturer_profile: profile }
      }));
      return profile;
    }

    function updateLocationLabels() {
      var rows = locationRows.querySelectorAll("[data-vp-manufacturer-location-row]");
      Array.prototype.forEach.call(rows, function (row, index) {
        var label = row.querySelector("[data-vp-manufacturer-location-label]");
        var remove = row.querySelector("[data-vp-remove-manufacturer-location]");
        if (label) { label.textContent = "Standort " + (index + 1); }
        if (remove) { remove.disabled = rows.length <= 1; }
      });
    }

    function selectAddress(row, item) {
      setRowValue(row, "address", item.address || item.formatted_address);
      setRowValue(row, "formatted_address", item.formatted_address || item.address);
      setRowValue(row, "mapbox_feature_id", item.mapbox_feature_id);
      setRowValue(row, "latitude", item.latitude);
      setRowValue(row, "longitude", item.longitude);
      setRowValue(row, "country_code", item.country_code || "DE");
      var suggestions = row.querySelector("[data-vp-manufacturer-address-suggestions]");
      var status = row.querySelector("[data-vp-manufacturer-address-status]");
      suggestions.hidden = true;
      suggestions.replaceChildren();
      if (status) { status.textContent = "Koordinaten gespeichert: " + Number(item.latitude).toFixed(5) + ", " + Number(item.longitude).toFixed(5); status.dataset.tone = "success"; }
      sync("address-selected");
    }

    function geocode(row, query) {
      var suggestions = row.querySelector("[data-vp-manufacturer-address-suggestions]");
      var status = row.querySelector("[data-vp-manufacturer-address-status]");
      if (query.length < 3) { suggestions.hidden = true; return; }
      if (status) { status.textContent = "Mapbox durchsucht Adressen …"; status.dataset.tone = "loading"; }
      fetch(geocodeApi + "?q=" + encodeURIComponent(query) + "&limit=5", { credentials: "same-origin" })
        .then(function (response) { return response.json().then(function (payload) { if (!response.ok) { throw new Error(payload.message || "Adresssuche fehlgeschlagen"); } return payload; }); })
        .then(function (payload) {
          suggestions.replaceChildren();
          (payload.items || []).forEach(function (item) {
            var button = document.createElement("button");
            button.type = "button";
            button.textContent = item.formatted_address || item.address;
            button.addEventListener("click", function () { selectAddress(row, item); });
            suggestions.appendChild(button);
          });
          suggestions.hidden = !(payload.items || []).length;
          if (status) { status.textContent = (payload.items || []).length ? "Adresse aus Trefferliste wählen." : "Keine passende Adresse gefunden."; status.dataset.tone = "info"; }
        })
        .catch(function (error) { if (status) { status.textContent = error.message; status.dataset.tone = "error"; } });
    }

    function addLocation(initial, silent) {
      if (!locationTemplate || !locationTemplate.content) { return; }
      var fragment = locationTemplate.content.cloneNode(true);
      var row = fragment.querySelector("[data-vp-manufacturer-location-row]");
      var item = initial && typeof initial === "object" ? initial : {};
      row.dataset.vpManufacturerLocationId = item.location_id || item.uid || "location_" + (locationRows.children.length + 1);
      ["name", "address", "formatted_address", "mapbox_feature_id", "latitude", "longitude", "country_code"].forEach(function (key) { setRowValue(row, key, item[key]); });
      setRowValue(row, "radius_km", item.radius_km === undefined ? item.delivery_radius_km : item.radius_km);
      var roles = Array.isArray(item.roles) ? item.roles : ["delivery", "distribution"];
      Array.prototype.forEach.call(row.querySelectorAll("[data-vp-manufacturer-location-role]"), function (field) { field.checked = roles.indexOf(field.value) >= 0; });
      var mode = item.coverage_mode || (Array.isArray(item.territory_codes) && item.territory_codes.indexOf("DE") >= 0 ? "country" : Array.isArray(item.territory_codes) && item.territory_codes.length ? "territories" : "radius");
      var modeField = row.querySelector('[data-vp-manufacturer-coverage-mode][value="' + mode + '"]') || row.querySelector('[data-vp-manufacturer-coverage-mode][value="radius"]');
      if (modeField) { modeField.checked = true; }
      var states = Array.isArray(item.territory_codes) ? item.territory_codes : [];
      Array.prototype.forEach.call(row.querySelectorAll("[data-vp-manufacturer-state]"), function (field) { field.checked = states.indexOf(field.value) >= 0; });
      renderAssignment(row, item);
      var address = row.querySelector("[data-vp-manufacturer-address]");
      var timer = 0;
      address.addEventListener("input", function () {
        setRowValue(row, "mapbox_feature_id", ""); setRowValue(row, "latitude", ""); setRowValue(row, "longitude", "");
        window.clearTimeout(timer); timer = window.setTimeout(function () { geocode(row, text(address.value)); }, 280);
      });
      locationRows.appendChild(fragment);
      applyCoverageMode(row);
      updateLocationLabels();
      if (!silent) { sync("location-added"); }
    }

    function fillManufacturer(item) {
      selectedManufacturer = item || null;
      setOrganizationValue("organization_id", item && (item.organization_id || item.uid) || "");
      ["name", "brand", "website", "country_code"].forEach(function (key) { setOrganizationValue(key, item && item[key] || (key === "country_code" ? "DE" : "")); });
      locationRows.replaceChildren();
      (item && Array.isArray(item.locations) ? item.locations : []).forEach(function (location) { addLocation(location, true); });
      if (!locationRows.children.length) { addLocation({ country_code: "DE", radius_km: 100, coverage_mode: "radius", applies_to_all_variants: true }, true); }
      transferPanel.hidden = !(platformAdmin && item && item.uid);
      renderRegistry();
      sync("manufacturer-selected");
      saveStatus.textContent = item ? "Hersteller geladen. Standorte können für alle Produkte wiederverwendet werden." : "Neuen Hersteller vollständig ausfüllen.";
    }

    function renderRegistry() {
      list.replaceChildren();
      registryItems.forEach(function (item) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "vp-create-manufacturer-registry__item";
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", String(!!(selectedManufacturer && selectedManufacturer.uid === item.uid)));
        var title = document.createElement("strong");
        var meta = document.createElement("span");
        title.textContent = item.name;
        meta.textContent = (item.brand || "Keine separate Marke") + " · " + (item.locations || []).length + " Standorte";
        button.append(title, meta);
        button.addEventListener("click", function () { fillManufacturer(item); });
        list.appendChild(button);
      });
      if (!registryItems.length) {
        var empty = document.createElement("p"); empty.textContent = "Noch kein Hersteller für dieses Objekt zugeordnet."; list.appendChild(empty);
      }
    }

    function loadRegistry() {
      var params = new URLSearchParams();
      var ref = familyRef();
      if (ref) { params.set("family_ref", ref); }
      if (includeAll) { params.set("include_all", "true"); }
      if (text(search.value)) { params.set("q", text(search.value)); }
      registryStatus.textContent = "Hersteller werden geladen …";
      fetch(api + "?" + params.toString(), { credentials: "same-origin" })
        .then(function (response) { return response.json().then(function (payload) { if (!response.ok) { throw new Error(payload.message || "Hersteller konnten nicht geladen werden"); } return payload; }); })
        .then(function (payload) {
          registryItems = Array.isArray(payload.items) ? payload.items : [];
          platformAdmin = !!(payload.capabilities && payload.capabilities.platform_admin);
          root.dataset.vpManufacturerPlatformAdmin = String(platformAdmin);
          if (newManufacturerButton) { newManufacturerButton.hidden = !platformAdmin; }
          transferPanel.hidden = !(platformAdmin && selectedManufacturer && selectedManufacturer.uid);
          registryStatus.textContent = registryItems.length + " Hersteller " + (includeAll ? "im Register" : "für dieses Objekt");
          renderRegistry();
        })
        .catch(function (error) { registryItems = []; registryStatus.textContent = error.message; renderRegistry(); });
    }

    function saveManufacturer() {
      var profile = sync("save-requested");
      var payload = Object.assign({}, profile.organization, {
        family_ref: familyRef(),
        locations: profile.availability.locations,
        variant_assignments: {
          schema_version: "vectoplan.manufacturer-family-link.v1",
          source: "wizard",
          variants_defined: currentVariants().map(function (item) { return item.id; }),
          by_location: profile.availability.locations.map(function (location) {
            return {
              location_id: location.location_id,
              applies_to_all_variants: location.applies_to_all_variants,
              variant_ids: location.variant_ids
            };
          })
        }
      });
      var existingId = selectedManufacturer && selectedManufacturer.uid;
      saveStatus.textContent = "Hersteller wird gespeichert …";
      fetch(existingId ? api + "/" + encodeURIComponent(existingId) : api, {
        method: existingId ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload)
      }).then(function (response) {
        return response.json().then(function (result) { if (!response.ok) { throw new Error(result.message || "Speichern fehlgeschlagen"); } return result; });
      }).then(function (result) {
        fillManufacturer(result.item);
        saveStatus.textContent = "Hersteller gespeichert und dem ausgewählten Objekt zugeordnet.";
        loadRegistry();
      }).catch(function (error) { saveStatus.textContent = error.message; });
    }

    root.addEventListener("input", function (event) {
      if (event.target === search) { window.clearTimeout(registryTimer); registryTimer = window.setTimeout(loadRegistry, 220); return; }
      if (!event.target.matches("[data-vp-manufacturer-address]")) { sync("input"); }
    });
    root.addEventListener("change", function (event) {
      var row = event.target.closest("[data-vp-manufacturer-location-row]");
      if (row && event.target.matches("[data-vp-manufacturer-coverage-mode]")) { applyCoverageMode(row); }
      if (row && event.target.matches("[data-vp-manufacturer-all-variants]")) {
        Array.prototype.forEach.call(row.querySelectorAll("[data-vp-manufacturer-variant-id]"), function (field) { field.checked = event.target.checked; field.disabled = event.target.checked; });
      }
      sync("change");
    });
    root.addEventListener("click", function (event) {
      var remove = event.target.closest("[data-vp-remove-manufacturer-location]");
      if (remove) { remove.closest("[data-vp-manufacturer-location-row]").remove(); updateLocationLabels(); sync("location-removed"); }
    });
    root.querySelector("[data-vp-add-manufacturer-location]").addEventListener("click", function () { addLocation({ country_code: "DE", radius_km: 100, coverage_mode: "radius", applies_to_all_variants: true }); });
    newManufacturerButton.addEventListener("click", function () { fillManufacturer(null); });
    root.querySelector("[data-vp-manufacturer-show-family]").addEventListener("click", function () { includeAll = false; loadRegistry(); });
    root.querySelector("[data-vp-manufacturer-show-all]").addEventListener("click", function () { includeAll = true; loadRegistry(); });
    root.querySelector("[data-vp-manufacturer-save]").addEventListener("click", saveManufacturer);
    root.querySelector("[data-vp-manufacturer-transfer]").addEventListener("click", function () {
      var account = text(root.querySelector("[data-vp-manufacturer-transfer-account]").value);
      if (!selectedManufacturer || !account) { saveStatus.textContent = "Zuerst Hersteller und Ziel-Account auswählen."; return; }
      fetch(api + "/" + encodeURIComponent(selectedManufacturer.uid) + "/transfer", {
        method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" }, credentials: "same-origin",
        body: JSON.stringify({ new_owner_account_id: account, family_ref: familyRef(), required_auth_role: "manufacturer" })
      }).then(function (response) { return response.json().then(function (payload) { if (!response.ok) { throw new Error(payload.message || "Übertragung fehlgeschlagen"); } return payload; }); })
        .then(function (payload) { fillManufacturer(payload.item); saveStatus.textContent = "Eigentum übertragen. Plattform-Adminzugriff bleibt erhalten."; })
        .catch(function (error) { saveStatus.textContent = error.message; });
    });
    ["vectoplan:create:variant-state-changed", "vectoplan:create:variant-values-changed"].forEach(function (name) {
      document.addEventListener(name, function () { Array.prototype.forEach.call(locationRows.querySelectorAll("[data-vp-manufacturer-location-row]"), function (row) { renderAssignment(row, collectAssignment(row)); }); sync("variants-changed"); });
    });
    document.addEventListener("vectoplan:create:library-source-selected", loadRegistry);
    if (form) { form.addEventListener("submit", function () { sync("submit"); }, true); }

    var initial = parseJson(profileField.value, {});
    var initialOrg = initial.organization || {};
    var initialLocations = initial.availability && Array.isArray(initial.availability.locations) ? initial.availability.locations : parseJson(locationsField.value, []);
    if (initialOrg.organization_id) {
      fillManufacturer(Object.assign({}, initialOrg, { uid: initialOrg.organization_id, locations: initialLocations }));
    } else {
      fillManufacturer(null);
    }
    loadRegistry();
    root.dataset.vpManufacturerProfileReady = "true";
    root.dataset.vpManufacturerProfileVersion = VERSION;
  }

  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", boot, { once: true }); }
  else { boot(); }
})();
