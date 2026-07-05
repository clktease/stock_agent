import { onMounted, onUnmounted, ref } from 'vue'

// Subscribes to the backend's existing /events SSE stream (shared with the
// scheduled-job and influencer-alert push notifications) and forwards every
// parsed message to onEvent, so callers just filter for the event types
// they care about (review_new / review_updated).
export function useSSE(onEvent) {
  const connected = ref(false)
  let source = null

  onMounted(() => {
    source = new EventSource('/events')
    source.onopen = () => { connected.value = true }
    source.onerror = () => { connected.value = false }
    source.onmessage = (evt) => {
      try {
        onEvent(JSON.parse(evt.data))
      } catch {
        // ignore malformed/heartbeat events
      }
    }
  })

  onUnmounted(() => {
    source?.close()
  })

  return { connected }
}
