import { describe, it, expect, beforeEach, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
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
      activeCount: vi.fn(() =>
        Promise.resolve({ data: { active_count: 2, limit: 15, available: 13 } }),
      ),
      importDefaults: vi.fn(() =>
        Promise.resolve({ data: { added: [], added_as_duplicate: [], skipped_identical: [] } }),
      ),
      profileDownloadUrl: (id) => `/api/v1/templates/${id}/profile.md`,
    },
    assignments: {
      list: vi.fn(() => Promise.resolve({ data: { assignments: [], count: 0 } })),
      toggle: vi.fn(() => Promise.resolve({ data: { is_active: true } })),
    },
    products: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
    },
    settings: {
      getGeneral: vi.fn(() => Promise.resolve({ data: { settings: { closeout_mode: 'hitl' } } })),
      getHeadlessLaunch: vi.fn(() => Promise.resolve({ data: { allow_headless_launch: false } })),
    },
  }
  return { api: apiObj, default: apiObj }
})
const showToast = vi.fn()
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }))

import api from '@/services/api'

const dataTableStub = {
  props: ['headers', 'items', 'loading', 'search', 'itemsPerPage'],
  template: `<div class="v-data-table"><div v-for="item in (items || [])" :key="item.id" class="row-stub"><slot name="item.product_id" :item="item" /><slot name="item.is_active" :item="item" /></div></div>`,
}
const switchStub = {
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  template: `<input type="checkbox" class="v-switch" v-bind="$attrs" :checked="modelValue" :disabled="disabled" @change="$emit('update:modelValue', $event.target.checked)" />`,
}
const listItemStub = {
  props: ['title'],
  template: `<button type="button" v-bind="$attrs">{{ title }}</button>`,
}

const A = 'prod-a'
const B = 'prod-b'
const PRODUCTS = [
  { id: A, name: 'Atlas', is_active: true },
  { id: B, name: 'Beacon', is_active: true },
]

const row = (o = {}) => ({
  id: 7,
  name: 'analyzer',
  role: 'analyzer',
  category: 'role',
  cli_tool: 'claude',
  is_active: true,
  _system: false,
  ...o,
})

function mountManager({ products = PRODUCTS, currentProductId = A } = {}) {
  return mount(TemplateManager, {
    global: {
      plugins: [
        router,
        createTestingPinia({
          initialState: {
            user: { currentUser: { id: 1, username: 'u', role: 'admin', tenant_key: 'tk' } },
            products: { activeProduct: null, currentProductId, products },
          },
          stubActions: false,
        }),
      ],
      stubs: {
        'v-data-table': dataTableStub,
        'v-switch': switchStub,
        'v-list-item': listItemStub,
        'v-menu': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
        'v-chip': { template: '<span v-bind="$attrs"><slot /></span>' },
        'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
        'v-dialog': { template: '<div><slot /></div>' },
        Teleport: true,
      },
    },
  })
}

const toggles = (w) => w.findAll('[data-testid^="template-toggle-"]')
const togglesChecked = (w) => toggles(w).map((t) => t.element.checked)

let puts = []
function recordPuts() {
  puts = []
  api.assignments.toggle.mockImplementation((pid, tid, active) => {
    puts.push([pid, tid, active])
    return Promise.resolve({ data: { is_active: active } })
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  showToast.mockClear()
  recordPuts()
  api.assignments.list.mockResolvedValue({ data: { assignments: [], count: 0 } })
  api.templates.list.mockResolvedValue({ data: [] })
  api.products.list.mockResolvedValue({ data: PRODUCTS })
})


describe('FE-9610c — the switch cannot lie about what the server serves', () => {
  it('an agent the product has switched on reads ON', async () => {
    api.templates.list.mockResolvedValue({ data: [row()] })
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: 7, is_active: true }], count: 1 },
    })

    const wrapper = mountManager()
    await flushPromises()

    expect(togglesChecked(wrapper)).toEqual([true])
  })

  it('an agent with no assignment reads OFF', async () => {
    api.templates.list.mockResolvedValue({
      data: [row({ id: 7, name: 'documenter', role: 'documenter' }), row({ id: 8, name: 'tester', role: 'tester' })],
    })
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: 7, is_active: true }], count: 1 },
    })

    const wrapper = mountManager()
    await flushPromises()

    expect(togglesChecked(wrapper)).toEqual([true, false])
  })

  it('an agent with an active assignment is on', async () => {
    api.templates.list.mockResolvedValue({ data: [row({ is_active: false })] })
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: 7, is_active: true }], count: 1 },
    })

    const wrapper = mountManager()
    await flushPromises()

    expect(togglesChecked(wrapper)).toEqual([true])
  })

  it('a product with no assignments shows every agent OFF', async () => {
    api.templates.list.mockResolvedValue({ data: [row(), row({ id: 8, role: 'tester' })] })
    api.assignments.list.mockResolvedValue({ data: { assignments: [], count: 0 } })

    const wrapper = mountManager()
    await flushPromises()

    expect(togglesChecked(wrapper)).toEqual([false, false])
  })

  it('a failed assignments load shows OFF rather than an optimistic ON', async () => {
    api.templates.list.mockResolvedValue({ data: [row()] })
    api.assignments.list.mockRejectedValue(new Error('network'))

    const wrapper = mountManager()
    await flushPromises()

    expect(togglesChecked(wrapper)).toEqual([false])
  })
})


