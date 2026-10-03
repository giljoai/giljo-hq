import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  mode: { value: 'ce' },
  threads: { value: [] },
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getGiljoMode: vi.fn(() => h.mode.value),
  },
}))

vi.mock('@/composables/useTutorialState', async (importOriginal) => ({
  ...(await importOriginal()),
  isActivateBreadcrumbArmed: () => false,
  clearActivateBreadcrumb: vi.fn(),
}))

vi.mock('@/composables/useOnboardingReminders', () => ({
  useOnboardingReminders: () => ({
    showIntegrationReminder: { value: () => false },
    showAgentReminder: { value: () => false },
    dismissIntegrationReminder: vi.fn(),
    dismissAgentReminder: vi.fn(),
  }),
}))

vi.mock('@/composables/useIntegrationStatus', async () => {
  const { ref } = await import('vue')
  return {
    useIntegrationStatus: () => ({
      gitEnabled: ref(true),
      resolved: ref(true),
      loading: ref(false),
      refresh: vi.fn().mockResolvedValue(),
    }),
  }
})

vi.mock('@/services/api', () => {
  const apiObj = {
    stats: { getDashboard: vi.fn(() => Promise.resolve({ data: { project_status_dist: {} } })) },
    notifications: { list: vi.fn(), markRead: vi.fn(), markDismissed: vi.fn() },
    threads: { list: vi.fn(() => Promise.resolve({ data: { threads: h.threads.value } })) },
  }
  return { default: apiObj, api: apiObj }
})

import SystemStatusBanner from './SystemStatusBanner.vue'
import { useUserStore } from '@/stores/user'

const ME = 'user-op-1'

const globalStubs = {
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
}

function thread(overrides = {}) {
  return {
    thread_id: overrides.thread_id || 'thr-1',
    chat_id: 'CHT-0001',
    subject: 'Test',
    status: 'open',
    next_action_owner: ME,
    updated_at: '2026-08-06T10:00:00Z',
    ...overrides,
  }
}

async function mountBanner({ threads = [], userId = ME, mode = 'ce' } = {}) {
  h.threads.value = threads
  h.mode.value = mode
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia], stubs: globalStubs } })
  useUserStore().currentUser = { id: userId, role: 'admin' }
  await flushPromises()
  await flushPromises()
  return wrapper
}

function installFunctionalLocalStorage() {
  const store = new Map()
  Object.defineProperty(window, 'localStorage', {
    value: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
      clear: () => store.clear(),
    },
    writable: true,
  })
}

function row(wrapper) {
  return wrapper.find('[data-testid="your-turn-banner"]')
}

describe('SystemStatusBanner your-turn row (FE-9368)', () => {
  beforeEach(() => {
    installFunctionalLocalStorage()
  })

  beforeEach(() => {
    h.push.mockClear()
  })

  it('names the single thread the operator owes an answer to', async () => {
    const wrapper = await mountBanner({ threads: [thread({ subject: 'Test' })] })
    expect(row(wrapper).exists()).toBe(true)
    expect(wrapper.find('[data-testid="your-turn-banner-text"]').text()).toBe(
      'Waiting on you in "Test"',
    )
  })

  it('credits the agent that handed the turn over when the list carries one', async () => {
    const wrapper = await mountBanner({
      threads: [thread({ subject: 'Test', last_message: { author: 'LANE_C' } })],
    })
    expect(wrapper.find('[data-testid="your-turn-banner-text"]').text()).toBe(
      'LANE_C is waiting on you in "Test"',
    )
  })

  it('opens THAT thread when only one is pending', async () => {
    const wrapper = await mountBanner({ threads: [thread({ thread_id: 'thr-42' })] })
    await wrapper.find('[data-testid="your-turn-cta"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thr-42', focus: 'baton' },
    })
  })

  it('collapses several pending threads into one row that opens the Hub list', async () => {
    const wrapper = await mountBanner({
      threads: [
        thread({ thread_id: 'thr-1', subject: 'One' }),
        thread({ thread_id: 'thr-2', subject: 'Two' }),
      ],
    })
    expect(wrapper.find('[data-testid="your-turn-banner-text"]').text()).toBe(
      'Multiple chat threads are waiting for you',
    )
    expect(wrapper.find('[data-testid="your-turn-cta"]').text()).toBe('Open Message Hub')

    await row(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledWith({ path: '/hub' })
  })

  it('stays hidden when the baton points at someone else', async () => {
    const wrapper = await mountBanner({
      threads: [thread({ next_action_owner: 'some-agent' }), thread({ thread_id: 't2', next_action_owner: null })],
    })
    expect(row(wrapper).exists()).toBe(false)
  })

  it('never claims a resolved thread is waiting on you', async () => {
    const wrapper = await mountBanner({
      threads: [thread({ status: 'resolved' }), thread({ thread_id: 't2', status: 'closed' })],
    })
    expect(row(wrapper).exists()).toBe(false)
  })

  it('carries a dismiss X that closes the row', async () => {
    const wrapper = await mountBanner({ threads: [thread()] })
    const x = row(wrapper).find('[data-testid="your-turn-dismiss"]')
    expect(x.exists()).toBe(true)

    await x.trigger('click')
    await flushPromises()

    expect(row(wrapper).exists()).toBe(false)
    expect(h.push).not.toHaveBeenCalled()
  })

  it('keeps the dismissal across a remount -- hidden is not dismissed', async () => {
    const first = await mountBanner({ threads: [thread()] })
    await row(first).find('[data-testid="your-turn-dismiss"]').trigger('click')
    await flushPromises()
    first.unmount()

    const second = await mountBanner({ threads: [thread()] })
    expect(row(second).exists()).toBe(false)
  })

  it('announces again when the baton arrives on a NEW post', async () => {
    const first = await mountBanner({
      threads: [thread({ last_message: { id: 'msg-1' } })],
    })
    await row(first).find('[data-testid="your-turn-dismiss"]').trigger('click')
    await flushPromises()
    first.unmount()

    const second = await mountBanner({
      threads: [thread({ last_message: { id: 'msg-2' } })],
    })
    expect(row(second).exists()).toBe(true)
  })

  it('behaves the same in SaaS mode: it is client-armed, not emitted by either edition', async () => {
    const wrapper = await mountBanner({ threads: [thread({ subject: 'Test' })], mode: 'saas' })
    expect(wrapper.find('[data-testid="your-turn-banner-text"]').text()).toBe(
      'Waiting on you in "Test"',
    )
  })
})
