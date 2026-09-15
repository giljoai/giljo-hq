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
  it('renders the taxonomy pill, title, and status pill for a Needs Input project', () => {
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents })
    expect(wrapper.find('[data-testid="jb-tax-pill"]').text()).toBe('BE-6174')
    expect(wrapper.find('[data-testid="jb-title"]').text()).toContain('headless launch fence')
    expect(wrapper.find('[data-testid="jb-status-pill"]').text()).toBe('Needs Input')
  })

  it("the title's hover tooltip reveals the project UUID", () => {
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents })
    expect(wrapper.find('[data-testid="jb-title-tooltip"]').text()).toContain(
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

  it('Staged: Open is the primary action; no Review & close button', () => {
    const wrapper = mountCard({
      project: { id: 'p-staged', taxonomy_alias: 'INF-6176', name: 'X', status: 'active', staging_status: 'staging_complete', implementation_launched_at: null },
      agents: [],
    })
    expect(wrapper.find('[data-testid="jb-btn-open"]').classes()).toContain('jb-btn-primary')
    expect(wrapper.find('[data-testid="jb-btn-review"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-btn-detail"]').exists()).toBe(true)
  })

  it('Needs Input / Implementing: Open is ghost, Jobs detail present, no Review & close, no Implement button anywhere', () => {
    const wrapper = mountCard({ project: needsInputProject, agents: needsInputAgents })
    expect(wrapper.find('[data-testid="jb-btn-open"]').classes()).toContain('jb-btn-ghost')
    expect(wrapper.find('[data-testid="jb-btn-review"]').exists()).toBe(false)
    const footerButtonText = wrapper.find('[data-testid="jb-btn-open"]').text()
      + wrapper.find('[data-testid="jb-btn-detail"]').text()
    expect(footerButtonText).not.toMatch(/\bImplement\b/)
  })

  it('Review: shows Review & close (green) AND Jobs detail together', () => {
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
    expect(wrapper.find('[data-testid="jb-btn-review"]').text()).toContain('Review & close')
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
