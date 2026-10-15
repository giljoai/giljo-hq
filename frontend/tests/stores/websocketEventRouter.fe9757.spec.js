/**
 * FE-9757: the unfiltered pass mirrors the stopped-agent events on `window`.
 *
 * useStoppedAgentSignals observes agent:status_changed, agent:silent and
 * job:progress_update as window CustomEvents, the same bridge
 * commHubEventRoutes gives useHubNotifications for thread events. The bridge
 * has to live in routeGlobalApprovalEvent rather than the main pass, because
 * the main pass drops agent events for any project that is not the open tab.
 * Tenant-scoped like the rest of that pass; nothing else is mirrored.
 *
 * Edition Scope: Both
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { routeGlobalApprovalEvent } from '@/stores/websocketEventRouter'

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: { tenant_key: 'tk_1' } }),
}))

const MIRRORED = ['agent:status_changed', 'agent:silent', 'job:progress_update']

describe('routeGlobalApprovalEvent mirrors stopped-agent events on window (FE-9757)', () => {
  const heard = []
  const listeners = []

  beforeEach(() => {
    setActivePinia(createPinia())
    heard.length = 0
    for (const type of MIRRORED) {
      const listener = (event) => heard.push({ type, detail: event.detail })
      window.addEventListener(type, listener)
      listeners.push({ type, listener })
    }
  })

  afterEach(() => {
    for (const { type, listener } of listeners) window.removeEventListener(type, listener)
    listeners.length = 0
  })

  it.each(MIRRORED)('mirrors %s with the normalized payload as detail, regardless of open project', async (type) => {
    const storeRegistry = { approvals: () => ({ handleStatusEvent: vi.fn().mockResolvedValue() }) }

    const routed = await routeGlobalApprovalEvent(
      { type, data: { job_id: 'job-1', project_id: 'proj-unopened', status: 'blocked' } },
      { storeRegistry },
    )

    expect(routed).toBe(true)
    expect(heard).toEqual([
      { type, detail: expect.objectContaining({ job_id: 'job-1', project_id: 'proj-unopened' }) },
    ])
  })

  it('does NOT mirror a cross-tenant event', async () => {
    const routed = await routeGlobalApprovalEvent(
      { type: 'agent:silent', data: { job_id: 'job-1', tenant_key: 'tk_someone_else' } },
      { storeRegistry: {} },
    )

    expect(routed).toBe(false)
    expect(heard).toEqual([])
  })

  it('does NOT mirror an event outside the three (agent:created stays with the approvals pass only)', async () => {
    await routeGlobalApprovalEvent(
      { type: 'agent:created', data: { job_id: 'job-1', project_id: 'proj-x' } },
      { storeRegistry: {} },
    )

    expect(heard).toEqual([])
  })

  it('still forwards an approval-bearing status event to the approvals store alongside the mirror', async () => {
    const approvalsStore = { handleStatusEvent: vi.fn().mockResolvedValue() }

    await routeGlobalApprovalEvent(
      {
        type: 'agent:status_changed',
        data: { job_id: 'job-1', project_id: 'proj-x', status: 'awaiting_user', user_approval_id: 'appr-1' },
      },
      { storeRegistry: { approvals: () => approvalsStore } },
    )

    expect(approvalsStore.handleStatusEvent).toHaveBeenCalledOnce()
    expect(heard).toHaveLength(1)
  })
})
