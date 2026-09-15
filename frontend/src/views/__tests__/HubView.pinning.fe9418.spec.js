import { describe, it, expect, beforeEach, vi } from 'vitest'
import { reactive, nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'

const h = vi.hoisted(() => ({ push: vi.fn(), route: null }))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push }),
  useRoute: () => h.route,
}))
vi.mock('@/stores/websocketEventRouter', () => ({ registerReconnectResync: () => () => {} }))

import HubView from '@/views/HubView.vue'
import api from '@/services/api'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'

const ME = 'user-op-1'
const THREAD_ID = 'thr-9'
const OLD_MESSAGE = 'msg-old'
const BATON_MESSAGE = 'msg-baton'
const NEWER_MESSAGE = 'msg-newer'

const childStubs = {
  ThreadList: { template: '<div class="stub-thread-list" />' },
  ThreadTimeline: {
    props: ['search', 'focusMessageId'],
    template: '<div class="stub-timeline" :data-focus="focusMessageId" />',
  },
  HubComposer: { template: '<div class="stub-composer" />' },
  AgentPill: { template: '<span class="stub-pill" />' },
  NewThreadDialog: { template: '<div />' },
  ThreadCreatedDialog: { template: '<div />' },
  ThreadDeletedDialog: { template: '<div />' },
  DeletedCountButton: { props: ['count', 'entity'], template: '<button class="stub-deleted" />' },
}

function batonThread(overrides = {}) {
  return {
    thread_id: THREAD_ID,
    chat_id: 'CHT-0009',
    subject: 'Baton thread',
    status: 'open',
    project_id: null,
    next_action_owner: ME,
    last_message: {
      id: BATON_MESSAGE,
      author: 'L25',
      excerpt: 'over to you',
      created_at: '2026-08-13T05:00:00Z',
    },
    ...overrides,
  }
}

function seedHistory(thread) {
  api.threads.history.mockResolvedValue({
    data: {
      thread,
      messages: [
        { message_id: OLD_MESSAGE, thread_id: THREAD_ID, content: 'earlier chatter' },
        { message_id: BATON_MESSAGE, thread_id: THREAD_ID, content: 'over to you' },
        { message_id: NEWER_MESSAGE, thread_id: THREAD_ID, content: 'and one more thing' },
      ],
    },
  })
}

async function mountHub({ query = {}, seed = null } = {}) {
  h.route = reactive({ query: { ...query } })
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useCommHubStore()
  if (seed) {
    store._testSeedThread(seed)
    seedHistory(seed)
  }
  useUserStore().currentUser = { id: ME, role: 'admin' }
  const wrapper = mount(HubView, { global: { plugins: [pinia], stubs: childStubs } })
  await flushPromises()
  await nextTick()
  return { wrapper, store }
}

const focusOf = (wrapper) => wrapper.find('.stub-timeline').attributes('data-focus')

describe('HubView exact-message pinning (FE-9418)', () => {
  beforeEach(() => {
    h.push.mockClear()
  })

  it('pins the message the notification NAMED, not the newest one', async () => {
    const { wrapper } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton', message: BATON_MESSAGE },
      seed: batonThread(),
    })
    expect(focusOf(wrapper)).toBe(BATON_MESSAGE)
    expect(focusOf(wrapper)).not.toBe(NEWER_MESSAGE)
  })

  it('falls back to the thread tail when the arrival names no message', async () => {
    const { wrapper } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton' },
      seed: batonThread(),
    })
    expect(focusOf(wrapper)).toBe(NEWER_MESSAGE)
  })

  it('falls back to the tail when the named message is not in the loaded timeline', async () => {
    const { wrapper } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton', message: 'msg-not-here' },
      seed: batonThread(),
    })
    expect(focusOf(wrapper)).toBe(NEWER_MESSAGE)
  })

  it('marks nothing on an ordinary arrival even when a message is named', async () => {
    const { wrapper } = await mountHub({
      query: { thread: THREAD_ID, message: BATON_MESSAGE },
      seed: batonThread(),
    })
    expect(wrapper.find('.stub-timeline').exists()).toBe(true)
    expect(focusOf(wrapper)).toBeUndefined()
  })

  it('still stops marking once the operator moves on to another thread', async () => {
    const { wrapper, store } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton', message: BATON_MESSAGE },
      seed: batonThread(),
    })
    expect(focusOf(wrapper)).toBe(BATON_MESSAGE)

    store._testSeedThread(batonThread({ thread_id: 'thr-other', subject: 'Unrelated' }))
    store.handleThreadMessage({
      thread_id: 'thr-other',
      message_id: 'msg-unrelated',
      from_agent_id: 'L25',
      from_kind: 'agent',
      content: 'nothing to do with the baton',
      created_at: '2026-08-13T05:10:00Z',
    })
    store.selectThread('thr-other')
    await flushPromises()

    expect(focusOf(wrapper)).toBeUndefined()
  })

  it('sends the attention-strip click with the anchor the thread carries', async () => {
    const { wrapper } = await mountHub({ query: { tab: 'town' }, seed: batonThread() })
    await wrapper.find('[data-testid="hub-attention-strip"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: THREAD_ID, focus: 'baton', message: BATON_MESSAGE },
    })
  })
})

describe('HubView -> ThreadTimeline, end to end (FE-9418)', () => {
  beforeEach(() => {
    h.push.mockClear()
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('renders "Waiting on you" on the NAMED post, not on the newest one', async () => {
    h.route = reactive({ query: { thread: THREAD_ID, focus: 'baton', message: BATON_MESSAGE } })
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useCommHubStore()
    store._testSeedThread(batonThread())
    seedHistory(batonThread())
    useUserStore().currentUser = { id: ME, role: 'admin' }

    const wrapper = mount(HubView, {
      global: {
        plugins: [pinia, createVuetify()],
        stubs: { ...childStubs, ThreadTimeline: false },
      },
    })
    await flushPromises()
    await nextTick()

    const named = wrapper.find(`[data-testid="timeline-message-${BATON_MESSAGE}"]`)
    const newest = wrapper.find(`[data-testid="timeline-message-${NEWER_MESSAGE}"]`)
    expect(named.exists()).toBe(true)
    expect(newest.exists()).toBe(true)

    expect(named.find('[data-testid="hub-focus-baton"]').exists()).toBe(true)
    expect(named.classes()).toContain('timeline-msg--focus')
    expect(newest.find('[data-testid="hub-focus-baton"]').exists()).toBe(false)
    expect(newest.classes()).not.toContain('timeline-msg--focus')
  })
})
