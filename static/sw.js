"use strict";
const shell = "aed-shell-v17";
const apiCache = "aed-public-api-v2";
const promoPaths = new Set(["/", "/kampania", "/promo", "/o-projekcie", "/promo.html", "/promo.css", "/promo.js"]);
const files = [
  "/index.html", "/zglos.html", "/panel.html",
  "/app.js", "/office.js", "/offline.js", "/styles.css", "/manifest.webmanifest", "/przyklad.geojson",
  "/vendor/leaflet.css", "/vendor/leaflet.js", "/vendor/boundaries.geojson",
  "/vendor/images/layers.png", "/vendor/images/layers-2x.png",
  "/video/geo.js", "/video/street_heart_logo.png",
  "/brand/mark.png", "/brand/wordmark.png", "/brand/atkinson.ttf", "/brand/atkinson-bold.ttf",
  "/brand/outfit.ttf", "/brand/icon-192.png", "/brand/icon-512.png", "/brand/roboto.ttf",
  "/brand/BebasNeue-Regular.ttf", "/brand/DMSans.ttf",
  "/app.css", "/app-i18n.js", "/office.css", "/offline-map.js",
];
const essential = ["/app.css", "/app-i18n.js", "/offline-map.js", "/index.html", "/app.js", "/offline.js", "/styles.css", "/vendor/leaflet.css", "/vendor/leaflet.js", "/vendor/boundaries.geojson", "/video/geo.js", "/video/street_heart_logo.png"];
const pages = new Map([
  ["/app", "/index.html"], ["/app/", "/index.html"], ["/mapa-aed", "/index.html"], ["/mapa", "/index.html"], ["/index.html", "/index.html"],
  ["/zglos", "/zglos.html"], ["/zglos.html", "/zglos.html"], ["/panel", "/panel.html"], ["/panel.html", "/panel.html"],
]);
self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(shell);
    // A broken essential asset must fail installation, leaving the previous working shell active.
    await cache.addAll(essential);
    await Promise.allSettled(files.filter((url) => !essential.includes(url)).map((url) => cache.add(url)));
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((name) => (name.startsWith("aed-shell-") && name !== shell) || name === "aed-api-v1").map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  // External tile providers use their normal browser HTTP cache. No bulk tile fetching.
  if (url.origin !== self.location.origin || promoPaths.has(url.pathname)) return;
  // Only public reads are cached; reviewer requests and authorization headers never enter Cache Storage.
  if (["/api/aeds", "/api/offline", "/api/sources"].includes(url.pathname) && !event.request.headers.has("Authorization")) {
    event.respondWith((async () => {
      const cache = await caches.open(apiCache);
      try {
        const response = await fetch(event.request);
        if (response.ok) {
          await cache.put(event.request, response.clone());
          // Bound query variants; saved packs and tags live in a separate persistent cache.
          const keys = await cache.keys();
          await Promise.all(keys.slice(0, Math.max(0, keys.length - 80)).map((key) => cache.delete(key)));
        }
        return response;
      } catch {
        const cached = await cache.match(event.request);
        if (cached) {
          const headers = new Headers(cached.headers); headers.set("X-AED-Offline", "1");
          return new Response(await cached.arrayBuffer(), {status:cached.status,headers});
        }
        return new Response(JSON.stringify({error:"Offline: wybierz zapisany obszar lub zaimportuj plik."}), {status:503,headers:{"Content-Type":"application/json; charset=utf-8"}});
      }
    })());
    return;
  }
  const page = event.request.mode === "navigate" ? pages.get(url.pathname) : null;
  if (page || files.includes(url.pathname)) {
    event.respondWith((async () => {
      const cache = await caches.open(shell); const key = page || url.pathname;
      try {
        const response = await fetch(event.request);
        if (response.ok) { await cache.put(key, response.clone()); return response; }
        const cached = await cache.match(key); return cached || response;
      } catch { return await cache.match(key) || Response.error(); }
    })());
  }
});
