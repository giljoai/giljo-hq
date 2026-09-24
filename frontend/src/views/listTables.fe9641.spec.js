import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('vuetify', () => ({ useDisplay: () => ({ smAndDown: { value: false } }) }))
vi.mock('@/utils/taxonomyBadge', () => ({
  taxonomyBadgeStyle: () => ({}),
  resolveTaxonomyColor: () => '#646464',
  isReservedTaskAlias: () => false,
  isHandoverRow: () => false,
}))
vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({ formatDateWithTime: () => '', formatDateCompactWithTime: () => '' }),
}))
vi.mock('@/config/agentColors', () => ({ getAgentColor: () => ({ hex: '#ffc300' }) }))
vi.mock('@/config/colorTokens', () => ({
  TEXT_MUTED: '#8895a8',
  TEXT_MUTED_MATERIAL: '#8895a8',
  DOT_SUCCESS: '#67bd6d',
  DOT_WARNING: '#ffc300',
  DOT_ERROR: '#ff6b6b',
}))

import ProjectsTable from './projects/ProjectsTable.vue'
import TasksTable from './tasks/TasksTable.vue'

const tableStub = (name) => ({
  name,
  template: '<div class="table-stub" />',
  props: { items: Array, showSelect: Boolean, modelValue: Array, headers: Array },
  emits: ['update:modelValue', 'update:currentItems', 'update:options'],
})

const shallowStubs = {
  'v-card': { template: '<div class="v-card"><slot /></div>' },
  SupersedeProjectModal: true,
}

describe('ProjectsTable bulk selection', () => {
  beforeEach(() => setActivePinia(createPinia()))

  const mountTable = (props) =>
    mount(ProjectsTable, {
      props: { projects: [{ id: 'p1', status: 'inactive' }], total: 1, ...props },
      global: { stubs: { ...shallowStubs, 'v-data-table-server': tableStub('Server') } },
    })

  it('turns on Vuetify row selection and binds the ticked ids', () => {
    const wrapper = mountTable({ bulkSelectedIds: ['p1'] })
    const table = wrapper.findComponent({ name: 'Server' })
    expect(table.props('showSelect')).toBe(true)
    expect(table.props('modelValue')).toEqual(['p1'])
  })

  it('reports selection changes upward', async () => {
    const wrapper = mountTable()
    await wrapper.findComponent({ name: 'Server' }).vm.$emit('update:modelValue', ['p1'])
    expect(wrapper.emitted('update:bulk-selected-ids')).toEqual([[['p1']]])
  })

  it('has one tick-box column: no link-mode "Linked" column, play button always listed', () => {
    const wrapper = mountTable({ inChainIds: ['p1'] })
    const keys = wrapper.findComponent({ name: 'Server' }).props('headers').map((h) => h.key)
    expect(keys).not.toContain('select')
    expect(keys).toContain('quick_action')
  })
})

describe('TasksTable bulk selection', () => {
  beforeEach(() => setActivePinia(createPinia()))

  const mountTable = (props) =>
    mount(TasksTable, {
      props: { tasks: [{ id: 't1', title: 'T', status: 'pending' }], ...props },
      global: { stubs: { ...shallowStubs, 'v-data-table': tableStub('Client') } },
    })

  it('turns on Vuetify row selection and binds the ticked ids', () => {
    const wrapper = mountTable({ selectedIds: ['t1'] })
    const table = wrapper.findComponent({ name: 'Client' })
    expect(table.props('showSelect')).toBe(true)
    expect(table.props('modelValue')).toEqual(['t1'])
  })

  it('reports the ticked ids and how many rows the current page shows', async () => {
    const wrapper = mountTable()
    const table = wrapper.findComponent({ name: 'Client' })
    await table.vm.$emit('update:modelValue', ['t1'])
    await table.vm.$emit('update:currentItems', [{}, {}, {}])
    expect(wrapper.emitted('update:selected-ids')).toEqual([[['t1']]])
    expect(wrapper.emitted('page-count')).toEqual([[3]])
  })
})
