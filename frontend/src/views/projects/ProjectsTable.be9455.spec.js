/**
 * ProjectsTable.be9455.spec.js — BE-9455: the per-page control must not offer
 * a page size the server will refuse.
 *
 * Edition scope: Both.
 *
 * This is the SERVER-mode table (`v-data-table-server`), so every page size the
 * footer offers becomes an HTTP `limit`. Vuetify's default option list ends in
 * `{ value: -1, title: 'All' }` and the component previously passed no explicit
 * list, so that default rendered — but `-1` is out of the endpoint's declared
 * `ge=1` range, so choosing it produced a 422 and the table silently did not
 * change. These tests pin that the component now declares its own bounded list.
 *
 * The companion `useProjectFilters.be9455.spec.js` pins the other half: even if
 * an out-of-contract size somehow reaches the composable, it is clamped before
 * it can become a request. Both halves are needed — the option list is where the
 * bad value enters, the clamp is what stops it crossing the wire.
 */
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
import { API_MAX_PAGE_SIZE } from '@/composables/useProjectFilters'

// Same stub as the sibling spec, plus the prop under test.
const tableStub = {
  template: '<div class="v-data-table" data-table><slot /><slot name="no-data" /></div>',
  props: [
    'items',
    'itemsLength',
    'loading',
    'headers',
    'sortBy',
    'page',
    'itemsPerPage',
    'itemsPerPageOptions',
  ],
}

const stubs = {
  'v-data-table-server': tableStub,
  'v-card': { template: '<div class="v-card"><slot /></div>' },
  'v-btn': { template: '<button class="v-btn"><slot /></button>' },
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-menu': { template: '<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>' },
  'v-list': { template: '<div class="v-list"><slot /></div>' },
  'v-list-item': { template: '<div class="v-list-item"><slot /></div>', props: ['prependIcon', 'title'] },
  'v-divider': { template: '<hr />' },
  'v-tooltip': { template: '<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>' },
  'v-progress-circular': { template: '<div class="v-progress-circular" />' },
  StatusBadge: { template: '<span class="status-badge">{{ status }}</span>', props: ['status'] },
  SupersedeProjectModal: true,
}

function mountTable(props = {}) {
  return mount(ProjectsTable, {
    props: { projects: [], total: 0, loading: false, ...props },
    global: { stubs },
  })
}

describe('BE-9455 — ProjectsTable per-page options are server-serviceable', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    smAndDownRef.value = false
  })

  it('declares an explicit option list rather than inheriting Vuetify\'s default', () => {
    const table = mountTable().findComponent(tableStub)
    const options = table.props('itemsPerPageOptions')
    expect(Array.isArray(options)).toBe(true)
    expect(options.length).toBeGreaterThan(0)
  })

  it('offers no option the API would reject', () => {
    const table = mountTable().findComponent(tableStub)
    for (const option of table.props('itemsPerPageOptions')) {
      // Options may be bare numbers or {value,title} objects; both are valid Vuetify.
      const value = typeof option === 'object' && option !== null ? option.value : option
      expect(value).toBeGreaterThanOrEqual(1)
      expect(value).toBeLessThanOrEqual(API_MAX_PAGE_SIZE)
    }
  })

  it('does not offer the Vuetify "All" sentinel, which this endpoint cannot serve', () => {
    const table = mountTable().findComponent(tableStub)
    const values = table
      .props('itemsPerPageOptions')
      .map((o) => (typeof o === 'object' && o !== null ? o.value : o))
    expect(values).not.toContain(-1)
  })

  it('still offers the everyday sizes, and reaches the API maximum', () => {
    const table = mountTable().findComponent(tableStub)
    const values = table
      .props('itemsPerPageOptions')
      .map((o) => (typeof o === 'object' && o !== null ? o.value : o))
    expect(values).toContain(10)
    expect(values).toContain(100)
    // The operator's workaround was "pick 100 and page"; the largest page the
    // server will serve must be reachable from the control.
    expect(values).toContain(API_MAX_PAGE_SIZE)
  })
})
