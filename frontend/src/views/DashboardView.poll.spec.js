import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/services/setupService', () => ({
  default: {
    baseURL: '',
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

let hidden = false

function setHidden(value) {
  hidden = value
  document.dispatchEvent(new Event('visibilitychange'))
}

let wrapper = null
const mountView = () => {
  wrapper = mount(DashboardView, {
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
  return wrapper
}

describe('DashboardView.vue — FE-6059 poll cadence + visibility pause', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    hidden = false
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    getDashboard.mockResolvedValue({ data: { project_status_dist: {}, total_commits: 0 } })
    getCallCounts.mockResolvedValue({ data: { total_api_calls: 0, total_mcp_calls: 0 } })
    vi.useFakeTimers()
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('polls call counts on a 60s cadence (not 30s) and pauses while hidden', async () => {
    mountView()
    await flushPromises()

    const base = getCallCounts.mock.calls.length
    expect(base).toBe(1)

    vi.advanceTimersByTime(30_000)
    await flushPromises()
    expect(getCallCounts).toHaveBeenCalledTimes(base)

    vi.advanceTimersByTime(30_000)
    await flushPromises()
    expect(getCallCounts).toHaveBeenCalledTimes(base + 1)

    setHidden(true)
    const afterHide = getCallCounts.mock.calls.length
    vi.advanceTimersByTime(180_000)
    await flushPromises()
    expect(getCallCounts).toHaveBeenCalledTimes(afterHide)
  })

  it('refetches immediately and resumes polling when the tab becomes visible again', async () => {
    mountView()
    await flushPromises()
    const base = getCallCounts.mock.calls.length

    setHidden(true)
    vi.advanceTimersByTime(120_000)
    await flushPromises()
    const afterHide = getCallCounts.mock.calls.length
    expect(afterHide).toBe(base)

    setHidden(false)
    await flushPromises()
    expect(getCallCounts).toHaveBeenCalledTimes(afterHide + 1)

    vi.advanceTimersByTime(60_000)
    await flushPromises()
    expect(getCallCounts).toHaveBeenCalledTimes(afterHide + 2)
  })
})
