/**
 * notificationRouting.js — FE-9191
 *
 * Pure route-resolution helpers extracted from NotificationDropdown.vue so the
 * host component and specs import the SAME code (reviewDispatch.js precedent).
 *
 * Edition scope: Both.
 */
import { hubThreadRoute, MENTION_FOCUS, APPROVAL_FOCUS } from '@/components/hub/hubThreadRoute'

/**
 * IMP-5037a: client-side type → named route mapping. The server does NOT
 * provide cta_route in the payload (5037b concern); all navigation is
 * resolved here by notification type.
 */
export const TYPE_ROUTE_MAP = {
  // api_key.expiring_soon → Tools connect tab (ApiKeyManager lives there)
  'api_key.expiring_soon': () => ({ name: 'Tools', query: { tab: 'connect' } }),
  // FE-9222: the context-tuning-due system banner deep-links to the Products
  // view, which opens the ProductTuningDialog for ?tune=<product_id>. Routing
  // it through this shared map (rather than the bare cta_route named-route the
  // banner emits) is what lets it carry the product context the tune dialog
  // needs — and keeps the banner and the bell on one routing source of truth.
  'system.context_tuning_due': (n) => ({ name: 'Products', query: { tune: productIdOf(n) } }),
  // FE-9289c: a Message Hub handover ("It's your call") lands on its thread. The
  // client-local _local row carries the thread id in metadata; Answer routes here and
  // HubView selects the thread on arrival (works from a cold page).
  //
  // FE-9418: built by hubThreadRoute() rather than by hand. These two rows and the two
  // surfaces that already used the helper — the app-wide banner and the Hub's attention
  // strip — are FOUR notifications raised by ONE hand-off, and until this change the
  // bell pair arrived without the baton context the other pair carried: same event,
  // same thread, one landing that marked the post and one that marked nothing. A
  // hand-built literal is how that happens, so there is no longer one here.
  //
  // Neither row can name a message: the client-local row stores only `{ thread_id }`
  // and the server row's payload schema is thread_id/chat_id/handed_by under
  // extra="forbid". The helper therefore omits the anchor and the Hub falls back to the
  // thread's newest post — the pre-FE-9418 behaviour, unchanged and still correct.
  handover: (n) => hubThreadRoute(threadIdOf(n)),
  // BE-9296a: the SERVER row for the same event. FE-9289c's `handover` above is
  // client-local (localStorage), so it does not exist after a reload or on a second
  // device; this type is the durable one the server writes. Same destination on
  // purpose — the two rows describe one hand-off and must land in the same place, and
  // sharing the helper is now what guarantees it instead of two literals agreeing.
  // threadIdOf already falls back to payload.thread_id, which is where the server
  // row carries it.
  'hub.baton_handover': (n) => hubThreadRoute(threadIdOf(n)),
  // FE-9436: the other two things that need the operator. Same helper, same landing
  // mechanism, and the reason is the only argument that differs — which is the operator
  // ruling expressed as code rather than as a comment.
  //
  // Unlike the two rows above, these CAN name a post: they are written from a
  // `thread_message` event, which carries message_id where the baton's `thread_update`
  // does not. So the row that could always have been exact finally is, and the row that
  // structurally cannot still lands on the thread tail. One rule, two honest outcomes.
  'hub.mention': (n) => hubThreadRoute(threadIdOf(n), { reason: MENTION_FOCUS, messageId: messageIdOf(n) }),
  'hub.approval': (n) => hubThreadRoute(threadIdOf(n), { reason: APPROVAL_FOCUS, messageId: messageIdOf(n) }),
}

/**
 * Handover 0831 / 0842d: these notification types keep the user on the
 * current page — clicking them must not navigate anywhere.
 */
const STAY_ON_PAGE_TYPES = new Set(['context_tuning', 'vision_analysis'])

/**
 * FE-9191: closeout-family notifications land on the project's Implementation
 * (jobs) tab — the closeout pill, Review project button, and decision surfaces
 * live there, not on the Launch tab. The bare project route otherwise falls to
 * ProjectTabs' generic default tab ('launch'), which is deliberate for every
 * other family, so the retarget is scoped per notification type here.
 */
export const CLOSEOUT_NOTIFICATION_TYPES = new Set([
  'project.pre_launch_workproduct', // BE-9085: closed-out-without-launch alarm
  'closeout.approval_required', // BE-9153: HITL closeout gate approval
])

/**
 * The project id a notification points at. Handover 0259 rows carry it in
 * metadata.project_id; structured-payload rows (BE-9085, TSK-9090) carry it
 * in payload.project_id. Read either so both deep-link to the project.
 */
export const projectIdOf = (n) => n?.metadata?.project_id ?? n?.payload?.project_id

/**
 * FE-9222: the product id a context-tuning banner points at. Structured-payload
 * rows carry it in payload.product_id; metadata-style rows in
 * metadata.product_id. Read either, mirroring projectIdOf. Module-local — only
 * the context-tuning route factory below consumes it.
 */
const productIdOf = (n) => n?.payload?.product_id ?? n?.metadata?.product_id

/**
 * FE-9289c: the thread id a Message Hub handover points at. Carried in metadata (the
 * client-local row) or payload, mirroring projectIdOf. Module-local — only the handover
 * route factory consumes it.
 */
const threadIdOf = (n) => n?.metadata?.thread_id ?? n?.payload?.thread_id

/**
 * FE-9436: the post a Hub notification points at, read from either shape for the same
 * reason threadIdOf is. Null when the row names none — the hand-off rows never do, and
 * the helper omits the anchor rather than emitting an empty one.
 */
const messageIdOf = (n) => n?.metadata?.message_id ?? n?.payload?.message_id ?? null

/**
 * Project deep-link for a notification, closeout-family-aware.
 * Returns null when the notification carries no project context.
 */
export function projectRouteFor(notification) {
  const projectId = projectIdOf(notification)
  if (!projectId) return null
  const route = { name: 'ProjectLaunch', params: { projectId } }
  if (CLOSEOUT_NOTIFICATION_TYPES.has(notification?.type)) {
    route.query = { tab: 'jobs' }
  }
  return route
}

/**
 * Full click resolution: stay-on-page carve-outs first, then the explicit
 * type → route map, then the project-context fallback. Returns null when the
 * click should not navigate.
 */
export function resolveNotificationRoute(notification) {
  if (STAY_ON_PAGE_TYPES.has(notification?.type)) return null
  const routeFactory = TYPE_ROUTE_MAP[notification?.type]
  if (routeFactory) return routeFactory(notification)
  return projectRouteFor(notification)
}
