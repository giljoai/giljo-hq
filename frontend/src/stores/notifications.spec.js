/**
 * notifications.spec.js — FE-9241
 *
 * Locks the client-side persistence + local dismiss/read behaviour for
 * `_local` notification rows (silent-agent / auto-failed bell notifications
 * emitted via addNotification() — see stores/eventRoutes/agentEventRoutes.js
 * — that never reach the server `notifications` table):
 *
 *  - dismiss/read on a `_local` row mutates in memory + re-persists to
 *    localStorage, with NO REST call (a REST call against a client id 404s).
 *  - fetch() MERGES server rows with persisted `_local` rows instead of
 *    replacing the list outright (the prior full-replace flushed silent-agent
 *    notifications on every reload).
 *  - `_local` rows rehydrate on store (re)creation — i.e. survive a reload —
 *    scoped to a per-user localStorage key so a different account on the
 *    same browser cannot read them.
 *  - server-backed rows are unaffected: markRead/markDismissed keep their
 *    original REST round trip.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockList = vi.fn()
const mockMarkRead = vi.fn()
const mockMarkDismissed = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    notifications: {
      list: (...a) => mockList(...a),
      markRead: (...a) => mockMarkRead(...a),
      markDismissed: (...a) => mockMarkDismissed(...a),
    },
  }
  return { api: apiMock, default: apiMock }
})

import { useNotificationStore } from './notifications'
import { useUserStore } from './user'

describe('notifications store — FE-9241 `_local` row persistence + dismiss/read', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockList.mockResolvedValue({ data: [] })

    // tests/setup.js stubs window.localStorage with no-op vi.fn()s (getItem
    // always undefined, setItem/removeItem no-ops) for the wider suite. This
    // spec exercises REAL persist/rehydrate round trips (FE-9241), so give it
    // an in-memory backing store for the duration of each test — jsdom's
    // environment is instantiated per test FILE, so this override cannot leak
    // into any other spec file.
    const backing = new Map()
    window.localStorage = {
      getItem: (k) => (backing.has(k) ? backing.get(k) : null),
      setItem: (k, v) => backing.set(k, String(v)),
      removeItem: (k) => backing.delete(k),
      clear: () => backing.clear(),
    }
  })

  it('markDismissed removes a `_local` row permanently with NO REST call', async () => {
    useUserStore().currentUser = { id: 'user-1' }
    const store = useNotificationStore()
    store.addNotification({
      id: 'local-1',
      type: 'agent_health',
      title: 'Agent Silent',
      message: 'implementer - stopped communicating',
    })
    expect(store.notifications.some((n) => n.id === 'local-1')).toBe(true)

    await store.markDismissed('local-1')

    expect(store.notifications.some((n) => n.id === 'local-1')).toBe(false)
    expect(mockMarkDismissed).not.toHaveBeenCalled()
  })

  it('markRead sets a `_local` row read in memory with NO REST call', async () => {
    useUserStore().currentUser = { id: 'user-1' }
    const store = useNotificationStore()
    store.addNotification({
      id: 'local-2',
      type: 'agent_health',
      title: 'Agent Silent',
      message: 'implementer - stopped communicating',
    })

    await store.markRead('local-2')

    const row = store.notifications.find((n) => n.id === 'local-2')
    expect(row.read).toBe(true)
    expect(row.read_at).toBeTruthy()
    expect(mockMarkRead).not.toHaveBeenCalled()
  })

  it('markDismissed on a server row keeps the REST round trip unchanged', async () => {
    mockMarkDismissed.mockResolvedValue({})
    const store = useNotificationStore()
    // Server-shaped row (no `_local` tag) — as fetch()/normalizeServerNotif would produce.
    store.notifications = [
      { id: 'server-1', type: 'system_alert', title: 'Server row', read: false },
    ]

    await store.markDismissed('server-1')

    expect(mockMarkDismissed).toHaveBeenCalledWith('server-1')
    expect(store.notifications.some((n) => n.id === 'server-1')).toBe(false)
  })

  it('markRead on a server row keeps the REST round trip unchanged', async () => {
    mockMarkRead.mockResolvedValue({
      data: { id: 'server-2', type: 'system_alert', title: 'Server row', read_at: '2026-07-23T00:00:00Z' },
    })
    const store = useNotificationStore()
    store.notifications = [
      { id: 'server-2', type: 'system_alert', title: 'Server row', read: false },
    ]

    await store.markRead('server-2')

    expect(mockMarkRead).toHaveBeenCalledWith('server-2')
    expect(store.notifications.find((n) => n.id === 'server-2').read).toBe(true)
  })

  it('fetch() MERGES server rows with persisted `_local` rows instead of replacing the list', async () => {
    useUserStore().currentUser = { id: 'user-1' }
    const store = useNotificationStore()
    store.addNotification({
      id: 'local-3',
      type: 'agent_health',
      title: 'Agent Silent',
      message: 'orchestrator - stopped communicating',
    })
    mockList.mockResolvedValue({
      data: [{ id: 'server-3', type: 'system_alert', title: 'Server row', body: 'b', created_at: '2026-07-23T00:00:00Z' }],
    })

    await store.fetch()

    const ids = store.notifications.map((n) => n.id)
    expect(ids).toContain('server-3')
    expect(ids).toContain('local-3')
  })

  it('`_local` rows rehydrate on store (re)creation — survives a simulated page reload', async () => {
    // "Session 1": user logs in, a silent-agent notification arrives and persists.
    useUserStore().currentUser = { id: 'user-1' }
    useNotificationStore().addNotification({
      id: 'local-4',
      type: 'agent_health',
      title: 'Agent Silent',
      message: 'implementer - stopped communicating',
    })

    // Simulate a full page reload: fresh Pinia (fresh in-memory state), same
    // logged-in user (cookie session survives a reload) — the store is
    // instantiated for the first time in this "session".
    setActivePinia(createPinia())
    useUserStore().currentUser = { id: 'user-1' }
    const reloadedStore = useNotificationStore()

    expect(reloadedStore.notifications.some((n) => n.id === 'local-4')).toBe(true)
  })

  it('user-scoped key isolation — a different account never rehydrates the prior user\'s `_local` rows', async () => {
    useUserStore().currentUser = { id: 'user-a' }
    useNotificationStore().addNotification({
      id: 'local-5',
      type: 'agent_health',
      title: 'Agent Silent',
      message: 'implementer - stopped communicating',
    })

    // A different account logs in on the same browser (fresh Pinia, different user id).
    setActivePinia(createPinia())
    useUserStore().currentUser = { id: 'user-b' }
    const otherUserStore = useNotificationStore()

    expect(otherUserStore.notifications.some((n) => n.id === 'local-5')).toBe(false)
  })

  it('clearAll(userId) clears that user\'s persisted `_local` rows so a later login as them starts empty', async () => {
    useUserStore().currentUser = { id: 'user-1' }
    const store = useNotificationStore()
    store.addNotification({
      id: 'local-6',
      type: 'agent_health',
      title: 'Agent Silent',
      message: 'implementer - stopped communicating',
    })

    // Logout path (stores/user.js) calls clearAll(outgoingUserId) with the id
    // captured before currentUser is nulled.
    store.clearAll('user-1')

    // Same user logs back in later (fresh Pinia — simulates the next session).
    setActivePinia(createPinia())
    useUserStore().currentUser = { id: 'user-1' }
    const nextSessionStore = useNotificationStore()

    expect(nextSessionStore.notifications.some((n) => n.id === 'local-6')).toBe(false)
  })
})
