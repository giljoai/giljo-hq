/**
 * Integration tests for Product UI Refactor (Handover 0316)
 * Tests reorganization of product form UI
 *
 * Post-refactor notes:
 * - ProductForm.vue is now a separate component (not inline in ProductsView)
 * - dialogTab, tabOrder, productForm are internal to ProductForm.vue
 * - Must mount ProductForm directly to test form internals
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { createRouter, createMemoryHistory } from 'vue-router'
import ProductForm from '@/components/products/ProductForm.vue'
import ProductSetupTab from '@/components/products/product-form/ProductSetupTab.vue'
import ProductTestingTab from '@/components/products/product-form/ProductTestingTab.vue'
import { withRealVuetify } from '../helpers/realVuetify.js'
import { api } from '@/services/api'

// FE-9427: ProductForm calls useRouter() -- after creating a product (or
// launching context tuning) it pushes /projects?project_id=... Without a router
// installed useRouter() returned `undefined`, and that push sits inside a
// try/catch written for a CANCELLED navigation, so the missing router was
// swallowed there and the navigation could not be observed at all.
const projectsRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/projects', name: 'Projects', component: { template: '<div />' } },
  ],
})

describe('Product UI Refactor (Handover 0316)', () => {
  let wrapper
  let vuetify

  beforeEach(() => {
    // Setup Pinia
    const pinia = createPinia()
    setActivePinia(pinia)

    // Setup Vuetify
    vuetify = createVuetify({
      components,
      directives,
    })

    // Mount ProductForm component directly
    wrapper = mount(ProductForm, {
      props: {
        modelValue: true,
        product: null,
        isEdit: false,
      },
      global: {
        plugins: [pinia, vuetify, projectsRouter],
      }
    })
  })

  it('Core Features field is in Setup tab', async () => {
    await wrapper.vm.$nextTick()

    // Should be on Setup tab by default
    expect(wrapper.vm.dialogTab).toBe('setup')

    // Core Features field is bound to productForm.coreFeatures
    const coreFeatures = wrapper.vm.productForm.coreFeatures
    expect(coreFeatures).toBeDefined()
  })

  it('Testing tab is renamed from "Features & Testing"', async () => {
    await wrapper.vm.$nextTick()

    // Check tab order - 'features' tab should still exist (internal value)
    expect(wrapper.vm.tabOrder).toContain('features')

    // The tab LABEL should not be "Features & Testing"
    const tabsText = wrapper.text()
    expect(tabsText).not.toContain('Features & Testing')
  })

  it('Quality Standards field exists in Testing tab', async () => {
    await wrapper.vm.$nextTick()

    // Navigate to Testing tab
    wrapper.vm.dialogTab = 'features'
    await wrapper.vm.$nextTick()

    // Quality Standards field should be in productForm.testConfig
    const form = wrapper.vm.productForm
    expect(form.testConfig).toBeDefined()
    expect(form.testConfig.quality_standards).toBeDefined()
  })

  it('Product creation saves quality_standards field', async () => {
    await wrapper.vm.$nextTick()

    // Fill basic info
    wrapper.vm.productForm.name = 'Test Product'
    wrapper.vm.productForm.description = 'Test description'

    // Navigate to Testing tab and verify quality_standards exists
    wrapper.vm.dialogTab = 'features'
    await wrapper.vm.$nextTick()

    // Set quality_standards
    if (wrapper.vm.productForm.testConfig.quality_standards !== undefined) {
      wrapper.vm.productForm.testConfig.quality_standards = '80% coverage, zero bugs'
    }

    // Verify form data is structured correctly
    expect(wrapper.vm.productForm.testConfig).toBeDefined()
  })

  it('tabOrder is defined correctly', () => {
    expect(wrapper.vm.tabOrder).toEqual(['setup', 'info', 'tech', 'arch', 'features'])
  })
})

/**
 * TSK-9404 — drive the tab toggle the way a user does.
 *
 * The tests above navigate by assigning `wrapper.vm.dialogTab = 'features'`.
 * That writes the model directly and never touches the control, so it says
 * nothing about whether a person can reach the panel. The gap is not
 * theoretical: in create mode every tab past `setup` is DISABLED until the
 * analysis gate opens, so the assignment walks through a door the UI holds
 * shut. A regression that dropped the `value` bindings, unbound `dialogTab`
 * from the buttons, or disabled the toggle outright would leave them green.
 *
 * WHY THIS MOUNTS REAL VUETIFY, AND WHY IT MUST
 * =============================================
 * `tests/setup.js` stubs `v-btn-toggle` as `<div v-bind="$attrs"><slot /></div>`
 * and `v-btn` as `<button v-bind="$attrs"><slot /></button>`. Neither carries
 * any selection behaviour, and the `vuetify` module itself is mocked, so a
 * click on the stubbed button can never move `dialogTab` — it is an inert
 * element that merely looks like a toggle. Measured, not assumed: clicking it
 * under the global stubs leaves `dialogTab` on 'setup' in EDIT mode, where the
 * gate is open and a real user would succeed.
 *
 * So under the default stubs this test cannot be written at all: the click is a
 * no-op, and the only way to get it green would be to weaken it into asserting
 * the stub's own markup. FE-9397 is what makes the tag resolve rather than
 * render as an inert unknown element; it does not make the stub behave like a
 * toggle. This uses the sanctioned escape hatch instead — `withRealVuetify()`
 * (FE-9366) — and lists VSlideGroup/VSlideGroupItem because VBtnToggle builds
 * its selection group out of them, so un-stubbing only the toggle would leave
 * its internals flat and the click inert again.
 *
 * Both assertions below are load-bearing, verified by mutation rather than
 * assumed. Changing the toggle's `v-model` to a one-way `:model-value` fails it
 * on `dialogTab`; pinning the `v-window` to 'setup' so the model moves but the
 * panel does not fails it on the active-panel index. In both cases the five
 * assignment-based tests above stayed green — which is the gap this closes.
 *
 * `restore()` runs in afterEach: the helper mutates the shared
 * `config.global.stubs` singleton, and leaking real components would change how
 * every later test in this file renders.
 *
 * Panel switching is asserted on `v-window-item--active` and on the Testing
 * panel actually mounting, not on `dialogTab` alone — a v-window that ignored
 * its v-model would still pass a model-only assertion.
 */
