import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ApprovalCard from '@/components/orchestration/ApprovalCard.vue'
import api from '@/services/api'
import { useApprovalsStore } from '@/stores/useApprovalsStore'

let pinia

const baseApproval = {
  id: 'appr-123',
  agent_display_name: 'orchestrator',
  job_id: 'job-abc',
  reason: 'Deferred findings need a call',
  context: { findings: 2, project: 'demo' },
  options: [
    { id: 'continue', label: 'Continue closeout' },
    { id: 'pause', label: 'Pause for rework' },
  ],
}

function mountCard(overrides = {}) {
  return mount(ApprovalCard, {
    props: { approval: { ...baseApproval, ...overrides } },
    global: { plugins: [pinia] },
  })
}

describe('ApprovalCard.vue (FE-5017 Phase C)', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.clearAllMocks()
    const store = useApprovalsStore()
    store.upsertApproval(baseApproval)
  })

  it('renders the reason as the title', () => {
    const wrapper = mountCard()
    expect(wrapper.text()).toContain('Deferred findings need a call')
  })

  it('renders one button per option, with stable test ids', () => {
    const wrapper = mountCard()
    const buttons = wrapper.findAll('[data-testid^="approval-option-"]')
    expect(buttons).toHaveLength(2)
    expect(wrapper.find('[data-testid="approval-option-continue"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="approval-option-pause"]').exists()).toBe(true)
  })

  it('marks the first option as primary, others as text', () => {
    const wrapper = mountCard()
    const primary = wrapper.find('[data-testid="approval-option-continue"]')
    const secondary = wrapper.find('[data-testid="approval-option-pause"]')
    expect(primary.attributes('variant')).toBe('flat')
    expect(primary.attributes('color')).toBe('primary')
    expect(secondary.attributes('variant')).toBe('text')
    expect(secondary.attributes('color')).toBeUndefined()
  })

  it('renders context entries when provided', () => {
    const wrapper = mountCard()
    expect(wrapper.text()).toContain('findings')
    expect(wrapper.text()).toContain('2')
    expect(wrapper.text()).toContain('project')
    expect(wrapper.text()).toContain('demo')
  })

  it('renders no context section when context is empty/null', () => {
    const wrapper = mountCard({ context: null })
    expect(wrapper.find('.approval-card__context').exists()).toBe(false)
  })

  it('POSTs to api.approvals.decide with the correct (id, optionId) on click', async () => {
    api.approvals.decide.mockResolvedValueOnce({
      data: {
        approval_id: baseApproval.id,
        status: 'decided',
        decided_option_id: 'continue',
        job_id: 'job-abc',
        project_id: 'p',
      },
    })

    const wrapper = mountCard()
    await wrapper.find('[data-testid="approval-option-continue"]').trigger('click')
    await flushPromises()

    expect(api.approvals.decide).toHaveBeenCalledWith(baseApproval.id, 'continue')
  })

  it('leaves the approval row in the store after decide (WS event handles removal)', async () => {
    api.approvals.decide.mockResolvedValueOnce({
      data: {
        approval_id: baseApproval.id,
        status: 'decided',
        decided_option_id: 'continue',
        job_id: 'job-abc',
        project_id: 'p',
      },
    })

    const store = useApprovalsStore()
    expect(store.approvalsById.has(baseApproval.id)).toBe(true)

    const wrapper = mountCard()
    await wrapper.find('[data-testid="approval-option-continue"]').trigger('click')
    await flushPromises()

    expect(store.approvalsById.has(baseApproval.id)).toBe(true)
  })

  it('emits "decided" with the chosen option on success', async () => {
    api.approvals.decide.mockResolvedValueOnce({
      data: {
        approval_id: baseApproval.id,
        status: 'decided',
        decided_option_id: 'pause',
        job_id: 'job-abc',
        project_id: 'p',
      },
    })

    const wrapper = mountCard()
    await wrapper.find('[data-testid="approval-option-pause"]').trigger('click')
    await flushPromises()

    const events = wrapper.emitted('decided')
    expect(events).toBeTruthy()
    expect(events[0][0]).toMatchObject({ approvalId: baseApproval.id, optionId: 'pause' })
  })

  it('shows an error and emits "error" when decide rejects', async () => {
    api.approvals.decide.mockRejectedValueOnce({
      response: { status: 409, data: { error_code: 'PROJECTSTATEERROR', message: 'Already decided' } },
    })

    const wrapper = mountCard()
    await wrapper.find('[data-testid="approval-option-continue"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('.approval-card__error').exists()).toBe(true)
    expect(wrapper.text()).toContain('Already decided')
    expect(wrapper.emitted('error')).toBeTruthy()
  })

  it('exposes role="alert" for screen-reader announceability', () => {
    const wrapper = mountCard()
    expect(wrapper.attributes('role')).toBe('alert')
    expect(wrapper.attributes('aria-live')).toBe('polite')
  })
})
