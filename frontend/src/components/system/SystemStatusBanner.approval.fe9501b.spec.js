/**
 * SystemStatusBanner.approval.fe9501b.spec.js — FE-9501b (D6)
 *
 * The awaiting_user raised-hand row, surfaced on the app-wide banner strip. D6:
 * DecisionModal only mounts inside ProjectTabs, so an approval question on a
 * project the operator does not have open was invisible everywhere else. This
 * row reuses the your-turn row's SHAPE (FE-9368) -- same markup, same live-read
 * behavior that leaves when the approval resolves -- but a DIFFERENT data
 * source: useApprovalsStore, since request_approval has no Hub thread/baton of
 * its own. FE-9589 added a dismiss X to both rows; it silences the strip and
 * writes no server state, so "live read" still holds.
 *
 * What these pin:
 *  - one pending approval opens ITS project;
 *  - several pending approvals collapse to one row that opens the Projects list,
 *    because we cannot pick for them;
 *  - the row is a live read of the store: no pending approval, no row;
 *  - FE-9589: its dismiss X hides the row and survives a remount, while the
 *    approval itself stays pending;
 *  - a pending approval already on the server when the page loads is picked up
 *    by the one-time fetchPending() read, not only by a live event.
 *
 * Edition scope: Both
 */
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
    // Fed once per mount (mirrors useYourTurnThreads' ensureThreadsLoaded): a
    // request_approval already pending when the page loads fires no live event.
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
    // FE-9511: server-derived; a bare fixture defaults to the common case.
    banner_state: 'decision_needed',
    taxonomy_alias: 'BE-0001',
    ...overrides,
  }
}

// tests/setup.js installs ONE shared pinia; a fresh per-test pinia keeps cases honest.
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

// tests/setup.js replaces window.localStorage with no-op vi.fn()s; FE-9589's
// dismissal state IS localStorage, so this spec installs a working in-memory one.
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
    // FE-9589: a fresh dismissal store per case.
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
    // FE-9538 (Ask 2): tab=jobs&decide=1 additionally land the click on the
    // actual decision UI (ProjectTabs consumes `decide` to open DecisionModal),
    // not just the bare project page -- see SystemStatusBanner.fe9538.spec.js.
    expect(h.push).toHaveBeenCalledWith({
      name: 'ProjectLaunch',
      params: { projectId: 'proj-42' },
      query: { tab: 'jobs', decide: '1' },
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

  // FE-9525d: several pending approvals used to always dump to the untargeted
  // Projects list. BE-9525c put product_id on the approval payload -- when one
  // of them belongs to the product tab the user is already viewing, go
  // straight to ITS project instead.
  it('with several pending approvals, opens the one in the VIEWED product tab instead of the untargeted list', async () => {
    const wrapper = await mountBanner({
      approvals: [
        approval({ id: 'a1', project_id: 'p1', product_id: 'prod-other', taxonomy_alias: 'BE-0024' }),
        approval({ id: 'a2', project_id: 'p2', product_id: 'prod-viewed', taxonomy_alias: 'BE-0031' }),
      ],
    })
    useProductStore().currentProductId = 'prod-viewed'

    await row(wrapper).trigger('click')
    // FE-9538 (Ask 2): every project-targeted branch carries tab=jobs&decide=1.
    expect(h.push).toHaveBeenCalledWith({
      name: 'ProjectLaunch',
      params: { projectId: 'p2' },
      query: { tab: 'jobs', decide: '1' },
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
    // The row rendering (proven by the previous test) must not itself have
    // pushed a route -- only an explicit click, exercised elsewhere in this
    // file, may ever call router.push.
    expect(h.push).not.toHaveBeenCalled()
  })

  // FE-9589 REVERSES this case. It asserted the row had NO dismiss button ("it
  // leaves when the approval is decided, not when it is waved away"); the
  // operator overruled that -- anything on screen must be closeable from where
  // it is on screen.
  it('carries a dismiss X that closes the row without touching the approval', async () => {
    const wrapper = await mountBanner({ approvals: [approval()] })
    const x = row(wrapper).find('[data-testid="approval-banner-dismiss"]')
    expect(x.exists()).toBe(true)

    await x.trigger('click')
    await flushPromises()

    expect(row(wrapper).exists()).toBe(false)
    // The obligation is NOT lost: the approval is still pending in the store,
    // which is what keeps it reachable from the project's Review screen and the
    // bell. Dismissal silences the announcement, nothing more.
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
    // No live WS event fires in this test at all -- the row must still appear from
    // the one-time fetchPending() read.
    const wrapper = await mountBanner({ approvals: [approval({ id: 'preexisting' })] })
    expect(row(wrapper).exists()).toBe(true)
  })

  it('behaves the same in SaaS mode: not gated by either banner emitter', async () => {
    const wrapper = await mountBanner({ approvals: [approval()], mode: 'saas' })
    expect(row(wrapper).exists()).toBe(true)
  })
})
