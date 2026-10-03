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
    props: { project, agents, now: Date.parse('2026-09-26T06:00:00Z'), ...props },
    global: {
      plugins: [vuetify, router],
      stubs: {
        'v-tooltip': tooltipStub,
        AgentTipsDialog: { template: '<button data-testid="agent-tips-stub" />' },
      },
    },
  })
}

const base = {
  id: 'p-stage',
  taxonomy_alias: 'BE-0139',
  name: 'Nightly export retry',
  status: 'active',
  description: 'The nightly CSV export fails silently when the storage token has expired.\nRetry three times with backoff.',
  implementation_launched_at: null,
  staging_status: null,
}
const orch = { agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'complete' }
const impl = { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'pending', phase: 1 }
const tester = { agent_id: 'a-te', job_id: 'j-te', agent_display_name: 'tester', status: 'pending', phase: 2 }

const staged = {
  ...base,
  id: 'p-staged',
  staging_status: 'staging_complete',
  execution_mode: 'multi_terminal',
  mission: 'Phase 1 frontend: BillingView copy.\nPhase 2 tester: specs.',
}

describe('JobsBoardCard summary rows (FE-9682)', () => {
  it('renders Description and Mission as the only one-line rows under the stat strip', () => {
    const wrapper = mountCard(staged, [orch, impl, tester])
    const rows = wrapper.find('[data-testid="jb-summary-rows"]')
    expect(rows.exists()).toBe(true)
    expect(wrapper.find('[data-testid="jb-row-description"]').text()).toContain('The nightly CSV export fails silently')
    expect(wrapper.find('[data-testid="jb-row-description"]').text()).not.toContain('Retry three times')
    expect(wrapper.find('[data-testid="jb-row-mission"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="jb-row-crew"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="jb-edit-description"]')).toHaveLength(1)
    expect(wrapper.find('[data-testid="jb-staging-panels"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-crew-tile"]').exists()).toBe(false)
  })

  it('Mission row, no mission: hollow dot and the Stage hint', () => {
    const wrapper = mountCard(base)
    const state = wrapper.find('[data-testid="jb-mission-state"]')
    expect(state.attributes('data-state')).toBe('none')
    expect(wrapper.find('[data-testid="jb-row-mission"]').text()).toMatch(/No mission yet\. Press Stage and the orchestrator writes it\./)
  })

  it('Mission row, staging in progress: pulsing dot and "Orchestrator writing"', () => {
    const wrapper = mountCard({ ...base, id: 'p-planning', staging_status: 'staging', execution_mode: 'subagent' }, [
      { ...orch, status: 'working' },
    ])
    const state = wrapper.find('[data-testid="jb-mission-state"]')
    expect(state.attributes('data-state')).toBe('writing')
    expect(wrapper.find('[data-testid="jb-row-mission"]').text()).toContain('Orchestrator writing')
  })

  it('Mission row, written: green dot, the word Written and the first line', () => {
    const wrapper = mountCard(staged, [orch, impl, tester])
    const state = wrapper.find('[data-testid="jb-mission-state"]')
    expect(state.attributes('data-state')).toBe('written')
    const row = wrapper.find('[data-testid="jb-row-mission"]')
    expect(row.text()).toContain('Written')
    expect(row.text()).toContain('Phase 1 frontend: BillingView copy.')
    expect(row.text()).not.toContain('Phase 2 tester')
  })

  it('the bottom work pane, not a summary row, is the one crew listing before staging', () => {
    const wrapper = mountCard(staged, [impl, tester, orch])
    expect(wrapper.find('[data-testid="jb-row-crew"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-agents-list"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="jb-agent-row"]')).toHaveLength(3)
  })

  it('the Description pencil on the row asks the board to open the edit dialog', async () => {
    const wrapper = mountCard(base)
    await wrapper.find('[data-testid="jb-row-description"] [data-testid="jb-edit-description"]').trigger('click')
    expect(wrapper.emitted('edit-description')?.[0]?.[0]).toMatchObject({ id: 'p-stage' })
  })
})

