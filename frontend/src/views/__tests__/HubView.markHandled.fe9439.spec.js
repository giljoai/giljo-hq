import { describe, it, expect, beforeEach, vi } from 'vitest'
import { reactive, nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), route: null }))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push, replace: h.replace }),
  useRoute: () => h.route,
}))
vi.mock('@/stores/websocketEventRouter', () => ({ registerReconnectResync: () => () => {} }))

const showToastMock = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

import HubView from '@/views/HubView.vue'
import api from '@/services/api'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'

const ME = 'user-op-1'
const THREAD_ID = 'thr-9439'
const BATON_MESSAGE = 'msg-baton-9439'
const OTHER_MESSAGE = 'msg-other-9439'

const childStubs = {
  ThreadList: { template: '<div class="stub-thread-list" />' },
  AgentPill: { template: '<span class="stub-pill" />' },
  NewThreadDialog: { template: '<div />' },
  ThreadCreatedDialog: { template: '<div />' },
  ThreadDeletedDialog: { template: '<div />' },
  DeletedCountButton: { props: ['count', 'entity'], template: '<button class="stub-deleted" />' },
}

function batonThread() {
  return {
    thread_id: THREAD_ID,
    chat_id: 'CHT-9439',
    subject: 'Baton thread',
    status: 'open',
    project_id: null,
    next_action_owner: ME,
    last_message: {
      id: BATON_MESSAGE,
      author: 'L25',
      excerpt: 'over to you',
      created_at: '2026-08-15T05:00:00Z',
    },
  }
}

async function mountHub() {
  h.push.mockClear()
  h.replace.mockClear()
  showToastMock.mockClear()

  h.route = reactive({
    path: '/hub',
    query: { thread: THREAD_ID, focus: 'baton', message: BATON_MESSAGE },
  })
  h.replace.mockImplementation((to) => {
    h.route.query = { ...(to?.query || {}) }
    return Promise.resolve()
  })

  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useCommHubStore()
  const thread = batonThread()
  store._testSeedThread(thread)
  api.threads.history.mockResolvedValue({
    data: {
      thread,
      messages: [
        { message_id: BATON_MESSAGE, thread_id: THREAD_ID, content: 'over to you' },
        { message_id: OTHER_MESSAGE, thread_id: THREAD_ID, content: 'and one more thing' },
      ],
    },
  })
  useUserStore().currentUser = { id: ME, role: 'admin' }

  const wrapper = mount(HubView, { global: { plugins: [pinia], stubs: childStubs } })
  await flushPromises()
  await nextTick()
  return { wrapper, store }
}

const batonFlag = (wrapper) => wrapper.find('[data-testid="hub-focus-baton"]')

describe('FE-9439 — mark handled clears the "Waiting on you" pin', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the pin on arrival from a baton notification (instrument check)', async () => {
    const { wrapper } = await mountHub()

    expect(batonFlag(wrapper).exists()).toBe(true)
    expect(batonFlag(wrapper).text()).toBe('Waiting on you')
    expect(wrapper.find('[data-testid="composer-mark-handled"]').exists()).toBe(true)
  })

  it('clears the baton server-side (the half that already worked)', async () => {
    const { wrapper, store } = await mountHub()
    const passBatonSpy = vi
      .spyOn(store, 'passBaton')
      .mockResolvedValue({ thread_id: THREAD_ID, next_action_owner: null })

    await wrapper.get('[data-testid="composer-mark-handled"]').trigger('click')
    await flushPromises()

    expect(passBatonSpy).toHaveBeenCalledTimes(1)
    expect(passBatonSpy).toHaveBeenCalledWith(THREAD_ID, 'none')
  })

  describe('both instances are the same control', () => {
    it.each([
      ['search bar', 'search-mark-handled'],
      ['composer', 'composer-mark-handled'],
    ])('the %s toggle issues exactly one passBaton(threadId, none)', async (_label, testid) => {
      const { wrapper, store } = await mountHub()
      const passBatonSpy = vi
        .spyOn(store, 'passBaton')
        .mockResolvedValue({ thread_id: THREAD_ID, next_action_owner: null })

      const instance = wrapper.get(`[data-testid="${testid}"]`)
      expect(instance.classes()).toContain('mark-handled-toggle')

      await instance.trigger('click')
      await flushPromises()

      expect(passBatonSpy).toHaveBeenCalledTimes(1)
      expect(passBatonSpy).toHaveBeenCalledWith(THREAD_ID, 'none')
      expect(h.route.query.focus).toBeUndefined()
    })

    it('renders both instances while the turn is the operator, ON', async () => {
      const { wrapper } = await mountHub()

      for (const testid of ['search-mark-handled', 'composer-mark-handled']) {
        const instance = wrapper.get(`[data-testid="${testid}"]`)
        expect(instance.attributes('aria-pressed')).toBe('true')
        expect(instance.attributes('color')).toBe('warning')
      }
    })
  })

  it('drops focus/message from the route so the pin cannot survive', async () => {
    const { wrapper, store } = await mountHub()
    vi.spyOn(store, 'passBaton').mockResolvedValue({ thread_id: THREAD_ID, next_action_owner: null })

    await wrapper.get('[data-testid="composer-mark-handled"]').trigger('click')
    await flushPromises()
    await nextTick()

    expect(h.route.query.focus).toBeUndefined()
    expect(h.route.query.message).toBeUndefined()
    expect(h.route.query.thread).toBe(THREAD_ID)
    expect(h.replace).toHaveBeenCalledTimes(1)
    expect(h.push).not.toHaveBeenCalled()

    expect(batonFlag(wrapper).exists()).toBe(false)
  })

  it('leaves the pin alone when the server refuses', async () => {
    const { wrapper, store } = await mountHub()
    vi.spyOn(store, 'passBaton').mockRejectedValue(new Error('nope'))

    await wrapper.get('[data-testid="composer-mark-handled"]').trigger('click')
    await flushPromises()
    await nextTick()

    expect(h.replace).not.toHaveBeenCalled()
    expect(h.route.query.focus).toBe('baton')
    expect(batonFlag(wrapper).exists()).toBe(true)
  })
})
