// static/js/inventar/taxonomy-navigation.js
(function () {
  "use strict";

  var MODULE_NAME = "VectoplanTaxonomyNavigation";
  var MODULE_VERSION = "1.1.0";

  var DEFAULT_TAXONOMY_URL = "/api/v1/vplib/taxonomy/create-options";
  var SESSION_CACHE_KEY = "vectoplan.inventory.taxonomy.createOptions.v1";
  var SESSION_CACHE_TTL_MS = 5 * 60 * 1000;

  var SPECIAL_DOMAIN_ALL = "all";
  var SPECIAL_WORLD_EDIT = "world_edit";

  var SELECTORS = {
    root: "[data-taxonomy-root]",
    fallbackRoot: ".vp-creative-layout",
    fallbackPage: ".vp-creative-inventar-page",

    tabs: "#vp-creative-taxonomy-tabs, [data-taxonomy-tabs], .vp-creative-tabs",
    filters: "#vp-creative-taxonomy-filters, [data-taxonomy-filters], .vp-creative-filters",
    subfilters: "#vp-creative-taxonomy-subfilters, [data-taxonomy-subfilters], .vp-creative-subfilters",
    status: "#vp-creative-taxonomy-status, [data-taxonomy-status], .vp-creative-taxonomy-status",

    creativeGrid: "[data-creative-library-grid], #creative-items, .vp-creative-grid",
    creativeCard: "[data-creative-item-card], .vp-creative-card",

    createToggle: "[data-create-embed-toggle]",
    createPanel: "[data-create-embed-panel]"
  };

  var CLASSES = {
    tab: "vp-creative-tab",
    tabActive: "vp-creative-tab--active",

    filter: "vp-creative-filter",
    filterActive: "vp-creative-filter--active",

    subfilter: "vp-creative-subfilter",
    subfilterActive: "vp-creative-subfilter--active",

    statusFilter: "vp-creative-filter vp-creative-filter--active",

    cardHidden: "vp-creative-card--hidden-by-taxonomy",
    cardVisible: "vp-creative-card--visible-by-taxonomy",

    taxonomyLocked: "vp-taxonomy-is-locked",
    controlLocked: "vp-creative-taxonomy-control--locked",

    statusBase: "vp-creative-taxonomy-status",
    statusLoading: "vp-creative-taxonomy-status--loading",
    statusReady: "vp-creative-taxonomy-status--ready",
    statusError: "vp-creative-taxonomy-status--error",
    statusInfo: "vp-creative-taxonomy-status--info"
  };

  var EVENTS = {
    selectionChange: "vectoplan:taxonomy-selection-change",
    selectionBlocked: "vectoplan:taxonomy-selection-blocked",
    ready: "vectoplan:taxonomy-ready",
    error: "vectoplan:taxonomy-error",
    filterApplied: "vectoplan:taxonomy-filter-applied",
    createEmbedOpen: "vectoplan:create-embed-open",
    createEmbedClose: "vectoplan:create-embed-close",
    createEmbedTaxonomyLockChange: "vectoplan:create-embed-taxonomy-lock-change"
  };

  var state = {
    initialized: false,
    eventsBound: false,
    loading: false,
    error: null,

    taxonomyUrl: DEFAULT_TAXONOMY_URL,
    includeWorldEdit: true,

    filterCardsEnabled: true,
    lockAware: true,

    taxonomy: null,

    selectedDomainId: SPECIAL_DOMAIN_ALL,
    selectedCategoryId: SPECIAL_DOMAIN_ALL,
    selectedSubcategoryId: SPECIAL_DOMAIN_ALL,

    lastRenderedAt: 0,
    lastFilterAppliedAt: 0,
    lastBlockedSelection: null,

    elements: {
      root: null,
      tabs: null,
      filters: null,
      subfilters: null,
      status: null,
      creativeGrid: null,
      creativeCards: []
    }
  };

  var memoryCache = {
    value: null,
    cachedAt: 0
  };

  function init() {
    try {
      if (state.initialized) {
        refreshElements();
        return true;
      }

      var root = findRootElement();

      if (!root) {
        return false;
      }

      state.elements.root = root;
      readConfiguration(root);
      refreshElements();

      if (!state.elements.tabs || !state.elements.filters) {
        warn("Required taxonomy navigation containers are missing.", {
          hasTabs: Boolean(state.elements.tabs),
          hasFilters: Boolean(state.elements.filters)
        });
        return false;
      }

      bindEvents();

      state.initialized = true;
      setStatus("Taxonomie wird geladen ...", "loading");

      loadTaxonomy()
        .then(function (taxonomy) {
          try {
            state.taxonomy = taxonomy;
            state.loading = false;
            state.error = null;

            normalizeInitialSelection();
            renderAll();
            applyCreativeCardFilter();
            setStatus("", "ready");
            dispatchReady();
            dispatchSelectionChanged({ source: "initial-load" });
          } catch (renderError) {
            state.error = renderError;
            state.loading = false;
            setStatus("Taxonomie konnte nicht gerendert werden.", "error");
            error("Rendering failed.", renderError);
            dispatchError(renderError, "render");
          }
        })
        .catch(function (loadError) {
          state.loading = false;
          state.error = loadError;

          setStatus("Taxonomie konnte nicht geladen werden.", "error");
          error("Loading failed.", loadError);
          dispatchError(loadError, "load");
        });

      return true;
    } catch (initError) {
      state.error = initError;
      state.loading = false;
      setStatus("Taxonomie konnte nicht initialisiert werden.", "error");
      error("Initialization failed.", initError);
      dispatchError(initError, "init");
      return false;
    }
  }

  function refreshElements() {
    try {
      var root = state.elements.root || findRootElement();

      if (!root) {
        return false;
      }

      state.elements.root = root;
      state.elements.tabs = findTabsElement(root);
      state.elements.filters = findFiltersElement(root);
      state.elements.subfilters = findOrCreateSubfiltersElement(root);
      state.elements.status = findOrCreateStatusElement(root);
      state.elements.creativeGrid = findCreativeGridElement(root);
      state.elements.creativeCards = findCreativeCards(root);

      return true;
    } catch (err) {
      state.error = err;
      error("Could not refresh taxonomy elements.", err);
      return false;
    }
  }

  function readConfiguration(root) {
    try {
      var element = root || state.elements.root;

      state.taxonomyUrl = readTaxonomyUrl(element);
      state.includeWorldEdit = readBooleanDataset(element, "includeWorldEdit", true);
      state.filterCardsEnabled = readBooleanDataset(element, "taxonomyFilterCards", true);
      state.lockAware = readBooleanDataset(element, "taxonomyLockAware", true);

      state.selectedDomainId = cleanString(readDatasetValue(element, "selectedDomain")) || SPECIAL_DOMAIN_ALL;
      state.selectedCategoryId = cleanString(readDatasetValue(element, "selectedCategory")) || SPECIAL_DOMAIN_ALL;
      state.selectedSubcategoryId = cleanString(readDatasetValue(element, "selectedSubcategory")) || SPECIAL_DOMAIN_ALL;

      syncRootDataset();
    } catch (err) {
      warn("Could not read taxonomy configuration. Defaults are used.", err);
      state.taxonomyUrl = DEFAULT_TAXONOMY_URL;
      state.includeWorldEdit = true;
      state.filterCardsEnabled = true;
      state.lockAware = true;
      state.selectedDomainId = SPECIAL_DOMAIN_ALL;
      state.selectedCategoryId = SPECIAL_DOMAIN_ALL;
      state.selectedSubcategoryId = SPECIAL_DOMAIN_ALL;
    }
  }

  function bindEvents() {
    if (state.eventsBound) {
      return;
    }

    state.eventsBound = true;

    try {
      document.addEventListener(EVENTS.createEmbedOpen, function () {
        try {
          syncLockedUi();
        } catch (err) {
          error("Create open sync failed.", err);
        }
      });
    } catch (err) {
      error("Could not bind create open event.", err);
    }

    try {
      document.addEventListener(EVENTS.createEmbedClose, function () {
        try {
          syncLockedUi();
        } catch (err) {
          error("Create close sync failed.", err);
        }
      });
    } catch (err) {
      error("Could not bind create close event.", err);
    }

    try {
      document.addEventListener(EVENTS.createEmbedTaxonomyLockChange, function () {
        try {
          syncLockedUi();
        } catch (err) {
          error("Create taxonomy lock sync failed.", err);
        }
      });
    } catch (err) {
      error("Could not bind taxonomy lock change event.", err);
    }
  }

  function findRootElement() {
    try {
      return (
        document.querySelector(SELECTORS.root) ||
        document.querySelector(SELECTORS.fallbackRoot) ||
        document.querySelector(SELECTORS.fallbackPage)
      );
    } catch (err) {
      error("Could not find root element.", err);
      return null;
    }
  }

  function findTabsElement(root) {
    try {
      return root ? root.querySelector(SELECTORS.tabs) : null;
    } catch (err) {
      error("Could not find tabs element.", err);
      return null;
    }
  }

  function findFiltersElement(root) {
    try {
      return root ? root.querySelector(SELECTORS.filters) : null;
    } catch (err) {
      error("Could not find filters element.", err);
      return null;
    }
  }

  function findOrCreateSubfiltersElement(root) {
    try {
      if (!root) {
        return null;
      }

      var existing = root.querySelector(SELECTORS.subfilters);

      if (existing) {
        return existing;
      }

      var filters = findFiltersElement(root);

      if (!filters || !filters.parentNode) {
        return null;
      }

      var subfilters = document.createElement("nav");
      subfilters.id = "vp-creative-taxonomy-subfilters";
      subfilters.className = "vp-creative-subfilters";
      subfilters.setAttribute("aria-label", "Creative Library Subkategorien");
      subfilters.setAttribute("data-taxonomy-subfilters", "true");
      subfilters.hidden = true;

      filters.parentNode.insertBefore(subfilters, filters.nextSibling);

      return subfilters;
    } catch (err) {
      error("Could not create subfilters element.", err);
      return null;
    }
  }

  function findOrCreateStatusElement(root) {
    try {
      if (!root) {
        return null;
      }

      var existing = root.querySelector(SELECTORS.status);

      if (existing) {
        return existing;
      }

      var filters = findFiltersElement(root);

      if (!filters || !filters.parentNode) {
        return null;
      }

      var status = document.createElement("div");
      status.id = "vp-creative-taxonomy-status";
      status.className = CLASSES.statusBase;
      status.setAttribute("aria-live", "polite");
      status.setAttribute("data-taxonomy-status", "true");
      status.hidden = true;

      filters.parentNode.insertBefore(status, filters);

      return status;
    } catch (err) {
      error("Could not create taxonomy status element.", err);
      return null;
    }
  }

  function findCreativeGridElement(root) {
    try {
      if (!root) {
        return null;
      }

      return root.querySelector(SELECTORS.creativeGrid);
    } catch (err) {
      error("Could not find creative grid.", err);
      return null;
    }
  }

  function findCreativeCards(root) {
    try {
      if (!root) {
        return [];
      }

      return toArray(root.querySelectorAll(SELECTORS.creativeCard));
    } catch (err) {
      error("Could not find creative cards.", err);
      return [];
    }
  }

  function readTaxonomyUrl(root) {
    try {
      var script = document.currentScript;
      var scriptUrl = script ? cleanString(script.getAttribute("data-taxonomy-url")) : "";
      var rootUrl = root ? cleanString(root.getAttribute("data-taxonomy-url")) : "";
      var bodyUrl = document.body ? cleanString(document.body.getAttribute("data-taxonomy-url")) : "";

      return scriptUrl || rootUrl || bodyUrl || DEFAULT_TAXONOMY_URL;
    } catch (err) {
      warn("Could not read taxonomy URL. Falling back to default.", err);
      return DEFAULT_TAXONOMY_URL;
    }
  }

  function loadTaxonomy() {
    state.loading = true;

    return new Promise(function (resolve, reject) {
      try {
        var memoryValue = readMemoryCache();

        if (memoryValue) {
          resolve(memoryValue);
          return;
        }

        var sessionValue = readSessionCache();

        if (sessionValue) {
          writeMemoryCache(sessionValue);
          resolve(sessionValue);
          return;
        }

        fetchTaxonomy()
          .then(function (payload) {
            try {
              var taxonomy = normalizeTaxonomyPayload(payload);

              if (!taxonomy || !Array.isArray(taxonomy.domains)) {
                throw new Error("Normalized taxonomy has no domains array.");
              }

              writeMemoryCache(taxonomy);
              writeSessionCache(taxonomy);

              resolve(taxonomy);
            } catch (normalizeError) {
              reject(normalizeError);
            }
          })
          .catch(reject);
      } catch (err) {
        reject(err);
      }
    });
  }

  function fetchTaxonomy() {
    return new Promise(function (resolve, reject) {
      try {
        var url = state.taxonomyUrl || DEFAULT_TAXONOMY_URL;

        if (typeof window.fetch !== "function") {
          reject(new Error("Fetch API is not available."));
          return;
        }

        fetch(url, {
          method: "GET",
          credentials: "same-origin",
          headers: {
            "Accept": "application/json",
            "X-VECTOPLAN-Taxonomy-Navigation": MODULE_VERSION
          },
          cache: "no-store"
        })
          .then(function (response) {
            return response.json().then(function (payload) {
              return {
                response: response,
                payload: payload
              };
            });
          })
          .then(function (result) {
            if (!result.response.ok || result.payload.ok === false) {
              throw new Error(extractMessage(result.payload) || ("Taxonomy request failed with HTTP " + result.response.status));
            }

            resolve(result.payload);
          })
          .catch(reject);
      } catch (err) {
        reject(err);
      }
    });
  }

  function readMemoryCache() {
    try {
      if (!memoryCache.value) {
        return null;
      }

      var age = Date.now() - Number(memoryCache.cachedAt || 0);

      if (age > SESSION_CACHE_TTL_MS) {
        memoryCache.value = null;
        memoryCache.cachedAt = 0;
        return null;
      }

      return memoryCache.value;
    } catch (err) {
      memoryCache.value = null;
      memoryCache.cachedAt = 0;
      return null;
    }
  }

  function writeMemoryCache(value) {
    try {
      memoryCache.value = value || null;
      memoryCache.cachedAt = value ? Date.now() : 0;
    } catch (err) {
      memoryCache.value = null;
      memoryCache.cachedAt = 0;
    }
  }

  function readSessionCache() {
    try {
      if (!window.sessionStorage) {
        return null;
      }

      var raw = window.sessionStorage.getItem(SESSION_CACHE_KEY);

      if (!raw) {
        return null;
      }

      var parsed = JSON.parse(raw);
      var cachedAt = Number(parsed.cachedAt || 0);
      var age = Date.now() - cachedAt;

      if (!parsed.value || age > SESSION_CACHE_TTL_MS) {
        window.sessionStorage.removeItem(SESSION_CACHE_KEY);
        return null;
      }

      return parsed.value;
    } catch (err) {
      try {
        window.sessionStorage.removeItem(SESSION_CACHE_KEY);
      } catch (removeError) {
        // ignore
      }

      return null;
    }
  }

  function writeSessionCache(value) {
    try {
      if (!window.sessionStorage || !value) {
        return;
      }

      window.sessionStorage.setItem(
        SESSION_CACHE_KEY,
        JSON.stringify({
          cachedAt: Date.now(),
          value: value
        })
      );
    } catch (err) {
      // sessionStorage can fail in private mode or due to quota.
    }
  }

  function clearCaches() {
    try {
      writeMemoryCache(null);

      if (window.sessionStorage) {
        window.sessionStorage.removeItem(SESSION_CACHE_KEY);
      }
    } catch (err) {
      // ignore
    }
  }

  function normalizeTaxonomyPayload(payload) {
    var root = unwrapPayload(payload);

    var rawDomains =
      asArray(root.domains) ||
      asArray(getPath(root, ["taxonomy", "domains"])) ||
      asArray(getPath(root, ["data", "domains"])) ||
      asArray(getPath(root, ["result", "domains"])) ||
      asArray(getPath(root, ["payload", "domains"])) ||
      [];

    var rawCategoriesByDomain =
      asObject(root.categories_by_domain) ||
      asObject(root.categoriesByDomain) ||
      asObject(getPath(root, ["data", "categories_by_domain"])) ||
      asObject(getPath(root, ["result", "categories_by_domain"])) ||
      asObject(getPath(root, ["payload", "categories_by_domain"])) ||
      {};

    var rawSubcategoriesByCategory =
      asObject(root.subcategories_by_category) ||
      asObject(root.subcategoriesByCategory) ||
      asObject(getPath(root, ["data", "subcategories_by_category"])) ||
      asObject(getPath(root, ["result", "subcategories_by_category"])) ||
      asObject(getPath(root, ["payload", "subcategories_by_category"])) ||
      {};

    var domains = normalizeDomains(rawDomains);
    var categoriesByDomain = normalizeCategoriesByDomain(domains, rawCategoriesByDomain);
    var subcategoriesByCategory = normalizeSubcategoriesByCategory(
      domains,
      categoriesByDomain,
      rawSubcategoriesByCategory
    );

    return {
      domains: domains,
      categoriesByDomain: categoriesByDomain,
      subcategoriesByCategory: subcategoriesByCategory,
      raw: payload
    };
  }

  function unwrapPayload(payload) {
    try {
      if (!payload || typeof payload !== "object") {
        return {};
      }

      if (Array.isArray(payload)) {
        return { domains: payload };
      }

      var candidates = [
        payload,
        payload.data,
        payload.result,
        payload.payload,
        payload.response,
        payload.taxonomy
      ];

      for (var i = 0; i < candidates.length; i += 1) {
        var candidate = candidates[i];

        if (!candidate || typeof candidate !== "object") {
          continue;
        }

        if (
          Array.isArray(candidate.domains) ||
          candidate.categories_by_domain ||
          candidate.categoriesByDomain ||
          candidate.subcategories_by_category ||
          candidate.subcategoriesByCategory ||
          candidate.taxonomy
        ) {
          return candidate;
        }
      }

      return payload;
    } catch (err) {
      return {};
    }
  }

  function normalizeDomains(rawDomains) {
    var result = [];

    try {
      rawDomains = Array.isArray(rawDomains) ? rawDomains : [];

      rawDomains.forEach(function (rawDomain) {
        var id = cleanString(rawDomain && (rawDomain.id || rawDomain.key || rawDomain.value || rawDomain.slug));
        var label = cleanString(rawDomain && (rawDomain.label || rawDomain.name || rawDomain.title)) || id;

        if (!id) {
          return;
        }

        result.push({
          id: id,
          label: label,
          description: cleanString(rawDomain.description),
          sortOrder: toNumber(rawDomain.sort_order || rawDomain.sortOrder, 9999),
          categories: normalizeCategoryList(rawDomain.categories || [])
        });
      });

      result.sort(sortByOrderThenLabel);
    } catch (err) {
      error("Could not normalize domains.", err);
    }

    return result;
  }

  function normalizeCategoriesByDomain(domains, rawCategoriesByDomain) {
    var result = {};

    try {
      domains.forEach(function (domain) {
        var fromDomain = normalizeCategoryList(domain.categories || []);
        var fromMap = normalizeCategoryList(rawCategoriesByDomain[domain.id] || []);

        result[domain.id] = fromMap.length ? fromMap : fromDomain;
      });
    } catch (err) {
      error("Could not normalize categories by domain.", err);
    }

    return result;
  }

  function normalizeSubcategoriesByCategory(domains, categoriesByDomain, rawSubcategoriesByCategory) {
    var result = {};

    try {
      domains.forEach(function (domain) {
        var categories = categoriesByDomain[domain.id] || [];

        categories.forEach(function (category) {
          var domainCategoryKey = makeCategoryKey(domain.id, category.id);
          var flatCategoryKey = category.id;

          var fromCategory = normalizeSubcategoryList(category.subcategories || []);
          var fromDomainCategoryMap = normalizeSubcategoryList(rawSubcategoriesByCategory[domainCategoryKey] || []);
          var fromFlatMap = normalizeSubcategoryList(rawSubcategoriesByCategory[flatCategoryKey] || []);

          result[domainCategoryKey] =
            fromDomainCategoryMap.length ? fromDomainCategoryMap :
            fromFlatMap.length ? fromFlatMap :
            fromCategory;
        });
      });
    } catch (err) {
      error("Could not normalize subcategories by category.", err);
    }

    return result;
  }

  function normalizeCategoryList(rawCategories) {
    var result = [];

    try {
      rawCategories = Array.isArray(rawCategories) ? rawCategories : [];

      rawCategories.forEach(function (rawCategory) {
        var id = cleanString(rawCategory && (rawCategory.id || rawCategory.key || rawCategory.value || rawCategory.slug));
        var label = cleanString(rawCategory && (rawCategory.label || rawCategory.name || rawCategory.title)) || id;

        if (!id) {
          return;
        }

        result.push({
          id: id,
          label: label,
          description: cleanString(rawCategory.description),
          sortOrder: toNumber(rawCategory.sort_order || rawCategory.sortOrder, 9999),
          allowedObjectKinds: asArray(rawCategory.allowed_object_kinds || rawCategory.allowedObjectKinds) || [],
          subcategories: normalizeSubcategoryList(rawCategory.subcategories || [])
        });
      });

      result.sort(sortByOrderThenLabel);
    } catch (err) {
      error("Could not normalize category list.", err);
    }

    return result;
  }

  function normalizeSubcategoryList(rawSubcategories) {
    var result = [];

    try {
      rawSubcategories = Array.isArray(rawSubcategories) ? rawSubcategories : [];

      rawSubcategories.forEach(function (rawSubcategory) {
        var id = cleanString(rawSubcategory && (rawSubcategory.id || rawSubcategory.key || rawSubcategory.value || rawSubcategory.slug));
        var label = cleanString(rawSubcategory && (rawSubcategory.label || rawSubcategory.name || rawSubcategory.title)) || id;

        if (!id) {
          return;
        }

        result.push({
          id: id,
          label: label,
          description: cleanString(rawSubcategory.description),
          sortOrder: toNumber(rawSubcategory.sort_order || rawSubcategory.sortOrder, 9999),
          allowedObjectKinds: asArray(rawSubcategory.allowed_object_kinds || rawSubcategory.allowedObjectKinds) || []
        });
      });

      result.sort(sortByOrderThenLabel);
    } catch (err) {
      error("Could not normalize subcategory list.", err);
    }

    return result;
  }

  function normalizeInitialSelection() {
    try {
      if (!isValidDomainId(state.selectedDomainId)) {
        state.selectedDomainId = SPECIAL_DOMAIN_ALL;
        state.selectedCategoryId = SPECIAL_DOMAIN_ALL;
        state.selectedSubcategoryId = SPECIAL_DOMAIN_ALL;
      }

      if (state.selectedDomainId === SPECIAL_DOMAIN_ALL || state.selectedDomainId === SPECIAL_WORLD_EDIT) {
        state.selectedCategoryId = SPECIAL_DOMAIN_ALL;
        state.selectedSubcategoryId = SPECIAL_DOMAIN_ALL;
      }

      if (state.selectedCategoryId !== SPECIAL_DOMAIN_ALL && !isValidCategoryId(state.selectedCategoryId)) {
        state.selectedCategoryId = SPECIAL_DOMAIN_ALL;
        state.selectedSubcategoryId = SPECIAL_DOMAIN_ALL;
      }

      if (state.selectedSubcategoryId !== SPECIAL_DOMAIN_ALL && !isValidSubcategoryId(state.selectedSubcategoryId)) {
        state.selectedSubcategoryId = SPECIAL_DOMAIN_ALL;
      }
    } catch (err) {
      state.selectedDomainId = SPECIAL_DOMAIN_ALL;
      state.selectedCategoryId = SPECIAL_DOMAIN_ALL;
      state.selectedSubcategoryId = SPECIAL_DOMAIN_ALL;
    }
  }

  function renderAll() {
    try {
      refreshElements();
      renderTabs();
      renderFilters();
      renderSubfilters();
      syncRootDataset();
      syncLockedUi();

      state.lastRenderedAt = Date.now();
    } catch (err) {
      error("Could not render taxonomy navigation.", err);
      throw err;
    }
  }

  function renderTabs() {
    var tabsElement = state.elements.tabs;

    if (!tabsElement) {
      return;
    }

    clearElement(tabsElement);

    var fragment = document.createDocumentFragment();

    fragment.appendChild(
      createTabButton({
        id: SPECIAL_DOMAIN_ALL,
        label: "Alle",
        active: state.selectedDomainId === SPECIAL_DOMAIN_ALL,
        special: false
      })
    );

    getDomains().forEach(function (domain) {
      fragment.appendChild(
        createTabButton({
          id: domain.id,
          label: domain.label,
          active: state.selectedDomainId === domain.id,
          special: false
        })
      );
    });

    if (state.includeWorldEdit) {
      fragment.appendChild(
        createTabButton({
          id: SPECIAL_WORLD_EDIT,
          label: "World Edit",
          active: state.selectedDomainId === SPECIAL_WORLD_EDIT,
          special: true
        })
      );
    }

    tabsElement.appendChild(fragment);
  }

  function renderFilters() {
    var filtersElement = state.elements.filters;

    if (!filtersElement) {
      return;
    }

    clearElement(filtersElement);

    var fragment = document.createDocumentFragment();

    if (state.selectedDomainId === SPECIAL_WORLD_EDIT) {
      fragment.appendChild(createStatusFilter("World Edit", "Tools"));
      filtersElement.appendChild(fragment);
      return;
    }

    var categories = getCategoriesForSelectedDomain();

    fragment.appendChild(
      createCategoryButton({
        id: SPECIAL_DOMAIN_ALL,
        label: state.selectedDomainId === SPECIAL_DOMAIN_ALL ? "Alles" : "Alle Kategorien",
        count: categories.length,
        active: state.selectedCategoryId === SPECIAL_DOMAIN_ALL
      })
    );

    categories.forEach(function (category) {
      fragment.appendChild(
        createCategoryButton({
          id: category.id,
          label: category.label,
          count: getSubcategoriesForCategory(category.id).length,
          active: state.selectedCategoryId === category.id
        })
      );
    });

    filtersElement.appendChild(fragment);
  }

  function renderSubfilters() {
    var subfiltersElement = state.elements.subfilters;

    if (!subfiltersElement) {
      return;
    }

    clearElement(subfiltersElement);

    if (
      state.selectedDomainId === SPECIAL_DOMAIN_ALL ||
      state.selectedDomainId === SPECIAL_WORLD_EDIT ||
      state.selectedCategoryId === SPECIAL_DOMAIN_ALL
    ) {
      subfiltersElement.hidden = true;
      subfiltersElement.setAttribute("aria-hidden", "true");
      return;
    }

    var subcategories = getSubcategoriesForSelectedCategory();

    if (!subcategories.length) {
      subfiltersElement.hidden = true;
      subfiltersElement.setAttribute("aria-hidden", "true");
      return;
    }

    subfiltersElement.hidden = false;
    subfiltersElement.removeAttribute("aria-hidden");

    var activeCategory = getSelectedCategory();
    var allLabel = activeCategory ? "Alle " + activeCategory.label : "Alle Subkategorien";

    var fragment = document.createDocumentFragment();

    fragment.appendChild(
      createSubcategoryButton({
        id: SPECIAL_DOMAIN_ALL,
        label: allLabel,
        active: state.selectedSubcategoryId === SPECIAL_DOMAIN_ALL
      })
    );

    subcategories.forEach(function (subcategory) {
      fragment.appendChild(
        createSubcategoryButton({
          id: subcategory.id,
          label: subcategory.label,
          active: state.selectedSubcategoryId === subcategory.id
        })
      );
    });

    subfiltersElement.appendChild(fragment);
  }

  function createTabButton(options) {
    var button = document.createElement("button");

    button.type = "button";
    button.className = CLASSES.tab + (options.active ? " " + CLASSES.tabActive : "");
    button.setAttribute("data-taxonomy-domain", options.id);
    button.setAttribute("aria-pressed", options.active ? "true" : "false");

    if (options.special) {
      button.setAttribute("data-taxonomy-special", "true");
    }

    setText(button, options.label);

    button.addEventListener("click", function (event) {
      handleControlClick(event, function () {
        selectDomain(options.id, { source: "tab-click" });
      });
    });

    return button;
  }

  function createCategoryButton(options) {
    var button = document.createElement("button");

    button.type = "button";
    button.className = CLASSES.filter + (options.active ? " " + CLASSES.filterActive : "");
    button.setAttribute("data-taxonomy-category", options.id);
    button.setAttribute("aria-pressed", options.active ? "true" : "false");

    var labelSpan = document.createElement("span");
    setText(labelSpan, options.label);

    var countStrong = document.createElement("strong");
    setText(countStrong, String(toNumber(options.count, 0)));

    button.appendChild(labelSpan);
    button.appendChild(countStrong);

    button.addEventListener("click", function (event) {
      handleControlClick(event, function () {
        selectCategory(options.id, { source: "category-click" });
      });
    });

    return button;
  }

  function createSubcategoryButton(options) {
    var button = document.createElement("button");

    button.type = "button";
    button.className = CLASSES.subfilter + (options.active ? " " + CLASSES.subfilterActive : "");
    button.setAttribute("data-taxonomy-subcategory", options.id);
    button.setAttribute("aria-pressed", options.active ? "true" : "false");

    var labelSpan = document.createElement("span");
    setText(labelSpan, options.label);

    button.appendChild(labelSpan);

    button.addEventListener("click", function (event) {
      handleControlClick(event, function () {
        selectSubcategory(options.id, { source: "subcategory-click" });
      });
    });

    return button;
  }

  function createStatusFilter(label, countText) {
    var item = document.createElement("div");

    item.className = CLASSES.statusFilter;
    item.setAttribute("data-taxonomy-status-filter", "true");

    var labelSpan = document.createElement("span");
    setText(labelSpan, label);

    var countStrong = document.createElement("strong");
    setText(countStrong, countText);

    item.appendChild(labelSpan);
    item.appendChild(countStrong);

    return item;
  }

  function handleControlClick(event, callback) {
    try {
      if (isSelectionLocked()) {
        blockSelection(event, {
          source: "control-click",
          reason: "create-embed-active"
        });
        return false;
      }

      if (typeof callback === "function") {
        callback();
      }

      return true;
    } catch (err) {
      state.error = err;
      error("Control click failed.", err);
      dispatchError(err, "control-click");
      return false;
    }
  }

  function selectDomain(domainId, options) {
    try {
      if (isSelectionLocked()) {
        return blockSelection(null, {
          source: options && options.source ? options.source : "select-domain",
          reason: "create-embed-active",
          requestedDomain: domainId
        });
      }

      var normalizedDomainId = cleanString(domainId) || SPECIAL_DOMAIN_ALL;

      if (!isValidDomainId(normalizedDomainId)) {
        normalizedDomainId = SPECIAL_DOMAIN_ALL;
      }

      state.selectedDomainId = normalizedDomainId;
      state.selectedCategoryId = SPECIAL_DOMAIN_ALL;
      state.selectedSubcategoryId = SPECIAL_DOMAIN_ALL;

      renderAll();
      applyCreativeCardFilter();
      dispatchSelectionChanged({
        source: options && options.source ? options.source : "select-domain"
      });

      return getPublicState();
    } catch (err) {
      state.error = err;
      error("Could not select domain.", err);
      dispatchError(err, "select-domain");
      return getPublicState();
    }
  }

  function selectCategory(categoryId, options) {
    try {
      if (isSelectionLocked()) {
        return blockSelection(null, {
          source: options && options.source ? options.source : "select-category",
          reason: "create-embed-active",
          requestedCategory: categoryId
        });
      }

      var normalizedCategoryId = cleanString(categoryId) || SPECIAL_DOMAIN_ALL;

      if (normalizedCategoryId !== SPECIAL_DOMAIN_ALL && !isValidCategoryId(normalizedCategoryId)) {
        normalizedCategoryId = SPECIAL_DOMAIN_ALL;
      }

      state.selectedCategoryId = normalizedCategoryId;
      state.selectedSubcategoryId = SPECIAL_DOMAIN_ALL;

      renderFilters();
      renderSubfilters();
      syncRootDataset();
      syncLockedUi();
      applyCreativeCardFilter();

      dispatchSelectionChanged({
        source: options && options.source ? options.source : "select-category"
      });

      return getPublicState();
    } catch (err) {
      state.error = err;
      error("Could not select category.", err);
      dispatchError(err, "select-category");
      return getPublicState();
    }
  }

  function selectSubcategory(subcategoryId, options) {
    try {
      if (isSelectionLocked()) {
        return blockSelection(null, {
          source: options && options.source ? options.source : "select-subcategory",
          reason: "create-embed-active",
          requestedSubcategory: subcategoryId
        });
      }

      var normalizedSubcategoryId = cleanString(subcategoryId) || SPECIAL_DOMAIN_ALL;

      if (normalizedSubcategoryId !== SPECIAL_DOMAIN_ALL && !isValidSubcategoryId(normalizedSubcategoryId)) {
        normalizedSubcategoryId = SPECIAL_DOMAIN_ALL;
      }

      state.selectedSubcategoryId = normalizedSubcategoryId;

      renderSubfilters();
      syncRootDataset();
      syncLockedUi();
      applyCreativeCardFilter();

      dispatchSelectionChanged({
        source: options && options.source ? options.source : "select-subcategory"
      });

      return getPublicState();
    } catch (err) {
      state.error = err;
      error("Could not select subcategory.", err);
      dispatchError(err, "select-subcategory");
      return getPublicState();
    }
  }

  function isSelectionLocked() {
    try {
      if (!state.lockAware) {
        return false;
      }

      var root = state.elements.root;

      if (!root || !root.dataset) {
        return false;
      }

      var createActive = root.dataset.createEmbedActive === "true";
      var taxonomyLocked = root.dataset.taxonomyLocked === "true";
      var lockConfigured = root.dataset.createEmbedLockTaxonomy !== "false";

      return Boolean(createActive && lockConfigured) || Boolean(taxonomyLocked);
    } catch (err) {
      return false;
    }
  }

  function blockSelection(event, detail) {
    try {
      if (event) {
        tryPreventDefault(event);
        tryStopPropagation(event);
      }

      var payload = detail && typeof detail === "object" ? detail : {};
      payload.domain = state.selectedDomainId;
      payload.category = state.selectedCategoryId;
      payload.subcategory = state.selectedSubcategoryId;
      payload.taxonomyLocked = true;
      payload.module = MODULE_NAME;
      payload.version = MODULE_VERSION;
      payload.blockedAt = Date.now();

      state.lastBlockedSelection = payload;

      syncLockedUi();

      document.dispatchEvent(
        new CustomEvent(EVENTS.selectionBlocked, {
          bubbles: true,
          detail: payload
        })
      );

      return getPublicState();
    } catch (err) {
      state.error = err;
      error("Could not block taxonomy selection.", err);
      return getPublicState();
    }
  }

  function syncLockedUi() {
    try {
      refreshElements();

      var locked = isSelectionLocked();
      var root = state.elements.root;
      var controls = []
        .concat(toArray(state.elements.tabs ? state.elements.tabs.children : []))
        .concat(toArray(state.elements.filters ? state.elements.filters.children : []))
        .concat(toArray(state.elements.subfilters ? state.elements.subfilters.children : []));

      if (root) {
        root.classList.toggle(CLASSES.taxonomyLocked, locked);

        if (root.dataset) {
          root.dataset.taxonomyNavigationLocked = locked ? "true" : "false";
        }
      }

      controls.forEach(function (control) {
        try {
          if (!control || control.getAttribute("data-taxonomy-status-filter") === "true") {
            return;
          }

          control.classList.toggle(CLASSES.controlLocked, locked);

          if (locked) {
            control.setAttribute("aria-disabled", "true");
            control.setAttribute("data-taxonomy-navigation-locked", "true");

            if (!control.hasAttribute("data-taxonomy-previous-tabindex")) {
              control.setAttribute(
                "data-taxonomy-previous-tabindex",
                control.hasAttribute("tabindex") ? control.getAttribute("tabindex") : ""
              );
            }

            control.setAttribute("tabindex", "-1");
          } else {
            control.removeAttribute("aria-disabled");
            control.removeAttribute("data-taxonomy-navigation-locked");

            if (control.hasAttribute("data-taxonomy-previous-tabindex")) {
              var previousTabindex = control.getAttribute("data-taxonomy-previous-tabindex");
              control.removeAttribute("data-taxonomy-previous-tabindex");

              if (previousTabindex === "") {
                control.removeAttribute("tabindex");
              } else {
                control.setAttribute("tabindex", previousTabindex);
              }
            }
          }
        } catch (err) {
          // ignore one control failure
        }
      });
    } catch (err) {
      error("Could not sync locked taxonomy UI.", err);
    }
  }

  function applyCreativeCardFilter() {
    try {
      if (!state.filterCardsEnabled) {
        return {
          enabled: false,
          total: 0,
          visible: 0,
          hidden: 0
        };
      }

      refreshElements();

      var cards = state.elements.creativeCards || [];
      var total = cards.length;
      var visible = 0;
      var hidden = 0;

      cards.forEach(function (card) {
        try {
          var shouldShow = shouldShowCard(card);

          card.hidden = !shouldShow;
          card.classList.toggle(CLASSES.cardHidden, !shouldShow);
          card.classList.toggle(CLASSES.cardVisible, shouldShow);
          card.setAttribute("aria-hidden", shouldShow ? "false" : "true");

          if (shouldShow) {
            visible += 1;
          } else {
            hidden += 1;
          }
        } catch (err) {
          visible += 1;
        }
      });

      state.lastFilterAppliedAt = Date.now();

      dispatchFilterApplied({
        total: total,
        visible: visible,
        hidden: hidden
      });

      return {
        enabled: true,
        total: total,
        visible: visible,
        hidden: hidden
      };
    } catch (err) {
      state.error = err;
      error("Could not apply creative card filter.", err);
      dispatchError(err, "apply-card-filter");
      return {
        enabled: state.filterCardsEnabled,
        total: 0,
        visible: 0,
        hidden: 0,
        error: stringifyError(err)
      };
    }
  }

  function shouldShowCard(card) {
    try {
      if (!card || !card.dataset) {
        return true;
      }

      var selectedDomain = state.selectedDomainId || SPECIAL_DOMAIN_ALL;
      var selectedCategory = state.selectedCategoryId || SPECIAL_DOMAIN_ALL;
      var selectedSubcategory = state.selectedSubcategoryId || SPECIAL_DOMAIN_ALL;

      if (selectedDomain === SPECIAL_WORLD_EDIT) {
        return false;
      }

      if (selectedDomain !== SPECIAL_DOMAIN_ALL) {
        if (cleanString(card.dataset.domain) !== selectedDomain) {
          return false;
        }
      }

      if (selectedCategory !== SPECIAL_DOMAIN_ALL) {
        if (cleanString(card.dataset.category) !== selectedCategory) {
          return false;
        }
      }

      if (selectedSubcategory !== SPECIAL_DOMAIN_ALL) {
        if (cleanString(card.dataset.subcategory) !== selectedSubcategory) {
          return false;
        }
      }

      return true;
    } catch (err) {
      return true;
    }
  }

  function getDomains() {
    try {
      return state.taxonomy && Array.isArray(state.taxonomy.domains)
        ? state.taxonomy.domains
        : [];
    } catch (err) {
      return [];
    }
  }

  function getCategoriesForSelectedDomain() {
    try {
      if (state.selectedDomainId === SPECIAL_DOMAIN_ALL) {
        return [];
      }

      if (state.selectedDomainId === SPECIAL_WORLD_EDIT) {
        return [];
      }

      return getCategoriesForDomain(state.selectedDomainId);
    } catch (err) {
      return [];
    }
  }

  function getCategoriesForDomain(domainId) {
    try {
      if (!state.taxonomy || !state.taxonomy.categoriesByDomain) {
        return [];
      }

      return state.taxonomy.categoriesByDomain[domainId] || [];
    } catch (err) {
      return [];
    }
  }

  function getSubcategoriesForSelectedCategory() {
    try {
      return getSubcategoriesForCategory(state.selectedCategoryId);
    } catch (err) {
      return [];
    }
  }

  function getSubcategoriesForCategory(categoryId) {
    try {
      if (
        !state.taxonomy ||
        !state.taxonomy.subcategoriesByCategory ||
        !state.selectedDomainId ||
        !categoryId ||
        categoryId === SPECIAL_DOMAIN_ALL
      ) {
        return [];
      }

      var key = makeCategoryKey(state.selectedDomainId, categoryId);

      return state.taxonomy.subcategoriesByCategory[key] || [];
    } catch (err) {
      return [];
    }
  }

  function getSelectedCategory() {
    try {
      var categories = getCategoriesForSelectedDomain();

      for (var i = 0; i < categories.length; i += 1) {
        if (categories[i].id === state.selectedCategoryId) {
          return categories[i];
        }
      }

      return null;
    } catch (err) {
      return null;
    }
  }

  function isValidDomainId(domainId) {
    try {
      var id = cleanString(domainId);

      if (id === SPECIAL_DOMAIN_ALL || id === SPECIAL_WORLD_EDIT) {
        return true;
      }

      var domains = getDomains();

      for (var i = 0; i < domains.length; i += 1) {
        if (domains[i].id === id) {
          return true;
        }
      }

      return false;
    } catch (err) {
      return false;
    }
  }

  function isValidCategoryId(categoryId) {
    try {
      var id = cleanString(categoryId);

      if (id === SPECIAL_DOMAIN_ALL) {
        return true;
      }

      var categories = getCategoriesForSelectedDomain();

      for (var i = 0; i < categories.length; i += 1) {
        if (categories[i].id === id) {
          return true;
        }
      }

      return false;
    } catch (err) {
      return false;
    }
  }

  function isValidSubcategoryId(subcategoryId) {
    try {
      var id = cleanString(subcategoryId);

      if (id === SPECIAL_DOMAIN_ALL) {
        return true;
      }

      var subcategories = getSubcategoriesForSelectedCategory();

      for (var i = 0; i < subcategories.length; i += 1) {
        if (subcategories[i].id === id) {
          return true;
        }
      }

      return false;
    } catch (err) {
      return false;
    }
  }

  function makeCategoryKey(domainId, categoryId) {
    return cleanString(domainId) + "::" + cleanString(categoryId);
  }

  function syncRootDataset() {
    try {
      var root = state.elements.root;

      if (!root || !root.dataset) {
        return;
      }

      root.dataset.selectedDomain = state.selectedDomainId;
      root.dataset.selectedCategory = state.selectedCategoryId;
      root.dataset.selectedSubcategory = state.selectedSubcategoryId;
      root.dataset.taxonomyLoaded = state.taxonomy ? "true" : "false";
      root.dataset.taxonomyLoading = state.loading ? "true" : "false";
      root.dataset.taxonomyFilterCards = state.filterCardsEnabled ? "true" : "false";
    } catch (err) {
      // ignore
    }
  }

  function dispatchSelectionChanged(extraDetail) {
    try {
      var detail = {
        domain: state.selectedDomainId,
        category: state.selectedCategoryId,
        subcategory: state.selectedSubcategoryId,
        taxonomyLoaded: Boolean(state.taxonomy),
        taxonomyLocked: isSelectionLocked(),
        module: MODULE_NAME,
        version: MODULE_VERSION,
        source: "unknown"
      };

      if (extraDetail && typeof extraDetail === "object") {
        Object.keys(extraDetail).forEach(function (key) {
          detail[key] = extraDetail[key];
        });
      }

      document.dispatchEvent(
        new CustomEvent(EVENTS.selectionChange, {
          bubbles: true,
          detail: detail
        })
      );
    } catch (err) {
      // CustomEvent can fail in older environments; not relevant for this UI.
    }
  }

  function dispatchReady() {
    try {
      document.dispatchEvent(
        new CustomEvent(EVENTS.ready, {
          bubbles: true,
          detail: getPublicState()
        })
      );
    } catch (err) {
      // ignore
    }
  }

  function dispatchError(err, operation) {
    try {
      document.dispatchEvent(
        new CustomEvent(EVENTS.error, {
          bubbles: true,
          detail: {
            operation: operation || "unknown",
            error: stringifyError(err),
            module: MODULE_NAME,
            version: MODULE_VERSION
          }
        })
      );
    } catch (eventError) {
      // ignore
    }
  }

  function dispatchFilterApplied(detail) {
    try {
      var payload = {
        domain: state.selectedDomainId,
        category: state.selectedCategoryId,
        subcategory: state.selectedSubcategoryId,
        module: MODULE_NAME,
        version: MODULE_VERSION
      };

      if (detail && typeof detail === "object") {
        Object.keys(detail).forEach(function (key) {
          payload[key] = detail[key];
        });
      }

      document.dispatchEvent(
        new CustomEvent(EVENTS.filterApplied, {
          bubbles: true,
          detail: payload
        })
      );
    } catch (err) {
      // ignore
    }
  }

  function setStatus(message, mode) {
    try {
      var statusElement = state.elements.status;

      if (!statusElement) {
        return;
      }

      var cleanedMessage = cleanString(message);
      var cleanedMode = cleanString(mode) || "info";

      statusElement.className = CLASSES.statusBase + " " + CLASSES.statusBase + "--" + cleanedMode;

      if (!cleanedMessage) {
        statusElement.hidden = true;
        statusElement.textContent = "";
        return;
      }

      statusElement.hidden = false;
      statusElement.textContent = cleanedMessage;
    } catch (err) {
      // ignore
    }
  }

  function clearElement(element) {
    try {
      while (element.firstChild) {
        element.removeChild(element.firstChild);
      }
    } catch (err) {
      try {
        element.innerHTML = "";
      } catch (innerError) {
        // ignore
      }
    }
  }

  function setText(element, value) {
    try {
      element.textContent = value == null ? "" : String(value);
    } catch (err) {
      // ignore
    }
  }

  function setFilterCardsEnabled(value) {
    try {
      state.filterCardsEnabled = Boolean(value);
      syncRootDataset();
      return applyCreativeCardFilter();
    } catch (err) {
      state.error = err;
      error("Could not set card filter state.", err);
      return null;
    }
  }

  function asArray(value) {
    return Array.isArray(value) ? value : null;
  }

  function asObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  }

  function getPath(source, path) {
    try {
      var current = source;

      for (var i = 0; i < path.length; i += 1) {
        if (!current || typeof current !== "object") {
          return undefined;
        }

        current = current[path[i]];
      }

      return current;
    } catch (err) {
      return undefined;
    }
  }

  function cleanString(value) {
    try {
      if (value === null || value === undefined) {
        return "";
      }

      return String(value).trim();
    } catch (err) {
      return "";
    }
  }

  function toNumber(value, fallback) {
    try {
      var number = Number(value);

      if (Number.isFinite(number)) {
        return number;
      }

      return fallback;
    } catch (err) {
      return fallback;
    }
  }

  function readBooleanDataset(element, key, fallback) {
    try {
      if (!element || !element.dataset) {
        return fallback;
      }

      if (!(key in element.dataset)) {
        return fallback;
      }

      var value = String(element.dataset[key]).toLowerCase().trim();

      if (value === "1" || value === "true" || value === "yes" || value === "ja" || value === "on") {
        return true;
      }

      if (value === "0" || value === "false" || value === "no" || value === "nein" || value === "off") {
        return false;
      }

      return fallback;
    } catch (err) {
      return fallback;
    }
  }

  function readDatasetValue(element, key) {
    try {
      if (!element || !element.dataset || !(key in element.dataset)) {
        return "";
      }

      return element.dataset[key];
    } catch (err) {
      return "";
    }
  }

  function sortByOrderThenLabel(left, right) {
    var orderDiff = toNumber(left.sortOrder, 9999) - toNumber(right.sortOrder, 9999);

    if (orderDiff !== 0) {
      return orderDiff;
    }

    return String(left.label || left.id || "").localeCompare(String(right.label || right.id || ""), "de");
  }

  function toArray(value) {
    try {
      return Array.prototype.slice.call(value || []);
    } catch (err) {
      return [];
    }
  }

  function tryPreventDefault(event) {
    try {
      if (event && typeof event.preventDefault === "function") {
        event.preventDefault();
      }
    } catch (err) {
      // ignore
    }
  }

  function tryStopPropagation(event) {
    try {
      if (event && typeof event.stopPropagation === "function") {
        event.stopPropagation();
      }
    } catch (err) {
      // ignore
    }

    try {
      if (event && typeof event.stopImmediatePropagation === "function") {
        event.stopImmediatePropagation();
      }
    } catch (err) {
      // ignore
    }
  }

  function extractMessage(payload) {
    try {
      var raw = payload || {};
      var errors = raw.errors;

      if (Array.isArray(errors) && errors.length) {
        return cleanString(errors[0].message || errors[0].code);
      }

      return cleanString(raw.message || raw.status);
    } catch (err) {
      return "";
    }
  }

  function stringifyError(err) {
    try {
      if (!err) {
        return "";
      }

      return String(err.message || err);
    } catch (stringifyFailure) {
      return "Unknown error";
    }
  }

  function warn(message, extra) {
    try {
      if (window.console && typeof window.console.warn === "function") {
        window.console.warn("[" + MODULE_NAME + "] " + message, extra || "");
      }
    } catch (err) {
      // ignore
    }
  }

  function error(message, err) {
    try {
      if (window.console && typeof window.console.error === "function") {
        window.console.error("[" + MODULE_NAME + "] " + message, err || "");
      }
    } catch (consoleError) {
      // ignore
    }
  }

  function getPublicState() {
    return {
      initialized: state.initialized,
      loading: state.loading,
      error: state.error ? stringifyError(state.error) : null,
      selectedDomainId: state.selectedDomainId,
      selectedCategoryId: state.selectedCategoryId,
      selectedSubcategoryId: state.selectedSubcategoryId,
      taxonomyUrl: state.taxonomyUrl,
      hasTaxonomy: Boolean(state.taxonomy),
      taxonomyLocked: isSelectionLocked(),
      includeWorldEdit: state.includeWorldEdit,
      filterCardsEnabled: state.filterCardsEnabled,
      lockAware: state.lockAware,
      domains: getDomains(),
      cards: {
        total: state.elements.creativeCards.length,
        lastFilterAppliedAt: state.lastFilterAppliedAt
      },
      lastRenderedAt: state.lastRenderedAt,
      lastBlockedSelection: state.lastBlockedSelection,
      module: MODULE_NAME,
      version: MODULE_VERSION
    };
  }

  function forceReload() {
    clearCaches();

    state.taxonomy = null;
    state.error = null;
    state.loading = false;

    setStatus("Taxonomie wird neu geladen ...", "loading");

    return loadTaxonomy().then(function (taxonomy) {
      state.taxonomy = taxonomy;
      state.loading = false;
      state.error = null;

      normalizeInitialSelection();
      renderAll();
      applyCreativeCardFilter();
      setStatus("", "ready");
      dispatchSelectionChanged({ source: "force-reload" });

      return getPublicState();
    }).catch(function (err) {
      state.loading = false;
      state.error = err;
      setStatus("Taxonomie konnte nicht neu geladen werden.", "error");
      error("Force reload failed.", err);
      dispatchError(err, "force-reload");
      return getPublicState();
    });
  }

  window[MODULE_NAME] = {
    init: init,
    forceReload: forceReload,
    clearCaches: clearCaches,
    getState: getPublicState,
    selectDomain: selectDomain,
    selectCategory: selectCategory,
    selectSubcategory: selectSubcategory,
    applyCreativeCardFilter: applyCreativeCardFilter,
    setFilterCardsEnabled: setFilterCardsEnabled,
    refreshElements: refreshElements
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();