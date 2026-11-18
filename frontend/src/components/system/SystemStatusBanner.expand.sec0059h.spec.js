import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { installBannerGeometry } from '../../../tests/helpers/bannerGeometry'

const h = vi.hoisted(() => ({ push: vi.fn(), mode: { value: 'saas' } }))

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

const geo = installBannerGeometry()

const NOTICE =
  'We updated our Terms of Service and Privacy Policy. The free trial is now one per person, ' +
  'and we describe a small record we keep to apply that rule. Nothing changes for your existing account.'

function row(overrides = {}) {
  return {
    id: 'n1',
    type: 'system.skills_drift',
    severity: 'info',
    title: 'Title',
    body: 'Body text',
    payload: null,
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

const legalRow = () => row({ id: 'legal1', type: 'saas.legal_updated', title: NOTICE, body: null })

async function mountStrip(rows) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(SystemStatusBanner, {
    attachTo: document.body,
    global: {
      plugins: [pinia],
      stubs: { 'v-icon': { template: '<i class="v-icon"><slot /></i>' } },
    },
  })
  useNotificationStore().notifications = rows
  useUserStore().currentUser = { id: 'u1', role: 'admin' }
  useProductStore().activeProduct = { id: 'p1' }
  await flushPromises()
  await flushPromises()
  return wrapper
}

const SYSTEM = '[data-testid="system-banner"]'
const TEXT = '.system-banner-alert__text'
const TOGGLE = '[data-testid="banner-expand-toggle"]'
const CHEVRON = '[data-testid="banner-fold-chevron"]'
const QTY = '[data-testid="banner-fold-qty"]'

describe('SEC-0059h strip: system-notice rows', () => {
  it('legal notice fits: no control, a click on the row changes nothing', async () => {
    geo.fits()
    const w = await mountStrip([legalRow()])
    expect(w.find(SYSTEM).exists()).toBe(true)
    expect(w.find(TOGGLE).exists()).toBe(false)
    await w.find(TEXT).trigger('click')
    expect(w.find(TEXT).classes()).not.toContain('is-expanded')
    w.unmount()
  })

  it('legal notice cut: "More" shows; a click on the text expands and collapses it', async () => {
    geo.cut()
    const w = await mountStrip([legalRow()])
    const toggle = w.find(`${SYSTEM} ${TOGGLE}`)
    expect(toggle.text()).toBe('More')
    expect(toggle.attributes('aria-label')).toBeUndefined()
    expect(w.find(TEXT).attributes('id')).toBeTruthy()
    expect(toggle.attributes('aria-controls')).toBe(w.find(TEXT).attributes('id'))

    await w.find(TEXT).trigger('click')
    expect(w.find(TEXT).classes()).toContain('is-expanded')
    expect(w.find(TEXT).text()).toBe(NOTICE)
    await w.find(TEXT).trigger('click')
    expect(w.find(TEXT).classes()).not.toContain('is-expanded')
    w.unmount()
  })

  it('legal notice cut: dismiss dismisses and does not toggle', async () => {
    geo.cut()
    const w = await mountStrip([legalRow()])
    const spy = vi.spyOn(useNotificationStore(), 'markDismissed').mockResolvedValue()
    await w.find('[data-testid="banner-dismiss-btn"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('legal1')
    expect(w.find(TEXT).classes()).not.toContain('is-expanded')
    w.unmount()
  })

  it('a system row CTA acts and does not toggle', async () => {
    geo.cut()
    const w = await mountStrip([
      row({ id: 's1', cta_route: 'Settings', cta_label: 'Go to settings' }),
    ])
    await w.find('[data-testid="banner-cta-btn"]').trigger('click')
    expect(h.push).toHaveBeenCalled()
    w.unmount()
  })
})

describe('SEC-0059h strip: one chevron, and it is the fold', () => {
  it('with two rows folded, the fold chevron is the only chevron and "More" is text', async () => {
    geo.cut()
    const w = await mountStrip([legalRow(), row({ id: 'sd1', body: 'Skills drifted' })])
    expect(w.findAll(CHEVRON)).toHaveLength(1)
    expect(w.find(QTY).text()).toBe('2')
    const toggle = w.find(TOGGLE)
    expect(toggle.text()).toBe('More')
    expect(toggle.find('.v-icon').exists()).toBe(false)
    w.unmount()
  })

  it('expanding the top row text never changes the fold', async () => {
    geo.cut()
    const w = await mountStrip([legalRow(), row({ id: 'sd1', body: 'Skills drifted' })])
    await w.find(TEXT).trigger('click')
    expect(w.find(TEXT).classes()).toContain('is-expanded')
    expect(w.findAll(SYSTEM)).toHaveLength(1)
    expect(w.find(CHEVRON).attributes('aria-expanded')).toBe('false')
    w.unmount()
  })

  it('the fold chevron folds rows and never toggles a row text', async () => {
    geo.cut()
    const w = await mountStrip([legalRow(), row({ id: 'sd1', body: 'Skills drifted' })])
    await w.find(CHEVRON).trigger('click')
    expect(w.findAll(SYSTEM)).toHaveLength(2)
    for (const t of w.findAll(TEXT)) expect(t.classes()).not.toContain('is-expanded')
    const ids = w.findAll(TEXT).map((t) => t.attributes('id'))
    expect(new Set(ids).size).toBe(2)
    w.findAll(TOGGLE).forEach((t, i) => expect(t.attributes('aria-controls')).toBe(ids[i]))
    w.unmount()
  })

  it('folding resets the rows it hides', async () => {
    geo.cut()
    const w = await mountStrip([legalRow(), row({ id: 'sd1', body: 'Skills drifted' })])
    await w.find(CHEVRON).trigger('click')
    const second = () => w.findAll(SYSTEM)[1]
    await second().find(TEXT).trigger('click')
    expect(second().find(TEXT).classes()).toContain('is-expanded')

    await w.find(CHEVRON).trigger('click')
    expect(w.findAll(SYSTEM)).toHaveLength(1)
    await w.find(CHEVRON).trigger('click')
    expect(second().find(TEXT).classes()).not.toContain('is-expanded')
    w.unmount()
  })
})
