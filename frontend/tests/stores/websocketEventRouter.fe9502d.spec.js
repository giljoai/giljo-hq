/**
 * FE-9751 — the product-tab activity pass is gone.
 *
 * The router used to run a third pass that counted agent/task/project events per
 * background product for the tab strip. The counters are removed; only the
 * approvals refresh stays. These tests drive the real initialised router with a
 * fake websocket store and prove an event for a background product (a) reaches no
 * activity counter and (b) still refreshes approvals when it carries an approval.
 *
 * Edition Scope: Both
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import * as routerModule from '@/stores/websocketEventRouter'

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: { tenant_key: 'tk_1' } }),
}))

function startRouter(storeRegistry) {
  const handlers = []
  const wsStore = {
    on: (name, handler) => handlers.push(handler),
    onConnectionChange: vi.fn(),
  }
  routerModule.initWebsocketEventRouter({ wsStore, storeRegistry })
  return async (event) => {
    for (const handler of handlers) await handler(event)
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

describe('product activity pass removed (FE-9751)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('exports no product-activity routing pass', () => {
    expect(Object.keys(routerModule)).not.toContain('routeProductActivityEvent')
  })

  it('background-product events reach no activity counter, and an approval-bearing one still refreshes approvals', async () => {
    const productActivity = { recordActivity: vi.fn() }
    const globalActivity = { recordActivity: vi.fn() }
    const approvals = { handleStatusEvent: vi.fn().mockResolvedValue() }
    const emit = startRouter({
      productActivity: () => productActivity,
      globalActivity: () => globalActivity,
      approvals: () => approvals,
    })

    for (const type of [
      'project_update',
      'task:updated',
      'agent:created',
      'agent:removed',
      'job:progress_update',
      'agent:status_changed',
    ]) {
      await emit({ type, data: { product_id: 'prod-bg', project_id: 'proj-bg' } })
    }
    expect(productActivity.recordActivity).not.toHaveBeenCalled()
    expect(globalActivity.recordActivity).not.toHaveBeenCalled()
    expect(approvals.handleStatusEvent).not.toHaveBeenCalled()

    await emit({
      type: 'agent:status_changed',
      data: { product_id: 'prod-bg', project_id: 'proj-bg', status: 'awaiting_user', user_approval_id: 'appr-1' },
    })
    expect(approvals.handleStatusEvent).toHaveBeenCalledWith(
      expect.objectContaining({ user_approval_id: 'appr-1' }),
    )
    expect(productActivity.recordActivity).not.toHaveBeenCalled()
    expect(globalActivity.recordActivity).not.toHaveBeenCalled()
  })
})
