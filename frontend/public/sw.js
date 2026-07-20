const CACHE = "autoassist-v6";
const STATIC_ASSETS = [
  "/",
  "/index.html",
  "/login.html",
  "/cadastro.html",
  "/logo.png",
  "/static/logo2.png",
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

// self.addEventListener("message", (event) => {
//   if (event.data && event.data.type === "SKIP_WAITING") {
//     self.skipWaiting();
//   }
// });

self.addEventListener("activate", (event) => {
  event.waitUntil(
    clients.claim(),
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
});

/* ── Push Event ── */

self.addEventListener("push", (event) => {
  if (!event.data) return;

  let data;
  try {
    data = event.data.json();
  } catch {
    data = { title: "AutoAssist", body: event.data.text() };
  }

  const title = data.title || "AutoAssist";
  const options = {
    body: data.body || "",
    icon: data.icon || "/static/logo2.png",
    badge: data.badge || "/static/logo2.png",
    data: data.data || {},
    requireInteraction: data.requireInteraction || false,
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const urlToOpen = event.notification.data?.url || "/";

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url === urlToOpen && "focus" in client) return client.focus();
      }
      return clients.openWindow(urlToOpen);
    })
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (url.origin !== location.origin) return;

  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/pagamentos/")) {
    return;
  }

  if (request.method !== "GET") return;

  const path = url.pathname.toLowerCase();
  const isAppShell =
    request.mode === "navigate" ||
    path === "/" ||
    path.endsWith(".html") ||
    path.endsWith(".js");

  if (isAppShell) {
    // Network-first para o app shell (HTML/JS): sempre busca a versão viva do
    // servidor quando houver rede. Evita servir uma UI obsoleta/quebrada enquanto
    // o backend está em cold start no Render. Só cai no cache se o servidor
    // estiver realmente fora do ar (PWA ainda abre offline).
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response && response.status === 200 && response.type === "basic") {
            const clone = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match(request).then((cached) => cached || Response.error()))
    );
    return;
  }

  // Demais assets estáticos (CSS, imagens, fontes): cache-first com atualização
  // em background. Não afetam a lógica de autenticação/estado do app.
  event.respondWith(
    caches.match(request).then((cached) => {
      const fetchPromise = fetch(request).then((response) => {
        if (response && response.status === 200 && response.type === "basic") {
          const clone = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, clone));
        }
        return response;
      }).catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
