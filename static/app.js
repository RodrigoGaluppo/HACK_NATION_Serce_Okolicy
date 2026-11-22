"use strict";

const byId = (id) => document.getElementById(id);
const results = byId("results");
const search = byId("search");
const radius = byId("radius");
const available = byId("available-only");
const onlyTagged = byId("only-tagged");
const sourceFilter = byId("source-filter");
const confidenceFilter = byId("confidence-filter");
const summary = byId("results-summary");
const notice = byId("notice");

const sourceNames = new Map([
  ["osm", "OpenAEDMap / OpenStreetMap"],
  ["krosno", "Miasto Krosno (dane.gov.pl)"],
  ["przemysl", "Miasto Przemyśl (dane.gov.pl)"],
  ["marki", "Miasto Marki (dane.gov.pl)"],
  ["warszawa", "Urząd m.st. Warszawy (SCB)"],
  ["inpost", "Sieć Paczkomat® InPost AED"],
  ["bydgoszcz", "Miasto Bydgoszcz"],
  ["trojmiasto", "Otwarte Dane Trójmiasto"],
  ["krakow", "MSIP Kraków"],
  ["wroclaw", "Otwarte Dane Wrocław"],
  ["poznan", "SIP Poznań"],
  ["katowice_gzm", "Otwarte Dane GZM & Katowice"],
  ["pkp_transport", "PKP S.A. & Lotniska"],
  ["ratuj_z_sercem", "Sieć Ratuj z Sercem · OSP"],
  ["operator", "Zatwierdzone zgłoszenie operatora"],
  ["pwa_offline_tag", "Oznaczenie terenowe PWA"],
]);

const number = new Intl.NumberFormat("pl-PL");
const decimals = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 1 });
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");

let center = { lat: 52.2297, lon: 21.0122 };
let items = [];
let controller;
let debounce;
let selected;
let remoteTiles;
let googleMap;
let googlePins = [];
let googleConfig;
let simulatedOffline = false;
let operational = navigator.onLine;
let savedPack;
let usingGoogle = false;
let forceVectorJS = false;
let mapTaggingMode = false;
let deferredInstallPrompt = null;
let viewportMode = false;
let mapInteraction = false;
let moveTimer;
let hasStoredView = false;
let initialLookup = true;

try {
  const previous = JSON.parse(sessionStorage.getItem("aed-map-view") || localStorage.getItem("aed-last-view"));
  if (previous && Number.isFinite(previous.center?.lat) && Number.isFinite(previous.center?.lon)) {
    hasStoredView = true;
    center = previous.center;
    search.value = previous.query || "";
    radius.value = previous.radius || "30";
    available.checked = previous.available ?? true;
    onlyTagged.checked = previous.onlyTagged ?? false;
  }
} catch {
  // Use default view when storage is unavailable
}

