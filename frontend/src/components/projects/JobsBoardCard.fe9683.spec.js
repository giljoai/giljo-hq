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

function mountCard(project, agents = []) {
  return mount(JobsBoardCard, {
    props: { project, agents, now: Date.parse('2026-09-26T14:00:00Z') },
    global: { plugins: [vuetify, router], stubs: { 'v-tooltip': tooltipStub } },
  })
}

const running = {
  id: 'p-run',
  taxonomy_alias: 'INF-6188',
  name: 'DEMO · Agent row variety',
  status: 'active',
  implementation_launched_at: '2026-09-26T13:00:00Z',
}
const orch = { agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'working', steps: { completed: 2, total: 5 } }
const blockedWorker = { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'blocked', block_reason: 'Waiting on a credential' }
const decidingWorker = { agent_id: 'a-te', job_id: 'j-te', agent_display_name: 'tester', status: 'awaiting_user' }

describe('JobsBoardCard header rows (FE-9683)', () => {
  it('row 1 holds the serial pill, the title and the fold chevron; row 2 holds every status pill, centered', async () => {
    const wrapper = mountCard(running, [orch, decidingWorker])
    const head = wrapper.find('[data-testid="jb-head"]')
    expect(head.find('[data-testid="jb-tax-pill"]').exists()).toBe(true)
    expect(head.find('[data-testid="jb-title"]').exists()).toBe(true)
    expect(head.find('[data-testid="jb-fold-btn"]').exists()).toBe(true)
    expect(head.find('[data-testid="jb-status-pill"]').exists()).toBe(false)

    const row = wrapper.find('[data-testid="jb-pill-row"]')
    expect(row.exists()).toBe(true)
    expect(row.find('[data-testid="jb-lifecycle-pill"]').text()).toBe('Needs decision')
    expect(row.find('[data-testid="jb-status-pill"]').text()).toBe('Your decision needed')
    const source = (await import('./JobsBoardCard.vue?raw')).default
    expect(source).toMatch(/\.jb-pills\s*\{[^}]*justify-content:\s*center/)
  })

  it('a card that needs nobody shows its lifecycle pill alone on row 2', () => {
    const wrapper = mountCard(running, [orch])
    const row = wrapper.find('[data-testid="jb-pill-row"]')
    expect(row.findAll('.jb-status-pill')).toHaveLength(1)
    expect(row.find('[data-testid="jb-status-pill"]').text()).toBe('Implementing...')
  })
})

describe('JobsBoardCard decision pill (FE-9683)', () => {
  it('is a solid button that opens Jobs detail, keyboard reachable, with its hint', async () => {
    const wrapper = mountCard(running, [orch, decidingWorker])
    const pill = wrapper.find('[data-testid="jb-status-pill"]')
    expect(pill.element.tagName).toBe('BUTTON')
    expect(pill.attributes('aria-label')).toBe('Open Jobs detail to decide')
    expect(pill.classes()).toContain('jb-status-pill--decision')
    expect(wrapper.find('[data-testid="jb-status-pill-hint"]').text()).toMatch(/Open Jobs detail to decide/)
    await pill.trigger('click')
    expect(wrapper.emitted('open-detail')?.[0]).toEqual([running])
  })

  it('the solid fill and the navy ink come from the design tokens', async () => {
    const source = (await import('./JobsBoardCard.vue?raw')).default
    const block = source.match(/\.jb-status-pill--decision\s*\{([^}]*)\}/)?.[1] || ''
    expect(block).toMatch(/background:\s*\$color-status-warning/)
    expect(block).toMatch(/color:\s*\$color-background-primary/)
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })

  it('a blocked agent with no pending approval is "<Role> blocked", a status and not a button', () => {
    const wrapper = mountCard(running, [orch, blockedWorker])
    const pill = wrapper.find('[data-testid="jb-status-pill"]')
    expect(pill.text()).toBe('Implementer blocked')
    expect(pill.element.tagName).not.toBe('BUTTON')
    expect(pill.classes()).not.toContain('jb-status-pill--decision')
    expect(wrapper.find('[data-testid="jb-status-pill-hint"]').text()).toMatch(/reason/)
  })
})

describe('JobsBoardCard actionable controls share the Jobs detail link colour (FE-9683)', () => {
  const LINK = /color:\s*\$color-text-tertiary/
  const MUTED = /color:\s*\$color-text-secondary/
  const block = (source, selector) => source.match(new RegExp(`${selector.replace('.', '\\.')}\\s*\\{([^}]*)\\}`))?.[1] || ''

  it('fold chevron and Details chevron', async () => {
    const source = (await import('./JobsBoardCard.vue?raw')).default
    expect(block(source, '.jb-fold-btn')).toMatch(LINK)
    expect(block(source, '.jb-fold-btn')).not.toMatch(MUTED)
    expect(block(source, '.jb-details-btn')).toMatch(LINK)
    expect(block(source, '.jb-details-btn')).not.toMatch(MUTED)
  })

  it('edit pencils on the rows and in the drawer', async () => {
    const rows = (await import('./JobsBoardSummaryRows.vue?raw')).default
    const drawer = (await import('./JobsBoardCardDrawer.vue?raw')).default
    expect(block(rows, '.jb-pen')).toMatch(LINK)
    expect(block(rows, '.jb-pen')).not.toMatch(MUTED)
    expect(block(drawer, '.jb-pen')).toMatch(LINK)
    expect(block(drawer, '.jb-pen')).not.toMatch(MUTED)
  })

  it('the "Run as" label next to the mode chips, and the Jobs detail link itself', async () => {
    const footer = (await import('./JobsBoardCardFooter.vue?raw')).default
    const runAs = (await import('./RunAsSwitch.vue?raw')).default
    expect(block(runAs, '.run-as-k')).toMatch(LINK)
    expect(block(runAs, '.run-as-k')).not.toMatch(MUTED)
    expect(block(footer, '.jb-btn-ghost')).toMatch(LINK)
  })
})

describe('finished chain step card (TSK-9690)', () => {
  it('a completed chain step reads Complete and offers no Stage', () => {
    const project = { id: 'p-done', taxonomy_alias: 'INF-6181', name: 'Step 1', status: 'completed', staging_status: 'staging_complete', implementation_launched_at: '2026-09-26T13:00:00Z' }
    const agents = [
      { agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'complete' },
      { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'complete' },
    ]
    const wrapper = mountCard(project, agents)
    expect(wrapper.find('[data-testid="jb-status-pill"]').text()).toBe('Complete')
    expect(wrapper.find('[data-testid="jbf-stage"]').exists()).toBe(false)
  })

  it('a cancelled step that never launched reads Stopped and offers no Stage', () => {
    const project = { id: 'p-stop', taxonomy_alias: 'INF-6183', name: 'Step 3', status: 'cancelled', staging_status: null, implementation_launched_at: null }
    const wrapper = mountCard(project, [])
    expect(wrapper.find('[data-testid="jb-status-pill"]').text()).toBe('Stopped')
    expect(wrapper.find('[data-testid="jbf-stage"]').exists()).toBe(false)
  })
})
