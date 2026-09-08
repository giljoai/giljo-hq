/**
 * notificationSignalRouter.js — FE-9553
 *
 * The single authority for "which surface owns this event".
 *
 * The product had grown four notification surfaces with overlapping jobs and
 * nothing arbitrating between them: one `thread_message` could land on the Hub
 * timeline, a waiting-count badge, a bell row, a toast, a browser popout AND
 * the your-turn banner, because each sink was wired independently. The ruled
 * model assigns each surface exactly one job, keyed on WHO caused the event:
 *
 *   toast   past tense, the USER's own action, seconds        feedback
 *   banner  present tense, the AGENTS' action, until handled  the only actionable surface
 *   popout  the banner, delivered when the app is hidden      a medium, not a class
 *   bell    past tense, anything, durable                     the archive, never alerts
 *
 * The binding rule: every event lives on exactly ONE live surface (toast XOR
 * banner). This module is where that decision is made, so it is made once.
 *
 * WHY A CLASSIFIER AND NOT A NEW SINK: the sinks already exist and each one
 * already owns its writes (lifecycleBannerStore announces banner rows, the
 * notification store owns bell rows). Adding a fifth writer here would be the
 * parallel write path the house rules forbid. So this module decides and the
 * existing owners consult it -- one decision, unchanged ownership.
 *
 * routeNotificationSignal is a FOURTH independent pass over the same raw WS
 * event stream, alongside routeGlobalActivityEvent (FE-9501b, project-not-open
 * would otherwise be invisible) and routeProductActivityEvent (FE-9502d,
 * product-not-viewed would otherwise be invisible). It is not just another
 * EVENT_MAP entry for the same reason those two are not: it must see every
 * event regardless of which project or product is open, since "which surface
 * should this land on" does not depend on what the operator happens to be
 * looking at.
 *
 * Edition Scope: Both
 */
import { useUserStore } from './user'
import { normalizeWebsocketPayload } from '@/utils/normalizeWebsocketPayload'

/**
 * Decisions, your-turn batons and mentions. ALWAYS banner, never toggleable --
 * a settings menu must never unplug the doorbell for decisions the system
 * blocks on, which is why the settings surface states this in text rather than
 * offering a switch.
 */
// SIGNAL_ADVISORY and classifySignal have a real consumer in src/ as of M4:
// the notification store's bannerNotifications getter asks the classifier
// whether a row is advisory before admitting it to the banner fold. Their
// orphaned-export annotations are gone accordingly.
//
// The two constants below are still test-only. They are the classifier's
// vocabulary rather than a value any sink needs to name yet, so they keep a
// truthful annotation instead of being deleted -- a classifier whose kinds
// cannot be referred to by name is harder to test and harder to read.
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- classifier vocabulary; asserted in tests/stores/notificationSignalRouter.fe9553.spec.js (outside src/)
export const SIGNAL_ACTIONABLE = 'actionable'

/** started / finished. Banner by default; the one banner toggle that exists. */
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- classifier vocabulary; asserted in tests/stores/notificationSignalRouter.fe9553.spec.js (outside src/)
export const SIGNAL_LIFECYCLE = 'lifecycle'

/** Bell-first. Never pops, and reaches the banner fold only if the user opts in. */
export const SIGNAL_ADVISORY = 'advisory'

/**
 * Event types that are actionable ONLY when the payload says so.
 *
 * The distinction the whole model rests on: `agent:status_changed` is a
 * decision the system is blocked on when it carries an approval id, and
 * routine progress otherwise. Same event type, different surface -- so
 * classification cannot be a type lookup alone.
 */
const CONDITIONAL_ACTIONABLE = {
  'agent:status_changed': (payload) =>
    Boolean(payload?.user_approval_id || payload?.decided_option_id),
  // A DIRECTED action-request is a baton; a BROADCAST one is not.
  //
  // FE-9586 (BE-9197) settled this: a broadcast requires_action post is
  // "whoever picks it up" and obligates nobody in particular, so it raises no
  // actionable signal -- it keeps its durable bell row and nothing else. The
  // server's directed-action query had always excluded broadcasts; the client's
  // signal gate quietly contradicted that until FE-9586 aligned it.
  //
  // This classifier has to match `getSignal()` in useHubNotifications exactly.
  // It did not, for a while: I classified on `requires_action` alone while the
  // gate had moved on. It was harmless only because nothing consulted the
  // classifier on that path yet, and "harmless today" is not a state to leave a
  // disagreement in -- the next consumer would have inherited it silently.
  // Aligned here in the same commit as the popout-scope gate so the two can
  // never ship out of step.
  thread_message: (payload) =>
    Boolean(payload?.requires_action) && Boolean(payload?.to_participant),
  thread_update: (payload) => Boolean(payload?.next_action_owner),
}

/** Unconditionally actionable: the server already decided it needs a human. */
const ALWAYS_ACTIONABLE = new Set([
  'closeout.approval_required',
  'hub.baton_handover',
  'hub.mention',
  'hub.approval',
])

/**
 * Lifecycle: the agents started or finished something. These dominate banner
 * volume in busy sessions, which is why the scope control exists at all.
 */
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

/**
 * Advisory: true, useful, and not about anything the operator must do now.
 * These are the bell's natural tenants. A health alert lives here rather than
 * in the actionable set deliberately -- the ruled actionable list is decisions,
 * your-turn and mentions, and an alert is none of those. It already writes a
 * bell row today, so this matches shipped behaviour rather than changing it.
 */
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

/**
 * Which surface owns this event, or null if this module has no opinion.
 *
 * Returning null rather than a default is deliberate: an unrecognised event
 * type must not be silently assigned a surface it was never designed for. A
 * caller that gets null leaves today's behaviour alone, which is what makes
 * this safe to introduce ahead of the sinks that consume it.
 *
 * @param {string} type - the WS event type or server notification type
 * @param {object} payload - the normalized event payload
 * @returns {{kind: string, surface: 'banner'|'bell'}|null}
 */
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

/** Tenant check, matching the three sibling passes in websocketEventRouter.js. */
function isSameTenant(payload) {
  const currentTenantKey = useUserStore()?.currentUser?.tenant_key
  if (!currentTenantKey) return true
  if (payload?.tenant_key && payload.tenant_key !== currentTenantKey) return false
  return true
}

/**
 * The fourth pass. Classifies one raw WS event and records the decision for
 * the surfaces to read.
 *
 * There is no toast path in this function, and that absence is the point: a
 * toast is feedback for the user's own click, and nothing arriving over the
 * WebSocket is the user's own click. The rule is therefore structural here
 * rather than a convention every future sink has to remember.
 *
 * @returns {boolean} true when the event was classified, false when dropped
 */
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- wired into initWebsocketEventRouter as the fourth pass in M2, when the popout sink consumes it; imported in tests/stores/notificationSignalRouter.fe9553.spec.js (outside src/)
export function routeNotificationSignal(rawEvent) {
  const { type, payload } = normalizeWebsocketPayload(rawEvent)
  if (!type) return false

  const signal = classifySignal(type, payload)
  if (!signal) return false

  if (!isSameTenant(payload)) return false

  return true
}
