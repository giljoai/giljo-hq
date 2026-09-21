
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import AgentRow from '@/components/projects/AgentRow.vue'
import { useUserStore } from '@/stores/user'

const vuetify = createVuetify()

const tooltipStub = {
  props: ['text'],
  template: `<div class="v-tooltip" :data-tooltip-text="text"><slot name="activator" :props="{}" /></div>`,
}
const listItemStub = {
  props: ['title', 'prependIcon'],
  template: `<div class="v-list-item" v-bind="$attrs" :title="title"><slot /></div>`,
}
const menuStub = {
  template: `<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>`,
}

const stubs = {
  'v-tooltip': tooltipStub,
  'v-menu': menuStub,
  'v-list-item': listItemStub,
  'v-btn': {
    props: ['icon', 'size', 'variant', 'color'],
    template: `<button v-bind="$attrs" class="v-btn" @click="$emit('click', $event)"><slot /></button>`,
  },
  'v-icon': { template: `<span class="v-icon"><slot /></span>` },
  'v-list': { template: `<div class="v-list"><slot /></div>` },
}

function makeWrapperComponent(agentRowProps) {
  return {
    components: { AgentRow },
    setup() {
      return { agentRowProps }
    },
    template: `
      <table>
        <tbody>
          <AgentRow v-bind="agentRowProps" />
        </tbody>
      </table>
    `,
  }
}

async function mountRow(props) {
  const pinia = createPinia()
  setActivePinia(pinia)

  const userStore = useUserStore()
  userStore.currentUser = { id: 'user-1', tenant_key: 'tenant-test' }

  const wrapper = mount(makeWrapperComponent(props), {
    global: { plugins: [pinia, vuetify], stubs },
  })
  await wrapper.vm.$nextTick()
  return wrapper
}

function makeAgent(overrides = {}) {
  return {
    job_id: 'job-001',
    agent_id: 'agent-001',
    agent_name: 'orchestrator',
    agent_display_name: 'orchestrator',
    status: 'working',
    phase: null,
    messages_waiting_count: 0,
    ...overrides,
  }
}

const NOW_MS = 1_700_000_000_000


describe('AgentRow — phase badge variants', () => {
  it('shows "All" when isSubagentMode=true', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ agent_name: 'implementer', agent_display_name: 'implementer', phase: 1 }),
      now: NOW_MS,
      isSubagentMode: true,
    })
    const badge = wrapper.find('[data-testid="phase-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('All')
  })

  it('shows "Start" for orchestrator in normal mode', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ agent_name: 'orchestrator', agent_display_name: 'orchestrator', phase: null }),
      now: NOW_MS,
      isSubagentMode: false,
    })
    const badge = wrapper.find('[data-testid="phase-badge"]')
    expect(badge.text()).toBe('Start')
  })

  it('shows em-dash for agent with phase=null (non-orchestrator)', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ agent_name: 'reviewer', agent_display_name: 'reviewer', phase: null }),
      now: NOW_MS,
      isSubagentMode: false,
    })
    const badge = wrapper.find('[data-testid="phase-badge"]')
    expect(badge.text()).toMatch(/—/)
  })

  it('shows "P2" for agent with phase=2', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ agent_name: 'implementer', agent_display_name: 'implementer', phase: 2 }),
      now: NOW_MS,
      isSubagentMode: false,
    })
    const badge = wrapper.find('[data-testid="phase-badge"]')
    expect(badge.text()).toBe('P2')
  })
})


describe('AgentRow — agent badge initials', () => {
  it('does not leak a bracket for a parenthetical display name ("Reviewer (Phase 5)" -> "R(")', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({
        agent_name: 'reviewer',
        agent_display_name: 'Reviewer (Phase 5)',
        status: 'working',
      }),
      now: NOW_MS,
      isSubagentMode: false,
    })
    const badge = wrapper.find('.agent-badge')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('RP')
    expect(badge.text()).not.toContain('(')
  })

  it('still renders ordinary two-word initials unchanged', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({
        agent_name: 'implementer',
        agent_display_name: 'Backend Implementer',
        status: 'waiting',
      }),
      now: NOW_MS,
      isSubagentMode: false,
    })
    const badge = wrapper.find('.agent-badge')
    expect(badge.text()).toBe('BI')
  })
})


describe('AgentRow — status chip', () => {
  it('renders status chip with the correct label for "waiting"', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'waiting' }),
      now: NOW_MS,
    })
    const chip = wrapper.find('[data-testid="status-chip"]')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('Waiting')
  })

  it('renders status chip with the correct label for "complete"', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'complete', duration_seconds: 120 }),
      now: NOW_MS,
    })
    const chip = wrapper.find('[data-testid="status-chip"]')
    expect(chip.text()).toContain('Complete')
  })

  it('renders status chip with the correct color style for "working"', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'working' }),
      now: NOW_MS,
    })
    const chip = wrapper.find('[data-testid="status-chip"]')
    expect(chip.attributes('style')).toContain('color: rgb(255, 255, 255)')
  })
})


