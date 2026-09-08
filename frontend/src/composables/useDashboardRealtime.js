/**
 * useDashboardRealtime.js — FE-9501c (D7)
 *
 * DashboardView had ZERO WebSocket wiring -- only a 60s call-count poll. This
 * subscribes to the lifecycle events that already drive Roadmap/Projects
 * (project_update, agent:created, task:updated) and debounces them into one
 * refetch, since a chain run or an agent-activity burst emits a lot of these
 * in a row. Subscribe on mount, unsubscribe on unmount -- the caller wires
 * nothing beyond passing the refetch function.
 *
 * @param {Function} refetch - called (debounced) on any of the wired events
 *
 * Edition scope: Both
 */
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
    unsubscribers.forEach((unsub) => unsub?.())
    unsubscribers = []
  })
}
