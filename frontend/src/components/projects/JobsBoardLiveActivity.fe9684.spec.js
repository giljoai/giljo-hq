import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobsBoardAgentRow from './JobsBoardAgentRow.vue'
import JobsBoardSummaryRows from './JobsBoardSummaryRows.vue'
import JobsBoardCardSummary from './JobsBoardCardSummary.vue'
import JobsBoardCardDrawer from './JobsBoardCardDrawer.vue'
import JobsBoardDetailModal from './JobsBoardDetailModal.vue'
import JobsBoardCard from './JobsBoardCard.vue'
import { isLiveStatusWord } from '@/utils/jobStatusWord'

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
const NOW = Date.parse('2026-09-26T14:00:00Z')

const working = { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'working', steps: { completed: 2, total: 6 } }
const STILL = [
  { agent_id: 'a-w', job_id: 'j-w', agent_display_name: 'tester', status: 'waiting' },
  { agent_id: 'a-c', job_id: 'j-c', agent_display_name: 'reviewer', status: 'complete' },
  { agent_id: 'a-b', job_id: 'j-b', agent_display_name: 'analyzer', status: 'blocked', block_reason: 'Needs a key' },
  { agent_id: 'a-h', job_id: 'j-h', agent_display_name: 'documenter', status: 'working', activity: 'holding' },
]

describe('isLiveStatusWord (FE-9684)', () => {
  it('only a working job is live; holding, silent and every resting state are not', () => {
    expect(isLiveStatusWord('working')).toBe(true)
    for (const word of ['holding', 'silent', 'waiting', 'blocked', 'awaiting_user', 'complete', 'closed', 'idle', '', undefined]) {
      expect(isLiveStatusWord(word)).toBe(false)
    }
  })
})

describe('Jobs board agent row (FE-9684)', () => {
  function mountRow(agent) {
    return mount(JobsBoardAgentRow, {
      props: { agent, now: NOW },
      global: { stubs: { 'v-tooltip': tooltipStub, 'v-menu': true } },
    })
  }

  it('a working agent breathes and its status word ends in decorative dots', () => {
    const wrapper = mountRow(working)
    expect(wrapper.find('[data-testid="jb-agent-badge"]').classes()).toContain('live-badge')
    const status = wrapper.find('[data-testid="jb-agent-status"]')
    const dots = status.find('[data-testid="live-dots"]')
    expect(dots.exists()).toBe(true)
    expect(dots.attributes('aria-hidden')).toBe('true')
    expect(dots.findAll('.live-dot')).toHaveLength(3)
    expect(status.text().startsWith('Working')).toBe(true)
  })

  it.each(STILL)('a $status agent ($agent_display_name) stays still', (agent) => {
    const wrapper = mountRow(agent)
    expect(wrapper.find('[data-testid="jb-agent-badge"]').classes()).not.toContain('live-badge')
    expect(wrapper.find('[data-testid="live-dots"]').exists()).toBe(false)
  })
})

describe('folded summary and drawer crew row (FE-9684)', () => {
  it('a folded card badge breathes only for a working agent', () => {
    const wrapper = mount(JobsBoardCardSummary, {
      props: { agents: [working, STILL[0]], steps: { hasSteps: false }, waiting: 0, duration: '1m' },
      global: { stubs: { 'v-tooltip': tooltipStub } },
    })
    const badges = wrapper.findAll('[data-testid="jb-summary-badge"]')
    expect(badges[0].classes()).toContain('live-badge')
    expect(badges[1].classes()).not.toContain('live-badge')
  })

  it('the drawer crew row breathes and ends in dots only once launched and working', () => {
    const launched = mount(JobsBoardCardDrawer, {
      props: { project: { id: 'p' }, agents: [working, STILL[1]], launched: true },
    })
    const rows = launched.findAll('[data-testid="jb-crew-row"]')
    expect(rows[0].find('.agent-badge-sq').classes()).toContain('live-badge')
    expect(rows[0].find('[data-testid="live-dots"]').exists()).toBe(true)
    expect(rows[1].find('.agent-badge-sq').classes()).not.toContain('live-badge')
    expect(rows[1].find('[data-testid="live-dots"]').exists()).toBe(false)

    const staged = mount(JobsBoardCardDrawer, {
      props: { project: { id: 'p' }, agents: [working], launched: false },
    })
    expect(staged.find('.live-badge').exists()).toBe(false)
  })

  it('"Orchestrator writing" ends in the dots while the mission is being written', () => {
    const wrapper = mount(JobsBoardSummaryRows, {
      props: { project: { id: 'p' }, missionState: 'writing' },
    })
    expect(wrapper.find('[data-testid="jb-row-mission"] [data-testid="live-dots"]').exists()).toBe(true)
    const written = mount(JobsBoardSummaryRows, {
      props: { project: { id: 'p' }, missionState: 'written', mission: 'Do it' },
    })
    expect(written.find('[data-testid="live-dots"]').exists()).toBe(false)
  })
})

