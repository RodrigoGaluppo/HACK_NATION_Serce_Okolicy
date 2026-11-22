"use strict";

const DATA_CACHE = "aed-saved-points-v2";
const LOCAL_TAGS_KEY = "aed-user-tagged-points-v2";
const MAX_IMPORT_BYTES = 12 * 1024 * 1024;
const MAX_IMPORT_ROWS = 10000;
const CANONICAL_FIELDS = [
  "aed_id", "site_name", "locality", "municipality", "teryt", "street", "house_number", "postcode",
  "coordinate_status", "longitude", "latitude", "coordinate_accuracy_m", "placement", "indoor_outdoor",
  "level", "cabinet_lock_status", "access_instructions", "device_type", "access_type", "opening_hours",
  "access_status", "readiness_status", "public_operator_name", "public_operator_contact_url",
  "location_checked_on", "access_checked_on", "readiness_checked_on", "is_stale", "source_ids", "field_sources"
];
const nullableText = (value) => value == null || value === "" ? null : String(value).trim() || null;
const coordinate = (value) => value == null || String(value).trim() === "" ? null : Number(value);
const enumValue = (value, allowed) => allowed.includes(value) ? value : "unknown";
const jsonValue = (value) => {
  if (typeof value !== "string") return value;
  try { return JSON.parse(value); } catch { return value; }
};
function normalizeToCanonicalItem(raw, index = 0) {
  const lat = coordinate(raw.latitude ?? raw.lat ?? raw.coordinates?.[1]);
  const lon = coordinate(raw.longitude ?? raw.lon ?? raw.coordinates?.[0]);
  const hasCoords = raw.coordinate_status !== "address_only" && lat !== null && lon !== null && Number.isFinite(lat) && Number.isFinite(lon)
    && Math.abs(lat) <= 90 && Math.abs(lon) <= 180;
  const aedId = String(raw.aed_id || raw.id || raw.operator_device_id || `local-aed-${index}`).trim();
  const siteName = String(raw.site_name || raw.name || "Punkt AED").trim();
  let sourceIds = jsonValue(raw.source_ids || raw.sources || ["pwa_offline_tag"]);
  if (typeof sourceIds === "string") sourceIds = [sourceIds];
  sourceIds = Array.isArray(sourceIds) ? [...new Set(sourceIds.filter((s) => typeof s === "string" && s.trim()))] : [];
  if (!sourceIds.length) sourceIds = ["pwa_offline_tag"];
  const givenSources = jsonValue(raw.field_sources);
  const fieldSources = {};
  if (givenSources && typeof givenSources === "object" && !Array.isArray(givenSources)) {
    for (const [field, source] of Object.entries(givenSources)) {
      if ((CANONICAL_FIELDS.includes(field) || field === "coordinates") && !["aed_id", "is_stale", "source_ids", "field_sources", "coordinate_status"].includes(field) && sourceIds.includes(source)) fieldSources[field] = source;
    }
  }
  const access = raw.access_type || raw.access;
  const accessType = ["yes", "designated"].includes(access) ? "public" : enumValue(access, ["public", "restricted", "unknown"]);
  const today = new Date().toISOString().slice(0, 10);
  const checkedOn = nullableText(raw.location_checked_on || raw.checked_on);
  const staleDates = [checkedOn, raw.access_checked_on, raw.readiness_checked_on].filter(Boolean);
  const isStale = raw.is_stale === true || raw.is_stale === "true" || staleDates.some((date) => (Date.parse(today) - Date.parse(date)) > 365 * 86400000);
  let confidence = coordinate(raw.confidence);
  if (confidence === null || !Number.isFinite(confidence)) confidence = hasCoords ? 30 : 10;
  confidence = Math.max(0, Math.min(100, Math.round(confidence)));
  const row = {
    aed_id: aedId, site_name: siteName,
    locality: nullableText(raw.locality || raw.municipality || raw.city),
    municipality: nullableText(raw.municipality || raw.locality || raw.city),
    teryt: nullableText(raw.teryt), street: nullableText(raw.street),
    house_number: nullableText(raw.house_number || raw.home_number), postcode: nullableText(raw.postcode),
    coordinate_status: hasCoords ? "located" : "address_only",
    longitude: hasCoords ? lon : null, latitude: hasCoords ? lat : null,
    coordinate_accuracy_m: coordinate(raw.coordinate_accuracy_m) > 0 ? Number(raw.coordinate_accuracy_m) : null,
    placement: nullableText(raw.placement), indoor_outdoor: enumValue(raw.indoor_outdoor, ["indoor", "outdoor", "unknown"]),
    level: nullableText(raw.level), cabinet_lock_status: enumValue(raw.cabinet_lock_status, ["unlocked", "locked", "not_applicable", "unknown"]),
    access_instructions: nullableText(raw.access_instructions), device_type: enumValue(raw.device_type, ["fixed", "mobile", "unknown"]),
    access_type: accessType, opening_hours: nullableText(raw.opening_hours || raw.hours),
    access_status: enumValue(raw.access_status, ["available", "restricted", "unavailable", "unknown"]),
    readiness_status: enumValue(raw.readiness_status, ["ready", "not_ready", "unknown"]),
    public_operator_name: nullableText(raw.public_operator_name || raw.operator),
    public_operator_contact_url: nullableText(raw.public_operator_contact_url),
    location_checked_on: checkedOn, access_checked_on: nullableText(raw.access_checked_on),
    readiness_checked_on: nullableText(raw.readiness_checked_on), is_stale: isStale,
    source_ids: sourceIds, field_sources: fieldSources,
    confidence, confidence_level: confidence >= 70 ? "high" : confidence >= 45 ? "medium" : "low",
    confidence_reasons: Array.isArray(raw.confidence_reasons) ? raw.confidence_reasons : ["Ocena dokumentacji lokalizacji; nie potwierdza gotowości urządzenia."],
    is_user_tagged: raw.is_user_tagged === true, synced: raw.synced === true,
    distance_km: raw.distance_km,
    id: aedId, name: siteName, lat: hasCoords ? lat : null, lon: hasCoords ? lon : null,
    address: nullableText(raw.address) || [raw.street, raw.house_number, raw.postcode, raw.locality || raw.municipality].filter(Boolean).join(" "),
    access: accessType, hours: nullableText(raw.opening_hours || raw.hours), checked_on: checkedOn, sources: sourceIds,
  };
  // Provenance describes observed fields only; it must not claim generated defaults.
  for (const field of Object.keys(fieldSources)) {
    if (field === "coordinates" ? !hasCoords : row[field] == null || row[field] === "unknown") delete fieldSources[field];
  }
  return row;
}

