/**
 * HubView.pinning.fe9418.spec.js — FE-9418
 *
 * The landing half of exact baton-message pinning.
 *
 * FE-9410 got the operator INTO the thread but could only approximate the post, because
 * nothing on the notification path named one: the baton's WS event
 * (`broadcast_thread_update`) and its durable bell row (`HubBatonHandoverPayload`) both
 * carry a thread id and no message id. So the Hub resolved the target as "the newest
 * post at the moment you arrive" — which is a DIFFERENT row from "the post that handed
 * you the baton" as soon as anything else lands in between, and under a sprint's worth
 * of agent traffic that is the ordinary case rather than the unlucky one.
 *
 * FE-9418 adds `Message.id` to the thread-list `last_message`, so the route can carry
 * the anchor. These pin the three things that must all hold at once:
 *
 *   1. a named anchor WINS over the tail — otherwise the change bought nothing;
 *   2. no anchor falls back to the tail UNCHANGED — three real callers cannot supply
 *      one (a bare thread id, a thread nobody has posted in, an older payload);
 *   3. an anchor naming a post that is not loaded ALSO falls back — an id nothing
 *      matches would mark nothing and scroll nowhere, which is worse than the tail.
 *
 * FE-9410's own guarantees are re-asserted here rather than assumed, because this lane
 * rewrites the computed that carries them.
 *
 * Edition scope: Both
 */
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

/**
 * The thread's history, oldest first. The baton post is deliberately NOT last: a post
 * landing between the notification and the click is the whole reason this project
 * exists, and a fixture whose anchor is already the tail cannot tell the two rules
 * apart — every assertion below would pass on unmodified FE-9410 code.
 */
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
    // Stated as its own assertion because it is the entire point of the project: the
    // tail is a real, different, plausible answer here and it is the wrong one.
    expect(focusOf(wrapper)).not.toBe(NEWER_MESSAGE)
  })

  it('falls back to the thread tail when the arrival names no message', async () => {
    // The bell rows hold only a thread id, and a thread nobody has posted in has no
    // anchor to give. FE-9410's behaviour must survive both untouched.
    const { wrapper } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton' },
      seed: batonThread(),
    })
    expect(focusOf(wrapper)).toBe(NEWER_MESSAGE)
  })

  it('falls back to the tail when the named message is not in the loaded timeline', async () => {
    // An anchor nothing matches is functionally absent: it would mark no post and
    // scroll nowhere, leaving the operator worse off than the approximation. A stale
    // bookmark, a bounded history window, or a deleted post all reach this.
    const { wrapper } = await mountHub({
      query: { thread: THREAD_ID, focus: 'baton', message: 'msg-not-here' },
      seed: batonThread(),
    })
    expect(focusOf(wrapper)).toBe(NEWER_MESSAGE)
  })

  it('marks nothing on an ordinary arrival even when a message is named', async () => {
    // A plain ?thread= deep link (the /jobs message icon, FE-9012c) is not a hand-off.
    // The anchor names a post but no baton was passed, so nothing may say "Waiting on
    // you" — the flag is the authority on WHETHER to mark, the anchor only on WHICH.
    const { wrapper } = await mountHub({
      query: { thread: THREAD_ID, message: BATON_MESSAGE },
      seed: batonThread(),
    })
    expect(wrapper.find('.stub-timeline').exists()).toBe(true)
    expect(focusOf(wrapper)).toBeUndefined()
  })

  it('still stops marking once the operator moves on to another thread', async () => {
    // FE-9410's 441dec7b0 guard, re-asserted rather than assumed: this lane rewrites the
    // computed that carries it, and a pinned anchor outliving its thread would put
    // "Waiting on you" on a post nobody handed over — the same defect through a new door.
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
    // The strip holds the enriched thread object, so it is the one entry point that CAN
    // name the post. It must actually do so, through the shared helper.
    const { wrapper } = await mountHub({ query: { tab: 'town' }, seed: batonThread() })
    await wrapper.find('[data-testid="hub-attention-strip"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: THREAD_ID, focus: 'baton', message: BATON_MESSAGE },
    })
  })
})

describe('HubView -> ThreadTimeline, end to end (FE-9418)', () => {
  /**
   * The DoD asks that clicking a baton notification HIGHLIGHTS the exact message. Every
   * test above stubs the timeline, so together with FE-9410's ThreadTimeline spec they
   * prove it by composition: the right id is resolved here, and the timeline marks
   * whatever id it is handed. Composition is not the same as connection.
   *
   * FE-9419 is the reason that distinction earns its own test. It shipped a prop that
   * never bound — invisible to the child's unit spec, because VTU maps prop OBJECTS
   * straight through and so never exercises the template binding where the defect lived.
   * A stub declaring `focusMessageId` has exactly that blind spot: it would accept the
   * prop under any name the parent used.
   *
   * So this one mounts the REAL timeline and asserts the flag lands on the exact post.
   */
  beforeEach(() => {
    h.push.mockClear()
    // jsdom has no scrollIntoView; install it rather than spy, or the timeline's scroll
    // would throw and read as "it chose not to scroll".
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
        // Every child stubbed EXCEPT ThreadTimeline — the binding under test.
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
    // The assertion that makes this test worth mounting the real component for: the tail
    // is present, plausible, and must NOT be the one marked.
    expect(newest.find('[data-testid="hub-focus-baton"]').exists()).toBe(false)
    expect(newest.classes()).not.toContain('timeline-msg--focus')
  })
})
