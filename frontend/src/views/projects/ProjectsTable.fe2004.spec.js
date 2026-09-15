import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

import { getAgentColor } from '@/config/agentColors'

const smAndDownRef = { value: true }
vi.mock('vuetify', () => ({
  useDisplay: () => ({ smAndDown: smAndDownRef }),
}))
vi.mock('@/utils/taxonomyBadge', () => ({
  taxonomyBadgeStyle: () => ({ background: 'rgba(100,100,100,0.15)', color: '#646464' }),
  DEFAULT_PROJECT_TYPE_COLOR: '#646464',
  resolveTaxonomyColor: ({ color } = {}) => color || '#646464',
  isReservedTaskAlias: (alias) => typeof alias === 'string' && /^TSK(?=[-\d])/.test(alias),
}))
vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({
    formatDateWithTime: (d) => (d ? 'Jun 1, 2026' : ''),
    formatDateCompactWithTime: (d) => (d ? '01/06' : ''),
  }),
}))

import ProjectsTable from './ProjectsTable.vue'

const rowStubs = {
  SupersedeProjectModal: true,
  'v-data-table-server': {
    template:
      '<div class="v-data-table" data-table>' +
      '<template v-for="item in items" :key="item.id">' +
      '<slot name="item.status" :item="item" />' +
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

function makeProject(id, status) {
  return {
    id,
    name: `Project ${id}`,
    status,
    series_number: 1,
    taxonomy_alias: `BE-${id}`,
    project_type: { color: '#ff6b6b' },
    staging_status: null,
    created_at: '2026-06-01T10:00:00Z',
    completed_at: null,
    updated_at: '2026-06-01T10:00:00Z',
    product_id: 'prod-1',
    hidden: false,
  }
}

function mountTable(status) {
  return mount(ProjectsTable, {
    props: {
      projects: [makeProject('p1', status)],
      total: 1,
      loading: false,
      hasActiveProject: false,
      inChainIds: [],
      lockedChainIds: [],
    },
    global: { stubs: rowStubs },
  })
}

function hexToRgbString(hex) {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgb(${r}, ${g}, ${b})`
}

describe('ProjectsTable FE-2004 — collapsed active status dot color', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = true
  })

  it('active status dot uses the implementer/active blue, not white', () => {
    const wrapper = mountTable('active')
    const dot = wrapper.find('.status-dot')
    expect(dot.exists()).toBe(true)

    const bg = dot.element.style.backgroundColor
    const activeBlue = hexToRgbString(getAgentColor('implementer').hex)

    expect(bg).not.toBe('rgb(255, 255, 255)')
    expect(bg).toBe(activeBlue)
  })
})
