import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobsBoardCard from './JobsBoardCard.vue'

const vuetify = createVuetify()

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/projects/:projectId', name: 'ProjectLaunch', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
  ],
})

const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

function mountCard({ project, agents = [], now = Date.parse('2026-08-30T22:55:00Z'), headlessAllowed = null }) {
  return mount(JobsBoardCard, {
    props: { project, agents, now, headlessAllowed },
    global: {
      plugins: [vuetify, router],
      stubs: { 'v-tooltip': tooltipStub },
    },
  })
}

const needsInputProject = {
  id: '841b8643-b5ef-4cc5-9629-e49f33729355',
  taxonomy_alias: 'BE-6174',
  name: 'Flip the headless launch fence to default on for every tenant',
  status: 'active',
  implementation_launched_at: '2026-08-30T22:14:00Z',
}
const needsInputAgents = [
  { agent_id: 'a-or', job_id: 'j-or', agent_display_name: 'orchestrator', status: 'waiting', steps: { completed: 3, total: 4 }, messages_waiting_count: 1 },
  { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'blocked', steps: { completed: 2, total: 6 }, messages_waiting_count: 0 },
  { agent_id: 'a-te', job_id: 'j-te', agent_display_name: 'tester', status: 'complete', steps: { completed: 2, total: 2 }, messages_waiting_count: 0 },
]

describe('JobsBoardCard', () => {
  it('renders the taxonomy pill, title, and status pill for a Needs attention project', () => {
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents })
    expect(wrapper.find('[data-testid="jb-tax-pill"]').text()).toBe('BE-6174')
    expect(wrapper.find('[data-testid="jb-title"]').text()).toContain('headless launch fence')
    expect(wrapper.attributes('data-lifecycle')).toBe('Needs attention')
    expect(wrapper.find('[data-testid="jb-status-pill"]').text()).toBe('Implementer blocked')
  })

  it("the title's hover tooltip reveals the full name, never the project UUID", () => {
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents })
    expect(wrapper.find('[data-testid="jb-title-tooltip"]').text()).toBe(needsInputProject.name)
    expect(wrapper.find('[data-testid="jb-title-tooltip"]').text()).not.toContain(
      '841b8643-b5ef-4cc5-9629-e49f33729355',
    )
  })

  it('aggregates the project-level stat strip from its agents (mock BE-6174: 7/12, 3, 1, 41m)', () => {
    const now = Date.parse('2026-08-30T22:55:00Z')
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents, now })
    expect(wrapper.find('[data-testid="jb-stat-steps"]').text()).toContain('7')
    expect(wrapper.find('[data-testid="jb-stat-steps"]').text()).toContain('/12')
    expect(wrapper.find('[data-testid="jb-stat-agents"]').text()).toBe('3')
    expect(wrapper.find('[data-testid="jb-stat-waiting"]').text()).toBe('1')
    expect(wrapper.find('[data-testid="jb-stat-duration"]').text()).toBe('41m 0s')
  })

  it('renders one JobsBoardAgentRow per agent', () => {
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents })
    expect(wrapper.findAll('[data-testid="jb-agent-row"]')).toHaveLength(3)
  })

  const stagedProject = { id: 'p-staged', taxonomy_alias: 'INF-6176', name: 'Close the QA harness coverage gaps', status: 'active', staging_status: 'staging_complete', implementation_launched_at: null }
  const stagedAgents = [{ agent_display_name: 'orchestrator', status: 'staged' }]

  it('shows the HITL gate note on a Staged card when headless is OFF, linking to Tools -> Agents', () => {
    const staged = mountCard({ project: stagedProject, agents: stagedAgents, headlessAllowed: false })
    const note = staged.find('[data-testid="jb-gate-note"]')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('Your launch required')
    expect(note.text()).toContain('Tools → Agents')
    expect(staged.find('[data-testid="jb-gate-note-link"]').exists()).toBe(true)

    const implementing = mountCard({ project: needsInputProject, agents: needsInputAgents, headlessAllowed: false })
    expect(implementing.find('[data-testid="jb-gate-note"]').exists()).toBe(false)
  })

  it('does NOT show the gate note on a Staged card when headless is ON (FE-9549)', () => {
    const staged = mountCard({ project: stagedProject, agents: stagedAgents, headlessAllowed: true })
    expect(staged.find('[data-testid="jb-gate-note"]').exists()).toBe(false)
  })

  it('does NOT show the gate note while the headless setting is still unknown (FE-9549)', () => {
    const staged = mountCard({ project: stagedProject, agents: stagedAgents, headlessAllowed: null })
    expect(staged.find('[data-testid="jb-gate-note"]').exists()).toBe(false)
  })

  it('Staged: Implement is the primary action; no Open, no Review button', () => {
    const wrapper = mountCard({
      project: { id: 'p-staged', taxonomy_alias: 'INF-6176', name: 'X', status: 'active', staging_status: 'staging_complete', implementation_launched_at: null, execution_mode: 'multi_terminal', mission: 'Do it' },
      agents: [],
    })
    expect(wrapper.find('[data-testid="jbf-implement"]').classes()).toContain('jb-btn-primary')
    expect(wrapper.find('[data-testid="jb-btn-open"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-btn-review"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-btn-detail"]').exists()).toBe(true)
  })

  it('Needs attention / Implementing: Jobs detail present, no Open, no Review & close, no Implement button anywhere', () => {
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents })
    expect(wrapper.find('[data-testid="jb-btn-open"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-btn-review"]').exists()).toBe(false)
    const footerButtonText = wrapper.find('[data-testid="jb-btn-detail"]').text()
    expect(footerButtonText).not.toMatch(/\bImplement\b/)
  })

  it('Review: shows Review project (green) AND Jobs detail together', () => {
    const wrapper = mountCard({
      project: {
        id: 'p-review',
        taxonomy_alias: 'BE-6177',
        name: 'Archive refuses without a closeout entry',
        status: 'active',
        implementation_launched_at: '2026-08-30T22:29:00Z',
        completed_at: '2026-08-30T23:41:00Z',
      },
      agents: [
        { agent_display_name: 'orchestrator', status: 'closed', steps: { completed: 5, total: 5 } },
        { agent_display_name: 'implementer', status: 'complete', steps: { completed: 6, total: 6 } },
      ],
    })
    expect(wrapper.find('[data-testid="jb-status-pill"]').text()).toBe('Review')
    expect(wrapper.find('[data-testid="jb-btn-review"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="jb-btn-review"]').text()).toContain('Review project')
    expect(wrapper.find('[data-testid="jb-btn-detail"]').exists()).toBe(true)
  })

  it('the Hub button uses mdi-forum (same icon NavigationDrawer.vue uses for Message Hub), not a literal emoji', () => {
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents })
    const hubBtn = wrapper.find('[data-testid="jb-btn-hub"]')
    expect(hubBtn.text()).toContain('mdi-forum')
    expect(hubBtn.text()).not.toContain('💬')
  })

  it('the gate note icon uses an mdi icon, not a literal emoji', () => {
    const staged = mountCard({
      project: { id: 'p-staged', taxonomy_alias: 'INF-6176', name: 'X', status: 'active', staging_status: 'staging_complete', implementation_launched_at: null },
      agents: [{ agent_display_name: 'orchestrator', status: 'staged' }],
      headlessAllowed: false,
    })
    const note = staged.find('[data-testid="jb-gate-note"]')
    expect(note.text()).not.toContain('⏸')
    expect(note.find('.v-icon').exists()).toBe(true)
  })

  it('emits open-detail and open-hub on the corresponding buttons', async () => {
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents })
    await wrapper.find('[data-testid="jb-btn-detail"]').trigger('click')
    expect(wrapper.emitted('open-detail')?.[0]).toEqual([needsInputProject])

    await wrapper.find('[data-testid="jb-btn-hub"]').trigger('click')
    expect(wrapper.emitted('open-hub')?.[0]).toEqual([needsInputProject])
  })
})

