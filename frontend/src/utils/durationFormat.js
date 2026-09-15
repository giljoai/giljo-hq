
export function formatDurationSeconds(totalSeconds) {
  if (totalSeconds == null) return '---'

  const seconds = Math.max(0, Math.floor(totalSeconds))
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}m ${secs}s`
  }
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return `${hours}h ${mins}m`
}

export function resolveAgentDurationSeconds(agent, nowMs) {
  const terminal = agent?.status === 'complete' || agent?.status === 'closed'
  let total = agent?.duration_seconds
  if (!terminal && agent?.working_started_at) {
    const anchor = Date.parse(agent.working_started_at)
    if (!Number.isNaN(anchor)) {
      total = (nowMs - anchor) / 1000
    }
  }
  return total == null ? null : total
}

export function formatAgentDuration(agent, nowMs) {
  return formatDurationSeconds(resolveAgentDurationSeconds(agent, nowMs))
}

export function formatTimeOfDay(iso) {
  if (!iso) return ''
  const parsed = Date.parse(iso)
  if (Number.isNaN(parsed)) return ''
  return new Date(parsed).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function elapsedSecondsSince(iso, nowMs) {
  if (!iso) return null
  const anchor = Date.parse(iso)
  if (Number.isNaN(anchor)) return null
  return Math.max(0, (nowMs - anchor) / 1000)
}
