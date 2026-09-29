import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  mode: { value: 'ce' },
  approvals: { value: [] },
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
    approvals: {
      listPending: vi.fn(() => Promise.resolve({ data: { items: h.approvals.value } })),
    },
  }
  return { default: apiObj, api: apiObj }
})

import SystemStatusBanner from './SystemStatusBanner.vue'
import { useUserStore } from '@/stores/user'
import { useProductStore } from '@/stores/products'
import { useApprovalsStore } from '@/stores/useApprovalsStore'

const globalStubs = {
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
}

function approval(overrides = {}) {
  return {
    id: overrides.id || 'appr-1',
    job_id: 'job-1',
    project_id: 'proj-1',
    reason: 'Which option?',
    options: [{ id: 'a', label: 'Option A' }],
    status: 'pending',
    banner_state: 'decision_needed',
    taxonomy_alias: 'BE-0001',
    ...overrides,
  }
}

async function mountBanner({ approvals = [], mode = 'ce' } = {}) {
  h.approvals.value = approvals
  h.mode.value = mode
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia], stubs: globalStubs } })
  useUserStore().currentUser = { id: 'user-op-1', role: 'admin' }
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
  return wrapper.find('[data-testid="approval-banner"]')
}

describe('SystemStatusBanner approval row (FE-9501b, D6)', () => {
  beforeEach(() => {
    h.push.mockClear()
    installFunctionalLocalStorage()
  })

  it('stays hidden when there is no pending approval', async () => {
    const wrapper = await mountBanner({ approvals: [] })
    expect(row(wrapper).exists()).toBe(false)
  })

  it('shows a single pending approval and names it generically', async () => {
    const wrapper = await mountBanner({ approvals: [approval()] })
    expect(row(wrapper).exists()).toBe(true)
    expect(wrapper.find('[data-testid="approval-banner-text"]').text()).toBe(
      'An agent is waiting on your decision',
    )
  })

  it('opens THAT approval\'s project when only one is pending', async () => {
    const wrapper = await mountBanner({ approvals: [approval({ project_id: 'proj-42' })] })
    await wrapper.find('[data-testid="approval-cta"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'proj-42', decide: '1' },
    })
  })

  it('collapses several pending approvals into one row that opens the Projects list', async () => {
    const wrapper = await mountBanner({
      approvals: [
        approval({ id: 'a1', project_id: 'p1', taxonomy_alias: 'BE-0024' }),
        approval({ id: 'a2', project_id: 'p2', taxonomy_alias: 'BE-0031' }),
      ],
    })
    expect(wrapper.find('[data-testid="approval-banner-text"]').text()).toBe('2 agents need your decision')

    await row(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledWith({ path: '/projects' })
  })

  it('with several pending approvals, opens the one in the VIEWED product tab instead of the untargeted list', async () => {
    const wrapper = await mountBanner({
      approvals: [
        approval({ id: 'a1', project_id: 'p1', product_id: 'prod-other', taxonomy_alias: 'BE-0024' }),
        approval({ id: 'a2', project_id: 'p2', product_id: 'prod-viewed', taxonomy_alias: 'BE-0031' }),
      ],
    })
    useProductStore().currentProductId = 'prod-viewed'

    await row(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'p2', decide: '1' },
    })
  })

  it('with several pending approvals and NONE in the viewed product, still falls back to the untargeted list', async () => {
    const wrapper = await mountBanner({
      approvals: [
        approval({ id: 'a1', project_id: 'p1', product_id: 'prod-a', taxonomy_alias: 'BE-0024' }),
        approval({ id: 'a2', project_id: 'p2', product_id: 'prod-b', taxonomy_alias: 'BE-0031' }),
      ],
    })
    useProductStore().currentProductId = 'prod-viewed'

    await row(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledWith({ path: '/projects' })
  })

  it('never navigates on its own -- ruling 14: the row announces, a click is the only trigger', async () => {
    await mountBanner({ approvals: [approval({ project_id: 'proj-99' })] })
    expect(h.push).not.toHaveBeenCalled()
  })

  it('carries a dismiss X that closes the row without touching the approval', async () => {
    const wrapper = await mountBanner({ approvals: [approval()] })
    const x = row(wrapper).find('[data-testid="approval-banner-dismiss"]')
    expect(x.exists()).toBe(true)

    await x.trigger('click')
    await flushPromises()

    expect(row(wrapper).exists()).toBe(false)
    expect(useApprovalsStore().pendingApprovals).toHaveLength(1)
    expect(h.push).not.toHaveBeenCalled()
  })

  it('keeps the dismissal across a remount -- hidden is not dismissed', async () => {
    const first = await mountBanner({ approvals: [approval()] })
    await row(first).find('[data-testid="approval-banner-dismiss"]').trigger('click')
    await flushPromises()
    first.unmount()

    const second = await mountBanner({ approvals: [approval()] })
    expect(row(second).exists()).toBe(false)
  })

  it('announces a DIFFERENT approval even after one was dismissed', async () => {
    const first = await mountBanner({ approvals: [approval({ id: 'appr-old' })] })
    await row(first).find('[data-testid="approval-banner-dismiss"]').trigger('click')
    await flushPromises()
    first.unmount()

    const second = await mountBanner({ approvals: [approval({ id: 'appr-new' })] })
    expect(row(second).exists()).toBe(true)
  })

  it('picks up an approval that was already pending on the server before the page loaded', async () => {
    const wrapper = await mountBanner({ approvals: [approval({ id: 'preexisting' })] })
    expect(row(wrapper).exists()).toBe(true)
  })

  it('behaves the same in SaaS mode: not gated by either banner emitter', async () => {
    const wrapper = await mountBanner({ approvals: [approval()], mode: 'saas' })
    expect(row(wrapper).exists()).toBe(true)
  })
})
