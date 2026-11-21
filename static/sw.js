"use strict";
const shell = "aed-shell-v7";
const files = [
  "/index.html", "/app.js", "/offline.js", "/styles.css", "/manifest.webmanifest",
  "/vendor/leaflet.css", "/vendor/leaflet.js", "/vendor/boundaries.geojson",
  "/brand/mark.png", "/brand/wordmark.png", "/brand/atkinson.ttf",
  "/brand/atkinson-bold.ttf", "/brand/outfit.ttf", "/brand/icon-192.png", "/brand/icon-512.png",
  "/brand/roboto.ttf",
];
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(shell).then((cache) => cache.addAll(files)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((name) => name.startsWith("aed-shell-") && name !== shell)
    .map((name) => caches.delete(name)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== "GET") return;
  if (event.request.mode === "navigate" && ["/", "/mapa", "/index.html"].includes(url.pathname)) {
    event.respondWith(caches.open(shell).then((cache) => cache.match("/index.html"))
      .then((page) => page || fetch(event.request)));
  } else if (files.includes(url.pathname)) {
    event.respondWith(caches.open(shell).then((cache) => cache.match(url.pathname))
      .then((asset) => asset || fetch(event.request)));
  }
});