function parseCSV(text) {
  const firstLine = text.split(/\r?\n/, 1)[0];
  const delimiter = firstLine.split(";").length > firstLine.split(",").length ? ";" : ",";
  const rows = []; let row = []; let value = ""; let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { value += '"'; i++; }
      else if (ch === '"') quoted = false;
      else value += ch;
    } else if (ch === '"' && value === "") quoted = true;
    else if (ch === delimiter) { row.push(value); value = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(value); if (row.some((cell) => cell.trim())) rows.push(row);
      row = []; value = "";
    } else value += ch;
  }
  if (quoted) throw new Error("CSV: niedomknięty cudzysłów.");
  row.push(value); if (row.some((cell) => cell.trim())) rows.push(row);
  if (rows.length < 2) throw new Error("Plik CSV nie zawiera wierszy danych.");
  const headers = rows.shift().map((header) => header.trim());
  if (new Set(headers).size !== headers.length || headers.some((header) => !header)) throw new Error("CSV: nagłówki muszą być unikalne i niepuste.");
  return rows.map((cells, i) => {
    if (cells.length !== headers.length) throw new Error(`Wiersz ${i + 2}: liczba kolumn nie odpowiada nagłówkom.`);
    return Object.fromEntries(headers.map((header, j) => [header, cells[j]]));
  });
}

