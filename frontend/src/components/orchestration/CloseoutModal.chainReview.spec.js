import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const { mockArchive, mockGetMemoryEntries, mockRouterPush, mockShowToast } = vi.hoisted(() => ({
  mockArchive: vi.fn(),
  mockGetMemoryEntries: vi.fn(),
  mockRouterPush: vi.fn(),
  mockShowToast: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  default: {
    projects: { archive: mockArchive },
    products: { getMemoryEntries: mockGetMemoryEntries },
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockRouterPush }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}))

vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({ formatDateTime: (v) => String(v) }),
}))

import CloseoutModal from './CloseoutModal.vue'

const globalConfig = {
  stubs: {
    'v-dialog': { template: '<div v-if="modelValue"><slot /></div>', props: ['modelValue'] },
    'v-card': { template: '<div><slot /></div>' },
    'v-card-text': { template: '<div><slot /></div>' },
    'v-btn': {
      template: '<button v-bind="$attrs" :data-testid="$attrs[\'data-testid\']" @click="$emit(\'click\')"><slot /></button>',
    },
    'v-icon': { template: '<i />' },
    'v-spacer': { template: '<div />' },
    'v-divider': { template: '<hr />' },
    'v-progress-circular': { template: '<div />' },
    'v-alert': { template: '<div><slot /></div>' },
    'v-expansion-panels': { template: '<div><slot /></div>' },
    'v-expansion-panel': { template: '<div><slot /></div>' },
    'v-expansion-panel-title': { template: '<div><slot /></div>' },
    'v-expansion-panel-text': { template: '<div><slot /></div>' },
    'v-list': { template: '<ul><slot /></ul>' },
    'v-list-item': { template: '<li><slot /></li>' },
    'v-list-item-title': { template: '<span><slot /></span>' },
  },
  directives: { draggable: {} },
}

function mountModal(props = {}) {
  return mount(CloseoutModal, {
    props: {
      show: true,
      projectId: 'proj-1',
      projectName: 'Test Project',
      productId: 'prod-1',
      projectStatus: 'active',
      suppressNavigation: false,
      ...props,
    },
    global: { ...globalConfig, plugins: [createPinia()] },
  })
}

describe('CloseoutModal — chain review skip-archive', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockArchive.mockResolvedValue({ data: { id: 'proj-1', status: 'completed' } })
    mockGetMemoryEntries.mockResolvedValue({ data: { entries: [] } })
  })

  it('SOLO: calls api.projects.archive when projectStatus is active', async () => {
    const wrapper = mountModal({ projectStatus: 'active', suppressNavigation: true })
    await flushPromises()

    const btn = wrapper.find('[data-testid="close-out-btn"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    await flushPromises()

    expect(mockArchive).toHaveBeenCalledWith('proj-1')
  })

  it('CHAIN review: skips api.projects.archive when projectStatus is completed', async () => {
    const wrapper = mountModal({ projectStatus: 'completed', suppressNavigation: true })
    await flushPromises()

    await wrapper.find('[data-testid="close-out-btn"]').trigger('click')
    await flushPromises()

    expect(mockArchive).not.toHaveBeenCalled()
  })

  it('CHAIN review: emits closeout even when archive is skipped', async () => {
    const wrapper = mountModal({ projectStatus: 'completed', suppressNavigation: true })
    await flushPromises()

    await wrapper.find('[data-testid="close-out-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('closeout')).toBeTruthy()
  })

  it('SOLO review of a completed project (FE-9191): Close acknowledges without re-firing the archive write', async () => {
    const wrapper = mountModal({ projectStatus: 'completed', suppressNavigation: false })
    await flushPromises()

    await wrapper.find('[data-testid="close-out-btn"]').trigger('click')
    await flushPromises()

    expect(mockArchive).not.toHaveBeenCalled()
    expect(wrapper.emitted('closeout')).toBeTruthy()
    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
  })

  it('CHAIN review: does not navigate away (suppressNavigation=true)', async () => {
    const wrapper = mountModal({ projectStatus: 'completed', suppressNavigation: true })
    await flushPromises()

    await wrapper.find('[data-testid="close-out-btn"]').trigger('click')
    await flushPromises()

    expect(mockRouterPush).not.toHaveBeenCalled()
  })
})
