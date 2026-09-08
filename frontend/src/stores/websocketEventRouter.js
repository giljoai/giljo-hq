import { useWebSocketStore } from './websocket'
import { useAgentJobsStore } from './agentJobsStore'
import { useProjectStateStore } from './projectStateStore'
import { useProjectStore } from './projects'
import { useTaskStore } from './tasks'
import { useProductStore } from './products'
import { useProjectTabsStore } from './projectTabs'
import { useUserStore } from '@/stores/user'
import { normalizeWebsocketPayload } from '@/utils/normalizeWebsocketPayload'

import { AGENT_EVENT_ROUTES } from './eventRoutes/agentEventRoutes'
import { COMM_HUB_EVENT_ROUTES } from './eventRoutes/commHubEventRoutes'
import { PROJECT_EVENT_ROUTES } from './eventRoutes/projectEventRoutes'
import { SEQUENCE_EVENT_ROUTES } from './eventRoutes/sequenceEventRoutes'
import { SYSTEM_EVENT_ROUTES } from './eventRoutes/systemEventRoutes'
import { useCommHubStore } from './commHubStore'
import { useSequenceRunStore } from './sequenceRunStore'
import { useGlobalActivityStore } from './globalActivityStore'
import { useProductActivityStore } from './productActivityStore'
import { useApprovalsStore } from './useApprovalsStore'
import { useMemoryStore } from './memoryStore'

const STORE_REGISTRY = {
  agentJobs: () => useAgentJobsStore(),
  agents: () => useAgentJobsStore(),
  commHub: () => useCommHubStore(),
  projectState: () => useProjectStateStore(),
  projects: () => useProjectStore(),
  tasks: () => useTaskStore(),
  products: () => useProductStore(),
  projectTabs: () => useProjectTabsStore(),
  sequenceRun: () => useSequenceRunStore(),
  globalActivity: () => useGlobalActivityStore(),
  productActivity: () => useProductActivityStore(),
  approvals: () => useApprovalsStore(),
  memory: () => useMemoryStore(),
}

// =========================================================================
// FE-3007b: generalized reconnect-resync registry
// =========================================================================
// Any store/view registers a resync callback; on a WS reconnect (automatic OR
// manual) EVERY registered callback refetches. This replaces the previous
// hardcoded "messages-only" single callback and the scattered per-view
// onConnectionChange resync blocks (DefaultLayout, useProjectTabsLifecycle,
// JobsTab). The router owns the ONE connection listener; views just register.
const reconnectResyncCallbacks = new Set()

/**
 * Register a resync callback fired on every WS reconnect.
 * @param {Function} callback - invoked (no args) on reconnect; may be async.
 * @returns {Function} unregister fn (call on teardown/unmount).
 */
export function registerReconnectResync(callback) {
  if (typeof callback !== 'function') return () => {}
  reconnectResyncCallbacks.add(callback)
  return () => reconnectResyncCallbacks.delete(callback)
}

/**
 * Run every registered resync callback. allSettled so one store's failed
 * refetch never blocks the others from refreshing. Internal — fired by the
 * router's single connection listener; tests drive it through that listener.
 */
async function runReconnectResyncs() {
  await Promise.allSettled(
    Array.from(reconnectResyncCallbacks).map((cb) => {
      try {
        return Promise.resolve(cb())
      } catch (error) {
        return Promise.reject(error)
      }
    }),
  )
}

// Handover 0463: Project-scoped event types that require project filtering
const PROJECT_SCOPED_EVENTS = new Set([
  'agent:status_changed',
  'agent:created',
  'agent:removed', // BE-6123: project-filtered like agent:created
  'agent:update',
  'job:progress_update',
])

/** Tenant check shared by defaultShouldRoute and the global-activity pass below. */
function isSameTenant(payload) {
  const currentTenantKey = useUserStore()?.currentUser?.tenant_key
  if (!currentTenantKey) return true
  if (payload?.tenant_key && payload.tenant_key !== currentTenantKey) return false
  return true
}

// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported in tests/stores/websocketEventRouter.*.spec.js (outside src/)
export function defaultShouldRoute(type, payload) {
  const currentTenantKey = useUserStore()?.currentUser?.tenant_key

  if (!currentTenantKey) {
    return true
  }

  if (payload?.tenant_key && payload.tenant_key !== currentTenantKey) {
    return false
  }

  // Handover 0463: Project-aware filtering to prevent cross-project ghost rows
  if (PROJECT_SCOPED_EVENTS.has(type)) {
    const projectTabsStore = useProjectTabsStore()
    const currentProjectId = projectTabsStore?.currentProject?.id

    if (currentProjectId && payload?.project_id) {
      if (payload.project_id !== currentProjectId) {
        // eslint-disable-next-line no-console
        console.debug('[websocketEventRouter] Dropping cross-project event:', {
          type,
          event_project: payload.project_id,
          current_project: currentProjectId,
        })
        return false
      }
    }

    if (currentProjectId && !payload?.project_id && type === 'agent:status_changed') {
      // eslint-disable-next-line no-console
      console.debug('[websocketEventRouter] Dropping status event without project_id:', {
        type,
        job_id: payload?.job_id,
      })
      return false
    }
  }

  return true
}

