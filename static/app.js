"use strict";

const byId = (id) => document.getElementById(id);
const results = byId("results");
const search = byId("search");
const radius = byId("radius");
const available = byId("available-only");
const summary = byId("results-summary");
const notice = byId("notice");
const sourceNames = new Map([["operator", "Zatwierdzone zgłoszenie"]]);
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
let operational = navigator.onLine;
let savedPack;
let usingGoogle = false;
try {
  const previous = JSON.parse(sessionStorage.getItem("aed-map-view"));
  if (previous && Number.isFinite(previous.center.lat) && Number.isFinite(previous.center.lon)) {
    center = previous.center;
    search.value = previous.query;
    radius.value = previous.radius;
    available.checked = previous.available;
  }
} catch {
  // Use the default area when browser storage is disabled.
}

function element(tag, text = "", className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

const map = L.map("local-map", { minZoom: 4, maxZoom: 19, zoomAnimation: !reducedMotion.matches }).setView([center.lat, center.lon], 12);
map.attributionControl.addAttribution('© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Natural Earth');
map.createPane("borders").style.zIndex = 150;
const points = L.layerGroup().addTo(map);
fetch("/vendor/boundaries.geojson").then((response) => response.json()).then((geo) => {
  L.geoJSON(geo, { pane: "borders", interactive: false, style: { color: "#8da396", weight: 1, fillColor: "#e1eadc", fillOpacity: 0.8 } }).addTo(map);
}).catch(() => {});
L.control.scale({ imperial: false }).addTo(map);

function basemap(online) {
  operational = online;
  if (!online) {
    if (remoteTiles) map.removeLayer(remoteTiles);
    showGoogle(false);
    byId("map-description").textContent = "Podkład offline · zapisane punkty AED";
    return;
  }
  if (!remoteTiles) {
    remoteTiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, maxNativeZoom: 19 });
    remoteTiles.on("tileerror", () => {
      if (!usingGoogle && operational) byId("map-description").textContent = "Podkład lokalny · część kafelków jest niedostępna";
    });
    remoteTiles.on("tileload", () => {
      if (!usingGoogle && operational) byId("map-description").textContent = "OpenStreetMap";
    });
  }
  if (!map.hasLayer(remoteTiles)) remoteTiles.addTo(map);
  byId("map-description").textContent = usingGoogle ? "Google Maps" : "OpenStreetMap";
}
basemap(operational);

function tone(item) {
  return item.confidence >= 70 ? "high" : item.confidence >= 45 ? "medium" : "low";
}
const toneLabel = { high: "Wysoka", medium: "Średnia", low: "Niska" };
const toneColor = { high: "#00843d", medium: "#966009", low: "#7b4642" };

function popupDetails(item) {
  const panel = element("div", "", "point-details");
  panel.append(element("strong", item.name), element("p", item.address || item.placement || "Brak dokładnego adresu"));
  panel.append(element("p", "Pewność danych · " + toneLabel[tone(item)] + " (" + (item.confidence ?? 0) + "/100)", "confidence " + tone(item)));
  const access = ["public", "yes", "designated"].includes(item.access) ? "Publiczny wg źródła"
    : item.access && item.access !== "unknown" ? "Ograniczony wg źródła" : "Nieznany";
  panel.append(element("p", "Dostęp · " + access));
  if (item.access_instructions) panel.append(element("p", item.access_instructions));
  if (item.placement) panel.append(element("p", "Umiejscowienie · " + item.placement));
  if (item.hours) panel.append(element("p", "Godziny wg źródła · " + item.hours));
  if (item.checked_on) panel.append(element("p", "Data sprawdzenia wg źródła · " + item.checked_on));
  panel.append(element("p", "Źródła · " + item.sources.map((id) => sourceNames.get(id) || id).join(", ")));
  const reasons = element("ul");
  for (const reason of item.confidence_reasons || []) reasons.append(element("li", reason));
  panel.append(reasons);
  const provenance = element("details");
  const fields = element("ul");
  for (const [key, label] of Object.entries({ coordinates: "Położenie", address: "Adres", placement: "Szafka",
    access: "Dostęp", access_type: "Dostęp", hours: "Godziny", opening_hours: "Godziny" })) {
    const source = item.field_sources?.[key];
    if (source) fields.append(element("li", label + " · " + (sourceNames.get(source) || source)));
  }
  if (fields.childElementCount) {
    provenance.append(element("summary", "Źródła poszczególnych pól"), fields);
    panel.append(provenance);
  }
  panel.append(element("small", "Ocena dotyczy danych o urządzeniu. Stan techniczny pozostaje nieznany."));
  return panel;
}

