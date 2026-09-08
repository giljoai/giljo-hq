/**
 * TemplateManager.spec.js — FE-6042b
 *
 * Characterization spec for TemplateManager.vue.
 * Written BEFORE the container/presentational split so the split is validated
 * by proving this same file (byte-unchanged) still passes after refactoring.
 *
 * Strategy: ALL assertions target either
 *   (a) api.templates.* mock calls (the public contract that never moves), OR
 *   (b) container-retained refs (editDialog, deleteDialog, resetDialog,
 *       deletingTemplate, resettingTemplate), OR
 *   (c) DOM testids that must be present whether the node lives in the container
 *       or in a child component (e.g., closeout-mode-toggle, template-toggle-${role}).
 *
 * The v-data-table stub iterates :items and renders named item.* slots so that
 * row-level testids (template-toggle-*, action menu items) are reachable in
 * jsdom. This stub shape also works once the table moves into TemplatesTable.
 *
 * FE-9385c: this is the SINGLE spec file for TemplateManager.vue. A second
 * TemplateManager.spec.js under frontend/tests/components/ used to duplicate
 * groups 13 and 14 verbatim; both runners collected it, so those nine tests ran
 * twice for no added coverage. It has been deleted — put new TemplateManager
 * cases here, not in a parallel file.
 *
 * Edition scope: CE
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import TemplateManager from '@/components/TemplateManager.vue'

// ---------------------------------------------------------------------------
// API mock — supplement the global setup.js mock with template-specific spies.
// ---------------------------------------------------------------------------
vi.mock('@/services/api', () => {
  const apiObj = {
    templates: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      get: vi.fn(() => Promise.resolve({ data: {} })),
      create: vi.fn(() => Promise.resolve({ data: { id: 42 } })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
      preview: vi.fn(() => Promise.resolve({ data: { preview: 'Mock preview content' } })),
      activeCount: vi.fn(() =>
        Promise.resolve({ data: { active_count: 2, limit: 15, available: 13 } })
      ),
      history: vi.fn(() => Promise.resolve({ data: [] })),
      restore: vi.fn(() => Promise.resolve({ data: { success: true } })),
      reset: vi.fn(() => Promise.resolve({ data: { success: true } })),
      importDefaults: vi.fn(() =>
        Promise.resolve({ data: { added: [], added_as_duplicate: [], skipped_identical: [] } })
      ),
    },
    settings: {
      getGeneral: vi.fn(() =>
        Promise.resolve({ data: { settings: { closeout_mode: 'hitl' } } })
      ),
      updateGeneral: vi.fn(() => Promise.resolve({ data: { success: true } })),
      // BE-9084: account-wide Headless-vs-HITL launch toggle
      getHeadlessLaunch: vi.fn(() =>
        Promise.resolve({ data: { allow_headless_launch: false } })
      ),
      updateHeadlessLaunch: vi.fn(() =>
        Promise.resolve({ data: { allow_headless_launch: true } })
      ),
      get: vi.fn(() => Promise.resolve({ data: {} })),
      update: vi.fn(() => Promise.resolve({ data: { success: true } })),
    },
    auth: {
      me: vi.fn(() => Promise.resolve({ data: { id: 1, username: 'testuser', role: 'admin' } })),
    },
  }
  return { api: apiObj, default: apiObj }
})

// ---------------------------------------------------------------------------
// Captured showToast spy (must be declared before vi.mock for hoisting)
// ---------------------------------------------------------------------------
let mockShowToast

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({
    showToast: (...args) => mockShowToast(...args),
  }),
}))

// ---------------------------------------------------------------------------
// Stubs
// ---------------------------------------------------------------------------

/**
 * v-data-table stub that renders item.* slots for every item.
 * This makes row-level testids reachable in jsdom both BEFORE and AFTER the
 * table moves into TemplatesTable — the slot names are the same either way.
 */
