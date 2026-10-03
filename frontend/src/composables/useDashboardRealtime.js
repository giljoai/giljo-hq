import { onMounted, onUnmounted } from 'vue'
import debounce from 'lodash-es/debounce'
import { useWebSocketStore } from '@/stores/websocket'

const DASHBOARD_REFRESH_EVENTS = ['project_update', 'agent:created', 'task:updated']

export function useDashboardRealtime(refetch, { debounceMs = 600 } = {}) {
  const wsStore = useWebSocketStore()
  const debouncedRefetch = debounce(() => refetch(), debounceMs)
  let unsubscribers = []

  onMounted(() => {
    unsubscribers = DASHBOARD_REFRESH_EVENTS.map((type) => wsStore.on(type, debouncedRefetch))
  })

  onUnmounted(() => {
    unsubscribers.forEach((unsub) => unsub())
    unsubscribers = []
  })
}