function select(item, pan = true, reveal = false) {
  selected = item.id;
  for (const row of results.children) {
    const active = row.dataset.id === selected;
    row.classList.toggle("active", active);
    const button = row.querySelector("button");
    if (button) button.setAttribute("aria-expanded", String(active));
    const detail = row.querySelector(".point-details");
    if (detail) detail.hidden = !active;
    if (active && reveal && location.pathname !== "/mapa") {
      row.scrollIntoView({ block: "nearest", behavior: reducedMotion.matches ? "instant" : "smooth" });
    }
  }
  if (!pan) return;
  if (usingGoogle) {
    googleMap.panTo({ lat: item.lat, lng: item.lon });
    return;
  }
  map.panTo([item.lat, item.lon], { animate: !reducedMotion.matches });
  points.eachLayer((layer) => { if (layer.itemId === item.id) layer.openPopup(); });
}

function render(fit) {
  const previous = selected;
  selected = undefined;
  results.replaceChildren();
  points.clearLayers();
  const bounds = [];
  if (!items.length) results.append(element("li", "Brak punktów. Zmień obszar lub filtr.", "empty"));
  for (const item of items) {
    const row = element("li", "", "result");
    row.dataset.id = item.id;
    const button = element("button", "", "result-button");
    button.type = "button";
    button.setAttribute("aria-expanded", "false");
    button.append(element("strong", item.name), element("span", item.address || item.municipality || "Adres nieznany", "address"));
    if (item.distance_km != null) button.append(element("span", decimals.format(item.distance_km) + " km", "distance"));
    const detail = popupDetails(item);
    detail.hidden = true;
    row.append(button, element("p", toneLabel[tone(item)] + " pewność danych", "confidence " + tone(item)), detail);
    button.addEventListener("click", () => select(item));
    results.append(row);

    const pin = L.circleMarker([item.lat, item.lon], { radius: 8, color: "#fff", weight: 2, fillColor: toneColor[tone(item)], fillOpacity: 1 });
    pin.itemId = item.id;
    pin.bindPopup(() => popupDetails(item));
    pin.on("click", () => select(item, false, true));
    points.addLayer(pin);
    bounds.push([item.lat, item.lon]);
  }
  if (fit && bounds.length) map.fitBounds(bounds, { maxZoom: 14, padding: [24, 24], animate: false });
  if (usingGoogle) renderGoogle(fit);
  const restore = items.find((item) => item.id === previous);
  if (restore) select(restore, false);
}

function matchSaved(pack, query) {
  if (!pack) return [];
  const folded = (text) => text.toLowerCase().replaceAll("ł", "l").normalize("NFD").replace(/\p{Diacritic}/gu, "");
  const words = folded(query).trim().split(/\s+/);
  const candidates = pack.items.filter((item) => (!available.checked || ["yes", "public", "designated"].includes(item.access)) &&
    words.every((word) => folded([item.name, item.address, item.municipality, item.placement].join(" ")).includes(word)));
  return candidates.map((item) => ({ ...item, distance_km: map.distance([center.lat, center.lon], [item.lat, item.lon]) / 1000 }))
    .filter((item) => query || item.distance_km <= Number(radius.value))
    .sort((a, b) => a.distance_km - b.distance_km);
}

