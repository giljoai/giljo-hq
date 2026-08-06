/**
 * Vitest specs for IMP-5037b banner rewrite — CE component only.
 *
 * SaaS banner specs live in tests/saas/banners.imp5037b.spec.js
 * (CE code must not import from saas/ directories).
 *
 * Covers SystemStatusBanner (CE):
 *  1. renders when a matching banner row is present in the store
 *  2. hidden when no matching row
 *  3. hidden when dismissed_at is set
 *  4. hidden when resolved_at is set
 *  5. CTA fires router.push({ name: <cta_route> }) — named route only
 *  6. non-dismissible banners expose NO close button
 *  7. dismissible banners show a close button; click calls markDismissed
 *  8. admin guard: role_filter='admin' rows hidden for non-admin users
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

// ---------------------------------------------------------------------------
// Router mock
// ---------------------------------------------------------------------------
const mockRouterPush = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockRouterPush }),
  useRoute: () => ({ name: 'Dashboard', meta: {} }),
}))

// ---------------------------------------------------------------------------
// Notification store helpers
// ---------------------------------------------------------------------------
import { useNotificationStore } from '@/stores/notifications'

function makeSystemBanner(overrides = {}) {
  return {
    id: 'sys-1',
    type: 'system.update_available',
    severity: 'info',
    title: 'Updates available (5 commits behind). Run `git pull`, then restart your server.',
    body: 'Updates available (5 commits behind). Run `git pull`, then restart your server.',
    surface: 'banner',
    role_filter: 'admin',
    cta_label: 'View release',
    // FE-6020: update_available links OUT to GitHub (no in-app route); the URL
    // rides in the payload.
    cta_route: null,
    payload: {
      commits_behind: 5,
      release_url: 'https://github.com/giljoai/giljo-hq/releases',
      tag: null,
    },
    dismissible: true,
    dismissed_at: null,
    resolved_at: null,
    created_at: '2026-06-03T00:00:00Z',
    ...overrides,
  }
}

/** A banner that deep-links to an in-app route (skills_drift still uses Tools). */
function makeRouteBanner(overrides = {}) {
  return makeSystemBanner({
    id: 'drift-1',
    type: 'system.skills_drift',
    cta_label: 'Update bundle',
    cta_route: 'Tools',
    payload: null,
    ...overrides,
  })
}

// ---------------------------------------------------------------------------
// Mount helper
// ---------------------------------------------------------------------------
function mountWithPinia(component, pinia) {
  return mount(component, { global: { plugins: [pinia] } })
}

