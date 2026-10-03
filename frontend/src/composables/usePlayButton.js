import { ref } from 'vue'
import { api } from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { shouldShowLaunchAction } from '@/utils/actionConfig'
import { isSubagentExecutionMode } from '@/composables/useExecutionMode'
import { parseErrorResponse } from '@/utils/errorMessages'

const DEFAULT_PLAY_TOOLTIP = 'Copy prompt'
export const REPLAY_LABEL = 'Re-issue the latest launch prompt after a disconnect or reboot'
const CLIPBOARD_BLOCKED = 'Browser blocked clipboard access. Copy from the dialog manually.'

function _implementationFetchError(error, showToast) {
  const status = error?.response?.status
  console.warn('[usePlayButton] Implementation prompt fetch failed:', {
    status,
    payload: error?.response?.data,
    error,
  })
  const statusLabel = status ? `HTTP ${status}` : 'Network error'
  showToast({
    message:
      `Couldn't copy implementation prompt (${statusLabel}). ` +
      'Make sure staging is complete and at least one agent has launched. Refresh the dashboard and try again.',
    type: 'error',
  })
}

export async function launchThenCopyImplementationPrompt({ projectId, executionMode, clipboardCopy, showToast }) {
  try {
    await api.projects.launchImplementation(projectId)
  } catch (gateError) {
    showToast({
      message: `Could not start implementation: ${parseErrorResponse(gateError).message || 'the server refused the launch.'}`,
      type: 'error',
    })
    return false
  }
  await _copyImplementationPrompt({ projectId, executionMode, clipboardCopy, showToast })
  return true
}

async function _copyImplementationPrompt({ projectId, executionMode, clipboardCopy, showToast, replay = false }) {
  let response
  try {
    response = await api.prompts.implementation(projectId)
  } catch (error) {
    _implementationFetchError(error, showToast)
    return false
  }
  const clipboardOk = await clipboardCopy(response?.data?.prompt)
  if (!clipboardOk) {
    showToast({ message: CLIPBOARD_BLOCKED, type: 'error' })
    return false
  }
  if (replay) {
    showToast({ message: 'Latest launch prompt copied. Paste it to reconnect.', type: 'success' })
    return true
  }
  const agentCount = response?.data?.agent_count ?? 0
  const message = isSubagentExecutionMode(executionMode)
    ? `Implementation prompt copied. ${agentCount + 1} jobs ready to launch (1 orchestrator, ${agentCount} specialists).`
    : `Orchestrator prompt copied. ${agentCount} specialists ready to launch.`
  showToast({ message, type: 'success' })
  return true
}