async function update(fit = true) {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  const query = search.value.trim();
  const params = new URLSearchParams({ limit: "50", radius_km: radius.value, available: available.checked ? "1" : "0" });
  if (query) params.set("q", query);
  else { params.set("lat", center.lat); params.set("lon", center.lon); }
  results.setAttribute("aria-busy", "true");
  summary.textContent = "Wczytywanie punktów…";
  const timer = setTimeout(() => current.abort(), 4500);
  try {
    if (!navigator.onLine) throw new Error("offline");
    const response = await fetch("/api/aeds?" + params, { signal: current.signal });
    if (!response.ok) throw new Error("lookup");
    const data = await response.json();
    if (controller !== current) return;
    if (data.center) center = data.center;
    items = data.items;
    basemap(true);
    summary.textContent = number.format(items.length) + " z " + number.format(data.count)
      + (data.center ? " · odległość w linii prostej" : "");
    offlineData.write("last", { items: data.items, center, date: new Date().toISOString() }).catch(() => {});
  } catch {
    if (controller !== current) return;
    const justDisconnected = operational;
    basemap(false);
    const pack = await offlineData.read().catch(() => null);
    if (controller !== current) return;
    if (pack && !query && (justDisconnected || !items.length)) center = pack.center;
    const saved = matchSaved(pack, query);
    items = saved.slice(0, 50);
    const suffix = pack ? " · zapis " + new Date(pack.date).toLocaleString("pl-PL") : " · brak zapisanych punktów";
    summary.textContent = "Offline · " + number.format(items.length) + " z " + number.format(saved.length) + suffix;
  } finally {
    clearTimeout(timer);
    if (controller === current) {
      results.setAttribute("aria-busy", "false");
      render(fit);
    }
  }
}

function activeCenter() {
  const current = usingGoogle ? googleMap.getCenter() : map.getCenter();
  return usingGoogle ? { lat: current.lat(), lon: current.lng() } : { lat: current.lat, lon: current.lng };
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
    const pinContent = new google.maps.marker.PinElement({ background: toneColor[tone(item)], borderColor: "#fff", glyphColor: "#fff" });
    const pin = new google.maps.marker.AdvancedMarkerElement({ map: googleMap, position, title: item.name, content: pinContent.element });
    pin.addListener("click", () => {
      select(item, false, true);
      popup.setContent(popupDetails(item));
      popup.open({ map: googleMap, anchor: pin });
    });
    googlePins.push(pin);
    bounds.extend(position);
  }
  if (fit && items.length > 1) googleMap.fitBounds(bounds, 36);
  else if (fit && items.length === 1) { googleMap.setCenter(bounds.getCenter()); googleMap.setZoom(14); }
}

async function startGoogle() {
  if (usingGoogle) { showGoogle(false); basemap(operational); return; }
  if (!operational || !googleConfig?.google_maps_key) { notice.textContent = "Google Maps wymaga połączenia i klucza."; return; }
  try {
    if (!googleMap) {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(reject, 8000);
        window.aedGoogleReady = () => { clearTimeout(timer); resolve(); };
        window.gm_authFailure = () => {
          clearTimeout(timer);
          googleMap = null;
          showGoogle(false);
          notice.textContent = "Google Maps odrzucił klucz. OpenStreetMap jest dostępny.";
          reject();
        };
        const script = document.createElement("script");
        const params = new URLSearchParams({ key: googleConfig.google_maps_key, callback: "aedGoogleReady", loading: "async", language: "pl" });
        script.src = "https://maps.googleapis.com/maps/api/js?" + params;
        script.onerror = () => { clearTimeout(timer); reject(); };
        document.head.append(script);
      });
      await Promise.all([google.maps.importLibrary("maps"), google.maps.importLibrary("marker")]);
      googleMap = new google.maps.Map(byId("google-map"), { center, zoom: 12,
        mapId: googleConfig.google_maps_map_id || "DEMO_MAP_ID", streetViewControl: false });
    }
    showGoogle(true);
    byId("map-description").textContent = "Google Maps · lokalne dane AED";
    renderGoogle(true);
  } catch {
    showGoogle(false);
    notice.textContent = "Google Maps jest niedostępny. Użyj OpenStreetMap.";
  }
}