describe('JobsBoardCard Details drawer (FE-9682)', () => {
  it('one Details chevron opens the drawer inside the card and closes it again', async () => {
    const wrapper = mountCard(staged, [orch, impl, tester])
    const btn = wrapper.find('[data-testid="jb-details-btn"]')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-testid="jb-drawer"]').exists()).toBe(false)

    await btn.trigger('click')
    expect(btn.attributes('aria-expanded')).toBe('true')
    const drawer = wrapper.find('[data-testid="jb-drawer"]')
    expect(drawer.exists()).toBe(true)
    expect(drawer.find('[data-testid="jb-drawer-description"]').text()).toContain('Retry three times with backoff.')
    expect(drawer.find('[data-testid="jb-drawer-mission"]').text()).toContain('Phase 2 tester: specs.')
    expect(drawer.find('[data-testid="jb-mission-tag"]').text()).toMatch(/Orchestrator generated/)

    await btn.trigger('click')
    expect(btn.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-testid="jb-drawer"]').exists()).toBe(false)
  })

  it('crew rows in the drawer carry a pencil for workers and none for the orchestrator', async () => {
    const wrapper = mountCard(staged, [orch, impl, tester])
    await wrapper.find('[data-testid="jb-details-btn"]').trigger('click')
    const rows = wrapper.findAll('[data-testid="jb-crew-row"]')
    expect(rows).toHaveLength(3)
    expect(rows[0].text()).toContain('orchestrator')
    expect(rows[0].find('[data-testid="jb-crew-edit"]').exists()).toBe(false)
    expect(rows[1].find('[data-testid="jb-crew-edit"]').exists()).toBe(true)
    expect(rows[2].find('[data-testid="jb-crew-edit"]').exists()).toBe(true)
    expect(rows[1].text()).toContain('phase 1')

    await rows[1].find('[data-testid="jb-crew-edit"]').trigger('click')
    expect(wrapper.emitted('agent-mission-edit')?.[0]?.[0]).toMatchObject({ agent_id: 'a-im' })
  })

  it('a crew row name in the drawer opens the agent role', async () => {
    const wrapper = mountCard(staged, [orch, impl])
    await wrapper.find('[data-testid="jb-details-btn"]').trigger('click')
    await wrapper.findAll('[data-testid="jb-crew-row-name"]')[0].trigger('click')
    expect(wrapper.emitted('agent-role')?.[0]?.[0]).toMatchObject({ agent_id: 'a-or' })
  })

  it('the drawer pencil on the full description opens the same edit dialog', async () => {
    const wrapper = mountCard(staged, [orch])
    await wrapper.find('[data-testid="jb-details-btn"]').trigger('click')
    await wrapper.find('[data-testid="jb-drawer-description"] [data-testid="jb-edit-description"]').trigger('click')
    expect(wrapper.emitted('edit-description')?.[0]?.[0]).toMatchObject({ id: 'p-staged' })
  })
})

describe('JobsBoardCard meta line icons and the retired Agent Lab (FE-9682)', () => {
  it('renders no AgentTipsDialog anywhere on the card', () => {
    const wrapper = mountCard(staged, [orch, impl], { gitEnabled: true, integrationsResolved: true })
    expect(wrapper.find('[data-testid="agent-tips-stub"]').exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'AgentTipsDialog' }).exists()).toBe(false)
  })

  it('Git and mode icons sit on the meta line, lit when on and dim when off', () => {
    const wrapper = mountCard(staged, [orch, impl], { gitEnabled: true, integrationsResolved: true })
    const meta = wrapper.find('[data-testid="jb-meta"]')
    const git = meta.find('[data-testid="git-status-icon"]')
    const mode = meta.find('[data-testid="agentic-tool-icon"]')
    expect(git.exists()).toBe(true)
    expect(mode.exists()).toBe(true)
    expect(meta.findAll('button')).toHaveLength(2)
    expect(git.classes()).toContain('jb-int--on')
    expect(mode.attributes('aria-label')).toMatch(/multi terminal/i)
    expect(meta.text()).toContain('Git integration enabled')

    const off = mountCard(staged, [orch, impl], { gitEnabled: false, integrationsResolved: true })
    const offMeta = off.find('[data-testid="jb-meta"]')
    expect(offMeta.find('[data-testid="git-status-icon"]').classes()).toContain('jb-int--off')
    expect(offMeta.text()).toContain('Git disabled')
  })

  it('an unread integration status renders as pending, never as off', () => {
    const wrapper = mountCard(staged, [orch], { integrationsResolved: false })
    const git = wrapper.find('[data-testid="git-status-icon"]')
    expect(git.classes()).toContain('jb-int--pending')
    expect(git.classes()).not.toContain('jb-int--off')
  })

  it('the icons show on an implementing card too, and the summary rows sit above the live agent rows', () => {
    const running = { ...staged, id: 'p-run', implementation_launched_at: '2026-09-26T05:00:00Z' }
    const wrapper = mountCard(running, [{ ...orch, status: 'working', steps: { completed: 1, total: 3 } }, impl], {
      integrationsResolved: true,
      gitEnabled: true,
    })
    expect(wrapper.find('[data-testid="jb-meta"] [data-testid="git-status-icon"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="jb-summary-rows"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="jb-agents-list"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="jb-agent-status"]').length).toBeGreaterThan(0)
  })
})

describe('JobsBoardCard inside a chain member (FE-9682 V1)', () => {
  it('V1: a chain member card is not forced to 100% height under the step label', async () => {
    const chainCtx = { runId: 'run-1', locked: true, projects: [], tabs: [] }
    const wrapper = mountCard(staged, [orch], { chainCtx })
    expect(wrapper.find('[data-testid="jobs-board-card"]').classes()).toContain('jb-card--member')
    const source = (await import('./JobsBoardCard.vue?raw')).default
    expect(source).toMatch(/\.jb-card--member\s*\{[^}]*height:\s*auto/)
  })

  it('V1: a loose card keeps its full-height layout', () => {
    const wrapper = mountCard(staged, [orch])
    expect(wrapper.find('[data-testid="jobs-board-card"]').classes()).not.toContain('jb-card--member')
  })
})
