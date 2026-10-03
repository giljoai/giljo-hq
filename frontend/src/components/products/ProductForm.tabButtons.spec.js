import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ProductForm from '@/components/products/ProductForm.vue'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))

const VBtn = {
  name: 'VBtn',
  props: ['value', 'disabled'],
  template: '<button class="tab-btn"><slot /></button>',
}
const stubs = {
  'v-btn': VBtn,
  'v-btn-toggle': { template: '<div class="toggle"><slot /></div>' },
  'v-icon': { template: '<i class="icon"><slot /></i>' },
  'v-tooltip': { props: ['activator', 'location'], template: '<span class="tip">[{{ activator }}/{{ location }}] <slot /></span>' },
  ProductIntroTour: true,
}

function tabs(isEdit) {
  const w = mount(ProductForm, {
    props: { modelValue: true, product: isEdit ? { id: 'p1', name: 'P' } : null, isEdit },
    global: { plugins: [createPinia()], stubs },
  })
  return w
    .find('.toggle')
    .findAllComponents(VBtn)
    .map((b) => ({
      value: b.props('value'),
      testid: b.attributes('data-testid'),
      disabled: b.props('disabled'),
      icon: b.find('.icon').text(),
      text: b.text().replace(/\s+/g, ' ').trim(),
    }))
}

describe('ProductForm tab strip', () => {
  it('new product: every tab after setup is locked with the unlock tip', () => {
    expect(tabs(false)).toEqual([
      { value: 'setup', testid: 'product-form-tab-setup', disabled: undefined, icon: 'mdi-cog', text: 'mdi-cog Product Setup' },
      { value: 'info', testid: 'product-form-tab-info', disabled: true, icon: 'mdi-information-outline', text: 'mdi-information-outline Product Info [parent/bottom] Run analysis to unlock' },
      { value: 'tech', testid: 'product-form-tab-tech', disabled: true, icon: 'mdi-code-braces', text: 'mdi-code-braces Tech Stack [parent/bottom] Run analysis to unlock' },
      { value: 'arch', testid: 'product-form-tab-arch', disabled: true, icon: 'mdi-sitemap', text: 'mdi-sitemap Architecture [parent/bottom] Run analysis to unlock' },
      { value: 'features', testid: 'product-form-tab-features', disabled: true, icon: 'mdi-test-tube', text: 'mdi-test-tube Testing [parent/bottom] Run analysis to unlock' },
    ])
  })

  it('existing product: tabs are open and carry no tip', () => {
    expect(tabs(true).map(({ value, disabled, text }) => ({ value, disabled, text }))).toEqual([
      { value: 'setup', disabled: undefined, text: 'mdi-cog Product Setup' },
      { value: 'info', disabled: false, text: 'mdi-information-outline Product Info' },
      { value: 'tech', disabled: false, text: 'mdi-code-braces Tech Stack' },
      { value: 'arch', disabled: false, text: 'mdi-sitemap Architecture' },
      { value: 'features', disabled: false, text: 'mdi-test-tube Testing' },
    ])
  })
})
