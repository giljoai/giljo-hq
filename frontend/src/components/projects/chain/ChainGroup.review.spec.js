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
  copy: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const api = {
    projects: {
      get: (...a) => h.getProject(...a),
      launchImplementation: (...a) => h.launch(...a),
    },
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
  p1: { id: 'p1', name: 'First', taxonomy_alias: 'FE-0001', status: 'active', implementation_launched_at: '2026-09-30T00:00:00Z', product_id: 'prod-1' },
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

const stubs = {
  CloseoutModal: {
    props: ['show', 'projectId', 'suppressNavigation'],
    emits: ['close', 'closeout'],
    template: `<div v-if="show" class="closeout-stub" :data-project="projectId">
      <button class="closeout-done" @click="$emit('closeout')">done</button></div>`,
  },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
}

let pinia
let store

async function mountGroup() {
  const wrapper = mount(ChainGroup, {
    props: { runId: 'run-1', agentsByProject: {}, now: Date.parse('2026-09-24T20:00:00Z') },
    global: { plugins: [pinia, router], stubs },
  })
  await flushPromises()
  return wrapper
}

beforeEach(async () => {
  pinia = createPinia()
  setActivePinia(pinia)
  store = useSequenceRunStore()
  vi.clearAllMocks()
  h.getProject.mockImplementation(async (id) => ({ data: PROJECTS[id] }))
  h.listRuns.mockResolvedValue({ data: [] })
  h.markReviewed.mockResolvedValue({ data: makeRun({ reviewed_project_ids: ['p1'] }) })
  await router.push('/')
})

describe('a finished chain member shows the solo Review project button', () => {
  it('shows the green Review project button on the unreviewed member only', async () => {
    store._testSeedRuns([makeRun()])
    const w = await mountGroup()
    const first = w.find('[data-project-id="p1"]')
    const btn = first.find('[data-testid="jb-btn-review"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toBe('Review project')
    expect(btn.classes()).toContain('jb-btn-review')
    expect(w.find('[data-project-id="p2"] [data-testid="jb-btn-review"]').exists()).toBe(false)
    expect(w.find('[data-testid="chain-member-review-p1"]').exists()).toBe(false)
  })

  it('opens the chain review in place and records the member as reviewed', async () => {
    store._testSeedRuns([makeRun()])
    const w = await mountGroup()
    await w.find('[data-project-id="p1"] [data-testid="jb-btn-review"]').trigger('click')
    expect(w.find('.closeout-stub').attributes('data-project')).toBe('p1')
    expect(w.emitted('review')).toBeUndefined()
    await w.find('.closeout-done').trigger('click')
    await flushPromises()
    expect(h.markReviewed).toHaveBeenCalledWith('run-1', 'p1')
    expect(router.currentRoute.value.name).toBe('Root')
    expect(w.find('[data-project-id="p1"] [data-testid="jb-btn-review"]').exists()).toBe(false)
  })

  it('a reviewed member shows no Review button', async () => {
    h.listRuns.mockResolvedValue({ data: [makeRun({ reviewed_project_ids: ['p1'] })] })
    await store.hydrate()
    const w = await mountGroup()
    expect(w.find('[data-testid="jb-btn-review"]').exists()).toBe(false)
  })
})