describe('AgentRow — play button visibility', () => {
  it('shows copy-prompt button when shouldShowCopy=true', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'waiting' }),
      now: NOW_MS,
      shouldShowCopy: true,
      playFaded: false,
    })
    const btn = wrapper.find('[aria-label="Copy agent prompt"]')
    expect(btn.exists()).toBe(true)
  })

  it('hides copy-prompt button when shouldShowCopy=false', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'waiting' }),
      now: NOW_MS,
      shouldShowCopy: false,
    })
    const btn = wrapper.find('[aria-label="Copy agent prompt"]')
    expect(btn.exists()).toBe(false)
  })

  it('adds play-btn-faded class when playFaded=true', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'working' }),
      now: NOW_MS,
      shouldShowCopy: true,
      playFaded: true,
    })
    const btn = wrapper.find('.play-circle-btn')
    expect(btn.classes()).toContain('play-btn-faded')
  })

  it('defaults the play tooltip to the solo wording', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'waiting' }),
      now: NOW_MS,
      shouldShowCopy: true,
      playFaded: false,
    })
    const tip = wrapper.find('.play-cell .v-tooltip')
    expect(tip.attributes('data-tooltip-text')).toBe('Copy prompt')
  })

  it('renders the supplied play tooltip (chain member waiting its turn)', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'waiting' }),
      now: NOW_MS,
      shouldShowCopy: true,
      playFaded: true,
      playTooltip: 'Starts after FE-9640 closes out',
    })
    const tip = wrapper.find('.play-cell .v-tooltip')
    expect(tip.attributes('data-tooltip-text')).toBe('Starts after FE-9640 closes out')
  })
})


describe('AgentRow — message badge', () => {
  it('renders zero-class badge when messages_waiting_count=0', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ messages_waiting_count: 0 }),
      now: NOW_MS,
    })
    const badge = wrapper.find('.msg-badge')
    expect(badge.exists()).toBe(true)
    expect(badge.classes()).toContain('zero')
    expect(badge.classes()).not.toContain('has-msgs')
    expect(badge.text()).toBe('0')
  })

  it('renders has-msgs-class badge when messages_waiting_count > 0', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ messages_waiting_count: 3 }),
      now: NOW_MS,
    })
    const badge = wrapper.find('.msg-badge')
    expect(badge.classes()).toContain('has-msgs')
    expect(badge.classes()).not.toContain('zero')
    expect(badge.text()).toBe('3')
  })

  it('emits messages event when the count badge is clicked', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ messages_waiting_count: 3 }),
      now: NOW_MS,
    })
    await wrapper.find('.message-count-button').trigger('click')
    expect(wrapper.findComponent(AgentRow).emitted('messages')).toHaveLength(1)
  })
})


describe('AgentRow — action_required_unread badge (BE-9273)', () => {
  it('renders needs-action class when action_required_unread > 0', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ messages_waiting_count: 2, action_required_unread: 1 }),
      now: NOW_MS,
    })
    const badge = wrapper.find('[data-testid="messages-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.classes()).toContain('needs-action')
    expect(badge.classes()).not.toContain('has-msgs')
    expect(badge.classes()).not.toContain('zero')
    expect(badge.text()).toBe('2')
  })

  it('needs-action takes priority even when it equals the full waiting count', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ messages_waiting_count: 1, action_required_unread: 1 }),
      now: NOW_MS,
    })
    const badge = wrapper.find('[data-testid="messages-badge"]')
    expect(badge.classes()).toContain('needs-action')
  })

  it('falls back to has-msgs when unread exists but none is action_required', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ messages_waiting_count: 3, action_required_unread: 0 }),
      now: NOW_MS,
    })
    const badge = wrapper.find('[data-testid="messages-badge"]')
    expect(badge.classes()).toContain('has-msgs')
    expect(badge.classes()).not.toContain('needs-action')
  })

  it('falls back to zero when both counts are zero', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ messages_waiting_count: 0, action_required_unread: 0 }),
      now: NOW_MS,
    })
    const badge = wrapper.find('[data-testid="messages-badge"]')
    expect(badge.classes()).toContain('zero')
    expect(badge.classes()).not.toContain('needs-action')
    expect(badge.classes()).not.toContain('has-msgs')
  })

  it('treats a missing action_required_unread field as 0 (backwards-compatible default)', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ messages_waiting_count: 2 }),
      now: NOW_MS,
    })
    const badge = wrapper.find('[data-testid="messages-badge"]')
    expect(badge.classes()).toContain('has-msgs')
    expect(badge.classes()).not.toContain('needs-action')
  })

  it('sets an actionable aria-label and title when action_required_unread > 0', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ messages_waiting_count: 1, action_required_unread: 1 }),
      now: NOW_MS,
    })
    const btn = wrapper.find('.message-count-button')
    expect(btn.attributes('aria-label')).toBe('View messages — action required')
    const badge = wrapper.find('[data-testid="messages-badge"]')
    expect(badge.attributes('title')).toBe('1 message(s) need your action')
  })

  it('keeps the plain aria-label when action_required_unread is 0', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ messages_waiting_count: 3, action_required_unread: 0 }),
      now: NOW_MS,
    })
    const btn = wrapper.find('.message-count-button')
    expect(btn.attributes('aria-label')).toBe('View messages')
  })
})


