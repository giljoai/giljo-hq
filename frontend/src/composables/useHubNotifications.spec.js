import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { effectScope, nextTick, ref } from 'vue'


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

let notificationsScope = null

async function startNotifications() {
  const { useHubNotifications } = await import('./useHubNotifications')
  notificationsScope?.stop()
  notificationsScope = effectScope()
  notificationsScope.run(() => useHubNotifications())
}

async function projectMentions(entries) {
  mockMentions.value = entries
  await nextTick()
}

function setHidden(hidden) {
  Object.defineProperty(document, 'hidden', {
    configurable: true,
    get: () => hidden,
  })
}

describe('useHubNotifications', () => {
  const activeListeners = []
  const _origAddEventListener = window.addEventListener.bind(window)
  const _origRemoveEventListener = window.removeEventListener.bind(window)

  beforeEach(async () => {
    setActivePinia(createPinia())
    vi.resetModules()
    vi.clearAllMocks()
    resetNotificationMock('granted')
    mockIsHubPresent.value = false
    setHidden(true)
    mockThreadsById.clear()
    mockMessagesByThreadId.clear()
    mockAddNotification.mockClear()
    mockMentions.value = null
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
    notificationsScope?.stop()
    notificationsScope = null
  })

  afterEach(() => {
    setHidden(false)
    for (const { type, handler } of activeListeners) {
      _origRemoveEventListener(type, handler)
    }
    activeListeners.length = 0
    vi.restoreAllMocks()
    delete global.Notification
  })


  it('does NOT fire Notification when user is present and baton handed to them', async () => {
    mockIsHubPresent.value = true
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
    setHidden(false)
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
      to_participant: 'user-001',
    })

    expect(mockShowToast).not.toHaveBeenCalled()
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('A BROADCAST requires_action post is QUIET, not SILENT: bell row, no popout', async () => {
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
      expect.objectContaining({
        id: 'approval:msg-broadcast',
        type: 'hub.approval',
        metadata: { thread_id: 'thread-1', message_id: 'msg-broadcast' },
      }),
    )
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('titles a broadcast ask for what it is, not as something the operator owes', async () => {
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
    mockIsHubPresent.value = false
    await startNotifications()

    await projectMentions([{ thread_id: 'thread-1', chat_id: 'CHT-0001', message_ids: ['msg-3'] }])

    expect(mockShowToast).not.toHaveBeenCalled()
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('does not announce the same mention twice when the projection is re-read', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    await projectMentions([{ thread_id: 'thread-1', message_ids: ['msg-3'] }])
    await projectMentions([{ thread_id: 'thread-1', message_ids: ['msg-3'] }])

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('announces a SECOND mention on the same thread -- it is a second thing asked', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    await projectMentions([{ thread_id: 'thread-1', message_ids: ['msg-3'] }])
    await projectMentions([{ thread_id: 'thread-1', message_ids: ['msg-4', 'msg-3'] }])

    const bellIds = mockAddNotification.mock.calls.map(([row]) => row.id)
    expect(bellIds).toContain('mention:msg-3')
    expect(bellIds).toContain('mention:msg-4')
  })


  it('sends a HANDOVER click through hubThreadRoute, so all four surfaces land alike', async () => {
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
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-1', next_action_owner: 'user-001' })
    NotificationConstructorSpy.mock.instances[0].onclick()

    expect('message' in mockRouterPush.mock.calls[0][0].query).toBe(false)
  })


  it('does not inspect post CONTENT at all -- a name in the body raises nothing by itself', async () => {
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


  it('does NOT notify for own posts (from_agent_id === currentUser.id)', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-4',
      from_agent_id: 'user-001',
      content: 'hello there',
      requires_action: true,
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })


  it('FE-9546: does NOT notify when requires_action post is directed at another agent', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_message', {
      thread_id: 'thread-1',
      message_id: 'msg-6',
      from_agent_id: 'orchestrator',
      content: 'please pick this up',
      requires_action: true,
      to_participant: 'CI2',
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
      to_participant: 'user-001',
    })

    expect(mockShowToast).not.toHaveBeenCalled()
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
    expect(mockAddNotification).toHaveBeenCalledOnce()
    const [title] = NotificationConstructorSpy.mock.calls[0]
    expect(title).toBe('Needs your approval')
  })


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
      next_action_owner: 'agent-xyz',
    })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })


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
    expect(mockAddNotification).toHaveBeenCalledOnce()
  })


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
    setHidden(false)
    await startNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-9', next_action_owner: 'user-001' })

    expect(mockAddNotification).toHaveBeenCalledOnce()
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('does NOT drop a bell entry for a message that needs nothing from you', async () => {
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
    expect(opts.body).toBe('P1 Orchestrator is waiting on you in Laptop interop')
  })

  it('falls back to the thread-only wording when no hander is named', async () => {
    mockIsHubPresent.value = false
    mockThreadsById.set('thread-1', { thread_id: 'thread-1', subject: 'Laptop interop' })
    await startNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-1', next_action_owner: 'user-001' })

    const [, opts] = NotificationConstructorSpy.mock.calls[0]
    expect(opts.body).toBe('Laptop interop — waiting on you')
    expect(opts.body).not.toContain('undefined')
  })

  it('carries the hander into the persistent bell entry, not just the toast', async () => {
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
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-42', next_action_owner: 'user-001' })

    const instance = NotificationConstructorSpy.mock.results[0]?.value ?? {}
    const onclick = NotificationConstructorSpy.mock.instances[0]?.onclick || instance.onclick
    expect(typeof onclick).toBe('function')
    onclick()

    expect(mockRouterPush).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thread-42', focus: 'baton' },
    })
  })


  it('routes a mention to its OWN post, which the event has always named', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

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
      to_participant: 'user-001',
    })
    NotificationConstructorSpy.mock.instances[0].onclick()

    expect(mockRouterPush).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thread-8', focus: 'approval', message: 'msg-decide' },
    })
  })

  it('leaves the HAND-OFF unpinned, because its event names no post', async () => {
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


  it('drops a durable bell row for a mention, keyed on the POST not the thread', async () => {
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
    mockIsHubPresent.value = true
    setHidden(false)
    await startNotifications()

    await projectMentions([{ thread_id: 'thread-3', message_ids: ['msg-m2'] }])

    expect(mockAddNotification).toHaveBeenCalledOnce()
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('keeps the hand-off row on its own thread-keyed id, unchanged', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    dispatchHubEvent('hub:thread_update', { thread_id: 'thread-2', next_action_owner: 'user-001' })

    expect(mockAddNotification).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'handover:thread-2', type: 'handover' }),
    )
  })


  it('de-dupes: same baton event on same thread does not fire twice', async () => {
    mockIsHubPresent.value = false
    await startNotifications()

    const payload = { thread_id: 'thread-1', next_action_owner: 'user-001' }
    dispatchHubEvent('hub:thread_update', payload)
    dispatchHubEvent('hub:thread_update', payload)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })
})
