/**
 * useHubNotifications.popouts.fe9553.spec.js — FE-9553, milestone 2.
 *
 * Ruling 4, clause by clause:
 *   (a) pop ONLY when the app is hidden (Page Visibility). A visible tab gets
 *       the banner alone, NEVER both.
 *   (b) best-effort, never the only carrier. Already satisfied before this
 *       milestone -- the durable bell row is written ahead of the gate -- and
 *       pinned in useHubNotifications.spec.js's permission-denied test.
 *   (c) popouts follow banner state INCLUDING DEATH: a `tag` for dedupe, and
 *       close() when the banner clears.
 *
 * All of (a) and (c) fail on pre-M2 code, and they fail for a reason worth
 * stating: the gate was `isHubPresent` -- "am I standing in the Hub pane" --
 * not "is the app hidden". Those are different questions, and the difference
 * is precisely the double-notification the ruling forbids: on any page other
 * than the Hub, with the tab in front of you, the old code popped an OS
 * notification at a window you were already looking at.
 *
 * document.hidden SUPERSEDES isHubPresent here rather than joining it. A
 * hidden tab is not "in the pane" in any meaningful sense, so the old in-pane
 * suppression is subsumed by the stricter gate rather than ANDed with it.
 *
 * Edition Scope: Both
 */
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
// FE-9553 ruling 5: the popout scope preference. Mutable so a test can flip it
// and show the surface stop, which is what "every toggle proven to gate its
// surface" requires -- the store-level gate tests cover the banner toggles, and
// this covers the popout one at the only place a popout is raised.
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

/**
 * Page Visibility is not writable, so it is redefined per test. Configurable so
 * each test can set it again -- a non-configurable stub would make the first
 * test's value stick and silently pass the rest.
 */
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
    mockIsHubPresent.value = false // on some other page -- the old code popped here

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

  // CHECKER-MUST-FIRE for the negative above: the visible-tab case must still
  // reach the bell. Without this, "no popout" would pass just as well if the
  // listener never registered or the signal gate dropped the event entirely.
  it('the visible-tab case still writes the bell row -- silent, not broken', async () => {
    setHidden(false)

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockAddNotification).toHaveBeenCalledOnce()
  })

  it('being IN the Hub pane while hidden still pops -- document.hidden supersedes presence', async () => {
    // A hidden tab is not "in the pane" in any meaningful sense. Pinning this
    // so the old isHubPresent check cannot quietly come back as an extra AND.
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

  // END-TO-END, and deliberately not stopping at "the registry was called".
  // From inside either half, registered-and-closable looks identical to
  // registered-and-orphaned. This drives the REAL signal path, the REAL
  // registry and the REAL lifecycle, so a break anywhere between the WS event
  // and the popout's close() fails HERE rather than on someone's desktop.
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

    // The real Notification instance the signal path constructed.
    const raised = NotificationConstructorSpy.mock.instances[0]
    const tag = popoutTag(BATON_FOCUS, 'thread-1')
    expect(registeredPopoutTags()).toContain(tag)
    expect(closeSpy).not.toHaveBeenCalled()

    // The baton moves on: no live tags at all, which is what the lifecycle
    // computes from an empty your-turn list.
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
    // Stability: the tag must be derivable from the signal, not minted fresh --
    // a random tag would dedupe nothing and could never be closed by state.
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
    // Asking a browser for a capability the operator has told us not to use is
    // how a site gets permanently blocked -- and the request is irreversible
    // from our side, so a spurious prompt costs the feature for good.
    resetNotificationMock('default')
    mockPopoutScope.value = 'off'

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()
    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy.requestPermission).not.toHaveBeenCalled()
  })

  // CHECKER-MUST-FIRE for both negatives above: the same dispatch with the
  // scope allowed MUST pop. Without this, "no popout" would pass just as well
  // if the listener never registered or the event were dropped upstream.
  it('scope ACTIONABLE: a baton still pops -- the negatives above are the setting, not a broken path', async () => {
    mockPopoutScope.value = 'actionable'

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()
    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('scope ALL: also pops -- and is currently INDISTINGUISHABLE from actionable', async () => {
    // Recorded rather than glossed. Ruling 5 defines 'all' as "everything a
    // banner shows (actionable + lifecycle)", but nothing lifecycle-shaped
    // raises a popout today -- lifecycle events raise a banner row and a bell
    // row and stop there. So both positions admit exactly the same set, and the
    // middle option has no observable effect yet.
    //
    // That is a gap in the ruling's premise, not in this gate: the control is
    // implemented faithfully and will separate the moment a lifecycle popout
    // exists. Raised with the orchestrator rather than silently shipping a
    // three-position control with two effective positions.
    mockPopoutScope.value = 'all'

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()
    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('the bell row is written regardless of scope -- off means no POPOUT, not no record', async () => {
    // Ruling 4(b): a popout is best-effort and never the only carrier. Turning
    // popouts off must not cost the operator the durable record.
    mockPopoutScope.value = 'off'

    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()
    dispatchHubEvent('hub:thread_update', BATON_EVENT)

    expect(mockAddNotification).toHaveBeenCalled()
  })
})
