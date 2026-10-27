// Red primero para la app (siempre la última versión), caché como respaldo sin conexión.
const CACHE = "pocketpanel-v6";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return;
  if (url.origin !== location.origin && !url.hostname.endsWith("jsdelivr.net")) return;
  // Las librerías de la CDN llevan la versión en la URL: no cambian, así que de la caché si están (y sin conexión)
  if (url.hostname.endsWith("jsdelivr.net")) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
      return res;
    })));
    return;
  }
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
        return res;
      })
      .catch(() => caches.match(e.request)),
  );
});

// Avisos del servidor
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data.json(); } catch { d = { title: "pocketpanel", body: e.data?.text() || "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "pocketpanel", {
    body: d.body || "",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { url: d.url || "/" },
    tag: d.body,  // el mismo aviso no se apila
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = new URL(e.notification.data?.url || "/", self.location.origin).href;
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) {
      if (w.url.startsWith(self.location.origin)) {
        await w.focus();
        return w.navigate(url);
      }
    }
    return self.clients.openWindow(url);
  })());
});