function element(tag, text = "", className = "") {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

const map = L.map("local-map", {
  minZoom: 4,
  maxZoom: 19,
  zoomAnimation: !reducedMotion.matches,
}).setView([center.lat, center.lon], 12);

map.attributionControl.addAttribution(
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Serce Okolicy · dane.gov.pl'
);
map.createPane("borders").style.zIndex = 150;
map.createPane("vectorJS").style.zIndex = 165;
const vectorJSLayer = L.layerGroup().addTo(map);
const points = L.layerGroup().addTo(map);

// 1. Load Poland boundaries GeoJSON
fetch("/vendor/boundaries.geojson")
  .then((response) => response.json())
  .then((geo) => {
    L.geoJSON(geo, {
      pane: "borders",
      interactive: false,
      style: { color: "#5e8c72", weight: 1.5, fillColor: "#dce8dc", fillOpacity: 0.85 },
    }).addTo(map);
  })
  .catch(() => {});

// 2. Build Offline JS Vector Map Layer from /video/geo.js (FilmGeo) + Polish reference cities
function buildOfflineJSVectorBasemap() {
  vectorJSLayer.clearLayers();
  const geo = window.FilmGeo;
  // Major Polish reference cities for offline navigation
  const polishCities = [
    ["Warszawa", 52.2297, 21.0122],
    ["Bydgoszcz", 53.1235, 18.0084],
    ["Kraków", 50.0647, 19.9450],
    ["Wrocław", 51.1079, 17.0385],
    ["Poznań", 52.4064, 16.9252],
    ["Gdańsk", 54.3520, 18.6466],
    ["Gdynia", 54.5189, 18.5305],
    ["Łódź", 51.7592, 19.4560],
    ["Katowice", 50.2649, 19.0238],
    ["Szczecin", 53.4285, 14.5528],
    ["Lublin", 51.2465, 22.5684],
    ["Białystok", 53.1325, 23.1688],
    ["Rzeszów", 50.0412, 21.9991],
    ["Krosno", 49.6884, 21.7706],
    ["Przemyśl", 49.7835, 22.7678],
    ["Marki", 52.3215, 21.1050],
    ["Toruń", 53.0138, 18.5984],
  ];

  for (const [name, lat, lon] of polishCities) {
    const cityDot = L.circleMarker([lat, lon], {
      pane: "vectorJS",
      radius: 3.5,
      interactive: false,
      color: "#0b3928",
      weight: 1,
      fillColor: "#b6ff9e",
      fillOpacity: 0.7,
    });
    cityDot.bindTooltip(name, {
      permanent: true,
      direction: "right",
      offset: [5, 0],
      className: "offline-city-label",
    });
    vectorJSLayer.addLayer(cityDot);
  }

  if (!geo) return;
  // Poland border from FilmGeo
  if (Array.isArray(geo.border) && geo.border.length) {
    const borderLatLngs = geo.border.map(([lon, lat]) => [lat, lon]);
    L.polygon(borderLatLngs, {
      pane: "vectorJS",
      interactive: false,
      color: "#00843d",
      weight: 2,
      fillColor: "#d5e6d7",
      fillOpacity: 0.35,
    }).addTo(vectorJSLayer);
  }

  // Local high-detail street/building/water/rail vector geometry from FilmGeo (Bydgoszcz showcase area)
  if (geo.local && Array.isArray(geo.port)) {
    const [portLon, portLat] = geo.port;
    const unitX = 111240 * Math.cos((portLat * Math.PI) / 180);
    const unitY = 111240;
    const toLatLng = ([dx, dy]) => [portLat - dy / unitY, portLon + dx / unitX];

    const vectorStyles = [
      ["water", { color: "#416c6b", weight: 1, fillColor: "#6ca09e", fillOpacity: 0.65 }, true],
      ["park", { color: "#8ab88a", weight: 1, fillColor: "#c5deb8", fillOpacity: 0.6 }, true],
      ["buildings", { color: "#9c9c8c", weight: 0.8, fillColor: "#cdc9b8", fillOpacity: 0.75 }, true],
      ["roads", { color: "#ffffff", weight: 3.2, opacity: 0.92 }, false],
      ["minor", { color: "#f6f2e5", weight: 1.6, opacity: 0.8 }, false],
      ["rail", { color: "#6e7a72", weight: 1.4, dashArray: "4,4", opacity: 0.85 }, false],
    ];

    for (const [key, style, isPoly] of vectorStyles) {
      const shapes = geo.local[key] || [];
      for (const pts of shapes) {
        if (!pts || pts.length < 2) continue;
        const latlngs = pts.map(toLatLng);
        const layer = isPoly
          ? L.polygon(latlngs, { pane: "vectorJS", interactive: false, ...style })
          : L.polyline(latlngs, { pane: "vectorJS", interactive: false, ...style });
        vectorJSLayer.addLayer(layer);
      }
    }
  }
}

buildOfflineJSVectorBasemap();
window.AEDOfflineMap?.init(map);
L.control.scale({ imperial: false }).addTo(map);

function isEffectiveOnline() {
  return navigator.onLine && !simulatedOffline;
}

function updateNetworkUI(online) {
  const pill = byId("net-pill");
  const label = byId("net-pill-label");
  const banner = byId("offline-banner");
  const simBtn = byId("toggle-offline-sim");
  const liveDot = byId("map-live-dot");

  pill.className = "net-pill " + (online ? "online" : "offline");
  label.textContent = online
    ? "Online"
    : simulatedOffline
    ? "Tryb lokalny"
    : "Offline";
  banner.hidden = online;
  liveDot.classList.toggle("offline", !online);
  simBtn.classList.toggle("active-sim", simulatedOffline);
  simBtn.textContent = simulatedOffline ? "Wróć do Online" : "Tryb Offline";
}

function basemap(online) {
  operational = online;
  window.AEDOfflineMap?.setOffline(!online || forceVectorJS);
  updateNetworkUI(online);
  if (!online || forceVectorJS) {
    if (remoteTiles && map.hasLayer(remoteTiles)) map.removeLayer(remoteTiles);
    if (!online) showGoogle(false);
    if (!map.hasLayer(vectorJSLayer)) vectorJSLayer.addTo(map);
    byId("map-description").textContent = !online
      ? (window.AEDOfflineMap?.hasSavedMap ? "Zapisana mapa ulic · poza obszarem mapa uproszczona" : "Mapa uproszczona · zapisane punkty")
      : "Mapa uproszczona · dostępna offline";
    return;
  }
  if (!remoteTiles) {
    remoteTiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      maxNativeZoom: 19,
    });
    remoteTiles.on("tileerror", () => {
      if (!usingGoogle && operational) {
        byId("map-description").textContent = "Podkład wektorowy JS + buforowane kafelki";
      }
    });
    remoteTiles.on("tileload", () => {
      if (!usingGoogle && operational && !forceVectorJS) {
        byId("map-description").textContent = "OpenStreetMap · przesuwaj, aby szukać";
      }
    });
  }
  if (!map.hasLayer(remoteTiles)) remoteTiles.addTo(map);
  byId("map-description").textContent = usingGoogle
    ? "Google Maps · lokalne dane AED"
    : "OpenStreetMap · przesuwaj, aby szukać";
}

basemap(isEffectiveOnline());

function tone(item) {
  const c = Number(item.confidence ?? 0);
  return c >= 70 ? "high" : c >= 45 ? "medium" : "low";
}
const toneLabel = { high: "Wysoka pewność", medium: "Średnia pewność", low: "Niska pewność" };
const toneColor = { high: "#00843d", medium: "#d49b00", low: "#d9483b" };
const lockLabels = {
  unlocked: "Szafka otwarta",
  locked: "Szafka zamknięta",
  not_applicable: "Bez szafki",
  unknown: "Zamek nieznany",
};

function updateTaggedCount() {
  const tags = window.offlineData ? window.offlineData.getTags() : [];
  const el = byId("stat-tagged");
  if (el) el.textContent = number.format(tags.length);
}