describe('FE-9610b — an empty product explains itself', () => {
  it('no agents at all: explanation, the harness-default consequence, and the remedy', async () => {
    api.templates.list.mockResolvedValue({ data: [] })
    const wrapper = mountManager()
    await flushPromises()

    const panel = wrapper.find('[data-testid="empty-no-agents"]')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toMatch(/default agent your coding tool provides/i)
    expect(wrapper.find('[data-testid="empty-add-defaults"]').exists()).toBe(true)
    expect(wrapper.find('.v-data-table').exists()).toBe(false)
  })

  it('the empty-state action actually seeds the roster', async () => {
    api.templates.list.mockResolvedValue({ data: [] })
    const wrapper = mountManager()
    await flushPromises()

    await wrapper.find('[data-testid="empty-add-defaults"]').trigger('click')
    await flushPromises()

    expect(api.templates.importDefaults).toHaveBeenCalled()
  })

  it('agents exist but every one is off here: a DIFFERENT message and a one-click enable-all', async () => {
    api.templates.list.mockResolvedValue({ data: [row(), row({ id: 8, role: 'tester' })] })
    api.assignments.list.mockResolvedValue({
      data: {
        assignments: [
          { template_id: 7, is_active: false, template_is_active: true },
          { template_id: 8, is_active: false, template_is_active: true },
        ],
        count: 2,
      },
    })

    const wrapper = mountManager()
    await flushPromises()

    const panel = wrapper.find('[data-testid="empty-none-active"]')
    expect(panel.exists()).toBe(true)
    expect(wrapper.find('[data-testid="empty-no-agents"]').exists()).toBe(false)
    expect(wrapper.find('.v-data-table').exists()).toBe(true)
    expect(wrapper.find('[data-testid="empty-enable-all"]').exists()).toBe(true)
  })

  it('the two empty states never share copy', async () => {
    api.templates.list.mockResolvedValue({ data: [] })
    const empty = mountManager()
    await flushPromises()
    const emptyText = empty.find('[data-testid="empty-no-agents"]').text()

    api.templates.list.mockResolvedValue({ data: [row()] })
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: 7, is_active: false, template_is_active: true }], count: 1 },
    })
    const allOff = mountManager()
    await flushPromises()

    expect(allOff.find('[data-testid="empty-none-active"]').text()).not.toBe(emptyText)
  })

  it('a populated, partly-on product shows neither panel', async () => {
    api.templates.list.mockResolvedValue({ data: [row(), row({ id: 8, role: 'tester' })] })
    api.assignments.list.mockResolvedValue({
      data: {
        assignments: [
          { template_id: 7, is_active: true, template_is_active: true },
          { template_id: 8, is_active: false, template_is_active: true },
        ],
        count: 2,
      },
    })

    const wrapper = mountManager()
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-no-agents"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="empty-none-active"]').exists()).toBe(false)
  })
})


