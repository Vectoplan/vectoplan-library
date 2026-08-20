(function () {
  "use strict";

  var VERSION = "1.0.0";

  function parse(value, fallback) {
    try {
      var decoded = JSON.parse(String(value || ""));
      return decoded !== null ? decoded : fallback;
    } catch (error) {
      return fallback;
    }
  }

  function number(value, fallback, minimum) {
    var parsed = Number(String(value === undefined ? "" : value).replace(",", "."));
    if (!Number.isFinite(parsed)) {
      parsed = fallback;
    }
    return Math.max(minimum === undefined ? -Infinity : minimum, parsed);
  }

  function boot() {
    var root = document.querySelector("[data-vp-pricing-root]");
    if (!root || root.getAttribute("data-vp-pricing-ready") === "true") {
      return;
    }
    var form = root.closest("form");
    var list = root.querySelector("[data-vp-pricing-list]");
    var empty = root.querySelector("[data-vp-pricing-empty]");
    var summary = root.querySelector("[data-vp-pricing-summary]");
    var contractField = root.querySelector("[data-vp-pricing-contract-json]");
    var variantsField = form && form.querySelector('[name="definition_variants_json"]');
    var template = document.querySelector("template[data-vp-pricing-rule-template]");
    var existing = parse(contractField && contractField.value, {});
    var rulesByVariant = {};
    var variantSignature = "";

    (Array.isArray(existing.rules) ? existing.rules : []).forEach(function (rule) {
      if (rule && rule.variant_id) {
        rulesByVariant[String(rule.variant_id)] = rule;
      }
    });

    function variants() {
      var items = parse(variantsField && variantsField.value, []);
      return Array.isArray(items) ? items : [];
    }

    function identity(variant, index) {
      return {
        id: String(variant.variant_id || variant.variantId || variant.id || ("variant_" + (index + 1))),
        label: String(variant.label || variant.name || variant.title || variant.variant_id || ("Variante " + (index + 1)))
      };
    }

    function set(row, key, value) {
      var field = row.querySelector('[data-vp-pricing-field="' + key + '"]');
      if (field && value !== undefined && value !== null) {
        field.value = String(value);
      }
    }

    function value(row, key, fallback) {
      var field = row.querySelector('[data-vp-pricing-field="' + key + '"]');
      return field && String(field.value || "").trim() ? String(field.value).trim() : fallback;
    }

    function readRule(row) {
      var id = row.getAttribute("data-vp-pricing-variant-id") || "";
      var label = row.querySelector("[data-vp-pricing-variant-label]");
      var amount = number(value(row, "price_amount", "0"), 0, 0);
      var outputQuantity = number(value(row, "output_quantity", "0"), 0, 0);
      var outputUnit = value(row, "output_unit", "Stück");
      return {
        variant_id: id,
        variant_label: label ? label.textContent.trim() : id,
        pricing_basis: value(row, "pricing_basis", "per_m2"),
        billing_quantity: number(value(row, "billing_quantity", "1"), 1, 0.000001),
        price: {
          amount: amount,
          currency: "EUR",
          vat_percent: number(value(row, "vat_percent", "19"), 19, 0),
          includes_vat: false
        },
        output: {
          quantity: outputQuantity,
          unit: outputUnit
        },
        minimum_order: number(value(row, "minimum_order", "0"), 0, 0),
        notes: value(row, "notes", ""),
        status: amount > 0 && outputQuantity > 0 && outputUnit ? "complete" : "incomplete"
      };
    }

    function basisLabel(value) {
      return ({
        per_m2: "m²",
        per_m3: "m³",
        per_meter: "lfm",
        per_piece: "Stück",
        per_package: "Verpackung",
        fixed: "Pauschale"
      })[value] || value;
    }

    function sync(reason) {
      var rows = Array.prototype.slice.call(list.querySelectorAll("[data-vp-pricing-rule]"));
      var rules = rows.map(readRule);
      var complete = 0;
      rules.forEach(function (rule, index) {
        rulesByVariant[rule.variant_id] = rule;
        if (rule.status === "complete") {
          complete += 1;
        }
        var row = rows[index];
        var status = row.querySelector("[data-vp-pricing-rule-status]");
        var result = row.querySelector("[data-vp-pricing-rule-result]");
        row.setAttribute("data-vp-pricing-rule-state", rule.status);
        if (status) {
          status.textContent = rule.status === "complete" ? "Vollständig" : "Preis ergänzen";
        }
        if (result) {
          result.textContent = rule.billing_quantity + " " + basisLabel(rule.pricing_basis) + " = " +
            rule.price.amount.toFixed(2).replace(".", ",") + " EUR → " +
            rule.output.quantity + " " + rule.output.unit;
        }
      });
      var contract = {
        schema_version: "vplib.pricing.v1",
        currency: "EUR",
        enforced: true,
        rule_count: rules.length,
        complete_rule_count: complete,
        incomplete_variant_ids: rules.filter(function (rule) { return rule.status !== "complete"; }).map(function (rule) { return rule.variant_id; }),
        rules: rules
      };
      if (contractField) {
        contractField.value = JSON.stringify(contract);
      }
      if (summary) {
        summary.textContent = complete + " von " + rules.length + " Preisen vollständig";
      }
      root.dispatchEvent(new CustomEvent("vectoplan:create:pricing-changed", {
        bubbles: true,
        detail: { version: VERSION, reason: reason || "change", pricing_contract: contract }
      }));
    }

    function render() {
      var items = variants();
      var nextSignature = JSON.stringify(items.map(identity));
      if (nextSignature === variantSignature) {
        return;
      }
      Array.prototype.slice.call(list.querySelectorAll("[data-vp-pricing-rule]")).forEach(function (row) {
        var rule = readRule(row);
        rulesByVariant[rule.variant_id] = rule;
      });
      variantSignature = nextSignature;
      list.innerHTML = "";
      items.forEach(function (variant, index) {
        var meta = identity(variant, index);
        var rule = rulesByVariant[meta.id] || {};
        var fragment = template.content.cloneNode(true);
        var row = fragment.querySelector("[data-vp-pricing-rule]");
        row.setAttribute("data-vp-pricing-variant-id", meta.id);
        row.querySelector("[data-vp-pricing-variant-label]").textContent = meta.label;
        set(row, "pricing_basis", rule.pricing_basis || "per_m2");
        set(row, "billing_quantity", rule.billing_quantity === undefined ? 1 : rule.billing_quantity);
        set(row, "price_amount", rule.price && rule.price.amount);
        set(row, "vat_percent", rule.price && rule.price.vat_percent !== undefined ? rule.price.vat_percent : 19);
        set(row, "output_quantity", rule.output && rule.output.quantity);
        set(row, "output_unit", rule.output && rule.output.unit || "Stück");
        set(row, "minimum_order", rule.minimum_order || 0);
        set(row, "notes", rule.notes || "");
        list.appendChild(fragment);
      });
      if (empty) {
        empty.hidden = items.length > 0;
      }
      sync("variants-rendered");
    }

    root.addEventListener("input", function () { sync("input"); });
    root.addEventListener("change", function () { sync("change"); });
    [
      "vectoplan:create:variants-changed",
      "vectoplan:create:variant-state-changed",
      "vectoplan:create:variant-saved",
      "vectoplan:create:payload-changed"
    ].forEach(function (eventName) {
      document.addEventListener(eventName, render);
    });
    if (form) {
      form.addEventListener("submit", function () { render(); sync("submit"); }, true);
    }
    window.setInterval(render, 1200);
    render();
    root.setAttribute("data-vp-pricing-ready", "true");
    root.setAttribute("data-vp-pricing-version", VERSION);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
