import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { getAgentColor } from '@/config/agentColors'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/services/setupService', () => ({
  default: {
    baseURL: '',
    checkStatus: vi.fn().mockResolvedValue({
      setup_mode: false,
      setup_complete: true,
      database_configured: true,
      database_connected: true,
      requires_setup: false,
    }),
  },
}))

const getDashboard = vi.fn()
const getCallCounts = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    stats: {
      getDashboard: (...a) => getDashboard(...a),
      getCallCounts: (...a) => getCallCounts(...a),
    },
  },
}))

import DashboardView from '@/views/DashboardView.vue'

function dashboardPayload(overrides = {}) {
  return {
    project_status_dist: { active: 2 },
    taxonomy_dist: [],
    agent_role_dist: [],
    recent_projects: [],
    recent_memories: [],
    task_status_dist: {},
    total_commits: 0,
    ...overrides,
  }
}

const mountView = () =>
  mount(DashboardView, {
    global: {
      stubs: {
        RecentProjectsList: true,
        RecentMemoriesList: true,
        ProjectReviewModal: true,
        AppAlert: true,
        RouterLink: true,
      },
    },
  })

describe('DashboardView.vue — Active status segment color (FE-2004 sibling)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getDashboard.mockResolvedValue({ data: dashboardPayload() })
    getCallCounts.mockResolvedValue({ data: { total_api_calls: 0, total_mcp_calls: 0 } })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders the Active distribution segment in implementer blue, not white', async () => {
    const wrapper = mountView()
    await flushPromises()

    const seg = wrapper.find('.micro-seg')
    expect(seg.exists()).toBe(true)

    const style = (seg.attributes('style') || '').toLowerCase().replace(/\s+/g, '')
    const blueHex = getAgentColor('implementer').hex.toLowerCase()
    const blueRgb = 'rgb(109,179,228)'

    expect(style).not.toContain('#ffffff')
    expect(style).not.toContain('rgb(255,255,255)')
    expect(style.includes(blueHex) || style.includes(blueRgb)).toBe(true)
  })
})