describe('FE-9610b — bulk actions for the viewed product', () => {
  const TWO_OFF = {
    data: {
      assignments: [
        { template_id: 7, is_active: false, template_is_active: true },
        { template_id: 8, is_active: false, template_is_active: true },
      ],
      count: 2,
    },
  }

  beforeEach(() => {
    api.templates.list.mockResolvedValue({ data: [row(), row({ id: 8, role: 'tester' })] })
  })

  it('Enable all: one PUT per agent, against the VIEWED product, in row order', async () => {
    api.assignments.list.mockResolvedValue(TWO_OFF)
    const wrapper = mountManager()
    await flushPromises()

    await wrapper.find('[data-testid="bulk-enable-product"]').trigger('click')
    await flushPromises()

    expect(puts).toEqual([
      [A, 7, true],
      [A, 8, true],
    ])
  })

  it('Disable all: one PUT per agent, false, against the viewed product', async () => {
    api.assignments.list.mockResolvedValue({
      data: {
        assignments: [
          { template_id: 7, is_active: true, template_is_active: true },
          { template_id: 8, is_active: true, template_is_active: true },
        ],
        count: 2,
      },
    })
    const wrapper = mountManager()
    await flushPromises()

    await wrapper.find('[data-testid="bulk-disable-product"]').trigger('click')
    await flushPromises()

    expect(puts).toEqual([
      [A, 7, false],
      [A, 8, false],
    ])
  })

  it('reports the number of agents actually changed', async () => {
    api.assignments.list.mockResolvedValue(TWO_OFF)
    const wrapper = mountManager()
    await flushPromises()

    await wrapper.find('[data-testid="bulk-enable-product"]').trigger('click')
    await flushPromises()

    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('2 agents') }),
    )
  })

  it('skips rows already in the target state, and says so rather than claiming a change', async () => {
    api.assignments.list.mockResolvedValue({
      data: {
        assignments: [
          { template_id: 7, is_active: true, template_is_active: true },
          { template_id: 8, is_active: true, template_is_active: true },
        ],
        count: 2,
      },
    })
    const wrapper = mountManager()
    await flushPromises()

    await wrapper.find('[data-testid="bulk-enable-product"]').trigger('click')
    await flushPromises()

    expect(puts).toEqual([])
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringMatching(/already enabled/i) }),
    )
  })

  it('one failure does not abandon the rest, and the casualty is named', async () => {
    api.assignments.list.mockResolvedValue(TWO_OFF)
    api.assignments.toggle.mockImplementation((pid, tid, active) => {
      puts.push([pid, tid, active])
      if (tid === 7) return Promise.reject(new Error('boom'))
      return Promise.resolve({ data: { is_active: active } })
    })
    const wrapper = mountManager()
    await flushPromises()

    await wrapper.find('[data-testid="bulk-enable-product"]').trigger('click')
    await flushPromises()

    expect(puts.map((p) => p[1])).toEqual([7, 8])
    expect(showToast).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'error',
        message: expect.stringContaining('analyzer'),
      }),
    )
  })

  it('the bulk control is unavailable with no product in view', async () => {
    api.assignments.list.mockResolvedValue(TWO_OFF)
    const wrapper = mountManager({ currentProductId: null })
    await flushPromises()

    expect(wrapper.find('[data-testid="product-bulk-menu"]').attributes('disabled')).toBeDefined()
  })
})



describe('FE-9610b — the list still follows the product tab (FE-9604 regression guard)', () => {
  it('switching the product tab re-scopes the rows', async () => {
    api.templates.list.mockResolvedValue({ data: [row()] })
    api.assignments.list.mockImplementation((pid) =>
      Promise.resolve({
        data: {
          assignments: [{ template_id: 7, is_active: pid === A, template_is_active: true }],
          count: 1,
        },
      }),
    )

    const wrapper = mountManager()
    await flushPromises()
    expect(api.assignments.list).toHaveBeenCalledWith(A)
    expect(togglesChecked(wrapper)).toEqual([true])

    useProductStore().currentProductId = B
    await flushPromises()

    expect(api.assignments.list).toHaveBeenCalledWith(B)
    expect(togglesChecked(wrapper)).toEqual([false])
  })
})


