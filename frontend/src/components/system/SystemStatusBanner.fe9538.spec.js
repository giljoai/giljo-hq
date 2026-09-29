import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ push: vi.fn() }))

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
      serenaEnabled: ref(true),
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
    approvals: { listPending: vi.fn(() => Promise.resolve({ data: { items: [] } })) },
  }
  return { default: apiObj, api: apiObj }
})

import SystemStatusBanner from './SystemStatusBanner.vue'
import { useUserStore } from '@/stores/user'
import { useLifecycleBannerStore } from '@/stores/lifecycleBannerStore'

const globalStubs = {
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
}

async function mountBanner() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia], stubs: globalStubs } })
  useUserStore().currentUser = { id: 'user-op-1', role: 'admin' }
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('SystemStatusBanner lifecycle banner row (FE-9538)', () => {
  it('renders a row naming the project and the moment', async () => {
    const wrapper = await mountBanner()
    useLifecycleBannerStore().rows.push({
      id: 'p1:staging_complete:1',
      projectId: 'p1',
      moment: 'staging_complete',
      taxonomyAlias: 'BE-1234',
      title: 'Fix the thing',
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="lifecycle-banner-text"]').text()).toBe(
      'Fix the thing is ready to launch',
    )
    expect(wrapper.find('[data-testid="lifecycle-banner-pill"]').text()).toBe('BE-1234')
  })

  it('clicking [Go to job] navigates to that project id, and ONLY on click', async () => {
    const wrapper = await mountBanner()
    useLifecycleBannerStore().rows.push({
      id: 'p1:activated:1',
      projectId: 'p1',
      moment: 'activated',
      taxonomyAlias: 'BE-1234',
      title: 'Fix the thing',
    })
    await flushPromises()

    expect(h.push).not.toHaveBeenCalled()
    await wrapper.find('[data-testid="lifecycle-banner-cta"]').trigger('click')

    expect(h.push).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'p1', detail: '1' },
    })
  })

  it('dismissing a row removes it without navigating', async () => {
    const wrapper = await mountBanner()
    useLifecycleBannerStore().rows.push({
      id: 'p1:activated:1',
      projectId: 'p1',
      moment: 'activated',
      taxonomyAlias: 'BE-1234',
      title: 'Fix the thing',
    })
    await flushPromises()

    await wrapper.find('[data-testid="lifecycle-banner-dismiss"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="lifecycle-banner"]').exists()).toBe(false)
    expect(h.push).not.toHaveBeenCalled()
  })

  it('a cache-miss project (no taxonomy/title resolved) degrades to generic wording, not a dropped row', async () => {
    const wrapper = await mountBanner()
    useLifecycleBannerStore().rows.push({
      id: 'p-unseen:activated:1',
      projectId: 'p-unseen',
      moment: 'activated',
      taxonomyAlias: null,
      title: null,
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="lifecycle-banner-text"]').text()).toBe(
      'A project has started',
    )
    expect(wrapper.find('[data-testid="lifecycle-banner-pill"]').exists()).toBe(false)
  })
})

describe('SystemStatusBanner decision banner navigation (FE-9538, Ask 2)', () => {
  it('a single pending approval navigates with tab=jobs&decide=1 (not just the bare project page)', async () => {
    const wrapper = await mountBanner()
    const { useApprovalsStore } = await import('@/stores/useApprovalsStore')
    useApprovalsStore().upsertApproval({
      id: 'appr-1',
      project_id: 'proj-1',
      taxonomy_alias: 'BE-9538',
      banner_state: 'decision_needed',
    })
    await flushPromises()

    await wrapper.find('[data-testid="approval-cta"]').trigger('click')

    expect(h.push).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'proj-1', decide: '1' },
    })
  })
})
