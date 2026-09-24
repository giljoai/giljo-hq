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
      activeCount: vi.fn(() => Promise.resolve({ data: { active_count: 2, limit: 15, available: 13 } })),
      importDefaults: vi.fn(() => Promise.resolve({ data: { added: [], added_as_duplicate: [], skipped_identical: [] } })),
    },
    assignments: {
      list: vi.fn(() => Promise.resolve({ data: { assignments: [], count: 0 } })),
      toggle: vi.fn(() => Promise.resolve({ data: { is_active: true } })),
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

const A = 'prod-a'
const B = 'prod-b'
const C = 'prod-c'
const TEMPLATE_ID = 7
const row = (o = {}) => ({ id: TEMPLATE_ID, name: 'My Analyzer', role: 'analyzer', category: 'role', cli_tool: 'claude', is_active: true, _system: false, ...o })

const calls = []
function recordWrites() {
  calls.length = 0
  api.templates.update.mockImplementation((id, body) => {
    calls.push(['tenant', id, body])
    return Promise.resolve({ data: {} })
  })
  api.assignments.toggle.mockImplementation((pid, tid, v) => {
    calls.push(['junction', pid, tid, v])
    return Promise.resolve({ data: { is_active: v } })
  })
}

function mountManager(products = [{ id: A }, { id: B }, { id: C }]) {
  return mount(TemplateManager, {
    global: {
      plugins: [
        router,
        createTestingPinia({
          initialState: {
            user: { currentUser: { id: 1, username: 'u', role: 'admin', tenant_key: 'tk' } },
            products: { activeProduct: null, currentProductId: A, products },
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

describe('FE-9604 — single switch per row', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    recordWrites()
    api.assignments.list.mockResolvedValue({ data: { assignments: [], count: 0 } })
  })

  it('the row switch is NOT disabled for an agent that is off at tenant level', async () => {
    api.templates.list.mockResolvedValue({ data: [row({ is_active: false })] })
    const wrapper = mountManager()
    await flushPromises()
    expect(toggle(wrapper).element.disabled).toBe(false)
    expect(toggle(wrapper).element.checked).toBe(false)
  })

  it('turning an agent ON writes ONE assignment and nothing else', async () => {
    api.templates.list.mockResolvedValue({ data: [row({ is_active: false })] })
    api.assignments.list.mockImplementation((pid) =>
      Promise.resolve({
        data: {
          assignments: pid === C ? [{ template_id: TEMPLATE_ID, is_active: true }] : [],
          count: pid === C ? 1 : 0,
        },
      }),
    )
    const wrapper = mountManager()
    await flushPromises()

    await toggle(wrapper).setValue(true)
    await flushPromises()

    expect(calls).toEqual([['junction', A, TEMPLATE_ID, true]])
    expect(toggle(wrapper).element.checked).toBe(true)
  })

  it('turning ON an agent that is already tenant-active writes ONLY the junction', async () => {
    api.templates.list.mockResolvedValue({ data: [row({ is_active: true })] })
    api.assignments.list.mockResolvedValue({ data: { assignments: [{ template_id: TEMPLATE_ID, is_active: false }], count: 1 } })
    const wrapper = mountManager()
    await flushPromises()

    await toggle(wrapper).setValue(true)
    await flushPromises()
    expect(calls).toEqual([['junction', A, TEMPLATE_ID, true]])
  })

  it('turning OFF changes only the assignment for this product', async () => {
    api.templates.list.mockResolvedValue({ data: [row({ is_active: true })] })
    api.assignments.list.mockResolvedValue({ data: { assignments: [{ template_id: TEMPLATE_ID, is_active: true }], count: 1 } })
    const wrapper = mountManager()
    await flushPromises()

    await toggle(wrapper).setValue(false)
    await flushPromises()
    expect(calls).toEqual([['junction', A, TEMPLATE_ID, false]])
  })

  it('an agent with an active assignment is on', async () => {
    api.templates.list.mockResolvedValue({ data: [row({ is_active: false })] })
    api.assignments.list.mockResolvedValue({ data: { assignments: [{ template_id: TEMPLATE_ID, is_active: true }], count: 1 } })
    const wrapper = mountManager()
    await flushPromises()

    expect(toggle(wrapper).element.checked).toBe(true)
  })
})

describe('FE-9610c — the cross-product bulk actions are gone', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    recordWrites()
    api.assignments.list.mockResolvedValue({ data: { assignments: [], count: 0 } })
    api.templates.list.mockResolvedValue({ data: [row()] })
  })

  it('the component exposes no cross-product bulk writer', async () => {
    const wrapper = mountManager()
    await flushPromises()

    expect(wrapper.vm.setEditingForAllProducts).toBeUndefined()
    expect(wrapper.vm.setForAllProducts).toBeUndefined()
  })

  it('nothing in the manager writes another product\'s junction', async () => {
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: TEMPLATE_ID, is_active: true }], count: 1 },
    })
    const wrapper = mountManager()
    await flushPromises()

    await toggle(wrapper).setValue(false)
    await flushPromises()

    const productsWritten = new Set(calls.filter((c) => c[0] === 'junction').map((c) => c[1]))
    expect([...productsWritten]).toEqual([A])
  })
})
