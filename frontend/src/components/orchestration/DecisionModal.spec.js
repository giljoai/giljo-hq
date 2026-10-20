import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DecisionModal from '@/components/orchestration/DecisionModal.vue'
import { useApprovalsStore } from '@/stores/useApprovalsStore'
import api from '@/services/api'

let pinia

const approval = {
  id: 'appr-1',
  job_id: 'job-1',
  agent_display_name: 'orchestrator',
  reason: 'Approve the Protected Zone edit?',
  context: { task_id: 'e8e118a5' },
  options: [{ id: 'approve', label: 'Approve' }],
  status: 'pending',
}

vi.mock('@/services/api', () => ({
  default: {
    approvals: {
      listPending: vi.fn().mockResolvedValue({ data: { items: [] } }),
      decide: vi.fn(),
    },
  },
}))

function mountModal(props = {}) {
  return mount(DecisionModal, {
    props: { show: true, orchestratorJobId: 'job-1', ...props },
    global: {
      plugins: [pinia],
      stubs: {
        'v-dialog': { template: '<div><slot /></div>' },
        'v-card': { template: '<div><slot /></div>' },
        'v-divider': true,
        'v-icon': true,
        'v-btn': {
          emits: ['click'],
          template: '<button @click="$emit(\'click\')"><slot /></button>',
        },
        'v-spacer': true,
      },
      directives: { draggable: {} },
    },
  })
}

describe('DecisionModal', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.clearAllMocks()
  })

  it('dialog title reads "Needs decision"', () => {
    const wrapper = mountModal()
    expect(wrapper.find('.dlg-title').text()).toBe('Needs decision')
  })

  it('renders ApprovalCard when an approval is in the store', () => {
    const store = useApprovalsStore()
    store.upsertApproval(approval)
    const wrapper = mountModal()
    expect(wrapper.find('[data-testid="decision-modal-card"]').exists()).toBe(true)
  })

  it('re-emits "approval-decided" when ApprovalCard signals "decided"', async () => {
    const store = useApprovalsStore()
    store.upsertApproval(approval)
    const wrapper = mountModal()
    const card = wrapper.findComponent({ name: 'ApprovalCard' })
    card.vm.$emit('decided', { approvalId: approval.id, optionId: 'approve' })
    await flushPromises()
    expect(wrapper.emitted('approval-decided')).toBeTruthy()
    expect(wrapper.emitted('approval-decided')[0][0]).toMatchObject({
      approvalId: approval.id,
      optionId: 'approve',
    })
  })

  it('emits "close" on Cancel click', async () => {
    const store = useApprovalsStore()
    store.upsertApproval(approval)
    const wrapper = mountModal()
    await wrapper.findAll('button').find((b) => b.text() === 'Cancel').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('hydrates pending approvals when show flips to true', async () => {
    api.approvals.listPending.mockClear()
    const wrapper = mountModal({ show: false })
    expect(api.approvals.listPending).not.toHaveBeenCalled()
    await wrapper.setProps({ show: true })
    await flushPromises()
    expect(api.approvals.listPending).toHaveBeenCalledTimes(1)
  })

  describe('never an empty modal (FE-9796)', () => {
    it('opening already-shown loads the pending decision and shows a loading state meanwhile', async () => {
      let resolve
      api.approvals.listPending.mockImplementationOnce(() => new Promise((r) => { resolve = r }))
      const wrapper = mountModal()
      await flushPromises()
      expect(api.approvals.listPending).toHaveBeenCalledTimes(1)
      expect(wrapper.find('[data-testid="decision-modal-loading"]').exists()).toBe(true)

      resolve({ data: { items: [approval] } })
      await flushPromises()
      expect(wrapper.find('[data-testid="decision-modal-loading"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="decision-modal-card"]').exists()).toBe(true)
    })

    it('a failed load shows the error and a Retry that loads again', async () => {
      api.approvals.listPending.mockRejectedValueOnce(new Error('timeout of 30000ms exceeded'))
      const wrapper = mountModal()
      await flushPromises()
      expect(wrapper.find('[data-testid="decision-modal-error"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="decision-modal-loading"]').exists()).toBe(false)

      api.approvals.listPending.mockResolvedValueOnce({ data: { items: [approval] } })
      await wrapper.find('[data-testid="decision-modal-retry"]').trigger('click')
      await flushPromises()
      expect(api.approvals.listPending).toHaveBeenCalledTimes(2)
      expect(wrapper.find('[data-testid="decision-modal-error"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="decision-modal-card"]').exists()).toBe(true)
    })

    it('a load that finds no pending decision for this job says so', async () => {
      api.approvals.listPending.mockResolvedValueOnce({ data: { items: [] } })
      const wrapper = mountModal()
      await flushPromises()
      expect(wrapper.find('[data-testid="decision-modal-card"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="decision-modal-empty"]').exists()).toBe(true)
    })

    it('after a decision the modal still closes through the parent as before', async () => {
      api.approvals.listPending.mockResolvedValueOnce({ data: { items: [approval] } })
      const wrapper = mountModal()
      await flushPromises()
      wrapper.findComponent({ name: 'ApprovalCard' }).vm.$emit('decided', { approvalId: approval.id, optionId: 'approve' })
      await flushPromises()
      expect(wrapper.emitted('approval-decided')).toHaveLength(1)
      await wrapper.setProps({ show: false })
      expect(api.approvals.listPending).toHaveBeenCalledTimes(1)
    })
  })
})