const dataTableStub = {
  props: ['headers', 'items', 'loading', 'search', 'itemsPerPage'],
  template: `
    <div class="v-data-table">
      <div v-for="item in (items || [])" :key="item.id" class="v-data-table-row">
        <slot name="item.name" :item="item" />
        <slot name="item.role" :item="item" />
        <slot name="item.is_active" :item="item" />
        <slot name="item.export_status" :item="item" />
        <slot name="item.updated_at" :item="item" />
        <slot name="item.actions" :item="item" />
      </div>
    </div>
  `,
}

/**
 * v-switch stub that properly emits update:model-value so toggle handlers fire.
 */
const switchStub = {
  props: ['modelValue', 'disabled', 'color', 'hideDetails', 'density', 'ariaLabel'],
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

/**
 * v-menu that renders both activator and default slots so action items appear.
 */
const menuStub = {
  template: `<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>`,
}

const listItemStub = {
  props: ['title', 'prependIcon'],
  template: `<div class="v-list-item" v-bind="$attrs" :title="title"><slot /></div>`,
}

const tooltipStub = {
  props: ['text', 'location'],
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

// ---------------------------------------------------------------------------
// Mount helper
// ---------------------------------------------------------------------------

function mountTemplateManager(options = {}) {
  return mount(TemplateManager, {
    global: {
      plugins: [
        createTestingPinia({
          initialState: {
            user: {
              currentUser: {
                id: 1,
                username: 'testuser',
                role: 'admin',
                tenant_key: 'tk_test',
              },
            },
          },
          stubActions: false,
        }),
      ],
      stubs: {
        'v-data-table': dataTableStub,
        'v-switch': switchStub,
        'v-menu': menuStub,
        'v-list-item': listItemStub,
        'v-tooltip': tooltipStub,
        // Keep dialog as passthrough so internal state (editingTemplate) works
        'v-dialog': { template: '<div class="v-dialog"><slot /></div>' },
        Teleport: true,
        ...options.stubs,
      },
    },
    ...options.mountOptions,
  })
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeTemplate(overrides = {}) {
  return {
    id: 7,
    name: 'My Analyzer',
    role: 'analyzer',
    category: 'role',
    cli_tool: 'claude',
    custom_suffix: 'v2',
    background_color: '#abc123',
    model: 'sonnet',
    user_instructions: 'Do analysis.',
    tools: null,
    is_active: true,
    may_be_stale: false,
    user_managed_export: false,
    _system: false,
    last_exported_at: '2024-01-01T12:00:00Z',
    updated_at: '2024-01-01T12:00:00Z',
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Group 1 — Header chip and stale banner
// ---------------------------------------------------------------------------

describe('TemplateManager — header chip', () => {
  let wrapper

  beforeEach(async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.templates.activeCount.mockResolvedValue({
      data: { active_count: 3, limit: 15 },
    })
    wrapper = mountTemplateManager()
    await flushPromises()
  })

  it('renders the Agent Template Manager heading', () => {
    expect(wrapper.text()).toContain('Agent Template Manager')
  })

  it('renders a chip showing totalActiveAgents / totalCapacity when loaded', async () => {
    // After loadActiveCount: totalActive = 3+1=4, totalCapacity = 15+1=16
    const chip = wrapper.find('.v-chip')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('4')
    expect(chip.text()).toContain('16')
  })
})

describe('TemplateManager — stale templates banner', () => {
  it('shows stale banner when at least one template is stale and not user-managed', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.templates.list.mockResolvedValue({
      data: [makeTemplate({ may_be_stale: true, user_managed_export: false })],
    })
    const wrapper = mountTemplateManager()
    await flushPromises()
    // The v-alert renders its slot text
    const text = wrapper.text()
    expect(text).toContain('update the agent templates')
  })

  it('hides stale banner when all stale templates are user-managed', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.templates.list.mockResolvedValue({
      data: [makeTemplate({ may_be_stale: true, user_managed_export: true })],
    })
    const wrapper = mountTemplateManager()
    await flushPromises()
    expect(wrapper.text()).not.toContain('update the agent templates')
  })
})


// ---------------------------------------------------------------------------
// Group 3 — Data table row rendering
// ---------------------------------------------------------------------------

describe('TemplateManager — data table rows', () => {
  let wrapper

  beforeEach(async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.templates.list.mockResolvedValue({
      data: [
        makeTemplate({ id: 1, name: 'Analyzer', role: 'analyzer', is_active: true }),
        makeTemplate({ id: 2, name: 'Reviewer', role: 'reviewer', is_active: false }),
      ],
    })
    wrapper = mountTemplateManager()
    await flushPromises()
  })

  it('renders template-toggle for active user-managed template', () => {
    expect(
      wrapper.find('[data-testid="template-toggle-analyzer"]').exists()
    ).toBe(true)
  })

  it('renders template-toggle for inactive user-managed template', () => {
    expect(
      wrapper.find('[data-testid="template-toggle-reviewer"]').exists()
    ).toBe(true)
  })

  it('renders role badge text for each template', () => {
    const text = wrapper.text()
    expect(text).toContain('analyzer')
    expect(text).toContain('reviewer')
  })
})

// ---------------------------------------------------------------------------
// Group 4 — Active toggle fires api.templates.update
// ---------------------------------------------------------------------------

describe('TemplateManager — active toggle calls API', () => {
  it('calls api.templates.update when toggle changes', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.templates.list.mockResolvedValue({
      data: [makeTemplate({ id: 5, role: 'frontend', is_active: true })],
    })
    const wrapper = mountTemplateManager()
    await flushPromises()

    const toggle = wrapper.find('[data-testid="template-toggle-frontend"]')
    toggle.element.checked = false
    await toggle.trigger('change')
    await flushPromises()

    expect(api.templates.update).toHaveBeenCalledWith(5, { is_active: false })
  })
})

