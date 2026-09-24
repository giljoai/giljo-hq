
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { createRouter, createMemoryHistory } from 'vue-router'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/', name: 'Root', component: { template: '<div />' } }],
})
import TemplateManager from '@/components/TemplateManager.vue'

vi.mock('@/services/api', () => {
  const apiObj = {
    templates: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      activeCount: vi.fn(() =>
        Promise.resolve({ data: { active_count: 2, limit: 15, available: 13 } })
      ),
      importDefaults: vi.fn(() =>
        Promise.resolve({ data: { added: [], added_as_duplicate: [], skipped_identical: [] } })
      ),
    },
    assignments: {
      list: vi.fn(() => Promise.resolve({ data: { assignments: [], count: 0 } })),
      toggle: vi.fn(() => Promise.resolve({ data: { is_active: false } })),
    },
    settings: {
      getGeneral: vi.fn(() => Promise.resolve({ data: { settings: { closeout_mode: 'hitl' } } })),
      getHeadlessLaunch: vi.fn(() => Promise.resolve({ data: { allow_headless_launch: false } })),
    },
  }
  return { api: apiObj, default: apiObj }
})

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

import api from '@/services/api'

const dataTableStub = {
  props: ['headers', 'items', 'loading', 'search', 'itemsPerPage'],
  template: `
    <div class="v-data-table">
      <div v-for="item in (items || [])" :key="item.id" class="v-data-table-row">
        <slot name="item.is_active" :item="item" />
      </div>
    </div>
  `,
}

const switchStub = {
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  template: `
    <input
      type="checkbox"
      class="v-switch"
      v-bind="$attrs"
      :checked="modelValue"
      :disabled="disabled"
      @change="$emit('update:modelValue', $event.target.checked)"
    />
  `,
}

const ACTIVE_PRODUCT_ID = 'prod-active-1111'
const BROWSED_PRODUCT_ID = 'prod-browsed-2222'

function makeTemplate(overrides = {}) {
  return {
    id: 7,
    name: 'My Analyzer',
    role: 'analyzer',
    category: 'role',
    cli_tool: 'claude',
    is_active: true,
    _system: false,
    updated_at: '2024-01-02T12:00:00Z',
    ...overrides,
  }
}

function mountManager({ products } = {}) {
  return mount(TemplateManager, {
    global: {
      plugins: [
        router,
        createTestingPinia({
          initialState: {
            user: { currentUser: { id: 1, username: 'testuser', role: 'admin', tenant_key: 'tk_test' } },
            products: products ?? { activeProduct: { id: ACTIVE_PRODUCT_ID, name: 'Active' } },
          },
          stubActions: false,
        }),
      ],
      stubs: {
        'v-data-table': dataTableStub,
        'v-switch': switchStub,
        'v-menu': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
        'v-list-item': { props: ['title'], template: '<div v-bind="$attrs" :title="title"><slot /></div>' },
        'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
        'v-dialog': { template: '<div><slot /></div>' },
        Teleport: true,
      },
    },
  })
}

describe('BE-9385a — the Agents toggle is per-product', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.templates.list.mockResolvedValue({ data: [makeTemplate()] })
    api.assignments.list.mockResolvedValue({ data: { assignments: [], count: 0 } })
  })

  it('writes the junction for the ACTIVE product, not the tenant-wide flag', async () => {
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: 7, is_active: true }], count: 1 },
    })
    const wrapper = mountManager()
    await flushPromises()

    await wrapper.find('[data-testid="template-toggle-analyzer"]').setValue(false)
    await flushPromises()

    expect(api.assignments.toggle).toHaveBeenCalledWith(ACTIVE_PRODUCT_ID, 7, false)
    expect(api.templates.update).not.toHaveBeenCalled()
  })

  it('FE-9524/D1: uses the BROWSED (viewed) product, not the legacy activeProduct slot, when they diverge', async () => {
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: 7, is_active: true }], count: 1 },
    })
    const wrapper = mountManager({
      products: {
        activeProduct: { id: ACTIVE_PRODUCT_ID, name: 'Active' },
        currentProductId: BROWSED_PRODUCT_ID,
      },
    })
    await flushPromises()

    await wrapper.find('[data-testid="template-toggle-analyzer"]').setValue(false)
    await flushPromises()

    expect(api.assignments.toggle).toHaveBeenCalledWith(BROWSED_PRODUCT_ID, 7, false)
    expect(api.assignments.toggle).not.toHaveBeenCalledWith(
      ACTIVE_PRODUCT_ID,
      expect.anything(),
      expect.anything()
    )
  })

  it('writes NOTHING when there is no product in view', async () => {
    const wrapper = mountManager({
      products: { activeProduct: null, currentProductId: null },
    })
    await flushPromises()

    expect(api.templates.update).not.toHaveBeenCalled()
    expect(api.assignments.toggle).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="empty-no-product"]').exists()).toBe(true)
  })

  it('shows the per-product state when an assignment exists', async () => {
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: 7, is_active: false }], count: 1 },
    })

    const wrapper = mountManager()
    await flushPromises()

    expect(api.assignments.list).toHaveBeenCalledWith(ACTIVE_PRODUCT_ID)
    expect(wrapper.find('[data-testid="template-toggle-analyzer"]').element.checked).toBe(false)
  })

  it('a template with no assignment reads OFF', async () => {
    const wrapper = mountManager()
    await flushPromises()

    expect(wrapper.find('[data-testid="template-toggle-analyzer"]').element.checked).toBe(false)
  })

  it('FE-9604: the per-product switch stays usable for an agent that is off tenant-wide', async () => {
    api.templates.list.mockResolvedValue({ data: [makeTemplate({ is_active: false })] })

    const wrapper = mountManager()
    await flushPromises()

    expect(wrapper.find('[data-testid="template-toggle-analyzer"]').element.disabled).toBe(false)
  })
})
