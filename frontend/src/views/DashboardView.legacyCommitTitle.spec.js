/**
 * DashboardView.legacyCommitTitle.spec.js — BE-9256 (frontend layer 4).
 *
 * Edition Scope: Both.
 *
 * Stored 360 memory rows can carry a git_commits entry with an empty
 * `message` (legacy bare-SHA normalization, pre-validator). Before this
 * fix, the "Recent Commits" tile rendered the commit-msg div blank for such
 * a row — visually, the project name on the meta line reads like the
 * commit's title. The floor: an empty message must render the short SHA
 * as the title text instead of a blank div.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

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
    project_status_dist: {},
    taxonomy_dist: [],
    agent_role_dist: [],
    recent_projects: [],
    recent_memories: [
      {
        product_name: 'Demo Product',
        project_name: 'Legacy Project',
        git_commits: [
          // Legacy row: empty message (pre-validator bare-SHA normalization)
          { sha: '569905bd0abcdef1234567890', message: '' },
        ],
      },
      {
        product_name: 'Demo Product',
        project_name: 'Titled Project',
        git_commits: [{ sha: 'aaa1112223334445556667778', message: 'BE-9256: fail-closed validator' }],
      },
    ],
    task_status_dist: {},
    total_commits: 2,
    ...overrides,
  }
}

describe('DashboardView.vue — Recent Commits legacy-title floor (BE-9256)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getDashboard.mockResolvedValue({ data: dashboardPayload() })
    getCallCounts.mockResolvedValue({ data: { total_api_calls: 0, total_mcp_calls: 0 } })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

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

  it('renders the short SHA as the title for a legacy empty-message commit row (never blank)', async () => {
    const wrapper = mountView()
    await flushPromises()

    const rows = wrapper.findAll('.commit-row')
    const legacyRow = rows.find((r) => r.text().includes('Legacy Project'))
    expect(legacyRow).toBeTruthy()

    const msgEl = legacyRow.find('.commit-msg')
    expect(msgEl.text()).not.toBe('')
    expect(msgEl.text()).toBe('569905bd')
  })

  it('renders the real message unchanged for a titled commit row', async () => {
    const wrapper = mountView()
    await flushPromises()

    const rows = wrapper.findAll('.commit-row')
    const titledRow = rows.find((r) => r.text().includes('Titled Project'))
    expect(titledRow).toBeTruthy()
    expect(titledRow.find('.commit-msg').text()).toBe('BE-9256: fail-closed validator')
  })
})
