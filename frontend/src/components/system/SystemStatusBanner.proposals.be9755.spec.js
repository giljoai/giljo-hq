import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  count: vi.fn(),
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))

vi.mock('@/services/configService', () => ({
  default: { fetchConfig: vi.fn().mockResolvedValue({}), getGiljoMode: vi.fn(() => 'ce') },
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
    threads: { list: vi.fn(() => Promise.resolve({ data: { threads: [] } })) },
    templateProposals: { count: h.count, list: vi.fn() },
  }
  return { default: apiObj, api: apiObj }
})

import SystemStatusBanner from './SystemStatusBanner.vue'
import { useUserStore } from '@/stores/user'

const stubs = { 'v-icon': { template: '<i class="v-icon"><slot /></i>' } }

async function mountBanner() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia], stubs } })
  useUserStore().currentUser = { id: 'user-1', role: 'admin' }
  await flushPromises()
  await flushPromises()
  return wrapper
}

const marker = (w) => w.find('[data-testid="template-proposals-banner"]')

describe('SystemStatusBanner template-proposals marker (BE-9755)', () => {
  beforeEach(() => {
    h.push.mockClear()
    h.count.mockReset()
  })

  it('shows the server count once the user is known', async () => {
    h.count.mockResolvedValue({ data: { count: 3 } })
    const w = await mountBanner()
    expect(h.count).toHaveBeenCalledTimes(1)
    expect(w.get('[data-testid="template-proposals-banner-text"]').text()).toBe(
      '3 template changes waiting',
    )
    expect(h.push).not.toHaveBeenCalled()
  })

  it('is absent at 0', async () => {
    h.count.mockResolvedValue({ data: { count: 0 } })
    const w = await mountBanner()
    expect(marker(w).exists()).toBe(false)
  })

  it('goes to Tools > Agents only when clicked', async () => {
    h.count.mockResolvedValue({ data: { count: 1 } })
    const w = await mountBanner()
    await w.get('[data-testid="template-proposals-cta"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({ path: '/tools', query: { tab: 'agents' } })
  })

  it('a failed count read leaves the row absent and the strip intact', async () => {
    h.count.mockRejectedValue(new Error('boom'))
    const w = await mountBanner()
    expect(marker(w).exists()).toBe(false)
  })
})
