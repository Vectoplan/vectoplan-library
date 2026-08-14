// static/js/inventar/creative-library.js
(function () {
  "use strict";

  var MODULE_NAME = "VectoplanCreativeLibrary";
  var MODULE_VERSION = "1.6.0";
  var DRAG_MIME = "application/x-vectoplan-vplib-item+json";
  var POINTER_DRAG_START = "vectoplan:creative-pointer-drag-start";
  var POINTER_DRAG_MOVE = "vectoplan:creative-pointer-drag-move";
  var POINTER_DRAG_END = "vectoplan:creative-pointer-drag-end";
  var WORLD_EDIT_SELECTION = "vectoplan:worldedit-inventory-selection";
  var WORLD_EDIT_SETTINGS_CHANGE = "vectoplan:worldedit-settings-change";
  var WORLD_EDIT_ACTION = "vectoplan:worldedit-action";
  var WORLD_EDIT_STATE_SYNC = "vectoplan:worldedit-state";
  var WORLD_EDIT_STATE_REQUEST = "vectoplan:creative-inventory-request-user-inventory-state";
  var POINTER_DRAG_THRESHOLD = 6;
  var REQUEST_TIMEOUT_MS = 12000;
  var AUTO_REFRESH_INTERVAL_MS = 10000;
  var SELECTORS = {
    grid: "[data-creative-library-grid]",
    search: "[data-creative-search]",
    empty: "[data-creative-empty]",
    status: "[data-taxonomy-status]",
    card: "[data-creative-item-card]"
  };

  var state = {
    initialized: false,
    loading: false,
    refreshTimer: 0,
    itemsSignature: "",
    items: [],
    query: "",
    selectedWorldEditToolId: "",
    worldEditSettings: {
      operation: "set",
      shape: "sphere",
      radius: 2,
      density: 100,
      wallThickness: 0,
      parcelMask: true,
      parcelGridMode: "boundary",
      parcelGridSetback: 0,
      parcelGridInfluence: 3
    },
    errors: []
  };

  var WORLD_EDIT_TOOLS = [
    { id: "selection", label: "Selection Tool", icon: "\u2317", group: "basic-tools", ready: true, description: "Quader markieren, an sechs Flaechenpunkten anpassen und als Set, Wand, Fill, Replace oder Clear ausfuehren." },
    { id: "parcel", label: "Flurstück Tool", icon: "\u2316", group: "basic-tools", ready: true, description: "Flurstücke direkt im 3D-Editor projektweit auswählen oder abwählen." },
    { id: "parcel-grid", label: "Grundstücksraster", icon: "\u22d5", group: "basic-tools", ready: true, description: "Eine Flurstücksgrenze als Bauachse wählen und direkte Grenzbebauung oder einen festen Abstand vorgeben." },
    { id: "paint", label: "Paint Brush", icon: "\u270e", group: "basic-tools", ready: true, description: "Kugel-, Quader- und Zylinderpinsel mit Radius, Dichte und Wandstaerke." },
    { id: "sculpt", label: "Sculpt Brush", icon: "\u2248", group: "basic-tools", ready: true, description: "Material auftragen oder mit Rechtsklick abtragen; bildet das Fundament fuer Smooth, Refine und Erosion." },
    { id: "shape", label: "Shape Tool", icon: "\u25c7", group: "basic-tools", description: "Parametrische Voll- und Hohlformen." },
    { id: "entity", label: "Entity Tool", icon: "\u25c9", group: "basic-tools", description: "Entities auswaehlen, platzieren und bearbeiten." },
    { id: "trigger-volume", label: "Trigger Volume", icon: "\u2318", group: "basic-tools", description: "Interaktions- und Triggerregionen anlegen." },
    { id: "ruler-laser", label: "Ruler & Laser", icon: "\u2194", group: "basic-tools", ready: true, description: "Distanzen zwischen zwei Punkten direkt in Metern messen." },
    { id: "copy-transform", label: "Copy / Cut / Paste", icon: "\u27f3", group: "basic-tools", ready: true, description: "Markierte Bereiche kopieren, ausschneiden und am Ziel wieder einfügen." },
    { id: "extrude-flood", label: "Extrude & Flood", icon: "\u21e5", group: "basic-tools", description: "Flaechen extrudieren oder zusammenhaengende Bereiche fluten." },
    { id: "boulder", label: "Boulder Brush", icon: "\u25ce", group: "terrain-brushes", description: "Unregelmaessige Felsvolumen." },
    { id: "cave", label: "Cave Brush", icon: "\u25d0", group: "terrain-brushes", description: "Tunnel und Hohlraeume aus Terrain schneiden." },
    { id: "mountain", label: "Mountain Brush", icon: "\u25b2", group: "terrain-brushes", description: "Gebirge und Hoehenzuege aufbauen." },
    { id: "tentacle", label: "Tentacle Brush", icon: "\u223f", group: "terrain-brushes", description: "Organische, gerichtete Volumenpfade." },
    { id: "lava-cracks", label: "Lava Cracks", icon: "\u26a1", group: "terrain-brushes", description: "Verzweigte Spalten und Materialadern." },
    { id: "grass-erosion", label: "Grass & Erosion", icon: "\u224b", group: "terrain-brushes", description: "Oberflaechenmaterial verteilen und Terrain erodieren." },
    { id: "path-wall-layer", label: "Path / Wall / Layer", icon: "\u2503", group: "terrain-brushes", description: "Pfade, Waende und Materialschichten entlang einer Spur." },
    { id: "revolve", label: "Revolve Tool", icon: "\u27f2", group: "terrain-brushes", description: "Profil um eine Achse rotieren und als Volumen aufbauen." }
  ];

  function clean(value) {
    try { return String(value == null ? "" : value).trim(); } catch (error) { return ""; }
  }

  function record(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function first() {
    for (var index = 0; index < arguments.length; index += 1) {
      var value = clean(arguments[index]);
      if (value) return value;
    }
    return "";
  }

  function booleanValue(value, fallback) {
    if (typeof value === "boolean") return value;
    var normalized = clean(value).toLowerCase();
    if (["true", "1", "yes", "on", "enabled", "published", "active"].indexOf(normalized) >= 0) return true;
    if (["false", "0", "no", "off", "disabled", "deleted", "invalid"].indexOf(normalized) >= 0) return false;
    return fallback;
  }

  function unwrapItems(payload) {
    var root = record(payload);
    var candidates = [
      root.items,
      record(root.data).items,
      record(root.payload).items,
      record(root.result).items,
      record(record(root.payload).data).items,
      record(record(root.data).payload).items
    ];
    for (var index = 0; index < candidates.length; index += 1) {
      if (Array.isArray(candidates[index])) return candidates[index];
    }
    return [];
  }

  function nestedValue(source, keys) {
    var value = source;
    for (var index = 0; index < keys.length; index += 1) {
      value = record(value)[keys[index]];
    }
    return value;
  }

  function normalizeVariant(value) {
    var raw = record(value);
    var variantId = first(raw.variant_id, raw.variantId, raw.id_in_family, raw.slug);
    if (!variantId) return null;

    var status = first(raw.publication_status, raw.status).toLowerCase();
    var enabled = booleanValue(raw.enabled, booleanValue(raw.active, true));
    var visible = booleanValue(raw.visible, true);
    var published = !status || ["published", "ready", "active", "ok"].indexOf(status) >= 0;
    if (!enabled || !visible || !published) return null;

    return {
      variant_id: variantId,
      label: first(raw.label, raw.name, variantId),
      description: first(raw.description),
      is_default: booleanValue(raw.is_default, false),
      definition_values: record(raw.definition_values || raw.definitionValues),
      metadata: record(raw.metadata),
      revision_hash: first(raw.revision_hash)
    };
  }

  function normalizeVariants(raw) {
    var values = Array.isArray(raw.variants) ? raw.variants : [];
    return values.map(normalizeVariant).filter(Boolean);
  }

  function selectedVariant(variants, variantId) {
    var selected = null;
    variants.some(function (variant) {
      if (variant.variant_id !== variantId) return false;
      selected = variant;
      return true;
    });
    if (selected) return selected;
    return variants.filter(function (variant) { return variant.is_default; })[0] || variants[0] || null;
  }

  function variantMetadata(baseMetadata, variant, variants) {
    return Object.assign({}, record(baseMetadata), {
      selected_variant_id: variant ? variant.variant_id : "default",
      definition_values: variant ? record(variant.definition_values) : {},
      available_variants: variants.map(function (entry) {
        return {
          variant_id: entry.variant_id,
          label: entry.label,
          definition_values: record(entry.definition_values)
        };
      })
    });
  }
  function normalizeAssets(raw, payload) {
    var candidates = [raw.assets, payload.assets, record(raw.revision).assets];
    var values = [];
    candidates.some(function (candidate) {
      if (!Array.isArray(candidate)) return false;
      values = candidate.map(record).filter(function (asset) {
        return booleanValue(asset.active, true) && booleanValue(asset.visible, true) && booleanValue(asset.exists, true);
      });
      return values.length > 0;
    });
    return values;
  }

  function normalizeAppearance(raw, payload, metadata, activeVariant, assets) {
    var definitionValues = activeVariant ? record(activeVariant.definition_values) : {};
    var textureAsset = assets.filter(function (asset) {
      var assetPayload = record(asset.payload);
      var role = first(asset.role, asset.purpose, asset.asset_kind, asset.kind, assetPayload.role, assetPayload.purpose).toLowerCase();
      var mimeType = first(asset.mime_type, asset.content_type, assetPayload.mime_type, assetPayload.content_type).toLowerCase();
      return ["albedo", "texture", "textures", "preview"].indexOf(role) >= 0 || mimeType.indexOf("image/") === 0;
    })[0] || {};
    var texturePayload = record(textureAsset.payload);
    var runtime = Object.assign({}, record(texturePayload.runtime), record(textureAsset.runtime));
    var textureUrl = safePreviewUrl(first(
      textureAsset.uri,
      textureAsset.url,
      texturePayload.uri,
      texturePayload.url
    ));
    var materialType = first(
      definitionValues["material.type"],
      nestedValue(definitionValues, ["material", "type"]),
      metadata.material_type,
      metadata.materialType,
      "generic"
    ).toLowerCase();
    var color = first(
      definitionValues["material.color_hint"],
      nestedValue(definitionValues, ["material", "color_hint"]),
      record(raw.icon).color,
      raw.color,
      payload.color,
      "#ffffff"
    );
    var metalness = Number(runtime.metalness);
    var roughness = Number(runtime.roughness);
    if (!Number.isFinite(metalness)) metalness = materialType.indexOf("steel") >= 0 ? 0.66 : 0.02;
    if (!Number.isFinite(roughness)) {
      roughness = materialType.indexOf("steel") >= 0 ? 0.52 : materialType.indexOf("wood") >= 0 || materialType.indexOf("timber") >= 0 ? 0.76 : 0.88;
    }

    return {
      version: "vplib-appearance.v1",
      textureUrl: textureUrl,
      textureKey: first(textureAsset.sha256, textureAsset.checksum, textureAsset.asset_hash, texturePayload.sha256, textureUrl),
      color: color,
      materialType: materialType,
      roughness: roughness,
      metalness: metalness,
      colorSpace: first(runtime.color_space, runtime.colorSpace, "srgb"),
      wrapS: first(runtime.wrap_s, runtime.wrapS, "repeat"),
      wrapT: first(runtime.wrap_t, runtime.wrapT, "repeat"),
      generateMipmaps: booleanValue(runtime.generate_mipmaps, true),
      anisotropy: Number(runtime.anisotropy || 4) || 4
    };
  }



  function normalizeItem(value) {
    var wrapper = record(value);
    var raw = record(wrapper.item && typeof wrapper.item === "object" ? wrapper.item : wrapper);
    var payload = record(raw.payload);
    var metadata = record(raw.metadata || payload.metadata);
    var placement = record(
      raw.placement ||
      payload.placement ||
      nestedValue(raw, ["variant", "placement"]) ||
      nestedValue(payload, ["variant", "placement"])
    );
    var command = record(raw.placementCommand || raw.placement_command || placement.command);
    var vplibUid = first(raw.vplib_uid, raw.vplibUid, raw.uid, payload.vplib_uid, payload.vplibUid);
    var familyId = first(raw.family_id, raw.familyId, payload.family_id, payload.familyId);
    var itemDbId = first(raw.item_db_id, raw.itemDbId, raw.family_db_id, raw.id, wrapper.item_db_id, wrapper.id);
    var packageId = first(raw.package_id, raw.packageId, payload.package_id, payload.packageId);
    var variants = normalizeVariants(raw);
    var requestedVariantId = first(raw.variant_id, raw.variantId, raw.default_variant_id, payload.variant_id, payload.variantId, "default");
    var activeVariant = selectedVariant(variants, requestedVariantId);
    var variantId = activeVariant ? activeVariant.variant_id : requestedVariantId;
    var runtimeBlockTypeId = first(
      raw.runtimeBlockTypeId,
      raw.runtime_block_type_id,
      raw.blockTypeId,
      raw.block_type_id,
      placement.runtimeBlockTypeId,
      placement.runtime_block_type_id,
      placement.blockTypeId,
      placement.block_type_id,
      command.runtimeBlockTypeId,
      command.blockTypeId,
      payload.runtimeBlockTypeId,
      payload.runtime_block_type_id,
      metadata.runtimeBlockTypeId,
      metadata.runtime_block_type_id,
      familyId,
      vplibUid ? "vplib:" + vplibUid + ":" + variantId : ""
    );
    var status = first(raw.publication_status, raw.status, wrapper.status).toLowerCase();
    var label = first(raw.label, raw.name, raw.title, payload.label, payload.name, familyId, vplibUid);
    var objectKind = first(raw.object_kind, raw.objectKind, raw.kind, payload.object_kind, payload.objectKind, "block");
    var enabled = booleanValue(raw.enabled, true) && booleanValue(raw.active, true);
    var visible = booleanValue(raw.visible, true) && !booleanValue(raw.is_deleted, false);
    var published = !status || ["published", "ready", "active", "ok"].indexOf(status) >= 0;
    var placeable = booleanValue(placement.placeable, booleanValue(raw.placeable, true));

    if (!enabled || !visible || !published || !placeable || !runtimeBlockTypeId || !(vplibUid || familyId || itemDbId) || !label) {
      return null;
    }

    var icon = record(raw.icon || payload.icon);
    var preview = record(raw.preview || payload.preview);
    var assets = normalizeAssets(raw, payload);
    var appearance = normalizeAppearance(raw, payload, metadata, activeVariant, assets);
    var description = first(raw.description, raw.text, payload.description);
    var domain = first(raw.domain, payload.domain, "all").toLowerCase();
    var category = first(raw.category, payload.category, "all").toLowerCase();
    var subcategory = first(raw.subcategory, payload.subcategory, "all").toLowerCase();
    var taxonomyPath = first(raw.taxonomy_path, raw.taxonomyPath, payload.taxonomy_path, [domain, category, subcategory].join("/"));
    var iconText = first(icon.text, icon.label, raw.icon_text, label).replace(/[^\p{L}\p{N}]/gu, "").slice(0, 2).toUpperCase() || "VP";
    var previewUrl = safePreviewUrl(first(preview.url, preview.src, raw.preview_url, raw.banner_url, appearance.textureUrl));
    var color = first(icon.color, appearance.color, raw.color, payload.color);

    return {
      id: itemDbId,
      item_db_id: itemDbId,
      vplib_uid: vplibUid,
      family_id: familyId,
      package_id: packageId,
      variant_id: variantId,
      runtimeBlockTypeId: runtimeBlockTypeId,
      blockTypeId: runtimeBlockTypeId,
      label: label,
      title: label,
      description: description,
      object_kind: objectKind,
      domain: domain,
      category: category,
      subcategory: subcategory,
      taxonomy_path: taxonomyPath,
      quantity: Number(raw.quantity || 1) || 1,
      source: first(raw.source, raw.source_scope, "creative-library"),
      scope: first(raw.scope, "editor"),
      mode: "creative",
      icon: { text: iconText, color: color, url: previewUrl },
      preview: previewUrl ? { url: previewUrl } : {},
      assets: {
        iconUrl: previewUrl,
        previewUrl: previewUrl,
        textureUrl: appearance.textureUrl,
        textureKey: appearance.textureKey,
        items: assets
      },
      appearance: appearance,
      placement: {
        kind: first(placement.kind, command.kind, "SetBlock"),
        runtimeBlockTypeId: runtimeBlockTypeId,
        blockTypeId: runtimeBlockTypeId,
        placeable: true,
        appearance: appearance
      },
      revision_hash: first(raw.revision_hash, raw.current_revision_hash),
      variants: variants,
      selected_variant: activeVariant,
      metadata: Object.assign(
        variantMetadata(metadata, activeVariant, variants),
        { appearance: appearance }
      )
    };
  }

  function expandItemVariants(value) {
    var wrapper = record(value);
    var raw = record(wrapper.item && typeof wrapper.item === "object" ? wrapper.item : wrapper);
    var variants = Array.isArray(raw.variants) ? raw.variants : [];
    if (!variants.length) return [value];

    var familyLabel = first(raw.label, raw.name, raw.title, raw.family_id, raw.vplib_uid);
    return variants.map(function (variantValue) {
      var variant = record(variantValue);
      var merged = Object.assign({}, raw);
      var variantId = first(variant.variant_id, variant.variantId, variant.id_in_family, variant.slug, "default");
      var variantLabel = first(variant.label, variant.name, variantId);

      merged.variant = variant;
      merged.variant_id = variantId;
      merged.label = variantLabel ? familyLabel + " - " + variantLabel : familyLabel;
      merged.description = first(variant.description, raw.description, raw.text);
      merged.enabled = booleanValue(raw.enabled, true) && booleanValue(variant.enabled, true);
      merged.visible = booleanValue(raw.visible, true) && booleanValue(variant.visible, true);
      merged.status = first(variant.publication_status, variant.status, raw.publication_status, raw.status);
      merged.publication_status = merged.status;
      merged.payload = Object.assign(
        {},
        record(raw.payload),
        record(variant.payload),
        record(variant.resolved_payload)
      );
      merged.metadata = Object.assign(
        {},
        record(raw.metadata),
        record(variant.metadata),
        { definition_values: record(variant.definition_values) }
      );
      return merged;
    });
  }

  function uniqueItems(values) {
    var result = [];
    var seen = Object.create(null);
    values.forEach(function (value) {
      var item = normalizeItem(value);
      if (!item) return;
      var key = item.vplib_uid || item.family_id || item.item_db_id;
      if (seen[key]) return;
      seen[key] = true;
      result.push(item);
    });
    return result.sort(function (left, right) { return left.label.localeCompare(right.label, "de"); });
  }

  function safePreviewUrl(value) {
    var url = clean(value);
    if (!url) return "";
    try {
      var parsed = new URL(url, window.location.href);
      if (["http:", "https:"].indexOf(parsed.protocol) < 0) return "";
      return parsed.href;
    } catch (error) {
      return "";
    }
  }

  function createTextureCube(textureUrl, extraClassName) {
    var cube = document.createElement("span");
    cube.className = "vp-inventory-cube " + (extraClassName || "");
    cube.setAttribute("aria-hidden", "true");
    ["front", "right", "top"].forEach(function (faceName) {
      var face = document.createElement("span");
      face.className = "vp-inventory-cube__face vp-inventory-cube__face--" + faceName;
      face.style.backgroundImage = "url(\"" + textureUrl.replace(/[\"\\]/g, "\\$&") + "\")";
      cube.appendChild(face);
    });
    return cube;
  }

  function isBlockLikeObjectKind(value) {
    var objectKind = clean(value).toLowerCase().replace(/-/g, "_");
    return !objectKind
      || objectKind === "block"
      || objectKind === "cell_block"
      || objectKind === "material"
      || objectKind === "terrain_block"
      || objectKind === "voxel";
  }

  function worldEditToolItem(tool) {
    var toolId = clean(tool && tool.id).toLowerCase();
    return {
      id: "world-edit-" + toolId,
      item_db_id: null,
      vplib_uid: "vectoplan.world-edit." + toolId,
      family_id: "world-edit." + toolId,
      package_id: "vectoplan.world-edit",
      variant_id: toolId,
      runtimeBlockTypeId: "",
      blockTypeId: "",
      label: tool.label,
      title: tool.label,
      description: tool.description,
      object_kind: "world_edit_tool",
      world_edit_tool: toolId,
      domain: "world-edit",
      category: tool.group,
      subcategory: "built-in",
      taxonomy_path: "world-edit/" + tool.group + "/" + toolId,
      quantity: 1,
      source: "system",
      scope: "editor",
      mode: "creative",
      icon: { text: tool.icon, color: "#315fc4" },
      preview: {},
      assets: [],
      appearance: {},
      placement: {
        kind: "editor-tool",
        tool: "world-edit",
        toolId: toolId,
        world_edit_tool: toolId
      },
      selected_variant: null,
      variants: [],
      metadata: {
        builtin: true,
        ready: Boolean(tool.ready),
        world_edit_tool: toolId
      }
    };
  }

  function itemPayload(item) {
    return {
      id: item.id,
      item_db_id: item.item_db_id,
      vplib_uid: item.vplib_uid,
      family_id: item.family_id,
      package_id: item.package_id,
      variant_id: item.variant_id,
      runtimeBlockTypeId: item.runtimeBlockTypeId,
      blockTypeId: item.blockTypeId,
      label: item.label,
      title: item.title,
      description: item.description,
      object_kind: item.object_kind,
      world_edit_tool: item.world_edit_tool,
      domain: item.domain,
      category: item.category,
      subcategory: item.subcategory,
      taxonomy_path: item.taxonomy_path,
      quantity: item.quantity,
      source: item.source,
      scope: item.scope,
      mode: item.mode,
      icon: item.icon,
      preview: item.preview,
      assets: item.assets,
      appearance: item.appearance,
      placement: item.placement,
      variant: item.selected_variant,
      variants: item.variants,
      metadata: item.metadata
    };
  }

  function postDragMessage(type, item, extraDetail) {
    if (!window.parent || window.parent === window) return;
    var targetOrigin = "*";
    try { if (document.referrer) targetOrigin = new URL(document.referrer).origin; } catch (error) { targetOrigin = "*"; }
    var detail = item ? { item: itemPayload(item) } : {};
    if (extraDetail && typeof extraDetail === "object") {
      Object.keys(extraDetail).forEach(function (key) { detail[key] = extraDetail[key]; });
    }
    window.parent.postMessage({
      type: type,
      source: "vectoplan-library-creative-inventory",
      version: MODULE_VERSION,
      detail: detail
    }, targetOrigin);
  }

  function bindCreativeCardDrag(card, item) {
    card.addEventListener("dragstart", function (event) {
      var payload = itemPayload(item);
      card.classList.add("vp-creative-card--dragging");
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "copy";
        event.dataTransfer.setData(DRAG_MIME, JSON.stringify(payload));
        event.dataTransfer.setData("text/plain", JSON.stringify(payload));
      }
      postDragMessage("vectoplan:creative-drag-start", item);
    });
    card.addEventListener("dragend", function () {
      card.classList.remove("vp-creative-card--dragging");
      postDragMessage("vectoplan:creative-drag-end", null);
    });

    var pointerDrag = null;
    var pointerMoveFrame = 0;

    function pointerDetail(event) {
      return {
        pointer: {
          pointerId: event.pointerId,
          pointerType: event.pointerType || "mouse",
          clientX: event.clientX,
          clientY: event.clientY
        }
      };
    }

    function sendPointerMove() {
      pointerMoveFrame = 0;
      if (!pointerDrag || !pointerDrag.started || !pointerDrag.lastEvent) return;
      postDragMessage(POINTER_DRAG_MOVE, item, pointerDetail(pointerDrag.lastEvent));
    }

    function finishPointerDrag(event, drop) {
      if (!pointerDrag || event.pointerId !== pointerDrag.pointerId) return;
      if (pointerMoveFrame) {
        window.cancelAnimationFrame(pointerMoveFrame);
        pointerMoveFrame = 0;
      }
      if (pointerDrag.started) {
        postDragMessage(POINTER_DRAG_END, item, Object.assign(pointerDetail(event), { drop: drop !== false }));
      }
      try { if (card.hasPointerCapture(event.pointerId)) card.releasePointerCapture(event.pointerId); } catch (error) { /* best effort */ }
      pointerDrag = null;
      card.classList.remove("vp-creative-card--dragging", "vp-creative-card--pointer-dragging");
    }

    card.addEventListener("pointerdown", function (event) {
      if (!event.isPrimary || event.button !== 0) return;
      pointerDrag = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        started: false,
        lastEvent: event
      };
      try { card.setPointerCapture(event.pointerId); } catch (error) { /* capture is optional */ }
      event.preventDefault();
    });

    card.addEventListener("pointermove", function (event) {
      if (!pointerDrag || event.pointerId !== pointerDrag.pointerId) return;
      pointerDrag.lastEvent = event;
      if (!pointerDrag.started) {
        var distance = Math.hypot(event.clientX - pointerDrag.startX, event.clientY - pointerDrag.startY);
        if (distance < POINTER_DRAG_THRESHOLD) return;
        pointerDrag.started = true;
        card.classList.add("vp-creative-card--dragging", "vp-creative-card--pointer-dragging");
        postDragMessage(POINTER_DRAG_START, item, pointerDetail(event));
      }
      event.preventDefault();
      if (!pointerMoveFrame) pointerMoveFrame = window.requestAnimationFrame(sendPointerMove);
    });

    card.addEventListener("pointerup", function (event) { finishPointerDrag(event, true); });
    card.addEventListener("pointercancel", function (event) { finishPointerDrag(event, false); });
    card.addEventListener("lostpointercapture", function (event) {
      if (pointerDrag && event.pointerId === pointerDrag.pointerId) finishPointerDrag(event, false);
    });
  }

  function showWorldEditTool(tool, card) {
    var aside = document.querySelector(".vp-creative-tools");
    var panel = document.querySelector("[data-world-edit-tool-config]");
    if (!aside || !panel || !tool) return;
    state.selectedWorldEditToolId = tool.id;
    Array.prototype.forEach.call(document.querySelectorAll("[data-world-edit-tool-card]"), function (entry) {
      entry.classList.toggle("is-selected", entry === card);
      entry.setAttribute("aria-selected", entry === card ? "true" : "false");
    });
    aside.dataset.worldEditConfigOpen = "true";
    panel.hidden = false;
    var title = panel.querySelector("[data-world-edit-config-title]");
    var description = panel.querySelector("[data-world-edit-config-description]");
    var status = panel.querySelector("[data-world-edit-config-status]");
    var panelTitle = aside.querySelector("[data-creative-tools-title]");
    var panelSubtitle = aside.querySelector("[data-creative-tools-subtitle]");
    var selectionSettings = panel.querySelector("[data-world-edit-selection-settings]");
    var brushSettings = panel.querySelector("[data-world-edit-brush-settings]");
    var utilitySettings = panel.querySelector("[data-world-edit-utility-settings]");
    var parcelGridSettings = panel.querySelector("[data-world-edit-parcel-grid-settings]");
    var utilityTitle = panel.querySelector("[data-world-edit-utility-title]");
    var utilityText = panel.querySelector("[data-world-edit-utility-text]");
    var operationField = panel.querySelector("[data-world-edit-operation-field]");
    var operationSelect = panel.querySelector("[data-world-edit-config-operation]");
    var parcelMask = panel.querySelector(".vp-world-edit-config__mask");
    var actions = panel.querySelector("[data-world-edit-config-actions]");
    panel.dataset.tool = tool.id;
    if (panelTitle) panelTitle.textContent = tool.label;
    if (panelSubtitle) panelSubtitle.textContent = "World Edit Einstellungen";
    if (title) title.textContent = tool.label;
    if (description) description.textContent = tool.description;
    if (selectionSettings) selectionSettings.hidden = tool.id !== "selection";
    if (brushSettings) brushSettings.hidden = tool.id !== "paint" && tool.id !== "sculpt";
    if (utilitySettings) utilitySettings.hidden = ["parcel", "parcel-grid", "ruler-laser", "copy-transform"].indexOf(tool.id) < 0;
    if (parcelGridSettings) parcelGridSettings.hidden = tool.id !== "parcel-grid";
    if (utilityTitle) utilityTitle.textContent = tool.label;
    if (utilityText) utilityText.textContent = tool.id === "parcel"
      ? "Flurstück anvisieren und anklicken. Die Auswahl wird sofort mit Map und Projekt synchronisiert."
      : tool.id === "parcel-grid"
        ? "Grenzkante anvisieren und anklicken. Die cyanfarbene Bauachse zeigt Grenzlage, Abstand und Wirkbereich."
      : tool.id === "ruler-laser"
        ? "Linksklick halten, Kamera bis zum zweiten Punkt bewegen und loslassen."
        : "Zuerst mit Selection markieren, dann Copy, Cut oder Paste wählen.";
    if (operationField) operationField.hidden = ["parcel", "parcel-grid", "ruler-laser"].indexOf(tool.id) >= 0;
    if (parcelMask) parcelMask.hidden = ["parcel", "parcel-grid", "ruler-laser"].indexOf(tool.id) >= 0;
    if (actions) actions.hidden = ["selection", "copy-transform"].indexOf(tool.id) < 0;
    if (operationSelect) {
      var clipboardTool = tool.id === "copy-transform";
      if (operationSelect.dataset.mode !== (clipboardTool ? "clipboard" : "world")) {
        operationSelect.innerHTML = clipboardTool
          ? '<option value="copy">Kopieren</option><option value="cut">Ausschneiden</option><option value="paste">Einfügen</option>'
          : '<option value="set">Setzen</option><option value="wall">Wände</option><option value="fill">Nur Luft füllen</option><option value="replace">Ersetzen</option><option value="clear">Leeren</option>';
        operationSelect.dataset.mode = clipboardTool ? "clipboard" : "world";
      }
      if (clipboardTool && ["copy", "cut", "paste"].indexOf(state.worldEditSettings.operation) < 0) state.worldEditSettings.operation = "copy";
      if (!clipboardTool && ["set", "wall", "fill", "replace", "clear"].indexOf(state.worldEditSettings.operation) < 0) state.worldEditSettings.operation = "set";
      operationSelect.value = state.worldEditSettings.operation;
    }
    if (status) {
      status.textContent = tool.ready ? "Im Editor eingebaut \u00b7 Grundst\u00fccksmaske aktiv" : "Analysiert \u00b7 folgt in einer Ausbauetappe";
      status.dataset.ready = tool.ready ? "true" : "false";
    }
    if (tool.ready) emitWorldEditSettings();
  }

  function hideWorldEditTool() {
    var aside = document.querySelector(".vp-creative-tools");
    var panel = document.querySelector("[data-world-edit-tool-config]");
    Array.prototype.forEach.call(document.querySelectorAll("[data-world-edit-tool-card]"), function (entry) {
      entry.classList.remove("is-selected");
      entry.setAttribute("aria-selected", "false");
    });
    if (aside) delete aside.dataset.worldEditConfigOpen;
    if (panel) panel.hidden = true;
    var panelTitle = aside && aside.querySelector("[data-creative-tools-title]");
    var panelSubtitle = aside && aside.querySelector("[data-creative-tools-subtitle]");
    if (panelTitle) panelTitle.textContent = "Creative Mode";
    if (panelSubtitle) panelSubtitle.textContent = "Schnelleinstellungen";
    state.selectedWorldEditToolId = "";
  }

  function findWorldEditTool(toolId) {
    var result = null;
    WORLD_EDIT_TOOLS.some(function (tool) {
      if (tool.id !== toolId) return false;
      result = tool;
      return true;
    });
    return result;
  }

  function worldEditToolIdFromSlot(slotValue) {
    var slot = record(slotValue);
    var payload = record(slot.payload);
    var metadata = record(slot.metadata || payload.metadata);
    var placement = record(slot.placement || payload.placement);
    var objectKind = first(slot.object_kind, slot.objectKind, payload.object_kind, payload.objectKind).toLowerCase().replace(/-/g, "_");
    var domain = first(slot.domain, payload.domain).toLowerCase().replace(/_/g, "-");
    var familyId = first(slot.family_id, slot.familyId, payload.family_id, payload.familyId).toLowerCase();
    var vplibUid = first(slot.vplib_uid, slot.vplibUid, payload.vplib_uid, payload.vplibUid).toLowerCase();
    var packageId = first(slot.package_id, slot.packageId, payload.package_id, payload.packageId).toLowerCase();
    var isWorldEdit = objectKind === "world_edit_tool"
      || domain === "world-edit"
      || familyId.indexOf("world-edit.") === 0
      || vplibUid.indexOf("vectoplan.world-edit.") === 0
      || packageId === "vectoplan.world-edit";
    if (!isWorldEdit) return "";

    var candidates = [
      slot.world_edit_tool,
      slot.worldEditTool,
      payload.world_edit_tool,
      payload.worldEditTool,
      metadata.world_edit_tool,
      metadata.worldEditTool,
      placement.world_edit_tool,
      placement.worldEditTool,
      placement.toolId,
      slot.variant_id,
      slot.variantId,
      payload.variant_id,
      payload.variantId,
      familyId,
      vplibUid
    ];
    for (var index = 0; index < candidates.length; index += 1) {
      var candidate = clean(candidates[index]).toLowerCase().replace(/_/g, "-");
      ["vectoplan.world-edit.", "world-edit.", "world-edit-"].some(function (prefix) {
        if (candidate.indexOf(prefix) !== 0) return false;
        candidate = candidate.slice(prefix.length);
        return true;
      });
      if (findWorldEditTool(candidate)) return candidate;
    }
    return "";
  }

  function updateWorldEditSettingOutputs() {
    var radius = document.querySelector("[data-world-edit-config-radius]");
    var density = document.querySelector("[data-world-edit-config-density]");
    var wall = document.querySelector("[data-world-edit-config-wall]");
    var setback = document.querySelector("[data-world-edit-config-setback]");
    var influence = document.querySelector("[data-world-edit-config-influence]");
    var radiusOutput = document.querySelector("[data-world-edit-config-radius-output]");
    var densityOutput = document.querySelector("[data-world-edit-config-density-output]");
    var wallOutput = document.querySelector("[data-world-edit-config-wall-output]");
    var setbackOutput = document.querySelector("[data-world-edit-config-setback-output]");
    var influenceOutput = document.querySelector("[data-world-edit-config-influence-output]");
    if (radiusOutput && radius) radiusOutput.textContent = radius.value;
    if (densityOutput && density) densityOutput.textContent = density.value + "%";
    if (wallOutput && wall) wallOutput.textContent = wall.value;
    if (setbackOutput && setback) setbackOutput.textContent = setback.value + " m";
    if (influenceOutput && influence) influenceOutput.textContent = influence.value + " m";
  }

  function applyWorldEditRuntimeState(value) {
    var detail = record(value);
    if (detail.toolId && state.selectedWorldEditToolId && detail.toolId !== state.selectedWorldEditToolId) return;
    var first = document.querySelector("[data-world-edit-runtime-first]");
    var second = document.querySelector("[data-world-edit-runtime-second]");
    var status = document.querySelector("[data-world-edit-config-status]");
    var actions = document.querySelector("[data-world-edit-config-actions]");
    var execute = document.querySelector('[data-world-edit-config-action="execute"]');
    var reset = document.querySelector('[data-world-edit-config-action="reset"]');
    var parcelGridInfluence = document.querySelector("[data-world-edit-config-influence]");
    if (first) first.textContent = clean(detail.first) || "im 3D-Fenster";
    if (second) second.textContent = clean(detail.second) || "im 3D-Fenster";
    if (status && clean(detail.status)) {
      status.textContent = clean(detail.status);
      status.dataset.ready = detail.statusKind === "error" || detail.statusKind === "warning" ? "false" : "true";
    }
    if (actions) actions.hidden = ["selection", "copy-transform"].indexOf(state.selectedWorldEditToolId) < 0;
    if (execute) execute.disabled = Boolean(detail.busy) || detail.canExecute === false;
    if (reset) reset.disabled = Boolean(detail.busy);
    if (parcelGridInfluence && Number.isFinite(Number(detail.parcelGridInfluence))) {
      parcelGridInfluence.value = String(Math.max(1, Math.min(6, Math.round(Number(detail.parcelGridInfluence)))));
      state.worldEditSettings.parcelGridInfluence = Number(parcelGridInfluence.value);
      updateWorldEditSettingOutputs();
    }
  }

  function bindWorldEditActions() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-world-edit-config-action]"), function (button) {
      button.addEventListener("click", function () {
        postDragMessage(WORLD_EDIT_ACTION, null, {
          tool: state.selectedWorldEditToolId,
          toolId: state.selectedWorldEditToolId,
          action: clean(button.getAttribute("data-world-edit-config-action"))
        });
      });
    });
  }

  function emitWorldEditSettings() {
    if (!state.selectedWorldEditToolId) return;
    postDragMessage(WORLD_EDIT_SETTINGS_CHANGE, null, {
      tool: state.selectedWorldEditToolId,
      toolId: state.selectedWorldEditToolId,
      operation: state.worldEditSettings.operation,
      shape: state.worldEditSettings.shape,
      radius: state.worldEditSettings.radius,
      density: state.worldEditSettings.density,
      wallThickness: state.worldEditSettings.wallThickness,
      parcelMask: state.worldEditSettings.parcelMask,
      parcelGridMode: state.worldEditSettings.parcelGridMode,
      parcelGridSetback: state.worldEditSettings.parcelGridSetback,
      parcelGridInfluence: state.worldEditSettings.parcelGridInfluence
    });
  }

  function bindWorldEditSettings() {
    var operation = document.querySelector("[data-world-edit-config-operation]");
    var shape = document.querySelector("[data-world-edit-config-shape]");
    var radius = document.querySelector("[data-world-edit-config-radius]");
    var density = document.querySelector("[data-world-edit-config-density]");
    var wall = document.querySelector("[data-world-edit-config-wall]");
    var parcelMask = document.querySelector("[data-world-edit-config-parcel-mask]");
    var parcelGridMode = document.querySelector("[data-world-edit-config-parcel-grid-mode]");
    var parcelGridSetback = document.querySelector("[data-world-edit-config-setback]");
    var parcelGridInfluence = document.querySelector("[data-world-edit-config-influence]");

    function readAndEmit() {
      state.worldEditSettings.operation = operation ? operation.value : "set";
      state.worldEditSettings.shape = shape ? shape.value : "sphere";
      state.worldEditSettings.radius = Number(radius ? radius.value : 2);
      state.worldEditSettings.density = Number(density ? density.value : 100);
      state.worldEditSettings.wallThickness = Number(wall ? wall.value : 0);
      state.worldEditSettings.parcelMask = Boolean(parcelMask && parcelMask.checked);
      state.worldEditSettings.parcelGridMode = parcelGridMode ? parcelGridMode.value : "boundary";
      state.worldEditSettings.parcelGridSetback = Number(parcelGridSetback ? parcelGridSetback.value : 0);
      state.worldEditSettings.parcelGridInfluence = Number(parcelGridInfluence ? parcelGridInfluence.value : 3);
      updateWorldEditSettingOutputs();
      emitWorldEditSettings();
    }

    [operation, shape, parcelMask, parcelGridMode].forEach(function (input) {
      if (input) input.addEventListener("change", readAndEmit);
    });
    [radius, density, wall, parcelGridSetback, parcelGridInfluence].forEach(function (input) {
      if (input) input.addEventListener("input", readAndEmit);
    });
    updateWorldEditSettingOutputs();
  }

  function applyWorldEditSelection(toolId) {
    var tool = toolId ? findWorldEditTool(toolId) : null;
    if (!tool) {
      hideWorldEditTool();
      return;
    }
    var card = document.querySelector('[data-world-edit-tool-id="' + tool.id + '"]');
    showWorldEditTool(tool, card);
  }

  function bindUserInventorySelection() {
    window.addEventListener("message", function (event) {
      if (!window.parent || event.source !== window.parent) return;
      var expectedOrigin = "";
      try { if (document.referrer) expectedOrigin = new URL(document.referrer).origin; } catch (error) { expectedOrigin = ""; }
      if (expectedOrigin && event.origin !== expectedOrigin) return;

      var message = record(event.data);
      if (message.source !== "vectoplan-editor") return;
      var type = clean(message.type);
      if (type === WORLD_EDIT_STATE_SYNC) {
        applyWorldEditRuntimeState(record(message.detail));
        return;
      }
      if (type === WORLD_EDIT_SELECTION) {
        var directDetail = record(message.detail);
        applyWorldEditSelection(clean(directDetail.toolId || directDetail.tool).toLowerCase());
        return;
      }
      if ([
        "vectoplan:user-inventory-selection-change",
        "vectoplan:user-inventory-load",
        "vectoplan:user-inventory-state"
      ].indexOf(type) < 0) return;

      var detail = record(message.detail);
      var slot = detail.selected_slot || detail.selectedSlot || detail.slot;
      var toolId = worldEditToolIdFromSlot(slot);
      applyWorldEditSelection(toolId);
    });
  }

  function createWorldEditToolCard(tool) {
    var item = worldEditToolItem(tool);
    var card = document.createElement("article");
    card.className = "vp-creative-card vp-world-edit-card" + (tool.ready ? " is-ready" : " is-planned");
    card.setAttribute("role", "listitem");
    card.setAttribute("tabindex", tool.ready ? "0" : "-1");
    card.setAttribute("draggable", tool.ready ? "true" : "false");
    card.setAttribute("aria-disabled", tool.ready ? "false" : "true");
    card.setAttribute("aria-label", tool.label + (tool.ready ? ", in einen Inventar-Slot ziehen" : ", geplant"));
    card.dataset.creativeItemCard = "true";
    card.dataset.creativeCard = "true";
    card.dataset.worldEditToolCard = "true";
    card.dataset.worldEditToolId = tool.id;
    card.dataset.itemId = item.id;
    card.dataset.vplibUid = item.vplib_uid;
    card.dataset.familyId = item.family_id;
    card.dataset.packageId = item.package_id;
    card.dataset.variantId = item.variant_id;
    card.dataset.objectKind = item.object_kind;
    card.dataset.domain = "world-edit";
    card.dataset.category = tool.group;
    card.dataset.subcategory = tool.ready ? "built-in" : "roadmap";
    card.dataset.taxonomyPath = "world-edit/" + tool.group + "/" + tool.id;
    card.dataset.itemTitle = tool.label;
    card.dataset.itemLabel = tool.label;
    card.dataset.itemDescription = tool.description;
    card.dataset.itemQuantity = "1";
    card.dataset.source = item.source;
    card.dataset.scope = item.scope;
    card.dataset.mode = item.mode;
    card.dataset.selectable = "true";
    card.dataset.draggable = tool.ready ? "true" : "false";
    card.dataset.disabled = tool.ready ? "false" : "true";
    card.dataset.searchText = [tool.label, tool.description, "world edit", tool.group, tool.ready ? "eingebaut" : "geplant"].join(" ").toLowerCase();

    var preview = document.createElement("span");
    preview.className = "vp-creative-card__preview vp-world-edit-card__preview";
    var icon = document.createElement("span");
    icon.className = "vp-world-edit-card__icon";
    icon.textContent = tool.icon;
    preview.appendChild(icon);
    var badge = document.createElement("small");
    badge.className = "vp-world-edit-card__badge";
    badge.textContent = tool.ready ? "BETA" : "PLAN";
    preview.appendChild(badge);
    card.appendChild(preview);

    var tooltip = document.createElement("span");
    tooltip.className = "vp-creative-card__tooltip";
    var tooltipTitle = document.createElement("strong");
    tooltipTitle.className = "vp-creative-card__tooltip-title";
    tooltipTitle.textContent = tool.label;
    var tooltipDetail = document.createElement("span");
    tooltipDetail.className = "vp-creative-card__tooltip-detail";
    tooltipDetail.textContent = tool.ready ? "Fest eingebaut" : "Analysiert / geplant";
    tooltip.appendChild(tooltipTitle);
    tooltip.appendChild(tooltipDetail);
    card.appendChild(tooltip);
    if (tool.ready) bindCreativeCardDrag(card, item);
    return card;
  }

  function createCard(item) {
    var card = document.createElement("article");
    card.className = "vp-creative-card vp-creative-card--real-item";
    card.setAttribute("role", "listitem");
    card.setAttribute("tabindex", "0");
    card.setAttribute("draggable", "true");
    card.setAttribute("aria-label", item.label + ", in einen Inventar-Slot ziehen");
    card.dataset.tooltip = item.label;
    card.dataset.creativeItemCard = "true";
    card.dataset.creativeCard = "true";
    card.dataset.itemId = item.id;
    card.dataset.itemDbId = item.item_db_id;
    card.dataset.vplibUid = item.vplib_uid;
    card.dataset.familyId = item.family_id;
    card.dataset.packageId = item.package_id;
    card.dataset.variantId = item.variant_id;
    card.dataset.definitionValues = JSON.stringify(item.selected_variant ? item.selected_variant.definition_values : {});
    card.dataset.runtimeBlockTypeId = item.runtimeBlockTypeId;
    card.dataset.blockTypeId = item.blockTypeId;
    card.dataset.domain = item.domain;
    card.dataset.category = item.category;
    card.dataset.subcategory = item.subcategory;
    card.dataset.taxonomyPath = item.taxonomy_path;
    card.dataset.objectKind = item.object_kind;
    card.dataset.itemTitle = item.title;
    card.dataset.itemLabel = item.label;
    card.dataset.itemDescription = item.description;
    card.dataset.itemQuantity = String(item.quantity);
    card.dataset.source = item.source;
    card.dataset.scope = item.scope;
    card.dataset.mode = item.mode;
    card.dataset.selectable = "true";
    card.dataset.draggable = "true";
    card.dataset.disabled = "false";
    card.dataset.searchText = [item.label, item.description, item.vplib_uid, item.family_id, item.package_id, item.domain, item.category, item.subcategory, item.variants.map(function (variant) { return variant.label; }).join(" ")].join(" ").toLowerCase();

    var preview = document.createElement("div");
    preview.className = "vp-creative-card__preview vp-creative-card__banner";
    preview.setAttribute("aria-hidden", "true");
    var previewUrl = safePreviewUrl(item.preview.url);
    if (previewUrl) {
      if (isBlockLikeObjectKind(item.object_kind)) {
        preview.appendChild(createTextureCube(previewUrl, "vp-creative-card__cube"));
      } else {
        var image = document.createElement("img");
        image.className = "vp-creative-card__preview-image vp-creative-card__banner-image";
        image.src = previewUrl;
        image.alt = "";
        image.loading = "lazy";
        image.decoding = "async";
        image.draggable = false;
        preview.appendChild(image);
      }
    }
    var icon = document.createElement("span");
    icon.className = "vp-creative-card__icon";
    icon.dataset.creativeCardIcon = "true";
    icon.textContent = item.icon.text;
    if (/^#[0-9a-f]{3,8}$/i.test(item.icon.color)) icon.style.backgroundColor = item.icon.color;
    preview.appendChild(icon);

    var tooltip = document.createElement("div");
    tooltip.className = "vp-creative-card__tooltip";
    tooltip.setAttribute("role", "tooltip");
    var tooltipTitle = document.createElement("strong");
    tooltipTitle.className = "vp-creative-card__tooltip-title";
    tooltipTitle.textContent = item.label;
    tooltip.appendChild(tooltipTitle);

    var variantDetail = item.selected_variant ? item.selected_variant.label : "";
    var tooltipDetail = document.createElement("span");
    tooltipDetail.className = "vp-creative-card__tooltip-detail";
    tooltipDetail.textContent = item.variants.length > 1
      ? (variantDetail ? "Standard: " + variantDetail + " · " : "") + item.variants.length + " Dicken hinterlegt"
      : first(variantDetail, item.description, item.appearance.materialType);
    tooltip.appendChild(tooltipDetail);

    card.dataset.hasTexture = previewUrl ? "true" : "false";
    card.appendChild(preview);
    card.appendChild(tooltip);
    bindCreativeCardDrag(card, item);
    return card;
  }

  function refreshTaxonomy() {
    try {
      var taxonomy = window.VectoplanTaxonomyNavigation;
      if (taxonomy) {
        if (typeof taxonomy.refreshCatalog === "function") {
          taxonomy.refreshCatalog();
        } else {
          taxonomy.refreshElements();
          taxonomy.applyCreativeCardFilter();
        }
      }
    } catch (error) { state.errors.push(String(error)); }
  }

  function itemsSignature(items) {
    return items.map(function (item) {
      return [
        first(item.vplib_uid, item.vplibUid, item.family_id, item.familyId, item.id),
        first(item.runtimeBlockTypeId, item.blockTypeId),
        (Array.isArray(item.variants) ? item.variants : []).map(function (variant) {
          return first(variant.variant_id, variant.variantId, variant.id) + ":" + first(variant.revision_hash);
        }).join(",")
      ].join("|");
    }).sort().join(";");
  }

  function updateEmptyState() {
    var grid = document.querySelector(SELECTORS.grid);
    var empty = document.querySelector(SELECTORS.empty);
    if (!grid || !empty) return;
    var cards = Array.prototype.slice.call(grid.querySelectorAll(SELECTORS.card));
    var visible = cards.filter(function (card) {
      return !card.hidden && !card.classList.contains("vp-creative-card--hidden-by-taxonomy") && !card.classList.contains("vp-creative-card--hidden-by-search");
    }).length;
    empty.hidden = visible > 0 || state.loading;
    grid.hidden = visible === 0;
  }

  function applySearch() {
    var grid = document.querySelector(SELECTORS.grid);
    if (!grid) return;
    var normalized = clean(state.query).toLocaleLowerCase("de");
    Array.prototype.forEach.call(grid.querySelectorAll(SELECTORS.card), function (card) {
      var haystack = clean(card.dataset.searchText || card.textContent).toLocaleLowerCase("de");
      card.classList.toggle("vp-creative-card--hidden-by-search", Boolean(normalized && haystack.indexOf(normalized) < 0));
    });
    updateEmptyState();
  }

  function setLoadingStatus(message) {
    var status = document.querySelector(SELECTORS.status);
    if (!status) return;
    status.hidden = !message;
    status.textContent = message || "";
  }

  function render(items) {
    var grid = document.querySelector(SELECTORS.grid);
    if (!grid) return;
    while (grid.firstChild) grid.removeChild(grid.firstChild);
    var fragment = document.createDocumentFragment();
    WORLD_EDIT_TOOLS.forEach(function (tool) { fragment.appendChild(createWorldEditToolCard(tool)); });
    items.forEach(function (item) { fragment.appendChild(createCard(item)); });
    grid.appendChild(fragment);
    state.items = items;
    state.itemsSignature = itemsSignature(items);
    if (state.selectedWorldEditToolId) {
      var selectedTool = findWorldEditTool(state.selectedWorldEditToolId);
      var selectedCard = document.querySelector('[data-world-edit-tool-id="' + state.selectedWorldEditToolId + '"]');
      if (selectedTool) showWorldEditTool(selectedTool, selectedCard);
    }
    refreshTaxonomy();
    applySearch();
    setLoadingStatus("");
    updateEmptyState();
    document.dispatchEvent(new CustomEvent("vectoplan:creative-library-ready", { detail: { itemCount: items.length, worldEditToolCount: WORLD_EDIT_TOOLS.length } }));
  }

  function requestItems(url) {
    if (!url || typeof window.fetch !== "function") return Promise.resolve([]);
    var controller = typeof window.AbortController === "function" ? new window.AbortController() : null;
    var timeoutId = window.setTimeout(function () {
      if (controller) controller.abort();
    }, REQUEST_TIMEOUT_MS);
    var options = { credentials: "same-origin", cache: "no-store", headers: { "Accept": "application/json" } };
    if (controller) options.signal = controller.signal;
    return window.fetch(url, options)
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status + " für " + url);
        return response.json();
      })
      .then(unwrapItems)
      .then(function (items) {
        window.clearTimeout(timeoutId);
        return items;
      }, function (error) {
        window.clearTimeout(timeoutId);
        throw error;
      });
  }

  function load() {
    var grid = document.querySelector(SELECTORS.grid);
    if (!grid) return Promise.resolve([]);
    state.loading = true;
    setLoadingStatus("Veröffentlichte VPLIB-Objekte werden geladen …");
    updateEmptyState();
    var primaryUrl = clean(grid.dataset.creativeItemsUrl);
    var fallbackUrl = clean(grid.dataset.publishedItemsUrl);

    function safeRequest(url) {
      if (!url) return Promise.resolve([]);
      return requestItems(url).catch(function (error) {
        state.errors.push(String(error));
        return [];
      });
    }

    return safeRequest(primaryUrl).then(function (rawItems) {
      if (rawItems.length || !fallbackUrl) return rawItems;
      return safeRequest(fallbackUrl);
    }).then(function (rawItems) {
      state.loading = false;
      var items = uniqueItems(rawItems);
      render(items);
      return items;
    }).catch(function (error) {
      state.loading = false;
      state.errors.push(String(error));
      render([]);
      return [];
    });
  }

  function refreshInBackground() {
    var grid = document.querySelector(SELECTORS.grid);
    if (!grid || state.loading || document.hidden || document.querySelector(".vp-creative-card--dragging")) {
      return Promise.resolve(state.items);
    }

    var primaryUrl = clean(grid.dataset.creativeItemsUrl);
    var fallbackUrl = clean(grid.dataset.publishedItemsUrl);
    if (!primaryUrl && !fallbackUrl) return Promise.resolve(state.items);

    function requestWithFallback() {
      if (!primaryUrl) return requestItems(fallbackUrl);
      return requestItems(primaryUrl).then(function (rawItems) {
        if (rawItems.length || !fallbackUrl) return rawItems;
        return requestItems(fallbackUrl);
      });
    }

    return requestWithFallback().then(function (rawItems) {
      var items = uniqueItems(rawItems);
      if (itemsSignature(items) !== state.itemsSignature) render(items);
      return items;
    }).catch(function (error) {
      state.errors.push(String(error));
      return state.items;
    });
  }

  function startAutoRefresh() {
    if (state.refreshTimer) return;
    state.refreshTimer = window.setInterval(function () {
      void refreshInBackground();
    }, AUTO_REFRESH_INTERVAL_MS);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) void refreshInBackground();
    });
  }

  function bindInventoryToggleKeys() {
    document.addEventListener("keydown", function (event) {
      if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;

      var target = event.target;
      var targetTag = target && target.tagName ? clean(target.tagName).toUpperCase() : "";
      if ((target && target.isContentEditable) || ["INPUT", "TEXTAREA", "SELECT"].indexOf(targetTag) >= 0) {
        return;
      }

      var normalizedKey = clean(event.key).toLowerCase();
      var togglesCreativeInventory = normalizedKey === "tab"
        || event.code === "Tab"
        || normalizedKey === "i"
        || event.code === "KeyI";
      if (!togglesCreativeInventory) return;

      event.preventDefault();
      event.stopImmediatePropagation();
      postDragMessage("vectoplan:creative-inventory-close", null);
    }, true);
  }

  function bindSearch() {
    var input = document.querySelector(SELECTORS.search);
    if (!input) return;
    input.addEventListener("input", function () { state.query = input.value; applySearch(); });
    document.addEventListener("keydown", function (event) {
      if ((event.key === "f" || event.key === "F") && !event.ctrlKey && !event.metaKey && !event.altKey && document.activeElement !== input) {
        var tag = document.activeElement && document.activeElement.tagName ? document.activeElement.tagName : "";
        if (["INPUT", "TEXTAREA", "SELECT"].indexOf(tag) < 0) {
          event.preventDefault();
          input.focus({ preventScroll: true });
        }
      }
    });
  }

  function init() {
    if (state.initialized) return;
    state.initialized = true;
    bindInventoryToggleKeys();
    bindSearch();
    bindUserInventorySelection();
    bindWorldEditSettings();
    bindWorldEditActions();
    document.addEventListener("vectoplan:taxonomy-filter-applied", function () { applySearch(); });
    void load();
    startAutoRefresh();
    postDragMessage(WORLD_EDIT_STATE_REQUEST, null, { reason: "creative-inventory-ready" });
  }

  window[MODULE_NAME] = { init: init, load: load, refresh: refreshInBackground, applySearch: applySearch, getState: function () { return state; } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