describe('FE-9610b — house rules', () => {
  const read = (p) => readFileSync(resolve(__dirname, p), 'utf8')
  const TOUCHED = [
    './TemplateManager.vue',
    './templates/TemplatesTable.vue',
    './common/EmptyState.vue',
  ]

  it.each(TOUCHED)('%s carries no hardcoded hex colour', (path) => {
    const source = read(path).replace(/#\{[^}]*\}/g, '')
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })

  it('the new bulk control sits in the wrapping filter bar, so the tablet band still fits', () => {
    const source = read('./templates/TemplateToolbar.vue')
    const bar = source.slice(
      source.indexOf('class="filter-bar"'),
      source.indexOf('</template>'),
    )
    expect(bar).toContain('data-testid="product-bulk-menu"')
    expect(source).toMatch(/@media \(max-width: 960px\)[\s\S]*?flex-wrap: wrap/)
  })
})


describe('FE-9610c — show all products', () => {
  const ATLAS_AGENT = row({ id: 7, name: 'documenter', role: 'documenter', product_id: A })
  const BEACON_AGENT = row({ id: 8, name: 'documenter-2', role: 'documenter', product_id: B })

  beforeEach(() => {
    api.templates.list.mockImplementation((productId) =>
      Promise.resolve({
        data: productId === A ? [ATLAS_AGENT] : [ATLAS_AGENT, BEACON_AGENT],
      }),
    )
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: 7, is_active: true }], count: 1 },
    })
  })

  const setScope = async (w, value) => {
    w.findComponent('[data-testid="show-all-products"]').vm.$emit('update:modelValue', value)
    await flushPromises()
  }

  it('scopes to the viewed product by default', async () => {
    const wrapper = mountManager()
    await flushPromises()

    expect(api.templates.list).toHaveBeenCalledWith(A)
    expect(wrapper.findAll('[data-testid^="template-toggle-"]')).toHaveLength(1)
  })

  it('switching it on reads across every product', async () => {
    const wrapper = mountManager()
    await flushPromises()

    await setScope(wrapper, 'all')

    expect(api.templates.list).toHaveBeenLastCalledWith(null)
  })

  it('every row names its owning product', async () => {
    const wrapper = mountManager()
    await flushPromises()
    await setScope(wrapper, 'all')

    expect(wrapper.find('[data-testid="product-chip-7"]').text()).toBe('Atlas')
    expect(wrapper.find('[data-testid="product-chip-8"]').text()).toBe('Beacon')
  })

  it('the owner is read from the chip, never inferred from the name suffix', async () => {
    const wrapper = mountManager()
    await flushPromises()
    await setScope(wrapper, 'all')

    expect(wrapper.find('[data-testid="product-chip-8"]').text()).toBe('Beacon')
    expect(wrapper.find('[data-testid="product-chip-8"]').text()).not.toMatch(/-?2/)
  })

  it('adds the product column only in show-all', async () => {
    const wrapper = mountManager()
    await flushPromises()
    expect(wrapper.vm.headers.map((h) => h.key)).not.toContain('product_id')

    await setScope(wrapper, 'all')
    expect(wrapper.vm.headers.map((h) => h.key)).toContain('product_id')
  })

  it('a foreign row is read-only and names the tab that owns it', async () => {
    const wrapper = mountManager()
    await flushPromises()
    await setScope(wrapper, 'all')

    expect(wrapper.find('[data-testid="foreign-agent-8"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="template-toggle-documenter"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Switch this agent on from the Beacon tab.')
  })

  it('product-scoped actions are unavailable in show-all', async () => {
    const wrapper = mountManager()
    await flushPromises()
    await setScope(wrapper, 'all')

    expect(wrapper.find('[data-testid="product-bulk-menu"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="add-default-agents"]').attributes('disabled')).toBeDefined()
  })
})


describe('FE-9610c — no product in view', () => {
  it('explains that agents belong to a product, and asks for nothing', async () => {
    const wrapper = mountManager({ currentProductId: null, products: [] })
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-no-product"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="empty-no-agents"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="empty-no-product"]').text()).toMatch(/crew of agents/i)
    expect(api.templates.activeCount).not.toHaveBeenCalled()
    expect(api.templates.list).not.toHaveBeenCalled()
  })

  it('offers no way to create an agent with nowhere to put it', async () => {
    const wrapper = mountManager({ currentProductId: null, products: [] })
    await flushPromises()

    expect(wrapper.find('[data-testid="add-default-agents"]').attributes('disabled')).toBeDefined()
  })
})
