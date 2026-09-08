/**
 * ProjectsTable.vue — FE-6165f (locked "In chain" checkbox merge)
 *
 * Tests the inChainIds prop: rows in the list are force-ticked + disabled +
 * show an "In chain" pill; rows selected-only are ticked + enabled.
 *
 * The v-data-table-server slot rendering is exercised via a custom stub that
 * calls the `item.select` scoped slot with a seeded item — same pattern used
 * across other ProjectsTable tests.
 *
 * Edition Scope: CE
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

// ── mocks ─────────────────────────────────────────────────────────────────────
vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({
    formatDateWithTime: vi.fn((d) => d),
    formatDateCompactWithTime: vi.fn((d) => d),
  }),
}))

vi.mock('@/utils/taxonomyBadge', () => ({
  taxonomyBadgeStyle: vi.fn(() => ({})),
  resolveTaxonomyColor: vi.fn(() => '#607D8B'),
  isReservedTaskAlias: vi.fn(() => false),
}))

vi.mock('vuetify', () => ({
  useDisplay: () => ({ smAndDown: { value: false } }),
}))

import ProjectsTable from '@/views/projects/ProjectsTable.vue'

// A stub that calls the item.select scoped slot with `item` so we can test
// the select cell without a real v-data-table-server.
function makeTableStub(item) {
  return {
    // v-data-table-server renders named scoped slots as `item.<key>`.
    // FE-6170: the "In chain" pill moved from the select cell to the status
    // column, so the stub must also render the item.status slot.
    template: `<div class="v-data-table-server">
      <slot name="item.select" :item="item" />
      <slot name="item.status" :item="item" />
    </div>`,
    props: ['headers', 'items', 'itemsLength', 'loading', 'itemsPerPage', 'page', 'sortBy', 'mustSort', 'itemKey', 'fixedHeader', 'itemProps'],
    setup() { return { item } },
  }
}

const INACTIVE_ITEM = {
  id: 'p-inactive',
  name: 'Project A',
  status: 'inactive',
  taxonomy_alias: 'BE-0001',
  project_type: { abbreviation: 'BE', color: '#6DB3E4' },
  series_number: 1,
  staging_status: null,
  created_at: '2024-01-01T00:00:00Z',
  completed_at: null,
  hidden: false,
  product_id: 'prod-1',
}

const commonProps = {
  projects: [INACTIVE_ITEM],
  total: 1,
  loading: false,
  currentPage: 1,
  itemsPerPage: 10,
  sortBy: [{ key: 'created_at', order: 'desc' }],
  selectedIds: [],
  electionActive: false,
  inChainIds: [],
}

function mountTable(extraProps = {}, item = INACTIVE_ITEM) {
  return mount(ProjectsTable, {
    props: { ...commonProps, ...extraProps },
    global: {
      stubs: {
        'v-data-table-server': makeTableStub(item),
        'v-card': { template: '<div class="v-card"><slot /></div>' },
        'v-checkbox-btn': {
          inheritAttrs: false,
          props: ['modelValue', 'disabled'],
          template: '<input type="checkbox" :checked="modelValue" :disabled="disabled" v-bind="$attrs" />',
        },
        StatusBadge: true,
        'v-tooltip': {
          props: ['text'],
          template: '<div><slot name="activator" :props="{}" /></div>',
        },
        'v-btn': { template: '<button v-bind="$attrs"><slot /></button>' },
        'v-icon': { template: '<span><slot /></span>' },
        'v-menu': { template: '<div><slot /></div>' },
        'v-list': { template: '<div><slot /></div>' },
        'v-list-item': { template: '<div><slot /></div>' },
        'v-divider': { template: '<hr />' },
      },
    },
  })
}

describe('ProjectsTable.vue — FE-6165f inChainIds prop', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the checkbox ticked AND disabled for a row in inChainIds (FE-6180: disabled = inChainIds membership, back-out via kebab)', () => {
    // FE-6180: once a project is in an active chain its tickbox is a PASSIVE
    // indicator — force-ticked + DISABLED by membership (inChainIds). Back-out
    // is via the kebab (Deactivate Chain), never by unticking.
    const w = mountTable({ inChainIds: ['p-inactive'], lockedChainIds: ['p-inactive'] })
    const cb = w.find('[data-testid="project-select-checkbox-p-inactive"]')
    expect(cb.exists()).toBe(true)
    expect(cb.element.checked).toBe(true)
    expect(cb.element.disabled).toBe(true)
  })

  it('renders the checkbox ticked AND disabled for a row in inChainIds even when lockedChainIds is empty (FE-6180: in-chain => force-ticked + disabled, back-out via kebab)', () => {
    // FE-6180: disable is driven by inChainIds membership alone — there is no
    // "Editing tier" exception. Any in-chain project is disabled regardless of
    // lockedChainIds. The "Editing tier keeps it enabled" premise no longer exists.
    const w = mountTable({ inChainIds: ['p-inactive'], lockedChainIds: [] })
    const cb = w.find('[data-testid="project-select-checkbox-p-inactive"]')
    expect(cb.exists()).toBe(true)
    expect(cb.element.checked).toBe(true)
    expect(cb.element.disabled).toBe(true)
  })

  it('renders the "In chain" pill for a row in inChainIds', () => {
    const w = mountTable({ inChainIds: ['p-inactive'] })
    const pill = w.find('[data-testid="project-in-chain-pill"]')
    expect(pill.exists()).toBe(true)
    expect(pill.text()).toBe('In chain')
  })

  it('does NOT render the pill when row is NOT in inChainIds', () => {
    const w = mountTable({ inChainIds: [] })
    expect(w.find('[data-testid="project-in-chain-pill"]').exists()).toBe(false)
  })

  it('renders the checkbox ticked but NOT disabled when selected-only (not in chain)', () => {
    const w = mountTable({ selectedIds: ['p-inactive'], inChainIds: [] })
    const cb = w.find('[data-testid="project-select-checkbox-p-inactive"]')
    expect(cb.element.checked).toBe(true)
    expect(cb.element.disabled).toBe(false)
  })

  it('checkbox model-value = (selectedIds.includes || inChainIds.includes)', () => {
    // selected=false, inChain=true → checked
    const w = mountTable({ selectedIds: [], inChainIds: ['p-inactive'] })
    const cb = w.find('[data-testid="project-select-checkbox-p-inactive"]')
    expect(cb.element.checked).toBe(true)
  })

  it('does NOT render a checkbox for an active (non-inactive) row, but DOES show In chain pill (FE-6221b)', () => {
    // Active rows have no select checkbox (they can't be elected into a new chain),
    // but FE-6221b: they DO show the "In chain" pill so chain membership remains
    // visible throughout the member's active run phase — matching /roadmap.
    const activeItem = { ...INACTIVE_ITEM, id: 'p-active', status: 'active' }
    const w = mountTable({ inChainIds: ['p-active'] }, activeItem)
    expect(w.find('[data-testid="project-select-checkbox"]').exists()).toBe(false) // no tickbox
    expect(w.find('[data-testid="project-in-chain-pill"]').exists()).toBe(true)    // pill present
  })
})
