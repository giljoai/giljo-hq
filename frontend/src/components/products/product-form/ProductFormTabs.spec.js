import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/composables/useFormatDate', () => ({
  useFormatDate: () => ({ formatDate: (d) => d || '' }),
}))

import ProductSetupTab from './ProductSetupTab.vue'
import ProductInfoTab from './ProductInfoTab.vue'
import ProductTechTab from './ProductTechTab.vue'
import ProductArchTab from './ProductArchTab.vue'
import ProductTestingTab from './ProductTestingTab.vue'

const baseStubs = {
  'v-text-field': { template: '<input class="v-text-field" />' },
  'v-textarea': { template: '<textarea class="v-textarea" />' },
  'v-checkbox': { template: '<input type="checkbox" class="v-checkbox" />' },
  'v-select': { template: '<div class="v-select"><slot name="label" /><slot name="item" :item="{ raw: {} }" :props="{}" /><slot name="selection" :item="{ raw: {} }" /></div>' },
  'v-alert': { template: '<div v-if="true" class="v-alert" :data-test="$attrs[\'data-test\']"><slot /></div>' },
  'v-btn': { template: '<button class="v-btn" :data-test="$attrs[\'data-test\']" @click="$emit(\'click\')"><slot /></button>' },
  'v-chip': { template: '<span class="v-chip"><slot /></span>' },
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-file-input': { template: '<input type="file" class="v-file-input" />' },
  'v-progress-circular': { template: '<div class="v-progress-circular" />' },
  'v-progress-linear': { template: '<div class="v-progress-linear" />' },
  'v-list': { template: '<div class="v-list"><slot /></div>' },
  'v-list-item': { template: '<div class="v-list-item"><slot /><slot name="prepend" /><slot name="append" /></div>' },
  'v-list-item-title': { template: '<div><slot /></div>' },
  'v-list-item-subtitle': { template: '<div><slot /></div>' },
  'v-expansion-panels': { template: '<div class="v-expansion-panels"><slot /></div>' },
  'v-expansion-panel': { template: '<div class="v-expansion-panel"><slot /></div>' },
  'v-expansion-panel-title': { template: '<div class="v-expansion-panel-title"><slot /></div>' },
  'v-expansion-panel-text': { template: '<div class="v-expansion-panel-text"><slot /></div>' },
  'v-slider': { template: '<div class="v-slider" />' },
}

function makeForm() {
  return {
    name: 'My Product',
    description: '',
    projectPath: '',
    targetPlatforms: ['all'],
    techStack: {
      programming_languages: '',
      frontend_frameworks: '',
      backend_frameworks: '',
      databases_storage: '',
      infrastructure: '',
    },
    architecture: {
      primary_pattern: '',
      design_patterns: '',
      api_style: '',
      architecture_notes: '',
      coding_conventions: '',
    },
    coreFeatures: '',
    brandGuidelines: '',
    testConfig: {
      quality_standards: '',
      test_strategy: 'TDD',
      coverage_target: 80,
      testing_frameworks: '',
    },
    extractionCustomInstructions: '',
  }
}

