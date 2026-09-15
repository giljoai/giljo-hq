
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

const ACTIVE_PRODUCT_ID = 'prod-active-9391'

function mountManager(overrides = {}) {
  return mount(TemplateManager, {
    global: {
      plugins: [
        createTestingPinia({
          initialState: {
            user: {
              currentUser: { id: 1, username: 'testuser', role: 'admin', tenant_key: 'tk_test' },
            },
            products: {
              activeProduct: { id: ACTIVE_PRODUCT_ID, name: 'Active' },
              products: [{ id: ACTIVE_PRODUCT_ID, name: 'Active', is_active: true }],
              ...(overrides.products || {}),
            },
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

describe('BE-9391 — an agent created in the UI is born tenant-active', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.templates.list.mockResolvedValue({ data: [] })
    api.assignments.list.mockResolvedValue({ data: { assignments: [], count: 0 } })
  })

  it('names the owning product, and sends no account-wide enable field', async () => {
    const wrapper = mountManager()
    await flushPromises()

    wrapper.vm.editingTemplate.id = null
    wrapper.vm.editingTemplate.role = 'implementer'
    wrapper.vm.editingTemplate.custom_suffix = 'be9391'

    await wrapper.vm.saveTemplate()
    await flushPromises()

    expect(api.templates.create).toHaveBeenCalledTimes(1)
    const payload = api.templates.create.mock.calls[0][0]

    expect(payload.product_id).toBe(ACTIVE_PRODUCT_ID)
    expect(Object.hasOwn(payload, 'is_active')).toBe(false)
  })

  it('refuses to create at all with no product tab in view', async () => {
    const wrapper = mountManager({ products: { activeProduct: null, currentProductId: null } })
    await flushPromises()

    wrapper.vm.editingTemplate.id = null
    wrapper.vm.editingTemplate.role = 'implementer'

    await wrapper.vm.saveTemplate()
    await flushPromises()

    expect(api.templates.create).not.toHaveBeenCalled()
  })

  it('does NOT send is_active in the update payload', async () => {
    const wrapper = mountManager()
    await flushPromises()

    wrapper.vm.editingTemplate.id = 42
    wrapper.vm.editingTemplate.role = 'implementer'

    await wrapper.vm.saveTemplate()
    await flushPromises()

    expect(api.templates.update).toHaveBeenCalledTimes(1)
    const [id, payload] = api.templates.update.mock.calls[0]

    expect(id).toBe(42)
    expect(Object.hasOwn(payload, 'is_active')).toBe(false)
  })
})
