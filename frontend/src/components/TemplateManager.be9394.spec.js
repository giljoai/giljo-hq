/**
 * TemplateManager.be9394.spec.js — BE-9394
 *
 * Two flags, one story. Since BE-9385a there have been two activation flags with
 * different meanings and unequal UI support:
 *
 *   - `agent_templates.is_active`        — the tenant-wide RETIRE switch
 *   - `product_agent_assignments.is_active` — per-product, written by the inline switch
 *
 * The tenant flag had NO writer at all while a product was active: the inline switch
 * writes only the junction, and the edit dialog's update payload did not carry the
 * field. So a user could not retire an agent everywhere from the UI. BE-9394 gives it
 * a writer — a control in the edit dialog — and these are the tests for it.
 *
 * The design point worth understanding before changing any of this: the update payload
 * carries `is_active` ONLY when the user actually moved the retire control, diffed
 * against the snapshot taken when the dialog opened (`useTemplateEditDialog`). That
 * conditional is the safety property, for two independent reasons:
 *
 *  1. An ordinary edit must never carry the tenant flag, or saving any change to a
 *     deliberately retired agent would silently un-retire it. That is exactly the
 *     boundary BE-9391's guard pinned — preserved here, not weakened.
 *  2. `editingTemplate` is a COPY taken at dialog-open while WebSocket updates keep
 *     patching the live row underneath it, so an unconditional send would write a
 *     STALE flag over a concurrent change.
 *
 * These tests drive the REAL flow — through `editTemplate`, so a snapshot actually
 * exists. BE-9391's own guard reaches the same conclusion via a path where
 * `originalSnapshot` is null, which is a weaker check; that file stays green and
 * untouched, and this one pins the behaviour on the honest path.
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

const ACTIVE_PRODUCT_ID = 'prod-active-9394'

/** A row exactly as the list endpoint returns one: the tenant flag is genuine. */
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

    // The honest path: open the dialog the way the UI does, so a snapshot exists.
    wrapper.vm.editTemplate(row())
    wrapper.vm.editingTemplate.description = 'after'

    await wrapper.vm.saveTemplate()
    await flushPromises()

    expect(api.templates.update).toHaveBeenCalledTimes(1)
    const [id, payload] = api.templates.update.mock.calls[0]

    expect(id).toBe(77)
    // Asserted on key PRESENCE: sending is_active: true would be just as wrong as
    // sending false, because the value is a stale copy taken when the dialog opened.
    expect(Object.hasOwn(payload, 'is_active')).toBe(false)
    expect(payload.description).toBe('after')
  })

  it('retiring the agent DOES send is_active: false', async () => {
    const wrapper = mountManager()
    await flushPromises()

    wrapper.vm.editTemplate(row({ is_active: true }))
    wrapper.vm.editingTemplate.is_active = false // the user moves the retire control

    await wrapper.vm.saveTemplate()
    await flushPromises()

    const [, payload] = api.templates.update.mock.calls[0]
    expect(Object.hasOwn(payload, 'is_active')).toBe(true)
    expect(payload.is_active).toBe(false)
  })

  it('un-retiring sends is_active: true, so the switch works in both directions', async () => {
    const wrapper = mountManager()
    await flushPromises()

    wrapper.vm.editTemplate(row({ is_active: false }))
    wrapper.vm.editingTemplate.is_active = true

    await wrapper.vm.saveTemplate()
    await flushPromises()

    const [, payload] = api.templates.update.mock.calls[0]
    expect(payload.is_active).toBe(true)
  })

  it('moving ONLY the retire control enables Save', async () => {
    const wrapper = mountManager()
    await flushPromises()

    wrapper.vm.editTemplate(row({ is_active: true }))
    expect(wrapper.vm.hasChanges).toBe(false)

    wrapper.vm.editingTemplate.is_active = false
    await flushPromises()

    // Save is :disabled="!hasChanges", so without is_active in TRACKED_FIELDS the
    // control would move and the user could not save the change they just made.
    expect(wrapper.vm.hasChanges).toBe(true)
  })

  it('the per-product toggle NEVER writes the tenant flag', async () => {
    const wrapper = mountManager()
    await flushPromises()

    await wrapper.vm.handleToggleActive(row({ is_active: true }), false)
    await flushPromises()

    // The hard constraint of this project, ruled twice: a per-product flip must not
    // reach agent_templates.is_active, or disabling an agent in one product would
    // retire it everywhere -- and re-enabling it would silently un-retire an agent
    // the user had deliberately retired.
    expect(api.assignments.toggle).toHaveBeenCalledTimes(1)
    expect(api.assignments.toggle).toHaveBeenCalledWith(ACTIVE_PRODUCT_ID, 77, false)
    expect(api.templates.update).not.toHaveBeenCalled()
  })
})
