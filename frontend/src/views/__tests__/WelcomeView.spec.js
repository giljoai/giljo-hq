import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { PROJECT_TEMPLATES } from '@/composables/projectTemplates'

// ---------- Module mocks ----------

const pushMock = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
}))

const showToastMock = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getRawConfig: vi.fn().mockReturnValue(null),
    getVersion: vi.fn().mockReturnValue('1.3.0'),
  },
}))

vi.mock('@/services/api', () => ({
  default: {
    templates: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      activeCount: vi.fn().mockResolvedValue({ data: { max_slots: 16 } }),
    },
    stats: {
      getDashboard: vi.fn().mockResolvedValue({ data: { recent_projects: [] } }),
    },
  },
}))

// Stub heavy child components so we don't need their full graphs.
vi.mock('@/components/GilMascot.vue', () => ({
  default: { name: 'GilMascot', template: '<div />' },
}))
vi.mock('@/components/setup/SetupWizardOverlay.vue', () => ({
  default: { name: 'SetupWizardOverlay', template: '<div />' },
}))
// FE-9200: the tutorial overlay pulls the whole beats/screens graph — stub it
// like the wizard (its own behavior is covered by tests/unit/components/tutorial/).
vi.mock('@/components/tutorial/TutorialOverlay.vue', () => ({
  default: { name: 'TutorialOverlay', template: '<div />' },
}))
vi.mock('@/components/setup/CertTrustModal.vue', () => ({
  default: { name: 'CertTrustModal', template: '<div />' },
}))
vi.mock('@/components/dashboard/RecentProjectsList.vue', () => ({
  default: { name: 'RecentProjectsList', template: '<div />' },
}))
vi.mock('@/components/projects/ProjectReviewModal.vue', () => ({
  default: { name: 'ProjectReviewModal', template: '<div />' },
}))

// Pinia stores -----------------------------------------------------------

const createProjectMock = vi.fn().mockResolvedValue({ id: 'proj-new' })

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: {
      full_name: 'Test User',
      setup_complete: true,
      learning_complete: true,
      setup_step_completed: 4,
      setup_selected_tools: [],
    },
    updateSetupState: vi.fn().mockResolvedValue(),
  }),
}))

// Mutable so FE-9524's "viewed tab wins over the legacy global slot" test
// (below) can diverge activeProduct from effectiveProductId; every other
// test leaves both at 'prod-1', matching the pre-existing fixture.
const productStoreState = {
  activeProduct: { id: 'prod-1', name: 'Test Product' },
  hasProducts: true,
  effectiveProductId: 'prod-1',
  fetchProducts: vi.fn().mockResolvedValue(),
}

vi.mock('@/stores/products', () => ({
  useProductStore: () => productStoreState,
}))

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    projects: [],
    activeProjects: [],
    fetchProjects: vi.fn().mockResolvedValue(),
    createProject: createProjectMock,
  }),
}))

// Vuetify icons rendered as v-icon — stub globally to avoid plugin setup
const globalStubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
  'router-link': { template: '<a><slot /></a>' },
}

async function mountWelcome() {
  const WelcomeView = (await import('@/views/WelcomeView.vue')).default
  return mount(WelcomeView, {
    global: { stubs: globalStubs },
  })
}

// -----------------------------------------------------------------------

// -----------------------------------------------------------------------
// Footer version label (INF-9115) — must derive from configService.getVersion(),
// never the dead api.stats.getSystem() field that never existed on the response.
// -----------------------------------------------------------------------

describe('WelcomeView — footer version label', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('reads the footer version from configService.getVersion(), not api.stats.getSystem()', async () => {
    const configService = (await import('@/services/configService')).default
    configService.getVersion.mockReturnValue('1.3.0')

    const wrapper = await mountWelcome()
    await flushPromises()

    expect(wrapper.find('.footer-item.mono').text()).toBe('1.3.0')
  })
})

// -----------------------------------------------------------------------
// Cert-modal "Don't show again" persistence (INF-6040)
// -----------------------------------------------------------------------

