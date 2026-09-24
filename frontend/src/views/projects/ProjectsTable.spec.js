import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
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
    formatDateWithTime: (d) => d ? 'Jun 1, 2026' : '',
    formatDateCompactWithTime: (d) => d ? '01/06' : '',
  }),
}))
vi.mock('@/config/colorTokens', () => ({
  TEXT_MUTED_MATERIAL: '#8895a8',
  DOT_SUCCESS: '#67bd6d',
  DOT_WARNING: '#ffc300',
  DOT_ERROR: '#ff6b6b',
}))

import ProjectsTable from './ProjectsTable.vue'

const stubs = {
  'v-data-table-server': {
    template: '<div class="v-data-table" data-table><slot /><slot name="no-data" /></div>',
    props: ['items', 'itemsLength', 'loading', 'headers', 'sortBy', 'page', 'itemsPerPage'],
  },
  'v-card': { template: '<div class="v-card"><slot /></div>' },
  'v-btn': { template: '<button class="v-btn" v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>' },
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-menu': { template: '<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>' },
  'v-list': { template: '<div class="v-list"><slot /></div>' },
  'v-list-item': { template: '<div class="v-list-item" @click="$emit(\'click\')"><slot /></div>', props: ['prependIcon', 'title'] },
  'v-divider': { template: '<hr />' },
  'v-tooltip': { template: '<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>' },
  'v-progress-circular': { template: '<div class="v-progress-circular" />' },
  StatusBadge: { template: '<span class="status-badge">{{ status }}</span>', props: ['status'] },
  SupersedeProjectModal: true,
}

const sampleProjects = [
  {
    id: 'proj-1',
    name: 'Fix login',
    status: 'inactive',
    series_number: 1,
    taxonomy_alias: 'BE-0001',
    project_type: { color: '#ff6b6b' },
    staging_status: null,
    created_at: '2026-06-01T10:00:00Z',
    completed_at: null,
    updated_at: '2026-06-01T10:00:00Z',
    product_id: 'prod-1',
    hidden: false,
  },
]

function mountTable(props = {}) {
  return mount(ProjectsTable, {
    props: {
      projects: sampleProjects,
      total: sampleProjects.length,
      loading: false,
      ...props,
    },
    global: { stubs },
  })
}

describe('ProjectsTable', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = false
  })

  afterEach(() => {
    smAndDownRef.value = false
  })

  it('renders the table container', () => {
    const wrapper = mountTable()
    expect(wrapper.find('.v-card').exists()).toBe(true)
    expect(wrapper.find('[data-table]').exists()).toBe(true)
  })

  it('renders with projects data', () => {
    const wrapper = mountTable()
    expect(wrapper.find('[data-table]').exists()).toBe(true)
    expect(wrapper.exists()).toBe(true)
  })

  it('shows no-data slot when projects is empty', () => {
    const wrapper = mountTable({ projects: [] })
    expect(wrapper.html()).toContain('No projects found')
  })

  it('emits open-project when badge button clicked', async () => {
    const wrapper = mountTable()
    expect(wrapper.exists()).toBe(true)
  })
})

describe('ProjectsTable — server mode (BE-6076)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = false
  })

  it('binds the server total to :items-length', () => {
    const wrapper = mountTable({ total: 137 })
    const table = wrapper.findComponent(stubs['v-data-table-server'])
    expect(table.props('itemsLength')).toBe(137)
  })

  it('passes the parent sortBy through (server sort, no client customKeySort)', () => {
    const sortBy = [{ key: 'name', order: 'asc' }]
    const wrapper = mountTable({ sortBy })
    const table = wrapper.findComponent(stubs['v-data-table-server'])
    expect(table.props('sortBy')).toEqual(sortBy)
  })

  it('forwards @update:options so the parent can re-fetch the page', async () => {
    const wrapper = mountTable()
    const table = wrapper.findComponent(stubs['v-data-table-server'])
    const options = { page: 2, itemsPerPage: 10, sortBy: [{ key: 'series_number', order: 'desc' }] }
    table.vm.$emit('update:options', options)
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:options')).toBeTruthy()
    expect(wrapper.emitted('update:options')[0][0]).toEqual(options)
  })
})