// ---------------------------------------------------------------------------
// Group 5 — Row action menu: edit opens dialog
// ---------------------------------------------------------------------------

describe('TemplateManager — row action: edit opens dialog', () => {
  it('sets editDialog=true when Edit is clicked', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.templates.list.mockResolvedValue({
      data: [makeTemplate({ id: 3, role: 'backend', name: 'My Backend' })],
    })
    const wrapper = mountTemplateManager()
    await flushPromises()

    // Find the Edit list item by title attribute
    const editItem = wrapper.find('[title="Edit"]')
    expect(editItem.exists()).toBe(true)
    await editItem.trigger('click')

    expect(wrapper.vm.editDialog).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Group 6 — Row action menu: duplicate opens dialog
// ---------------------------------------------------------------------------

describe('TemplateManager — row action: duplicate', () => {
  it('sets editDialog=true and id=null when Duplicate is clicked', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.templates.list.mockResolvedValue({
      data: [makeTemplate({ id: 4, role: 'tester', name: 'My Tester' })],
    })
    const wrapper = mountTemplateManager()
    await flushPromises()

    const dupItem = wrapper.find('[title="Duplicate"]')
    expect(dupItem.exists()).toBe(true)
    await dupItem.trigger('click')

    expect(wrapper.vm.editDialog).toBe(true)
    expect(wrapper.vm.editingTemplate.id).toBeNull()
  })

  // FE-9386: the duplicate action used to spread the source row wholesale, so a
  // seeded template's is_default=true rode along into the create payload. The
  // service clears sibling defaults on create (template_service.py:292-295),
  // which flipped the ORIGINAL's flag and — via onupdate=func.now() — stamped
  // its updated_at, moving it in the list and in the export-packaging order.
  it('sends is_default=false when saving a duplicate of a default template', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    const source = makeTemplate({
      id: 11,
      role: 'implementer',
      name: 'implementer-backend',
      is_default: true,
      updated_at: '2024-01-01T12:00:00Z',
    })
    api.templates.list.mockResolvedValue({ data: [source] })
    const wrapper = mountTemplateManager()
    await flushPromises()

    await wrapper.find('[title="Duplicate"]').trigger('click')
    expect(wrapper.vm.editingTemplate.is_default).toBe(false)

    await wrapper.vm.saveTemplate()
    await flushPromises()

    expect(api.templates.create).toHaveBeenCalledWith(
      expect.objectContaining({ is_default: false })
    )
    // The source row must also survive the duplicate untouched client-side.
    expect(source.is_default).toBe(true)
    expect(source.updated_at).toBe('2024-01-01T12:00:00Z')
  })
})

// ---------------------------------------------------------------------------
// Group 7 — Row action menu: reset opens confirm dialog
// ---------------------------------------------------------------------------

describe('TemplateManager — row action: reset to default', () => {
  it('sets resetDialog=true and resettingTemplate when Reset is clicked', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    const tpl = makeTemplate({ id: 6, role: 'documenter', name: 'My Docs', is_default: true })
    api.templates.list.mockResolvedValue({ data: [tpl] })
    const wrapper = mountTemplateManager()
    await flushPromises()

    const resetItem = wrapper.find('[title="Reset to Default"]')
    expect(resetItem.exists()).toBe(true)
    await resetItem.trigger('click')

    expect(wrapper.vm.resetDialog).toBe(true)
    expect(wrapper.vm.resettingTemplate?.id).toBe(6)
  })
})