export function usePlayButton(project, getProjectState, clipboardCopy, chainCtx = null) {
  const { showToast } = useToast()
  const sequenceRunStore = useSequenceRunStore()

  const reactivatedAgents = ref(new Set())

  function _getProject() {
    return project?.value ?? project
  }

  function _projectId() {
    const proj = _getProject()
    return proj?.project_id || proj?.id
  }

  function _chainTabs() {
    const ctx = chainCtx?.value ?? chainCtx
    return ctx?.tabs || []
  }

  function _isChainMember(agent) {
    if (agent?.agent_display_name !== 'orchestrator') return false
    const pid = _projectId()
    return _chainTabs().some((tab) => tab.projectId === pid)
  }

  function _blockingPredecessorLabel() {
    const tabs = _chainTabs()
    const index = tabs.findIndex((tab) => tab.projectId === _projectId())
    if (index <= 0) return null
    const previous = tabs[index - 1]
    return previous.taxonomyAlias || previous.name || 'the previous project'
  }

  function shouldShowCopyButton(agent) {
    const proj = _getProject()
    const projectId = proj?.project_id || proj?.id
    const state = getProjectState(projectId)
    if (!state?.stagingComplete && !_isChainMember(agent)) return false

    const executionMode = state?.execution_mode ?? proj?.execution_mode
    const claudeCodeCliMode = isSubagentExecutionMode(executionMode)

    return shouldShowLaunchAction(agent, claudeCodeCliMode)
  }

  function isPlayButtonFaded(agent) {
    const jobId = agent.job_id || agent.agent_id
    if (reactivatedAgents.value.has(jobId)) return false
    if (_isChainMember(agent)) {
      if (!sequenceRunStore.isProjectStartable(_projectId())) return true
      return agent.status !== 'waiting'
    }
    if (agent?.agent_display_name === 'orchestrator') return true
    return agent.status !== 'waiting'
  }

  function playButtonTooltip(agent) {
    if (agent?.agent_display_name === 'orchestrator' && !_isChainMember(agent)) {
      return 'Start this project with Implement'
    }
    if (!_isChainMember(agent) || sequenceRunStore.isProjectStartable(_projectId())) {
      return DEFAULT_PLAY_TOOLTIP
    }
    const predecessor = _blockingPredecessorLabel()
    return predecessor ? `Starts after ${predecessor} closes out` : DEFAULT_PLAY_TOOLTIP
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
      if (_isChainMember(agent)) {
        await _handleChainMemberPlay()
        return
      }

      if (agent.agent_display_name === 'orchestrator') {
        const projectId = proj?.project_id || proj?.id
        const executionMode = getProjectState(projectId)?.execution_mode ?? proj?.execution_mode
        await launchThenCopyImplementationPrompt({ projectId, executionMode, clipboardCopy, showToast })
        return
      }

      const response = await api.prompts.agentPrompt(agent.agent_id || agent.job_id)
      const promptText = response.data?.prompt || ''

      if (!promptText) {
        throw new Error('No prompt text returned')
      }

      await _copyPrompt(promptText)
      const role = _titleCaseRole(agent.agent_display_name)
      showToast({ message: `${role} prompt copied. Paste in a fresh terminal to bring this specialist online.`, type: 'success' })
    } catch (error) {
      console.error('[usePlayButton] Failed to prepare launch prompt:', error)
      const msg = parseErrorResponse(error).message || 'Failed to prepare launch prompt'
      showToast({ message: msg, type: 'error' })
    }
  }

  async function _handleChainMemberPlay() {
    const projectId = _projectId()
    if (!sequenceRunStore.isProjectStartable(projectId)) return

    try {
      await api.projects.launchImplementation(projectId)
    } catch (gateError) {
      const msg = parseErrorResponse(gateError).message || 'Could not start this project.'
      showToast({ message: msg, type: 'error' })
      return
    }

    await _copyChainMemberPrompt(projectId, 'Orchestrator prompt copied. Paste it in a fresh session to run this project.')
  }

  async function _copyChainMemberPrompt(projectId, successMessage) {
    const { data } = await api.prompts.chainMember(projectId)
    const prompt = data?.prompt
    if (!prompt) throw new Error('No prompt text returned')

    const clipboardOk = await clipboardCopy(prompt)
    if (!clipboardOk) {
      showToast({ message: CLIPBOARD_BLOCKED, type: 'error' })
      return
    }
    showToast({ message: successMessage, type: 'success' })
  }

  function _projectLaunched() {
    const proj = _getProject()
    const state = getProjectState(_projectId())
    return Boolean(proj?.implementation_launched_at || state?.implementationLaunched || state?.isLaunched)
  }

  function canReplay(agent) {
    if (!isPlayButtonFaded(agent)) return false
    if (_isChainMember(agent)) return sequenceRunStore.isProjectStartable(_projectId()) && _projectLaunched()
    if (agent?.agent_display_name === 'orchestrator') return _projectLaunched()
    return true
  }

  async function handleReplay(agent) {
    const projectId = _projectId()
    try {
      if (_isChainMember(agent)) {
        await _copyChainMemberPrompt(projectId, 'Latest launch prompt copied. Paste it to reconnect.')
        return
      }
      if (agent?.agent_display_name === 'orchestrator') {
        await _copyImplementationPrompt({ projectId, clipboardCopy, showToast, replay: true })
        return
      }
      const response = await api.prompts.agentPrompt(agent.agent_id || agent.job_id)
      const promptText = response.data?.prompt || ''
      if (!promptText) throw new Error('No prompt text returned')
      await _copyPrompt(promptText)
      showToast({ message: 'Latest launch prompt copied. Paste it to reconnect.', type: 'success' })
    } catch (error) {
      console.error('[usePlayButton] Failed to re-issue launch prompt:', error)
      showToast({ message: parseErrorResponse(error).message || 'Failed to re-issue the launch prompt', type: 'error' })
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

  return {
    reactivatedAgents,
    shouldShowCopyButton,
    isPlayButtonFaded,
    playButtonTooltip,
    reactivatePlay,
    canReplay,
    handleReplay,
    handlePlay,
  }
}
