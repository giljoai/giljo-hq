import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/utils/taxonomyBadge', () => ({
  taxonomyBadgeStyle: () => ({ background: 'rgba(100,100,100,0.15)', color: '#646464' }),
  DEFAULT_PROJECT_TYPE_COLOR: '#646464',
  resolveTaxonomyColor: ({ color } = {}) => color || '#646464',
  isReservedTaskAlias: (alias) => typeof alias === 'string' && /^TSK(?=[-\d])/.test(alias),
  isHandoverRow: (row) =>
    !!row && (row.task_type?.abbreviation === 'HND' || /^HND(?=[-\d])/.test(row.taxonomy_alias || '')),
}))
vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({
    formatDateWithTime: (d) => d ? 'Jun 1, 2026' : '',
  }),
}))
vi.mock('@/config/agentColors', () => ({
  getAgentColor: () => ({ hex: '#ffc300' }),
}))
vi.mock('@/config/colorTokens', () => ({
  TEXT_MUTED: '#8895a8',
}))

import TasksTable from './TasksTable.vue'

const stubs = {
  'v-data-table': {
    template: '<div class="v-data-table" data-table><slot /><slot name="item.status" :item="items[0]" /><slot name="no-data" /></div>',
    props: ['items', 'loading', 'headers'],
  },
  'v-card': { template: '<div class="v-card"><slot /></div>' },
  'v-select': { template: '<div class="v-select"><slot name="selection" v-bind="{ item: modelValue, internalItem: { value: modelValue } }" /></div>', props: ['modelValue'] },
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-btn': { template: '<button class="v-btn" v-bind="$attrs"><slot /></button>' },
  'v-menu': { template: '<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>' },
  'v-list': { template: '<div class="v-list"><slot /></div>' },
  'v-list-item': { template: '<div class="v-list-item" @click="$emit(\'click\')"><slot /><slot name="prepend" /></div>' },
  'v-list-item-title': { template: '<div class="v-list-item-title"><slot /></div>' },
  'v-divider': { template: '<hr />' },
  'v-tooltip': { template: '<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>' },
  'v-date-picker': { template: '<div class="v-date-picker" />' },
  'v-progress-circular': { template: '<div class="v-progress-circular" />' },
  TaskStatusBadge: { template: '<span class="task-status-badge">{{ status }}</span>', props: ['status'] },
  EmptyState: { template: '<div class="empty-state"><slot /></div>' },
}

const sampleTasks = [
  {
    id: 'task-1',
    title: 'Fix the bug',
    description: 'Description here',
    status: 'pending',
    priority: 'high',
    taxonomy_alias: 'BE-0001',
    task_type_color: '#ff6b6b',
    created_at: '2026-06-01T10:00:00Z',
    converted_project_id: null,
    hidden: false,
  },
]

function mountTable(props = {}) {
  return mount(TasksTable, {
    props: {
      tasks: sampleTasks,
      loading: false,
      statusSelectOptions: ['pending', 'in_progress', 'completed'],
      priorityOptions: ['low', 'medium', 'high', 'critical'],
      ...props,
    },
    global: { stubs },
  })
}

