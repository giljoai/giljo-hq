import { describe, it, expect, beforeEach, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const m = vi.hoisted(() => ({
  staging: vi.fn(),
  update: vi.fn(),
  restage: vi.fn(),
  unstage: vi.fn(),
  getOrchestrator: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const api = {
    prompts: { staging: (...a) => m.staging(...a) },
    projects: {
      update: (...a) => m.update(...a),
      restage: (...a) => m.restage(...a),
      unstage: (...a) => m.unstage(...a),
      getOrchestrator: (...a) => m.getOrchestrator(...a),
    },
  }
  return { default: api, api }
})
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: m.toast }) }))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn() }) }))

import { useProjectStageControls } from './useProjectStageControls'

function setup(project) {
  let controls
  const projectRef = ref(project)
  const Host = defineComponent({
    setup() {
      controls = useProjectStageControls({ project: projectRef, seedState: true })
      return () => h('div')
    },
  })
  const wrapper = mount(Host, { global: { plugins: [createPinia()] } })
  return { controls, wrapper, projectRef }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  m.staging.mockResolvedValue({ data: { prompt: 'STAGE ME' } })
  m.update.mockImplementation((id, patch) => Promise.resolve({ data: { id, ...patch } }))
  m.restage.mockResolvedValue({ data: { staging_status: null, mission: '' } })
  m.getOrchestrator.mockResolvedValue({ data: { orchestrator: null } })
})

const UNSTAGED_WITH_ROW_MODE = {
  id: 'p-1',
  name: 'Sloppy stage',
  status: 'active',
  staging_status: null,
  implementation_launched_at: null,
  execution_mode: 'multi_terminal',
  mission: 'A mission written at creation (CTX bootstrap shape).',
}

describe('useProjectStageControls mode gate (FE-9679)', () => {
  it('the incident: an unstaged project whose row carries a mode and a mission is NOT pre-selected', () => {
    const { controls } = setup(UNSTAGED_WITH_ROW_MODE)
    expect(controls.executionPlatform.value).toBeNull()
    expect(controls.executionModeSelected.value).toBe(false)
  })

  it('Stage with no choice refuses visibly and sends nothing; the button is not disabled for it', async () => {
    const { controls } = setup(UNSTAGED_WITH_ROW_MODE)
    expect(controls.stageButtonDisabled.value).toBe(false)
    expect(controls.modeRefused.value).toBe(false)

    await controls.handleStageOrRestage()
    expect(m.staging).not.toHaveBeenCalled()
    expect(controls.modeRefused.value).toBe(true)
  })

  it('picking a mode clears the refusal and Stage then sends that mode, never the stale row value', async () => {
    const { controls } = setup(UNSTAGED_WITH_ROW_MODE)
    await controls.handleStageOrRestage()
    expect(controls.modeRefused.value).toBe(true)

    await controls.handleExecutionModeChange('subagent')
    await flushPromises()
    expect(controls.modeRefused.value).toBe(false)
    expect(m.update).toHaveBeenCalledWith('p-1', { execution_mode: 'subagent' })

    await controls.handleStageOrRestage()
    expect(m.staging).toHaveBeenCalledTimes(1)
    expect(m.staging.mock.calls[0][1]).toMatchObject({ execution_mode: 'subagent' })
  })

  it('FE-9689: the board refreshing with the mode just picked keeps the pick; Stage goes through', async () => {
    const { controls, projectRef } = setup({ ...UNSTAGED_WITH_ROW_MODE, execution_mode: null })
    await controls.handleExecutionModeChange('multi_terminal')
    await flushPromises()
    expect(controls.executionPlatform.value).toBe('multi_terminal')

    projectRef.value = { ...projectRef.value, execution_mode: 'multi_terminal' }
    await flushPromises()
    expect(controls.executionPlatform.value).toBe('multi_terminal')

    await controls.handleStageOrRestage()
    expect(controls.modeRefused.value).toBe(false)
    expect(m.staging).toHaveBeenCalledTimes(1)
    expect(m.staging.mock.calls[0][1]).toMatchObject({ execution_mode: 'multi_terminal' })
  })

  it('FE-9689: Stage pressed while the mode save is still in flight sends the picked mode', async () => {
    let finishSave
    m.update.mockImplementation((id, patch) => new Promise((resolve) => {
      finishSave = () => resolve({ data: { id, ...patch } })
    }))
    const { controls } = setup({ ...UNSTAGED_WITH_ROW_MODE, execution_mode: null })
    const saving = controls.handleExecutionModeChange('subagent')
    await controls.handleStageOrRestage()
    expect(m.staging).toHaveBeenCalledTimes(1)
    expect(m.staging.mock.calls[0][1]).toMatchObject({ execution_mode: 'subagent' })
    finishSave()
    await saving
  })

  it('FE-9689: a refresh bringing a DIFFERENT mode than the pick (changed elsewhere) asks again', async () => {
    const { controls, projectRef } = setup({ ...UNSTAGED_WITH_ROW_MODE, execution_mode: null })
    await controls.handleExecutionModeChange('multi_terminal')
    await flushPromises()
    projectRef.value = { ...projectRef.value, execution_mode: 'subagent' }
    await flushPromises()
    expect(controls.executionPlatform.value).toBeNull()
  })

  it('once staging is a fact (staging or staged) the radio mirrors the row: the mode is shown, locked', () => {
    const staged = setup({ ...UNSTAGED_WITH_ROW_MODE, id: 'p-2', staging_status: 'staging_complete', execution_mode: 'subagent' })
    expect(staged.controls.executionPlatform.value).toBe('subagent')
    expect(staged.controls.isExecutionModeLocked.value).toBe(true)

    const staging = setup({ ...UNSTAGED_WITH_ROW_MODE, id: 'p-3', staging_status: 'staging', execution_mode: 'multi_terminal' })
    expect(staging.controls.executionPlatform.value).toBe('multi_terminal')
  })

  it('Re-Stage clears the choice: the next Stage asks again', async () => {
    const { controls } = setup({ ...UNSTAGED_WITH_ROW_MODE, id: 'p-4', staging_status: 'staging_complete', execution_mode: 'multi_terminal' })
    expect(controls.executionPlatform.value).toBe('multi_terminal')
    expect(controls.canRestage.value).toBe(true)

    await controls.handleStageOrRestage()
    await flushPromises()
    expect(m.restage).toHaveBeenCalledWith('p-4')
    expect(controls.executionPlatform.value).toBeNull()
    expect(controls.executionModeSelected.value).toBe(false)
  })
})