function popupDetails(item) {
  const panel = element("div", "", "point-details");
  const access = ["public", "yes", "designated"].includes(item.access_type || item.access)
    ? "Publiczny"
    : (item.access_type || item.access) && (item.access_type || item.access) !== "unknown"
    ? "Ograniczony"
    : "Nieznany";

  panel.append(
    element("p", `ID: ${item.aed_id || item.id}`),
    element("p", `Dostęp: ${access}${item.opening_hours || item.hours ? " · Godziny: " + (item.opening_hours || item.hours) : ""}`),
  );
  if (item.placement) panel.append(element("p", `Szafka AED: ${item.placement}${item.level ? " (poziom: " + item.level + ")" : ""}`));
  if (item.cabinet_lock_status && item.cabinet_lock_status !== "unknown") {
    panel.append(element("p", `Stan zamka: ${lockLabels[item.cabinet_lock_status] || item.cabinet_lock_status}`));
  }
  if (item.access_instructions) panel.append(element("p", `Wskazówki: ${item.access_instructions}`));
  if (item.public_operator_name) panel.append(element("p", `Dysponent: ${item.public_operator_name}`));
  for (const [field, label] of [["location_checked_on", "Lokalizacja"], ["access_checked_on", "Dostęp"], ["readiness_checked_on", "Sprawność"]]) {
    panel.append(element("p", `${label} · sprawdzono: ${item[field] || "brak daty"}`));
  }
  panel.append(element("p", `Sprawność: ${item.readiness_status === "ready" ? "potwierdzona na dzień kontroli" : item.readiness_status === "not_ready" ? "zgłoszono niesprawność" : "nieznana"}`));

  const srcList = (item.source_ids || item.sources || []).map((id) => sourceNames.get(id) || id).join(", ");
  panel.append(element("p", `Źródła: ${srcList || "Rejestr lokalny"}`));

  const reasons = element("ul");
  for (const reason of item.confidence_reasons || []) {
    reasons.append(element("li", reason));
  }
  if (reasons.childElementCount) panel.append(reasons);

  const provenance = element("details");
  const fields = element("ul");
  for (const [key, label] of Object.entries({
    coordinates: "Współrzędne WGS84",
    site_name: "Nazwa obiektu",
    address: "Adres",
    placement: "Lokalizacja szafki",
    access_type: "Rodzaj dostępu",
    opening_hours: "Godziny dostępności",
    location_checked_on: "Data weryfikacji",
  })) {
    const source = item.field_sources?.[key];
    if (source) fields.append(element("li", `${label} → ${sourceNames.get(source) || source}`));
  }
  if (fields.childElementCount) {
    provenance.append(element("summary", "Proweniencja pól (dane.gov.pl)"), fields);
    panel.append(provenance);
  }

  const actions = element("div", "", "point-actions");
  const tagBtn = element("button", "Oznacz / popraw dane", "button compact mint-btn");
  tagBtn.type = "button";
  tagBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    openTagModalForItem(item);
  });
  actions.append(tagBtn);

  const exportOneBtn = element("button", "GeoJSON punktu", "button compact secondary");
  exportOneBtn.type = "button";
  exportOneBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    downloadBlob(
      JSON.stringify(window.offlineData.toCanonicalGeoJSON([item]), null, 2),
      `aed-${(item.aed_id || item.id).replace(/[^a-zA-Z0-9_-]/g, "_")}.geojson`,
      "application/geo+json"
    );
  });
  actions.append(exportOneBtn);

  if (item.is_user_tagged) {
    const delBtn = element("button", "Usuń lokalny tag", "button compact secondary");
    delBtn.type = "button";
    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      try { window.offlineData.removeTag(item.aed_id || item.id); } catch (err) { notice.textContent = err.message; return; }
      updateTaggedCount();
      update(false);
    });
    actions.append(delBtn);
  }

  panel.append(actions);
  return panel;
}

function select(item, pan = true, reveal = false) {
  selected = item.id;
  for (const row of results.children) {
    const active = row.dataset.id === selected;
    row.classList.toggle("active", active);
    const button = row.querySelector(".result-button");
    if (button) button.setAttribute("aria-expanded", String(active));
    const detail = row.querySelector(".point-details");
    if (detail) detail.hidden = !active;
    if (active && reveal && location.pathname !== "/mapa") {
      row.scrollIntoView({ block: "nearest", behavior: reducedMotion.matches ? "instant" : "smooth" });
    }
  }
  if (!pan) return;
  if (usingGoogle && googleMap) {
    googleMap.panTo({ lat: item.lat, lng: item.lon });
    return;
  }
  map.panTo([item.lat, item.lon], { animate: !reducedMotion.matches });
  points.eachLayer((layer) => {
    if (layer.itemId === item.id) layer.openPopup();
  });
}

function render(fit) {
  const previous = selected;
  selected = undefined;
  results.replaceChildren();
  points.clearLayers();
  const bounds = [];

  if (!items.length) {
    results.append(
      element("li", "Brak punktów spełniających kryteria. Zmień promień, filtr lub oznacz nowy punkt AED.", "empty")
    );
  }

  for (const item of items) {
    if (!Number.isFinite(item.lat) || !Number.isFinite(item.lon)) continue;
    const itemTone = tone(item);
    const row = element("li", "", "result");
    row.dataset.id = item.id;

    const button = element("button", "", "result-button");
    button.type = "button";
    button.setAttribute("aria-expanded", "false");

    const topLine = element("div", "", "result-header-line");
    topLine.append(element("strong", item.site_name || item.name));
    if (item.distance_km != null) {
      topLine.append(element("span", `${decimals.format(item.distance_km)} km`, "distance"));
    }
    button.append(
      topLine,
      element("span", item.address || item.municipality || "Polska", "address")
    );
    if (item.placement) {
      button.append(element("span", `Szafka: ${item.placement}`, "placement-preview"));
    }

    const badges = element("div", "", "card-badges");
    badges.append(
      element("span", `${item.confidence ?? 0}/100 · ${toneLabel[itemTone]}`, `conf-badge ${itemTone}`)
    );
    if (item.opening_hours || item.hours) {
      badges.append(element("span", item.opening_hours || item.hours, "meta-pill hours-pill"));
    }
    if (item.cabinet_lock_status && item.cabinet_lock_status !== "unknown") {
      badges.append(element("span", lockLabels[item.cabinet_lock_status] || item.cabinet_lock_status, "meta-pill"));
    }
    if (item.is_user_tagged || (item.source_ids || item.sources || []).includes("pwa_offline_tag")) {
      badges.append(element("span", "TAG PWA", "meta-pill tag-pill"));
    }
    button.append(badges);

    const detail = popupDetails(item);
    detail.hidden = true;
    row.append(button, detail);
    button.addEventListener("click", () => select(item));
    results.append(row);

    const isTagged = item.is_user_tagged || (item.source_ids || item.sources || []).includes("pwa_offline_tag");
    const pin = L.circleMarker([item.lat, item.lon], {
      radius: isTagged ? 9 : 8,
      color: isTagged ? "#b6ff9e" : "#ffffff",
      weight: isTagged ? 3 : 2,
      fillColor: isTagged ? "#1d4ed8" : toneColor[itemTone],
      fillOpacity: 1,
    });
    pin.itemId = item.id;
    pin.bindPopup(() => {
      const wrap = element("div");
      wrap.append(
        element("strong", item.site_name || item.name),
        element("p", `${item.confidence ?? 0}/100 · ${toneLabel[itemTone]}`, `conf-badge ${itemTone}`),
        popupDetails(item)
      );
      return wrap;
    });
    pin.on("click", () => select(item, false, true));
    points.addLayer(pin);
    bounds.push([item.lat, item.lon]);
  }

  if (fit && bounds.length) {
    map.fitBounds(bounds, { maxZoom: 14, padding: [28, 28], animate: false });
  }
  if (usingGoogle) renderGoogle(fit);
  const restore = items.find((item) => item.id === previous);
  if (restore) select(restore, false);
}

