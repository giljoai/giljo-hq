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
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
  ],
})

const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

function mountCard(project, agents = [], props = {}) {
  return mount(JobsBoardCard, {
    props: { project, agents, now: Date.parse('2026-10-10T06:00:00Z'), ...props },
    global: {
      plugins: [vuetify, router],
      stubs: { 'v-tooltip': tooltipStub },
    },
  })
}

const HINT = 'This project was completed without the HQ staging flow, so there are no agent, step or time records.'

const emptyDone = {
  id: 'p-empty',
  taxonomy_alias: 'FE-9745',
  name: 'Closed without staging',
  status: 'completed',
  review_pending: true,
  mission: '',
  description: 'Fixed directly in a session.',
  staging_status: null,
  implementation_launched_at: null,
  completed_at: '2026-10-08T12:00:00Z',
  agent_count: 0,
}

const orch = { agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'complete' }
const impl = { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'complete', phase: 1 }

describe('JobsBoardCard, a completed project with no agent run (FE-9763)', () => {
  it('replaces the empty stat strip with "No agent run recorded" and its hover/focus text', () => {
    const wrapper = mountCard(emptyDone)
    const line = wrapper.find('[data-testid="jb-empty-run"]')
    expect(line.exists()).toBe(true)
    expect(line.text()).toContain('No agent run recorded')
    expect(line.text()).toContain(HINT)
    expect(line.find('[tabindex="0"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="jb-stat-steps"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-stat-duration"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-meta"]').text()).not.toMatch(/---/)
  })

  it('never says "Press Stage"; with no closeout the mission line reads "No mission recorded."', async () => {
    const wrapper = mountCard(emptyDone)
    expect(wrapper.find('[data-testid="jb-row-mission"]').text()).toContain('No mission recorded.')
    await wrapper.find('[data-testid="jb-details-btn"]').trigger('click')
    expect(wrapper.find('[data-testid="jb-drawer-mission"]').text()).toContain('No mission recorded.')
    expect(wrapper.text()).not.toMatch(/Press Stage/)
  })

  it('with a closeout summary the mission line reads "Closeout: ..." with the full text on hover', async () => {
    const summary = 'Shipped the export retry.\nThree attempts with backoff, covered by a service test.'
    const wrapper = mountCard({ ...emptyDone, closeout_summary: summary })
    const row = wrapper.find('[data-testid="jb-row-mission"]')
    expect(row.text()).toContain('Closeout: Shipped the export retry.')
    expect(row.text()).not.toContain('Three attempts')
    expect(row.find('[title]').attributes('title')).toBe(`Closeout: ${summary}`)
    await wrapper.find('[data-testid="jb-details-btn"]').trigger('click')
    expect(wrapper.find('[data-testid="jb-drawer-mission"]').text()).toContain('Closeout: Shipped the export retry.')
    expect(wrapper.find('[data-testid="jb-drawer-mission"]').text()).toContain('Three attempts with backoff')
    expect(wrapper.text()).not.toMatch(/Press Stage/)
  })

  it('folded, the one-line summary says "No agent run recorded" instead of empty numbers', () => {
    const wrapper = mountCard(emptyDone, [], { density: 'compact' })
    const facts = wrapper.find('[data-testid="jb-summary-facts"]')
    expect(facts.text()).toContain('No agent run recorded')
    expect(facts.text()).not.toMatch(/---/)
  })
})

describe('JobsBoardCard, cards with a real agent run are unchanged (FE-9763)', () => {
  it('a completed card with agents keeps its stat strip and no empty-run line', () => {
    const wrapper = mountCard({ ...emptyDone, agent_count: 2, mission: 'Phase 1: fix it.' }, [orch, impl])
    expect(wrapper.find('[data-testid="jb-empty-run"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-stat-agents"]').text()).toBe('2')
    expect(wrapper.find('[data-testid="jb-row-mission"]').text()).toContain('Phase 1: fix it.')
  })

  it('an agent count from the board read holds the strip while the agent list loads', () => {
    const wrapper = mountCard({ ...emptyDone, agent_count: 3 })
    expect(wrapper.find('[data-testid="jb-empty-run"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-stat-steps"]').exists()).toBe(true)
  })

  it('a not-yet-staged active card still tells the user to press Stage', () => {
    const wrapper = mountCard({ ...emptyDone, status: 'active', review_pending: false, completed_at: null })
    expect(wrapper.find('[data-testid="jb-row-mission"]').text()).toMatch(/No mission yet\. Press Stage/)
    expect(wrapper.find('[data-testid="jb-empty-run"]').exists()).toBe(false)
  })
})
