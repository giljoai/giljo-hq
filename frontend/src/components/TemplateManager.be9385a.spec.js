/**
 * TemplateManager.be9385a.spec.js — BE-9385a
 *
 * The Agents toggle used to write the TENANT-WIDE `agent_templates.is_active`
 * flag (`api.templates.update`). Nothing about it was per-product, which is why
 * curating agents while product A was active did nothing for product A and
 * everything for every other product — the reported export leak.
 *
 * It now writes the `product_agent_assignments` junction, scoped to the ACTIVE
 * product, through the PUT that already existed and had zero callers
 * (`api.assignments.toggle`). These tests pin that contract, the tolerance
 * fallback, and the one subtle part: WHICH product id is used.
 *
 * Kept in its own file rather than added to TemplateManager.spec.js — that spec
 * is a deliberate byte-unchanged characterization of the FE-6042b split and is
 * documented as such at its head.
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
    may_be_stale: false,
    user_managed_export: false,
    _system: false,
    last_exported_at: '2024-01-01T12:00:00Z',
    updated_at: '2024-01-02T12:00:00Z',
    ...overrides,
  }
}

function mountManager({ products } = {}) {
  return mount(TemplateManager, {
    global: {
      plugins: [
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
    const wrapper = mountManager()
    await flushPromises()

    await wrapper.find('[data-testid="template-toggle-analyzer"]').setValue(false)
    await flushPromises()

    expect(api.assignments.toggle).toHaveBeenCalledWith(ACTIVE_PRODUCT_ID, 7, false)
    expect(api.templates.update).not.toHaveBeenCalled()
  })

  it('FE-9524/D1: uses the BROWSED (viewed) product, not the legacy activeProduct slot, when they diverge', async () => {
    // FE-9524/D1 retired "active product" as a global concept -- several
    // products may be shown at once, and the server exports/spawns for
    // whichever product_id a call names explicitly (BE-9523), not for one
    // tenant-wide "the active product". `effectiveProductId` (the viewed tab)
    // is therefore the correct scope; keying on `activeProduct` here would
    // curate agents for whichever product happens to be MOST RECENTLY shown,
    // not the one on screen -- this is the exact stale-reader class the
    // project record calls out (finding 3), rewritten from the pre-D1 pin
    // that asserted the opposite.
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

  it('falls back to the tenant flag when there is no active product', async () => {
    // Tolerance mirror: with nothing to scope to, the old behaviour is better
    // than a toggle that silently does nothing.
    const wrapper = mountManager({ products: { activeProduct: null } })
    await flushPromises()

    await wrapper.find('[data-testid="template-toggle-analyzer"]').setValue(false)
    await flushPromises()

    expect(api.templates.update).toHaveBeenCalledWith(7, { is_active: false })
    expect(api.assignments.toggle).not.toHaveBeenCalled()
  })

  it('shows the per-product state, not the tenant flag, when a junction row exists', async () => {
    // Tenant-active but disabled for THIS product: the switch must read off.
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: 7, is_active: false }], count: 1 },
    })

    const wrapper = mountManager()
    await flushPromises()

    expect(api.assignments.list).toHaveBeenCalledWith(ACTIVE_PRODUCT_ID)
    expect(wrapper.find('[data-testid="template-toggle-analyzer"]').element.checked).toBe(false)
  })

  it('falls back to the tenant flag for a template with no junction row', async () => {
    // A product that has never been curated shows every tenant-active agent —
    // the same tolerance the server applies when selecting what to export.
    const wrapper = mountManager()
    await flushPromises()

    expect(wrapper.find('[data-testid="template-toggle-analyzer"]').element.checked).toBe(true)
  })

  it('disables the per-product switch for an agent retired tenant-wide', async () => {
    // The master retire switch beats the per-product one; re-enabling it belongs
    // in the edit dialog's Status field, which is the visually distinct affordance.
    api.templates.list.mockResolvedValue({ data: [makeTemplate({ is_active: false })] })

    const wrapper = mountManager()
    await flushPromises()

    expect(wrapper.find('[data-testid="template-toggle-analyzer"]').element.disabled).toBe(true)
  })
})
