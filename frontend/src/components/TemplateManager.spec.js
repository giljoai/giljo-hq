
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
      get: vi.fn(() => Promise.resolve({ data: {} })),
      create: vi.fn(() => Promise.resolve({ data: { id: 42 } })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
      preview: vi.fn(() => Promise.resolve({ data: { preview: 'Mock preview content' } })),
      profileDownloadUrl: (id) => `/api/v1/templates/${id}/profile.md`,
      activeCount: vi.fn(() =>
        Promise.resolve({ data: { active_count: 2, limit: 15, available: 13 } })
      ),
      history: vi.fn(() => Promise.resolve({ data: [] })),
      restore: vi.fn(() => Promise.resolve({ data: { success: true } })),
      reset: vi.fn(() => Promise.resolve({ data: { success: true } })),
      resetAll: vi.fn(() => Promise.resolve({ data: { reset: [], skipped: [], failed: [] } })),
      importDefaults: vi.fn(() =>
        Promise.resolve({ data: { added: [], added_as_duplicate: [], skipped_identical: [] } })
      ),
    },
    settings: {
      getGeneral: vi.fn(() =>
        Promise.resolve({ data: { settings: { closeout_mode: 'hitl' } } })
      ),
      updateCloseoutMode: vi.fn(() => Promise.resolve({ data: {} })),
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
    assignments: {
      list: vi.fn(() => Promise.resolve({ data: { assignments: [], count: 0 } })),
      toggle: vi.fn(() => Promise.resolve({ data: { is_active: true } })),
    },
  }
  return { api: apiObj, default: apiObj }
})

let mockShowToast

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({
    showToast: (...args) => mockShowToast(...args),
  }),
}))


const dataTableStub = {
  props: ['headers', 'items', 'loading', 'search', 'itemsPerPage'],
  template: `
    <div class="v-data-table">
      <div v-for="item in (items || [])" :key="item.id" class="v-data-table-row">
        <slot name="item.name" :item="item" />
        <slot name="item.role" :item="item" />
        <slot name="item.is_active" :item="item" />
        <slot name="item.updated_at" :item="item" />
        <slot name="item.actions" :item="item" />
      </div>
    </div>
  `,
}

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


function mountTemplateManager(options = {}) {
  return mount(TemplateManager, {
    global: {
      plugins: [
        router,
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
            products: {
              currentProductId: 'prod-test',
              activeProduct: null,
              products: [{ id: 'prod-test', name: 'Test Product', is_active: true }],
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
        'v-dialog': { template: '<div class="v-dialog"><slot /></div>' },
        Teleport: true,
        ...options.stubs,
      },
    },
    ...options.mountOptions,
  })
}


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
    _system: false,
    updated_at: '2024-01-01T12:00:00Z',
    ...overrides,
  }
}


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
    const chip = wrapper.find('.v-chip')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('4')
    expect(chip.text()).toContain('16')
  })
})



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


describe('TemplateManager — active toggle calls API', () => {
  it('writes the per-product junction, not the account-wide flag', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.templates.list.mockResolvedValue({
      data: [makeTemplate({ id: 5, role: 'frontend' })],
    })
    api.assignments.list.mockResolvedValue({
      data: { assignments: [{ template_id: 5, is_active: true }], count: 1 },
    })
    const wrapper = mountTemplateManager()
    await flushPromises()

    const toggle = wrapper.find('[data-testid="template-toggle-frontend"]')
    toggle.element.checked = false
    await toggle.trigger('change')
    await flushPromises()

    expect(api.assignments.toggle).toHaveBeenCalledWith('prod-test', 5, false)
    expect(api.templates.update).not.toHaveBeenCalled()
  })
})


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

    const editItem = wrapper.find('[title="Edit"]')
    expect(editItem.exists()).toBe(true)
    await editItem.trigger('click')

    expect(wrapper.vm.editDialog).toBe(true)
  })
})


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
    expect(source.is_default).toBe(true)
    expect(source.updated_at).toBe('2024-01-01T12:00:00Z')
  })
})


