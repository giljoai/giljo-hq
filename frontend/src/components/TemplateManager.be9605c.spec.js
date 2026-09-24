
import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { createRouter, createMemoryHistory } from 'vue-router'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/', name: 'Root', component: { template: '<div />' } }],
})

import TemplateManager from './TemplateManager.vue'

vi.mock('@/services/api', () => {
  const apiObj = {
    templates: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
      get: vi.fn(() => Promise.resolve({ data: {} })),
      create: vi.fn(() => Promise.resolve({ data: { id: 42 } })),
      update: vi.fn(() => Promise.resolve({ data: {} })),
      delete: vi.fn(() => Promise.resolve({ data: { success: true } })),
      preview: vi.fn(() => Promise.resolve({ data: { preview: '' } })),
      activeCount: vi.fn(() => Promise.resolve({ data: { active_count: 2, limit: 15 } })),
      history: vi.fn(() => Promise.resolve({ data: [] })),
      reset: vi.fn(() => Promise.resolve({ data: {} })),
      importDefaults: vi.fn(() => Promise.resolve({ data: {} })),
      profileDownloadUrl: vi.fn((id) => `/api/v1/templates/${id}/profile.md`),
    },
  }
  return { default: apiObj, api: apiObj }
})

vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

const dataTableStub = {
  props: ['headers', 'items', 'loading', 'search', 'itemsPerPage'],
  template: `
    <div class="v-data-table">
      <div v-for="item in (items || [])" :key="item.id" class="v-data-table-row">
        <slot name="item.name" :item="item" />
        <slot name="item.actions" :item="item" />
      </div>
    </div>
  `,
}
const menuStub = { template: `<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>` }
const listItemStub = {
  props: ['title', 'prependIcon'],
  template: `<div class="v-list-item" v-bind="$attrs" :title="title"><slot /></div>`,
}
const tooltipStub = {
  props: ['text', 'location'],
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

function mountManager() {
  return mount(TemplateManager, {
    global: {
      plugins: [
        router,
        createTestingPinia({
          initialState: {
            user: { currentUser: { id: 1, username: 'u', role: 'admin', tenant_key: 'tk' } },
            products: {
              currentProductId: 'prod-9605c',
              products: [{ id: 'prod-9605c', name: 'Product', is_active: true }],
            },
          },
          stubActions: false,
        }),
      ],
      stubs: {
        'v-data-table': dataTableStub,
        'v-menu': menuStub,
        'v-list-item': listItemStub,
        'v-tooltip': tooltipStub,
        'v-dialog': { template: '<div class="v-dialog"><slot /></div>' },
        Teleport: true,
      },
    },
  })
}

const legacyStaleTemplate = {
  id: 7,
  name: 'My Analyzer',
  role: 'analyzer',
  category: 'role',
  cli_tool: 'claude',
  is_active: true,
  may_be_stale: true,
  user_managed_export: false,
  last_exported_at: null,
  updated_at: '2024-01-01T12:00:00Z',
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('TemplateManager — BE-9605c', () => {
  it('never shows the outdated-templates banner, even for a legacy stale payload', async () => {
    const api = (await import('@/services/api')).default
    api.templates.list.mockResolvedValue({ data: [legacyStaleTemplate] })
    const wrapper = mountManager()
    await flushPromises()
    const text = wrapper.text()
    expect(text).not.toContain('update the agent templates')
    expect(text).not.toContain('Agents only')
  })

  it('download-profile opens the profile.md download for that template', async () => {
    const api = (await import('@/services/api')).default
    api.templates.list.mockResolvedValue({ data: [legacyStaleTemplate] })
    const opened = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = mountManager()
    await flushPromises()
    await wrapper.find('[data-testid="action-download-profile"]').trigger('click')
    expect(opened).toHaveBeenCalledTimes(1)
    expect(opened.mock.calls[0][0]).toBe('/api/v1/templates/7/profile.md')
  })
})
