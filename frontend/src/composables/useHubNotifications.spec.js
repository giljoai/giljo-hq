/**
 * useHubNotifications.spec.js — FE-6054f
 * Tests for the gated, no-spam alerting composable.
 *
 * Gate rules (as of FE-9586):
 * - thread_update: next_action_owner === currentUser.id → notify if AWAY
 * - thread_message: requires_action === true AND to_participant === currentUser.id
 *   (a DIRECTED ask) → notify if AWAY. A BROADCAST requires_action post signals
 *   NOTHING: BE-9197 rules it "whoever picks it up", obligating nobody in particular.
 * - MENTIONS come from the server's projection (useThreadPostAttention), not from the
 *   event. The client no longer inspects post CONTENT at all — it could not see all
 *   of it, so a mention past the broker's excerpt cut-off was invisible to the reader
 *   it named. Identity comparisons stay client-side; interpretation moved.
 * - OWN posts (from_agent_id === currentUser.id) → NEVER notify
 * - Popouts are gated on document.hidden (FE-9553 ruling 4a), not Hub presence.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { effectScope, nextTick, ref } from 'vue'

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

// FE-9586: mentions are projected from the server, so the spec drives the projection
// rather than an event body. `mentions` is null until loaded, exactly as the real
// composable is -- an empty array would let a test pass that the cold-load guard should
// catch.
const mockMentions = ref(null)
vi.mock('./useThreadPostAttention', () => ({
  useThreadPostAttention: () => ({
    mentions: mockMentions,
    directedAsks: ref(null),
    loaded: ref(mockMentions.value !== null),
    ensureLoaded: vi.fn(() => Promise.resolve()),
    refresh: vi.fn(() => Promise.resolve()),
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

/**
 * Start the composable inside a DISPOSABLE scope.
 *
 * FE-9586 needed this and it fixes a leak that predates it. The composable registers
 * its window listeners with `onScopeDispose`, which only runs `if (getCurrentScope())`
 * -- and calling it bare from a spec provides no scope, so nothing was ever torn down.
 * Every test's listeners stayed live for the rest of the file. That was invisible while
 * each test drove a fresh EVENT (the accumulated listeners fired on a payload the
 * earlier assertions no longer looked at), and became visible the moment a test drove
 * shared reactive STATE instead: seven surviving watchers each announced the same
 * mention, and the count assertion read 7.
 *
 * So each instance now lives in its own scope and is stopped after the test.
 */
let notificationsScope = null

async function startNotifications() {
  const { useHubNotifications } = await import('./useHubNotifications')
  notificationsScope?.stop()
  notificationsScope = effectScope()
  notificationsScope.run(() => useHubNotifications())
}

/**
 * The server says these posts name you.
 *
 * Replaces "dispatch an event whose content contains my name" everywhere below. It is
 * a await-able state change rather than an event because that is what the projection
 * is -- the event is only a hint to re-ask.
 */
async function projectMentions(entries) {
  mockMentions.value = entries
  await nextTick()
}

/**
 * FE-9553: what "AWAY" means changed, so this harness has to say it.
 *
 * Every away-case below was written against the pre-FE-9553 gate, where away
 * meant `isHubPresent === false` -- not standing in the Hub pane. Ruling 4(a)
 * moved the popout gate to Page Visibility: a popout fires only when the app
 * is HIDDEN, because the old gate fired an OS notification at a window the
 * operator was already looking at on every page except the Hub.
 *
 * jsdom reports document.hidden as false (visible) by default, so without this
 * the whole away half of the file would be asserting against a visible tab and
 * expecting popouts the ruling now forbids. The tests' INTENT is unchanged --
 * "the operator is away, so reach them" -- only the definition of away is.
 *
 * Redefined per test rather than once, and configurable, so a later
 * redefinition cannot be silently swallowed.
 */
