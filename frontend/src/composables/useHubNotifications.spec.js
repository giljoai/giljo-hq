/**
 * useHubNotifications.spec.js — FE-6054f
 * Tests for the gated, no-spam alerting composable.
 *
 * Gate rules:
 * - thread_update: next_action_owner === currentUser.id → notify if AWAY
 * - thread_message: requires_action === true → notify if AWAY
 * - thread_message: content mentions user display_name (case-insensitive) → notify if AWAY
 * - OWN posts (from_agent_id === currentUser.id) → NEVER notify
 * - Presence (isHubPresent=true) → NEVER notify (in-pane cue only)
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { ref } from 'vue'

// ── mocks ──

const mockCurrentUser = ref({
  id: 'user-001',
  display_name: 'Patrik',
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

// FE-9289c: the composable now routes on handover click and reads the thread name
// from the store for the notification body.
const mockRouterPush = vi.fn(() => Promise.resolve())
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockRouterPush }),
}))

const mockThreadsById = new Map()
vi.mock('@/stores/commHubStore', () => ({
  useCommHubStore: () => ({ threadsById: mockThreadsById }),
}))

// FE-9289c: a handover also drops a persistent entry in the notification bell.
const mockAddNotification = vi.fn()
vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ addNotification: mockAddNotification }),
}))

// Minimal Notification mock
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

describe('useHubNotifications', () => {
  // Track registered listeners so we can clean them up manually —
  // onScopeDispose does not fire in plain unit tests (no Vue scope)
  const activeListeners = []
  const _origAddEventListener = window.addEventListener.bind(window)
  const _origRemoveEventListener = window.removeEventListener.bind(window)

  beforeEach(async () => {
    setActivePinia(createPinia())
    vi.resetModules()
    vi.clearAllMocks()
    resetNotificationMock('granted')
    mockIsHubPresent.value = false
    mockThreadsById.clear()
    mockAddNotification.mockClear()
    mockCurrentUser.value = {
      id: 'user-001',
      display_name: 'Patrik',
      tenant_key: 'tenant-abc',
    }

    // Intercept addEventListener so we can clean up between tests
    vi.spyOn(window, 'addEventListener').mockImplementation((type, handler, options) => {
      if (type === 'hub:thread_message' || type === 'hub:thread_update') {
        activeListeners.push({ type, handler })
      }
      return _origAddEventListener(type, handler, options)
    })
  })

  afterEach(() => {
    // Remove all hub listeners accumulated during this test
    for (const { type, handler } of activeListeners) {
      _origRemoveEventListener(type, handler)
    }
    activeListeners.length = 0
    vi.restoreAllMocks()
    delete global.Notification
  })

  // ── PRESENT → in-pane only, no Notification ──

  it('does NOT fire Notification when user is present and baton handed to them', async () => {
    mockIsHubPresent.value = true
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'user-001',
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('does NOT fire Notification when present and message requires_action', async () => {
    mockIsHubPresent.value = true
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-1',
      from_agent_id: 'agent-x',
      content: 'urgent',
      requires_action: true,
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  // ── AWAY → toast + Notification ──

  it('fires toast + Notification when AWAY and baton handed to currentUser', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'user-001',
    })

    expect(mockShowToast).toHaveBeenCalledOnce()
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('fires toast + Notification when AWAY and message has requires_action=true', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-2',
      from_agent_id: 'agent-x',
      content: 'please review',
      requires_action: true,
    })

    expect(mockShowToast).toHaveBeenCalledOnce()
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('fires toast + Notification when AWAY and message mentions display_name (case-insensitive)', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-3',
      from_agent_id: 'agent-x',
      content: 'hey patrik, take a look',
      requires_action: false,
    })

    expect(mockShowToast).toHaveBeenCalledOnce()
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  // ── Own posts → never notify ──

  it('does NOT notify for own posts (from_agent_id === currentUser.id)', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-4',
      from_agent_id: 'user-001', // own post
      content: 'hello there',
      requires_action: true,
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  // ── Non-user-invoked → never notify ──

  it('does NOT notify for a plain broadcast with no requires_action and no mention', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-5',
      from_agent_id: 'agent-x',
      content: 'running build step 3',
      requires_action: false,
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('does NOT notify for a thread_update where baton goes to someone else', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'agent-xyz', // not the current user
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  // ── Notification.permission denied → no Notification, toast still fires ──

  it('fires toast but NOT Notification when permission is denied', async () => {
    resetNotificationMock('denied')
    mockIsHubPresent.value = false

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'user-001',
    })

    expect(mockShowToast).toHaveBeenCalledOnce()
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  // ── FE-9289c: persistent bell entry (survives navigation) ──

  it('drops a persistent handover entry on baton, deduped by a stable per-thread id', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-9', next_action_owner: 'user-001' })

    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'handover:thread-9', type: 'handover', metadata: { thread_id: 'thread-9' } }),
    )
  })

  it('records the persistent entry even when the operator IS in the Hub (durable record)', async () => {
    mockIsHubPresent.value = true
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-9', next_action_owner: 'user-001' })

    // Persistent entry recorded, but the interruptive channels stayed silent in-pane.
    expect(mockAddNotification).toHaveBeenCalledOnce()
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('does NOT drop a bell entry for an ordinary message (only handovers persist)', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'm1',
      from_agent_id: 'agent-x',
      content: 'hey patrik',
      requires_action: false,
    })

    expect(mockAddNotification).not.toHaveBeenCalled()
  })

  // ── FE-9289c: handover copy + deep-link ──

  it('titles a handover "It\'s your call" and names the thread, not "Message Hub / Your turn"', async () => {
    mockIsHubPresent.value = false
    mockThreadsById.set('thread-1', { thread_id: 'thread-1', subject: 'Laptop interop' })
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-1', next_action_owner: 'user-001' })

    const [title, opts] = NotificationConstructorSpy.mock.calls[0]
    expect(title).toBe("It's your call")
    expect(opts.body).toContain('Laptop interop')
    expect(opts.body).toContain('waiting on you')
  })

  it('deep-links the handover Notification click to the thread (works from a cold page)', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-42', next_action_owner: 'user-001' })

    // Simulate the operator clicking the browser notification.
    const instance = NotificationConstructorSpy.mock.results[0]?.value ?? {}
    // The composable assigns onclick to the constructed Notification; grab it off the
    // instance the constructor was invoked with.
    const onclick = NotificationConstructorSpy.mock.instances[0]?.onclick || instance.onclick
    expect(typeof onclick).toBe('function')
    onclick()

    expect(mockRouterPush).toHaveBeenCalledWith({ path: '/hub', query: { thread: 'thread-42' } })
  })

  // ── De-dup: same signal key does not fire twice ──

  it('de-dupes: same baton event on same thread does not fire twice', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    const payload = { thread_id: 'thread-1', next_action_owner: 'user-001' }
    dispatchHubEvent('hub:thread_update', payload)
    dispatchHubEvent('hub:thread_update', payload)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })
})