describe('JobsBoardCard status words (BE-9655b)', () => {
  const launchedProject = {
    id: '6026affc-2f2c-487f-82bf-48bee9757f07',
    taxonomy_alias: 'BE-9655b',
    name: 'The board stops crying wolf',
    status: 'active',
    implementation_launched_at: '2026-08-30T22:14:00Z',
  }
  const orchestrator = {
    agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator',
    status: 'working', activity: 'working', steps: { completed: 1, total: 3 }, action_required_unread: 0,
  }

  it('renders a finished worker waiting for review as Holding, and the card as Implementing', () => {
    const holder = {
      agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer',
      status: 'silent', activity: 'holding', steps: { completed: 3, total: 3 }, action_required_unread: 0,
    }
    const wrapper = mountCard({ project: launchedProject, agents: [orchestrator, holder] })
    const statuses = wrapper.findAll('[data-testid="jb-agent-status"]').map((s) => s.text())
    expect(statuses).toContain('Holding')
    expect(statuses).not.toContain('Silent')
    expect(wrapper.find('[data-testid="jb-status-pill"]').text()).toBe('Implementing...')
  })

  it('names the owner and the count on Needs attention: "Orchestrator: answer 1"', async () => {
    const wrapper = mountCard({
      project: launchedProject,
      agents: [{ ...orchestrator, action_required_unread: 1 }],
    })
    expect(wrapper.attributes('data-lifecycle')).toBe('Needs attention')
    const pill = wrapper.find('[data-testid="jb-status-pill"]')
    expect(pill.text()).toBe('Orchestrator: answer 1')
    expect(pill.element.tagName).not.toBe('BUTTON')
    expect(wrapper.find('[data-testid="jb-status-pill-hint"]').text()).toMatch(/Hub thread/)
    await wrapper.find('[data-testid="jb-btn-hub"]').trigger('click')
    expect(wrapper.emitted('open-hub')?.[0]?.[0]).toEqual(launchedProject)
  })

  it('names the operator when an agent is waiting on a human decision', () => {
    const wrapper = mountCard({
      project: launchedProject,
      agents: [orchestrator, { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'awaiting_user' }],
    })
    expect(wrapper.find('[data-testid="jb-status-pill"]').text()).toBe('Your decision needed')
  })

  it('uses design tokens only (no hard-coded hex colors in the card)', async () => {
    const source = (await import('./JobsBoardCard.vue?raw')).default
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})

describe('JobsBoardCard fixes (FE-9678)', () => {
  const secProject = {
    id: 'p-sec',
    taxonomy_alias: 'SEC-9663',
    name: 'Gil can confirm his own add_person proposal',
    status: 'active',
    implementation_launched_at: '2026-08-30T22:14:00Z',
    project_type: { abbreviation: 'SEC', color: '#e05252' },
  }
  const implementingAgents = [
    { agent_id: 'a-a2', job_id: 'j-a2', agent_display_name: 'analyzer', status: 'complete', phase: 1, steps: { completed: 6, total: 6 } },
    { agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'working', steps: { completed: 5, total: 9 } },
  ]

  it('colours the taxonomy pill from the project type, the same helper the Projects list uses', () => {
    const wrapper = mountCard({ project: secProject, agents: implementingAgents })
    const pill = wrapper.find('[data-testid="jb-tax-pill"]')
    expect(pill.element.style.color).toBe('rgb(224, 82, 82)')
    expect(pill.element.style.backgroundColor).toMatch(/rgba\(224, 82, 82, 0\.1[45]/)
  })

  it('falls back to the default type colour when the row carries no type', () => {
    const wrapper = mountCard({ project: { ...secProject, project_type: null }, agents: implementingAgents })
    const pill = wrapper.find('[data-testid="jb-tax-pill"]')
    expect(pill.element.style.color).toBe('rgb(96, 125, 139)')
  })

  it('renders the orchestrator row first whatever order the store handed the agents', () => {
    const wrapper = mountCard({ project: secProject, agents: implementingAgents })
    const rows = wrapper.findAll('[data-testid="jb-agent-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].find('[data-testid="jb-agent-tooltip"]').text()).toMatch(/orchestrator/i)
  })

  it('the Needs attention reason pill is not a button, says what happened, and its tooltip says what to do', () => {
    const wrapper = mountCard({
      project: secProject,
      agents: [{ agent_id: 'a-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'silent', steps: { completed: 7, total: 9 } }],
    })
    const pill = wrapper.find('[data-testid="jb-status-pill"]')
    expect(pill.element.tagName).not.toBe('BUTTON')
    expect(pill.text()).toBe('Orchestrator silent')
    expect(wrapper.find('[data-testid="jb-status-pill-hint"]').text()).toMatch(/Nobody else can nudge the orchestrator/)
  })

  it('folds to one line that keeps the numbers and the primary action, and unfolds again', async () => {
    const wrapper = mountCard({ project: secProject, agents: implementingAgents })
    expect(wrapper.find('[data-testid="jb-summary"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-agents-list"]').exists()).toBe(true)

    await wrapper.find('[data-testid="jb-fold-btn"]').trigger('click')
    expect(wrapper.find('[data-testid="jb-agents-list"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-stat-steps"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-footer"]').exists()).toBe(false)
    const summary = wrapper.find('[data-testid="jb-summary"]')
    expect(summary.exists()).toBe(true)
    expect(summary.text()).toMatch(/11\s*\/\s*15/)
    expect(summary.findAll('[data-testid="jb-summary-badge"]')).toHaveLength(2)
    expect(summary.find('[data-testid="jb-summary-action"]').exists()).toBe(true)

    await wrapper.find('[data-testid="jb-fold-btn"]').trigger('click')
    expect(wrapper.find('[data-testid="jb-summary"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-agents-list"]').exists()).toBe(true)
  })

  it('under Compact density every card starts folded, a card that needs you too, with its attention edge (FE-9685)', () => {
    const quiet = mount(JobsBoardCard, {
      props: { project: secProject, agents: implementingAgents, now: Date.now(), density: 'compact' },
      global: { plugins: [vuetify, router], stubs: { 'v-tooltip': tooltipStub } },
    })
    expect(quiet.find('[data-testid="jb-summary"]').exists()).toBe(true)

    const loud = mount(JobsBoardCard, {
      props: { project: needsInputProject, agents: needsInputAgents, now: Date.now(), density: 'compact' },
      global: { plugins: [vuetify, router], stubs: { 'v-tooltip': tooltipStub } },
    })
    expect(loud.find('[data-testid="jb-summary"]').exists()).toBe(true)
    expect(loud.find('[data-testid="jobs-board-card"]').classes()).toContain('jb-card--attn')
  })

  it('under Detailed density a card that needs nobody starts open (FE-9685)', () => {
    const open = mount(JobsBoardCard, {
      props: { project: secProject, agents: implementingAgents, now: Date.now(), density: 'detailed' },
      global: { plugins: [vuetify, router], stubs: { 'v-tooltip': tooltipStub } },
    })
    expect(open.find('[data-testid="jb-summary"]').exists()).toBe(false)
    expect(open.find('[data-testid="jb-agents-list"]').exists()).toBe(true)
  })

  it('a card that needs you, folded by hand, keeps an attention edge so a folded board is still a to-do list', async () => {
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents })
    await wrapper.find('[data-testid="jb-fold-btn"]').trigger('click')
    expect(wrapper.find('[data-testid="jobs-board-card"]').classes()).toContain('jb-card--attn')
  })
})

describe('JobsBoardCard staging layout (FE-9679)', () => {
  const base = {
    id: 'p-stage',
    taxonomy_alias: 'FE-9679',
    name: 'Staging joins the board',
    status: 'active',
    description: 'Every activated project gets a blocky card with description, mission and crew.',
    implementation_launched_at: null,
    execution_mode: null,
    mission: '',
    created_at: '2026-09-26T09:12:00Z',
  }

  it('Activated: staging stats, the description, an empty mission; the (empty) agent pane already shows', () => {
    const wrapper = mountCard({ project: { ...base, staging_status: null } })
    for (const k of ['mode', 'harness', 'phases']) {
      expect(wrapper.find(`[data-testid="jb-stat-${k}"]`).exists()).toBe(true)
    }
    expect(wrapper.find('[data-testid="jb-stat-crew"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-stat-steps"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-stat-mode"]').text()).toMatch(/not picked/i)
    expect(wrapper.find('[data-testid="jb-row-description"]').text()).toContain('blocky card')
    expect(wrapper.find('[data-testid="jb-row-mission"]').text()).toMatch(/No mission yet/)
    expect(wrapper.find('[data-testid="jb-row-crew"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-agents-list"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="jb-agent-row"]')).toHaveLength(0)
  })

  it('Planning: the mission row shows the orchestrator writing, live', () => {
    const wrapper = mountCard({
      project: { ...base, id: 'p-planning', staging_status: 'staging', execution_mode: 'subagent' },
      agents: [{ agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'working' }],
    })
    expect(wrapper.find('[data-testid="jb-mission-state"]').attributes('data-state')).toBe('writing')
    expect(wrapper.find('[data-testid="jb-row-mission"]').text()).toMatch(/Orchestrator writing/)
    expect(wrapper.find('[data-testid="jb-stat-mode"]').text()).toMatch(/Subagent/)
  })

  it('Staged: the written mission on its row, and one agent-pane row per agent', () => {
    const wrapper = mountCard({
      project: {
        ...base,
        id: 'p-staged',
        staging_status: 'staging_complete',
        execution_mode: 'multi_terminal',
        mission: 'Phase 1: build the panels.\nPhase 2: test them.',
      },
      agents: [
        { agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'complete' },
        { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'pending', phase: 1 },
        { agent_id: 'a-te', job_id: 'j-te', agent_display_name: 'tester', status: 'pending', phase: 2 },
      ],
    })
    expect(wrapper.find('[data-testid="jb-mission-state"]').attributes('data-state')).toBe('written')
    expect(wrapper.find('[data-testid="jb-row-mission"]').text()).toContain('build the panels')
    expect(wrapper.findAll('[data-testid="jb-agent-row"]')).toHaveLength(3)
    expect(wrapper.find('[data-testid="jb-stat-phases"]').text()).toContain('2')
  })

  it('the description pencil asks the board to open the one project edit dialog', async () => {
    const wrapper = mountCard({ project: { ...base, staging_status: null } })
    await wrapper.find('[data-testid="jb-edit-description"]').trigger('click')
    expect(wrapper.emitted('edit-description')?.[0]?.[0]).toMatchObject({ id: 'p-stage' })
  })

  it('a launched card keeps the implementation layout (steps, agent rows)', () => {
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents })
    expect(wrapper.find('[data-testid="jb-stat-steps"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="jb-stat-mode"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-agents-list"]').exists()).toBe(true)
  })
})
