import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getRawConfig: vi.fn().mockReturnValue(null),
    getVersion: vi.fn().mockReturnValue('1.3.0'),
  },
}))

const templatesList = vi.fn().mockResolvedValue({ data: [] })
const templatesActiveCount = vi.fn().mockResolvedValue({ data: { max_slots: 16 } })
const assignmentsList = vi.fn().mockResolvedValue({ data: { assignments: [], count: 0 } })

vi.mock('@/services/api', () => ({
  default: {
    templates: {
      list: (...a) => templatesList(...a),
      activeCount: (...a) => templatesActiveCount(...a),
    },
    assignments: {
      list: (...a) => assignmentsList(...a),
    },
    stats: {
      getDashboard: vi.fn().mockResolvedValue({ data: { project_status_dist: {} } }),
    },
  },
}))

const getGitSettings = vi.fn().mockResolvedValue({ enabled: false })
const getSerenaStatus = vi.fn().mockResolvedValue({ enabled: false })
vi.mock('@/services/setupService', () => ({
  default: {
    getGitSettings: (...a) => getGitSettings(...a),
    getSerenaStatus: (...a) => getSerenaStatus(...a),
  },
}))

vi.mock('@/components/GilMascot.vue', () => ({ default: { name: 'GilMascot', template: '<div />' } }))
vi.mock('@/components/setup/SetupWizardOverlay.vue', () => ({
  default: { name: 'SetupWizardOverlay', template: '<div />' },
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

const userState = {
  currentUser: {
    full_name: 'Test User',
    setup_complete: true,
    learning_complete: true,
    setup_step_completed: 4,
    setup_selected_tools: [],
  },
  updateSetupState: vi.fn().mockResolvedValue(),
}
let productsState
let projectsState

vi.mock('@/stores/user', () => ({ useUserStore: () => userState }))
vi.mock('@/stores/products', () => ({ useProductStore: () => productsState }))
vi.mock('@/stores/projects', () => ({ useProjectStore: () => projectsState }))

const globalStubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
  'router-link': { template: '<a><slot /></a>' },
}

async function mountWelcome() {
  const WelcomeView = (await import('@/views/WelcomeView.vue')).default
  const wrapper = mount(WelcomeView, { global: { stubs: globalStubs } })
  await flushPromises()
  return wrapper
}

describe('WelcomeView — FE-6059 first-paint defer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.getItem.mockReturnValue(null)
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('does NOT request templates / git / serena on cold (onboarding) first paint', async () => {
    productsState = {
      activeProduct: null,
      hasProducts: false,
      effectiveProductId: null,
      fetchProducts: vi.fn().mockResolvedValue(),
    }
    projectsState = {
      projects: [],
      activeProjects: [],
      fetchProjects: vi.fn().mockResolvedValue(),
      createProject: vi.fn().mockResolvedValue({ id: 'p' }),
    }

    await mountWelcome()

    expect(templatesList).not.toHaveBeenCalled()
    expect(templatesActiveCount).not.toHaveBeenCalled()
    expect(getGitSettings).not.toHaveBeenCalled()
    expect(getSerenaStatus).not.toHaveBeenCalled()
  })

  it('DOES load team templates once onboarded (defer is conditional, not removal)', async () => {
    productsState = {
      activeProduct: { id: 'prod-1', name: 'Test Product' },
      hasProducts: true,
      effectiveProductId: 'prod-1',
      fetchProducts: vi.fn().mockResolvedValue(),
    }
    projectsState = {
      projects: [{ id: 'proj-1' }],
      activeProjects: [],
      fetchProjects: vi.fn().mockResolvedValue(),
      createProject: vi.fn().mockResolvedValue({ id: 'p' }),
    }

    await mountWelcome()

    expect(templatesList).toHaveBeenCalledTimes(1)
    expect(templatesActiveCount).toHaveBeenCalledTimes(1)
  })
})