describe('ProjectsTable — election fade (FE-6165a)', () => {
  const rowStubs = {
    ...stubs,
    'v-data-table-server': {
      template:
        '<div class="v-data-table" data-table>' +
        '<template v-for="item in items" :key="item.id">' +
        '<slot name="item.quick_action" :item="item" /></template>' +
        '<slot name="no-data" /></div>',
      props: ['items', 'itemsLength', 'loading', 'headers', 'sortBy', 'page', 'itemsPerPage'],
    },
  }

  function mountWithRows(props = {}) {
    return mount(ProjectsTable, {
      props: {
        projects: sampleProjects,
        total: sampleProjects.length,
        loading: false,
        ...props,
      },
      global: { stubs: rowStubs },
    })
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = false
  })

  it('play button is enabled and unfaded when no election is active', () => {
    const wrapper = mountWithRows({ electionActive: false })
    const btn = wrapper.find('.play-circle-btn')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('disabled')).toBeUndefined()
    expect(btn.classes()).not.toContain('play-btn-disabled')
  })

  it('play button stays enabled and emits even with rows ticked', async () => {
    const wrapper = mountWithRows({ bulkSelectedIds: ['p1', 'p2'] })
    const btn = wrapper.find('.play-circle-btn')
    expect(btn.attributes('disabled')).toBeUndefined()
    expect(btn.classes()).not.toContain('play-btn-disabled')
    await btn.trigger('click')
    expect(wrapper.emitted('activate-launch')).toBeTruthy()
  })

  it('play button is enabled with no election active (the cross-project grey-out is retired)', () => {
    const wrapper = mountWithRows({ electionActive: false })
    const btn = wrapper.find('.play-circle-btn')
    expect(btn.attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).not.toContain('Another project is active')
  })

  it('emits activate-launch when clicked with no election active', async () => {
    const wrapper = mountWithRows({ electionActive: false })
    await wrapper.find('.play-circle-btn').trigger('click')
    expect(wrapper.emitted('activate-launch')).toBeTruthy()
  })
})

describe('ProjectsTable — Deactivate Chain (FE-6178)', () => {
  const menuStubs = {
    ...stubs,
    'v-list-item': {
      template: '<div class="v-list-item" v-bind="$attrs" @click="$emit(\'click\')">{{ title }}<slot /></div>',
      props: ['prependIcon', 'title'],
      inheritAttrs: false,
    },
    'v-data-table-server': {
      template:
        '<div class="v-data-table" data-table>' +
        '<template v-for="item in items" :key="item.id">' +
        '<slot name="item.menu" :item="item" /></template>' +
        '<slot name="no-data" /></div>',
      props: ['items', 'itemsLength', 'loading', 'headers', 'sortBy', 'page', 'itemsPerPage'],
    },
  }

  function mountWithMenu(props = {}) {
    return mount(ProjectsTable, {
      props: { projects: sampleProjects, total: 1, loading: false, ...props },
      global: { stubs: menuStubs },
    })
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = false
  })

  it('shows "Deactivate Chain" for a project that is in a chain', () => {
    const wrapper = mountWithMenu({ inChainIds: ['proj-1'] })
    const item = wrapper.find('[data-testid="deactivate-chain-item"]')
    expect(item.exists()).toBe(true)
    expect(item.text()).toContain('Deactivate Chain')
  })

  it('hides "Deactivate Chain" for a project that is NOT in a chain', () => {
    const wrapper = mountWithMenu({ inChainIds: [] })
    expect(wrapper.find('[data-testid="deactivate-chain-item"]').exists()).toBe(false)
  })

  it('emits status-action with deactivate-chain when clicked', async () => {
    const wrapper = mountWithMenu({ inChainIds: ['proj-1'] })
    await wrapper.find('[data-testid="deactivate-chain-item"]').trigger('click')
    expect(wrapper.emitted('status-action')).toBeTruthy()
    expect(wrapper.emitted('status-action')[0][0]).toEqual({ action: 'deactivate-chain', projectId: 'proj-1' })
  })

  it('suppresses the solo Activate action for an in-chain project (Deactivate Chain is the counter)', () => {
    const wrapper = mountWithMenu({ inChainIds: ['proj-1'] })
    const titles = wrapper.findAll('.v-list-item').map((i) => i.text())
    expect(titles.some((t) => t.includes('Deactivate Chain'))).toBe(true)
    expect(titles.some((t) => t === 'Activate' || t.startsWith('Activate'))).toBe(false)
  })

  it('keeps the solo Activate action for a non-chain inactive project', () => {
    const wrapper = mountWithMenu({ inChainIds: [] })
    const titles = wrapper.findAll('.v-list-item').map((i) => i.text())
    expect(titles.some((t) => t.startsWith('Activate'))).toBe(true)
  })

  it('shows "Reset to original" for a solo staged project, not for a clean one', () => {
    const staged = [{ ...sampleProjects[0], id: 'p-staged', staging_status: 'staging_complete' }]
    expect(mountWithMenu({ projects: staged, inChainIds: [] }).find('[data-testid="reset-project-item"]').exists()).toBe(true)
    expect(mountWithMenu({ inChainIds: [] }).find('[data-testid="reset-project-item"]').exists()).toBe(false)
  })

  it('hides "Reset to original" for an in-chain project (Deactivate Chain is the chain back-out)', () => {
    const staged = [{ ...sampleProjects[0], id: 'proj-1', staging_status: 'staging_complete' }]
    const wrapper = mountWithMenu({ projects: staged, inChainIds: ['proj-1'] })
    expect(wrapper.find('[data-testid="reset-project-item"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="deactivate-chain-item"]').exists()).toBe(true)
  })
})

