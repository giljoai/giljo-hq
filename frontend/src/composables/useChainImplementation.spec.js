import { describe, it, expect, beforeEach, vi } from 'vitest'
import api from '@/services/api'

const { mockShowToast, mockCopy } = vi.hoisted(() => ({
  mockShowToast: vi.fn(),
  mockCopy: vi.fn(() => Promise.resolve(true)),
}))

vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: mockShowToast }) }))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: mockCopy }) }))

import { useChainImplementation } from './useChainImplementation'

describe('useChainImplementation (FE-6165f)', () => {
  beforeEach(() => {
    mockShowToast.mockClear()
    mockCopy.mockClear()
    mockCopy.mockResolvedValue(true)
  })

  it('fetches the chain-implementation prompt and copies it, with a success toast', async () => {
    api.prompts.chainImplementation.mockResolvedValueOnce({ data: { prompt: 'DRIVE THE CHAIN' } })
    const { copyImplPrompt } = useChainImplementation()
    const ok = await copyImplPrompt('run-9')
    expect(ok).toBe(true)
    expect(api.prompts.chainImplementation).toHaveBeenCalledWith('run-9')
    expect(mockCopy).toHaveBeenCalledWith('DRIVE THE CHAIN')
    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
  })

  it('returns false and toasts an error when the clipboard is blocked', async () => {
    api.prompts.chainImplementation.mockResolvedValueOnce({ data: { prompt: 'X' } })
    mockCopy.mockResolvedValueOnce(false)
    const { copyImplPrompt } = useChainImplementation()
    const ok = await copyImplPrompt('run-9')
    expect(ok).toBe(false)
    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
  })

  it('no-ops without a runId', async () => {
    const { copyImplPrompt } = useChainImplementation()
    const ok = await copyImplPrompt('')
    expect(ok).toBe(false)
    expect(api.prompts.chainImplementation).not.toHaveBeenCalled()
  })

  it('launches the head project gate BEFORE fetching the chain-implementation prompt', async () => {
    api.projects.launchImplementation.mockClear()
    api.prompts.chainImplementation.mockClear()
    api.prompts.chainImplementation.mockResolvedValueOnce({ data: { prompt: 'DRIVE' } })

    const { copyImplPrompt } = useChainImplementation()
    const ok = await copyImplPrompt('run-9', 'head-pid')

    expect(ok).toBe(true)
    expect(api.projects.launchImplementation).toHaveBeenCalledWith('head-pid')
    expect(api.prompts.chainImplementation).toHaveBeenCalledWith('run-9')
    const launchOrder = api.projects.launchImplementation.mock.invocationCallOrder[0]
    const fetchOrder = api.prompts.chainImplementation.mock.invocationCallOrder[0]
    expect(launchOrder).toBeLessThan(fetchOrder)
  })

  it('treats a failing head launch as non-blocking and still copies the prompt', async () => {
    api.projects.launchImplementation.mockClear()
    api.projects.launchImplementation.mockRejectedValueOnce(new Error('gate 409'))
    api.prompts.chainImplementation.mockResolvedValueOnce({ data: { prompt: 'DRIVE' } })

    const { copyImplPrompt } = useChainImplementation()
    const ok = await copyImplPrompt('run-9', 'head-pid')

    expect(ok).toBe(true)
    expect(api.prompts.chainImplementation).toHaveBeenCalledWith('run-9')
    expect(mockCopy).toHaveBeenCalledWith('DRIVE')
  })

  it('skips the launch gate when no head pid is supplied (still fetches)', async () => {
    api.projects.launchImplementation.mockClear()
    api.prompts.chainImplementation.mockResolvedValueOnce({ data: { prompt: 'DRIVE' } })

    const { copyImplPrompt } = useChainImplementation()
    const ok = await copyImplPrompt('run-9')

    expect(ok).toBe(true)
    expect(api.projects.launchImplementation).not.toHaveBeenCalled()
    expect(api.prompts.chainImplementation).toHaveBeenCalledWith('run-9')
  })
})
