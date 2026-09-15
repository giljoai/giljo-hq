import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({ row: null, products: [], createProduct: null }))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({
    products: h.products,
    fetchProductById: vi.fn(async () => h.row),
    createProduct: h.createProduct,
  }),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn(async () => true), copied: { value: false } }),
}))

vi.mock('@/composables/useGiljoMode', () => ({
  useGiljoMode: () => ({ isSaasMode: () => false }),
}))

import TutorialPromptScreen from './TutorialPromptScreen.vue'

const stubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': {
    template: '<button v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
    emits: ['click'],
  },
}

function mountDoorD() {
  return mount(TutorialPromptScreen, {
    props: { path: 'D', productId: null },
    global: { stubs },
  })
}

describe('TutorialPromptScreen — gate F1: what door D may adopt (FE-9566)', () => {
  beforeEach(() => {
    h.row = { id: 'created-1', consolidated_vision_light: '' }
    h.products = []
    h.createProduct = vi.fn(async () => ({ id: 'created-1' }))
  })

  it('adopts a SHOWN nameless draft — the shape create_product actually produces', async () => {
    h.products = [{ id: 'draft-shown', is_active: true, name: '' }]
    const wrapper = mountDoorD()
    await flushPromises()

    expect(h.createProduct).not.toHaveBeenCalled()
    expect(wrapper.emitted('product-created')[0]).toEqual(['draft-shown'])
  })

  it('adopts a hidden nameless draft too — hidden or shown is not what decides it', async () => {
    h.products = [{ id: 'draft-hidden', is_active: false, name: '' }]
    const wrapper = mountDoorD()
    await flushPromises()

    expect(h.createProduct).not.toHaveBeenCalled()
    expect(wrapper.emitted('product-created')[0]).toEqual(['draft-hidden'])
  })

  it('treats a whitespace-only name as nameless', async () => {
    h.products = [{ id: 'draft-ws', is_active: true, name: '   ' }]
    const wrapper = mountDoorD()
    await flushPromises()

    expect(h.createProduct).not.toHaveBeenCalled()
    expect(wrapper.emitted('product-created')[0]).toEqual(['draft-ws'])
  })


  it('never adopts the user\'s real SHOWN product', async () => {
    h.products = [{ id: 'real-shown', is_active: true, name: 'My Real Product' }]
    const wrapper = mountDoorD()
    await flushPromises()

    expect(h.createProduct).toHaveBeenCalled()
    expect(wrapper.emitted('product-created')[0]).toEqual(['created-1'])
  })

  it('never adopts the user\'s real HIDDEN product', async () => {
    h.products = [{ id: 'real-hidden', is_active: false, name: 'Archived Product' }]
    const wrapper = mountDoorD()
    await flushPromises()

    expect(h.createProduct).toHaveBeenCalled()
    expect(wrapper.emitted('product-created')[0]).toEqual(['created-1'])
  })

  it('never adopts products[0] just because it is first — it picks the nameless one', async () => {
    h.products = [
      { id: 'real-first', is_active: true, name: 'The Users Product' },
      { id: 'draft-second', is_active: true, name: '' },
    ]
    const wrapper = mountDoorD()
    await flushPromises()

    expect(h.createProduct).not.toHaveBeenCalled()
    expect(wrapper.emitted('product-created')[0]).toEqual(['draft-second'])
  })

  it('creates when every product the user has is named', async () => {
    h.products = [
      { id: 'real-a', is_active: true, name: 'Product A' },
      { id: 'real-b', is_active: false, name: 'Product B' },
    ]
    const wrapper = mountDoorD()
    await flushPromises()

    expect(h.createProduct).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('product-created')[0]).toEqual(['created-1'])
  })
})
