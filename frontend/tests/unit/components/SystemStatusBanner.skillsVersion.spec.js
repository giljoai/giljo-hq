// Tests for the skills-version drift surface in SystemStatusBanner.vue.
//
// IMP-5037b rewrite: SystemStatusBanner now renders from bannerNotifications.
// The old API polling (/api/system/status, /check-skills-version) has been
// replaced by notification rows from the backend.
//
// Behaviour under test:
//   - A 'system.skills_drift' banner row in the store shows the drift banner
//     to admins; non-admins never see it (role_filter guard).
//   - Dismissing calls notifStore.markDismissed — no localStorage.
//   - A 'system.update_available' banner row shows the update banner.
//   - A 'system.pending_migrations' banner row shows the migration banner.
//   - Rows with dismissed_at/resolved_at set are not rendered.
//   - Copy comes from the notification row's body/title (backend-set); the
//     component does not generate edition-specific copy itself.
//   - A non-dismissible row (dismissible=false) has no close button.
//   - A dismissible row has a close button that calls markDismissed.
//   - A CTA button calls router.push({ name: cta_route }).

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { useUserStore } from '@/stores/user'
import { useNotificationStore } from '@/stores/notifications'

const mockRouterPush = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockRouterPush }),
  useRoute: () => ({ name: 'Dashboard', meta: {} }),
}))

// configService mock — default CE mode; individual tests override giljoMode.
const mockGiljoMode = { value: 'ce' }
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue(undefined),
    getGiljoMode: vi.fn(() => mockGiljoMode.value),
  },
}))

async function importBanner() {
  const mod = await import('@/components/system/SystemStatusBanner.vue')
  return mod.default
}

function makeSkillsDrift(overrides = {}) {
  return {
    id: 'skills-1',
    type: 'system.skills_drift',
    severity: 'warning',
    title: 'Skills updated to v1.1.12.',
    body: 'Skills updated to v1.1.12. Update with git pull, restart server and run giljo_setup MCP command.',
    surface: 'banner',
    role_filter: 'admin',
    cta_label: 'Go to settings',
    cta_route: 'Tools',
    dismissible: true,
    dismissed_at: null,
    resolved_at: null,
    created_at: '2026-06-03T00:00:00Z',
    ...overrides,
  }
}

