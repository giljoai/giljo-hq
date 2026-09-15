import { describe, it, expect, beforeEach, vi } from 'vitest'
import { reactive, nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

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
    last_message: { author: 'L25', excerpt: 'over to you', created_at: '2026-08-13T05:00:00Z' },
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

const inThreadView = (wrapper) => wrapper.find('[data-testid="hub-back"]').exists()

describe('HubView baton navigation (FE-9410)', () => {
  beforeEach(() => {
    h.push.mockClear()
  })

  it('sends the attention-strip click to the thread WITH the message context', async () => {
    const { wrapper } = await mountHub({ query: { tab: 'town' }, seed: batonThread() })
    const strip = wrapper.find('[data-testid="hub-attention-strip"]')
    expect(strip.exists()).toBe(true)

    await strip.trigger('click')
    expect(h.push).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: THREAD_ID, focus: 'baton' },
    })
  })

  it('OPENS the thread on a ?thread= arrival instead of leaving the list up', async () => {
    const { wrapper, store } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton' },
      seed: batonThread(),
    })
    expect(store.selectedThreadId).toBe(THREAD_ID)
    expect(inThreadView(wrapper)).toBe(true)
    expect(wrapper.find('.stub-thread-list').exists()).toBe(false)
  })

  it('opens the thread when the query changes under a Hub that is already mounted', async () => {
    const { wrapper, store } = await mountHub({ query: {}, seed: batonThread() })
    expect(store.selectedThreadId).toBe(null)

    h.route.query = { thread: THREAD_ID, focus: 'baton' }
    await flushPromises()
    await nextTick()

    expect(store.selectedThreadId).toBe(THREAD_ID)
    expect(inThreadView(wrapper)).toBe(true)
  })

  it('resolves the baton arrival to an actual message and hands it to the timeline', async () => {
    const { wrapper } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton' },
      seed: batonThread(),
    })
    expect(wrapper.find('.stub-timeline').attributes('data-focus')).toBe(BATON_MESSAGE)
  })

  it('stops marking once the operator moves on to a thread nobody handed them', async () => {
    const { wrapper, store } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton' },
      seed: batonThread(),
    })
    expect(wrapper.find('.stub-timeline').attributes('data-focus')).toBe(BATON_MESSAGE)

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

    expect(wrapper.find('.stub-timeline').attributes('data-focus')).toBeUndefined()
  })

  it('does not claim a focused message for an ordinary thread arrival', async () => {
    const { wrapper } = await mountHub({ query: { thread: THREAD_ID }, seed: batonThread() })
    const timeline = wrapper.find('.stub-timeline')
    expect(timeline.exists()).toBe(true)
    expect(timeline.attributes('data-focus')).toBeUndefined()
  })
})
