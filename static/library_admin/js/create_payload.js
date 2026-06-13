/* services/vectoplan-library/static/library_admin/js/create_payload.js */

/* -----------------------------------------------------------------------------
  VECTOPLAN Library · VPLIB Create Payload Runtime

  Zweck:
  - Eigenständige Payload-Schicht für /create.
  - Entlastet die bisher zu große create.js.
  - Sammelt Formulardaten robust ein.
  - Synchronisiert die neue definition-managed Variant Runtime in das Formular.
  - Hält Legacy-Variantenzeilen weiterhin als Fallback lesbar.
  - Stellt definition_variants_json als zentrale Backend-Brücke sicher.
  - Normalisiert Defaultwerte, Taxonomie, Objektart, Geometrie und Profile.
  - Erzeugt keine VPLIB-Dateien im Browser.

  Abhängigkeit:
  - Muss nach create_core.js geladen werden.
  - Sollte vor create_actions.js geladen werden.
  - Nutzt optional:
    - window.VectoplanCreateVariantState
    - window.VectoplanCreateVariantProfiles
    - window.VectoplanCreateDefinitionsRuntime

  Öffentliche API:
  - window.VectoplanCreatePayload.initialize()
  - window.VectoplanCreatePayload.collectPayload(form, options)
  - window.VectoplanCreatePayload.syncVariantRuntimeToForm(form)
  - window.VectoplanCreatePayload.getDefinitionVariants(form)
  - window.VectoplanCreatePayload.getDefinitionVariantsJson(form)
  - window.VectoplanCreatePayload.normalizeDefinitionVariant(variant, index, context)
  - window.VectoplanCreatePayload.ensureDefinitionVariantHiddenFields(form)
  - window.VectoplanCreatePayload.getState()
----------------------------------------------------------------------------- */