describe('TemplateManager — row action: reset to default', () => {
  it('sets resetDialog=true and resettingTemplate when Reset is clicked', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    const tpl = makeTemplate({ id: 6, role: 'documenter', name: 'My Docs', can_reset: true })
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

  it('a failed delete shows the server reason and keeps the dialog open', async () => {
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    api.templates.delete.mockRejectedValueOnce(
      Object.assign(new Error('x'), { response: { status: 409, data: { message: 'agent is in use' } } }),
    )
    const wrapper = mountTemplateManager()
    await flushPromises()

    wrapper.vm.deletingTemplate = makeTemplate({ id: 77 })
    wrapper.vm.deleteDialog = true
    await wrapper.vm.deleteTemplate()
    await flushPromises()

    expect(wrapper.vm.deleteDialog).toBe(true)
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('agent is in use') }),
    )
  })
})


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

  it('a failed reset shows the server reason and keeps the dialog open', async () => {
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    api.templates.reset.mockRejectedValueOnce(
      Object.assign(new Error('x'), { response: { status: 500, data: { message: 'reset failed upstream' } } }),
    )
    const wrapper = mountTemplateManager()
    await flushPromises()

    wrapper.vm.resettingTemplate = makeTemplate({ id: 88 })
    wrapper.vm.resetDialog = true
    await wrapper.vm.resetTemplate()
    await flushPromises()

    expect(wrapper.vm.resetDialog).toBe(true)
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('reset failed upstream') }),
    )
  })
})


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
      response: {
        status: 400,
        data: { error_code: 'VALIDATIONERROR', message: 'Template with this name already exists.' },
      },
    })
    await wrapper.vm.saveTemplate()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'warning', title: 'Name Already Exists' })
    )
  })

  it('shows warning toast titled "Name Already Exists" on 400 + "unique"', async () => {
    api.templates.create.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { error_code: 'VALIDATIONERROR', message: 'unique constraint violation on name' },
      },
    })
    await wrapper.vm.saveTemplate()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'warning', title: 'Name Already Exists' })
    )
  })

  it('shows generic error toast on 400 with unrelated detail', async () => {
    api.templates.create.mockRejectedValueOnce({
      response: {
        status: 400,
        data: { error_code: 'VALIDATIONERROR', message: 'Invalid role value.' },
      },
    })
    await wrapper.vm.saveTemplate()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', title: 'Error' })
    )
  })

  it('shows generic error toast on 500', async () => {
    api.templates.create.mockRejectedValueOnce({
      response: {
        status: 500,
        data: {
          error_code: 'INTERNAL_SERVER_ERROR',
          message: 'The server hit an unexpected internal error handling this request. Full details were logged server-side.',
        },
      },
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


describe('TemplateManager — duplicateTemplate()', () => {
  let wrapper

  beforeEach(async () => {
    mockShowToast = vi.fn()
    wrapper = mountTemplateManager()
  })

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
    api.assignments.list.mockResolvedValue({
      data: {
        assignments: [
          { template_id: 1, is_active: true },
          { template_id: 2, is_active: false },
        ],
        count: 2,
      },
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

})


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

  it('offers Add default agents from the bulk-actions menu', () => {
    const item = wrapper.find('[data-testid="add-default-agents"]')
    expect(item.exists()).toBe(true)
    expect(item.attributes('title')).toBe('Add default agents')
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
      response: { status: 500, data: { error_code: 'INTERNAL_SERVER_ERROR', message: 'boom' } },
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


describe('TemplateManager — BE-9646: reset all agents to default', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockShowToast = vi.fn()
  })

  async function mountWithRoster(templates) {
    const api = (await import('@/services/api')).default
    api.templates.list.mockResolvedValue({ data: templates })
    const wrapper = mountTemplateManager()
    await flushPromises()
    return wrapper
  }

  it('warns exactly what a per-agent reset replaces and what survives it', async () => {
    const wrapper = await mountWithRoster([makeTemplate({ id: 1, name: 'tester-2', can_reset: true })])

    await wrapper.find('[title="Reset to Default"]').trigger('click')
    await flushPromises()

    const warning = wrapper.find('[data-testid="reset-warning"]').text().replace(/\s+/g, ' ').trim()
    expect(warning).toBe(
      "This replaces this agent's instructions, rules and success criteria with the current " +
        'default. Your customizations will be lost. A copy is kept in version history.'
    )
  })

  it('names the number of agents the reset would affect, counting only resettable ones', async () => {
    const wrapper = await mountWithRoster([
      makeTemplate({ id: 1, name: 'tester-2', can_reset: true }),
      makeTemplate({ id: 2, name: 'implementer-2', can_reset: true }),
      makeTemplate({ id: 3, name: 'my-own-agent', can_reset: false }),
    ])

    await wrapper.find('[data-testid="reset-all-agents"]').trigger('click')
    await flushPromises()

    expect(wrapper.vm.resetAllDialog).toBe(true)
    expect(wrapper.find('[data-testid="reset-all-count"]').text()).toContain('2 agents')
  })

  it('resets the VIEWED product only, through the bulk endpoint', async () => {
    const api = (await import('@/services/api')).default
    const wrapper = await mountWithRoster([makeTemplate({ id: 1, name: 'tester-2', can_reset: true })])

    await wrapper.find('[data-testid="reset-all-agents"]').trigger('click')
    await wrapper.find('[data-testid="reset-all-confirm"]').trigger('click')
    await flushPromises()

    expect(api.templates.resetAll).toHaveBeenCalledTimes(1)
    expect(api.templates.resetAll).toHaveBeenCalledWith(wrapper.vm.viewedProductId)
    expect(wrapper.vm.resetAllDialog).toBe(false)
  })

  it('names the agents that failed instead of collapsing a partial run', async () => {
    const api = (await import('@/services/api')).default
    api.templates.resetAll.mockResolvedValue({
      data: { reset: ['tester-2'], skipped: [], failed: [{ name: 'reviewer-2', error: 'nope' }] },
    })
    const wrapper = await mountWithRoster([
      makeTemplate({ id: 1, name: 'tester-2', can_reset: true }),
      makeTemplate({ id: 2, name: 'reviewer-2', can_reset: true }),
    ])

    await wrapper.find('[data-testid="reset-all-agents"]').trigger('click')
    await wrapper.find('[data-testid="reset-all-confirm"]').trigger('click')
    await flushPromises()

    const messages = mockShowToast.mock.calls.map((c) => c[0].message).join(' | ')
    expect(messages).toContain('reviewer-2')
    expect(messages).toContain('Reset 1 agent to default')
  })
})
