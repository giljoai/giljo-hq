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
