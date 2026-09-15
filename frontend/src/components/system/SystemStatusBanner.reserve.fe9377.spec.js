import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  mode: { value: 'ce' },
  integShow: { fn: () => true },
  agentShow: { fn: () => false },
  dismissInteg: vi.fn(),
  dismissAgent: vi.fn(),
  dist: { value: { active: 2 } },
  refreshDeferred: { value: null },
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
    showIntegrationReminder: { value: (hp) => h.integShow.fn(hp) },
    showAgentReminder: { value: (hc) => h.agentShow.fn(hc) },
    dismissIntegrationReminder: h.dismissInteg,
    dismissAgentReminder: h.dismissAgent,
  }),
}))

vi.mock('@/composables/useIntegrationStatus', async () => {
  const { ref } = await import('vue')
  return {
    useIntegrationStatus: () => {
      const gitEnabled = ref(false)
      const serenaEnabled = ref(false)
      const resolved = ref(false)
      return {
        gitEnabled,
        serenaEnabled,
        resolved,
        loading: ref(false),
        refresh: () =>
          h.refreshDeferred.value.promise.then(({ git, serena }) => {
            gitEnabled.value = git
            serenaEnabled.value = serena
            resolved.value = true
          }),
      }
    },
  }
})

vi.mock('@/services/api', () => {
  const apiObj = {
    stats: {
      getDashboard: vi.fn(() => Promise.resolve({ data: { project_status_dist: h.dist.value } })),
    },
    notifications: { list: vi.fn(), markRead: vi.fn(), markDismissed: vi.fn() },
  }
  return { default: apiObj, api: apiObj }
})

import SystemStatusBanner from './SystemStatusBanner.vue'
import { useNotificationStore } from '@/stores/notifications'
import { useUserStore } from '@/stores/user'
import { useProductStore } from '@/stores/products'

const globalStubs = { 'v-icon': { template: '<i class="v-icon"><slot /></i>' } }
const RESERVED = '[data-testid="banner-reserved-space"]'
const NUDGE = '[data-testid="onboarding-integration-banner"]'
const RESERVE_KEY = 'giljo_banner_reserved_rows'

function seedReserve(rows, owner = 'u1') {
  localStorage.setItem(RESERVE_KEY, JSON.stringify({ u: owner, n: rows }))
}

function storedReserve() {
  return JSON.parse(localStorage.getItem(RESERVE_KEY))
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

function makeDeferred() {
  let settle
  const promise = new Promise((res) => {
    settle = res
  })
  return { promise, settle }
}

function mountPending() {
  h.refreshDeferred.value = makeDeferred()
  const wrapper = mount(SystemStatusBanner, { global: { stubs: globalStubs } })
  useNotificationStore().notifications = []
  useUserStore().currentUser = { id: 'u1', role: 'admin' }
  useProductStore().activeProduct = { id: 'p1' }
  return wrapper
}

async function resolveNudge(wrapper) {
  await flushPromises()
  h.refreshDeferred.value.settle({ git: false, serena: false })
  await flushPromises()
  return wrapper
}

describe('SystemStatusBanner first-frame space reservation (FE-9377)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    installFunctionalLocalStorage()
    localStorage.clear()
    h.integShow.fn = () => true
    h.agentShow.fn = () => false
    h.dist.value = { active: 2 }
  })

  afterEach(() => {
    vi.useRealTimers()
    localStorage.clear()
  })

  it('THE SHIFT: a cached row count reserves the space SYNCHRONOUSLY at first render', () => {
    seedReserve(1)
    const wrapper = mountPending()
    const reserved = wrapper.find(RESERVED)
    expect(reserved.exists()).toBe(true)
    expect(reserved.attributes('style')).toContain('height: 42px')
  })

  it('an arriving row fills the reserved space in place — strip height never changes', async () => {
    seedReserve(1)
    const wrapper = mountPending()
    expect(wrapper.find(RESERVED).attributes('style')).toContain('height: 42px')

    await resolveNudge(wrapper)

    expect(wrapper.find(NUDGE).exists()).toBe(true)
    expect(wrapper.find(RESERVED).exists()).toBe(false)
  })

  it('DoD 2: nothing cached and nothing due renders no strip at all', async () => {
    h.integShow.fn = () => false
    const wrapper = mountPending()
    expect(wrapper.find('.system-status-banner').exists()).toBe(false)
    await flushPromises()
    expect(wrapper.find('.system-status-banner').exists()).toBe(false)
  })

  it('a stale reservation collapses at the settle timeout and self-corrects the cache', async () => {
    vi.useFakeTimers()
    seedReserve(2)
    const wrapper = mountPending()
    expect(wrapper.find(RESERVED).attributes('style')).toContain('height: 84px')

    await resolveNudge(wrapper)
    expect(wrapper.find(RESERVED).attributes('style')).toContain('height: 42px')

    await vi.advanceTimersByTimeAsync(4000)
    expect(wrapper.find(RESERVED).exists()).toBe(false)
    expect(storedReserve()).toEqual({ u: 'u1', n: 1 })
  })

  it('a settled load persists its rendered row count for the next first frame', async () => {
    vi.useFakeTimers()
    const wrapper = mountPending()
    await resolveNudge(wrapper)
    expect(wrapper.find(NUDGE).exists()).toBe(true)

    await vi.advanceTimersByTimeAsync(4000)
    expect(storedReserve()).toEqual({ u: 'u1', n: 1 })
  })

  it('dismissing the last row writes 0 — the next no-banner load reserves nothing', async () => {
    vi.useFakeTimers()
    const wrapper = mountPending()
    await resolveNudge(wrapper)
    await vi.advanceTimersByTimeAsync(4000)
    expect(storedReserve()).toEqual({ u: 'u1', n: 1 })

    await wrapper.find(NUDGE).findAll('button').at(-1).trigger('click')
    await flushPromises()
    expect(storedReserve()).toEqual({ u: 'u1', n: 0 })
  })

  it('the reservation cap holds: an absurd cached value reserves at most 3 rows', () => {
    seedReserve(9)
    const wrapper = mountPending()
    expect(wrapper.find(RESERVED).attributes('style')).toContain('height: 126px')
  })

  it('a garbage cached value reserves nothing', () => {
    localStorage.setItem(RESERVE_KEY, 'not-a-number')
    const wrapper = mountPending()
    expect(wrapper.find(RESERVED).exists()).toBe(false)
  })

  it("another account's reservation is dropped when this session's identity resolves", async () => {
    seedReserve(1, 'someone-else')
    h.integShow.fn = () => false
    const wrapper = mountPending()
    await flushPromises()
    expect(wrapper.find(RESERVED).exists()).toBe(false)
  })

  it("the owner's own reservation is kept when identity matches", async () => {
    seedReserve(1, 'u1')
    const wrapper = mountPending()
    await flushPromises()
    expect(wrapper.find(RESERVED).exists()).toBe(true)
    expect(wrapper.find(RESERVED).attributes('style')).toContain('height: 42px')
  })

  it('writes stamp the owning user id', async () => {
    vi.useFakeTimers()
    const wrapper = mountPending()
    await resolveNudge(wrapper)
    await vi.advanceTimersByTimeAsync(4000)
    expect(storedReserve().u).toBe('u1')
  })
})