function folded(text) {
  return String(text || "")
    .toLowerCase()
    .replaceAll("ł", "l")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "");
}

function mergeWithLocalTags(baseItems, query) {
  const localTags = window.offlineData ? window.offlineData.getTags() : [];
  const minConf = Number(confidenceFilter.value || 0);
  const srcFilter = sourceFilter.value;
  const words = folded(query).trim().split(/\s+/).filter(Boolean);

  const filterItem = (item) => {
    if (!Number.isFinite(item.lat) || !Number.isFinite(item.lon)) return false;
    if (viewportMode && !usingGoogle && !map.getBounds().contains([item.lat, item.lon])) return false;
    if (onlyTagged.checked && !item.is_user_tagged && !(item.source_ids || item.sources || []).includes("pwa_offline_tag")) {
      return false;
    }
    if (available.checked && !["yes", "public", "designated"].includes(item.access_type || item.access)) {
      return false;
    }
    if (minConf > 0 && Number(item.confidence ?? 0) < minConf) {
      return false;
    }
    if (srcFilter && !(item.source_ids || item.sources || []).includes(srcFilter)) {
      return false;
    }
    if (words.length) {
      const hay = folded([item.site_name, item.name, item.address, item.municipality, item.placement, item.aed_id].join(" "));
      if (!words.every((w) => hay.includes(w))) return false;
    }
    return true;
  };

  const byIdMap = new Map();
  for (const tag of localTags) {
    if (!Number.isFinite(tag.lat) || !Number.isFinite(tag.lon)) continue;
    const dist = map.distance([center.lat, center.lon], [tag.lat, tag.lon]) / 1000;
    const withDist = { ...tag, distance_km: Number(dist.toFixed(2)) };
    if (filterItem(withDist) && (query || viewportMode || withDist.distance_km <= Number(radius.value))) {
      byIdMap.set(withDist.aed_id || withDist.id, withDist);
    }
  }
  for (const raw of baseItems) {
    const item = window.offlineData ? window.offlineData.normalizeItem(raw) : raw;
    if (!Number.isFinite(item.lat) || !Number.isFinite(item.lon)) continue;
    const dist = Number((map.distance([center.lat, center.lon], [item.lat, item.lon]) / 1000).toFixed(2));
    const withDist = { ...item, distance_km: dist };
    if (filterItem(withDist) && (query || withDist.distance_km <= Number(radius.value) || viewportMode) && !byIdMap.has(withDist.aed_id || withDist.id)) {
      byIdMap.set(withDist.aed_id || withDist.id, withDist);
    }
  }

  const combined = Array.from(byIdMap.values());
  combined.sort((a, b) => (a.distance_km ?? 9999) - (b.distance_km ?? 9999));
  return combined;
}

async function update(fit = true) {
  const firstLookup = initialLookup; initialLookup = false;
  controller?.abort();
  const current = new AbortController();
  controller = current;
  const query = search.value.trim();
  const params = new URLSearchParams({
    limit: "80",
    radius_km: radius.value,
    available: available.checked ? "1" : "0",
    min_confidence: confidenceFilter.value || "0",
  });
  if (sourceFilter.value) {
    params.set("source", sourceFilter.value);
  }
  if (query) params.set("q", query);
  else {
    params.set("lat", center.lat);
    params.set("lon", center.lon);
  }

  if (viewportMode && !usingGoogle && !query) {
    const b = map.getBounds();
    params.set("west", Math.max(-180, b.getWest())); params.set("east", Math.min(180, b.getEast()));
    params.set("south", Math.max(-90, b.getSouth())); params.set("north", Math.min(90, b.getNorth()));
    params.set("radius_km", Math.min(600, Math.max(0.1, map.distance(map.getCenter(), b.getNorthEast()) / 1000 + 1)));
  }
  results.setAttribute("aria-busy", "true");
  summary.textContent = "Wczytywanie punktów AED…";
  const timer = setTimeout(() => current.abort(), 5000);

  try {
    if (!isEffectiveOnline()) throw new Error("offline");
    const response = await fetch("/api/aeds?" + params, { signal: current.signal });
    if (!response.ok) throw new Error("lookup");
    const data = await response.json();
    if (controller !== current) return;
    if (data.center) center = data.center;
    basemap(response.headers.get("X-AED-Offline") !== "1");
    const merged = mergeWithLocalTags(data.items || [], query);
    items = merged.slice(0, 80);
    const localTagCount = window.offlineData.getTags().length;
    summary.textContent = `${number.format(items.length)} punktów w wynikach`;
    window.offlineData.write("last", {
      items: data.items,
      center,
      radius: Number(radius.value),
      date: new Date().toISOString(),
    }).catch(() => {});
  } catch {
    if (controller !== current) return;
    basemap(false);
    const pack = await window.offlineData.read().catch(() => null);
    if (controller !== current) return;
    if (firstLookup && !hasStoredView && pack?.center && Number.isFinite(pack.center.lat) && Number.isFinite(pack.center.lon)) {
      center = pack.center;
      const choices = [...radius.options].map(option => Number(option.value));
      radius.value = String(choices.find(value => value >= pack.radius) || 500);
      map.setView([center.lat, center.lon], 12, {animate:false});
    }
    const cachedItems = pack?.items || [];
    const merged = mergeWithLocalTags(cachedItems, query);
    items = merged.slice(0, 120);
    const suffix = pack?.date
      ? ` · pamięć Cache z ${new Date(pack.date).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}`
      : " · lokalne punkty";
    summary.textContent = `Offline · ${number.format(items.length)} punktów${suffix}`;
  } finally {
    clearTimeout(timer);
    if (controller === current) {
      results.setAttribute("aria-busy", "false");
      updateTaggedCount();
      try { localStorage.setItem("aed-last-view", JSON.stringify({center, radius:radius.value, available:available.checked, onlyTagged:onlyTagged.checked})); } catch {}
      render(fit);
    }
  }
}

