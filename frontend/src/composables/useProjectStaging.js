import { ref, isRef } from 'vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useClipboard } from '@/composables/useClipboard'
import { parseErrorResponse } from '@/utils/errorMessages'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { useProjectTabsStore } from '@/stores/projectTabs'
import { launchThenCopyImplementationPrompt } from '@/composables/usePlayButton'

export function useProjectStaging({ projectId, executionMode, isProjectStaged, readyToLaunch, canRestage = null }) {
  const { showToast } = useToast()
  const { copy: clipboardCopy } = useClipboard()
  const projectStateStore = useProjectStateStore()
  const tabsStore = useProjectTabsStore()

  const loadingStageProject = ref(false)

  const launchSuccessCallbacks = []
  function onLaunchSuccess(cb) {
    launchSuccessCallbacks.push(cb)
  }

  function showError(message) {
    showToast({ message: message || 'Unexpected error', type: 'error' })
  }

  const _platformToTool = {
    multi_terminal: 'claude-code',
    subagent: 'claude-code',
    claude_code_cli: 'claude-code',
    codex_cli: 'codex',
    gemini_cli: 'claude-code',
    antigravity_cli: 'claude-code',
  }

  const _pasteLabels = {
    multi_terminal: 'Orchestrator brief copied. Paste into any terminal to stage the project.',
    subagent: 'Orchestrator brief copied. Paste into your subagent orchestrator session to stage the project.',
    claude_code_cli: 'Orchestrator brief copied. Paste into Claude Code CLI to stage the project.',
    codex_cli: 'Orchestrator brief copied. Paste into Codex CLI to stage the project.',
    gemini_cli: 'Orchestrator brief copied. Paste into your subagent orchestrator session to stage the project.',
    antigravity_cli: 'Orchestrator brief copied. Paste into your subagent orchestrator session to stage the project.',
  }

  async function handleStageProject() {
    loadingStageProject.value = true

    try {
      const pid = projectId.value
      if (!pid) {
        throw new Error('Project missing ID')
      }

      const currentMode = executionMode.value
      const response = await api.prompts.staging(pid, {
        tool: _platformToTool[currentMode] || 'claude-code',
        execution_mode: currentMode,
      })

      if (!response.data?.prompt) {
        throw new Error('Invalid response from staging endpoint')
      }

      const { prompt } = response.data

      projectStateStore.setIsStaged(pid, true)

      const copied = await clipboardCopy(prompt)

      if (copied) {
        showToast({ message: _pasteLabels[currentMode] || _pasteLabels.multi_terminal, type: 'success' })
      } else {
        showToast({ message: 'Copy failed. Check your browser\'s clipboard permissions and try again.', type: 'warning' })
      }
    } catch (error) {
      console.error('Stage project failed:', error)

      const errorMsg = parseErrorResponse(error).message || 'Failed to stage project'

      if (errorMsg.toLowerCase().includes('orchestrator already exists')) {
        showToast({ message: 'An orchestrator is already active for this project. The existing orchestrator will be reused.', type: 'info' })
      } else if (error.response?.status === 409 && errorMsg.toLowerCase().includes('execution mode')) {
        showToast({ message: 'Please select an execution mode before staging.', type: 'warning' })
      } else {
        showError(errorMsg)
      }
    } finally {
      loadingStageProject.value = false
    }
  }

  async function handleUnstageProject() {
    try {
      await projectStateStore.unstageProject(projectId.value)
      showToast({
        message: 'Project unstaged. You can change execution mode and stage again.',
        type: 'success',
      })
    } catch (error) {
      console.error('Unstage failed:', error)
      const msg = parseErrorResponse(error).message || 'Failed to unstage project'
      showError(msg)
    }
  }

  async function handleRestageProject() {
    try {
      await projectStateStore.restageProject(projectId.value)
      showToast({
        message: 'Project recovery complete. Execution mode unlocked — you can re-stage with a new mode.',
        type: 'success',
      })
    } catch (error) {
      console.error('Restage failed:', error)
      const msg = parseErrorResponse(error).message || 'Failed to recover project staging'
      showError(msg)
    }
  }

  function _canRestage() {
    if (canRestage === null || canRestage === undefined) return false
    return isRef(canRestage) ? canRestage.value : Boolean(canRestage)
  }

  async function handleStageOrRestage() {
    if (isProjectStaged.value) {
      await handleUnstageProject()
    } else if (_canRestage()) {
      await handleRestageProject()
    } else {
      await handleStageProject()
    }
  }

  async function handleLaunchJobs(project) {
    try {
      if (!readyToLaunch.value) {
        showError('Project not ready to launch')
        return
      }

      const launched = await launchThenCopyImplementationPrompt({
        projectId: projectId.value,
        executionMode: executionMode?.value,
        clipboardCopy,
        showToast,
      })
      if (!launched) return
      await api.orchestrator.launchProject({ project_id: projectId.value })
      tabsStore.isLaunched = true
      tabsStore.currentProject = project
      projectStateStore.setLaunched(projectId.value, true)

      for (const cb of launchSuccessCallbacks) {
        cb()
      }
    } catch (error) {
      console.error('Launch jobs failed:', error)
      const msg = parseErrorResponse(error).message || 'Failed to launch jobs'
      showError(msg)
    }
  }

  return {
    loadingStageProject,
    handleStageProject,
    handleUnstageProject,
    handleRestageProject,
    handleStageOrRestage,
    handleLaunchJobs,
    onLaunchSuccess,
  }
}
