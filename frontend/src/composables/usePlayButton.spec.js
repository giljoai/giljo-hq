import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { usePlayButton } from './usePlayButton'
import { api } from '@/services/api'

const mockShowToast = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}))

describe('usePlayButton', () => {
  let project
  let getProjectState
  let clipboardCopy

  beforeEach(() => {
    setActivePinia(createPinia())
    project = { project_id: 'proj-1', execution_mode: 'multi_terminal' }
    getProjectState = vi.fn(() => ({ stagingComplete: true }))
    clipboardCopy = vi.fn(() => Promise.resolve(true))
    vi.clearAllMocks()
  })

  it('shouldShowCopyButton returns false when staging not complete', () => {
    getProjectState = vi.fn(() => ({ stagingComplete: false }))
    const { shouldShowCopyButton } = usePlayButton(project, getProjectState, clipboardCopy)

    const agent = { agent_display_name: 'implementer', status: 'waiting' }
    expect(shouldShowCopyButton(agent)).toBe(false)
  })

  it('isPlayButtonFaded returns false for waiting agent', () => {
    const { isPlayButtonFaded } = usePlayButton(project, getProjectState, clipboardCopy)
    const agent = { job_id: 'job-1', status: 'waiting' }
    expect(isPlayButtonFaded(agent)).toBe(false)
  })

  it('isPlayButtonFaded returns true for non-waiting agent', () => {
    const { isPlayButtonFaded } = usePlayButton(project, getProjectState, clipboardCopy)
    const agent = { job_id: 'job-1', status: 'working' }
    expect(isPlayButtonFaded(agent)).toBe(true)
  })

  it('reactivatePlay makes isPlayButtonFaded return false', () => {
    const { reactivatePlay, isPlayButtonFaded } = usePlayButton(project, getProjectState, clipboardCopy)
    const agent = { job_id: 'job-2', status: 'working' }

    expect(isPlayButtonFaded(agent)).toBe(true)
    reactivatePlay(agent)
    expect(isPlayButtonFaded(agent)).toBe(false)
  })

  it('handlePlay calls clipboard copy for specialist agent', async () => {
    api.prompts.agentPrompt.mockResolvedValue({ data: { prompt: 'specialist prompt text' } })

    const { handlePlay } = usePlayButton(project, getProjectState, clipboardCopy)
    const agent = { agent_id: 'agent-1', agent_display_name: 'implementer', status: 'waiting' }

    await handlePlay(agent)

    expect(api.prompts.agentPrompt).toHaveBeenCalledWith('agent-1')
    expect(clipboardCopy).toHaveBeenCalledWith('specialist prompt text')
    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
  })

  it('handlePlay re-fades button after re-copy', async () => {
    api.prompts.agentPrompt.mockResolvedValue({ data: { prompt: 'prompt' } })

    const { handlePlay, reactivatePlay, isPlayButtonFaded } = usePlayButton(
      project, getProjectState, clipboardCopy
    )
    const agent = { job_id: 'job-3', agent_id: 'agent-3', agent_display_name: 'implementer', status: 'working' }

    reactivatePlay(agent)
    expect(isPlayButtonFaded(agent)).toBe(false)

    await handlePlay(agent)
    expect(isPlayButtonFaded(agent)).toBe(true)
  })

  it('handlePlay for CLI orchestrator calls implementation and copies prompt', async () => {
    project = { project_id: 'proj-2', execution_mode: 'claude_code_cli' }
    api.projects.launchImplementation.mockResolvedValue({ data: { success: true } })
    api.prompts.implementation.mockResolvedValue({
      data: { prompt: 'impl prompt', agent_count: 2 },
    })

    const { handlePlay } = usePlayButton(project, getProjectState, clipboardCopy)
    const agent = { job_id: 'job-orch', agent_display_name: 'orchestrator', status: 'waiting' }

    await handlePlay(agent)

    expect(api.prompts.implementation).toHaveBeenCalledWith('proj-2')
    expect(clipboardCopy).toHaveBeenCalledWith('impl prompt')
    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
  })

  it('handlePlay shows error toast when specialist prompt empty', async () => {
    api.prompts.agentPrompt.mockResolvedValue({ data: { prompt: '' } })

    const { handlePlay } = usePlayButton(project, getProjectState, clipboardCopy)
    const agent = { agent_id: 'agent-5', agent_display_name: 'implementer', status: 'waiting' }

    await handlePlay(agent)

    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
  })


  it('handlePlay surfaces actionable toast when implementation prompt returns 404', async () => {
    project = { project_id: 'proj-404', execution_mode: 'claude_code_cli' }
    api.projects.launchImplementation.mockResolvedValue({ data: { success: true } })
    const err = new Error('Request failed')
    err.response = { status: 404, data: { detail: 'Project not staged' } }
    api.prompts.implementation.mockRejectedValue(err)
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    const { handlePlay } = usePlayButton(project, getProjectState, clipboardCopy)
    const agent = { job_id: 'job-orch', agent_display_name: 'orchestrator', status: 'waiting' }

    await handlePlay(agent)

    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'error',
        message: expect.stringMatching(/404/),
      })
    )
    const call = mockShowToast.mock.calls.find(([opts]) => opts?.type === 'error')
    expect(call[0].message.toLowerCase()).toMatch(/staging|refresh|launched/)
    expect(warnSpy).toHaveBeenCalled()
    warnSpy.mockRestore()
  })

  it('handlePlay surfaces toast with status code when implementation prompt returns 500', async () => {
    project = { project_id: 'proj-500', execution_mode: 'claude_code_cli' }
    api.projects.launchImplementation.mockResolvedValue({ data: { success: true } })
    const err = new Error('Server error')
    err.response = { status: 500, data: { detail: 'boom' } }
    api.prompts.implementation.mockRejectedValue(err)
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    const { handlePlay } = usePlayButton(project, getProjectState, clipboardCopy)
    const agent = { job_id: 'job-orch', agent_display_name: 'orchestrator', status: 'waiting' }

    await handlePlay(agent)

    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'error',
        message: expect.stringMatching(/500/),
      })
    )
    expect(warnSpy).toHaveBeenCalled()
    warnSpy.mockRestore()
  })

  it('handlePlay shows success toast on successful implementation prompt copy', async () => {
    project = { project_id: 'proj-ok', execution_mode: 'claude_code_cli' }
    api.projects.launchImplementation.mockResolvedValue({ data: { success: true } })
    api.prompts.implementation.mockResolvedValue({
      data: { prompt: 'impl prompt', agent_count: 2 },
    })

    const { handlePlay } = usePlayButton(project, getProjectState, clipboardCopy)
    const agent = { job_id: 'job-orch', agent_display_name: 'orchestrator', status: 'waiting' }

    await handlePlay(agent)

    expect(clipboardCopy).toHaveBeenCalledWith('impl prompt')
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'success' })
    )
  })

  it('handlePlay shows distinct clipboard-error toast when clipboard write fails', async () => {
    project = { project_id: 'proj-clip', execution_mode: 'claude_code_cli' }
    api.projects.launchImplementation.mockResolvedValue({ data: { success: true } })
    api.prompts.implementation.mockResolvedValue({
      data: { prompt: 'impl prompt', agent_count: 2 },
    })
    clipboardCopy = vi.fn(() => Promise.resolve(false))

    const { handlePlay } = usePlayButton(project, getProjectState, clipboardCopy)
    const agent = { job_id: 'job-orch', agent_display_name: 'orchestrator', status: 'waiting' }

    await handlePlay(agent)

    const errorCalls = mockShowToast.mock.calls.filter(([opts]) => opts?.type === 'error')
    expect(errorCalls.length).toBeGreaterThan(0)
    const clipboardCall = errorCalls.find(([opts]) =>
      /clipboard|browser blocked/i.test(opts.message || '')
    )
    expect(clipboardCall).toBeDefined()
  })

  it('handlePlay logs payload to console.warn on non-2xx implementation fetch', async () => {
    project = { project_id: 'proj-warn', execution_mode: 'claude_code_cli' }
    api.projects.launchImplementation.mockResolvedValue({ data: { success: true } })
    const err = new Error('boom')
    err.response = { status: 422, data: { detail: 'validation', extra: 'payload' } }
    api.prompts.implementation.mockRejectedValue(err)
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    const { handlePlay } = usePlayButton(project, getProjectState, clipboardCopy)
    const agent = { job_id: 'job-orch', agent_display_name: 'orchestrator', status: 'waiting' }

    await handlePlay(agent)

    expect(warnSpy).toHaveBeenCalled()
    const calledWithPayload = warnSpy.mock.calls.some((args) =>
      args.some(
        (a) =>
          a && typeof a === 'object' && a.payload && a.payload.detail === 'validation'
      )
    )
    expect(calledWithPayload).toBe(true)
    warnSpy.mockRestore()
  })


  it('[FE-6019] shouldShowCopyButton uses store execution_mode over stale prop', () => {
    const staleProject = { project_id: 'proj-fe6019', execution_mode: 'claude_code_cli' }
    const storeState = { stagingComplete: true, execution_mode: 'multi_terminal' }
    const getStoreFn = vi.fn(() => storeState)

    const { shouldShowCopyButton } = usePlayButton(staleProject, getStoreFn, clipboardCopy)

    const specialist = { agent_display_name: 'implementer', status: 'waiting' }
    expect(shouldShowCopyButton(specialist)).toBe(true)
  })

  it('[FE-6019] shouldShowCopyButton correctly hides specialist button in CLI mode from store', () => {
    const staleProject = { project_id: 'proj-fe6019b', execution_mode: 'multi_terminal' }
    const storeState = { stagingComplete: true, execution_mode: 'claude_code_cli' }
    const getStoreFn = vi.fn(() => storeState)

    const { shouldShowCopyButton } = usePlayButton(staleProject, getStoreFn, clipboardCopy)

    const specialist = { agent_display_name: 'implementer', status: 'waiting' }
    expect(shouldShowCopyButton(specialist)).toBe(false)
  })

  it('[BE-9035a] shouldShowCopyButton treats generic_mcp as a subagent CLI mode', () => {
    const project = { project_id: 'proj-9035a', execution_mode: 'generic_mcp' }
    const storeState = { stagingComplete: true, execution_mode: 'generic_mcp' }
    const getStoreFn = vi.fn(() => storeState)

    const { shouldShowCopyButton } = usePlayButton(project, getStoreFn, clipboardCopy)

    const specialist = { agent_display_name: 'implementer', status: 'waiting' }
    expect(shouldShowCopyButton(specialist)).toBe(false)
  })
})



