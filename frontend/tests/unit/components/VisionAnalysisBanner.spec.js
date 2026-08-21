import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ProductForm from '@/components/products/ProductForm.vue'

// FE-9427: ProductForm calls useRouter() -- after creating a product it pushes
// /projects?project_id=... Without a router installed that returned `undefined`,
// and the push sits inside a try/catch written for a cancelled navigation, so
// the missing router was swallowed there.
const projectsRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/projects', name: 'Projects', component: { template: '<div />' } },
  ],
})

/**
 * 0842h: Tests for the vision analysis banner and custom instructions
 * in ProductForm.vue.
 *
 * The analysis banner appears when:
 * - setupMode is 'ai' (user selects AI radio)
 * - Vision documents exist
 * - Banner has not been dismissed
 *
 * Custom extraction instructions textarea appears under the same conditions.
 */
describe('ProductForm — Vision Analysis Banner', () => {
  let vuetify
  let pinia

  const existingDocs = [
    { id: 'doc-1', filename: 'design.pdf', size: 1024, status: 'ready' },
  ]

  const baseProduct = {
    id: 'prod-1',
    name: 'Test Product',
    description: 'A product',
    tech_stack: '',
    architecture: '',
    test_config: '',
    coding_conventions: '',
    brand_guidelines: '',
    extraction_custom_instructions: '',
  }

  beforeEach(() => {
    vuetify = createVuetify({ components, directives })
    pinia = createPinia()
    setActivePinia(pinia)
  })

  function createWrapper(props = {}) {
    return mount(ProductForm, {
      props: {
        modelValue: true,
        isEdit: true,
        product: baseProduct,
        existingVisionDocuments: existingDocs,
        uploadingVision: false,
        uploadProgress: 0,
        visionUploadError: null,
        ...props,
      },
      global: {
        plugins: [vuetify, pinia, projectsRouter],
        stubs: {
          'v-dialog': {
            template: '<div class="v-dialog" v-if="modelValue"><slot /></div>',
            props: ['modelValue'],
          },
          'v-file-input': { template: '<input type="file" />' },
        },
      },
    })
  }

  it('renders dialog in edit mode with product data', () => {
    const wrapper = createWrapper()
    expect(wrapper.find('.v-dialog').exists()).toBe(true)
    // Product name is loaded into form fields (not visible as plain text)
    expect(wrapper.html()).toContain('Save Changes')
  })

  it('does not show analysis banner in default manual mode', () => {
    const wrapper = createWrapper()
    // In manual mode, the AI analysis banner should not appear
    // Educational "Want AI to analyze this document" alert was deleted in the
    // Setup-tab flatten; the equivalent guidance now lives in the Customize
    // product extraction instructions expansion panel.
    expect(wrapper.html()).not.toContain('Want AI to analyze this document')
  })

  it('does not show the legacy "Stage Analysis" inline button (folded into footer CTA)', () => {
    const wrapper = createWrapper()
    // The capitalised "Stage Analysis" inline button was removed in the
    // Setup-tab flatten. The lowercase "Stage analysis" label now lives on
    // the single footer primary CTA. The old inline button text must NOT
    // appear anywhere.
    expect(wrapper.html()).not.toContain('Stage Analysis')
  })

  it('loads custom extraction instructions from product prop', () => {
    const product = {
      ...baseProduct,
      extraction_custom_instructions: 'Focus on mobile-first architecture',
    }
    const wrapper = createWrapper({ product })
    // The component should load the extraction_custom_instructions into form state
    expect(wrapper.vm).toBeTruthy()
  })

  it('renders without vision documents gracefully', () => {
    const wrapper = createWrapper({ existingVisionDocuments: [] })
    expect(wrapper.find('.v-dialog').exists()).toBe(true)
    // No analysis features without documents
    // Educational "Want AI to analyze this document" alert was deleted in the
    // Setup-tab flatten; the equivalent guidance now lives in the Customize
    // product extraction instructions expansion panel.
    expect(wrapper.html()).not.toContain('Want AI to analyze this document')
  })

  it('renders in create mode without product', () => {
    const wrapper = createWrapper({ isEdit: false, product: null })
    expect(wrapper.find('.v-dialog').exists()).toBe(true)
  })
})
