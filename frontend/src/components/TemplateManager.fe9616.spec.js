import { describe, it, expect, beforeEach, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import TemplateManager from '@/components/TemplateManager.vue'

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
    products: { list: vi.fn(() => Promise.resolve({ data: [] })) },
    settings: {
      getGeneral: vi.fn(() => Promise.resolve({ data: { settings: { closeout_mode: 'hitl' } } })),
      getHeadlessLaunch: vi.fn(() => Promise.resolve({ data: { allow_headless_launch: true } })),
      getExecutionModeDefault: vi.fn(() =>
        Promise.resolve({ data: { execution_mode_default: 'ask' } }),
      ),
      getAgentSilenceThreshold: vi.fn(() =>
        Promise.resolve({ data: { agent_silence_threshold_minutes: 10 } }),
      ),
      getAgentCheckinCadence: vi.fn(() =>
        Promise.resolve({ data: { agent_checkin_cadence_minutes: 10 } }),
      ),
    },
  }
  return { api: apiObj, default: apiObj }
})
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import api from '@/services/api'

const dataTableStub = {
  props: ['headers', 'items', 'loading', 'search', 'itemsPerPage'],
  template: `<div class="v-data-table" />`,
}
const listItemStub = {
  props: ['title', 'prependIcon'],
  template: `<div class="v-list-item" v-bind="$attrs" :title="title"><slot /></div>`,
}
const selectStub = {
  props: ['modelValue', 'items'],
  emits: ['update:modelValue'],
  template: `<select class="v-select" v-bind="$attrs" @change="$emit('update:modelValue', $event.target.value)">
    <option v-for="i in (items || [])" :key="i.value ?? i" :value="i.value ?? i" :selected="(i.value ?? i) === modelValue">{{ i.title ?? i }}</option>
  </select>`,
}
const behaviourDialogStub = {
  props: ['modelValue'],
  template: `<div class="agent-behaviour-dialog-stub" :data-open="String(modelValue)" />`,
}

const A = 'prod-a'
const PRODUCTS = [{ id: A, name: 'Atlas', is_active: true }]

function mountManager({ currentProductId = A } = {}) {
  return mount(TemplateManager, {
    global: {
      plugins: [
        createTestingPinia({
          initialState: {
            user: { currentUser: { id: 1, username: 'u', role: 'admin', tenant_key: 'tk' } },
            products: { activeProduct: null, currentProductId, products: PRODUCTS },
          },
          stubActions: false,
        }),
      ],
      stubs: {
        'v-data-table': dataTableStub,
        'v-select': selectStub,
        'v-list-item': listItemStub,
        'v-menu': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
        'v-tooltip': {
          props: ['text'],
          template: '<div><slot name="activator" :props="{}" /><slot />{{ text }}</div>',
        },
        'v-dialog': { template: '<div><slot /></div>' },
        AgentBehaviourDialog: behaviourDialogStub,
        Teleport: true,
      },
    },
  })
}

const scopeSelect = (w) => w.find('[data-testid="show-all-products"]')
const setScope = async (w, value) => {
  await scopeSelect(w).setValue(value)
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  api.templates.list.mockResolvedValue({ data: [] })
  api.assignments.list.mockResolvedValue({ data: { assignments: [], count: 0 } })
})

describe('FE-9616 — the behaviour dialog opens from the toolbar', () => {
  it('starts shut, and the button opens it', async () => {
    const wrapper = mountManager()
    await flushPromises()

    const dialog = wrapper.find('.agent-behaviour-dialog-stub')
    expect(dialog.attributes('data-open')).toBe('false')

    await wrapper.find('[data-testid="agent-behaviour-button"]').trigger('click')

    expect(wrapper.find('.agent-behaviour-dialog-stub').attributes('data-open')).toBe('true')
  })

  it('shows no badge until a setting differs from its default', async () => {
    const wrapper = mountManager()
    await flushPromises()

    expect(wrapper.find('[data-testid="agent-behaviour-badge"]').exists()).toBe(false)

    wrapper.findComponent(behaviourDialogStub).vm.$emit('update:changed-count', 3)
    await flushPromises()

    expect(wrapper.find('[data-testid="agent-behaviour-badge"]').text()).toBe('3')
  })
})

describe('FE-9616 — the scope dropdown', () => {
  it('offers exactly this product and all products, scoped to the product by default', async () => {
    const wrapper = mountManager()
    await flushPromises()

    const options = scopeSelect(wrapper).findAll('option')
    expect(options.map((o) => o.text())).toEqual(['This product', 'All products'])
    expect(scopeSelect(wrapper).element.value).toBe('product')
  })

  it('choosing all products widens the read, and choosing back narrows it', async () => {
    const wrapper = mountManager()
    await flushPromises()

    await setScope(wrapper, 'all')
    expect(api.templates.list).toHaveBeenLastCalledWith(null)

    await setScope(wrapper, 'product')
    expect(api.templates.list).toHaveBeenLastCalledWith(A)
  })
})

