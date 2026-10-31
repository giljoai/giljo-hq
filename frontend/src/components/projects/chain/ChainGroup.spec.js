import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const h = vi.hoisted(() => ({
  getProject: vi.fn(),
  getDefault: vi.fn(),
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
    settings: { getExecutionModeDefault: (...a) => h.getDefault(...a) },
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
  p1: { id: 'p1', name: 'First', taxonomy_alias: 'FE-0001', status: 'completed', product_id: 'prod-1' },
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
  JobsBoardCard: {
    props: ['project', 'agents', 'showStaging', 'chainCtx'],
    template: `<div class="card-stub" :data-project="project.id" :data-show-staging="String(showStaging)"
      :data-chain="chainCtx ? 'yes' : 'no'" :data-description="project.description">{{ project.name }}</div>`,
  },
  CloseoutModal: {
    props: ['show', 'projectId', 'suppressNavigation'],
    emits: ['close', 'closeout'],
    template: `<div v-if="show" class="closeout-stub" :data-project="projectId">
      <button class="closeout-done" @click="$emit('closeout')">done</button></div>`,
  },
  BaseDialog: {
    props: ['modelValue', 'title', 'confirmLabel'],
    emits: ['confirm', 'cancel', 'update:modelValue'],
    template: `<div v-if="modelValue" class="dialog-stub" :data-title="title">
      <div class="dialog-body"><slot /></div>
      <button class="dialog-confirm" @click="$emit('confirm')">go</button></div>`,
  },
  EmptyState: { props: ['title'], template: '<div class="empty-stub">{{ title }}</div>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
  'v-menu': { template: '<div class="menu-stub"><slot name="activator" :props="{}" /><slot /></div>' },
}

let pinia
let store

function seed(run) {
  store._testSeedRuns([run])
}

async function mountGroup(props = {}) {
  const wrapper = mount(ChainGroup, {
    props: {
      runId: 'run-1',
      agentsByProject: {
        p1: [{ job_id: 'j1' }],
        p2: [{ job_id: 'j2' }, { job_id: 'j3' }],
        p3: [],
      },
      now: Date.parse('2026-09-24T20:00:00Z'),
      ...props,
    },
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
  h.getDefault.mockResolvedValue({ data: { execution_mode_default: 'ask' } })
  h.listRuns.mockResolvedValue({ data: [] })
  h.copy.mockResolvedValue(true)
  h.launch.mockResolvedValue({ data: {} })
  h.stopRun.mockResolvedValue({ data: makeRun({ status: 'cancelled' }) })
  h.deactivateRun.mockResolvedValue({ data: {} })
  h.chainStaging.mockResolvedValue({ data: { prompt: 'STAGING PROMPT' } })
  h.chainImplementation.mockResolvedValue({ data: { prompt: 'MASTER PROMPT' } })
  h.chainMemberFallback.mockResolvedValue({ data: { prompt: 'FALLBACK PROMPT' } })
  h.markReviewed.mockResolvedValue({ data: makeRun({ reviewed_project_ids: ['p1'] }) })
  h.updateRun.mockImplementation(async (id, patch) => ({ data: { ...makeRun(), ...patch } }))
  await router.push('/')
})

describe('ChainGroup header (FE-9655d)', () => {
  it('shows the chain name, the step counter and the chain goal', async () => {
    seed(makeRun())
    const w = await mountGroup()
    expect(w.find('[data-testid="chain-group-name"]').text()).toBe('One Jobs board')
    expect(w.find('[data-testid="chain-group-counter"]').text()).toBe('Step 2 of 3')
    expect(w.find('[data-testid="chain-mission-window"]').text()).toContain('Fold chains into the board.')
    expect(w.find('[data-testid="chain-mission-window"]').text()).toContain('Chain goal')
  })

  it('falls back to the member aliases when the goal has no heading', async () => {
    seed(makeRun({ chain_mission: '' }))
    const w = await mountGroup()
    expect(w.find('[data-testid="chain-group-name"]').text()).toBe('FE-0001 → FE-0002 → FE-0003')
  })

  it('the control area sits under the title, above the goal and every member (operator ruling 2026-10-19)', async () => {
    seed(makeRun({ status: 'pending', locked: false, current_index: 0, project_statuses: { p1: 'pending', p2: 'pending', p3: 'pending' } }))
    const w = await mountGroup()
    const area = w.find('[data-testid="staging-control-area"]')
    expect(area.exists()).toBe(true)
    const name = w.find('[data-testid="chain-group-name"]').element
    const goal = w.find('[data-testid="chain-mission-window"]').element
    const firstMember = w.findAll('[data-testid="chain-group-member"]').at(0).element
    expect(name.compareDocumentPosition(area.element) & 4).toBe(4)
    expect(goal.compareDocumentPosition(area.element) & 2).toBe(2)
    expect(firstMember.compareDocumentPosition(area.element) & 2).toBe(2)
    for (const id of ['radio-multi-terminal', 'stage-chain-btn']) {
      expect(area.find(`[data-testid="${id}"]`).exists(), id).toBe(true)
    }
  })

  it('puts the Conductor Generated badge on its own line directly above the goal box', async () => {
    seed(makeRun())
    const w = await mountGroup()
    const tag = w.find('[data-testid="chain-mission-tag"]')
    const box = w.find('[data-testid="chain-mission-window"]')
    expect(tag.exists()).toBe(true)
    expect(box.find('[data-testid="chain-mission-tag"]').exists()).toBe(false)
    expect(box.text()).not.toContain('Conductor Generated')
    expect(tag.element.parentElement.nextElementSibling).toBe(box.element)
  })
})

describe('ChainGroup control area (FE-9749)', () => {
  const UNSTAGED = { status: 'pending', locked: false, current_index: 0, project_statuses: { p1: 'pending', p2: 'pending', p3: 'pending' } }
  const STAGED = { status: 'pending', current_index: 0, project_statuses: { p1: 'staged', p2: 'staged', p3: 'staged' } }
  const WAITING_AGENTS = { p1: [{ job_id: 'j1', status: 'waiting' }], p2: [], p3: [] }

  it('before staging with no mode: Stage chain waits for a mode, nothing is sent', async () => {
    seed(makeRun({ ...UNSTAGED, execution_mode: null }))
    const w = await mountGroup()
    const stage = w.find('[data-testid="stage-chain-btn"]')
    expect(stage.text()).toBe('Stage chain')
    expect(stage.attributes('aria-disabled')).toBe('true')
    expect(w.find('[data-testid="sca-mode-reason"]').text()).toBe('Pick a mode first')
    await stage.trigger('click')
    await flushPromises()
    expect(h.updateRun).not.toHaveBeenCalled()
    expect(h.chainStaging).not.toHaveBeenCalled()
  })

  it('before staging with a mode: Stage chain is the filled step and locks the run through the store', async () => {
    seed(makeRun(UNSTAGED))
    const w = await mountGroup()
    expect(w.find('[data-testid="radio-multi-terminal"]').attributes('aria-pressed')).toBe('true')
    expect(w.find('[data-testid="chain-group-mode-tag"]').exists()).toBe(false)
    const stage = w.find('[data-testid="stage-chain-btn"]')
    expect(stage.classes()).toContain('jb-btn-primary')
    await stage.trigger('click')
    await flushPromises()
    expect(h.updateRun).toHaveBeenCalledWith('run-1', { locked: true })
    expect(h.chainStaging).toHaveBeenCalledWith('run-1')
    expect(h.copy).toHaveBeenCalledWith('STAGING PROMPT')
  })

  it('the account default is preselected on an unstaged chain', async () => {
    h.getDefault.mockResolvedValue({ data: { execution_mode_default: 'subagent' } })
    seed(makeRun({ ...UNSTAGED, execution_mode: null }))
    const w = await mountGroup()
    expect(w.find('[data-testid="radio-subagent"]').attributes('aria-pressed')).toBe('true')
    expect(w.find('[data-testid="stage-chain-btn"]').classes()).toContain('jb-btn-primary')
  })

  it.each(['multi_terminal', 'subagent'])(
    'staged %s chain: Implement chain is filled, opens the head gate and copies the chain prompt, on the board',
    async (mode) => {
      seed(makeRun({ ...STAGED, execution_mode: mode }))
      const w = await mountGroup()
      expect(w.find('[data-testid="chain-group-mode-tag"]').exists()).toBe(true)
      expect(w.find('[data-testid="stage-chain-btn"]').text()).toBe('Unstage chain')
      expect(w.find('[data-testid="stage-chain-btn"]').classes()).toContain('jb-btn-secondary')
      const implement = w.find('[data-testid="implement-chain-btn"]')
      expect(implement.classes()).toContain('jb-btn-primary')
      await implement.trigger('click')
      await flushPromises()
      expect(h.launch).toHaveBeenCalledWith('p1')
      expect(h.chainImplementation).toHaveBeenCalledWith('run-1')
      expect(h.copy).toHaveBeenCalledWith('MASTER PROMPT')
      expect(h.toast).toHaveBeenCalledWith({ message: 'Chain prompt copied. Paste it into your conductor session.', type: 'success' })
      expect(router.currentRoute.value.name).toBe('Root')
    },
  )

  it('no separate copy-master-prompt link remains', async () => {
    seed(makeRun(STAGED))
    const w = await mountGroup()
    expect(w.find('[data-testid="chain-group-copy-master"]').exists()).toBe(false)
  })

  it('waiting for pickup: Copy chain prompt filled, Stop chain outlined, Deactivate chain a text link', async () => {
    seed(makeRun({ current_index: 0, project_statuses: { p1: 'implementing', p2: 'pending', p3: 'pending' } }))
    const w = await mountGroup({ agentsByProject: WAITING_AGENTS })
    expect(w.find('[data-testid="staging-control-area"]').attributes('data-phase')).toBe('pickup')
    expect(w.find('[data-testid="sca-pickup-hint"]').text()).toBe('No agent has picked this up yet')
    const copy = w.find('[data-testid="sca-copy-prompt"]')
    expect(copy.text()).toContain('Copy chain prompt')
    expect(w.find('[data-testid="stop-chain-btn"]').text()).toContain('Stop chain')
    expect(w.find('[data-testid="chain-group-deactivate"]').classes()).toContain('sca-link')
    await copy.trigger('click')
    await flushPromises()
    expect(h.chainImplementation).toHaveBeenCalledWith('run-1')
    expect(h.copy).toHaveBeenCalledWith('MASTER PROMPT')
    expect(h.launch).not.toHaveBeenCalled()
  })

  it('BE-9813: a conductor that picked the chain up makes it running while every member still waits', async () => {
    seed(makeRun({ current_index: 0, conductor_status: 'working', project_statuses: { p1: 'implementing', p2: 'pending', p3: 'pending' } }))
    const w = await mountGroup({ agentsByProject: WAITING_AGENTS })
    expect(w.find('[data-testid="staging-control-area"]').exists()).toBe(false)
    expect(w.find('[data-testid="sca-pickup-hint"]').exists()).toBe(false)
    expect(w.find('[data-testid="chain-group-header"]').find('[data-testid="stop-chain-btn"]').exists()).toBe(true)
  })

  it('BE-9813: a conductor still waiting leaves the chain waiting for pickup', async () => {
    seed(makeRun({ current_index: 0, conductor_status: 'waiting', project_statuses: { p1: 'implementing', p2: 'pending', p3: 'pending' } }))
    const w = await mountGroup({ agentsByProject: WAITING_AGENTS })
    expect(w.find('[data-testid="staging-control-area"]').attributes('data-phase')).toBe('pickup')
  })

  it('running (FE-9793): Stop chain sits on the header row, confirms, then posts the stop path without leaving the board', async () => {
    seed(makeRun())
    const w = await mountGroup({ agentsByProject: { p1: [{ status: 'complete' }], p2: [{ status: 'working' }], p3: [] } })
    expect(w.find('[data-testid="staging-control-area"]').exists()).toBe(false)
    expect(w.find('[data-testid="implement-chain-btn"]').exists()).toBe(false)
    expect(w.find('[data-testid="chain-compact-controls"]').exists()).toBe(false)
    expect(w.find('[data-testid="chain-more-menu"]').exists()).toBe(false)
    const header = w.find('[data-testid="chain-group-header"]')
    const stop = header.find('[data-testid="stop-chain-btn"]')
    expect(stop.exists()).toBe(true)
    expect(stop.text()).toContain('Stop chain')
    expect(stop.classes()).not.toContain('csc-btn--icon')
    const row = header.find('[data-testid="chain-mission-row"]')
    const tag = row.find('[data-testid="chain-mission-tag"]')
    const actions = row.find('[data-testid="chain-header-actions"]')
    expect(tag.exists()).toBe(true)
    expect(actions.exists()).toBe(true)
    expect(tag.element.compareDocumentPosition(actions.element) & 4).toBe(4)
    await stop.trigger('click')
    const dialog = w.find('.dialog-stub[data-title="Stop chain?"]')
    expect(dialog.exists()).toBe(true)
    await dialog.find('.dialog-confirm').trigger('click')
    await flushPromises()
    expect(h.stopRun).toHaveBeenCalledWith('run-1')
    expect(router.currentRoute.value.name).toBe('Root')
  })

  it('running (FE-9793): Deactivate chain sits on the header row after Stop chain, names the agents it removes, then posts the rewind', async () => {
    seed(makeRun())
    const w = await mountGroup()
    expect(w.find('[data-testid="chain-more-menu"]').exists()).toBe(false)
    const header = w.find('[data-testid="chain-group-header"]')
    const deactivate = header.find('[data-testid="chain-header-actions"] [data-testid="chain-group-deactivate"]')
    expect(deactivate.exists()).toBe(true)
    expect(deactivate.text()).toBe('Deactivate chain')
    expect(w.findAll('[data-testid="chain-group-deactivate"]')).toHaveLength(1)
    const stop = header.find('[data-testid="stop-chain-btn"]')
    expect(stop.element.compareDocumentPosition(deactivate.element) & 4).toBe(4)
    await deactivate.trigger('click')
    const dialog = w.find('.dialog-stub[data-title="Deactivate chain?"]')
    expect(dialog.text()).toContain('3 agents')
    expect(dialog.text()).toContain('3 linked projects')
    expect(h.deactivateRun).not.toHaveBeenCalled()
    await dialog.find('.dialog-confirm').trigger('click')
    await flushPromises()
    expect(h.deactivateRun).toHaveBeenCalledWith('run-1')
  })
})

describe('ChainGroup members (FE-9655d)', () => {
  it('renders members in resolved order with step numbers; only the current member is lit', async () => {
    seed(makeRun())
    const w = await mountGroup()
    const members = w.findAll('[data-testid="chain-group-member"]')
    expect(members.map((m) => m.attributes('data-project-id'))).toEqual(['p1', 'p2', 'p3'])
    expect(members.map((m) => m.find('[data-testid="chain-member-step"]').text())).toEqual(['Step 1', 'Step 2', 'Step 3'])
    expect(members.map((m) => m.attributes('data-member-state'))).toEqual(['done', 'current', 'waiting'])
    expect(members[1].classes()).toContain('cg-member--current')
    expect(members[0].classes()).not.toContain('cg-member--current')
    expect(members.some((m) => m.classes().includes('cg-member--dim'))).toBe(false)
  })

  it('never desaturates a non-current member (no saturate filter in the group styles)', async () => {
    const source = (await import('./ChainGroup.vue?raw')).default
    expect(source).not.toMatch(/saturate\(/)
    expect(source).not.toMatch(/cg-member--dim/)
  })

  it('gives every grid child min-width: 0 and a column floor that fits the frame', async () => {
    const source = (await import('./ChainGroup.vue?raw')).default
    expect(source).toMatch(/\.cg-member\s*\{[^}]*min-width:\s*0/)
    expect(source).toMatch(/\.cg-members\s*\{[^}]*minmax\(min\(100%,\s*\d+px\)/)
  })

  it('V1: a member is a flex column so the card takes the room left under the label', async () => {
    const source = (await import('./ChainGroup.vue?raw')).default
    const member = source.match(/\.cg-member\s*\{([^}]*)\}/)?.[1] || ''
    expect(member).toMatch(/display:\s*flex/)
    expect(member).toMatch(/flex-direction:\s*column/)
  })

  it('V2: a member known only as a trimmed list row is fetched in full, so its card has the description', async () => {
    const { useProjectStore } = await import('@/stores/projects')
    const projectStore = useProjectStore()
    projectStore.projects = Object.values(PROJECTS).map((p) => ({ ...p }))
    h.getProject.mockImplementation(async (id) => ({ data: { ...PROJECTS[id], description: `Full text of ${id}` } }))
    seed(makeRun())
    const w = await mountGroup()
    expect(h.getProject).toHaveBeenCalledTimes(3)
    const cards = w.findAll('.card-stub')
    expect(cards.map((c) => c.attributes('data-description'))).toEqual(['Full text of p1', 'Full text of p2', 'Full text of p3'])
  })

  it('labels the current step and what the others wait for', async () => {
    seed(makeRun())
    const w = await mountGroup()
    const members = w.findAll('[data-testid="chain-group-member"]')
    expect(members[1].find('[data-testid="chain-member-state"]').text()).toMatch(/current/i)
    expect(members[2].find('[data-testid="chain-member-state"]').text()).toMatch(/waiting for step 2/i)
    expect(members[0].find('[data-testid="chain-member-state"]').text()).toMatch(/done/i)
  })

  it('member cards drop the staging buttons and carry the chain context', async () => {
    seed(makeRun())
    const w = await mountGroup()
    const cards = w.findAll('.card-stub')
    expect(cards).toHaveLength(3)
    expect(cards.every((c) => c.attributes('data-show-staging') === 'false')).toBe(true)
    expect(cards.every((c) => c.attributes('data-chain') === 'yes')).toBe(true)
  })

  it('FE-9749: every member offers "Run this project alone (recovery)" in its more-menu; it copies that member only', async () => {
    seed(makeRun())
    const w = await mountGroup()
    for (const pid of ['p1', 'p2', 'p3']) {
      expect(w.find(`[data-testid="chain-member-menu-${pid}"]`).exists(), pid).toBe(true)
    }
    expect(w.find('[data-testid="chain-member-fallback-p2"]').text()).toBe('Run this project alone (recovery)')
    expect(w.find('.cg-fallback').exists()).toBe(false)
    await w.find('[data-testid="chain-member-fallback-p2"]').trigger('click')
    await flushPromises()
    expect(h.chainMemberFallback).toHaveBeenCalledWith('p2')
    expect(h.copy).toHaveBeenCalledWith('FALLBACK PROMPT')
    expect(h.launch).not.toHaveBeenCalled()
    expect(h.updateRun).not.toHaveBeenCalled()
  })

  it('FE-9749: a status line instead of a start button: who runs it, or what it waits for', async () => {
    seed(makeRun())
    const w = await mountGroup()
    const members = w.findAll('[data-testid="chain-group-member"]')
    expect(members[0].find('[data-testid="chain-member-status"]').exists()).toBe(false)
    expect(members[1].find('[data-testid="chain-member-status"]').text()).toBe('Run by the conductor')
    expect(members[2].find('[data-testid="chain-member-status"]').text()).toBe('Starts after step 2 is merged')
  })

  it('BE-9833: a detached member reads dropped and shows no start line', async () => {
    seed(makeRun({ current_index: 1, project_statuses: { p1: 'completed', p2: 'implementing', p3: 'detached' } }))
    const w = await mountGroup()
    const members = w.findAll('[data-testid="chain-group-member"]')
    expect(members[2].find('[data-testid="chain-member-state"]').text()).toContain('dropped')
    expect(members[2].find('[data-testid="chain-member-status"]').exists()).toBe(false)
  })

  it('an unstaged chain offers no fallback prompt yet (members have no orchestrator)', async () => {
    seed(makeRun({ status: 'pending', locked: false, current_index: 0, project_statuses: {} }))
    const w = await mountGroup()
    expect(w.find('[data-testid="chain-member-fallback-p1"]').exists()).toBe(false)
  })

  it('marks the group highlighted when the board was opened for this run', async () => {
    seed(makeRun())
    const w = await mountGroup({ highlighted: true })
    expect(w.find('[data-testid="chain-group"]').classes()).toContain('cg--highlight')
    expect(w.find('[data-testid="chain-group"]').attributes('data-run-id')).toBe('run-1')
  })
})

describe('ChainGroup forwards every member-card event (FE-9681 B1)', () => {
  const emittingCard = {
    props: ['project', 'agents', 'showStaging', 'chainCtx'],
    template: `<div class="card-stub" :data-project="project.id">
      <button class="e-edit" @click="$emit('edit-description', project)">edit</button>
      <button class="e-mission" @click="$emit('agent-mission-edit', { agent_id: 'a-1' })">mission</button>
      <button class="e-steps" @click="$emit('steps', { agent_id: 'a-1' })">steps</button>
      <button class="e-role" @click="$emit('agent-role', { agent_id: 'a-1' })">role</button>
    </div>`,
  }

  it('re-emits edit-description, agent-mission-edit and steps with their payloads', async () => {
    seed(makeRun({ status: 'running', current_index: 0 }))
    const wrapper = mount(ChainGroup, {
      props: { runId: 'run-1', agentsByProject: {}, now: Date.parse('2026-09-24T20:00:00Z') },
      global: { plugins: [pinia, router], stubs: { ...stubs, JobsBoardCard: emittingCard } },
    })
    await flushPromises()
    const first = wrapper.find('.card-stub')
    expect(first.exists()).toBe(true)

    await first.find('.e-edit').trigger('click')
    await first.find('.e-mission').trigger('click')
    await first.find('.e-steps').trigger('click')
    await first.find('.e-role').trigger('click')

    expect(wrapper.emitted('edit-description')?.[0]?.[0]).toMatchObject({ id: first.attributes('data-project') })
    expect(wrapper.emitted('agent-mission-edit')?.[0]?.[0]).toEqual({ agent_id: 'a-1' })
    expect(wrapper.emitted('steps')?.[0]?.[0]).toEqual({ agent_id: 'a-1' })
    expect(wrapper.emitted('agent-role')?.[0]?.[0]).toEqual({ agent_id: 'a-1' })
  })
})
