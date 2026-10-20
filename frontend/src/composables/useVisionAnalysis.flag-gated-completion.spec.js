import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useVisionAnalysis } from './useVisionAnalysis'

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn(() => Promise.resolve(true)), copied: { value: false } }),
}))

const PRODUCT_ID = 'prod-9794'
const row = (complete) => ({
  id: PRODUCT_ID,
  name: 'Agent Proposal',
  vision_analysis_complete: complete,
  tech_stack: {},
  architecture: {},
  test_config: {},
})
const event = (complete) =>
  new CustomEvent('vision-analysis-complete', {
    detail: { product_id: PRODUCT_ID, fields_written: 3, vision_analysis_complete: complete },
  })

describe('useVisionAnalysis -- completion follows vision_analysis_complete', () => {
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

  it('(a) an intermediate write (flag false, row false) does not complete and keeps polling', async () => {
    const analysis = useVisionAnalysis(patchProductForm, { copyPromptOnStage: false })
    productStore.fetchProductById = vi.fn(() => Promise.resolve(row(false)))

    await analysis.stageAnalysis({ name: 'Doc' }, PRODUCT_ID)
    await analysis.onVisionAnalysisComplete(event(false), PRODUCT_ID)

    expect(patchProductForm).not.toHaveBeenCalled()
    expect(analysis.analysisInProgress.value).toBe(true)

    const callsAfterEvent = productStore.fetchProductById.mock.calls.length
    await vi.advanceTimersByTimeAsync(10_000)
    expect(productStore.fetchProductById.mock.calls.length).toBe(callsAfterEvent + 1)
    expect(patchProductForm).not.toHaveBeenCalled()
    expect(analysis.analysisInProgress.value).toBe(true)

    await vi.advanceTimersByTimeAsync(60_000)
    expect(analysis.analysisHintVisible.value).toBe(false)
    expect(analysis.analysisInProgress.value).toBe(true)
  })

  it('(b) an event that says the analysis is complete completes it', async () => {
    const analysis = useVisionAnalysis(patchProductForm, { copyPromptOnStage: false })
    productStore.fetchProductById = vi.fn(() => Promise.resolve(row(true)))

    await analysis.stageAnalysis({ name: 'Doc' }, PRODUCT_ID)
    await analysis.onVisionAnalysisComplete(event(true), PRODUCT_ID)

    expect(patchProductForm).toHaveBeenCalledTimes(1)
    expect(analysis.analysisInProgress.value).toBe(false)

    const callsAfterEvent = productStore.fetchProductById.mock.calls.length
    await vi.advanceTimersByTimeAsync(30_000)
    expect(productStore.fetchProductById.mock.calls.length).toBe(callsAfterEvent)
  })

  it('(c) after a flag-false event the poll waits for the row flag, then completes', async () => {
    const analysis = useVisionAnalysis(patchProductForm, { copyPromptOnStage: false })
    let current = row(false)
    productStore.fetchProductById = vi.fn(() => Promise.resolve(current))

    await analysis.stageAnalysis({ name: 'Doc' }, PRODUCT_ID)
    await analysis.onVisionAnalysisComplete(event(false), PRODUCT_ID)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(patchProductForm).not.toHaveBeenCalled()
    expect(analysis.analysisInProgress.value).toBe(true)

    current = row(true)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(patchProductForm).toHaveBeenCalledTimes(1)
    expect(analysis.analysisInProgress.value).toBe(false)
  })

  it('(c2) a flag-false event whose fetched row already says complete completes', async () => {
    const analysis = useVisionAnalysis(patchProductForm, { copyPromptOnStage: false })
    productStore.fetchProductById = vi.fn(() => Promise.resolve(row(true)))

    await analysis.stageAnalysis({ name: 'Doc' }, PRODUCT_ID)
    await analysis.onVisionAnalysisComplete(event(false), PRODUCT_ID)

    expect(patchProductForm).toHaveBeenCalledTimes(1)
    expect(analysis.analysisInProgress.value).toBe(false)
  })

  it('(d) a completion event whose fetch rejects is finished later by the poll', async () => {
    const analysis = useVisionAnalysis(patchProductForm, { copyPromptOnStage: false })
    let calls = 0
    productStore.fetchProductById = vi.fn(() =>
      ++calls === 1 ? Promise.reject(new Error('429')) : Promise.resolve(row(true)),
    )

    await analysis.stageAnalysis({ name: 'Doc' }, PRODUCT_ID)
    await analysis.onVisionAnalysisComplete(event(true), PRODUCT_ID).catch(() => {})
    expect(patchProductForm).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(10_000)
    expect(patchProductForm).toHaveBeenCalledTimes(1)
  })
})
