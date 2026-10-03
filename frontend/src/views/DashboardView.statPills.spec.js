import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/services/setupService', () => ({ default: { baseURL: '' } }))

const getDashboard = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    stats: {
      getDashboard: (...a) => getDashboard(...a),
      getCallCounts: () => Promise.resolve({ data: { total_api_calls: 0, total_mcp_calls: 0 } }),
    },
  },
}))

import DashboardView from '@/views/DashboardView.vue'

describe('DashboardView stat pills', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getDashboard.mockResolvedValue({
      data: {
        project_status_dist: { active: 2, completed: 1, deleted: 5 },
        taxonomy_dist: [{ label: 'BE', count: 3, color: '#123456' }, { count: 1 }],
        agent_role_dist: [{ label: 'implementer', count: 4 }],
        recent_projects: [],
        recent_memories: [],
        task_status_dist: {},
        total_commits: 0,
      },
    })
  })

  it('renders each pill in order with its total, unit, bar and legend', async () => {
    const wrapper = mount(DashboardView, {
      global: {
        stubs: { RecentProjectsList: true, RecentMemoriesList: true, ProjectReviewModal: true, AppAlert: true, RouterLink: true },
      },
    })
    await flushPromises()

    const pills = wrapper.findAll('.stat-pills > .stat-pill')
    const seen = pills.map((p) => ({
      classes: p.classes(),
      label: p.find('.stat-pill-label').text(),
      value: p.find('.stat-pill-value').text(),
      segs: p.findAll('.micro-seg').length,
      legend: p.findAll('.micro-legend-item').map((l) => l.text()),
    }))

    expect(seen).toEqual([
      {
        classes: ['stat-pill', 'smooth-border', 'main-window-reveal', 'main-window-delay-3'],
        label: 'Status Distribution',
        value: '3projects',
        segs: 2,
        legend: ['Active 2', 'Completed 1'],
      },
      {
        classes: ['stat-pill', 'smooth-border', 'main-window-reveal', 'main-window-delay-4'],
        label: 'Project Types',
        value: '4types',
        segs: 2,
        legend: ['BE 3', 'Untyped 1'],
      },
      {
        classes: ['stat-pill', 'smooth-border', 'main-window-reveal', 'main-window-delay-5'],
        label: 'Agent Roles',
        value: '4spawned',
        segs: 1,
        legend: ['implementer 4'],
      },
    ])
  })
})