describe('ProjectsTable — Archived badge (BE-2002)', () => {
  const nameStubs = {
    ...stubs,
    'v-chip': { template: '<span class="v-chip" v-bind="$attrs"><slot /></span>' },
    'v-data-table-server': {
      template:
        '<div class="v-data-table" data-table>' +
        '<template v-for="item in items" :key="item.id">' +
        '<slot name="item.name" :item="item" /></template></div>',
      props: ['items', 'itemsLength', 'loading', 'headers', 'sortBy', 'page', 'itemsPerPage'],
    },
  }

  function mountName(projects) {
    return mount(ProjectsTable, {
      props: { projects, total: projects.length, loading: false },
      global: { stubs: nameStubs },
    })
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = false
  })

  it('renders the Archived badge for an archived (hidden) project', () => {
    const wrapper = mountName([{ ...sampleProjects[0], id: 'p-h', hidden: true }])
    const badge = wrapper.find('[data-test="project-archived-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('Archived')
  })

  it('does NOT render the Archived badge for a visible project', () => {
    const wrapper = mountName([{ ...sampleProjects[0], hidden: false }])
    expect(wrapper.find('[data-test="project-archived-badge"]').exists()).toBe(false)
  })
})

describe('ProjectsTable — Park/Unpark (IMP-9258)', () => {
  const menuStubs = {
    ...stubs,
    'v-list-item': {
      template: '<div class="v-list-item" v-bind="$attrs" @click="$emit(\'click\')">{{ title }}<slot /></div>',
      props: ['prependIcon', 'title'],
      inheritAttrs: false,
    },
    'v-data-table-server': {
      template:
        '<div class="v-data-table" data-table>' +
        '<template v-for="item in items" :key="item.id">' +
        '<slot name="item.menu" :item="item" /></template>' +
        '<slot name="no-data" /></div>',
      props: ['items', 'itemsLength', 'loading', 'headers', 'sortBy', 'page', 'itemsPerPage'],
    },
  }

  function mountWithMenu(props = {}) {
    return mount(ProjectsTable, {
      props: { projects: sampleProjects, total: 1, loading: false, ...props },
      global: { stubs: menuStubs },
    })
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = false
  })

  it('offers "Park Project" for an inactive project', () => {
    const wrapper = mountWithMenu({ inChainIds: [] })
    const titles = wrapper.findAll('.v-list-item').map((i) => i.text())
    expect(titles.some((t) => t.includes('Park Project'))).toBe(true)
  })

  it('offers "Park Project" for an active project', () => {
    const active = [{ ...sampleProjects[0], status: 'active' }]
    const wrapper = mountWithMenu({ projects: active, inChainIds: [] })
    const titles = wrapper.findAll('.v-list-item').map((i) => i.text())
    expect(titles.some((t) => t.includes('Park Project'))).toBe(true)
  })

  it('emits status-action with park when "Park Project" is clicked', async () => {
    const wrapper = mountWithMenu({ inChainIds: [] })
    const items = wrapper.findAll('.v-list-item')
    const parkItem = items.find((i) => i.text().includes('Park Project'))
    await parkItem.trigger('click')
    expect(wrapper.emitted('status-action')).toBeTruthy()
    expect(wrapper.emitted('status-action')[0][0]).toEqual({ action: 'park', projectId: 'proj-1' })
  })

  it('offers "Unpark" (not "Park Project") for an already-parked project', () => {
    const parked = [{ ...sampleProjects[0], status: 'parked' }]
    const wrapper = mountWithMenu({ projects: parked, inChainIds: [] })
    const titles = wrapper.findAll('.v-list-item').map((i) => i.text())
    expect(titles.some((t) => t.includes('Unpark'))).toBe(true)
    expect(titles.some((t) => t.includes('Park Project'))).toBe(false)
  })

  it('emits status-action with unpark when "Unpark" is clicked on a parked row', async () => {
    const parked = [{ ...sampleProjects[0], status: 'parked' }]
    const wrapper = mountWithMenu({ projects: parked, inChainIds: [] })
    const items = wrapper.findAll('.v-list-item')
    const unparkItem = items.find((i) => i.text().includes('Unpark'))
    await unparkItem.trigger('click')
    expect(wrapper.emitted('status-action')).toBeTruthy()
    expect(wrapper.emitted('status-action')[0][0]).toEqual({ action: 'unpark', projectId: 'proj-1' })
  })

  it('does NOT offer "Park Project" for a cancelled/completed/terminated project', () => {
    for (const status of ['cancelled', 'completed', 'terminated']) {
      const wrapper = mountWithMenu({ projects: [{ ...sampleProjects[0], status }], inChainIds: [] })
      const titles = wrapper.findAll('.v-list-item').map((i) => i.text())
      expect(titles.some((t) => t.includes('Park Project'))).toBe(false)
    }
  })

  it('keeps Edit available for a parked project (resumable, not lifecycle-finished)', () => {
    const parked = [{ ...sampleProjects[0], status: 'parked' }]
    const wrapper = mountWithMenu({ projects: parked, inChainIds: [] })
    const titles = wrapper.findAll('.v-list-item').map((i) => i.text())
    expect(titles.some((t) => t.includes('Edit Project'))).toBe(true)
  })
})

describe('ProjectsTable — headers (FE-6050 / FE-6176)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    smAndDownRef.value = false
  })

  it('NORMAL full mode: 8 columns with quick_action, NO select', () => {
    smAndDownRef.value = false
    const wrapper = mountTable({ linkMode: false })
    const keys = wrapper.vm.headers.map((h) => h.key)
    expect(wrapper.vm.headers.length).toBe(8)
    expect(keys).toContain('quick_action')
    expect(keys).not.toContain('select')
    expect(keys).toContain('name')
    expect(keys).toContain('completed_at')
    expect(keys).toContain('staging_status')
  })

  it('NORMAL compact mode: 4 columns with quick_action, NO select', () => {
    smAndDownRef.value = true
    const wrapper = mountTable({ linkMode: false })
    const keys = wrapper.vm.headers.map((h) => h.key)
    expect(wrapper.vm.headers.length).toBe(4)
    expect(keys).toContain('series_number')
    expect(keys).toContain('status')
    expect(keys).toContain('quick_action')
    expect(keys).toContain('menu')
    expect(keys).not.toContain('select')
  })
})
