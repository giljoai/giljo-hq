import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const showToastMock = vi.fn()
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: showToastMock }) }))

const calls = []
const stampMock = vi.fn(async () => { calls.push('stamp') })
const promptMock = vi.fn(async () => { calls.push('prompt'); return { data: { prompt: 'IMPL', agent_count: 1 } } })
const launchProjectMock = vi.fn(async () => { calls.push('launch-project') })
vi.mock('@/services/api', () => {
  const a = {
    prompts: { implementation: (...x) => promptMock(...x) },
    orchestrator: { launchProject: (...x) => launchProjectMock(...x) },
    projects: { launchImplementation: (...x) => stampMock(...x) },
  }
  return { default: a, api: a }
})
const copyMock = vi.fn(async () => { calls.push('copy'); return true })
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: copyMock }) }))
const setLaunchedMock = vi.fn()
vi.mock('@/stores/projectStateStore', () => ({ useProjectStateStore: () => ({ setLaunched: setLaunchedMock }) }))
vi.mock('@/stores/projectTabs', () => ({ useProjectTabsStore: () => ({ isLaunched: false, currentProject: null }) }))

async function make() {
  const { useProjectStaging } = await import('./useProjectStaging')
  return useProjectStaging({
    projectId: ref('p1'), executionMode: ref('multi_terminal'), isProjectStaged: ref(true), readyToLaunch: ref(true),
  })
}

describe('FE-9670d Implement is the one true Play', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    calls.length = 0
  })

  it('stamps the gate, then fetches and copies the prompt', async () => {
    const { handleLaunchJobs } = await make()
    await handleLaunchJobs()
    expect(stampMock).toHaveBeenCalledWith('p1')
    expect(calls.slice(0, 3)).toEqual(['stamp', 'prompt', 'copy'])
    expect(setLaunchedMock).toHaveBeenCalledWith('p1', true)
  })

  it('a refused stamp is a toast; no prompt, no copy, not marked launched', async () => {
    stampMock.mockRejectedValueOnce({
      response: { status: 409, data: { error_code: 'VALIDATIONERROR', message: 'Staging is not complete.' } },
    })
    const { handleLaunchJobs } = await make()
    await handleLaunchJobs()
    expect(promptMock).not.toHaveBeenCalled()
    expect(copyMock).not.toHaveBeenCalled()
    expect(setLaunchedMock).not.toHaveBeenCalled()
    expect(showToastMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
  })
})
