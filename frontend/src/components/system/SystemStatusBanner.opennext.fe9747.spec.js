import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  route: { value: { path: '/' } },
  threads: { value: [] },
  listCalls: { value: 0 },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push, currentRoute: h.route }),
}))

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
    threads: {
      list: vi.fn(() => {
        h.listCalls.value += 1
        return Promise.resolve({ data: { threads: h.threads.value } })
      }),
      markRead: vi.fn(() => Promise.resolve({})),
    },
  }
  return { default: apiObj, api: apiObj }
})

import SystemStatusBanner from './SystemStatusBanner.vue'
import { useUserStore } from '@/stores/user'
import { useCommHubStore } from '@/stores/commHubStore'

const ME = 'user-op-1'

const globalStubs = { 'v-icon': { template: '<i class="v-icon"><slot /></i>' } }

function thread(id, updatedAt, overrides = {}) {
  return {
    thread_id: id,
    chat_id: `CHT-${id}`,
    subject: `Subject ${id}`,
    status: 'open',
    next_action_owner: ME,
    updated_at: updatedAt,
    ...overrides,
  }
}

const THREE = () => [
  thread('thr-c', '2026-10-06T11:00:00Z'),
  thread('thr-a', '2026-10-06T10:00:00Z'),
  thread('thr-b', '2026-10-06T09:00:00Z'),
]

async function mountBanner({ threads = [], route = { path: '/' } } = {}) {
  h.threads.value = threads
  h.route.value = route
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia], stubs: globalStubs } })
  useUserStore().currentUser = { id: ME, role: 'admin' }
  await flushPromises()
  await flushPromises()
  return { wrapper, hub: useCommHubStore() }
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

const text = (w) => w.find('[data-testid="your-turn-banner-text"]').text()
const cta = (w) => w.find('[data-testid="your-turn-cta"]')
const rowEl = (w) => w.find('[data-testid="your-turn-banner"]')
const routeTo = (id) => ({ path: '/hub', query: { thread: id, focus: 'baton' } })

describe('SystemStatusBanner Open next (FE-9747)', () => {
  beforeEach(() => {
    installFunctionalLocalStorage()
    h.push.mockClear()
    h.listCalls.value = 0
  })

  it('one waiting thread is unchanged: names it, "Open thread", goes straight to it', async () => {
    const { wrapper } = await mountBanner({ threads: [thread('thr-a', '2026-10-06T10:00:00Z')] })
    expect(text(wrapper)).toBe('Waiting on you in "Subject thr-a"')
    expect(cta(wrapper).text()).toBe('Open thread')
    await cta(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledWith(routeTo('thr-a'))
  })

  it('several waiting threads read "<N> threads are waiting for you" with an "Open next" button', async () => {
    const { wrapper } = await mountBanner({ threads: THREE() })
    expect(text(wrapper)).toBe('3 threads are waiting for you')
    expect(cta(wrapper).text()).toBe('Open next')
  })

  it('Open next opens the thread that has waited longest, not the first in list order', async () => {
    const { wrapper } = await mountBanner({ threads: THREE() })
    await cta(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledTimes(1)
    expect(h.push).toHaveBeenCalledWith(routeTo('thr-b'))
  })

  it('clicking the banner body does exactly what the button does', async () => {
    const { wrapper } = await mountBanner({ threads: THREE() })
    await rowEl(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledTimes(1)
    expect(h.push).toHaveBeenCalledWith(routeTo('thr-b'))
  })

  it('a thread with no timestamp waits last rather than first', async () => {
    const { wrapper } = await mountBanner({
      threads: [thread('thr-x', null), thread('thr-a', '2026-10-06T10:00:00Z')],
    })
    await cta(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledWith(routeTo('thr-a'))
  })

  it('never reopens the thread being viewed: skips it and opens the next-longest', async () => {
    const { wrapper, hub } = await mountBanner({ threads: THREE(), route: { path: '/hub' } })
    hub.selectedThreadId = 'thr-b'
    await flushPromises()
    expect(text(wrapper)).toBe('2 threads are waiting for you')
    await cta(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledWith(routeTo('thr-a'))
  })

  it('walks on from the viewed thread to the one that waited after it, wrapping round', async () => {
    const { wrapper, hub } = await mountBanner({ threads: THREE(), route: { path: '/hub' } })
    hub.selectedThreadId = 'thr-a'
    await flushPromises()
    await cta(wrapper).trigger('click')
    expect(h.push).toHaveBeenLastCalledWith(routeTo('thr-c'))

    hub.selectedThreadId = 'thr-c'
    await flushPromises()
    await cta(wrapper).trigger('click')
    expect(h.push).toHaveBeenLastCalledWith(routeTo('thr-b'))
  })

  it('reads waiting time from the newest post when the thread has no live activity stamp', async () => {
    const stampless = (id, postAt) => ({
      ...thread(id, null),
      updated_at: undefined,
      created_at: '2026-01-01T00:00:00Z',
      last_message: { id: `m-${id}`, created_at: postAt },
    })
    const { wrapper } = await mountBanner({
      threads: [stampless('thr-new', '2026-10-06T11:00:00Z'), stampless('thr-old', '2026-10-06T08:00:00Z')],
    })
    await cta(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 'thr-old', focus: 'baton', message: 'm-thr-old' },
    })
  })

  it('with one other thread left it reads as the single-thread case for THAT thread', async () => {
    const { wrapper, hub } = await mountBanner({
      threads: [thread('thr-a', '2026-10-06T10:00:00Z'), thread('thr-b', '2026-10-06T09:00:00Z')],
      route: { path: '/hub' },
    })
    hub.selectedThreadId = 'thr-b'
    await flushPromises()
    expect(text(wrapper)).toBe('Waiting on you in "Subject thr-a"')
    expect(cta(wrapper).text()).toBe('Open thread')
    await cta(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledWith(routeTo('thr-a'))
  })

  it('hides when the only waiting thread is the one being viewed', async () => {
    const { wrapper, hub } = await mountBanner({
      threads: [thread('thr-a', '2026-10-06T10:00:00Z')],
      route: { path: '/hub' },
    })
    hub.selectedThreadId = 'thr-a'
    await flushPromises()
    expect(rowEl(wrapper).exists()).toBe(false)
  })

  it('a selection left over from an earlier Hub visit does not count as viewing', async () => {
    const { wrapper, hub } = await mountBanner({ threads: THREE(), route: { path: '/projects' } })
    hub.selectedThreadId = 'thr-b'
    await flushPromises()
    expect(text(wrapper)).toBe('3 threads are waiting for you')
    await cta(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledWith(routeTo('thr-b'))
  })

  it('follows the store when a baton leaves: count drops and Open next moves on, no new read', async () => {
    const { wrapper, hub } = await mountBanner({ threads: THREE() })
    const readsAfterMount = h.listCalls.value

    hub.handleThreadUpdate({ thread_id: 'thr-b', next_action_owner: 'some-agent' })
    await flushPromises()

    expect(text(wrapper)).toBe('2 threads are waiting for you')
    await cta(wrapper).trigger('click')
    expect(h.push).toHaveBeenCalledWith(routeTo('thr-a'))
    expect(h.listCalls.value).toBe(readsAfterMount)
  })

  it('the dismiss X still closes the row and navigates nowhere', async () => {
    const { wrapper } = await mountBanner({ threads: THREE() })
    await wrapper.find('[data-testid="your-turn-dismiss"]').trigger('click')
    await flushPromises()
    expect(rowEl(wrapper).exists()).toBe(false)
    expect(h.push).not.toHaveBeenCalled()
  })
})
