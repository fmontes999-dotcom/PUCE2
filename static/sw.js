// Service worker mínimo: permite instalar la app. No guarda nada en caché,
// así los pedidos siempre vienen del servidor.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
