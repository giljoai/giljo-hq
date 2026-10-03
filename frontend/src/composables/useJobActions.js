import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { useProjectBoundThread } from '@/composables/useProjectBoundThread'

export function useJobActions(getJob) {
  const { showToast } = useToast()
  const router = useRouter()
  const { resolveExistingProjectThread } = useProjectBoundThread()

  const showAgentDetailsModal = ref(false)
  const showAgentJobModal = ref(false)
  const jobModalInitialTab = ref('mission')
  const selectedJobId = ref(null)

  const selectedAgent = computed(() => getJob(selectedJobId.value))

  async function handleMessages(agent, projectIdOverride = null) {
    selectedJobId.value = agent.job_id || agent.agent_id
    const projectId = projectIdOverride || agent.project_id || null
    const bound = projectId ? await resolveExistingProjectThread(projectId) : null
    if (!bound) {
      router.push({ name: 'Hub', query: { tab: 'project' } })
      showToast({ message: 'No project thread yet for this agent.', type: 'info' })
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

  return {
    showAgentDetailsModal,
    showAgentJobModal,
    jobModalInitialTab,
    selectedJobId,
    selectedAgent,
    handleMessages,
    handleStepsClick,
    handleAgentRole,
    handleAgentJob,
  }
}