// ---------------------------------------------------------------------------
// SystemStatusBanner — CE
// ---------------------------------------------------------------------------
describe('SystemStatusBanner (CE) — notification-driven', () => {
  let pinia

  beforeEach(async () => {
    pinia = createPinia()
    setActivePinia(pinia)
    mockRouterPush.mockReset()

    // Set up admin user so admin-gated banners render
    const { useUserStore } = await import('@/stores/user')
    const userStore = useUserStore()
    userStore.currentUser = { id: 1, username: 'admin', role: 'admin' }
  })

  it('renders when a system.update_available banner row is in the store', async () => {
    const store = useNotificationStore()
    store.handleWsNewNotification(makeSystemBanner())

    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="system-banner"]').exists()).toBe(true)
  })

  it('renders nothing when no banner notifications', async () => {
    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="system-banner"]').exists()).toBe(false)
  })

  it('hidden when the banner notification has dismissed_at set', async () => {
    const store = useNotificationStore()
    store.handleWsNewNotification(
      makeSystemBanner({ dismissed_at: '2026-06-03T05:00:00Z' }),
    )

    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="system-banner"]').exists()).toBe(false)
  })

  it('hidden when the banner notification has resolved_at set', async () => {
    const store = useNotificationStore()
    store.handleWsNewNotification(
      makeSystemBanner({ id: 'res-sys', resolved_at: '2026-06-03T06:00:00Z' }),
    )

    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="system-banner"]').exists()).toBe(false)
  })

  it('CTA button fires router.push({ name: cta_route }) for in-app banners', async () => {
    const store = useNotificationStore()
    store.handleWsNewNotification(makeRouteBanner())

    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    const ctaBtn = wrapper.find('[data-testid="banner-cta-btn"]')
    expect(ctaBtn.exists()).toBe(true)
    await ctaBtn.trigger('click')
    expect(mockRouterPush).toHaveBeenCalledWith({ name: 'Tools' })
  })

  // FE-6020: the update-available banner links OUT to GitHub releases (the
  // upgrade happens in the user's terminal), NOT to an in-app route.
  it('update_available CTA opens GitHub releases externally, not router.push', async () => {
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const store = useNotificationStore()
    store.handleWsNewNotification(makeSystemBanner())

    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    const ctaBtn = wrapper.find('[data-testid="banner-cta-btn"]')
    expect(ctaBtn.exists()).toBe(true)
    await ctaBtn.trigger('click')
    expect(openSpy).toHaveBeenCalledWith(
      'https://github.com/giljoai/giljo-hq/releases',
      '_blank',
      'noopener',
    )
    expect(mockRouterPush).not.toHaveBeenCalled()
    openSpy.mockRestore()
  })

  // FE-6020: update_available with no payload release_url falls back to the
  // releases landing page rather than rendering a dead button.
  it('update_available CTA falls back to releases page when payload lacks a URL', async () => {
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const store = useNotificationStore()
    store.handleWsNewNotification(makeSystemBanner({ payload: { commits_behind: 3 } }))

    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="banner-cta-btn"]').trigger('click')
    expect(openSpy).toHaveBeenCalledWith(
      'https://github.com/giljoai/giljo-hq/releases',
      '_blank',
      'noopener',
    )
    openSpy.mockRestore()
  })

  it('dismissible banner shows a close button', async () => {
    const store = useNotificationStore()
    store.handleWsNewNotification(makeSystemBanner({ dismissible: true }))

    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="banner-dismiss-btn"]').exists()).toBe(true)
  })

  it('non-dismissible banner has no close button', async () => {
    const store = useNotificationStore()
    store.handleWsNewNotification(
      makeSystemBanner({ id: 'mig-1', type: 'system.pending_migrations', dismissible: false }),
    )

    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="banner-dismiss-btn"]').exists()).toBe(false)
  })

  it('dismiss button calls markDismissed on the store', async () => {
    const store = useNotificationStore()
    store.handleWsNewNotification(makeSystemBanner({ dismissible: true }))
    const dismissSpy = vi.spyOn(store, 'markDismissed').mockResolvedValue(undefined)

    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="banner-dismiss-btn"]').trigger('click')
    expect(dismissSpy).toHaveBeenCalledWith('sys-1')
  })

  it('admin-only banner hidden for non-admin users', async () => {
    // Override user to non-admin
    const { useUserStore } = await import('@/stores/user')
    const userStore = useUserStore()
    userStore.currentUser = { id: 2, username: 'regular', role: 'user' }

    const store = useNotificationStore()
    store.handleWsNewNotification(makeSystemBanner({ role_filter: 'admin' }))

    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="system-banner"]').exists()).toBe(false)
  })

  // FE-6011 regression: CE system banners must route to the Tools page (/tools),
  // not SystemSettings (/admin/settings). The backend emits cta_route='Tools' and
  // the component navigates via router.push({ name: n.cta_route }).
  it('FE-6011 regression: CE system banner CTA navigates to route "Tools" (not "SystemSettings")', async () => {
    const store = useNotificationStore()
    // An in-app banner (skills_drift) with cta_route='Tools' — this asserts the
    // correct route name flows through to router.push, proving FE-6011 is wired
    // end-to-end. (update_available now links out to GitHub, so it is no longer
    // the right fixture for an in-app routing assertion — see FE-6020.)
    store.handleWsNewNotification(makeRouteBanner())

    const { default: SystemStatusBanner } = await import(
      '@/components/system/SystemStatusBanner.vue'
    )
    const wrapper = mountWithPinia(SystemStatusBanner, pinia)
    await flushPromises()
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="banner-cta-btn"]').trigger('click')
    // Must navigate to 'Tools' (/tools), NOT 'SystemSettings' (/admin/settings)
    expect(mockRouterPush).toHaveBeenCalledWith({ name: 'Tools' })
    expect(mockRouterPush).not.toHaveBeenCalledWith({ name: 'SystemSettings' })
  })
})
