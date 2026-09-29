import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobsBoardDetailModal from './JobsBoardDetailModal.vue'

const vuetify = createVuetify()
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/projects/:projectId', name: 'ProjectLaunch', component: { template: '<div />' } },
  ],
})

const project = {
  id: '4b2179e3-b1db-4bc5-b01a-720ab8851829',
  taxonomy_alias: 'BE-6177',
  name: 'Archive refuses without a closeout entry',
}
const agents = [
  {
    agent_id: '5c15df26-1bd2-40cd-b155-419cadda28d8',
    job_id: '3e900a9d-f3b6-4be8-a85e-fd797a186116',
    agent_display_name: 'orchestrator',
    status: 'closed',
    steps: { completed: 5, total: 5 },
    duration_seconds: 4320,
    messages_waiting_count: 0,
  },
  {
    agent_id: '9665e646-2db4-418e-b2a1-8b783dc1e3bb',
    job_id: '7de4d4df-2b8f-42f7-89cd-cf4934a9217d',
    agent_display_name: 'implementer',
    status: 'complete',
    steps: { completed: 6, total: 6 },
    duration_seconds: 3480,
    messages_waiting_count: 0,
  },
]

function mountModal(props = {}) {
  return mount(JobsBoardDetailModal, {
    props: { modelValue: true, project, agents, now: Date.now(), ...props },
    global: { plugins: [vuetify, router] },
  })
}

beforeEach(() => {
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
  Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
})

describe('JobsBoardDetailModal', () => {

  it('hides the review strip when the project is NOT ready for review (FE-9550)', () => {
    const wrapper = mountModal({
      project: { id: 'p-staged', taxonomy_alias: 'INF-6176', name: 'Staged work', status: 'active', implementation_launched_at: null },
      agents: [{ agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'waiting' }],
    })
    expect(wrapper.find('[data-testid="jb-review-strip"]').exists()).toBe(false)
  })

  it('shows the review strip when every agent is terminal (FE-9550)', () => {
    const wrapper = mountModal({
      project: { id: 'p-done', taxonomy_alias: 'BE-6177', name: 'Finished work', status: 'active', implementation_launched_at: '2026-08-31T04:29:00Z' },
      agents: [
        { agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'closed' },
        { agent_name: 'implementer-backend', agent_display_name: 'implementer-backend', status: 'closed' },
      ],
    })
    expect(wrapper.find('[data-testid="jb-review-strip"]').exists()).toBe(true)
  })
  it('renders one row per agent with FULL, untruncated Agent ID and Job ID', () => {
    const wrapper = mountModal()
    const rows = wrapper.findAll('[data-testid="jb-detail-row"]')
    expect(rows).toHaveLength(2)

    const agentIds = wrapper.findAll('[data-testid="jb-detail-agent-id"]').map((n) => n.text())
    const jobIds = wrapper.findAll('[data-testid="jb-detail-job-id"]').map((n) => n.text())
    expect(agentIds).toContain('5c15df26-1bd2-40cd-b155-419cadda28d8')
    expect(jobIds).toContain('3e900a9d-f3b6-4be8-a85e-fd797a186116')
    expect(agentIds[0]).not.toContain('…')
    expect(agentIds[0].length).toBe(36)
  })

  it('copy buttons write the full ID to the clipboard and show a checkmark', async () => {
    const wrapper = mountModal()
    const copyBtn = wrapper.findAll('[data-testid="jb-detail-copy-agent"]')[0]
    await copyBtn.trigger('click')
    await Promise.resolve()
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('5c15df26-1bd2-40cd-b155-419cadda28d8')
    await wrapper.vm.$nextTick()
    expect(copyBtn.classes()).toContain('jb-copy-btn--done')
  })

  it('the review strip opens the closeout on the board, the same flow, no navigation', async () => {
    const wrapper = mountModal()
    expect(wrapper.find('[data-testid="jb-review-strip"]').text()).toContain('Review and close it here')
    const btn = wrapper.find('[data-testid="jb-review-strip-btn"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('Review and close')
    await btn.trigger('click')
    expect(wrapper.emitted('open-closeout')).toHaveLength(1)
  })

  it('uses the shared .agent-badge-sq and .msg-badge classes, not bespoke ones', () => {
    const wrapper = mountModal()
    const badges = wrapper.findAll('[data-testid="jb-detail-row"] .agent-badge-sq')
    expect(badges.length).toBe(2)

    const msgCells = wrapper.findAll('.msg-badge')
    expect(msgCells.length).toBe(2)
    expect(msgCells[0].classes()).toContain('zero')
  })

  it('the copy buttons render mdi-content-copy, switching to mdi-check once copied', async () => {
    const wrapper = mountModal()
    const copyBtn = wrapper.findAll('[data-testid="jb-detail-copy-agent"]')[0]
    expect(copyBtn.text()).toBe('mdi-content-copy')

    await copyBtn.trigger('click')
    await Promise.resolve()
    await wrapper.vm.$nextTick()
    expect(copyBtn.text()).toBe('mdi-check')
  })

  it('closing emits update:modelValue false', async () => {
    const wrapper = mountModal()
    await wrapper.find('[data-testid="jb-detail-close"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
  })
})
