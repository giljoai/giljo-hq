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

// FE-9289c: the composable now routes on handover click and reads the thread name
// from the store for the notification body.
const mockRouterPush = vi.fn(() => Promise.resolve())
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockRouterPush }),
}))

const mockThreadsById = new Map()
// BE-9414: the store is now also consulted for the FULL body of a message whose
// event carried only a bounded excerpt. Additive — every pre-existing test in this
// file dispatches untruncated events, which never reach messagesFor.
const mockMessagesByThreadId = new Map()
vi.mock('@/stores/commHubStore', () => ({
  useCommHubStore: () => ({
    threadsById: mockThreadsById,
    messagesFor: (threadId) => mockMessagesByThreadId.get(threadId) || [],
  }),
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
    mockMessagesByThreadId.clear()
    mockAddNotification.mockClear()
    mockCurrentUser.value = {
      id: 'user-001',
      display_name: 'Sam Rivera',
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

  /**
   * FE-9439 item 4 — the desktop notification wears the AVATAR, not the wordmark.
   *
   * `/Giljo_YW.svg` is the yellow GiljoAI WORDMARK, so the Windows popup showed a strip
   * of text where every other surface in the app shows the face. The shipped badge is a
   * padded square PNG on solid navy: the OS renders this slot at a size and on a
   * background we do not control, so a non-square source letterboxes and a transparent
   * one loses its light-grey eyes against a light-theme notification surface.
   *
   * Asserted as a literal rather than against the module's own constant — importing the
   * value the code under test uses would pass whatever that value became.
   */
  it('badges the desktop notification with the avatar, not the wordmark', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'user-001',
    })

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
    const [, options] = NotificationConstructorSpy.mock.calls[0]
    expect(options.icon).toBe('/icons/Giljo_Face_Avatar.png')
    expect(options.icon).not.toContain('Giljo_YW.svg')
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
      content: 'hey sam rivera, take a look',
      requires_action: false,
    })

    expect(mockShowToast).toHaveBeenCalledOnce()
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  // ── FE-9418: the browser notification's click travels the shared route ──

  it('sends a HANDOVER click through hubThreadRoute, so all four surfaces land alike', async () => {
    // The banner, the Hub's attention strip and both bell rows already route through
    // the helper. This was the fourth notification raised by the same hand-off and the
    // only one still hand-building its route, so it arrived without the baton context
    // and marked nothing.
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-1', next_action_owner: 'user-001' })
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()

    NotificationConstructorSpy.mock.instances[0].onclick()
    expect(mockRouterPush).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thread-1', focus: 'baton' },
    })
  })

  it('does NOT stamp the baton flag on a mention, which nobody handed over', async () => {
    // MEANING CHANGED by FE-9436, on the FE-9418 precedent below. This used to assert the
    // bare `{ thread }` query, because the only flag that existed said "Waiting on you"
    // and a mention must never carry it. The GUARANTEE is unchanged and still asserted —
    // a mention does not acquire the baton flag — but it is now met by carrying the
    // mention's OWN reason rather than by carrying no reason at all. Routing a mention
    // through the helper is no longer the defect; routing it as a baton still would be.
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-mention',
      from_agent_id: 'agent-x',
      content: 'hey sam rivera, take a look',
      requires_action: false,
    })
    NotificationConstructorSpy.mock.instances[0].onclick()

    expect(mockRouterPush.mock.calls[0][0].query.focus).not.toBe('baton')
    expect(mockRouterPush).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thread-1', focus: 'mention', message: 'msg-mention' },
    })
  })

  it('pins no message id, because the store cannot know which post handed the baton', async () => {
    // The store holds the thread, so passing the object to hubThreadRoute would compile
    // and look right — and it would pin a STALE post. `last_message` is refreshed only
    // by a thread-list read; an incoming message bumps last_activity_at and nothing
    // else. The tail fallback resolves the real one from the loaded timeline.
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-1', next_action_owner: 'user-001' })
    NotificationConstructorSpy.mock.instances[0].onclick()

    expect('message' in mockRouterPush.mock.calls[0][0].query).toBe(false)
  })

  // ── BE-9414: a mention written past the broker's excerpt cut-off ──

  it('still notifies when the mention is past the excerpt the event could carry', async () => {
    // A post over ~5.8 KB crosses the cross-worker broker as a bounded excerpt
    // (pg_notify caps a NOTIFY payload at 7999 bytes). Matching the operator's name
    // against that excerpt would silently drop the bell for anyone named later in a
    // long post -- they would never learn they had been asked. The store holds the
    // full body by the time this event is dispatched, so the check reads it there.
    mockIsHubPresent.value = false
    mockMessagesByThreadId.set('thread-long', [
      { message_id: 'msg-long', content: 'a very long post ... and finally, sam rivera, over to you' },
    ])
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-long',
      message_id: 'msg-long',
      from_agent_id: 'agent-x',
      content: 'a very long post ...', // the excerpt: the name is NOT in it
      content_truncated: true,
      content_length: 53,
      requires_action: false,
    })

    expect(mockShowToast).toHaveBeenCalledOnce()
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('does not invent a mention when neither the excerpt nor the stored body names you', async () => {
    mockIsHubPresent.value = false
    mockMessagesByThreadId.set('thread-long', [
      { message_id: 'msg-long', content: 'a very long post that names nobody in particular' },
    ])
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-long',
      message_id: 'msg-long',
      from_agent_id: 'agent-x',
      content: 'a very long post',
      content_truncated: true,
      content_length: 48,
      requires_action: false,
    })

    expect(mockShowToast).not.toHaveBeenCalled()
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
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

  it('does NOT drop a bell entry for a message that needs nothing from you', async () => {
    // MEANING CHANGED by FE-9436. This used to dispatch a MENTION and assert no row,
    // because only hand-offs persisted. Under the operator's ruling everything that needs
    // the user persists, so the mention case moved to its own test below and this one now
    // uses a genuinely ordinary post. The guarantee it defends is unchanged and is the
    // one that matters: a durable row is raised by the SIGNAL, never by mere traffic.
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'm1',
      from_agent_id: 'agent-x',
      content: 'running build step 3',
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

  // BE-9296a: name WHO is waiting, not just where.

  it('names the handing agent when the event carries one', async () => {
    mockIsHubPresent.value = false
    mockThreadsById.set('thread-1', { thread_id: 'thread-1', subject: 'Laptop interop' })
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'user-001',
      from_display_name: 'P1 Orchestrator',
      from_kind: 'agent',
    })

    const [title, opts] = NotificationConstructorSpy.mock.calls[0]
    expect(title).toBe("It's your call")
    // The agent is the part the operator could not already see.
    expect(opts.body).toBe('P1 Orchestrator is waiting on you in Laptop interop')
  })

  it('falls back to the thread-only wording when no hander is named', async () => {
    // A hand-off from an anonymous caller carries no name; the alert must not
    // render "undefined is waiting on you".
    mockIsHubPresent.value = false
    mockThreadsById.set('thread-1', { thread_id: 'thread-1', subject: 'Laptop interop' })
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-1', next_action_owner: 'user-001' })

    const [, opts] = NotificationConstructorSpy.mock.calls[0]
    expect(opts.body).toBe('Laptop interop — waiting on you')
    expect(opts.body).not.toContain('undefined')
  })

  it('carries the hander into the persistent bell entry, not just the toast', async () => {
    // The dropdown row is the durable record — it must say the same thing the
    // transient toast said, or the operator loses the name on navigation.
    mockIsHubPresent.value = true
    mockThreadsById.set('thread-5', { thread_id: 'thread-5', subject: 'Interop' })
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-5',
      next_action_owner: 'user-001',
      from_display_name: 'Lane 2',
    })

    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({ body: 'Lane 2 is waiting on you in Interop' }),
    )
  })

  it('deep-links the handover Notification click to the thread (works from a cold page)', async () => {
    // MEANING CHANGED by FE-9418. This used to assert the bare `{ thread }` query, and
    // that bare route was the defect rather than the contract: three other surfaces
    // raise a notification for the SAME hand-off and all three carried the baton
    // context, so a click here landed on the thread with nothing marked while a click
    // on the banner marked the post. The guarantee under test — a cold-page click lands
    // ON the thread — is unchanged and still asserted; only the route it travels moved,
    // and it now comes from the shared helper instead of a literal.
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

    expect(mockRouterPush).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thread-42', focus: 'baton' },
    })
  })

  // ── FE-9436: one announcer, three reasons, and never a raw id in the words ──

  it('routes a mention to its OWN post, which the event has always named', async () => {
    // The asymmetry this work order turns on. thread_message carries message_id and
    // thread_update does not, so a mention can pin the exact post while a hand-off still
    // resolves to the thread tail. The id was on the wire the whole time and the
    // hand-built route here was discarding it.
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-7',
      message_id: 'msg-named',
      from_agent_id: 'agent-x',
      content: 'sam rivera, thoughts?',
      requires_action: false,
    })
    NotificationConstructorSpy.mock.instances[0].onclick()

    expect(mockRouterPush).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thread-7', focus: 'mention', message: 'msg-named' },
    })
  })

  it('routes an approval to its own post, under the approval reason', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-8',
      message_id: 'msg-decide',
      from_agent_id: 'agent-x',
      content: 'ship it or hold?',
      requires_action: true,
    })
    NotificationConstructorSpy.mock.instances[0].onclick()

    expect(mockRouterPush).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thread-8', focus: 'approval', message: 'msg-decide' },
    })
  })

  it('leaves the HAND-OFF unpinned, because its event names no post', async () => {
    // The pre-FE-9436 route, unchanged. Pinning the store's `last_message` here would
    // compile and look right and would pin a STALE post — FE-9418's reasoning, which
    // survives the widening intact.
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-9', next_action_owner: 'user-001' })
    NotificationConstructorSpy.mock.instances[0].onclick()

    expect(mockRouterPush).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thread-9', focus: 'baton' },
    })
  })

  it('titles each reason for what it is, from one announcer', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 't-a', next_action_owner: 'user-001' })
    dispatchHubEvent('hub:thread_message', {
      thread_id: 't-b',
      message_id: 'm-b',
      from_agent_id: 'agent-x',
      content: 'sam rivera, look',
      requires_action: false,
    })
    dispatchHubEvent('hub:thread_message', {
      thread_id: 't-c',
      message_id: 'm-c',
      from_agent_id: 'agent-x',
      content: 'approve?',
      requires_action: true,
    })

    const titles = NotificationConstructorSpy.mock.calls.map(([title]) => title)
    expect(titles).toEqual(["It's your call", 'You were mentioned', 'Needs your approval'])
  })

  it('never puts a raw thread id in the words, on any surface', async () => {
    // The store has NOT hydrated this thread — which is the cold-page/away case the
    // browser notification exists for, so it is the common case here rather than an
    // edge one. The old fallback rendered `thread <uuid>` into the toast, the browser
    // notification AND the durable bell row, all from this one string.
    mockIsHubPresent.value = false
    const THREAD_UUID = '9f8e7d6c-5b4a-4321-9876-0abcdef12345'
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: THREAD_UUID,
      chat_id: 'CHT-0493',
      next_action_owner: 'user-001',
      from_display_name: 'Lane 7',
    })

    const [, opts] = NotificationConstructorSpy.mock.calls[0]
    const toastArg = mockShowToast.mock.calls[0][0]
    const bellRow = mockAddNotification.mock.calls[0][0]
    for (const words of [opts.body, toastArg.message, bellRow.body]) {
      expect(words).not.toContain(THREAD_UUID)
    }
    // And it says something USEFUL instead: the serial the operator actually quotes.
    expect(opts.body).toBe('Lane 7 is waiting on you in CHT-0493')
  })

  it('prefers the thread NAME over its serial when the store knows one', async () => {
    mockIsHubPresent.value = false
    mockThreadsById.set('thr-named', { thread_id: 'thr-named', subject: 'Laptop interop' })
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thr-named',
      chat_id: 'CHT-0001',
      next_action_owner: 'user-001',
    })

    expect(NotificationConstructorSpy.mock.calls[0][1].body).toBe('Laptop interop — waiting on you')
  })

  it('falls back to plain words when neither a name nor a serial is available', async () => {
    // Never "thread undefined", and never the id. This matches SystemStatusBanner's
    // wording, which the two surfaces are deliberately kept identical on.
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thr-unknown',
      next_action_owner: 'user-001',
    })

    const body = NotificationConstructorSpy.mock.calls[0][1].body
    expect(body).toBe('a thread — waiting on you')
    expect(body).not.toContain('thr-unknown')
    expect(body).not.toContain('undefined')
  })

  // ── FE-9436: a mention that vanishes when the toast fades is not harmonized ──

  it('drops a durable bell row for a mention, keyed on the POST not the thread', async () => {
    // Keyed on the message on purpose, unlike the hand-off. A second hand-off in a thread
    // is the same standing obligation — answer it — so it dedupes to one row. A second
    // mention is a second thing someone asked you, and collapsing them loses one.
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-3',
      message_id: 'msg-m1',
      from_agent_id: 'agent-x',
      content: 'sam rivera, can you look',
      requires_action: false,
    })

    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'mention:msg-m1',
        type: 'hub.mention',
        title: 'You were mentioned',
        metadata: { thread_id: 'thread-3', message_id: 'msg-m1' },
      }),
    )
  })

  it('drops a durable bell row for an approval, carrying its own post', async () => {
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-4',
      message_id: 'msg-a1',
      from_agent_id: 'agent-x',
      content: 'approve the rollout?',
      requires_action: true,
    })

    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'approval:msg-a1',
        type: 'hub.approval',
        title: 'Needs your approval',
        metadata: { thread_id: 'thread-4', message_id: 'msg-a1' },
      }),
    )
  })

  it('records the mention row even when the operator IS in the Hub', async () => {
    // Same rule the hand-off already followed: the dropdown is the DURABLE record
    // regardless of presence, while the interruptive channels stay gated on being away.
    mockIsHubPresent.value = true
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-3',
      message_id: 'msg-m2',
      from_agent_id: 'agent-x',
      content: 'sam rivera?',
      requires_action: false,
    })

    expect(mockAddNotification).toHaveBeenCalledOnce()
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('keeps the hand-off row on its own thread-keyed id, unchanged', async () => {
    // The bare `handover` type and the thread-keyed id are pre-FE-9436 and stay: rows
    // already sitting in a browser's localStorage would be orphaned by a rename.
    mockIsHubPresent.value = false
    const { useHubNotifications } = await import('./useHubNotifications')
    useHubNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-2', next_action_owner: 'user-001' })

    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'handover:thread-2', type: 'handover' }),
    )
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
