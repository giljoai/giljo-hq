/**
 * HubView.baton.fe9410.spec.js — FE-9410
 *
 * Entry point 2 of 2 for the baton notification: the attention strip above the thread
 * list. Plus the landing half that BOTH entry points depend on.
 *
 * The defect these pin is one missing call, reached by two doors. HubView's
 * onThreadSelect() loads a thread's messages and participants but never calls
 * commHub.selectThread(), and selection is the only thing that swaps the region from
 * the list to the thread (the two are v-if branches over selectedThreadId). Selection
 * happens inside ThreadList.onSelect(), so a click routed through a CARD works and a
 * click that reaches onThreadSelect DIRECTLY does not:
 *
 *   - the attention strip called it directly           -> data fetched, list still up;
 *   - the ?thread= deep link called it directly        -> the banner's own landing,
 *                                                         which the operator read as
 *                                                         "it dumped me at the Hub".
 *
 * The last case here is the one no mount-time test could have caught: the banner is
 * app-wide, so it is clickable while already standing in the Hub, where a pushed query
 * remounts nothing.
 *
 * Edition scope: Both
 */
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
    project_id: null, // General tab: the attention strip only renders there
    next_action_owner: ME,
    last_message: { author: 'L25', excerpt: 'over to you', created_at: '2026-08-13T05:00:00Z' },
    ...overrides,
  }
}

/** The thread's history as the server would return it: oldest first, newest last. */
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

/** The thread view is up (as opposed to the list) when its back-row is rendered. */
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
    // This is the banner's landing. Fetching the thread is not opening it.
    const { wrapper, store } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton' },
      seed: batonThread(),
    })
    expect(store.selectedThreadId).toBe(THREAD_ID)
    expect(inThreadView(wrapper)).toBe(true)
    expect(wrapper.find('.stub-thread-list').exists()).toBe(false)
  })

  it('opens the thread when the query changes under a Hub that is already mounted', async () => {
    // The banner is app-wide, so it is clickable FROM the Hub. onMounted never runs
    // again for that click; without a query watcher the notification does nothing.
    const { wrapper, store } = await mountHub({ query: {}, seed: batonThread() })
    expect(store.selectedThreadId).toBe(null)

    h.route.query = { thread: THREAD_ID, focus: 'baton' }
    await flushPromises()
    await nextTick()

    expect(store.selectedThreadId).toBe(THREAD_ID)
    expect(inThreadView(wrapper)).toBe(true)
  })

  it('resolves the baton arrival to an actual message and hands it to the timeline', async () => {
    // The notification can only ever name a THREAD. This is the step that turns that
    // into a message: the newest post, which is the one that handed the baton over and
    // the same row the server calls last_message. Naming a real id is what makes
    // "navigate to the message" true rather than approximately true.
    const { wrapper } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton' },
      seed: batonThread(),
    })
    expect(wrapper.find('.stub-timeline').attributes('data-focus')).toBe(BATON_MESSAGE)
  })

  it('stops marking once the operator moves on to a thread nobody handed them', async () => {
    // focus=baton stays in the URL after the arrival. Selecting another thread from the
    // list must not inherit it, or the next thread opened by hand shows a post labelled
    // "Waiting on you" that no agent ever handed over.
    const { wrapper, store } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton' },
      seed: batonThread(),
    })
    expect(wrapper.find('.stub-timeline').attributes('data-focus')).toBe(BATON_MESSAGE)

    // The other thread must actually HAVE messages, or this would pass merely because
    // there was nothing to mark — which is not the guarantee under test.
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
    // A plain ?thread= deep link (the /jobs message icon, FE-9012c) is not a baton
    // hand-off and must not decorate anything.
    const { wrapper } = await mountHub({ query: { thread: THREAD_ID }, seed: batonThread() })
    // The thread must still OPEN — "nothing is marked" only means something if the
    // operator got there. Asserting the absence alone would also pass on a Hub that
    // never navigated at all, which is the very defect this project closes.
    const timeline = wrapper.find('.stub-timeline')
    expect(timeline.exists()).toBe(true)
    expect(timeline.attributes('data-focus')).toBeUndefined()
  })
})
