
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import TemplatesTable from './TemplatesTable.vue'
import { getAgentColor } from '@/config/agentColors'


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


function makeTemplate(overrides = {}) {
  return {
    id: 1,
    name: 'My Analyzer',
    role: 'analyzer',
    category: 'role',
    is_active: true,
    _system: false,
    updated_at: '2024-01-01T12:00:00Z',
    ...overrides,
  }
}

const defaultHeaders = [
  { title: 'Agent Name', key: 'name', align: 'start' },
  { title: 'Role', key: 'role', align: 'start' },
  { title: 'Active', key: 'is_active', align: 'center' },
]

function mountTable(propsData = {}) {
  return mount(TemplatesTable, {
    props: {
      templates: [makeTemplate()],
      loading: false,
      headers: defaultHeaders,
      search: '',
      remainingUserSlots: 5,
      userAgentLimit: 7,
      ...propsData,
    },
    global: {
      stubs: {
        'v-data-table': dataTableStub,
        'v-switch': switchStub,
        'v-menu': menuStub,
        'v-list-item': listItemStub,
        'v-tooltip': tooltipStub,
      },
    },
  })
}


describe('TemplatesTable — render', () => {
  it('renders without errors for an empty template list', () => {
    const wrapper = mountTable({ templates: [] })
    expect(wrapper.find('.v-data-table').exists()).toBe(true)
  })

  it('renders a row per template', () => {
    const wrapper = mountTable({
      templates: [
        makeTemplate({ id: 1, role: 'analyzer' }),
        makeTemplate({ id: 2, role: 'reviewer' }),
      ],
    })
    const rows = wrapper.findAll('.v-data-table-row')
    expect(rows).toHaveLength(2)
  })

  it('renders role badge text for each template', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ role: 'backend' })],
    })
    expect(wrapper.text()).toContain('backend')
  })

  it('renders a toggle (v-switch) for user-managed templates', () => {
    const wrapper = mountTable()
    expect(wrapper.find('.v-switch').exists()).toBe(true)
  })

  it('does not render a toggle for system-managed (_system=true) templates', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ _system: true })],
    })
    expect(wrapper.find('.v-switch').exists()).toBe(false)
  })

  it('renders testid template-toggle-{role} for user-managed template', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ id: 5, role: 'frontend' })],
    })
    expect(wrapper.find('[data-testid="template-toggle-frontend"]').exists()).toBe(true)
  })

  it('does not render action menu for _system templates', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ _system: true })],
    })
    expect(wrapper.find('[aria-label="Template actions"]').exists()).toBe(false)
  })

  it('offers "Edit orchestrator prompt" on the _system row when the prompt is reachable', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ _system: true })],
      canEditPrompt: true,
    })
    expect(wrapper.find('[data-testid="edit-orchestrator-prompt"]').exists()).toBe(true)
  })

  it('hides "Edit orchestrator prompt" on the _system row when the prompt is not reachable', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ _system: true })],
      canEditPrompt: false,
    })
    expect(wrapper.find('[data-testid="edit-orchestrator-prompt"]').exists()).toBe(false)
  })

  it('emits edit-orchestrator-prompt when the link is clicked', async () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ _system: true })],
      canEditPrompt: true,
    })
    await wrapper.find('[data-testid="edit-orchestrator-prompt"]').trigger('click')
    expect(wrapper.emitted('edit-orchestrator-prompt')).toHaveLength(1)
  })
})


describe('TemplatesTable — emit: toggle-active', () => {
  it('emits toggle-active with (item, newValue) when switch changes', async () => {
    const tpl = makeTemplate({ id: 10, role: 'tester', is_active: true })
    const wrapper = mountTable({ templates: [tpl] })

    const toggle = wrapper.find('[data-testid="template-toggle-tester"]')
    toggle.element.checked = false
    await toggle.trigger('change')

    expect(wrapper.emitted('toggle-active')).toHaveLength(1)
    expect(wrapper.emitted('toggle-active')[0]).toEqual([tpl, false])
  })
})

describe('TemplatesTable — emit: edit', () => {
  it('emits edit with the item when Edit is clicked', async () => {
    const tpl = makeTemplate({ id: 3, role: 'backend' })
    const wrapper = mountTable({ templates: [tpl] })

    await wrapper.find('[title="Edit"]').trigger('click')

    expect(wrapper.emitted('edit')).toHaveLength(1)
    expect(wrapper.emitted('edit')[0]).toEqual([tpl])
  })
})

describe('TemplatesTable — emit: duplicate', () => {
  it('emits duplicate with the item when Duplicate is clicked', async () => {
    const tpl = makeTemplate({ id: 4, role: 'documenter' })
    const wrapper = mountTable({ templates: [tpl] })

    await wrapper.find('[title="Duplicate"]').trigger('click')

    expect(wrapper.emitted('duplicate')).toHaveLength(1)
    expect(wrapper.emitted('duplicate')[0]).toEqual([tpl])
  })
})

describe('TemplatesTable — emit: reset', () => {
  it('emits reset with the item when Reset to Default is clicked', async () => {
    const tpl = makeTemplate({ id: 6, role: 'reviewer', can_reset: true })
    const wrapper = mountTable({ templates: [tpl] })

    await wrapper.find('[title="Reset to Default"]').trigger('click')

    expect(wrapper.emitted('reset')).toHaveLength(1)
    expect(wrapper.emitted('reset')[0]).toEqual([tpl])
  })

  it('hides Reset to Default for a custom template', () => {
    const tpl = makeTemplate({ id: 7, role: 'reviewer', can_reset: false })
    const wrapper = mountTable({ templates: [tpl] })

    expect(wrapper.find('[title="Reset to Default"]').exists()).toBe(false)
  })
})

