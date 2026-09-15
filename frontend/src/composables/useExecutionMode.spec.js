import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import { useNotificationStore } from '@/stores/notifications'

const showToastMock = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

const apiUpdateMock = vi.fn()
vi.mock('@/services/api', () => {
  const apiMock = { projects: { update: (...args) => apiUpdateMock(...args) } }
  return { default: apiMock, api: apiMock }
})

describe('useExecutionMode', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiUpdateMock.mockImplementation((id, updates) => Promise.resolve({ data: { id, ...updates } }))
  })

  async function makeComposable(overrides = {}) {
    const { useExecutionMode } = await import('./useExecutionMode')
    const projectId = ref(overrides.projectId ?? 'proj-1')
    const missionText = ref(overrides.missionText ?? '')
    const isProjectStaged = ref(overrides.isProjectStaged ?? false)
    const isProjectStaging = ref(overrides.isProjectStaging ?? false)
    const initialMode = overrides.initialMode ?? null
    return useExecutionMode({ projectId, missionText, isProjectStaged, isProjectStaging, initialMode })
  }

  it('executionPlatform starts null by default', async () => {
    const { executionPlatform } = await makeComposable()
    expect(executionPlatform.value).toBeNull()
  })

  it('executionMode stays null until a mode is chosen (NULL-state redesign)', async () => {
    const { executionMode } = await makeComposable({ initialMode: null })
    expect(executionMode.value).toBeNull()
  })

  it('executionMode initializes from the project mode when one is already set', async () => {
    const { executionMode } = await makeComposable({ initialMode: 'subagent' })
    expect(executionMode.value).toBe('subagent')
  })

  it('executionModeSelected is false when platform is null', async () => {
    const { executionModeSelected } = await makeComposable()
    expect(executionModeSelected.value).toBe(false)
  })

  it('executionModeSelected is true after setting a platform', async () => {
    const { executionPlatform, executionModeSelected } = await makeComposable()
    executionPlatform.value = 'multi_terminal'
    expect(executionModeSelected.value).toBe(true)
  })

  it('isExecutionModeLocked is false when no mission, not staged, not staging', async () => {
    const { isExecutionModeLocked } = await makeComposable()
    expect(isExecutionModeLocked.value).toBe(false)
  })

  it('isExecutionModeLocked is true when a mode is set and missionText has content', async () => {
    const { isExecutionModeLocked } = await makeComposable({ initialMode: 'multi_terminal', missionText: 'some mission' })
    expect(isExecutionModeLocked.value).toBe(true)
  })

  it('isExecutionModeLocked is true when a mode is set and project is staged', async () => {
    const { isExecutionModeLocked } = await makeComposable({ initialMode: 'multi_terminal', isProjectStaged: true })
    expect(isExecutionModeLocked.value).toBe(true)
  })

  it('isExecutionModeLocked is true when a mode is set and project is staging', async () => {
    const { isExecutionModeLocked } = await makeComposable({ initialMode: 'multi_terminal', isProjectStaging: true })
    expect(isExecutionModeLocked.value).toBe(true)
  })

  it('isExecutionModeLocked is FALSE when mode is unselected even with a mission (deadlock guard)', async () => {
    const { isExecutionModeLocked } = await makeComposable({ initialMode: null, missionText: 'a bootstrap mission' })
    expect(isExecutionModeLocked.value).toBe(false)
  })

  it('isSubagentMode is false when executionMode is multi_terminal', async () => {
    const { executionMode, isSubagentMode } = await makeComposable()
    executionMode.value = 'multi_terminal'
    expect(isSubagentMode.value).toBe(false)
  })

  it('isSubagentMode is true when executionMode is subagent', async () => {
    const { executionMode, isSubagentMode } = await makeComposable()
    executionMode.value = 'subagent'
    expect(isSubagentMode.value).toBe(true)
  })

  it('isSubagentMode is true when executionMode is a tolerated legacy CLI token', async () => {
    const { executionMode, isSubagentMode } = await makeComposable()
    executionMode.value = 'gemini_cli'
    expect(isSubagentMode.value).toBe(true)
  })

  it('isSubagentMode is false when executionMode is unset', async () => {
    const { isSubagentMode } = await makeComposable()
    expect(isSubagentMode.value).toBe(false)
  })

  it('agenticTool returns null when no platform selected', async () => {
    const { agenticTool } = await makeComposable()
    expect(agenticTool.value).toBeNull()
  })

  it('agenticTool returns a generic subagent icon entry for subagent', async () => {
    const { executionPlatform, agenticTool } = await makeComposable()
    executionPlatform.value = 'subagent'
    expect(agenticTool.value).toMatchObject({ type: 'icon', icon: 'mdi-connection', label: 'Subagent' })
  })

  it('agenticTool returns icon entry for multi_terminal', async () => {
    const { executionPlatform, agenticTool } = await makeComposable()
    executionPlatform.value = 'multi_terminal'
    expect(agenticTool.value).toMatchObject({ type: 'icon', icon: 'mdi-monitor-multiple' })
  })

  it('handleExecutionModeChange updates platform and calls api.projects.update', async () => {
    const { executionPlatform, handleExecutionModeChange } = await makeComposable()
    await handleExecutionModeChange('subagent')
    expect(executionPlatform.value).toBe('subagent')
    expect(apiUpdateMock).toHaveBeenCalledWith('proj-1', { execution_mode: 'subagent' })
  })

  it('handleExecutionModeChange reverts platform on API error', async () => {
    apiUpdateMock.mockRejectedValueOnce(new Error('fail'))
    const { executionPlatform, handleExecutionModeChange } = await makeComposable()
    executionPlatform.value = 'multi_terminal'
    await handleExecutionModeChange('subagent')
    expect(executionPlatform.value).toBe('multi_terminal')
  })

  it('handleExecutionModeChange writes the new mode into projectStateStore', async () => {
    const { useProjectStateStore } = await import('@/stores/projectStateStore')
    const store = useProjectStateStore()
    store.setProject({ id: 'proj-1', execution_mode: 'multi_terminal' })
    expect(store.getProjectState('proj-1')?.execution_mode).toBe('multi_terminal')

    const { handleExecutionModeChange } = await makeComposable()
    await handleExecutionModeChange('subagent')

    expect(store.getProjectState('proj-1')?.execution_mode).toBe('subagent')
  })

  it('pushes a persistent notification carrying the server reason when the save fails (FE-9466)', async () => {
    const serverMessage = 'Cannot change execution mode after staging.'
    apiUpdateMock.mockRejectedValueOnce(
      Object.assign(new Error('Request failed with status code 409'), {
        response: {
          status: 409,
          data: { error_code: 'EXECUTION_MODE_LOCKED', message: serverMessage, context: {} },
        },
      }),
    )
    const { handleExecutionModeChange } = await makeComposable({ projectId: 'proj-9' })
    await handleExecutionModeChange('subagent')

    const store = useNotificationStore()
    expect(store.notifications.some((n) => n.message === serverMessage)).toBe(true)
  })

  it('falls back to a generic notification message on an unstructured failure (FE-9466)', async () => {
    apiUpdateMock.mockRejectedValueOnce(new Error('Network Error'))
    const { handleExecutionModeChange } = await makeComposable({ projectId: 'proj-9' })
    await handleExecutionModeChange('subagent')

    const store = useNotificationStore()
    const pushed = store.notifications.find((n) =>
      n.id?.startsWith('failure:project.executionMode:proj-9'),
    )
    expect(pushed?.message).toBe('Failed to save execution mode. Please try again.')
  })

  it('handleExecutionModeChange does NOT update the store when the API call fails', async () => {
    const { useProjectStateStore } = await import('@/stores/projectStateStore')
    const store = useProjectStateStore()
    store.setProject({ id: 'proj-1', execution_mode: 'multi_terminal' })

    apiUpdateMock.mockRejectedValueOnce(new Error('fail'))
    const { handleExecutionModeChange } = await makeComposable()
    await handleExecutionModeChange('subagent')

    expect(store.getProjectState('proj-1')?.execution_mode).toBe('multi_terminal')
  })

  it('isExecutionModeLocked releases when missionText changes from truthy to empty string', async () => {
    const missionText = ref('some mission')
    const { useExecutionMode } = await import('./useExecutionMode')
    const projectId = ref('proj-1')
    const isProjectStaged = ref(false)
    const isProjectStaging = ref(false)
    const composable = useExecutionMode({
      projectId,
      missionText,
      isProjectStaged,
      isProjectStaging,
      initialMode: 'multi_terminal',
    })
    expect(composable.isExecutionModeLocked.value).toBe(true)
    missionText.value = ''
    expect(composable.isExecutionModeLocked.value).toBe(false)
  })

  it('isExecutionModeLocked is false when all inputs are falsy (empty string mission)', async () => {
    const { isExecutionModeLocked } = await makeComposable({ missionText: '' })
    expect(isExecutionModeLocked.value).toBe(false)
  })
})

describe('isSubagentExecutionMode', () => {
  it('is true for every subagent CLI mode, including generic_mcp', async () => {
    const { isSubagentExecutionMode, SUBAGENT_EXECUTION_MODES } = await import('./useExecutionMode')
    expect(SUBAGENT_EXECUTION_MODES).toContain('generic_mcp')
    for (const mode of SUBAGENT_EXECUTION_MODES) {
      expect(isSubagentExecutionMode(mode), `${mode} should be a subagent mode`).toBe(true)
    }
  })

  it('is false for multi_terminal and for null/undefined/unselected', async () => {
    const { isSubagentExecutionMode } = await import('./useExecutionMode')
    expect(isSubagentExecutionMode('multi_terminal')).toBe(false)
    expect(isSubagentExecutionMode(null)).toBe(false)
    expect(isSubagentExecutionMode(undefined)).toBe(false)
  })
})