/** Composed event map from domain-specific route files */
export const EVENT_MAP = {
  ...AGENT_EVENT_ROUTES,
  ...COMM_HUB_EVENT_ROUTES,
  ...PROJECT_EVENT_ROUTES,
  ...SEQUENCE_EVENT_ROUTES,
  ...SYSTEM_EVENT_ROUTES,
}

/**
 * Route a single WebSocket event to the configured store action.
 */
export async function routeWebsocketEvent(
  rawEvent,
  { eventMap, storeRegistry, shouldRoute } = {},
) {
  const { type, payload } = normalizeWebsocketPayload(rawEvent)
  if (!type) return false

  const routeConfig = eventMap?.[type]
  if (!routeConfig) return false

  if (typeof shouldRoute === 'function' && !shouldRoute(type, payload)) {
    return false
  }

  if (typeof routeConfig.filter === 'function' && !routeConfig.filter(payload)) {
    return false
  }

  const transformedPayload =
    typeof routeConfig.transform === 'function' ? routeConfig.transform(payload) : payload

  if (typeof routeConfig.handler === 'function') {
    await routeConfig.handler(transformedPayload, {
      type,
      payload: transformedPayload,
      storeRegistry,
    })
    return true
  }

  const storeFactory = storeRegistry?.[routeConfig.store]
  if (typeof storeFactory !== 'function') return false

  const store = storeFactory()
  const action = store?.[routeConfig.action]
  if (typeof action !== 'function') return false

  await action.call(store, transformedPayload)
  return true
}

// FE-9501b (D5, D6): the events this pass cares about, out of the whole EVENT_MAP --
// the same agent/job lifecycle types PROJECT_SCOPED_EVENTS filters above, so an
// unopened project's activity is still counted somewhere even while the main
// pass drops it for agentJobsStore.
const GLOBAL_ACTIVITY_EVENT_TYPES = new Set([
  'agent:created',
  'agent:status_changed',
  'agent:removed',
  'job:progress_update',
])

/**
 * FE-9501b (D5, D6): a SECOND, independent routing pass over the same raw
 * events the main pass sees -- additive, not a replacement. defaultShouldRoute
 * and PROJECT_SCOPED_EVENTS (and every ghost-row guard in agentJobsStore) are
 * untouched; this pass only ever WRITES to two places, and both are cheap:
 *
 *   1. globalActivityStore.recordActivity(project_id) -- a Map increment, no
 *      fetch, for every agent/job lifecycle event regardless of which tab is
 *      open. Feeds the "Projects" nav badge (D5).
 *   2. approvalsStore.handleStatusEvent(payload) -- ONLY when the event
 *      carries user_approval_id/decided_option_id, exactly the fields that
 *      already gate it inside agentEventRoutes.js's project-scoped handler.
 *      That handler never runs at all for a project that isn't the open tab
 *      (shouldRoute drops the event first), which is D6: an approval raised
 *      on an unopened project never reaches the store that feeds the
 *      raised-hand banner. This pass is the fix -- same trigger condition,
 *      just not gated on the open tab.
 *
 * Only the tenant check applies here (via isSameTenant) -- deliberately no
 * project-match check, since "count/surface activity for a project I don't
 * have open" is the entire point.
 */
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported in tests/stores/websocketEventRouter.*.spec.js (outside src/)
export function routeGlobalActivityEvent(rawEvent, { storeRegistry = STORE_REGISTRY } = {}) {
  const { type, payload } = normalizeWebsocketPayload(rawEvent)
  if (!type || !GLOBAL_ACTIVITY_EVENT_TYPES.has(type)) return false
  if (!isSameTenant(payload)) return false

  const projectId = payload?.project_id
  if (projectId) {
    const activityStore = storeRegistry?.globalActivity?.() ?? useGlobalActivityStore()
    activityStore.recordActivity(projectId)
  }

  if (type === 'agent:status_changed' && (payload?.user_approval_id || payload?.decided_option_id)) {
    const approvalsStore = storeRegistry?.approvals?.() ?? useApprovalsStore()
    // Best-effort, matching agentEventRoutes.js's own handling of this same
    // payload shape: a hiccup here must never break the rest of the app, but it
    // is still logged rather than swallowed outright -- this path is now
    // reachable from every page, not just the one project tab.
    approvalsStore.handleStatusEvent(payload).catch((error) => {
      // eslint-disable-next-line no-console
      console.debug('[websocketEventRouter] global-activity approvals refresh failed:', error?.message)
    })
  }

  return true
}

