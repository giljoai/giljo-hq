import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import api from '@/services/api'
import { useProjectTabsStore } from '@/stores/projectTabs'

const { mockShowToast } = vi.hoisted(() => ({ mockShowToast: vi.fn() }))

vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: mockShowToast }) }))

import { useChainImplementation } from './useChainImplementation'

describe('useChainImplementation — starting the chain at member 1 (FE-9629)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockShowToast.mockClear()
    api.projects.launchImplementation.mockClear()
    api.projects.launchImplementation.mockResolvedValue({ data: { success: true } })
    api.prompts.chainImplementation.mockClear()
  })

  it('opens the head member\'s launch gate and reports success', async () => {
    const { launchChainHead } = useChainImplementation()

    const ok = await launchChainHead('head-pid')

    expect(ok).toBe(true)
    expect(api.projects.launchImplementation).toHaveBeenCalledWith('head-pid')
  })

  it('the user\'s own press moves the Jobs board to Implementation (noteUserImplement)', async () => {
    const tabs = useProjectTabsStore()
    const note = vi.spyOn(tabs, 'noteUserImplement')
    const { launchChainHead } = useChainImplementation()

    await launchChainHead('head-pid')

    expect(note).toHaveBeenCalledTimes(1)
    expect(note).toHaveBeenCalledWith({ id: 'head-pid' })
    expect(tabs.isLaunched).toBe(true)
    expect(tabs.currentProject).toEqual({ id: 'head-pid' })
  })

  it('a refused launch does not move the board', async () => {
    api.projects.launchImplementation.mockRejectedValueOnce({ response: { data: { message: 'no' } } })
    const note = vi.spyOn(useProjectTabsStore(), 'noteUserImplement')
    await useChainImplementation().launchChainHead('head-pid')
    expect(note).not.toHaveBeenCalled()
  })

  it('copies nothing itself (the chain prompt copy is the caller\'s next step)', async () => {
    const { launchChainHead } = useChainImplementation()

    await launchChainHead('head-pid')

    expect(api.prompts.chainImplementation).not.toHaveBeenCalled()
    expect(mockShowToast).not.toHaveBeenCalled()
  })

  it('reports failure and surfaces the server refusal when the head will not open', async () => {
    api.projects.launchImplementation.mockRejectedValueOnce({
      response: { data: { message: 'Cannot start this chain member yet: FE-9640 is still open.' } },
    })
    const { launchChainHead } = useChainImplementation()

    const ok = await launchChainHead('head-pid')

    expect(ok).toBe(false)
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('FE-9640') }),
    )
  })

  it('no-ops without a head project id', async () => {
    const { launchChainHead } = useChainImplementation()

    const ok = await launchChainHead('')

    expect(ok).toBe(false)
    expect(api.projects.launchImplementation).not.toHaveBeenCalled()
  })
})
