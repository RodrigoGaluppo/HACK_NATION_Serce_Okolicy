"use strict";
const dataCache = "aed-saved-points-v1";
const offlineData = {
  async write(key, value) {
    const cache = await caches.open(dataCache);
    await cache.put("/_offline/" + key, new Response(JSON.stringify(value)));
  },
  async read(key) {
    if (!("caches" in window)) return null;
    const cache = await caches.open(dataCache);
    const response = key ? await cache.match("/_offline/" + key)
      : await cache.match("/_offline/pack") || await cache.match("/_offline/last");
    return response ? response.json() : null;
  },
};
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
