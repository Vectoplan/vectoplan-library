(function () {
  "use strict";

  var VERSION = "1.1.0";

  function boot() {
    var root = document.querySelector("[data-vp-spatial-root]");
    if (!root || root.getAttribute("data-vp-spatial-ready") === "true") {
      return;
    }

    var form = root.closest("form");
    var list = root.querySelector("[data-vp-connector-list]");
    var empty = root.querySelector("[data-vp-connector-empty]");
    var addButton = root.querySelector("[data-vp-connector-add]");
    var template = document.querySelector("template[data-vp-connector-template]");
    var connectorsField = root.querySelector("[data-vp-connection-points-json]");
    var contractField = root.querySelector("[data-vp-spatial-contract-json]");
    var summary = root.querySelector("[data-vp-spatial-summary]");
    var modeFields = Array.prototype.slice.call(root.querySelectorAll('[name="spatial_mode"]'));
    var uniformField = root.querySelector("[data-vp-scale-uniform]");
    var scaleFields = Array.prototype.slice.call(root.querySelectorAll("[data-vp-model-scale]"));

    function parseJson(value, fallback) {
      try {
        var parsed = JSON.parse(String(value || ""));
        return parsed !== null ? parsed : fallback;
      } catch (error) {
        return fallback;
      }
    }

    function read(name, fallback) {
      var field = form && form.querySelector('[name="' + name + '"]');
      return field && String(field.value || "").trim() ? String(field.value).trim() : fallback;
    }

    function number(value, fallback, minimum) {
      var parsed = Number(String(value === undefined ? "" : value).replace(",", "."));
      if (!Number.isFinite(parsed)) {
        parsed = fallback;
      }
      return Math.max(minimum === undefined ? -Infinity : minimum, parsed);
    }

    function integer(value, fallback) {
      return Math.max(1, Math.round(number(value, fallback, 1)));
    }

    function slug(value, fallback) {
      var normalized = String(value || "")
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9äöüß]+/g, "_")
        .replace(/^_+|_+$/g, "");
      return normalized || fallback;
    }

    function currentMode() {
      var checked = root.querySelector('[name="spatial_mode"]:checked');
      return checked ? checked.value : "contained";
    }

    function fieldValue(row, key, fallback) {
      var field = row.querySelector('[data-vp-connector-field="' + key + '"]');
      return field && String(field.value || "").trim() ? String(field.value).trim() : fallback;
    }

    function connectorFromRow(row, index) {
      var label = fieldValue(row, "label", "Anschluss " + (index + 1));
      var compatible = fieldValue(row, "compatible_types", "")
        .split(",")
        .map(function (item) { return slug(item, ""); })
        .filter(Boolean);

      return {
        connector_id: row.getAttribute("data-vp-connector-id") || slug(label, "connector_" + (index + 1)),
        label: label,
        interface_type: fieldValue(row, "interface_type", "generic"),
        role: fieldValue(row, "role", "bidirectional"),
        coordinate_space: "local",
        position: {
          x: number(fieldValue(row, "position_x", "0"), 0),
          y: number(fieldValue(row, "position_y", "0"), 0),
          z: number(fieldValue(row, "position_z", "0"), 0),
          unit: read("geometry_unit", "m")
        },
        normal: {
          x: number(fieldValue(row, "normal_x", "0"), 0),
          y: number(fieldValue(row, "normal_y", "1"), 1),
          z: number(fieldValue(row, "normal_z", "0"), 0)
        },
        snap_radius: number(fieldValue(row, "snap_radius", "0.05"), 0.05, 0),
        compatible_types: compatible
      };
    }

    function collectConnectors() {
      return Array.prototype.slice.call(list.querySelectorAll("[data-vp-connector-row]")).map(connectorFromRow);
    }

    function setRowValue(row, key, value) {
      var field = row.querySelector('[data-vp-connector-field="' + key + '"]');
      if (field && value !== undefined && value !== null) {
        field.value = Array.isArray(value) ? value.join(", ") : String(value);
      }
    }

    function addConnector(initial) {
      if (!template || !template.content || !list) {
        return;
      }
      var fragment = template.content.cloneNode(true);
      var row = fragment.querySelector("[data-vp-connector-row]");
      var count = list.querySelectorAll("[data-vp-connector-row]").length;
      var item = initial && typeof initial === "object" ? initial : {};
      var connectorId = item.connector_id || item.id || "connector_" + (count + 1);

      row.setAttribute("data-vp-connector-id", slug(connectorId, "connector_" + (count + 1)));
      setRowValue(row, "label", item.label || "");
      setRowValue(row, "interface_type", item.interface_type || item.type || "generic");
      setRowValue(row, "role", item.role || "bidirectional");
      setRowValue(row, "position_x", item.position && item.position.x);
      setRowValue(row, "position_y", item.position && item.position.y);
      setRowValue(row, "position_z", item.position && item.position.z);
      setRowValue(row, "normal_x", item.normal && item.normal.x);
      setRowValue(row, "normal_y", item.normal && item.normal.y);
      setRowValue(row, "normal_z", item.normal && item.normal.z);
      setRowValue(row, "snap_radius", item.snap_radius);
      setRowValue(row, "compatible_types", item.compatible_types || []);

      list.appendChild(fragment);
      refreshNumbers();
      sync("connector-added");
    }

    function refreshNumbers() {
      var rows = Array.prototype.slice.call(list.querySelectorAll("[data-vp-connector-row]"));
      rows.forEach(function (row, index) {
        var numberNode = row.querySelector("[data-vp-connector-number]");
        if (numberNode) {
          numberNode.textContent = "Anschluss " + (index + 1);
        }
      });
      if (empty) {
        empty.hidden = rows.length > 0;
      }
    }

    function buildContract() {
      var mode = currentMode();
      var cells = {
        x: integer(read("editor_cells_x", "1"), 1),
        y: integer(read("editor_cells_y", "1"), 1),
        z: integer(read("editor_cells_z", "1"), 1)
      };
      var dimensions = {
        width: number(read("geometry_width", "1"), 1, 0.0001),
        height: number(read("geometry_height", "1"), 1, 0.0001),
        depth: number(read("geometry_depth", "1"), 1, 0.0001),
        unit: read("geometry_unit", "m")
      };
      var source = read("zone_source", "manual_dimensions");
      var clearance = {};
      var clearanceDistances = [];
      Array.prototype.slice.call(root.querySelectorAll("[data-vp-clearance-side]")).forEach(function (row) {
        var side = row.getAttribute("data-vp-clearance-side") || "";
        var enabled = row.querySelector("[data-vp-clearance-enabled]");
        var distance = row.querySelector("[data-vp-clearance-value]");
        var normalizedDistance = number(distance && distance.value, 0, 0);
        clearance[side] = {
          enabled: !!(enabled && enabled.checked),
          distance: enabled && enabled.checked ? normalizedDistance : 0,
          unit: read("geometry_unit", "m")
        };
        if (clearance[side].enabled) {
          clearanceDistances.push(normalizedDistance);
        }
      });
      var margin = clearanceDistances.length ? Math.max.apply(Math, clearanceDistances) : 0;
      var legacyMargin = root.querySelector("[data-vp-zone-margin]");
      if (legacyMargin) {
        legacyMargin.value = String(margin);
      }
      var scaleInBlocks = {
        x: number(read("model_scale_x", "1"), 1, 0.1),
        y: number(read("model_scale_y", "1"), 1, 0.1),
        z: number(read("model_scale_z", "1"), 1, 0.1)
      };
      var blockSize = {
        x: dimensions.width / cells.x,
        y: dimensions.height / cells.y,
        z: dimensions.depth / cells.z,
        unit: dimensions.unit
      };
      var modelDriven = mode === "asset_driven" || mode === "hybrid";
      var occupiedCells = modelDriven ? {
        x: Math.max(1, Math.ceil(scaleInBlocks.x)),
        y: Math.max(1, Math.ceil(scaleInBlocks.y)),
        z: Math.max(1, Math.ceil(scaleInBlocks.z))
      } : cells;
      var zoneDimensions = modelDriven ? {
        width: blockSize.x * occupiedCells.x,
        height: blockSize.y * occupiedCells.y,
        depth: blockSize.z * occupiedCells.z,
        unit: dimensions.unit
      } : dimensions;

      return {
        schema_version: "vplib.spatial.v1",
        mode: mode,
        primary_asset_role: mode === "contained" ? "embedded_geometry" : "zone_driver",
        model_transform: {
          unit_basis: "editor_cell",
          uniform: !!(uniformField && uniformField.checked),
          scale_in_blocks: scaleInBlocks,
          block_reference: blockSize,
          resulting_size: {
            x: blockSize.x * scaleInBlocks.x,
            y: blockSize.y * scaleInBlocks.y,
            z: blockSize.z * scaleInBlocks.z,
            unit: dimensions.unit
          }
        },
        zone: {
          source: source,
          shape: read("zone_shape", "box"),
          auto_fit: mode !== "contained" && source !== "manual_dimensions",
          margin: margin,
          clearance: clearance,
          unit: dimensions.unit,
          dimensions: zoneDimensions,
          grid: {
            occupancy: "rectangular_span",
            cells: occupiedCells,
            cell_size: blockSize
          }
        },
        connectors: collectConnectors()
      };
    }

    function sync(reason) {
      var contract = buildContract();
      var json = JSON.stringify(contract);
      var cards = root.querySelectorAll(".vp-create-spatial-mode");

      root.setAttribute("data-vp-spatial-mode", contract.mode);
      Array.prototype.forEach.call(cards, function (card) {
        var input = card.querySelector('input[type="radio"]');
        card.classList.toggle("is-selected", !!(input && input.checked));
      });
      if (connectorsField) {
        connectorsField.value = JSON.stringify(contract.connectors);
      }
      if (contractField) {
        contractField.value = json;
      }
      if (summary) {
        var cells = contract.zone.grid.cells;
        var modeLabel = contract.mode === "asset_driven" ? "Modellzone" : contract.mode === "hybrid" ? "Hybridzone" : "Blockzone";
        summary.textContent = cells.x + " × " + cells.y + " × " + cells.z + " · " + modeLabel + " · " + contract.connectors.length + " Anschlüsse";
      }
      updateScaleOutputs(contract);

      root.dispatchEvent(new CustomEvent("vectoplan:create:spatial-contract-changed", {
        bubbles: true,
        detail: { version: VERSION, reason: reason || "change", spatial_contract: contract }
      }));
    }

    function updateScaleOutputs(contract) {
      var current = contract || buildContract();
      scaleFields.forEach(function (field) {
        var axis = field.getAttribute("data-vp-model-scale");
        var output = root.querySelector('[data-vp-scale-output="' + axis + '"]');
        var value = current.model_transform.scale_in_blocks[axis];
        var size = current.model_transform.resulting_size[axis];
        if (output) {
          output.textContent = value.toFixed(2).replace(".", ",") + " × Block · " + size.toFixed(2).replace(".", ",") + " " + current.model_transform.resulting_size.unit;
        }
      });
      root.setAttribute("data-vp-scale-uniform", current.model_transform.uniform ? "true" : "false");
    }

    function handleScaleInput(field) {
      if (uniformField && uniformField.checked) {
        scaleFields.forEach(function (candidate) {
          if (candidate !== field) {
            candidate.value = field.value;
          }
        });
      }
      sync("model-scale");
    }

    function handleModeChange(event) {
      var mode = currentMode();
      var source = root.querySelector("[data-vp-zone-source]");
      if (source && mode !== "contained" && source.value === "manual_dimensions") {
        source.value = "primary_model_bounds";
      }

      var kind = form && form.querySelector("[data-vp-geometry-object-kind-select]");
      if (kind && mode !== "contained" && kind.value === "cell_block") {
        kind.value = "multi_cell_module";
        kind.dispatchEvent(new Event("change", { bubbles: true }));
      }
      sync(event ? "mode-changed" : "init");
    }

    if (addButton) {
      addButton.addEventListener("click", function () { addConnector({}); });
    }
    list.addEventListener("click", function (event) {
      var remove = event.target.closest("[data-vp-connector-remove]");
      if (!remove) {
        return;
      }
      var row = remove.closest("[data-vp-connector-row]");
      if (row) {
        row.remove();
        refreshNumbers();
        sync("connector-removed");
      }
    });
    root.addEventListener("input", function (event) {
      if (event.target.matches("[data-vp-model-scale]")) {
        handleScaleInput(event.target);
        return;
      }
      if (!event.target.matches('[name="spatial_mode"]')) {
        sync("input");
      }
    });
    root.addEventListener("change", function (event) {
      if (event.target.matches('[name="spatial_mode"]')) {
        handleModeChange(event);
      } else if (event.target.matches("[data-vp-scale-uniform]")) {
        if (event.target.checked && scaleFields.length) {
          handleScaleInput(scaleFields[0]);
        } else {
          sync("scale-link-changed");
        }
      } else if (event.target.matches("[data-vp-clearance-enabled]")) {
        var clearanceRow = event.target.closest("[data-vp-clearance-side]");
        var clearanceValue = clearanceRow && clearanceRow.querySelector("[data-vp-clearance-value]");
        if (clearanceValue) {
          clearanceValue.disabled = !event.target.checked;
        }
        sync("clearance-toggle");
      } else {
        sync("change");
      }
    });
    if (form) {
      form.addEventListener("input", function (event) {
        if (/^(geometry_|editor_cells_)/.test(event.target.name || "")) {
          sync("geometry-input");
        }
      });
      form.addEventListener("submit", function () { sync("submit"); }, true);
    }

    var initialContract = parseJson(contractField && contractField.value, {});
    var initialConnectors = Array.isArray(initialContract.connectors)
      ? initialContract.connectors
      : parseJson(connectorsField && connectorsField.value, []);
    if (Array.isArray(initialConnectors)) {
      initialConnectors.forEach(addConnector);
    }
    refreshNumbers();
    Array.prototype.slice.call(root.querySelectorAll("[data-vp-clearance-side]")).forEach(function (row) {
      var enabled = row.querySelector("[data-vp-clearance-enabled]");
      var value = row.querySelector("[data-vp-clearance-value]");
      if (value) {
        value.disabled = !(enabled && enabled.checked);
      }
    });
    handleModeChange(null);
    root.setAttribute("data-vp-spatial-ready", "true");
    root.setAttribute("data-vp-spatial-version", VERSION);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
