import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const h = vi.hoisted(() => ({
  getProject: vi.fn(),
  launch: vi.fn(),
  chainStaging: vi.fn(),
  chainImplementation: vi.fn(),
  chainMemberFallback: vi.fn(),
  updateRun: vi.fn(),
  stopRun: vi.fn(),
  deactivateRun: vi.fn(),
  listRuns: vi.fn(),
  markReviewed: vi.fn(),
  archive: vi.fn(),
  projReviewed: vi.fn(),
  memory: vi.fn(),
  copy: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const api = {
    projects: {
      get: (...a) => h.getProject(...a),
      launchImplementation: (...a) => h.launch(...a),
      archive: (...a) => h.archive(...a),
      markReviewed: (...a) => h.projReviewed(...a),
    },
    products: { getMemoryEntries: (...a) => h.memory(...a) },
    prompts: {
      chainStaging: (...a) => h.chainStaging(...a),
      chainImplementation: (...a) => h.chainImplementation(...a),
      chainMemberFallback: (...a) => h.chainMemberFallback(...a),
    },
    sequenceRuns: {
      update: (...a) => h.updateRun(...a),
      stop: (...a) => h.stopRun(...a),
      deactivate: (...a) => h.deactivateRun(...a),
      list: (...a) => h.listRuns(...a),
      markReviewed: (...a) => h.markReviewed(...a),
    },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: h.copy, copied: { value: false } }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.toast }) }))

import ChainGroup from './ChainGroup.vue'
import CloseoutModal from '@/components/orchestration/CloseoutModal.vue'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/jobs-overview', name: 'JobsViewport', component: { template: '<div />' } },
    { path: '/projects/:projectId', name: 'ProjectLaunch', component: { template: '<div />' } },
    { path: '/projects', name: 'Projects', component: { template: '<div />' } },
  ],
})

const PROJECTS = {
  p1: { id: 'p1', name: 'First', taxonomy_alias: 'FE-0001', status: 'inactive', implementation_launched_at: '2026-09-30T00:00:00Z', product_id: 'prod-1' },
  p2: { id: 'p2', name: 'Second', taxonomy_alias: 'FE-0002', status: 'active', product_id: 'prod-1' },
  p3: { id: 'p3', name: 'Third', taxonomy_alias: 'FE-0003', status: 'active', product_id: 'prod-1' },
}

function makeRun(overrides = {}) {
  return {
    id: 'run-1',
    project_ids: ['p3', 'p1', 'p2'],
    resolved_order: ['p1', 'p2', 'p3'],
    current_index: 1,
    execution_mode: 'multi_terminal',
    status: 'running',
    locked: true,
    chain_mission: '# Chain mission: One Jobs board\n\nFold chains into the board.',
    project_statuses: { p1: 'completed', p2: 'implementing', p3: 'pending' },
    reviewed_project_ids: [],
    ...overrides,
  }
}

const passthrough = { template: '<div><slot /></div>' }
const stubs = {
  'v-dialog': { template: '<div v-if="modelValue"><slot /></div>', props: ['modelValue'] },
  'v-card': passthrough,
  'v-card-text': passthrough,
  'v-btn': { template: '<button><slot /></button>' },
  'v-icon': { template: '<i />' },
  'v-spacer': { template: '<div />' },
  'v-divider': { template: '<hr />' },
  'v-progress-circular': { template: '<div />' },
  'v-alert': passthrough,
  'v-expansion-panels': passthrough,
  'v-expansion-panel': passthrough,
  'v-expansion-panel-title': passthrough,
  'v-expansion-panel-text': passthrough,
  'v-list': { template: '<ul><slot /></ul>' },
  'v-list-item': { template: '<li><slot /></li>' },
  'v-list-item-title': { template: '<span><slot /></span>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
}

describe('Close on a chain member whose project row is inactive', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    h.getProject.mockImplementation(async (id) => ({ data: PROJECTS[id] }))
    h.listRuns.mockResolvedValue({ data: [] })
    h.memory.mockResolvedValue({ data: { entries: [] } })
    h.archive.mockResolvedValue({ data: {} })
    h.projReviewed.mockRejectedValue(Object.assign(new Error('409'), { response: { status: 409 } }))
    h.markReviewed.mockResolvedValue({ data: {} })
    await router.push('/')
  })

  it('closes through the chain review only and never calls the project reviewed endpoint', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    useSequenceRunStore()._testSeedRuns([makeRun()])
    const w = mount(ChainGroup, {
      props: { runId: 'run-1', agentsByProject: {}, now: Date.parse('2026-09-24T20:00:00Z') },
      global: { plugins: [pinia, router], stubs, directives: { draggable: {} } },
    })
    await flushPromises()
    await w.find('[data-testid="jb-btn-review"], [data-testid="chain-member-review-p1"]').trigger('click')
    await flushPromises()
    const close = w.findAll('button').find((b) => /close/i.test(b.text()) && !/review/i.test(b.text()))
    await close.trigger('click')
    await flushPromises()
    expect(h.archive.mock.calls).toEqual([])
    expect(h.projReviewed).not.toHaveBeenCalled()
    expect(h.markReviewed.mock.calls).toEqual([['run-1', 'p1']])
  })

  it('a solo card review of a finished project still calls the project reviewed endpoint', async () => {
    h.projReviewed.mockResolvedValue({ data: {} })
    const pinia = createPinia()
    setActivePinia(pinia)
    const w = mount(CloseoutModal, {
      props: { show: true, projectId: 'solo-1', projectName: 'Solo', productId: 'prod-1', projectStatus: 'completed', suppressNavigation: true },
      global: { plugins: [pinia, router], stubs, directives: { draggable: {} } },
    })
    await flushPromises()
    await w.find('[data-testid="close-out-btn"]').trigger('click')
    await flushPromises()
    expect(h.projReviewed).toHaveBeenCalledWith('solo-1')
  })
})
