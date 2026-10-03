import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import CloseoutModal from '@/components/orchestration/CloseoutModal.vue'

// Track router.push calls
const pushMock = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
}))

// Track toast calls
const showToastMock = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

// Track formatDateTime calls
vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({ formatDateTime: vi.fn(() => 'mocked-date') }),
}))

// Mock api — archive resolves successfully by default
const archiveMock = vi.fn().mockResolvedValue({ data: { id: 'proj-1' } })
const getMemoryEntriesMock = vi.fn().mockResolvedValue({ data: { entries: [] } })
vi.mock('@/services/api', () => ({
  default: {
    projects: { archive: (...args) => archiveMock(...args), markReviewed: () => Promise.resolve({ data: {} }) },
    products: { getMemoryEntries: (...args) => getMemoryEntriesMock(...args) },
  },
}))

describe('CloseoutModal — WI-2 post-archive UX', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    pushMock.mockClear()
    showToastMock.mockClear()
    archiveMock.mockClear()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function mountModal() {
    return mount(CloseoutModal, {
      props: {
        show: true,
        projectId: 'proj-1',
        projectName: 'Test Project',
        productId: 'prod-1',
        projectStatus: 'active',
      },
      global: {
        plugins: [createPinia()],
      },
    })
  }

  it('shows success toast after successful archive', async () => {
    const wrapper = mountModal()
    const btn = wrapper.find('[data-testid="close-out-btn"]')
    await btn.trigger('click')

    // Wait for async archive call
    await vi.waitFor(() => {
      expect(archiveMock).toHaveBeenCalledWith('proj-1')
    })

    expect(showToastMock).toHaveBeenCalledWith({
      message: 'Project closed out successfully',
      type: 'success',
    })
  })

  it('navigates to /projects immediately on successful archive (TSK-9195)', async () => {
    const wrapper = mountModal()
    const btn = wrapper.find('[data-testid="close-out-btn"]')
    await btn.trigger('click')

    await vi.waitFor(() => {
      expect(archiveMock).toHaveBeenCalled()
    })

    // TSK-9195: navigation fires in the same tick as the archive success —
    // no window where the stale Jobs view (re-clickable Review) stays on screen.
    expect(pushMock).toHaveBeenCalledWith('/projects')
  })

  it('leaves no timer-based navigation pending after Close success (TSK-9195)', async () => {
    const wrapper = mountModal()
    await wrapper.find('[data-testid="close-out-btn"]').trigger('click')

    await vi.waitFor(() => {
      expect(archiveMock).toHaveBeenCalled()
    })

    expect(pushMock).toHaveBeenCalledTimes(1)

    // No delayed second navigation may exist.
    vi.advanceTimersByTime(10000)
    expect(pushMock).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does NOT show toast or navigate on archive failure', async () => {
    archiveMock.mockRejectedValueOnce(new Error('Network error'))

    const wrapper = mountModal()
    const btn = wrapper.find('[data-testid="close-out-btn"]')
    await btn.trigger('click')

    await vi.waitFor(() => {
      expect(archiveMock).toHaveBeenCalled()
    })

    expect(showToastMock).not.toHaveBeenCalled()
    vi.advanceTimersByTime(5000)
    expect(pushMock).not.toHaveBeenCalled()
  })
})
