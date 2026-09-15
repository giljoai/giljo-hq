import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

const smAndDownRef = { value: false }
vi.mock('vuetify', () => ({
  useDisplay: () => ({ smAndDown: smAndDownRef }),
}))
vi.mock('@/utils/taxonomyBadge', () => ({
  taxonomyBadgeStyle: () => ({ background: 'rgba(100,100,100,0.15)', color: '#646464' }),
  DEFAULT_PROJECT_TYPE_COLOR: '#646464',
  resolveTaxonomyColor: ({ color } = {}) => color || '#646464',
  isReservedTaskAlias: (alias) => typeof alias === 'string' && /^TSK(?=[-\d])/.test(alias),
}))
vi.mock('@/config/colorTokens', () => ({
  TEXT_MUTED_MATERIAL: '#8895a8',
  DOT_SUCCESS: '#67bd6d',
  DOT_WARNING: '#ffc300',
  DOT_ERROR: '#ff6b6b',
}))
vi.mock('@/composables/useFormatDate', () => {
  const label = (d) =>
    d === '2026-07-01T10:00:00Z' ? 'COMPLETED-DATE' : d === '2026-07-20T23:59:00Z' ? 'UPDATED-DATE' : 'NO-DATE'
  return { useFormatDate: () => ({ formatDateWithTime: label, formatDateCompactWithTime: label }) }
})

const COMPLETED_AT = '2026-07-01T10:00:00Z'
const UPDATED_AT = '2026-07-20T23:59:00Z'
const COMPLETED_TEXT = 'COMPLETED-DATE'
const UPDATED_TEXT = 'UPDATED-DATE'

import ProjectsTable from './ProjectsTable.vue'

const rowStubs = {
  SupersedeProjectModal: true,
  'v-data-table-server': {
    template:
      '<div class="v-data-table" data-table>' +
      '<template v-for="item in items" :key="item.id">' +
      '<slot name="item.completed_at" :item="item" />' +
      '</template></div>',
    props: ['items', 'itemsLength', 'loading', 'headers', 'sortBy', 'page', 'itemsPerPage'],
  },
  'v-card': { template: '<div class="v-card"><slot /></div>' },
  'v-btn': { template: '<button class="v-btn" v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>' },
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-menu': { template: '<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>' },
  'v-list': { template: '<div class="v-list"><slot /></div>' },
  'v-list-item': {
    template: '<div class="v-list-item" :data-title="title" @click="$emit(\'click\')"><slot /></div>',
    props: ['prependIcon', 'title'],
    emits: ['click'],
  },
  'v-divider': { template: '<hr />' },
  'v-tooltip': { template: '<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>' },
  'v-progress-circular': { template: '<div class="v-progress-circular" />' },
  StatusBadge: { template: '<span class="status-badge">{{ status }}</span>', props: ['status'] },
}

function makeProject({ status, completed_at }) {
  return {
    id: 'p1',
    name: 'Project p1',
    status,
    series_number: 1,
    taxonomy_alias: 'BE-9343',
    project_type: { color: '#ff6b6b' },
    staging_status: null,
    created_at: '2026-06-01T10:00:00Z',
    completed_at,
    updated_at: UPDATED_AT,
    product_id: 'prod-1',
    hidden: false,
  }
}

function mountTable(project) {
  return mount(ProjectsTable, {
    props: {
      projects: [makeProject(project)],
      total: 1,
      loading: false,
      hasActiveProject: false,
      inChainIds: [],
      lockedChainIds: [],
    },
    global: { stubs: rowStubs },
  })
}

describe('ProjectsTable BE-9343 — the Completed column reads completed_at only', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = false
  })

  it('shows the real completion date when the backend stamped one', () => {
    const wrapper = mountTable({ status: 'completed', completed_at: COMPLETED_AT })
    expect(wrapper.text()).toContain(COMPLETED_TEXT)
    expect(wrapper.text()).not.toContain(UPDATED_TEXT)
  })

  it('THE regression: never falls back to updated_at when completed_at is missing', () => {
    const wrapper = mountTable({ status: 'completed', completed_at: null })
    expect(wrapper.text()).not.toContain(UPDATED_TEXT)
    expect(wrapper.find('.date-cell--empty').exists()).toBe(true)
  })

  it.each(['cancelled', 'terminated'])(
    'applies the same rule to %s, not just completed',
    (status) => {
      const wrapper = mountTable({ status, completed_at: null })
      expect(wrapper.text()).not.toContain(UPDATED_TEXT)
      expect(wrapper.find('.date-cell--empty').exists()).toBe(true)
    },
  )

  it('a running project still shows the em-dash', () => {
    const wrapper = mountTable({ status: 'active', completed_at: null })
    expect(wrapper.find('.date-cell--empty').exists()).toBe(true)
    expect(wrapper.text()).not.toContain(UPDATED_TEXT)
  })
})
