/**
 * Test suite for SystemPromptTab.vue component
 * TDD Implementation: RED Phase
 *
 * Tests the System Orchestrator Prompt tab:
 * - Rendering of prompt editor and metadata
 * - Warning alerts and feedback messages
 * - API integration for loading/saving/resetting prompt
 * - State management and dirty tracking
 * - Loading and saving states
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { nextTick, reactive } from 'vue'
import SystemPromptTab from '@/components/settings/tabs/SystemPromptTab.vue'

// BE-9385d: the component reads the ACTIVE PRODUCT from the products store. Mock the
// store module rather than installing a pinia: a test-pinia installed at mount stays
// the globally active one afterwards, which leaks into unrelated specs in the same
// worker. A plain object is enough here -- every test sets it before mounting.
//
// FE-9413: `reactive` so that a product change AFTER mount actually propagates. The
// real store is reactive, and the indicator's staleness guard fires on exactly that
// transition -- against a plain object `activeProductId` caches its first value and
// the guard could never be exercised. Every existing test sets these BEFORE mounting,
// so this changes nothing for them.
const productStoreMock = reactive({
  effectiveProductId: null,
  currentProduct: null,
  activeProduct: null,
})

vi.mock('@/stores/products', () => ({
  useProductStore: () => productStoreMock,
}))

// Mock the api service
vi.mock('@/services/api', () => ({
  default: {
    system: {
      getOrchestratorPrompt: vi.fn(),
      updateOrchestratorPrompt: vi.fn(),
      resetOrchestratorPrompt: vi.fn(),
    },
  },
}))

describe('SystemPromptTab.vue', () => {
  let vuetify
  let wrapper
  let apiMock

  const defaultPromptResponse = {
    data: {
      content: 'You are the Giljo Orchestrator...',
      is_override: false,
      updated_at: null,
      updated_by: null,
    },
  }

  const overridePromptResponse = {
    data: {
      content: 'Custom orchestrator prompt...',
      is_override: true,
      updated_at: '2025-11-19T10:30:00Z',
      updated_by: 'admin',
    },
  }

  beforeEach(async () => {
    // BE-9385d: default to "no product selected" so the pre-ladder tests below keep
    // exercising the tenant-wide rung, which is the behavior they were written for.
    productStoreMock.effectiveProductId = null
    productStoreMock.currentProduct = null

    // Setup Vuetify
    vuetify = createVuetify({
      components,
      directives,
    })

    // Setup api mock
    const api = await import('@/services/api')
    apiMock = api.default.system
    apiMock.getOrchestratorPrompt.mockResolvedValue(defaultPromptResponse)
    apiMock.updateOrchestratorPrompt.mockResolvedValue(overridePromptResponse)
    apiMock.resetOrchestratorPrompt.mockResolvedValue(defaultPromptResponse)
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
    vi.clearAllMocks()
  })

  // FE-9408: `draggable` is registered on the app in main.js, not by any plugin a
  // unit mount installs. BaseDialog (the no-op save guard's confirm dialog) puts
  // `v-draggable` on its card, and an unregistered directive warns rather than
  // failing -- the FE-9397 guard only matches "Failed to resolve component". Stub
  // it here so the dialog mounts silently, exactly as sibling dialog specs do.
  const mountComponent = () => {
    return mount(SystemPromptTab, {
      global: {
        plugins: [vuetify],
        directives: { draggable: {} },
      },
    })
  }

  describe('Component Rendering', () => {
    it('renders the component', () => {
      wrapper = mountComponent()
      expect(wrapper.exists()).toBe(true)
    })

    it('displays card title "System Orchestrator Prompt"', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.text()).toContain('System Orchestrator Prompt')
    })

    it('displays card subtitle with admin override note', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.text()).toContain('Core instructions for the Giljo Orchestrator')
      expect(wrapper.text()).toContain('admin override only')
    })

    it('displays warning alert about editing impact', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.text()).toContain('Editing this prompt can break orchestrator coordination')
    })

    it('renders prompt textarea', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Check for textarea element in rendered HTML
      expect(wrapper.html()).toContain('textarea')
    })

    it('displays status text showing default or override', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.text()).toContain('Using the default orchestrator prompt (you have not saved an override)')
    })

    it('displays tenant-scope notice in info alert', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.text()).toContain('You can customise this per product, or once for everything.')
    })
  })

  describe('Prompt Content Display', () => {
    it('displays loaded prompt content in textarea', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Check that the prompt value was loaded into the component state
      expect(wrapper.vm.prompt).toBe('You are the Giljo Orchestrator...')
    })

    it('displays override status when prompt is customized', async () => {
      apiMock.getOrchestratorPrompt.mockResolvedValueOnce(overridePromptResponse)

      wrapper = mountComponent()
      await flushPromises()

      const text = wrapper.text()
      expect(text).toContain('Override applied to all products')
      expect(text).toContain('admin')
    })
  })

  describe('Action Buttons', () => {
    it('renders the scope-aware save button', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const text = wrapper.text()
      expect(text).toContain('Save for all products')
    })

    it('renders Restore Default button', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const text = wrapper.text()
      expect(text).toContain('Restore Default')
    })

    it('Save button is disabled when prompt is not dirty', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Not dirty, so save should be disabled
      expect(wrapper.vm.promptDirty).toBe(false)
    })

    it('Save button is enabled when prompt is modified', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Modify the prompt
      wrapper.vm.prompt = 'Modified prompt content'
      await nextTick()

      expect(wrapper.vm.promptDirty).toBe(true)
    })
  })

  describe('API Integration', () => {
    it('fetches prompt on mount', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(apiMock.getOrchestratorPrompt).toHaveBeenCalledTimes(1)
    })

    it('saves prompt when save is triggered', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Modify prompt and call save directly
      wrapper.vm.prompt = 'New custom prompt'
      await nextTick()

      await wrapper.vm.savePrompt()
      await flushPromises()

      expect(apiMock.updateOrchestratorPrompt).toHaveBeenCalledWith('New custom prompt', null)
    })

    it('resets prompt when restore is triggered', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Call restore directly
      await wrapper.vm.restorePrompt()
      await flushPromises()

      expect(apiMock.resetOrchestratorPrompt).toHaveBeenCalledTimes(1)
    })

    it('handles API error on load gracefully', async () => {
      apiMock.getOrchestratorPrompt.mockRejectedValueOnce({
        response: { data: { error_code: 'VALIDATIONERROR', message: 'Failed to load prompt' } },
      })

      wrapper = mountComponent()
      await flushPromises()

      // Should display error
      expect(wrapper.text()).toContain('Failed to load')
    })

    it('handles API error on save gracefully', async () => {
      wrapper = mountComponent()
      await flushPromises()

      apiMock.updateOrchestratorPrompt.mockRejectedValueOnce({
        response: { data: { error_code: 'VALIDATIONERROR', message: 'Save failed' } },
      })

      // Modify and save
      wrapper.vm.prompt = 'Test content'
      await nextTick()

      await wrapper.vm.savePrompt()
      await flushPromises()

      // Should display error
      expect(wrapper.vm.promptError).toContain('Save failed')
    })

    it('handles API error on reset gracefully', async () => {
      wrapper = mountComponent()
      await flushPromises()

      apiMock.resetOrchestratorPrompt.mockRejectedValueOnce({
        response: { data: { error_code: 'VALIDATIONERROR', message: 'Reset failed' } },
      })

      await wrapper.vm.restorePrompt()
      await flushPromises()

      // Should display error
      expect(wrapper.vm.promptError).toContain('Reset failed')
    })
  })

  describe('State Management', () => {
    it('tracks dirty state when prompt is modified', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Initially not dirty
      expect(wrapper.vm.promptDirty).toBe(false)

      // Modify prompt
      wrapper.vm.prompt = 'Modified content'
      await nextTick()

      expect(wrapper.vm.promptDirty).toBe(true)
    })

    it('clears dirty state after successful save', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Modify prompt
      wrapper.vm.prompt = 'Modified content'
      await nextTick()

      expect(wrapper.vm.promptDirty).toBe(true)

      // Save
      await wrapper.vm.savePrompt()
      await flushPromises()

      expect(wrapper.vm.promptDirty).toBe(false)
    })

    it('clears dirty state after successful reset', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Modify prompt
      wrapper.vm.prompt = 'Modified content'
      await nextTick()

      // Reset
      await wrapper.vm.restorePrompt()
      await flushPromises()

      expect(wrapper.vm.promptDirty).toBe(false)
    })

    it('updates metadata after successful save', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Modify and save
      wrapper.vm.prompt = 'New prompt'
      await nextTick()

      await wrapper.vm.savePrompt()
      await flushPromises()

      expect(wrapper.vm.promptMetadata.isOverride).toBe(true)
      expect(wrapper.vm.promptMetadata.updatedBy).toBe('admin')
    })
  })

  describe('Loading States', () => {
    it('shows loading state during fetch', async () => {
      // Delay the response
      apiMock.getOrchestratorPrompt.mockImplementationOnce(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve(defaultPromptResponse), 100)
          )
      )

      wrapper = mountComponent()

      // Check loading state before response
      expect(wrapper.vm.loading).toBe(true)
    })

    it('shows saving state during save', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Delay save response
      apiMock.updateOrchestratorPrompt.mockImplementationOnce(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve(overridePromptResponse), 100)
          )
      )

      // Modify and start save
      wrapper.vm.prompt = 'Test'
      await nextTick()

      wrapper.vm.savePrompt()
      await nextTick()

      expect(wrapper.vm.saving).toBe(true)
    })

    it('disables actions during loading', async () => {
      apiMock.getOrchestratorPrompt.mockImplementationOnce(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve(defaultPromptResponse), 100)
          )
      )

      wrapper = mountComponent()
      await nextTick()

      // During loading, buttons should be disabled
      expect(wrapper.vm.loading).toBe(true)
    })

    it('disables actions during saving', async () => {
      wrapper = mountComponent()
      await flushPromises()

      apiMock.updateOrchestratorPrompt.mockImplementationOnce(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve(overridePromptResponse), 100)
          )
      )

      // Modify and start save
      wrapper.vm.prompt = 'Test'
      await nextTick()

      wrapper.vm.savePrompt()
      await nextTick()

      expect(wrapper.vm.saving).toBe(true)
    })
  })

  describe('Feedback Messages', () => {
    it('displays success message after save', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Modify and save
      wrapper.vm.prompt = 'New content'
      await nextTick()

      await wrapper.vm.savePrompt()
      await flushPromises()

      expect(wrapper.vm.promptFeedback).toContain('Override saved for all products')
    })

    it('displays success message after reset', async () => {
      wrapper = mountComponent()
      await flushPromises()

      await wrapper.vm.restorePrompt()
      await flushPromises()

      expect(wrapper.vm.promptFeedback).toContain('Reverted to default')
    })

    it('can clear error state', async () => {
      apiMock.getOrchestratorPrompt.mockRejectedValueOnce({
        response: { data: { error_code: 'VALIDATIONERROR', message: 'Test error' } },
      })

      wrapper = mountComponent()
      await flushPromises()

      // Error should be displayed
      expect(wrapper.vm.promptError).toContain('Test error')

      // Clear the error
      wrapper.vm.promptError = null
      await nextTick()

      expect(wrapper.vm.promptError).toBeNull()
    })

    it('can clear success state', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Trigger save to show success message
      wrapper.vm.prompt = 'New content'
      await nextTick()

      await wrapper.vm.savePrompt()
      await flushPromises()

      // Clear the success feedback
      wrapper.vm.promptFeedback = null
      await nextTick()

      expect(wrapper.vm.promptFeedback).toBeNull()
    })
  })

  describe('Textarea Properties', () => {
    it('loading state makes textarea readonly', async () => {
      apiMock.getOrchestratorPrompt.mockImplementationOnce(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve(defaultPromptResponse), 100)
          )
      )

      wrapper = mountComponent()
      await nextTick()

      // During loading, textarea should be readonly
      expect(wrapper.vm.loading).toBe(true)
    })

    it('textarea label is configured correctly', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Check that the component contains the label text
      expect(wrapper.text()).toContain('Orchestrator Prompt')
    })

    it('component has monospace style', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Check that the style is applied
      const style = wrapper.find('.mono-textarea')
      expect(style.exists()).toBe(true)
    })
  })

  describe('Status Display', () => {
    it('shows tenant-scoped default prompt notice when not override', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.text()).toContain('Using the default orchestrator prompt (you have not saved an override)')
    })

    it('shows override timestamp and actor when is override', async () => {
      apiMock.getOrchestratorPrompt.mockResolvedValueOnce(overridePromptResponse)

      wrapper = mountComponent()
      await flushPromises()

      const text = wrapper.text()
      expect(text).toContain('Override applied to all products')
      expect(text).toContain('admin')
    })
  })

  describe('Accessibility', () => {
    it('component uses outlined variant for textarea', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Check for outlined class in the HTML
      expect(wrapper.html()).toContain('outlined')
    })

    it('buttons display icons', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Check that icons are rendered (mdi icon classes)
      const html = wrapper.html()
      expect(html).toContain('mdi-content-save')
      expect(html).toContain('mdi-backup-restore')
    })
  })

  describe('Card Structure', () => {
    it('contains card title text', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.text()).toContain('System Orchestrator Prompt')
    })

    it('contains card subtitle text', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.text()).toContain('admin override only')
    })

    it('contains card content area', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Check for card content elements
      expect(wrapper.text()).toContain('Orchestrator Prompt')
    })

    it('contains card action buttons', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.text()).toContain('Save for all products')
      expect(wrapper.text()).toContain('Restore Default')
    })
  })
  // -------------------------------------------------------------------------
  // BE-9385d: the editor reads and writes ONE rung of the product -> tenant ->
  // seed ladder. What is pinned here is that the rung the user picked is the rung
  // that reaches the API, and that INHERITED content is labelled as inherited
  // rather than presented as if the product owned it.
  // -------------------------------------------------------------------------
  describe('Resolution ladder (BE-9385d)', () => {
    const PRODUCT_ID = 'ffffffff-1111-2222-3333-444444444444'

    const mountWithProduct = async ({ withProduct = true } = {}) => {
      productStoreMock.effectiveProductId = withProduct ? PRODUCT_ID : null
      productStoreMock.currentProduct = withProduct ? { id: PRODUCT_ID, name: 'Acme Widgets' } : null
      const w = mountComponent()
      await flushPromises()
      return w
    }

    it('loads the active product rung when a product is selected', async () => {
      wrapper = await mountWithProduct()
      expect(apiMock.getOrchestratorPrompt).toHaveBeenCalledWith(PRODUCT_ID)
      // The scope control must actually render -- an unresolved component would
      // otherwise leave the user no way to reach the tenant-wide rung.
      expect(wrapper.find('[data-test="prompt-scope-toggle"]').exists()).toBe(true)
      expect(wrapper.find('[data-test="prompt-scope-product"]').exists()).toBe(true)
      expect(wrapper.find('[data-test="prompt-scope-tenant"]').exists()).toBe(true)
    })

    it('loads the tenant-wide rung, and offers no scope choice, with no product selected', async () => {
      wrapper = await mountWithProduct({ withProduct: false })
      expect(apiMock.getOrchestratorPrompt).toHaveBeenCalledWith(null)
      expect(wrapper.find('[data-test="prompt-scope-toggle"]').exists()).toBe(false)
    })

    it('re-reads the other rung when the user switches scope', async () => {
      wrapper = await mountWithProduct()
      apiMock.getOrchestratorPrompt.mockClear()

      await wrapper.find('[data-test="prompt-scope-tenant"]').trigger('click')
      await flushPromises()

      expect(apiMock.getOrchestratorPrompt).toHaveBeenCalledWith(null)
    })

    it('saves to the rung being edited', async () => {
      wrapper = await mountWithProduct()
      wrapper.vm.prompt = 'my product prompt'
      await nextTick()
      await wrapper.vm.savePrompt()

      expect(apiMock.updateOrchestratorPrompt).toHaveBeenCalledWith('my product prompt', PRODUCT_ID)
    })

    it('saves tenant-wide when the tenant rung is selected', async () => {
      wrapper = await mountWithProduct()
      await wrapper.find('[data-test="prompt-scope-tenant"]').trigger('click')
      await flushPromises()
      wrapper.vm.prompt = 'everywhere prompt'
      await nextTick()
      await wrapper.vm.savePrompt()

      expect(apiMock.updateOrchestratorPrompt).toHaveBeenCalledWith('everywhere prompt', null)
    })

    it('resets only the rung being edited', async () => {
      wrapper = await mountWithProduct()
      await wrapper.vm.restorePrompt()
      expect(apiMock.resetOrchestratorPrompt).toHaveBeenCalledWith(PRODUCT_ID)
    })

    it('says the content is INHERITED when the product has no override of its own', async () => {
      apiMock.getOrchestratorPrompt.mockResolvedValue({
        data: { content: 'tenant text', is_override: true, scope: 'tenant', updated_at: null, updated_by: null },
      })
      wrapper = await mountWithProduct()

      const status = wrapper.find('[data-test="prompt-status"]').text()
      expect(status).toContain('Inherited')
      expect(status).toContain('Acme Widgets')
    })

    it('does not call it inherited when the product owns the override', async () => {
      apiMock.getOrchestratorPrompt.mockResolvedValue({
        data: { content: 'product text', is_override: true, scope: 'product', updated_at: null, updated_by: null },
      })
      wrapper = await mountWithProduct()

      const status = wrapper.find('[data-test="prompt-status"]').text()
      expect(status).not.toContain('Inherited')
      expect(status).toContain('Acme Widgets')
    })

    it('offers no restore when this rung has no override to remove', async () => {
      apiMock.getOrchestratorPrompt.mockResolvedValue({
        data: { content: 'tenant text', is_override: true, scope: 'tenant', updated_at: null, updated_by: null },
      })
      // Viewing the PRODUCT rung while only a tenant-wide override exists: there is
      // nothing product-scoped to remove, so restore must not offer to remove one.
      wrapper = await mountWithProduct()
      expect(wrapper.vm.canRestore).toBe(false)

      await wrapper.find('[data-test="prompt-scope-tenant"]').trigger('click')
      await flushPromises()
      expect(wrapper.vm.canRestore).toBe(true)
    })
  })

  // -------------------------------------------------------------------------
  // FE-9408: identity provenance in the editor.
  //
  // Two invisible mechanisms are made visible here, and NEITHER changes which
  // rung the ladder resolves:
  //
  //   1. Viewing a product while an account-wide (tenant) override exists. The
  //      component can already infer inheritance when the SERVER answers
  //      scope==='tenant' -- but when the product owns its own override the
  //      server answers scope==='product' and the shadowed tenant row becomes
  //      completely invisible. `tenant_override_exists` is what closes that.
  //   2. Saving text byte-identical to the packaged default, which silently
  //      pins the account to that day's text and detaches it from every future
  //      improvement. Proven on prod twice.
  //
  // All three fields are FEATURE-DETECTED: an older server omits them and both
  // mechanisms must stay completely inert, with no notice, no guard, and no
  // console noise.
  // -------------------------------------------------------------------------
  describe('Identity provenance (FE-9408)', () => {
    const PRODUCT_ID = 'ffffffff-1111-2222-3333-444444444444'

    // Midday UTC on purpose: the saved date renders from the browser's LOCAL
    // calendar day (matching the local-time status line above), and a midday
    // stamp lands on the same calendar date on a UTC CI runner and on an
    // Eastern workstation alike. A midnight stamp would not.
    const TENANT_SAVED_AT = '2026-07-16T12:00:00Z'
    const TENANT_SAVED_DATE = '2026-07-16'

    const SEED_TEXT = 'You are the Giljo Orchestrator. Packaged default text.'

    // The operator's copy, verbatim (em dash included). Ships as-is.
    const ACCOUNT_NOTICE = `An account-wide override (saved ${TENANT_SAVED_DATE}) currently governs every product without its own override — including this one.`
    const NOOP_WARNING =
      "Identical to the built-in default — saving pins your account to today's text and it stops receiving improvements."

    /** A response in the NEW shape. Pass overrides to vary one field. */
    const provenanceResponse = (overrides = {}) => ({
      data: {
        content: 'Custom orchestrator prompt...',
        is_override: true,
        scope: 'product',
        updated_at: null,
        updated_by: null,
        tenant_override_exists: true,
        tenant_override_updated_at: TENANT_SAVED_AT,
        default_content: SEED_TEXT,
        ...overrides,
      },
    })

    const mountAt = async (scope, response) => {
      if (response) apiMock.getOrchestratorPrompt.mockResolvedValue(response)
      productStoreMock.effectiveProductId = PRODUCT_ID
      productStoreMock.currentProduct = { id: PRODUCT_ID, name: 'Acme Widgets' }
      const w = mountComponent()
      await flushPromises()
      if (scope === 'tenant') {
        await w.find('[data-test="prompt-scope-tenant"]').trigger('click')
        await flushPromises()
      }
      return w
    }

    describe('Account-wide override notice', () => {
      it('renders on the product rung when a tenant override exists', async () => {
        wrapper = await mountAt('product', provenanceResponse())

        const notice = wrapper.find('[data-test="account-override-notice"]')
        expect(notice.exists()).toBe(true)
        // Verbatim, em dash and all -- this is the operator's own wording.
        expect(notice.text()).toContain(ACCOUNT_NOTICE)
      })

      it('shows the saved date as YYYY-MM-DD', async () => {
        wrapper = await mountAt('product', provenanceResponse())

        expect(wrapper.find('[data-test="account-override-notice"]').text()).toContain(
          `(saved ${TENANT_SAVED_DATE})`
        )
      })

      it('does NOT render on the tenant rung -- there it is the row you are editing', async () => {
        wrapper = await mountAt('tenant', provenanceResponse({ scope: 'tenant' }))

        expect(wrapper.find('[data-test="account-override-notice"]').exists()).toBe(false)
      })

      it('does NOT render when tenant_override_exists is false', async () => {
        wrapper = await mountAt(
          'product',
          provenanceResponse({ tenant_override_exists: false, tenant_override_updated_at: null })
        )

        expect(wrapper.find('[data-test="account-override-notice"]').exists()).toBe(false)
      })

      it('does NOT render when tenant_override_exists is undefined (older server)', async () => {
        wrapper = await mountAt('product', {
          data: {
            content: 'Custom orchestrator prompt...',
            is_override: true,
            scope: 'product',
            updated_at: null,
            updated_by: null,
          },
        })

        expect(wrapper.find('[data-test="account-override-notice"]').exists()).toBe(false)
      })

      it('its affordance switches to the tenant rung and re-reads it', async () => {
        wrapper = await mountAt('product', provenanceResponse())
        apiMock.getOrchestratorPrompt.mockClear()

        await wrapper.find('[data-test="account-override-manage"]').trigger('click')
        await flushPromises()

        expect(apiMock.getOrchestratorPrompt).toHaveBeenCalledWith(null)
      })
    })

    describe('Tenant-rung truth', () => {
      it('shows the saved date and makes Restore Default the prominent action', async () => {
        wrapper = await mountAt('tenant', provenanceResponse({ scope: 'tenant' }))

        const summary = wrapper.find('[data-test="tenant-override-summary"]')
        expect(summary.exists()).toBe(true)
        expect(summary.text()).toContain(TENANT_SAVED_DATE)
        // `flat` is the filled variant; `text` is the quiet one it uses when
        // there is no override worth removing.
        expect(wrapper.find('[data-test="restore-prompt-btn"]').attributes('variant')).toBe('flat')
      })

      it('leaves Restore Default quiet on the product rung with no product override', async () => {
        wrapper = await mountAt('product', provenanceResponse({ scope: 'tenant' }))

        expect(wrapper.find('[data-test="tenant-override-summary"]').exists()).toBe(false)
        expect(wrapper.find('[data-test="restore-prompt-btn"]').attributes('variant')).toBe('text')
      })
    })

    describe('No-op save guard', () => {
      it('fires on byte-identical text and does not save until confirmed', async () => {
        wrapper = await mountAt('product', provenanceResponse())

        wrapper.vm.prompt = SEED_TEXT
        await nextTick()
        expect(wrapper.vm.promptDirty).toBe(true)

        await wrapper.vm.savePrompt()
        await flushPromises()

        expect(wrapper.text()).toContain(NOOP_WARNING)
        expect(apiMock.updateOrchestratorPrompt).not.toHaveBeenCalled()
      })

      it('does NOT fire on a one-character difference', async () => {
        wrapper = await mountAt('product', provenanceResponse())

        wrapper.vm.prompt = `${SEED_TEXT}X`
        await nextTick()
        await wrapper.vm.savePrompt()
        await flushPromises()

        expect(wrapper.text()).not.toContain(NOOP_WARNING)
        expect(apiMock.updateOrchestratorPrompt).toHaveBeenCalledWith(`${SEED_TEXT}X`, PRODUCT_ID)
      })

      it('does NOT fire on trailing whitespace -- byte-identical means byte-identical', async () => {
        // Explicit: the rule is no trim and no normalization. A trailing space
        // is a real edit, and treating it as one is the ruled behavior.
        wrapper = await mountAt('product', provenanceResponse())

        wrapper.vm.prompt = `${SEED_TEXT} `
        await nextTick()
        await wrapper.vm.savePrompt()
        await flushPromises()

        expect(wrapper.text()).not.toContain(NOOP_WARNING)
        expect(apiMock.updateOrchestratorPrompt).toHaveBeenCalledWith(`${SEED_TEXT} `, PRODUCT_ID)
      })

      it('saves when the user confirms', async () => {
        wrapper = await mountAt('product', provenanceResponse())

        wrapper.vm.prompt = SEED_TEXT
        await nextTick()
        await wrapper.vm.savePrompt()
        await flushPromises()

        await wrapper.find('[data-testid="dialog-confirm"]').trigger('click')
        await flushPromises()

        expect(apiMock.updateOrchestratorPrompt).toHaveBeenCalledWith(SEED_TEXT, PRODUCT_ID)
        expect(wrapper.text()).not.toContain(NOOP_WARNING)
      })

      it('cancelling sends nothing and keeps the edit', async () => {
        wrapper = await mountAt('product', provenanceResponse())

        wrapper.vm.prompt = SEED_TEXT
        await nextTick()
        await wrapper.vm.savePrompt()
        await flushPromises()

        await wrapper.find('[data-testid="dialog-cancel"]').trigger('click')
        await flushPromises()

        expect(apiMock.updateOrchestratorPrompt).not.toHaveBeenCalled()
        expect(wrapper.text()).not.toContain(NOOP_WARNING)
        // The edit survives the cancel -- the user is put back where they were.
        expect(wrapper.vm.prompt).toBe(SEED_TEXT)
        expect(wrapper.vm.promptDirty).toBe(true)
      })

      it('does not arm at all when the response carries no default_content', async () => {
        wrapper = await mountAt('product', provenanceResponse({ default_content: undefined }))

        wrapper.vm.prompt = SEED_TEXT
        await nextTick()
        await wrapper.vm.savePrompt()
        await flushPromises()

        expect(wrapper.text()).not.toContain(NOOP_WARNING)
        expect(apiMock.updateOrchestratorPrompt).toHaveBeenCalledWith(SEED_TEXT, PRODUCT_ID)
      })
    })

    describe('Older server (all three fields absent)', () => {
      it('renders no notice, arms no guard, and logs nothing', async () => {
        const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
        const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

        try {
          wrapper = await mountAt('product', {
            data: {
              content: 'Custom orchestrator prompt...',
              is_override: true,
              scope: 'product',
              updated_at: null,
              updated_by: null,
            },
          })

          expect(wrapper.find('[data-test="account-override-notice"]').exists()).toBe(false)
          expect(wrapper.find('[data-test="tenant-override-summary"]').exists()).toBe(false)

          // Anything the user types is a normal save -- there is no default to
          // compare against, so the guard cannot fire.
          wrapper.vm.prompt = SEED_TEXT
          await nextTick()
          await wrapper.vm.savePrompt()
          await flushPromises()

          expect(wrapper.text()).not.toContain(NOOP_WARNING)
          expect(apiMock.updateOrchestratorPrompt).toHaveBeenCalledWith(SEED_TEXT, PRODUCT_ID)

          expect(errorSpy).not.toHaveBeenCalled()
          expect(warnSpy).not.toHaveBeenCalled()
        } finally {
          errorSpy.mockRestore()
          warnSpy.mockRestore()
        }
      })
    })
  })

  // -------------------------------------------------------------------------
  // FE-9413: which prompt is THIS PRODUCT actually getting, right now.
  //
  // The operator formed the exact misconception this screen invites: that saving
  // on the all-products rung returns a product to the shared prompt. It does not
  // -- the product's own row still wins -- and nothing on screen said so. The two
  // rung tabs stay freely clickable (unchanged); what is added is a standing
  // per-product answer, and copy on the remove action naming what the product
  // falls back TO.
  //
  // The computation, and where each input comes from (measured against the
  // server, not assumed):
  //   P = this product owns its own override row
  //   T = an account-wide row exists
  //   serving = P ? product override : T ? account-wide override : built-in default
  //
  // T is fresh on EVERY response: `tenant_override_exists` comes from a sibling
  // read independent of the ladder (system_prompts.py:93 via
  // service.read_tenant_override_row), applied on GET, PUT and reset alike.
  //
  // P is only readable on the PRODUCT rung: `_fetch_ladder` short-circuits, so a
  // request with a product_id answers scope==='product' exactly when the product
  // row exists -- while a tenant-rung request (product_id=null) can only ever
  // answer 'tenant' or 'default' and says nothing about P. So P is measured on
  // the product rung and remembered, which is sound precisely BECAUSE saving one
  // rung never touches another (the ruled invariant, pinned below).
  // -------------------------------------------------------------------------
  describe('Serving indicator (FE-9413)', () => {
    const PRODUCT_ID = 'ffffffff-1111-2222-3333-444444444444'
    const OTHER_PRODUCT_ID = 'aaaaaaaa-5555-6666-7777-888888888888'
    const TENANT_SAVED_AT = '2026-07-16T12:00:00Z'
    const SEED_TEXT = 'You are the Giljo Orchestrator. Packaged default text.'

    const SERVING_PRODUCT = 'product override'
    const SERVING_TENANT = 'account-wide override'
    const SERVING_DEFAULT = 'built-in default'

    // One sentence, as ruled: most specific rung wins, remove a rung to fall through.
    const LADDER_TOOLTIP =
      "The most specific prompt wins: this product's own override, then your all-products override, then the built-in default, so removing a rung lets this product fall through to the next one."

    // v-tooltip teleports and renders its content lazily under the real Vuetify, so
    // the house specs stub it (JobsTab, AgentRow, ProductCard all do). Stubbed HERE
    // ONLY: the shared mountComponent() above -- the one the legacy and FE-9408
    // describes mount through -- is deliberately untouched.
    const tooltipStub = {
      props: ['text'],
      template: '<div class="v-tooltip-stub" :data-tooltip-text="text" />',
    }

    const mountWithTooltipStub = () =>
      mount(SystemPromptTab, {
        global: {
          plugins: [vuetify],
          directives: { draggable: {} },
          stubs: { 'v-tooltip': tooltipStub },
        },
      })

    /** A response in the FE-9408 shape. `tenantRow` is what the sibling read found. */
    const ladderResponse = ({ scope, tenantRow }) => ({
      data: {
        content: `${scope} rung text`,
        is_override: scope !== 'default',
        scope,
        updated_at: null,
        updated_by: null,
        tenant_override_exists: tenantRow,
        tenant_override_updated_at: tenantRow ? TENANT_SAVED_AT : null,
        default_content: SEED_TEXT,
      },
    })

    /** Which rung the server would resolve for each request, given (P, T). */
    const productRungScope = (product, tenant) =>
      product ? 'product' : tenant ? 'tenant' : 'default'
    const tenantRungScope = (tenant) => (tenant ? 'tenant' : 'default')

    const mountLadder = async ({ product, tenant, rung = 'product' }) => {
      productStoreMock.effectiveProductId = PRODUCT_ID
      productStoreMock.currentProduct = { id: PRODUCT_ID, name: 'Acme Widgets' }
      apiMock.getOrchestratorPrompt.mockImplementation((id) =>
        Promise.resolve(
          id
            ? ladderResponse({ scope: productRungScope(product, tenant), tenantRow: tenant })
            : ladderResponse({ scope: tenantRungScope(tenant), tenantRow: tenant })
        )
      )
      const w = mountWithTooltipStub()
      await flushPromises()
      if (rung === 'tenant') {
        await w.find('[data-test="prompt-scope-tenant"]').trigger('click')
        await flushPromises()
      }
      return w
    }

    const servingText = (w) => w.find('[data-test="serving-value"]').text()

    describe('Truth table -- all four (product row, tenant row) combinations, both rungs', () => {
      it('product rung, product row + tenant row: the product override serves', async () => {
        wrapper = await mountLadder({ product: true, tenant: true })
        expect(servingText(wrapper)).toBe(SERVING_PRODUCT)
      })

      it('product rung, product row only: the product override serves', async () => {
        wrapper = await mountLadder({ product: true, tenant: false })
        expect(servingText(wrapper)).toBe(SERVING_PRODUCT)
      })

      it('product rung, tenant row only: the account-wide override serves', async () => {
        wrapper = await mountLadder({ product: false, tenant: true })
        expect(servingText(wrapper)).toBe(SERVING_TENANT)
      })

      it('product rung, neither row: the built-in default serves', async () => {
        wrapper = await mountLadder({ product: false, tenant: false })
        expect(servingText(wrapper)).toBe(SERVING_DEFAULT)
      })

      it('all-products rung, product row + tenant row: the product override still serves', async () => {
        wrapper = await mountLadder({ product: true, tenant: true, rung: 'tenant' })
        expect(servingText(wrapper)).toBe(SERVING_PRODUCT)
      })

      // THE OPERATOR'S MISCONCEPTION, in one test. He is looking at the all-products
      // tab showing packaged text, and his product is running its own override the
      // whole time. Today the screen says nothing about that.
      it('says the product is on its own override even while you are looking at the all-products tab', async () => {
        wrapper = await mountLadder({ product: true, tenant: false, rung: 'tenant' })
        expect(servingText(wrapper)).toBe(SERVING_PRODUCT)
      })

      it('all-products rung, tenant row only: the account-wide override serves', async () => {
        wrapper = await mountLadder({ product: false, tenant: true, rung: 'tenant' })
        expect(servingText(wrapper)).toBe(SERVING_TENANT)
      })

      it('all-products rung, neither row: the built-in default serves', async () => {
        wrapper = await mountLadder({ product: false, tenant: false, rung: 'tenant' })
        expect(servingText(wrapper)).toBe(SERVING_DEFAULT)
      })

      it('explains the ladder in one sentence', async () => {
        wrapper = await mountLadder({ product: true, tenant: true })
        expect(wrapper.find('[data-tooltip-text]').attributes('data-tooltip-text')).toBe(
          LADDER_TOOLTIP
        )
      })
    })

    describe('It updates the moment the ladder changes', () => {
      it('flips to the product override immediately after saving this product rung', async () => {
        wrapper = await mountLadder({ product: false, tenant: true })
        expect(servingText(wrapper)).toBe(SERVING_TENANT)

        apiMock.updateOrchestratorPrompt.mockResolvedValue(
          ladderResponse({ scope: 'product', tenantRow: true })
        )
        wrapper.vm.prompt = 'my own prompt'
        await nextTick()
        await wrapper.vm.savePrompt()
        await flushPromises()

        expect(servingText(wrapper)).toBe(SERVING_PRODUCT)
      })

      it('falls through to the account-wide override after removing the product override', async () => {
        wrapper = await mountLadder({ product: true, tenant: true })
        expect(servingText(wrapper)).toBe(SERVING_PRODUCT)

        apiMock.resetOrchestratorPrompt.mockResolvedValue(
          ladderResponse({ scope: 'tenant', tenantRow: true })
        )
        await wrapper.vm.restorePrompt()
        await flushPromises()

        expect(servingText(wrapper)).toBe(SERVING_TENANT)
      })

      it('falls through to the built-in default when there is no account-wide override behind it', async () => {
        wrapper = await mountLadder({ product: true, tenant: false })
        expect(servingText(wrapper)).toBe(SERVING_PRODUCT)

        apiMock.resetOrchestratorPrompt.mockResolvedValue(
          ladderResponse({ scope: 'default', tenantRow: false })
        )
        await wrapper.vm.restorePrompt()
        await flushPromises()

        expect(servingText(wrapper)).toBe(SERVING_DEFAULT)
      })
    })

    // These pass on unmodified master and are REGRESSION GUARDS, not fail-first:
    // they exist so that "save = activate" cannot ever be built without a named red.
    // Save has exactly one meaning -- write this text on the rung being viewed.
    describe('Save writes one rung and never touches another', () => {
      it('saving the product rung issues no reset or delete of any other rung', async () => {
        wrapper = await mountLadder({ product: true, tenant: true })
        apiMock.updateOrchestratorPrompt.mockResolvedValue(
          ladderResponse({ scope: 'product', tenantRow: true })
        )
        wrapper.vm.prompt = 'edited product text'
        await nextTick()
        await wrapper.vm.savePrompt()
        await flushPromises()

        expect(apiMock.resetOrchestratorPrompt).not.toHaveBeenCalled()
      })

      it('saving the all-products rung issues no reset, and leaves the product on its own override', async () => {
        wrapper = await mountLadder({ product: true, tenant: true, rung: 'tenant' })
        apiMock.updateOrchestratorPrompt.mockResolvedValue(
          ladderResponse({ scope: 'tenant', tenantRow: true })
        )
        wrapper.vm.prompt = 'edited account-wide text'
        await nextTick()
        await wrapper.vm.savePrompt()
        await flushPromises()

        expect(apiMock.resetOrchestratorPrompt).not.toHaveBeenCalled()
        // The whole misconception: editing the shared prompt did NOT hand this
        // product back to it.
        expect(servingText(wrapper)).toBe(SERVING_PRODUCT)
      })
    })

    describe('The remove action says what this product falls back TO', () => {
      it('names the all-products prompt when an account-wide override stands behind it', async () => {
        wrapper = await mountLadder({ product: true, tenant: true })
        const hint = wrapper.find('[data-test="fallback-hint"]')
        expect(hint.exists()).toBe(true)
        expect(hint.text()).toContain('Acme Widgets')
        expect(hint.text()).toContain('all-products prompt')
      })

      it('names the built-in default when nothing stands behind it', async () => {
        wrapper = await mountLadder({ product: true, tenant: false })
        const hint = wrapper.find('[data-test="fallback-hint"]')
        expect(hint.exists()).toBe(true)
        expect(hint.text()).toContain('built-in default')
      })

      it('says nothing when there is no product override to remove', async () => {
        wrapper = await mountLadder({ product: false, tenant: true })
        expect(wrapper.find('[data-test="fallback-hint"]').exists()).toBe(false)
      })

      it('says nothing on the all-products rung -- that rung is not this control', async () => {
        wrapper = await mountLadder({ product: true, tenant: true, rung: 'tenant' })
        expect(wrapper.find('[data-test="fallback-hint"]').exists()).toBe(false)
      })
    })

    describe('It refuses to answer rather than guess', () => {
      it('shows nothing when no product is selected -- there is no per-product question', async () => {
        productStoreMock.effectiveProductId = null
        productStoreMock.currentProduct = null
        wrapper = mountWithTooltipStub()
        await flushPromises()

        expect(wrapper.find('[data-test="serving-indicator"]').exists()).toBe(false)
      })

      it('hides rather than describing the previous product when the product changes under the all-products tab', async () => {
        wrapper = await mountLadder({ product: true, tenant: true, rung: 'tenant' })
        expect(servingText(wrapper)).toBe(SERVING_PRODUCT)

        // Switching product while standing on the all-products rung deliberately does
        // not re-read (that rung is a different stored value) -- so what was measured
        // for Acme Widgets must not be presented as an answer about Globex.
        productStoreMock.effectiveProductId = OTHER_PRODUCT_ID
        productStoreMock.currentProduct = { id: OTHER_PRODUCT_ID, name: 'Globex' }
        await flushPromises()

        expect(wrapper.find('[data-test="serving-indicator"]').exists()).toBe(false)
      })

      it('answers again as soon as the product rung is read for the new product', async () => {
        wrapper = await mountLadder({ product: true, tenant: true, rung: 'tenant' })
        productStoreMock.effectiveProductId = OTHER_PRODUCT_ID
        productStoreMock.currentProduct = { id: OTHER_PRODUCT_ID, name: 'Globex' }
        await flushPromises()
        expect(wrapper.find('[data-test="serving-indicator"]').exists()).toBe(false)

        // Globex has no override of its own; the account-wide one governs it.
        apiMock.getOrchestratorPrompt.mockImplementation((id) =>
          Promise.resolve(
            id
              ? ladderResponse({ scope: 'tenant', tenantRow: true })
              : ladderResponse({ scope: 'tenant', tenantRow: true })
          )
        )
        await wrapper.find('[data-test="prompt-scope-product"]').trigger('click')
        await flushPromises()

        expect(servingText(wrapper)).toBe(SERVING_TENANT)
      })
    })

    // DoD 3. An older server omits the three FE-9408 fields; T is then unknowable and
    // the indicator must not appear at all, silently.
    describe('Older server without the provenance fields', () => {
      it('hides the indicator and the fallback copy entirely, and logs nothing', async () => {
        const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
        const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

        try {
          productStoreMock.effectiveProductId = PRODUCT_ID
          productStoreMock.currentProduct = { id: PRODUCT_ID, name: 'Acme Widgets' }
          apiMock.getOrchestratorPrompt.mockResolvedValue({
            data: {
              content: 'Custom orchestrator prompt...',
              is_override: true,
              scope: 'product',
              updated_at: null,
              updated_by: null,
            },
          })

          wrapper = mountWithTooltipStub()
          await flushPromises()

          expect(wrapper.find('[data-test="serving-indicator"]').exists()).toBe(false)
          expect(wrapper.find('[data-test="fallback-hint"]').exists()).toBe(false)
          expect(errorSpy).not.toHaveBeenCalled()
          expect(warnSpy).not.toHaveBeenCalled()
        } finally {
          errorSpy.mockRestore()
          warnSpy.mockRestore()
        }
      })
    })
  })
})
