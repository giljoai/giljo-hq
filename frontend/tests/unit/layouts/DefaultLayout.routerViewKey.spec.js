/**
 * FE-9000e — DefaultLayout.vue:22 router-view keying.
 *
 * Regression coverage at the layer the bug lives (the layout's router-view
 * :key expression), using a REAL router + REAL route records so remount vs.
 * instance-reuse can be observed directly (mount/unmount lifecycle hooks),
 * rather than asserting on the key string.
 *
 * Three behaviors, matching the WO-9000E constraints:
 * 1. Param-only nav within the SAME route record (e.g. chain-tab project
 *    switch /projects/A -> /projects/B) must REUSE the component instance
 *    (FE-6174b behavior — ProjectTabs/the view must not unmount).
 * 2. Nav to a DIFFERENT route record must still remount (dc2bbf197 stays
 *    dead — a route-record change is a real navigation, not a param tweak).
 * 3. Query-only nav on the SAME route must NOT remount (710bc6c32 stays
 *    fixed — welcome-overlay flash regression).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { h, onMounted, onUnmounted } from 'vue'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import api from '@/services/api'

vi.mock('@/services/api', () => ({
  default: {
    auth: { me: vi.fn() },
  },
}))

vi.mock('@/components/navigation/NavigationDrawer.vue', () => ({
  default: {
    name: 'NavigationDrawer',
    template: '<div>NavigationDrawer</div>',
    props: ['modelValue', 'rail', 'currentUser'],
    emits: ['update:modelValue', 'toggle-rail'],
  },
}))

vi.mock('@/components/ToastManager.vue', () => ({
  default: { name: 'ToastManager', template: '<div>ToastManager</div>' },
}))

vi.mock('@/components/LicensingDialog.vue', () => ({
  __esModule: true,
  default: { name: 'LicensingDialog', template: '<div>LicensingDialog</div>', __isTeleport: false, __isSuspense: false },
}))

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on: vi.fn(() => vi.fn()),
    connect: vi.fn().mockResolvedValue(),
    disconnect: vi.fn(),
  }),
}))

vi.mock('@/stores/websocketEventRouter', () => ({
  initWebsocketEventRouter: vi.fn(),
  registerReconnectResync: vi.fn(() => vi.fn()),
}))

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    fetchProjects: vi.fn().mockResolvedValue(),
  }),
}))

const mockFetch = vi.fn()
global.fetch = mockFetch

// Lifecycle counters reset per-test. onMounted stamps a fresh incrementing id
// on this component instance -- if it's the SAME instance across a nav, the
// rendered id stays put; if it's a NEW instance, the id changes.
let mountCalls
let unmountCalls
let nextInstanceId

function makeTrackedView(label) {
  return {
    name: label,
    props: ['currentUser'],
    setup() {
      const id = ++nextInstanceId
      mountCalls++
      onMounted(() => {})
      onUnmounted(() => {
        unmountCalls++
      })
      return () => h('div', { class: 'tracked-view' }, String(id))
    },
  }
}

describe('DefaultLayout.vue router-view keying (FE-9000e)', () => {
  let vuetify
  let wrapper
  let router
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vuetify = createVuetify({ components, directives })
    mountCalls = 0
    unmountCalls = 0
    nextInstanceId = 0

    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/items/:id',
          name: 'Item',
          component: makeTrackedView('TrackedItemView'),
          meta: { layout: 'default', requiresAuth: true },
        },
        {
          path: '/other',
          name: 'Other',
          component: { name: 'OtherView', template: '<div class="other-view">other</div>' },
          meta: { layout: 'default', requiresAuth: true },
        },
      ],
    })

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ is_fresh_install: false }),
    })
    api.auth.me.mockResolvedValue({ data: { username: 'admin', role: 'admin' } })
  })

  afterEach(() => {
    if (wrapper) wrapper.unmount()
    vi.clearAllMocks()
  })

  async function mountAt(location) {
    await router.push(location)
    wrapper = mount(DefaultLayout, {
      global: { plugins: [vuetify, router, pinia] },
    })
    await flushPromises()
  }

  it('reuses the component instance on a param-only nav within the same route record (chain-tab project switch)', async () => {
    await mountAt('/items/1')
    const firstId = wrapper.get('.tracked-view').text()
    expect(unmountCalls).toBe(0)

    await router.push('/items/2')
    await flushPromises()

    const secondId = wrapper.get('.tracked-view').text()
    expect(secondId).toBe(firstId) // same instance -- not remounted
    expect(unmountCalls).toBe(0)
    expect(mountCalls).toBe(1)
  })

  it('remounts when navigating to a different route record', async () => {
    await mountAt('/items/1')
    expect(unmountCalls).toBe(0)

    await router.push('/other')
    await flushPromises()

    expect(unmountCalls).toBe(1)
    expect(wrapper.find('.tracked-view').exists()).toBe(false)
    expect(wrapper.find('.other-view').exists()).toBe(true)
  })

  it('does not remount on a query-only nav within the same route (welcome-overlay flash stays dead)', async () => {
    await mountAt('/items/1')
    const firstId = wrapper.get('.tracked-view').text()

    await router.push({ path: '/items/1', query: { tab: 'startup' } })
    await flushPromises()

    const secondId = wrapper.get('.tracked-view').text()
    expect(secondId).toBe(firstId)
    expect(unmountCalls).toBe(0)
    expect(mountCalls).toBe(1)
  })
})
