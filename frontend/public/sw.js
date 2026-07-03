const CACHE = "autoassist-v2";
const STATIC_ASSETS = [
  "/",
  "/index.html",
  "/login.html",
  "/cadastro.html",
  "/static/css/dark-theme.css",
  "/static/css/shared.css",
  "/static/css/responsive.css",
  "/static/js/config.js",
  "/static/js/auth.js",
  "/static/js/responsive.js",
  "/static/js/notifications.js",
  "/static/css/notifications.css",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch(() => {});
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(clients.claim());
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (url.origin !== location.origin) return;

  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/pagamentos/")) {
    return;
  }

  if (request.method !== "GET") return;

  event.respondWith(
    caches.match(request).then((cached) => {
      const fetchPromise = fetch(request).then((response) => {
        if (response && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE).then((cache) => {
            cache.put(request, clone);
          });
        }
        return response;
      }).catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
