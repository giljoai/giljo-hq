import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { shallowMount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  patch: vi.fn(),
  me: vi.fn(),
  list: null,
  listCalls: 0,
  push: vi.fn(),
  ws: new Map(),
  route: { meta: {}, name: 'Tools', path: '/tools' },
}))

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    connect: vi.fn(async () => {}),
    disconnect: vi.fn(),
    on: (type, fn) => {
      if (!h.ws.has(type)) h.ws.set(type, new Set())
      h.ws.get(type).add(fn)
      return () => h.ws.get(type)?.delete(fn)
    },
    onConnectionChange: () => () => {},
  }),
}))
vi.mock('@/stores/projects', () => ({ useProjectStore: () => ({ refreshList: vi.fn() }) }))
vi.mock('vue-router', () => ({
  useRoute: () => h.route,
  useRouter: () => ({ push: h.push, afterEach: vi.fn() }),
}))
vi.mock('@/services/api', () => {
  const apiObj = {
    auth: { me: (...a) => h.me(...a), updateSetupState: (...a) => h.patch(...a) },
    onboarding: {
      startList: vi.fn(async () => {
        h.listCalls += 1
        return { data: JSON.parse(JSON.stringify(h.list)) }
      }),
    },
  }
  return { default: apiObj, api: apiObj }
})
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    products: [],
    openProductIds: [],
    openProductTabs: [],
    initializeFromStorage: async () => {},
  }),
}))
vi.mock('@/stores/jobsScope', () => ({ useJobsScopeStore: () => ({}) }))
vi.mock('@/stores/projectStatusesStore', () => ({
  useProjectStatusesStore: () => ({ ensureLoaded: async () => {} }),
}))
vi.mock('@/stores/taskStatusesStore', () => ({
  useTaskStatusesStore: () => ({ ensureLoaded: async () => {} }),
}))
vi.mock('@/services/setupService', () => ({
  default: { checkEnhancedStatus: async () => ({ is_fresh_install: false }) },
}))
vi.mock('@/composables/useHubNotifications', () => ({ useHubNotifications: () => {} }))
vi.mock('@/composables/useBannerPopoutLifecycle', () => ({ useBannerPopoutLifecycle: () => {} }))
vi.mock('@/composables/useActiveProductReconciliation', () => ({
  useActiveProductReconciliation: () => ({ stop: () => {} }),
}))
vi.mock('@/composables/useProductTabNavigation', () => ({
  useProductTabNavigation: () => ({ selectTab: () => {} }),
}))
vi.mock('@/composables/useGiljoMode', () => ({ useGiljoMode: () => ({ isSaasMode: () => false }) }))

import DefaultLayout from '@/layouts/DefaultLayout.vue'
import GuidePane from '@/components/onboarding/GuidePane.vue'
import IntroVideoDialog from '@/components/onboarding/IntroVideoDialog.vue'
import { useGuideStore } from '@/stores/guide'
import { startListPayload } from '../../../tests/helpers/startListRows'

const mem = new Map()
window.localStorage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => mem.set(k, String(v)),
  removeItem: (k) => mem.delete(k),
  clear: () => mem.clear(),
}

const NEW_USER = {
  id: 'u-1', tenant_key: 'tk', created_at: '2026-11-16T10:00:00Z', guide_closed: false,
  intro_video_seen: true, setup_complete: false,
}

let seq = 0
const mounted = []
async function mountLayout(user = {}, list = startListPayload()) {
  const pinia = createPinia()
  setActivePinia(pinia)
  h.list = list
  seq += 1
  h.me.mockResolvedValue({ data: { ...NEW_USER, id: `u-${seq}`, ...user } })
  const w = shallowMount(DefaultLayout, {
    global: {
      plugins: [pinia],
      stubs: { 'router-view': true },
      mocks: { $route: { matched: [], path: '/tools' } },
    },
  })
  mounted.push(w)
  await flushPromises()
  return w
}
afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount())
})
const fire = (type) => h.ws.get(type)?.forEach((fn) => fn({}))