function setHidden(hidden) {
  Object.defineProperty(document, 'hidden', {
    configurable: true,
    get: () => hidden,
  })
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
    // FE-9553: hidden is the new "away" for popout purposes -- see setHidden.
    setHidden(true)
    mockThreadsById.clear()
    mockMessagesByThreadId.clear()
    mockAddNotification.mockClear()
    // FE-9586: the projection is module-scoped, like the real one. Back to null (NOT
    // []) between tests, so a test that never mentions mentions cannot inherit the
    // previous one's -- and so the unloaded state is what a fresh mount sees.
    mockMentions.value = null
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
    notificationsScope?.stop()
    notificationsScope = null
  })

  afterEach(() => {
    // FE-9553: hand the visibility stub back, so a spec that runs after this
    // file in the same worker sees a normal visible document.
    setHidden(false)
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
    // FE-9553: being present now means present AND looking -- a visible tab.
    // Presence alone no longer suppresses a popout, because a HIDDEN tab whose
    // last route was the Hub is not somewhere the operator can see anything.
    setHidden(false)
    await startNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'user-001',
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('does NOT fire Notification when present and message requires_action', async () => {
    mockIsHubPresent.value = true
    setHidden(false) // FE-9553: present means present AND visible.
    await startNotifications()

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

  // FE-9553: the toast assertion here inverted deliberately. This test pinned
  // the pre-FE-9553 contract, where an away baton fired a toast AND a popout;
  // ruling 6 puts toasts on user-initiated actions only, and ruling 3 puts a
  // baton on the banner. The popout and the bell row are unchanged, so the
  // test still asserts the operator is reached -- just not twice.
  it('fires Notification but NOT a toast when AWAY and baton handed to currentUser', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'user-001',
    })

    expect(mockShowToast).not.toHaveBeenCalled()
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
    await startNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'user-001',
    })

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
    const [, options] = NotificationConstructorSpy.mock.calls[0]
    expect(options.icon).toBe('/icons/Giljo_Face_Avatar.png')
    expect(options.icon).not.toContain('Giljo_YW.svg')
  })

  it('fires a Notification when AWAY and a DIRECTED requires_action post names the operator', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-2',
      from_agent_id: 'agent-x',
      content: 'please review',
      requires_action: true,
      // FE-9586: the recipient field is now REQUIRED for this to signal. An id
      // comparison is a question the client can answer exactly, which is why it stays
      // client-side while content interpretation moved to the server.
      to_participant: 'user-001',
    })

    // FE-9553: no toast for an agent-initiated actionable signal.
    expect(mockShowToast).not.toHaveBeenCalled()
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('A BROADCAST requires_action post is QUIET, not SILENT: bell row, no popout', async () => {
    // FE-9586b, and this is a REGRESSION FIX rather than a change of mind.
    //
    // FE-9586 aligned the client to BE-9197 -- a broadcast requires_action post is
    // "whoever picks it up" and obligates nobody in particular, so it must not raise
    // an actionable banner or popout. Both the docblock and the PR body said, in
    // those words, that "the post keeps its durable bell row". It did not: the bell
    // row is written AFTER the signal gate, so returning null from the gate skipped
    // the bell as well and the post vanished from every surface at once. Documented
    // intent and shipped behaviour disagreed, and the operator noticed by losing
    // track of asks his agents were broadcasting.
    //
    // The bell is the durable archive (ruling 1: a missed informational event goes
    // to the bell), so this is what "quiet" has to mean: recorded, not interruptive.
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-broadcast',
      from_agent_id: 'agent-x',
      content: 'somebody should handle the deploy',
      requires_action: true,
      // no to_participant: a broadcast
    })

    // The durable record survives...
    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'approval:msg-broadcast',
        type: 'hub.approval',
        metadata: { thread_id: 'thread-1', message_id: 'msg-broadcast' },
      }),
    )
    // ...and nothing interrupts, even though the tab is hidden, which is the case
    // that would otherwise pop.
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('titles a broadcast ask for what it is, not as something the operator owes', async () => {
    // The bell list is the one place a broadcast ask and a directed ask sit side by
    // side, and "Needs your approval" on a post nobody in particular owes is the same
    // false claim FE-9586 removed from the banner. WORDING FLAGGED for the operator's
    // walkthrough -- it is a one-line change if he wants different copy.
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-broadcast',
      from_agent_id: 'agent-x',
      content: 'somebody should handle the deploy',
      requires_action: true,
    })

    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Open ask from an agent' }),
    )
  })

  it('THE CONTRAST: a broadcast gets a bell row, an ask aimed at another agent gets nothing', async () => {
    // The three cases in one test, because collapsing any two of them has already
    // caused a defect in both directions. FE-9586 collapsed broadcast into "nothing"
    // and lost the ask entirely. My first FE-9586b attempt collapsed
    // directed-elsewhere into "quiet" and would have put a bell row in front of the
    // operator for every directive an orchestrator sent a lane agent -- the exact spam
    // FE-9546 removed, moved from the popout to the bell. The pre-existing FE-9546
    // test caught it; this pins the distinction where it is readable.
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-broadcast',
      message_id: 'msg-b',
      from_agent_id: 'orchestrator',
      content: 'somebody should handle the deploy',
      requires_action: true,
    })
    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-elsewhere',
      message_id: 'msg-e',
      from_agent_id: 'orchestrator',
      content: 'CI2, take this one',
      requires_action: true,
      to_participant: 'CI2',
    })

    const bellIds = mockAddNotification.mock.calls.map(([row]) => row.id)
    expect(bellIds).toContain('approval:msg-b')
    expect(bellIds).not.toContain('approval:msg-e')
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('a DIRECTED ask still gets the full attention treatment -- the two must not converge', async () => {
    // The negative control for the change above: if "quiet" leaked onto the directed
    // path, this suite would still be green on the broadcast test while the signal
    // the operator actually owes an answer to had gone silent.
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-2',
      message_id: 'msg-directed',
      from_agent_id: 'agent-x',
      content: 'please decide',
      requires_action: true,
      to_participant: 'user-001',
    })

    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Needs your approval' }),
    )
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('fires a Notification but NOT a toast when AWAY and the server reports a mention', async () => {
    // FE-9586: no content in this test at all. The old version put the operator's name
    // in the event body and relied on a substring match; the client no longer looks.
    mockIsHubPresent.value = false
    await startNotifications()

    await projectMentions([{ thread_id: 'thread-1', chat_id: 'CHT-0001', message_ids: ['msg-3'] }])

    // FE-9553: a mention is actionable and agent-initiated -- banner + bell + popout, no toast.
    expect(mockShowToast).not.toHaveBeenCalled()
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('does not announce the same mention twice when the projection is re-read', async () => {
    // The projection is re-read on every thread event, so it reports the same unread
    // mention again and again until the operator reads the thread. Announcing per READ
    // rather than per POST would re-pop the same mention on every unrelated message in
    // the tenant.
    mockIsHubPresent.value = false
    await startNotifications()

    await projectMentions([{ thread_id: 'thread-1', message_ids: ['msg-3'] }])
    await projectMentions([{ thread_id: 'thread-1', message_ids: ['msg-3'] }])

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('announces a SECOND mention on the same thread -- it is a second thing asked', async () => {
    // The BELL_ROWS keyOnPost precedent: a second baton is the same standing
    // obligation, a second mention is not. Tracking announcements per THREAD would
    // swallow the second one.
    mockIsHubPresent.value = false
    await startNotifications()

    await projectMentions([{ thread_id: 'thread-1', message_ids: ['msg-3'] }])
    await projectMentions([{ thread_id: 'thread-1', message_ids: ['msg-4', 'msg-3'] }])

    const bellIds = mockAddNotification.mock.calls.map(([row]) => row.id)
    expect(bellIds).toContain('mention:msg-3')
    expect(bellIds).toContain('mention:msg-4')
  })

  // ── FE-9418: the browser notification's click travels the shared route ──

  it('sends a HANDOVER click through hubThreadRoute, so all four surfaces land alike', async () => {
    // The banner, the Hub's attention strip and both bell rows already route through
    // the helper. This was the fourth notification raised by the same hand-off and the
    // only one still hand-building its route, so it arrived without the baton context
    // and marked nothing.
    mockIsHubPresent.value = false
    await startNotifications()

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
    await startNotifications()

    await projectMentions([{ thread_id: 'thread-1', message_ids: ['msg-mention'] }])
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
    await startNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-1', next_action_owner: 'user-001' })
    NotificationConstructorSpy.mock.instances[0].onclick()

    expect('message' in mockRouterPush.mock.calls[0][0].query).toBe(false)
  })

  // ── BE-9414: a mention written past the broker's excerpt cut-off ──

  it('does not inspect post CONTENT at all -- a name in the body raises nothing by itself', async () => {
    // MEANING INVERTED BY FE-9586, deliberately. This test used to assert that a
    // mention past the broker's ~5.8 KB excerpt cut-off still notified, via a
    // store-hydration fallback -- and that fallback's own docblock conceded it read the
    // excerpt whenever the hydrating read had failed, which is the case it most needed
    // to cover. The client no longer decides what a mention is, so the honest assertion
    // is that a name in an event body does nothing on its own. The guarantee the old
    // test wanted is now enforced server-side, where the content column is simply
    // readable: see tests/repositories/test_comm_thread_unread_mentions_mixin.py, which
    // pins a 9,000-character body with the name at the end.
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-long',
      message_id: 'msg-long',
      from_agent_id: 'agent-x',
      content: 'and finally, sam rivera, over to you',
      requires_action: false,
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockAddNotification).not.toHaveBeenCalled()
  })

  it('does not invent a mention when neither the excerpt nor the stored body names you', async () => {
    mockIsHubPresent.value = false
    mockMessagesByThreadId.set('thread-long', [
      { message_id: 'msg-long', content: 'a very long post that names nobody in particular' },
    ])
    await startNotifications()

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
    await startNotifications()

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

  // ── FE-9546: a requires_action post directed at ANOTHER agent is not the
  // operator's business, no matter the flag. Only BATON_FOCUS (thread_update,
  // separately gated on next_action_owner) and a requires_action post actually
  // addressed to the operator (to_participant matches, or a broadcast with no
  // specific addressee — "all recipients must act") are the operator's approval
  // signal. Decision, stated: an agent-to-agent directed post drops NO bell row
  // either — it was never addressed to the operator, so there is nothing to
  // archive for them, matching how any other not-my-business event is treated. ──

  it('FE-9546: does NOT notify when requires_action post is directed at another agent', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-6',
      from_agent_id: 'orchestrator',
      content: 'please pick this up',
      requires_action: true,
      to_participant: 'CI2', // directed at a lane agent, not the operator
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
    expect(mockAddNotification).not.toHaveBeenCalled()
  })

  it('FE-9546: still notifies + drops a bell row when the requires_action post is directed at the operator', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-7',
      from_agent_id: 'orchestrator',
      content: 'need your sign-off',
      requires_action: true,
      to_participant: 'user-001', // the operator's own id
    })

    // FE-9553: the FE-9546 recipient filter is unchanged; only the toast goes.
    expect(mockShowToast).not.toHaveBeenCalled()
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
    expect(mockAddNotification).toHaveBeenCalledOnce()
    // Title stays exactly what it was — this project changes the filter, not the copy.
    const [title] = NotificationConstructorSpy.mock.calls[0]
    expect(title).toBe('Needs your approval')
  })

  // ── Non-user-invoked → never notify ──

  it('does NOT notify for a plain broadcast with no requires_action and no mention', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

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
    await startNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'agent-xyz', // not the current user
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  // ── Notification.permission denied → no popout; the bell row still lands ──
  //
  // FE-9553 rewrote this test rather than inverting it. It used to assert that
  // a denied permission still reached the operator VIA THE TOAST, and with the
  // toast gone that reading would leave two bare negatives asserting nothing.
  // The claim worth pinning is the one ruling 4(b) makes: a popout is
  // best-effort and never the only carrier, so with permission denied the
  // durable bell row must still be written. That is what actually protects the
  // operator here, and it is now what fails if someone breaks it.

  it('writes the bell row but fires no popout and no toast when permission is denied', async () => {
    resetNotificationMock('denied')
    mockIsHubPresent.value = false

    await startNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: 'thread-1',
      next_action_owner: 'user-001',
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
    // The carrier that survives a denied permission.
    expect(mockAddNotification).toHaveBeenCalledOnce()
  })

  // ── FE-9289c: persistent bell entry (survives navigation) ──

  it('drops a persistent handover entry on baton, deduped by a stable per-thread id', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-9', next_action_owner: 'user-001' })

    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'handover:thread-9', type: 'handover', metadata: { thread_id: 'thread-9' } }),
    )
  })

  it('records the persistent entry even when the operator IS in the Hub (durable record)', async () => {
    mockIsHubPresent.value = true
    setHidden(false) // FE-9553: present means present AND visible.
    await startNotifications()

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
    await startNotifications()

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
    await startNotifications()

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
    await startNotifications()

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
    await startNotifications()

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
    await startNotifications()

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
    await startNotifications()

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
    await startNotifications()

    // FE-9586: the post id now comes from the PROJECTION rather than the event, which
    // is why the projection returns message ids at all. A thread-only verdict would
    // have left this deep-link pointing at the thread tail again.
    await projectMentions([{ thread_id: 'thread-7', message_ids: ['msg-named'] }])
    NotificationConstructorSpy.mock.instances[0].onclick()

    expect(mockRouterPush).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thread-7', focus: 'mention', message: 'msg-named' },
    })
  })

  it('routes an approval to its own post, under the approval reason', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-8',
      message_id: 'msg-decide',
      from_agent_id: 'agent-x',
      content: 'ship it or hold?',
      requires_action: true,
      to_participant: 'user-001', // FE-9586: directed, or it signals nothing
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
    await startNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-9', next_action_owner: 'user-001' })
    NotificationConstructorSpy.mock.instances[0].onclick()

    expect(mockRouterPush).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thread-9', focus: 'baton' },
    })
  })

  it('titles each reason for what it is, from one announcer', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 't-a', next_action_owner: 'user-001' })
    await projectMentions([{ thread_id: 't-b', message_ids: ['m-b'] }])
    dispatchHubEvent('hub:thread_message', {
      thread_id: 't-c',
      message_id: 'm-c',
      from_agent_id: 'agent-x',
      content: 'approve?',
      requires_action: true,
      to_participant: 'user-001',
    })

    const titles = NotificationConstructorSpy.mock.calls.map(([title]) => title)
    expect(titles).toEqual(["It's your call", 'You were mentioned', 'Needs your approval'])
  })

  it('never puts a raw thread id in the words, on any surface', async () => {
    // The store has NOT hydrated this thread — which is the cold-page/away case the
    // browser notification exists for, so it is the common case here rather than an
    // edge one. The old fallback rendered `thread <uuid>` into the toast, the browser
    // notification AND the durable bell row, all from this one string.
    //
    // FE-9553: the toast is no longer one of those surfaces, so it is no longer
    // one of the strings checked. The remaining two are the popout body and the
    // bell row body — still both fed from the one shared string, so the claim
    // this test makes is unchanged.
    mockIsHubPresent.value = false
    const THREAD_UUID = '9f8e7d6c-5b4a-4321-9876-0abcdef12345'
    await startNotifications()

    dispatchHubEvent('hub:thread_update', {
      thread_id: THREAD_UUID,
      chat_id: 'CHT-0493',
      next_action_owner: 'user-001',
      from_display_name: 'Lane 7',
    })

    const [, opts] = NotificationConstructorSpy.mock.calls[0]
    const bellRow = mockAddNotification.mock.calls[0][0]
    for (const words of [opts.body, bellRow.body]) {
      expect(words).not.toContain(THREAD_UUID)
    }
    // And it says something USEFUL instead: the serial the operator actually quotes.
    expect(opts.body).toBe('Lane 7 is waiting on you in CHT-0493')
  })

  it('prefers the thread NAME over its serial when the store knows one', async () => {
    mockIsHubPresent.value = false
    mockThreadsById.set('thr-named', { thread_id: 'thr-named', subject: 'Laptop interop' })
    await startNotifications()

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
    await startNotifications()

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
    await startNotifications()

    await projectMentions([{ thread_id: 'thread-3', message_ids: ['msg-m1'] }])

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
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-4',
      message_id: 'msg-a1',
      from_agent_id: 'agent-x',
      content: 'approve the rollout?',
      requires_action: true,
      to_participant: 'user-001',
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
    setHidden(false) // FE-9553: present means present AND visible.
    await startNotifications()

    await projectMentions([{ thread_id: 'thread-3', message_ids: ['msg-m2'] }])

    expect(mockAddNotification).toHaveBeenCalledOnce()
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('keeps the hand-off row on its own thread-keyed id, unchanged', async () => {
    // The bare `handover` type and the thread-keyed id are pre-FE-9436 and stay: rows
    // already sitting in a browser's localStorage would be orphaned by a rename.
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-2', next_action_owner: 'user-001' })

    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'handover:thread-2', type: 'handover' }),
    )
  })

  // ── De-dup: same signal key does not fire twice ──

  it('de-dupes: same baton event on same thread does not fire twice', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    const payload = { thread_id: 'thread-1', next_action_owner: 'user-001' }
    dispatchHubEvent('hub:thread_update', payload)
    dispatchHubEvent('hub:thread_update', payload)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })
})
