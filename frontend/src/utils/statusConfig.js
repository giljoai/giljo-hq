
export const STATUS_COLORS = {
  WAITING: '#ffd700',
  WORKING: '#ffffff',
  BLOCKED: '#f44336',
  SILENT: '#e060b0',
  COMPLETE: '#67bd6d',
  IDLE: '#7a9bb5',
  SLEEPING: '#9b89b3',
  HANDED_OVER: '#9e9e9e',
  CLOSED: '#4a9c5f',
  DECOMMISSIONED: '#757575',
  CLOSEOUT: '#ffc107',
  PENDING: '#9e9e9e',
  FALLBACK: '#666666',
}

const statusConfig = {
  waiting: {
    label: 'Waiting.',
    color: STATUS_COLORS.WAITING,
    chipColor: 'warning',
  },
  working: {
    label: 'Working',
    color: STATUS_COLORS.WORKING,
    chipColor: 'default',
  },
  blocked: {
    label: 'Blocked',
    color: STATUS_COLORS.BLOCKED,
    chipColor: 'warning',
  },
  complete: {
    label: 'Complete',
    color: STATUS_COLORS.COMPLETE,
    chipColor: 'success',
  },
  idle: {
    label: 'Monitoring',
    color: STATUS_COLORS.IDLE,
    chipColor: 'default',
  },
  sleeping: {
    label: 'Sleeping',
    color: STATUS_COLORS.SLEEPING,
    chipColor: 'default',
  },
  holding: {
    label: 'Holding',
    color: STATUS_COLORS.IDLE,
    chipColor: 'default',
  },
  silent: {
    label: 'Silent',
    color: STATUS_COLORS.SILENT,
    chipColor: 'warning',
  },
  monitoring: {
    label: 'Monitoring',
    color: STATUS_COLORS.IDLE,
    chipColor: 'default',
  },
  result_waiting: {
    label: 'Result waiting',
    color: STATUS_COLORS.SILENT,
    chipColor: 'warning',
  },
  planning: {
    label: 'Planning',
    color: STATUS_COLORS.SLEEPING,
    chipColor: 'default',
  },
  closed: {
    label: 'Closed',
    color: STATUS_COLORS.CLOSED,
    chipColor: 'success',
  },
  handed_over: {
    label: 'Handed Over',
    color: STATUS_COLORS.HANDED_OVER,
    chipColor: 'default',
  },
  decommissioned: {
    label: 'Decommissioned',
    color: STATUS_COLORS.DECOMMISSIONED,
    chipColor: 'default',
  },
}

export const isAwaitingUser = (status) => {
  return status === 'awaiting_user'
}

const WAKE_SIGNAL_MARKER = /\bwake_mode=signal\b/
const WAKE_TIMER_MARKER = /\bwake_in_minutes=(\d+)\b/

export const getStatusLabel = (status, blockReason = '') => {
  if (isAwaitingUser(status)) return 'Needs decision'
  if (status === 'sleeping' && typeof blockReason === 'string') {
    if (WAKE_SIGNAL_MARKER.test(blockReason)) return 'Waiting for wake'
    const timer = blockReason.match(WAKE_TIMER_MARKER)
    if (timer) return `Sleeping (${timer[1]}m)`
  }
  return statusConfig[status]?.label || 'Unknown'
}

export const getStatusColor = (status) => {
  if (isAwaitingUser(status)) return STATUS_COLORS.CLOSEOUT
  return statusConfig[status]?.color || STATUS_COLORS.FALLBACK
}