function activeCenter() {
  const current = usingGoogle && googleMap ? googleMap.getCenter() : map.getCenter();
  return usingGoogle && googleMap
    ? { lat: current.lat(), lon: current.lng() }
    : { lat: current.lat, lon: current.lng };
}

function showGoogle(enabled) {
  usingGoogle = enabled && Boolean(googleMap);
  byId("google-map").hidden = !usingGoogle;
  byId("local-map").hidden = usingGoogle;
  byId("google-switch").textContent = usingGoogle ? "OpenStreetMap" : "Google Maps";
  if (!usingGoogle) requestAnimationFrame(() => map.invalidateSize());
}

function renderGoogle(fit) {
  for (const pin of googlePins) pin.map = null;
  googlePins = [];
  const bounds = new google.maps.LatLngBounds();
  const popup = new google.maps.InfoWindow();
  for (const item of items) {
    const position = { lat: item.lat, lng: item.lon };
    const pinContent = new google.maps.marker.PinElement({
      background: toneColor[tone(item)],
      borderColor: "#fff",
      glyphColor: "#fff",
    });
    const pin = new google.maps.marker.AdvancedMarkerElement({
      map: googleMap,
      position,
      title: item.name,
      content: pinContent.element,
    });
    pin.addListener("click", () => {
      select(item, false, true);
      popup.setContent(popupDetails(item));
      popup.open({ map: googleMap, anchor: pin });
    });
    googlePins.push(pin);
    bounds.extend(position);
  }
  if (fit && items.length > 1) googleMap.fitBounds(bounds, 36);
  else if (fit && items.length === 1) {
    googleMap.setCenter(bounds.getCenter());
    googleMap.setZoom(14);
  }
}

async function startGoogle() {
  if (usingGoogle) {
    showGoogle(false);
    basemap(isEffectiveOnline());
    return;
  }
  if (!isEffectiveOnline() || !googleConfig?.google_maps_key) {
    notice.textContent = "Google Maps wymaga połączenia z internetem i klucza API.";
    return;
  }
  try {
    if (!googleMap) {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(reject, 8000);
        window.aedGoogleReady = () => { clearTimeout(timer); resolve(); };
        window.gm_authFailure = () => {
          clearTimeout(timer);
          googleMap = null;
          showGoogle(false);
          notice.textContent = "Google Maps odrzucił klucz. Używany jest podkład OpenStreetMap.";
          reject();
        };
        const script = document.createElement("script");
        const params = new URLSearchParams({
          key: googleConfig.google_maps_key,
          callback: "aedGoogleReady",
          loading: "async",
          language: "pl",
        });
        script.src = "https://maps.googleapis.com/maps/api/js?" + params;
        script.onerror = () => { clearTimeout(timer); reject(); };
        document.head.append(script);
      });
      await Promise.all([google.maps.importLibrary("maps"), google.maps.importLibrary("marker")]);
      googleMap = new google.maps.Map(byId("google-map"), {
        center,
        zoom: 12,
        mapId: googleConfig.google_maps_map_id || "DEMO_MAP_ID",
        streetViewControl: false,
      });
    }
    showGoogle(true);
    byId("map-description").textContent = "Google Maps · lokalne dane AED";
    renderGoogle(true);
  } catch {
    showGoogle(false);
    notice.textContent = "Google Maps jest niedostępny. Użyj OpenStreetMap.";
  }
}

// Search & Filter Listeners
byId("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(debounce);
  viewportMode = false;
  update();
});
search.addEventListener("input", () => {
  clearTimeout(debounce);
  viewportMode = false;
  debounce = setTimeout(update, 320);
});
radius.addEventListener("change", () => update());
available.addEventListener("change", () => update());
onlyTagged.addEventListener("change", () => update(false));
sourceFilter.addEventListener("change", () => update());
confidenceFilter.addEventListener("change", () => update());

for (const chip of document.querySelectorAll(".city-chip")) {
  chip.addEventListener("click", () => {
    viewportMode = false;
    center = { lat: Number(chip.dataset.lat), lon: Number(chip.dataset.lon) };
    search.value = "";
    map.setView([center.lat, center.lon], chip.dataset.city === "Bydgoszcz" ? 14 : 12);
    update(false);
  });
}

byId("map-search").addEventListener("click", () => {
  center = activeCenter();
  search.value = "";
  update(false);
});

byId("locate").addEventListener("click", () => {
  if (!navigator.geolocation) {
    notice.textContent = "Geolokalizacja GPS nie jest wspierana przez tę przeglądarkę.";
    return;
  }
  notice.textContent = "Ustalanie pozycji GPS…";
  navigator.geolocation.getCurrentPosition(
    ({ coords }) => {
      center = { lat: coords.latitude, lon: coords.longitude };
      search.value = "";
      notice.textContent = "";
      update();
    },
    () => {
      notice.textContent = "Nie udało się pobrać GPS. Wybierz miasto lub przesuń mapę.";
    },
    { timeout: 7000, maximumAge: 120000 }
  );
});

byId("google-switch").addEventListener("click", startGoogle);

// Query the visible area after deliberate map movement; rendering results never recenters it.
map.on("dragstart", () => { mapInteraction = true; });
map.getContainer().addEventListener("wheel", () => { mapInteraction = true; }, {passive:true});
map.getContainer().addEventListener("keydown", (e) => { if (["ArrowUp","ArrowDown","ArrowLeft","ArrowRight","+","-"].includes(e.key)) mapInteraction = true; });
map.getContainer().querySelector(".leaflet-control-zoom")?.addEventListener("click", () => { mapInteraction = true; scheduleViewportSearch(); });
function scheduleViewportSearch() {
  if (!byId("search-as-move").checked || mapTaggingMode) return;
  clearTimeout(moveTimer);
  moveTimer = setTimeout(() => {
    center = activeCenter(); search.value = ""; viewportMode = true; update(false);
  }, 300);
}
map.on("moveend", () => {
  if (!mapInteraction) return;
  mapInteraction = false; scheduleViewportSearch();
});
byId("search-as-move").addEventListener("change", () => {
  byId("map-search").style.display = byId("search-as-move").checked ? "none" : "inline-flex";
});

