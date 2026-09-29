import { describe, it, expect } from 'vitest'
import {
  resolveNotificationRoute,
  projectRouteFor,
  CLOSEOUT_NOTIFICATION_TYPES,
} from './notificationRouting'
import { hubThreadRoute, BATON_FOCUS } from '@/components/hub/hubThreadRoute'

describe('notificationRouting — FE-9191 closeout family lands on the jobs tab', () => {
  it('project.pre_launch_workproduct (payload project context) routes to ?tab=jobs', () => {
    const route = resolveNotificationRoute({
      type: 'project.pre_launch_workproduct',
      payload: { project_id: 'p-1', project_name: 'Demo' },
    })
    expect(route).toEqual({ name: 'JobsViewport', query: { project: 'p-1', detail: '1' } })
  })

  it('closeout.approval_required (payload project context) routes to ?tab=jobs', () => {
    const route = resolveNotificationRoute({
      type: 'closeout.approval_required',
      payload: { project_id: 'p-9', approval_id: 'a-1' },
    })
    expect(route).toEqual({ name: 'JobsViewport', query: { project: 'p-9', detail: '1' } })
  })

  it('closeout family with metadata-style project context also opens Jobs detail on the board', () => {
    const route = resolveNotificationRoute({
      type: 'project.pre_launch_workproduct',
      metadata: { project_id: 'p-3' },
    })
    expect(route.query).toEqual({ project: 'p-3', detail: '1' })
  })

  it('the project-name chip navigation (projectRouteFor) is family-aware too', () => {
    const closeout = projectRouteFor({
      type: 'closeout.approval_required',
      payload: { project_id: 'p-4' },
    })
    expect(closeout.query).toEqual({ project: 'p-4', detail: '1' })

    const generic = projectRouteFor({
      type: 'project_update',
      metadata: { project_id: 'p-5' },
    })
    expect(generic.query).toEqual({ project: 'p-5' })
  })

  it('the closeout family set contains exactly the two closeout notification types', () => {
    expect([...CLOSEOUT_NOTIFICATION_TYPES].sort()).toEqual([
      'closeout.approval_required',
      'project.pre_launch_workproduct',
    ])
  })
})

describe('notificationRouting — regression map: other families keep their targets', () => {
  it('api_key.expiring_soon keeps its Tools connect target', () => {
    const route = resolveNotificationRoute({ type: 'api_key.expiring_soon' })
    expect(route).toEqual({ name: 'Tools', query: { tab: 'connect' } })
  })

  it('a generic project notification lands on the board card, Jobs detail closed', () => {
    const route = resolveNotificationRoute({
      type: 'project_update',
      metadata: { project_id: 'p-2' },
    })
    expect(route).toEqual({ name: 'JobsViewport', query: { project: 'p-2' } })
  })

  it('context_tuning and vision_analysis stay on the current page (no route)', () => {
    expect(resolveNotificationRoute({ type: 'context_tuning', metadata: { project_id: 'p-6' } })).toBeNull()
    expect(resolveNotificationRoute({ type: 'vision_analysis', payload: { project_id: 'p-7' } })).toBeNull()
  })

  it('a notification without project context resolves to no route', () => {
    expect(resolveNotificationRoute({ type: 'system_alert' })).toBeNull()
    expect(projectRouteFor({ type: 'project.pre_launch_workproduct' })).toBeNull()
  })
})

describe('notificationRouting — FE-9222 context-tuning banner deep-links to the tune dialog', () => {
  it('system.context_tuning_due routes to Products with ?tune=<product_id>', () => {
    const route = resolveNotificationRoute({
      type: 'system.context_tuning_due',
      payload: { product_id: 'prod-42', product_name: 'Acme' },
    })
    expect(route).toEqual({ name: 'Products', query: { tune: 'prod-42' } })
  })

  it('reads the product id from metadata as well as payload', () => {
    const route = resolveNotificationRoute({
      type: 'system.context_tuning_due',
      metadata: { product_id: 'prod-99' },
    })
    expect(route).toEqual({ name: 'Products', query: { tune: 'prod-99' } })
  })

  it('carries an undefined tune when the row has no product context (fails soft to Products)', () => {
    const route = resolveNotificationRoute({ type: 'system.context_tuning_due' })
    expect(route).toEqual({ name: 'Products', query: { tune: undefined } })
  })

  it('FE-9289c: a handover routes to its thread THROUGH the shared helper', () => {
    const route = resolveNotificationRoute({ type: 'handover', metadata: { thread_id: 'thr-42' } })
    expect(route).toEqual(hubThreadRoute('thr-42'))
    expect(route).toEqual({ path: '/hub', query: { thread: 'thr-42', focus: BATON_FOCUS } })
  })

  it('BE-9296a: the SERVER handover row deep-links to the same thread', () => {
    const route = resolveNotificationRoute({
      type: 'hub.baton_handover',
      payload: { thread_id: 'thr-77', chat_id: 'CHT-0007' },
    })
    expect(route).toEqual(hubThreadRoute('thr-77'))
    expect(route).toEqual({ path: '/hub', query: { thread: 'thr-77', focus: BATON_FOCUS } })
  })

  it('FE-9418: a bell row names no message, so it lands on the thread tail', () => {
    for (const n of [
      { type: 'handover', metadata: { thread_id: 'thr-42' } },
      { type: 'hub.baton_handover', payload: { thread_id: 'thr-42' } },
    ]) {
      expect('message' in resolveNotificationRoute(n).query).toBe(false)
    }
  })

  it('BE-9296a: both handover rows — client-local and server — land in the same place', () => {
    const local = resolveNotificationRoute({ type: 'handover', metadata: { thread_id: 'thr-9' } })
    const server = resolveNotificationRoute({ type: 'hub.baton_handover', payload: { thread_id: 'thr-9' } })
    expect(server).toEqual(local)
  })

  it('FE-9436: a mention row lands on the POST it names, under its own reason', () => {
    const route = resolveNotificationRoute({
      type: 'hub.mention',
      metadata: { thread_id: 'thr-42', message_id: 'msg-7' },
    })
    expect(route).toEqual({
      path: '/hub',
      query: { thread: 'thr-42', focus: 'mention', message: 'msg-7' },
    })
  })

  it('FE-9436: an approval row lands on its own post too', () => {
    const route = resolveNotificationRoute({
      type: 'hub.approval',
      payload: { thread_id: 'thr-43', message_id: 'msg-8' },
    })
    expect(route).toEqual({
      path: '/hub',
      query: { thread: 'thr-43', focus: 'approval', message: 'msg-8' },
    })
  })

  it('FE-9436: neither new row can acquire the baton flag', () => {
    for (const type of ['hub.mention', 'hub.approval']) {
      const route = resolveNotificationRoute({ type, metadata: { thread_id: 't', message_id: 'm' } })
      expect(route.query.focus).not.toBe(BATON_FOCUS)
    }
  })

  it('FE-9436: a row that names no post still lands on its thread, not nowhere', () => {
    const route = resolveNotificationRoute({ type: 'hub.mention', metadata: { thread_id: 'thr-5' } })
    expect(route).toEqual({ path: '/hub', query: { thread: 'thr-5', focus: 'mention' } })
    expect('message' in route.query).toBe(false)
  })

  it('plain system banners (no product/project context) resolve to null so the banner falls back to cta_route', () => {
    expect(resolveNotificationRoute({ type: 'system.pending_migrations', payload: { pending: 3, head: 'x' } })).toBeNull()
    expect(resolveNotificationRoute({ type: 'system.skills_drift', payload: { current: '2', announced: '1' } })).toBeNull()
  })
})
