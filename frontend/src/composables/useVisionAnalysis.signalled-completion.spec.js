import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useVisionAnalysis } from './useVisionAnalysis'

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn(() => Promise.resolve(true)), copied: { value: false } }),
}))

const PRODUCT_ID = 'prod-123'
const FLAG_FALSE_ROW = {
  id: PRODUCT_ID,
  name: 'Agent Proposal',
  vision_analysis_complete: false,
  tech_stack: {},
  architecture: {},
  test_config: {},
}

describe('useVisionAnalysis -- completion signalled while the product read failed', () => {
  let patchProductForm
  let productStore

  beforeEach(async () => {
    setActivePinia(createPinia())
    patchProductForm = vi.fn()
    vi.useFakeTimers()
    const { useProductStore } = await import('@/stores/products')
    productStore = useProductStore()
    productStore.updateProduct = vi.fn(() => Promise.resolve({}))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  const event = () => new CustomEvent('vision-analysis-complete', { detail: { product_id: PRODUCT_ID } })

  it('advances on the first successful poll read after the event read failed, even with the flag false', async () => {
    const analysis = useVisionAnalysis(patchProductForm, { copyPromptOnStage: false })
    let calls = 0
    productStore.fetchProductById = vi.fn(() => Promise.resolve(++calls <= 2 ? null : FLAG_FALSE_ROW))

    await analysis.stageAnalysis({ name: 'Doc' }, PRODUCT_ID)
    await analysis.onVisionAnalysisComplete(event(), PRODUCT_ID)
    expect(patchProductForm).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(10_000)
    expect(patchProductForm).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(10_000)

    expect(patchProductForm).toHaveBeenCalledTimes(1)
    expect(patchProductForm).toHaveBeenCalledWith(expect.objectContaining({ name: 'Agent Proposal' }))
  })

  it('without any completion event the poll still waits for the flag', async () => {
    const analysis = useVisionAnalysis(patchProductForm, { copyPromptOnStage: false })
    productStore.fetchProductById = vi.fn(() => Promise.resolve(FLAG_FALSE_ROW))

    await analysis.stageAnalysis({ name: 'Doc' }, PRODUCT_ID)
    await vi.advanceTimersByTimeAsync(30_000)

    expect(patchProductForm).not.toHaveBeenCalled()
  })

  it('an event for another product does not arm the poll', async () => {
    const analysis = useVisionAnalysis(patchProductForm, { copyPromptOnStage: false })
    productStore.fetchProductById = vi.fn(() => Promise.resolve(FLAG_FALSE_ROW))

    await analysis.stageAnalysis({ name: 'Doc' }, PRODUCT_ID)
    await analysis.onVisionAnalysisComplete(
      new CustomEvent('vision-analysis-complete', { detail: { product_id: 'other' } }),
      PRODUCT_ID,
    )
    await vi.advanceTimersByTimeAsync(30_000)

    expect(patchProductForm).not.toHaveBeenCalled()
  })
})