describe('ProductForm tab toggle (TSK-9404)', () => {
  const TESTING_TAB = '[data-testid="product-form-tab-features"]'

  // VBtnToggle's selection group is VSlideGroup/VSlideGroupItem; VBtn is what
  // is actually clicked; VWindow/VWindowItem is the panel being switched.
  const REAL_COMPONENTS = [
    'VBtnToggle',
    'VBtn',
    'VWindow',
    'VWindowItem',
    'VSlideGroup',
    'VSlideGroupItem',
    'VIcon',
  ]

  let restoreStubs = null

  afterEach(() => {
    if (restoreStubs) {
      restoreStubs()
      restoreStubs = null
    }
  })

  async function mountForm(props = {}) {
    const real = await withRealVuetify(REAL_COMPONENTS)
    restoreStubs = real.restore
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(ProductForm, {
      props: { modelValue: true, product: null, isEdit: false, ...props },
      global: { plugins: [pinia, real.plugin, projectsRouter] },
    })
    await wrapper.vm.$nextTick()
    return wrapper
  }

  // Edit mode: the analysis gate is open, so every tab is reachable.
  function mountUnlocked() {
    return mountForm({
      isEdit: true,
      product: {
        id: 'prod-tsk9404',
        name: 'Test Product',
        description: 'Test description',
        vision_analysis_complete: true,
      },
    })
  }

  // Index of the panel the window is actually showing.
  function activePanelIndex(wrapper) {
    return wrapper.findAll('.v-window-item').findIndex((item) => item.classes('v-window-item--active'))
  }

  it('clicking the Testing tab switches the visible panel', async () => {
    const wrapper = await mountUnlocked()

    // Precondition — Setup is the panel on screen, and Testing has not mounted.
    expect(wrapper.vm.dialogTab).toBe('setup')
    expect(wrapper.findComponent(ProductSetupTab).exists()).toBe(true)
    expect(wrapper.findComponent(ProductTestingTab).exists()).toBe(false)
    expect(activePanelIndex(wrapper)).toBe(0)

    const testingTab = wrapper.find(TESTING_TAB)
    expect(testingTab.exists()).toBe(true)
    // Guard against asserting the stub: the real VBtn is what carries this.
    expect(testingTab.classes()).toContain('v-btn')
    expect(testingTab.attributes('disabled')).toBeUndefined()

    await testingTab.trigger('click')
    await wrapper.vm.$nextTick()

    // The model moved...
    expect(wrapper.vm.dialogTab).toBe('features')
    // ...the toggle reflects the selection...
    expect(wrapper.find(TESTING_TAB).classes()).toContain('v-btn--active')
    // ...and the window actually switched panels, which is the real claim.
    expect(activePanelIndex(wrapper)).toBe(4)
    expect(wrapper.findComponent(ProductTestingTab).exists()).toBe(true)
  })

  it('the Testing tab is disabled in create mode and clicking it does nothing', async () => {
    const wrapper = await mountForm({ isEdit: false, product: null })

    const testingTab = wrapper.find(TESTING_TAB)
    expect(testingTab.exists()).toBe(true)
    expect(testingTab.classes()).toContain('v-btn--disabled')

    await testingTab.trigger('click')
    await wrapper.vm.$nextTick()

    // Still on Setup. This is precisely what direct assignment to `dialogTab`
    // cannot tell you -- that reaches 'features' here, which no user can, so
    // the assignment-based tests above are silently exercising an unreachable
    // state. The analysis gate (ProductForm's `gateActive`) is real UI.
    expect(wrapper.vm.dialogTab).toBe('setup')
    expect(activePanelIndex(wrapper)).toBe(0)
    expect(wrapper.findComponent(ProductTestingTab).exists()).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// FE-9427: where the context-update launch actually SENDS you.
//
// ProductForm.confirmCtxLaunch() ends with
//   await router.push({ path: '/projects', query: { project_id: created.id } })
// wrapped in a try/catch whose comment says it is there for a CANCELLED
// navigation. Before this lane the spec mounted ProductForm with no router, so
// useRouter() returned `undefined` and that same catch silently swallowed the
// resulting TypeError -- the navigation could not be observed at all, and its
// absence could not have failed anything. With a real router installed the
// destination is assertable, so assert it.
// ---------------------------------------------------------------------------
describe('ProductForm — context-update launch navigates to the new project (FE-9427)', () => {
  let wrapper
  let ctxRouter

  const PRODUCT = { id: 'prod-1', name: 'Demo Product' }

  beforeEach(() => {
    setActivePinia(createPinia())

    ctxRouter = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'Root', component: { template: '<div />' } },
        { path: '/projects', name: 'Projects', component: { template: '<div />' } },
      ],
    })

    wrapper = mount(ProductForm, {
      props: { modelValue: true, product: PRODUCT, isEdit: true },
      global: {
        plugins: [createPinia(), createVuetify({ components, directives }), ctxRouter],
      },
    })
  })

  afterEach(() => {
    wrapper?.unmount()
  })

  it('lands on /projects with the newly created project id', async () => {
    // No open CTX project yet -- 404 is the documented "proceed to create" path.
    api.products.getContextUpdateProject = vi
      .fn()
      .mockRejectedValue({ response: { status: 404 } })
    api.taxonomyTypes.list.mockResolvedValue({ data: [{ id: 'tt-ctx', abbreviation: 'CTX' }] })
    api.projects.create.mockResolvedValue({
      data: { id: 'proj-new', taxonomy_alias: 'CTX-0001' },
    })

    await wrapper.vm.confirmCtxLaunch()
    await flushPromises()

    expect(ctxRouter.currentRoute.value.path).toBe('/projects')
    expect(ctxRouter.currentRoute.value.query).toEqual({ project_id: 'proj-new' })
  })

  it('lands on the EXISTING project when one is already open, rather than creating a second', async () => {
    api.products.getContextUpdateProject = vi.fn().mockResolvedValue({
      data: { project_id: 'proj-existing', hash_matches: true, taxonomy_alias: 'CTX-0007' },
    })

    await wrapper.vm.confirmCtxLaunch()
    await flushPromises()

    expect(ctxRouter.currentRoute.value.fullPath).toBe('/projects?project_id=proj-existing')
    // The idempotency probe short-circuits: no second project is minted.
    expect(api.projects.create).not.toHaveBeenCalled()
  })
})
