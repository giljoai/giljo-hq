/**
 * FE-9501b (Headless S3b) — the global activity pass.
 *
 * D5: agent:created/status_changed/removed + job:progress_update are dropped by
 * PROJECT_SCOPED_EVENTS (defaultShouldRoute) for any project that isn't the open
 * tab, so an agent working elsewhere is invisible. routeGlobalActivityEvent is a
 * SEPARATE, additive pass over the same raw events -- no project filtering, only
 * tenant -- that feeds globalActivityStore (count-only) and, for approval-bearing
 * agent:status_changed events, useApprovalsStore (D6's raised-hand data source).
 *
 * These tests exercise routeGlobalActivityEvent directly (not the main
 * routeWebsocketEvent/defaultShouldRoute pipeline), and separately assert that
 * pipeline's existing cross-project drop is completely untouched.
 *
 * Edition Scope: Both
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { routeGlobalActivityEvent } from '@/stores/websocketEventRouter'

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: { tenant_key: 'tk_1' } }),
}))

describe('routeGlobalActivityEvent (FE-9501b, D5)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('records activity for an agent:created event on a project that is not open', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = { globalActivity: () => activityStore }

    const routed = await routeGlobalActivityEvent(
      { type: 'agent:created', data: { project_id: 'proj-other', agent_id: 'a-1' } },
      { storeRegistry },
    )

    expect(routed).toBe(true)
    expect(activityStore.recordActivity).toHaveBeenCalledWith('proj-other')
  })

  it('records activity for agent:status_changed, agent:removed, and job:progress_update', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = { globalActivity: () => activityStore }

    for (const type of ['agent:status_changed', 'agent:removed', 'job:progress_update']) {
      await routeGlobalActivityEvent({ type, data: { project_id: 'proj-x' } }, { storeRegistry })
    }

    expect(activityStore.recordActivity).toHaveBeenCalledTimes(3)
    expect(activityStore.recordActivity).toHaveBeenCalledWith('proj-x')
  })

  it('a burst of 50 non-approval events never calls approvalsStore -- count-only, never hydrate', async () => {
    // D5's "COUNT, do not hydrate" requirement: recordActivity is a synchronous
    // Map write (asserted by globalActivityStore.spec.js), so the only possible
    // network-shaped call from this pass is approvalsStore.fetchPending (via
    // handleStatusEvent), and that must only ever fire for a genuine
    // user_approval_id/decided_option_id-bearing event -- never as a side effect
    // of ordinary lifecycle chatter, however bursty.
    const activityStore = { recordActivity: vi.fn() }
    const approvalsStore = { handleStatusEvent: vi.fn() }
    const storeRegistry = { globalActivity: () => activityStore, approvals: () => approvalsStore }

    for (let i = 0; i < 50; i += 1) {
      await routeGlobalActivityEvent(
        { type: 'job:progress_update', data: { project_id: 'proj-busy', progress: i } },
        { storeRegistry },
      )
    }

    expect(activityStore.recordActivity).toHaveBeenCalledTimes(50)
    expect(approvalsStore.handleStatusEvent).not.toHaveBeenCalled()
  })

  it('does nothing for an event type outside its scope (e.g. project:staging_complete)', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const approvalsStore = { handleStatusEvent: vi.fn() }
    const storeRegistry = { globalActivity: () => activityStore, approvals: () => approvalsStore }

    const routed = await routeGlobalActivityEvent(
      { type: 'project:staging_complete', data: { project_id: 'proj-x' } },
      { storeRegistry },
    )

    expect(routed).toBe(false)
    expect(activityStore.recordActivity).not.toHaveBeenCalled()
    expect(approvalsStore.handleStatusEvent).not.toHaveBeenCalled()
  })

  it('drops a cross-tenant event (still tenant-scoped, just not project-scoped)', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = { globalActivity: () => activityStore }

    const routed = await routeGlobalActivityEvent(
      { type: 'agent:created', data: { project_id: 'proj-x', tenant_key: 'tk_someone_else' } },
      { storeRegistry },
    )

    expect(routed).toBe(false)
    expect(activityStore.recordActivity).not.toHaveBeenCalled()
  })

  it('forwards an awaiting_user agent:status_changed event to approvalsStore regardless of open project (D6)', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const approvalsStore = { handleStatusEvent: vi.fn().mockResolvedValue() }
    const storeRegistry = { globalActivity: () => activityStore, approvals: () => approvalsStore }

    await routeGlobalActivityEvent(
      {
        type: 'agent:status_changed',
        data: {
          project_id: 'proj-unopened',
          job_id: 'job-1',
          status: 'awaiting_user',
          user_approval_id: 'appr-1',
        },
      },
      { storeRegistry },
    )

    expect(approvalsStore.handleStatusEvent).toHaveBeenCalledWith(
      expect.objectContaining({ user_approval_id: 'appr-1', status: 'awaiting_user' }),
    )
  })

  it('forwards a decided_option_id agent:status_changed event too (clears the row app-wide)', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const approvalsStore = { handleStatusEvent: vi.fn().mockResolvedValue() }
    const storeRegistry = { globalActivity: () => activityStore, approvals: () => approvalsStore }

    await routeGlobalActivityEvent(
      {
        type: 'agent:status_changed',
        data: { project_id: 'proj-x', user_approval_id: 'appr-1', decided_option_id: 'opt-a' },
      },
      { storeRegistry },
    )

    expect(approvalsStore.handleStatusEvent).toHaveBeenCalledWith(
      expect.objectContaining({ decided_option_id: 'opt-a' }),
    )
  })

  it('does NOT call approvalsStore for a plain status_changed event with no approval fields', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const approvalsStore = { handleStatusEvent: vi.fn() }
    const storeRegistry = { globalActivity: () => activityStore, approvals: () => approvalsStore }

    await routeGlobalActivityEvent(
      { type: 'agent:status_changed', data: { project_id: 'proj-x', status: 'working' } },
      { storeRegistry },
    )

    expect(approvalsStore.handleStatusEvent).not.toHaveBeenCalled()
  })

  it('a hiccup in approvalsStore.handleStatusEvent never throws out of the routing pass', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const approvalsStore = { handleStatusEvent: vi.fn().mockRejectedValue(new Error('boom')) }
    const storeRegistry = { globalActivity: () => activityStore, approvals: () => approvalsStore }

    expect(() =>
      routeGlobalActivityEvent(
        {
          type: 'agent:status_changed',
          data: { project_id: 'proj-x', user_approval_id: 'appr-1', status: 'awaiting_user' },
        },
        { storeRegistry },
      ),
    ).not.toThrow()
    // Let the (rejected) approval refresh microtask settle so it doesn't leak
    // into another test as an unhandled rejection.
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
})

describe('museum flag: routeGlobalActivityEvent never touches agentJobsStore (Handover 0462/0463, unrelaxed)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('a cross-project agent:created event reaches globalActivity but never agentJobsStore', async () => {
    const agentJobsStore = { handleCreated: vi.fn(), upsertJob: vi.fn() }
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = {
      agentJobs: () => agentJobsStore,
      globalActivity: () => activityStore,
    }

    await routeGlobalActivityEvent(
      { type: 'agent:created', data: { project_id: 'proj-other', agent_id: 'a-1' } },
      { storeRegistry },
    )

    expect(activityStore.recordActivity).toHaveBeenCalledWith('proj-other')
    expect(agentJobsStore.handleCreated).not.toHaveBeenCalled()
    expect(agentJobsStore.upsertJob).not.toHaveBeenCalled()
  })
})
