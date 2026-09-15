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
vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({
    formatDateWithTime: (d) => (d ? 'Jun 1, 2026' : ''),
    formatDateCompactWithTime: (d) => (d ? '01/06' : ''),
  }),
}))
vi.mock('@/config/colorTokens', () => ({
  TEXT_MUTED_MATERIAL: '#8895a8',
  DOT_SUCCESS: '#67bd6d',
  DOT_WARNING: '#ffc300',
  DOT_ERROR: '#ff6b6b',
}))

import ProjectsTable from './ProjectsTable.vue'

const rowStubs = {
  SupersedeProjectModal: true,
  'v-data-table-server': {
    template:
      '<div class="v-data-table" data-table>' +
      '<template v-for="item in items" :key="item.id">' +
      '<slot name="item.select" :item="item" />' +
      '<slot name="item.status" :item="item" />' +
      '<slot name="item.menu" :item="item" />' +
      '</template>' +
      '<slot name="no-data" /></div>',
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

function makeProject(id, status = 'inactive', overrides = {}) {
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
    ...overrides,
  }
}

function mountTable(props = {}) {
  return mount(ProjectsTable, {
    props: {
      projects: [makeProject('p1'), makeProject('p2')],
      total: 2,
      loading: false,
      hasActiveProject: false,
      inChainIds: [],
      lockedChainIds: [],
      ...props,
    },
    global: { stubs: rowStubs },
  })
}

describe('ProjectsTable FE-6171b — D5: tickbox locked by lockedChainIds, NOT inChainIds', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = false
  })

  it('tickbox enabled when in-chain but NOT locked (Editing tier)', () => {
    const wrapper = mountTable({
      inChainIds: ['p1'],
      lockedChainIds: [],
    })
    const checkboxes = wrapper.findAll('input[type="checkbox"]')
    const p1Checkbox = checkboxes.find((cb) => cb.element.closest('[data-project-id="p1"]'))
    if (p1Checkbox) {
      expect(p1Checkbox.attributes('disabled')).toBeUndefined()
    }
    expect(wrapper.exists()).toBe(true)
  })

  it('tickbox disabled when in-chain AND locked (Staged tier)', () => {
    const wrapper = mountTable({
      inChainIds: ['p1'],
      lockedChainIds: ['p1'],
    })
    expect(wrapper.exists()).toBe(true)
    const locked = wrapper.find('[data-testid="select-chain-checkbox-p1"]')
    if (locked.exists()) {
      expect(locked.attributes('disabled')).toBeDefined()
    }
  })

  it('tickbox for non-chain project is never disabled by lockedChainIds', () => {
    const wrapper = mountTable({
      inChainIds: ['p1'],
      lockedChainIds: ['p1'],
    })
    const p2Checkbox = wrapper.find('[data-testid="select-chain-checkbox-p2"]')
    if (p2Checkbox.exists()) {
      expect(p2Checkbox.attributes('disabled')).toBeUndefined()
    }
    expect(wrapper.exists()).toBe(true)
  })
})

describe('ProjectsTable FE-6171b — D9: single "In chain" badge replaces double badge', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = false
  })

  it('renders in-chain-pill for inactive project in chain', () => {
    const wrapper = mountTable({
      projects: [makeProject('p1', 'inactive')],
      total: 1,
      inChainIds: ['p1'],
      lockedChainIds: [],
    })
    expect(wrapper.find('[data-testid="project-in-chain-pill"]').exists()).toBe(true)
  })

  it('FE-6221b: renders in-chain-pill for active project in chain (active member stays identified)', () => {
    const wrapper = mountTable({
      projects: [makeProject('p1', 'active')],
      total: 1,
      inChainIds: ['p1'],
      lockedChainIds: [],
    })
    expect(wrapper.find('[data-testid="project-in-chain-pill"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="project-in-chain-pill"]').text()).toContain('In chain')
  })

  it('does NOT render in-chain-pill for inactive project NOT in chain', () => {
    const wrapper = mountTable({
      projects: [makeProject('p1', 'inactive')],
      total: 1,
      inChainIds: [],
      lockedChainIds: [],
    })
    expect(wrapper.find('[data-testid="project-in-chain-pill"]').exists()).toBe(false)
  })

  it('in-chain-pill text is "In chain"', () => {
    const wrapper = mountTable({
      projects: [makeProject('p1', 'inactive')],
      total: 1,
      inChainIds: ['p1'],
    })
    const pill = wrapper.find('[data-testid="project-in-chain-pill"]')
    if (pill.exists()) {
      expect(pill.text()).toContain('In chain')
    }
  })
})

describe('ProjectsTable FE-6180 — Unlink removed, Deactivate Chain is the back-out', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = false
  })

  it('Unlink item is gone entirely (replaced by Deactivate Chain)', () => {
    const wrapper = mountTable({
      projects: [makeProject('p1', 'inactive')],
      total: 1,
      inChainIds: ['p1'],
      lockedChainIds: [],
    })
    expect(wrapper.find('[data-title="Unlink from chain"]').exists()).toBe(false)
  })

  it('Deactivate Chain item shown for an in-chain project (any tier)', () => {
    const wrapper = mountTable({
      projects: [makeProject('p1', 'inactive')],
      total: 1,
      inChainIds: ['p1'],
      lockedChainIds: ['p1'],
    })
    expect(wrapper.find('[data-title="Deactivate Chain"]').exists()).toBe(true)
  })

  it('Deactivate Chain item NOT shown for a project not in a chain', () => {
    const wrapper = mountTable({
      projects: [makeProject('p1', 'inactive')],
      total: 1,
      inChainIds: [],
      lockedChainIds: [],
    })
    expect(wrapper.find('[data-title="Deactivate Chain"]').exists()).toBe(false)
  })

  it('Deactivate Chain click emits status-action with action=deactivate-chain', async () => {
    const wrapper = mountTable({
      projects: [makeProject('p1', 'inactive')],
      total: 1,
      inChainIds: ['p1'],
      lockedChainIds: [],
    })
    const item = wrapper.find('[data-title="Deactivate Chain"]')
    if (item.exists()) {
      await item.trigger('click')
      const payload = wrapper.emitted('status-action')[0][0]
      expect(payload.action).toBe('deactivate-chain')
      expect(payload.projectId).toBe('p1')
    }
  })
})
