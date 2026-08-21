/**
 * TemplateManager.be9391.spec.js — BE-9391
 *
 * The backend half of BE-9391 gives a newly-usable agent a junction row in the
 * active product. That door only opens for an agent that is tenant-ACTIVE — and
 * the UI never made one.
 *
 * `TemplateCreate.is_active` defaults to false server-side, and `saveTemplate`'s
 * create payload did not send the key, so every agent created here was born
 * inactive. The inline Active switch does not fix that: since BE-9385a it writes
 * only the `product_agent_assignments` junction whenever a product is active
 * (`useProductAgentAssignments.toggleAgent`), never the tenant flag. The edit
 * dialog's update payload does not carry `is_active` either. So with a product
 * active there was NO route through this component that could make an agent
 * tenant-active — it showed as ON and stayed unspawnable, because every
 * selection site still requires `AgentTemplate.is_active`.
 *
 * The fix is one line: the create payload sends `is_active: true`. These tests
 * are the red/green proof of it. The second test is the guard on the ruling's
 * boundary — the update branch must NOT gain the field, or a per-product edit
 * would silently un-retire an agent the user retired tenant-wide.
 *
 * Own file rather than added to TemplateManager.spec.js — that spec is a
 * deliberate byte-unchanged characterization of the FE-6042b split and is
 * documented as such at its head. Same reasoning as the BE-9385a spec beside it.
 *
 * Edition scope: CE
 */

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

describe('BE-9391 — an agent created in the UI is born tenant-active', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.templates.list.mockResolvedValue({ data: [] })
    api.assignments.list.mockResolvedValue({ data: { assignments: [], count: 0 } })
  })

  it('sends is_active: true in the create payload', async () => {
    const wrapper = mountManager()
    await flushPromises()

    // Exactly what the create dialog does: no id, a role, nothing about activeness.
    wrapper.vm.editingTemplate.id = null
    wrapper.vm.editingTemplate.role = 'implementer'
    wrapper.vm.editingTemplate.custom_suffix = 'be9391'

    await wrapper.vm.saveTemplate()
    await flushPromises()

    expect(api.templates.create).toHaveBeenCalledTimes(1)
    const payload = api.templates.create.mock.calls[0][0]

    expect(payload.is_active).toBe(true)
    // Asserted on the key's presence too: the server defaults is_active to false,
    // so an omitted key is not the same thing as a false one -- omission is the
    // exact shape of the original defect and would otherwise read as "not true".
    expect(Object.hasOwn(payload, 'is_active')).toBe(true)
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
    // The tenant flag is the master retire switch; the inline toggle is
    // per-product. If an ordinary edit started carrying is_active, saving any
    // change to a deliberately retired agent would silently un-retire it.
  })
})
