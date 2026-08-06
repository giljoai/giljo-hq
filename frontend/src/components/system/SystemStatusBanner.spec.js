/**
 * SystemStatusBanner.spec.js — FE-9202
 *
 * Locks the unified Gil banner behaviour:
 *  - every server banner row leads with the Gil avatar (voiced as Gil)
 *  - the new system.context_tuning_due row renders + dismisses
 *  - allowed-type gating per edition (CE vs SaaS)
 *  - the folded-in client-armed tutorial "activate your product" row:
 *    arm/retire semantics preserved from the former TutorialActivateBreadcrumb
 *
 * Edition scope: Both
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ACTIVATE_BREADCRUMB_ARMED_EVENT } from '@/composables/useTutorialState'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  clearBreadcrumb: vi.fn(),
  armed: { value: false },
  mode: { value: 'ce' },
  // Onboarding-nudge controls (default: neither card eligible → no fetch).
  integShow: { fn: () => false },
  agentShow: { fn: () => false },
  dismissInteg: vi.fn(),
  dismissAgent: vi.fn(),
  git: { value: false },
  serena: { value: false },
  dist: { value: {} },
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getGiljoMode: vi.fn(() => h.mode.value),
  },
}))

// Spread the REAL module so ACTIVATE_BREADCRUMB_ARMED_EVENT is the genuine
// constant, not a copy: renaming the event at the source must break this spec
// rather than leave it passing against a stale literal. Only the two
// storage-backed functions are stubbed.
vi.mock('@/composables/useTutorialState', async (importOriginal) => ({
  ...(await importOriginal()),
  isActivateBreadcrumbArmed: () => h.armed.value,
  clearActivateBreadcrumb: (...a) => h.clearBreadcrumb(...a),
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
    useIntegrationStatus: () => ({
      gitEnabled: ref(h.git.value),
      serenaEnabled: ref(h.serena.value),
      // FE-9233: these tests all assert POST-resolution behaviour (mountBanner
      // flushes promises before asserting), so the status is resolved. The
      // pending/errored windows are covered in
      // SystemStatusBanner.integ-flash.spec.js.
      resolved: ref(true),
      loading: ref(false),
      refresh: vi.fn().mockResolvedValue(),
    }),
  }
})

vi.mock('@/services/api', () => {
  const apiObj = {
    stats: { getDashboard: vi.fn(() => Promise.resolve({ data: { project_status_dist: h.dist.value } })) },
    notifications: { list: vi.fn(), markRead: vi.fn(), markDismissed: vi.fn() },
  }
  return { default: apiObj, api: apiObj }
})

import SystemStatusBanner from './SystemStatusBanner.vue'
import { useNotificationStore } from '@/stores/notifications'
import { useUserStore } from '@/stores/user'
import { useProductStore } from '@/stores/products'
import { api } from '@/services/api'

const globalStubs = {
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
}

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
    role_filter: overrides.role_filter ?? null,
    cta_route: overrides.cta_route ?? null,
    cta_label: overrides.cta_label ?? null,
    dismissible: overrides.dismissible ?? true,
    ...overrides,
  }
}

async function mountBanner({ rows = [], armed = false, mode = 'ce', activeProduct = null, role = 'admin' } = {}) {
  h.armed.value = armed
  h.mode.value = mode
  const wrapper = mount(SystemStatusBanner, { global: { stubs: globalStubs } })
  const notif = useNotificationStore()
  notif.notifications = rows
  useUserStore().currentUser = { role }
  // effectiveProductId = currentProductId || activeProduct?.id — an activeProduct
  // with an id lets the nudge-input watcher fire the dashboard read.
  useProductStore().activeProduct = activeProduct
  await flushPromises()
  return wrapper
}

describe('SystemStatusBanner (FE-9202 unified Gil banner)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.push.mockClear()
    h.clearBreadcrumb.mockClear()
    h.dismissInteg.mockClear()
    h.dismissAgent.mockClear()
    // Reset nudge controls to "neither eligible".
    h.integShow.fn = () => false
    h.agentShow.fn = () => false
    h.git.value = false
    h.serena.value = false
    h.dist.value = {}
  })

  it('renders the Gil avatar on each server banner row', async () => {
    const wrapper = await mountBanner({ rows: [bannerRow({ type: 'system.skills_drift' })] })
    const row = wrapper.find('[data-testid="system-banner"]')
    expect(row.exists()).toBe(true)
    const avatar = row.find('img.system-banner-alert__avatar')
    expect(avatar.exists()).toBe(true)
    // Built path in prod (/icons/Giljo_YW_Face.svg); Vite inlines the public SVG
    // as a data: URI under vitest — accept either, but lock it to the Gil face.
    expect(avatar.attributes('src')).toMatch(/Giljo_YW_Face\.svg|data:image\/svg/)
  })

  it('renders the context_tuning_due row and dismisses it', async () => {
    const wrapper = await mountBanner({
      rows: [bannerRow({ id: 'ct1', type: 'system.context_tuning_due', body: 'Time for a review', cta_route: 'Tools' })],
    })
    const notif = useNotificationStore()
    const dismissSpy = vi.spyOn(notif, 'markDismissed').mockResolvedValue()

    const row = wrapper.find('[data-testid="system-banner"]')
    expect(row.text()).toContain('Time for a review')
    await row.find('[data-testid="banner-dismiss-btn"]').trigger('click')
    expect(dismissSpy).toHaveBeenCalledWith('ct1')
  })

  it('CE mode shows context_tuning_due; SaaS mode also shows it but hides update/pending', async () => {
    const rows = [
      bannerRow({ id: 'a', type: 'system.context_tuning_due' }),
      bannerRow({ id: 'b', type: 'system.update_available' }),
      bannerRow({ id: 'c', type: 'system.pending_migrations' }),
    ]
    const ce = await mountBanner({ rows, mode: 'ce' })
    expect(ce.findAll('[data-testid="system-banner"]').length).toBe(3)

    setActivePinia(createPinia())
    const saas = await mountBanner({ rows, mode: 'saas' })
    // SaaS allowed set = skills_drift + context_tuning_due; update/pending suppressed.
    expect(saas.findAll('[data-testid="system-banner"]').length).toBe(1)
    expect(saas.text()).not.toContain('update')
  })

  it('shows the tutorial activate row when armed and no active product', async () => {
    const wrapper = await mountBanner({ armed: true, activeProduct: null })
    const row = wrapper.find('[data-testid="tutorial-activate-banner"]')
    expect(row.exists()).toBe(true)
    expect(row.find('img.system-banner-alert__avatar').exists()).toBe(true)
    expect(row.text()).toContain('activate your product')
  })

  it('hides the tutorial activate row when a product is already active', async () => {
    const wrapper = await mountBanner({ armed: true, activeProduct: { id: 'p1' } })
    expect(wrapper.find('[data-testid="tutorial-activate-banner"]').exists()).toBe(false)
  })

  it('hides the tutorial activate row when not armed', async () => {
    const wrapper = await mountBanner({ armed: false, activeProduct: null })
    expect(wrapper.find('[data-testid="tutorial-activate-banner"]').exists()).toBe(false)
  })

  it('tutorial CTA navigates to Products', async () => {
    const wrapper = await mountBanner({ armed: true })
    await wrapper.find('[data-testid="tutorial-activate-cta"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith('/Products')
  })

  it('tutorial dismiss clears the breadcrumb and hides the row', async () => {
    const wrapper = await mountBanner({ armed: true })
    await wrapper.find('[data-testid="tutorial-activate-dismiss"]').trigger('click')
    expect(h.clearBreadcrumb).toHaveBeenCalled()
    expect(wrapper.find('[data-testid="tutorial-activate-banner"]').exists()).toBe(false)
  })

  // FE-9320: the nudge is armed on the way OUT of the tutorial (door C), which
  // happens long after this banner mounted. The banner lives in DefaultLayout,
  // OUTSIDE <router-view> and with no :key, so it never remounts — it read the
  // armed flag once at setup and nothing re-read it for the rest of the
  // session, making the arming inert. The deleted TutorialActivateBreadcrumb
  // only worked because it was mounted INSIDE the views, and router-view IS
  // keyed by route path. Every test above arms BEFORE mounting, so they all
  // miss this. This one arms AFTER.
  it('shows the tutorial activate row when the breadcrumb is armed AFTER mount', async () => {
    const wrapper = await mountBanner({ armed: false, activeProduct: null })
    expect(wrapper.find('[data-testid="tutorial-activate-banner"]').exists()).toBe(false)

    h.armed.value = true
    // The real constant, not a literal: if the emit side renames the event this
    // test must break with it rather than keep passing against a stale copy.
    window.dispatchEvent(new Event(ACTIVATE_BREADCRUMB_ARMED_EVENT))
    await flushPromises()

    expect(wrapper.find('[data-testid="tutorial-activate-banner"]').exists()).toBe(true)
  })

  it('retires the tutorial row on first product activation', async () => {
    const wrapper = await mountBanner({ armed: true, activeProduct: null })
    expect(wrapper.find('[data-testid="tutorial-activate-banner"]').exists()).toBe(true)
    useProductStore().activeProduct = { id: 'p1' }
    await flushPromises()
    expect(wrapper.find('[data-testid="tutorial-activate-banner"]').exists()).toBe(false)
    expect(h.clearBreadcrumb).toHaveBeenCalled()
  })

  // ── Converted onboarding nudges ────────────────────────────────────────────

  it('shows the integration nudge when eligible with projects and integrations off', async () => {
    h.integShow.fn = () => true // composable says eligible (has projects, not dismissed)
    h.git.value = false
    h.serena.value = false
    h.dist.value = { active: 2 } // total > 0 → hasProjects
    const wrapper = await mountBanner({ activeProduct: { id: 'p1' } })
    const row = wrapper.find('[data-testid="onboarding-integration-banner"]')
    expect(row.exists()).toBe(true)
    expect(row.find('img.system-banner-alert__avatar').exists()).toBe(true)
    expect(row.text()).toContain('Git and Serena')
  })

  it('hides the integration nudge when both integrations are enabled', async () => {
    h.integShow.fn = () => true
    h.git.value = true
    h.serena.value = true
    h.dist.value = { active: 2 }
    const wrapper = await mountBanner({ activeProduct: { id: 'p1' } })
    expect(wrapper.find('[data-testid="onboarding-integration-banner"]').exists()).toBe(false)
  })

  it('carries over dismissal: a dismissed integration popup never reappears as a banner', async () => {
    h.integShow.fn = () => false // composable reports it as permanently dismissed
    h.dist.value = { active: 2 }
    const wrapper = await mountBanner({ activeProduct: { id: 'p1' } })
    expect(wrapper.find('[data-testid="onboarding-integration-banner"]').exists()).toBe(false)
  })

  it('integration nudge dismiss persists via the composable and hides the row', async () => {
    h.integShow.fn = () => true
    h.dist.value = { active: 1 }
    const wrapper = await mountBanner({ activeProduct: { id: 'p1' } })
    await wrapper.find('[data-testid="onboarding-integration-dismiss"]').trigger('click')
    expect(h.dismissInteg).toHaveBeenCalled()
    expect(wrapper.find('[data-testid="onboarding-integration-banner"]').exists()).toBe(false)
  })

  it('shows the tune-agents nudge on a completed project', async () => {
    h.agentShow.fn = () => true
    h.dist.value = { completed: 1 }
    const wrapper = await mountBanner({ activeProduct: { id: 'p1' } })
    const row = wrapper.find('[data-testid="onboarding-agent-banner"]')
    expect(row.exists()).toBe(true)
    await row.find('[data-testid="onboarding-agent-dismiss"]').trigger('click')
    expect(h.dismissAgent).toHaveBeenCalled()
    expect(wrapper.find('[data-testid="onboarding-agent-banner"]').exists()).toBe(false)
  })

  it('co-occurrence guard: the tune-agents nudge suppresses the recurring context_tuning_due row', async () => {
    h.agentShow.fn = () => true
    h.dist.value = { completed: 1 }
    const wrapper = await mountBanner({
      rows: [bannerRow({ id: 'ct1', type: 'system.context_tuning_due', body: 'Time for a review' })],
      activeProduct: { id: 'p1' },
    })
    expect(wrapper.find('[data-testid="onboarding-agent-banner"]').exists()).toBe(true)
    // The recurring server banner is held back while the one-shot nudge shows.
    expect(wrapper.find('[data-testid="system-banner"]').exists()).toBe(false)
  })

  it('does not fetch dashboard stats when neither nudge is eligible', async () => {
    // Defaults: integShow/agentShow both false → gated, no fetch.
    const wrapper = await mountBanner({ activeProduct: { id: 'p1' } })
    expect(wrapper.find('[data-testid="onboarding-integration-banner"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="onboarding-agent-banner"]').exists()).toBe(false)
    expect(api.stats.getDashboard).not.toHaveBeenCalled()
  })

  // ── FE-9222: banner CTAs route through the shared notificationRouting map ────

  it('context_tuning_due CTA deep-links to the Products tune dialog for its product', async () => {
    const wrapper = await mountBanner({
      rows: [
        bannerRow({
          id: 'ct1',
          type: 'system.context_tuning_due',
          cta_route: 'Tools', // server emits a bare Tools route; the map overrides it
          cta_label: 'Review context',
          payload: { product_id: 'prod-7', product_name: 'Acme' },
        }),
      ],
    })
    await wrapper.find('[data-testid="banner-cta-btn"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({ name: 'Products', query: { tune: 'prod-7' } })
  })

  it('two-sided regression: a plain system banner still routes to its bare cta_route', async () => {
    const wrapper = await mountBanner({
      rows: [bannerRow({ id: 'sd1', type: 'system.skills_drift', cta_route: 'Tools', payload: null })],
    })
    await wrapper.find('[data-testid="banner-cta-btn"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({ name: 'Tools' })
  })
})
