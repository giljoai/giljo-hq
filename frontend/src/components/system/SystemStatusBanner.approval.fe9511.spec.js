/**
 * SystemStatusBanner.approval.fe9511.spec.js — FE-9511
 *
 * Approval banner: server-derived canned states + project pill, prose demoted
 * to the Review screen. Extends FE-9501b's raised-hand row (see the sibling
 * .fe9501b.spec.js for the base shape: single-vs-multiple collapse, no
 * dismiss button, click-only navigation) with:
 *
 *  - a CANNED text per `banner_state` (never `approval.reason`);
 *  - project pills (taxonomy_alias), capped at 4 with a "+N more" tail;
 *  - the pill renders straight from the payload -- no product-store lookup,
 *    so it works for a project this session never opened (FE-9508's trap).
 *
 * Edition scope: Both
 */
import { describe, it, expect, vi } from 'vitest'
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
  // Deliberately DO NOT populate productStore -- proves the pill needs no
  // store lookup (FE-9508's trap: the project may not be in the store at all
  // because the user never opened it this session).
  await flushPromises()
  await flushPromises()
  return wrapper
}

function pillTexts(wrapper) {
  return wrapper.findAll('[data-testid="approval-banner-pill"]').map((el) => el.text())
}

describe('SystemStatusBanner approval row -- canned states (FE-9511)', () => {
  it('renders the canned text for waiting_at_staging', async () => {
    const wrapper = await mountBanner({ approvals: [approval({ banner_state: 'waiting_at_staging' })] })
    expect(wrapper.find('[data-testid="approval-banner-text"]').text()).toBe(
      'A project is waiting for you at staging',
    )
  })

  it('renders the canned text for decision_needed', async () => {
    const wrapper = await mountBanner({ approvals: [approval({ banner_state: 'decision_needed' })] })
    expect(wrapper.find('[data-testid="approval-banner-text"]').text()).toBe('An agent is waiting on your decision')
  })

  it('renders the canned text for blocked', async () => {
    const wrapper = await mountBanner({ approvals: [approval({ banner_state: 'blocked' })] })
    expect(wrapper.find('[data-testid="approval-banner-text"]').text()).toBe('An agent is blocked and needs you')
  })

  it('renders the canned text for input_needed', async () => {
    const wrapper = await mountBanner({ approvals: [approval({ banner_state: 'input_needed' })] })
    expect(wrapper.find('[data-testid="approval-banner-text"]').text()).toBe('An agent needs your input')
  })

  it('falls back to the decision_needed text for an unrecognized state rather than rendering nothing', async () => {
    const wrapper = await mountBanner({ approvals: [approval({ banner_state: 'not_a_real_state' })] })
    expect(wrapper.find('[data-testid="approval-banner-text"]').text()).toBe('An agent is waiting on your decision')
  })

  it('NEVER renders approval.reason, however long -- prose is demoted to the Review screen, not shown here', async () => {
    const longReason = 'x'.repeat(2000)
    const wrapper = await mountBanner({
      approvals: [approval({ banner_state: 'decision_needed', reason: longReason })],
    })
    const text = wrapper.find('[data-testid="approval-banner-text"]').text()
    expect(text).toBe('An agent is waiting on your decision')
    expect(text).not.toContain('x'.repeat(50))
    expect(wrapper.text()).not.toContain(longReason)
  })
})

describe('SystemStatusBanner approval row -- project pills (FE-9511)', () => {
  it('shows a pill for the project even though the product store was never populated', async () => {
    expect(useProductStore().activeProduct).toBeFalsy() // sanity: store genuinely empty
    const wrapper = await mountBanner({ approvals: [approval({ taxonomy_alias: 'FE-9511' })] })
    expect(pillTexts(wrapper)).toEqual(['FE-9511'])
  })

  it('dedupes pills by project across several approvals on the same project', async () => {
    const wrapper = await mountBanner({
      approvals: [
        approval({ id: 'a1', project_id: 'p1', taxonomy_alias: 'BE-0024' }),
        approval({ id: 'a2', project_id: 'p1', taxonomy_alias: 'BE-0024' }),
      ],
    })
    expect(pillTexts(wrapper)).toEqual(['BE-0024'])
  })

  it('caps pills at 4 and shows a +N more tail, one row never a stack', async () => {
    const approvals = ['BE-0001', 'BE-0002', 'BE-0003', 'BE-0004', 'BE-0005', 'BE-0006'].map((alias, i) =>
      approval({ id: `a${i}`, project_id: `p${i}`, taxonomy_alias: alias }),
    )
    const wrapper = await mountBanner({ approvals })
    expect(pillTexts(wrapper)).toEqual(['BE-0001', 'BE-0002', 'BE-0003', 'BE-0004'])
    expect(wrapper.find('[data-testid="approval-banner-pill-overflow"]').text()).toBe('+2')
    expect(wrapper.find('[data-testid="approval-banner-text"]').text()).toBe('6 agents need your decision')
  })

  it('shows no overflow pill when there are 4 or fewer distinct projects', async () => {
    const approvals = ['BE-0001', 'BE-0002'].map((alias, i) =>
      approval({ id: `a${i}`, project_id: `p${i}`, taxonomy_alias: alias }),
    )
    const wrapper = await mountBanner({ approvals })
    expect(wrapper.find('[data-testid="approval-banner-pill-overflow"]').exists()).toBe(false)
  })

  it('renders no pill when a row carries no taxonomy_alias (defensive, should not happen server-side)', async () => {
    const wrapper = await mountBanner({ approvals: [approval({ taxonomy_alias: null })] })
    expect(pillTexts(wrapper)).toEqual([])
    expect(wrapper.find('[data-testid="approval-banner-text"]').exists()).toBe(true)
  })
})
