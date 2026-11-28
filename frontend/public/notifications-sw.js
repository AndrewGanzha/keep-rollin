const notificationPaths = new Set([
  '/account/rentals',
  '/account/tickets',
  '/account/verification',
  '/admin/rentals',
  '/admin/tickets',
])

function notificationPath(path) {
  return notificationPaths.has(path) ? path : '/'
}

function readPayload(data) {
  try {
    return data?.json() ?? {}
  } catch {
    return {}
  }
}

async function appWindows() {
  const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
  return windows.filter(client =>
    client.frameType !== 'nested' && client.url.startsWith(`${self.location.origin}/`),
  )
}

async function openNotification(path) {
  const destination = notificationPath(path)
  const target = `${self.location.origin}${destination}`
  const windows = await appWindows()
  let existing = windows.find(client => client.url === target)
  if (!existing && destination !== '/') {
    // After login, the window may still report the login document as its URL.
    existing = windows.find((client) => {
      const current = new URL(client.url)
      return current.pathname === '/login' && current.searchParams.get('next') === destination
    }) ?? windows[0]
  }
  if (existing) {
    try {
      const focused = await existing.focus()
      // Client.url may still be the address from before a client-side route change.
      if (await focused.navigate(target)) return
    } catch {
      // The window can close or lose its controller between enumeration and focus.
    }
  }
  await self.clients.openWindow(target)
}

async function notifySubscriptionChange() {
  for (const client of await appWindows()) {
    client.postMessage({ type: 'pushsubscriptionchange' })
  }
}

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('push', (event) => {
  const payload = readPayload(event.data)
  const title = typeof payload.title === 'string' && payload.title.trim() ? payload.title : 'Keep Rollin'
  event.waitUntil(self.registration.showNotification(title, {
    body: typeof payload.body === 'string' ? payload.body : 'У вас новое уведомление.',
    icon: '/icons/app-192.png',
    tag: typeof payload.tag === 'string' ? payload.tag : undefined,
    data: { url: notificationPath(payload.url) },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(openNotification(event.notification.data?.url))
})

self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil(notifySubscriptionChange())
})
