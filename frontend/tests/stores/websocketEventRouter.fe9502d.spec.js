/**
 * FE-9502d (Headless S4d) — the product activity pass.
 *
 * One level up from FE-9501b's routeGlobalActivityEvent (project-not-open ->
 * invisible): here it's product-not-viewed -> invisible. The existing
 * PROJECT_SCOPED_EVENTS filter is already safe against cross-product
 * hydration leakage (project ids are globally unique), so this pass exists
 * purely to make background-product activity VISIBLE, not to fix a leak.
 *
 * routeProductActivityEvent is a THIRD, independent pass over the same raw
 * events -- tenant-scoped only, no product match check (that is the whole
 * point) -- feeding productActivityStore (count-only, per-tab badge data).
 *
 * `conductor_job_minter.py`'s agent:created carries no product_id --
 * legitimate no-badge case (sequence_runs has no product_id column), not a
 * bug. recordActivity's falsy-id guard (pinned in productActivityStore.spec.js)
 * makes this a no-op rather than a crash or a phantom badge.
 *
 * Edition Scope: Both
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { routeProductActivityEvent } from '@/stores/websocketEventRouter'
import { useProductActivityStore } from '@/stores/productActivityStore'
import { withProductActivityBadges } from '@/composables/useProductTabBadges'

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: { tenant_key: 'tk_1' } }),
}))

describe('routeProductActivityEvent (FE-9502d)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('records activity for a project_update event carrying product_id', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = { productActivity: () => activityStore }

    const routed = await routeProductActivityEvent(
      { type: 'project_update', data: { project_id: 'proj-1', product_id: 'prod-other' } },
      { storeRegistry },
    )

    expect(routed).toBe(true)
    expect(activityStore.recordActivity).toHaveBeenCalledWith('prod-other')
  })

  it('records activity for task:updated, agent:status_changed, agent:health_alert, agent:auto_failed, orchestrator:prompt_generated', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = { productActivity: () => activityStore }

    const types = [
      'task:updated',
      'agent:status_changed',
      'agent:health_alert',
      'agent:auto_failed',
      'orchestrator:prompt_generated',
    ]
    for (const type of types) {
      await routeProductActivityEvent({ type, data: { product_id: 'prod-x' } }, { storeRegistry })
    }

    expect(activityStore.recordActivity).toHaveBeenCalledTimes(types.length)
    expect(activityStore.recordActivity).toHaveBeenCalledWith('prod-x')
  })

  // BE-9525c: closed the gap this suite used to pin as an exclusion -- these
  // three now carry product_id from every emitter except the project-less
  // chain conductor's own agent:created (a declared exception, covered by the
  // no-badge test below), so they are admitted to the set.
  it('records activity for agent:created, agent:removed, job:progress_update (BE-9525c)', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = { productActivity: () => activityStore }

    const types = ['agent:created', 'agent:removed', 'job:progress_update']
    for (const type of types) {
      await routeProductActivityEvent({ type, data: { product_id: 'prod-y' } }, { storeRegistry })
    }

    expect(activityStore.recordActivity).toHaveBeenCalledTimes(types.length)
    expect(activityStore.recordActivity).toHaveBeenCalledWith('prod-y')
  })

  it('the conductor no-product exception: agent:status_changed / agent:created with no product_id never records (no crash, no phantom badge)', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = { productActivity: () => activityStore }

    await routeProductActivityEvent(
      { type: 'agent:status_changed', data: { project_id: null, product_id: null } },
      { storeRegistry },
    )

    expect(activityStore.recordActivity).not.toHaveBeenCalled()
  })

  it('does nothing for an event type outside its scope (e.g. project:staging_complete)', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = { productActivity: () => activityStore }

    const routed = await routeProductActivityEvent(
      { type: 'project:staging_complete', data: { product_id: 'prod-x' } },
      { storeRegistry },
    )

    expect(routed).toBe(false)
    expect(activityStore.recordActivity).not.toHaveBeenCalled()
  })

  it('drops a cross-tenant event (still tenant-scoped, just not product-scoped)', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = { productActivity: () => activityStore }

    const routed = await routeProductActivityEvent(
      { type: 'project_update', data: { product_id: 'prod-x', tenant_key: 'tk_someone_else' } },
      { storeRegistry },
    )

    expect(routed).toBe(false)
    expect(activityStore.recordActivity).not.toHaveBeenCalled()
  })

  it('does NOT filter by viewed product -- that is the entire point of this pass', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = { productActivity: () => activityStore }

    // No productStore/currentProductId wiring at all in this call -- if this
    // pass required it, this test would throw rather than record.
    await routeProductActivityEvent(
      { type: 'project_update', data: { product_id: 'prod-background' } },
      { storeRegistry },
    )

    expect(activityStore.recordActivity).toHaveBeenCalledWith('prod-background')
  })
})

describe('museum flag: routeProductActivityEvent never touches hydration stores', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('a background-product project_update reaches productActivity but never projects/agentJobs', async () => {
    const projectStore = { handleRealtimeUpdate: vi.fn() }
    const agentJobsStore = { handleUpdated: vi.fn() }
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = {
      projects: () => projectStore,
      agentJobs: () => agentJobsStore,
      productActivity: () => activityStore,
    }

    await routeProductActivityEvent(
      { type: 'project_update', data: { project_id: 'proj-other', product_id: 'prod-other' } },
      { storeRegistry },
    )

    expect(activityStore.recordActivity).toHaveBeenCalledWith('prod-other')
    expect(projectStore.handleRealtimeUpdate).not.toHaveBeenCalled()
    expect(agentJobsStore.handleUpdated).not.toHaveBeenCalled()
  })
})

describe('end-to-end: a background-tab event LANDS SOMEWHERE VISIBLE, not merely routed (FE-9502d DoD)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  // The whole reason this pass exists: from inside the router,
  // routed-and-shown and routed-and-dropped look identical. This test does
  // not stop at "recordActivity was called" -- it runs the REAL
  // productActivityStore and the REAL badge-mapping function used by
  // ProductTabStrip, so a regression that silently breaks the chain anywhere
  // between the WS event and the rendered pill fails HERE, not in production.
  it('an event for a product with no open tab still produces a nonzero badgeCount once that tab opens', async () => {
    // No storeRegistry override -- routeProductActivityEvent falls back to
    // the real useProductActivityStore(), exactly as it does in production.
    await routeProductActivityEvent({
      type: 'agent:status_changed',
      data: { product_id: 'prod-b', project_id: 'proj-in-b' },
    })

    const realStore = useProductActivityStore()
    const tabs = [
      { id: 'prod-a', name: 'Product A' },
      { id: 'prod-b', name: 'Product B' },
    ]
    const decorated = withProductActivityBadges(tabs, 'prod-a', realStore.getCount)

    const backgroundTab = decorated.find((t) => t.id === 'prod-b')
    expect(backgroundTab.badgeCount).toBe(1)
  })

  it('the conductor no-product exception never produces a phantom badge on any tab', async () => {
    await routeProductActivityEvent({
      type: 'agent:status_changed',
      data: { product_id: null, project_id: null },
    })

    const realStore = useProductActivityStore()
    expect(realStore.totalCount).toBe(0)
  })
})
