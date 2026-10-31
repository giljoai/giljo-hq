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

describe('FE-9835 (X) on the step row', () => {
  it('a running chain shows (X) on open members only, with the started tooltip', async () => {
    const w = await mountGroup(makeRun({ project_statuses: { p1: 'completed', p2: 'implementing', p3: 'pending' } }))
    expect(drop(w, 'p1').exists()).toBe(false)
    expect(drop(w, 'p2').exists()).toBe(true)
    expect(drop(w, 'p3').attributes('title')).toBe('Drop this project from the chain. It is parked, not deleted.')
  })

  it('a chain that has not started shows (X) with the short tooltip', async () => {
    const w = await mountGroup(
      makeRun({ status: 'pending', locked: false, current_index: 0, project_statuses: {} }),
    )
    expect(drop(w, 'p1').attributes('title')).toBe('Drop this project from the chain.')
  })

  it('a staged chain shows no (X)', async () => {
    const w = await mountGroup(
      makeRun({ status: 'pending', locked: true, current_index: 0, project_statuses: {} }),
    )
    expect(drop(w, 'p1').exists()).toBe(false)
  })

  it('a dropped member shows no (X)', async () => {
    const w = await mountGroup(makeRun({ project_statuses: { p1: 'completed', p2: 'implementing', p3: 'detached' } }))
    expect(drop(w, 'p3').exists()).toBe(false)
  })

  it('dropping a waiting member in a running chain parks it with no confirm', async () => {
    const w = await mountGroup(makeRun())
    await drop(w, 'p3').trigger('click')
    await flushPromises()
    expect(w.find('.dialog-stub').exists()).toBe(false)
    expect(h.updateProject).toHaveBeenCalledWith('p3', { status: 'parked' })
  })

  it('dropping the current member asks first, then parks', async () => {
    const w = await mountGroup(makeRun())
    await drop(w, 'p2').trigger('click')
    await flushPromises()
    expect(h.updateProject).not.toHaveBeenCalled()
    expect(w.find('.dialog-stub').text()).toContain('This project is running now.')
    expect(w.find('.dialog-stub').text()).toContain('clears its plan and agents')
    await w.find('.dialog-confirm').trigger('click')
    await flushPromises()
    expect(h.updateProject).toHaveBeenCalledWith('p2', { status: 'parked' })
  })

  it('before the run starts a drop unlinks the member', async () => {
    const w = await mountGroup(
      makeRun({ status: 'pending', locked: false, current_index: 0, project_statuses: {} }),
    )
    await drop(w, 'p2').trigger('click')
    await flushPromises()
    expect(h.removeMember).toHaveBeenCalledWith('run-1', 'p2')
    expect(h.updateProject).not.toHaveBeenCalled()
  })
})

describe('FE-9835 dropped card', () => {
  const dropped = () => makeRun({ project_statuses: { p1: 'completed', p2: 'implementing', p3: 'detached' } })

  it('renders faded with only "Dropped from chain": no card, no buttons, no Review, no closeout', async () => {
    const w = await mountGroup(dropped())
    const members = w.findAll('[data-testid="chain-group-member"]')
    const card = members[2].find('[data-testid="chain-member-dropped"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain('Dropped from chain')
    expect(members[2].find('.card-stub').exists()).toBe(false)
    expect(members[2].findAll('button').length).toBe(0)
    expect(members[2].text()).not.toContain('Review')
    expect(w.find('.closeout-stub').exists()).toBe(false)
  })

  it('the dropped title carries the full name as its tooltip', async () => {
    const w = await mountGroup(dropped())
    expect(w.find('[data-testid="chain-member-dropped-title"]').attributes('title')).toBe(
      'Third project with a very long name',
    )
  })
})
