const BASE = '/api/review'

async function handle(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || `Request failed: ${res.status}`)
  }
  return res.json()
}

export function listItems(params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v))
  )
  return fetch(`${BASE}/items?${qs}`).then(handle)
}

export function getItem(id) {
  return fetch(`${BASE}/items/${id}`).then(handle)
}

export function updateItem(id, payload) {
  return fetch(`${BASE}/items/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(handle)
}

export function getStats() {
  return fetch(`${BASE}/stats`).then(handle)
}
