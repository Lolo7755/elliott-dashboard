// Service Worker des Elliott-Dashboards: macht die Seite installierbar und zeigt offline den letzten Stand.
// Strategie: immer zuerst frisch aus dem Netz laden (Daten ändern sich täglich), nur bei fehlender
// Verbindung aus dem Zwischenspeicher. Externe Bibliotheken/Schriften: aus dem Speicher, im Hintergrund erneuern.
const CACHE = "elliott-v2";
const SHELL = ["./", "index.html", "style.css", "app.js", "manifest.webmanifest", "icon-192.png", "icon-512.png"];
const EXTERN = ["unpkg.com", "fonts.googleapis.com", "fonts.gstatic.com"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const ohneQuery = req => { const u = new URL(req.url); u.search = ""; return u.href; };

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET" || req.headers.has("range")) return;
  const url = new URL(req.url);
  if (url.origin === self.location.origin) {
    e.respondWith((async () => {
      const c = await caches.open(CACHE), key = ohneQuery(req);
      try {
        const res = await fetch(req, {cache: "no-store"});
        if (res.ok) c.put(key, res.clone());
        return res;
      } catch (err) {
        return (await c.match(key)) || (req.mode === "navigate" ? await c.match(new URL("./", self.location).href) : undefined)
          || new Response("", {status: 504, statusText: "offline"});
      }
    })());
  } else if (EXTERN.includes(url.hostname)) {
    e.respondWith((async () => {
      const c = await caches.open(CACHE), hit = await c.match(req);
      const neu = fetch(req).then(res => { if (res.ok || res.type === "opaque") c.put(req, res.clone()); return res; }).catch(() => hit);
      return hit || neu;
    })());
  }
});
