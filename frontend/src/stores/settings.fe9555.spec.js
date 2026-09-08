/**
 * settings.fe9555.spec.js — FE-9555
 *
 * The account-level execution-mode default behind the Tools -> Agents control.
 *
 * Ruling 6: "Execution mode must be ASKED, both doors." `stage_project` refuses
 * an omitted mode rather than picking one, and a refusal with no off switch is a
 * nag — so the ruling pairs it with exactly ONE account default: ask every time
 * (the default) / terminals / subagents. This store owns the client half of it.
 *
 * The load path is where the real risk sits. A failed read that leaves the ref
 * undefined would render the select as blank, a user would "fix" it by picking a
 * mode, and they would have silently turned OFF the asking this project exists to
 * turn ON. So a failure falls back to 'ask' rather than propagating.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockGet = vi.fn()
const mockUpdate = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    settings: {
      getExecutionModeDefault: (...a) => mockGet(...a),
      updateExecutionModeDefault: (...a) => mockUpdate(...a),
    },
  }
  return { api: apiMock, default: apiMock }
})

import { useSettingsStore } from './settings'

describe('settings store — execution-mode default (FE-9555)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockGet.mockReset()
    mockUpdate.mockReset()
  })

  it('starts on "ask" before anything is loaded', () => {
    const store = useSettingsStore()
    expect(store.executionModeDefault).toBe('ask')
  })

  it('loads the stored value from the server', async () => {
    mockGet.mockResolvedValue({ data: { execution_mode_default: 'subagent' } })
    const store = useSettingsStore()

    const loaded = await store.loadExecutionModeDefault()

    expect(loaded).toBe('subagent')
    expect(store.executionModeDefault).toBe('subagent')
  })

  it('falls back to "ask" when the read fails, never to a mode', async () => {
    mockGet.mockRejectedValue(new Error('network'))
    const store = useSettingsStore()

    const loaded = await store.loadExecutionModeDefault()

    expect(loaded).toBe('ask')
    expect(store.executionModeDefault).toBe('ask')
  })

  it('falls back to "ask" when the server answers with something unrecognised', async () => {
    mockGet.mockResolvedValue({ data: { execution_mode_default: 'terminals' } })
    const store = useSettingsStore()

    expect(await store.loadExecutionModeDefault()).toBe('ask')
  })

  it('writes the choice and mirrors what the server confirmed, not what was sent', async () => {
    mockUpdate.mockResolvedValue({ data: { execution_mode_default: 'multi_terminal' } })
    const store = useSettingsStore()

    const saved = await store.updateExecutionModeDefault('multi_terminal')

    expect(mockUpdate).toHaveBeenCalledWith('multi_terminal')
    expect(saved).toBe('multi_terminal')
    expect(store.executionModeDefault).toBe('multi_terminal')
  })
})
