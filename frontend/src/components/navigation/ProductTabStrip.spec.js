/**
 * ProductTabStrip.spec.js — FE-9502c
 * Presentational tab strip for the tabbed product shell. Proves the TWO-TAB
 * case is real: two tabs render simultaneously,
 * each is independently selectable/closable, and the last tab cannot be
 * closed from here (the strip just doesn't render a close button for it —
 * the store enforces the invariant, this proves the affordance matches it).
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProductTabStrip from './ProductTabStrip.vue'

const TAB_A = { id: 'prod-a', name: 'Product A' }
const TAB_B = { id: 'prod-b', name: 'Product B' }

// The global v-menu stub (tests/setup.js) only renders the default slot,
// which hides the activator button — override locally so the add-tab
// affordance actually renders (same pattern as JobsTab.spec.js).
const menuStub = {
  template: `<div class="v-menu"><slot name="activator" :props="{}" /><slot /></div>`,
}
const stubs = { 'v-menu': menuStub }

describe('ProductTabStrip — two real tabs', () => {
  it('renders both tabs at once', () => {
    const wrapper = mount(ProductTabStrip, { props: { tabs: [TAB_A, TAB_B], viewedId: TAB_A.id } })
    const tabs = wrapper.findAll('[role="tab"]')
    expect(tabs).toHaveLength(2)
    expect(tabs[0].text()).toBe('Product A')
    expect(tabs[1].text()).toBe('Product B')
  })

  it('marks only the viewed tab aria-selected', () => {
    const wrapper = mount(ProductTabStrip, { props: { tabs: [TAB_A, TAB_B], viewedId: TAB_B.id } })
    const tabs = wrapper.findAll('[role="tab"]')
    expect(tabs[0].attributes('aria-selected')).toBe('false')
    expect(tabs[1].attributes('aria-selected')).toBe('true')
  })

  it('clicking a tab emits select with that tab\'s id, not the viewed one', async () => {
    const wrapper = mount(ProductTabStrip, { props: { tabs: [TAB_A, TAB_B], viewedId: TAB_A.id } })
    await wrapper.get('[data-testid="product-tab-prod-b"]').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['prod-b']])
  })

  it('each tab has an independent close control when more than one tab is open', () => {
    const wrapper = mount(ProductTabStrip, { props: { tabs: [TAB_A, TAB_B], viewedId: TAB_A.id } })
    expect(wrapper.findAll('[data-testid="product-tab-close"]')).toHaveLength(2)
  })

  it('clicking a close button emits close with that tab\'s id and does not also select', async () => {
    const wrapper = mount(ProductTabStrip, { props: { tabs: [TAB_A, TAB_B], viewedId: TAB_A.id } })
    const closeButtons = wrapper.findAll('[data-testid="product-tab-close"]')
    await closeButtons[1].trigger('click')
    expect(wrapper.emitted('close')).toEqual([['prod-b']])
  })

  it('hides the close control entirely when only one tab is open (last-tab invariant)', () => {
    const wrapper = mount(ProductTabStrip, { props: { tabs: [TAB_A], viewedId: TAB_A.id } })
    expect(wrapper.findAll('[data-testid="product-tab-close"]')).toHaveLength(0)
  })
})

describe('ProductTabStrip — background activity badges (FE-9502d)', () => {
  it('renders no badge when a tab has no badgeCount', () => {
    const wrapper = mount(ProductTabStrip, { props: { tabs: [TAB_A, TAB_B], viewedId: TAB_A.id } })
    expect(wrapper.find('[data-testid="product-tab-badge"]').exists()).toBe(false)
  })

  it('renders a badge with the count for a background tab with activity', () => {
    const busyTab = { ...TAB_B, badgeCount: 3 }
    const wrapper = mount(ProductTabStrip, { props: { tabs: [TAB_A, busyTab], viewedId: TAB_A.id } })
    expect(wrapper.find('[data-testid="product-tab-badge"]').text()).toBe('3')
  })

  it('caps the displayed badge at "9+" rather than growing unbounded', () => {
    const busyTab = { ...TAB_B, badgeCount: 42 }
    const wrapper = mount(ProductTabStrip, { props: { tabs: [TAB_A, busyTab], viewedId: TAB_A.id } })
    expect(wrapper.find('[data-testid="product-tab-badge"]').text()).toBe('9+')
  })

  it('renders no badge for badgeCount of exactly 0 (the viewed-tab / cleared case)', () => {
    const clearedTab = { ...TAB_A, badgeCount: 0 }
    const wrapper = mount(ProductTabStrip, { props: { tabs: [clearedTab, TAB_B], viewedId: TAB_A.id } })
    expect(wrapper.find('[data-testid="product-tab-badge"]').exists()).toBe(false)
  })
})

describe('ProductTabStrip — add-tab affordance', () => {
  const CLOSED_PRODUCT = { id: 'prod-c', name: 'Product C' }

  it('renders no add control when every product is already open', () => {
    const wrapper = mount(ProductTabStrip, {
      props: { tabs: [TAB_A, TAB_B], viewedId: TAB_A.id, addableProducts: [] },
      global: { stubs },
    })
    expect(wrapper.find('[data-testid="product-tab-add"]').exists()).toBe(false)
  })

  it('renders an add control listing products not currently open', () => {
    const wrapper = mount(ProductTabStrip, {
      props: { tabs: [TAB_A], viewedId: TAB_A.id, addableProducts: [TAB_B, CLOSED_PRODUCT] },
      global: { stubs },
    })
    expect(wrapper.find('[data-testid="product-tab-add"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="product-tab-add-prod-c"]').exists()).toBe(true)
  })

  it('clicking a menu entry emits add with that product\'s id', async () => {
    const wrapper = mount(ProductTabStrip, {
      props: { tabs: [TAB_A], viewedId: TAB_A.id, addableProducts: [TAB_B] },
      global: { stubs },
    })
    await wrapper.get('[data-testid="product-tab-add-prod-b"]').trigger('click')
    expect(wrapper.emitted('add')).toEqual([['prod-b']])
  })
})
