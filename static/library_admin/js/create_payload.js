/* services/vectoplan-library/static/library_admin/js/create_payload.js */

/* -----------------------------------------------------------------------------
  VECTOPLAN Library · VPLIB Create Payload Runtime

  Zweck:
  - Eigenständige Payload-Schicht für /create.
  - Entlastet create.js.
  - Sammelt Formulardaten robust ein.
  - Synchronisiert definition-managed Variant Runtime in das Formular.
  - Hält Legacy-Variantenzeilen weiterhin als Fallback lesbar.
  - Stellt definition_variants_json als zentrale Backend-Brücke sicher.
  - Normalisiert Defaultwerte, Taxonomie, Objektart, Geometrie, Profile und
    Upload-Metadaten.
  - Erzeugt keine VPLIB-Dateien im Browser.
  - Überträgt keine echten Datei-Bytes.
  - Erfasst Uploads nur als lokale Metadaten.

  Fix 0.6.1:
  - Verhindert Upload-Reentrancy zwischen create_uploads.js und create_payload.js.
  - Upload-Events lösen keinen erneuten Upload-Runtime-syncAll aus.
  - syncAll wird nur noch still aufgerufen.
  - payload-uploads-synced wird nur bei geänderter Upload-Signatur ausgelöst.
  - Native input/change Events auf Hidden-Upload-Feldern werden nicht erzeugt.
----------------------------------------------------------------------------- */