// ---------------------------------------------------------------------------
// Group 8 — Row action menu: delete opens confirm dialog
// ---------------------------------------------------------------------------

describe('TemplateManager — row action: delete', () => {
  it('sets deleteDialog=true and deletingTemplate when Delete is clicked', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    const tpl = makeTemplate({ id: 9, role: 'reviewer', name: 'Reviewer' })
    api.templates.list.mockResolvedValue({ data: [tpl] })
    const wrapper = mountTemplateManager()
    await flushPromises()

    const deleteItem = wrapper.find('[title="Delete"]')
    expect(deleteItem.exists()).toBe(true)
    await deleteItem.trigger('click')

    expect(wrapper.vm.deleteDialog).toBe(true)
    expect(wrapper.vm.deletingTemplate?.id).toBe(9)
  })
})

// ---------------------------------------------------------------------------
// Group 9 — Row action menu: mark-user-managed calls API
// ---------------------------------------------------------------------------

describe('TemplateManager — row action: mark as user managed', () => {
  it('calls api.templates.update with user_managed_export=true', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    const tpl = makeTemplate({ id: 11, role: 'analyzer', may_be_stale: true, user_managed_export: false })
    api.templates.list.mockResolvedValue({ data: [tpl] })
    const wrapper = mountTemplateManager()
    await flushPromises()

    const markItem = wrapper.find('[title="Mark as User Managed"]')
    expect(markItem.exists()).toBe(true)
    await markItem.trigger('click')
    await flushPromises()

    expect(api.templates.update).toHaveBeenCalledWith(11, { user_managed_export: true })
  })
})

// ---------------------------------------------------------------------------
// Group 10 — Create / Edit / Save flow
// ---------------------------------------------------------------------------