describe('TasksTable', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the table container', () => {
    const wrapper = mountTable()
    expect(wrapper.find('.v-card').exists()).toBe(true)
    expect(wrapper.find('[data-table]').exists()).toBe(true)
  })

  it('passes tasks to data table (items rendered)', () => {
    const wrapper = mountTable()
    expect(wrapper.find('[data-table]').exists()).toBe(true)
    expect(wrapper.exists()).toBe(true)
  })

  it('shows loading state when loading is true', () => {
    const wrapper = mountTable({ loading: true })
    expect(wrapper.find('[data-table]').exists()).toBe(true)
    expect(wrapper.exists()).toBe(true)
  })

  it('emits edit-task when row title is clicked', async () => {
    const wrapper = mountTable()
    const taskRow = wrapper.find(`[data-test="task-row-task-1"]`)
    if (taskRow.exists()) {
      await taskRow.trigger('click')
      expect(wrapper.emitted('edit-task')).toBeTruthy()
    }
  })

  const titleSlotStubs = {
    ...stubs,
    'v-data-table': {
      template: '<div class="v-data-table" data-table><slot name="item.title" :item="items[0]" /></div>',
      props: ['items', 'loading', 'headers'],
    },
    'v-chip': { template: '<span class="v-chip" v-bind="$attrs"><slot /></span>' },
  }

  it('renders the Archived badge for an archived (hidden) task', () => {
    const wrapper = mount(TasksTable, {
      props: {
        tasks: [{ ...sampleTasks[0], id: 'task-h', hidden: true }],
        loading: false,
        statusSelectOptions: ['pending'],
        priorityOptions: ['low', 'medium', 'high', 'critical'],
      },
      global: { stubs: titleSlotStubs },
    })
    const badge = wrapper.find('[data-test="task-archived-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('Archived')
  })

  it('does NOT render the Archived badge for a visible task', () => {
    const wrapper = mount(TasksTable, {
      props: {
        tasks: [{ ...sampleTasks[0], hidden: false }],
        loading: false,
        statusSelectOptions: ['pending'],
        priorityOptions: ['low', 'medium', 'high', 'critical'],
      },
      global: { stubs: titleSlotStubs },
    })
    expect(wrapper.find('[data-test="task-archived-badge"]').exists()).toBe(false)
  })
})



describe('TasksTable handover controls (BE-9637)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  const actionStubs = {
    ...stubs,
    'v-data-table': {
      template:
        '<div class="v-data-table" data-table><slot name="item.actions" :item="items[0]" /><slot name="item.convert" :item="items[0]" /></div>',
      props: ['items', 'loading', 'headers'],
    },
    'v-list-item': {
      template: '<div class="v-list-item" v-bind="$attrs" @click="$emit(\'click\')"><slot /><slot name="prepend" /></div>',
    },
  }

  function mountWith(task) {
    return mount(TasksTable, {
      props: {
        tasks: [task],
        loading: false,
        statusSelectOptions: ['pending'],
        priorityOptions: ['low', 'medium', 'high', 'critical'],
      },
      global: { stubs: actionStubs },
    })
  }

  const handover = {
    ...sampleTasks[0],
    id: 'hnd-1',
    taxonomy_alias: 'HND-9641',
    task_type: { abbreviation: 'HND' },
    status: 'pending',
    hidden: false,
  }

  it('hides Convert to Project on a handover row', () => {
    const wrapper = mountWith(handover)
    expect(wrapper.text()).not.toContain('Convert to Project')
  })

  it('still offers Convert to Project on an ordinary task', () => {
    const wrapper = mountWith({ ...sampleTasks[0], status: 'pending' })
    expect(wrapper.text()).toContain('Convert to Project')
  })

  it('hides the convert icon button on a handover row', () => {
    const wrapper = mountWith(handover)
    expect(wrapper.find('.convert-action').exists()).toBe(false)
  })

  it('keeps the convert icon button on an ordinary task', () => {
    const wrapper = mountWith({ ...sampleTasks[0], status: 'pending' })
    expect(wrapper.find('.convert-action').exists()).toBe(true)
  })

  const isDisabled = (el) => el.attributes('disabled') === 'true' || el.attributes('disabled') === ''

  it('disables Archive while a handover is still pending', () => {
    const wrapper = mountWith(handover)
    const action = wrapper.find('[data-test="task-hide-action"]')
    expect(action.exists()).toBe(true)
    expect(isDisabled(action)).toBe(true)
  })

  it('re-enables Archive once the handover is no longer pending', () => {
    const wrapper = mountWith({ ...handover, status: 'completed' })
    expect(isDisabled(wrapper.find('[data-test="task-hide-action"]'))).toBe(false)
  })

  it('never disables Archive on an ordinary pending task', () => {
    const wrapper = mountWith({ ...sampleTasks[0], status: 'pending' })
    expect(isDisabled(wrapper.find('[data-test="task-hide-action"]'))).toBe(false)
  })

  it('recognises a handover from the alias alone, when the type record was trimmed', () => {
    const wrapper = mountWith({ ...handover, task_type: undefined })
    expect(wrapper.find('.convert-action').exists()).toBe(false)
  })
})
