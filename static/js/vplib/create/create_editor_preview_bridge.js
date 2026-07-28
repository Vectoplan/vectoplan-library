(function () {
  "use strict";

  var CONTRACT = "vectoplan-generator-preview.v1";
  var UPDATE_MESSAGE = "vectoplan.generator-preview.update";
  var READY_MESSAGE = "vectoplan.generator-preview.ready";
  var RESULT_MESSAGE = "vectoplan.generator-preview.result";
  var ERROR_MESSAGE = "vectoplan.generator-preview.error";
  var ROOT_SELECTOR = "[data-vp-create-preview]";
  var FRAME_SELECTOR = "[data-vp-editor-generator-preview-frame]";
  var STATUS_SELECTOR = "[data-vp-editor-generator-preview-status]";
  var MAX_FILES = 32;
  var MAX_FILE_BYTES = 64 * 1024 * 1024;

  function asText(value, fallback, maxLength) {
    var result = value === undefined || value === null ? "" : String(value).trim();
    if (!result) {
      result = fallback || "";
    }
    return result.slice(0, maxLength || 512);
  }

  function asNumber(value, fallback, min, max) {
    var parsed = Number.parseFloat(String(value === undefined ? "" : value).replace(",", "."));
    if (!Number.isFinite(parsed)) {
      parsed = fallback;
    }
    return Math.min(max, Math.max(min, parsed));
  }

  function asInteger(value, fallback, min, max) {
    return Math.round(asNumber(value, fallback, min, max));
  }

  function readValue(form, name, fallback) {
    var elements = Array.prototype.slice.call(form.querySelectorAll('[name="' + name + '"]'));
    var selected = elements.find(function (element) {
      return (element.type === "radio" || element.type === "checkbox") && element.checked;
    });
    if (selected) {
      return asText(selected.value, fallback);
    }
    var usable = elements.find(function (element) {
      return !element.disabled && asText(element.value, "");
    });
    return usable ? asText(usable.value, fallback) : fallback;
  }

  function readLegacyState() {
    try {
      if (
        window.VectoplanCreatePreview &&
        typeof window.VectoplanCreatePreview.getState === "function"
      ) {
        return window.VectoplanCreatePreview.getState() || {};
      }
    } catch (error) {
      // The iframe bridge is independent of the legacy placeholder state.
    }
    return {};
  }

  function collectRawValues(form) {
    var raw = {};
    Array.prototype.forEach.call(form.elements || [], function (element) {
      if (!element || !element.name || element.disabled) {
        return;
      }
      if (/_uploads_json$/i.test(element.name)) {
        return;
      }
      if (element.type === "file" || element.type === "submit" || element.type === "button") {
        return;
      }
      if ((element.type === "radio" || element.type === "checkbox") && !element.checked) {
        return;
      }
      var value = asText(element.value, "", 2_000);
      if (value && Object.keys(raw).length < 256) {
        raw[element.name] = value;
      }
    });
    return raw;
  }

  function collectFiles(form) {
    var result = [];
    var selectors = [
      'input[type="file"][name="geometry_model_files"]',
      'input[type="file"][name="texture_files"]',
    ];
    selectors.forEach(function (selector) {
      var input = form.querySelector(selector);
      if (!input || !input.files) {
        return;
      }
      Array.prototype.forEach.call(input.files, function (file) {
        if (result.length < MAX_FILES && file.size <= MAX_FILE_BYTES) {
          result.push(file);
        }
      });
    });
    return result;
  }

  function buildPayload(form) {
    var legacy = readLegacyState();
    var raw = collectRawValues(form);
    var width = asNumber(readValue(form, "geometry_width", legacy.width || "1"), 1, 0.0001, 10_000);
    var height = asNumber(readValue(form, "geometry_height", legacy.height || "1"), 1, 0.0001, 10_000);
    var depth = asNumber(readValue(form, "geometry_depth", legacy.depth || "1"), 1, 0.0001, 10_000);

    return {
      familyName: readValue(form, "family_name", "Library-Baustein"),
      familySlug: readValue(form, "family_slug", ""),
      objectKind: readValue(form, "object_kind", legacy.objectKind || "cell_block"),
      variantId: readValue(form, "default_variant_id", "default"),
      materialClass: readValue(form, "material_class", "default"),
      colorHint:
        readValue(form, "material.color_hint", "") ||
        readValue(form, "color_hint", ""),
      geometry: {
        shape: readValue(form, "primitive_shape", legacy.shape || "block"),
        width: width,
        height: height,
        depth: depth,
        unit: readValue(form, "geometry_unit", legacy.unit || "m"),
        cellsX: asInteger(readValue(form, "editor_cells_x", legacy.cellsX || "1"), 1, 1, 1_024),
        cellsY: asInteger(readValue(form, "editor_cells_y", legacy.cellsY || "1"), 1, 1, 1_024),
        cellsZ: asInteger(readValue(form, "editor_cells_z", legacy.cellsZ || "1"), 1, 1, 1_024),
      },
      raw: raw,
    };
  }

  function start() {
    var root = document.querySelector(ROOT_SELECTOR);
    var frame = root && root.querySelector(FRAME_SELECTOR);
    var status = root && root.querySelector(STATUS_SELECTOR);
    var form = root && root.closest("form");
    if (!root || !frame || !form) {
      return;
    }

    var targetOrigin = asText(root.dataset.editorPreviewTargetOrigin, "");
    if (!targetOrigin) {
      try {
        targetOrigin = new URL(frame.src, window.location.href).origin;
      } catch (error) {
        return;
      }
    }

    var sequence = 0;
    var ready = false;
    var destroyed = false;
    var debounceTimer = 0;
    var readyTimer = 0;
    var queuedReason = "initial";
    var lastFingerprint = "";

    function setStatus(message, state) {
      root.dataset.editorPreviewState = state;
      if (status) {
        status.textContent = message;
        status.dataset.status = state;
      }
    }

    function publish(reason) {
      queuedReason = reason || "form-change";
      if (!ready || destroyed || !frame.contentWindow) {
        return false;
      }
      var nextPayload = buildPayload(form);
      var nextAssets = collectFiles(form);
      var fingerprint = JSON.stringify({
        payload: nextPayload,
        assets: nextAssets.map(function (file) {
          return [file.name, file.size, file.type, file.lastModified];
        }),
      });
      if (queuedReason !== "editor-ready" && fingerprint === lastFingerprint) {
        root.dataset.editorPreviewLastReason = "duplicate-skipped";
        return false;
      }
      lastFingerprint = fingerprint;
      sequence += 1;
      frame.contentWindow.postMessage(
        {
          contract: CONTRACT,
          type: UPDATE_MESSAGE,
          sequence: sequence,
          reason: queuedReason,
          payload: nextPayload,
          assets: nextAssets,
        },
        targetOrigin
      );
      root.dataset.editorPreviewSequence = String(sequence);
      root.dataset.editorPreviewLastReason = queuedReason;
      return true;
    }

    function schedule(reason, delay) {
      queuedReason = reason || queuedReason;
      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(function () {
        publish(queuedReason);
      }, typeof delay === "number" ? delay : 90);
    }

    function onMessage(event) {
      if (
        destroyed ||
        event.origin !== targetOrigin ||
        event.source !== frame.contentWindow ||
        !event.data ||
        event.data.contract !== CONTRACT
      ) {
        return;
      }
      if (event.data.type === READY_MESSAGE) {
        ready = true;
        window.clearTimeout(readyTimer);
        root.dataset.editorPreviewReady = "true";
        setStatus("Editor-Vorschau verbunden", "ready");
        publish("editor-ready");
        return;
      }
      if (event.data.type === RESULT_MESSAGE) {
        setStatus(
          event.data.renderer === "uploaded-model"
            ? "3D-Modell im Editor geladen"
            : "Editor-Vorschau aktuell",
          "ready"
        );
        return;
      }
      if (event.data.type === ERROR_MESSAGE) {
        setStatus(asText(event.data.message, "3D-Modell konnte nicht geladen werden"), "error");
      }
    }

    function onFormEvent(event) {
      if (!event.target || !form.contains(event.target)) {
        return;
      }
      var immediate = event.type === "change" && event.target.type === "file";
      schedule(immediate ? "file-change" : "form-change", immediate ? 0 : 90);
    }

    function onPreviewEvent(event) {
      var reason = event && event.type ? event.type : "generator-event";
      schedule(reason, 50);
    }

    frame.addEventListener("load", function () {
      ready = false;
      root.dataset.editorPreviewReady = "false";
      setStatus("Editor-Vorschau wird verbunden …", "loading");
    });
    form.addEventListener("input", onFormEvent);
    form.addEventListener("change", onFormEvent);
    window.addEventListener("message", onMessage);
    [
      "vectoplan:create:preview-updated",
      "vectoplan:create:upload-changed",
      "vectoplan:create:variant-changed",
      "vp:create:preview-updated",
      "vp:create:upload-changed",
      "vp:create:variant-changed",
    ].forEach(function (eventName) {
      window.addEventListener(eventName, onPreviewEvent);
    });

    readyTimer = window.setTimeout(function () {
      if (!ready) {
        setStatus("Editor nicht erreichbar – Service auf Port 5100 prüfen", "error");
      }
    }, 12_000);

    window.VectoplanCreateEditorPreviewBridge = {
      contract: CONTRACT,
      publish: publish,
      getState: function () {
        return {
          ready: ready,
          sequence: sequence,
          targetOrigin: targetOrigin,
          payload: buildPayload(form),
          files: collectFiles(form).map(function (file) {
            return { name: file.name, size: file.size, type: file.type };
          }),
        };
      },
      destroy: function () {
        destroyed = true;
        window.clearTimeout(debounceTimer);
        window.clearTimeout(readyTimer);
        form.removeEventListener("input", onFormEvent);
        form.removeEventListener("change", onFormEvent);
        window.removeEventListener("message", onMessage);
      },
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