// Vector JS Offline Basemap Toggle
byId("vector-switch").addEventListener("click", () => {
  forceVectorJS = !forceVectorJS;
  byId("vector-switch").setAttribute("aria-pressed", String(forceVectorJS));
  byId("vector-switch").textContent = forceVectorJS ? "Włącz kafelki OSM" : "Podkład JS Offline";
  basemap(isEffectiveOnline());
});

// Simulated Offline PWA Mode Toggle
byId("toggle-offline-sim").addEventListener("click", () => {
  simulatedOffline = !simulatedOffline;
  notice.textContent = simulatedOffline
    ? "Włączono lokalny tryb Offline PWA — aplikacja korzysta wyłącznie z pamięci podręcznej i silnika JS."
    : "Przywrócono połączenie Online z serwerem rejestru.";
  update(false);
});

// Interactive Map Click Tagging Mode
const tagDialog = byId("tag-dialog");
const tagConfidenceSlider = byId("tag-confidence");
const tagConfidenceOutput = byId("tag-confidence-output");

function updateConfidenceBadge(val, outputEl) {
  const score = Number(val);
  const lvl = score >= 70 ? "high" : score >= 45 ? "medium" : "low";
  const lbl = score >= 70 ? "WYSOKA PEWNOŚĆ" : score >= 45 ? "ŚREDNIA PEWNOŚĆ" : "NISKA / ORIENTACYJNA";
  outputEl.className = `conf-badge ${lvl}`;
  outputEl.textContent = `${score} / 100 · ${lbl}`;
  for (const btn of document.querySelectorAll(".preset-btn")) {
    btn.classList.toggle("active", Number(btn.dataset.conf) === score);
  }
}

tagConfidenceSlider.addEventListener("input", () => {
  updateConfidenceBadge(tagConfidenceSlider.value, tagConfidenceOutput);
});
for (const btn of document.querySelectorAll(".preset-btn")) {
  btn.addEventListener("click", () => {
    tagConfidenceSlider.value = btn.dataset.conf;
    updateConfidenceBadge(btn.dataset.conf, tagConfidenceOutput);
  });
}

function setMapTaggingMode(active) {
  mapTaggingMode = active;
  byId("map-tag-toggle").setAttribute("aria-pressed", String(active));
  byId("map-tag-hint").hidden = !active;
  byId("local-map").classList.toggle("tagging-cursor", active);
}

byId("map-tag-toggle").addEventListener("click", () => {
  setMapTaggingMode(!mapTaggingMode);
});

map.on("click", (e) => {
  if (!mapTaggingMode) return;
  setMapTaggingMode(false);
  openTagModalAtCoords(e.latlng.lat, e.latlng.lng);
});

function openTagModalAtCoords(lat, lon) {
  byId("tag-id").value = `tag-${lat.toFixed(5)}-${lon.toFixed(5)}`;
  byId("tag-name").value = "";
  byId("tag-municipality").value = "";
  byId("tag-lat").value = lat.toFixed(6);
  byId("tag-lon").value = lon.toFixed(6);
  byId("tag-street").value = "";
  byId("tag-house").value = "";
  byId("tag-postcode").value = "";
  byId("tag-placement").value = "";
  byId("tag-level").value = "";
  byId("tag-lock").value = "unknown";
  byId("tag-access").value = "unknown";
  byId("tag-hours").value = "";
  byId("tag-instructions").value = "";
  tagConfidenceSlider.value = "50";
  updateConfidenceBadge(50, tagConfidenceOutput);
  byId("tag-status").textContent = "";
  tagDialog.showModal();
}

function openTagModalForItem(item) {
  byId("tag-id").value = item.aed_id || item.id;
  byId("tag-name").value = item.site_name || item.name || "";
  byId("tag-municipality").value = item.municipality || item.locality || "Polska";
  byId("tag-lat").value = Number(item.latitude ?? item.lat).toFixed(6);
  byId("tag-lon").value = Number(item.longitude ?? item.lon).toFixed(6);
  byId("tag-street").value = item.street || "";
  byId("tag-house").value = item.house_number || "";
  byId("tag-postcode").value = item.postcode || "";
  byId("tag-placement").value = item.placement || "";
  byId("tag-level").value = item.level || "";
  byId("tag-lock").value = item.cabinet_lock_status && item.cabinet_lock_status !== "unknown" ? item.cabinet_lock_status : "unknown";
  byId("tag-access").value = ["public", "restricted"].includes(item.access_type || item.access) ? (item.access_type || item.access) : "unknown";
  byId("tag-hours").value = item.opening_hours || item.hours || "";
  byId("tag-instructions").value = item.access_instructions || "";
  const newConf = Number(item.user_confidence || 50);
  tagConfidenceSlider.value = String(newConf);
  updateConfidenceBadge(newConf, tagConfidenceOutput);
  byId("tag-status").textContent = "";
  tagDialog.showModal();
}

byId("open-tag-modal").addEventListener("click", () => {
  const c = activeCenter();
  openTagModalAtCoords(c.lat, c.lon);
});
byId("banner-tag-btn").addEventListener("click", () => {
  const c = activeCenter();
  openTagModalAtCoords(c.lat, c.lon);
});
byId("tag-dialog-close").addEventListener("click", () => tagDialog.close());
byId("tag-use-map-center").addEventListener("click", () => {
  const c = activeCenter();
  byId("tag-lat").value = c.lat.toFixed(6);
  byId("tag-lon").value = c.lon.toFixed(6);
});