byId("search-form").addEventListener("submit", (event) => { event.preventDefault(); clearTimeout(debounce); update(); });
search.addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(update, 285); });
radius.addEventListener("change", () => update());
available.addEventListener("change", () => update());
byId("map-search").addEventListener("click", () => { center = activeCenter(); search.value = ""; update(false); });
byId("locate").addEventListener("click", () => {
  if (!navigator.geolocation) { notice.textContent = "Lokalizacja jest niedostępna."; return; }
  notice.textContent = "Ustalanie położenia…";
  navigator.geolocation.getCurrentPosition(({ coords }) => {
    center = { lat: coords.latitude, lon: coords.longitude };
    search.value = "";
    notice.textContent = "";
    update();
  }, () => { notice.textContent = "Wpisz miejscowość, aby wybrać obszar."; }, { timeout: 7000, maximumAge: 120000 });
});
byId("google-switch").addEventListener("click", startGoogle);
fetch("/api/config").then((r) => r.json()).then((data) => {
  googleConfig = data;
  byId("google-switch").hidden = !data.google_maps_key;
}).catch(() => {});
fetch("/api/sources").then((r) => r.json()).then(({ sources }) => {
  sources.forEach((source) => sourceNames.set(source.id, source.name));
  render(false);
}).catch(() => {});

const dialog = byId("offline-dialog");
byId("offline-open").onclick = () => {
  dialog.showModal();
  offlineData.read("pack").then((pack) => {
    if (!pack) return;
    savedPack = pack;
    byId("offline-file").hidden = false;
    byId("offline-status").textContent = "W przeglądarce · " + number.format(pack.items.length) + " punktów · " + pack.radius + " km";
  }).catch(() => {});
};
byId("offline-close").onclick = () => dialog.close();
byId("offline-save").onclick = async () => {
  const input = byId("offline-radius");
  if (!input.reportValidity()) return;
  const status = byId("offline-status");
  const target = activeCenter();
  const params = new URLSearchParams({ ...target, radius_km: input.value });
  status.textContent = "Zapisywanie…";
  try {
    if (!("caches" in window) || !("serviceWorker" in navigator)) throw new Error("storage");
    const response = await fetch("/api/offline?" + params, { signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error("pack");
    const { items: saved, count } = await response.json();
    await navigator.serviceWorker.ready;
    savedPack = { items: saved, center: target, radius: Number(input.value), date: new Date().toISOString() };
    await offlineData.write("pack", savedPack);
    byId("offline-file").hidden = false;
    status.textContent = "Zapisano " + number.format(saved.length) + " punktów w przeglądarce."
      + (count > saved.length ? " Osiągnięto limit. Zmniejsz promień, aby zapisać wszystkie punkty obszaru." : "");
  } catch { status.textContent = "Nie udało się zapisać obszaru. Sprawdź połączenie i dostęp do pamięci przeglądarki."; }
};
byId("offline-file").onclick = () => {
  if (!savedPack) return;
  const features = savedPack.items.map(({ id, lat, lon, ...properties }) => ({
    type: "Feature", id, geometry: { type: "Point", coordinates: [lon, lat] }, properties: { ...properties, aed_id: id },
  }));
  const url = URL.createObjectURL(new Blob([JSON.stringify({ type: "FeatureCollection", features })], { type: "application/geo+json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "aed-obszar-" + savedPack.radius + "km.geojson";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
if (location.pathname === "/mapa") {
  document.body.classList.add("full-map");
  byId("expand-map").href = "/";
  byId("expand-map").textContent = "Mapa i lista";
  requestAnimationFrame(() => map.invalidateSize());
}
byId("expand-map").addEventListener("click", () => {
  try {
    sessionStorage.setItem("aed-map-view", JSON.stringify({ center: activeCenter(), query: search.value,
      radius: radius.value, available: available.checked }));
  } catch {
    // Navigation works even without browser storage.
  }
});
window.addEventListener("offline", () => update());
window.addEventListener("online", () => update());
update();
