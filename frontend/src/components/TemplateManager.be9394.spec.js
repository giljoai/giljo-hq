
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import TemplateManager from '@/components/TemplateManager.vue'

vi.mock('@/services/api', () => {
  const apiObj = {
    templates: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      create: vi.fn(() => Promise.resolve({ data: {} })),
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
      toggle: vi.fn(() => Promise.resolve({ data: { is_active: true } })),
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

const ACTIVE_PRODUCT_ID = 'prod-active-9394'

function row(overrides = {}) {
  return {
    id: 77,
    name: 'implementer-be9394',
    role: 'implementer',
    cli_tool: 'claude',
    description: 'before',
    user_instructions: 'prose',
    model: 'sonnet',
    tools: null,
    is_active: true,
    is_default: false,
    ...overrides,
  }
}

function mountManager() {
  return mount(TemplateManager, {
    global: {
      plugins: [
        createTestingPinia({
          initialState: {
            user: {
              currentUser: { id: 1, username: 'testuser', role: 'admin', tenant_key: 'tk_test' },
            },
            products: { activeProduct: { id: ACTIVE_PRODUCT_ID, name: 'Active' } },
          },
          stubActions: false,
        }),
      ],
      stubs: {
        'v-data-table': { props: ['headers', 'items'], template: '<div />' },
        'v-menu': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
        'v-list-item': { props: ['title'], template: '<div><slot /></div>' },
        'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
        'v-dialog': { template: '<div><slot /></div>' },
        Teleport: true,
      },
    },
  })
}

describe('BE-9394 — the retire switch gets a writer, without becoming a hazard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.templates.list.mockResolvedValue({ data: [] })
    api.assignments.list.mockResolvedValue({ data: { assignments: [], count: 0 } })
  })

  it('an ordinary edit does NOT send is_active — driven through the real edit flow', async () => {
    const wrapper = mountManager()
    await flushPromises()

    wrapper.vm.editTemplate(row())
    wrapper.vm.editingTemplate.description = 'after'

    await wrapper.vm.saveTemplate()
    await flushPromises()

    expect(api.templates.update).toHaveBeenCalledTimes(1)
    const [id, payload] = api.templates.update.mock.calls[0]

    expect(id).toBe(77)
    expect(Object.hasOwn(payload, 'is_active')).toBe(false)
    expect(payload.description).toBe('after')
  })

  it('no edit path sends an account-wide enable field', async () => {
    const wrapper = mountManager()
    await flushPromises()

    wrapper.vm.editTemplate(row({ is_active: true }))
    wrapper.vm.editingTemplate.is_active = false
    wrapper.vm.editingTemplate.description = 'after'

    await wrapper.vm.saveTemplate()
    await flushPromises()

    const [, payload] = api.templates.update.mock.calls[0]
    expect(Object.hasOwn(payload, 'is_active')).toBe(false)
  })

  it('no edit path can move an agent to another product', async () => {
    const wrapper = mountManager()
    await flushPromises()

    wrapper.vm.editTemplate(row({ product_id: 'prod-other' }))
    wrapper.vm.editingTemplate.description = 'after'

    await wrapper.vm.saveTemplate()
    await flushPromises()

    const [, payload] = api.templates.update.mock.calls[0]
    expect(Object.hasOwn(payload, 'product_id')).toBe(false)
  })

  it('the per-product toggle writes only the assignment for this product', async () => {
    const wrapper = mountManager()
    await flushPromises()

    await wrapper.vm.handleToggleActive(row({ is_active: true }), false)
    await flushPromises()

    expect(api.assignments.toggle).toHaveBeenCalledTimes(1)
    expect(api.assignments.toggle).toHaveBeenCalledWith(ACTIVE_PRODUCT_ID, 77, false)
    expect(api.templates.update).not.toHaveBeenCalled()
  })
})