describe('WelcomeView — cert modal "don\'t show again" localStorage gate', () => {
  // NOTE: tests/setup.js stubs window.localStorage with vi.fn() mocks (not real storage).
  // We work with those stubs: mock getItem return values per-test, assert setItem calls.

  beforeEach(() => {
    setActivePinia(createPinia())
    // Reset localStorage mock return values to default (null = key not present)
    localStorage.getItem.mockReturnValue(null)
    localStorage.setItem.mockReset()
    sessionStorage.clear()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('(a) shouldShowCertModal returns false when localStorage cert_modal_never is set', async () => {
    // Arrange: remote HTTPS client, no session dismissal, but the never-flag is persisted
    const configService = (await import('@/services/configService')).default
    configService.getRawConfig.mockReturnValue({
      api: { ssl_enabled: true, is_remote_client: true },
    })
    // Simulate the device having cert_modal_never='1' in persistent storage
    localStorage.getItem.mockImplementation((key) => {
      if (key === 'cert_modal_never') return '1'
      return null
    })

    const WelcomeView = (await import('@/views/WelcomeView.vue')).default
    const wrapper = mount(WelcomeView, { global: { stubs: globalStubs } })
    await flushPromises()

    expect(wrapper.vm.shouldShowCertModal()).toBe(false)
  })

  it('(b) handleCertContinue with dontShowAgain=true persists cert_modal_never to localStorage', async () => {
    const configService = (await import('@/services/configService')).default
    configService.getRawConfig.mockReturnValue({
      api: { ssl_enabled: true, is_remote_client: true },
    })
    localStorage.getItem.mockReturnValue(null)

    const WelcomeView = (await import('@/views/WelcomeView.vue')).default
    const wrapper = mount(WelcomeView, { global: { stubs: globalStubs } })
    await flushPromises()

    // Simulate parent receiving emit('continue', true) from CertTrustModal
    wrapper.vm.handleCertContinue(true)

    expect(localStorage.setItem).toHaveBeenCalledWith('cert_modal_never', '1')
    expect(sessionStorage.getItem('cert_modal_dismissed')).toBe('1')
  })

  it('(c) handleCertContinue with dontShowAgain=false does NOT set cert_modal_never', async () => {
    const configService = (await import('@/services/configService')).default
    configService.getRawConfig.mockReturnValue({
      api: { ssl_enabled: true, is_remote_client: true },
    })
    localStorage.getItem.mockReturnValue(null)

    const WelcomeView = (await import('@/views/WelcomeView.vue')).default
    const wrapper = mount(WelcomeView, { global: { stubs: globalStubs } })
    await flushPromises()

    // Simulate clicking Continue without checking the box
    wrapper.vm.handleCertContinue(false)

    expect(localStorage.setItem).not.toHaveBeenCalledWith('cert_modal_never', '1')
    expect(sessionStorage.getItem('cert_modal_dismissed')).toBe('1')
  })

  it('(c2) shouldShowCertModal respects ssl_enabled && is_remote_client gate without never-flag', async () => {
    const configService = (await import('@/services/configService')).default
    // Returns true when both flags are set and neither storage key is set
    configService.getRawConfig.mockReturnValue({
      api: { ssl_enabled: true, is_remote_client: true },
    })
    localStorage.getItem.mockReturnValue(null)

    const WelcomeView = (await import('@/views/WelcomeView.vue')).default
    const wrapper = mount(WelcomeView, { global: { stubs: globalStubs } })
    await flushPromises()

    expect(wrapper.vm.shouldShowCertModal()).toBe(true)
  })

  it('(c3) shouldShowCertModal returns false when session is dismissed (existing behavior unchanged)', async () => {
    const configService = (await import('@/services/configService')).default
    configService.getRawConfig.mockReturnValue({
      api: { ssl_enabled: true, is_remote_client: true },
    })
    localStorage.getItem.mockReturnValue(null)
    sessionStorage.setItem('cert_modal_dismissed', '1')

    const WelcomeView = (await import('@/views/WelcomeView.vue')).default
    const wrapper = mount(WelcomeView, { global: { stubs: globalStubs } })
    await flushPromises()

    expect(wrapper.vm.shouldShowCertModal()).toBe(false)
  })
})

// -----------------------------------------------------------------------

describe('WelcomeView — step-4 template-card bootstrap', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    pushMock.mockClear()
    createProjectMock.mockClear()
    createProjectMock.mockResolvedValue({ id: 'proj-new' })
    showToastMock.mockClear()
    productStoreState.activeProduct = { id: 'prod-1', name: 'Test Product' }
    productStoreState.effectiveProductId = 'prod-1'
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('FE-9524/D1: template create uses the VIEWED tab, not the legacy activeProduct slot, when they diverge', async () => {
    // Several products may be shown at once; activeProduct is now just the
    // most-recently-shown one, not necessarily the tab on screen.
    productStoreState.activeProduct = { id: 'prod-other-shown', name: 'Some Other Shown Product' }
    productStoreState.effectiveProductId = 'prod-1'

    const wrapper = await mountWelcome()
    await flushPromises()

    const card = wrapper.find(`[data-template-id="${PROJECT_TEMPLATES[0].id}"]`)
    await card.trigger('click')
    await flushPromises()

    expect(createProjectMock).toHaveBeenCalledWith(
      expect.objectContaining({ product_id: 'prod-1' }),
    )
  })

  it('renders three quick-launch cards in order: [newProjectCard, template[0], template[1]]', async () => {
    const wrapper = await mountWelcome()
    await flushPromises()

    const cards = wrapper.findAll('.quick-card')
    expect(cards).toHaveLength(3)

    // First card: blank-slate "New Project" — no data-template-id attr
    expect(cards[0].attributes('data-template-id')).toBeFalsy()
    expect(cards[0].text()).toContain('New Project')

    // Second + third: template cards in PROJECT_TEMPLATES order
    expect(cards[1].attributes('data-template-id')).toBe(PROJECT_TEMPLATES[0].id)
    expect(cards[1].text()).toContain(PROJECT_TEMPLATES[0].cardTitle)

    expect(cards[2].attributes('data-template-id')).toBe(PROJECT_TEMPLATES[1].id)
    expect(cards[2].text()).toContain(PROJECT_TEMPLATES[1].cardTitle)
  })

  it('clicking each template card calls projectStore.createProject with the verbatim template payload', async () => {
    const wrapper = await mountWelcome()
    await flushPromises()

    for (let i = 0; i < PROJECT_TEMPLATES.length; i += 1) {
      const tmpl = PROJECT_TEMPLATES[i]
      const card = wrapper.find(`[data-template-id="${tmpl.id}"]`)
      expect(card.exists()).toBe(true)

      await card.trigger('click')
      await flushPromises()

      expect(createProjectMock).toHaveBeenCalledWith({
        name: tmpl.projectName,
        description: tmpl.projectDescription,
        product_id: 'prod-1',
      })
    }
    expect(createProjectMock).toHaveBeenCalledTimes(PROJECT_TEMPLATES.length)
    // Each successful template create routes to /Projects (matching newProjectCard).
    expect(pushMock).toHaveBeenCalledWith('/Projects')
  })

  it('clicking "New Project" card still triggers the existing manual flow (router push to /Projects)', async () => {
    const wrapper = await mountWelcome()
    await flushPromises()

    const newProjectCard = wrapper.findAll('.quick-card')[0]
    await newProjectCard.trigger('click')
    await flushPromises()

    expect(createProjectMock).not.toHaveBeenCalled()
    expect(pushMock).toHaveBeenCalledWith('/Projects')
  })

  it('surfaces a toast when createProject fails and clears the busy state', async () => {
    createProjectMock.mockRejectedValueOnce(new Error('boom'))
    const wrapper = await mountWelcome()
    await flushPromises()

    const card = wrapper.find(`[data-template-id="${PROJECT_TEMPLATES[0].id}"]`)
    await card.trigger('click')
    await flushPromises()

    expect(showToastMock).toHaveBeenCalledTimes(1)
    expect(showToastMock.mock.calls[0][0].color).toBe('error')

    // Busy class should be cleared after the rejection resolves.
    expect(card.classes()).not.toContain('quick-card--busy')
  })
})
