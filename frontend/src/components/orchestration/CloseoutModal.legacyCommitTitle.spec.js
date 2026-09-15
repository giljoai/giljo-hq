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

vi.mock('vuetify', () => ({
  useDisplay: () => ({ mobile: { value: false } }),
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
      template:
        '<button v-bind="$attrs" :data-testid="$attrs[\'data-testid\']" @click="$emit(\'click\')"><slot /></button>',
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
    'v-list-item-title': { template: '<span class="commit-title-stub"><slot /></span>' },
  },
  directives: { draggable: {} },
}

const BASE_PROPS = {
  projectId: 'proj-1',
  projectName: 'Test Project',
  productId: 'prod-1',
  projectStatus: 'completed',
  suppressNavigation: true,
}

describe('CloseoutModal — legacy titleless commit-row floor (BE-9256)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockArchive.mockResolvedValue({ data: { id: 'proj-1', status: 'completed' } })
    mockGetMemoryEntries.mockResolvedValue({
      data: {
        entries: [
          {
            id: 'm1',
            summary: 'x',
            entry_type: 'lesson',
            git_commits: [
              { sha: '569905bd0abcdef1234567890', message: '', author: 'a', timestamp: '2026-07-01T00:00:00Z' },
              { sha: 'aaa1112223334445556667778', message: 'BE-9256: fail-closed validator', author: 'b' },
            ],
          },
        ],
      },
    })
  })

  it('renders the short SHA for a legacy empty-message commit row, never blank', async () => {
    const wrapper = mount(CloseoutModal, {
      props: { ...BASE_PROPS, show: true },
      global: { ...globalConfig, plugins: [createPinia()] },
    })

    await flushPromises()

    const titles = wrapper.findAll('.commit-title-stub').map((el) => el.text())
    expect(titles).toContain('569905bd')
    expect(titles).not.toContain('')
  })

  it('renders the real message unchanged for a titled commit row', async () => {
    const wrapper = mount(CloseoutModal, {
      props: { ...BASE_PROPS, show: true },
      global: { ...globalConfig, plugins: [createPinia()] },
    })

    await flushPromises()

    const titles = wrapper.findAll('.commit-title-stub').map((el) => el.text())
    expect(titles).toContain('BE-9256: fail-closed validator')
  })
})
