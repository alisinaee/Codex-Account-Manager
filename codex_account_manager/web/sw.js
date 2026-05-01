self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("notificationclick", (event) => {
  try { event.notification.close(); } catch(_) {}
  const targetUrl = "/?v=__UI_VERSION__";
  event.waitUntil((async () => {
    const allClients = await clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of allClients) {
      try {
        if (client && "focus" in client) {
          await client.focus();
          if ("navigate" in client) await client.navigate(targetUrl);
          return;
        }
      } catch(_) {}
    }
    if (clients.openWindow) {
      await clients.openWindow(targetUrl);
    }
  })());
});
