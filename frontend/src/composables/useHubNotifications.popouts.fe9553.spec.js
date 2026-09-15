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

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(() => Promise.resolve()) }),
}))

const mockThreadsById = new Map()
vi.mock('@/stores/commHubStore', () => ({
  useCommHubStore: () => ({
    threadsById: mockThreadsById,
    messagesFor: () => [],
  }),
}))

const mockAddNotification = vi.fn()
const mockPopoutScope = vi.hoisted(() => ({ value: 'all' }))
vi.mock('@/stores/settings', () => ({
  useSettingsStore: () => ({
    get popoutScope() {
      return mockPopoutScope.value
    },
  }),
}))

vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ addNotification: mockAddNotification }),
}))

let NotificationConstructorSpy
const closeSpy = vi.fn()

function resetNotificationMock(permission = 'granted') {
  closeSpy.mockClear()
  NotificationConstructorSpy = vi.fn(function MockNotification() {
    this.close = closeSpy
  })
  NotificationConstructorSpy.permission = permission
  NotificationConstructorSpy.requestPermission = vi.fn().mockResolvedValue(permission)
  global.Notification = NotificationConstructorSpy
}

function setHidden(hidden) {
  Object.defineProperty(document, 'hidden', {
    configurable: true,
    get: () => hidden,
  })
}

function dispatchHubEvent(name, detail) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

const BATON_EVENT = {
  thread_id: 'thread-1',
  chat_id: 'CHT-0001',
  next_action_owner: 'user-001',
  from_display_name: 'Lane 7',
}

describe('FE-9553 M2 ruling 4(a): pop ONLY when the app is hidden', () => {
  const activeListeners = []
  const _origAdd = window.addEventListener.bind(window)
  const _origRemove = window.removeEventListener.bind(window)

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetModules()
    vi.clearAllMocks()
    resetNotificationMock('granted')
    mockIsHubPresent.value = false
    mockThreadsById.clear()
    setHidden(true)
    vi.spyOn(window, 'addEventListener').mockImplementation((type, handler, options) => {
      if (type === 'hub:thread_message' || type === 'hub:thread_update') {
        activeListeners.push({ type, handler })
      }
      return _origAdd(type, handler, options)
    })
  })

  afterEach(() => {
    for (const { type, handler } of activeListeners) _origRemove(type, handler)
    activeListeners.length = 0
    vi.restoreAllMocks()
    delete global.Notification
    setHidden(false)
  })

  it('a VISIBLE tab gets NO popout, even when the operator is away from the Hub pane', async () => {
    setHidden(false)
    mockIsHubPresent.value = false

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('a HIDDEN tab does get the popout', async () => {
    setHidden(true)

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('the visible-tab case still writes the bell row -- silent, not broken', async () => {
    setHidden(false)

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockAddNotification).toHaveBeenCalledOnce()
  })

  it('being IN the Hub pane while hidden still pops -- document.hidden supersedes presence', async () => {
    setHidden(true)
    mockIsHubPresent.value = true

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })
})

describe('FE-9553 M2 ruling 4(c): tag for dedupe', () => {
  const activeListeners = []
  const _origAdd = window.addEventListener.bind(window)
  const _origRemove = window.removeEventListener.bind(window)

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetModules()
    vi.clearAllMocks()
    resetNotificationMock('granted')
    mockIsHubPresent.value = false
    mockThreadsById.clear()
    setHidden(true)
    vi.spyOn(window, 'addEventListener').mockImplementation((type, handler, options) => {
      if (type === 'hub:thread_message' || type === 'hub:thread_update') {
        activeListeners.push({ type, handler })
      }
      return _origAdd(type, handler, options)
    })
  })

  afterEach(() => {
    for (const { type, handler } of activeListeners) _origRemove(type, handler)
    activeListeners.length = 0
    vi.restoreAllMocks()
    delete global.Notification
    setHidden(false)
  })

  it('passes a tag so the OS replaces rather than stacks a repeat of the same signal', async () => {
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    const [, opts] = NotificationConstructorSpy.mock.calls[0]
    expect(opts.tag).toBeTruthy()
  })

  it('a baton popout raised while hidden is closed for real once the baton moves on', async () => {
    const { clearPopoutRegistry, registeredPopoutTags, reconcilePopouts } = await import(
      '@/utils/popoutRegistry'
    )
    const { popoutTag } = await import('@/utils/popoutTag')
    const { BATON_FOCUS } = await import('@/components/hub/hubThreadRoute')
    clearPopoutRegistry()

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    const raised = NotificationConstructorSpy.mock.instances[0]
    const tag = popoutTag(BATON_FOCUS, 'thread-1')
    expect(registeredPopoutTags()).toContain(tag)
    expect(closeSpy).not.toHaveBeenCalled()

    reconcilePopouts(new Set())

    expect(raised.close).toHaveBeenCalledOnce()
    expect(registeredPopoutTags()).not.toContain(tag)
  })

  it('the tag is STABLE for the same signal on the same thread, and distinct across threads', async () => {
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', BATON_EVENT)
    dispatchHubEvent('hub:thread_update', { ...BATON_EVENT, thread_id: 'thread-2' })

    const tags = NotificationConstructorSpy.mock.calls.map(([, opts]) => opts.tag)
    expect(tags).toHaveLength(2)
    expect(tags[0]).not.toBe(tags[1])
    expect(tags[0]).toContain('thread-1')
    expect(tags[1]).toContain('thread-2')
  })
})

describe('FE-9553 ruling 5: the popout scope preference gates the surface', () => {
  const activeListeners = []
  const _origAdd = window.addEventListener.bind(window)
  const _origRemove = window.removeEventListener.bind(window)

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetModules()
    vi.clearAllMocks()
    resetNotificationMock('granted')
    mockIsHubPresent.value = false
    mockThreadsById.clear()
    mockPopoutScope.value = 'all'
    setHidden(true)
    vi.spyOn(window, 'addEventListener').mockImplementation((type, handler, options) => {
      if (type === 'hub:thread_message' || type === 'hub:thread_update') {
        activeListeners.push({ type, handler })
      }
      return _origAdd(type, handler, options)
    })
  })

  afterEach(() => {
    for (const { type, handler } of activeListeners) _origRemove(type, handler)
    activeListeners.length = 0
    vi.restoreAllMocks()
    delete global.Notification
    setHidden(false)
  })

  it('scope OFF: no popout, even hidden and with permission granted', async () => {
    mockPopoutScope.value = 'off'

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()
    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('scope OFF does not even ASK for permission', async () => {
    resetNotificationMock('default')
    mockPopoutScope.value = 'off'

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()
    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy.requestPermission).not.toHaveBeenCalled()
  })

  it('scope ACTIONABLE: a baton still pops -- the negatives above are the setting, not a broken path', async () => {
    mockPopoutScope.value = 'actionable'

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()
    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('scope ALL: also pops -- and is currently INDISTINGUISHABLE from actionable', async () => {
    mockPopoutScope.value = 'all'

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()
    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('the bell row is written regardless of scope -- off means no POPOUT, not no record', async () => {
    mockPopoutScope.value = 'off'

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()
    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(mockAddNotification).toHaveBeenCalled()
  })
})
