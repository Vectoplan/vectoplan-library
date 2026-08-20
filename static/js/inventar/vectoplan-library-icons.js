// Shared VECTOPLAN library icon system for Creative Library and User Inventory.
(function () {
  "use strict";

  var MODULE_VERSION = "1.1.0";
  var SVG_NS = "http://www.w3.org/2000/svg";

  function record(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function clean(value) {
    try { return String(value == null ? "" : value).trim(); } catch (error) { return ""; }
  }

  function first() {
    for (var index = 0; index < arguments.length; index += 1) {
      var value = clean(arguments[index]);
      if (value) return value;
    }
    return "";
  }

  function normalize(value) {
    return clean(value)
      .toLowerCase()
      .replace(/[ä]/g, "ae")
      .replace(/[ö]/g, "oe")
      .replace(/[ü]/g, "ue")
      .replace(/[ß]/g, "ss")
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  function definitionValues(item) {
    var payload = record(item.payload);
    var metadata = record(item.metadata);
    var payloadMetadata = record(payload.metadata);
    var variant = record(item.selected_variant || item.variant || payload.selected_variant || payload.variant);
    return Object.assign(
      {},
      record(payloadMetadata.definition_values),
      record(metadata.definition_values),
      record(variant.definition_values || variant.definitionValues),
      record(item.definition_values || item.definitionValues)
    );
  }

  function kind(itemValue) {
    var item = record(itemValue);
    var payload = record(item.payload);
    var values = definitionValues(item);
    var explicit = normalize(first(
      item.icon_kind,
      item.iconKind,
      payload.icon_kind,
      payload.iconKind,
      values["inventory.icon_kind"],
      values["geometry.profile_id"],
      values["geometry.primitive_shape"]
    ));
    var identity = normalize([
      explicit,
      item.object_kind,
      payload.object_kind,
      item.domain,
      item.category,
      item.subcategory,
      item.family_id,
      item.vplib_uid,
      item.label,
      item.name,
      payload.family_id,
      payload.label,
      values["material.subtype"]
    ].join(" "));

    if (/window|fenster|thin_window/.test(identity)) return "window";
    if (/door|tuer|innentuer|aussentuer|hinged_door/.test(identity)) return "door";
    if (/pipe|rohr|leitung|conduit/.test(identity)) return "pipe";
    if (/manhole|schacht|ring|vertical_cylinder/.test(identity)) return "cylinder";
    if (/stair|trepp/.test(identity)) return "stair";
    if (/rail|gleis/.test(identity)) return "rail";
    if (/column|stuetze|pfeiler|pfahl/.test(identity)) return "column";
    if (/beam|traeger|balken|schwelle|bordstein/.test(identity)) return "beam";
    if (/wall|wand|spundwand|schlitzwand|gabione/.test(identity)) return "wall";
    if (/slab|decke|platte|estrich|asphalt|abdichtung|planum|schicht/.test(identity)) return "slab";
    return "block";
  }

  function color(itemValue) {
    var item = record(itemValue);
    var payload = record(item.payload);
    var icon = record(item.icon);
    var payloadIcon = record(payload.icon);
    var values = definitionValues(item);
    var candidate = first(
      item.preview_color,
      item.previewColor,
      icon.color,
      payloadIcon.color,
      item.color,
      payload.color,
      values["material.color_hint"]
    );
    if (candidate && (!window.CSS || !window.CSS.supports || window.CSS.supports("color", candidate))) {
      return candidate;
    }
    return "#6386b6";
  }

  var ICON_MARKUP = {
    block: [
      '<path d="M12 25 36 12l24 13-24 13Z" fill="#eef5fc" stroke="#203956" stroke-width="2.4" stroke-linejoin="round"/>',
      '<path d="m12 25 24 13v26L12 51Z" fill="currentColor" stroke="#203956" stroke-width="2.4" stroke-linejoin="round"/>',
      '<path d="m36 38 24-13v26L36 64Z" fill="currentColor" fill-opacity=".68" stroke="#203956" stroke-width="2.4" stroke-linejoin="round"/>',
      '<path d="m17 28 19 10 19-10" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="2" stroke-linecap="round"/>'
    ].join(""),
    wall: [
      '<path d="M8 24 45 13l19 10-37 12Z" fill="#f3f7fc" stroke="#203956" stroke-width="2.2" stroke-linejoin="round"/>',
      '<path d="m27 35 37-12v26L27 62Z" fill="currentColor" stroke="#203956" stroke-width="2.2" stroke-linejoin="round"/>',
      '<path d="M8 24 27 35v27L8 51Z" fill="currentColor" fill-opacity=".67" stroke="#203956" stroke-width="2.2" stroke-linejoin="round"/>',
      '<path d="M33 39 58 31M33 48l25-8M33 56l25-8" fill="none" stroke="#fff" stroke-opacity=".48" stroke-width="1.7" stroke-linecap="round"/>'
    ].join(""),
    slab: [
      '<path d="M7 30 42 15l23 12-36 16Z" fill="#f4f8fc" stroke="#203956" stroke-width="2.3" stroke-linejoin="round"/>',
      '<path d="m29 43 36-16v14L29 57Z" fill="currentColor" stroke="#203956" stroke-width="2.3" stroke-linejoin="round"/>',
      '<path d="M7 30 29 43v14L7 44Z" fill="currentColor" fill-opacity=".65" stroke="#203956" stroke-width="2.3" stroke-linejoin="round"/>',
      '<path d="m13 31 29-12 16 8" fill="none" stroke="#fff" stroke-opacity=".72" stroke-width="2" stroke-linecap="round"/>'
    ].join(""),
    beam: [
      '<path d="M7 31 45 15l20 10-38 17Z" fill="#f3f7fc" stroke="#203956" stroke-width="2.3" stroke-linejoin="round"/>',
      '<path d="m27 42 38-17v15L27 57Z" fill="currentColor" stroke="#203956" stroke-width="2.3" stroke-linejoin="round"/>',
      '<path d="M7 31 27 42v15L7 46Z" fill="currentColor" fill-opacity=".63" stroke="#203956" stroke-width="2.3" stroke-linejoin="round"/>',
      '<path d="m14 32 31-13M31 44l27-12" fill="none" stroke="#fff" stroke-opacity=".48" stroke-width="1.8" stroke-linecap="round"/>'
    ].join(""),
    column: [
      '<path d="m21 17 19-8 13 7-19 8Z" fill="#f3f7fc" stroke="#203956" stroke-width="2.3" stroke-linejoin="round"/>',
      '<path d="m21 17 13 7v39l-13-8Z" fill="currentColor" fill-opacity=".68" stroke="#203956" stroke-width="2.3" stroke-linejoin="round"/>',
      '<path d="m34 24 19-8v39l-19 8Z" fill="currentColor" stroke="#203956" stroke-width="2.3" stroke-linejoin="round"/>',
      '<path d="M39 26v30" stroke="#fff" stroke-opacity=".48" stroke-width="2" stroke-linecap="round"/>'
    ].join(""),
    cylinder: [
      '<path d="M17 20c0-7 38-7 38 0v32c0 8-38 8-38 0Z" fill="currentColor" stroke="#203956" stroke-width="2.3"/>',
      '<ellipse cx="36" cy="20" rx="19" ry="8" fill="#f1f6fb" stroke="#203956" stroke-width="2.3"/>',
      '<ellipse cx="36" cy="20" rx="11" ry="4.5" fill="#9fb2c7" stroke="#203956" stroke-width="1.8"/>',
      '<path d="M22 26v23" stroke="#fff" stroke-opacity=".5" stroke-width="2.2" stroke-linecap="round"/>'
    ].join(""),
    pipe: [
      '<path d="M13 46c0-11 8-19 19-19h14" fill="none" stroke="#203956" stroke-width="18" stroke-linecap="round" stroke-linejoin="round"/>',
      '<path d="M13 46c0-11 8-19 19-19h14" fill="none" stroke="currentColor" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/>',
      '<path d="M17 43c2-7 8-11 15-11h13" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="2.5" stroke-linecap="round"/>',
      '<ellipse cx="48" cy="27" rx="9" ry="11" fill="#e8f0f7" stroke="#203956" stroke-width="2.3"/>',
      '<ellipse cx="48" cy="27" rx="4.5" ry="6" fill="#637991"/>'
    ].join(""),
    window: [
      '<path d="M14 13h44v47H14Z" fill="#dff5ff" stroke="#203956" stroke-width="3.2" stroke-linejoin="round"/>',
      '<path d="M36 15v43M16 36h40" fill="none" stroke="#203956" stroke-width="3"/>',
      '<path d="m19 18 12 0-12 13ZM39 39h14v14Z" fill="#fff" fill-opacity=".78"/>',
      '<path d="M10 61h52" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>'
    ].join(""),
    door: [
      '<path d="M13 62V12h38v50" fill="#eef4fa" stroke="#203956" stroke-width="3.2" stroke-linejoin="round"/>',
      '<path d="m19 17 31 5v38l-31 3Z" fill="currentColor" stroke="#203956" stroke-width="2.3" stroke-linejoin="round"/>',
      '<path d="M45 39a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" fill="#ffd56a" stroke="#203956" stroke-width="1.5"/>',
      '<path d="M51 61c7-2 11-7 13-13" fill="none" stroke="#4d72a0" stroke-width="2" stroke-linecap="round" stroke-dasharray="3 3"/>'
    ].join(""),
    stair: [
      '<path d="M8 58h14V47h12V36h12V25h17v33Z" fill="currentColor" stroke="#203956" stroke-width="2.3" stroke-linejoin="round"/>',
      '<path d="M22 47h12M34 36h12M46 25h17" fill="none" stroke="#fff" stroke-opacity=".62" stroke-width="2"/>',
      '<path d="M11 52 57 17" fill="none" stroke="#203956" stroke-width="2.4" stroke-linecap="round"/>',
      '<path d="m52 17 7-1-2 7" fill="none" stroke="#203956" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
    ].join(""),
    rail: [
      '<path d="m22 9-9 54M50 9l9 54" fill="none" stroke="#203956" stroke-width="5" stroke-linecap="round"/>',
      '<path d="M20 18h32M18 31h36M16 45h40M14 58h44" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/>',
      '<path d="M22 18h28M20 31h32M18 45h36" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="1.5" stroke-linecap="round"/>'
    ].join("")
  };

  /* Purpose-built World Edit symbols. They share one stroke language instead
     of mixing font glyphs whose shape changes with the operating system. */
  var TOOL_MARKUP = {
    selection: '<path d="M12 27V13h14M46 13h14v14M60 45v14H46M26 59H12V45"/><path d="m27 28 9-5 9 5v11l-9 5-9-5Z"/><path d="m27 28 9 5 9-5M36 33v11"/>',
    room: '<path d="M14 13h44v46H14Z"/><path d="M35 13v19H14M35 32h23M35 46v13M35 46h12v13"/><path d="M14 43h10v16"/>',
    parcel: '<path d="m13 25 17-13 27 8 3 30-20 10-25-8Z"/><path d="m20 29 15-9 17 6-1 18-13 7-17-6Z" stroke-dasharray="4 4"/>',
    "parcel-grid": '<path d="M13 13h46v46H13Z"/><path d="M28 13v46M44 13v46M13 28h46M13 44h46"/><path d="M10 35h52M36 10v52" stroke="#52c5e8" stroke-width="3.5"/>',
    paint: '<path d="m17 50 28-28 10 10-28 28H17Z"/><path d="m41 18 5-5 13 13-5 5"/><path d="M17 50c-7 1-8 8-3 10 5 2 11-1 13-5" fill="#52c5e8" stroke="none"/>',
    sculpt: '<path d="M10 52c9-19 17-7 25-23 8 18 16 6 27 23"/><path d="M14 59h44"/><path d="M22 26v-9m-4 4 4-4 4 4M51 27v-9m-4 5 4-5 4 5" stroke="#52c5e8"/>',
    shape: '<rect x="12" y="16" width="19" height="19" rx="2"/><circle cx="49" cy="26" r="10"/><path d="m23 58 12-20 12 20Z"/>',
    entity: '<circle cx="36" cy="20" r="8"/><path d="M22 58c1-16 7-25 14-25s13 9 14 25Z"/><path d="M27 43h18" stroke="#52c5e8"/>',
    "trigger-volume": '<path d="m14 24 22-11 22 11v26L36 61 14 50Z" stroke-dasharray="5 4"/><path d="m39 23-11 18h9l-4 12 13-19h-9Z" fill="#52c5e8" stroke="none"/>',
    "ruler-laser": '<path d="m14 50 34-34 10 10-34 34Z"/><path d="m25 45 5 5m1-17 5 5m1-17 5 5"/><path d="M10 17h19M10 17l6-6m-6 6 6 6" stroke="#52c5e8"/>',
    "copy-transform": '<rect x="12" y="23" width="29" height="29" rx="3"/><rect x="31" y="12" width="29" height="29" rx="3"/><path d="M24 60h31m0 0-6-6m6 6-6 6" stroke="#52c5e8"/>',
    "extrude-flood": '<path d="m13 43 23-11 23 11-23 12Z"/><path d="M36 32V12m-7 7 7-7 7 7" stroke="#52c5e8"/><path d="M13 55c7-5 14 5 22 0s15 5 24 0"/>',
    boulder: '<path d="m14 42 7-20 18-9 17 12 3 19-13 15-21-2Z"/><path d="m21 22 15 10 20-7M36 32l10 27" stroke="#52c5e8"/>',
    cave: '<path d="M9 58c4-30 14-45 27-45s23 15 27 45Z"/><path d="M24 58c1-17 5-26 12-26s11 9 12 26Z" fill="#203956"/><path d="M9 58h54"/>',
    mountain: '<path d="m8 58 19-37 9 14 8-16 20 39Z"/><path d="m20 35 7-14 7 11-7-3Z" fill="#52c5e8" stroke="none"/><path d="m37 34 7-15 9 18-9-5Z" fill="#52c5e8" stroke="none"/>',
    tentacle: '<path d="M12 55c12-2 5-23 18-24 11-1 6 15 17 14 10-1 5-18 13-28"/><circle cx="12" cy="55" r="4" fill="#52c5e8"/><circle cx="30" cy="31" r="4" fill="#52c5e8"/><circle cx="47" cy="45" r="4" fill="#52c5e8"/>',
    "lava-cracks": '<path d="m39 9-14 22 11 3-12 29 25-34-12-3Z" fill="#52c5e8"/><path d="m25 31-12-8m23 11 13 10m-13-10 1 15"/>',
    "grass-erosion": '<path d="M13 57c11-8 17 5 28-3 8-6 13 1 20-4M12 46c10-7 18 4 28-3 8-6 14 0 21-5"/><path d="M22 42V20m0 13-7-8m7 4 8-10M47 39V17m0 13-8-8m8 4 7-7" stroke="#52c5e8"/>',
    "path-wall-layer": '<path d="M12 57c8-29 18-41 48-42"/><path d="M22 60c6-22 16-31 39-34"/><path d="M17 43h16m-9-13h16m-5-11h16" stroke="#52c5e8"/>',
    revolve: '<path d="M36 17v42M28 20h16M28 56h16"/><path d="M18 38c0-13 8-23 18-23M18 38l-6-7m6 7 7-6M54 34c0 13-8 23-18 23m18-23 6 7m-6-7-7 6" stroke="#52c5e8"/>'
  };

  function createTool(toolValue, options) {
    var tool = record(toolValue);
    var toolId = normalize(typeof toolValue === "string" ? toolValue : first(tool.id, tool.world_edit_tool, tool.toolId));
    var settings = record(options);
    var wrapper = document.createElement(settings.tagName || "span");
    wrapper.className = clean(settings.className) || "vp-library-tool-icon";
    wrapper.classList.add("vp-library-tool-icon", "vp-library-tool-icon--" + toolId);
    wrapper.setAttribute("aria-hidden", "true");
    wrapper.setAttribute("data-library-tool-icon", toolId);

    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 72 72");
    svg.setAttribute("focusable", "false");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "3");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.innerHTML = TOOL_MARKUP[toolId] || TOOL_MARKUP[toolId.replace(/_/g, "-")] || TOOL_MARKUP.shape;
    wrapper.appendChild(svg);
    return wrapper;
  }

  function create(item, options) {
    var settings = record(options);
    var iconKind = kind(item);
    var wrapper = document.createElement(settings.tagName || "span");
    wrapper.className = clean(settings.className) || "vp-library-icon";
    wrapper.classList.add("vp-library-icon", "vp-library-icon--" + iconKind);
    wrapper.style.color = color(item);
    wrapper.setAttribute("aria-hidden", "true");
    wrapper.setAttribute("data-library-icon-kind", iconKind);

    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 72 72");
    svg.setAttribute("focusable", "false");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = ICON_MARKUP[iconKind] || ICON_MARKUP.block;
    wrapper.appendChild(svg);
    return wrapper;
  }

  var publicApi = Object.freeze({
    version: MODULE_VERSION,
    kind: kind,
    color: color,
    create: create,
    createTool: createTool
  });

  /* Inventory frames refresh their contents without navigating. Keeping the
     renderer as a stable, non-configurable page capability prevents cleanup
     code from turning later refreshes back into the legacy fallback icons. */
  if (!window.VectoplanLibraryIcons) {
    Object.defineProperty(window, "VectoplanLibraryIcons", {
      configurable: false,
      enumerable: false,
      writable: false,
      value: publicApi
    });
  }
})();
