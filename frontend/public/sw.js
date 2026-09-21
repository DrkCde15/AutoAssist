const CACHE_NAME = "autoassist-v2";
const PRECACHE = ["/", "/css/styles.css", "/logo2.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request).then(function(r){ return r || caches.match(e.request); }).catch(function(){ return caches.match(e.request); })
  );
});

// Push notification handler
self.addEventListener("push", (e) => {
  var data = { title: "AutoAssist", body: "" };
  if (e.data) {
    try { data = e.data.json(); } catch (_) { data.body = e.data.text(); }
  }
  var options = {
    body: data.body,
    icon: "/logo2.png",
    badge: "/logo2.png",
    vibrate: [100, 50, 100],
    data: data.data || {},
    requireInteraction: true
  };
  e.waitUntil(self.registration.showNotification(data.title, options));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  var url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (wins) {
      for (var i = 0; i < wins.length; i++) {
        var w = wins[i];
        if (w.url.includes(self.location.origin) && "focus" in w) {
          w.focus();
          if (url !== "/") w.navigate(url);
          return;
        }
      }
      return clients.openWindow(url);
    })
  );
});
