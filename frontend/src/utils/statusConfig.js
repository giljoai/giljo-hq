
const STATUS_COLORS = {
  WAITING: '#ffd700',
  WORKING: '#ffffff',
  BLOCKED: '#ff9800',
  COMPLETE: '#67bd6d',
  IDLE: '#7a9bb5',
  SLEEPING: '#9b89b3',
  HANDED_OVER: '#9e9e9e',
  CLOSED: '#4a9c5f',
  DECOMMISSIONED: '#757575',
  CLOSEOUT: '#ffc107',
  FALLBACK: '#666666',
}

const statusConfig = {
  waiting: {
    label: 'Waiting.',
    color: STATUS_COLORS.WAITING,
    italic: true,
    chipColor: 'warning',
  },
  working: {
    label: 'Working',
    color: STATUS_COLORS.WORKING,
    italic: true,
    chipColor: 'default',
  },
  blocked: {
    label: 'Needs Input',
    color: STATUS_COLORS.BLOCKED,
    italic: false,
    chipColor: 'warning',
  },
  complete: {
    label: 'Complete',
    color: STATUS_COLORS.COMPLETE,
    italic: false,
    chipColor: 'success',
  },
  idle: {
    label: 'Monitoring',
    color: STATUS_COLORS.IDLE,
    italic: true,
    chipColor: 'default',
  },
  sleeping: {
    label: 'Sleeping',
    color: STATUS_COLORS.SLEEPING,
    italic: true,
    chipColor: 'default',
  },
  silent: {
    label: 'Silent',
    color: STATUS_COLORS.BLOCKED,
    italic: false,
    chipColor: 'warning',
  },
  planning: {
    label: 'Planning',
    color: STATUS_COLORS.SLEEPING,
    italic: false,
    chipColor: 'default',
  },
  closed: {
    label: 'Closed',
    color: STATUS_COLORS.CLOSED,
    italic: false,
    chipColor: 'success',
  },
  handed_over: {
    label: 'Handed Over',
    color: STATUS_COLORS.HANDED_OVER,
    italic: false,
    chipColor: 'default',
  },
  decommissioned: {
    label: 'Decommissioned',
    color: STATUS_COLORS.DECOMMISSIONED,
    italic: false,
    chipColor: 'default',
  },
}

export const isAwaitingUser = (status) => {
  return status === 'awaiting_user'
}

const WAKE_SIGNAL_MARKER = /\bwake_mode=signal\b/
const WAKE_TIMER_MARKER = /\bwake_in_minutes=(\d+)\b/

export const getStatusLabel = (status, blockReason = '') => {
  if (isAwaitingUser(status)) return 'Decision Required'
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

export const isStatusItalic = (status) => {
  return statusConfig[status]?.italic || false
}
