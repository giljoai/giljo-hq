/**
 * FE-9501b (D6) / FE-9751 — the cross-project approvals pass.
 *
 * agent:status_changed is dropped by PROJECT_SCOPED_EVENTS (defaultShouldRoute)
 * for any project that isn't the open tab. routeGlobalApprovalEvent is a
 * SEPARATE, additive pass over the same raw events -- no project filtering, only
 * tenant -- that feeds useApprovalsStore for approval-bearing agent:status_changed
 * events (D6's raised-hand data source). FE-9751: it keeps no activity count.
 *
 * These tests exercise routeGlobalApprovalEvent directly (not the main
 * routeWebsocketEvent/defaultShouldRoute pipeline), and separately assert that
 * pipeline's existing cross-project drop is completely untouched.
 *
 * Edition Scope: Both
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { routeGlobalApprovalEvent } from '@/stores/websocketEventRouter'

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: { tenant_key: 'tk_1' } }),
}))

describe('routeGlobalApprovalEvent (FE-9501b, D5)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('keeps no activity count for lifecycle events on a project that is not open', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const approvalsStore = { handleStatusEvent: vi.fn() }
    const storeRegistry = { globalActivity: () => activityStore, approvals: () => approvalsStore }

    for (const type of ['agent:created', 'agent:status_changed', 'agent:removed', 'job:progress_update']) {
      await routeGlobalApprovalEvent({ type, data: { project_id: 'proj-x' } }, { storeRegistry })
    }

    expect(activityStore.recordActivity).not.toHaveBeenCalled()
    expect(approvalsStore.handleStatusEvent).not.toHaveBeenCalled()
  })

  it('a burst of 50 non-approval events never calls approvalsStore -- never hydrate', async () => {
    const approvalsStore = { handleStatusEvent: vi.fn() }
    const storeRegistry = { approvals: () => approvalsStore }

    for (let i = 0; i < 50; i += 1) {
      await routeGlobalApprovalEvent(
        { type: 'job:progress_update', data: { project_id: 'proj-busy', progress: i } },
        { storeRegistry },
      )
    }

    expect(approvalsStore.handleStatusEvent).not.toHaveBeenCalled()
  })

  it('does nothing for an event type outside its scope (e.g. project:staging_complete)', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const approvalsStore = { handleStatusEvent: vi.fn() }
    const storeRegistry = { globalActivity: () => activityStore, approvals: () => approvalsStore }

    const routed = await routeGlobalApprovalEvent(
      { type: 'project:staging_complete', data: { project_id: 'proj-x' } },
      { storeRegistry },
    )

    expect(routed).toBe(false)
    expect(activityStore.recordActivity).not.toHaveBeenCalled()
    expect(approvalsStore.handleStatusEvent).not.toHaveBeenCalled()
  })

  it('drops a cross-tenant approval event (still tenant-scoped, just not project-scoped)', async () => {
    const approvalsStore = { handleStatusEvent: vi.fn() }
    const storeRegistry = { approvals: () => approvalsStore }

    const routed = await routeGlobalApprovalEvent(
      {
        type: 'agent:status_changed',
        data: { project_id: 'proj-x', tenant_key: 'tk_someone_else', user_approval_id: 'appr-1' },
      },
      { storeRegistry },
    )

    expect(routed).toBe(false)
    expect(approvalsStore.handleStatusEvent).not.toHaveBeenCalled()
  })

  it('forwards an awaiting_user agent:status_changed event to approvalsStore regardless of open project (D6)', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const approvalsStore = { handleStatusEvent: vi.fn().mockResolvedValue() }
    const storeRegistry = { globalActivity: () => activityStore, approvals: () => approvalsStore }

    await routeGlobalApprovalEvent(
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
    expect(activityStore.recordActivity).not.toHaveBeenCalled()
  })

  it('forwards a decided_option_id agent:status_changed event too (clears the row app-wide)', async () => {
    const activityStore = { recordActivity: vi.fn() }
    const approvalsStore = { handleStatusEvent: vi.fn().mockResolvedValue() }
    const storeRegistry = { globalActivity: () => activityStore, approvals: () => approvalsStore }

    await routeGlobalApprovalEvent(
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

    await routeGlobalApprovalEvent(
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
      routeGlobalApprovalEvent(
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

describe('museum flag: routeGlobalApprovalEvent never touches agentJobsStore (Handover 0462/0463, unrelaxed)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('a cross-project agent:created event never reaches agentJobsStore', async () => {
    const agentJobsStore = { handleCreated: vi.fn(), upsertJob: vi.fn() }
    const activityStore = { recordActivity: vi.fn() }
    const storeRegistry = {
      agentJobs: () => agentJobsStore,
      globalActivity: () => activityStore,
    }

    await routeGlobalApprovalEvent(
      { type: 'agent:created', data: { project_id: 'proj-other', agent_id: 'a-1' } },
      { storeRegistry },
    )

    expect(activityStore.recordActivity).not.toHaveBeenCalled()
    expect(agentJobsStore.handleCreated).not.toHaveBeenCalled()
    expect(agentJobsStore.upsertJob).not.toHaveBeenCalled()
  })
})
