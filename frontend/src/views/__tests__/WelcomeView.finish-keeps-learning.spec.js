import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

const routeState = vi.hoisted(() => ({ query: {} }))
const h = vi.hoisted(() => ({
  store: null,
  patchDelayMs: 0,
  calls: [],
  t0: 0,
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getRawConfig: vi.fn().mockReturnValue(null),
    getVersion: vi.fn().mockReturnValue('probe'),
  },
}))
vi.mock('@/services/api', () => ({
  default: {
    templates: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      activeCount: vi.fn().mockResolvedValue({ data: { max_slots: 16 } }),
    },
    stats: { getDashboard: vi.fn().mockResolvedValue({ data: { recent_projects: [] } }) },
    connect: { credentialStatus: vi.fn().mockResolvedValue({ data: {} }) },
  },
}))
vi.mock('@/components/GilMascot.vue', () => ({ default: { name: 'GilMascot', template: '<div />' } }))
vi.mock('@/components/dashboard/RecentProjectsList.vue', () => ({
  default: { name: 'RecentProjectsList', template: '<div />' },
}))
vi.mock('@/components/projects/ProjectReviewModal.vue', () => ({
  default: { name: 'ProjectReviewModal', template: '<div />' },
}))
vi.mock('@/components/tutorial/TutorialOverlay.vue', () => ({
  default: {
    name: 'TutorialOverlay',
    props: ['modelValue', 'startOver'],
    emits: ['dismiss', 'update:modelValue'],
    template:
      '<div data-testid="tour-stub" :data-open="String(modelValue)">' +
      '<button data-testid="tour-exit" @click="$emit(\'dismiss\'); $emit(\'update:modelValue\', false)" />' +
      '</div>',
  },
}))

vi.mock('@/stores/user', async () => {
  const { reactive } = await import('vue')
  const currentUser = reactive({})
  const store = {
    currentUser,
    updateSetupState: vi.fn(async (payload) => {
      h.calls.push({ atMs: Date.now() - h.t0, payload: { ...payload } })
      if (h.patchDelayMs) await new Promise((r) => setTimeout(r, h.patchDelayMs))
      Object.assign(currentUser, payload)
      return payload
    }),
  }
  h.store = store
  return { useUserStore: () => store }
})
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    activeProduct: null,
    hasProducts: false,
    effectiveProductId: null,
    fetchProducts: vi.fn().mockResolvedValue(),
  }),
}))
vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({ projects: [], activeProjects: [], fetchProjects: vi.fn().mockResolvedValue() }),
}))

const stubs = {
  teleport: true,
  SetupStep2Connect: { template: '<div />' },
  'v-btn': { template: '<button v-bind="$attrs"><slot /></button>' },
  'v-icon': { template: '<i><slot /></i>' },
  'v-dialog': { template: '<div><slot /></div>' },
  'v-card': { template: '<div><slot /></div>' },
  'v-card-text': { template: '<div><slot /></div>' },
  'v-spacer': { template: '<span />' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
  'router-link': { template: '<a><slot /></a>' },
}

async function settle() {
  for (let i = 0; i < 20; i++) await Promise.resolve()
  await nextTick()
  for (let i = 0; i < 20; i++) await Promise.resolve()
}

async function mountHomeForNewPerson() {
  Object.keys(h.store?.currentUser || {}).forEach((k) => delete h.store.currentUser[k])
  const WelcomeView = (await import('@/views/WelcomeView.vue')).default
  Object.assign(h.store.currentUser, {
    full_name: 'New Person',
    setup_complete: false,
    learning_complete: false,
    setup_step_completed: 1,
    setup_selected_tools: ['claude_code'],
  })
  if (!routeState.query.openGuide) routeState.query = { openSetup: 'true' }
  const wrapper = mount(WelcomeView, { global: { stubs } })
  await settle()
  routeState.query = {}
  return wrapper
}

const tourOpen = (w) => w.find('[data-testid="tour-stub"]').attributes('data-open')
const learningSaves = () => h.calls.filter((c) => c.payload.learning_complete === true)

describe('WelcomeView + SetupWizardOverlay: learning_complete is only written by a tour exit', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    h.calls.length = 0
    h.patchDelayMs = 0
    h.t0 = Date.now()
    routeState.query = {}
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('Skip on Connect closes the pop-up, saves no learning flag, opens NO tour, and Home still shows Quick Launch', async () => {
    const w = await mountHomeForNewPerson()
    await w.find('[data-testid="connect-skip"]').trigger('click')
    await settle()
    await vi.advanceTimersByTimeAsync(3000)
    await settle()
    expect(learningSaves()).toHaveLength(0)
    expect(tourOpen(w)).toBe('false')
    expect(w.find('[data-testid="setup-wizard-overlay"]').exists()).toBe(false)
    expect(w.text()).toContain('Quick Launch')
    expect(h.store.currentUser.learning_complete).toBe(false)
    expect(h.store.currentUser.setup_complete).toBe(false)
  })

  it('a tour exit (the tour reached from Tools > Startup > Learning) saves learning_complete exactly once', async () => {
    routeState.query = { openGuide: 'true' }
    const w = await mountHomeForNewPerson()
    routeState.query = {}
    expect(tourOpen(w)).toBe('true')
    await w.find('[data-testid="tour-exit"]').trigger('click')
    await settle()
    expect(learningSaves()).toHaveLength(1)
    expect(h.store.currentUser.learning_complete).toBe(true)
    expect(tourOpen(w)).toBe('false')
  })

  it('X on Connect closes the pop-up, opens NO tour, saves no learning flag, shows Quick Launch', async () => {
    const w = await mountHomeForNewPerson()
    await w.find('[aria-label="Close setup wizard"]').trigger('click')
    await settle()
    await vi.advanceTimersByTimeAsync(3000)
    await settle()
    expect(learningSaves()).toHaveLength(0)
    expect(tourOpen(w)).toBe('false')
    expect(w.text()).toContain('Quick Launch')
    expect(h.store.currentUser.setup_complete).toBe(false)
  })

  it('a slow save on Skip still saves no learning flag', async () => {
    h.patchDelayMs = 2000
    const w = await mountHomeForNewPerson()
    await w.find('[data-testid="connect-skip"]').trigger('click')
    await settle()
    await vi.advanceTimersByTimeAsync(8000)
    await settle()
    expect(learningSaves()).toHaveLength(0)
    expect(tourOpen(w)).toBe('false')
    expect(w.text()).toContain('Quick Launch')
  })

  it('a returning person closing the re-run wizard leaves learning_complete alone', async () => {
    routeState.query = { openSetup: 'true' }
    const WelcomeView = (await import('@/views/WelcomeView.vue')).default
    Object.keys(h.store.currentUser).forEach((k) => delete h.store.currentUser[k])
    Object.assign(h.store.currentUser, {
      full_name: 'Returning Person',
      setup_complete: true,
      learning_complete: true,
      setup_step_completed: 4,
      setup_selected_tools: ['claude_code'],
    })
    const w = mount(WelcomeView, { global: { stubs } })
    await settle()
    routeState.query = {}
    expect(tourOpen(w)).toBe('false')
    const x = w.find('[aria-label="Close setup wizard"]')
    expect(x.exists()).toBe(true)
    await x.trigger('click')
    await settle()
    await vi.advanceTimersByTimeAsync(3000)
    await settle()
    expect(h.calls.filter((c) => 'learning_complete' in c.payload)).toHaveLength(0)
    expect(h.store.currentUser.learning_complete).toBe(true)
    expect(tourOpen(w)).toBe('false')
  })
})