describe('TemplateManager — create / save flow', () => {
  let wrapper
  let api

  beforeEach(async () => {
    mockShowToast = vi.fn()
    api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    wrapper = mountTemplateManager()
    await flushPromises()
  })

  it('calls api.templates.create with correct data when saving a new template', async () => {
    wrapper.vm.editingTemplate.id = null
    wrapper.vm.editingTemplate.role = 'analyzer'
    wrapper.vm.editingTemplate.custom_suffix = 'fast'
    wrapper.vm.editingTemplate.description = 'Fast analyzer'
    wrapper.vm.editingTemplate.user_instructions = 'Be fast'

    await wrapper.vm.saveTemplate()
    await flushPromises()

    expect(api.templates.create).toHaveBeenCalledWith(
      expect.objectContaining({
        role: 'analyzer',
        category: 'role',
      })
    )
  })

  it('calls api.templates.update when saving an existing template', async () => {
    wrapper.vm.editingTemplate.id = 42
    wrapper.vm.editingTemplate.role = 'backend'
    wrapper.vm.editingTemplate.user_instructions = 'Be good'

    await wrapper.vm.saveTemplate()
    await flushPromises()

    expect(api.templates.update).toHaveBeenCalledWith(42, expect.any(Object))
  })

  it('closes editDialog after successful save', async () => {
    wrapper.vm.editDialog = true
    wrapper.vm.editingTemplate.id = null
    wrapper.vm.editingTemplate.role = 'tester'

    await wrapper.vm.saveTemplate()
    await flushPromises()

    expect(wrapper.vm.editDialog).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Group 11 — Delete confirm flow
// ---------------------------------------------------------------------------

describe('TemplateManager — delete confirm flow', () => {
  it('calls api.templates.delete with correct id and closes dialog', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    const wrapper = mountTemplateManager()
    await flushPromises()

    wrapper.vm.deletingTemplate = makeTemplate({ id: 77 })
    wrapper.vm.deleteDialog = true

    await wrapper.vm.deleteTemplate()
    await flushPromises()

    expect(api.templates.delete).toHaveBeenCalledWith(77)
    expect(wrapper.vm.deleteDialog).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Group 12 — Reset confirm flow
// ---------------------------------------------------------------------------

describe('TemplateManager — reset confirm flow', () => {
  it('calls api.templates.reset with correct id and closes dialog', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    const wrapper = mountTemplateManager()
    await flushPromises()

    wrapper.vm.resettingTemplate = makeTemplate({ id: 88 })
    wrapper.vm.resetDialog = true

    await wrapper.vm.resetTemplate()
    await flushPromises()

    expect(api.templates.reset).toHaveBeenCalledWith(88)
    expect(wrapper.vm.resetDialog).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Group 13 — saveTemplate() error handling (consolidated from the former tests/components spec)
// ---------------------------------------------------------------------------

describe('TemplateManager — saveTemplate() error handling', () => {
  let wrapper
  let api

  beforeEach(async () => {
    mockShowToast = vi.fn()
    api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    wrapper = mountTemplateManager()
    wrapper.vm.editingTemplate.id = null
    wrapper.vm.editingTemplate.role = 'analyzer'
    wrapper.vm.editingTemplate.custom_suffix = 'mycopy'
  })

  it('shows warning toast titled "Name Already Exists" on 400 + "already exists"', async () => {
    api.templates.create.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'Template with this name already exists.' } },
    })
    await wrapper.vm.saveTemplate()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'warning', title: 'Name Already Exists' })
    )
  })

  it('shows warning toast titled "Name Already Exists" on 400 + "unique"', async () => {
    api.templates.create.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'unique constraint violation on name' } },
    })
    await wrapper.vm.saveTemplate()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'warning', title: 'Name Already Exists' })
    )
  })

  it('shows generic error toast on 400 with unrelated detail', async () => {
    api.templates.create.mockRejectedValueOnce({
      response: { status: 400, data: { detail: 'Invalid role value.' } },
    })
    await wrapper.vm.saveTemplate()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', title: 'Error' })
    )
  })

  it('shows generic error toast on 500', async () => {
    api.templates.create.mockRejectedValueOnce({
      response: { status: 500, data: { detail: 'Internal server error' } },
    })
    await wrapper.vm.saveTemplate()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', title: 'Error' })
    )
  })

  it('shows generic error toast on network failure (no response)', async () => {
    api.templates.create.mockRejectedValueOnce(new Error('Network Error'))
    await wrapper.vm.saveTemplate()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', title: 'Error' })
    )
  })
})

// ---------------------------------------------------------------------------
// Group 14 — duplicateTemplate() (consolidated from the former tests/components spec)
// ---------------------------------------------------------------------------