function validateImportedRow(raw, index, seen) {
  const error = (message) => { throw new Error(`Wiersz ${index + 1}: ${message}`); };
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) error("oczekiwano obiektu AED.");
  const id = nullableText(raw.aed_id || raw.id || raw.operator_device_id);
  if (!id || id.length > 200) error("wymagany stabilny identyfikator aed_id (do 200 znaków).");
  if (seen.has(id)) error(`powtórzony identyfikator ${id}.`);
  seen.add(id);
  if (!nullableText(raw.site_name || raw.name)) error("brak nazwy site_name.");
  const lat = coordinate(raw.latitude ?? raw.lat); const lon = coordinate(raw.longitude ?? raw.lon);
  const hasLat = lat !== null; const hasLon = lon !== null;
  if (hasLat !== hasLon || (hasLat && (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180))) error("nieprawidłowa para współrzędnych WGS84.");
  if (raw.coordinate_status === "located" && !hasLat) error("punkt located wymaga współrzędnych.");
  if (!hasLat && !nullableText(raw.locality || raw.municipality || raw.address || raw.street)) error("podaj współrzędne lub adres.");
  for (const field of ["location_checked_on", "access_checked_on", "readiness_checked_on"]) {
    if (raw[field] && (!/^\d{4}-\d{2}-\d{2}$/.test(raw[field]) || Number.isNaN(Date.parse(raw[field])) || new Date(raw[field]).toISOString().slice(0, 10) !== raw[field])) error(`nieprawidłowa data ${field}.`);
  }
  for (const [field, allowed] of Object.entries({access_type:["public","restricted","unknown"], readiness_status:["ready","not_ready","unknown"], access_status:["available","restricted","unavailable","unknown"], cabinet_lock_status:["locked","unlocked","not_applicable","unknown"], coordinate_status:["located","address_only"], device_type:["fixed","mobile","unknown"], indoor_outdoor:["indoor","outdoor","unknown"]})) {
    if (raw[field] && !allowed.includes(raw[field])) error(`nieznana wartość ${field}.`);
  }
  for (const value of Object.values(raw)) if (typeof value === "string" && value.length > 10000) error("pole tekstowe przekracza 10 000 znaków.");
  return normalizeToCanonicalItem({...raw, aed_id:id, is_user_tagged:true, synced:false}, index);
}

