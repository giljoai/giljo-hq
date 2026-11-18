import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

const h = vi.hoisted(() => ({
  getTuningSections: vi.fn(),
  generateTuningPrompt: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  default: { products: h },
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import ProductTuningDialog from './ProductTuningDialog.vue'
import { withRealVuetify } from '../../../tests/helpers/realVuetify.js'

const A = { id: 'prod-a', name: 'Memory Hub' }
const B = { id: 'prod-b', name: 'Agent Message Hub' }

const REAL = ['VDialog', 'VOverlay', 'VCard', 'VBtn', 'VIcon', 'VCheckbox', 'VExpandTransition', 'VTextarea']

describe('ProductTuningDialog: prompt belongs to the product it was opened for', () => {
  let real
  let wrapper

  beforeEach(async () => {
    h.getTuningSections.mockReset().mockResolvedValue({ data: { sections: ['description'] } })
    h.generateTuningPrompt.mockReset().mockImplementation((id) =>
      Promise.resolve({ data: { prompt: `PROMPT FOR ${id}` } }),
    )
    real = await withRealVuetify(REAL)
  })

  afterEach(() => {
    wrapper?.unmount()
    real.restore()
    document.body.innerHTML = ''
  })

  function mountDialog(product) {
    return mount(ProductTuningDialog, {
      props: { modelValue: true, product },
      attachTo: document.body,
      global: { plugins: [real.plugin] },
    })
  }

  const shown = () =>
    document.body.textContent + [...document.body.querySelectorAll('textarea')].map((t) => t.value).join('\n')

  async function generate() {
    const btn = document.body.querySelector('[data-testid="product-tuning-generate"]')
    btn.click()
    await flushPromises()
  }

  it('the dialog shows no prompt for B after a prompt was generated for A', async () => {
    wrapper = mountDialog(A)
    await flushPromises()
    await generate()
    expect(document.body.querySelector('textarea').value).toBe('PROMPT FOR prod-a')

    await wrapper.setProps({ modelValue: false })
    await flushPromises()
    await new Promise((r) => setTimeout(r, 400))
    await wrapper.setProps({ product: B, modelValue: true })
    await flushPromises()

    expect(shown()).not.toContain('PROMPT FOR prod-a')
  })

  it('B opened straight after A closes (before the leave finishes) shows no prompt for A', async () => {
    wrapper = mountDialog(A)
    await flushPromises()
    await generate()

    await wrapper.setProps({ modelValue: false })
    await nextTick()
    await wrapper.setProps({ product: B, modelValue: true })
    await flushPromises()

    expect(shown()).not.toContain('PROMPT FOR prod-a')
    expect(h.getTuningSections).toHaveBeenLastCalledWith('prod-b')
  })

  it('switching the product while open never leaves the previous prompt up', async () => {
    wrapper = mountDialog(A)
    await flushPromises()
    await generate()

    await wrapper.setProps({ product: B })
    await flushPromises()

    expect(shown()).not.toContain('PROMPT FOR prod-a')
    expect(h.getTuningSections).toHaveBeenLastCalledWith('prod-b')
  })
})