describe('TemplateManager — duplicateTemplate()', () => {
  let wrapper

  beforeEach(async () => {
    mockShowToast = vi.fn()
    wrapper = mountTemplateManager()
  })

  // BE-9394: these two assertions previously pinned `custom_suffix: ''` and a display
  // name of "<original name> (Copy)". Both described a name the server never used --
  // it regenerates from slugify_name(role, custom_suffix) and consults the supplied
  // name only when role is falsy -- so "(Copy)" was discarded and the copy landed as
  // "<role>-2". Updated to the ruled behaviour: the copy carries a real suffix so the
  // name shown, saved, exported and resolved by spawn are one string.
  it('sets custom_suffix to "copy" so the server derives the name', () => {
    const tpl = makeTemplate({ custom_suffix: 'old-suffix' })
    wrapper.vm.duplicateTemplate(tpl)
    expect(wrapper.vm.editingTemplate.custom_suffix).toBe('copy')
  })

  it('does not fabricate a "(Copy)" display name the server would discard', () => {
    const tpl = makeTemplate({ name: 'My Analyzer' })
    wrapper.vm.duplicateTemplate(tpl)
    expect(wrapper.vm.editingTemplate.name).not.toContain('(Copy)')
  })

  it('sets id to null', () => {
    const tpl = makeTemplate({ id: 99 })
    wrapper.vm.duplicateTemplate(tpl)
    expect(wrapper.vm.editingTemplate.id).toBeNull()
  })

  it('opens the edit dialog', () => {
    const tpl = makeTemplate()
    wrapper.vm.duplicateTemplate(tpl)
    expect(wrapper.vm.editDialog).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Group 15 — FE-9203: filter options locked to the model's real values
// ---------------------------------------------------------------------------
// The AgentTemplate model has exactly one lifecycle field: is_active (bool).
// There is no `status` column and no archived/draft state. This lock exists
// because the page once offered Active/Archived/Draft bound to a nonexistent
// `t.status` field — every option, including "Active", filtered to an empty
// table and no test caught it.

describe('TemplateManager — FE-9203 filter option lock', () => {
  let wrapper

  beforeEach(async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.templates.list.mockResolvedValue({
      data: [
        makeTemplate({ id: 1, name: 'analyzer', role: 'analyzer', is_active: true }),
        makeTemplate({ id: 2, name: 'reviewer', role: 'reviewer', is_active: false }),
      ],
    })
    wrapper = mountTemplateManager()
    await flushPromises()
  })

  it('status options are EXACTLY active/inactive — the only states the model has', () => {
    expect(wrapper.vm.statusOptions).toEqual([
      { title: 'Active', value: 'active' },
      { title: 'Inactive', value: 'inactive' },
    ])
  })

  it('phantom status values (archived/draft) must not return', () => {
    const values = wrapper.vm.statusOptions.map((o) => o.value)
    expect(values).not.toContain('archived')
    expect(values).not.toContain('draft')
  })

  it('role filter options come from the loaded data, not a hardcoded category list', () => {
    expect(wrapper.vm.availableRoles).toEqual(['analyzer', 'reviewer'])
    expect(wrapper.vm.availableRoles).not.toContain('project_type')
    expect(wrapper.vm.availableRoles).not.toContain('custom')
  })

  it('selecting "active" status actually returns the active templates (original bug: empty)', async () => {
    wrapper.vm.filterStatus = 'active'
    await flushPromises()
    const ids = wrapper.vm.filteredTemplates.map((t) => t.id)
    expect(ids).toEqual([1])
  })

  it('selecting "inactive" status returns the inactive templates', async () => {
    wrapper.vm.filterStatus = 'inactive'
    await flushPromises()
    const ids = wrapper.vm.filteredTemplates.map((t) => t.id)
    expect(ids).toEqual([2])
  })

  it('selecting a role filters by the real role field', async () => {
    wrapper.vm.filterRole = 'reviewer'
    await flushPromises()
    const ids = wrapper.vm.filteredTemplates.map((t) => t.id)
    expect(ids).toEqual([2])
  })

  it('Export Status column is sortable via the real export signals', () => {
    const header = wrapper.vm.headers.find((h) => h.key === 'export_status')
    expect(header.sortable).not.toBe(false)
    expect(typeof header.sortRaw).toBe('function')
    // needs-export (stale) sorts before exported; system row sorts last
    const stale = makeTemplate({ may_be_stale: true, last_exported_at: null })
    const exported = makeTemplate({ may_be_stale: false, last_exported_at: '2026-01-01T00:00:00Z' })
    const system = { _system: true }
    expect(header.sortRaw(stale, exported)).toBeLessThan(0)
    expect(header.sortRaw(system, exported)).toBeGreaterThan(0)
  })
})

// ---------------------------------------------------------------------------
// Group 16 — FE-9203 Part 2: "Add default agents" button
// ---------------------------------------------------------------------------
// Additive import of the seeded defaults. The server owns the semantics
// (skip-identical, never overwrite, -duplicate collision copies); the component
// contract is: button present, calls the endpoint, reports the summary, and
// disables while in flight.

describe('TemplateManager — FE-9203 Add default agents button', () => {
  let wrapper
  let api

  beforeEach(async () => {
    mockShowToast = vi.fn()
    api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    wrapper = mountTemplateManager()
    await flushPromises()
  })

  it('renders the Add Default Agents button in the toolbar', () => {
    const btn = wrapper.findAll('button').find((b) => b.text().includes('Add Default Agents'))
    expect(btn).toBeTruthy()
  })

  it('calls the import endpoint and refreshes templates + active count', async () => {
    api.templates.importDefaults.mockResolvedValueOnce({
      data: { added: ['implementer'], added_as_duplicate: [], skipped_identical: [] },
    })
    api.templates.list.mockClear()
    api.templates.activeCount.mockClear()
    await wrapper.vm.importDefaultAgents()
    expect(api.templates.importDefaults).toHaveBeenCalledTimes(1)
    expect(api.templates.list).toHaveBeenCalled()
    expect(api.templates.activeCount).toHaveBeenCalled()
  })

  it('shows a success summary when agents were added (incl. duplicates)', async () => {
    api.templates.importDefaults.mockResolvedValueOnce({
      data: {
        added: ['tester'],
        added_as_duplicate: ['implementer-duplicate'],
        skipped_identical: ['analyzer', 'reviewer', 'documenter'],
      },
    })
    await wrapper.vm.importDefaultAgents()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'success',
        message: expect.stringContaining('1 added, 1 added as duplicate, 3 already present'),
      })
    )
  })

  it('shows an info summary when everything is already present (repeat click)', async () => {
    api.templates.importDefaults.mockResolvedValueOnce({
      data: {
        added: [],
        added_as_duplicate: [],
        skipped_identical: ['implementer', 'tester', 'analyzer', 'reviewer', 'documenter'],
      },
    })
    await wrapper.vm.importDefaultAgents()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'info',
        message: expect.stringContaining('5 already present'),
      })
    )
  })

  it('shows an error toast on failure', async () => {
    api.templates.importDefaults.mockRejectedValueOnce({
      response: { status: 500, data: { detail: 'boom' } },
    })
    await wrapper.vm.importDefaultAgents()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: 'boom' })
    )
  })

  it('disables the trigger while the import is in flight', async () => {
    let resolveImport
    api.templates.importDefaults.mockImplementationOnce(
      () => new Promise((resolve) => (resolveImport = resolve))
    )
    const pending = wrapper.vm.importDefaultAgents()
    await flushPromises()
    expect(wrapper.vm.importingDefaults).toBe(true)
    resolveImport({ data: { added: [], added_as_duplicate: [], skipped_identical: [] } })
    await pending
    expect(wrapper.vm.importingDefaults).toBe(false)
  })
})