const offlineData = {
  normalizeItem: normalizeToCanonicalItem,
  async write(key, value) {
    const body = JSON.stringify(value); let persisted = false;
    if ("caches" in window) {
      try {
        const cache = await caches.open(DATA_CACHE);
        await cache.put("/_offline/" + key, new Response(body, {headers:{"Content-Type":"application/json; charset=utf-8"}}));
        persisted = true;
      } catch { /* Small localStorage fallback below. */ }
    }
    try { localStorage.setItem("aed-cache-" + key, body); persisted = true; } catch { /* Cache API may hold a larger pack. */ }
    if (!persisted) throw new Error("Nie można zapisać danych offline. Zwolnij pamięć przeglądarki i spróbuj ponownie.");
    if (navigator.storage?.persist) navigator.storage.persist().catch(() => {});
  },
  async read(key) {
    const keys = key ? [key] : ["pack", "last"];
    for (const candidate of keys) {
      if ("caches" in window) {
        try { const response = await (await caches.open(DATA_CACHE)).match("/_offline/" + candidate); if (response) return await response.json(); } catch { /* Try fallback. */ }
      }
      try { const body = localStorage.getItem("aed-cache-" + candidate); if (body) return JSON.parse(body); } catch { /* Try next. */ }
    }
    return null;
  },
  getTags() {
    try { const list = JSON.parse(localStorage.getItem(LOCAL_TAGS_KEY) || "[]"); return Array.isArray(list) ? list.map(normalizeToCanonicalItem) : []; } catch { return []; }
  },
  saveTags(tags) {
    if (!Array.isArray(tags) || tags.length > MAX_IMPORT_ROWS) throw new Error("Maksymalnie 10 000 lokalnych oznaczeń.");
    const normalized = tags.map(normalizeToCanonicalItem);
    // Tags are written synchronously so a successful UI confirmation means they are durable.
    try { localStorage.setItem(LOCAL_TAGS_KEY, JSON.stringify(normalized)); }
    catch { throw new Error("Brak miejsca na lokalne oznaczenia. Wyeksportuj dane i zwolnij pamięć przeglądarki."); }
    this.write("tags", normalized).catch(() => {});
    return normalized;
  },
  addOrUpdateTag(tag) {
    const current = this.getTags(); const item = normalizeToCanonicalItem({...tag, is_user_tagged:true}, current.length);
    const index = current.findIndex((existing) => existing.aed_id === item.aed_id);
    if (index >= 0) current[index] = item; else current.unshift(item);
    return this.saveTags(current);
  },
  removeTag(aedId) { return this.saveTags(this.getTags().filter((tag) => tag.aed_id !== aedId)); },
  toCanonicalGeoJSON(items) {
    const rows = items.map(normalizeToCanonicalItem);
    const features = rows.filter((row) => row.coordinate_status === "located").map((row) => ({
      type:"Feature", id:row.aed_id, geometry:{type:"Point", coordinates:[row.longitude,row.latitude]},
      properties:Object.fromEntries(CANONICAL_FIELDS.filter((key) => !["longitude","latitude"].includes(key)).map((key) => [key,row[key] ?? null]))
    }));
    return {type:"FeatureCollection", metadata:{schema:"dane.gov.pl/odblokuj-aed/v1",generated_at:new Date().toISOString(),record_count:features.length,local_unreviewed:true,address_only_omitted:rows.length-features.length},features};
  },
  toCanonicalJSON(items) {
    const rows = items.map(normalizeToCanonicalItem).map((row) => Object.fromEntries(CANONICAL_FIELDS.map((key) => [key,row[key] ?? null])));
    return {schema:"dane.gov.pl/odblokuj-aed/v1",generated_at:new Date().toISOString(),record_count:rows.length,local_unreviewed:true,items:rows};
  },
  toCanonicalCSV(items) {
    const cell = (value) => {
      if (value == null) return "";
      let text = typeof value === "object" ? JSON.stringify(value) : String(value);
      if (typeof value === "string" && /^[=+@\t\r-]/.test(text)) text = "'" + text;
      return /[",\r\n]/.test(text) ? '"' + text.replaceAll('"','""') + '"' : text;
    };
    return [CANONICAL_FIELDS.join(","), ...items.map(normalizeToCanonicalItem).map((row) => CANONICAL_FIELDS.map((key) => cell(row[key])).join(","))].join("\r\n") + "\r\n";
  },
  async parseImportText(text, filename = "") {
    if (new Blob([text]).size > MAX_IMPORT_BYTES) throw new Error("Plik przekracza limit 12 MB.");
    const trimmed = text.trim().replace(/^\uFEFF/, ""); let rows;
    if (/^[{[]/.test(trimmed) || /\.(geo)?json$/i.test(filename)) {
      const payload = JSON.parse(trimmed);
      if (Array.isArray(payload)) rows = payload;
      else if (Array.isArray(payload.items)) rows = payload.items;
      else if (payload.type === "FeatureCollection" && Array.isArray(payload.features)) {
        rows = payload.features.map((feature, index) => {
          if (feature.type !== "Feature" || feature.geometry?.type !== "Point" || !Array.isArray(feature.geometry.coordinates) || feature.geometry.coordinates.length < 2 || feature.geometry.coordinates.slice(0,2).some((n) => typeof n !== "number")) throw new Error(`Wiersz ${index + 1}: GeoJSON wymaga geometrii Point z liczbowymi współrzędnymi.`);
          return {...feature.properties,aed_id:feature.properties?.aed_id || feature.id,longitude:feature.geometry.coordinates[0],latitude:feature.geometry.coordinates[1]};
        });
      } else throw new Error("Nieobsługiwana struktura JSON/GeoJSON.");
    } else rows = parseCSV(trimmed);
    if (!rows.length || rows.length > MAX_IMPORT_ROWS) throw new Error("Plik musi zawierać od 1 do 10 000 rekordów.");
    const seen = new Set(); return rows.map((row,index) => validateImportedRow(row,index,seen));
  },
};
window.offlineData = offlineData;
if ("serviceWorker" in navigator) {
  window.aedOfflineReady = navigator.serviceWorker.register("/sw.js", {updateViaCache:"none"})
    .then(() => navigator.serviceWorker.ready)
    .then((registration) => { window.dispatchEvent(new CustomEvent("aed-offline-ready")); return registration; });
  window.aedOfflineReady.catch(() => {});
}
