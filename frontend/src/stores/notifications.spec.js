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
    useUserStore().currentUser = { id: 'user-1' }
    useNotificationStore().addNotification({
      id: 'local-4',
      type: 'agent_health',
      title: 'Agent Silent',
      message: 'implementer - stopped communicating',
    })

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

    store.clearAll('user-1')

    setActivePinia(createPinia())
    useUserStore().currentUser = { id: 'user-1' }
    const nextSessionStore = useNotificationStore()

    expect(nextSessionStore.notifications.some((n) => n.id === 'local-6')).toBe(false)
  })
})

describe('notifications store — D16 (Headless S3d) live resolve/update WS handlers', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockList.mockResolvedValue({ data: [] })
  })

  it('handleWsResolvedNotification drops every resolved id from the local list', async () => {
    const store = useNotificationStore()
    store.notifications = [
      { id: 'n1', type: 'system.skills_drift', surface: 'banner', dismissed_at: null, resolved_at: null },
      { id: 'n2', type: 'system.pending_migrations', surface: 'banner', dismissed_at: null, resolved_at: null },
      { id: 'n3', type: 'system.context_tuning_due', surface: 'banner', dismissed_at: null, resolved_at: null },
    ]

    store.handleWsResolvedNotification({ ids: ['n1', 'n3'] })

    expect(store.notifications.map((n) => n.id)).toEqual(['n2'])
    expect(store.bannerNotifications.some((n) => n.id === 'n1')).toBe(false)
  })

  it('handleWsResolvedNotification is a no-op for ids not currently known', () => {
    const store = useNotificationStore()
    store.notifications = [{ id: 'n1', type: 'system.skills_drift', surface: 'banner', dismissed_at: null, resolved_at: null }]

    store.handleWsResolvedNotification({ ids: ['does-not-exist'] })

    expect(store.notifications.map((n) => n.id)).toEqual(['n1'])
  })

  it('handleWsResolvedNotification ignores a malformed/empty payload', () => {
    const store = useNotificationStore()
    store.notifications = [{ id: 'n1', type: 'system.skills_drift', surface: 'banner', dismissed_at: null, resolved_at: null }]

    store.handleWsResolvedNotification({})
    store.handleWsResolvedNotification(null)
    store.handleWsResolvedNotification({ ids: [] })

    expect(store.notifications.map((n) => n.id)).toEqual(['n1'])
  })

  it('handleWsUpdatedNotification replaces an existing row by id in place', () => {
    const store = useNotificationStore()
    store.notifications = [
      {
        id: 'n1',
        type: 'system.pending_migrations',
        title: '5 database migrations pending',
        surface: 'banner',
        dismissed_at: null,
        resolved_at: null,
      },
    ]

    store.handleWsUpdatedNotification({
      id: 'n1',
      type: 'system.pending_migrations',
      title: '3 database migrations pending',
      surface: 'banner',
      dismissible: true,
    })

    expect(store.notifications).toHaveLength(1)
    expect(store.notifications[0].title).toBe('3 database migrations pending')
  })

  it('handleWsUpdatedNotification adds the row when the id is not yet known', () => {
    const store = useNotificationStore()
    store.notifications = []

    store.handleWsUpdatedNotification({ id: 'n9', type: 'system.skills_drift', title: 'Drift', surface: 'banner' })

    expect(store.notifications.map((n) => n.id)).toEqual(['n9'])
  })

  it('handleWsUpdatedNotification ignores a payload with no id', () => {
    const store = useNotificationStore()
    store.notifications = []

    store.handleWsUpdatedNotification({ title: 'no id here' })

    expect(store.notifications).toEqual([])
  })
})