describe('Jobs detail agent table (FE-9684)', () => {
  it('only the working row breathes and ends in dots', () => {
    const wrapper = mount(JobsBoardDetailModal, {
      props: { modelValue: true, project: { id: 'p', name: 'x' }, agents: [working, STILL[1]], now: NOW },
      global: {
        plugins: [vuetify, router],
        stubs: { MessageComposer: true, ProjectStatusBanner: true, 'v-dialog': { template: '<div><slot /></div>' } },
      },
    })
    const rows = wrapper.findAll('[data-testid="jb-detail-row"]')
    expect(rows[0].find('.agent-badge-sq').classes()).toContain('live-badge')
    expect(rows[0].find('[data-testid="live-dots"]').exists()).toBe(true)
    expect(rows[1].find('.agent-badge-sq').classes()).not.toContain('live-badge')
    expect(rows[1].find('[data-testid="live-dots"]').exists()).toBe(false)
  })
})

describe('card lifecycle pill (FE-9684)', () => {
  function mountCard(project, agents = []) {
    return mount(JobsBoardCard, {
      props: { project, agents, now: NOW },
      global: { plugins: [vuetify, router], stubs: { 'v-tooltip': tooltipStub } },
    })
  }
  const base = { id: 'p', taxonomy_alias: 'FE-1', name: 'x', status: 'active' }

  it('an Implementing card glows and its pill ends in dots', () => {
    const wrapper = mountCard({ ...base, implementation_launched_at: '2026-09-26T13:00:00Z' }, [working])
    const pill = wrapper.find('[data-testid="jb-status-pill"]')
    expect(pill.text().startsWith('Implementing')).toBe(true)
    expect(pill.classes()).toContain('live-pill')
    expect(pill.find('[data-testid="live-dots"]').exists()).toBe(true)
  })

  it('a Planning card (staging running) glows too', () => {
    const pill = mountCard({ ...base, staging_status: 'staging' }).find('[data-testid="jb-status-pill"]')
    expect(pill.classes()).toContain('live-pill')
  })

  it('a Staged card is still', () => {
    const pill = mountCard({ ...base, staging_status: 'staging_complete' }).find('[data-testid="jb-status-pill"]')
    expect(pill.classes()).not.toContain('live-pill')
    expect(pill.find('[data-testid="live-dots"]').exists()).toBe(false)
  })
})

describe('the shared live-activity styles (FE-9684)', () => {
  const partial = readFileSync(resolve(__dirname, '../../styles/_live-activity.scss'), 'utf8')
  const main = readFileSync(resolve(__dirname, '../../styles/main.scss'), 'utf8')

  it('is loaded once, globally, from main.scss', () => {
    expect(main).toMatch(/@use\s+["']\.\/_?live-activity(\.scss)?["']/)
  })

  it('defines the badge, dots, dot pulse and pill animations', () => {
    for (const cls of ['.live-badge', '.live-dots', '.live-dot', '.live-dot-pulse', '.live-pill']) {
      expect(partial).toContain(cls)
    }
    expect(partial).toMatch(/@keyframes\s+live-badge-breathe/)
    expect(partial).toMatch(/@keyframes\s+live-pulse-ring/)
    expect(partial).toMatch(/@keyframes\s+live-dot-blink/)
  })

  it('stops every animation when the operator asks for reduced motion', () => {
    const block = partial.match(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*)\}\s*$/)
    expect(block).not.toBeNull()
    expect(block[1]).toMatch(/animation:\s*none/)
  })

  it('carries no hard-coded hex colour', () => {
    expect(partial).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})
