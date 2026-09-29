import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useJobActions } from './useJobActions'
import { useCommHubStore } from '@/stores/commHubStore'

const mockShowToast = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}))

const mockRouterPush = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockRouterPush }),
}))

describe('useJobActions', () => {
  let getJob

  beforeEach(() => {
    setActivePinia(createPinia())
    getJob = vi.fn(() => null)
    vi.clearAllMocks()
  })

  it('initializes with all modals closed', () => {
    const {
      showAgentDetailsModal,
      showAgentJobModal,
    } = useJobActions(getJob)

    expect(showAgentDetailsModal.value).toBe(false)
    expect(showAgentJobModal.value).toBe(false)
  })

  it('handleMessages deep-links to the project bound thread on the Project comms tab', async () => {
    const { handleMessages, selectedJobId } = useJobActions(getJob)
    const commHub = useCommHubStore()
    commHub._testSeedThread({ thread_id: 'thr-1', project_id: 'proj-1' })

    await handleMessages({ job_id: 'job-1', project_id: 'proj-1' })

    expect(selectedJobId.value).toBe('job-1')
    expect(mockRouterPush).toHaveBeenCalledWith({
      name: 'Hub',
      query: { thread: 'thr-1', tab: 'project' },
    })
  })

  it('handleMessages with no bound thread lands on the Project comms tab and informs the user', async () => {
    const { handleMessages, selectedJobId } = useJobActions(getJob)
    const commHub = useCommHubStore()
    commHub._testSeedThread({ thread_id: 'thr-x', project_id: 'other-proj' })

    await handleMessages({ job_id: 'job-2', agent_id: 'agent-2', project_id: 'proj-none' })

    expect(selectedJobId.value).toBe('job-2')
    expect(mockRouterPush).toHaveBeenCalledWith({ name: 'Hub', query: { tab: 'project' } })
    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'info' }))
  })

  it('handleStepsClick opens job modal on plan tab', () => {
    const { handleStepsClick, showAgentJobModal, jobModalInitialTab, selectedJobId } =
      useJobActions(getJob)

    handleStepsClick({ job_id: 'job-1', steps: { completed: 2, total: 5 } })

    expect(selectedJobId.value).toBe('job-1')
    expect(jobModalInitialTab.value).toBe('plan')
    expect(showAgentJobModal.value).toBe(true)
  })

  it('handleStepsClick does nothing when steps data invalid', () => {
    const { handleStepsClick, showAgentJobModal } = useJobActions(getJob)

    handleStepsClick({ job_id: 'job-1', steps: null })
    expect(showAgentJobModal.value).toBe(false)

    handleStepsClick({ job_id: 'job-1', steps: { completed: 'x', total: 5 } })
    expect(showAgentJobModal.value).toBe(false)
  })

  it('handleAgentRole opens agent details modal', () => {
    const { handleAgentRole, showAgentDetailsModal, selectedJobId } = useJobActions(getJob)

    handleAgentRole({ job_id: 'job-3' })

    expect(selectedJobId.value).toBe('job-3')
    expect(showAgentDetailsModal.value).toBe(true)
  })

  it('handleAgentJob opens job modal on mission tab', () => {
    const { handleAgentJob, showAgentJobModal, jobModalInitialTab, selectedJobId } =
      useJobActions(getJob)

    handleAgentJob({ job_id: 'job-4' })

    expect(selectedJobId.value).toBe('job-4')
    expect(jobModalInitialTab.value).toBe('mission')
    expect(showAgentJobModal.value).toBe(true)
  })

  it('selectedAgent delegates to getJob with selectedJobId', () => {
    const mockJob = { job_id: 'job-7', agent_display_name: 'implementer' }
    getJob = vi.fn((id) => (id === 'job-7' ? mockJob : null))

    const { selectedAgent, handleAgentRole } = useJobActions(getJob)
    handleAgentRole({ job_id: 'job-7' })

    expect(selectedAgent.value).toEqual(mockJob)
  })
})
