/**
 * Vitest spec for DB-backed notifications store (IMP-5037a Phase 2)
 *
 * Covers:
 *  - fetch() on mount loads from GET /api/notifications
 *  - notification:new WS event merges into list (deduped by id)
 *  - markRead() calls PATCH .../read and updates local state
 *  - markDismissed() calls PATCH .../dismiss and removes from list
 *  - mark-read persists across a simulated refresh (re-fetch)
 *
 * Conventions: setActivePinia per test, mock api service, no order deps.
 * setup.js already mocks @/services/api; we override per test via mockResolvedValueOnce.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useNotificationStore } from '@/stores/notifications'

// setup.js mocks @/services/api globally. We import the mock and control it here.
import { api } from '@/services/api'

// ---------------------------------------------------------------------------
// Sample fixtures matching backend NotificationResponse shape
// ---------------------------------------------------------------------------
const NOTIF_1 = {
  id: 'notif-1',
  type: 'api_key.expiring_soon',
  severity: 'warning',
  title: 'API key expiring',
  body: 'Your key "dev-key" expires in 7 days',
  payload: { api_key_id: 'key-1', name: 'dev-key', expires_at: '2026-06-10T00:00:00Z' },
  read_at: null,
  dismissed_at: null,
  created_at: '2026-06-03T00:00:00Z',
}

const NOTIF_2 = {
  id: 'notif-2',
  type: 'api_key.expiring_soon',
  severity: 'warning',
  title: 'Another key expiring',
  body: 'Your key "prod-key" expires in 3 days',
  payload: { api_key_id: 'key-2', name: 'prod-key', expires_at: '2026-06-06T00:00:00Z' },
  read_at: null,
  dismissed_at: null,
  created_at: '2026-06-02T00:00:00Z',
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('useNotificationStore (DB-backed)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  // -------------------------------------------------------------------------
  // 1. fetch() loads from GET /api/notifications
  // -------------------------------------------------------------------------
  describe('fetch()', () => {
    it('populates notifications from GET /api/notifications', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1, NOTIF_2] })

      const store = useNotificationStore()
      await store.fetch()

      expect(store.notifications).toHaveLength(2)
      expect(store.notifications.find((n) => n.id === 'notif-1')).toBeTruthy()
      expect(store.notifications.find((n) => n.id === 'notif-2')).toBeTruthy()
    })

    it('sets read=false when read_at is null, read=true when read_at is set', async () => {
      const readNotif = { ...NOTIF_2, read_at: '2026-06-03T01:00:00Z' }
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1, readNotif] })

      const store = useNotificationStore()
      await store.fetch()

      const unread = store.notifications.find((n) => n.id === 'notif-1')
      const read = store.notifications.find((n) => n.id === 'notif-2')
      expect(unread.read).toBe(false)
      expect(read.read).toBe(true)
    })

    it('updates unreadCount after fetch', async () => {
      const readNotif = { ...NOTIF_2, read_at: '2026-06-03T01:00:00Z' }
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1, readNotif] })

      const store = useNotificationStore()
      await store.fetch()

      expect(store.unreadCount).toBe(1)
    })

    it('replaces existing notifications on re-fetch (simulates page refresh)', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1] })
      const store = useNotificationStore()
      await store.fetch()
      expect(store.notifications).toHaveLength(1)

      // Second fetch — NOTIF_1 now read, NOTIF_2 added
      const readNotif1 = { ...NOTIF_1, read_at: '2026-06-03T02:00:00Z' }
      api.notifications.list.mockResolvedValueOnce({ data: [readNotif1, NOTIF_2] })
      await store.fetch()

      expect(store.notifications).toHaveLength(2)
      const n1 = store.notifications.find((n) => n.id === 'notif-1')
      expect(n1.read_at).toBe('2026-06-03T02:00:00Z')
      expect(n1.read).toBe(true)
    })

    it('handles empty response gracefully', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [] })

      const store = useNotificationStore()
      await store.fetch()

      expect(store.notifications).toHaveLength(0)
      expect(store.unreadCount).toBe(0)
    })

    it('does not throw on fetch error and preserves existing notifications', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1] })
      const store = useNotificationStore()
      await store.fetch()
      expect(store.notifications).toHaveLength(1)

      // Second fetch fails — existing notifications preserved
      api.notifications.list.mockRejectedValueOnce(new Error('Network error'))
      await expect(store.fetch()).resolves.toBeUndefined()
      expect(store.notifications).toHaveLength(1)
    })
  })

  // -------------------------------------------------------------------------
  // 2. notification:new WS event merges into list (handleWsNewNotification)
  // -------------------------------------------------------------------------
  describe('handleWsNewNotification()', () => {
    it('appends a new notification from a WS broadcast event', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1] })
      const store = useNotificationStore()
      await store.fetch()

      store.handleWsNewNotification({
        id: 'notif-ws-1',
        user_id: null,
        type: 'api_key.expiring_soon',
        severity: 'warning',
        title: 'WS notification',
        body: null,
        payload: { api_key_id: 'key-3', name: 'dev-key-2', expires_at: '2026-06-15T00:00:00Z' },
        created_at: '2026-06-03T01:00:00Z',
      })

      expect(store.notifications).toHaveLength(2)
      expect(store.notifications.find((n) => n.id === 'notif-ws-1')).toBeTruthy()
    })

    it('deduplicates by id — ignores event if id already present', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1] })
      const store = useNotificationStore()
      await store.fetch()

      // Same id as NOTIF_1 arrives again via WS
      store.handleWsNewNotification({ ...NOTIF_1 })

      expect(store.notifications).toHaveLength(1)
    })

    it('new WS notification increments unreadCount', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [] })
      const store = useNotificationStore()
      await store.fetch()
      expect(store.unreadCount).toBe(0)

      store.handleWsNewNotification({
        id: 'notif-ws-2',
        user_id: null,
        type: 'api_key.expiring_soon',
        severity: 'warning',
        title: 'WS notification',
        body: null,
        payload: { api_key_id: 'k', name: 'k', expires_at: '2026-07-01T00:00:00Z' },
        created_at: '2026-06-03T01:00:00Z',
      })

      expect(store.unreadCount).toBe(1)
    })
  })

  // -------------------------------------------------------------------------
  // 3. markRead() calls PATCH and updates local state
  // -------------------------------------------------------------------------
  describe('markRead(id)', () => {
    it('calls api.notifications.markRead with the correct id', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1] })
      api.notifications.markRead.mockResolvedValueOnce({
        data: { ...NOTIF_1, read_at: '2026-06-03T02:00:00Z' },
      })

      const store = useNotificationStore()
      await store.fetch()
      await store.markRead('notif-1')

      expect(api.notifications.markRead).toHaveBeenCalledWith('notif-1')
    })

    it('updates local read_at and read flag after markRead', async () => {
      const readAt = '2026-06-03T02:00:00Z'
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1] })
      api.notifications.markRead.mockResolvedValueOnce({
        data: { ...NOTIF_1, read_at: readAt },
      })

      const store = useNotificationStore()
      await store.fetch()
      expect(store.notifications[0].read).toBe(false)

      await store.markRead('notif-1')

      const updated = store.notifications.find((n) => n.id === 'notif-1')
      expect(updated.read_at).toBe(readAt)
      expect(updated.read).toBe(true)
    })

    it('unreadCount decrements after markRead', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1, NOTIF_2] })
      api.notifications.markRead.mockResolvedValueOnce({
        data: { ...NOTIF_1, read_at: '2026-06-03T02:00:00Z' },
      })

      const store = useNotificationStore()
      await store.fetch()
      expect(store.unreadCount).toBe(2)

      await store.markRead('notif-1')
      expect(store.unreadCount).toBe(1)
    })

    it('mark-read persists across simulated page refresh', async () => {
      // First fetch — both unread
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1, NOTIF_2] })
      api.notifications.markRead.mockResolvedValueOnce({
        data: { ...NOTIF_1, read_at: '2026-06-03T02:00:00Z' },
      })

      const store = useNotificationStore()
      await store.fetch()
      await store.markRead('notif-1')

      // Simulate page refresh — server returns NOTIF_1 with read_at set
      const readNotif1 = { ...NOTIF_1, read_at: '2026-06-03T02:00:00Z' }
      api.notifications.list.mockResolvedValueOnce({ data: [readNotif1, NOTIF_2] })
      await store.fetch()

      const n1 = store.notifications.find((n) => n.id === 'notif-1')
      expect(n1.read).toBe(true)
      expect(store.unreadCount).toBe(1)
    })
  })

  // -------------------------------------------------------------------------
  // 4. markDismissed() calls PATCH and removes from local list
  // -------------------------------------------------------------------------
  describe('markDismissed(id)', () => {
    it('calls api.notifications.markDismissed with the correct id', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1] })
      api.notifications.markDismissed.mockResolvedValueOnce({
        data: { ...NOTIF_1, dismissed_at: '2026-06-03T02:00:00Z' },
      })

      const store = useNotificationStore()
      await store.fetch()
      await store.markDismissed('notif-1')

      expect(api.notifications.markDismissed).toHaveBeenCalledWith('notif-1')
    })

    it('removes dismissed notification from local list', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1, NOTIF_2] })
      api.notifications.markDismissed.mockResolvedValueOnce({
        data: { ...NOTIF_1, dismissed_at: '2026-06-03T02:00:00Z' },
      })

      const store = useNotificationStore()
      await store.fetch()
      expect(store.notifications).toHaveLength(2)

      await store.markDismissed('notif-1')

      expect(store.notifications).toHaveLength(1)
      expect(store.notifications.find((n) => n.id === 'notif-1')).toBeUndefined()
    })
  })

  // -------------------------------------------------------------------------
  // 5. sortedNotifications uses created_at from server response
  // -------------------------------------------------------------------------
  describe('sortedNotifications', () => {
    it('sorts by created_at descending (newest first)', async () => {
      // NOTIF_1 created_at 2026-06-03, NOTIF_2 created_at 2026-06-02
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_2, NOTIF_1] })

      const store = useNotificationStore()
      await store.fetch()

      expect(store.sortedNotifications[0].id).toBe('notif-1') // newer
      expect(store.sortedNotifications[1].id).toBe('notif-2') // older
    })
  })

  // -------------------------------------------------------------------------
  // 6. FE-9553 ruling 2: the bell keeps a quiet unseen-count only.
  //
  // This block used to assert badgeColor mapped severity to red/amber for the
  // bell. That getter is deleted, not renamed: ranking unread rows by urgency
  // in order to alert on the bell is the exact behaviour the ruling removes,
  // and urgency now lives in banners exclusively. The count itself is still
  // pinned -- immediately below -- because that is what the bell is FOR.
  // Behaviour coverage for the quiet bell lives in
  // tests/components/navigation/NotificationDropdown.bellquiet.fe9553.spec.js.
  // -------------------------------------------------------------------------
  describe('the quiet counter (FE-9553)', () => {
    it('counts an unread server notification without expressing any urgency about it', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [NOTIF_1] })

      const store = useNotificationStore()
      await store.fetch()

      expect(store.unreadCount).toBe(1)
      // The store no longer offers ANY severity-derived signal for the bell.
      expect(store.badgeColor).toBeUndefined()
    })

    it('counts zero when there is nothing unread', async () => {
      api.notifications.list.mockResolvedValueOnce({ data: [] })

      const store = useNotificationStore()
      await store.fetch()

      expect(store.unreadCount).toBe(0)
    })
  })
})
