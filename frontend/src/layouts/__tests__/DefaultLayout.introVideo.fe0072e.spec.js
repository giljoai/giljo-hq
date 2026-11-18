import { describe, it, expect, beforeEach, vi } from 'vitest'
import { shallowMount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ patch: vi.fn(), me: vi.fn() }))

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    connect: vi.fn(async () => {}),
    disconnect: vi.fn(),
    on: vi.fn(() => () => {}),
    onConnectionChange: () => () => {},
  }),
}))
vi.mock('@/stores/projects', () => ({ useProjectStore: () => ({ refreshList: vi.fn() }) }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ meta: { hideDrawer: true }, name: 'Welcome' }),
  useRouter: () => ({ push: vi.fn(), afterEach: vi.fn() }),
}))
vi.mock('@/services/api', () => {
  const apiObj = { auth: { me: h.me, updateSetupState: h.patch } }
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
import IntroVideoDialog from '@/components/onboarding/IntroVideoDialog.vue'

async function mountLayout(user) {
  h.me.mockResolvedValue({ data: { id: 'user-1', tenant_key: 'tk', ...user } })
  const wrapper = shallowMount(DefaultLayout, {
    global: {
      stubs: { 'router-view': true },
      mocks: { $route: { matched: [], path: '/home' } },
    },
  })
  await flushPromises()
  return wrapper
}
const dialog = (w) => w.findComponent(IntroVideoDialog)

describe('DefaultLayout first-run intro video', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.patch.mockReset()
    h.me.mockReset()
  })

  it('opens the gated pop-up when the account has not seen the video', async () => {
    const w = await mountLayout({ id: 'user-a', intro_video_seen: false })
    expect(dialog(w).props('modelValue')).toBe(true)
    expect(dialog(w).props('gated')).toBe(true)
    w.unmount()
  })

  it('does not open it when the flag is true', async () => {
    const w = await mountLayout({ id: 'user-b', intro_video_seen: true })
    expect(dialog(w).props('modelValue')).toBe(false)
    w.unmount()
  })

  it('does not open it when the session read has no flag at all', async () => {
    const w = await mountLayout({ id: 'user-c' })
    expect(dialog(w).props('modelValue')).toBe(false)
    w.unmount()
  })

  it('closing saves the flag through the setup-state writer and the pop-up goes away', async () => {
    h.patch.mockResolvedValue({ data: { intro_video_seen: true } })
    const w = await mountLayout({ id: 'user-d', intro_video_seen: false })
    dialog(w).vm.$emit('close')
    await flushPromises()
    expect(h.patch).toHaveBeenCalledTimes(1)
    expect(h.patch).toHaveBeenCalledWith({ intro_video_seen: true })
    expect(dialog(w).props('modelValue')).toBe(false)
    w.unmount()
  })

  it('a failed save still closes it for this visit', async () => {
    h.patch.mockRejectedValue(new Error('offline'))
    const w = await mountLayout({ id: 'user-e', intro_video_seen: false })
    dialog(w).vm.$emit('close')
    await flushPromises()
    expect(dialog(w).props('modelValue')).toBe(false)
    w.unmount()
  })

  it('the licensing dialog waits while the video is pending and mounts after it', async () => {
    h.patch.mockResolvedValue({ data: { intro_video_seen: true } })
    const w = await mountLayout({ id: 'user-f', intro_video_seen: false })
    expect(w.find('licensing-dialog-stub').exists()).toBe(false)
    dialog(w).vm.$emit('close')
    await flushPromises()
    expect(w.find('licensing-dialog-stub').exists()).toBe(true)
    w.unmount()
  })
})
