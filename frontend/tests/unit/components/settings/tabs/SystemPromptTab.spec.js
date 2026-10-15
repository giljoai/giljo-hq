/**
 * SystemPromptTab.spec.js -- FE-9789b
 *
 * The Orchestrator prompt screen: a read-only built-in prompt, then ONE additions
 * box per product chosen with a Product select. No account-wide scope, one warning.
 *
 * Mock shapes mirror OrchestratorPromptResponse in api/endpoints/system_prompts.py:
 * content, is_override, updated_at, updated_by, scope, tenant_override_exists,
 * tenant_override_updated_at, default_content, mode ('additions' | 'replace' | null),
 * additions.
 *
 * Edition Scope: Both
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { reactive } from 'vue'
import SystemPromptTab from '@/components/settings/tabs/SystemPromptTab.vue'
import { withRealVuetify } from '../../../../helpers/realVuetify.js'

const productStoreMock = reactive({
  products: [],
  effectiveProductId: null,
  fetchProducts: vi.fn(),
})
vi.mock('@/stores/products', () => ({ useProductStore: () => productStoreMock }))

const showToast = vi.fn()
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast }) }))

const proposalsStoreMock = reactive({
  additionsProposalFor: vi.fn(() => null),
  ensureLoaded: vi.fn(() => Promise.resolve([])),
})
vi.mock('@/stores/templateProposalsStore', () => ({
  useTemplateProposalsStore: () => proposalsStoreMock,
}))

vi.mock('@/services/api', () => ({
  default: {
    system: {
      getOrchestratorPrompt: vi.fn(),
      updateOrchestratorPrompt: vi.fn(),
      resetOrchestratorPrompt: vi.fn(),
    },
  },
}))

import api from '@/services/api'

const BUILT_IN = '# Giljo HQ Agent\n\n## Identity\n\nYou are the **Orchestrator Agent**.'
const OLD_FULL_PROMPT = 'You are a custom orchestrator. Do it my way.'

const PRODUCTS = [
  { id: 'prod-a', name: 'Atlas' },
  { id: 'prod-b', name: 'Borealis' },
  { id: 'prod-c', name: 'Cascade' },
]

function response(overrides = {}) {
  return {
    data: {
      content: BUILT_IN,
      is_override: false,
      updated_at: null,
      updated_by: null,
      scope: 'default',
      tenant_override_exists: false,
      tenant_override_updated_at: null,
      default_content: BUILT_IN,
      mode: null,
      additions: null,
      ...overrides,
    },
  }
}

const withAdditions = (text) =>
  response({
    content: `${BUILT_IN}\n\n${text}`,
    is_override: true,
    scope: 'product',
    updated_at: '2026-10-13T10:00:00Z',
    updated_by: 'admin',
    mode: 'additions',
    additions: text,
  })

const legacyReplace = () =>
  response({
    content: OLD_FULL_PROMPT,
    is_override: true,
    scope: 'product',
    updated_at: '2026-06-01T10:00:00Z',
    updated_by: 'admin',
    mode: 'replace',
    additions: null,
  })

let realVuetify = null

async function mountTab() {
  realVuetify = await withRealVuetify([
    'VSelect',
    'VTextField',
    'VTextarea',
    'VField',
    'VInput',
    'VLabel',
    'VAlert',
    'VBtn',
    'VIcon',
    'VMessages',
    'VCounter',
  ])
  const w = mount(SystemPromptTab, {
    global: { plugins: [realVuetify.plugin], directives: { draggable: {} } },
  })
  await flushPromises()
  return w
}

const textarea = (w) => w.find('[data-test="additions-field"] textarea')
const saveBtn = (w) => w.get('[data-test="save-prompt-btn"]')
const select = (w) => w.getComponent('[data-test="product-select"]')

beforeEach(() => {
  vi.clearAllMocks()
  productStoreMock.products = PRODUCTS
  productStoreMock.effectiveProductId = 'prod-a'
  proposalsStoreMock.additionsProposalFor.mockReturnValue(null)
  api.system.getOrchestratorPrompt.mockResolvedValue(response())
  api.system.updateOrchestratorPrompt.mockResolvedValue(withAdditions('Saved.'))
  api.system.resetOrchestratorPrompt.mockResolvedValue(response())
})

afterEach(() => {
  realVuetify?.restore()
  realVuetify = null
})

describe('SystemPromptTab (FE-9789b)', () => {
  describe('built-in only', () => {
    it('shows the built-in prompt as rendered, read-only text and a blank additions box', async () => {
      const w = await mountTab()

      const card = w.get('[data-test="builtin-prompt"]')
      expect(card.text()).toContain('System prompt (read only)')
      // markdown is rendered, not shown raw
      expect(card.find('h1').text()).toBe('Giljo HQ Agent')
      expect(card.find('strong').text()).toBe('Orchestrator Agent')
      expect(card.text()).not.toContain('## Identity')
      expect(card.find('textarea').exists()).toBe(false)
      expect(card.find('.scrollbar-standard').exists()).toBe(true)

      expect(textarea(w).element.value).toBe('')
      expect(textarea(w).attributes('placeholder')).toBe(
        'Add instructions for this product. Leave blank to use the system prompt only.',
      )
      expect(w.text()).toContain('Instructions')
      expect(w.text()).toContain('You can customize your system prompt per product.')
    })

    it('reads the active product on mount, with product_id', async () => {
      await mountTab()
      expect(api.system.getOrchestratorPrompt).toHaveBeenCalledTimes(1)
      expect(api.system.getOrchestratorPrompt).toHaveBeenCalledWith('prod-a')
    })

    it('strips script from the built-in prompt before it reaches the DOM', async () => {
      api.system.getOrchestratorPrompt.mockResolvedValue(
        response({ default_content: 'Safe text\n\n<img src=x onerror="window.__pwned=1">\n\n<script>window.__pwned=1</script>' }),
      )
      const w = await mountTab()
      const html = w.get('[data-test="builtin-prompt"]').html()
      expect(html).not.toContain('onerror')
      expect(html).not.toContain('<script')
      expect(html).toContain('Safe text')
    })
  })

  describe('chrome: exactly one warning, nothing about scopes or overrides', () => {
    it('renders exactly one alert, the warning, with the exact text', async () => {
      const w = await mountTab()
      const alerts = w.findAllComponents({ name: 'VAlert' })
      expect(alerts).toHaveLength(1)
      expect(alerts[0].props('type')).toBe('warning')
      expect(alerts[0].props('variant')).toBe('tonal')
      expect(alerts[0].text()).toBe(
        'Changing the orchestrator prompt can have adverse effects on the Giljo HQ product. Use custom additions with caution.',
      )
    })

    it('never says "override" or "all products", in any state', async () => {
      const states = [response(), withAdditions('Be terse.'), legacyReplace()]
      for (const state of states) {
        api.system.getOrchestratorPrompt.mockResolvedValue(state)
        const w = await mountTab()
        const text = w.text().toLowerCase()
        expect(text).not.toContain('override')
        expect(text).not.toContain('all products')
        expect(text).not.toContain('account-wide')
        expect(w.find('[data-test="restore-prompt-btn"]').exists()).toBe(false)
        expect(w.find('[data-test="prompt-scope-toggle"]').exists()).toBe(false)
        realVuetify.restore()
      }
    })

    it('lists a labelled Product select and a labelled textarea', async () => {
      const w = await mountTab()
      expect(select(w).props('label')).toBe('Product')
      expect(w.find('[data-test="additions-field"] textarea').attributes('aria-label')).toBeTruthy()
    })
  })

  describe('product with additions', () => {
    it('fills the box with that product’s saved additions', async () => {
      api.system.getOrchestratorPrompt.mockResolvedValue(withAdditions('Always run the linter.'))
      const w = await mountTab()
      expect(textarea(w).element.value).toBe('Always run the linter.')
      expect(saveBtn(w).attributes('disabled')).toBeDefined()
    })
  })

  describe('Product select', () => {
    it('lists every product the user owns and defaults to the active one', async () => {
      const w = await mountTab()
      const items = select(w).props('items')
      expect(items.map((i) => i.value ?? i.id)).toEqual(['prod-a', 'prod-b', 'prod-c'])
      expect(select(w).props('modelValue')).toBe('prod-a')
    })

    it('loads the other product’s additions when the selection changes', async () => {
      api.system.getOrchestratorPrompt.mockImplementation((productId) =>
        Promise.resolve(productId === 'prod-b' ? withAdditions('Borealis rules.') : response()),
      )
      const w = await mountTab()
      expect(textarea(w).element.value).toBe('')

      await select(w).vm.$emit('update:modelValue', 'prod-b')
      await flushPromises()

      expect(api.system.getOrchestratorPrompt).toHaveBeenLastCalledWith('prod-b')
      expect(textarea(w).element.value).toBe('Borealis rules.')
    })

    it('is independent of the header switcher: a store change does not move it', async () => {
      const w = await mountTab()
      await select(w).vm.$emit('update:modelValue', 'prod-c')
      await flushPromises()
      productStoreMock.effectiveProductId = 'prod-b'
      await flushPromises()
      expect(select(w).props('modelValue')).toBe('prod-c')
    })

    it('ignores a slow answer for a product the user already left', async () => {
      let releaseA
      api.system.getOrchestratorPrompt.mockImplementation((productId) =>
        productId === 'prod-a'
          ? new Promise((resolve) => {
              releaseA = () => resolve(withAdditions('Atlas, arrived late.'))
            })
          : Promise.resolve(withAdditions('Borealis rules.')),
      )
      const w = await mountTab()
      await select(w).vm.$emit('update:modelValue', 'prod-b')
      await flushPromises()
      releaseA()
      await flushPromises()
      expect(textarea(w).element.value).toBe('Borealis rules.')
    })

    it('with no products, sends nothing and cannot save', async () => {
      productStoreMock.products = []
      productStoreMock.effectiveProductId = null
      const w = await mountTab()
      expect(api.system.getOrchestratorPrompt).not.toHaveBeenCalled()
      await textarea(w).setValue('Text with nowhere to go.')
      expect(saveBtn(w).attributes('disabled')).toBeDefined()
    })
  })

  describe('saving', () => {
    it('Save with text PUTs additions and product_id, then toasts success', async () => {
      const w = await mountTab()
      await textarea(w).setValue('Prefer small diffs.')
      expect(saveBtn(w).attributes('disabled')).toBeUndefined()

      await saveBtn(w).trigger('click')
      await flushPromises()

      expect(api.system.updateOrchestratorPrompt).toHaveBeenCalledWith('Prefer small diffs.', 'prod-a')
      expect(api.system.resetOrchestratorPrompt).not.toHaveBeenCalled()
      expect(showToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
    })

    it('Save on an emptied box POSTs reset with product_id and never PUTs', async () => {
      api.system.getOrchestratorPrompt.mockResolvedValue(withAdditions('Old additions.'))
      const w = await mountTab()
      await textarea(w).setValue('')
      await saveBtn(w).trigger('click')
      await flushPromises()

      expect(api.system.resetOrchestratorPrompt).toHaveBeenCalledWith('prod-a')
      expect(api.system.updateOrchestratorPrompt).not.toHaveBeenCalled()
      expect(showToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }))
    })

    it('whitespace-only counts as empty', async () => {
      api.system.getOrchestratorPrompt.mockResolvedValue(withAdditions('Old additions.'))
      const w = await mountTab()
      await textarea(w).setValue('  \n\t ')
      await saveBtn(w).trigger('click')
      await flushPromises()

      expect(api.system.resetOrchestratorPrompt).toHaveBeenCalledWith('prod-a')
      expect(api.system.updateOrchestratorPrompt).not.toHaveBeenCalled()
    })

    it('saves for the product chosen in the select, not the header product', async () => {
      const w = await mountTab()
      await select(w).vm.$emit('update:modelValue', 'prod-c')
      await flushPromises()
      await textarea(w).setValue('For Cascade.')
      await saveBtn(w).trigger('click')
      await flushPromises()
      expect(api.system.updateOrchestratorPrompt).toHaveBeenCalledWith('For Cascade.', 'prod-c')
    })

    it('a failed save toasts an error and keeps what was typed', async () => {
      api.system.updateOrchestratorPrompt.mockRejectedValue({
        response: { status: 400, data: { detail: 'Invalid prompt content.' } },
      })
      const w = await mountTab()
      await textarea(w).setValue('Keep me.')
      await saveBtn(w).trigger('click')
      await flushPromises()

      expect(showToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
      expect(textarea(w).element.value).toBe('Keep me.')
      expect(w.findAllComponents({ name: 'VAlert' })).toHaveLength(1)
    })

    it('asks before saving text identical to the built-in prompt', async () => {
      const w = await mountTab()
      await textarea(w).setValue(BUILT_IN)
      await saveBtn(w).trigger('click')
      await flushPromises()
      expect(api.system.updateOrchestratorPrompt).not.toHaveBeenCalled()
      expect(w.find('[data-test="noop-save-confirm"]').exists()).toBe(true)
    })
  })

  describe('old full prompt (mode "replace")', () => {
    it('shows one line and a Convert button, and does not offer to save until converted', async () => {
      api.system.getOrchestratorPrompt.mockResolvedValue(legacyReplace())
      const w = await mountTab()

      const line = w.get('[data-test="legacy-line"]')
      expect(line.text()).toContain('This product uses an old full prompt instead of the one above.')
      expect(w.find('[data-test="convert-to-additions"]').exists()).toBe(true)
      expect(textarea(w).element.value).toBe('')
      expect(w.find('[data-test="legacy-replacement"]').exists()).toBe(false)
      expect(saveBtn(w).attributes('disabled')).toBeDefined()
      // the only alert is still the single warning
      expect(w.findAllComponents({ name: 'VAlert' })).toHaveLength(1)
    })

    it('Convert keeps the box empty and shows the old text read-only to copy from', async () => {
      api.system.getOrchestratorPrompt.mockResolvedValue(legacyReplace())
      const w = await mountTab()
      await w.get('[data-test="convert-to-additions"]').trigger('click')

      expect(textarea(w).element.value).toBe('')
      const old = w.get('[data-test="legacy-replacement"] textarea')
      expect(old.element.value).toBe(OLD_FULL_PROMPT)
      expect(old.attributes('readonly')).toBeDefined()
      expect(w.find('[data-test="legacy-line"]').exists()).toBe(false)
      expect(api.system.updateOrchestratorPrompt).not.toHaveBeenCalled()
      expect(api.system.resetOrchestratorPrompt).not.toHaveBeenCalled()
    })

    it('after Convert, saving text PUTs additions (which replaces the old prompt)', async () => {
      api.system.getOrchestratorPrompt.mockResolvedValue(legacyReplace())
      const w = await mountTab()
      await w.get('[data-test="convert-to-additions"]').trigger('click')
      await textarea(w).setValue('The part I keep.')
      await saveBtn(w).trigger('click')
      await flushPromises()

      expect(api.system.updateOrchestratorPrompt).toHaveBeenCalledWith('The part I keep.', 'prod-a')
      expect(w.find('[data-test="legacy-replacement"]').exists()).toBe(false)
    })

    it('after Convert, an empty Save resets (drops the old prompt) with product_id', async () => {
      api.system.getOrchestratorPrompt.mockResolvedValue(legacyReplace())
      const w = await mountTab()
      await w.get('[data-test="convert-to-additions"]').trigger('click')
      expect(saveBtn(w).attributes('disabled')).toBeUndefined()
      await saveBtn(w).trigger('click')
      await flushPromises()

      expect(api.system.resetOrchestratorPrompt).toHaveBeenCalledWith('prod-a')
      expect(api.system.updateOrchestratorPrompt).not.toHaveBeenCalled()
    })

    it('switching product after Convert drops the conversion', async () => {
      api.system.getOrchestratorPrompt.mockImplementation((productId) =>
        Promise.resolve(productId === 'prod-a' ? legacyReplace() : response()),
      )
      const w = await mountTab()
      await w.get('[data-test="convert-to-additions"]').trigger('click')
      await select(w).vm.$emit('update:modelValue', 'prod-b')
      await flushPromises()
      expect(w.find('[data-test="legacy-replacement"]').exists()).toBe(false)
      expect(w.find('[data-test="legacy-line"]').exists()).toBe(false)
    })
  })

  describe('agent proposal for the product on screen (BE-9755)', () => {
    it('shows a review line for the selected product only, without adding an alert', async () => {
      proposalsStoreMock.additionsProposalFor.mockImplementation((rung, productId) =>
        rung === 'product' && productId === 'prod-b'
          ? { id: 'p-1', proposed_by: 'orchestrator', reason: 'Lint drift', rung: 'product', product_id: 'prod-b' }
          : null,
      )
      const w = await mountTab()
      expect(w.find('[data-test="additions-proposal-notice"]').exists()).toBe(false)

      await select(w).vm.$emit('update:modelValue', 'prod-b')
      await flushPromises()
      const notice = w.get('[data-test="additions-proposal-notice"]')
      expect(notice.text()).toContain('Orchestrator proposed a change to these orchestrator additions: Lint drift')
      expect(w.findAllComponents({ name: 'VAlert' })).toHaveLength(1)
    })
  })
})
