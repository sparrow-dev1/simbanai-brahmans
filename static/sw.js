const CACHE = 'simbanai-shell-v16';
const SHELL = ['/', '/static/style.css', '/static/auth.js', '/static/app.js', '/static/farm.js', '/static/report-letterhead.png', '/static/company-logo.png', '/static/company-logo-green.svg', '/static/company-logo-transparent.png', '/static/favicon-v6.svg', '/static/favicon-v6.ico', '/static/icon.svg', '/static/icon-192-v6.png', '/static/icon-512-v6.png', '/static/manifest.webmanifest'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith('simbanai-shell-') && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== 'GET' || url.pathname.startsWith('/api/')) return;
  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(() => caches.match('/')));
  } else if (SHELL.includes(url.pathname)) {
    event.respondWith(caches.match(event.request, {ignoreSearch:true}).then(cached => cached || fetch(event.request)));
  }
});