byId("tag-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const lat = Number(byId("tag-lat").value.replace(",", "."));
  const lon = Number(byId("tag-lon").value.replace(",", "."));
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < 48.9 || lat > 55 || lon < 14 || lon > 24.2) {
    byId("tag-status").textContent = "Podaj poprawne współrzędne liczbowe WGS84.";
    return;
  }
  const conf = Number(tagConfidenceSlider.value);
  const payload = {
    aed_id: byId("tag-id").value || `tag-${lat.toFixed(5)}-${lon.toFixed(5)}`,
    site_name: byId("tag-name").value.trim(),
    municipality: byId("tag-municipality").value.trim(),
    latitude: lat,
    longitude: lon,
    street: byId("tag-street").value.trim(),
    house_number: byId("tag-house").value.trim(),
    postcode: byId("tag-postcode").value.trim(),
    placement: byId("tag-placement").value.trim(),
    level: byId("tag-level").value.trim() || null,
    cabinet_lock_status: byId("tag-lock").value,
    access_type: byId("tag-access").value,
    opening_hours: byId("tag-hours").value.trim() || null,
    access_instructions: byId("tag-instructions").value.trim(),
    user_confidence: conf,
    confidence: 30,
    source_ids: ["pwa_offline_tag"],
    is_user_tagged: true,
    synced: false,
  };

  // Always save immediately to local PWA storage so it works 100% offline
  try { window.offlineData.addOrUpdateTag(payload); } catch (err) {
    byId("tag-status").textContent = err.message; return;
  }
  updateTaggedCount();

  if (isEffectiveOnline()) {
    try {
      const res = await fetch("/api/tag", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        window.offlineData.addOrUpdateTag({ ...payload, synced: true });
      }
    } catch {
      // Kept in local offline store for later sync
    }
  }

  center = { lat, lon };
  tagDialog.close();
  notice.textContent = `Zapisano lokalnie: ${payload.site_name}. Publikacja wymaga zatwierdzenia.`;
  available.checked = false; onlyTagged.checked = true; viewportMode = false;
  await update(false);
  map.setView([lat, lon], Math.max(map.getZoom(), 14));
});

// Download helper
function downloadBlob(content, filename, mimeType) {
  const url = URL.createObjectURL(new Blob([content], { type: mimeType }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1200);
}

// Offline Pack, Export & Import Modal
const offlineDialog = byId("offline-dialog");
async function openOfflineHub() {
  offlineDialog.showModal();
  const pack = await window.offlineData.read().catch(() => null);
  const tags = window.offlineData.getTags();
  if (pack) {
    savedPack = pack;
    byId("offline-status").textContent =
      `W pamięci przeglądarki: ${number.format(pack.items?.length || 0)} pkt z bazy + ${number.format(tags.length)} otagowanych lokalnie.`;
  } else {
    byId("offline-status").textContent =
      `W pamięci lokalnej: ${number.format(items.length)} bieżących punktów + ${number.format(tags.length)} otagowanych lokalnie.`;
  }
}

byId("offline-open").addEventListener("click", openOfflineHub);
byId("banner-export-btn").addEventListener("click", openOfflineHub);
byId("offline-close").addEventListener("click", () => offlineDialog.close());

byId("offline-save").addEventListener("click", async () => {
  const input = byId("offline-radius");
  if (!input.reportValidity()) return;
  const status = byId("offline-status");
  const target = activeCenter();
  if (!isEffectiveOnline()) { status.textContent = "Połącz się z internetem, aby pobrać nowy obszar. Zapisany obszar pozostaje dostępny."; return; }
  const params = new URLSearchParams({ lat: target.lat, lon: target.lon, radius_km: input.value });
  status.textContent = "Pobieranie i zapisywanie bazy offline w pamięci PWA…";
  try {
    const response = await fetch("/api/offline?" + params, { signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error("pack");
    const { items: saved, count } = await response.json();
    savedPack = {
      items: saved,
      center: target,
      radius: Number(input.value),
      date: new Date().toISOString(),
    };
    await window.offlineData.write("pack", savedPack);
    if (!window.aedOfflineReady) throw new Error("Tryb offline wymaga HTTPS lub localhost.");
    await window.aedOfflineReady;
    status.textContent = `Zapisano ${number.format(saved.length)} z ${number.format(count)} punktów w obszarze (${input.value} km). Uproszczona mapa jest dostępna offline.`;
    if (saved.length < count) status.textContent += " Obszar przekracza limit paczki; zapisz mniejszy obszar, aby zachować wszystkie punkty.";
  } catch (err) {
    status.textContent = `Nie udało się zapisać obszaru. ${err.message || "Sprawdź połączenie i wolne miejsce."} Poprzednia paczka pozostaje dostępna.`;
  }
});

function getExportableItems(tagsOnly = false) {
  const tags = window.offlineData.getTags();
  if (tagsOnly) return tags;
  const base = savedPack?.items?.length ? savedPack.items : items;
  const byIdMap = new Map();
  for (const t of tags) byIdMap.set(t.aed_id || t.id, t);
  for (const b of base) {
    const id = b.aed_id || b.id;
    if (!byIdMap.has(id)) byIdMap.set(id, b);
  }
  return Array.from(byIdMap.values());
}

byId("offline-file").addEventListener("click", () => {
  const list = getExportableItems(false);
  const geo = window.offlineData.toCanonicalGeoJSON(list);
  downloadBlob(JSON.stringify(geo, null, 2), `odblokuj-aed-offline-${list.length}.geojson`, "application/geo+json");
});

byId("export-canonical-json").addEventListener("click", () => {
  const list = getExportableItems(false);
  const jsonPayload = window.offlineData.toCanonicalJSON(list);
  downloadBlob(JSON.stringify(jsonPayload, null, 2), `odblokuj-aed-dane-gov-pl-${list.length}.json`, "application/json");
});

byId("export-canonical-csv").addEventListener("click", () => {
  const list = getExportableItems(false);
  const csvPayload = window.offlineData.toCanonicalCSV(list);
  downloadBlob(csvPayload, `odblokuj-aed-dane-gov-pl-${list.length}.csv`, "text/csv;charset=utf-8");
});

byId("export-tags-only").addEventListener("click", () => {
  const tags = getExportableItems(true);
  if (!tags.length) {
    byId("import-status").textContent = "Brak własnych otagowanych punktów. Oznacz najpierw AED na mapie!";
    return;
  }
  const geo = window.offlineData.toCanonicalGeoJSON(tags);
  downloadBlob(JSON.stringify(geo, null, 2), `moje-tagi-aed-${tags.length}.geojson`, "application/geo+json");
});

byId("import-offline-btn").addEventListener("click", async () => {
  const fileInput = byId("import-offline-file");
  const status = byId("import-status");
  const file = fileInput.files?.[0];
  if (!file) {
    status.textContent = "Wybierz plik .geojson, .json lub .csv do zaimportowania.";
    return;
  }
  try {
    if (file.size > 20 * 1024 * 1024) throw new Error("Maksymalny rozmiar pliku: 20 MB.");
    const text = await file.text();
    const imported = await window.offlineData.parseImportText(text, file.name);
    if (!imported.length) throw new Error("Plik nie zawiera żadnych punktów AED.");
    const existing = window.offlineData.getTags();
    const mapById = new Map(existing.map((i) => [i.aed_id, i]));
    for (const item of imported) {
      mapById.set(item.aed_id, { ...item, is_user_tagged: true });
    }
    const mergedTags = window.offlineData.saveTags(Array.from(mapById.values()));
    updateTaggedCount();
    const located = imported.find(item => Number.isFinite(item.latitude) && Number.isFinite(item.longitude));
    if (located) center = { lat: located.latitude, lon: located.longitude };
    available.checked = false; onlyTagged.checked = true; search.value = ""; viewportMode = false;
    status.textContent = `Zaimportowano pomyślnie ${number.format(imported.length)} lokalizacji AED (łącznie lokalnych: ${mergedTags.length}).`;
    await update(true);
  } catch (err) {
    status.textContent = `Błąd importu: ${err.message}`;
  }
});

byId("sync-tags-btn").addEventListener("click", async () => {
  const status = byId("import-status");
  const tags = window.offlineData.getTags();
  if (!tags.length) {
    status.textContent = "Brak lokalnych tagów do synchronizacji.";
    return;
  }
  if (!isEffectiveOnline()) {
    status.textContent = "Włącz tryb Online / Wi-Fi, aby zsynchronizować lokalne tagi z serwerem.";
    return;
  }
  status.textContent = "Synchronizacja lokalnych tagów z serwerem…";
  let syncedCount = 0;
  for (const tag of tags.filter(tag => !tag.synced)) {
    try {
      const res = await fetch("/api/tag", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(tag),
      });
      if (res.ok) {
        tag.synced = true;
        syncedCount++;
      }
    } catch {
      // ignore failed individual sync
    }
  }
  try { window.offlineData.saveTags(tags); } catch (err) { status.textContent = err.message; return; }
  status.textContent = `Zsynchronizowano ${syncedCount} z ${tags.length} lokalnych oznaczeń z serwerem rejestru.`;
  update(false);
});

byId("clear-tags-btn").addEventListener("click", () => {
  try { window.offlineData.saveTags([]); } catch (err) { byId("import-status").textContent = err.message; return; }
  updateTaggedCount();
  byId("import-status").textContent = "Wyczyszczono lokalnie otagowane i zaimportowane punkty.";
  update(false);
});

// Sources & Architecture Modal
const sourcesDialog = byId("sources-dialog");
byId("sources-open").addEventListener("click", () => sourcesDialog.showModal());
byId("sources-close").addEventListener("click", () => sourcesDialog.close());

// PWA Installation Handling
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredInstallPrompt = e;
  byId("pwa-install-btn").textContent = "Zainstaluj aplikację PWA";
});

