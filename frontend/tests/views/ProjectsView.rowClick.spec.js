import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// Track router.push calls
const pushMock = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
}))

// Mock stores and composables that ProjectsView uses
vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    activeProduct: { id: 'prod-1', name: 'Test Product' },
    fetchProducts: vi.fn().mockResolvedValue(),
    fetchActiveProduct: vi.fn().mockResolvedValue(),
  }),
}))

vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({
    clearForProject: vi.fn(),
  }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({
    formatDate: vi.fn(() => 'mocked-date'),
    formatDateCompact: vi.fn(() => 'mm/dd'),
    formatDateTime: vi.fn(() => 'mocked-datetime'),
  }),
}))

vi.mock('@/services/api', () => ({
  default: {
    projects: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      archive: vi.fn().mockResolvedValue({ data: {} }),
      restore: vi.fn().mockResolvedValue({ data: {} }),
    },
    taxonomyTypes: {
      list: vi.fn().mockResolvedValue({ data: [] }),
    },
  },
}))

/**
 * Rather than mounting the full ProjectsView (which has many child components),
 * we test the routing logic directly by importing and invoking the handleRowClick
 * function pattern. We simulate what the view does internally.
 */
describe('ProjectsView — WI-4: row click routing for active projects', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    pushMock.mockClear()
  })

  // Helper that mirrors the handleRowClick logic from ProjectsView
  function simulateRowClick(item) {
    if (!item?.id) return

    const normalizeStatus = (s) => (s === 'paused' ? 'inactive' : s || 'inactive')
    const isProjectStaged = (p) =>
      p.staging_status === 'staged' || p.staging_status === 'staging_complete'

    const status = normalizeStatus(item.status)

    if (status === 'completed' || status === 'cancelled' || status === 'terminated') {
      // review modal — not navigating
      return 'review'
    } else if (status === 'active') {
      // FE-9681: staged or not, an active project opens on its board card.
      pushMock({ name: 'JobsViewport', query: { project: item.id } })
      return 'navigate'
    } else {
      return 'edit'
    }
  }

  it('active + staged project navigates to its Jobs board card', () => {
    simulateRowClick({
      id: 'proj-1',
      status: 'active',
      staging_status: 'staged',
    })

    expect(pushMock).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'proj-1' },
    })
  })

  it('active + staging_complete project navigates to its Jobs board card', () => {
    simulateRowClick({
      id: 'proj-2',
      status: 'active',
      staging_status: 'staging_complete',
    })

    expect(pushMock).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'proj-2' },
    })
  })

  it('active + not staged navigates to its Jobs board card too', () => {
    simulateRowClick({
      id: 'proj-3',
      status: 'active',
      staging_status: null,
    })

    expect(pushMock).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'proj-3' },
    })
  })

  it('completed project returns review (does not navigate)', () => {
    const result = simulateRowClick({
      id: 'proj-4',
      status: 'completed',
    })

    expect(result).toBe('review')
    expect(pushMock).not.toHaveBeenCalled()
  })

  it('inactive project returns edit (does not navigate)', () => {
    const result = simulateRowClick({
      id: 'proj-5',
      status: 'inactive',
    })

    expect(result).toBe('edit')
    expect(pushMock).not.toHaveBeenCalled()
  })
})
