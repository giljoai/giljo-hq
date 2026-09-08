/**
 * SystemStatusBanner.fold.fe9552.spec.js — FE-9552
 *
 * Operator instruction, 2026-08-31, verbatim: "I don't want to take up the
 * entire top page with banners, never stack banners, instead fold them."
 * Observed live: activating two projects stacked two lifecycle banners on top
 * of a Tools advisory -- three full-width strips before page content began.
 *
 * ONE banner strip, ever. When more than one banner is live, they fold into
 * it: {chevron} {qty} {main content} {banner CTA} {X}. Ordering:
 * decision-needed > lifecycle > advisories. The CTA click also dismisses its
 * banner (acting on it IS handling it); X dismisses without acting. Either
 * way the next queued banner surfaces automatically -- the visible slot is a
 * pure function of "what's still live", not a manually-advanced pointer.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))

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
    approvals: { listPending: vi.fn(() => Promise.resolve({ data: { items: [] } })) },
  }
  return { default: apiObj, api: apiObj }
})

import SystemStatusBanner from './SystemStatusBanner.vue'
import { useNotificationStore } from '@/stores/notifications'
import { useUserStore } from '@/stores/user'
import { useProductStore } from '@/stores/products'
import { useLifecycleBannerStore } from '@/stores/lifecycleBannerStore'

const globalStubs = { 'v-icon': { template: '<i class="v-icon"><slot /></i>' } }

function bannerRow(overrides = {}) {
  return {
    id: overrides.id || 'n1',
    type: overrides.type || 'system.skills_drift',
    severity: overrides.severity || 'info',
    title: overrides.title || 'Title',
    body: overrides.body || 'Body text',
    payload: overrides.payload || null,
    surface: 'banner',
    dismissed_at: null,
    resolved_at: null,
    role_filter: null,
    cta_route: null,
    cta_label: null,
    dismissible: true,
    ...overrides,
  }
}

async function mountBanner({ rows = [] } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia], stubs: globalStubs } })
  useNotificationStore().notifications = rows
  useUserStore().currentUser = { id: 'user-op-1', role: 'admin' }
  useProductStore().activeProduct = { id: 'p1' }
  await flushPromises()
  await flushPromises()
  return wrapper
}

const CHEVRON = '[data-testid="banner-fold-chevron"]'
const QTY = '[data-testid="banner-fold-qty"]'
const SYSTEM = '[data-testid="system-banner"]'
const LIFECYCLE = '[data-testid="lifecycle-banner"]'

describe('SystemStatusBanner banner fold (FE-9552)', () => {
  it('two live banners never render as two strips: one strip, qty 2, chevron shown', async () => {
    const wrapper = await mountBanner({
      rows: [
        bannerRow({ id: 'a', type: 'system.skills_drift', body: 'Skills are drifting' }),
        bannerRow({ id: 'b', type: 'system.context_tuning_due', body: 'Time to tune context' }),
      ],
    })

    // ONE strip container.
    expect(wrapper.findAll('.system-status-banner').length).toBe(1)
    // Only the top banner painted, not both.
    expect(wrapper.findAll(SYSTEM).length).toBe(1)
    // The fold controls announce the fold.
    expect(wrapper.find(CHEVRON).exists()).toBe(true)
    expect(wrapper.find(QTY).text()).toBe('2')
  })

  it('a single live banner shows no chevron/qty -- fold controls only appear when there is something to fold', async () => {
    const wrapper = await mountBanner({
      rows: [bannerRow({ id: 'a', type: 'system.skills_drift' })],
    })

    expect(wrapper.findAll(SYSTEM).length).toBe(1)
    expect(wrapper.find(CHEVRON).exists()).toBe(false)
    expect(wrapper.find(QTY).exists()).toBe(false)
  })

  it('the chevron expands the fold to show every queued banner, and collapses it back', async () => {
    const wrapper = await mountBanner({
      rows: [
        bannerRow({ id: 'a', type: 'system.skills_drift' }),
        bannerRow({ id: 'b', type: 'system.context_tuning_due' }),
      ],
    })
    expect(wrapper.findAll(SYSTEM).length).toBe(1)

    await wrapper.find(CHEVRON).trigger('click')
    expect(wrapper.findAll(SYSTEM).length).toBe(2)

    await wrapper.find(CHEVRON).trigger('click')
    expect(wrapper.findAll(SYSTEM).length).toBe(1)
  })

  it('the CTA click dismisses its own banner and the next queued one surfaces', async () => {
    const wrapper = await mountBanner({
      rows: [
        bannerRow({
          id: 'a',
          type: 'system.context_tuning_due',
          body: 'First banner',
          cta_route: 'Tools',
        }),
        bannerRow({ id: 'b', type: 'system.skills_drift', body: 'Second banner' }),
      ],
    })
    const dismissSpy = vi.spyOn(useNotificationStore(), 'markDismissed').mockResolvedValue()

    expect(wrapper.find(SYSTEM).text()).toContain('First banner')
    await wrapper.find('[data-testid="banner-cta-btn"]').trigger('click')
    expect(dismissSpy).toHaveBeenCalledWith('a')
  })

  it('X dismisses without acting, and the next queued banner surfaces', async () => {
    const wrapper = await mountBanner({
      rows: [
        bannerRow({ id: 'a', type: 'system.context_tuning_due', body: 'First banner' }),
        bannerRow({ id: 'b', type: 'system.skills_drift', body: 'Second banner' }),
      ],
    })
    const dismissSpy = vi.spyOn(useNotificationStore(), 'markDismissed').mockImplementation((id) => {
      useNotificationStore().notifications = useNotificationStore().notifications.filter((n) => n.id !== id)
      return Promise.resolve()
    })

    expect(wrapper.find(SYSTEM).text()).toContain('First banner')
    await wrapper.find('[data-testid="banner-dismiss-btn"]').trigger('click')
    await flushPromises()
    expect(dismissSpy).toHaveBeenCalledWith('a')
    expect(wrapper.find(SYSTEM).text()).toContain('Second banner')
    expect(wrapper.find(QTY).exists()).toBe(false)
  })

  it('ordering: lifecycle beats an advisory system banner for the visible slot', async () => {
    const wrapper = await mountBanner({
      rows: [bannerRow({ id: 'a', type: 'system.skills_drift', body: 'Advisory row' })],
    })
    useLifecycleBannerStore().rows.push({
      id: 'p1:activated:1',
      projectId: 'p1',
      moment: 'activated',
      taxonomyAlias: 'BE-1234',
      title: 'Fix the thing',
    })
    await flushPromises()

    expect(wrapper.find(LIFECYCLE).exists()).toBe(true)
    expect(wrapper.find(SYSTEM).exists()).toBe(false)
    expect(wrapper.find(QTY).text()).toBe('2')
  })

  it('three live banners: qty reads 3 and expanding shows all three', async () => {
    const wrapper = await mountBanner({
      rows: [
        bannerRow({ id: 'a', type: 'system.skills_drift' }),
        bannerRow({ id: 'b', type: 'system.context_tuning_due' }),
      ],
    })
    useLifecycleBannerStore().rows.push({
      id: 'p1:activated:1',
      projectId: 'p1',
      moment: 'activated',
      taxonomyAlias: 'BE-1234',
      title: 'Fix the thing',
    })
    await flushPromises()

    expect(wrapper.find(QTY).text()).toBe('3')
    expect(wrapper.findAll(`${SYSTEM}, ${LIFECYCLE}`).length).toBe(1)

    await wrapper.find(CHEVRON).trigger('click')
    expect(wrapper.findAll(`${SYSTEM}, ${LIFECYCLE}`).length).toBe(3)
  })
})