// FE-9502d: the event types confirmed to carry `product_id` on at least one
// active emitter. Deliberately NOT the same set as GLOBAL_ACTIVITY_EVENT_TYPES
// above. BE-9525c closed the gap this comment used to describe --
// agent:created/agent:removed/job:progress_update now carry product_id from
// every emitter except the project-less chain conductor's own agent:created
// (conductor_job_minter.py -- sequence_runs has no product_id column, and
// that stays a declared exception, not a bug). recordActivity's falsy-id
// guard makes that specific case a no-op rather than a phantom badge, so
// admitting these three types here is safe.
const PRODUCT_ACTIVITY_EVENT_TYPES = new Set([
  'project_update',
  'task:updated',
  'agent:status_changed',
  'agent:health_alert',
  'agent:auto_failed',
  'agent:created',
  'agent:removed',
  'job:progress_update',
  'orchestrator:prompt_generated',
])

/**
 * FE-9502d: a THIRD, independent routing pass over the same raw events --
 * additive, like routeGlobalActivityEvent one level down (project-not-open ->
 * invisible; here it's product-not-viewed -> invisible). Only ever WRITES to
 * productActivityStore.recordActivity(product_id) -- a Map increment, no
 * fetch, no hydration -- feeding the ProductTabStrip badge for a background
 * tab. Deliberately no viewed-tab match check: "count activity for a product
 * I'm not looking at" is the entire point, mirroring routeGlobalActivityEvent's
 * own reasoning at the project level.
 *
 * `conductor_job_minter.py`'s agent:created has no product_id (sequence_runs
 * has no such column) -- recordActivity's falsy-id guard makes that a no-op,
 * not a bug: no invented value, no phantom badge, no crash.
 */
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported in tests/stores/websocketEventRouter.*.spec.js (outside src/)
export function routeProductActivityEvent(rawEvent, { storeRegistry = STORE_REGISTRY } = {}) {
  const { type, payload } = normalizeWebsocketPayload(rawEvent)
  if (!type || !PRODUCT_ACTIVITY_EVENT_TYPES.has(type)) return false
  if (!isSameTenant(payload)) return false

  const productId = payload?.product_id
  if (productId) {
    const activityStore = storeRegistry?.productActivity?.() ?? useProductActivityStore()
    activityStore.recordActivity(productId)
  }

  return true
}

let isInitialized = false
const unregister = []

/**
 * Initialize the router once for the entire app.
 */
export function initWebsocketEventRouter({
  wsStore = null,
  eventMap = EVENT_MAP,
  storeRegistry = STORE_REGISTRY,
  shouldRoute = null,
} = {}) {
  if (isInitialized) {
    return
  }

  const resolvedWsStore = wsStore || useWebSocketStore()
  const resolvedShouldRoute = shouldRoute || defaultShouldRoute

  unregister.push(
    resolvedWsStore.on('*', (event) =>
      routeWebsocketEvent(event, {
        eventMap,
        storeRegistry,
        shouldRoute: resolvedShouldRoute,
      }).catch((error) => {

        console.error('[websocketEventRouter] Unhandled routing error:', error)
      }),
    ),
  )

  // FE-9501b (D5, D6): independent second pass, see routeGlobalActivityEvent's
  // own doc comment for why this cannot just be another EVENT_MAP entry.
  unregister.push(
    resolvedWsStore.on('*', (event) => {
      try {
        routeGlobalActivityEvent(event, { storeRegistry })
      } catch (error) {
        console.error('[websocketEventRouter] Unhandled global-activity routing error:', error)
      }
    }),
  )

  // FE-9502d: independent third pass, one level up from the second (product-
  // not-viewed -> invisible instead of project-not-open -> invisible). See
  // routeProductActivityEvent's own doc comment.
  unregister.push(
    resolvedWsStore.on('*', (event) => {
      try {
        routeProductActivityEvent(event, { storeRegistry })
      } catch (error) {
        console.error('[websocketEventRouter] Unhandled product-activity routing error:', error)
      }
    }),
  )

  // FE-3007b: the SINGLE reconnect listener. On any reconnect (automatic via
  // backoff, or manual via wsStore.reconnect() which flags isReconnect=true)
  // fan out to every store/view that registered a resync callback.
  unregister.push(
    resolvedWsStore.onConnectionChange((connectionEvent) => {
      if (connectionEvent?.state === 'connected' && connectionEvent?.isReconnect) {
        return runReconnectResyncs()
      }
    }),
  )

  isInitialized = true
}
