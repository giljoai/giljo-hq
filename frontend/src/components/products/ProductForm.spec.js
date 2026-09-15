import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick, ref } from 'vue'

const { pushMock, showToastMock, apiMock } = vi.hoisted(() => {
  return {
    pushMock: vi.fn(),
    showToastMock: vi.fn(),
    apiMock: {
      products: {
        getContextUpdateProject: vi.fn(),
      },
      taxonomyTypes: {
        list: vi.fn(),
      },
      projects: {
        create: vi.fn(),
      },
    },
  }
})

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock, hideToast: vi.fn(), removeToast: vi.fn(), toasts: { value: [] } }),
}))

vi.mock('@/services/api', () => ({
  default: apiMock,
  api: apiMock,
  apiClient: {},
}))

vi.mock('@/composables/useVisionAnalysis', () => ({
  useVisionAnalysis: () => ({
    analysisPromptCopied: ref(false),
    promptFallbackText: ref(null),
    analysisInProgress: ref(false),
    analysisAgentConnected: ref(false),
    analysisHintVisible: ref(false),
    resetAnalysisState: vi.fn(),
    stageAnalysis: vi.fn(),
    onVisionAnalysisStarted: vi.fn(),
    onVisionAnalysisComplete: vi.fn(),
  }),
}))

import ProductForm from '@/components/products/ProductForm.vue'
import { useProductStore } from '@/stores/products'

function findFooterPrimaryBtn(wrapper) {
  const footer = wrapper.find('.dlg-footer')
  if (!footer.exists()) return undefined
  const primaryBtns = footer.findAll('button').filter((b) => {
    const html = b.html()
    return (
      html.includes('Next') ||
      html.includes('Save Changes') ||
      html.includes('Create Product') ||
      html.includes('Stage analysis') ||
      html.includes('Analyzing')
    )
  })
  return primaryBtns[primaryBtns.length - 1]
}