describe('ProductSetupTab', () => {
  beforeEach(() => { setActivePinia(createPinia()) })

  it('renders without errors', () => {
    const wrapper = mount(ProductSetupTab, {
      props: {
        form: makeForm(),
        isEdit: false,
        skipAiAnalysis: false,
        existingVisionDocuments: [],
        uploadingVision: false,
        uploadProgress: 0,
        visionUploadError: null,
        promptFallbackText: null,
        showStalenessBanner: false,
        stalenessBannerText: '',
        ctxLaunching: false,
      },
      global: { stubs: baseStubs },
    })
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.text()).toContain('Product Setup')
  })

  it('shows staleness banner when showStalenessBanner is true', () => {
    const wrapper = mount(ProductSetupTab, {
      props: {
        form: makeForm(),
        isEdit: true,
        skipAiAnalysis: false,
        existingVisionDocuments: [],
        uploadingVision: false,
        uploadProgress: 0,
        visionUploadError: null,
        promptFallbackText: null,
        showStalenessBanner: true,
        stalenessBannerText: 'Context is stale',
        ctxLaunching: false,
      },
      global: { stubs: baseStubs },
    })
    expect(wrapper.find('[data-test="ctx-staleness-banner"]').exists()).toBe(true)
  })

  it('emits open-ctx-confirm when CTA clicked', async () => {
    const wrapper = mount(ProductSetupTab, {
      props: {
        form: makeForm(),
        isEdit: true,
        skipAiAnalysis: false,
        existingVisionDocuments: [],
        uploadingVision: false,
        uploadProgress: 0,
        visionUploadError: null,
        promptFallbackText: null,
        showStalenessBanner: true,
        stalenessBannerText: 'Context is stale',
        ctxLaunching: false,
      },
      global: { stubs: baseStubs },
    })
    await wrapper.find('[data-test="ctx-update-cta"]').trigger('click')
    expect(wrapper.emitted('open-ctx-confirm')).toBeTruthy()
  })

  it('hides staleness banner when showStalenessBanner is false', () => {
    const wrapper = mount(ProductSetupTab, {
      props: {
        form: makeForm(),
        isEdit: true,
        skipAiAnalysis: false,
        existingVisionDocuments: [],
        uploadingVision: false,
        uploadProgress: 0,
        visionUploadError: null,
        promptFallbackText: null,
        showStalenessBanner: false,
        stalenessBannerText: '',
        ctxLaunching: false,
      },
      global: { stubs: baseStubs },
    })
    expect(wrapper.find('[data-test="ctx-staleness-banner"]').exists()).toBe(false)
  })

  it('shows skip checkbox in create mode', () => {
    const wrapper = mount(ProductSetupTab, {
      props: {
        form: makeForm(),
        isEdit: false,
        skipAiAnalysis: false,
        existingVisionDocuments: [],
        uploadingVision: false,
        uploadProgress: 0,
        visionUploadError: null,
        promptFallbackText: null,
        showStalenessBanner: false,
        stalenessBannerText: '',
        ctxLaunching: false,
      },
      global: { stubs: baseStubs },
    })
    expect(wrapper.html()).toContain('Skip AI Analysis')
  })

  it('hides skip checkbox in edit mode', () => {
    const wrapper = mount(ProductSetupTab, {
      props: {
        form: makeForm(),
        isEdit: true,
        skipAiAnalysis: false,
        existingVisionDocuments: [],
        uploadingVision: false,
        uploadProgress: 0,
        visionUploadError: null,
        promptFallbackText: null,
        showStalenessBanner: false,
        stalenessBannerText: '',
        ctxLaunching: false,
      },
      global: { stubs: baseStubs },
    })
    expect(wrapper.html()).not.toContain('Skip AI Analysis')
  })
})

describe('ProductInfoTab', () => {
  beforeEach(() => { setActivePinia(createPinia()) })

  it('renders without errors', () => {
    const wrapper = mount(ProductInfoTab, {
      props: { form: makeForm() },
      global: { stubs: baseStubs },
    })
    expect(wrapper.text()).toContain('Product Information')
  })
})

describe('ProductTechTab', () => {
  beforeEach(() => { setActivePinia(createPinia()) })

  it('renders without errors', () => {
    const wrapper = mount(ProductTechTab, {
      props: { form: makeForm(), platformValidationError: '' },
      global: { stubs: baseStubs },
    })
    expect(wrapper.text()).toContain('Technology Stack')
  })

  it('shows platform validation error', () => {
    const wrapper = mount(ProductTechTab, {
      props: { form: makeForm(), platformValidationError: 'At least one platform required' },
      global: { stubs: baseStubs },
    })
    expect(wrapper.text()).toContain('At least one platform required')
  })
})

describe('ProductArchTab', () => {
  beforeEach(() => { setActivePinia(createPinia()) })

  it('renders without errors', () => {
    const wrapper = mount(ProductArchTab, {
      props: { form: makeForm() },
      global: { stubs: baseStubs },
    })
    expect(wrapper.text()).toContain('Architecture')
  })
})

describe('ProductTestingTab', () => {
  beforeEach(() => { setActivePinia(createPinia()) })

  it('renders without errors', () => {
    const wrapper = mount(ProductTestingTab, {
      props: { form: makeForm() },
      global: { stubs: baseStubs },
    })
    expect(wrapper.text()).toContain('Quality Standards')
  })

  it('shows coverage target', () => {
    const wrapper = mount(ProductTestingTab, {
      props: { form: makeForm() },
      global: { stubs: baseStubs },
    })
    expect(wrapper.text()).toContain('80%')
  })
})
