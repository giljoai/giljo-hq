import { hubThreadRoute, MENTION_FOCUS, APPROVAL_FOCUS } from '@/components/hub/hubThreadRoute'

export const TYPE_ROUTE_MAP = {
  'api_key.expiring_soon': () => ({ name: 'Tools', query: { tab: 'connect' } }),
  'system.context_tuning_due': (n) => ({ name: 'Products', query: { tune: productIdOf(n) } }),
  handover: (n) => hubThreadRoute(threadIdOf(n)),
  'hub.baton_handover': (n) => hubThreadRoute(threadIdOf(n)),
  'hub.mention': (n) => hubThreadRoute(threadIdOf(n), { reason: MENTION_FOCUS, messageId: messageIdOf(n) }),
  'hub.approval': (n) => hubThreadRoute(threadIdOf(n), { reason: APPROVAL_FOCUS, messageId: messageIdOf(n) }),
}

const STAY_ON_PAGE_TYPES = new Set(['context_tuning', 'vision_analysis'])

export const CLOSEOUT_NOTIFICATION_TYPES = new Set([
  'project.pre_launch_workproduct',
  'closeout.approval_required',
])

export const projectIdOf = (n) => n?.project_id ?? n?.metadata?.project_id ?? n?.payload?.project_id

const productIdOf = (n) => n?.product_id ?? n?.payload?.product_id ?? n?.metadata?.product_id

const threadIdOf = (n) => n?.metadata?.thread_id ?? n?.payload?.thread_id

const messageIdOf = (n) => n?.metadata?.message_id ?? n?.payload?.message_id ?? null

export function projectRouteFor(notification) {
  const projectId = projectIdOf(notification)
  if (!projectId) return null
  const route = { name: 'JobsViewport', query: { project: projectId } }
  if (CLOSEOUT_NOTIFICATION_TYPES.has(notification?.type)) {
    route.query.detail = '1'
  }
  return route
}

export function resolveNotificationRoute(notification) {
  if (STAY_ON_PAGE_TYPES.has(notification?.type)) return null
  const routeFactory = TYPE_ROUTE_MAP[notification?.type]
  if (routeFactory) return routeFactory(notification)
  return projectRouteFor(notification)
}
