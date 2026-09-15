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

const reconnectResyncCallbacks = new Set()

export function registerReconnectResync(callback) {
  if (typeof callback !== 'function') return () => {}
  reconnectResyncCallbacks.add(callback)
  return () => reconnectResyncCallbacks.delete(callback)
}

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

const PROJECT_SCOPED_EVENTS = new Set([
  'agent:status_changed',
  'agent:created',
  'agent:removed',
  'agent:update',
  'job:progress_update',
])

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

export const EVENT_MAP = {
  ...AGENT_EVENT_ROUTES,
  ...COMM_HUB_EVENT_ROUTES,
  ...PROJECT_EVENT_ROUTES,
  ...SEQUENCE_EVENT_ROUTES,
  ...SYSTEM_EVENT_ROUTES,
}

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

const GLOBAL_ACTIVITY_EVENT_TYPES = new Set([
  'agent:created',
  'agent:status_changed',
  'agent:removed',
  'job:progress_update',
])

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
    approvalsStore.handleStatusEvent(payload).catch((error) => {
      // eslint-disable-next-line no-console
      console.debug('[websocketEventRouter] global-activity approvals refresh failed:', error?.message)
    })
  }

  return true
}

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

  unregister.push(
    resolvedWsStore.on('*', (event) => {
      try {
        routeGlobalActivityEvent(event, { storeRegistry })
      } catch (error) {
        console.error('[websocketEventRouter] Unhandled global-activity routing error:', error)
      }
    }),
  )

  unregister.push(
    resolvedWsStore.on('*', (event) => {
      try {
        routeProductActivityEvent(event, { storeRegistry })
      } catch (error) {
        console.error('[websocketEventRouter] Unhandled product-activity routing error:', error)
      }
    }),
  )

  unregister.push(
    resolvedWsStore.onConnectionChange((connectionEvent) => {
      if (connectionEvent?.state === 'connected' && connectionEvent?.isReconnect) {
        return runReconnectResyncs()
      }
    }),
  )

  isInitialized = true
}
