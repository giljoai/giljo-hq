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

const childStubs = {
  ThreadList: { props: ['scope', 'search', 'sort'], template: '<div class="stub-thread-list" :data-scope="scope" />' },
  ThreadTimeline: { template: '<div class="stub-timeline" />' },
  HubComposer: { template: '<div class="stub-composer" />' },
  AgentPill: { template: '<span />' },
  NewThreadDialog: { template: '<div />' },
  ThreadCreatedDialog: { template: '<div />' },
  ThreadDeletedDialog: { template: '<div />' },
  DeletedCountButton: { props: ['count', 'entity'], template: '<button class="stub-deleted" />' },
}

const thread = (overrides = {}) => ({
  thread_id: 'thr-1',
  chat_id: 'CHT-0001',
  subject: 'A thread',
  status: 'open',
  project_id: null,
  next_action_owner: ME,
  last_message: { id: 'm1', author: 'L25', excerpt: 'over to you', created_at: '2026-10-01T05:00:00Z' },
  ...overrides,
})

async function mountHub({ query = {}, seed = [] } = {}) {
  h.route = reactive({ query: { ...query } })
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useCommHubStore()
  seed.forEach((t) => store._testSeedThread(t))
  seed.forEach((t) => {
    api.threads.history.mockResolvedValue({ data: { thread: t, messages: [] } })
  })
  useUserStore().currentUser = { id: ME, role: 'admin' }
  const wrapper = mount(HubView, { global: { plugins: [pinia, createVuetify()], stubs: childStubs } })
  await flushPromises()
  await nextTick()
  return { wrapper, store }
}

describe('HubView one list (FE-9741)', () => {
  beforeEach(() => h.push.mockClear())

  it('renders no General / Projects tab row', async () => {
    const { wrapper } = await mountHub()
    expect(wrapper.find('[data-testid="hub-tab-town"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="hub-tab-project"]').exists()).toBe(false)
    expect(wrapper.find('[role="tablist"]').exists()).toBe(false)
  })

  it('hands the list no tab scope', async () => {
    const { wrapper } = await mountHub()
    expect(wrapper.find('.stub-thread-list').attributes('data-scope')).toBeUndefined()
  })

  it('shows the attention strip for a PROJECT-bound thread waiting on the operator', async () => {
    const { wrapper } = await mountHub({ seed: [thread({ project_id: 'proj-1' })] })
    expect(wrapper.find('[data-testid="hub-attention-strip"]').exists()).toBe(true)
  })

  it('shows the attention strip for a standalone thread waiting on the operator', async () => {
    const { wrapper } = await mountHub({ seed: [thread()] })
    expect(wrapper.find('[data-testid="hub-attention-strip"]').exists()).toBe(true)
  })

  it('does not show the strip for a resolved thread the baton stopped on', async () => {
    const { wrapper } = await mountHub({ seed: [thread({ status: 'resolved', project_id: 'proj-1' })] })
    expect(wrapper.find('[data-testid="hub-attention-strip"]').exists()).toBe(false)
  })

  it('opens a ?thread= deep link to a resolved project thread, with a legacy ?tab= in the URL', async () => {
    const { wrapper, store } = await mountHub({
      query: { thread: 'thr-1', tab: 'town' },
      seed: [thread({ status: 'resolved', project_id: 'proj-1', next_action_owner: null })],
    })
    expect(store.selectedThreadId).toBe('thr-1')
    expect(wrapper.find('[data-testid="hub-back"]').exists()).toBe(true)
  })
})
