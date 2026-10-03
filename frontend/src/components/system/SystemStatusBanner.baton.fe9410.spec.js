import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  threads: { value: [] },
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getGiljoMode: vi.fn(() => 'ce'),
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
    thread_id: 'thr-42',
    chat_id: 'CHT-0042',
    subject: 'Baton thread',
    status: 'open',
    next_action_owner: ME,
    updated_at: '2026-08-13T05:00:00Z',
    last_message: { author: 'L25', excerpt: 'over to you', created_at: '2026-08-13T05:00:00Z' },
    ...overrides,
  }
}

async function mountBanner({ threads = [] } = {}) {
  h.threads.value = threads
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia], stubs: globalStubs } })
  useUserStore().currentUser = { id: ME, role: 'admin' }
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('SystemStatusBanner baton navigation (FE-9410)', () => {
  beforeEach(() => {
    h.push.mockClear()
  })

  it('sends the CTA click to the thread WITH the message context, not the thread alone', async () => {
    const wrapper = await mountBanner({ threads: [thread()] })
    await wrapper.find('[data-testid="your-turn-cta"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thr-42', focus: 'baton' },
    })
  })

  it('carries the same context when the whole row is clicked, not only the CTA', async () => {
    const wrapper = await mountBanner({ threads: [thread()] })
    await wrapper.find('[data-testid="your-turn-banner"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thr-42', focus: 'baton' },
    })
  })

  it('still opens the plain Hub list when several threads are pending', async () => {
    const wrapper = await mountBanner({
      threads: [thread(), thread({ thread_id: 'thr-43', subject: 'Second' })],
    })
    await wrapper.find('[data-testid="your-turn-cta"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({ path: '/hub' })
  })
})