(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreatePayload";
  var MODULE_NAME = "payload";
  var PAYLOAD_VERSION = "0.6.1";
  var CORE_NAME = "VectoplanCreateCore";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 80;

  var FIELD_NAMES = {
    definitionVariantsJson: "definition_variants_json",
    defaultVariantId: "default_variant_id",
    familyProfileId: "family_profile_id",
    variantProfileId: "variant_profile_id",
    objectKind: "object_kind",
    domain: "domain",
    category: "category",
    subcategory: "subcategory",
    geometryModelUploadsJson: "geometry_model_uploads_json",
    technicalDocumentUploadsJson: "technical_document_uploads_json",
    variantDocumentUploadsJson: "variant_document_uploads_json"
  };

  var VARIANT_ID_KEYS = [
    "variant_id",
    "variantId",
    "id",
    "slug",
    "variant_slug",
    "variantSlug"
  ];

  var VARIANT_LABEL_KEYS = [
    "label",
    "name",
    "variant_name",
    "variantName",
    "display_name",
    "displayName",
    "title"
  ];

  var VARIANT_DESCRIPTION_KEYS = [
    "description",
    "variant_description",
    "variantDescription",
    "notes",
    "note"
  ];

  var SYSTEM_VARIANT_VALUE_KEYS = {
    "variant.variant_id": true,
    "variant.variantId": true,
    "variant.id": true,
    "variant_id": true,
    "variantId": true,
    "id": true
  };

  var UPLOAD_EVENT_NAMES = [
    "vectoplan:create:upload-changed",
    "vectoplan:create:upload-cleared",
    "vectoplan:create:uploads-runtime-ready",
    "vectoplan:create:geometry-upload-changed",
    "vectoplan:create:technical-upload-changed",
    "vectoplan:create:variables-upload-changed"
  ];

  var DEFAULT_SELECTORS = {
    form: "[data-vp-create-form], [data-create-form='true'], #vp-create-form, form[data-create-form]",
    variantRow: "[data-vp-variant-row='true'], [data-create-variant-row='true']",
    objectKindSelect: "[data-create-object-kind='true'], [name='object_kind']",
    domainSelect: "[name='domain'], [data-vp-taxonomy-domain]",
    categorySelect: "[name='category'], [data-vp-taxonomy-category]",
    subcategorySelect: "[name='subcategory'], [data-vp-taxonomy-subcategory]",
    uploadZone: "[data-vp-upload-zone], [data-create-upload-zone], [data-vp-upload]",
    uploadInput: "[data-vp-upload-input], input[type='file'][data-vp-upload-kind], input[type='file'][name='geometry_model_files'], input[type='file'][name='technical_document_files'], input[type='file'][name^='variant_document_files']",
    uploadMetadata: "[data-vp-upload-metadata], [name='geometry_model_uploads_json'], [name='technical_document_uploads_json'], [name='variant_document_uploads_json'], [name^='variant_document_uploads[']"
  };

  var core = null;
  var selectors = null;
  var initialized = false;

  var localState = {
    version: PAYLOAD_VERSION,
    initialized: false,
    lastPayload: null,
    lastPayloadSummary: null,
    lastSync: null,
    lastUploadSync: null,
    lastUploadSignature: "",
    lastError: null,
    collectCount: 0,
    syncCount: 0,
    uploadSyncCount: 0,
    skippedUploadSyncCount: 0,
    suppressedUploadEventCount: 0,
    fallbackVariantCount: 0,
    runtimeVariantCount: 0,
    uploadFileCount: 0,
    uploadErrorCount: 0,
    uploadSyncActive: false
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

        fallbackWarn("Core runtime missing; initializing payload runtime with defensive fallback core.");
        maybeCore = buildFallbackCore();
      }

      initialize(maybeCore);
    } catch (error) {
      fallbackWarn("Payload boot failed.", error);
    }
  }

  function initialize(coreRuntime) {
    try {
      if (initialized) {
        return api;
      }

      core = coreRuntime || window[CORE_NAME] || buildFallbackCore();

      if (!core) {
        fallbackWarn("Cannot initialize payload runtime without a core fallback.");
        return api;
      }

      selectors = Object.assign({}, DEFAULT_SELECTORS, core.selectors || {});

      if (typeof core.refreshContext === "function") {
        core.refreshContext();
      }

      bindPayloadEvents();
      ensureDefinitionVariantHiddenFields();
      ensureUploadHiddenFields();

      initialized = true;
      localState.initialized = true;

      if (typeof core.registerModule === "function") {
        core.registerModule(MODULE_NAME, api);
      }

      safeSetAttribute(document.documentElement, "data-vp-create-payload-ready", "true");
      safeSetAttribute(document.documentElement, "data-vp-create-payload-version", PAYLOAD_VERSION);

      safeDispatch("vectoplan:create:payload-ready", getState());

      return api;
    } catch (error) {
      localState.initialized = false;
      localState.lastError = normalizeError(error);
      safeError("Payload initialization failed.", error);
      return api;
    }
  }

  function bindPayloadEvents() {
    try {
      bindOnce("create-payload-form-change-sync", function () {
        document.addEventListener("change", function (event) {
          try {
            var target = event && event.target ? event.target : null;

            if (!target || !target.matches) {
              return;
            }

            if (
              target.matches(selectorFor("objectKindSelect")) ||
              target.matches(selectorFor("domainSelect")) ||
              target.matches(selectorFor("categorySelect")) ||
              target.matches(selectorFor("subcategorySelect"))
            ) {
              ensureDefinitionVariantHiddenFields();
              syncProfileIdsIntoForm(null, {
                source: "form-change"
              });
            }

            if (target.matches(selectorFor("uploadInput"))) {
              syncUploadsRuntimeToForm(null, {
                source: "input-change",
                skipRuntimeSync: false,
                silentRuntimeSync: true,
                emitEvents: true
              });
            }
          } catch (handlerError) {
            safeWarn("Payload change sync failed.", handlerError);
          }
        }, true);
      });

      bindOnce("create-payload-variant-state-sync", function () {
        [
          "vectoplan:create:variant-state-changed",
          "vectoplan:create:variant-state-synced",
          "vectoplan:create:variant-updated",
          "vectoplan:create:variant-added",
          "vectoplan:create:variant-removed",
          "vectoplan:create:variant-drawer-apply-finished"
        ].forEach(function (eventName) {
          document.addEventListener(eventName, function () {
            try {
              syncVariantRuntimeToForm(null, {
                source: eventName
              });
            } catch (handlerError) {
              safeWarn("Variant state payload sync failed: " + eventName, handlerError);
            }
          });
        });
      });

      bindOnce("create-payload-upload-state-sync", function () {
        UPLOAD_EVENT_NAMES.forEach(function (eventName) {
          document.addEventListener(eventName, function (event) {
            try {
              var detail = event && event.detail ? event.detail : {};
              var eventSource = detail.source || eventName;

              syncUploadsRuntimeToForm(null, {
                source: eventName,
                upstreamSource: eventSource,
                fromUploadEvent: true,
                skipRuntimeSync: true,
                emitEvents: true,
                forceEvent: false
              });
            } catch (handlerError) {
              safeWarn("Upload payload sync failed: " + eventName, handlerError);
            }
          });
        });
      });
    } catch (error) {
      safeWarn("Payload event binding failed.", error);
    }
  }

  function collectPayload(form, options) {
    try {
      ensureCore();

      var safeForm = resolveForm(form);
      var safeOptions = options || {};

      if (!safeForm) {
        throw new Error("Create form not found.");
      }

      localState.collectCount += 1;

      if (safeOptions.syncVariants !== false) {
        syncVariantRuntimeToForm(safeForm, {
          source: safeOptions.source || "collectPayload"
        });
      }

      if (safeOptions.syncUploads !== false) {
        syncUploadsRuntimeToForm(safeForm, {
          source: safeOptions.source || "collectPayload",
          skipRuntimeSync: safeOptions.skipRuntimeSync === true,
          silentRuntimeSync: true,
          emitEvents: false
        });
      }

      var payload = collectFormPayloadRaw(safeForm);

      ensureUncheckedDefaults(safeForm, payload);
      augmentPayloadWithDefinitionVariants(payload, safeForm);
      augmentPayloadWithUploads(payload, safeForm, safeOptions);
      syncProfileIdsIntoPayload(payload, safeForm);
      normalizePayloadBeforeSend(payload, safeForm);

      localState.lastPayload = clone(payload);
      localState.lastPayloadSummary = summarizePayload(payload);

      safeDispatch("vectoplan:create:payload-collected", {
        payload: clone(payload),
        summary: localState.lastPayloadSummary,
        source: safeOptions.source || "api"
      });

      return payload;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Payload collection failed.", error);

      return {};
    }
  }

  function collectFormPayloadRaw(form) {
    try {
      var formData = new FormData(form);
      var payload = {};

      formData.forEach(function (value, key) {
        try {
          if (isFileValue(value)) {
            if (value.name) {
              assignPayloadValue(payload, key, fileToPayloadValue(value));
            }

            return;
          }

          assignPayloadValue(payload, key, value);
        } catch (entryError) {
          safeWarn("Payload entry skipped: " + key, entryError);
        }
      });

      return payload;
    } catch (error) {
      safeError("Raw form payload collection failed.", error);
      return {};
    }
  }

  function assignPayloadValue(payload, key, value) {
    try {
      if (!payload || !key) {
        return;
      }

      if (Object.prototype.hasOwnProperty.call(payload, key)) {
        if (!Array.isArray(payload[key])) {
          payload[key] = [payload[key]];
        }

        payload[key].push(value);
      } else {
        payload[key] = value;
      }
    } catch (error) {
      safeWarn("Assign payload value failed: " + key, error);
    }
  }

  function ensureUncheckedDefaults(form, payload) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm || !payload) {
        return payload;
      }

      var variantRows = qsa(selectorFor("variantRow"), safeForm);

      variantRows.forEach(function (row, index) {
        try {
          var key = "variants[" + index + "][is_default]";

          if (!Object.prototype.hasOwnProperty.call(payload, key)) {
            payload[key] = index === 0 ? "true" : "false";
          }
        } catch (rowError) {
          safeWarn("Unchecked default fallback skipped.", rowError);
        }
      });

      return payload;
    } catch (error) {
      safeWarn("Ensure unchecked defaults failed.", error);
      return payload;
    }
  }

  function normalizePayloadBeforeSend(payload, form) {
    try {
      var safeForm = resolveForm(form);
      var defaults = getNested(core.state, ["uiState", "defaults"], {});
      var objectKind = String(
        payload.object_kind ||
        defaults.object_kind ||
        defaults.objectKind ||
        getFieldValue(safeForm, "object_kind") ||
        "cell_block"
      ).trim();

      if (!payload.domain) {
        payload.domain = getFieldValue(safeForm, "domain") || defaults.domain || "hochbau";
      }

      if (!payload.category) {
        payload.category = getFieldValue(safeForm, "category") || defaults.category || "bloecke";
      }

      if (!payload.subcategory) {
        payload.subcategory = getFieldValue(safeForm, "subcategory") || defaults.subcategory || "basis";
      }

      if (!payload.object_kind) {
        payload.object_kind = objectKind;
      }

      if (!payload.primitive_shape) {
        payload.primitive_shape = getFieldValue(safeForm, "primitive_shape") || defaults.primitive_shape || defaults.primitiveShape || "block";
      }

      if (!payload.geometry_unit) {
        payload.geometry_unit = getFieldValue(safeForm, "geometry_unit") || defaults.geometry_unit || defaults.geometryUnit || "m";
      }

      if (!payload.geometry_width) {
        payload.geometry_width = getFieldValue(safeForm, "geometry_width") || defaults.geometry_width || defaults.geometryWidth || "1.00";
      }

      if (!payload.geometry_height) {
        payload.geometry_height = getFieldValue(safeForm, "geometry_height") || defaults.geometry_height || defaults.geometryHeight || "1.00";
      }

      if (!payload.geometry_depth) {
        payload.geometry_depth = getFieldValue(safeForm, "geometry_depth") || defaults.geometry_depth || defaults.geometryDepth || "1.00";
      }

      objectKind = normalizeToken(objectKind, "cell_block");

      if (objectKind === "cell_block" || objectKind === "adaptive_system") {
        payload.editor_cells_x = "1";
        payload.editor_cells_y = "1";
        payload.editor_cells_z = "1";
      } else {
        if (!payload.editor_cells_x) {
          payload.editor_cells_x = getFieldValue(safeForm, "editor_cells_x") || defaults.editor_cells_x || defaults.editorCellsX || "1";
        }

        if (!payload.editor_cells_y) {
          payload.editor_cells_y = getFieldValue(safeForm, "editor_cells_y") || defaults.editor_cells_y || defaults.editorCellsY || "1";
        }

        if (!payload.editor_cells_z) {
          payload.editor_cells_z = getFieldValue(safeForm, "editor_cells_z") || defaults.editor_cells_z || defaults.editorCellsZ || "1";
        }
      }

      payload.family_name = String(payload.family_name || "").trim();
      payload.family_description = String(payload.family_description || "").trim();
      payload.material_class = String(payload.material_class || "").trim();

      payload.domain = normalizeToken(payload.domain, "hochbau");
      payload.category = normalizeToken(payload.category, "bloecke");
      payload.subcategory = normalizeToken(payload.subcategory, "basis");
      payload.object_kind = normalizeToken(payload.object_kind, "cell_block");

      payload.geometry_width = String(payload.geometry_width || "1.00").trim();
      payload.geometry_height = String(payload.geometry_height || "1.00").trim();
      payload.geometry_depth = String(payload.geometry_depth || "1.00").trim();

      ensureDefinitionVariantAliases(payload);
      ensureUploadAliases(payload);

      return payload;
    } catch (error) {
      safeWarn("Payload normalization failed.", error);
      return payload;
    }
  }

  function syncVariantRuntimeToForm(form, options) {
    try {
      ensureCore();

      var safeForm = resolveForm(form);

      if (!safeForm) {
        return false;
      }

      var hiddenFields = ensureDefinitionVariantHiddenFields(safeForm);
      var variants = getRuntimeDefinitionVariants(safeForm);
      var source = options && options.source ? options.source : "api";

      if (!variants.length) {
        variants = readDefinitionVariantsJson(safeForm);
      }

      if (!variants.length) {
        variants = buildFallbackDefinitionVariantsFromLegacyRows(safeForm);
      }

      variants = normalizeDefinitionVariants(variants, buildPayloadContext(safeForm));

      var defaultVariantId = resolveDefaultVariantId(variants, safeForm);
      var variantsJson = stringifyJson(variants);

      if (hiddenFields.definitionVariantsJson && hiddenFields.definitionVariantsJson.value !== variantsJson) {
        hiddenFields.definitionVariantsJson.value = variantsJson;
      }

      if (hiddenFields.defaultVariantId && hiddenFields.defaultVariantId.value !== defaultVariantId) {
        hiddenFields.defaultVariantId.value = defaultVariantId;
      }

      syncProfileIdsIntoForm(safeForm, {
        source: source
      });

      localState.syncCount += 1;
      localState.lastSync = {
        source: source,
        variantCount: variants.length,
        defaultVariantId: defaultVariantId,
        timestamp: timestamp()
      };

      safeDispatch("vectoplan:create:payload-variants-synced", {
        source: source,
        variantCount: variants.length,
        defaultVariantId: defaultVariantId,
        variants: clone(variants)
      });

      return true;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Variant runtime to form sync failed.", error);
      return false;
    }
  }

  function syncUploadsRuntimeToForm(form, options) {
    try {
      ensureCore();

      var safeForm = resolveForm(form);
      var safeOptions = options || {};
      var source = safeOptions.source || "api";

      if (!safeForm) {
        return false;
      }

      if (localState.uploadSyncActive) {
        localState.skippedUploadSyncCount += 1;
        return true;
      }

      localState.uploadSyncActive = true;

      try {
        if (shouldCallUploadRuntimeSync(source, safeOptions)) {
          syncUploadRuntimeSilently(safeForm, source);
        }

        var hiddenFields = ensureUploadHiddenFields(safeForm);
        var uploadMetadata = getUploadMetadata(safeForm, {
          source: source
        });
        var signature = uploadMetadataSignature(uploadMetadata);
        var changed = signature !== localState.lastUploadSignature || safeOptions.force === true;

        if (changed) {
          localState.lastUploadSignature = signature;
          syncUploadHiddenFieldsFromMetadata(safeForm, uploadMetadata, {
            fields: hiddenFields,
            force: true
          });
        } else {
          syncUploadHiddenFieldsFromMetadata(safeForm, uploadMetadata, {
            fields: hiddenFields,
            force: false
          });
        }

        localState.uploadSyncCount += 1;
        localState.uploadFileCount = uploadMetadata.summary ? uploadMetadata.summary.fileCount : 0;
        localState.uploadErrorCount = uploadMetadata.summary ? uploadMetadata.summary.errorCount : 0;
        localState.lastUploadSync = {
          source: source,
          upstreamSource: safeOptions.upstreamSource || "",
          changed: changed,
          fileCount: localState.uploadFileCount,
          errorCount: localState.uploadErrorCount,
          timestamp: timestamp()
        };

        if (safeOptions.emitEvents !== false && (changed || safeOptions.forceEvent === true)) {
          safeDispatch("vectoplan:create:payload-uploads-synced", {
            source: source,
            upstreamSource: safeOptions.upstreamSource || "",
            uploads: clone(uploadMetadata),
            summary: uploadMetadata.summary || {}
          });
        } else if (!changed) {
          localState.suppressedUploadEventCount += 1;
        }

        return true;
      } finally {
        localState.uploadSyncActive = false;
      }
    } catch (error) {
      localState.uploadSyncActive = false;
      localState.lastError = normalizeError(error);
      safeError("Upload runtime to form sync failed.", error);
      return false;
    }
  }

  function shouldCallUploadRuntimeSync(source, options) {
    try {
      var safeOptions = options || {};
      var safeSource = String(source || "");

      if (safeOptions.skipRuntimeSync === true || safeOptions.fromUploadEvent === true) {
        return false;
      }

      if (
        safeSource.indexOf("vectoplan:create:upload") === 0 ||
        safeSource.indexOf("geometry-upload") !== -1 ||
        safeSource.indexOf("technical-upload") !== -1 ||
        safeSource.indexOf("variables-upload") !== -1
      ) {
        return false;
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function syncUploadRuntimeSilently(form, source) {
    try {
      if (
        window.VectoplanCreateUploads &&
        typeof window.VectoplanCreateUploads.syncAll === "function"
      ) {
        window.VectoplanCreateUploads.syncAll(form || document, {
          source: "payload:" + (source || "sync"),
          silent: true,
          emitEvents: false,
          emitNativeEvents: false
        });
      }

      return true;
    } catch (runtimeError) {
      safeWarn("Upload runtime silent syncAll failed.", runtimeError);
      return false;
    }
  }

  function ensureDefinitionVariantHiddenFields(form) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm) {
        return {};
      }

      return {
        definitionVariantsJson: ensureHiddenField(safeForm, FIELD_NAMES.definitionVariantsJson, "[]"),
        defaultVariantId: ensureHiddenField(safeForm, FIELD_NAMES.defaultVariantId, "default"),
        familyProfileId: ensureHiddenField(safeForm, FIELD_NAMES.familyProfileId, ""),
        variantProfileId: ensureHiddenField(safeForm, FIELD_NAMES.variantProfileId, "")
      };
    } catch (error) {
      safeWarn("Ensure definition variant hidden fields failed.", error);
      return {};
    }
  }

  function ensureUploadHiddenFields(form) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm) {
        return {};
      }

      return {
        geometryModelUploadsJson: ensureHiddenField(safeForm, FIELD_NAMES.geometryModelUploadsJson, stringifyJson(emptyUploadPayload("geometry_model"))),
        technicalDocumentUploadsJson: ensureHiddenField(safeForm, FIELD_NAMES.technicalDocumentUploadsJson, stringifyJson(emptyUploadPayload("technical_documents"))),
        variantDocumentUploadsJson: ensureHiddenField(safeForm, FIELD_NAMES.variantDocumentUploadsJson, stringifyJson(emptyUploadPayload("variant_documents")))
      };
    } catch (error) {
      safeWarn("Ensure upload hidden fields failed.", error);
      return {};
    }
  }

  function getRuntimeDefinitionVariants(form) {
    try {
      var variantState = window.VectoplanCreateVariantState;
      var variants = [];

      if (variantState && typeof variantState.getPayload === "function") {
        var payload = variantState.getPayload();

        if (Array.isArray(payload)) {
          variants = payload;
        } else if (payload && Array.isArray(payload.variants)) {
          variants = payload.variants;
        } else if (payload && Array.isArray(payload.definition_variants)) {
          variants = payload.definition_variants;
        } else if (payload && Array.isArray(payload.definitionVariants)) {
          variants = payload.definitionVariants;
        }
      }

      if (!variants.length && variantState && typeof variantState.getVariants === "function") {
        variants = variantState.getVariants() || [];
      }

      if (!variants.length && variantState && typeof variantState.getPayloadJson === "function") {
        var parsed = safeJsonParse(variantState.getPayloadJson(), null);

        if (Array.isArray(parsed)) {
          variants = parsed;
        } else if (parsed && Array.isArray(parsed.variants)) {
          variants = parsed.variants;
        }
      }

      if (!variants.length && window.VectoplanCreateVariantTable && typeof window.VectoplanCreateVariantTable.getPayloads === "function") {
        variants = window.VectoplanCreateVariantTable.getPayloads(resolveForm(form)) || [];
      }

      if (variants.length) {
        localState.runtimeVariantCount = variants.length;
      }

      return Array.isArray(variants) ? variants : [];
    } catch (error) {
      safeWarn("Runtime definition variant read failed.", error);
      return [];
    }
  }

  function buildFallbackDefinitionVariantsFromLegacyRows(form) {
    try {
      var safeForm = resolveForm(form);
      var rows = safeForm ? qsa(selectorFor("variantRow"), safeForm) : [];
      var context = buildPayloadContext(safeForm);
      var variants = [];

      rows.forEach(function (row, index) {
        try {
          var variant = variantFromLegacyRow(row, index, context);

          if (variant) {
            variants.push(variant);
          }
        } catch (rowError) {
          safeWarn("Legacy variant row skipped.", rowError);
        }
      });

      if (!variants.length) {
        variants.push(buildDefaultVariant(context));
      }

      localState.fallbackVariantCount = variants.length;

      return variants;
    } catch (error) {
      safeWarn("Fallback definition variants failed.", error);
      return [buildDefaultVariant(buildPayloadContext(resolveForm(form)))];
    }
  }

  function variantFromLegacyRow(row, index, context) {
    try {
      if (!row) {
        return null;
      }

      var variantId = getRowFieldValue(row, "variant_slug") ||
        getRowFieldValue(row, "slug") ||
        row.getAttribute("data-vp-variant-id") ||
        row.getAttribute("data-vp-definition-variant-id") ||
        getRowFieldValue(row, "variant_id") ||
        (index === 0 ? "default" : "variant_" + (index + 1));

      var label = getRowFieldValue(row, "variant_name") ||
        row.getAttribute("data-vp-variant-label") ||
        getRowFieldValue(row, "label") ||
        getRowFieldValue(row, "name") ||
        (index === 0 ? "Standard" : "Variante " + (index + 1));

      var description = getRowFieldValue(row, "variant_description") ||
        getRowFieldValue(row, "description") ||
        "";

      var variantProfileId = getRowFieldValue(row, "variant_profile_id") ||
        row.getAttribute("data-vp-variant-profile-id") ||
        context.variant_profile_id ||
        "";

      var definitionValuesJson = getRowFieldValue(row, "definition_values_json");
      var definitionValues = safeJsonParse(definitionValuesJson, {});
      var summaryRaw = getRowFieldValue(row, "definition_summary");
      var additionalRaw = getRowFieldValue(row, "additional_field_keys");
      var additionalFieldKeys = normalizeAdditionalKeys(additionalRaw);

      var isDefault = index === 0 ||
        toBoolean(getRowFieldValue(row, "variant_is_default"), false) ||
        toBoolean(row.getAttribute("data-vp-is-default"), false) ||
        row.getAttribute("data-vp-default") === "true";

      return {
        variant_id: normalizeVariantId(variantId, index),
        variantId: normalizeVariantId(variantId, index),
        label: String(label || "").trim() || (index === 0 ? "Standard" : "Variante " + (index + 1)),
        name: String(label || "").trim() || (index === 0 ? "Standard" : "Variante " + (index + 1)),
        description: String(description || "").trim(),
        is_default: !!isDefault,
        isDefault: !!isDefault,
        family_profile_id: context.family_profile_id || "",
        familyProfileId: context.family_profile_id || "",
        variant_profile_id: variantProfileId,
        variantProfileId: variantProfileId,
        object_kind: context.object_kind || "cell_block",
        objectKind: context.object_kind || "cell_block",
        definition_values: definitionValues && typeof definitionValues === "object" && !Array.isArray(definitionValues) ? definitionValues : {},
        definitionValues: definitionValues && typeof definitionValues === "object" && !Array.isArray(definitionValues) ? definitionValues : {},
        definition_values_json: definitionValuesJson || "{}",
        definitionValuesJson: definitionValuesJson || "{}",
        definition_summary: summaryRaw || "",
        definitionSummary: summaryRaw || "",
        additional_field_keys: additionalFieldKeys,
        additionalFieldKeys: additionalFieldKeys,
        source: "legacy_row"
      };
    } catch (error) {
      safeWarn("Variant from legacy row failed.", error);
      return null;
    }
  }

  function getRowFieldValue(row, fieldName) {
    try {
      if (!row || !fieldName) {
        return "";
      }

      var selectorsToTry = [
        "[data-create-field='" + cssEscape(fieldName) + "']",
        "[data-vp-row-" + fieldName.replace(/_/g, "-") + "]",
        "[data-vp-" + fieldName.replace(/_/g, "-") + "]",
        "[name$='[" + cssEscape(fieldName) + "]']",
        "[name='" + cssEscape(fieldName) + "']"
      ];

      for (var index = 0; index < selectorsToTry.length; index += 1) {
        var field = qs(selectorsToTry[index], row);

        if (field && typeof field.value !== "undefined") {
          return String(field.value || "");
        }
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function buildDefaultVariant(context) {
    try {
      var safeContext = context || {};

      return {
        variant_id: "default",
        variantId: "default",
        label: "Standard",
        name: "Standard",
        description: "",
        is_default: true,
        isDefault: true,
        family_profile_id: safeContext.family_profile_id || "",
        familyProfileId: safeContext.family_profile_id || "",
        variant_profile_id: safeContext.variant_profile_id || "",
        variantProfileId: safeContext.variant_profile_id || "",
        object_kind: safeContext.object_kind || "cell_block",
        objectKind: safeContext.object_kind || "cell_block",
        definition_values: {},
        definitionValues: {},
        additional_field_keys: [],
        additionalFieldKeys: [],
        source: "payload_default"
      };
    } catch (error) {
      return {
        variant_id: "default",
        label: "Standard",
        description: "",
        is_default: true,
        definition_values: {},
        additional_field_keys: []
      };
    }
  }

  function getDefinitionVariants(form) {
    try {
      var safeForm = resolveForm(form);
      var context = buildPayloadContext(safeForm);
      var variants = [];

      variants = getRuntimeDefinitionVariants(safeForm);

      if (!variants.length) {
        variants = readDefinitionVariantsJson(safeForm);
      }

      if (!variants.length) {
        variants = buildFallbackDefinitionVariantsFromLegacyRows(safeForm);
      }

      return normalizeDefinitionVariants(variants, context);
    } catch (error) {
      safeWarn("Get definition variants failed.", error);
      return [buildDefaultVariant(buildPayloadContext(resolveForm(form)))];
    }
  }

  function getDefinitionVariantsJson(form) {
    try {
      var variants = getDefinitionVariants(form);
      return stringifyJson(variants);
    } catch (error) {
      safeWarn("Get definition variants JSON failed.", error);
      return "[]";
    }
  }

  function readDefinitionVariantsJson(form) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm) {
        return [];
      }

      var field = safeForm.elements ? safeForm.elements[FIELD_NAMES.definitionVariantsJson] : null;

      if (!field) {
        field = qs("[name='" + cssEscape(FIELD_NAMES.definitionVariantsJson) + "']", safeForm);
      }

      var raw = field && typeof field.value !== "undefined" ? field.value : "";
      var parsed = safeJsonParse(raw, []);

      if (Array.isArray(parsed)) {
        return parsed;
      }

      if (parsed && Array.isArray(parsed.variants)) {
        return parsed.variants;
      }

      if (parsed && Array.isArray(parsed.definition_variants)) {
        return parsed.definition_variants;
      }

      if (parsed && Array.isArray(parsed.definitionVariants)) {
        return parsed.definitionVariants;
      }

      return [];
    } catch (error) {
      safeWarn("Read definition variants JSON failed.", error);
      return [];
    }
  }

  function normalizeDefinitionVariants(variants, context) {
    try {
      var safeVariants = Array.isArray(variants) ? variants : [];
      var safeContext = context || {};
      var normalized = [];

      safeVariants.forEach(function (variant, index) {
        try {
          var item = normalizeDefinitionVariant(variant, index, safeContext);

          if (item) {
            normalized.push(item);
          }
        } catch (variantError) {
          safeWarn("Definition variant normalization skipped.", variantError);
        }
      });

      if (!normalized.length) {
        normalized.push(buildDefaultVariant(safeContext));
      }

      return ensureSingleDefaultVariant(normalized);
    } catch (error) {
      safeWarn("Normalize definition variants failed.", error);
      return [buildDefaultVariant(context || {})];
    }
  }

  function normalizeDefinitionVariant(variant, index, context) {
    try {
      var safeVariant = variant && typeof variant === "object" ? cloneObject(variant) : {};
      var safeContext = context || {};
      var safeIndex = typeof index === "number" ? index : 0;

      var rawId = firstValue(safeVariant, VARIANT_ID_KEYS);
      var rawLabel = firstValue(safeVariant, VARIANT_LABEL_KEYS);
      var rawDescription = firstValue(safeVariant, VARIANT_DESCRIPTION_KEYS);

      var variantId = normalizeVariantId(rawId || (safeIndex === 0 ? "default" : "variant_" + (safeIndex + 1)), safeIndex);
      var label = String(rawLabel || "").trim() || (variantId === "default" ? "Standard" : humanizeVariantId(variantId));
      var description = String(rawDescription || "").trim();

      var values = extractDefinitionValues(safeVariant);
      var additionalFieldKeys = extractAdditionalFieldKeys(safeVariant, values);

      var familyProfileId = safeVariant.family_profile_id ||
        safeVariant.familyProfileId ||
        safeContext.family_profile_id ||
        safeContext.familyProfileId ||
        "";

      var variantProfileId = safeVariant.variant_profile_id ||
        safeVariant.variantProfileId ||
        safeContext.variant_profile_id ||
        safeContext.variantProfileId ||
        "";

      var objectKind = safeVariant.object_kind ||
        safeVariant.objectKind ||
        safeContext.object_kind ||
        safeContext.objectKind ||
        "cell_block";

      var isDefault = toBoolean(
        safeVariant.is_default !== undefined ? safeVariant.is_default : safeVariant.isDefault,
        safeIndex === 0 || variantId === "default"
      );

      var normalized = {
        variant_id: variantId,
        variantId: variantId,
        label: label,
        name: label,
        description: description,
        is_default: !!isDefault,
        isDefault: !!isDefault,
        family_profile_id: String(familyProfileId || "").trim(),
        familyProfileId: String(familyProfileId || "").trim(),
        variant_profile_id: String(variantProfileId || "").trim(),
        variantProfileId: String(variantProfileId || "").trim(),
        object_kind: normalizeToken(objectKind, "cell_block"),
        objectKind: normalizeToken(objectKind, "cell_block"),
        definition_values: values,
        definitionValues: values,
        definition_values_json: stringifyJson(values),
        definitionValuesJson: stringifyJson(values),
        additional_field_keys: additionalFieldKeys,
        additionalFieldKeys: additionalFieldKeys
      };

      if (safeVariant.summary) {
        normalized.summary = safeVariant.summary;
      }

      if (safeVariant.definition_summary || safeVariant.definitionSummary) {
        normalized.definition_summary = safeVariant.definition_summary || safeVariant.definitionSummary;
        normalized.definitionSummary = normalized.definition_summary;
      }

      if (safeVariant.summary_payload || safeVariant.summaryPayload) {
        normalized.summary_payload = safeVariant.summary_payload || safeVariant.summaryPayload;
        normalized.summaryPayload = normalized.summary_payload;
      }

      if (safeVariant.validation) {
        normalized.validation = safeVariant.validation;
      }

      if (safeVariant.source) {
        normalized.source = safeVariant.source;
      }

      return normalized;
    } catch (error) {
      safeWarn("Normalize definition variant failed.", error);
      return null;
    }
  }

  function extractDefinitionValues(variant) {
    try {
      var candidate = variant.definition_values ||
        variant.definitionValues ||
        variant.values ||
        variant.definition_values_json ||
        variant.definitionValuesJson ||
        {};

      var values = {};

      if (typeof candidate === "string") {
        values = safeJsonParse(candidate, {});
      } else if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
        values = cloneObject(candidate);
      }

      if (!values || typeof values !== "object" || Array.isArray(values)) {
        values = {};
      }

      Object.keys(values).forEach(function (key) {
        try {
          if (SYSTEM_VARIANT_VALUE_KEYS[key]) {
            delete values[key];
          }
        } catch (deleteError) {
          safeWarn("System definition value cleanup skipped.", deleteError);
        }
      });

      return values;
    } catch (error) {
      safeWarn("Extract definition values failed.", error);
      return {};
    }
  }

  function extractAdditionalFieldKeys(variant, values) {
    try {
      var keys = variant.additional_field_keys ||
        variant.additionalFieldKeys ||
        variant.additional_fields ||
        variant.additionalFields ||
        [];

      if (typeof keys === "string") {
        keys = normalizeAdditionalKeys(keys);
      }

      if (!Array.isArray(keys)) {
        keys = [];
      }

      var result = uniqueArray(keys.map(function (key) {
        return String(key || "").trim();
      }).filter(Boolean));

      Object.keys(values || {}).forEach(function (key) {
        try {
          if (!SYSTEM_VARIANT_VALUE_KEYS[key] && result.indexOf(key) === -1 && isLikelyAdditionalValueKey(key)) {
            result.push(key);
          }
        } catch (valueError) {
          safeWarn("Additional field key inference skipped.", valueError);
        }
      });

      return uniqueArray(result);
    } catch (error) {
      safeWarn("Extract additional field keys failed.", error);
      return [];
    }
  }

  function normalizeAdditionalKeys(value) {
    try {
      if (Array.isArray(value)) {
        return uniqueArray(value.map(function (item) {
          return String(item || "").trim();
        }).filter(Boolean));
      }

      if (typeof value === "string") {
        var parsed = safeJsonParse(value, null);

        if (Array.isArray(parsed)) {
          return normalizeAdditionalKeys(parsed);
        }

        return uniqueArray(value.split(",").map(function (item) {
          return String(item || "").trim();
        }).filter(Boolean));
      }

      return [];
    } catch (error) {
      return [];
    }
  }

  function isLikelyAdditionalValueKey(key) {
    try {
      var text = String(key || "").trim();

      if (!text || SYSTEM_VARIANT_VALUE_KEYS[text]) {
        return false;
      }

      return text.indexOf(".") !== -1;
    } catch (error) {
      return false;
    }
  }

  function ensureSingleDefaultVariant(variants) {
    try {
      var list = Array.isArray(variants) ? variants : [];
      var defaultIndex = -1;

      list.forEach(function (variant, index) {
        if (toBoolean(variant.is_default, false) || toBoolean(variant.isDefault, false) || variant.variant_id === "default") {
          if (defaultIndex === -1) {
            defaultIndex = index;
          }
        }
      });

      if (defaultIndex === -1 && list.length) {
        defaultIndex = 0;
      }

      list.forEach(function (variant, index) {
        var isDefault = index === defaultIndex;

        variant.is_default = isDefault;
        variant.isDefault = isDefault;

        if (isDefault && !variant.variant_id) {
          variant.variant_id = "default";
          variant.variantId = "default";
        }
      });

      return list;
    } catch (error) {
      safeWarn("Ensure single default variant failed.", error);
      return variants;
    }
  }

  function resolveDefaultVariantId(variants, form) {
    try {
      var list = Array.isArray(variants) ? variants : [];

      for (var index = 0; index < list.length; index += 1) {
        if (toBoolean(list[index].is_default, false) || toBoolean(list[index].isDefault, false)) {
          return list[index].variant_id || list[index].variantId || "default";
        }
      }

      var safeForm = resolveForm(form);
      var fieldValue = getFieldValue(safeForm, FIELD_NAMES.defaultVariantId);

      return fieldValue || "default";
    } catch (error) {
      return "default";
    }
  }

  function augmentPayloadWithDefinitionVariants(payload, form) {
    try {
      if (!payload) {
        return payload;
      }

      var variants = getDefinitionVariants(form);
      var defaultVariantId = resolveDefaultVariantId(variants, form);
      var variantsJson = stringifyJson(variants);

      payload.definition_variants = variants;
      payload.definitionVariants = variants;
      payload.definition_variants_json = variantsJson;
      payload.definitionVariantsJson = variantsJson;
      payload.default_variant_id = defaultVariantId;
      payload.defaultVariantId = defaultVariantId;

      return payload;
    } catch (error) {
      safeWarn("Augment payload with definition variants failed.", error);
      return payload;
    }
  }

  function augmentPayloadWithUploads(payload, form, options) {
    try {
      if (!payload) {
        return payload;
      }

      var uploadMetadata = getUploadMetadata(form, {
        source: options && options.source ? options.source : "augmentPayload"
      });

      payload.uploads = uploadMetadata.byKind || {};
      payload.uploadsByKind = uploadMetadata.byKind || {};
      payload.uploads_summary = uploadMetadata.summary || {};
      payload.uploadsSummary = uploadMetadata.summary || {};
      payload.uploads_json = stringifyJson(uploadMetadata.byKind || {});
      payload.uploadsJson = payload.uploads_json;

      payload.geometry_model_uploads = uploadMetadata.geometry_model || emptyUploadPayload("geometry_model");
      payload.geometryModelUploads = payload.geometry_model_uploads;
      payload.geometry_model_uploads_json = stringifyJson(payload.geometry_model_uploads);
      payload.geometryModelUploadsJson = payload.geometry_model_uploads_json;
      payload.geometry_model_files = payload.geometry_model_uploads.files || [];

      payload.technical_document_uploads = uploadMetadata.technical_documents || emptyUploadPayload("technical_documents");
      payload.technicalDocumentUploads = payload.technical_document_uploads;
      payload.technical_document_uploads_json = stringifyJson(payload.technical_document_uploads);
      payload.technicalDocumentUploadsJson = payload.technical_document_uploads_json;
      payload.technical_document_files = payload.technical_document_uploads.files || [];

      payload.variant_document_uploads = uploadMetadata.variant_documents || emptyUploadPayload("variant_documents");
      payload.variantDocumentUploads = payload.variant_document_uploads;
      payload.variant_document_uploads_json = stringifyJson(payload.variant_document_uploads);
      payload.variantDocumentUploadsJson = payload.variant_document_uploads_json;
      payload.variant_document_files = payload.variant_document_uploads.files || [];
      payload.variant_document_uploads_by_field = uploadMetadata.variantDocumentsByField || {};
      payload.variantDocumentUploadsByField = payload.variant_document_uploads_by_field;

      syncUploadHiddenFieldsFromMetadata(form, uploadMetadata, {
        force: false
      });

      return payload;
    } catch (error) {
      safeWarn("Augment payload with uploads failed.", error);
      return payload;
    }
  }

  function getUploadMetadata(form, options) {
    try {
      var safeForm = resolveForm(form);
      var source = options && options.source ? options.source : "api";
      var payloads = [];

      payloads = payloads.concat(readRuntimeUploadPayloads(safeForm));
      payloads = payloads.concat(readHiddenUploadPayloads(safeForm));
      payloads = payloads.concat(readFileInputUploadPayloads(safeForm));

      var bundle = mergeUploadPayloads(payloads);
      bundle.source = source;
      bundle.timestamp = timestamp();

      return bundle;
    } catch (error) {
      safeWarn("Get upload metadata failed.", error);

      return {
        byKind: {},
        geometry_model: emptyUploadPayload("geometry_model"),
        technical_documents: emptyUploadPayload("technical_documents"),
        variant_documents: emptyUploadPayload("variant_documents"),
        variantDocumentsByField: {},
        summary: {
          fileCount: 0,
          errorCount: 1,
          ok: false
        },
        errors: [{
          code: "upload_metadata_failed",
          message: String(error && error.message ? error.message : error)
        }]
      };
    }
  }

  function readRuntimeUploadPayloads(form) {
    try {
      var safeForm = resolveForm(form);
      var runtime = window.VectoplanCreateUploads;

      if (!runtime || typeof runtime.getPayloads !== "function") {
        return [];
      }

      var payloads = runtime.getPayloads(safeForm || document);

      return Array.isArray(payloads) ? payloads : [];
    } catch (error) {
      safeWarn("Runtime upload payload read failed.", error);
      return [];
    }
  }

  function readHiddenUploadPayloads(form) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm) {
        return [];
      }

      var nodes = qsa(selectorFor("uploadMetadata"), safeForm);
      var payloads = [];

      nodes.forEach(function (node) {
        try {
          if (!node || typeof node.value === "undefined") {
            return;
          }

          var name = node.getAttribute("name") || "";
          var kind = inferUploadKindFromFieldName(name) ||
            node.getAttribute("data-vp-upload-metadata-kind") ||
            node.getAttribute("data-vp-upload-kind") ||
            "";

          var fieldKey = node.getAttribute("data-vp-field-key") || inferFieldKeyFromName(name);
          var parsed = parseUploadValue(node.value, kind, fieldKey, name);

          if (Array.isArray(parsed)) {
            payloads = payloads.concat(parsed);
          } else if (parsed) {
            payloads.push(parsed);
          }
        } catch (nodeError) {
          safeWarn("Hidden upload metadata skipped.", nodeError);
        }
      });

      return payloads;
    } catch (error) {
      safeWarn("Hidden upload payload read failed.", error);
      return [];
    }
  }

  function readFileInputUploadPayloads(form) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm) {
        return [];
      }

      return qsa(selectorFor("uploadInput"), safeForm).map(function (input) {
        try {
          var zone = input.closest ? input.closest(selectorFor("uploadZone")) : null;
          var kind = input.getAttribute("data-vp-upload-kind") ||
            (zone ? zone.getAttribute("data-vp-upload-kind") : "") ||
            inferUploadKindFromFieldName(input.name || "") ||
            "generic_upload";

          var purpose = input.getAttribute("data-vp-upload-purpose") ||
            (zone ? zone.getAttribute("data-vp-upload-purpose") : "") ||
            getDefaultUploadPurpose(kind);

          var fieldKey = input.getAttribute("data-vp-field-key") ||
            (zone ? zone.getAttribute("data-vp-field-key") : "") ||
            inferFieldKeyFromName(input.name || "");

          var files = qsaFileList(input.files).map(function (file, index) {
            return fileToUploadFile(file, index, kind, purpose, fieldKey);
          });

          return normalizeUploadPayload({
            kind: kind,
            purpose: purpose,
            field_key: fieldKey,
            fieldKey: fieldKey,
            field: input.name || "",
            count: files.length,
            files: files,
            errors: [],
            ok: true,
            backend_enabled: false,
            backendEnabled: false,
            local_only: true,
            localOnly: true,
            source: "file_input"
          }, kind, fieldKey);
        } catch (inputError) {
          safeWarn("File input upload payload skipped.", inputError);
          return null;
        }
      }).filter(Boolean);
    } catch (error) {
      safeWarn("File input upload payload read failed.", error);
      return [];
    }
  }

  function parseUploadValue(raw, fallbackKind, fieldKey, fieldName) {
    try {
      if (raw === null || typeof raw === "undefined" || String(raw).trim() === "") {
        return normalizeUploadPayload(emptyUploadPayload(fallbackKind || inferUploadKindFromFieldName(fieldName) || "generic_upload"), fallbackKind, fieldKey);
      }

      var parsed = safeJsonParse(raw, null);

      if (Array.isArray(parsed)) {
        return normalizeUploadPayload({
          kind: fallbackKind || inferUploadKindFromFieldName(fieldName) || "variant_documents",
          purpose: getDefaultUploadPurpose(fallbackKind || inferUploadKindFromFieldName(fieldName) || "variant_documents"),
          field_key: fieldKey || "",
          fieldKey: fieldKey || "",
          field: fieldName || "",
          files: parsed,
          count: parsed.length,
          errors: [],
          ok: true,
          backend_enabled: false,
          backendEnabled: false,
          local_only: true,
          localOnly: true,
          source: "hidden_array"
        }, fallbackKind, fieldKey);
      }

      if (parsed && typeof parsed === "object") {
        return normalizeUploadPayload(parsed.payload || parsed, fallbackKind, fieldKey);
      }

      return normalizeUploadPayload(emptyUploadPayload(fallbackKind || "generic_upload"), fallbackKind, fieldKey);
    } catch (error) {
      safeWarn("Upload value parse failed.", error);
      return normalizeUploadPayload(emptyUploadPayload(fallbackKind || "generic_upload"), fallbackKind, fieldKey);
    }
  }

  function normalizeUploadPayload(payload, fallbackKind, fallbackFieldKey) {
    try {
      var source = payload && typeof payload === "object" ? cloneObject(payload) : {};
      var kind = normalizeToken(source.kind || source.upload_kind || fallbackKind || "generic_upload", "generic_upload");
      var purpose = normalizeToken(source.purpose || source.upload_purpose || getDefaultUploadPurpose(kind), getDefaultUploadPurpose(kind));
      var files = Array.isArray(source.files) ? source.files : [];
      var errors = Array.isArray(source.errors) ? source.errors : [];
      var fieldKey = source.field_key || source.fieldKey || fallbackFieldKey || "";

      files = files.map(function (file, index) {
        try {
          var meta = file && typeof file === "object" ? cloneObject(file) : {};
          meta.index = typeof meta.index === "number" ? meta.index : index;
          meta.kind = meta.kind || kind;
          meta.purpose = meta.purpose || purpose;
          meta.field_key = meta.field_key || meta.fieldKey || fieldKey;
          meta.fieldKey = meta.fieldKey || meta.field_key || fieldKey;
          meta.local_only = meta.local_only !== undefined ? meta.local_only : true;
          meta.localOnly = meta.localOnly !== undefined ? meta.localOnly : meta.local_only;
          meta.backend_stored = meta.backend_stored !== undefined ? meta.backend_stored : false;
          meta.backendStored = meta.backendStored !== undefined ? meta.backendStored : meta.backend_stored;
          meta.extension = meta.extension || extensionFromName(meta.name || "");
          meta.size_label = meta.size_label || meta.sizeLabel || fileSizeLabel(meta.size || 0);
          meta.sizeLabel = meta.sizeLabel || meta.size_label;
          return meta;
        } catch (fileError) {
          return fileToUploadFile(null, index, kind, purpose, fieldKey);
        }
      });

      var validCount = files.filter(function (file) {
        return file.valid !== false;
      }).length;
      var invalidCount = files.filter(function (file) {
        return file.valid === false;
      }).length;

      return {
        version: source.version || PAYLOAD_VERSION,
        kind: kind,
        purpose: purpose,
        field_key: fieldKey,
        fieldKey: fieldKey,
        field: source.field || "",
        metadata_field: source.metadata_field || source.metadataField || "",
        metadataField: source.metadataField || source.metadata_field || "",
        backend_enabled: toBoolean(source.backend_enabled !== undefined ? source.backend_enabled : source.backendEnabled, false),
        backendEnabled: toBoolean(source.backend_enabled !== undefined ? source.backend_enabled : source.backendEnabled, false),
        local_only: source.local_only !== undefined ? toBoolean(source.local_only, true) : toBoolean(source.localOnly, true),
        localOnly: source.localOnly !== undefined ? toBoolean(source.localOnly, true) : toBoolean(source.local_only, true),
        count: parseInt(source.count, 10) || files.length,
        valid_count: parseInt(source.valid_count !== undefined ? source.valid_count : source.validCount, 10) || validCount,
        validCount: parseInt(source.valid_count !== undefined ? source.valid_count : source.validCount, 10) || validCount,
        invalid_count: parseInt(source.invalid_count !== undefined ? source.invalid_count : source.invalidCount, 10) || invalidCount,
        invalidCount: parseInt(source.invalid_count !== undefined ? source.invalid_count : source.invalidCount, 10) || invalidCount,
        files: files,
        errors: errors,
        ok: source.ok !== undefined ? toBoolean(source.ok, errors.length === 0) : errors.length === 0,
        updated_at: source.updated_at || source.updatedAt || timestamp(),
        updatedAt: source.updatedAt || source.updated_at || timestamp(),
        source: source.source || "normalized"
      };
    } catch (error) {
      safeWarn("Upload payload normalization failed.", error);
      return emptyUploadPayload(fallbackKind || "generic_upload");
    }
  }

  function mergeUploadPayloads(payloads) {
    try {
      var list = Array.isArray(payloads) ? payloads : [];
      var byKind = {};
      var variantDocumentsByField = {};
      var allFiles = [];
      var allErrors = [];

      list.forEach(function (payload) {
        try {
          if (!payload) {
            return;
          }

          var normalized = normalizeUploadPayload(payload, payload.kind || "", payload.fieldKey || payload.field_key || "");
          var kind = normalized.kind || "generic_upload";

          if (!byKind[kind]) {
            byKind[kind] = emptyUploadPayload(kind);
            byKind[kind].purpose = normalized.purpose || byKind[kind].purpose;
          }

          byKind[kind].files = dedupeUploadFiles((byKind[kind].files || []).concat(normalized.files || []));
          byKind[kind].errors = (byKind[kind].errors || []).concat(normalized.errors || []);
          byKind[kind].count = byKind[kind].files.length;
          byKind[kind].valid_count = byKind[kind].files.filter(function (file) {
            return file.valid !== false;
          }).length;
          byKind[kind].validCount = byKind[kind].valid_count;
          byKind[kind].invalid_count = byKind[kind].files.filter(function (file) {
            return file.valid === false;
          }).length;
          byKind[kind].invalidCount = byKind[kind].invalid_count;
          byKind[kind].ok = byKind[kind].errors.length === 0;
          byKind[kind].updated_at = timestamp();
          byKind[kind].updatedAt = byKind[kind].updated_at;

          if (kind === "variant_documents") {
            var fieldKey = normalized.fieldKey || normalized.field_key || "documents";

            if (!variantDocumentsByField[fieldKey]) {
              variantDocumentsByField[fieldKey] = emptyUploadPayload("variant_documents");
              variantDocumentsByField[fieldKey].field_key = fieldKey;
              variantDocumentsByField[fieldKey].fieldKey = fieldKey;
            }

            variantDocumentsByField[fieldKey].files = dedupeUploadFiles((variantDocumentsByField[fieldKey].files || []).concat(normalized.files || []));
            variantDocumentsByField[fieldKey].errors = (variantDocumentsByField[fieldKey].errors || []).concat(normalized.errors || []);
            variantDocumentsByField[fieldKey].count = variantDocumentsByField[fieldKey].files.length;
            variantDocumentsByField[fieldKey].ok = variantDocumentsByField[fieldKey].errors.length === 0;
          }
        } catch (itemError) {
          safeWarn("Upload payload merge item skipped.", itemError);
        }
      });

      Object.keys(byKind).forEach(function (kind) {
        allFiles = allFiles.concat(byKind[kind].files || []);
        allErrors = allErrors.concat(byKind[kind].errors || []);
      });

      if (!byKind.geometry_model) {
        byKind.geometry_model = emptyUploadPayload("geometry_model");
      }

      if (!byKind.technical_documents) {
        byKind.technical_documents = emptyUploadPayload("technical_documents");
      }

      if (!byKind.variant_documents) {
        byKind.variant_documents = emptyUploadPayload("variant_documents");
      }

      return {
        byKind: byKind,
        geometry_model: byKind.geometry_model,
        technical_documents: byKind.technical_documents,
        variant_documents: byKind.variant_documents,
        variantDocumentsByField: variantDocumentsByField,
        summary: {
          fileCount: dedupeUploadFiles(allFiles).length,
          errorCount: allErrors.length,
          ok: allErrors.length === 0,
          kinds: Object.keys(byKind),
          timestamp: timestamp()
        },
        errors: allErrors
      };
    } catch (error) {
      safeWarn("Upload payload merge failed.", error);

      return {
        byKind: {},
        geometry_model: emptyUploadPayload("geometry_model"),
        technical_documents: emptyUploadPayload("technical_documents"),
        variant_documents: emptyUploadPayload("variant_documents"),
        variantDocumentsByField: {},
        summary: {
          fileCount: 0,
          errorCount: 1,
          ok: false,
          timestamp: timestamp()
        },
        errors: [{
          code: "merge_failed",
          message: String(error && error.message ? error.message : error)
        }]
      };
    }
  }

  function syncUploadHiddenFieldsFromMetadata(form, uploadMetadata, options) {
    try {
      var safeForm = resolveForm(form);
      var safeOptions = options || {};
      var fields = safeOptions.fields || ensureUploadHiddenFields(safeForm);

      writeHiddenJsonIfChanged(fields.geometryModelUploadsJson, uploadMetadata.geometry_model || emptyUploadPayload("geometry_model"), safeOptions.force === true);
      writeHiddenJsonIfChanged(fields.technicalDocumentUploadsJson, uploadMetadata.technical_documents || emptyUploadPayload("technical_documents"), safeOptions.force === true);
      writeHiddenJsonIfChanged(fields.variantDocumentUploadsJson, uploadMetadata.variant_documents || emptyUploadPayload("variant_documents"), safeOptions.force === true);
    } catch (error) {
      safeWarn("Upload hidden field sync failed.", error);
    }
  }

  function writeHiddenJsonIfChanged(field, value, force) {
    try {
      if (!field) {
        return false;
      }

      var text = stringifyJson(value);

      if (!force && field.value === text) {
        return false;
      }

      field.value = text;
      field.setAttribute("data-vp-payload-sync-version", PAYLOAD_VERSION);
      field.setAttribute("data-vp-payload-sync-at", String(Date.now()));

      return true;
    } catch (error) {
      safeWarn("Hidden JSON write failed.", error);
      return false;
    }
  }

  function uploadMetadataSignature(uploadMetadata) {
    try {
      var source = uploadMetadata || {};
      var byKind = source.byKind || {};
      var normalized = {};

      ["geometry_model", "technical_documents", "variant_documents"].forEach(function (kind) {
        var payload = byKind[kind] || source[kind] || emptyUploadPayload(kind);

        normalized[kind] = {
          count: payload.count || 0,
          ok: payload.ok !== false,
          files: (payload.files || []).map(function (file) {
            return {
              name: file.name || "",
              size: file.size || 0,
              type: file.type || "",
              extension: file.extension || "",
              lastModified: file.lastModified || file.last_modified || null,
              fieldKey: file.fieldKey || file.field_key || ""
            };
          }),
          errors: (payload.errors || []).map(function (errorItem) {
            return {
              code: errorItem.code || "",
              file: errorItem.file || "",
              message: errorItem.message || ""
            };
          })
        };
      });

      return JSON.stringify(normalized);
    } catch (error) {
      return String(Date.now());
    }
  }

  function ensureDefinitionVariantAliases(payload) {
    try {
      if (!payload || typeof payload !== "object") {
        return payload;
      }

      mirrorAlias(payload, "definition_variants_json", "definitionVariantsJson");
      mirrorAlias(payload, "definition_variants", "definitionVariants");
      mirrorAlias(payload, "default_variant_id", "defaultVariantId");
      mirrorAlias(payload, "family_profile_id", "familyProfileId");
      mirrorAlias(payload, "variant_profile_id", "variantProfileId");

      return payload;
    } catch (error) {
      safeWarn("Ensure definition variant aliases failed.", error);
      return payload;
    }
  }

  function ensureUploadAliases(payload) {
    try {
      if (!payload || typeof payload !== "object") {
        return payload;
      }

      mirrorAlias(payload, "geometry_model_uploads_json", "geometryModelUploadsJson");
      mirrorAlias(payload, "technical_document_uploads_json", "technicalDocumentUploadsJson");
      mirrorAlias(payload, "variant_document_uploads_json", "variantDocumentUploadsJson");
      mirrorAlias(payload, "uploads_json", "uploadsJson");

      return payload;
    } catch (error) {
      safeWarn("Ensure upload aliases failed.", error);
      return payload;
    }
  }

  function mirrorAlias(object, snakeKey, camelKey) {
    try {
      if (object[snakeKey] && !object[camelKey]) {
        object[camelKey] = object[snakeKey];
      }

      if (object[camelKey] && !object[snakeKey]) {
        object[snakeKey] = object[camelKey];
      }
    } catch (error) {
      /* no-op */
    }
  }

  function syncProfileIdsIntoPayload(payload, form) {
    try {
      var safeForm = resolveForm(form);
      var context = buildPayloadContext(safeForm);

      if (!payload.family_profile_id && context.family_profile_id) {
        payload.family_profile_id = context.family_profile_id;
      }

      if (!payload.familyProfileId && payload.family_profile_id) {
        payload.familyProfileId = payload.family_profile_id;
      }

      if (!payload.variant_profile_id && context.variant_profile_id) {
        payload.variant_profile_id = context.variant_profile_id;
      }

      if (!payload.variantProfileId && payload.variant_profile_id) {
        payload.variantProfileId = payload.variant_profile_id;
      }

      return payload;
    } catch (error) {
      safeWarn("Sync profile IDs into payload failed.", error);
      return payload;
    }
  }

  function syncProfileIdsIntoForm(form, options) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm) {
        return false;
      }

      var fields = ensureDefinitionVariantHiddenFields(safeForm);
      var context = buildPayloadContext(safeForm);

      if (fields.familyProfileId && fields.familyProfileId.value !== (context.family_profile_id || "")) {
        fields.familyProfileId.value = context.family_profile_id || "";
      }

      if (fields.variantProfileId && fields.variantProfileId.value !== (context.variant_profile_id || "")) {
        fields.variantProfileId.value = context.variant_profile_id || "";
      }

      return true;
    } catch (error) {
      safeWarn("Sync profile IDs into form failed.", error);
      return false;
    }
  }

  function buildPayloadContext(form) {
    try {
      var safeForm = resolveForm(form);
      var variantProfileBundle = getCurrentVariantProfileBundle();
      var profileContext = variantProfileBundle.context || {};
      var profilePayload = variantProfileBundle.payload || {};

      var context = {
        domain: getFieldValue(safeForm, FIELD_NAMES.domain) ||
          profileContext.domain ||
          getNested(core.state, ["uiState", "defaults", "domain"], "hochbau"),

        category: getFieldValue(safeForm, FIELD_NAMES.category) ||
          profileContext.category ||
          getNested(core.state, ["uiState", "defaults", "category"], "bloecke"),

        subcategory: getFieldValue(safeForm, FIELD_NAMES.subcategory) ||
          profileContext.subcategory ||
          getNested(core.state, ["uiState", "defaults", "subcategory"], "basis"),

        object_kind: getFieldValue(safeForm, FIELD_NAMES.objectKind) ||
          profileContext.object_kind ||
          profileContext.objectKind ||
          getNested(core.state, ["uiState", "defaults", "object_kind"], "cell_block"),

        family_profile_id: getFieldValue(safeForm, FIELD_NAMES.familyProfileId) ||
          profilePayload.family_profile_id ||
          profilePayload.familyProfileId ||
          profileContext.family_profile_id ||
          profileContext.familyProfileId ||
          "",

        variant_profile_id: getFieldValue(safeForm, FIELD_NAMES.variantProfileId) ||
          profilePayload.variant_profile_id ||
          profilePayload.variantProfileId ||
          profilePayload.profile_id ||
          profilePayload.id ||
          profileContext.variant_profile_id ||
          profileContext.variantProfileId ||
          ""
      };

      context.domain = normalizeToken(context.domain, "hochbau");
      context.category = normalizeToken(context.category, "bloecke");
      context.subcategory = normalizeToken(context.subcategory, "basis");
      context.object_kind = normalizeToken(context.object_kind, "cell_block");

      return context;
    } catch (error) {
      safeWarn("Build payload context failed.", error);

      return {
        domain: "hochbau",
        category: "bloecke",
        subcategory: "basis",
        object_kind: "cell_block",
        family_profile_id: "",
        variant_profile_id: ""
      };
    }
  }

  function getCurrentVariantProfileBundle() {
    try {
      var profilesRuntime = window.VectoplanCreateVariantProfiles;

      if (profilesRuntime && typeof profilesRuntime.getResolvedProfileBundle === "function") {
        var bundle = profilesRuntime.getResolvedProfileBundle();

        if (bundle && typeof bundle === "object") {
          return bundle;
        }
      }

      if (profilesRuntime && typeof profilesRuntime.getCacheSnapshot === "function") {
        var cache = profilesRuntime.getCacheSnapshot();

        if (cache && cache.currentBundle) {
          return cache.currentBundle;
        }

        if (cache && cache.resolvedProfileBundle) {
          return cache.resolvedProfileBundle;
        }
      }

      var definitionsRuntime = window.VectoplanCreateDefinitionsRuntime;

      if (definitionsRuntime && typeof definitionsRuntime.getCurrentProfilePayload === "function") {
        return {
          payload: definitionsRuntime.getCurrentProfilePayload() || {},
          context: definitionsRuntime.collectContext ? definitionsRuntime.collectContext() || {} : {}
        };
      }

      return {
        payload: {},
        context: {}
      };
    } catch (error) {
      return {
        payload: {},
        context: {}
      };
    }
  }

  function normalizeVariantId(value, index) {
    try {
      var fallback = index === 0 ? "default" : "variant_" + (index + 1);
      var text = slugify(value || fallback);

      if (!text) {
        text = fallback;
      }

      if (index === 0 && (text === "standard" || text === "default_variant")) {
        text = "default";
      }

      return text;
    } catch (error) {
      return index === 0 ? "default" : "variant_" + (index + 1);
    }
  }

  function humanizeVariantId(value) {
    try {
      var text = String(value || "")
        .replace(/^variant_/, "Variante ")
        .replace(/_/g, " ")
        .replace(/\s+/g, " ")
        .trim();

      if (!text) {
        return "Variante";
      }

      return text.charAt(0).toUpperCase() + text.slice(1);
    } catch (error) {
      return "Variante";
    }
  }

  function firstValue(object, keys) {
    try {
      if (!object || typeof object !== "object" || !Array.isArray(keys)) {
        return "";
      }

      for (var index = 0; index < keys.length; index += 1) {
        var key = keys[index];

        if (
          Object.prototype.hasOwnProperty.call(object, key) &&
          object[key] !== null &&
          typeof object[key] !== "undefined" &&
          String(object[key]).trim() !== ""
        ) {
          return object[key];
        }
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function summarizePayload(payload) {
    try {
      var variants = [];

      if (Array.isArray(payload.definition_variants)) {
        variants = payload.definition_variants;
      } else {
        variants = safeJsonParse(payload.definition_variants_json, []);
      }

      var uploadsSummary = payload.uploads_summary || payload.uploadsSummary || {};

      return {
        family_name: payload.family_name || "",
        domain: payload.domain || "",
        category: payload.category || "",
        subcategory: payload.subcategory || "",
        object_kind: payload.object_kind || "",
        family_profile_id: payload.family_profile_id || "",
        variant_profile_id: payload.variant_profile_id || "",
        default_variant_id: payload.default_variant_id || "",
        definition_variant_count: Array.isArray(variants) ? variants.length : 0,
        has_definition_variants_json: !!payload.definition_variants_json,
        upload_file_count: uploadsSummary.fileCount || uploadsSummary.file_count || 0,
        upload_error_count: uploadsSummary.errorCount || uploadsSummary.error_count || 0,
        has_geometry_model_uploads: !!(payload.geometry_model_uploads && payload.geometry_model_uploads.count),
        has_technical_document_uploads: !!(payload.technical_document_uploads && payload.technical_document_uploads.count),
        has_variant_document_uploads: !!(payload.variant_document_uploads && payload.variant_document_uploads.count),
        timestamp: timestamp()
      };
    } catch (error) {
      return {
        summary_error: String(error && error.message ? error.message : error)
      };
    }
  }

  function resolveForm(form) {
    try {
      if (form && form.nodeType === 1) {
        return form;
      }

      return qs(selectorFor("form"));
    } catch (error) {
      return null;
    }
  }

  function getState() {
    try {
      return {
        version: PAYLOAD_VERSION,
        initialized: initialized,
        collectCount: localState.collectCount,
        syncCount: localState.syncCount,
        uploadSyncCount: localState.uploadSyncCount,
        skippedUploadSyncCount: localState.skippedUploadSyncCount,
        suppressedUploadEventCount: localState.suppressedUploadEventCount,
        fallbackVariantCount: localState.fallbackVariantCount,
        runtimeVariantCount: localState.runtimeVariantCount,
        uploadFileCount: localState.uploadFileCount,
        uploadErrorCount: localState.uploadErrorCount,
        uploadSyncActive: localState.uploadSyncActive,
        lastSync: localState.lastSync,
        lastUploadSync: localState.lastUploadSync,
        lastPayloadSummary: localState.lastPayloadSummary,
        lastError: localState.lastError
      };
    } catch (error) {
      return {
        version: PAYLOAD_VERSION,
        initialized: initialized,
        state_error: String(error && error.message ? error.message : error)
      };
    }
  }

  function emptyUploadPayload(kind) {
    try {
      var safeKind = normalizeToken(kind, "generic_upload");

      return {
        version: PAYLOAD_VERSION,
        kind: safeKind,
        purpose: getDefaultUploadPurpose(safeKind),
        field_key: "",
        fieldKey: "",
        backend_enabled: false,
        backendEnabled: false,
        local_only: true,
        localOnly: true,
        count: 0,
        valid_count: 0,
        validCount: 0,
        invalid_count: 0,
        invalidCount: 0,
        files: [],
        errors: [],
        ok: true,
        updated_at: timestamp(),
        updatedAt: timestamp(),
        source: "empty"
      };
    } catch (error) {
      return {
        version: PAYLOAD_VERSION,
        kind: kind || "generic_upload",
        count: 0,
        files: [],
        errors: [],
        ok: true
      };
    }
  }

  function fileToPayloadValue(file) {
    try {
      return {
        name: file.name || "",
        size: file.size || 0,
        size_label: fileSizeLabel(file.size || 0),
        sizeLabel: fileSizeLabel(file.size || 0),
        type: file.type || "",
        extension: extensionFromName(file.name || ""),
        last_modified: file.lastModified || null,
        lastModified: file.lastModified || null,
        backend_stored: false,
        backendStored: false,
        local_only: true,
        localOnly: true
      };
    } catch (error) {
      return {
        name: "",
        size: 0,
        type: "",
        last_modified: null,
        backend_stored: false,
        local_only: true
      };
    }
  }

  function fileToUploadFile(file, index, kind, purpose, fieldKey) {
    try {
      var base = file ? fileToPayloadValue(file) : {};

      base.index = index || 0;
      base.kind = kind || "generic_upload";
      base.purpose = purpose || getDefaultUploadPurpose(kind);
      base.field_key = fieldKey || "";
      base.fieldKey = fieldKey || "";
      base.valid = true;
      base.errors = [];

      return base;
    } catch (error) {
      return {
        index: index || 0,
        name: "",
        size: 0,
        type: "",
        extension: "",
        kind: kind || "generic_upload",
        purpose: purpose || getDefaultUploadPurpose(kind),
        field_key: fieldKey || "",
        fieldKey: fieldKey || "",
        valid: true,
        errors: [],
        backend_stored: false,
        local_only: true
      };
    }
  }

  function isFileValue(value) {
    try {
      return typeof File !== "undefined" && value instanceof File;
    } catch (error) {
      return false;
    }
  }

  function qsaFileList(fileList) {
    try {
      return Array.prototype.slice.call(fileList || []);
    } catch (error) {
      return [];
    }
  }

  function inferUploadKindFromFieldName(fieldName) {
    try {
      var name = String(fieldName || "");

      if (name === "geometry_model_uploads_json" || name === "geometry_model_files") {
        return "geometry_model";
      }

      if (name === "technical_document_uploads_json" || name === "technical_document_files" || name === "manufacturer_document_uploads_json") {
        return "technical_documents";
      }

      if (name === "variant_document_uploads_json" || name.indexOf("variant_document_uploads[") === 0 || name.indexOf("variant_document_files") === 0) {
        return "variant_documents";
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function inferFieldKeyFromName(fieldName) {
    try {
      var match = String(fieldName || "").match(/\[([^\]]+)\]/);

      return match && match[1] ? match[1] : "";
    } catch (error) {
      return "";
    }
  }

  function getDefaultUploadPurpose(kind) {
    try {
      if (kind === "geometry_model") {
        return "geometry_model";
      }

      if (kind === "technical_documents") {
        return "manufacturer_documents";
      }

      if (kind === "variant_documents") {
        return "variant_document_list";
      }

      return kind || "upload";
    } catch (error) {
      return "upload";
    }
  }

  function dedupeUploadFiles(files) {
    try {
      var seen = {};
      var result = [];

      (Array.isArray(files) ? files : []).forEach(function (file) {
        try {
          var key = [
            file.kind || "",
            file.field_key || file.fieldKey || "",
            file.name || "",
            file.size || "",
            file.last_modified || file.lastModified || ""
          ].join("::");

          if (!seen[key]) {
            seen[key] = true;
            result.push(file);
          }
        } catch (fileError) {
          result.push(file);
        }
      });

      return result;
    } catch (error) {
      return Array.isArray(files) ? files : [];
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

      return (value / (1024 * 1024)).toFixed(1).replace(".0", "") + " MB";
    } catch (error) {
      return "";
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
        core = window[CORE_NAME] || buildFallbackCore();
      }

      if (!core) {
        throw new Error("VectoplanCreateCore is not available.");
      }

      if (!selectors) {
        selectors = Object.assign({}, DEFAULT_SELECTORS, core.selectors || {});
      }

      return core;
    } catch (error) {
      throw error;
    }
  }

  function selectorFor(key) {
    try {
      if (!selectors) {
        selectors = Object.assign({}, DEFAULT_SELECTORS, core && core.selectors ? core.selectors : {});
      }

      return selectors[key] || DEFAULT_SELECTORS[key] || "";
    } catch (error) {
      return DEFAULT_SELECTORS[key] || "";
    }
  }

  function qs(selector, root) {
    try {
      if (!selector) {
        return null;
      }

      if (core && typeof core.qs === "function") {
        return core.qs(selector, root || document);
      }

      return (root || document).querySelector(selector);
    } catch (error) {
      return null;
    }
  }

  function qsa(selector, root) {
    try {
      if (!selector) {
        return [];
      }

      if (core && typeof core.qsa === "function") {
        return core.qsa(selector, root || document);
      }

      return Array.prototype.slice.call((root || document).querySelectorAll(selector));
    } catch (error) {
      return [];
    }
  }

  function ensureHiddenField(form, name, defaultValue) {
    try {
      if (core && typeof core.ensureHiddenField === "function") {
        return core.ensureHiddenField(form, name, defaultValue);
      }

      var field = form.elements ? form.elements[name] : null;

      if (!field || field.nodeType !== 1) {
        field = qs("[name='" + cssEscape(name) + "']", form);
      }

      if (!field) {
        field = document.createElement("input");
        field.type = "hidden";
        field.name = name;
        field.value = defaultValue || "";
        field.setAttribute("data-vp-created-by", GLOBAL_NAME);
        form.appendChild(field);
      }

      if (field.value === "" && defaultValue !== undefined && defaultValue !== null) {
        field.value = String(defaultValue);
      }

      return field;
    } catch (error) {
      safeWarn("Ensure hidden field failed: " + name, error);
      return null;
    }
  }

  function getFieldValue(form, name) {
    try {
      if (core && typeof core.getFieldValue === "function") {
        return core.getFieldValue(form, name);
      }

      var safeForm = resolveForm(form);

      if (!safeForm || !name) {
        return "";
      }

      var field = safeForm.elements ? safeForm.elements[name] : null;

      if (!field || field.nodeType !== 1) {
        field = qs("[name='" + cssEscape(name) + "']", safeForm);
      }

      if (!field || typeof field.value === "undefined") {
        return "";
      }

      return String(field.value || "");
    } catch (error) {
      return "";
    }
  }

  function getNested(object, path, fallbackValue) {
    try {
      if (core && typeof core.getNested === "function") {
        return core.getNested(object, path, fallbackValue);
      }

      var cursor = object;

      for (var index = 0; index < path.length; index += 1) {
        if (!cursor || typeof cursor !== "object" || !(path[index] in cursor)) {
          return fallbackValue;
        }

        cursor = cursor[path[index]];
      }

      return cursor === undefined || cursor === null ? fallbackValue : cursor;
    } catch (error) {
      return fallbackValue;
    }
  }

  function stringifyJson(value) {
    try {
      if (core && typeof core.stringifyJson === "function") {
        return core.stringifyJson(value);
      }

      return JSON.stringify(value === undefined ? null : value);
    } catch (error) {
      return "null";
    }
  }

  function safeJsonParse(value, fallbackValue) {
    try {
      if (core && typeof core.safeJsonParse === "function") {
        return core.safeJsonParse(value, fallbackValue);
      }

      if (value === null || typeof value === "undefined" || String(value).trim() === "") {
        return fallbackValue;
      }

      return JSON.parse(value);
    } catch (error) {
      return fallbackValue;
    }
  }

  function clone(value) {
    try {
      if (core && typeof core.clone === "function") {
        return core.clone(value);
      }

      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      return value;
    }
  }

  function cloneObject(value) {
    try {
      if (core && typeof core.cloneObject === "function") {
        return core.cloneObject(value);
      }

      if (!value || typeof value !== "object" || Array.isArray(value)) {
        return {};
      }

      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      return {};
    }
  }

  function normalizeToken(value, fallbackValue) {
    try {
      if (core && typeof core.normalizeToken === "function") {
        return core.normalizeToken(value, fallbackValue);
      }

      var text = String(value || "")
        .trim()
        .toLowerCase()
        .replace(/ä/g, "ae")
        .replace(/ö/g, "oe")
        .replace(/ü/g, "ue")
        .replace(/ß/g, "ss")
        .replace(/[-\s]+/g, "_")
        .replace(/[^a-z0-9_./]/g, "")
        .replace(/_{2,}/g, "_")
        .replace(/^_+|_+$/g, "");

      return text || fallbackValue || "";
    } catch (error) {
      return fallbackValue || "";
    }
  }

  function slugify(value) {
    try {
      if (core && typeof core.slugify === "function") {
        return core.slugify(value);
      }

      return normalizeToken(value, "");
    } catch (error) {
      return "";
    }
  }

  function toBoolean(value, fallbackValue) {
    try {
      if (core && typeof core.toBoolean === "function") {
        return core.toBoolean(value, fallbackValue);
      }

      if (value === true || value === false) {
        return value;
      }

      var text = String(value || "").trim().toLowerCase();

      if (["true", "1", "yes", "ja", "on", "active", "enabled", "default", "selected"].indexOf(text) >= 0) {
        return true;
      }

      if (["false", "0", "no", "nein", "off", "inactive", "disabled"].indexOf(text) >= 0) {
        return false;
      }

      return !!fallbackValue;
    } catch (error) {
      return !!fallbackValue;
    }
  }

  function uniqueArray(values) {
    try {
      if (core && typeof core.uniqueArray === "function") {
        return core.uniqueArray(values);
      }

      var seen = {};
      var result = [];

      (Array.isArray(values) ? values : []).forEach(function (item) {
        var key = String(item);

        if (!seen[key]) {
          seen[key] = true;
          result.push(item);
        }
      });

      return result;
    } catch (error) {
      return Array.isArray(values) ? values : [];
    }
  }

  function cssEscape(value) {
    try {
      if (core && typeof core.cssEscape === "function") {
        return core.cssEscape(value);
      }

      if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(String(value || ""));
      }

      return String(value || "").replace(/["\\]/g, "\\$&");
    } catch (error) {
      return String(value || "");
    }
  }

  function safeSetAttribute(node, name, value) {
    try {
      if (!node || !name) {
        return false;
      }

      if (core && typeof core.safeSetAttribute === "function") {
        core.safeSetAttribute(node, name, value);
        return true;
      }

      node.setAttribute(name, value);
      return true;
    } catch (error) {
      return false;
    }
  }

  function safeDispatch(eventName, detail) {
    try {
      if (core && typeof core.dispatch === "function") {
        core.dispatch(eventName, detail || {});
        return true;
      }

      document.dispatchEvent(new CustomEvent(eventName, {
        bubbles: true,
        cancelable: false,
        detail: detail || {}
      }));

      return true;
    } catch (error) {
      fallbackWarn("Dispatch failed: " + eventName, error);
      return false;
    }
  }

  function bindOnce(key, callback) {
    try {
      if (core && typeof core.bindOnce === "function") {
        core.bindOnce(key, callback);
        return;
      }

      var attr = "data-vp-" + String(key || "bind-once").replace(/[^a-z0-9_-]/gi, "-");

      if (document.documentElement.getAttribute(attr) === "true") {
        return;
      }

      document.documentElement.setAttribute(attr, "true");

      if (typeof callback === "function") {
        callback();
      }
    } catch (error) {
      safeWarn("bindOnce failed: " + key, error);
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
          window.console.warn("[VPLIB Create Payload] " + message, error);
        } else {
          window.console.warn("[VPLIB Create Payload] " + message);
        }
      }
    } catch (consoleError) {
      /* no-op */
    }
  }

  function buildFallbackCore() {
    try {
      return {
        selectors: DEFAULT_SELECTORS,
        state: {
          uiState: {
            defaults: {}
          }
        },
        qs: function (selector, root) {
          return (root || document).querySelector(selector);
        },
        qsa: function (selector, root) {
          return Array.prototype.slice.call((root || document).querySelectorAll(selector));
        },
        cssEscape: cssEscape,
        clone: clone,
        cloneObject: cloneObject,
        stringifyJson: stringifyJson,
        safeJsonParse: safeJsonParse,
        getFieldValue: getFieldValue,
        normalizeToken: normalizeToken,
        slugify: slugify,
        toBoolean: toBoolean,
        uniqueArray: uniqueArray,
        getNested: getNested,
        ensureHiddenField: ensureHiddenField,
        safeSetAttribute: safeSetAttribute,
        dispatch: safeDispatch,
        registerModule: function () {},
        bindOnce: bindOnce,
        refreshContext: function () {},
        warn: fallbackWarn,
        error: fallbackWarn
      };
    } catch (error) {
      return null;
    }
  }

  var api = {
    version: PAYLOAD_VERSION,

    initialize: initialize,
    collectPayload: collectPayload,
    collectFormPayload: collectPayload,
    collectFormPayloadRaw: collectFormPayloadRaw,

    syncVariantRuntimeToForm: syncVariantRuntimeToForm,
    ensureDefinitionVariantHiddenFields: ensureDefinitionVariantHiddenFields,

    syncUploadsRuntimeToForm: syncUploadsRuntimeToForm,
    ensureUploadHiddenFields: ensureUploadHiddenFields,
    getUploadMetadata: getUploadMetadata,
    augmentPayloadWithUploads: augmentPayloadWithUploads,

    getDefinitionVariants: getDefinitionVariants,
    getDefinitionVariantsJson: getDefinitionVariantsJson,
    readDefinitionVariantsJson: readDefinitionVariantsJson,

    normalizeDefinitionVariant: normalizeDefinitionVariant,
    normalizeDefinitionVariants: normalizeDefinitionVariants,
    buildFallbackDefinitionVariantsFromLegacyRows: buildFallbackDefinitionVariantsFromLegacyRows,

    augmentPayloadWithDefinitionVariants: augmentPayloadWithDefinitionVariants,
    normalizePayloadBeforeSend: normalizePayloadBeforeSend,
    syncProfileIdsIntoPayload: syncProfileIdsIntoPayload,
    syncProfileIdsIntoForm: syncProfileIdsIntoForm,
    buildPayloadContext: buildPayloadContext,

    getState: getState
  };

  window[GLOBAL_NAME] = api;

  try {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        boot(0);
      }, { once: true });
    } else {
      boot(0);
    }
  } catch (error) {
    fallbackWarn("Payload runtime scheduling failed.", error);
  }
})();