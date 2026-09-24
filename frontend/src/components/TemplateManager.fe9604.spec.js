import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { createRouter, createMemoryHistory } from 'vue-router'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/', name: 'Root', component: { template: '<div />' } }],
})
import TemplateManager from '@/components/TemplateManager.vue'
import { useProductStore } from '@/stores/products'

vi.mock('@/services/api', () => {
  const apiObj = {
    templates: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      activeCount: vi.fn(() => Promise.resolve({ data: { active_count: 2, limit: 15, available: 13 } })),
      importDefaults: vi.fn(() => Promise.resolve({ data: { added: [], added_as_duplicate: [], skipped_identical: [] } })),
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
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import api from '@/services/api'

const dataTableStub = {
  props: ['headers', 'items', 'loading', 'search', 'itemsPerPage'],
  template: `<div><div v-for="item in (items || [])" :key="item.id"><slot name="item.is_active" :item="item" /></div></div>`,
}
const switchStub = {
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  template: `<input type="checkbox" class="v-switch" v-bind="$attrs" :checked="modelValue" :disabled="disabled" @change="$emit('update:modelValue', $event.target.checked)" />`,
}

const PRODUCT_A = 'prod-aaaa'
const PRODUCT_B = 'prod-bbbb'
const TEMPLATE = { id: 7, name: 'My Analyzer', role: 'analyzer', category: 'role', cli_tool: 'claude', is_active: true, _system: false }

function mountManager() {
  return mount(TemplateManager, {
    global: {
      plugins: [
        router,
        createTestingPinia({
          initialState: {
            user: { currentUser: { id: 1, username: 'u', role: 'admin', tenant_key: 'tk' } },
            products: { activeProduct: null, currentProductId: PRODUCT_A },
          },
          stubActions: false,
        }),
      ],
      stubs: {
        'v-data-table': dataTableStub,
        'v-switch': switchStub,
        'v-menu': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
        'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
        'v-dialog': { template: '<div><slot /></div>' },
        Teleport: true,
      },
    },
  })
}

const toggle = (w) => w.find('[data-testid="template-toggle-analyzer"]')

describe('FE-9604 — the agent list follows the product tab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.templates.list.mockResolvedValue({ data: [{ ...TEMPLATE }] })
    api.assignments.list.mockImplementation((pid) =>
      Promise.resolve({
        data: { assignments: [{ template_id: 7, is_active: pid === PRODUCT_A }], count: 1 },
      }),
    )
  })

  it('switching product reloads assignments and the switch reflects the NEW product', async () => {
    const wrapper = mountManager()
    await flushPromises()
    expect(api.assignments.list).toHaveBeenCalledWith(PRODUCT_A)
    expect(toggle(wrapper).element.checked).toBe(true)

    useProductStore().currentProductId = PRODUCT_B
    await flushPromises()

    expect(api.assignments.list).toHaveBeenCalledWith(PRODUCT_B)
    expect(toggle(wrapper).element.checked).toBe(false)
  })

  it('the PUT carries the product the rows were LOADED for, not the store value at click time', async () => {
    const wrapper = mountManager()
    await flushPromises()

    api.assignments.list.mockImplementation((pid) =>
      pid === PRODUCT_B ? new Promise(() => {}) : Promise.resolve({ data: { assignments: [] } }),
    )
    api.templates.list.mockImplementation(() => new Promise(() => {}))
    useProductStore().currentProductId = PRODUCT_B
    await flushPromises()

    await wrapper.vm.handleToggleActive({ ...TEMPLATE }, false)
    expect(api.assignments.toggle).toHaveBeenCalledWith(PRODUCT_A, 7, false)
    expect(api.assignments.toggle).not.toHaveBeenCalledWith(PRODUCT_B, expect.anything(), expect.anything())
  })

  it('after a failed load for the new product, a toggle writes to the NEW product (fallback rows), not the old one', async () => {
    const wrapper = mountManager()
    await flushPromises()

    api.assignments.list.mockImplementation((pid) =>
      pid === PRODUCT_B ? Promise.reject(new Error('down')) : Promise.resolve({ data: { assignments: [] } }),
    )
    useProductStore().currentProductId = PRODUCT_B
    await flushPromises()

    await wrapper.vm.handleToggleActive({ ...TEMPLATE }, false)
    expect(api.assignments.toggle).toHaveBeenCalledWith(PRODUCT_B, 7, false)
    expect(api.assignments.toggle).not.toHaveBeenCalledWith(PRODUCT_A, expect.anything(), expect.anything())
  })

  it('disables the switch while assignments are loading, enables it after', async () => {
    let resolveList
    api.assignments.list.mockImplementation(() => new Promise((r) => (resolveList = r)))
    api.templates.list.mockResolvedValue({ data: [{ ...TEMPLATE }] })
    const wrapper = mountManager()
    await flushPromises()
    expect(toggle(wrapper).element.disabled).toBe(true)

    resolveList({ data: { assignments: [], count: 0 } })
    await flushPromises()
    expect(toggle(wrapper).element.disabled).toBe(false)
  })
})
