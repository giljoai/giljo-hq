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
})