describe('AgentRow — duration formatting via now prop', () => {
  it('shows "---" when agent has no duration_seconds and no working_started_at', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'waiting', duration_seconds: null, working_started_at: null }),
      now: NOW_MS,
    })
    const cell = wrapper.find('[data-testid="duration"]')
    expect(cell.text()).toBe('---')
  })

  it('shows backend duration for terminal status (complete)', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'complete', duration_seconds: 75, working_started_at: null }),
      now: NOW_MS,
    })
    const cell = wrapper.find('[data-testid="duration"]')
    expect(cell.text()).toBe('1m 15s')
  })

  it('ticks live duration from working_started_at when status is working', async () => {
    const startedAt = new Date(NOW_MS - 5000).toISOString()
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'working', working_started_at: startedAt, duration_seconds: null }),
      now: NOW_MS,
    })
    const cell = wrapper.find('[data-testid="duration"]')
    expect(cell.text()).toBe('5s')
  })

  it('displays seconds for short durations', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'complete', duration_seconds: 45 }),
      now: NOW_MS,
    })
    expect(wrapper.find('[data-testid="duration"]').text()).toBe('45s')
  })

  it('displays hours+minutes for long durations', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'complete', duration_seconds: 3 * 3600 + 25 * 60 }),
      now: NOW_MS,
    })
    expect(wrapper.find('[data-testid="duration"]').text()).toBe('3h 25m')
  })
})


describe('AgentRow — action emits', () => {
  it('emits "messages" with agent when messages button is clicked', async () => {
    const agent = makeAgent()
    const wrapper = await mountRow({ agent, now: NOW_MS })
    await wrapper.find('[data-testid="jobs-messages-btn"]').trigger('click')
    const emitted = wrapper.findComponent(AgentRow).emitted('messages')
    expect(emitted).toBeTruthy()
    expect(emitted[0][0]).toEqual(agent)
  })

  it('emits "agent-role" with agent when role button is clicked', async () => {
    const agent = makeAgent()
    const wrapper = await mountRow({ agent, now: NOW_MS })
    await wrapper.find('[data-testid="jobs-role-btn"]').trigger('click')
    const emitted = wrapper.findComponent(AgentRow).emitted('agent-role')
    expect(emitted).toBeTruthy()
    expect(emitted[0][0]).toEqual(agent)
  })

  it('emits "agent-job" with agent when info button is clicked', async () => {
    const agent = makeAgent()
    const wrapper = await mountRow({ agent, now: NOW_MS })
    await wrapper.find('[data-testid="jobs-info-btn"]').trigger('click')
    const emitted = wrapper.findComponent(AgentRow).emitted('agent-job')
    expect(emitted).toBeTruthy()
    expect(emitted[0][0]).toEqual(agent)
  })

  it('emits "stop-project" (no payload) when stop button is clicked for orchestrator + working', async () => {
    const agent = makeAgent({ agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'working' })
    const wrapper = await mountRow({ agent, now: NOW_MS })
    await wrapper.find('[data-testid="jobs-stop-btn"]').trigger('click')
    const emitted = wrapper.findComponent(AgentRow).emitted('stop-project')
    expect(emitted).toBeTruthy()
  })

  it('does NOT render stop button for non-orchestrator agent', async () => {
    const agent = makeAgent({ agent_name: 'implementer', agent_display_name: 'implementer', status: 'working' })
    const wrapper = await mountRow({ agent, now: NOW_MS })
    expect(wrapper.find('[data-testid="jobs-stop-btn"]').exists()).toBe(false)
  })

  it('emits "play" with agent when copy-prompt button is clicked', async () => {
    const agent = makeAgent({ status: 'waiting' })
    const wrapper = await mountRow({ agent, now: NOW_MS, shouldShowCopy: true, playFaded: false })
    await wrapper.find('[aria-label="Copy agent prompt"]').trigger('click')
    const emitted = wrapper.findComponent(AgentRow).emitted('play')
    expect(emitted).toBeTruthy()
    expect(emitted[0][0]).toEqual(agent)
  })

  it('emits "reactivate-play" with agent when re-copy prompt button is clicked', async () => {
    const agent = makeAgent({ status: 'working' })
    const wrapper = await mountRow({ agent, now: NOW_MS, shouldShowCopy: true, playFaded: true })
    await wrapper.find('[aria-label="Re-copy prompt"]').trigger('click')
    const emitted = wrapper.findComponent(AgentRow).emitted('reactivate-play')
    expect(emitted).toBeTruthy()
    expect(emitted[0][0]).toEqual(agent)
  })

  it('emits "handover" with agent when hand-over button is clicked', async () => {
    const agent = makeAgent({ agent_display_name: 'orchestrator', status: 'working' })
    const wrapper = await mountRow({ agent, now: NOW_MS })
    await wrapper.find('[aria-label="Hand over session"]').trigger('click')
    const emitted = wrapper.findComponent(AgentRow).emitted('handover')
    expect(emitted).toBeTruthy()
    expect(emitted[0][0]).toEqual(agent)
  })

  it('emits "steps" with agent when steps-trigger button is clicked', async () => {
    const agent = makeAgent({ steps: { completed: 1, total: 3 } })
    const wrapper = await mountRow({ agent, now: NOW_MS })
    await wrapper.find('[data-testid="steps-trigger"]').trigger('click')
    const emitted = wrapper.findComponent(AgentRow).emitted('steps')
    expect(emitted).toBeTruthy()
    expect(emitted[0][0]).toEqual(agent)
  })
})


