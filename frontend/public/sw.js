// Service worker: PWA-оболонка ("Додати на екран Домівки" на iPhone).
//
// Кешується лише статична оболонка застосунку (HTML/JS/CSS/іконки) —
// ЖОДНОГО кешування /api/, /ws, /health: котирування, спред, баланс і
// сигнали ребалансування завжди мають бути live, ніколи з кешу
// (той самий принцип "не використовувати stale дані", що й у backend).
const CACHE_NAME = "spread-monitor-shell-v1";
const SHELL_PATHS = ["/", "/manifest.webmanifest"];

const isBypassedPath = (pathname) =>
  pathname.startsWith("/api/") || pathname.startsWith("/ws") || pathname === "/health";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_PATHS)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || isBypassedPath(url.pathname)) {
    return; // мережа напряму, без втручання service worker'а
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      const network = fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    }),
  );
});