byId("pwa-install-btn").addEventListener("click", async () => {
  if (deferredInstallPrompt) {
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice.catch(() => {});
    deferredInstallPrompt = null;
  } else {
    await openOfflineHub();
    byId("offline-status").textContent += " Instalacja: w menu przeglądarki wybierz Zainstaluj aplikację lub Dodaj do ekranu początkowego (iOS: Udostępnij).";
  }
});

// Initial Metadata & Sources Fetch
fetch("/api/config")
  .then((r) => r.json())
  .then((data) => {
    googleConfig = data;
    byId("google-switch").hidden = !data.google_maps_key;
  })
  .catch(() => {});

function applySourceMetadata(data) {
    const { sources = [], site_count, sync_schedule } = data;
    if (site_count) byId("stat-total").textContent = number.format(site_count);
    if (sources?.length) byId("stat-sources").textContent = String(sources.length);
    const previousFilter = sourceFilter.value;
    sourceFilter.replaceChildren(new Option("Wszystkie źródła", ""), ...sources.map(source => new Option(source.name, source.id)), new Option("Moje lokalne punkty", "pwa_offline_tag"));
    sourceFilter.value = previousFilter;
    if (sync_schedule) {
      byId("sync-badge").textContent = `Harmonogram: ${sync_schedule} · Kanoniczny JSON dane.gov.pl`;
    }
    const listEl = byId("sources-modal-list");
    listEl.replaceChildren();
    sources.forEach((source) => {
      sourceNames.set(source.id, source.name);
      const card = element("article");
      const h3 = element("h3", source.name);
      const meta = element(
        "p",
        `${number.format(source.count)} obserwacji źródłowych · ${source.scope || "Polska"} · Odświeżanie: ${source.cadence || "codziennie (24h)"}`
      );
      const lic = element("p", `Licencja / warunki: ${source.license || "Otwarte Dane"}`);
      const link = element("a", source.url);
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener";
      card.append(h3, meta, lic, link);
      listEl.append(card);
    });
    render(false);
}
fetch("/api/sources")
  .then(r => { if (!r.ok) throw new Error("sources"); return r.json(); })
  .then(data => { window.offlineData.write("sources", data).catch(() => {}); applySourceMetadata(data); })
  .catch(async () => { const cached = await window.offlineData.read("sources").catch(() => null); if (cached) applySourceMetadata(cached); });

if (location.pathname === "/mapa") {
  document.body.classList.add("full-map");
  byId("expand-map").href = "/app";
  byId("expand-map").textContent = "Mapa i lista";
  requestAnimationFrame(() => map.invalidateSize());
}

byId("expand-map").addEventListener("click", () => {
  try {
    sessionStorage.setItem(
      "aed-map-view",
      JSON.stringify({
        center: activeCenter(),
        query: search.value,
        radius: radius.value,
        available: available.checked,
      })
    );
  } catch {
    // Ignore storage error
  }
});

window.addEventListener("offline", () => update(false));
window.addEventListener("online", () => update(false));
updateTaggedCount();
update();