describe('AgentRow — required testid and attribute presence', () => {
  it('renders agent-row testid on the <tr>', async () => {
    const wrapper = await mountRow({
      agent: makeAgent(),
      now: NOW_MS,
    })
    expect(wrapper.find('[data-testid="agent-row"]').exists()).toBe(true)
  })

  it('sets data-agent-display-name on <tr>', async () => {
    const agent = makeAgent({ agent_display_name: 'my-agent' })
    const wrapper = await mountRow({ agent, now: NOW_MS })
    const tr = wrapper.find('[data-testid="agent-row"]')
    expect(tr.attributes('data-agent-display-name')).toBe('my-agent')
  })

  it('sets data-agent-status on <tr>', async () => {
    const agent = makeAgent({ status: 'blocked' })
    const wrapper = await mountRow({ agent, now: NOW_MS })
    const tr = wrapper.find('[data-testid="agent-row"]')
    expect(tr.attributes('data-agent-status')).toBe('blocked')
  })

  it('renders steps-trigger when steps data is present', async () => {
    const agent = makeAgent({ steps: { completed: 2, total: 5, skipped: 0 } })
    const wrapper = await mountRow({ agent, now: NOW_MS })
    expect(wrapper.find('[data-testid="steps-trigger"]').exists()).toBe(true)
  })
})


describe('AgentRow — isolated-PR hand-off (BE-8003j)', () => {
  it('shows a PR link when the completion result carries a pr_url', async () => {
    const prUrl = 'https://gitea.internal/org/repo/pulls/42'
    const agent = makeAgent({
      agent_name: 'implementer',
      agent_display_name: 'web-coder-1',
      status: 'complete',
      result: { pr_url: prUrl, branch: 'feat/x' },
    })
    const wrapper = await mountRow({ agent, now: NOW_MS })
    const link = wrapper.find('[data-testid="jobs-pr-link"]')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe(prUrl)
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toContain('noopener')
  })

  it('omits the PR link when there is no result or pr_url', async () => {
    const noResult = await mountRow({ agent: makeAgent({ status: 'complete' }), now: NOW_MS })
    expect(noResult.find('[data-testid="jobs-pr-link"]').exists()).toBe(false)

    const branchOnly = await mountRow({
      agent: makeAgent({ status: 'complete', result: { branch: 'feat/x' } }),
      now: NOW_MS,
    })
    expect(branchOnly.find('[data-testid="jobs-pr-link"]').exists()).toBe(false)
  })

  it('ignores a blank pr_url', async () => {
    const wrapper = await mountRow({
      agent: makeAgent({ status: 'complete', result: { pr_url: '   ' } }),
      now: NOW_MS,
    })
    expect(wrapper.find('[data-testid="jobs-pr-link"]').exists()).toBe(false)
  })
})
