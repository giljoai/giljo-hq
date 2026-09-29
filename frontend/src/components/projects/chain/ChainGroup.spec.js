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

  it('before staging: mode pills and Stage chain, which locks the run through the store', async () => {
    seed(makeRun({ status: 'pending', locked: false, current_index: 0, project_statuses: { p1: 'pending', p2: 'pending', p3: 'pending' } }))
    const w = await mountGroup()
    expect(w.find('[data-testid="radio-multi-terminal"]').exists()).toBe(true)
    expect(w.find('[data-testid="chain-group-mode-tag"]').exists()).toBe(false)
    const stage = w.find('[data-testid="stage-chain-btn"]')
    expect(stage.text()).toBe('Stage Chain')
    await stage.trigger('click')
    await flushPromises()
    expect(h.updateRun).toHaveBeenCalledWith('run-1', { locked: true })
    expect(h.chainStaging).toHaveBeenCalledWith('run-1')
    expect(h.copy).toHaveBeenCalledWith('STAGING PROMPT')
  })

  it('staged: Implement starts the head member and stays on the board', async () => {
    seed(makeRun({ status: 'pending', current_index: 0, project_statuses: { p1: 'staged', p2: 'staged', p3: 'staged' } }))
    const w = await mountGroup()
    expect(w.find('[data-testid="chain-group-mode-tag"]').text()).toContain('Multi-Terminal')
    expect(w.find('[data-testid="stage-chain-btn"]').text()).toBe('Unstage Chain')
    await w.find('[data-testid="implement-chain-btn"]').trigger('click')
    await flushPromises()
    expect(h.launch).toHaveBeenCalledWith('p1')
    expect(router.currentRoute.value.name).toBe('Root')
  })

  it('staged multi-terminal chain keeps the copy-master-prompt link', async () => {
    seed(makeRun({ status: 'pending', current_index: 0, project_statuses: { p1: 'staged', p2: 'staged', p3: 'staged' } }))
    const w = await mountGroup()
    await w.find('[data-testid="chain-group-copy-master"]').trigger('click')
    await flushPromises()
    expect(h.chainImplementation).toHaveBeenCalledWith('run-1')
    expect(h.copy).toHaveBeenCalledWith('MASTER PROMPT')
  })

  it('subagent chains do not offer the master prompt link', async () => {
    seed(makeRun({ status: 'pending', execution_mode: 'subagent', current_index: 0, project_statuses: { p1: 'staged', p2: 'staged', p3: 'staged' } }))
    const w = await mountGroup()
    expect(w.find('[data-testid="chain-group-copy-master"]').exists()).toBe(false)
  })

  it('running: Stop chain confirms, then posts the stop path without leaving the board', async () => {
    seed(makeRun())
    const w = await mountGroup()
    expect(w.find('[data-testid="implement-chain-btn"]').exists()).toBe(false)
    await w.find('[data-testid="stop-chain-btn"]').trigger('click')
    const dialog = w.find('.dialog-stub[data-title="Stop chain?"]')
    expect(dialog.exists()).toBe(true)
    await dialog.find('.dialog-confirm').trigger('click')
    await flushPromises()
    expect(h.stopRun).toHaveBeenCalledWith('run-1')
    expect(router.currentRoute.value.name).toBe('Root')
  })

  it('Deactivate chain names the agents it removes, then posts the rewind', async () => {
    seed(makeRun())
    const w = await mountGroup()
    await w.find('[data-testid="chain-group-deactivate"]').trigger('click')
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

  it('a finished member shows its Review link, which reviews in place without navigating', async () => {
    seed(makeRun())
    const w = await mountGroup()
    const review = w.find('[data-testid="chain-member-review-p1"]')
    expect(review.exists()).toBe(true)
    expect(w.find('[data-testid="chain-member-review-p2"]').exists()).toBe(false)
    await review.trigger('click')
    const modal = w.find('.closeout-stub')
    expect(modal.attributes('data-project')).toBe('p1')
    await modal.find('.closeout-done').trigger('click')
    await flushPromises()
    expect(h.markReviewed).toHaveBeenCalledWith('run-1', 'p1')
    expect(store.isReviewed('run-1', 'p1')).toBe(true)
    expect(router.currentRoute.value.name).toBe('Root')
  })

  it('the recycle control copies the fallback prompt for that member only', async () => {
    seed(makeRun())
    const w = await mountGroup()
    expect(w.find('[data-testid="chain-member-fallback-p2"]').attributes('aria-label')).toMatch(
      /^Re-issue the latest launch prompt after a disconnect or reboot/,
    )
    await w.find('[data-testid="chain-member-fallback-p2"]').trigger('click')
    await flushPromises()
    expect(h.chainMemberFallback).toHaveBeenCalledWith('p2')
    expect(h.copy).toHaveBeenCalledWith('FALLBACK PROMPT')
    expect(h.launch).not.toHaveBeenCalled()
    expect(h.updateRun).not.toHaveBeenCalled()
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
      <button class="e-review" @click="$emit('review', project)">review</button>
      <button class="e-role" @click="$emit('agent-role', { agent_id: 'a-1' })">role</button>
    </div>`,
  }

  it('re-emits edit-description, agent-mission-edit, steps and review with their payloads', async () => {
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
    await first.find('.e-review').trigger('click')
    await first.find('.e-role').trigger('click')

    expect(wrapper.emitted('edit-description')?.[0]?.[0]).toMatchObject({ id: first.attributes('data-project') })
    expect(wrapper.emitted('agent-mission-edit')?.[0]?.[0]).toEqual({ agent_id: 'a-1' })
    expect(wrapper.emitted('steps')?.[0]?.[0]).toEqual({ agent_id: 'a-1' })
    expect(wrapper.emitted('review')?.[0]?.[0]).toMatchObject({ id: first.attributes('data-project') })
    expect(wrapper.emitted('agent-role')?.[0]?.[0]).toEqual({ agent_id: 'a-1' })
  })
})
