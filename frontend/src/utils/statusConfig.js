/**
 * Status configuration for agent job status display
 * Provides consistent status labels, colors, and styles across JobsTab and other components
 *
 * Handover 0243c: Dynamic Status Display with real-time WebSocket updates
 */

// Status color tokens — keep in sync with design-tokens.scss ($color-status-*)
const STATUS_COLORS = {
  WAITING: '#ffd700',     // $color-status-waiting
  WORKING: '#ffffff',     // $color-status-working
  BLOCKED: '#ff9800',     // $color-status-blocked
  COMPLETE: '#67bd6d',    // $color-status-complete
  IDLE: '#7a9bb5',        // $color-status-idle
  SLEEPING: '#9b89b3',    // $color-status-sleeping
  HANDED_OVER: '#9e9e9e', // $color-status-handed-over
  CLOSED: '#4a9c5f',      // $color-status-closed (darker green, signals finality)
  DECOMMISSIONED: '#757575', // $color-status-decommissioned
  CLOSEOUT: '#ffc107',    // $color-status-staged — amber for closeout decision required
  FALLBACK: '#666666',    // Fallback muted
}

// JobsTab-specific status configuration (Handover 0243c)
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
  // Handover 0880: Agent resting states
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
  // FE-9239: a chain member actively being staged (Project.staging_status
  // 'staging'/'staged') — distinct from generic 'waiting' so a staged chain
  // project doesn't look identical to a genuinely-queued one.
  planning: {
    label: 'Planning',
    color: STATUS_COLORS.SLEEPING, // $color-status-sleeping — matches chain-tab__badge--planning
    italic: false,
    chipColor: 'default',
  },
  // Handover 0435b: Final acceptance by orchestrator
  closed: {
    label: 'Closed',
    color: STATUS_COLORS.CLOSED,
    italic: false,
    chipColor: 'success',
  },
  // Handover 0506: Status after orchestrator hands over to successor
  handed_over: {
    label: 'Handed Over',
    color: STATUS_COLORS.HANDED_OVER,
    italic: false,
    chipColor: 'default',
  },
  // Agent ID Swap: Status for old orchestrator after succession (ID swapped to decomm-xxx)
  decommissioned: {
    label: 'Decommissioned',
    color: STATUS_COLORS.DECOMMISSIONED,
    italic: false,
    chipColor: 'default',
  },
}

/**
 * Check if an agent is awaiting a user-approval decision.
 * BE-5029 / FE-5017 Phase C: replaced the legacy
 * (status === 'blocked' && blockReason.startsWith('Closeout')) heuristic
 * with the canonical 'awaiting_user' status flipped server-side by
 * UserApprovalService.create_pending().
 *
 * @param {string} status - Agent status value
 * @returns {boolean}
 */
export const isAwaitingUser = (status) => {
  return status === 'awaiting_user'
}

// FE-9296b: structured markers set_agent_status stores in block_reason. The
// service builds these (never free prose), so matching them is mechanism, not
// string-guessing: `wake_mode=signal` = parked on get_my_turn(wait_seconds=...)
// (BE-9296a wake) — without wait_seconds that call answers immediately, so the
// agent is polling rather than parked and no signal marker is set;
// `wake_in_minutes=N` = timed sleep of N minutes.
const WAKE_SIGNAL_MARKER = /\bwake_mode=signal\b/
const WAKE_TIMER_MARKER = /\bwake_in_minutes=(\d+)\b/

/**
 * Get human-readable label for status.
 * When the agent is awaiting_user, returns "Decision Required" instead of "Needs Input".
 * FE-9296b: a sleeping agent's block_reason markers split the label three ways —
 * "Waiting for wake" (parked on the server wake signal), "Sleeping (Nm)" (timed
 * sleep), plain "Sleeping" (no marker). "Dark" stays the distinct 'silent' status.
 * @param {string} status - Agent status value
 * @param {string} [blockReason] - The agent's block_reason (carries wake markers)
 * @returns {string} Display label
 */
export const getStatusLabel = (status, blockReason = '') => {
  if (isAwaitingUser(status)) return 'Decision Required'
  if (status === 'sleeping' && typeof blockReason === 'string') {
    if (WAKE_SIGNAL_MARKER.test(blockReason)) return 'Waiting for wake'
    const timer = blockReason.match(WAKE_TIMER_MARKER)
    if (timer) return `Sleeping (${timer[1]}m)`
  }
  return statusConfig[status]?.label || 'Unknown'
}

/**
 * Get color for status display.
 * awaiting_user uses amber (#ffc107) to distinguish from generic blocked orange.
 * @param {string} status - Agent status value
 * @returns {string} Hex color code
 */
export const getStatusColor = (status) => {
  if (isAwaitingUser(status)) return STATUS_COLORS.CLOSEOUT
  return statusConfig[status]?.color || STATUS_COLORS.FALLBACK
}

/**
 * Check if status should be displayed in italic
 * @param {string} status - Agent status value
 * @returns {boolean} True if italic
 */
export const isStatusItalic = (status) => {
  return statusConfig[status]?.italic || false
}