function makeUpdateAvailable(overrides = {}) {
  return {
    id: 'update-1',
    type: 'system.update_available',
    severity: 'info',
    title: 'Updates available (5 commits behind).',
    body: 'Updates available (5 commits behind). Run `git pull`, then restart your server.',
    surface: 'banner',
    role_filter: 'admin',
    // FE-6020: links OUT to GitHub releases (no in-app route); URL in payload.
    cta_label: 'View release',
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

function makePendingMigrations(overrides = {}) {
  return {
    id: 'mig-1',
    type: 'system.pending_migrations',
    severity: 'warning',
    title: 'Database needs updating.',
    body: 'Database needs updating. Restart your server to apply pending migrations (or run python update.py).',
    surface: 'banner',
    role_filter: 'admin',
    cta_label: 'Go to settings',
    cta_route: 'Tools',
    dismissible: false,
    dismissed_at: null,
    resolved_at: null,
    created_at: '2026-06-03T00:00:00Z',
    ...overrides,
  }
}

describe('SystemStatusBanner — notification-driven (IMP-5037b)', () => {
  let pinia

  beforeEach(async () => {
    pinia = createPinia()
    setActivePinia(pinia)
    mockRouterPush.mockReset()
    mockGiljoMode.value = 'ce'

    const userStore = useUserStore()
    userStore.currentUser = { id: 1, username: 'admin', role: 'admin' }
  })

  it('shows the drift banner for admin when system.skills_drift row is present', async () => {
    const notifStore = useNotificationStore()
    notifStore.handleWsNewNotification(makeSkillsDrift())

    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toMatch(/Skills updated/i)
  })

  it('hides the drift banner when no skills_drift row is present', async () => {
    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).not.toMatch(/Skills updated/i)
  })

  it('hides the drift banner for non-admin users even when row is present', async () => {
    const userStore = useUserStore()
    userStore.currentUser = { id: 2, username: 'user', role: 'user' }

    const notifStore = useNotificationStore()
    notifStore.handleWsNewNotification(makeSkillsDrift())

    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).not.toMatch(/Skills updated/i)
  })

  it('hides the drift banner when dismissed_at is set on the row', async () => {
    const notifStore = useNotificationStore()
    notifStore.handleWsNewNotification(
      makeSkillsDrift({ dismissed_at: '2026-06-03T01:00:00Z' }),
    )

    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).not.toMatch(/Skills updated/i)
  })

  it('calling dismiss button invokes markDismissed on the store', async () => {
    const notifStore = useNotificationStore()
    notifStore.handleWsNewNotification(makeSkillsDrift())
    const dismissSpy = vi.spyOn(notifStore, 'markDismissed').mockResolvedValue(undefined)

    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    const dismissBtn = wrapper.find('[data-testid="banner-dismiss-btn"]')
    expect(dismissBtn.exists()).toBe(true)
    await dismissBtn.trigger('click')
    expect(dismissSpy).toHaveBeenCalledWith('skills-1')
  })

  it('CE copy (from notification body) includes git pull text', async () => {
    const notifStore = useNotificationStore()
    notifStore.handleWsNewNotification(makeSkillsDrift())

    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    // Body set by backend; CE body includes "git pull"
    expect(wrapper.text()).toMatch(/git pull/i)
  })

  it('SaaS copy (from notification body) does not mention git pull', async () => {
    const notifStore = useNotificationStore()
    // SaaS backend sets different body for skills_drift
    notifStore.handleWsNewNotification(
      makeSkillsDrift({ body: 'Skills updated to v1.1.12. Run giljo_setup MCP command to install.' }),
    )

    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toMatch(/Skills updated/i)
    expect(wrapper.text()).not.toMatch(/git pull/i)
  })

  it('shows update_available banner when row is present', async () => {
    const notifStore = useNotificationStore()
    notifStore.handleWsNewNotification(makeUpdateAvailable())

    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="system-banner"]').exists()).toBe(true)
    expect(wrapper.text()).toMatch(/Updates available/i)
  })

  it('shows pending_migrations banner when row is present', async () => {
    const notifStore = useNotificationStore()
    notifStore.handleWsNewNotification(makePendingMigrations())

    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toMatch(/Database needs updating/i)
  })

  it('pending_migrations is non-dismissible — no close button', async () => {
    const notifStore = useNotificationStore()
    notifStore.handleWsNewNotification(makePendingMigrations({ dismissible: false }))

    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="banner-dismiss-btn"]').exists()).toBe(false)
  })

  it('CTA button fires router.push({ name: "Tools" }) for in-app banners', async () => {
    // FE-6020: pending_migrations still deep-links in-app; update_available now
    // links out to GitHub, so it is no longer the right fixture for this test.
    const notifStore = useNotificationStore()
    notifStore.handleWsNewNotification(makePendingMigrations())

    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="banner-cta-btn"]').trigger('click')
    expect(mockRouterPush).toHaveBeenCalledWith({ name: 'Tools' })
  })

  it('update_available CTA opens GitHub releases externally (FE-6020)', async () => {
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const notifStore = useNotificationStore()
    notifStore.handleWsNewNotification(makeUpdateAvailable())

    const SystemStatusBanner = await importBanner()
    const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="banner-cta-btn"]').trigger('click')
    expect(openSpy).toHaveBeenCalledWith(
      'https://github.com/giljoai/giljo-hq/releases',
      '_blank',
      'noopener',
    )
    expect(mockRouterPush).not.toHaveBeenCalled()
    openSpy.mockRestore()
  })

  // BE-6031c: SaaS defense-in-depth — secondary render guard
  describe('SaaS mode: update_available and pending_migrations excluded', () => {
    it('hides update_available banner in SaaS mode', async () => {
      mockGiljoMode.value = 'saas'
      const notifStore = useNotificationStore()
      notifStore.handleWsNewNotification(makeUpdateAvailable())

      const SystemStatusBanner = await importBanner()
      const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
      await flushPromises()
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[data-testid="system-banner"]').exists()).toBe(false)
    })

    it('hides pending_migrations banner in SaaS mode', async () => {
      mockGiljoMode.value = 'saas'
      const notifStore = useNotificationStore()
      notifStore.handleWsNewNotification(makePendingMigrations())

      const SystemStatusBanner = await importBanner()
      const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
      await flushPromises()
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[data-testid="system-banner"]').exists()).toBe(false)
    })

    it('still shows skills_drift banner in SaaS mode', async () => {
      mockGiljoMode.value = 'saas'
      const notifStore = useNotificationStore()
      notifStore.handleWsNewNotification(makeSkillsDrift())

      const SystemStatusBanner = await importBanner()
      const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia] } })
      await flushPromises()
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[data-testid="system-banner"]').exists()).toBe(true)
      expect(wrapper.text()).toMatch(/Skills updated/i)
    })
  })
})
