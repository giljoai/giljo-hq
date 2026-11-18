import { onBeforeUnmount, onMounted } from 'vue'

import { useStartListStore } from '@/stores/startList'
import { useWebSocketStore } from '@/stores/websocket'

export const START_LIST_EVENTS = Object.freeze([
  'setup:tool_connected',
  'setup:bootstrap_complete',
  'product:created',
  'project:created',
  'project:staging_complete',
  'project_update',
  'project:implementation_launched',
  'project:launched',
  'project:memory_updated',
])

const DEBOUNCE_MS = 400

export function useStartListLive() {
  const store = useStartListStore()
  const ws = useWebSocketStore()
  let timer = null
  let offs = []

  function schedule() {
    clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      store.refresh({ force: true })
    }, DEBOUNCE_MS)
  }

  onMounted(() => {
    store.refresh()
    offs = START_LIST_EVENTS.map((type) => ws.on(type, schedule))
    window.addEventListener('focus', schedule)
  })

  onBeforeUnmount(() => {
    offs.forEach((off) => off?.())
    offs = []
    window.removeEventListener('focus', schedule)
    clearTimeout(timer)
  })
}