describe('ProductForm.vue — flattened Setup tab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the Skip AI Analysis checkbox by default in create mode', () => {
    const wrapper = mount(ProductForm, {
      props: {
        modelValue: true,
        isEdit: false,
        product: null,
        existingVisionDocuments: [],
      },
    })
    expect(wrapper.html()).toContain('Skip AI Analysis')
    wrapper.unmount()
  })

  it('renders the secondary "Create blank" affordance in create mode', () => {
    const wrapper = mount(ProductForm, {
      props: {
        modelValue: true,
        isEdit: false,
        product: null,
        existingVisionDocuments: [],
      },
    })
    expect(wrapper.find('[data-test="create-blank-toggle"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('does NOT render the legacy radio group or educational alert', () => {
    const wrapper = mount(ProductForm, {
      props: {
        modelValue: true,
        isEdit: false,
        product: null,
        existingVisionDocuments: [
          { id: 'doc-1', filename: 'vision.md', file_size_bytes: 100, created_at: '2026-01-01' },
        ],
      },
    })
    const html = wrapper.html()
    expect(html).not.toContain('Manually define product')
    expect(html).not.toContain('Use AI coding agent')
    expect(html).not.toContain('Want AI to analyze this document')
    wrapper.unmount()
  })

  it('hides the Customize product extraction instructions panel until a vision doc is attached', () => {
    const wrapper = mount(ProductForm, {
      props: {
        modelValue: true,
        isEdit: false,
        product: null,
        existingVisionDocuments: [],
      },
    })
    expect(wrapper.html()).not.toContain('Customize product extraction instructions')
    wrapper.unmount()
  })

  it('shows the Customize product extraction instructions panel once a vision doc is attached', () => {
    const wrapper = mount(ProductForm, {
      props: {
        modelValue: true,
        isEdit: false,
        product: null,
        existingVisionDocuments: [
          { id: 'doc-1', filename: 'vision.md', file_size_bytes: 100, created_at: '2026-01-01' },
        ],
      },
    })
    expect(wrapper.html()).toContain('Customize product extraction instructions')
    wrapper.unmount()
  })

  it('hides the Customize product extraction instructions panel when Skip AI Analysis is checked', async () => {
    const wrapper = mount(ProductForm, {
      props: {
        modelValue: true,
        isEdit: false,
        product: null,
        existingVisionDocuments: [
          { id: 'doc-1', filename: 'vision.md', file_size_bytes: 100, created_at: '2026-01-01' },
        ],
      },
    })
    expect(wrapper.html()).toContain('Customize product extraction instructions')
    wrapper.vm.skipAiAnalysis = true
    await wrapper.vm.$nextTick()
    expect(wrapper.html()).not.toContain('Customize product extraction instructions')
    wrapper.unmount()
  })

  it('Skip AI Analysis keeps the document (no NULL-description warning) and shows the doc-still-uploads note', async () => {
    const wrapper = mount(ProductForm, {
      props: {
        modelValue: true,
        isEdit: false,
        product: null,
        existingVisionDocuments: [],
      },
    })
    expect(wrapper.html()).not.toContain('document still uploads and is chunked')
    wrapper.vm.skipAiAnalysis = true
    await nextTick()
    expect(wrapper.html()).toContain('document still uploads and is chunked')
    expect(wrapper.html()).not.toContain('the product description and AI context start empty')
    wrapper.unmount()
  })

  it('Create blank shows the empty-context warning', async () => {
    const wrapper = mount(ProductForm, {
      props: {
        modelValue: true,
        isEdit: false,
        product: null,
        existingVisionDocuments: [],
      },
    })
    expect(wrapper.html()).not.toContain('the product description and AI context start empty')
    wrapper.vm.createBlank = true
    await nextTick()
    expect(wrapper.html()).toContain('the product description and AI context start empty')
    wrapper.unmount()
  })

  it('does NOT disable the file picker when Skip AI Analysis is checked (doc still required), but DOES when Create blank is chosen', async () => {
    const wrapper = mount(ProductForm, {
      props: {
        modelValue: true,
        isEdit: false,
        product: { id: 'prod-skip', name: 'SkipTest' },
        existingVisionDocuments: [],
      },
    })
    wrapper.vm.productForm.name = 'SkipTest'
    await nextTick()
    let fileInput = wrapper.find('input[type="file"]')
    expect(fileInput.exists()).toBe(true)
    expect(fileInput.attributes('disabled')).toBeUndefined()

    wrapper.vm.skipAiAnalysis = true
    await nextTick()
    fileInput = wrapper.find('input[type="file"]')
    expect(fileInput.attributes('disabled')).toBeUndefined()

    wrapper.vm.skipAiAnalysis = false
    wrapper.vm.createBlank = true
    await nextTick()
    fileInput = wrapper.find('input[type="file"]')
    expect(fileInput.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})

describe('ProductForm.vue — footer single-CTA state matrix', () => {
  let productStore
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    productStore = useProductStore()
  })

  function mountForm({
    docs = [],
    name = '',
    skipAiAnalysis = false,
    createBlank = false,
    visionAnalysisComplete = false,
    productId = 'prod-cta-1',
    isEdit = false,
  } = {}) {
    const product = {
      id: productId,
      name,
      vision_analysis_complete: visionAnalysisComplete,
    }
    productStore.$patch({
      currentProductId: productId,
      currentProduct: { ...product },
    })
    const wrapper = mount(ProductForm, {
      global: { plugins: [pinia] },
      props: {
        modelValue: true,
        isEdit,
        product,
        existingVisionDocuments: docs,
      },
    })
    wrapper.vm.productForm.name = name
    wrapper.vm.skipAiAnalysis = skipAiAnalysis
    wrapper.vm.createBlank = createBlank
    return wrapper
  }

  it('State 1: idle, no docs, Skip OFF → "Stage analysis" + disabled', async () => {
    const wrapper = mountForm({ docs: [], name: 'My Product', skipVision: false })
    await nextTick()
    const btn = findFooterPrimaryBtn(wrapper)
    expect(btn).toBeDefined()
    expect(btn.html()).toContain('Stage analysis')
    expect(btn.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('State 2: idle, ≥1 doc, Skip OFF, not yet analyzed → "Stage analysis" + enabled', async () => {
    const wrapper = mountForm({
      docs: [{ id: 'd1', filename: 'a.md' }],
      name: 'My Product',
      skipVision: false,
      visionAnalysisComplete: false,
    })
    await nextTick()
    const btn = findFooterPrimaryBtn(wrapper)
    expect(btn).toBeDefined()
    expect(btn.html()).toContain('Stage analysis')
    expect(btn.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('State 3: agent running (analysisInProgress) → "Analyzing" + disabled', async () => {
    const wrapper = mountForm({
      docs: [{ id: 'd1', filename: 'a.md' }],
      name: 'My Product',
      skipVision: false,
    })
    wrapper.vm.analysisInProgress = true
    await nextTick()
    const btn = findFooterPrimaryBtn(wrapper)
    expect(btn).toBeDefined()
    expect(btn.html()).toContain('Analyzing')
    expect(btn.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('State 4: analysis complete → "Next" + enabled', async () => {
    const wrapper = mountForm({
      docs: [{ id: 'd1', filename: 'a.md' }],
      name: 'My Product',
      skipVision: false,
      visionAnalysisComplete: true,
    })
    await nextTick()
    const btn = findFooterPrimaryBtn(wrapper)
    expect(btn).toBeDefined()
    expect(btn.html()).toContain('Next')
    expect(btn.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('State 5: Skip AI Analysis ON, name filled, but NO doc → "Next" + disabled (doc required)', async () => {
    const wrapper = mountForm({ docs: [], name: 'My Product', skipAiAnalysis: true })
    await nextTick()
    const btn = findFooterPrimaryBtn(wrapper)
    expect(btn).toBeDefined()
    expect(btn.html()).toContain('Next')
    expect(btn.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('State 5b: Skip AI Analysis ON, name filled, WITH doc → "Next" + enabled', async () => {
    const wrapper = mountForm({
      docs: [{ id: 'd1', filename: 'a.md' }],
      name: 'My Product',
      skipAiAnalysis: true,
    })
    await nextTick()
    const btn = findFooterPrimaryBtn(wrapper)
    expect(btn).toBeDefined()
    expect(btn.html()).toContain('Next')
    expect(btn.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('State 6: Create blank ON, name filled, no doc → "Next" + enabled', async () => {
    const wrapper = mountForm({ docs: [], name: 'My Product', createBlank: true })
    await nextTick()
    const btn = findFooterPrimaryBtn(wrapper)
    expect(btn).toBeDefined()
    expect(btn.html()).toContain('Next')
    expect(btn.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('Create blank ON but no name → "Next" + disabled (name required)', async () => {
    const wrapper = mountForm({ docs: [], name: '', createBlank: true })
    await nextTick()
    const btn = findFooterPrimaryBtn(wrapper)
    expect(btn).toBeDefined()
    expect(btn.html()).toContain('Next')
    expect(btn.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})

describe('ProductForm.vue — BE-5118 vision analysis gate (post-flatten)', () => {
  let productStore
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    productStore = useProductStore()
  })

  function mountWithFlag({
    visionAnalysisComplete,
    docs,
    isEdit = false,
    productId = 'prod-gate-1',
  }) {
    const product = {
      id: productId,
      name: 'Gate Test Product',
      vision_analysis_complete: visionAnalysisComplete,
    }
    productStore.$patch({
      currentProductId: productId,
      currentProduct: { ...product },
    })
    return mount(ProductForm, {
      global: { plugins: [pinia] },
      props: {
        modelValue: true,
        isEdit,
        product,
        existingVisionDocuments: docs,
      },
    })
  }

  it('locks tabs info/tech/arch/features while the gate is closed', async () => {
    const wrapper = mountWithFlag({
      visionAnalysisComplete: false,
      docs: [{ id: 'd1', filename: 'a.md' }],
    })
    await nextTick()
    const allBtns = wrapper.findAll('button')
    const lockableLabels = ['Product Info', 'Tech Stack', 'Architecture', 'Testing']
    for (const label of lockableLabels) {
      const btn = allBtns.find((b) => b.text().includes(label))
      expect(btn, `tab "${label}" should render`).toBeDefined()
      expect(btn.attributes('disabled'), `tab "${label}" should be disabled while gate closed`).toBeDefined()
    }
    wrapper.unmount()
  })

  it('unlocks all tabs once the gate opens', async () => {
    const wrapper = mountWithFlag({
      visionAnalysisComplete: true,
      docs: [{ id: 'd1', filename: 'a.md' }],
    })
    await nextTick()
    const allBtns = wrapper.findAll('button')
    const lockableLabels = ['Product Info', 'Tech Stack', 'Architecture', 'Testing']
    for (const label of lockableLabels) {
      const btn = allBtns.find((b) => b.text().includes(label))
      expect(btn).toBeDefined()
      expect(btn.attributes('disabled'), `tab "${label}" should be enabled once gate opens`).toBeUndefined()
    }
    wrapper.unmount()
  })

  it('multi-file end-to-end: 2 docs pending → store flips → Next enables', async () => {
    const docs = [
      { id: 'd1', filename: 'a.md' },
      { id: 'd2', filename: 'b.md' },
    ]
    const wrapper = mountWithFlag({ visionAnalysisComplete: false, docs })
    await nextTick()
    let nextBtn = findFooterPrimaryBtn(wrapper)
    expect(nextBtn.html()).toContain('Stage analysis')

    productStore.$patch({
      productsById: {
        ...productStore.productsById,
        'prod-gate-1': { ...productStore.currentProduct, vision_analysis_complete: true },
      },
    })
    await nextTick()

    nextBtn = findFooterPrimaryBtn(wrapper)
    expect(nextBtn.html()).toContain('Next')
    expect(nextBtn.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('edit mode is not affected by the gate (Save Changes still enabled)', async () => {
    const wrapper = mountWithFlag({
      visionAnalysisComplete: false,
      docs: [{ id: 'd1', filename: 'a.md' }],
      isEdit: true,
    })
    await nextTick()
    wrapper.vm.formValid = true
    await nextTick()
    const saveBtn = findFooterPrimaryBtn(wrapper)
    expect(saveBtn).toBeDefined()
    expect(saveBtn.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('FE-6007: edit mode unlocks tabs even when docs present and analysis incomplete', async () => {
    const wrapper = mountWithFlag({
      visionAnalysisComplete: false,
      docs: [{ id: 'd1', filename: 'a.md' }],
      isEdit: true,
    })
    await nextTick()
    expect(wrapper.vm.isTabLocked('tech')).toBe(false)
    expect(wrapper.vm.isTabLocked('features')).toBe(false)
    expect(wrapper.vm.isTabLocked('info')).toBe(false)
    expect(wrapper.vm.isTabLocked('arch')).toBe(false)
    const allBtns = wrapper.findAll('button')
    const lockableLabels = ['Product Info', 'Tech Stack', 'Architecture', 'Testing']
    for (const label of lockableLabels) {
      const btn = allBtns.find((b) => b.text().includes(label))
      expect(btn, `tab "${label}" should render`).toBeDefined()
      expect(btn.attributes('disabled'), `tab "${label}" must not be disabled in edit mode`).toBeUndefined()
    }
    wrapper.unmount()
  })

  it('FE-6007: Skip-vision checkbox and warning alert are absent in edit mode', async () => {
    const wrapper = mountWithFlag({
      visionAnalysisComplete: false,
      docs: [{ id: 'd1', filename: 'a.md' }],
      isEdit: true,
    })
    await nextTick()
    expect(wrapper.html()).not.toContain('Skip AI Analysis')
    expect(wrapper.html()).not.toContain('document still uploads and is chunked')
    wrapper.unmount()
  })

  it('FE-6007: create mode regression — docs present + analysis incomplete still locks tabs and shows Skip checkbox', async () => {
    const wrapper = mountWithFlag({
      visionAnalysisComplete: false,
      docs: [{ id: 'd1', filename: 'a.md' }],
      isEdit: false,
    })
    await nextTick()
    expect(wrapper.vm.isTabLocked('tech')).toBe(true)
    expect(wrapper.vm.isTabLocked('features')).toBe(true)
    const allBtns = wrapper.findAll('button')
    const lockableLabels = ['Product Info', 'Tech Stack', 'Architecture', 'Testing']
    for (const label of lockableLabels) {
      const btn = allBtns.find((b) => b.text().includes(label))
      expect(btn, `tab "${label}" should render`).toBeDefined()
      expect(btn.attributes('disabled'), `tab "${label}" must still be disabled in create mode`).toBeDefined()
    }
    expect(wrapper.html()).toContain('Skip AI Analysis')
    wrapper.unmount()
  })
})

describe('ProductForm.vue — FE-9121 store-first gate (not selection-first)', () => {
  let productStore
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    productStore = useProductStore()
  })

  it('CTA advances via productsById write-through even when the edited product is NOT the selected product', async () => {
    const product = { id: 'p-new', name: 'Wizard Product', vision_analysis_complete: false }
    productStore.$patch({ currentProductId: 'p-other-selected', currentProduct: { id: 'p-other-selected' } })

    const wrapper = mount(ProductForm, {
      global: { plugins: [pinia] },
      props: {
        modelValue: true,
        isEdit: false,
        product,
        existingVisionDocuments: [{ id: 'd1', filename: 'a.md' }],
      },
    })
    await nextTick()
    let btn = findFooterPrimaryBtn(wrapper)
    expect(btn.html()).toContain('Stage analysis')

    productStore.$patch({
      productsById: { ...productStore.productsById, 'p-new': { ...product, vision_analysis_complete: true } },
    })
    window.dispatchEvent(new CustomEvent('vision-analysis-complete', { detail: { product_id: 'p-new' } }))
    await nextTick()

    btn = findFooterPrimaryBtn(wrapper)
    expect(btn.html()).toContain('Next')
    expect(btn.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
})

describe('ProductForm.vue — FE-6088 three-path onboarding gate', () => {
  let productStore
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    productStore = useProductStore()
  })

  function mountGate({
    docs = [],
    visionAnalysisComplete = false,
    productId = 'prod-6088',
  } = {}) {
    const product = {
      id: productId,
      name: 'Gate Product',
      vision_analysis_complete: visionAnalysisComplete,
    }
    productStore.$patch({
      currentProductId: productId,
      currentProduct: { ...product },
    })
    return mount(ProductForm, {
      global: { plugins: [pinia] },
      props: {
        modelValue: true,
        isEdit: false,
        product,
        existingVisionDocuments: docs,
      },
    })
  }

  const LOCKABLE = ['info', 'tech', 'arch', 'features']

  it('Gate state 1 — locked until a doc is attached: new product, no doc, no path chosen → all tabs LOCKED', async () => {
    const wrapper = mountGate({ docs: [] })
    await nextTick()
    for (const t of LOCKABLE) {
      expect(wrapper.vm.isTabLocked(t), `tab "${t}" should be locked by default`).toBe(true)
    }
    wrapper.unmount()
  })

  it('Gate state 2 — Skip AI Analysis requires a doc, then unlocks', async () => {
    const wrapper = mountGate({ docs: [] })
    wrapper.vm.skipAiAnalysis = true
    await nextTick()
    for (const t of LOCKABLE) {
      expect(wrapper.vm.isTabLocked(t), `tab "${t}" must stay locked: skip on, no doc`).toBe(true)
    }
    await wrapper.setProps({ existingVisionDocuments: [{ id: 'd1', filename: 'a.md' }] })
    await nextTick()
    for (const t of LOCKABLE) {
      expect(wrapper.vm.isTabLocked(t), `tab "${t}" must unlock: skip on + doc`).toBe(false)
    }
    wrapper.unmount()
  })

  it('Gate state 3 — Create blank unlocks with NO doc', async () => {
    const wrapper = mountGate({ docs: [] })
    wrapper.vm.createBlank = true
    await nextTick()
    for (const t of LOCKABLE) {
      expect(wrapper.vm.isTabLocked(t), `tab "${t}" must unlock via create-blank`).toBe(false)
    }
    wrapper.unmount()
  })

  it('Gate state 4 — Path A: optimistic unlock on analysis completion', async () => {
    const wrapper = mountGate({ docs: [{ id: 'd1', filename: 'a.md' }], visionAnalysisComplete: false })
    await nextTick()
    expect(wrapper.vm.isTabLocked('tech')).toBe(true)
    productStore.$patch({
      productsById: {
        ...productStore.productsById,
        'prod-6088': { ...productStore.currentProduct, vision_analysis_complete: true },
      },
    })
    await nextTick()
    for (const t of LOCKABLE) {
      expect(wrapper.vm.isTabLocked(t), `tab "${t}" must unlock on completion`).toBe(false)
    }
    wrapper.unmount()
  })

  it('the two paths are mutually exclusive (choosing one clears the other)', async () => {
    const wrapper = mountGate({ docs: [{ id: 'd1', filename: 'a.md' }] })
    wrapper.vm.onSkipAiAnalysis(true)
    await nextTick()
    expect(wrapper.vm.skipAiAnalysis).toBe(true)
    expect(wrapper.vm.createBlank).toBe(false)
    wrapper.vm.onCreateBlank(true)
    await nextTick()
    expect(wrapper.vm.createBlank).toBe(true)
    expect(wrapper.vm.skipAiAnalysis).toBe(false)
    wrapper.unmount()
  })
})

describe('useVisionAnalysis — BE-9164 slim single-source prompt', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetModules()
  })

  it('points the agent at get_vision_document + extraction_instructions and teaches staged update_product_context calls', async () => {
    vi.doUnmock('@/composables/useVisionAnalysis')
    const copyMock = vi.fn(() => Promise.resolve(true))
    vi.doMock('@/composables/useClipboard', () => ({
      useClipboard: () => ({ copy: copyMock, copied: { value: false } }),
    }))
    const { useVisionAnalysis } = await import('@/composables/useVisionAnalysis')
    const { stageAnalysis } = useVisionAnalysis(vi.fn())
    const productForm = { name: 'MyProduct', extractionCustomInstructions: '' }
    await stageAnalysis(productForm, 'prod-xyz')

    expect(copyMock).toHaveBeenCalledTimes(1)
    const prompt = copyMock.mock.calls[0][0]
    expect(prompt).toContain('get_vision_document(product_id="prod-xyz")')
    expect(prompt).toMatch(/extraction_instructions/)
    expect(prompt).toContain('update_product_context')
    expect(prompt).toMatch(/stages|staged/i)
    expect(prompt).toMatch(/emit_completion/)
    expect(prompt).toMatch(/vision_analysis_complete/)
    expect(prompt).toContain('MyProduct')
  })
})


describe('ProductForm.vue — FE-5073 staleness banner + CTX bootstrap CTA', () => {
  let productStore
  let pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    productStore = useProductStore()
    pushMock.mockReset()
    showToastMock.mockReset()
    apiMock.products.getContextUpdateProject.mockReset()
    apiMock.taxonomyTypes.list.mockReset()
    apiMock.projects.create.mockReset()
  })

  function mountWithProduct({
    isEdit = true,
    productOverrides = {},
    docs = [],
    productId = 'prod-fe5073',
  } = {}) {
    const product = {
      id: productId,
      name: 'AcmeApp',
      vision_analysis_complete: true,
      consolidated_vision_hash: 'aaaa',
      consolidated_at: '2026-05-01T00:00:00Z',
      vision_inputs_hash: 'sha256:aaaa',
      ...productOverrides,
    }
    productStore.$patch({ currentProductId: productId, currentProduct: { ...product } })
    return mount(ProductForm, {
      global: { plugins: [pinia] },
      props: {
        modelValue: true,
        isEdit,
        product,
        existingVisionDocuments: docs,
      },
    })
  }

  it('1. hides banner in create mode even when hashes differ', async () => {
    const wrapper = mountWithProduct({
      isEdit: false,
      productOverrides: { vision_inputs_hash: 'sha256:bbbb', consolidated_vision_hash: 'aaaa' },
    })
    await nextTick()
    expect(wrapper.find('[data-test="ctx-staleness-banner"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('2. hides banner in edit mode when sha256-prefixed hash matches raw-hex persisted hash', async () => {
    const wrapper = mountWithProduct({
      productOverrides: { vision_inputs_hash: 'sha256:aaaa', consolidated_vision_hash: 'aaaa' },
    })
    await nextTick()
    expect(wrapper.find('[data-test="ctx-staleness-banner"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('3. shows banner in edit mode when consolidated_vision_hash is null but inputs hash is non-empty', async () => {
    const wrapper = mountWithProduct({
      productOverrides: {
        vision_inputs_hash: 'sha256:abc',
        consolidated_vision_hash: null,
      },
    })
    await nextTick()
    expect(wrapper.find('[data-test="ctx-staleness-banner"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('4. shows banner in edit mode when hashes differ', async () => {
    const wrapper = mountWithProduct({
      productOverrides: { vision_inputs_hash: 'sha256:bbbb', consolidated_vision_hash: 'aaaa' },
    })
    await nextTick()
    expect(wrapper.find('[data-test="ctx-staleness-banner"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('5. hides banner when vision_inputs_hash is the sha256:empty sentinel', async () => {
    const wrapper = mountWithProduct({
      productOverrides: {
        vision_inputs_hash: 'sha256:empty',
        consolidated_vision_hash: null,
      },
    })
    await nextTick()
    expect(wrapper.find('[data-test="ctx-staleness-banner"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('6. banner is reactive to store mutation, not props', async () => {
    const wrapper = mountWithProduct({
      productOverrides: { vision_inputs_hash: 'sha256:bbbb', consolidated_vision_hash: 'aaaa' },
    })
    await nextTick()
    expect(wrapper.find('[data-test="ctx-staleness-banner"]').exists()).toBe(true)
    productStore.$patch({
      productsById: {
        ...productStore.productsById,
        'prod-fe5073': {
          ...productStore.currentProduct,
          consolidated_vision_hash: 'bbbb',
        },
      },
    })
    await nextTick()
    expect(wrapper.find('[data-test="ctx-staleness-banner"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('7. counter uses doc count when consolidated_at is present (singular)', async () => {
    const docs = [
      { id: 'd1', filename: 'a.md', created_at: '2026-05-15T00:00:00Z' },
    ]
    const wrapper = mountWithProduct({
      productOverrides: {
        vision_inputs_hash: 'sha256:bbbb',
        consolidated_vision_hash: 'aaaa',
        consolidated_at: '2026-05-01T00:00:00Z',
      },
      docs,
    })
    await nextTick()
    const banner = wrapper.find('[data-test="ctx-staleness-banner"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('1 document added since the last AI context refresh')
    wrapper.unmount()
  })

  it('8. counter falls back to generic copy when 0 new docs since consolidation', async () => {
    const docs = [
      { id: 'd1', filename: 'a.md', created_at: '2026-04-01T00:00:00Z' },
    ]
    const wrapper = mountWithProduct({
      productOverrides: {
        vision_inputs_hash: 'sha256:bbbb',
        consolidated_vision_hash: 'aaaa',
        consolidated_at: '2026-05-01T00:00:00Z',
      },
      docs,
    })
    await nextTick()
    const banner = wrapper.find('[data-test="ctx-staleness-banner"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('Your vision documents have changed since the last AI context refresh.')
    wrapper.unmount()
  })

  it('9. clicking CTA opens the confirm dialog with verbatim copy', async () => {
    const wrapper = mountWithProduct({
      productOverrides: { vision_inputs_hash: 'sha256:bbbb', consolidated_vision_hash: 'aaaa' },
    })
    await nextTick()
    expect(wrapper.vm.ctxConfirmOpen).toBe(false)
    await wrapper.find('[data-test="ctx-update-cta"]').trigger('click')
    await nextTick()
    expect(wrapper.vm.ctxConfirmOpen).toBe(true)
    expect(wrapper.html()).toContain('Spawning project CTX-#### — run this next to refresh')
    expect(wrapper.html()).toContain('appear in your projects list')
    wrapper.unmount()
  })

  it('10. confirm → idempotency probe (404) → POST with {document_name, document_type} payload + toast + file-attach does NOT spawn', async () => {
    apiMock.products.getContextUpdateProject.mockRejectedValueOnce({ response: { status: 404 } })
    apiMock.taxonomyTypes.list.mockResolvedValueOnce({
      data: [
        { id: 'tax-other', abbreviation: 'BE', label: 'Backend' },
        { id: 'tax-ctx', abbreviation: 'CTX', label: 'Context update' },
      ],
    })
    apiMock.projects.create.mockResolvedValueOnce({
      data: { id: 'proj-99', taxonomy_alias: 'CTX-0001' },
    })

    const docs = [
      { id: 'd1', filename: 'one.md', document_type: 'text/markdown', created_at: '2026-05-15T00:00:00Z' },
      { id: 'd2', filename: 'two.md', created_at: '2026-05-16T00:00:00Z' },
    ]
    const wrapper = mountWithProduct({
      productOverrides: { vision_inputs_hash: 'sha256:bbbb', consolidated_vision_hash: 'aaaa' },
      docs,
    })
    await nextTick()
    await wrapper.find('[data-test="ctx-update-cta"]').trigger('click')
    await nextTick()
    await wrapper.vm.confirmCtxLaunch()
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()
    await new Promise((r) => setTimeout(r, 0))

    expect(apiMock.products.getContextUpdateProject).toHaveBeenCalledWith('prod-fe5073')
    expect(apiMock.taxonomyTypes.list).toHaveBeenCalledTimes(1)
    expect(apiMock.projects.create).toHaveBeenCalledTimes(1)
    const payload = apiMock.projects.create.mock.calls[0][0]
    expect(payload.project_type_id).toBe('tax-ctx')
    expect(payload.product_id).toBe('prod-fe5073')
    expect(payload.bootstrap_template_vars).toEqual({
      new_documents: [
        { document_name: 'one.md', document_type: 'text/markdown' },
        { document_name: 'two.md', document_type: '' },
      ],
    })
    expect(payload).not.toHaveProperty('mission')
    expect(showToastMock).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('CTX-0001') }),
    )

    apiMock.products.getContextUpdateProject.mockClear()
    apiMock.taxonomyTypes.list.mockClear()
    apiMock.projects.create.mockClear()
    wrapper.vm.productForm.name = 'AcmeApp'
    wrapper.vm.onFilesAttached([new File(['x'], 'new.md', { type: 'text/markdown' })])
    await nextTick()
    expect(apiMock.products.getContextUpdateProject).not.toHaveBeenCalled()
    expect(apiMock.taxonomyTypes.list).not.toHaveBeenCalled()
    expect(apiMock.projects.create).not.toHaveBeenCalled()
    expect(wrapper.emitted('upload-vision-files')).toBeTruthy()
    wrapper.unmount()
  })
})
