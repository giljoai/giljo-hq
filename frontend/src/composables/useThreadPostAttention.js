import { computed, ref } from 'vue'

import api from '@/services/api'

const mentions = ref(null)
const directedAsks = ref(null)

let inFlight = null
let requested = false
let listening = false

async function refresh() {
  if (inFlight) return inFlight
  inFlight = (async () => {
    try {
      const res = await api.threads.attention()
      mentions.value = Array.isArray(res?.data?.mentions) ? res.data.mentions : []
      directedAsks.value = Array.isArray(res?.data?.directed_action) ? res.data.directed_action : []
    } catch {
      // Keep whatever we last knew. Never fall back to [].
    } finally {
      inFlight = null
    }
  })()
  return inFlight
}

async function ensureLoaded() {
  if (requested) return
  requested = true
  await refresh()
}

function listen() {
  if (listening || typeof window === 'undefined') return
  listening = true
  window.addEventListener('hub:thread_message', () => refresh())
  window.addEventListener('hub:thread_update', () => refresh())
}

export function useThreadPostAttention() {
  listen()

  return {
    mentions,
    directedAsks,
    loaded: computed(() => mentions.value !== null),
    attentionCount: computed(
      () => (mentions.value?.length || 0) + (directedAsks.value?.length || 0),
    ),
    ensureLoaded,
    refresh,
  }
}

export function __resetThreadPostAttention() {
  mentions.value = null
  directedAsks.value = null
  inFlight = null
  requested = false
}
