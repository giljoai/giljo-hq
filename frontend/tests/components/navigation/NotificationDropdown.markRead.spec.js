/**
 * Characterization of the bell's two navigate paths (row click and project
 * chip): an unread notification is marked read before the route push, a read
 * one is not, and a failed mark-read still navigates.
 *
 * Edition scope: CE
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import NotificationDropdown from '@/components/navigation/NotificationDropdown.vue'
import { useNotificationStore } from '@/stores/notifications'

const h = vi.hoisted(() => ({ calls: [] }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: (r) => h.calls.push(['push', r]) }) }))
vi.mock('date-fns', () => ({ formatDistanceToNow: vi.fn(() => '2 hours ago') }))
vi.mock('@/stores/websocket', () => ({ useWebSocketStore: () => ({ on: vi.fn(() => vi.fn()) }) }))
vi.mock('@/stores/user', () => ({ useUserStore: () => ({ currentUser: { id: 'user-1' } }) }))

const note = (over) => ({
  id: 'n1',
  type: 'agent_health',
  severity: 'warning',
  title: 't',
  body: 'b',
  read: false,
  project_id: 'p1',
  payload: { project_name: 'Proj' },
  metadata: { project_id: 'p1', project_name: 'Proj' },
  created_at: '2026-06-03T00:00:00Z',
  timestamp: '2026-06-03T00:00:00Z',
  ...over,
})

function mountWith(n, markRead) {
  const w = mount(NotificationDropdown, {
    global: {
      plugins: [createTestingPinia({ createSpy: vi.fn, initialState: { notifications: { notifications: [n] } } })],
    },
  })
  useNotificationStore().markRead = vi.fn(async (id) => {
    h.calls.push(['markRead', id])
    if (markRead === 'fail') throw new Error('offline')
  })
  return w
}

const ROUTE = { name: 'JobsViewport', query: { project: 'p1' } }
const PATHS = [
  ['row click', (w) => w.find('.notification-item').trigger('click')],
  ['project chip', (w) => w.find('.notification-project-chip').trigger('click')],
]

describe('NotificationDropdown navigate paths', () => {
  beforeEach(() => {
    h.calls.length = 0
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it.each(PATHS)('%s: unread is marked read, then navigates', async (_n, click) => {
    const w = mountWith(note())
    await click(w)
    await flushPromises()
    expect(h.calls).toEqual([['markRead', 'n1'], ['push', ROUTE]])
  })

  it.each(PATHS)('%s: already read skips mark-read', async (_n, click) => {
    const w = mountWith(note({ read: true }))
    await click(w)
    await flushPromises()
    expect(h.calls).toEqual([['push', ROUTE]])
  })

  it.each(PATHS)('%s: a failed mark-read still navigates and is logged', async (_n, click) => {
    const w = mountWith(note(), 'fail')
    await click(w)
    await flushPromises()
    expect(h.calls).toEqual([['markRead', 'n1'], ['push', ROUTE]])
    expect(console.error).toHaveBeenCalledWith(
      '[NotificationDropdown] Error marking notification as read:',
      expect.any(Error),
    )
  })
})
