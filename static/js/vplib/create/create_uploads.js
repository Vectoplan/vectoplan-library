/* services/vectoplan-library/static/js/vplib/create/create_uploads.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateUploads";
  var COMPONENT_NAME = "VECTOPLAN Create Uploads";
  var COMPONENT_VERSION = "0.7.0";

  var ROOT_READY_ATTR = "data-vp-create-uploads-runtime-ready";
  var ROOT_EVENTS_BOUND_ATTR = "data-vp-create-uploads-global-events-bound";
  var ZONE_READY_ATTR = "data-vp-upload-zone-ready";
  var INPUT_BOUND_ATTR = "data-vp-upload-bound";
  var SYNCING_ATTR = "data-vp-upload-syncing";

  var ZONE_SELECTOR = [
    "[data-vp-upload-zone]",
    "[data-create-upload-zone]",
    "[data-vp-upload]"
  ].join(",");

  var INPUT_SELECTOR = [
    "[data-vp-upload-input]",
    "input[type='file'][data-vp-upload-kind]",
    "input[type='file'][name='geometry_model_files']",
    "input[type='file'][name='technical_document_files']",
    "input[type='file'][name^='variant_document_files']"
  ].join(",");

  var DEFAULTS = {
    maxFiles: 12,
    maxFileSizeBytes: 250 * 1024 * 1024,
    backendEnabled: true,
    localOnly: true,
    allowedExtensions: {
      geometry_model: ["glb", "gltf", "obj", "fbx", "stl", "zip"],
      technical_documents: ["pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "md", "png", "jpg", "jpeg", "webp", "zip"],
      variant_documents: ["pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "md", "png", "jpg", "jpeg", "webp", "zip"]
    }
  };

  var runtimeState = {
    version: COMPONENT_VERSION,
    initialized: false,
    readyDispatched: false,
    syncCount: 0,
    eventCount: 0,
    skippedReentrantSyncCount: 0,
    lastSyncAt: "",
    lastError: null,
    lastConfig: null
  };

  function warn(message, error) {
    try {
      if (window.console && typeof window.console.warn === "function") {
        window.console.warn("[" + COMPONENT_NAME + "] " + message, error || "");
      }
    } catch (consoleError) {
      /* no-op */
    }
  }

  function toArray(value) {
    try {
      return Array.prototype.slice.call(value || []);
    } catch (error) {
      return [];
    }
  }

  function timestamp() {
    try {
      return new Date().toISOString();
    } catch (error) {
      return "";
    }
  }

  function dispatch(node, eventName, detail, options) {
    try {
      if (!node || !eventName) {
        return null;
      }

      var safeOptions = options || {};
      var event = new CustomEvent(eventName, {
        bubbles: safeOptions.bubbles !== false,
        cancelable: !!safeOptions.cancelable,
        detail: detail || {}
      });

      node.dispatchEvent(event);
      runtimeState.eventCount += 1;

      return event;
    } catch (error) {
      runtimeState.lastError = normalizeError(error);
      warn("Event dispatch failed: " + eventName, error);
      return null;
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

  function normalizeToken(value, fallbackValue) {
    try {
      var normalized = String(value || "")
        .trim()
        .toLowerCase()
        .replace(/ä/g, "ae")
        .replace(/ö/g, "oe")
        .replace(/ü/g, "ue")
        .replace(/ß/g, "ss")
        .replace(/[-\s]+/g, "_")
        .replace(/[^a-z0-9_./[\]]/g, "")
        .replace(/_{2,}/g, "_")
        .replace(/^_+|_+$/g, "");

      return normalized || fallbackValue || "";
    } catch (error) {
      return fallbackValue || "";
    }
  }

  function readBool(value, fallbackValue) {
    try {
      if (value === true || value === false) {
        return value;
      }

      var text = String(value || "").trim().toLowerCase();

      if (["true", "1", "yes", "ja", "on", "enabled", "active", "ok", "ready"].indexOf(text) >= 0) {
        return true;
      }

      if (["false", "0", "no", "nein", "off", "disabled", "inactive"].indexOf(text) >= 0) {
        return false;
      }

      return !!fallbackValue;
    } catch (error) {
      return !!fallbackValue;
    }
  }

  function safeJsonParse(value, fallbackValue) {
    try {
      if (value && typeof value === "object") {
        return value;
      }

      if (value === null || value === undefined || String(value).trim() === "") {
        return fallbackValue;
      }

      return JSON.parse(String(value));
    } catch (error) {
      return fallbackValue;
    }
  }

  function fileSizeLabel(bytes) {
    try {
      var value = parseInt(bytes, 10);

      if (!Number.isFinite(value) || value <= 0) {
        return "0 B";
      }

      if (value < 1024) {
        return value + " B";
      }

      if (value < 1024 * 1024) {
        return (value / 1024).toFixed(1).replace(".0", "") + " KB";
      }

      if (value < 1024 * 1024 * 1024) {
        return (value / (1024 * 1024)).toFixed(1).replace(".0", "") + " MB";
      }

      return (value / (1024 * 1024 * 1024)).toFixed(1).replace(".0", "") + " GB";
    } catch (error) {
      return "";
    }
  }

  function extensionFromName(fileName) {
    try {
      var text = String(fileName || "").trim();

      if (!text || text.indexOf(".") < 0) {
        return "";
      }

      return text.split(".").pop().toLowerCase();
    } catch (error) {
      return "";
    }
  }

  function cssEscape(value) {
    try {
      if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(String(value || ""));
      }

      return String(value || "").replace(/["\\]/g, "\\$&");
    } catch (error) {
      return String(value || "");
    }
  }

  function getCreateContext() {
    try {
      return window.VectoplanCreateContext || {};
    } catch (error) {
      return {};
    }
  }

  function getGeneratorContext() {
    try {
      var context = getCreateContext();
      return window.VectoplanGeneratorContext ||
        context.generatorContext ||
        context.generator_context ||
        {};
    } catch (error) {
      return {};
    }
  }

  function getUploadConfig() {
    try {
      var context = getCreateContext();
      var generator = getGeneratorContext();
      var generatorData = generator.data || generator.payload || generator.generator_data || generator.generatorData || generator || {};
      var config = Object.assign(
        {},
        generatorData.upload_config || {},
        generatorData.uploads || {},
        context.uploadConfig || {},
        context.uploads || {},
        window.VectoplanCreateUploadConfig || {}
      );

      runtimeState.lastConfig = config;

      return config;
    } catch (error) {
      return {};
    }
  }

  function getConfigValue(names, fallbackValue) {
    try {
      var config = getUploadConfig();

      for (var index = 0; index < names.length; index += 1) {
        var name = names[index];

        if (config && config[name] !== undefined && config[name] !== null && config[name] !== "") {
          return config[name];
        }
      }

      return fallbackValue;
    } catch (error) {
      return fallbackValue;
    }
  }

  function getClosestZone(input) {
    try {
      if (!input || !input.closest) {
        return null;
      }

      return input.closest(ZONE_SELECTOR);
    } catch (error) {
      return null;
    }
  }

  function getZoneInput(zone) {
    try {
      if (!zone) {
        return null;
      }

      if (zone.matches && zone.matches("input[type='file']")) {
        return zone;
      }

      return zone.querySelector(INPUT_SELECTOR);
    } catch (error) {
      return null;
    }
  }

  function getZoneMetadataField(zone, input) {
    try {
      if (!zone) {
        return null;
      }

      var explicitField = zone.getAttribute("data-vp-upload-metadata-field") ||
        (input ? input.getAttribute("data-vp-upload-metadata-field") : "") ||
        "";

      if (explicitField) {
        var byName = zone.querySelector('[name="' + cssEscape(explicitField) + '"]') ||
          document.querySelector('[name="' + cssEscape(explicitField) + '"]');

        if (byName) {
          return byName;
        }
      }

      return zone.querySelector("[data-vp-upload-metadata]") ||
        zone.querySelector("[data-vp-geometry-model-upload-metadata='true']") ||
        zone.querySelector("[data-vp-technical-document-upload-metadata='true']") ||
        zone.querySelector("[data-vp-variant-document-upload-metadata='true']") ||
        zone.querySelector("input[type='hidden'][name$='_uploads_json']") ||
        zone.querySelector("input[type='hidden'][name^='variant_document_uploads']");
    } catch (error) {
      return null;
    }
  }

  function getUploadKind(zone, input) {
    try {
      var raw = "";
      var name = input && input.name ? String(input.name) : "";

      if (input) {
        raw = input.getAttribute("data-vp-upload-kind") || "";
      }

      if (!raw && zone) {
        raw = zone.getAttribute("data-vp-upload-kind") || "";
      }

      if (!raw && name === "geometry_model_files") {
        raw = "geometry_model";
      }

      if (!raw && name === "technical_document_files") {
        raw = "technical_documents";
      }

      if (!raw && name.indexOf("variant_document_files") === 0) {
        raw = "variant_documents";
      }

      return normalizeToken(raw, "generic_upload");
    } catch (error) {
      return "generic_upload";
    }
  }

  function getUploadPurpose(zone, input, kind) {
    try {
      var raw = "";

      if (input) {
        raw = input.getAttribute("data-vp-upload-purpose") || "";
      }

      if (!raw && zone) {
        raw = zone.getAttribute("data-vp-upload-purpose") || "";
      }

      if (!raw && kind === "technical_documents") {
        raw = "manufacturer_documents";
      }

      if (!raw && kind === "variant_documents") {
        raw = "variant_document_list";
      }

      if (!raw && kind === "geometry_model") {
        raw = "geometry_model";
      }

      return normalizeToken(raw, kind || "upload");
    } catch (error) {
      return kind || "upload";
    }
  }

  function getFieldKey(zone, input) {
    try {
      var raw = "";

      if (input) {
        raw = input.getAttribute("data-vp-field-key") ||
          input.getAttribute("data-vp-variable-key") ||
          "";
      }

      if (!raw && zone) {
        raw = zone.getAttribute("data-vp-field-key") ||
          zone.getAttribute("data-vp-variable-key") ||
          "";
      }

      if (!raw && input && input.name) {
        var match = String(input.name).match(/\[([^\]]+)\]/);
        if (match && match[1]) {
          raw = match[1];
        }
      }

      return raw || "";
    } catch (error) {
      return "";
    }
  }

  function getAllowedExtensions(kind, input) {
    try {
      var config = getUploadConfig();
      var fromInput = input && input.accept
        ? String(input.accept)
          .split(",")
          .map(function (item) {
            return item.trim().replace(/^\./, "").toLowerCase();
          })
          .filter(Boolean)
        : [];

      if (fromInput.length) {
        return fromInput;
      }

      var configExtensions = config.allowed_extensions ||
        config.allowedExtensions ||
        [];

      if (Array.isArray(configExtensions) && configExtensions.length) {
        return normalizeExtensionList(configExtensions);
      }

      if (config.allowed_extensions_by_kind && config.allowed_extensions_by_kind[kind]) {
        return normalizeExtensionList(config.allowed_extensions_by_kind[kind]);
      }

      if (config.allowedExtensionsByKind && config.allowedExtensionsByKind[kind]) {
        return normalizeExtensionList(config.allowedExtensionsByKind[kind]);
      }

      return DEFAULTS.allowedExtensions[kind] || [];
    } catch (error) {
      return [];
    }
  }

  function normalizeExtensionList(value) {
    try {
      return toArray(value)
        .map(function (item) {
          return String(item || "").trim().replace(/^\./, "").toLowerCase();
        })
        .filter(Boolean);
    } catch (error) {
      return [];
    }
  }

  function readMaxFiles(zone, input) {
    try {
      var raw = "";

      if (input) {
        raw = input.getAttribute("data-vp-upload-max-files") || "";
      }

      if (!raw && zone) {
        raw = zone.getAttribute("data-vp-upload-max-files") || "";
      }

      if (!raw) {
        raw = getConfigValue(["max_files_per_field", "maxFilesPerField", "max_files", "maxFiles"], DEFAULTS.maxFiles);
      }

      var parsed = parseInt(raw, 10);

      if (!Number.isFinite(parsed) || parsed <= 0) {
        return DEFAULTS.maxFiles;
      }

      return parsed;
    } catch (error) {
      return DEFAULTS.maxFiles;
    }
  }

  function readMaxFileSize(zone, input) {
    try {
      var raw = "";

      if (input) {
        raw = input.getAttribute("data-vp-upload-max-file-size") ||
          input.getAttribute("data-vp-upload-max-file-size-bytes") ||
          "";
      }

      if (!raw && zone) {
        raw = zone.getAttribute("data-vp-upload-max-file-size") ||
          zone.getAttribute("data-vp-upload-max-file-size-bytes") ||
          "";
      }

      if (!raw) {
        raw = getConfigValue(["max_size_bytes", "maxSizeBytes", "max_file_size_bytes", "maxFileSizeBytes"], "");
      }

      if (!raw) {
        var mb = getConfigValue(["max_size_mb", "maxSizeMb", "max_file_size_mb", "maxFileSizeMb"], "");
        if (mb) {
          raw = parseInt(mb, 10) * 1024 * 1024;
        }
      }

      var parsed = parseInt(raw, 10);

      if (!Number.isFinite(parsed) || parsed <= 0) {
        return DEFAULTS.maxFileSizeBytes;
      }

      return parsed;
    } catch (error) {
      return DEFAULTS.maxFileSizeBytes;
    }
  }

  function readBackendEnabled(zone, input) {
    try {
      var raw = "";

      if (input) {
        raw = input.getAttribute("data-vp-upload-backend-enabled") || "";
      }

      if (!raw && zone) {
        raw = zone.getAttribute("data-vp-upload-backend-enabled") || "";
      }

      if (raw !== "") {
        return readBool(raw, DEFAULTS.backendEnabled);
      }

      var config = getUploadConfig();

      if (config.backend_enabled !== undefined) {
        return readBool(config.backend_enabled, DEFAULTS.backendEnabled);
      }

      if (config.backendEnabled !== undefined) {
        return readBool(config.backendEnabled, DEFAULTS.backendEnabled);
      }

      return DEFAULTS.backendEnabled;
    } catch (error) {
      return DEFAULTS.backendEnabled;
    }
  }

  function buildFileMetadata(file, index, kind, purpose, fieldKey) {
    try {
      var extension = extensionFromName(file && file.name ? file.name : "");
      var size = file && file.size ? file.size : 0;
      var lastModified = file && file.lastModified ? file.lastModified : null;

      return {
        index: index,
        name: file && file.name ? file.name : "",
        size: size,
        size_label: fileSizeLabel(size),
        sizeLabel: fileSizeLabel(size),
        type: file && file.type ? file.type : "",
        extension: extension,
        last_modified: lastModified,
        lastModified: lastModified,
        field_key: fieldKey || "",
        fieldKey: fieldKey || "",
        kind: kind || "generic_upload",
        purpose: purpose || kind || "upload",
        backend_stored: false,
        backendStored: false,
        local_only: true,
        localOnly: true,
        source: "browser_file_input"
      };
    } catch (error) {
      return {
        index: index,
        name: "",
        size: 0,
        size_label: "0 B",
        sizeLabel: "0 B",
        type: "",
        extension: "",
        last_modified: null,
        lastModified: null,
        field_key: fieldKey || "",
        fieldKey: fieldKey || "",
        kind: kind || "generic_upload",
        purpose: purpose || kind || "upload",
        backend_stored: false,
        backendStored: false,
        local_only: true,
        localOnly: true,
        source: "browser_file_input"
      };
    }
  }

  function validateFile(fileMeta, allowedExtensions, maxFileSizeBytes) {
    try {
      var errors = [];

      if (
        allowedExtensions &&
        allowedExtensions.length &&
        fileMeta.extension &&
        allowedExtensions.indexOf(fileMeta.extension) < 0
      ) {
        errors.push({
          code: "extension_not_allowed",
          message: "Dateityp ." + fileMeta.extension + " ist nicht erlaubt.",
          file: fileMeta.name
        });
      }

      if (fileMeta.size > maxFileSizeBytes) {
        errors.push({
          code: "file_too_large",
          message: "Datei überschreitet die maximale Größe von " + fileSizeLabel(maxFileSizeBytes) + ".",
          file: fileMeta.name
        });
      }

      return errors;
    } catch (error) {
      return [];
    }
  }

  function readFiles(input, kind, purpose, fieldKey, allowedExtensions, maxFileSizeBytes) {
    try {
      if (!input || !input.files) {
        return {
          files: [],
          errors: []
        };
      }

      var errors = [];
      var files = toArray(input.files).map(function (file, index) {
        var meta = buildFileMetadata(file, index, kind, purpose, fieldKey);
        var fileErrors = validateFile(meta, allowedExtensions, maxFileSizeBytes);

        if (fileErrors.length) {
          errors = errors.concat(fileErrors);
          meta.valid = false;
          meta.errors = fileErrors;
        } else {
          meta.valid = true;
          meta.errors = [];
        }

        return meta;
      });

      return {
        files: files,
        errors: errors
      };
    } catch (error) {
      warn("File list read failed.", error);

      return {
        files: [],
        errors: [{
          code: "read_failed",
          message: "Dateiliste konnte nicht gelesen werden."
        }]
      };
    }
  }

  function emptyUploadPayload(kind) {
    var safeKind = normalizeToken(kind, "generic_upload");
    var now = timestamp();
    var backendEnabled = readBackendEnabled(null, null);

    return {
      version: COMPONENT_VERSION,
      kind: safeKind,
      purpose: safeKind,
      field_key: "",
      fieldKey: "",
      field: "",
      metadata_field: "",
      metadataField: "",
      backend_enabled: backendEnabled,
      backendEnabled: backendEnabled,
      local_only: true,
      localOnly: true,
      count: 0,
      valid_count: 0,
      validCount: 0,
      invalid_count: 0,
      invalidCount: 0,
      max_files: DEFAULTS.maxFiles,
      maxFiles: DEFAULTS.maxFiles,
      max_file_size_bytes: readMaxFileSize(null, null),
      maxFileSizeBytes: readMaxFileSize(null, null),
      allowed_extensions: DEFAULTS.allowedExtensions[safeKind] || [],
      allowedExtensions: DEFAULTS.allowedExtensions[safeKind] || [],
      files: [],
      errors: [],
      ok: true,
      updated_at: now,
      updatedAt: now,
      source: "empty"
    };
  }

  function getPayloadForZone(zone) {
    try {
      var input = getZoneInput(zone);
      var kind = getUploadKind(zone, input);
      var purpose = getUploadPurpose(zone, input, kind);
      var fieldKey = getFieldKey(zone, input);
      var allowedExtensions = getAllowedExtensions(kind, input);
      var maxFiles = readMaxFiles(zone, input);
      var maxFileSizeBytes = readMaxFileSize(zone, input);
      var backendEnabled = readBackendEnabled(zone, input);
      var readResult = readFiles(input, kind, purpose, fieldKey, allowedExtensions, maxFileSizeBytes);
      var files = readResult.files || [];
      var errors = readResult.errors || [];

      if (files.length > maxFiles) {
        errors.push({
          code: "too_many_files",
          message: "Maximal " + maxFiles + " Dateien erlaubt.",
          count: files.length,
          max: maxFiles
        });

        files.forEach(function (file, index) {
          if (index >= maxFiles) {
            file.valid = false;
            file.errors = (file.errors || []).concat([{
              code: "too_many_files",
              message: "Datei liegt außerhalb der erlaubten Maximalanzahl."
            }]);
          }
        });
      }

      var validCount = files.filter(function (file) {
        return file.valid !== false;
      }).length;

      var invalidCount = files.filter(function (file) {
        return file.valid === false;
      }).length;

      return {
        version: COMPONENT_VERSION,
        kind: kind,
        purpose: purpose,
        field_key: fieldKey,
        fieldKey: fieldKey,
        field: input && input.name ? input.name : "",
        metadata_field: zone ? zone.getAttribute("data-vp-upload-metadata-field") || "" : "",
        metadataField: zone ? zone.getAttribute("data-vp-upload-metadata-field") || "" : "",
        backend_enabled: backendEnabled,
        backendEnabled: backendEnabled,
        local_only: true,
        localOnly: true,
        count: files.length,
        valid_count: validCount,
        validCount: validCount,
        invalid_count: invalidCount,
        invalidCount: invalidCount,
        max_files: maxFiles,
        maxFiles: maxFiles,
        max_file_size_bytes: maxFileSizeBytes,
        maxFileSizeBytes: maxFileSizeBytes,
        allowed_extensions: allowedExtensions,
        allowedExtensions: allowedExtensions,
        files: files,
        errors: errors,
        ok: errors.length === 0,
        updated_at: timestamp(),
        updatedAt: timestamp(),
        source: "browser_metadata"
      };
    } catch (error) {
      warn("Upload payload build failed.", error);

      var fallback = emptyUploadPayload("generic_upload");
      fallback.errors = [{
        code: "payload_failed",
        message: "Upload-Metadaten konnten nicht aufgebaut werden."
      }];
      fallback.ok = false;

      return fallback;
    }
  }

  function payloadSignature(payload) {
    try {
      var files = (payload.files || []).map(function (file) {
        return {
          name: file.name || "",
          size: file.size || 0,
          type: file.type || "",
          extension: file.extension || "",
          lastModified: file.lastModified || file.last_modified || null,
          valid: file.valid !== false,
          fieldKey: file.fieldKey || file.field_key || ""
        };
      });

      var errors = (payload.errors || []).map(function (errorItem) {
        return {
          code: errorItem.code || "",
          file: errorItem.file || "",
          message: errorItem.message || ""
        };
      });

      return JSON.stringify({
        kind: payload.kind || "",
        purpose: payload.purpose || "",
        fieldKey: payload.fieldKey || payload.field_key || "",
        field: payload.field || "",
        count: payload.count || 0,
        ok: payload.ok !== false,
        backendEnabled: payload.backendEnabled || payload.backend_enabled || false,
        files: files,
        errors: errors
      });
    } catch (error) {
      return String(Date.now());
    }
  }

  function writeMetadata(zone, payload, options) {
    try {
      var safeOptions = options || {};
      var input = getZoneInput(zone);
      var metadata = getZoneMetadataField(zone, input);

      if (!metadata) {
        return false;
      }

      var text = JSON.stringify(payload || emptyUploadPayload("generic_upload"));

      if (metadata.value === text && safeOptions.force !== true) {
        return false;
      }

      metadata.value = text;
      metadata.setAttribute("data-vp-last-upload-sync", String(Date.now()));
      metadata.setAttribute("data-vp-upload-kind", payload.kind || "");
      metadata.setAttribute("data-vp-upload-count", String(payload.count || 0));
      metadata.setAttribute("data-vp-upload-ok", payload.ok ? "true" : "false");
      metadata.setAttribute("data-vp-upload-backend-enabled", payload.backendEnabled || payload.backend_enabled ? "true" : "false");
      metadata.setAttribute("data-vp-upload-local-only", payload.localOnly || payload.local_only ? "true" : "false");

      if (payload.fieldKey || payload.field_key) {
        metadata.setAttribute("data-vp-field-key", payload.fieldKey || payload.field_key);
      }

      if (safeOptions.emitNativeEvents === true) {
        window.setTimeout(function () {
          try {
            metadata.dispatchEvent(new Event("input", {
              bubbles: true,
              cancelable: false
            }));

            metadata.dispatchEvent(new Event("change", {
              bubbles: true,
              cancelable: false
            }));
          } catch (eventError) {
            warn("Metadata native event dispatch skipped.", eventError);
          }
        }, 0);
      }

      return true;
    } catch (error) {
      runtimeState.lastError = normalizeError(error);
      warn("Metadata write failed.", error);
      return false;
    }
  }

  function renderUploadList(zone, payload) {
    try {
      if (!zone) {
        return;
      }

      var files = payload && payload.files ? payload.files : [];
      var list = zone.querySelector("[data-vp-upload-file-list]");
      var empty = zone.querySelector("[data-vp-upload-empty]");
      var countLabel = zone.querySelector("[data-vp-upload-count-label]");
      var errorNode = zone.querySelector("[data-vp-upload-errors]");

      if (countLabel) {
        countLabel.textContent = files.length === 1 ? "1 Datei" : files.length + " Dateien";
      }

      if (empty) {
        if (files.length) {
          empty.textContent = payload.backendEnabled
            ? "Dateien ausgewählt. Upload-Metadaten werden an das Backend übergeben."
            : "Dateien werden aktuell nur lokal als Metadaten erfasst.";
        } else if (payload.kind === "geometry_model") {
          empty.textContent = "Noch kein 3D-Modell ausgewählt.";
        } else if (payload.kind === "technical_documents") {
          empty.textContent = "Noch keine technischen Unterlagen ausgewählt.";
        } else if (payload.kind === "variant_documents") {
          empty.textContent = "Noch keine Dokumente ausgewählt.";
        } else {
          empty.textContent = "Noch keine Dateien ausgewählt.";
        }
      }

      if (list) {
        list.innerHTML = "";

        files.forEach(function (file) {
          try {
            var row = document.createElement("div");
            row.className = "vp-create-upload__file";
            row.setAttribute("data-vp-upload-file", "true");
            row.setAttribute("data-vp-upload-file-valid", file.valid === false ? "false" : "true");

            var copy = document.createElement("div");
            copy.className = "vp-create-upload__file-copy";

            var name = document.createElement("strong");
            name.className = "vp-create-upload__file-name";
            name.setAttribute("data-vp-upload-file-name", "true");
            name.textContent = file.name || "Unbenannte Datei";

            var meta = document.createElement("span");
            meta.className = "vp-create-upload__file-meta";
            meta.setAttribute("data-vp-upload-file-meta", "true");
            meta.textContent = [
              file.size_label || file.sizeLabel || "",
              file.extension ? "." + file.extension : "",
              file.type || "unbekannter Typ"
            ].filter(Boolean).join(" · ");

            copy.appendChild(name);
            copy.appendChild(meta);

            if (file.valid === false && file.errors && file.errors.length) {
              var errorText = document.createElement("span");
              errorText.className = "vp-create-upload__file-error";
              errorText.setAttribute("data-vp-upload-file-error", "true");
              errorText.textContent = file.errors.map(function (item) {
                return item.message || item.code || "Ungültig";
              }).join(" ");

              copy.appendChild(errorText);
            }

            row.appendChild(copy);
            list.appendChild(row);
          } catch (rowError) {
            warn("Upload row render skipped.", rowError);
          }
        });
      }

      if (errorNode) {
        errorNode.textContent = payload.errors && payload.errors.length
          ? payload.errors.map(function (item) {
            return item.message || item.code || "Fehler";
          }).join(" ")
          : "";
        errorNode.hidden = !(payload.errors && payload.errors.length);
      }
    } catch (error) {
      warn("Upload list render failed.", error);
    }
  }

  function updateZoneAttributes(zone, payload) {
    try {
      if (!zone) {
        return;
      }

      zone.setAttribute("data-vp-upload-count", String(payload.count || 0));
      zone.setAttribute("data-vp-upload-valid-count", String(payload.valid_count || payload.validCount || 0));
      zone.setAttribute("data-vp-upload-invalid-count", String(payload.invalid_count || payload.invalidCount || 0));
      zone.setAttribute("data-vp-upload-has-files", payload.count > 0 ? "true" : "false");
      zone.setAttribute("data-vp-upload-ok", payload.ok ? "true" : "false");
      zone.setAttribute("data-vp-upload-last-update", String(Date.now()));
      zone.setAttribute("data-vp-upload-kind", payload.kind || "");
      zone.setAttribute("data-vp-upload-purpose", payload.purpose || "");
      zone.setAttribute("data-vp-upload-local-only", payload.localOnly || payload.local_only ? "true" : "false");
      zone.setAttribute("data-vp-upload-backend-enabled", payload.backendEnabled || payload.backend_enabled ? "true" : "false");

      if (payload.fieldKey || payload.field_key) {
        zone.setAttribute("data-vp-field-key", payload.fieldKey || payload.field_key);
      }

      var parentSection = zone.closest("[data-vp-create-section], [data-create-section]");
      if (parentSection) {
        parentSection.setAttribute("data-vp-upload-count-" + normalizeToken(payload.kind, "upload"), String(payload.count || 0));
        parentSection.setAttribute("data-vp-upload-ok-" + normalizeToken(payload.kind, "upload"), payload.ok ? "true" : "false");
      }
    } catch (error) {
      warn("Zone attribute update failed.", error);
    }
  }

  function shouldEmitEvents(options, changed) {
    try {
      var safeOptions = options || {};

      if (safeOptions.silent === true) {
        return false;
      }

      if (safeOptions.emitEvents === false) {
        return false;
      }

      if (safeOptions.emitEvents === true) {
        return true;
      }

      if (!changed) {
        return false;
      }

      return [
        "input-change",
        "input",
        "change",
        "clear",
        "public-clear-zone",
        "public-clear-all"
      ].indexOf(String(safeOptions.source || "")) >= 0;
    } catch (error) {
      return false;
    }
  }

  function emitUploadEvents(zone, payload, options) {
    try {
      var safeOptions = options || {};
      var detail = {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        payload: payload,
        kind: payload.kind,
        purpose: payload.purpose,
        count: payload.count,
        files: payload.files || [],
        errors: payload.errors || [],
        fieldKey: payload.fieldKey || payload.field_key || "",
        backendEnabled: payload.backendEnabled || payload.backend_enabled || false,
        localOnly: payload.localOnly || payload.local_only || false,
        source: safeOptions.source || "sync"
      };

      if (!payload.ok) {
        dispatch(zone, "vectoplan:create:upload-error", detail);
        dispatch(document, "vectoplan:create:upload-error", detail);
      }

      dispatch(zone, "vectoplan:create:upload-changed", detail);
      dispatch(document, "vectoplan:create:upload-changed", detail);

      if (payload.kind === "geometry_model") {
        dispatch(document, "vectoplan:create:geometry-upload-changed", detail);
      }

      if (payload.kind === "technical_documents") {
        dispatch(document, "vectoplan:create:technical-upload-changed", detail);
      }

      if (payload.kind === "variant_documents") {
        dispatch(document, "vectoplan:create:variables-upload-changed", detail);
      }
    } catch (error) {
      runtimeState.lastError = normalizeError(error);
      warn("Upload event emission failed.", error);
    }
  }

  function syncZone(zone, options) {
    try {
      if (!zone) {
        return null;
      }

      var safeOptions = options || {};

      if (zone.getAttribute(SYNCING_ATTR) === "true") {
        runtimeState.skippedReentrantSyncCount += 1;
        return zone.__vpUploadPayload || null;
      }

      zone.setAttribute(SYNCING_ATTR, "true");

      var payload = getPayloadForZone(zone);
      var signature = payloadSignature(payload);
      var previousSignature = zone.__vpUploadSignature || "";
      var changed = safeOptions.force === true || signature !== previousSignature;

      if (!changed && zone.__vpUploadPayload) {
        payload.updated_at = zone.__vpUploadPayload.updated_at || zone.__vpUploadPayload.updatedAt || timestamp();
        payload.updatedAt = payload.updated_at;
      } else {
        payload.updated_at = timestamp();
        payload.updatedAt = payload.updated_at;
      }

      payload.source = safeOptions.source || "sync";

      zone.__vpUploadSignature = signature;
      zone.__vpUploadPayload = payload;

      writeMetadata(zone, payload, {
        force: changed,
        emitNativeEvents: safeOptions.emitNativeEvents === true
      });

      renderUploadList(zone, payload);
      updateZoneAttributes(zone, payload);

      runtimeState.syncCount += 1;
      runtimeState.lastSyncAt = timestamp();

      if (shouldEmitEvents(safeOptions, changed)) {
        emitUploadEvents(zone, payload, safeOptions);
      }

      return payload;
    } catch (error) {
      runtimeState.lastError = normalizeError(error);
      warn("Zone sync failed.", error);
      return null;
    } finally {
      try {
        if (zone) {
          zone.setAttribute(SYNCING_ATTR, "false");
        }
      } catch (cleanupError) {
        /* no-op */
      }
    }
  }

  function clearZone(zone, options) {
    try {
      if (!zone) {
        return false;
      }

      var input = getZoneInput(zone);
      var source = options && options.source ? options.source : "clear";

      if (input) {
        try {
          input.value = "";
        } catch (inputError) {
          warn("Input clear skipped.", inputError);
        }
      }

      var payload = syncZone(zone, {
        source: source,
        force: true,
        silent: false,
        emitEvents: true
      });

      dispatch(zone, "vectoplan:create:upload-cleared", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        payload: payload,
        kind: payload ? payload.kind : "",
        source: source
      });

      dispatch(document, "vectoplan:create:upload-cleared", {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        payload: payload,
        kind: payload ? payload.kind : "",
        source: source
      });

      return true;
    } catch (error) {
      runtimeState.lastError = normalizeError(error);
      warn("Zone clear failed.", error);
      return false;
    }
  }

  function bindZone(zone) {
    try {
      if (!zone) {
        return;
      }

      var input = getZoneInput(zone);

      if (input && input.getAttribute(INPUT_BOUND_ATTR) !== "true") {
        input.addEventListener("change", function () {
          syncZone(zone, {
            source: "input-change",
            silent: false,
            emitEvents: true,
            force: true
          });
        });

        input.setAttribute(INPUT_BOUND_ATTR, "true");
      }

      if (zone.getAttribute(ZONE_READY_ATTR) !== "true") {
        zone.setAttribute(ZONE_READY_ATTR, "true");
        zone.setAttribute("data-vp-upload-runtime-version", COMPONENT_VERSION);

        dispatch(zone, "vectoplan:create:upload-zone-ready", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          zone: zone,
          kind: getUploadKind(zone, input)
        });
      }

      syncZone(zone, {
        source: "init",
        silent: true
      });
    } catch (error) {
      runtimeState.lastError = normalizeError(error);
      warn("Zone binding failed.", error);

      try {
        zone.setAttribute("data-vp-upload-zone-status", "initialization_failed");
        zone.setAttribute("data-vp-upload-zone-error", String(error && error.message ? error.message : error));
      } catch (statusError) {
        /* no-op */
      }
    }
  }

  function getZones(root) {
    try {
      var scope = root || document;
      var zones = toArray(scope.querySelectorAll(ZONE_SELECTOR));

      if (scope.matches && scope.matches(ZONE_SELECTOR)) {
        zones.unshift(scope);
      }

      return zones.filter(function (zone, index, list) {
        return zone && list.indexOf(zone) === index;
      });
    } catch (error) {
      return [];
    }
  }

  function syncAll(root, options) {
    try {
      var safeOptions = options || {};
      var source = safeOptions.source || "sync-all";
      var silent = safeOptions.silent !== false;

      return getZones(root || document).map(function (zone) {
        return syncZone(zone, {
          source: source,
          silent: silent,
          emitEvents: safeOptions.emitEvents === true,
          emitNativeEvents: safeOptions.emitNativeEvents === true,
          force: safeOptions.force === true
        });
      }).filter(Boolean);
    } catch (error) {
      runtimeState.lastError = normalizeError(error);
      warn("syncAll failed.", error);
      return [];
    }
  }

  function initializeAll(root) {
    try {
      getZones(root || document).forEach(function (zone) {
        bindZone(zone);
      });

      runtimeState.initialized = true;

      document.documentElement.setAttribute(ROOT_READY_ATTR, "true");
      document.documentElement.setAttribute("data-vp-create-uploads-runtime-version", COMPONENT_VERSION);

      if (!runtimeState.readyDispatched) {
        runtimeState.readyDispatched = true;

        dispatch(document, "vectoplan:create:uploads-runtime-ready", {
          component: COMPONENT_NAME,
          version: COMPONENT_VERSION,
          zoneCount: getZones(document).length,
          config: getUploadConfig()
        });
      }
    } catch (error) {
      runtimeState.lastError = normalizeError(error);
      warn("Global initialization failed.", error);
    }
  }

  function bindGlobalEvents() {
    try {
      if (document.documentElement.getAttribute(ROOT_EVENTS_BOUND_ATTR) === "true") {
        return;
      }

      document.addEventListener("vectoplan:create:context-ready", function () {
        try {
          syncAll(document, {
            source: "context-ready",
            silent: true,
            force: true
          });
        } catch (error) {
          warn("Context-ready upload refresh failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:uploads-refresh-requested", function () {
        try {
          initializeAll(document);
          syncAll(document, {
            source: "uploads-refresh-requested",
            silent: true
          });
        } catch (error) {
          warn("Upload refresh request failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:step-changed", function () {
        try {
          initializeAll(document);
        } catch (error) {
          warn("Step change upload refresh failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:wizard-step-changed", function () {
        try {
          initializeAll(document);
        } catch (error) {
          warn("Wizard step change upload refresh failed.", error);
        }
      });

      document.documentElement.setAttribute(ROOT_EVENTS_BOUND_ATTR, "true");
    } catch (error) {
      runtimeState.lastError = normalizeError(error);
      warn("Global event binding failed.", error);
    }
  }

  function getSummary(root) {
    try {
      var payloads = getPayloads(root || document);
      var count = payloads.reduce(function (sum, payload) {
        return sum + (parseInt(payload.count, 10) || 0);
      }, 0);
      var errors = payloads.reduce(function (all, payload) {
        return all.concat(payload.errors || []);
      }, []);

      return {
        ready: document.documentElement.getAttribute(ROOT_READY_ATTR) === "true",
        version: COMPONENT_VERSION,
        zoneCount: payloads.length,
        fileCount: count,
        errorCount: errors.length,
        ok: errors.length === 0,
        backendEnabled: readBackendEnabled(null, null),
        payloads: payloads,
        errors: errors,
        config: getUploadConfig()
      };
    } catch (error) {
      return {
        ready: false,
        version: COMPONENT_VERSION,
        zoneCount: 0,
        fileCount: 0,
        errorCount: 1,
        ok: false,
        payloads: [],
        errors: [{
          code: "summary_failed",
          message: String(error && error.message ? error.message : error)
        }]
      };
    }
  }

  function getPayloads(root) {
    try {
      return getZones(root || document).map(function (zone) {
        return zone.__vpUploadPayload || getPayloadForZone(zone);
      });
    } catch (error) {
      return [];
    }
  }

  function getPayloadsByKind(kind, root) {
    try {
      var normalizedKind = normalizeToken(kind, "");

      return getPayloads(root || document).filter(function (payload) {
        return normalizeToken(payload.kind, "") === normalizedKind;
      });
    } catch (error) {
      return [];
    }
  }

  function createPublicApi() {
    try {
      var previousApi = window[GLOBAL_NAME] || {};

      var api = Object.assign({}, previousApi, {
        component: COMPONENT_NAME,
        version: COMPONENT_VERSION,
        __version: COMPONENT_VERSION,

        initialize: function (root) {
          initializeAll(root || document);
          return true;
        },

        getZones: function (root) {
          return getZones(root || document);
        },

        syncZone: function (zone, options) {
          return syncZone(zone, options || {
            source: "public-sync-zone",
            silent: false,
            emitEvents: true
          });
        },

        syncAll: function (root, options) {
          return syncAll(root || document, Object.assign({
            source: "public-sync-all",
            silent: true
          }, options || {}));
        },

        clearZone: function (zone) {
          return clearZone(zone, {
            source: "public-clear-zone"
          });
        },

        clearAll: function (root) {
          try {
            return getZones(root || document).map(function (zone) {
              return clearZone(zone, {
                source: "public-clear-all"
              });
            });
          } catch (error) {
            warn("Public clearAll failed.", error);
            return [];
          }
        },

        getPayload: function (zone) {
          return zone ? (zone.__vpUploadPayload || getPayloadForZone(zone)) : null;
        },

        getPayloads: getPayloads,
        getPayloadsByKind: getPayloadsByKind,
        getSummary: getSummary,
        getUploadConfig: getUploadConfig,

        getState: function () {
          return {
            version: COMPONENT_VERSION,
            initialized: runtimeState.initialized,
            readyDispatched: runtimeState.readyDispatched,
            syncCount: runtimeState.syncCount,
            eventCount: runtimeState.eventCount,
            skippedReentrantSyncCount: runtimeState.skippedReentrantSyncCount,
            lastSyncAt: runtimeState.lastSyncAt,
            lastError: runtimeState.lastError,
            lastConfig: runtimeState.lastConfig,
            zoneCount: getZones(document).length,
            summary: getSummary(document)
          };
        }
      });

      window[GLOBAL_NAME] = api;
      return api;
    } catch (error) {
      runtimeState.lastError = normalizeError(error);
      warn("Public API creation failed.", error);
      return null;
    }
  }

  function boot() {
    try {
      createPublicApi();
      bindGlobalEvents();
      initializeAll(document);
    } catch (error) {
      runtimeState.lastError = normalizeError(error);
      warn("Bootstrap failed.", error);
    }
  }

  try {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", boot, {
        once: true
      });
    } else {
      boot();
    }
  } catch (error) {
    runtimeState.lastError = normalizeError(error);
    warn("Boot scheduling failed.", error);
  }
})();