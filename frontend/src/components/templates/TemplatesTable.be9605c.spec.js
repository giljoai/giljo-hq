
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import TemplatesTable from './TemplatesTable.vue'
import { TEMPLATE_TABLE_HEADERS } from './templateTableConfig.js'

const dataTableStub = {
  props: ['headers', 'items', 'loading', 'search', 'itemsPerPage'],
  template: `
    <div class="v-data-table">
      <div v-for="item in (items || [])" :key="item.id" class="v-data-table-row">
        <slot name="item.name" :item="item" />
        <slot name="item.is_active" :item="item" />
        <slot name="item.export_status" :item="item" />
        <slot name="item.actions" :item="item" />
      </div>
    </div>
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

function makeTemplate(overrides = {}) {
  return {
    id: 1,
    name: 'My Analyzer',
    role: 'analyzer',
    category: 'role',
    cli_tool: 'claude',
    is_active: true,
    is_default: false,
    _system: false,
    updated_at: '2024-01-01T12:00:00Z',
    ...overrides,
  }
}

function mountTable(props = {}) {
  return mount(TemplatesTable, {
    props: { templates: [], loading: false, search: '', headers: TEMPLATE_TABLE_HEADERS, ...props },
    global: {
      stubs: {
        'v-data-table': dataTableStub,
        'v-menu': menuStub,
        'v-list-item': listItemStub,
        'v-tooltip': tooltipStub,
      },
    },
  })
}

describe('TemplatesTable — BE-9605c export status retired', () => {
  it('has no Export Status header', () => {
    const titles = TEMPLATE_TABLE_HEADERS.map((h) => h.title)
    expect(titles).not.toContain('Export Status')
    expect(TEMPLATE_TABLE_HEADERS.map((h) => h.key)).not.toContain('export_status')
  })

  it('renders no staleness chip even for a legacy payload carrying may_be_stale', () => {
    const wrapper = mountTable({ templates: [makeTemplate({ may_be_stale: true, last_exported_at: null })] })
    expect(wrapper.text()).not.toContain('May be outdated')
    expect(wrapper.text()).not.toContain('Never exported')
    expect(wrapper.text()).not.toContain('Agents only')
  })

  it('has no Mark as User Managed action', () => {
    const wrapper = mountTable({ templates: [makeTemplate({ may_be_stale: true, user_managed_export: false })] })
    expect(wrapper.find('[data-testid="action-mark-user-managed"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Mark as User Managed')
  })
})

describe('TemplatesTable — BE-9605c download profile', () => {
  it('offers Download profile (.md) in every row menu and emits download-profile with the row', async () => {
    const tpl = makeTemplate({ id: 42 })
    const wrapper = mountTable({ templates: [tpl] })
    const item = wrapper.find('[data-testid="action-download-profile"]')
    expect(item.exists()).toBe(true)
    expect(item.attributes('title')).toBe('Download profile (.md)')
    await item.trigger('click')
    expect(wrapper.emitted('download-profile')).toHaveLength(1)
    expect(wrapper.emitted('download-profile')[0]).toEqual([tpl])
  })
})
