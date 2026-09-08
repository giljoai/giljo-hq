/**
 * products.fe9412.spec.js — FE-9412, demoted by FE-9502c
 *
 * Activating a product in one session must reach every OTHER open session's
 * DISPLAYED active-product value.
 *
 * Two Pinia instances stand in for two browsers on the same tenant. The event
 * is fed through the REAL router (`routeWebsocketEvent` + the real EVENT_MAP),
 * not by hand-calling the handler, so these specs cover the wiring — route
 * table, store lookup, action name — and not merely the function body.
 *
 * FE-9502c: the old contract — a session learning about an activation
 * second-hand re-scopes its ENTIRE session (currentProductId, project list,
 * tasks) to match — was correct for the pre-tabs single-product model, where
 * currentProductId WAS the server's active product by construction. Under
 * the tabbed shell, currentProductId is the VIEWED TAB, a UI-local choice;
 * a live event from a DIFFERENT browser's activation must not silently
 * switch what THIS session is looking at (ruling 3, no auto-navigation).
 * Only the displayed `activeProduct` (now a legacy-default value) follows
 * the event. See useActiveProductReconciliation.spec.js for the matching
 * focus/reconnect-backstop specs.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const PRODUCT_A = { id: 'prod-hermes', name: 'Hermes' }
const PRODUCT_B = { id: 'prod-auditor', name: 'Codebase_Auditor' }

const mockGetDefault = vi.fn()
const mockGet = vi.fn()
const mockList = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    products: {
      list: (...a) => mockList(...a),
      get: (...a) => mockGet(...a),
      getDefault: (...a) => mockGetDefault(...a),
    },
    tasks: { list: vi.fn(() => Promise.resolve({ data: [] })) },
  }
  return { api: apiMock, default: apiMock }
})

import { useProductStore } from '@/stores/products'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import { routeWebsocketEvent, EVENT_MAP } from '@/stores/websocketEventRouter'

/**
 * One browser session: its own Pinia instance, its own product store, with the
 * dependent stores' fetchers stubbed so "did the dependent views re-scope?" is
 * directly observable.
 */
function createSession() {
  const pinia = createPinia()
  setActivePinia(pinia)

  const projectStore = useProjectStore()
  projectStore.fetchProjects = vi.fn(() => Promise.resolve())

  const taskStore = useTaskStore()
  taskStore.fetchTasks = vi.fn(() => Promise.resolve())

  const products = useProductStore()
  return { pinia, products, projectStore, taskStore }
}

/** Deliver the activation event to ONE session, through the real router. */
async function deliverActivationEvent(session, productId) {
  return routeWebsocketEvent(
    {
      type: 'product:status:changed',
      data: { tenant_key: 'tk_operator', product_id: productId, is_active: true },
    },
    {
      eventMap: EVENT_MAP,
      storeRegistry: { products: () => session.products },
    },
  )
}

describe('FE-9412 — an activation in one session reaches the others', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()

    // The server has already flipped: B is active, A is not.
    mockGetDefault.mockResolvedValue({
      data: { has_active_product: true, product: PRODUCT_B },
    })
    mockList.mockResolvedValue({ data: [PRODUCT_A, PRODUCT_B] })
    mockGet.mockImplementation((id) =>
      Promise.resolve({ data: id === PRODUCT_B.id ? PRODUCT_B : PRODUCT_A }),
    )
  })

  it('updates the second session ACTIVE PRODUCT when the first session activates', async () => {
    const sessionTwo = createSession()
    sessionTwo.products.$patch({
      activeProduct: PRODUCT_A,
      currentProductId: PRODUCT_A.id,
      currentProduct: PRODUCT_A,
    })

    const routed = await deliverActivationEvent(sessionTwo, PRODUCT_B.id)

    expect(routed).toBe(true)
    expect(sessionTwo.products.activeProduct).toMatchObject({ id: PRODUCT_B.id })
  })

  it('FE-9502c: does NOT re-scope the second session\'s viewed tab — only the displayed activeProduct follows', async () => {
    const sessionTwo = createSession()
    sessionTwo.products.$patch({
      activeProduct: PRODUCT_A,
      currentProductId: PRODUCT_A.id,
      currentProduct: PRODUCT_A,
      openProductIds: [PRODUCT_A.id],
    })

    await deliverActivationEvent(sessionTwo, PRODUCT_B.id)

    // activeProduct (display/legacy-default) follows the event...
    expect(sessionTwo.products.activeProduct).toMatchObject({ id: PRODUCT_B.id })
    // ...but the tab this session is VIEWING never moves on its own —
    // reassigning it from a background event would be silent auto-navigation.
    expect(sessionTwo.products.currentProductId).toBe(PRODUCT_A.id)
    expect(sessionTwo.products.currentProduct).toMatchObject({ id: PRODUCT_A.id })
  })

  it('FE-9502c: does NOT refetch the dependent views — nothing was re-scoped', async () => {
    const sessionTwo = createSession()
    sessionTwo.products.$patch({
      activeProduct: PRODUCT_A,
      currentProductId: PRODUCT_A.id,
      currentProduct: PRODUCT_A,
      openProductIds: [PRODUCT_A.id],
    })

    await deliverActivationEvent(sessionTwo, PRODUCT_B.id)

    expect(sessionTwo.projectStore.fetchProjects).not.toHaveBeenCalled()
    expect(sessionTwo.taskStore.fetchTasks).not.toHaveBeenCalled()
  })

  it('leaves the session that PERFORMED the activation alone (no gratuitous re-scope)', async () => {
    // Session one already activated B locally, so it is already on B. The
    // broadcast reaches it too; it must be a no-op, not a second reload.
    const sessionOne = createSession()
    sessionOne.products.$patch({
      activeProduct: PRODUCT_B,
      currentProductId: PRODUCT_B.id,
      currentProduct: PRODUCT_B,
    })

    await deliverActivationEvent(sessionOne, PRODUCT_B.id)

    expect(sessionOne.products.currentProductId).toBe(PRODUCT_B.id)
    expect(sessionOne.projectStore.fetchProjects).not.toHaveBeenCalled()
    expect(sessionOne.taskStore.fetchTasks).not.toHaveBeenCalled()
  })

  it('does not cross-contaminate: one session receiving the event does not mutate the other', async () => {
    const sessionOne = createSession()
    sessionOne.products.$patch({
      activeProduct: PRODUCT_B,
      currentProductId: PRODUCT_B.id,
      currentProduct: PRODUCT_B,
      openProductIds: [PRODUCT_B.id],
    })

    const sessionTwo = createSession()
    sessionTwo.products.$patch({
      activeProduct: PRODUCT_A,
      currentProductId: PRODUCT_A.id,
      currentProduct: PRODUCT_A,
      openProductIds: [PRODUCT_A.id],
    })

    await deliverActivationEvent(sessionTwo, PRODUCT_B.id)

    // sessionTwo's displayed activeProduct follows the event; its viewed tab
    // (currentProductId) does not (FE-9502c). sessionOne, an entirely
    // separate Pinia instance the event was never routed to, is untouched.
    expect(sessionTwo.products.activeProduct).toMatchObject({ id: PRODUCT_B.id })
    expect(sessionTwo.products.currentProductId).toBe(PRODUCT_A.id)
    expect(sessionOne.products.currentProductId).toBe(PRODUCT_B.id)
    expect(sessionOne.products.activeProduct).toMatchObject({ id: PRODUCT_B.id })
    expect(sessionOne.projectStore.fetchProjects).not.toHaveBeenCalled()
  })
})