describe('usePlayButton — chain member (FE-9629)', () => {
  let getProjectState
  let clipboardCopy
  let store

  const ORCHESTRATOR = { agent_display_name: 'orchestrator', job_id: 'orc-job', status: 'waiting' }

  function chainCtx(currentIndex = 0, statuses = { 'p1': 'planning', 'p2': 'pending' }) {
    return ref({
      runId: 'run-1',
      run: {
        id: 'run-1',
        project_ids: ['p1', 'p2'],
        resolved_order: ['p1', 'p2'],
        current_index: currentIndex,
        project_statuses: statuses,
      },
      tabs: [
        { projectId: 'p1', taxonomyAlias: 'FE-9640', name: 'Ingest rewrite' },
        { projectId: 'p2', taxonomyAlias: 'FE-9641', name: 'Search index' },
      ],
    })
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useSequenceRunStore()
    store._testSeedRuns([
      {
        id: 'run-1',
        project_ids: ['p1', 'p2'],
        resolved_order: ['p1', 'p2'],
        current_index: 0,
        status: 'running',
        execution_mode: 'multi_terminal',
        project_statuses: { p1: 'planning', p2: 'pending' },
      },
    ])
    getProjectState = vi.fn(() => ({ stagingComplete: false, execution_mode: 'multi_terminal' }))
    clipboardCopy = vi.fn(() => Promise.resolve(true))
    vi.clearAllMocks()
  })

  it('renders the play button for the member at the current index, despite staging not being complete', () => {
    const { shouldShowCopyButton, isPlayButtonFaded, playButtonTooltip } = usePlayButton(
      { project_id: 'p1' }, getProjectState, clipboardCopy, chainCtx(0),
    )
    expect(shouldShowCopyButton(ORCHESTRATOR)).toBe(true)
    expect(isPlayButtonFaded(ORCHESTRATOR)).toBe(false)
    expect(playButtonTooltip(ORCHESTRATOR)).toBe('Copy prompt')
  })

  it('renders a FADED button naming the predecessor for a member whose turn has not come', () => {
    const { shouldShowCopyButton, isPlayButtonFaded, playButtonTooltip } = usePlayButton(
      { project_id: 'p2' }, getProjectState, clipboardCopy, chainCtx(0),
    )
    expect(shouldShowCopyButton(ORCHESTRATOR)).toBe(true)
    expect(isPlayButtonFaded(ORCHESTRATOR)).toBe(true)
    expect(playButtonTooltip(ORCHESTRATOR)).toBe('Starts after FE-9640 closes out')
  })

  it('handlePlay launches THIS member and copies ITS OWN orchestrator prompt', async () => {
    api.prompts.chainMember.mockResolvedValue({ data: { prompt: 'MEMBER 1 BOOTSTRAP' } })
    const { handlePlay } = usePlayButton(
      { project_id: 'p1' }, getProjectState, clipboardCopy, chainCtx(0),
    )

    await handlePlay(ORCHESTRATOR)

    expect(api.projects.launchImplementation).toHaveBeenCalledWith('p1')
    expect(api.prompts.chainMember).toHaveBeenCalledWith('p1')
    expect(api.prompts.implementation).not.toHaveBeenCalled()
    expect(clipboardCopy).toHaveBeenCalledWith('MEMBER 1 BOOTSTRAP')
    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
    const launchOrder = api.projects.launchImplementation.mock.invocationCallOrder[0]
    const fetchOrder = api.prompts.chainMember.mock.invocationCallOrder[0]
    expect(launchOrder).toBeLessThan(fetchOrder)
  })

  it('handlePlay does nothing at all for a member whose turn has not come', async () => {
    const { handlePlay } = usePlayButton(
      { project_id: 'p2' }, getProjectState, clipboardCopy, chainCtx(0),
    )

    await handlePlay(ORCHESTRATOR)

    expect(api.projects.launchImplementation).not.toHaveBeenCalled()
    expect(api.prompts.chainMember).not.toHaveBeenCalled()
    expect(clipboardCopy).not.toHaveBeenCalled()
  })

  it('surfaces the server refusal verbatim when the launch is rejected', async () => {
    api.projects.launchImplementation.mockRejectedValueOnce({
      response: { data: { message: 'Cannot start this chain member yet: FE-9640 is still open.' } },
    })
    const { handlePlay } = usePlayButton(
      { project_id: 'p1' }, getProjectState, clipboardCopy, chainCtx(0),
    )

    await handlePlay(ORCHESTRATOR)

    expect(api.prompts.chainMember).not.toHaveBeenCalled()
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('FE-9640') }),
    )
  })

  it('leaves a SPECIALIST row on the solo rule (chain membership changes the orchestrator row only)', () => {
    const { shouldShowCopyButton } = usePlayButton(
      { project_id: 'p1' }, getProjectState, clipboardCopy, chainCtx(0),
    )
    expect(shouldShowCopyButton({ agent_display_name: 'implementer', status: 'waiting' })).toBe(false)
  })

  it('leaves a SOLO project untouched when no chain context is supplied', async () => {
    api.prompts.implementation.mockResolvedValue({ data: { prompt: 'SOLO', agent_count: 2 } })
    getProjectState = vi.fn(() => ({ stagingComplete: true, execution_mode: 'multi_terminal' }))
    const { shouldShowCopyButton, handlePlay } = usePlayButton(
      { project_id: 'solo-pid' }, getProjectState, clipboardCopy,
    )

    expect(shouldShowCopyButton(ORCHESTRATOR)).toBe(true)
    await handlePlay(ORCHESTRATOR)
    expect(api.prompts.implementation).toHaveBeenCalledWith('solo-pid')
    expect(api.prompts.chainMember).not.toHaveBeenCalled()
  })
})
