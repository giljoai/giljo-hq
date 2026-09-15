import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { ref } from 'vue'

const mockCurrentUser = ref({
  id: 'user-001',
  display_name: 'Sam Rivera',
  tenant_key: 'tenant-abc',
})
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: mockCurrentUser.value }),
}))

const mockIsHubPresent = ref(false)
vi.mock('./useHubPresence', () => ({
  useHubPresence: () => ({ isHubPresent: mockIsHubPresent }),
}))

const mockShowToast = vi.fn()
vi.mock('./useToast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}))

const mockRouterPush = vi.fn(() => Promise.resolve())
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockRouterPush }),
}))

const mockThreadsById = new Map()
const mockMessagesByThreadId = new Map()
vi.mock('@/stores/commHubStore', () => ({
  useCommHubStore: () => ({
    threadsById: mockThreadsById,
    messagesFor: (threadId) => mockMessagesByThreadId.get(threadId) || [],
  }),
}))

const mockAddNotification = vi.fn()
vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ addNotification: mockAddNotification }),
}))

let NotificationConstructorSpy
function resetNotificationMock(permission = 'granted') {
  NotificationConstructorSpy = vi.fn()
  NotificationConstructorSpy.permission = permission
  NotificationConstructorSpy.requestPermission = vi.fn().mockResolvedValue(permission)
  global.Notification = NotificationConstructorSpy
}

function dispatchHubEvent(name, detail) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

describe('FE-9553 M1: an agent-initiated Hub event produces NO toast', () => {
  const activeListeners = []
  const _origAddEventListener = window.addEventListener.bind(window)
  const _origRemoveEventListener = window.removeEventListener.bind(window)

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetModules()
    vi.clearAllMocks()
    resetNotificationMock('granted')
    mockIsHubPresent.value = false
    mockThreadsById.clear()
    mockMessagesByThreadId.clear()
    mockCurrentUser.value = {
      id: 'user-001',
      display_name: 'Sam Rivera',
      tenant_key: 'tenant-abc',
    }
    vi.spyOn(window, 'addEventListener').mockImplementation((type, handler, options) => {
      if (type === 'hub:thread_message' || type === 'hub:thread_update') {
        activeListeners.push({ type, handler })
      }
      return _origAddEventListener(type, handler, options)
    })
  })

  afterEach(() => {
    for (const { type, handler } of activeListeners) {
      _origRemoveEventListener(type, handler)
    }
    activeListeners.length = 0
    vi.restoreAllMocks()
    delete global.Notification
  })

  it('a baton handed to me while I am away from the Hub does not toast (ruling 3: batons are banners)', async () => {
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'user-001',
    })

    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('a directed action-request post does not toast', async () => {
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-2',
      message_id: 'msg-1',
      from_agent_id: 'CI2',
      requires_action: true,
      content: 'need a decision',
    })

    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('a mention does not toast', async () => {
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-3',
      message_id: 'msg-2',
      from_agent_id: 'CI2',
      content: 'Sam Rivera can you look at this',
    })

    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('the same event still reaches the bell -- proving the path is live, not merely silent', async () => {
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-4',
      next_action_owner: 'user-001',
    })

    expect(mockAddNotification).toHaveBeenCalled()
  })
})
