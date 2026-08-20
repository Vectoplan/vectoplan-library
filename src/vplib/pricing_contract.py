"""Normalize per-variant commercial pricing rules for portable VPLIB packages."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


PRICING_SCHEMA_VERSION = "vplib.pricing.v1"
ALLOWED_PRICING_BASES = {
    "per_piece",
    "per_m2",
    "per_m3",
    "per_meter",
    "per_package",
    "fixed",
}
ALLOWED_CURRENCIES = {"EUR", "CHF", "GBP", "USD"}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _text(value: Any, default: str = "", *, maximum: int = 255) -> str:
    return str(value or default).replace("\x00", "").strip()[:maximum]


def _token(value: Any, default: str = "") -> str:
    token = re.sub(r"[^a-z0-9_]+", "_", _text(value).lower()).strip("_")
    return token or default


def _number(value: Any, default: float = 0.0, *, minimum: float = 0.0) -> float:
    try:
        parsed = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "ja"}


def _variant_identity(value: Any, index: int) -> tuple[str, str]:
    source = _mapping(value)
    variant_id = _text(
        source.get("variant_id") or source.get("variantId") or source.get("id"),
        f"variant_{index + 1}",
        maximum=160,
    )
    label = _text(
        source.get("label") or source.get("name") or source.get("title"),
        variant_id,
        maximum=200,
    )
    return variant_id, label


def _normalize_rule(source: Mapping[str, Any], *, variant_id: str, label: str) -> dict[str, Any]:
    price = _mapping(source.get("price"))
    output = _mapping(source.get("output") or source.get("yield"))
    basis = _token(source.get("pricing_basis") or source.get("basis"), "per_m2")
    if basis not in ALLOWED_PRICING_BASES:
        basis = "per_m2"
    currency = _text(price.get("currency") or source.get("currency") or "EUR", maximum=3).upper()
    if currency not in ALLOWED_CURRENCIES:
        currency = "EUR"
    amount = _number(price.get("amount", source.get("price_amount")), 0.0)
    billing_quantity = _number(source.get("billing_quantity"), 1.0, minimum=0.000001)
    output_quantity = _number(output.get("quantity", source.get("output_quantity")), 0.0)
    output_unit = _text(output.get("unit") or source.get("output_unit"), "Stück", maximum=80)
    vat_percent = _number(price.get("vat_percent", source.get("vat_percent")), 19.0)
    status = "complete" if amount > 0 and output_quantity > 0 and output_unit else "incomplete"
    return {
        "variant_id": variant_id,
        "variant_label": label,
        "pricing_basis": basis,
        "billing_quantity": billing_quantity,
        "price": {
            "amount": amount,
            "currency": currency,
            "vat_percent": vat_percent,
            "includes_vat": _bool(price.get("includes_vat", source.get("includes_vat")), False),
        },
        "output": {
            "quantity": output_quantity,
            "unit": output_unit,
        },
        "minimum_order": _number(source.get("minimum_order"), 0.0),
        "notes": _text(source.get("notes"), maximum=1000),
        "status": status,
    }


def normalize_pricing_contract(
    payload: Mapping[str, Any],
    *,
    variants: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return exactly one normalized pricing rule for every definition variant."""
    raw = _mapping(
        payload.get("pricing_contract")
        or payload.get("pricingContract")
        or payload.get("pricing_contract_json")
        or payload.get("pricingContractJson")
    )
    raw_rules = _list(raw.get("rules") or raw.get("variant_prices") or payload.get("variant_prices_json"))
    by_variant = {
        _text(_mapping(item).get("variant_id") or _mapping(item).get("variantId"), maximum=160): _mapping(item)
        for item in raw_rules
        if _mapping(item)
    }
    variant_items = list(variants or [])
    rules: list[dict[str, Any]] = []
    for index, variant in enumerate(variant_items):
        variant_id, label = _variant_identity(variant, index)
        rules.append(_normalize_rule(by_variant.get(variant_id, {}), variant_id=variant_id, label=label))

    # Keep explicitly supplied rules when a legacy payload contains no variant list.
    if not variant_items:
        for index, item in enumerate(raw_rules):
            source = _mapping(item)
            if not source:
                continue
            variant_id, label = _variant_identity(source, index)
            rules.append(_normalize_rule(source, variant_id=variant_id, label=label))

    incomplete = [rule["variant_id"] for rule in rules if rule["status"] != "complete"]
    return {
        "schema_version": PRICING_SCHEMA_VERSION,
        "currency": _text(raw.get("currency") or "EUR", maximum=3).upper(),
        "enforced": _bool(raw.get("enforced"), default=bool(raw_rules)),
        "rule_count": len(rules),
        "complete_rule_count": len(rules) - len(incomplete),
        "incomplete_variant_ids": incomplete,
        "rules": rules,
    }


__all__ = ["PRICING_SCHEMA_VERSION", "normalize_pricing_contract"]