describe('DefaultLayout: the getting-started pane and what feeds it', () => {
  beforeEach(() => {
    mem.clear()
    h.ws.clear()
    h.listCalls = 0
    h.route = { meta: {}, name: 'Tools', path: '/tools' }
    ;[h.patch, h.me, h.push].forEach((m) => m.mockReset())
    h.patch.mockImplementation(async (p) => ({ data: p }))
  })
  afterEach(() => vi.useRealTimers())

  it('mounts the pane on a normal page, and not on a page without the drawer', async () => {
    const w = await mountLayout()
    expect(w.findComponent(GuidePane).exists()).toBe(true)
    w.unmount()
    h.route = { meta: { hideDrawer: true }, name: 'Welcome', path: '/welcome' }
    const w2 = await mountLayout()
    expect(w2.findComponent(GuidePane).exists()).toBe(false)
    w2.unmount()
  })

  it('reads the start list on a non-Home route, and again when the project events arrive', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const w = await mountLayout()
    const first = h.listCalls
    expect(first).toBeGreaterThanOrEqual(1)
    for (const type of [
      'project:created', 'project_update', 'project:staging_complete',
      'project:implementation_launched', 'project:memory_updated', 'project:launched',
    ]) {
      expect(h.ws.get(type)?.size, type).toBeGreaterThan(0)
    }
    fire('project_update')
    fire('project_update')
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()
    expect(h.listCalls).toBe(first + 1)
    w.unmount()
  })

  it('saves setup_complete from a non-Home route once a tool is connected and set up', async () => {
    const w = await mountLayout(
      {},
      startListPayload({
        tool_connected: { done: true, live: true, tool_name: 'Claude' },
        skills_installed: { done: true },
      }),
    )
    await flushPromises()
    expect(h.patch).toHaveBeenCalledWith({ setup_complete: true })
    expect(h.patch.mock.calls.filter(([p]) => p.setup_complete === true)).toHaveLength(1)
    w.unmount()
  })

  it('does not save it when only the tool is connected', async () => {
    const w = await mountLayout({}, startListPayload({ tool_connected: { done: true, live: true } }))
    expect(h.patch).not.toHaveBeenCalledWith({ setup_complete: true })
    w.unmount()
  })

  it('does not save it when it is already saved', async () => {
    const w = await mountLayout(
      { setup_complete: true },
      startListPayload({ tool_connected: { done: true, live: true }, skills_installed: { done: true } }),
    )
    expect(h.patch).not.toHaveBeenCalled()
    w.unmount()
  })

  it('does not save it while the setup pop-up is open', async () => {
    const w = await mountLayout({}, startListPayload())
    useGuideStore().setupWizardOpen = true
    h.list = startListPayload({
      tool_connected: { done: true, live: true },
      skills_installed: { done: true },
    })
    fire('setup:tool_connected')
    await vi.waitFor(() => expect(h.listCalls).toBeGreaterThan(1), { timeout: 2000 })
    await flushPromises()
    expect(h.patch).not.toHaveBeenCalledWith({ setup_complete: true })
    useGuideStore().setupWizardOpen = false
    await flushPromises()
    expect(h.patch).toHaveBeenCalledWith({ setup_complete: true })
    w.unmount()
  })

  it('a failed save is tried again next time, not lost', async () => {
    h.patch.mockRejectedValueOnce(new Error('offline'))
    const w = await mountLayout(
      {},
      startListPayload({ tool_connected: { done: true, live: true }, skills_installed: { done: true } }),
    )
    await flushPromises()
    fire('setup:tool_connected')
    await vi.waitFor(() => expect(h.patch.mock.calls.filter(([p]) => p.setup_complete).length).toBe(2), {
      timeout: 2000,
    })
    w.unmount()
  })
})

describe('DefaultLayout: the connect pop-up after the intro video', () => {
  beforeEach(() => {
    mem.clear()
    h.ws.clear()
    h.route = { meta: {}, name: 'Tools', path: '/tools' }
    ;[h.patch, h.me, h.push].forEach((m) => m.mockReset())
    h.patch.mockImplementation(async (p) => ({ data: p }))
  })

  it('opens once, through home?openSetup=true, when the video closes and no tool is connected', async () => {
    const w = await mountLayout({ intro_video_seen: false }, startListPayload())
    expect(h.push).not.toHaveBeenCalled()
    w.findComponent(IntroVideoDialog).vm.$emit('close')
    await flushPromises()
    expect(h.push).toHaveBeenCalledWith({ path: '/home', query: { openSetup: 'true' } })
    expect(h.push).toHaveBeenCalledTimes(1)
    w.unmount()
  })

  it('never for a person who already has a tool connected', async () => {
    const w = await mountLayout(
      { intro_video_seen: false },
      startListPayload({ tool_connected: { done: true, live: true, tool_name: 'Claude' } }),
    )
    w.findComponent(IntroVideoDialog).vm.$emit('close')
    await flushPromises()
    expect(h.push).not.toHaveBeenCalled()
    w.unmount()
  })

  it('never on an ordinary page load (the video was seen long ago)', async () => {
    const w = await mountLayout({ intro_video_seen: true }, startListPayload())
    await flushPromises()
    expect(h.push).not.toHaveBeenCalled()
    w.unmount()
  })
})
