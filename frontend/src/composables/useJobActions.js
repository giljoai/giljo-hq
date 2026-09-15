import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useProjectBoundThread } from '@/composables/useProjectBoundThread'

export function useJobActions(getJob) {
  const { showToast } = useToast()
  const router = useRouter()
  const { resolveExistingProjectThread } = useProjectBoundThread()

  const showAgentDetailsModal = ref(false)
  const showAgentJobModal = ref(false)
  const showHandoverModal = ref(false)
  const handoverData = ref({ retirement_prompt: '', continuation_prompt: '' })
  const jobModalInitialTab = ref('mission')
  const selectedJobId = ref(null)

  const selectedAgent = computed(() => getJob(selectedJobId.value))

  async function handleMessages(agent, projectIdOverride = null) {
    selectedJobId.value = agent.job_id || agent.agent_id
    const projectId = projectIdOverride || agent.project_id || null
    const bound = projectId ? await resolveExistingProjectThread(projectId) : null
    if (!bound) {
      router.push({ name: 'Hub', query: { tab: 'project' } })
      showToast({ message: 'No project thread yet for this agent.', type: 'info', timeout: 4000 })
      return
    }
    router.push({ name: 'Hub', query: { thread: bound.thread_id, tab: 'project' } })
  }

  function handleStepsClick(agent) {
    if (
      !agent.steps ||
      typeof agent.steps.completed !== 'number' ||
      typeof agent.steps.total !== 'number'
    ) {
      return
    }

    selectedJobId.value = agent.job_id || agent.agent_id
    jobModalInitialTab.value = 'plan'
    showAgentJobModal.value = true
  }

  function handleAgentRole(agent) {
    selectedJobId.value = agent.job_id || agent.agent_id
    showAgentDetailsModal.value = true
  }

  function handleAgentJob(agent) {
    selectedJobId.value = agent.job_id || agent.agent_id
    jobModalInitialTab.value = 'mission'
    showAgentJobModal.value = true
  }

  async function handleHandOver(agent) {
    try {
      const jobId = agent.job_id || agent.agent_id
      const response = await api.agentJobs.simpleHandover(jobId)

      if (response.data.success) {
        handoverData.value = {
          retirement_prompt: response.data.retirement_prompt,
          continuation_prompt: response.data.continuation_prompt,
        }
        showHandoverModal.value = true
      } else {
        throw new Error(response.data.error || 'Session refresh failed')
      }
    } catch (error) {
      console.error('[useJobActions] Hand over failed:', error)
      const msg = error.response?.data?.detail || error.message || 'Hand over failed'
      showToast({ message: msg, type: 'error', timeout: 5000 })
    }
  }

  async function handleStopProject(projectId, clipboardCopy) {
    try {
      const response = await api.prompts.termination(projectId)

      if (response.data.prompt) {
        const copyOk = await clipboardCopy(response.data.prompt)
        if (!copyOk) throw new Error('Clipboard copy failed')

        showToast({
          message: `Termination prompt copied. Paste to stop all ${response.data.agent_count} agents and save progress.`,
          type: 'warning',
          timeout: 8000,
        })
      } else {
        throw new Error('No prompt returned')
      }
    } catch (error) {
      console.error('[useJobActions] Stop project failed:', error)
      const msg = error.response?.data?.detail || error.message || 'Failed to generate termination prompt'
      showToast({ message: msg, type: 'error', timeout: 5000 })
    }
  }

  return {
    showAgentDetailsModal,
    showAgentJobModal,
    showHandoverModal,
    handoverData,
    jobModalInitialTab,
    selectedJobId,
    selectedAgent,
    handleMessages,
    handleStepsClick,
    handleAgentRole,
    handleAgentJob,
    handleHandOver,
    handleStopProject,
  }
}
