import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobsBoardCard from './JobsBoardCard.vue'
import { STATUS_COLORS } from '@/utils/statusConfig'

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

function rgb(hex) {
  const n = parseInt(hex.replace('#', ''), 16)
  return `rgb(${n >> 16}, ${(n >> 8) & 255}, ${n & 255})`
}

const project = { id: 'p', taxonomy_alias: 'BE-1', name: 'x', status: 'active', implementation_launched_at: '2026-09-29T13:00:00Z' }
const orch = (orchestratorState) => ({
  agent_id: 'a-or',
  job_id: 'j-or',
  agent_name: 'orchestrator',
  agent_display_name: 'orchestrator',
  status: 'silent',
  activity: 'silent',
  steps: { completed: 0, total: 7 },
  orchestrator_state: orchestratorState,
})
const worker = (status) => ({ agent_id: `a-${status}`, job_id: `j-${status}`, agent_display_name: 'implementer', status, activity: status })

const CASES = [
  {
    state: 'monitoring',
    label: 'Monitoring (2 agents running)',
    color: STATUS_COLORS.IDLE,
    agents: [orch({ state: 'monitoring', label: 'Monitoring (2 agents running)', agents: 2 }), worker('working')],
    pill: null,
  },
  {
    state: 'result_waiting',
    label: 'Result waiting, not picked up (9 min)',
    color: STATUS_COLORS.SILENT,
    agents: [orch({ state: 'result_waiting', label: 'Result waiting, not picked up (9 min)', agents: 1, minutes: 9 }), worker('complete')],
    pill: 'Result not picked up',
  },
  {
    state: 'silent',
    label: 'Silent',
    color: STATUS_COLORS.SILENT,
    agents: [orch({ state: 'silent', label: 'Silent', agents: 0 }), worker('closed')],
    pill: 'Orchestrator silent',
  },
]

function mountCard(agents) {
  return mount(JobsBoardCard, {
    props: { project, agents, now: Date.parse('2026-09-29T14:00:00Z') },
    global: { plugins: [vuetify, router], stubs: { 'v-tooltip': tooltipStub } },
  })
}

function orchestratorStatus(wrapper) {
  const row = wrapper.findAll('[data-testid="jb-agent-row"]')[0]
  return row.find('[data-testid="jb-agent-status"]')
}

describe('a stale orchestrator on the Jobs board card (BE-9717)', () => {
  it.each(CASES)('$state renders the server label in its colour token', ({ label, color, agents }) => {
    const status = orchestratorStatus(mountCard(agents))
    expect(status.text()).toBe(label)
    expect(status.element.style.color).toBe(rgb(color))
  })

  it.each(CASES)('$state: the reason pill is $pill', ({ agents, pill }) => {
    const wrapper = mountCard(agents)
    const texts = wrapper.findAll('[data-testid="jb-status-pill"]').map((p) => p.text())
    if (pill) expect(texts).toContain(pill)
    else expect(texts.join(' ')).not.toMatch(/silent|not picked up/i)
  })

  it('a row whose stored status went live-to-idle drops the derived state', () => {
    const idle = { ...orch({ state: 'silent', label: 'Silent', agents: 0 }), status: 'idle', activity: 'idle' }
    const status = orchestratorStatus(mountCard([idle]))
    expect(status.text()).toBe('Monitoring')
    expect(status.element.style.color).toBe(rgb(STATUS_COLORS.IDLE))
  })
})
