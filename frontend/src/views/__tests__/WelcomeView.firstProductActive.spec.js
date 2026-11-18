import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

const h = vi.hoisted(() => ({ user: null }))
const created = { id: 'p-1', name: 'Recipe Box', is_active: true }
const productsApi = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  getDefault: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
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
vi.mock('@/services/api', () => {
  const api = {
    products: productsApi,
    templates: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      activeCount: vi.fn().mockResolvedValue({ data: { max_slots: 16 } }),
    },
    stats: { getDashboard: vi.fn().mockResolvedValue({ data: { recent_projects: [] } }) },
  }
  return { api, default: api }
})
vi.mock('@/stores/websocket', () => ({ useWebSocketStore: () => ({ on: () => () => {} }) }))
vi.mock('@/stores/user', async () => {
  const { reactive } = await import('vue')
  const currentUser = reactive({
    id: 'u-1',
    full_name: 'Alex Test',
    setup_complete: true,
    learning_complete: true,
    setup_step_completed: 4,
    setup_selected_tools: ['claude_code'],
  })
  return { useUserStore: () => ({ currentUser, updateSetupState: vi.fn() }) }
})
vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({ projects: [], activeProjects: [], fetchProjects: vi.fn().mockResolvedValue() }),
}))
vi.mock('@/stores/tasks', () => ({
  useTaskStore: () => ({ fetchTasks: vi.fn().mockResolvedValue() }),
}))
vi.mock('@/stores/commHubStore', () => ({
  useCommHubStore: () => ({ loadThreads: vi.fn().mockResolvedValue() }),
}))
vi.mock('@/components/GilMascot.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/dashboard/RecentProjectsList.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/projects/ProjectReviewModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/setup/SetupWizardOverlay.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/tutorial/TutorialOverlay.vue', () => ({ default: { template: '<div />' } }))

const stubs = {
  teleport: true,
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': { template: '<button v-bind="$attrs"><slot /></button>' },
  'router-link': { template: '<a><slot /></a>' },
}

async function settle() {
  for (let i = 0; i < 30; i++) await Promise.resolve()
  await nextTick()
  for (let i = 0; i < 30; i++) await Promise.resolve()
}

describe('Home after an AI tool makes the first product', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    productsApi.list.mockResolvedValue({ data: [] })
    productsApi.get.mockResolvedValue({ data: created })
    productsApi.getDefault.mockResolvedValue({ data: { has_active_product: false, product: null } })
  })

  it('shows no Activate Product card once the server reports the product active', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const WelcomeView = (await import('@/views/WelcomeView.vue')).default
    const w = mount(WelcomeView, { global: { stubs, plugins: [pinia] } })
    await settle()
    expect(w.text()).not.toContain('Activate Product')

    productsApi.list.mockResolvedValue({ data: [created] })
    productsApi.getDefault.mockResolvedValue({ data: { has_active_product: true, product: created } })
    const { SYSTEM_EVENT_ROUTES } = await import('@/stores/eventRoutes/systemEventRoutes')
    await SYSTEM_EVENT_ROUTES['product:created'].handler({ product_id: 'p-1', name: 'Recipe Box' })
    await settle()

    expect(w.text()).not.toContain('Activate Product')
    expect(w.text()).not.toContain("it's not active")
  })
})
