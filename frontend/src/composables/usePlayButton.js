import { ref } from 'vue'
import { api } from '@/services/api'
import { useToast } from '@/composables/useToast'
import { shouldShowLaunchAction } from '@/utils/actionConfig'
import { isSubagentExecutionMode } from '@/composables/useExecutionMode'

export function usePlayButton(project, getProjectState, clipboardCopy) {
  const { showToast } = useToast()

  const reactivatedAgents = ref(new Set())

  function _getProject() {
    return project?.value ?? project
  }

  function shouldShowCopyButton(agent) {
    const proj = _getProject()
    const projectId = proj?.project_id || proj?.id
    const state = getProjectState(projectId)
    if (!state?.stagingComplete) return false

    const executionMode = state?.execution_mode ?? proj?.execution_mode
    const claudeCodeCliMode = isSubagentExecutionMode(executionMode)

    return shouldShowLaunchAction(agent, claudeCodeCliMode)
  }

  function isPlayButtonFaded(agent) {
    const jobId = agent.job_id || agent.agent_id
    if (reactivatedAgents.value.has(jobId)) return false
    return agent.status !== 'waiting'
  }

  function reactivatePlay(agent) {
    const jobId = agent.job_id || agent.agent_id
    reactivatedAgents.value.add(jobId)
  }

  async function handlePlay(agent) {
    const jobId = agent.job_id || agent.agent_id
    reactivatedAgents.value.delete(jobId)

    const proj = _getProject()

    try {
      if (agent.agent_display_name === 'orchestrator') {
        const projectId = proj?.project_id || proj?.id
        const storeState = getProjectState(projectId)
        const executionMode = storeState?.execution_mode ?? proj?.execution_mode
        const isCliMode = isSubagentExecutionMode(executionMode)

        try {
          await api.projects.launchImplementation(projectId)
        } catch (gateError) {
          console.warn(
            '[usePlayButton] launch-implementation call failed (non-blocking):',
            gateError
          )
        }

        let response
        try {
          response = await api.prompts.implementation(projectId)
        } catch (error) {
          _handleImplementationFetchError(error)
          return
        }

        const prompt = response?.data?.prompt
        const clipboardOk = await clipboardCopy(prompt)
        if (!clipboardOk) {
          showToast({
            message: 'Browser blocked clipboard access. Copy from the dialog manually.',
            type: 'error',
            timeout: 6000,
          })
          return
        }

        const agentCount = response?.data?.agent_count ?? 0
        const successMsg = isCliMode
          ? `Implementation prompt copied. ${agentCount + 1} jobs ready to launch (1 orchestrator, ${agentCount} specialists).`
          : `Orchestrator prompt copied. ${agentCount} specialists ready to launch.`
        showToast({ message: successMsg, type: 'success', timeout: 5000 })
        return
      }

      const response = await api.prompts.agentPrompt(agent.agent_id || agent.job_id)
      const promptText = response.data?.prompt || ''

      if (!promptText) {
        throw new Error('No prompt text returned')
      }

      await _copyPrompt(promptText)
      const role = _titleCaseRole(agent.agent_display_name)
      showToast({ message: `${role} prompt copied. Paste in a fresh terminal to bring this specialist online.`, type: 'success', timeout: 3000 })
    } catch (error) {
      console.error('[usePlayButton] Failed to prepare launch prompt:', error)
      const msg = error.response?.data?.detail || error.message || 'Failed to prepare launch prompt'
      showToast({ message: msg, type: 'error', timeout: 5000 })
    }
  }

  function _titleCaseRole(name) {
    if (!name) return 'Specialist'
    return String(name).replace(/\b\w/g, (c) => c.toUpperCase())
  }

  async function _copyPrompt(text) {
    const success = await clipboardCopy(text)
    if (!success) {
      throw new Error('Clipboard copy failed')
    }
  }

  function _handleImplementationFetchError(error) {
    const status = error?.response?.status
    const payload = error?.response?.data
    console.warn(
      '[usePlayButton] Implementation prompt fetch failed:',
      { status, payload, error }
    )

    const statusLabel = status ? `HTTP ${status}` : 'Network error'
    const hint =
      'Make sure staging is complete and at least one agent has launched. ' +
      'Refresh the dashboard and try again.'
    showToast({
      message: `Couldn't copy implementation prompt (${statusLabel}). ${hint}`,
      type: 'error',
      timeout: 7000,
    })
  }

  return {
    reactivatedAgents,
    shouldShowCopyButton,
    isPlayButtonFaded,
    reactivatePlay,
    handlePlay,
  }
}