describe('FE-9616 — the bulk menu and the new-template button', () => {
  it('carries the three product-wide actions, and nothing else', async () => {
    const wrapper = mountManager()
    await flushPromises()

    const titles = wrapper.findAll('.v-list-item').map((i) => i.attributes('title'))
    expect(titles).toEqual([
      'Enable all for this product',
      'Disable all for this product',
      'Add default agents',
    ])
  })

  it.each([
    ['product-bulk-menu', 'Bulk actions for this product'],
    ['new-template', 'New template'],
  ])('%s names itself with a native title, not a tooltip', async (testid, label) => {
    const wrapper = mountManager()
    await flushPromises()

    const btn = wrapper.find(`[data-testid="${testid}"]`)
    expect(btn.attributes('title')).toBe(label)
    expect(btn.attributes('aria-label')).toBeTruthy()
  })

  it('keeps Add default agents reachable before the assignments have loaded', async () => {
    let releaseAssignments
    api.assignments.list.mockReturnValue(
      new Promise((resolve) => {
        releaseAssignments = () => resolve({ data: { assignments: [], count: 0 } })
      }),
    )

    const wrapper = mountManager()
    await flushPromises()

    const itemDisabled = (id) => wrapper.find(`[data-testid="${id}"]`).attributes('disabled')

    expect(wrapper.find('[data-testid="product-bulk-menu"]').attributes('disabled')).toBeUndefined()
    expect(itemDisabled('add-default-agents')).toBe('false')
    expect(itemDisabled('bulk-enable-product')).toBe('true')

    releaseAssignments()
    await flushPromises()

    expect(itemDisabled('bulk-enable-product')).toBe('false')
  })

  it('Add default agents still calls the import endpoint', async () => {
    const wrapper = mountManager()
    await flushPromises()

    await wrapper.find('[data-testid="add-default-agents"]').trigger('click')
    await flushPromises()

    expect(api.templates.importDefaults).toHaveBeenCalledTimes(1)
  })

  it('disables the product-scoped controls under All products', async () => {
    const wrapper = mountManager()
    await flushPromises()
    expect(wrapper.find('[data-testid="new-template"]').attributes('disabled')).toBeUndefined()

    await setScope(wrapper, 'all')

    expect(wrapper.find('[data-testid="new-template"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="product-bulk-menu"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="add-default-agents"]').attributes('disabled')).toBeDefined()
  })
})


describe('FE-9616 — the toolbar stays with the list it belongs to', () => {
  const read = (p) => readFileSync(resolve(__dirname, p), 'utf8')
  const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')

  it('the filter bar is sticky, under whatever the app bar reserves', () => {
    const source = read('./templates/TemplateToolbar.vue')
    const rule = source.slice(source.indexOf('.filter-bar {'), source.indexOf('.filter-search {'))

    expect(rule).toContain('position: sticky')
    expect(rule).toContain('top: var(--v-layout-top, 0px)')
    expect(rule).toMatch(/background:\s*rgb\(var\(--v-theme-background\)\)/)
  })

  it('ToolsView unclips the window the sticky bar lives in', () => {
    const source = read('../views/ToolsView.vue')
    const rule = source.slice(source.indexOf('.pill-tabs-content :deep(.v-window)'))

    expect(rule).toMatch(/\.pill-tabs-content :deep\(\.v-window\)\s*\{\s*overflow:\s*visible;/)
  })

  it('App.vue keeps the horizontal clip on html only, never on body', () => {
    const source = stripComments(read('../App.vue'))
    const styles = source.slice(source.indexOf('<style'))

    const bodyRules = [...styles.matchAll(/([^{}]*)\{([^{}]*)\}/g)]
      .filter(([, selector]) => selector.split(',').some((s) => s.trim() === 'body'))
      .map(([, , body]) => body)

    expect(bodyRules.length).toBeGreaterThan(0)
    for (const declarations of bodyRules) expect(declarations).not.toMatch(/overflow/)

    const htmlRules = [...styles.matchAll(/([^{}]*)\{([^{}]*)\}/g)]
      .filter(([, selector]) => selector.split(',').some((s) => s.trim() === 'html'))
      .map(([, , body]) => body)
    expect(htmlRules.some((d) => /overflow-x:\s*hidden/.test(d))).toBe(true)
  })
})