describe('TemplatesTable — emit: delete', () => {
  it('emits delete with the item when Delete is clicked', async () => {
    const tpl = makeTemplate({ id: 9, role: 'implementer' })
    const wrapper = mountTable({ templates: [tpl] })

    await wrapper.find('[title="Delete"]').trigger('click')

    expect(wrapper.emitted('delete')).toHaveLength(1)
    expect(wrapper.emitted('delete')[0]).toEqual([tpl])
  })
})


describe('TemplatesTable — search prop', () => {
  it('passes search to the v-data-table stub', () => {
    const wrapper = mountTable({ search: 'hello' })
    const table = wrapper.findComponent(dataTableStub)
    expect(table.props('search')).toBe('hello')
  })
})


describe('TemplatesTable — FE-9385c Updated state column', () => {
  const cell = (wrapper, id) => wrapper.find(`[data-testid="updated-state-${id}"]`)

  it('shows "Never edited" for a stock agent whose updated_at is NULL', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ id: 11, updated_at: null, created_at: '2026-07-01T10:00:00Z' })],
    })

    expect(cell(wrapper, 11).text()).toBe('Never edited')
    expect(cell(wrapper, 11).classes()).toContain('text-muted-a11y')
    expect(cell(wrapper, 11).classes()).not.toContain('updated-new')
  })

  it('shows a formatted date once the agent has been edited', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ id: 12, updated_at: '2026-08-05T10:00:00Z' })],
    })

    const text = cell(wrapper, 12).text()
    expect(text).not.toBe('Never edited')
    expect(text).not.toBe('Added today')
    expect(text).toMatch(/Aug 05, 2026/)
  })

  it('shows "Added today" with the accent for an agent added today', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ id: 13, updated_at: null, created_at: new Date().toISOString() })],
    })

    expect(cell(wrapper, 13).text()).toBe('Added today')
    expect(cell(wrapper, 13).classes()).toContain('updated-new')
  })


  it('renders a system-managed row as a dash', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ id: 15, _system: true, updated_at: null })],
    })

    expect(cell(wrapper, 15).text()).toBe('—')
  })
})


describe('TemplatesTable — FE-9385c vocabulary', () => {
  it('FE-9604: does not send the user to a dialog control that no longer exists', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ id: 21, is_active: false })],
      remainingUserSlots: 5,
    })

    const html = wrapper.html()
    expect(html).not.toContain('Available in all products')
    expect(html).not.toMatch(/Edit\s*(&rarr;|→)\s*Availability/)
    expect(wrapper.find('[data-testid="template-toggle-analyzer"]').element.disabled).toBe(false)
  })

  it('FE-9604: the row shows the per-product state when an assignment exists', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ id: 23, is_active: true, product_active: false })],
    })
    expect(wrapper.find('[data-testid="template-toggle-analyzer"]').element.checked).toBe(false)
  })

  it('FE-9610c: an agent with an active assignment shows as on', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ id: 23, is_active: false, product_active: true })],
    })
    expect(wrapper.find('[data-testid="template-toggle-analyzer"]').element.checked).toBe(true)
  })

  it('FE-9604: holds the switch while assignments load', () => {
    const wrapper = mountTable({ templates: [makeTemplate({ id: 24 })], assignmentsLoading: true })
    expect(wrapper.find('[data-testid="template-toggle-analyzer"]').element.disabled).toBe(true)
  })

  it('never shows the internal name for the account-wide switch', () => {
    const wrapper = mountTable({
      templates: [makeTemplate({ id: 22, is_active: false })],
      remainingUserSlots: 5,
    })

    expect(wrapper.text()).not.toMatch(/retire/i)
  })
})

describe('TemplatesTable — BE-9646: reset visibility follows factory origin', () => {
  it('offers Reset to Default on a factory-born agent whose is_default is false', () => {
    const tpl = makeTemplate({ id: 61, name: 'tester-2', role: 'tester', is_default: false, can_reset: true })
    const wrapper = mountTable({ templates: [tpl] })

    expect(wrapper.find('[title="Reset to Default"]').exists()).toBe(true)
  })

  it('hides Reset to Default on a user-created agent, even one flagged as default', () => {
    const tpl = makeTemplate({ id: 62, name: 'tester-specialist', role: 'tester', is_default: true, can_reset: false })
    const wrapper = mountTable({ templates: [tpl] })

    expect(wrapper.find('[title="Reset to Default"]').exists()).toBe(false)
  })
})


describe('TemplatesTable — role badge tint', () => {
  it('tints the badge with the role colour at 15% and fades an inactive row', () => {
    const wrapper = mountTable({
      templates: [
        makeTemplate({ id: 1, role: 'analyzer', product_active: true }),
        makeTemplate({ id: 2, role: 'analyzer', product_active: false }),
      ],
    })
    const styles = wrapper.findAll('.template-role-badge').map((b) => b.attributes('style'))
    const { hex } = getAgentColor('analyzer')
    const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(', ')
    expect(styles).toEqual([
      `background-color: rgba(${rgb}, 0.15); color: rgb(${rgb}); opacity: 1;`,
      `background-color: rgba(${rgb}, 0.15); color: rgb(${rgb}); opacity: 0.4;`,
    ])
  })
})
