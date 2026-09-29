import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const showToastMock = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

const stagingMock = vi.fn()
const launchMock = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    prompts: { staging: (...args) => stagingMock(...args) },
    orchestrator: { launchProject: (...args) => launchMock(...args) },
    projects: { get: vi.fn().mockResolvedValue({ data: { id: 'proj-1' } }), launchImplementation: vi.fn().mockResolvedValue({}) },
  },
  api: {
    projects: { launchImplementation: vi.fn().mockResolvedValue({}) },
    prompts: { implementation: vi.fn().mockResolvedValue({ data: { prompt: 'IMPL', agent_count: 0 } }) },
  },
}))

const clipboardCopyMock = vi.fn().mockResolvedValue(true)
vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: clipboardCopyMock }),
}))

const setIsStagedMock = vi.fn()
const setLaunchedMock = vi.fn()
const unstageProjectMock = vi.fn()
const restageProjectMock = vi.fn()
vi.mock('@/stores/projectStateStore', () => ({
  useProjectStateStore: () => ({
    setIsStaged: setIsStagedMock,
    setLaunched: setLaunchedMock,
    unstageProject: unstageProjectMock,
    restageProject: restageProjectMock,
  }),
}))

vi.mock('@/stores/projectTabs', () => ({
  useProjectTabsStore: () => ({
    isLaunched: false,
    currentProject: null,
  }),
}))

describe('useProjectStaging', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function makeComposable(overrides = {}) {
    const { useProjectStaging } = await import('./useProjectStaging')
    const projectId = ref(overrides.projectId ?? 'proj-1')
    const executionMode = ref('executionMode' in overrides ? overrides.executionMode : 'multi_terminal')
    const isProjectStaged = ref(overrides.isProjectStaged ?? false)
    const readyToLaunch = ref(overrides.readyToLaunch ?? true)
    const canRestage = ref(overrides.canRestage ?? false)
    return useProjectStaging({ projectId, executionMode, isProjectStaged, readyToLaunch, canRestage })
  }

  it('handleStageProject calls api.prompts.staging with correct payload', async () => {
    stagingMock.mockResolvedValueOnce({ data: { prompt: 'test prompt' } })
    const { handleStageProject } = await makeComposable()
    await handleStageProject()
    expect(stagingMock).toHaveBeenCalledWith('proj-1', {
      tool: 'claude-code',
      execution_mode: 'multi_terminal',
    })
  })

  it('handleStageProject sets staged state and copies to clipboard on success', async () => {
    stagingMock.mockResolvedValueOnce({ data: { prompt: 'copied prompt' } })
    const { handleStageProject } = await makeComposable()
    await handleStageProject()
    expect(setIsStagedMock).toHaveBeenCalledWith('proj-1', true)
    expect(clipboardCopyMock).toHaveBeenCalledWith('copied prompt')
  })

  it('handleStageProject shows toast on error', async () => {
    stagingMock.mockRejectedValueOnce(new Error('staging failed'))
    const { handleStageProject } = await makeComposable()
    await handleStageProject()
    expect(showToastMock).toHaveBeenCalled()
  })

  it('handleStageProject omits execution_mode when none chosen (NULL-state)', async () => {
    stagingMock.mockResolvedValueOnce({ data: { prompt: 'p' } })
    const { handleStageProject } = await makeComposable({ executionMode: null })
    await handleStageProject()
    expect(stagingMock).toHaveBeenCalledWith('proj-1', {
      tool: 'claude-code',
      execution_mode: null,
    })
  })

  it('handleStageProject shows a friendly warning on the 409 no-execution-mode gate', async () => {
    const err = new Error('No execution mode selected')
    err.response = {
      status: 409,
      data: { error_code: 'VALIDATIONERROR', message: 'No execution mode selected. Choose an execution mode before staging.' },
    }
    stagingMock.mockRejectedValueOnce(err)
    const { handleStageProject } = await makeComposable({ executionMode: null })
    await handleStageProject()
    expect(showToastMock).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'warning', message: expect.stringContaining('execution mode') }),
    )
  })

  it('handleUnstageProject calls unstageProject', async () => {
    unstageProjectMock.mockResolvedValueOnce()
    const { handleUnstageProject } = await makeComposable({ isProjectStaged: true })
    await handleUnstageProject()
    expect(unstageProjectMock).toHaveBeenCalledWith('proj-1')
  })

  it('handleLaunchJobs calls api.orchestrator.launchProject', async () => {
    launchMock.mockResolvedValueOnce({})
    const { handleLaunchJobs, onLaunchSuccess } = await makeComposable({ readyToLaunch: true })
    onLaunchSuccess(() => {})
    await handleLaunchJobs()
    expect(launchMock).toHaveBeenCalledWith({ project_id: 'proj-1' })
  })

  it('handleLaunchJobs shows error if not readyToLaunch', async () => {
    const { handleLaunchJobs } = await makeComposable({ readyToLaunch: false })
    await handleLaunchJobs()
    expect(launchMock).not.toHaveBeenCalled()
    expect(showToastMock).toHaveBeenCalled()
  })

  it('loadingStageProject is false initially', async () => {
    const { loadingStageProject } = await makeComposable()
    expect(loadingStageProject.value).toBe(false)
  })

  it('handleRestageProject calls restageProject store action', async () => {
    restageProjectMock.mockResolvedValueOnce()
    const { handleRestageProject } = await makeComposable({ canRestage: true })
    await handleRestageProject()
    expect(restageProjectMock).toHaveBeenCalledWith('proj-1')
  })

  it('handleRestageProject shows success toast on recovery', async () => {
    restageProjectMock.mockResolvedValueOnce()
    const { handleRestageProject } = await makeComposable({ canRestage: true })
    await handleRestageProject()
    expect(showToastMock).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'success' })
    )
  })

  it('handleRestageProject shows error toast on 409 (impl already launched)', async () => {
    const err = new Error('Cannot recover mode')
    err.response = {
      data: { error_code: 'VALIDATIONERROR', message: 'Cannot recover mode: implementation already launched' },
    }
    restageProjectMock.mockRejectedValueOnce(err)
    const { handleRestageProject } = await makeComposable({ canRestage: true })
    await handleRestageProject()
    expect(showToastMock).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error' })
    )
  })

  it('handleStageOrRestage calls restageProject when canRestage is true', async () => {
    restageProjectMock.mockResolvedValueOnce()
    const { handleStageOrRestage } = await makeComposable({ isProjectStaged: false, canRestage: true })
    await handleStageOrRestage()
    expect(restageProjectMock).toHaveBeenCalledWith('proj-1')
    expect(unstageProjectMock).not.toHaveBeenCalled()
  })

  it('handleStageOrRestage calls unstageProject when isProjectStaged is true', async () => {
    unstageProjectMock.mockResolvedValueOnce()
    const { handleStageOrRestage } = await makeComposable({ isProjectStaged: true, canRestage: false })
    await handleStageOrRestage()
    expect(unstageProjectMock).toHaveBeenCalledWith('proj-1')
    expect(restageProjectMock).not.toHaveBeenCalled()
  })
})
