/* services/vectoplan-library/static/js/vplib/create/create_wizard.js */
(function () {
  "use strict";

  var GLOBAL_NAME = "VectoplanCreateWizard";
  var MODULE_NAME = "wizard";
  var WIZARD_VERSION = "0.7.0";
  var CORE_NAME = "VectoplanCreateCore";
  var BOOT_RETRY_MS = 40;
  var BOOT_MAX_ATTEMPTS = 80;
  var NAVIGATION_LOCK_MS = 180;

  var SELECTORS = {
    app: "[data-vp-create-app]",
    form: "[data-vp-create-form], [data-create-form='true'], #vp-create-form, form[data-create-form]",
    stepsRoot: "[data-vp-create-steps]",
    step: "[data-vp-create-step]",
    stepSection: "[data-vp-create-section], [data-create-section], [data-vp-step-panel]",
    stepper: "[data-vp-create-stepper]",
    stepperButton: "[data-vp-step-button], [data-vp-step-target], [data-step-target], [data-step]",
    stepperItem: "[data-vp-step-item]",
    stepperProgressFill: "[data-vp-step-progress-fill]",
    stepperCurrentLabel: "[data-vp-current-step-label]",
    stepperTotalLabel: "[data-vp-total-step-label]",
    stepperLiveRegion: "[data-vp-step-live-region]",

    wizardNav: "[data-vp-wizard-nav], [data-create-wizard-nav='true']",
    wizardPrev: [
      "[data-vp-wizard-prev]",
      "[data-vp-wizard-prev='true']",
      "[data-vp-wizard-previous='true']",
      "[data-create-wizard-prev='true']",
      "[data-create-wizard-previous='true']",
      "[data-create-prev='true']",
      "[data-create-back='true']",
      "[data-vp-prev-step='true']",
      "[data-vp-step-prev='true']",
      "[data-vp-wizard-action='previous']",
      "[data-vp-wizard-action='prev']",
      "[data-vp-wizard-action='back']",
      "[data-create-wizard-action='previous']",
      "[data-create-wizard-action='prev']",
      "[data-create-wizard-action='back']",
      "[data-action='previous']",
      "[data-action='prev']",
      "[data-action='back']",
      "button[name='previous']",
      "button[name='prev']",
      "button[value='previous']",
      "button[value='prev']"
    ].join(","),

    wizardNext: [
      "[data-vp-wizard-next]",
      "[data-vp-wizard-next='true']",
      "[data-create-wizard-next='true']",
      "[data-create-next='true']",
      "[data-create-next-step='true']",
      "[data-vp-next-step='true']",
      "[data-vp-step-next='true']",
      "[data-vp-submit-next='true']",
      "[data-vp-wizard-action='next']",
      "[data-create-wizard-action='next']",
      "[data-action='next']",
      "button[name='next']",
      "button[value='next']"
    ].join(","),

    wizardNextLabel: "[data-vp-wizard-next-label]",
    wizardPrevLabel: "[data-vp-wizard-prev-label]",
    wizardProgressText: "[data-vp-wizard-progress-text], [data-create-wizard-progress-text='true']",
    wizardStepLabel: "[data-vp-wizard-step-label], [data-create-wizard-step-label='true']",
    wizardHint: "[data-vp-wizard-hint], [data-create-wizard-hint='true']",

    variantDrawerOpen: [
      "[data-vp-variant-drawer][aria-hidden='false']",
      "[data-vp-variant-drawer-root][aria-hidden='false']",
      "[data-vp-variant-drawer-state='open']",
      "[data-vp-variant-editor-state='open']",
      ".vp-create-variant-drawer.is-open",
      "[role='dialog'][aria-modal='true']"
    ].join(","),

    requiredField: "input[required], select[required], textarea[required], [data-create-required='true']"
  };

  var DEFAULT_STEPS = [
    {
      index: 1,
      key: "identity",
      label: "Grunddaten",
      short_label: "Daten",
      shortLabel: "Daten",
      hint: "Name und Beschreibung des neuen Library-Bausteins festlegen.",
      target: "identity"
    },
    {
      index: 2,
      key: "taxonomy",
      label: "Taxonomie",
      short_label: "Taxonomie",
      shortLabel: "Taxonomie",
      hint: "Fachliche Einordnung für Library, Scanner und spätere Navigation auswählen.",
      target: "taxonomy"
    },
    {
      index: 3,
      key: "variables",
      alias: "object",
      aliases: ["object", "object-variants", "variables"],
      label: "Variablen",
      short_label: "Variablen",
      shortLabel: "Variablen",
      hint: "Variablen, Varianten und Unterlagen definieren.",
      target: "object-variants"
    },
    {
      index: 4,
      key: "geometry",
      label: "Geometrie",
      short_label: "Geometrie",
      shortLabel: "Geometrie",
      hint: "Primitive Form, reale Maße, Editor-Raster und optionales 3D-Modell definieren.",
      target: "geometry"
    },
    {
      index: 5,
      key: "technical",
      label: "Technik",
      short_label: "Technik",
      shortLabel: "Technik",
      hint: "Materialklasse, technische Kennwerte und optionale Unterlagen ergänzen.",
      target: "technical"
    },
    {
      index: 6,
      key: "actions",
      alias: "create",
      aliases: ["create", "actions"],
      label: "Erzeugen",
      short_label: "Erzeugen",
      shortLabel: "Erzeugen",
      hint: "Draft, Validierung, Package-Plan, Download oder Speichern ausführen.",
      target: "actions"
    }
  ];

  var core = null;
  var initialized = false;
  var eventsBound = false;
  var navLockUntil = 0;

  var state = {
    version: WIZARD_VERSION,
    initialized: false,
    currentStep: 1,
    stepCount: 6,
    maxReachedStep: 1,
    steps: DEFAULT_STEPS.slice(),
    lastNavigation: null,
    lastValidation: null,
    navigationCount: 0,
    blockedCount: 0,
    clickCaptureEnabled: true,
    keyboardNavigationEnabled: true,
    submitNavigatesNext: true,
    directStepClickEnabled: true,
    preventSkipForward: true,
    generatorContextReady: false,
    definitionsReady: false
  };

  function boot(attempt) {
    try {
      var safeAttempt = typeof attempt === "number" ? attempt : 0;
      var maybeCore = window[CORE_NAME];

      if (!maybeCore || !maybeCore.state) {
        if (safeAttempt < BOOT_MAX_ATTEMPTS) {
          window.setTimeout(function () {
            boot(safeAttempt + 1);
          }, BOOT_RETRY_MS);
          return;
        }

        initialize(null);
        return;
      }

      initialize(maybeCore);
    } catch (error) {
      warn("Wizard boot failed.", error);
    }
  }

  function initialize(coreRuntime) {
    try {
      if (initialized) {
        return api;
      }

      core = coreRuntime || window[CORE_NAME] || null;

      resolveInitialState();
      normalizeButtons();
      bindEvents();
      updateWizardUi(state.currentStep, {
        source: "initialize",
        focus: false,
        announce: false
      });

      initialized = true;
      state.initialized = true;

      if (core && typeof core.registerModule === "function") {
        core.registerModule(MODULE_NAME, api);
      }

      setRootAttr("data-vp-create-wizard-ready", "true");
      setRootAttr("data-vp-create-wizard-version", WIZARD_VERSION);

      dispatchDocument("vectoplan:create:wizard-ready", getState());

      return api;
    } catch (error) {
      warn("Wizard initialization failed.", error);
      return api;
    }
  }

  function resolveInitialState() {
    try {
      if (core && typeof core.refreshContext === "function") {
        core.refreshContext();
      }

      var stepsRoot = qs(SELECTORS.stepsRoot);
      var nav = qs(SELECTORS.wizardNav);
      var app = qs(SELECTORS.app);
      var form = qs(SELECTORS.form);

      var coreState = core && core.state ? core.state : {};
      var coreSteps = Array.isArray(coreState.steps) && coreState.steps.length
        ? coreState.steps
        : null;

      var stepCount =
        toInt(attr(stepsRoot, "data-vp-step-count", "")) ||
        toInt(attr(nav, "data-vp-step-count", "")) ||
        toInt(attr(app, "data-vp-step-count", "")) ||
        toInt(attr(form, "data-vp-step-count", "")) ||
        coreState.stepCount ||
        DEFAULT_STEPS.length;

      var currentStep =
        toInt(attr(stepsRoot, "data-vp-current-step", "")) ||
        toInt(attr(nav, "data-vp-current-step", "")) ||
        toInt(attr(app, "data-vp-current-step", "")) ||
        toInt(attr(form, "data-vp-current-step", "")) ||
        coreState.currentStep ||
        1;

      if (coreSteps) {
        state.steps = coreSteps.map(normalizeStep).filter(Boolean);
      } else {
        state.steps = DEFAULT_STEPS.map(normalizeStep).filter(Boolean);
      }

      if (!state.steps.length) {
        state.steps = DEFAULT_STEPS.slice();
      }

      state.stepCount = stepCount || state.steps.length || DEFAULT_STEPS.length;
      state.currentStep = clampStep(currentStep);
      state.maxReachedStep = Math.max(state.maxReachedStep || 1, state.currentStep);

      state.directStepClickEnabled = readWizardBoolean("allowDirectStepClick", true);
      state.preventSkipForward = readWizardBoolean("preventSkipForward", true);
      state.generatorContextReady = !!(coreState.generatorContext && Object.keys(coreState.generatorContext).length);
      state.definitionsReady = readDefinitionsReady(coreState);

      if (core && core.state) {
        core.state.steps = state.steps.slice();
        core.state.currentStep = state.currentStep;
        core.state.stepCount = state.stepCount;
        core.state.maxReachedStep = state.maxReachedStep;
      }
    } catch (error) {
      state.currentStep = 1;
      state.stepCount = DEFAULT_STEPS.length;
      state.maxReachedStep = 1;
      state.steps = DEFAULT_STEPS.slice();
    }
  }

  function readWizardBoolean(name, fallback) {
    try {
      var coreState = core && core.state ? core.state : {};
      var context = coreState.context || {};
      var wizard = coreState.wizard || context.wizard || {};
      var snakeName = String(name || "").replace(/[A-Z]/g, function (letter) {
        return "_" + letter.toLowerCase();
      });

      if (Object.prototype.hasOwnProperty.call(wizard, name)) {
        return toBoolean(wizard[name], fallback);
      }

      if (Object.prototype.hasOwnProperty.call(wizard, snakeName)) {
        return toBoolean(wizard[snakeName], fallback);
      }

      return !!fallback;
    } catch (error) {
      return !!fallback;
    }
  }

  function readDefinitionsReady(coreState) {
    try {
      var definitions = coreState && coreState.definitions ? coreState.definitions : {};

      if (definitions.ready === true || definitions.ok === true) {
        return true;
      }

      var counts = definitions.counts || {};

      return !!(
        counts.object_kinds ||
        counts.objectKinds ||
        counts.variant_profiles ||
        counts.variantProfiles
      );
    } catch (error) {
      return false;
    }
  }

  function bindEvents() {
    try {
      if (eventsBound) {
        return;
      }

      eventsBound = true;

      document.addEventListener("click", handleClickCapture, true);
      document.addEventListener("submit", handleSubmitCapture, true);
      document.addEventListener("keydown", handleKeydown, true);

      document.addEventListener("vectoplan:create:step-request", function (event) {
        try {
          var detail = event && event.detail ? event.detail : {};

          if (event && typeof event.preventDefault === "function") {
            event.preventDefault();
          }

          if (detail.direction === "next" || detail.action === "next") {
            nextStep({
              source: detail.source || "step-request",
              validate: detail.validate !== false,
              focus: detail.focus !== false,
              force: detail.force === true
            });
            return;
          }

          if (
            detail.direction === "previous" ||
            detail.direction === "prev" ||
            detail.direction === "back" ||
            detail.action === "previous" ||
            detail.action === "prev" ||
            detail.action === "back"
          ) {
            previousStep({
              source: detail.source || "step-request",
              focus: detail.focus !== false,
              force: detail.force === true
            });
            return;
          }

          var target = detail.targetStep || detail.step || detail.currentStep;

          if (target) {
            goToStep(target, {
              source: detail.source || "step-request",
              validate: detail.validate === true,
              focus: detail.focus !== false,
              force: detail.force === true
            });
          }
        } catch (error) {
          warn("Step request failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:next-step", function (event) {
        try {
          if (event && typeof event.preventDefault === "function") {
            event.preventDefault();
          }

          nextStep({
            source: "event:next-step",
            validate: true,
            focus: true
          });
        } catch (error) {
          warn("Next-step event failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:previous-step", function (event) {
        try {
          if (event && typeof event.preventDefault === "function") {
            event.preventDefault();
          }

          previousStep({
            source: "event:previous-step",
            focus: true
          });
        } catch (error) {
          warn("Previous-step event failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:core-context-refreshed", function () {
        try {
          syncFromCore();
        } catch (error) {
          warn("Core context refresh sync failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:definitions-ready", function () {
        try {
          state.definitionsReady = true;
          updateWizardUi(state.currentStep, {
            source: "definitions-ready",
            focus: false,
            announce: false
          });
        } catch (error) {
          warn("Definitions-ready wizard sync failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:stepper-ready", function () {
        try {
          updateWizardUi(state.currentStep, {
            source: "stepper-ready",
            focus: false,
            announce: false
          });
        } catch (error) {
          warn("Stepper ready sync failed.", error);
        }
      });

      document.addEventListener("vectoplan:create:wizard-nav-ready", function () {
        try {
          updateWizardUi(state.currentStep, {
            source: "wizard-nav-ready",
            focus: false,
            announce: false
          });
        } catch (error) {
          warn("Wizard nav ready sync failed.", error);
        }
      });
    } catch (error) {
      warn("Wizard event binding failed.", error);
    }
  }

  function handleClickCapture(event) {
    try {
      if (!state.clickCaptureEnabled || !event || !event.target) {
        return;
      }

      var target = event.target;
      var nextButton = closest(target, SELECTORS.wizardNext);
      var prevButton = closest(target, SELECTORS.wizardPrev);
      var stepButton = closest(target, SELECTORS.stepperButton);

      if (!nextButton && !prevButton && !stepButton) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();

      if (typeof event.stopImmediatePropagation === "function") {
        event.stopImmediatePropagation();
      }

      if (nextButton && !isDisabled(nextButton)) {
        nextStep({
          source: "wizard-next-click",
          validate: true,
          focus: true
        });
        return;
      }

      if (prevButton && !isDisabled(prevButton)) {
        previousStep({
          source: "wizard-prev-click",
          focus: true
        });
        return;
      }

      if (stepButton && !isDisabled(stepButton)) {
        if (!state.directStepClickEnabled) {
          blockNavigation("stepper-disabled", state.currentStep, resolveStepTarget(stepButton), "stepper-click");
          return;
        }

        var targetStep = resolveStepTarget(stepButton);

        if (targetStep) {
          goToStep(targetStep, {
            source: "stepper-click",
            validate: targetStep > state.currentStep,
            focus: true
          });
        }
      }
    } catch (error) {
      warn("Wizard click capture failed.", error);
    }
  }

  function handleSubmitCapture(event) {
    try {
      if (!event || !event.target || !matches(event.target, SELECTORS.form)) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();

      if (typeof event.stopImmediatePropagation === "function") {
        event.stopImmediatePropagation();
      }

      if (!state.submitNavigatesNext) {
        return;
      }

      var submitter = event.submitter || qs("button[type='submit'], input[type='submit']", event.target);

      if (submitter && matches(submitter, SELECTORS.wizardPrev)) {
        previousStep({
          source: "form-submit-prev",
          focus: true
        });
        return;
      }

      if (state.currentStep >= state.stepCount) {
        dispatchDocument("vectoplan:create:final-submit-requested", {
          currentStep: state.currentStep,
          stepCount: state.stepCount,
          source: "form-submit-final"
        });
        return;
      }

      nextStep({
        source: "form-submit-next",
        validate: true,
        focus: true
      });
    } catch (error) {
      warn("Wizard submit handling failed.", error);
    }
  }

  function handleKeydown(event) {
    try {
      if (!state.keyboardNavigationEnabled || !event) {
        return;
      }

      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return;
      }

      if (isInteractive(event.target) || isDrawerOpen()) {
        return;
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        previousStep({
          source: "keyboard-left",
          focus: true
        });
        return;
      }

      if (event.key === "ArrowRight") {
        event.preventDefault();
        nextStep({
          source: "keyboard-right",
          validate: false,
          focus: true
        });
      }
    } catch (error) {
      warn("Wizard keyboard handling failed.", error);
    }
  }

  function goToStep(targetStep, options) {
    try {
      var config = options || {};
      var target = clampStep(targetStep);
      var current = clampStep(state.currentStep);
      var source = config.source || "goToStep";

      if (!target) {
        blockNavigation("invalid-target", current, target, source);
        return current;
      }

      if (target === current) {
        updateWizardUi(target, config);
        traceNavigation(current, target, source, "same-step");
        return target;
      }

      if (!config.force && Date.now() < navLockUntil) {
        blockNavigation("navigation-lock", current, target, source);
        return current;
      }

      if (!config.force && state.preventSkipForward && target > current + 1) {
        blockNavigation("skip-forward-blocked", current, target, source);
        return current;
      }

      navLockUntil = Date.now() + NAVIGATION_LOCK_MS;

      if (target > current && config.validate !== false) {
        var valid = validateCurrentStep(current, {
          source: source,
          focusInvalid: true
        });

        if (!valid) {
          blockNavigation("validation-failed", current, target, source);
          return current;
        }
      }

      var beforeEvent = dispatchDocument("vectoplan:create:before-step-change", {
        currentStep: current,
        previousStep: current,
        nextStep: target,
        step: target,
        source: source
      }, {
        cancelable: true
      });

      if (beforeEvent && beforeEvent.defaultPrevented) {
        blockNavigation("before-event-cancelled", current, target, source);
        return current;
      }

      state.currentStep = target;
      state.maxReachedStep = Math.max(state.maxReachedStep, target);
      state.navigationCount += 1;

      if (core && core.state) {
        core.state.currentStep = target;
        core.state.stepCount = state.stepCount;
        core.state.maxReachedStep = state.maxReachedStep;
      }

      updateWizardUi(target, config);
      traceNavigation(current, target, source, "changed");

      dispatchDocument("vectoplan:create:step-changed", {
        currentStep: target,
        previousStep: current,
        step: target,
        source: source,
        stepCount: state.stepCount,
        maxReachedStep: state.maxReachedStep,
        stepMeta: getStepMeta(target)
      });

      dispatchDocument("vectoplan:create:wizard-step-changed", {
        currentStep: target,
        previousStep: current,
        step: target,
        source: source,
        stepCount: state.stepCount,
        maxReachedStep: state.maxReachedStep,
        stepMeta: getStepMeta(target)
      });

      return target;
    } catch (error) {
      warn("goToStep failed.", error);
      return state.currentStep || 1;
    }
  }

  function nextStep(options) {
    return goToStep((state.currentStep || 1) + 1, Object.assign({
      source: "next",
      validate: true,
      focus: true
    }, options || {}));
  }

  function previousStep(options) {
    return goToStep((state.currentStep || 1) - 1, Object.assign({
      source: "previous",
      validate: false,
      focus: true
    }, options || {}));
  }

  function updateWizardUi(stepIndex, options) {
    try {
      var config = options || {};
      var step = clampStep(stepIndex);
      var meta = getStepMeta(step);

      updateRootAttributes(step);
      updatePanels(step);
      updateStepper(step, meta);
      updateNav(step, meta);

      setRootAttr("data-vp-create-current-step", String(step));
      setRootAttr("data-vp-create-current-step-key", meta.key || "");
      setRootAttr("data-vp-create-current-step-target", meta.target || "");

      if (config.focus) {
        focusStep(step);
      }

      if (config.announce !== false) {
        announceStep(step, meta);
      }

      dispatchDocument("vectoplan:create:wizard-ui-updated", {
        currentStep: step,
        step: step,
        stepMeta: meta,
        source: config.source || "update-ui"
      });
    } catch (error) {
      warn("Wizard UI update failed.", error);
    }
  }

  function updateRootAttributes(step) {
    try {
      var meta = getStepMeta(step);

      [qs(SELECTORS.app), qs(SELECTORS.form), qs(SELECTORS.stepsRoot)].forEach(function (node) {
        if (!node) {
          return;
        }

        node.setAttribute("data-vp-current-step", String(step));
        node.setAttribute("data-vp-step-count", String(state.stepCount));
        node.setAttribute("data-vp-current-step-key", meta.key || "");
        node.setAttribute("data-vp-current-step-target", meta.target || "");
        node.setAttribute("data-vp-current-step-label", meta.label || "");
      });
    } catch (error) {
      /* no-op */
    }
  }

  function updatePanels(step) {
    try {
      var panels = qsa(SELECTORS.step);

      panels.forEach(function (panel) {
        var panelStep = resolvePanelStep(panel);
        var active = panelStep === step;

        panel.classList.toggle("is-active", active);
        panel.classList.toggle("is-hidden", !active);
        panel.hidden = !active;
        panel.setAttribute("aria-hidden", active ? "false" : "true");

        if (active) {
          panel.removeAttribute("inert");
          panel.setAttribute("data-vp-step-active", "true");
        } else {
          panel.setAttribute("data-vp-step-active", "false");

          try {
            panel.setAttribute("inert", "");
          } catch (error) {
            /* no-op */
          }
        }
      });

      if (!panels.length) {
        updateSectionFallback(step);
      }
    } catch (error) {
      warn("Panel update failed.", error);
    }
  }

  function updateSectionFallback(step) {
    try {
      var meta = getStepMeta(step);
      var target = meta.target || meta.key || "";
      var sections = qsa(SELECTORS.stepSection);

      sections.forEach(function (section) {
        try {
          var sectionKey = attr(section, "data-vp-create-section", "") ||
            attr(section, "data-create-section", "") ||
            attr(section, "data-vp-step-panel", "");
          var alias = attr(section, "data-vp-create-section-alias", "");
          var active = sectionKey === target ||
            alias === target ||
            (target === "object-variants" && (alias === "variables" || sectionKey === "variables"));

          section.classList.toggle("is-active", active);
          section.classList.toggle("is-hidden", !active);
          section.hidden = !active;
          section.setAttribute("aria-hidden", active ? "false" : "true");

          if (active) {
            section.removeAttribute("inert");
          } else {
            section.setAttribute("inert", "");
          }
        } catch (sectionError) {
          warn("Section fallback update skipped.", sectionError);
        }
      });
    } catch (error) {
      warn("Section fallback update failed.", error);
    }
  }

  function updateStepper(step, meta) {
    try {
      var steppers = qsa(SELECTORS.stepper);

      steppers.forEach(function (stepper) {
        try {
          stepper.setAttribute("data-vp-current-step", String(step));
          stepper.setAttribute("data-vp-step-count", String(state.stepCount));
          stepper.setAttribute("data-vp-max-reached-step", String(state.maxReachedStep));
          stepper.style.setProperty("--vp-create-current-step", String(step));
          stepper.style.setProperty("--vp-create-step-count", String(state.stepCount));

          var currentLabel = qs(SELECTORS.stepperCurrentLabel, stepper);
          var totalLabel = qs(SELECTORS.stepperTotalLabel, stepper);
          var progressFill = qs(SELECTORS.stepperProgressFill, stepper);
          var liveRegion = qs(SELECTORS.stepperLiveRegion, stepper);

          if (currentLabel) {
            currentLabel.textContent = String(step);
          }

          if (totalLabel) {
            totalLabel.textContent = String(state.stepCount);
          }

          if (progressFill) {
            var progress = state.stepCount > 1
              ? ((step - 1) / (state.stepCount - 1)) * 100
              : 100;

            progressFill.style.width = Math.max(0, Math.min(100, progress)) + "%";
          }

          qsa(SELECTORS.stepperButton, stepper).forEach(function (button) {
            updateStepperButton(button, step);
          });

          if (liveRegion) {
            liveRegion.textContent = "Schritt " + step + " von " + state.stepCount + ": " + (meta.label || "Schritt") + ".";
          }
        } catch (stepperError) {
          warn("Single stepper update failed.", stepperError);
        }
      });
    } catch (error) {
      warn("Stepper update failed.", error);
    }
  }

  function updateStepperButton(button, step) {
    try {
      var targetStep = resolveStepTarget(button);
      var item = closest(button, SELECTORS.stepperItem);
      var targetMeta = targetStep ? getStepMeta(targetStep) : {};
      var active = targetStep === step;
      var complete = targetStep > 0 && targetStep < step;
      var locked = isStepLocked(targetStep, step);

      if (item) {
        item.classList.toggle("is-active", active);
        item.classList.toggle("is-complete", complete);
        item.classList.toggle("is-locked", locked);
        item.setAttribute("data-vp-step-state", active ? "active" : complete ? "complete" : locked ? "locked" : "available");
      }

      button.classList.toggle("is-active", active);
      button.classList.toggle("is-complete", complete);
      button.classList.toggle("is-locked", locked);

      if (active) {
        button.setAttribute("aria-current", "step");
      } else {
        button.removeAttribute("aria-current");
      }

      button.setAttribute("aria-disabled", locked ? "true" : "false");
      button.disabled = locked;
      button.setAttribute("data-vp-step-state", active ? "active" : complete ? "complete" : locked ? "locked" : "available");

      if (targetMeta && targetMeta.label) {
        button.setAttribute("aria-label", "Schritt " + targetStep + ": " + targetMeta.label);
      }

      updateVisibleStepperText(button, targetMeta);
    } catch (error) {
      warn("Stepper button update failed.", error);
    }
  }

  function updateVisibleStepperText(button, meta) {
    try {
      if (!button || !meta) {
        return;
      }

      var labelNode = qs("[data-vp-step-label], [data-vp-step-title]", button);
      var shortLabelNode = qs("[data-vp-step-short-label]", button);
      var hintNode = qs("[data-vp-step-hint]", button);

      if (labelNode && meta.label) {
        labelNode.textContent = meta.label;
      }

      if (shortLabelNode && (meta.short_label || meta.shortLabel || meta.label)) {
        shortLabelNode.textContent = meta.short_label || meta.shortLabel || meta.label;
      }

      if (hintNode && meta.hint) {
        hintNode.textContent = meta.hint;
      }
    } catch (error) {
      /* no-op */
    }
  }

  function isStepLocked(targetStep, currentStep) {
    try {
      if (!targetStep || targetStep < 1) {
        return false;
      }

      if (!state.directStepClickEnabled) {
        return true;
      }

      if (targetStep <= currentStep) {
        return false;
      }

      if (state.preventSkipForward && targetStep > currentStep + 1) {
        return true;
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function updateNav(step, meta) {
    try {
      qsa(SELECTORS.wizardNav).forEach(function (nav) {
        try {
          var prevButton = qs(SELECTORS.wizardPrev, nav);
          var nextButton = qs(SELECTORS.wizardNext, nav);
          var nextLabel = qs(SELECTORS.wizardNextLabel, nav);
          var prevLabel = qs(SELECTORS.wizardPrevLabel, nav);
          var progressText = qs(SELECTORS.wizardProgressText, nav);
          var stepLabel = qs(SELECTORS.wizardStepLabel, nav);
          var stepHint = qs(SELECTORS.wizardHint, nav);
          var isFinal = step >= state.stepCount;

          nav.setAttribute("data-vp-current-step", String(step));
          nav.setAttribute("data-vp-step-count", String(state.stepCount));
          nav.setAttribute("data-vp-current-step-key", meta.key || "");
          nav.setAttribute("data-vp-current-step-target", meta.target || "");
          nav.classList.toggle("is-first-step", step <= 1);
          nav.classList.toggle("is-final-step", isFinal);

          if (prevButton) {
            prevButton.disabled = step <= 1;
            prevButton.setAttribute("aria-disabled", step <= 1 ? "true" : "false");
            prevButton.setAttribute("type", "button");
          }

          if (nextButton) {
            nextButton.disabled = isFinal;
            nextButton.setAttribute("aria-disabled", isFinal ? "true" : "false");
            nextButton.setAttribute("type", "button");
          }

          if (prevLabel) {
            prevLabel.textContent = "Zurück";
          }

          if (nextLabel) {
            nextLabel.textContent = isFinal ? "Aktionen ausführen" : "Weiter";
          }

          if (progressText) {
            progressText.textContent = "Schritt " + step + " von " + state.stepCount;
          }

          if (stepLabel) {
            stepLabel.textContent = meta.label || "Schritt " + step;
          }

          if (stepHint) {
            stepHint.textContent = meta.hint || meta.description || "Führe den aktuellen Schritt aus und gehe anschließend weiter.";
          }
        } catch (navError) {
          warn("Single nav update failed.", navError);
        }
      });
    } catch (error) {
      warn("Nav update failed.", error);
    }
  }

  function validateCurrentStep(stepIndex, options) {
    try {
      var config = options || {};
      var panel = findPanel(stepIndex);
      var invalid = [];

      if (!panel) {
        return true;
      }

      clearFieldIssues(panel);

      qsa(SELECTORS.requiredField, panel).forEach(function (field) {
        try {
          if (!field || field.disabled || field.type === "hidden" || isHidden(field)) {
            return;
          }

          var value = typeof field.value !== "undefined" ? String(field.value).trim() : "";

          if (!value) {
            invalid.push(field);
            markInvalid(field);
          }
        } catch (error) {
          /* no-op */
        }
      });

      var valid = invalid.length === 0;

      state.lastValidation = {
        step: stepIndex,
        valid: valid,
        invalidCount: invalid.length,
        timestamp: timestamp()
      };

      dispatchDocument("vectoplan:create:step-validated", {
        step: stepIndex,
        currentStep: stepIndex,
        valid: valid,
        invalidCount: invalid.length,
        source: config.source || "validate"
      });

      if (!valid && config.focusInvalid !== false && invalid[0]) {
        focusField(invalid[0]);
      }

      return valid;
    } catch (error) {
      state.lastValidation = {
        step: stepIndex,
        valid: true,
        reason: "validation-runtime-error-fallback",
        error: String(error && error.message ? error.message : error),
        timestamp: timestamp()
      };

      return true;
    }
  }

  function clearFieldIssues(root) {
    try {
      qsa(".is-invalid, [aria-invalid='true']", root).forEach(function (field) {
        field.classList.remove("is-invalid");
        field.removeAttribute("aria-invalid");
      });

      qsa("[data-create-field-message='true']", root).forEach(function (node) {
        node.remove();
      });
    } catch (error) {
      /* no-op */
    }
  }

  function markInvalid(field) {
    try {
      field.classList.add("is-invalid");
      field.setAttribute("aria-invalid", "true");

      var wrapper = closest(field, ".vp-create-field") || closest(field, "label") || field.parentElement;

      if (!wrapper || qs("[data-create-field-message='true']", wrapper)) {
        return;
      }

      var message = document.createElement("span");
      message.setAttribute("data-create-field-message", "true");
      message.className = "vp-create-field-error";
      message.textContent = "Pflichtfeld prüfen.";
      wrapper.appendChild(message);
    } catch (error) {
      /* no-op */
    }
  }

  function focusField(field) {
    try {
      if (!field || typeof field.focus !== "function") {
        return;
      }

      field.focus({ preventScroll: true });

      try {
        field.scrollIntoView({
          block: "center",
          inline: "nearest",
          behavior: "smooth"
        });
      } catch (error) {
        field.scrollIntoView();
      }
    } catch (error) {
      /* no-op */
    }
  }

  function focusStep(stepIndex) {
    try {
      var panel = findPanel(stepIndex);

      if (!panel) {
        return;
      }

      window.setTimeout(function () {
        var target = qs("input:not([type='hidden']):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex='-1'])", panel);

        if (target && typeof target.focus === "function") {
          target.focus({ preventScroll: true });
        }
      }, 40);
    } catch (error) {
      /* no-op */
    }
  }

  function announceStep(step, meta) {
    try {
      var liveRegion = qs(SELECTORS.stepperLiveRegion);

      if (liveRegion) {
        liveRegion.textContent = "Schritt " + step + " von " + state.stepCount + ": " + (meta.label || "Schritt") + ".";
      }
    } catch (error) {
      /* no-op */
    }
  }

  function normalizeButtons() {
    try {
      qsa(SELECTORS.wizardPrev + ", " + SELECTORS.wizardNext + ", " + SELECTORS.stepperButton).forEach(function (button) {
        if (button && button.tagName && button.tagName.toLowerCase() === "button") {
          button.setAttribute("type", "button");
        }
      });
    } catch (error) {
      /* no-op */
    }
  }

  function findPanel(stepIndex) {
    try {
      var direct = qs('[data-vp-create-step][data-vp-step-index="' + String(stepIndex) + '"]') ||
        qs('[data-vp-create-step][data-step="' + String(stepIndex) + '"]');

      if (direct) {
        return direct;
      }

      var meta = getStepMeta(stepIndex);
      var target = meta.target || meta.key || "";

      if (!target) {
        return null;
      }

      return qs('[data-vp-create-step][data-vp-step-target="' + cssEscape(target) + '"]') ||
        qs('[data-vp-step-panel="' + cssEscape(target) + '"]') ||
        qs('[data-vp-create-section="' + cssEscape(target) + '"]') ||
        qs('[data-create-section="' + cssEscape(target) + '"]') ||
        (target === "object-variants" ? qs("[data-vp-create-section-alias='variables'], [data-vp-create-section='variables'], [data-create-section='variables']") : null);
    } catch (error) {
      return null;
    }
  }

  function resolvePanelStep(panel) {
    try {
      var direct = toInt(attr(panel, "data-vp-step-index", "")) ||
        toInt(attr(panel, "data-step", ""));

      if (direct) {
        return direct;
      }

      var target = attr(panel, "data-vp-step-target", "") ||
        attr(panel, "data-vp-step-panel", "") ||
        attr(panel, "data-vp-create-section", "") ||
        attr(panel, "data-create-section", "");

      if (!target && attr(panel, "data-vp-create-section-alias", "") === "variables") {
        target = "object-variants";
      }

      for (var index = 0; index < state.steps.length; index += 1) {
        if (
          state.steps[index].target === target ||
          state.steps[index].key === target ||
          state.steps[index].alias === target ||
          arrayContains(state.steps[index].aliases, target)
        ) {
          return toInt(state.steps[index].index);
        }
      }

      return 0;
    } catch (error) {
      return 0;
    }
  }

  function resolveStepTarget(button) {
    try {
      var explicit = toInt(attr(button, "data-vp-step-target", "")) ||
        toInt(attr(button, "data-create-step-target", "")) ||
        toInt(attr(button, "data-step-target", "")) ||
        toInt(attr(button, "data-step", ""));

      if (explicit) {
        return explicit;
      }

      var key = attr(button, "data-vp-step-key", "") ||
        attr(button, "data-step-key", "") ||
        attr(button, "data-vp-step-panel", "") ||
        attr(button, "data-vp-step-target-key", "");

      if (!key) {
        return 0;
      }

      for (var index = 0; index < state.steps.length; index += 1) {
        if (
          state.steps[index].key === key ||
          state.steps[index].target === key ||
          state.steps[index].alias === key ||
          arrayContains(state.steps[index].aliases, key)
        ) {
          return toInt(state.steps[index].index);
        }
      }

      return 0;
    } catch (error) {
      return 0;
    }
  }

  function getStepMeta(stepIndex) {
    try {
      var list = state.steps && state.steps.length ? state.steps : DEFAULT_STEPS;
      var parsed = toInt(stepIndex);

      for (var index = 0; index < list.length; index += 1) {
        if (toInt(list[index].index) === parsed) {
          return normalizeStep(list[index], index) || list[index];
        }
      }

      return {
        index: parsed,
        key: "step-" + parsed,
        label: "Schritt " + parsed,
        short_label: String(parsed),
        shortLabel: String(parsed),
        hint: "",
        target: "step-" + parsed
      };
    } catch (error) {
      return {
        index: stepIndex,
        key: "step-" + stepIndex,
        label: "Schritt " + stepIndex,
        short_label: String(stepIndex || ""),
        shortLabel: String(stepIndex || ""),
        hint: "",
        target: "step-" + stepIndex
      };
    }
  }

  function normalizeStep(step, index) {
    try {
      var fallbackIndex = typeof index === "number" ? index + 1 : toInt(step && step.index) || 1;
      var stepIndex = toInt(step && step.index) || fallbackIndex;

      if (!step || typeof step !== "object") {
        return null;
      }

      var key = step.key || "step-" + stepIndex;
      var target = step.target || step.panel || key;
      var alias = step.alias || "";
      var aliases = Array.isArray(step.aliases) ? step.aliases.slice() : [];

      if (stepIndex === 3 && (key === "object" || key === "variables" || target === "object-variants" || target === "variables" || alias === "variables")) {
        return {
          index: 3,
          key: "variables",
          alias: "object",
          aliases: uniqueArray(["object", "object-variants", "variables"].concat(aliases)),
          label: step.label && step.label !== "Objekt" ? step.label : "Variablen",
          short_label: step.short_label && step.short_label !== "Objekt" ? step.short_label : "Variablen",
          shortLabel: step.shortLabel && step.shortLabel !== "Objekt" ? step.shortLabel : "Variablen",
          hint: step.hint || step.description || "Variablen, Varianten und Unterlagen definieren.",
          description: step.description || "",
          target: "object-variants"
        };
      }

      if (stepIndex === 6 && (key === "create" || key === "actions" || target === "actions" || alias === "create")) {
        return {
          index: 6,
          key: "actions",
          alias: "create",
          aliases: uniqueArray(["create", "actions"].concat(aliases)),
          label: step.label || "Erzeugen",
          short_label: step.short_label || step.shortLabel || "Erzeugen",
          shortLabel: step.shortLabel || step.short_label || "Erzeugen",
          hint: step.hint || step.description || "Draft, Validierung, Package-Plan, Download oder Speichern ausführen.",
          description: step.description || "",
          target: "actions"
        };
      }

      return {
        index: stepIndex,
        key: key,
        alias: alias,
        aliases: aliases,
        label: step.label || "Schritt " + stepIndex,
        short_label: step.short_label || step.shortLabel || step.label || String(stepIndex),
        shortLabel: step.shortLabel || step.short_label || step.label || String(stepIndex),
        hint: step.hint || step.description || "",
        description: step.description || "",
        target: target
      };
    } catch (error) {
      return null;
    }
  }

  function clampStep(value) {
    var parsed = toInt(value) || 1;

    if (parsed < 1) {
      return 1;
    }

    if (parsed > state.stepCount) {
      return state.stepCount;
    }

    return parsed;
  }

  function blockNavigation(reason, fromStep, toStep, source) {
    state.blockedCount += 1;

    state.lastNavigation = {
      fromStep: fromStep,
      toStep: toStep,
      source: source || "unknown",
      status: "blocked",
      reason: reason || "blocked",
      timestamp: timestamp()
    };

    dispatchDocument("vectoplan:create:step-change-blocked", state.lastNavigation);
  }

  function traceNavigation(fromStep, toStep, source, status) {
    state.lastNavigation = {
      fromStep: fromStep,
      toStep: toStep,
      source: source || "unknown",
      status: status || "changed",
      timestamp: timestamp()
    };

    if (core && typeof core.traceNavigation === "function") {
      core.traceNavigation(state.lastNavigation);
    }
  }

  function syncFromCore() {
    try {
      if (!core || !core.state) {
        return;
      }

      if (Array.isArray(core.state.steps) && core.state.steps.length) {
        state.steps = core.state.steps.map(normalizeStep).filter(Boolean);
      }

      state.stepCount = core.state.stepCount || state.steps.length || DEFAULT_STEPS.length;
      state.currentStep = clampStep(core.state.currentStep || state.currentStep || 1);
      state.maxReachedStep = Math.max(state.maxReachedStep, core.state.maxReachedStep || state.currentStep);
      state.generatorContextReady = !!(core.state.generatorContext && Object.keys(core.state.generatorContext).length);
      state.definitionsReady = readDefinitionsReady(core.state);

      updateWizardUi(state.currentStep, {
        source: "sync-from-core",
        focus: false,
        announce: false
      });
    } catch (error) {
      warn("Sync from core failed.", error);
    }
  }

  function isDisabled(node) {
    return !!(node && (node.disabled || node.getAttribute("aria-disabled") === "true"));
  }

  function isInteractive(node) {
    try {
      if (!node) {
        return false;
      }

      var element = node.nodeType === 1 ? node : node.parentElement;

      if (!element) {
        return false;
      }

      if (element.isContentEditable) {
        return true;
      }

      return !!closest(element, "input, textarea, select, button, a, [contenteditable='true'], [role='textbox'], [role='combobox'], [role='button']");
    } catch (error) {
      return false;
    }
  }

  function isDrawerOpen() {
    try {
      return !!qs(SELECTORS.variantDrawerOpen);
    } catch (error) {
      return false;
    }
  }

  function isHidden(field) {
    try {
      if (!field) {
        return true;
      }

      if (field.hidden) {
        return true;
      }

      if (field.closest("[hidden], [aria-hidden='true'], [inert]")) {
        return true;
      }

      var style = window.getComputedStyle ? window.getComputedStyle(field) : null;

      if (style && (style.display === "none" || style.visibility === "hidden")) {
        return true;
      }

      return false;
    } catch (error) {
      return false;
    }
  }

  function getState() {
    return {
      version: WIZARD_VERSION,
      initialized: initialized,
      currentStep: state.currentStep,
      stepCount: state.stepCount,
      maxReachedStep: state.maxReachedStep,
      steps: state.steps.slice ? state.steps.slice() : state.steps,
      lastNavigation: state.lastNavigation,
      lastValidation: state.lastValidation,
      navigationCount: state.navigationCount,
      blockedCount: state.blockedCount,
      clickCaptureEnabled: state.clickCaptureEnabled,
      keyboardNavigationEnabled: state.keyboardNavigationEnabled,
      submitNavigatesNext: state.submitNavigatesNext,
      directStepClickEnabled: state.directStepClickEnabled,
      preventSkipForward: state.preventSkipForward,
      generatorContextReady: state.generatorContextReady,
      definitionsReady: state.definitionsReady
    };
  }

  function setKeyboardNavigationEnabled(enabled) {
    state.keyboardNavigationEnabled = !!enabled;
    return state.keyboardNavigationEnabled;
  }

  function setClickCaptureEnabled(enabled) {
    state.clickCaptureEnabled = !!enabled;
    return state.clickCaptureEnabled;
  }

  function setPreventNativeSubmit(enabled) {
    state.submitNavigatesNext = !!enabled;
    return state.submitNavigatesNext;
  }

  function setSubmitNavigatesNext(enabled) {
    state.submitNavigatesNext = !!enabled;
    return state.submitNavigatesNext;
  }

  function setDirectStepClickEnabled(enabled) {
    state.directStepClickEnabled = !!enabled;
    updateWizardUi(state.currentStep, {
      source: "set-direct-step-click",
      focus: false,
      announce: false
    });
    return state.directStepClickEnabled;
  }

  function setPreventSkipForward(enabled) {
    state.preventSkipForward = !!enabled;
    updateWizardUi(state.currentStep, {
      source: "set-prevent-skip-forward",
      focus: false,
      announce: false
    });
    return state.preventSkipForward;
  }

  function update() {
    resolveInitialState();
    normalizeButtons();
    updateWizardUi(state.currentStep, {
      source: "update",
      focus: false,
      announce: false
    });

    return getState();
  }

  function qs(selector, root) {
    try {
      if (!selector) {
        return null;
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

  function matches(node, selector) {
    try {
      return !!(node && node.matches && node.matches(selector));
    } catch (error) {
      return false;
    }
  }

  function attr(node, name, fallback) {
    try {
      if (!node) {
        return fallback || "";
      }

      var value = node.getAttribute(name);
      return value === null || value === undefined ? fallback || "" : value;
    } catch (error) {
      return fallback || "";
    }
  }

  function toInt(value) {
    var parsed = parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function toBoolean(value, fallback) {
    try {
      if (core && typeof core.toBoolean === "function") {
        return core.toBoolean(value, fallback);
      }

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

      return !!fallback;
    } catch (error) {
      return !!fallback;
    }
  }

  function timestamp() {
    try {
      return new Date().toISOString();
    } catch (error) {
      return "";
    }
  }

  function setRootAttr(name, value) {
    try {
      document.documentElement.setAttribute(name, String(value));
    } catch (error) {
      /* no-op */
    }
  }

  function dispatchDocument(eventName, detail, options) {
    try {
      if (core && typeof core.dispatch === "function") {
        return core.dispatch(eventName, detail || {}, options || {});
      }

      var event = new CustomEvent(eventName, {
        bubbles: !(options && options.bubbles === false),
        cancelable: !!(options && options.cancelable),
        detail: detail || {}
      });

      document.dispatchEvent(event);
      return event;
    } catch (error) {
      return null;
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

  function arrayContains(list, value) {
    try {
      return Array.isArray(list) && list.indexOf(value) !== -1;
    } catch (error) {
      return false;
    }
  }

  function uniqueArray(values) {
    try {
      var seen = {};
      var result = [];

      (Array.isArray(values) ? values : []).forEach(function (value) {
        var key = String(value || "").trim();

        if (key && !seen[key]) {
          seen[key] = true;
          result.push(key);
        }
      });

      return result;
    } catch (error) {
      return [];
    }
  }

  function warn(message, error) {
    try {
      if (core && typeof core.warn === "function") {
        core.warn(message, error);
        return;
      }

      if (window.console && typeof window.console.warn === "function") {
        window.console.warn("[VPLIB Create Wizard] " + message, error || "");
      }
    } catch (consoleError) {
      /* no-op */
    }
  }

  var api = {
    version: WIZARD_VERSION,

    initialize: initialize,
    update: update,

    goToStep: goToStep,
    nextStep: nextStep,
    previousStep: previousStep,
    prevStep: previousStep,

    validateCurrentStep: validateCurrentStep,
    updateWizardUi: updateWizardUi,

    setKeyboardNavigationEnabled: setKeyboardNavigationEnabled,
    setClickCaptureEnabled: setClickCaptureEnabled,
    setPreventNativeSubmit: setPreventNativeSubmit,
    setSubmitNavigatesNext: setSubmitNavigatesNext,
    setDirectStepClickEnabled: setDirectStepClickEnabled,
    setPreventSkipForward: setPreventSkipForward,

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