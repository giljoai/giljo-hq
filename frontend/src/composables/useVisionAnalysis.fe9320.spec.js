/**
 * useVisionAnalysis.fe9320.spec.js — FE-9320
 *
 * Two things the pre-existing spec cannot see:
 *
 * 1. THE FINISH STATE COULD NOT ARRIVE. completeAnalysis() is the only thing
 *    that calls patchProductForm — the hook the tutorial uses to advance to the
 *    review screen — and it can only run with a product in hand. When the
 *    completion event fired but fetchProductById threw or returned null, the
 *    advance was skipped AND the same `finally` tore down the FE-9166 poll that
 *    would have retried it. The wizard then sat on "Waiting for your agent's
 *    analysis..." forever, with nothing left running to rescue it.
 *
 * 2. A consumer must be able to stage an analysis WITHOUT the clipboard write,
 *    so a screen that stages as a side effect of another action can own an
 *    explicit copy control instead.
 *
 * Edition scope: Both (shared frontend/src).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useVisionAnalysis } from './useVisionAnalysis'

const copyMock = vi.fn(() => Promise.resolve(true))
vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: copyMock, copied: { value: false } }),
}))

const PRODUCT_ID = 'prod-123'

const COMPLETED_ROW = {
  id: PRODUCT_ID,
  name: 'Recovered Product',
  vision_analysis_complete: true,
  tech_stack: {},
  architecture: {},
  test_config: {},
}

describe('useVisionAnalysis — the finish state can actually arrive (FE-9320)', () => {
  let patchProductForm

  beforeEach(() => {
    setActivePinia(createPinia())
    patchProductForm = vi.fn()
    vi.clearAllMocks()
    copyMock.mockImplementation(() => Promise.resolve(true))
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  async function stage(analysis, productStore) {
    productStore.updateProduct = vi.fn(() => Promise.resolve({}))
    await analysis.stageAnalysis({ name: 'My Product', extractionCustomInstructions: '' }, PRODUCT_ID)
  }

  function completionEvent() {
    return new CustomEvent('vision-analysis-complete', { detail: { product_id: PRODUCT_ID } })
  }

  it('recovers when the product fetch REJECTS during the completion event', async () => {
    const analysis = useVisionAnalysis(patchProductForm)
    const { useProductStore } = await import('@/stores/products')
    const productStore = useProductStore()

    let calls = 0
    productStore.fetchProductById = vi.fn(() => {
      calls += 1
      if (calls === 1) return Promise.reject(new Error('network down'))
      return Promise.resolve(COMPLETED_ROW)
    })

    await stage(analysis, productStore)
    await analysis.onVisionAnalysisComplete(completionEvent(), PRODUCT_ID).catch(() => {})

    // Nothing to patch yet — but the recovery poll must still be armed.
    expect(patchProductForm).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(10_000)

    expect(patchProductForm).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Recovered Product' }),
    )
  })

  it('recovers when the product fetch returns NULL during the completion event', async () => {
    const analysis = useVisionAnalysis(patchProductForm)
    const { useProductStore } = await import('@/stores/products')
    const productStore = useProductStore()

    let calls = 0
    productStore.fetchProductById = vi.fn(() => {
      calls += 1
      return Promise.resolve(calls === 1 ? null : COMPLETED_ROW)
    })

    await stage(analysis, productStore)
    await analysis.onVisionAnalysisComplete(completionEvent(), PRODUCT_ID)

    expect(patchProductForm).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(10_000)

    expect(patchProductForm).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Recovered Product' }),
    )
  })

  it('a SUCCESSFUL completion still stops the poll (no runaway interval)', async () => {
    const analysis = useVisionAnalysis(patchProductForm)
    const { useProductStore } = await import('@/stores/products')
    const productStore = useProductStore()
    productStore.fetchProductById = vi.fn(() => Promise.resolve(COMPLETED_ROW))

    await stage(analysis, productStore)
    await analysis.onVisionAnalysisComplete(completionEvent(), PRODUCT_ID)

    expect(patchProductForm).toHaveBeenCalledTimes(1)
    const afterCompletion = productStore.fetchProductById.mock.calls.length

    await vi.advanceTimersByTimeAsync(30_000)

    expect(productStore.fetchProductById).toHaveBeenCalledTimes(afterCompletion)
  })
})

describe('useVisionAnalysis — copyPromptOnStage opt-out (FE-9320)', () => {
  let patchProductForm

  beforeEach(() => {
    setActivePinia(createPinia())
    patchProductForm = vi.fn()
    vi.clearAllMocks()
    copyMock.mockImplementation(() => Promise.resolve(true))
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not touch the clipboard when the consumer opted out, but publishes the prompt', async () => {
    const { stageAnalysis, analysisPromptText, analysisInProgress, promptFallbackText } =
      useVisionAnalysis(patchProductForm, { copyPromptOnStage: false })
    const { useProductStore } = await import('@/stores/products')
    useProductStore().updateProduct = vi.fn(() => Promise.resolve({}))

    await stageAnalysis({ name: 'My Product', extractionCustomInstructions: '' }, PRODUCT_ID)

    expect(copyMock).not.toHaveBeenCalled()
    // The prompt is still published for an explicit control to copy...
    expect(analysisPromptText.value).toContain(`get_vision_doc(product_id="${PRODUCT_ID}")`)
    // ...and no "clipboard blocked" fallback is armed, because nothing was blocked.
    expect(promptFallbackText.value).toBeNull()
    // Staging still did its real work.
    expect(analysisInProgress.value).toBe(true)
  })

  it('still copies by DEFAULT — the product-card path depends on it', async () => {
    const { stageAnalysis, analysisPromptText } = useVisionAnalysis(patchProductForm)
    const { useProductStore } = await import('@/stores/products')
    useProductStore().updateProduct = vi.fn(() => Promise.resolve({}))

    await stageAnalysis({ name: 'My Product', extractionCustomInstructions: '' }, PRODUCT_ID)

    expect(copyMock).toHaveBeenCalledTimes(1)
    expect(copyMock.mock.calls[0][0]).toBe(analysisPromptText.value)
  })
})
