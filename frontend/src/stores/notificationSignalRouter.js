import { useUserStore } from './user'
import { normalizeWebsocketPayload } from '@/utils/normalizeWebsocketPayload'

// eslint-disable-next-line giljo-internal/no-orphaned-exports -- classifier vocabulary; asserted in tests/stores/notificationSignalRouter.fe9553.spec.js (outside src/)
export const SIGNAL_ACTIONABLE = 'actionable'

// eslint-disable-next-line giljo-internal/no-orphaned-exports -- classifier vocabulary; asserted in tests/stores/notificationSignalRouter.fe9553.spec.js (outside src/)
export const SIGNAL_LIFECYCLE = 'lifecycle'

export const SIGNAL_ADVISORY = 'advisory'

const CONDITIONAL_ACTIONABLE = {
  'agent:status_changed': (payload) =>
    Boolean(payload?.user_approval_id || payload?.decided_option_id),
  thread_message: (payload) =>
    Boolean(payload?.requires_action) && Boolean(payload?.to_participant),
  thread_update: (payload) => Boolean(payload?.next_action_owner),
}

const ALWAYS_ACTIONABLE = new Set([
  'closeout.approval_required',
  'hub.baton_handover',
  'hub.mention',
  'hub.approval',
])

const LIFECYCLE = new Set([
  'project:staging_complete',
  'project:implementation_launched',
  'project:launched',
  'project:created',
  'agent:created',
  'agent:removed',
  'agent:status_changed',
  'agent:update',
  'job:progress_update',
  'sequence:updated',
  'orchestrator:handover_initiated',
  'orchestrator:prompt_generated',
  'thread_message',
  'thread_update',
])

const ADVISORY = new Set([
  'system:update_available',
  'system.update_available',
  'system.pending_migrations',
  'system.skills_drift',
  'system.context_tuning_due',
  'system.tool_rename_notice',
  'api_key.expiring_soon',
  'agent:health_alert',
  'agent:silent',
  'agent:auto_failed',
  'vision:analysis_started',
  'vision:analysis_complete',
  'product:context_updated',
  'project:memory_updated',
  'product:memory:updated',
])

export function classifySignal(type, payload = {}) {
  if (!type) return null

  if (ALWAYS_ACTIONABLE.has(type)) {
    return { kind: SIGNAL_ACTIONABLE, surface: 'banner' }
  }

  const condition = CONDITIONAL_ACTIONABLE[type]
  if (typeof condition === 'function' && condition(payload)) {
    return { kind: SIGNAL_ACTIONABLE, surface: 'banner' }
  }

  if (ADVISORY.has(type)) {
    return { kind: SIGNAL_ADVISORY, surface: 'bell' }
  }

  if (LIFECYCLE.has(type)) {
    return { kind: SIGNAL_LIFECYCLE, surface: 'banner' }
  }

  return null
}

function isSameTenant(payload) {
  const currentTenantKey = useUserStore()?.currentUser?.tenant_key
  if (!currentTenantKey) return true
  if (payload?.tenant_key && payload.tenant_key !== currentTenantKey) return false
  return true
}

// eslint-disable-next-line giljo-internal/no-orphaned-exports -- wired into initWebsocketEventRouter as the fourth pass in M2, when the popout sink consumes it; imported in tests/stores/notificationSignalRouter.fe9553.spec.js (outside src/)
export function routeNotificationSignal(rawEvent) {
  const { type, payload } = normalizeWebsocketPayload(rawEvent)
  if (!type) return false

  const signal = classifySignal(type, payload)
  if (!signal) return false

  if (!isSameTenant(payload)) return false

  return true
}
