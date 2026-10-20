import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn(async () => true), copied: { value: false } }),
}))

import ProductForm from '@/components/products/ProductForm.vue'
import { useProductStore } from '@/stores/products'

const PRODUCT_ID = 'prod-wizard-9794'
const row = (complete, name) => ({
  id: PRODUCT_ID,
  name,
  description: 'Filled by the agent',
  vision_analysis_complete: complete,
  tech_stack: {},
  architecture: {},
  test_config: {},
})

function emitServerEvent(complete) {
  window.dispatchEvent(
    new CustomEvent('vision-analysis-complete', {
      detail: { product_id: PRODUCT_ID, fields_written: 2, vision_analysis_complete: complete },
    }),
  )
}

describe('ProductForm — analysis ends only when the server says it is complete (FE-9794)', () => {
  let productStore
  let wrapper

  beforeEach(() => {
    const pinia = createPinia()
    setActivePinia(pinia)
    vi.useFakeTimers()
    productStore = useProductStore()
    productStore.updateProduct = vi.fn(async () => ({}))
    wrapper = mount(ProductForm, {
      props: {
        modelValue: true,
        isEdit: false,
        product: { id: PRODUCT_ID, name: 'Draft', vision_analysis_complete: false },
        existingVisionDocuments: [{ id: 'd1', filename: 'vision.md' }],
      },
      global: { plugins: [pinia] },
    })
  })

  afterEach(() => {
    wrapper.unmount()
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('stays analyzing through an intermediate write, then fills the form on the completing write', async () => {
    productStore.fetchProductById = vi.fn(async () => row(false, 'Partial Name'))
    await wrapper.vm.stageAnalysis()
    await flushPromises()
    expect(wrapper.vm.analysisInProgress).toBe(true)

    emitServerEvent(false)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(wrapper.vm.analysisInProgress).toBe(true)
    expect(wrapper.vm.productForm.name).not.toBe('Partial Name')

    productStore.fetchProductById = vi.fn(async () => row(true, 'Agent Proposed Name'))
    emitServerEvent(true)
    await flushPromises()

    expect(wrapper.vm.analysisInProgress).toBe(false)
    expect(wrapper.vm.productForm.name).toBe('Agent Proposed Name')
  })
})
