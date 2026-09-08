/**
 * useActiveProductReconciliation.spec.js — FE-9412, demoted by FE-9502c
 *
 * The staleness backstop for a DEAD socket, scoped to the DISPLAYED
 * server-active product only.
 *
 * The live `product:status:changed` event only helps a session whose socket is
 * alive. The session in the original FE-9412 incident sat stale for over an
 * hour because its socket never delivered the event and nothing on the client
 * ever re-asked. These specs pin the reconciliation half: on tab focus /
 * visibilitychange — and on a WS reconnect — the session re-reads the active
 * product against persisted server state with one lightweight GET, and
 * corrects `activeProduct` if it was stale.
 *
 * FE-9502c: this no longer re-scopes `currentProductId` (the viewed tab).
 * Under the tabbed shell that would be silent auto-navigation off a
 * background event — a session with two tabs open must not have
 * its viewed tab reassigned just because some OTHER session activated a
 * different product on the server. The specs below assert the NEGATIVE
 * explicitly: currentProductId never moves, no matter what activeProduct does.
 *
 * Mirrors the FE-9407/FE-9166 rule: never trust the live event alone.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { effectScope } from 'vue'

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

const mockUnregisterResync = vi.fn()
const mockRegisterReconnectResync = vi.fn(() => mockUnregisterResync)
vi.mock('@/stores/websocketEventRouter', () => ({
  registerReconnectResync: (...a) => mockRegisterReconnectResync(...a),
}))

import { useProductStore } from '@/stores/products'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import { useActiveProductReconciliation } from './useActiveProductReconciliation'

function setVisibility(state) {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  })
}

/** A session VIEWING product A's tab while the server's active product is stale/unknown to it. */
function createStaleSession() {
  const projectStore = useProjectStore()
  projectStore.fetchProjects = vi.fn(() => Promise.resolve())
  const taskStore = useTaskStore()
  taskStore.fetchTasks = vi.fn(() => Promise.resolve())

  const products = useProductStore()
  products.$patch({
    activeProduct: PRODUCT_A,
    currentProductId: PRODUCT_A.id,
    currentProduct: PRODUCT_A,
    openProductIds: [PRODUCT_A.id],
  })
  return { products, projectStore, taskStore }
}

describe('FE-9412/FE-9502c — activeProduct heals on focus, the viewed tab never moves', () => {
  let scope

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    setVisibility('visible')

    // Server truth: B is active. The session below still displays A.
    mockGetDefault.mockResolvedValue({
      data: { has_active_product: true, product: PRODUCT_B },
    })
    mockList.mockResolvedValue({ data: [PRODUCT_A, PRODUCT_B] })
    mockGet.mockImplementation((id) =>
      Promise.resolve({ data: id === PRODUCT_B.id ? PRODUCT_B : PRODUCT_A }),
    )

    scope = effectScope()
  })

  afterEach(() => {
    scope?.stop()
  })

  it('refreshes the displayed activeProduct when the tab becomes visible again', async () => {
    const session = createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    setVisibility('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.waitFor(() => expect(session.products.activeProduct).toMatchObject({ id: PRODUCT_B.id }))

    expect(mockGetDefault).toHaveBeenCalled()
  })

  it('does NOT reassign the viewed tab (currentProductId) even though activeProduct diverges', async () => {
    const session = createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    document.dispatchEvent(new Event('visibilitychange'))
    await vi.waitFor(() => expect(session.products.activeProduct).toMatchObject({ id: PRODUCT_B.id }))

    // The user is still looking at A's tab -- a background reconciliation
    // must never silently switch what's on screen.
    expect(session.products.currentProductId).toBe(PRODUCT_A.id)
    expect(session.projectStore.fetchProjects).not.toHaveBeenCalled()
  })

  it('re-validates on window focus', async () => {
    const session = createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    window.dispatchEvent(new Event('focus'))
    await vi.waitFor(() => expect(session.products.activeProduct).toMatchObject({ id: PRODUCT_B.id }))

    expect(mockGetDefault).toHaveBeenCalled()
    expect(session.products.currentProductId).toBe(PRODUCT_A.id)
  })

  it('does not re-validate when the tab goes HIDDEN', async () => {
    createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    setVisibility('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    await Promise.resolve()

    expect(mockGetDefault).not.toHaveBeenCalled()
  })

  it('re-validates on a WebSocket reconnect (the other way a session learns it missed something)', async () => {
    const session = createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    expect(mockRegisterReconnectResync).toHaveBeenCalledTimes(1)
    const resync = mockRegisterReconnectResync.mock.calls[0][0]
    await resync()

    expect(mockGetDefault).toHaveBeenCalled()
    expect(session.products.activeProduct).toMatchObject({ id: PRODUCT_B.id })
    expect(session.products.currentProductId).toBe(PRODUCT_A.id)
  })

  it('a FAILED re-validation leaves the displayed activeProduct exactly as it was', async () => {
    // This fires on every tab focus, so a laptop waking before its network
    // does must not blank the header.
    mockGetDefault.mockRejectedValue(new Error('network down'))
    const session = createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    document.dispatchEvent(new Event('visibilitychange'))
    // The start and end states are deliberately identical here (nothing must
    // change), so neither "the GET was called" nor a waitFor on the end state
    // can tell settled from mid-flight — the first samples before the restore,
    // the second passes on its first poll before anything has happened. Drain
    // to a macrotask instead: every pending microtask in the reconcile chain
    // has run by then.
    await vi.waitFor(() => expect(mockGetDefault).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 0))

    // The header is the assertion that matters: fetchActiveProduct nulls it in
    // its catch, so without the restore this reads "No active product".
    expect(session.products.activeProduct).toMatchObject({ id: PRODUCT_A.id })
    expect(session.products.currentProductId).toBe(PRODUCT_A.id)
    expect(session.projectStore.fetchProjects).not.toHaveBeenCalled()
  })

  it('detaches its listeners and its resync registration on teardown', async () => {
    createStaleSession()
    scope.run(() => useActiveProductReconciliation())

    scope.stop()

    document.dispatchEvent(new Event('visibilitychange'))
    window.dispatchEvent(new Event('focus'))
    await Promise.resolve()

    expect(mockGetDefault).not.toHaveBeenCalled()
    expect(mockUnregisterResync).toHaveBeenCalledTimes(1)
  })
})
