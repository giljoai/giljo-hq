/**
 * products.fe9412.spec.js — FE-9412
 *
 * Activating a product in one session must reach every OTHER open session.
 *
 * Two Pinia instances stand in for two browsers on the same tenant. The event
 * is fed through the REAL router (`routeWebsocketEvent` + the real EVENT_MAP),
 * not by hand-calling the handler, so these specs cover the wiring — route
 * table, store lookup, action name — and not merely the function body.
 *
 * The contract under test is the one the LOCAL activation path already
 * satisfies (useProductActivation.js: activate -> fetchActiveProduct ->
 * setCurrentProduct -> reload): a session learning about the activation from
 * the event must end in the SAME state as the session that performed it.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const PRODUCT_A = { id: 'prod-hermes', name: 'Hermes' }
const PRODUCT_B = { id: 'prod-auditor', name: 'Codebase_Auditor' }

const mockGetActive = vi.fn()
const mockGet = vi.fn()
const mockList = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    products: {
      list: (...a) => mockList(...a),
      get: (...a) => mockGet(...a),
      getActive: (...a) => mockGetActive(...a),
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
    mockGetActive.mockResolvedValue({
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

  it('RE-SCOPES the second session to the newly activated product, not just its header', async () => {
    const sessionTwo = createSession()
    sessionTwo.products.$patch({
      activeProduct: PRODUCT_A,
      currentProductId: PRODUCT_A.id,
      currentProduct: PRODUCT_A,
    })

    await deliverActivationEvent(sessionTwo, PRODUCT_B.id)

    // The selection the whole session is scoped by — the thing the project
    // list, roadmap and task views read — must follow the activation.
    expect(sessionTwo.products.currentProductId).toBe(PRODUCT_B.id)
    expect(sessionTwo.products.currentProduct).toMatchObject({ id: PRODUCT_B.id })
    expect(sessionTwo.products.effectiveProductId).toBe(PRODUCT_B.id)
  })

  it('refetches the dependent views so the stale project list cannot survive', async () => {
    const sessionTwo = createSession()
    sessionTwo.products.$patch({
      activeProduct: PRODUCT_A,
      currentProductId: PRODUCT_A.id,
      currentProduct: PRODUCT_A,
    })

    await deliverActivationEvent(sessionTwo, PRODUCT_B.id)

    expect(sessionTwo.projectStore.fetchProjects).toHaveBeenCalled()
    expect(sessionTwo.taskStore.fetchTasks).toHaveBeenCalledWith({ product_id: PRODUCT_B.id })
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
    })

    const sessionTwo = createSession()
    sessionTwo.products.$patch({
      activeProduct: PRODUCT_A,
      currentProductId: PRODUCT_A.id,
      currentProduct: PRODUCT_A,
    })

    await deliverActivationEvent(sessionTwo, PRODUCT_B.id)

    expect(sessionTwo.products.currentProductId).toBe(PRODUCT_B.id)
    expect(sessionOne.products.currentProductId).toBe(PRODUCT_B.id)
    expect(sessionOne.projectStore.fetchProjects).not.toHaveBeenCalled()
  })
})
