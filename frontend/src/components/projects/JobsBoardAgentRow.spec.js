import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import JobsBoardAgentRow from './JobsBoardAgentRow.vue'

const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

function mountRow(agent, now = Date.parse('2026-08-30T12:00:00Z')) {
  return mount(JobsBoardAgentRow, {
    props: { agent, now },
    global: { stubs: { 'v-tooltip': tooltipStub } },
  })
}

describe('JobsBoardAgentRow', () => {
  it('renders exactly badge, steps, duration, status, messages -- no visible name text', () => {
    const wrapper = mountRow({
      agent_id: 'e8312b95-4c1a-4f7e-b3d2-77a9e1c0d4f8',
      job_id: '69760e9d-2b11-4a03-9c5e-1f2d3a4b5c6d',
      agent_display_name: 'implementer',
      agent_name: 'implementer-backend',
      status: 'working',
      steps: { completed: 3, total: 4 },
      duration_seconds: 41,
      messages_waiting_count: 1,
    })

    expect(wrapper.find('[data-testid="jb-agent-badge"]').text()).toBe('IM')
    expect(wrapper.find('[data-testid="jb-agent-steps"]').text()).toContain('3')
    expect(wrapper.find('[data-testid="jb-agent-steps"]').text()).toContain('/4')
    expect(wrapper.find('[data-testid="jb-agent-status"]').text()).toBe('Working...')
    expect(wrapper.find('[data-testid="jb-agent-messages"]').text()).toBe('1')
    expect(wrapper.find('[data-testid="jb-agent-row"]').text()).not.toContain('implementer-backend')
  })

  it('shows "—" for steps when no numeric steps summary is present', () => {
    const wrapper = mountRow({ agent_display_name: 'orchestrator', status: 'staged' })
    expect(wrapper.find('[data-testid="jb-agent-steps"]').text()).toBe('—')
  })

  it('tints the messages pill using the shared .msg-badge classes, zero vs has-msgs', () => {
    const zero = mountRow({ agent_display_name: 'tester', status: 'complete', messages_waiting_count: 0 })
    expect(zero.find('[data-testid="jb-agent-messages"]').classes()).toContain('msg-badge')
    expect(zero.find('[data-testid="jb-agent-messages"]').classes()).toContain('zero')

    const nonZero = mountRow({ agent_display_name: 'tester', status: 'complete', messages_waiting_count: 2 })
    expect(nonZero.find('[data-testid="jb-agent-messages"]').classes()).toContain('msg-badge')
    expect(nonZero.find('[data-testid="jb-agent-messages"]').classes()).toContain('has-msgs')
    expect(nonZero.find('[data-testid="jb-agent-messages"]').classes()).not.toContain('zero')
  })

  it('the hover tooltip carries name and role, never the agent or job UUID', () => {
    const wrapper = mountRow({
      agent_id: 'e8312b95-4c1a-4f7e-b3d2-77a9e1c0d4f8',
      job_id: '69760e9d-2b11-4a03-9c5e-1f2d3a4b5c6d',
      agent_display_name: 'orchestrator',
      agent_name: 'Orchestrator',
      status: 'working',
    })
    const tooltip = wrapper.find('[data-testid="jb-agent-tooltip"]')
    expect(tooltip.text()).toContain('Orchestrator')
    expect(tooltip.text()).toContain('Fixed System Agent')
    expect(tooltip.text()).not.toContain('e8312b95-4c1a-4f7e-b3d2-77a9e1c0d4f8')
    expect(tooltip.text()).not.toContain('69760e9d-2b11-4a03-9c5e-1f2d3a4b5c6d')
  })

  it('uses the shared .agent-badge-sq--sm class instead of a bespoke badge', () => {
    const wrapper = mountRow({ agent_display_name: 'implementer', status: 'working' })
    const badge = wrapper.find('[data-testid="jb-agent-badge"]')
    expect(badge.classes()).toContain('agent-badge-sq')
    expect(badge.classes()).toContain('agent-badge-sq--sm')
  })

  it('never hardcodes a hex color -- badge and status styling resolve through getAgentBadgeStyle/getStatusColor', () => {
    const wrapper = mountRow({ agent_display_name: 'reviewer', status: 'blocked' })
    const badgeStyle = wrapper.find('[data-testid="jb-agent-badge"]').attributes('style')
    expect(badgeStyle).toMatch(/rgba\(/)
  })

  it('the small badge modifier uses the sharp radius token, not a hardcoded px', async () => {
    const { readFileSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const src = readFileSync(resolve(__dirname, '../../styles/main.scss'), 'utf8')
    const smBlock = src.match(/&--sm\s*\{([^}]*)\}/)?.[1] || ''
    expect(smBlock).toMatch(/border-radius:\s*\$border-radius-sharp/)
    expect(smBlock).not.toMatch(/border-radius:\s*5px/)
  })
})

const menuStub = {
  template: `<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>`,
}

function mountLiveRow(agent, props = {}) {
  return mount(JobsBoardAgentRow, {
    props: { agent, now: Date.parse('2026-08-30T12:00:00Z'), interactive: true, showCopy: true, ...props },
    global: { stubs: { 'v-tooltip': tooltipStub, 'v-menu': menuStub } },
  })
}

const LIVE_AGENT = {
  agent_id: 'a-im',
  job_id: 'j-im',
  agent_display_name: 'implementer',
  status: 'waiting',
  messages_waiting_count: 2,
}

describe('JobsBoardAgentRow (interactive, FE-9655c)', () => {
  it('a display-only row has no play, kebab or clickable messages', () => {
    const wrapper = mountRow(LIVE_AGENT)
    for (const id of ['jb-agent-play', 'jb-agent-recopy', 'jb-agent-kebab', 'jb-agent-messages-btn']) {
      expect(wrapper.find(`[data-testid="${id}"]`).exists()).toBe(false)
    }
  })

  it('keeps play and the messages badge visible; both emit', async () => {
    const wrapper = mountLiveRow(LIVE_AGENT)
    await wrapper.find('[data-testid="jb-agent-play"]').trigger('click')
    await wrapper.find('[data-testid="jb-agent-messages-btn"]').trigger('click')
    expect(wrapper.emitted('play')[0][0].job_id).toBe('j-im')
    expect(wrapper.emitted('messages')[0][0].job_id).toBe('j-im')
    expect(wrapper.find('[data-testid="jb-agent-messages"]').text()).toBe('2')
  })

  it('FE-9670d: a launched agent shows the replay control in the play slot, which emits replay', async () => {
    const wrapper = mountLiveRow(LIVE_AGENT, { playFaded: true, canReplay: true })
    expect(wrapper.find('[data-testid="jb-agent-play"]').exists()).toBe(false)
    await wrapper.find('[data-testid="jb-agent-recopy"]').trigger('click')
    expect(wrapper.emitted('replay')[0][0].job_id).toBe('j-im')
  })

  it('FE-9670d: a faded Play with no launch to re-issue stays a disabled Play, never a replay', () => {
    const wrapper = mountLiveRow(LIVE_AGENT, { playFaded: true, canReplay: false })
    expect(wrapper.find('[data-testid="jb-agent-recopy"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-agent-play"]').attributes('disabled')).toBeDefined()
  })

  it('no copy available: the play slot stays empty', () => {
    const wrapper = mountLiveRow(LIVE_AGENT, { showCopy: false })
    expect(wrapper.find('[data-testid="jb-agent-play"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="jb-agent-recopy"]').exists()).toBe(false)
  })

  it('the kebab holds View messages, View agent role, View assigned job; no PR item without a PR', async () => {
    const wrapper = mountLiveRow(LIVE_AGENT)
    expect(wrapper.find('[data-testid="jb-agent-kebab"]').exists()).toBe(true)
    const items = wrapper.findAll('[data-testid="jb-agent-menu"] .v-list-item')
    expect(items.map((i) => i.attributes('title'))).toEqual(['View messages', 'View agent role', 'View assigned job'])
    expect(wrapper.find('[data-testid="jb-agent-menu-pr"]').exists()).toBe(false)

    await wrapper.find('[data-testid="jb-agent-menu-role"]').trigger('click')
    await wrapper.find('[data-testid="jb-agent-menu-job"]').trigger('click')
    await wrapper.find('[data-testid="jb-agent-menu-messages"]').trigger('click')
    expect(wrapper.emitted('agent-role')).toHaveLength(1)
    expect(wrapper.emitted('agent-job')).toHaveLength(1)
    expect(wrapper.emitted('messages')).toHaveLength(1)
    expect(wrapper.text()).not.toMatch(/Hand over|Stop project/)
  })

  it('adds Open pull request when the job recorded a PR URL', () => {
    const wrapper = mountLiveRow({ ...LIVE_AGENT, result: { pr_url: 'http://example.test/pr/7' } })
    const pr = wrapper.find('[data-testid="jb-agent-menu-pr"]')
    expect(pr.exists()).toBe(true)
    expect(pr.attributes('href')).toBe('http://example.test/pr/7')
  })
})
