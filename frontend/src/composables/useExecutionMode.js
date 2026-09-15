import { ref, computed } from 'vue'
import { useToast } from '@/composables/useToast'
import { useProjectStore } from '@/stores/projects'
import { useNotificationStore } from '@/stores/notifications'
import { notifyFailure } from '@/utils/notifyFailure'

const GENERIC_EXECUTION_MODE_FAILURE = 'Failed to save execution mode. Please try again.'

export const SUBAGENT_EXECUTION_MODES = ['claude_code_cli', 'codex_cli', 'gemini_cli', 'antigravity_cli', 'generic_mcp']

export function useExecutionMode({ projectId, missionText, isProjectStaged, isProjectStaging, initialMode = null }) {
  const { showToast } = useToast()
  const projectStore = useProjectStore()
  const notificationStore = useNotificationStore()

  const executionPlatform = ref(null)

  const executionMode = ref(initialMode ?? null)

  const executionModeSelected = computed(() => executionPlatform.value !== null)

  const isExecutionModeLocked = computed(
    () =>
      Boolean(executionMode.value) &&
      (Boolean(missionText.value) || isProjectStaged.value || isProjectStaging.value),
  )

  const isSubagentMode = computed(() => isSubagentExecutionMode(executionMode.value))

  const agenticTool = computed(() => {
    const mode = executionPlatform.value
    if (!mode) return null
    if (mode === 'multi_terminal') return { type: 'icon', icon: 'mdi-monitor-multiple', label: 'Multi Terminal', alt: 'Multi terminal mode active' }
    return { type: 'icon', icon: 'mdi-connection', label: 'Subagent', alt: 'Subagent mode active' }
  })

  const _modeLabels = {
    multi_terminal: 'Multi-Terminal mode enabled',
    subagent: 'Subagent mode enabled',
  }

  async function handleExecutionModeChange(newValue) {
    const previousValue = executionPlatform.value
    executionPlatform.value = newValue

    try {
      await projectStore.updateProject(projectId.value, { execution_mode: newValue })
      executionMode.value = newValue
      showToast({
        message: _modeLabels[newValue] || 'Execution mode updated',
        type: 'info',
        timeout: 3000,
      })
    } catch (error) {
      executionPlatform.value = previousValue
      console.error('Failed to update execution mode:', error)
      showToast({
        message: GENERIC_EXECUTION_MODE_FAILURE,
        type: 'error',
        timeout: 3000,
      })
      notifyFailure(notificationStore, {
        operation: 'project.executionMode',
        entityId: projectId.value,
        error,
        fallbackMessage: GENERIC_EXECUTION_MODE_FAILURE,
        title: 'Execution mode not saved',
      })
    }
  }

  return {
    executionPlatform,
    executionMode,
    executionModeSelected,
    isExecutionModeLocked,
    isSubagentMode,
    agenticTool,
    handleExecutionModeChange,
  }
}

export function isSubagentExecutionMode(mode) {
  return Boolean(mode) && mode !== 'multi_terminal'
}
