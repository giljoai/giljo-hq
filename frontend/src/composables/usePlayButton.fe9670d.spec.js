import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { usePlayButton, launchThenCopyImplementationPrompt } from './usePlayButton'
import { api } from '@/services/api'

const mockShowToast = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}))

const ORCH = { job_id: 'job-orch', agent_display_name: 'orchestrator', status: 'waiting' }

describe('FE-9670d launchThenCopyImplementationPrompt', () => {
  let clipboardCopy
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    clipboardCopy = vi.fn(() => Promise.resolve(true))
    api.projects.launchImplementation.mockResolvedValue({ data: { success: true } })
    api.prompts.implementation.mockResolvedValue({ data: { prompt: 'IMPL', agent_count: 2 } })
  })

  it('stamps the gate BEFORE fetching the prompt, then copies it', async () => {
    const ok = await launchThenCopyImplementationPrompt({
      projectId: 'p1', executionMode: 'multi_terminal', clipboardCopy, showToast: mockShowToast,
    })
    expect(ok).toBe(true)
    const stamp = api.projects.launchImplementation.mock.invocationCallOrder[0]
    const fetch = api.prompts.implementation.mock.invocationCallOrder[0]
    const copy = clipboardCopy.mock.invocationCallOrder[0]
    expect(stamp).toBeLessThan(fetch)
    expect(fetch).toBeLessThan(copy)
    expect(clipboardCopy).toHaveBeenCalledWith('IMPL')
  })

  it('a failed stamp shows an error toast and copies nothing', async () => {
    api.projects.launchImplementation.mockRejectedValueOnce({
      response: { status: 409, data: { error_code: 'VALIDATIONERROR', message: 'Staging is not complete.' } },
    })
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const ok = await launchThenCopyImplementationPrompt({
      projectId: 'p1', executionMode: 'multi_terminal', clipboardCopy, showToast: mockShowToast,
    })
    expect(ok).toBe(false)
    expect(api.prompts.implementation).not.toHaveBeenCalled()
    expect(clipboardCopy).not.toHaveBeenCalled()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('Staging is not complete.') }),
    )
    expect(warnSpy).not.toHaveBeenCalled()
    warnSpy.mockRestore()
  })
})

describe('FE-9670d usePlayButton solo orchestrator', () => {
  let clipboardCopy
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    clipboardCopy = vi.fn(() => Promise.resolve(true))
    api.projects.launchImplementation.mockResolvedValue({ data: { success: true } })
    api.prompts.implementation.mockResolvedValue({ data: { prompt: 'IMPL', agent_count: 2 } })
  })

  it('handlePlay: stamp then copy; a failed stamp is a toast, not a console.warn', async () => {
    api.projects.launchImplementation.mockRejectedValueOnce(new Error('gate refused'))
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { handlePlay } = usePlayButton({ project_id: 'p1' }, () => ({ stagingComplete: true }), clipboardCopy)
    await handlePlay(ORCH)
    expect(clipboardCopy).not.toHaveBeenCalled()
    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
    expect(warnSpy).not.toHaveBeenCalled()
    warnSpy.mockRestore()
  })

  it('handleReplay re-issues the latest prompt and never stamps', async () => {
    const project = { project_id: 'p1', implementation_launched_at: '2026-09-25T00:00:00Z' }
    const { handleReplay } = usePlayButton(project, () => ({ stagingComplete: true }), clipboardCopy)
    await handleReplay({ ...ORCH, status: 'working' })
    expect(api.projects.launchImplementation).not.toHaveBeenCalled()
    expect(api.prompts.implementation).toHaveBeenCalledWith('p1')
    expect(clipboardCopy).toHaveBeenCalledWith('IMPL')
  })

  it('replay is not offered before the project launched, and is after', () => {
    const notLaunched = usePlayButton({ project_id: 'p1' }, () => ({ stagingComplete: true }), clipboardCopy)
    expect(notLaunched.canReplay({ ...ORCH, status: 'working' })).toBe(false)
    const launched = usePlayButton(
      { project_id: 'p1', implementation_launched_at: 'x' }, () => ({ stagingComplete: true }), clipboardCopy,
    )
    expect(launched.canReplay({ ...ORCH, status: 'working' })).toBe(true)
  })

  it('specialist replay copies its prompt without stamping', async () => {
    const { handleReplay } = usePlayButton({ project_id: 'p1' }, () => ({ stagingComplete: true }), clipboardCopy)
    await handleReplay({ agent_id: 'a1', agent_display_name: 'implementer', status: 'working' })
    expect(api.prompts.agentPrompt).toHaveBeenCalledWith('a1')
    expect(api.projects.launchImplementation).not.toHaveBeenCalled()
  })
})

describe('FE-9670d chain member', () => {
  let clipboardCopy
  let store
  const chainCtx = { tabs: [{ projectId: 'p1', taxonomyAlias: 'FE-1a' }, { projectId: 'p2', taxonomyAlias: 'FE-1b' }] }
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    store = useSequenceRunStore()
    clipboardCopy = vi.fn(() => Promise.resolve(true))
  })

  it('a member whose turn has not come offers no replay (a faded Play only)', () => {
    vi.spyOn(store, 'isProjectStartable').mockReturnValue(false)
    const { canReplay, isPlayButtonFaded } = usePlayButton({ project_id: 'p2' }, () => ({}), clipboardCopy, chainCtx)
    const agent = { ...ORCH, status: 'working' }
    expect(isPlayButtonFaded(agent)).toBe(true)
    expect(canReplay(agent)).toBe(false)
  })

  it('member replay copies the member prompt and never stamps', async () => {
    vi.spyOn(store, 'isProjectStartable').mockReturnValue(true)
    const { handleReplay } = usePlayButton(
      { project_id: 'p2', implementation_launched_at: 'x' }, () => ({}), clipboardCopy, chainCtx,
    )
    await handleReplay({ ...ORCH, status: 'working' })
    expect(api.prompts.chainMember).toHaveBeenCalledWith('p2')
    expect(api.projects.launchImplementation).not.toHaveBeenCalled()
    expect(clipboardCopy).toHaveBeenCalled()
  })
})
