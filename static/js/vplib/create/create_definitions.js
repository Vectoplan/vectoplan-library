// services/vectoplan-library/static/js/vplib/create/create_definitions.js
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateDefinitionsRuntime";
  var COMPONENT_NAME = "VECTOPLAN Create Definitions Runtime Bridge";
  var RUNTIME_VERSION = "0.7.0";
  var READY_ATTR = "data-vp-create-definitions-runtime-ready";
  var CORE_NAME = "VectoplanCreateCore";
  var DEFAULT_DEFINITIONS_PREFIX = "/api/v1/vplib/definitions";

  var SELECTORS = {
    form: "[data-vp-create-form], [data-create-form='true'], #vp-create-form",

    domainSelect: "[data-create-taxonomy-select='domain'], [name='domain'], [data-vp-taxonomy-domain]",
    categorySelect: "[data-create-taxonomy-select='category'], [name='category'], [data-vp-taxonomy-category]",
    subcategorySelect: "[data-create-taxonomy-select='subcategory'], [name='subcategory'], [data-vp-taxonomy-subcategory]",
    objectKindSelect: "[data-create-object-kind='true'], [name='object_kind'], [name='object_class'], [data-vp-object-kind-field='true']",

    familyProfileField: "[name='family_profile_id'], [data-create-field='family_profile_id'], [data-vp-family-profile-id-field='true'], [data-vp-variant-drawer-family-profile-id-field='true']",
    variantProfileField: "[name='variant_profile_id'], [data-create-field='variant_profile_id'], [data-vp-variant-profile-id-field='true'], [data-vp-variant-drawer-profile-id-field='true']",

    definitionVariantsJson: "[name='definition_variants_json'], [data-vp-definition-variants-json='true']",
    defaultVariantId: "[name='default_variant_id'], [data-vp-definition-variants-default-id='true']",

    workspace: "[data-vp-variant-workspace-root='true'], [data-vp-variant-workspace='true']",
    table: "[data-vp-variant-table-root='true'], [data-vp-variant-table='true'], [data-create-variant-table='true']",
    row: "[data-vp-variant-row='true'], [data-create-variant-row='true']",
    drawer: "[data-vp-variant-drawer-root='true'], [data-vp-variant-drawer='true']",

    addVariant: "[data-vp-add-variant='true'], [data-create-add-variant='true']",
    editVariant: "[data-vp-edit-definition-variant='true']",

    status: "[data-vp-action-status], [data-create-action-status='true']"
  };

  var state = {
    initialized: false,
    ready: false,
    bridgeReady: false,

    suppressProfileFieldChange: false,
    pendingResolve: false,

    context: {},
    generatorContext: {},
    definitions: {},
    definitionsApi: null,
    collections: createEmptyCollections(),
    maps: createEmptyMaps(),
    routes: {},
    endpoints: {},

    currentProfilePayload: null,
    variants: [],

    lastError: null,
    lastResolveAt: 0,
    lastSyncAt: 0,
    lastEventAt: 0,
    lastAggregateJson: "",
    lastProfileSignature: "",

    syncInProgress: false,
    hydrateInProgress: false,
    suppressVariantEvent: false,
    syncDepth: 0,
    suppressedSyncCount: 0,

    modules: {}
  };

  function initializeRuntime() {
    try {
      if (state.initialized) {
        exposePublicApi();
        return window[GLOBAL_NAME];
      }

      state.context = resolveContext();
      state.generatorContext = resolveGeneratorContext();
      state.definitionsApi = resolveDefinitionsApi();
      state.definitions = state.definitionsApi || resolveDefinitions();
      state.collections = normalizeCollections(state.definitions);
      state.maps = buildMaps(state.collections);
      state.routes = resolveDefinitionRoutes(state.context, state.definitions);
      state.endpoints = resolveDefinitionEndpoints(state.context, state.definitions, state.routes);
      state.ready = isDefinitionsReady(state.definitions, state.collections);
      state.modules = detectModules();

      hydrateVariants({
        source: "initialize",
        emitEvents: false
      });

      exposePublicApi();
      bindGlobalEvents();
      bindPassiveLegacyFallbacks();

      state.initialized = true;
      state.bridgeReady = true;

      safeSetAttribute(document.documentElement, READY_ATTR, state.ready ? "true" : "false");
      safeSetAttribute(document.documentElement, "data-vp-create-definitions-runtime-version", RUNTIME_VERSION);
      safeSetAttribute(document.documentElement, "data-vp-create-definitions-runtime-mode", "bridge");
      safeSetAttribute(document.documentElement, "data-vp-create-definitions-runtime-bridge-ready", "true");
      safeSetAttribute(document.documentElement, "data-vp-create-definitions-runtime-legacy-drawer-disabled", "true");

      dispatchDocument("vectoplan:create:definitions-runtime-ready", {
        component: COMPONENT_NAME,
        version: RUNTIME_VERSION,
        mode: "bridge",
        ready: state.ready,
        bridgeReady: state.bridgeReady,
        counts: collectionCounts(),
        modules: state.modules,
        __vp_bridge_event: true
      });

      dispatchDocument("vectoplan:create:definitions-runtime-bridge-ready", {
        component: COMPONENT_NAME,
        version: RUNTIME_VERSION,
        ready: state.ready,
        counts: collectionCounts(),
        modules: state.modules,
        __vp_bridge_event: true
      });

      redispatchDefinitionsState();

      return window[GLOBAL_NAME];
    } catch (error) {
      state.lastError = error;
      warn("Runtime initialization failed.", error);

      exposePublicApi();

      try {
        safeSetAttribute(document.documentElement, READY_ATTR, "false");
        safeSetAttribute(document.documentElement, "data-vp-create-definitions-runtime-error", errorMessage(error));
      } catch (attributeError) {
        /* no-op */
      }

      return window[GLOBAL_NAME];
    }
  }

  function detectModules() {
    try {
      return {
        core: !!window[CORE_NAME],
        utils: !!window.VectoplanCreateVariantUtils,
        state: !!window.VectoplanCreateVariantState,
        profiles: !!window.VectoplanCreateVariantProfiles,
        fieldRenderer: !!window.VectoplanCreateVariantFieldRenderer,
        summary: !!window.VectoplanCreateVariantSummary,
        validation: !!window.VectoplanCreateVariantValidation,
        drawer: !!window.VectoplanCreateVariantDrawer,
        table: !!window.VectoplanCreateVariantTable,
        context: !!window.VectoplanCreateContext,
        generatorContext: !!window.VectoplanGeneratorContext,
        definitions: !!window.VectoplanCreateDefinitions
      };
    } catch (error) {
      return {};
    }
  }

  function redispatchDefinitionsState() {
    try {
      window.setTimeout(function () {
        try {
          if (state.ready) {
            dispatchDocument("vectoplan:create:definitions-ready", buildDefinitionsReadyPayload());
          } else {
            dispatchDocument("vectoplan:create:definitions-unavailable", {
              component: COMPONENT_NAME,
              version: RUNTIME_VERSION,
              mode: "bridge",
              ok: !!(state.definitions && state.definitions.ok),
              ready: false,
              counts: collectionCounts(),
              error: {
                code: "definitions_not_ready",
                message: "Definitionsdaten sind nicht vollständig verfügbar."
              },
              __vp_bridge_event: true
            });
          }
        } catch (error) {
          warn("Definitions state redispatch failed.", error);
        }
      }, 0);
    } catch (error) {
      warn("Could not schedule definitions redispatch.", error);
    }
  }

  function buildDefinitionsReadyPayload() {
    return {
      component: COMPONENT_NAME,
      version: RUNTIME_VERSION,
      mode: "bridge",
      ok: true,
      ready: true,
      definitions: state.definitions,
      definitionsApi: state.definitionsApi || state.definitions,
      collections: state.collections,
      maps: state.maps,
      routes: state.routes,
      endpoints: state.endpoints,
      counts: collectionCounts(),
      __vp_bridge_event: true
    };
  }

  function resolveContext() {
    try {
      if (window.VectoplanCreateContext && typeof window.VectoplanCreateContext === "object") {
        return window.VectoplanCreateContext;
      }

      var core = window[CORE_NAME];
      if (core && core.state && core.state.context) {
        return core.state.context;
      }

      return {};
    } catch (error) {
      return {};
    }
  }

  function resolveGeneratorContext() {
    try {
      var context = resolveContext();

      return window.VectoplanGeneratorContext ||
        context.generatorContext ||
        context.generator_context ||
        {};
    } catch (error) {
      return {};
    }
  }

  function resolveDefinitionsApi() {
    try {
      var context = resolveContext();
      var generator = resolveGeneratorContext();
      var generatorData = generator.data || generator.payload || generator || {};

      if (context.definitionsApi && typeof context.definitionsApi === "object") {
        return context.definitionsApi;
      }

      if (context.definitions_api && typeof context.definitions_api === "object") {
        return context.definitions_api;
      }

      if (window.VectoplanCreateDefinitions && typeof window.VectoplanCreateDefinitions === "object") {
        return window.VectoplanCreateDefinitions;
      }

      if (generatorData.definitions && typeof generatorData.definitions === "object") {
        return generatorData.definitions;
      }

      return null;
    } catch (error) {
      return null;
    }
  }

  function resolveDefinitions() {
    try {
      var context = resolveContext();
      var generator = resolveGeneratorContext();
      var generatorData = generator.data || generator.payload || generator || {};

      if (window.VectoplanCreateDefinitions && typeof window.VectoplanCreateDefinitions === "object") {
        return window.VectoplanCreateDefinitions;
      }

      if (context.definitions && typeof context.definitions === "object") {
        return context.definitions;
      }

      if (generatorData.definitions && typeof generatorData.definitions === "object") {
        return generatorData.definitions;
      }

      return {};
    } catch (error) {
      return {};
    }
  }

  function resolveDefinitionRoutes(context, definitions) {
    try {
      var routes = {};
      var contextObject = context || {};
      var definitionsObject = definitions || {};
      var apiPrefix = resolveDefinitionsPrefix(contextObject);

      if (definitionsObject.routes && typeof definitionsObject.routes === "object") {
        routes = safeMerge(routes, definitionsObject.routes);
      }

      if (definitionsObject.endpoints && typeof definitionsObject.endpoints === "object") {
        routes = safeMerge(routes, definitionsObject.endpoints);
      }

      if (
        contextObject.context &&
        contextObject.context.definitions &&
        contextObject.context.definitions.routes
      ) {
        routes = safeMerge(routes, contextObject.context.definitions.routes);
      }

      if (
        contextObject.context &&
        contextObject.context.definitions &&
        contextObject.context.definitions.endpoints
      ) {
        routes = safeMerge(routes, contextObject.context.definitions.endpoints);
      }

      if (contextObject.routes && typeof contextObject.routes === "object") {
        routes.resolve_family_profile =
          routes.resolve_family_profile ||
          routes.resolveFamilyProfile ||
          contextObject.routes.definitions_resolve_family_profile ||
          contextObject.routes.definitionsResolveFamilyProfile ||
          "";

        routes.resolve_variant_profile =
          routes.resolve_variant_profile ||
          routes.resolveVariantProfile ||
          contextObject.routes.definitions_resolve_variant_profile ||
          contextObject.routes.definitionsResolveVariantProfile ||
          "";

        routes.variant_profile_base =
          routes.variant_profile_base ||
          routes.variantProfileBase ||
          contextObject.routes.definitions_variant_profile_base ||
          contextObject.routes.definitionsVariantProfileBase ||
          "";

        routes.empty_variant_values =
          routes.empty_variant_values ||
          routes.emptyVariantValues ||
          contextObject.routes.definitions_empty_variant_values ||
          contextObject.routes.definitionsEmptyVariantValues ||
          "";

        routes.empty_variant_values_base =
          routes.empty_variant_values_base ||
          routes.emptyValuesBase ||
          contextObject.routes.definitions_empty_variant_values_base ||
          contextObject.routes.definitionsEmptyVariantValuesBase ||
          "";

        routes.validate_variant =
          routes.validate_variant ||
          routes.validateVariant ||
          contextObject.routes.definitions_validate_variant ||
          contextObject.routes.definitionsValidateVariant ||
          "";
      }

      routes.options = routes.options || apiPrefix + "/options";
      routes.payload = routes.payload || apiPrefix + "/payload";
      routes.resolve_family_profile = routes.resolve_family_profile || routes.resolveFamilyProfile || apiPrefix + "/resolve-family-profile";
      routes.resolve_variant_profile = routes.resolve_variant_profile || routes.resolveVariantProfile || apiPrefix + "/resolve-variant-profile";
      routes.variant_profile_base = routes.variant_profile_base || routes.variantProfileBase || apiPrefix + "/variant-profiles/";
      routes.empty_variant_values = routes.empty_variant_values || routes.emptyVariantValues || apiPrefix + "/empty-variant-values";
      routes.empty_variant_values_base = routes.empty_variant_values_base || routes.emptyValuesBase || apiPrefix + "/empty-variant-values/";
      routes.validate_variant = routes.validate_variant || routes.validateVariant || apiPrefix + "/validate-variant";

      routes.resolveFamilyProfile = routes.resolve_family_profile;
      routes.resolveVariantProfile = routes.resolve_variant_profile;
      routes.variantProfileBase = routes.variant_profile_base;
      routes.emptyVariantValues = routes.empty_variant_values;
      routes.emptyValuesBase = routes.empty_variant_values_base;
      routes.validateVariant = routes.validate_variant;

      return routes;
    } catch (error) {
      return defaultDefinitionRoutes();
    }
  }

  function resolveDefinitionsPrefix(context) {
    try {
      var root = document.documentElement;
      var contextObject = context || {};

      return String(
        contextObject.definitions_api_prefix ||
        contextObject.definitionsApiPrefix ||
        root.getAttribute("data-vp-definitions-api-prefix") ||
        DEFAULT_DEFINITIONS_PREFIX
      ).replace(/\/+$/, "");
    } catch (error) {
      return DEFAULT_DEFINITIONS_PREFIX;
    }
  }

  function defaultDefinitionRoutes() {
    return {
      options: DEFAULT_DEFINITIONS_PREFIX + "/options",
      payload: DEFAULT_DEFINITIONS_PREFIX + "/payload",
      resolve_family_profile: DEFAULT_DEFINITIONS_PREFIX + "/resolve-family-profile",
      resolveFamilyProfile: DEFAULT_DEFINITIONS_PREFIX + "/resolve-family-profile",
      resolve_variant_profile: DEFAULT_DEFINITIONS_PREFIX + "/resolve-variant-profile",
      resolveVariantProfile: DEFAULT_DEFINITIONS_PREFIX + "/resolve-variant-profile",
      variant_profile_base: DEFAULT_DEFINITIONS_PREFIX + "/variant-profiles/",
      variantProfileBase: DEFAULT_DEFINITIONS_PREFIX + "/variant-profiles/",
      empty_variant_values: DEFAULT_DEFINITIONS_PREFIX + "/empty-variant-values",
      emptyVariantValues: DEFAULT_DEFINITIONS_PREFIX + "/empty-variant-values",
      empty_variant_values_base: DEFAULT_DEFINITIONS_PREFIX + "/empty-variant-values/",
      emptyValuesBase: DEFAULT_DEFINITIONS_PREFIX + "/empty-variant-values/",
      validate_variant: DEFAULT_DEFINITIONS_PREFIX + "/validate-variant",
      validateVariant: DEFAULT_DEFINITIONS_PREFIX + "/validate-variant"
    };
  }

  function resolveDefinitionEndpoints(context, definitions, routes) {
    try {
      var routeMap = routes || resolveDefinitionRoutes(context, definitions);

      return {
        options: routeMap.options || DEFAULT_DEFINITIONS_PREFIX + "/options",
        payload: routeMap.payload || DEFAULT_DEFINITIONS_PREFIX + "/payload",
        resolveFamilyProfile: routeMap.resolveFamilyProfile || routeMap.resolve_family_profile || DEFAULT_DEFINITIONS_PREFIX + "/resolve-family-profile",
        resolve_family_profile: routeMap.resolve_family_profile || routeMap.resolveFamilyProfile || DEFAULT_DEFINITIONS_PREFIX + "/resolve-family-profile",
        resolveVariantProfile: routeMap.resolveVariantProfile || routeMap.resolve_variant_profile || DEFAULT_DEFINITIONS_PREFIX + "/resolve-variant-profile",
        resolve_variant_profile: routeMap.resolve_variant_profile || routeMap.resolveVariantProfile || DEFAULT_DEFINITIONS_PREFIX + "/resolve-variant-profile",
        variantProfileBase: routeMap.variantProfileBase || routeMap.variant_profile_base || DEFAULT_DEFINITIONS_PREFIX + "/variant-profiles/",
        variant_profile_base: routeMap.variant_profile_base || routeMap.variantProfileBase || DEFAULT_DEFINITIONS_PREFIX + "/variant-profiles/",
        emptyValuesBase: routeMap.emptyValuesBase || routeMap.empty_variant_values_base || DEFAULT_DEFINITIONS_PREFIX + "/empty-variant-values/",
        empty_values_base: routeMap.empty_variant_values_base || routeMap.emptyValuesBase || DEFAULT_DEFINITIONS_PREFIX + "/empty-variant-values/",
        validateVariant: routeMap.validateVariant || routeMap.validate_variant || DEFAULT_DEFINITIONS_PREFIX + "/validate-variant",
        validate_variant: routeMap.validate_variant || routeMap.validateVariant || DEFAULT_DEFINITIONS_PREFIX + "/validate-variant"
      };
    } catch (error) {
      return {};
    }
  }

  function normalizeCollections(definitions) {
    try {
      var raw = definitions || {};
      var rawDefinitions = raw.definitions || {};
      var options = raw.options || {};
      var catalogs = raw.catalogs || raw.definition_catalogs || raw.definitionCatalogs || {};

      return {
        objectKinds: firstArray(
          raw.objectKinds,
          raw.object_kinds,
          options.objectKinds,
          options.object_kinds,
          catalogs.objectKinds,
          catalogs.object_kinds,
          rawDefinitions.objectKinds,
          rawDefinitions.object_kinds
        ),
        familyProfiles: firstArray(
          raw.familyProfiles,
          raw.family_profiles,
          options.familyProfiles,
          options.family_profiles,
          catalogs.familyProfiles,
          catalogs.family_profiles,
          rawDefinitions.familyProfiles,
          rawDefinitions.family_profiles
        ),
        variantProfiles: firstArray(
          raw.variantProfiles,
          raw.variant_profiles,
          options.variantProfiles,
          options.variant_profiles,
          catalogs.variantProfiles,
          catalogs.variant_profiles,
          rawDefinitions.variantProfiles,
          rawDefinitions.variant_profiles
        ),
        variables: firstArray(
          raw.variables,
          options.variables,
          catalogs.variables,
          rawDefinitions.variables
        ),
        units: firstArray(
          raw.units,
          options.units,
          catalogs.units,
          rawDefinitions.units
        ),
        materials: firstArray(
          raw.materials,
          raw.material_classes,
          raw.materialClasses,
          options.materials,
          options.material_classes,
          options.materialClasses,
          catalogs.materials,
          catalogs.material_classes,
          catalogs.materialClasses,
          rawDefinitions.materials,
          rawDefinitions.material_classes,
          rawDefinitions.materialClasses
        ),
        documentTypes: firstArray(
          raw.documentTypes,
          raw.document_types,
          options.documentTypes,
          options.document_types,
          catalogs.documentTypes,
          catalogs.document_types,
          rawDefinitions.documentTypes,
          rawDefinitions.document_types
        ),
        profileBindings: firstArray(
          raw.profileBindings,
          raw.profile_bindings,
          options.profileBindings,
          options.profile_bindings,
          catalogs.profileBindings,
          catalogs.profile_bindings,
          rawDefinitions.profileBindings,
          rawDefinitions.profile_bindings
        )
      };
    } catch (error) {
      warn("Collection normalization failed.", error);
      return createEmptyCollections();
    }
  }

  function createEmptyCollections() {
    return {
      objectKinds: [],
      familyProfiles: [],
      variantProfiles: [],
      variables: [],
      units: [],
      materials: [],
      documentTypes: [],
      profileBindings: []
    };
  }

  function buildMaps(collections) {
    try {
      var source = collections || createEmptyCollections();

      return {
        objectKinds: indexById(source.objectKinds),
        familyProfiles: indexById(source.familyProfiles),
        variantProfiles: indexById(source.variantProfiles),
        variables: indexByKey(source.variables),
        units: indexById(source.units),
        materials: indexById(source.materials),
        documentTypes: indexById(source.documentTypes),
        profileBindings: indexById(source.profileBindings)
      };
    } catch (error) {
      warn("Map build failed.", error);
      return createEmptyMaps();
    }
  }

  function createEmptyMaps() {
    return {
      objectKinds: {},
      familyProfiles: {},
      variantProfiles: {},
      variables: {},
      units: {},
      materials: {},
      documentTypes: {},
      profileBindings: {}
    };
  }

  function isDefinitionsReady(definitions, collections) {
    try {
      var defs = definitions || {};
      var cols = collections || createEmptyCollections();

      return Boolean(
        (defs.ready || defs.ok || cols.variables.length > 0) &&
        cols.objectKinds.length > 0 &&
        cols.familyProfiles.length > 0 &&
        cols.variantProfiles.length > 0 &&
        cols.variables.length > 0
      );
    } catch (error) {
      return false;
    }
  }

  function collectionCounts() {
    return {
      objectKinds: state.collections.objectKinds.length,
      familyProfiles: state.collections.familyProfiles.length,
      variantProfiles: state.collections.variantProfiles.length,
      variables: state.collections.variables.length,
      units: state.collections.units.length,
      materials: state.collections.materials.length,
      documentTypes: state.collections.documentTypes.length,
      profileBindings: state.collections.profileBindings.length
    };
  }

  function bindGlobalEvents() {
    try {
      if (document.documentElement.getAttribute("data-vp-create-definitions-runtime-events-bound") === "true") {
        return;
      }

      document.addEventListener("vectoplan:create:context-ready", function (event) {
        try {
          if (event && event.detail) {
            state.context = event.detail;
          }
        } catch (error) {
          warn("Context-ready listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:definitions-ready", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail.__vp_bridge_event && detail.component === COMPONENT_NAME) {
            return;
          }

          var definitionsCandidate = detail.definitionsApi || detail.definitions || detail;

          state.definitionsApi = definitionsCandidate;
          state.definitions = definitionsCandidate;
          state.collections = normalizeCollections(definitionsCandidate);
          state.maps = buildMaps(state.collections);
          state.ready = isDefinitionsReady(definitionsCandidate, state.collections);

          safeSetAttribute(document.documentElement, READY_ATTR, state.ready ? "true" : "false");
        } catch (error) {
          warn("Definitions-ready listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:definitions-unavailable", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (detail.__vp_bridge_event && detail.component === COMPONENT_NAME) {
            return;
          }

          state.ready = false;

          if (detail.error) {
            state.lastError = detail.error;
          }

          safeSetAttribute(document.documentElement, READY_ATTR, "false");
        } catch (error) {
          warn("Definitions-unavailable listener failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:variant-profile-resolved", function (event) {
        try {
          syncResolvedProfileToLegacyFields(event && event.detail ? event.detail : {}, "event");
        } catch (error) {
          warn("Variant-profile-resolved listener failed.", error);
        }
      });

      [
        "vectoplan:create:variant-state-ready",
        "vectoplan:create:variant-state-changed",
        "vectoplan:create:variant-state-synced",
        "vectoplan:create:variant-added",
        "vectoplan:create:variant-updated",
        "vectoplan:create:variant-removed"
      ].forEach(function (eventName) {
        document.addEventListener(eventName, function (event) {
          try {
            if (eventName === "vectoplan:create:variant-state-ready") {
              hydrateVariants({
                source: "variant-state-ready",
                emitEvents: false
              });
              return;
            }

            syncVariantsFromEvent(event && event.detail ? event.detail : {}, {
              source: eventName.replace("vectoplan:create:", "")
            });
          } catch (error) {
            warn("Variant event listener failed: " + eventName, error);
          }
        });
      });

      document.documentElement.setAttribute("data-vp-create-definitions-runtime-events-bound", "true");
    } catch (error) {
      warn("Global event binding failed.", error);
    }
  }

  function bindPassiveLegacyFallbacks() {
    try {
      if (document.documentElement.getAttribute("data-vp-create-definitions-runtime-passive-fallbacks-bound") === "true") {
        return;
      }

      document.addEventListener("change", function (event) {
        try {
          var target = event.target;

          if (!target || !target.matches || isProgrammaticEventTarget(target) || state.suppressProfileFieldChange) {
            return;
          }

          var changedContext =
            target.matches(SELECTORS.domainSelect) ||
            target.matches(SELECTORS.categorySelect) ||
            target.matches(SELECTORS.subcategorySelect) ||
            target.matches(SELECTORS.objectKindSelect);

          if (!changedContext) {
            return;
          }

          clearLegacyProfileFields();
          requestProfileResolve("legacy_context_change");
        } catch (error) {
          warn("Passive context-change fallback failed.", error);
        }
      });

      document.addEventListener("click", function (event) {
        try {
          var target = event.target;

          if (!target || !target.closest) {
            return;
          }

          var addButton = target.closest(SELECTORS.addVariant);
          if (addButton && !window.VectoplanCreateVariantDrawer) {
            dispatchDocument("vectoplan:create:variant-add-requested", {
              source: COMPONENT_NAME,
              reason: "legacy_add_button_without_new_drawer",
              __vp_bridge_event: true
            });
            return;
          }

          var editButton = target.closest(SELECTORS.editVariant);
          if (editButton && !window.VectoplanCreateVariantDrawer) {
            var row = closest(editButton, SELECTORS.row);
            dispatchDocument("vectoplan:create:variant-edit-requested", row ? safeMerge(payloadFromRow(row), {
              __vp_bridge_event: true
            }) : {
              source: COMPONENT_NAME,
              reason: "legacy_edit_button_without_new_drawer",
              __vp_bridge_event: true
            });
          }
        } catch (error) {
          warn("Passive add/edit fallback failed.", error);
        }
      });

      document.documentElement.setAttribute("data-vp-create-definitions-runtime-passive-fallbacks-bound", "true");
    } catch (error) {
      warn("Passive fallback binding failed.", error);
    }
  }

  function resolveCurrentProfile(options) {
    try {
      var config = options || {};
      var now = Date.now();

      if (state.pendingResolve && now - state.lastResolveAt < 80 && !config.force) {
        return Promise.resolve(state.currentProfilePayload);
      }

      state.pendingResolve = true;
      state.lastResolveAt = now;

      var context = safeMerge(collectContext(), config.context || {});

      dispatchDocument("vectoplan:create:variant-profile-resolve-requested", {
        component: COMPONENT_NAME,
        version: RUNTIME_VERSION,
        source: config.source || "definitions-runtime-bridge",
        context: context,
        force: !!config.force,
        __vp_bridge_event: true
      });

      if (
        window.VectoplanCreateVariantProfiles &&
        typeof window.VectoplanCreateVariantProfiles.resolveCurrentProfile === "function"
      ) {
        return Promise.resolve(window.VectoplanCreateVariantProfiles.resolveCurrentProfile({
          source: config.source || "definitions-runtime-bridge",
          context: context,
          force: !!config.force
        })).then(function (result) {
          state.pendingResolve = false;

          if (result && result.ok) {
            state.currentProfilePayload = normalizeProfilePayload(result);
            syncResolvedProfileToLegacyFields(state.currentProfilePayload, "profiles_api");
          }

          return result;
        }).catch(function (error) {
          state.pendingResolve = false;
          state.lastError = error;
          warn("Delegated profile resolution failed.", error);

          var fallback = resolveVariantProfileLocally(context);
          if (fallback && fallback.ok) {
            state.currentProfilePayload = normalizeProfilePayload(fallback);
            syncResolvedProfileToLegacyFields(state.currentProfilePayload, "local_fallback");
          }

          return fallback;
        });
      }

      var local = resolveVariantProfileLocally(context);
      state.pendingResolve = false;

      if (local && local.ok) {
        state.currentProfilePayload = normalizeProfilePayload(local);
        syncResolvedProfileToLegacyFields(state.currentProfilePayload, "local");
      }

      return Promise.resolve(local);
    } catch (error) {
      state.pendingResolve = false;
      state.lastError = error;
      warn("resolveCurrentProfile failed.", error);
      return Promise.reject(error);
    }
  }

  function requestProfileResolve(reason) {
    try {
      window.setTimeout(function () {
        resolveCurrentProfile({
          source: reason || "legacy_bridge",
          force: false
        }).catch(function (error) {
          warn("Scheduled profile resolve failed.", error);
        });
      }, 80);
    } catch (error) {
      warn("Could not request profile resolve.", error);
    }
  }

  function resolveVariantProfileLocally(context) {
    try {
      var ctx = normalizeContext(context || collectContext());

      if (ctx.variant_profile_id && state.maps.variantProfiles[ctx.variant_profile_id]) {
        return {
          ok: true,
          source: "legacy_bridge_local_explicit",
          family_profile_id: ctx.family_profile_id,
          variant_profile_id: ctx.variant_profile_id,
          variant_profile: state.maps.variantProfiles[ctx.variant_profile_id],
          profile: state.maps.variantProfiles[ctx.variant_profile_id],
          context: ctx
        };
      }

      var familyId = ctx.family_profile_id || resolveFamilyProfileIdLocally(ctx);
      var binding = resolveBindingLocally(safeMerge(ctx, {
        family_profile_id: familyId
      }));

      if (binding && binding.variant_profile_id && state.maps.variantProfiles[binding.variant_profile_id]) {
        return {
          ok: true,
          source: "legacy_bridge_local_binding",
          family_profile_id: familyId,
          family_profile: familyId ? state.maps.familyProfiles[familyId] || null : null,
          variant_profile_id: binding.variant_profile_id,
          variant_profile: state.maps.variantProfiles[binding.variant_profile_id],
          profile: state.maps.variantProfiles[binding.variant_profile_id],
          binding: binding,
          context: safeMerge(ctx, {
            family_profile_id: familyId,
            variant_profile_id: binding.variant_profile_id
          })
        };
      }

      if (familyId && state.maps.familyProfiles[familyId]) {
        var family = state.maps.familyProfiles[familyId];
        var defaultVariantProfileId = family.default_variant_profile_id || family.defaultVariantProfileId || "";

        if (defaultVariantProfileId && state.maps.variantProfiles[defaultVariantProfileId]) {
          return {
            ok: true,
            source: "legacy_bridge_local_family_default",
            family_profile_id: familyId,
            family_profile: family,
            variant_profile_id: defaultVariantProfileId,
            variant_profile: state.maps.variantProfiles[defaultVariantProfileId],
            profile: state.maps.variantProfiles[defaultVariantProfileId],
            context: safeMerge(ctx, {
              family_profile_id: familyId,
              variant_profile_id: defaultVariantProfileId
            })
          };
        }
      }

      var matched = firstCompatibleVariantProfile(ctx, familyId);

      if (matched) {
        return {
          ok: true,
          source: "legacy_bridge_local_profile_match",
          family_profile_id: familyId,
          family_profile: familyId ? state.maps.familyProfiles[familyId] || null : null,
          variant_profile_id: matched.id || matched.profile_id || "",
          variant_profile: matched,
          profile: matched,
          context: safeMerge(ctx, {
            family_profile_id: familyId,
            variant_profile_id: matched.id || matched.profile_id || ""
          })
        };
      }

      return {
        ok: false,
        source: "legacy_bridge_local",
        error: {
          code: "variant_profile_not_found",
          message: "Kein Variant Profile lokal gefunden."
        },
        context: ctx
      };
    } catch (error) {
      return {
        ok: false,
        source: "legacy_bridge_local",
        error: normalizeError(error),
        context: normalizeContext(context || {})
      };
    }
  }

  function resolveFamilyProfileIdLocally(context) {
    try {
      var ctx = normalizeContext(context || {});

      if (ctx.family_profile_id && state.maps.familyProfiles[ctx.family_profile_id]) {
        return ctx.family_profile_id;
      }

      var binding = resolveBindingLocally(ctx);

      if (binding && binding.family_profile_id && state.maps.familyProfiles[binding.family_profile_id]) {
        return binding.family_profile_id;
      }

      var candidates = state.collections.familyProfiles.filter(function (profile) {
        return profileMatchesContext(profile, ctx);
      });

      candidates.sort(function (a, b) {
        return profileScore(b, ctx) - profileScore(a, ctx);
      });

      if (candidates.length) {
        return candidates[0].id || candidates[0].profile_id || "";
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function resolveBindingLocally(context) {
    try {
      var ctx = normalizeContext(context || {});
      var candidates = state.collections.profileBindings.filter(function (binding) {
        return bindingMatchesContext(binding, ctx);
      });

      candidates.sort(function (a, b) {
        var scoreDiff = bindingScore(b, ctx) - bindingScore(a, ctx);

        if (scoreDiff !== 0) {
          return scoreDiff;
        }

        var priorityA = parseInt(a.priority || "1000", 10);
        var priorityB = parseInt(b.priority || "1000", 10);

        if (priorityA !== priorityB) {
          return priorityA - priorityB;
        }

        var sortA = parseInt(a.sort_order || "1000", 10);
        var sortB = parseInt(b.sort_order || "1000", 10);

        if (sortA !== sortB) {
          return sortA - sortB;
        }

        return String(a.id || "").localeCompare(String(b.id || ""));
      });

      return candidates[0] || null;
    } catch (error) {
      return null;
    }
  }

  function bindingMatchesContext(binding, context) {
    try {
      if (!binding || binding.active === false) {
        return false;
      }

      var ctx = normalizeContext(context || {});
      var match = binding.match || {};

      if ((binding.use_only_if_family_profile_selected || match.use_only_if_family_profile_selected) && !ctx.family_profile_id) {
        return false;
      }

      if (!wildcardMatches(binding.domain || match.domain, ctx.domain)) {
        return false;
      }

      if (!wildcardMatches(binding.category || match.category, ctx.category)) {
        return false;
      }

      if (!wildcardMatches(binding.subcategory || match.subcategory, ctx.subcategory)) {
        return false;
      }

      if (!wildcardMatches(binding.object_kind || binding.objectKind || match.object_kind || match.objectKind, ctx.object_kind)) {
        return false;
      }

      if (ctx.family_profile_id && binding.family_profile_id && binding.family_profile_id !== ctx.family_profile_id) {
        return false;
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function bindingScore(binding, context) {
    try {
      var score = 0;
      var ctx = normalizeContext(context || {});

      if (binding.domain && wildcardMatches(binding.domain, ctx.domain)) {
        score += 10;
      }

      if (binding.category && wildcardMatches(binding.category, ctx.category)) {
        score += 20;
      }

      if (binding.subcategory && wildcardMatches(binding.subcategory, ctx.subcategory)) {
        score += 30;
      }

      if ((binding.object_kind || binding.objectKind) && wildcardMatches(binding.object_kind || binding.objectKind, ctx.object_kind)) {
        score += 40;
      }

      if (binding.family_profile_id && ctx.family_profile_id && binding.family_profile_id === ctx.family_profile_id) {
        score += 50;
      }

      if (binding.variant_profile_id) {
        score += 8;
      }

      return score;
    } catch (error) {
      return 0;
    }
  }

  function profileMatchesContext(profile, context) {
    try {
      if (!profile || profile.active === false) {
        return false;
      }

      var ctx = normalizeContext(context || {});

      if (ctx.object_kind && !listContains(profile.object_kinds || profile.objectKinds, ctx.object_kind, true)) {
        return false;
      }

      if (ctx.domain && !listContains(profile.taxonomy_domains || profile.domains, ctx.domain, true)) {
        return false;
      }

      if (ctx.category && !listContains(profile.taxonomy_categories || profile.categories, ctx.category, true)) {
        return false;
      }

      if (ctx.subcategory && !listContains(profile.taxonomy_subcategories || profile.subcategories, ctx.subcategory, true)) {
        return false;
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function profileScore(profile, context) {
    try {
      var ctx = normalizeContext(context || {});
      var score = 0;

      if (listContains(profile.object_kinds || profile.objectKinds, ctx.object_kind, false)) {
        score += 20;
      }

      if (listContains(profile.taxonomy_domains || profile.domains, ctx.domain, false)) {
        score += 10;
      }

      if (listContains(profile.taxonomy_categories || profile.categories, ctx.category, false)) {
        score += 20;
      }

      if (listContains(profile.taxonomy_subcategories || profile.subcategories, ctx.subcategory, false)) {
        score += 30;
      }

      return score;
    } catch (error) {
      return 0;
    }
  }

  function firstCompatibleVariantProfile(context, familyId) {
    try {
      var ctx = normalizeContext(context || {});
      var familyProfileId = familyId || ctx.family_profile_id || "";

      var candidates = state.collections.variantProfiles.filter(function (profile) {
        if (!profile || profile.active === false) {
          return false;
        }

        if (ctx.object_kind && !listContains(profile.object_kinds || profile.objectKinds, ctx.object_kind, true)) {
          return false;
        }

        if (familyProfileId && !listContains(profile.family_profiles || profile.familyProfiles, familyProfileId, true)) {
          return false;
        }

        return true;
      });

      candidates.sort(function (a, b) {
        return (parseInt(a.sort_order || "1000", 10) || 1000) - (parseInt(b.sort_order || "1000", 10) || 1000);
      });

      return candidates[0] || null;
    } catch (error) {
      return null;
    }
  }

  function normalizeProfilePayload(payload) {
    try {
      var source = payload || {};
      var profile = source.variant_profile || source.variantProfile || source.profile || null;
      var variantProfileId = source.variant_profile_id || source.variantProfileId || source.profile_id || source.profileId || (profile && profile.id) || "";
      var familyProfileId = source.family_profile_id || source.familyProfileId || "";

      if (!familyProfileId && source.family_profile && source.family_profile.id) {
        familyProfileId = source.family_profile.id;
      }

      if (!familyProfileId && profile && Array.isArray(profile.family_profiles) && profile.family_profiles.length) {
        familyProfileId = profile.family_profiles[0];
      }

      return {
        ok: source.ok !== false,
        status: source.status || "ok",
        source: source.source || "definitions_runtime_bridge",
        family_profile_id: familyProfileId,
        familyProfileId: familyProfileId,
        family_profile: source.family_profile || source.familyProfile || (familyProfileId ? state.maps.familyProfiles[familyProfileId] || null : null),
        familyProfile: source.family_profile || source.familyProfile || (familyProfileId ? state.maps.familyProfiles[familyProfileId] || null : null),
        variant_profile_id: variantProfileId,
        variantProfileId: variantProfileId,
        variant_profile: profile || (variantProfileId ? state.maps.variantProfiles[variantProfileId] || null : null),
        variantProfile: profile || (variantProfileId ? state.maps.variantProfiles[variantProfileId] || null : null),
        profile: profile || (variantProfileId ? state.maps.variantProfiles[variantProfileId] || null : null),
        binding: source.binding || null,
        binding_id: source.binding_id || source.bindingId || "",
        bindingId: source.binding_id || source.bindingId || "",
        resolution_strategy: source.resolution_strategy || source.resolutionStrategy || source.strategy || "",
        resolutionStrategy: source.resolution_strategy || source.resolutionStrategy || source.strategy || "",
        context: normalizeContext(source.context || collectContext()),
        raw: source
      };
    } catch (error) {
      return payload || {};
    }
  }

  function syncResolvedProfileToLegacyFields(payload, source) {
    try {
      var normalized = normalizeProfilePayload(payload || {});
      var familyProfileId = normalized.family_profile_id || "";
      var variantProfileId = normalized.variant_profile_id || "";
      var signature = familyProfileId + "::" + variantProfileId + "::" + String(source || "");

      if (!familyProfileId && !variantProfileId) {
        return false;
      }

      if (state.lastProfileSignature === signature && source === "event") {
        return false;
      }

      state.lastProfileSignature = signature;
      state.suppressProfileFieldChange = true;

      queryAll(SELECTORS.familyProfileField).forEach(function (field) {
        if (familyProfileId) {
          setFieldValue(field, familyProfileId, false);
        }
      });

      queryAll(SELECTORS.variantProfileField).forEach(function (field) {
        if (variantProfileId) {
          setFieldValue(field, variantProfileId, false);
        }
      });

      state.suppressProfileFieldChange = false;
      state.currentProfilePayload = normalized;

      queryAll(SELECTORS.workspace + ", " + SELECTORS.table + ", " + SELECTORS.drawer).forEach(function (node) {
        if (familyProfileId) {
          safeSetAttribute(node, "data-vp-current-family-profile-id", familyProfileId);
          safeSetAttribute(node, "data-vp-family-profile-id", familyProfileId);
        }

        if (variantProfileId) {
          safeSetAttribute(node, "data-vp-current-variant-profile-id", variantProfileId);
          safeSetAttribute(node, "data-vp-variant-profile-id", variantProfileId);
        }
      });

      safeSetAttribute(document.documentElement, "data-vp-current-family-profile", familyProfileId);
      safeSetAttribute(document.documentElement, "data-vp-current-variant-profile", variantProfileId);

      if (source && source !== "event") {
        dispatchDocument("vectoplan:create:variant-profile-resolved", safeMerge(normalized, {
          source: source || "definitions_runtime_bridge",
          __vp_bridge_event: true
        }));
      }

      return true;
    } catch (error) {
      state.suppressProfileFieldChange = false;
      warn("Profile field sync failed.", error);
      return false;
    }
  }

  function clearLegacyProfileFields() {
    try {
      state.suppressProfileFieldChange = true;

      queryAll(SELECTORS.familyProfileField).forEach(function (field) {
        setFieldValue(field, "", false);
      });

      queryAll(SELECTORS.variantProfileField).forEach(function (field) {
        setFieldValue(field, "", false);
      });

      state.suppressProfileFieldChange = false;
      state.currentProfilePayload = null;
      state.lastProfileSignature = "";

      queryAll(SELECTORS.workspace + ", " + SELECTORS.table + ", " + SELECTORS.drawer).forEach(function (node) {
        safeSetAttribute(node, "data-vp-current-family-profile-id", "");
        safeSetAttribute(node, "data-vp-current-variant-profile-id", "");
        safeSetAttribute(node, "data-vp-family-profile-id", "");
        safeSetAttribute(node, "data-vp-variant-profile-id", "");
      });

      dispatchDocument("vectoplan:create:variant-profile-cleared", {
        component: COMPONENT_NAME,
        version: RUNTIME_VERSION,
        source: "definitions_runtime_bridge",
        __vp_bridge_event: true
      });
    } catch (error) {
      state.suppressProfileFieldChange = false;
      warn("Clearing legacy profile fields failed.", error);
    }
  }

  function openVariantDrawer(options) {
    try {
      var config = options || {};

      if (
        window.VectoplanCreateVariantDrawer &&
        typeof window.VectoplanCreateVariantDrawer.open === "function"
      ) {
        return window.VectoplanCreateVariantDrawer.open(safeMerge(config, {
          mode: config.mode || "create",
          source: config.source || "definitions_runtime_bridge"
        }));
      }

      dispatchDocument("vectoplan:create:variant-add-requested", {
        component: COMPONENT_NAME,
        version: RUNTIME_VERSION,
        source: config.source || "definitions_runtime_bridge",
        mode: config.mode || "create",
        __vp_bridge_event: true
      });

      return Promise.resolve(null);
    } catch (error) {
      state.lastError = error;
      warn("openVariantDrawer bridge failed.", error);
      return Promise.reject(error);
    }
  }

  function editVariantDrawer(payload) {
    try {
      var normalizedPayload = normalizeVariantPayload(payload || {});

      if (
        window.VectoplanCreateVariantDrawer &&
        typeof window.VectoplanCreateVariantDrawer.open === "function"
      ) {
        return window.VectoplanCreateVariantDrawer.open(safeMerge(normalizedPayload, {
          mode: "edit",
          source: "definitions_runtime_bridge"
        }));
      }

      dispatchDocument("vectoplan:create:variant-edit-requested", safeMerge(normalizedPayload, {
        component: COMPONENT_NAME,
        version: RUNTIME_VERSION,
        source: "definitions_runtime_bridge",
        __vp_bridge_event: true
      }));

      return Promise.resolve(null);
    } catch (error) {
      state.lastError = error;
      warn("editVariantDrawer bridge failed.", error);
      return Promise.reject(error);
    }
  }

  function closeVariantDrawer(reason) {
    try {
      if (
        window.VectoplanCreateVariantDrawer &&
        typeof window.VectoplanCreateVariantDrawer.close === "function"
      ) {
        return window.VectoplanCreateVariantDrawer.close(reason || "definitions_runtime_bridge");
      }

      if (
        window.VectoplanCreateVariantDrawerShell &&
        typeof window.VectoplanCreateVariantDrawerShell.close === "function"
      ) {
        return window.VectoplanCreateVariantDrawerShell.close(reason || "definitions_runtime_bridge");
      }

      dispatchDocument("vectoplan:create:variant-drawer-close-requested", {
        component: COMPONENT_NAME,
        version: RUNTIME_VERSION,
        reason: reason || "definitions_runtime_bridge",
        __vp_bridge_event: true
      });

      return true;
    } catch (error) {
      warn("closeVariantDrawer bridge failed.", error);
      return false;
    }
  }

  function validateVariant(input, options) {
    try {
      var payload = input || {};
      var config = options || {};

      if (
        window.VectoplanCreateVariantValidation &&
        typeof window.VectoplanCreateVariantValidation.validateVariant === "function"
      ) {
        return window.VectoplanCreateVariantValidation.validateVariant(payload, config);
      }

      if (
        window.VectoplanCreateVariantDrawer &&
        typeof window.VectoplanCreateVariantDrawer.validateDrawer === "function"
      ) {
        return window.VectoplanCreateVariantDrawer.validateDrawer(config);
      }

      return Promise.resolve(localValidateVariant(payload));
    } catch (error) {
      return Promise.resolve({
        ok: false,
        valid: false,
        errors: [normalizeError(error)],
        warnings: []
      });
    }
  }

  function validateDrawer(options) {
    try {
      if (
        window.VectoplanCreateVariantValidation &&
        typeof window.VectoplanCreateVariantValidation.validateDrawer === "function"
      ) {
        return window.VectoplanCreateVariantValidation.validateDrawer(options || {});
      }

      if (
        window.VectoplanCreateVariantDrawer &&
        typeof window.VectoplanCreateVariantDrawer.validateDrawer === "function"
      ) {
        return window.VectoplanCreateVariantDrawer.validateDrawer(options || {});
      }

      return Promise.resolve(localValidateVariant({}));
    } catch (error) {
      return Promise.resolve({
        ok: false,
        valid: false,
        errors: [normalizeError(error)],
        warnings: []
      });
    }
  }

  function buildEmptyVariantValues(profileId, context) {
    try {
      if (
        window.VectoplanCreateVariantProfiles &&
        typeof window.VectoplanCreateVariantProfiles.getEmptyVariantValues === "function"
      ) {
        return window.VectoplanCreateVariantProfiles.getEmptyVariantValues(profileId, context || collectContext());
      }

      return Promise.resolve(buildEmptyVariantValuesLocally(profileId));
    } catch (error) {
      return Promise.resolve({});
    }
  }

  function buildEmptyVariantValuesLocally(profileId) {
    try {
      var profile = profileId ? state.maps.variantProfiles[profileId] : null;
      var values = {};

      if (!profile) {
        return values;
      }

      var fields = collectProfileFields(profile);

      fields.forEach(function (fieldKey) {
        var variable = state.maps.variables[fieldKey] || {};

        if (profile.default_values && Object.prototype.hasOwnProperty.call(profile.default_values, fieldKey)) {
          values[fieldKey] = deepClone(profile.default_values[fieldKey]);
        } else if (Object.prototype.hasOwnProperty.call(variable, "default_value")) {
          values[fieldKey] = deepClone(variable.default_value);
        } else {
          values[fieldKey] = emptyValueForVariable(variable);
        }
      });

      if (!values["variant.variant_id"]) {
        values["variant.variant_id"] = "default";
      }

      if (!values["variant.label"]) {
        values["variant.label"] = "Standard";
      }

      return values;
    } catch (error) {
      return {};
    }
  }

  function localValidateVariant(input) {
    try {
      var variant = normalizeVariantPayload(input || {});
      var values = variant.definition_values || {};
      var errors = [];

      if (!values["variant.variant_id"] && !variant.variant_id) {
        errors.push({
          code: "required",
          field_key: "variant.variant_id",
          message: "Variant-ID fehlt."
        });
      }

      if (!values["variant.label"] && !variant.label && !variant.name) {
        errors.push({
          code: "required",
          field_key: "variant.label",
          message: "Variantenname fehlt."
        });
      }

      return {
        ok: errors.length === 0,
        valid: errors.length === 0,
        errors: errors,
        warnings: [],
        source: "definitions_runtime_bridge_local"
      };
    } catch (error) {
      return {
        ok: false,
        valid: false,
        errors: [normalizeError(error)],
        warnings: []
      };
    }
  }

  function hydrateVariants(options) {
    try {
      var config = options || {};

      if (state.hydrateInProgress) {
        state.suppressedSyncCount += 1;
        return state.variants.slice();
      }

      state.hydrateInProgress = true;

      if (
        window.VectoplanCreateVariantState &&
        typeof window.VectoplanCreateVariantState.getVariants === "function"
      ) {
        state.variants = window.VectoplanCreateVariantState.getVariants() || [];
        syncAggregateVariantsJson({
          source: config.source || "hydrate-state",
          emitEvents: false,
          pullFromVariantState: true
        });

        state.hydrateInProgress = false;
        return state.variants;
      }

      var aggregate = query(SELECTORS.definitionVariantsJson);
      if (aggregate && aggregate.value) {
        var parsed = safeJsonParse(aggregate.value, []);
        state.variants = Array.isArray(parsed) ? parsed : [];
        state.hydrateInProgress = false;
        return state.variants;
      }

      state.variants = queryAll(SELECTORS.row).map(payloadFromRow).filter(Boolean);
      syncAggregateVariantsJson({
        source: config.source || "hydrate-rows",
        emitEvents: false,
        pullFromVariantState: false
      });

      state.hydrateInProgress = false;
      return state.variants;
    } catch (error) {
      state.hydrateInProgress = false;
      warn("Variant hydration failed.", error);
      state.variants = [];
      return state.variants;
    }
  }

  function syncVariantsFromEvent(detail, options) {
    try {
      var payload = detail || {};
      var config = options || {};

      if (state.syncInProgress) {
        state.suppressedSyncCount += 1;
        return false;
      }

      if (payload.__vp_bridge_event && payload.component === COMPONENT_NAME) {
        return false;
      }

      state.syncInProgress = true;
      state.syncDepth += 1;

      if (state.syncDepth > 3) {
        state.suppressedSyncCount += 1;
        state.syncDepth -= 1;
        state.syncInProgress = false;
        return false;
      }

      if (payload.variants && Array.isArray(payload.variants)) {
        state.variants = payload.variants.slice();
      } else if (payload.state && payload.state.variants && Array.isArray(payload.state.variants)) {
        state.variants = payload.state.variants.slice();
      } else if (
        window.VectoplanCreateVariantState &&
        typeof window.VectoplanCreateVariantState.getVariants === "function"
      ) {
        state.variants = window.VectoplanCreateVariantState.getVariants() || [];
      }

      syncAggregateVariantsJson({
        source: config.source || "variant-event",
        emitEvents: false,
        pullFromVariantState: true
      });

      state.lastSyncAt = Date.now();
      state.lastEventAt = Date.now();

      state.syncDepth -= 1;
      state.syncInProgress = false;

      return true;
    } catch (error) {
      state.syncDepth = Math.max(0, state.syncDepth - 1);
      state.syncInProgress = false;
      warn("Variant sync from event failed.", error);
      return false;
    }
  }

  function syncAggregateVariantsJson(options) {
    try {
      var config = options || {};
      var aggregate = query(SELECTORS.definitionVariantsJson);
      var variants = [];

      if (config.pullFromVariantState !== false &&
        window.VectoplanCreateVariantState &&
        typeof window.VectoplanCreateVariantState.getPayload === "function"
      ) {
        variants = window.VectoplanCreateVariantState.getPayload() || [];
      } else if (config.pullFromVariantState !== false &&
        window.VectoplanCreateVariantState &&
        typeof window.VectoplanCreateVariantState.getVariants === "function"
      ) {
        variants = window.VectoplanCreateVariantState.getVariants() || [];
      } else {
        variants = state.variants || [];
      }

      if (!Array.isArray(variants)) {
        if (variants && Array.isArray(variants.variants)) {
          variants = variants.variants;
        } else if (variants && Array.isArray(variants.definition_variants)) {
          variants = variants.definition_variants;
        } else {
          variants = [];
        }
      }

      if (!aggregate) {
        var form = query(SELECTORS.form);

        if (!form) {
          return false;
        }

        aggregate = document.createElement("input");
        aggregate.type = "hidden";
        aggregate.name = "definition_variants_json";
        aggregate.setAttribute("data-vp-definition-variants-json", "true");
        aggregate.setAttribute("data-vp-bridge-owned", "true");
        form.appendChild(aggregate);
      }

      var json = stringifyJson(variants);

      if (aggregate.value === json && state.lastAggregateJson === json) {
        return true;
      }

      aggregate.value = json;
      aggregate.setAttribute("data-vp-last-bridge-sync", String(Date.now()));
      aggregate.setAttribute("data-vp-last-bridge-sync-source", String(config.source || "bridge"));
      state.lastAggregateJson = json;

      if (config.emitEvents === true) {
        dispatchNativeEvent(aggregate, "input", {
          silent: true
        });
        dispatchNativeEvent(aggregate, "change", {
          silent: true
        });
      }

      return true;
    } catch (error) {
      warn("Aggregate variant JSON sync failed.", error);
      return false;
    }
  }

  function getVariants() {
    try {
      if (
        window.VectoplanCreateVariantState &&
        typeof window.VectoplanCreateVariantState.getVariants === "function"
      ) {
        return window.VectoplanCreateVariantState.getVariants() || [];
      }

      if (Array.isArray(state.variants)) {
        return state.variants.slice();
      }

      return [];
    } catch (error) {
      return [];
    }
  }

  function normalizeVariantPayload(payload) {
    try {
      if (!payload) {
        return {};
      }

      if (payload.nodeType === 1) {
        return payloadFromRow(payload);
      }

      var source = safeMerge({}, payload);
      var values = {};

      if (source.definition_values && typeof source.definition_values === "object") {
        values = deepClone(source.definition_values);
      } else if (source.values && typeof source.values === "object") {
        values = deepClone(source.values);
      } else if (source.definition_values_json) {
        values = safeJsonParse(source.definition_values_json, {});
      } else if (source.valuesJson) {
        values = safeJsonParse(source.valuesJson, {});
      } else if (source.values_json) {
        values = safeJsonParse(source.values_json, {});
      }

      if (source.variant_id || source.variantId || source.slug || source.id) {
        values["variant.variant_id"] = values["variant.variant_id"] || source.variant_id || source.variantId || source.slug || source.id;
      }

      if (source.label || source.name || source.variant_label || source.variantLabel) {
        values["variant.label"] = values["variant.label"] || source.label || source.name || source.variant_label || source.variantLabel;
      }

      if (source.description) {
        values["variant.description"] = values["variant.description"] || source.description;
      }

      return safeMerge(source, {
        variant_id: source.variant_id || source.variantId || source.slug || source.id || values["variant.variant_id"] || "",
        label: source.label || source.name || source.variant_label || source.variantLabel || values["variant.label"] || "",
        name: source.name || source.label || values["variant.label"] || "",
        description: source.description || values["variant.description"] || "",
        variant_profile_id: source.variant_profile_id || source.variantProfileId || source.profile_id || "",
        family_profile_id: source.family_profile_id || source.familyProfileId || "",
        definition_values: values,
        definition_values_json: stringifyJson(values)
      });
    } catch (error) {
      return payload || {};
    }
  }

  function payloadFromRow(row) {
    try {
      if (!row) {
        return {};
      }

      function field(selector, fallback) {
        var node = query(selector, row);
        return node ? getValue(node, fallback || "") : fallback || "";
      }

      var valuesJson = field("[data-vp-row-definition-values-json]", "");
      var values = safeJsonParse(valuesJson, {});

      var variantId =
        getAttr(row, "data-vp-variant-id", "") ||
        getAttr(row, "data-vp-definition-variant-id", "") ||
        field("[data-vp-variant-slug]", "") ||
        values["variant.variant_id"] ||
        "";

      var label =
        getAttr(row, "data-vp-variant-label", "") ||
        field("[data-vp-variant-name]", "") ||
        values["variant.label"] ||
        "";

      return {
        row: row,
        rowIndex: parseInt(getAttr(row, "data-row-index", getAttr(row, "data-vp-variant-index", "0")), 10) || 0,
        variant_id: variantId,
        variantId: variantId,
        slug: variantId,
        id: variantId,
        label: label,
        name: label,
        kind: getAttr(row, "data-vp-variant-kind", "") || field("[data-vp-row-variant-kind]", ""),
        description: field("[data-vp-row-variant-description]", "") || values["variant.description"] || "",
        variant_profile_id: getAttr(row, "data-vp-variant-profile-id", "") || field("[data-vp-row-variant-profile-id]", ""),
        variantProfileId: getAttr(row, "data-vp-variant-profile-id", "") || field("[data-vp-row-variant-profile-id]", ""),
        family_profile_id: getAttr(row, "data-vp-family-profile-id", ""),
        familyProfileId: getAttr(row, "data-vp-family-profile-id", ""),
        definition_values: values,
        definition_values_json: valuesJson,
        values: values,
        valuesJson: valuesJson,
        definition_summary: field("[data-vp-row-definition-summary-input]", "") || getText(query("[data-vp-row-definition-summary='true']", row)),
        summary: field("[data-vp-row-definition-summary-input]", "") || getText(query("[data-vp-row-definition-summary='true']", row)),
        is_default: getAttr(row, "data-vp-is-default", "") === "true" || variantId === "default"
      };
    } catch (error) {
      return {};
    }
  }

  function collectContext(form) {
    try {
      var safeForm = form || query(SELECTORS.form);

      var context = {
        domain: normalizeToken(getFieldValue(safeForm, "domain") || getValue(query(SELECTORS.domainSelect), ""), ""),
        category: normalizeToken(getFieldValue(safeForm, "category") || getValue(query(SELECTORS.categorySelect), ""), ""),
        subcategory: normalizeToken(getFieldValue(safeForm, "subcategory") || getValue(query(SELECTORS.subcategorySelect), ""), ""),
        object_kind: normalizeToken(
          getFieldValue(safeForm, "object_kind") ||
          getFieldValue(safeForm, "object_class") ||
          getValue(query(SELECTORS.objectKindSelect), "") ||
          "cell_block",
          "cell_block"
        ),
        family_profile_id: normalizeProfileId(getFieldValue(safeForm, "family_profile_id") || getValue(query(SELECTORS.familyProfileField), "")),
        variant_profile_id: normalizeProfileId(getFieldValue(safeForm, "variant_profile_id") || getValue(query(SELECTORS.variantProfileField), ""))
      };

      return normalizeContext(context);
    } catch (error) {
      return {
        domain: "",
        category: "",
        subcategory: "",
        object_kind: "cell_block",
        family_profile_id: "",
        variant_profile_id: ""
      };
    }
  }

  function normalizeContext(context) {
    try {
      var source = context || {};

      return {
        domain: normalizeToken(source.domain || source.taxonomy_domain || "", ""),
        category: normalizeToken(source.category || source.taxonomy_category || "", ""),
        subcategory: normalizeToken(source.subcategory || source.taxonomy_subcategory || "", ""),
        object_kind: normalizeToken(source.object_kind || source.objectKind || source.object_class || "cell_block", "cell_block"),
        family_profile_id: normalizeProfileId(source.family_profile_id || source.familyProfileId || ""),
        variant_profile_id: normalizeProfileId(source.variant_profile_id || source.variantProfileId || "")
      };
    } catch (error) {
      return {
        domain: "",
        category: "",
        subcategory: "",
        object_kind: "cell_block",
        family_profile_id: "",
        variant_profile_id: ""
      };
    }
  }

  function getFieldValue(form, name) {
    try {
      if (!form || !name) {
        return "";
      }

      var field = form.elements ? form.elements[name] : null;

      if (!field) {
        field = query("[name='" + cssEscape(name) + "']", form);
      }

      if (!field) {
        return "";
      }

      if (typeof RadioNodeList !== "undefined" && field instanceof RadioNodeList) {
        return field.value || "";
      }

      return typeof field.value !== "undefined" ? String(field.value) : "";
    } catch (error) {
      return "";
    }
  }

  function exposePublicApi() {
    try {
      window[GLOBAL_NAME] = {
        version: RUNTIME_VERSION,
        bridgeVersion: RUNTIME_VERSION,
        mode: "bridge",
        initialize: initializeRuntime,

        getState: function () {
          return {
            initialized: state.initialized,
            ready: state.ready,
            bridgeReady: state.bridgeReady,
            pendingResolve: state.pendingResolve,
            counts: collectionCounts(),
            currentProfilePayload: state.currentProfilePayload,
            variants: getVariants(),
            routes: safeMerge({}, state.routes),
            endpoints: safeMerge({}, state.endpoints),
            modules: detectModules(),
            lastError: state.lastError ? errorMessage(state.lastError) : null,
            sync: {
              lastSyncAt: state.lastSyncAt,
              lastAggregateJsonLength: state.lastAggregateJson ? state.lastAggregateJson.length : 0,
              syncInProgress: state.syncInProgress,
              syncDepth: state.syncDepth,
              suppressedSyncCount: state.suppressedSyncCount
            }
          };
        },

        getDefinitions: function () {
          return {
            raw: state.definitions,
            definitionsApi: state.definitionsApi,
            collections: state.collections,
            maps: state.maps,
            routes: state.routes,
            endpoints: state.endpoints,
            counts: collectionCounts()
          };
        },

        getCollections: function () {
          return deepClone(state.collections);
        },

        getMaps: function () {
          return state.maps;
        },

        getRoutes: function () {
          return safeMerge({}, state.routes);
        },

        getEndpoints: function () {
          return safeMerge({}, state.endpoints);
        },

        getVariants: getVariants,

        syncVariants: function () {
          hydrateVariants({
            source: "public_api",
            emitEvents: false
          });
          syncAggregateVariantsJson({
            source: "public_api",
            emitEvents: false,
            pullFromVariantState: true
          });
          return getVariants();
        },

        collectContext: collectContext,

        resolveCurrentProfile: resolveCurrentProfile,
        resolveVariantProfile: function (context) {
          return resolveCurrentProfile({
            context: context || collectContext(),
            source: "definitions_runtime_public_api",
            force: true
          });
        },

        getCurrentProfilePayload: function () {
          return deepClone(state.currentProfilePayload);
        },

        getVariantProfile: function (profileId) {
          try {
            var id = normalizeProfileId(profileId || "");

            if (
              window.VectoplanCreateVariantProfiles &&
              typeof window.VectoplanCreateVariantProfiles.getVariantProfile === "function"
            ) {
              return window.VectoplanCreateVariantProfiles.getVariantProfile(id);
            }

            return Promise.resolve({
              ok: !!state.maps.variantProfiles[id],
              profile_id: id,
              variant_profile_id: id,
              variant_profile: state.maps.variantProfiles[id] || null,
              profile: state.maps.variantProfiles[id] || null,
              source: "definitions_runtime_bridge_local"
            });
          } catch (error) {
            return Promise.reject(error);
          }
        },

        buildEmptyVariantValues: buildEmptyVariantValues,

        openVariantDrawer: openVariantDrawer,
        editVariantDrawer: editVariantDrawer,
        closeVariantDrawer: closeVariantDrawer,
        closeDrawer: closeVariantDrawer,

        validateVariant: validateVariant,
        validateDrawer: validateDrawer,

        refresh: function () {
          state.context = resolveContext();
          state.generatorContext = resolveGeneratorContext();
          state.definitionsApi = resolveDefinitionsApi();
          state.definitions = state.definitionsApi || resolveDefinitions();
          state.collections = normalizeCollections(state.definitions);
          state.maps = buildMaps(state.collections);
          state.routes = resolveDefinitionRoutes(state.context, state.definitions);
          state.endpoints = resolveDefinitionEndpoints(state.context, state.definitions, state.routes);
          state.ready = isDefinitionsReady(state.definitions, state.collections);

          hydrateVariants({
            source: "refresh",
            emitEvents: false
          });

          safeSetAttribute(document.documentElement, READY_ATTR, state.ready ? "true" : "false");
          redispatchDefinitionsState();
          return this.getState();
        }
      };
    } catch (error) {
      warn("Expose public API failed.", error);
    }
  }

  function query(selector, root) {
    try {
      if (!selector) {
        return null;
      }

      return (root || document).querySelector(selector);
    } catch (error) {
      return null;
    }
  }

  function queryAll(selector, root) {
    try {
      if (!selector) {
        return [];
      }

      return Array.prototype.slice.call((root || document).querySelectorAll(selector));
    } catch (error) {
      return [];
    }
  }

  function closest(node, selector) {
    try {
      return node && node.closest ? node.closest(selector) : null;
    } catch (error) {
      return null;
    }
  }

  function getAttr(node, name, fallback) {
    try {
      if (!node || !name) {
        return fallback || "";
      }

      var value = node.getAttribute(name);

      if (value === null || value === undefined) {
        return fallback || "";
      }

      return value;
    } catch (error) {
      return fallback || "";
    }
  }

  function getValue(node, fallback) {
    try {
      if (!node) {
        return fallback || "";
      }

      if (node.type === "checkbox") {
        return node.checked ? "true" : "false";
      }

      if (typeof node.value !== "undefined") {
        return String(node.value);
      }

      return String(node.textContent || fallback || "");
    } catch (error) {
      return fallback || "";
    }
  }

  function getText(node) {
    try {
      if (!node) {
        return "";
      }

      return String(node.textContent || "").trim();
    } catch (error) {
      return "";
    }
  }

  function setFieldValue(field, value, emitEvents) {
    try {
      if (!field) {
        return false;
      }

      var nextValue = value === null || value === undefined ? "" : String(value);

      if (field.value === nextValue) {
        return false;
      }

      field.value = nextValue;
      field.setAttribute("data-vp-bridge-updated", "true");
      field.setAttribute("data-vp-bridge-updated-at", String(Date.now()));

      if (emitEvents === true && !state.suppressProfileFieldChange) {
        dispatchNativeEvent(field, "input", {
          silent: true
        });
        dispatchNativeEvent(field, "change", {
          silent: true
        });
      }

      return true;
    } catch (error) {
      return false;
    }
  }

  function dispatchNativeEvent(node, eventName, options) {
    try {
      if (!node || !eventName) {
        return false;
      }

      var utils = window.VectoplanCreateVariantUtils;

      if (utils && typeof utils.dispatchNative === "function") {
        return utils.dispatchNative(node, eventName, safeMerge({
          source: COMPONENT_NAME,
          silent: true
        }, options || {}));
      }

      node.setAttribute("data-vp-programmatic-event", String(eventName));
      node.setAttribute("data-vp-programmatic-event-source", COMPONENT_NAME);

      node.dispatchEvent(new Event(eventName, {
        bubbles: true,
        cancelable: false
      }));

      window.setTimeout(function () {
        try {
          if (node.getAttribute("data-vp-programmatic-event") === String(eventName)) {
            node.removeAttribute("data-vp-programmatic-event");
            node.removeAttribute("data-vp-programmatic-event-source");
          }
        } catch (cleanupError) {
          /* no-op */
        }
      }, 0);

      return true;
    } catch (error) {
      try {
        var event = document.createEvent("Event");
        event.initEvent(eventName, true, false);
        node.dispatchEvent(event);
        return true;
      } catch (legacyError) {
        return false;
      }
    }
  }

  function dispatchDocument(name, detail) {
    try {
      var payload = safeMerge(detail || {}, {
        __vp_bridge_event: true,
        __vp_bridge_component: COMPONENT_NAME,
        __vp_bridge_version: RUNTIME_VERSION
      });

      var utils = window.VectoplanCreateVariantUtils;

      if (utils && typeof utils.dispatchDocument === "function") {
        return utils.dispatchDocument(name, payload, {
          silent: true
        });
      }

      document.dispatchEvent(new CustomEvent(name, {
        bubbles: true,
        cancelable: false,
        detail: payload
      }));

      return true;
    } catch (error) {
      return false;
    }
  }

  function safeSetAttribute(node, name, value) {
    try {
      if (node) {
        node.setAttribute(name, value);
      }
    } catch (error) {
      /* no-op */
    }
  }

  function firstArray() {
    try {
      for (var index = 0; index < arguments.length; index += 1) {
        if (Array.isArray(arguments[index])) {
          return arguments[index];
        }
      }

      return [];
    } catch (error) {
      return [];
    }
  }

  function indexById(items) {
    var map = {};

    try {
      (items || []).forEach(function (item) {
        var id = item && (item.id || item.profile_id || item.variant_profile_id || item.key || item.value);

        if (id) {
          map[String(id)] = item;
        }
      });
    } catch (error) {
      /* no-op */
    }

    return map;
  }

  function indexByKey(items) {
    var map = {};

    try {
      (items || []).forEach(function (item) {
        var key = item && (item.key || item.id || item.value);

        if (key) {
          map[String(key)] = item;
        }
      });
    } catch (error) {
      /* no-op */
    }

    return map;
  }

  function safeMerge() {
    try {
      var output = {};
      var args = Array.prototype.slice.call(arguments);

      args.forEach(function (object) {
        if (!object || typeof object !== "object") {
          return;
        }

        Object.keys(object).forEach(function (key) {
          output[key] = object[key];
        });
      });

      return output;
    } catch (error) {
      return {};
    }
  }

  function deepClone(value) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      if (Array.isArray(value)) {
        return value.slice();
      }

      if (value && typeof value === "object") {
        return safeMerge({}, value);
      }

      return value;
    }
  }

  function safeJsonParse(value, fallback) {
    try {
      if (value && typeof value === "object") {
        return value;
      }

      var text = String(value || "").trim();

      if (!text) {
        return fallback;
      }

      return JSON.parse(text);
    } catch (error) {
      return fallback;
    }
  }

  function stringifyJson(value) {
    try {
      return JSON.stringify(value);
    } catch (error) {
      return "[]";
    }
  }

  function normalizeToken(value, fallback) {
    try {
      var text = String(value || "")
        .trim()
        .toLowerCase()
        .replace(/ä/g, "ae")
        .replace(/ö/g, "oe")
        .replace(/ü/g, "ue")
        .replace(/ß/g, "ss")
        .replace(/[-\s]+/g, "_")
        .replace(/[^a-z0-9_./]/g, "");

      return text || fallback || "";
    } catch (error) {
      return fallback || "";
    }
  }

  function normalizeProfileId(value) {
    try {
      return String(value || "")
        .trim()
        .replace(/\s+/g, "")
        .replace(/-/g, "_");
    } catch (error) {
      return "";
    }
  }

  function wildcardMatches(expected, actual) {
    try {
      var cleanExpected = normalizeToken(expected || "", "");
      var cleanActual = normalizeToken(actual || "", "");

      if (!cleanExpected || cleanExpected === "*" || cleanExpected === "any") {
        return true;
      }

      if (!cleanActual) {
        return false;
      }

      return cleanExpected === cleanActual;
    } catch (error) {
      return false;
    }
  }

  function listContains(list, value, emptyMeansTrue) {
    try {
      var array = Array.isArray(list) ? list : [];

      if (!array.length) {
        return !!emptyMeansTrue;
      }

      return array.map(String).indexOf(String(value || "")) !== -1;
    } catch (error) {
      return false;
    }
  }

  function collectProfileFields(profile) {
    try {
      var fields = [];
      var seen = {};

      function add(key) {
        if (!key || seen[key]) {
          return;
        }

        seen[key] = true;
        fields.push(key);
      }

      (profile.sections || []).forEach(function (section) {
        (section.fields || []).forEach(add);
      });

      (profile.all_fields || []).forEach(add);
      (profile.required_fields || []).forEach(add);
      (profile.optional_fields || []).forEach(add);

      return fields;
    } catch (error) {
      return [];
    }
  }

  function emptyValueForVariable(variable) {
    try {
      var type = variable.value_type || variable.type || "string";

      if (type === "boolean") {
        return false;
      }

      if (type === "array" || type === "multi_enum" || type === "document_list") {
        return [];
      }

      if (type === "object") {
        return {};
      }

      if (type === "number" || type === "integer" || type === "money") {
        return null;
      }

      return "";
    } catch (error) {
      return "";
    }
  }

  function cssEscape(value) {
    try {
      if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(String(value));
      }

      return String(value || "").replace(/["\\]/g, "\\$&");
    } catch (error) {
      return String(value || "").replace(/["\\]/g, "\\$&");
    }
  }

  function isProgrammaticEventTarget(node) {
    try {
      if (!node) {
        return false;
      }

      if (node.getAttribute("data-vp-programmatic-event")) {
        return true;
      }

      if (node.__vpProgrammaticEvent) {
        return true;
      }

      if (node.getAttribute("data-vp-bridge-updated") === "true") {
        var updatedAt = parseInt(node.getAttribute("data-vp-bridge-updated-at") || "0", 10);

        if (Date.now() - updatedAt < 50) {
          return true;
        }
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function normalizeError(error) {
    try {
      if (!error) {
        return {
          code: "unknown_error",
          message: "Unbekannter Fehler."
        };
      }

      return {
        code: error.code || error.status || "error",
        message: error.message || String(error),
        status: error.status || null,
        payload: error.payload || null
      };
    } catch (innerError) {
      return {
        code: "error",
        message: "Fehler konnte nicht normalisiert werden."
      };
    }
  }

  function errorMessage(error) {
    return String(error && error.message ? error.message : error || "");
  }

  function warn(message, error) {
    try {
      if (window.console && typeof window.console.warn === "function") {
        window.console.warn("[" + COMPONENT_NAME + "] " + message, error || "");
      }
    } catch (consoleError) {
      /* no-op */
    }
  }

  function onReady(callback) {
    try {
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", callback, {
          once: true
        });
      } else {
        callback();
      }
    } catch (error) {
      warn("DOM ready binding failed.", error);
    }
  }

  exposePublicApi();

  onReady(function () {
    initializeRuntime();
  });
})();