import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const { mockArchive, mockMarkReviewed, mockGetMemoryEntries } = vi.hoisted(() => ({
  mockArchive: vi.fn(),
  mockMarkReviewed: vi.fn(),
  mockGetMemoryEntries: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  default: {
    projects: { archive: mockArchive, markReviewed: mockMarkReviewed },
    products: { getMemoryEntries: mockGetMemoryEntries },
  },
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({ formatDateTime: (v) => String(v) }),
}))

import CloseoutModal from './CloseoutModal.vue'

const passthrough = { template: '<div><slot /></div>' }
const globalConfig = {
  stubs: {
    'v-dialog': { template: '<div v-if="modelValue"><slot /></div>', props: ['modelValue'] },
    'v-card': passthrough,
    'v-card-text': passthrough,
    'v-btn': { template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>' },
    'v-icon': { template: '<i />' },
    'v-spacer': { template: '<div />' },
    'v-divider': { template: '<hr />' },
    'v-progress-circular': { template: '<div />' },
    'v-alert': passthrough,
    'v-expansion-panels': passthrough,
    'v-expansion-panel': passthrough,
    'v-expansion-panel-title': passthrough,
    'v-expansion-panel-text': passthrough,
    'v-list': { template: '<ul><slot /></ul>' },
    'v-list-item': { template: '<li><slot /></li>' },
    'v-list-item-title': { template: '<span><slot /></span>' },
  },
  directives: { draggable: {} },
}

function mountModal(projectStatus) {
  return mount(CloseoutModal, {
    props: {
      show: true,
      projectId: 'proj-1',
      projectName: 'Test Project',
      productId: 'prod-1',
      projectStatus,
      suppressNavigation: true,
    },
    global: { ...globalConfig, plugins: [createPinia()] },
  })
}

describe('CloseoutModal stamps the human review (FE-9708)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockArchive.mockResolvedValue({ data: { id: 'proj-1', status: 'completed' } })
    mockMarkReviewed.mockResolvedValue({ data: { id: 'proj-1', reviewed_at: '2026-10-01T00:00:00Z' } })
    mockGetMemoryEntries.mockResolvedValue({ data: { entries: [] } })
  })

  it('Close on a project the agent already completed calls the reviewed endpoint, not archive', async () => {
    const wrapper = mountModal('completed')
    await flushPromises()
    await wrapper.find('[data-testid="close-out-btn"]').trigger('click')
    await flushPromises()
    expect(mockArchive).not.toHaveBeenCalled()
    expect(mockMarkReviewed).toHaveBeenCalledWith('proj-1')
    expect(wrapper.emitted('closeout')).toBeTruthy()
  })

  it('Close on an active project archives, then stamps the review', async () => {
    const wrapper = mountModal('active')
    await flushPromises()
    await wrapper.find('[data-testid="close-out-btn"]').trigger('click')
    await flushPromises()
    expect(mockArchive).toHaveBeenCalledWith('proj-1')
    expect(mockMarkReviewed).toHaveBeenCalledWith('proj-1')
    expect(mockArchive.mock.invocationCallOrder[0]).toBeLessThan(mockMarkReviewed.mock.invocationCallOrder[0])
  })

  it('a failed stamp keeps the modal open and shows the error', async () => {
    mockMarkReviewed.mockRejectedValue(new Error('nope'))
    const wrapper = mountModal('completed')
    await flushPromises()
    await wrapper.find('[data-testid="close-out-btn"]').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('close')).toBeFalsy()
    expect(wrapper.text()).toContain('nope')
  })
})
