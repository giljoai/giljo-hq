import { onUnmounted } from 'vue'

export const AGENT_REFRESH_EVENTS = Object.freeze([
  'agent:status_changed',
  'agent:created',
  'agent:removed',
  'agent:update',
  'agent:silent',
  'agent:auto_failed',
  'agent:health_alert',
  'agent:mission_updated',
  'job:progress_update',
  'job:mission_updated',
  'thread_message',
])

export const BOARD_REFRESH_EVENTS = Object.freeze([
  'project:staging_complete',
  'project:implementation_launched',
  'project:mission_updated',
  'project:launched',
  'project:created',
  'project:memory_updated',
  'project_update',
  'projects:bulk:deactivated',
  'sequence:updated',
])

function projectIdOf(payload) {
  return payload?.project_id || null
}

export function useJobsBoardLiveRefresh({ wsStore, isOnBoard, refreshAgents, refreshBoard, delay = 300 }) {
  const cardTimers = new Map()
  let boardTimer = null
  const boardProjectIds = new Set()

  function scheduleBoard(payload) {
    const projectId = projectIdOf(payload)
    if (projectId) boardProjectIds.add(projectId)
    clearTimeout(boardTimer)
    boardTimer = setTimeout(() => {
      boardTimer = null
      const named = [...boardProjectIds]
      boardProjectIds.clear()
      refreshBoard(named)
    }, delay)
  }

  function scheduleCard(projectId) {
    clearTimeout(cardTimers.get(projectId))
    cardTimers.set(
      projectId,
      setTimeout(() => {
        cardTimers.delete(projectId)
        refreshAgents(projectId)
      }, delay),
    )
  }

  function onAgentEvent(type, payload) {
    const projectId = projectIdOf(payload)
    if (projectId && isOnBoard(projectId)) scheduleCard(projectId)
    else if (!projectId || type === 'agent:created') scheduleBoard(payload)
  }

  function onVisibility() {
    if (document.visibilityState === 'visible') scheduleBoard()
  }

  const offs = [
    ...AGENT_REFRESH_EVENTS.map((type) => wsStore.on(type, (payload) => onAgentEvent(type, payload))),
    ...BOARD_REFRESH_EVENTS.map((type) => wsStore.on(type, scheduleBoard)),
  ]
  document.addEventListener('visibilitychange', onVisibility)

  onUnmounted(() => {
    offs.forEach((off) => off?.())
    document.removeEventListener('visibilitychange', onVisibility)
    clearTimeout(boardTimer)
    cardTimers.forEach((timer) => clearTimeout(timer))
    cardTimers.clear()
  })
}
