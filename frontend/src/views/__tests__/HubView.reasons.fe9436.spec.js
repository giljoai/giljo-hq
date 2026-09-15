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
const THREAD_ID = 'thr-reasons'
const OLD_MESSAGE = 'msg-old'
const TARGET_MESSAGE = 'msg-target'
const NEWER_MESSAGE = 'msg-newer'

const childStubs = {
  ThreadList: { template: '<div class="stub-thread-list" />' },
  HubComposer: { template: '<div class="stub-composer" />' },
  AgentPill: { template: '<span class="stub-pill" />' },
  NewThreadDialog: { template: '<div />' },
  ThreadCreatedDialog: { template: '<div />' },
  ThreadDeletedDialog: { template: '<div />' },
  DeletedCountButton: { props: ['count', 'entity'], template: '<button class="stub-deleted" />' },
}

function thread() {
  return {
    thread_id: THREAD_ID,
    chat_id: 'CHT-0493',
    subject: 'Action needed thread',
    status: 'open',
    project_id: null,
    next_action_owner: null,
    last_message: {
      id: NEWER_MESSAGE,
      author: 'L25',
      excerpt: 'and one more thing',
      created_at: '2026-08-15T05:00:00Z',
    },
  }
}

function seedHistory(t) {
  api.threads.history.mockResolvedValue({
    data: {
      thread: t,
      messages: [
        { message_id: OLD_MESSAGE, thread_id: THREAD_ID, content: 'earlier chatter' },
        { message_id: TARGET_MESSAGE, thread_id: THREAD_ID, content: 'the post that wants you' },
        { message_id: NEWER_MESSAGE, thread_id: THREAD_ID, content: 'and one more thing' },
      ],
    },
  })
}

async function mountHubWithRealTimeline(query) {
  h.route = reactive({ query: { ...query } })
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useCommHubStore()
  const seed = thread()
  store._testSeedThread(seed)
  seedHistory(seed)
  useUserStore().currentUser = { id: ME, role: 'admin' }

  const wrapper = mount(HubView, {
    global: {
      plugins: [pinia, createVuetify()],
      stubs: { ...childStubs, ThreadTimeline: false },
    },
  })
  await flushPromises()
  await nextTick()
  return wrapper
}

const REASONS = [
  { focus: 'baton', testid: 'hub-focus-baton', copy: 'Waiting on you' },
  { focus: 'mention', testid: 'hub-focus-mention', copy: 'You were mentioned' },
  { focus: 'approval', testid: 'hub-focus-approval', copy: 'Needs your approval' },
]

describe('HubView -> ThreadTimeline, per reason, end to end (FE-9436)', () => {
  beforeEach(() => {
    h.push.mockClear()
    Element.prototype.scrollIntoView = vi.fn()
  })

  for (const { focus, testid, copy } of REASONS) {
    it(`lands a ${focus} notification on the NAMED post with ${focus} copy`, async () => {
      const wrapper = await mountHubWithRealTimeline({
        thread: THREAD_ID,
        focus,
        message: TARGET_MESSAGE,
      })

      const named = wrapper.find(`[data-testid="timeline-message-${TARGET_MESSAGE}"]`)
      const newest = wrapper.find(`[data-testid="timeline-message-${NEWER_MESSAGE}"]`)
      expect(named.exists()).toBe(true)
      expect(newest.exists()).toBe(true)

      expect(named.find(`[data-testid="${testid}"]`).text()).toBe(copy)
      expect(named.classes()).toContain('timeline-msg--focus')

      expect(newest.find(`[data-testid="${testid}"]`).exists()).toBe(false)
      expect(newest.classes()).not.toContain('timeline-msg--focus')

      expect(wrapper.findAll('.timeline-msg__focus-flag')).toHaveLength(1)
    })
  }

  it('never puts the hand-off words on a mention or an approval, end to end', async () => {
    for (const focus of ['mention', 'approval']) {
      const wrapper = await mountHubWithRealTimeline({
        thread: THREAD_ID,
        focus,
        message: TARGET_MESSAGE,
      })
      expect(wrapper.find('[data-testid="hub-focus-baton"]').exists()).toBe(false)
      expect(wrapper.find('.timeline-msg__focus-flag').text()).not.toContain('Waiting on you')
    }
  })

  it('falls back to the tail when the reason names no post, on every reason', async () => {
    for (const { focus, testid } of REASONS) {
      const wrapper = await mountHubWithRealTimeline({ thread: THREAD_ID, focus })
      const newest = wrapper.find(`[data-testid="timeline-message-${NEWER_MESSAGE}"]`)
      expect(newest.find(`[data-testid="${testid}"]`).exists()).toBe(true)
      expect(
        wrapper.find(`[data-testid="timeline-message-${TARGET_MESSAGE}"]`).classes(),
      ).not.toContain('timeline-msg--focus')
    }
  })

  it('marks NOTHING for an arrival whose reason it does not recognise', async () => {
    const wrapper = await mountHubWithRealTimeline({
      thread: THREAD_ID,
      focus: 'urgent-ish',
      message: TARGET_MESSAGE,
    })
    expect(wrapper.findAll('.timeline-msg__focus-flag')).toHaveLength(0)
    expect(wrapper.findAll('.timeline-msg--focus')).toHaveLength(0)
  })

  it('marks nothing on an ordinary deep link that merely names a post', async () => {
    const wrapper = await mountHubWithRealTimeline({
      thread: THREAD_ID,
      message: TARGET_MESSAGE,
    })
    expect(wrapper.findAll('.timeline-msg__focus-flag')).toHaveLength(0)
  })
})
