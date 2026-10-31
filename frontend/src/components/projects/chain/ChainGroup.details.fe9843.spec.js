import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const h = vi.hoisted(() => ({
  getProject: vi.fn(),
  getDefault: vi.fn(),
  listRuns: vi.fn(),
  updateProject: vi.fn(),
  removeMember: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const api = {
    projects: { get: (...a) => h.getProject(...a), update: (...a) => h.updateProject(...a), list: vi.fn(async () => ({ data: [] })) },
    prompts: {},
    settings: { getExecutionModeDefault: (...a) => h.getDefault(...a) },
    sequenceRuns: { list: (...a) => h.listRuns(...a), removeMember: (...a) => h.removeMember(...a) },
  }
  return { default: api, api }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn(), copied: { value: false } }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import ChainGroup from './ChainGroup.vue'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [{ path: '/', name: 'Root', component: { template: '<div />' } }],
})

const PROJECTS = {
  p1: { id: 'p1', name: 'First', taxonomy_alias: 'FE-0001', status: 'completed', product_id: 'prod-1' },
  p2: { id: 'p2', name: 'Second', taxonomy_alias: 'FE-0002', status: 'active', product_id: 'prod-1' },
  p3: { id: 'p3', name: 'Third project with a very long name', taxonomy_alias: 'FE-0003', status: 'parked', product_id: 'prod-1' },
}

function makeRun(overrides = {}) {
  return {
    id: 'run-1',
    project_ids: ['p1', 'p2', 'p3'],
    resolved_order: ['p1', 'p2', 'p3'],
    current_index: 1,
    execution_mode: 'multi_terminal',
    status: 'running',
    locked: true,
    chain_mission: '# Chain mission: One\n\nGoal.',
    project_statuses: { p1: 'completed', p2: 'implementing', p3: 'pending' },
    reviewed_project_ids: ['p1'],
    ...overrides,
  }
}

const stubs = {
  JobsBoardCard: {
    props: ['project'],
    template: `<div class="card-stub" :data-project="project.id">{{ project.name }}</div>`,
  },
  CloseoutModal: { props: ['show'], template: `<div v-if="show" class="closeout-stub" />` },
  BaseDialog: {
    props: ['modelValue', 'title'],
    emits: ['confirm', 'cancel', 'update:modelValue'],
    template: `<div v-if="modelValue" class="dialog-stub"><div class="dialog-body"><slot /></div>
      <button class="dialog-confirm" @click="$emit('confirm')">go</button></div>`,
  },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
  'v-menu': { template: '<div class="menu-stub"><slot name="activator" :props="{}" /><slot /></div>' },
}

let pinia
let store

async function mountGroup(run) {
  store._testSeedRuns([run])
  const w = mount(ChainGroup, {
    props: { runId: 'run-1', agentsByProject: {}, now: Date.parse('2026-09-24T20:00:00Z') },
    global: { plugins: [pinia, router], stubs },
  })
  await flushPromises()
  return w
}

const drop = (w, id) => w.find(`[data-testid="chain-member-drop-${id}"]`)

const twoPending = () =>
  makeRun({ project_ids: ['p1', 'p2'], resolved_order: ['p1', 'p2'], status: 'pending', locked: false, current_index: 0, project_statuses: {}, reviewed_project_ids: [] })

beforeEach(async () => {
  pinia = createPinia()
  setActivePinia(pinia)
  store = useSequenceRunStore()
  vi.clearAllMocks()
  h.getProject.mockImplementation(async (id) => ({ data: PROJECTS[id] }))
  h.getDefault.mockResolvedValue({ data: { execution_mode_default: 'ask' } })
  h.listRuns.mockResolvedValue({ data: [] })
  h.updateProject.mockResolvedValue({ data: {} })
  h.removeMember.mockResolvedValue({ data: {} })
  await router.push('/')
})

describe('FE-9843 dropping to one member', () => {
  it('asks first and says the chain will be cancelled, then unlinks on confirm', async () => {
    const w = await mountGroup(twoPending())
    await drop(w, 'p2').trigger('click')
    await flushPromises()
    expect(h.removeMember).not.toHaveBeenCalled()
    const text = w.find('.dialog-stub').text()
    expect(text).toContain('cancelled')
    expect(text).toContain('one project is not a chain')
    await w.find('.dialog-confirm').trigger('click')
    await flushPromises()
    expect(h.removeMember).toHaveBeenCalledWith('run-1', 'p2')
  })

  it('a three-member pending chain still drops with no confirm', async () => {
    const w = await mountGroup(makeRun({ status: 'pending', locked: false, current_index: 0, project_statuses: {} }))
    await drop(w, 'p2').trigger('click')
    await flushPromises()
    expect(w.find('.dialog-stub').exists()).toBe(false)
    expect(h.removeMember).toHaveBeenCalledWith('run-1', 'p2')
  })
})

describe('FE-9843 (X) label', () => {
  it('names the project, not its serial', async () => {
    const w = await mountGroup(twoPending())
    expect(drop(w, 'p2').attributes('aria-label')).toBe('Drop Second from the chain')
  })

  it('falls back to the serial when the project has no name', async () => {
    h.getProject.mockImplementation(async (id) => ({ data: { ...PROJECTS[id], name: id === 'p2' ? '' : PROJECTS[id].name } }))
    const w = await mountGroup(twoPending())
    expect(drop(w, 'p2').attributes('aria-label')).toBe('Drop FE-0002 from the chain')
  })
})
