import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useNotificationStore } from '@/stores/notifications'

// Mock crypto.randomUUID
vi.stubGlobal('crypto', {
  randomUUID: vi.fn(() => `mock-uuid-${  Math.random().toString(36).substring(7)}`),
})

describe('useNotificationStore', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useNotificationStore()
    vi.clearAllMocks()
  })

  describe('State initialization', () => {
    it('initializes with empty notifications array', () => {
      expect(store.notifications).toEqual([])
    })

    it('initializes with unreadCount of 0', () => {
      expect(store.unreadCount).toBe(0)
    })

    it('initializes with empty sortedNotifications', () => {
      expect(store.sortedNotifications).toEqual([])
    })
  })

  describe('addNotification', () => {
    it('adds notification with auto-generated id and timestamp', () => {
      const notification = {
        type: 'system',
        title: 'Test Notification',
        message: 'Test message',
      }

      store.addNotification(notification)

      expect(store.notifications).toHaveLength(1)
      expect(store.notifications[0]).toMatchObject({
        type: 'system',
        title: 'Test Notification',
        message: 'Test message',
        read: false,
      })
      expect(store.notifications[0].id).toBeDefined()
      expect(store.notifications[0].timestamp).toBeDefined()
      expect(new Date(store.notifications[0].timestamp).toISOString()).toBe(
        store.notifications[0].timestamp,
      )
    })

    it('sets read to false by default', () => {
      store.addNotification({
        type: 'info',
        title: 'Info',
        message: 'Message',
      })

      expect(store.notifications[0].read).toBe(false)
    })

    it('includes metadata when provided', () => {
      const notification = {
        type: 'agent_health',
        title: 'Agent Failed',
        message: 'Agent xyz failed',
        metadata: {
          agent_id: 'agent-123',
          job_id: 'job-456',
          health_status: 'critical',
        },
      }

      store.addNotification(notification)

      expect(store.notifications[0].metadata).toEqual({
        agent_id: 'agent-123',
        job_id: 'job-456',
        health_status: 'critical',
      })
    })

    it('does not overwrite provided id if present', () => {
      const notification = {
        id: 'custom-id',
        type: 'system',
        title: 'Test',
        message: 'Message',
      }

      store.addNotification(notification)

      expect(store.notifications[0].id).toBe('custom-id')
    })

    it('does not overwrite provided timestamp if present', () => {
      const customTimestamp = '2025-01-01T00:00:00.000Z'
      const notification = {
        type: 'system',
        title: 'Test',
        message: 'Message',
        timestamp: customTimestamp,
      }

      store.addNotification(notification)

      expect(store.notifications[0].timestamp).toBe(customTimestamp)
    })

    it('increments unreadCount when adding notification', () => {
      expect(store.unreadCount).toBe(0)

      store.addNotification({ type: 'info', title: 'Test', message: 'Message' })
      expect(store.unreadCount).toBe(1)

      store.addNotification({ type: 'system', title: 'Test 2', message: 'Message 2' })
      expect(store.unreadCount).toBe(2)
    })
  })

  describe('markAsRead', () => {
    it('marks single notification as read', () => {
      store.addNotification({ type: 'info', title: 'Test', message: 'Message' })
      const id = store.notifications[0].id

      expect(store.notifications[0].read).toBe(false)
      expect(store.unreadCount).toBe(1)

      store.markAsRead(id)

      expect(store.notifications[0].read).toBe(true)
      expect(store.unreadCount).toBe(0)
    })

    it('does nothing if notification id not found', () => {
      store.addNotification({ type: 'info', title: 'Test', message: 'Message' })

      expect(store.unreadCount).toBe(1)
      store.markAsRead('non-existent-id')
      expect(store.unreadCount).toBe(1)
    })

    it('does not affect other notifications', () => {
      store.addNotification({ type: 'info', title: 'Test 1', message: 'Message 1' })
      store.addNotification({ type: 'info', title: 'Test 2', message: 'Message 2' })
      const firstId = store.notifications[0].id

      store.markAsRead(firstId)

      expect(store.notifications[0].read).toBe(true)
      expect(store.notifications[1].read).toBe(false)
      expect(store.unreadCount).toBe(1)
    })

    it('is idempotent - marking already read notification does nothing', () => {
      store.addNotification({ type: 'info', title: 'Test', message: 'Message' })
      const id = store.notifications[0].id

      store.markAsRead(id)
      expect(store.unreadCount).toBe(0)

      store.markAsRead(id)
      expect(store.unreadCount).toBe(0)
      expect(store.notifications[0].read).toBe(true)
    })
  })

  describe('markAllAsRead', () => {
    it('marks all notifications as read', () => {
      store.addNotification({ type: 'info', title: 'Test 1', message: 'Message 1' })
      store.addNotification({ type: 'system', title: 'Test 2', message: 'Message 2' })
      store.addNotification({ type: 'agent_health', title: 'Test 3', message: 'Message 3' })

      expect(store.unreadCount).toBe(3)

      store.markAllAsRead()

      expect(store.unreadCount).toBe(0)
      expect(store.notifications.every((n) => n.read === true)).toBe(true)
    })

    it('does nothing if no notifications exist', () => {
      expect(store.notifications).toHaveLength(0)
      store.markAllAsRead()
      expect(store.notifications).toHaveLength(0)
    })

    it('is idempotent - can call multiple times safely', () => {
      store.addNotification({ type: 'info', title: 'Test', message: 'Message' })

      store.markAllAsRead()
      expect(store.unreadCount).toBe(0)

      store.markAllAsRead()
      expect(store.unreadCount).toBe(0)
    })
  })

  describe('removeNotification', () => {
    it('removes notification by id', () => {
      store.addNotification({ type: 'info', title: 'Test 1', message: 'Message 1' })
      store.addNotification({ type: 'info', title: 'Test 2', message: 'Message 2' })

      const idToRemove = store.notifications[0].id
      expect(store.notifications).toHaveLength(2)

      store.removeNotification(idToRemove)

      expect(store.notifications).toHaveLength(1)
      expect(store.notifications.find((n) => n.id === idToRemove)).toBeUndefined()
    })

    it('updates unreadCount when removing unread notification', () => {
      store.addNotification({ type: 'info', title: 'Test 1', message: 'Message 1' })
      store.addNotification({ type: 'info', title: 'Test 2', message: 'Message 2' })

      expect(store.unreadCount).toBe(2)

      const idToRemove = store.notifications[0].id
      store.removeNotification(idToRemove)

      expect(store.unreadCount).toBe(1)
    })

    it('does not change unreadCount when removing read notification', () => {
      store.addNotification({ type: 'info', title: 'Test 1', message: 'Message 1' })
      store.addNotification({ type: 'info', title: 'Test 2', message: 'Message 2' })

      const idToRemove = store.notifications[0].id
      store.markAsRead(idToRemove)

      expect(store.unreadCount).toBe(1)

      store.removeNotification(idToRemove)

      expect(store.unreadCount).toBe(1)
    })

    it('does nothing if notification id not found', () => {
      store.addNotification({ type: 'info', title: 'Test', message: 'Message' })

      expect(store.notifications).toHaveLength(1)
      store.removeNotification('non-existent-id')
      expect(store.notifications).toHaveLength(1)
    })
  })

  describe('clearAll', () => {
    it('removes all notifications', () => {
      store.addNotification({ type: 'info', title: 'Test 1', message: 'Message 1' })
      store.addNotification({ type: 'system', title: 'Test 2', message: 'Message 2' })
      store.addNotification({ type: 'agent_health', title: 'Test 3', message: 'Message 3' })

      expect(store.notifications).toHaveLength(3)

      store.clearAll()

      expect(store.notifications).toHaveLength(0)
      expect(store.unreadCount).toBe(0)
    })

    it('does nothing if no notifications exist', () => {
      expect(store.notifications).toHaveLength(0)
      store.clearAll()
      expect(store.notifications).toHaveLength(0)
    })
  })

  describe('clearForProject', () => {
    it('removes notifications matching the project_id', () => {
      store.addNotification({
        type: 'agent_health', title: 'Alert 1', message: 'msg',
        metadata: { project_id: 'AAA' },
      })
      store.addNotification({
        type: 'agent_health', title: 'Alert 2', message: 'msg',
        metadata: { project_id: 'AAA' },
      })
      store.addNotification({
        type: 'agent_health', title: 'Alert 3', message: 'msg',
        metadata: { project_id: 'BBB' },
      })

      store.clearForProject('AAA')

      expect(store.notifications).toHaveLength(1)
      expect(store.notifications[0].metadata.project_id).toBe('BBB')
    })

    it('preserves system notifications without project_id', () => {
      store.addNotification({
        type: 'connection_lost', title: 'Connection Lost', message: 'msg',
      })
      store.addNotification({
        type: 'agent_health', title: 'Alert', message: 'msg',
        metadata: { project_id: 'AAA' },
      })

      store.clearForProject('AAA')

      expect(store.notifications).toHaveLength(1)
      expect(store.notifications[0].type).toBe('connection_lost')
    })

    it('is a no-op when called with null', () => {
      store.addNotification({ type: 'info', title: 'Test', message: 'msg' })

      store.clearForProject(null)

      expect(store.notifications).toHaveLength(1)
    })

    it('is a no-op when called with undefined', () => {
      store.addNotification({ type: 'info', title: 'Test', message: 'msg' })

      store.clearForProject(undefined)

      expect(store.notifications).toHaveLength(1)
    })

    it('updates unreadCount after clearing', () => {
      store.addNotification({
        type: 'agent_health', title: 'Alert 1', message: 'msg',
        metadata: { project_id: 'AAA' },
      })
      store.addNotification({
        type: 'agent_health', title: 'Alert 2', message: 'msg',
        metadata: { project_id: 'AAA' },
      })

      expect(store.unreadCount).toBe(2)

      store.clearForProject('AAA')

      expect(store.unreadCount).toBe(0)
    })

    // FE-9553: was 'recalculates badgeColor after clearing warning
    // notifications'. badgeColor is gone -- ruling 2 removed the bell's
    // severity treatment entirely -- but this test's real subject was
    // clearForProject, with badgeColor only as the observable. Re-pointed at
    // unreadCount so the clearForProject coverage survives the getter it
    // happened to be measured through.
    it('recalculates the unseen count after clearing a project\'s notifications', () => {
      store.addNotification({
        type: 'agent_health', title: 'Alert', message: 'msg',
        metadata: { project_id: 'AAA' },
      })

      expect(store.unreadCount).toBe(1)

      store.clearForProject('AAA')

      expect(store.unreadCount).toBe(0)
    })

    it('does not remove notifications with different project_id', () => {
      store.addNotification({
        type: 'agent_health', title: 'Alert', message: 'msg',
        metadata: { project_id: 'BBB' },
      })

      store.clearForProject('AAA')

      expect(store.notifications).toHaveLength(1)
    })

    // BE-9525c: the real shape-mismatch bug. A server-shape row (structured
    // payload, project_id inside payload not metadata) was never cleared
    // because clearForProject filtered on n.metadata?.project_id only.
    it('removes a server-shape row whose project_id lives in payload, not metadata', () => {
      store.handleWsNewNotification({
        id: 'srv-1',
        type: 'project.pre_launch_workproduct',
        title: 'Work committed without launch',
        payload: { project_id: 'AAA', project_name: 'Test', commit_count: 1 },
      })

      store.clearForProject('AAA')

      expect(store.notifications).toHaveLength(0)
    })

    // BE-9525c: the normalized shape -- a server row carrying the id
    // top-level (post-fix notification:new envelope) must also clear.
    it('removes a normalized row whose project_id is top-level', () => {
      store.handleWsNewNotification({
        id: 'srv-2',
        type: 'project.pre_launch_workproduct',
        project_id: 'AAA',
        title: 'Work committed without launch',
      })

      store.clearForProject('AAA')

      expect(store.notifications).toHaveLength(0)
    })
  })

  describe('Getters', () => {
    describe('unreadCount', () => {
      it('returns count of unread notifications', () => {
        store.addNotification({ type: 'info', title: 'Test 1', message: 'Message 1' })
        store.addNotification({ type: 'info', title: 'Test 2', message: 'Message 2' })
        store.addNotification({ type: 'info', title: 'Test 3', message: 'Message 3' })

        expect(store.unreadCount).toBe(3)

        store.markAsRead(store.notifications[0].id)
        expect(store.unreadCount).toBe(2)

        store.markAsRead(store.notifications[1].id)
        expect(store.unreadCount).toBe(1)

        store.markAllAsRead()
        expect(store.unreadCount).toBe(0)
      })
    })

    describe('sortedNotifications', () => {
      it('returns notifications sorted by timestamp (newest first)', () => {
        const oldTimestamp = '2025-01-01T00:00:00.000Z'
        const midTimestamp = '2025-01-02T00:00:00.000Z'
        const newTimestamp = '2025-01-03T00:00:00.000Z'

        store.addNotification({
          type: 'info',
          title: 'Old',
          message: 'Old message',
          timestamp: oldTimestamp,
        })
        store.addNotification({
          type: 'info',
          title: 'New',
          message: 'New message',
          timestamp: newTimestamp,
        })
        store.addNotification({
          type: 'info',
          title: 'Mid',
          message: 'Mid message',
          timestamp: midTimestamp,
        })

        const sorted = store.sortedNotifications

        expect(sorted[0].timestamp).toBe(newTimestamp)
        expect(sorted[1].timestamp).toBe(midTimestamp)
        expect(sorted[2].timestamp).toBe(oldTimestamp)
      })

      it('returns empty array if no notifications', () => {
        expect(store.sortedNotifications).toEqual([])
      })

      it('handles notifications with same timestamp consistently', () => {
        const sameTime = '2025-01-01T00:00:00.000Z'

        store.addNotification({
          type: 'info',
          title: 'First',
          message: 'First message',
          timestamp: sameTime,
        })
        store.addNotification({
          type: 'info',
          title: 'Second',
          message: 'Second message',
          timestamp: sameTime,
        })

        expect(store.sortedNotifications).toHaveLength(2)
      })
    })
  })

  describe('Multiple notifications workflow', () => {
    it('handles complex workflow of add, read, remove', () => {
      // Add three notifications
      store.addNotification({
        type: 'agent_health',
        title: 'Agent Failed',
        message: 'Agent xyz failed',
        metadata: { agent_id: 'agent-1' },
      })
      store.addNotification({ type: 'system', title: 'System Update', message: 'System updated' })
      store.addNotification({ type: 'info', title: 'Info', message: 'Info message' })

      expect(store.notifications).toHaveLength(3)
      expect(store.unreadCount).toBe(3)

      // Mark one as read
      const firstId = store.notifications[0].id
      store.markAsRead(firstId)

      expect(store.unreadCount).toBe(2)

      // Remove one
      const secondId = store.notifications[1].id
      store.removeNotification(secondId)

      expect(store.notifications).toHaveLength(2)
      expect(store.unreadCount).toBe(1)

      // Mark all as read
      store.markAllAsRead()

      expect(store.unreadCount).toBe(0)
      expect(store.notifications).toHaveLength(2)

      // Clear all
      store.clearAll()

      expect(store.notifications).toHaveLength(0)
      expect(store.unreadCount).toBe(0)
    })
  })

  describe('Edge cases', () => {
    it('handles notification with minimal data', () => {
      store.addNotification({
        type: 'info',
        title: 'Title',
        message: 'Message',
      })

      expect(store.notifications[0]).toMatchObject({
        type: 'info',
        title: 'Title',
        message: 'Message',
        read: false,
      })
      expect(store.notifications[0].id).toBeDefined()
      expect(store.notifications[0].timestamp).toBeDefined()
    })

    it('handles notification with all optional fields', () => {
      const notification = {
        id: 'custom-id',
        type: 'agent_health',
        title: 'Complete Notification',
        message: 'Complete message',
        timestamp: '2025-01-01T00:00:00.000Z',
        read: true,
        metadata: {
          agent_id: 'agent-123',
          job_id: 'job-456',
          extra_field: 'extra_value',
        },
      }

      store.addNotification(notification)

      // FE-9241: addNotification() now tags every row `_local: true` (these
      // client-originated rows are mirrored to localStorage so silent-agent
      // notifications survive a refresh) — assert the input fields verbatim
      // plus that tag, rather than a strict toEqual against the raw input.
      expect(store.notifications[0]).toEqual({ ...notification, _local: true })
      expect(store.unreadCount).toBe(0) // Because read: true
    })

    it('handles empty metadata object', () => {
      store.addNotification({
        type: 'info',
        title: 'Test',
        message: 'Message',
        metadata: {},
      })

      expect(store.notifications[0].metadata).toEqual({})
    })

    it('preserves notification order after operations', () => {
      store.addNotification({
        type: 'info',
        title: 'First',
        message: 'First',
        timestamp: '2025-01-01T00:00:00.000Z',
      })
      store.addNotification({
        type: 'info',
        title: 'Second',
        message: 'Second',
        timestamp: '2025-01-02T00:00:00.000Z',
      })
      store.addNotification({
        type: 'info',
        title: 'Third',
        message: 'Third',
        timestamp: '2025-01-03T00:00:00.000Z',
      })

      // Mark middle one as read
      store.markAsRead(store.notifications[1].id)

      // Original array should maintain insertion order
      expect(store.notifications[0].title).toBe('First')
      expect(store.notifications[1].title).toBe('Second')
      expect(store.notifications[2].title).toBe('Third')

      // But sorted should be reverse chronological
      expect(store.sortedNotifications[0].title).toBe('Third')
      expect(store.sortedNotifications[1].title).toBe('Second')
      expect(store.sortedNotifications[2].title).toBe('First')
    })
  })
})