(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreatePayload";
  var MODULE_NAME = "payload";
  var PAYLOAD_VERSION = "0.4.0";
  var CORE_NAME = "VectoplanCreateCore";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 80;

  var FIELD_NAMES = {
    definitionVariantsJson: "definition_variants_json",
    definitionVariants: "definition_variants",
    defaultVariantId: "default_variant_id",
    familyProfileId: "family_profile_id",
    variantProfileId: "variant_profile_id",
    objectKind: "object_kind",
    domain: "domain",
    category: "category",
    subcategory: "subcategory"
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
    "displayName"
  ];

  var VARIANT_DESCRIPTION_KEYS = [
    "description",
    "variant_description",
    "variantDescription",
    "notes"
  ];

  var SYSTEM_VARIANT_VALUE_KEYS = {
    "variant.variant_id": true,
    "variant.variantId": true,
    "variant.id": true,
    "variant_id": true,
    "variantId": true,
    "id": true
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
    lastError: null,
    collectCount: 0,
    syncCount: 0,
    fallbackVariantCount: 0,
    runtimeVariantCount: 0
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

        fallbackWarn("Core runtime missing; payload runtime not initialized.");
        return;
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

      core = coreRuntime || window[CORE_NAME];

      if (!core) {
        fallbackWarn("Cannot initialize payload runtime without create_core.js.");
        return api;
      }

      selectors = core.selectors || {};

      if (typeof core.refreshContext === "function") {
        core.refreshContext();
      }

      bindPayloadEvents();
      ensureDefinitionVariantHiddenFields();

      initialized = true;
      localState.initialized = true;

      if (typeof core.registerModule === "function") {
        core.registerModule(MODULE_NAME, api);
      }

      core.safeSetAttribute(document.documentElement, "data-vp-create-payload-ready", "true");
      core.safeSetAttribute(document.documentElement, "data-vp-create-payload-version", PAYLOAD_VERSION);

      core.dispatch("vectoplan:create:payload-ready", getState());

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
      if (!core || typeof core.bindOnce !== "function") {
        return;
      }

      core.bindOnce("create-payload-form-change-sync", function () {
        document.addEventListener("change", function (event) {
          try {
            var target = event && event.target ? event.target : null;

            if (!target) {
              return;
            }

            if (target.matches && (
              target.matches(selectors.objectKindSelect) ||
              target.matches(selectors.domainSelect) ||
              target.matches(selectors.categorySelect) ||
              target.matches(selectors.subcategorySelect)
            )) {
              ensureDefinitionVariantHiddenFields();
              syncProfileIdsIntoForm();
            }
          } catch (handlerError) {
            safeWarn("Payload change sync failed.", handlerError);
          }
        }, true);
      });

      core.bindOnce("create-payload-variant-state-sync", function () {
        document.addEventListener("vectoplan:create:variant-state-changed", function () {
          try {
            syncVariantRuntimeToForm();
          } catch (handlerError) {
            safeWarn("Variant state payload sync failed.", handlerError);
          }
        });

        document.addEventListener("vectoplan:create:variant-state-synced", function () {
          try {
            syncVariantRuntimeToForm();
          } catch (handlerError) {
            safeWarn("Variant state synced payload sync failed.", handlerError);
          }
        });

        document.addEventListener("vectoplan:create:variant-updated", function () {
          try {
            syncVariantRuntimeToForm();
          } catch (handlerError) {
            safeWarn("Variant updated payload sync failed.", handlerError);
          }
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

      var payload = collectFormPayloadRaw(safeForm);

      ensureUncheckedDefaults(safeForm, payload);
      augmentPayloadWithDefinitionVariants(payload, safeForm);
      syncProfileIdsIntoPayload(payload, safeForm);
      normalizePayloadBeforeSend(payload, safeForm);

      localState.lastPayload = core.clone(payload);
      localState.lastPayloadSummary = summarizePayload(payload);

      core.dispatch("vectoplan:create:payload-collected", {
        payload: core.clone(payload),
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
          if (value instanceof File) {
            if (value.name) {
              assignPayloadValue(payload, key, {
                name: value.name,
                size: value.size,
                type: value.type || "",
                last_modified: value.lastModified || null
              });
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

      var variantRows = core.qsa(selectors.variantRow, safeForm);

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
      var defaults = core.getNested(core.state.uiState, ["defaults"], {});
      var objectKind = String(
        payload.object_kind ||
        defaults.object_kind ||
        defaults.objectKind ||
        core.getFieldValue(safeForm, "object_kind") ||
        "cell_block"
      ).trim();

      if (!payload.domain) {
        payload.domain = core.getFieldValue(safeForm, "domain") || defaults.domain || "hochbau";
      }

      if (!payload.category) {
        payload.category = core.getFieldValue(safeForm, "category") || defaults.category || "bloecke";
      }

      if (!payload.subcategory) {
        payload.subcategory = core.getFieldValue(safeForm, "subcategory") || defaults.subcategory || "basis";
      }

      if (!payload.object_kind) {
        payload.object_kind = objectKind;
      }

      if (!payload.primitive_shape) {
        payload.primitive_shape = core.getFieldValue(safeForm, "primitive_shape") || defaults.primitive_shape || defaults.primitiveShape || "block";
      }

      if (!payload.geometry_unit) {
        payload.geometry_unit = core.getFieldValue(safeForm, "geometry_unit") || defaults.geometry_unit || defaults.geometryUnit || "m";
      }

      if (!payload.geometry_width) {
        payload.geometry_width = core.getFieldValue(safeForm, "geometry_width") || defaults.geometry_width || defaults.geometryWidth || "1.00";
      }

      if (!payload.geometry_height) {
        payload.geometry_height = core.getFieldValue(safeForm, "geometry_height") || defaults.geometry_height || defaults.geometryHeight || "1.00";
      }

      if (!payload.geometry_depth) {
        payload.geometry_depth = core.getFieldValue(safeForm, "geometry_depth") || defaults.geometry_depth || defaults.geometryDepth || "1.00";
      }

      if (objectKind === "cell_block" || objectKind === "adaptive_system") {
        payload.editor_cells_x = "1";
        payload.editor_cells_y = "1";
        payload.editor_cells_z = "1";
      } else {
        if (!payload.editor_cells_x) {
          payload.editor_cells_x = core.getFieldValue(safeForm, "editor_cells_x") || defaults.editor_cells_x || defaults.editorCellsX || "1";
        }

        if (!payload.editor_cells_y) {
          payload.editor_cells_y = core.getFieldValue(safeForm, "editor_cells_y") || defaults.editor_cells_y || defaults.editorCellsY || "1";
        }

        if (!payload.editor_cells_z) {
          payload.editor_cells_z = core.getFieldValue(safeForm, "editor_cells_z") || defaults.editor_cells_z || defaults.editorCellsZ || "1";
        }
      }

      payload.family_name = String(payload.family_name || "").trim();
      payload.family_description = String(payload.family_description || "").trim();
      payload.material_class = String(payload.material_class || "").trim();

      payload.domain = core.normalizeToken(payload.domain, "hochbau");
      payload.category = core.normalizeToken(payload.category, "bloecke");
      payload.subcategory = core.normalizeToken(payload.subcategory, "basis");
      payload.object_kind = core.normalizeToken(payload.object_kind, "cell_block");

      payload.geometry_width = String(payload.geometry_width || "1.00").trim();
      payload.geometry_height = String(payload.geometry_height || "1.00").trim();
      payload.geometry_depth = String(payload.geometry_depth || "1.00").trim();

      ensureDefinitionVariantAliases(payload);

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
        variants = buildFallbackDefinitionVariantsFromLegacyRows(safeForm);
      }

      variants = normalizeDefinitionVariants(variants, buildPayloadContext(safeForm));

      var defaultVariantId = resolveDefaultVariantId(variants, safeForm);
      var variantsJson = core.stringifyJson(variants);

      if (hiddenFields.definitionVariantsJson) {
        hiddenFields.definitionVariantsJson.value = variantsJson;
      }

      if (hiddenFields.defaultVariantId) {
        hiddenFields.defaultVariantId.value = defaultVariantId;
      }

      syncProfileIdsIntoForm(safeForm);

      localState.syncCount += 1;
      localState.lastSync = {
        source: source,
        variantCount: variants.length,
        defaultVariantId: defaultVariantId,
        timestamp: timestamp()
      };

      core.dispatch("vectoplan:create:payload-variants-synced", {
        source: source,
        variantCount: variants.length,
        defaultVariantId: defaultVariantId,
        variants: core.clone(variants)
      });

      return true;
    } catch (error) {
      localState.lastError = normalizeError(error);
      safeError("Variant runtime to form sync failed.", error);
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
        definitionVariantsJson: core.ensureHiddenField(safeForm, FIELD_NAMES.definitionVariantsJson, "[]"),
        defaultVariantId: core.ensureHiddenField(safeForm, FIELD_NAMES.defaultVariantId, "default"),
        familyProfileId: core.ensureHiddenField(safeForm, FIELD_NAMES.familyProfileId, ""),
        variantProfileId: core.ensureHiddenField(safeForm, FIELD_NAMES.variantProfileId, "")
      };
    } catch (error) {
      safeWarn("Ensure definition variant hidden fields failed.", error);
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
        var parsed = core.safeJsonParse(variantState.getPayloadJson(), null);

        if (Array.isArray(parsed)) {
          variants = parsed;
        } else if (parsed && Array.isArray(parsed.variants)) {
          variants = parsed.variants;
        }
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
      var rows = safeForm ? core.qsa(selectors.variantRow, safeForm) : [];
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
        getRowFieldValue(row, "variant_id") ||
        getRowFieldValue(row, "slug") ||
        (index === 0 ? "default" : "variant_" + (index + 1));

      var label = getRowFieldValue(row, "variant_name") ||
        getRowFieldValue(row, "label") ||
        getRowFieldValue(row, "name") ||
        (index === 0 ? "Standard" : "Variante " + (index + 1));

      var description = getRowFieldValue(row, "variant_description") ||
        getRowFieldValue(row, "description") ||
        "";

      var isDefault = index === 0 ||
        core.toBoolean(getRowFieldValue(row, "variant_is_default"), false) ||
        row.getAttribute("data-vp-default") === "true";

      return {
        variant_id: normalizeVariantId(variantId, index),
        label: String(label || "").trim() || (index === 0 ? "Standard" : "Variante " + (index + 1)),
        description: String(description || "").trim(),
        is_default: !!isDefault,
        family_profile_id: context.family_profile_id || "",
        variant_profile_id: context.variant_profile_id || "",
        object_kind: context.object_kind || "cell_block",
        definition_values: {},
        additional_field_keys: [],
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
        "[data-create-field='" + core.cssEscape(fieldName) + "']",
        "[name$='[" + core.cssEscape(fieldName) + "]']",
        "[name='" + core.cssEscape(fieldName) + "']"
      ];

      for (var index = 0; index < selectorsToTry.length; index += 1) {
        var field = core.qs(selectorsToTry[index], row);

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
        label: "Standard",
        description: "",
        is_default: true,
        family_profile_id: safeContext.family_profile_id || "",
        variant_profile_id: safeContext.variant_profile_id || "",
        object_kind: safeContext.object_kind || "cell_block",
        definition_values: {},
        additional_field_keys: [],
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
      return core.stringifyJson(variants);
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
        field = core.qs("[name='" + core.cssEscape(FIELD_NAMES.definitionVariantsJson) + "']", safeForm);
      }

      var raw = field && typeof field.value !== "undefined" ? field.value : "";
      var parsed = core.safeJsonParse(raw, []);

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
      var safeVariant = variant && typeof variant === "object" ? core.cloneObject(variant) : {};
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

      var isDefault = core.toBoolean(
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
        object_kind: core.normalizeToken(objectKind, "cell_block"),
        objectKind: core.normalizeToken(objectKind, "cell_block"),
        definition_values: values,
        definitionValues: values,
        additional_field_keys: additionalFieldKeys,
        additionalFieldKeys: additionalFieldKeys
      };

      if (safeVariant.summary) {
        normalized.summary = safeVariant.summary;
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
        values = core.safeJsonParse(candidate, {});
      } else if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
        values = core.cloneObject(candidate);
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
        var parsed = core.safeJsonParse(keys, null);

        if (Array.isArray(parsed)) {
          keys = parsed;
        } else {
          keys = keys.split(",");
        }
      }

      if (!Array.isArray(keys)) {
        keys = [];
      }

      var result = core.uniqueArray(keys.map(function (key) {
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

      return core.uniqueArray(result);
    } catch (error) {
      safeWarn("Extract additional field keys failed.", error);
      return [];
    }
  }

  function isLikelyAdditionalValueKey(key) {
    try {
      var text = String(key || "").trim();

      if (!text || SYSTEM_VARIANT_VALUE_KEYS[text]) {
        return false;
      }

      if (text.indexOf(".") !== -1) {
        return true;
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function ensureSingleDefaultVariant(variants) {
    try {
      var list = Array.isArray(variants) ? variants : [];
      var defaultIndex = -1;

      list.forEach(function (variant, index) {
        if (core.toBoolean(variant.is_default, false) || core.toBoolean(variant.isDefault, false) || variant.variant_id === "default") {
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
        if (core.toBoolean(list[index].is_default, false) || core.toBoolean(list[index].isDefault, false)) {
          return list[index].variant_id || list[index].variantId || "default";
        }
      }

      var safeForm = resolveForm(form);
      var fieldValue = core.getFieldValue(safeForm, FIELD_NAMES.defaultVariantId);

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
      var variantsJson = core.stringifyJson(variants);

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

  function ensureDefinitionVariantAliases(payload) {
    try {
      if (!payload || typeof payload !== "object") {
        return payload;
      }

      if (payload.definition_variants_json && !payload.definitionVariantsJson) {
        payload.definitionVariantsJson = payload.definition_variants_json;
      }

      if (payload.definitionVariantsJson && !payload.definition_variants_json) {
        payload.definition_variants_json = payload.definitionVariantsJson;
      }

      if (payload.definition_variants && !payload.definitionVariants) {
        payload.definitionVariants = payload.definition_variants;
      }

      if (payload.definitionVariants && !payload.definition_variants) {
        payload.definition_variants = payload.definitionVariants;
      }

      if (payload.default_variant_id && !payload.defaultVariantId) {
        payload.defaultVariantId = payload.default_variant_id;
      }

      if (payload.defaultVariantId && !payload.default_variant_id) {
        payload.default_variant_id = payload.defaultVariantId;
      }

      if (payload.family_profile_id && !payload.familyProfileId) {
        payload.familyProfileId = payload.family_profile_id;
      }

      if (payload.familyProfileId && !payload.family_profile_id) {
        payload.family_profile_id = payload.familyProfileId;
      }

      if (payload.variant_profile_id && !payload.variantProfileId) {
        payload.variantProfileId = payload.variant_profile_id;
      }

      if (payload.variantProfileId && !payload.variant_profile_id) {
        payload.variant_profile_id = payload.variantProfileId;
      }

      return payload;
    } catch (error) {
      safeWarn("Ensure definition variant aliases failed.", error);
      return payload;
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

  function syncProfileIdsIntoForm(form) {
    try {
      var safeForm = resolveForm(form);

      if (!safeForm) {
        return false;
      }

      var fields = ensureDefinitionVariantHiddenFields(safeForm);
      var context = buildPayloadContext(safeForm);

      if (fields.familyProfileId) {
        fields.familyProfileId.value = context.family_profile_id || "";
      }

      if (fields.variantProfileId) {
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
        domain: core.getFieldValue(safeForm, FIELD_NAMES.domain) ||
          profileContext.domain ||
          core.getNested(core.state.uiState, ["defaults", "domain"], "hochbau"),

        category: core.getFieldValue(safeForm, FIELD_NAMES.category) ||
          profileContext.category ||
          core.getNested(core.state.uiState, ["defaults", "category"], "bloecke"),

        subcategory: core.getFieldValue(safeForm, FIELD_NAMES.subcategory) ||
          profileContext.subcategory ||
          core.getNested(core.state.uiState, ["defaults", "subcategory"], "basis"),

        object_kind: core.getFieldValue(safeForm, FIELD_NAMES.objectKind) ||
          profileContext.object_kind ||
          profileContext.objectKind ||
          core.getNested(core.state.uiState, ["defaults", "object_kind"], "cell_block"),

        family_profile_id: core.getFieldValue(safeForm, FIELD_NAMES.familyProfileId) ||
          profilePayload.family_profile_id ||
          profilePayload.familyProfileId ||
          profileContext.family_profile_id ||
          profileContext.familyProfileId ||
          "",

        variant_profile_id: core.getFieldValue(safeForm, FIELD_NAMES.variantProfileId) ||
          profilePayload.variant_profile_id ||
          profilePayload.variantProfileId ||
          profilePayload.profile_id ||
          profilePayload.id ||
          profileContext.variant_profile_id ||
          profileContext.variantProfileId ||
          ""
      };

      context.domain = core.normalizeToken(context.domain, "hochbau");
      context.category = core.normalizeToken(context.category, "bloecke");
      context.subcategory = core.normalizeToken(context.subcategory, "basis");
      context.object_kind = core.normalizeToken(context.object_kind, "cell_block");

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
      var text = core.slugify(value || fallback);

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

        if (Object.prototype.hasOwnProperty.call(object, key) && object[key] !== null && typeof object[key] !== "undefined" && String(object[key]).trim() !== "") {
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
        variants = core.safeJsonParse(payload.definition_variants_json, []);
      }

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

      return core && typeof core.qs === "function" ? core.qs(selectors.form) : document.querySelector("[data-vp-create-form], [data-create-form='true'], #vp-create-form");
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
        fallbackVariantCount: localState.fallbackVariantCount,
        runtimeVariantCount: localState.runtimeVariantCount,
        lastSync: localState.lastSync,
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
        core = window[CORE_NAME];
      }

      if (!core) {
        throw new Error("VectoplanCreateCore is not available.");
      }

      if (!selectors) {
        selectors = core.selectors || {};
      }

      return core;
    } catch (error) {
      throw error;
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

  var api = {
    version: PAYLOAD_VERSION,

    initialize: initialize,
    collectPayload: collectPayload,
    collectFormPayload: collectPayload,

    syncVariantRuntimeToForm: syncVariantRuntimeToForm,
    ensureDefinitionVariantHiddenFields: ensureDefinitionVariantHiddenFields,

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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      boot(0);
    }, { once: true });
  } else {
    boot(0);
  }
})();