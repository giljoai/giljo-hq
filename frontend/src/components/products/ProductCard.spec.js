/**
 * ProductCard.spec.js — FE-6006 unit 3b
 *
 * Tests the pure-presentational product card component.
 * Edition scope: CE
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/utils/colorUtils', () => ({
  hexToRgba: (hex, alpha) => `rgba(${hex},${alpha})`,
}))
vi.mock('@/utils/statusConfig', () => ({
  getStatusColor: () => '#67bd6d',
}))
vi.mock('@/config/agentColors', () => ({
  getAgentColor: () => ({ hex: '#ffc300' }),
}))

import ProductCard from './ProductCard.vue'

const baseProduct = {
  id: 'prod-1',
  name: 'My Product',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: null,
  task_count: 3,
  project_count: 5,
  unfinished_projects: 2,
  // BE-6066 P4: the lean list ships pre-aggregated vision_summary, not the
  // full vision_documents array.
  vision_summary: { doc_count: 0, chunked_count: 0, chunk_total: 0, embedded_count: 0 },
  vision_analysis_complete: false,
}

function mountCard(props = {}) {
  return mount(ProductCard, {
    props: {
      product: baseProduct,
      isActive: false,
      isDefault: false,
      ...props,
    },
    global: {
      stubs: {
        'v-icon': { template: '<i class="v-icon"><slot /></i>' },
        'v-btn': { template: '<button class="v-btn" v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>' },
        'v-card': { template: '<div class="v-card"><slot /></div>' },
        'v-card-text': { template: '<div class="v-card-text"><slot /></div>' },
        'v-card-actions': { template: '<div class="v-card-actions"><slot /></div>' },
        'v-divider': { template: '<hr />' },
        'v-row': { template: '<div class="v-row"><slot /></div>' },
        'v-col': { template: '<div class="v-col"><slot /></div>' },
        'v-tooltip': {
          template: '<div class="v-tooltip"><slot name="default" /><slot name="activator" :props="{}" /></div>',
        },
        // The global setup.js stub is an inert `<input v-bind="$attrs">` --
        // model-value/update:model-value never round-trip through it, so a
        // local stub that actually implements v-model semantics is needed to
        // test the Default checkbox's toggle behavior.
        'v-checkbox': {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template:
            '<input type="checkbox" class="v-checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" />',
        },
      },
    },
  })
}

describe('ProductCard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders product name', () => {
    const wrapper = mountCard()
    expect(wrapper.text()).toContain('My Product')
  })

  it('shows Shown chip when isActive is true', () => {
    const wrapper = mountCard({ isActive: true })
    expect(wrapper.text()).toContain('Shown')
  })

  it('does not show Shown chip when isActive is false', () => {
    const wrapper = mountCard({ isActive: false })
    expect(wrapper.text()).not.toContain('Shown')
  })

  it('displays task_count and project_count', () => {
    const wrapper = mountCard()
    expect(wrapper.text()).toContain('3') // task_count
    expect(wrapper.text()).toContain('5') // project_count
  })

  it('computes completed count as project_count - unfinished_projects', () => {
    const wrapper = mountCard()
    expect(wrapper.text()).toContain('3') // 5 - 2 = 3 completed
  })

  it('emits info event when info button clicked', async () => {
    const wrapper = mountCard()
    const btns = wrapper.findAll('.v-btn')
    // Find the info button by aria-label
    const infoBtn = btns.find(b => b.attributes('aria-label') === 'View product details')
    expect(infoBtn).toBeDefined()
    await infoBtn.trigger('click')
    expect(wrapper.emitted('info')).toBeTruthy()
    expect(wrapper.emitted('info')[0][0]).toEqual(baseProduct)
  })

  it('emits tune event when tune button clicked', async () => {
    const wrapper = mountCard()
    const tuneBtn = wrapper.findAll('.v-btn').find(b => b.attributes('aria-label') === 'Tune context')
    expect(tuneBtn).toBeDefined()
    await tuneBtn.trigger('click')
    expect(wrapper.emitted('tune')).toBeTruthy()
  })

  it('emits edit event when edit button clicked', async () => {
    const wrapper = mountCard()
    const editBtn = wrapper.findAll('.v-btn').find(b => b.attributes('aria-label') === 'Edit product')
    expect(editBtn).toBeDefined()
    await editBtn.trigger('click')
    expect(wrapper.emitted('edit')).toBeTruthy()
  })

  it('emits delete event when delete button clicked', async () => {
    const wrapper = mountCard()
    const delBtn = wrapper.findAll('.v-btn').find(b => b.attributes('aria-label') === 'Delete product')
    expect(delBtn).toBeDefined()
    await delBtn.trigger('click')
    expect(wrapper.emitted('delete')).toBeTruthy()
  })

  it('emits toggle-activation event when show/hide button clicked', async () => {
    const wrapper = mountCard()
    const activateBtn = wrapper.findAll('.v-btn').find(b =>
      b.attributes('aria-label') === 'Show product' || b.attributes('aria-label') === 'Hide product'
    )
    expect(activateBtn).toBeDefined()
    await activateBtn.trigger('click')
    expect(wrapper.emitted('toggle-activation')).toBeTruthy()
  })

  it('renders the docs chip and chunks from vision_summary', () => {
    const product = {
      ...baseProduct,
      vision_summary: { doc_count: 1, chunked_count: 1, chunk_total: 10, embedded_count: 1 },
      vision_analysis_complete: true,
    }
    const wrapper = mountCard({ product })
    expect(wrapper.text()).toContain('1 docs')
    expect(wrapper.text()).toContain('10 chunks')
    expect(wrapper.text()).toContain('Analyzed')
  })

  it('hides the vision block when vision_summary doc_count is 0', () => {
    const wrapper = mountCard()
    expect(wrapper.text()).not.toContain('docs')
  })

  it('shows Pending analysis with progress from vision_summary.embedded_count', () => {
    const product = {
      ...baseProduct,
      vision_summary: { doc_count: 3, chunked_count: 0, chunk_total: 0, embedded_count: 1 },
      vision_analysis_complete: false,
    }
    const wrapper = mountCard({ product })
    expect(wrapper.text()).toContain('Pending analysis — 1 of 3 docs analyzed')
  })

  // FE-9529: the Default control.
  describe('Default control', () => {
    it('is unchecked when isDefault is false', () => {
      const wrapper = mountCard({ isDefault: false })
      const box = wrapper.find('[data-testid="product-card-default"]')
      expect(box.element.checked).toBe(false)
    })

    it('is checked when isDefault is true', () => {
      const wrapper = mountCard({ isDefault: true })
      const box = wrapper.find('[data-testid="product-card-default"]')
      expect(box.element.checked).toBe(true)
    })

    it('checking an unchecked box emits set-default with the product', async () => {
      const wrapper = mountCard({ isDefault: false })
      const box = wrapper.find('[data-testid="product-card-default"]')
      await box.setValue(true)
      expect(wrapper.emitted('set-default')).toBeTruthy()
      expect(wrapper.emitted('set-default')[0][0]).toEqual(baseProduct)
    })

    it('is a radio-like single selection: clicking an already-checked box is a no-op, never emits set-default', async () => {
      const wrapper = mountCard({ isDefault: true })
      const box = wrapper.find('[data-testid="product-card-default"]')
      await box.setValue(true)
      expect(wrapper.emitted('set-default')).toBeFalsy()
    })

    it('the tooltip explains the read/write distinction, not a write default', () => {
      const wrapper = mountCard()
      expect(wrapper.text()).toContain('Where reads go when nothing else is specified')
      expect(wrapper.text()).toContain('Agents must always name a product when writing')
    })

    it('shows the Default control regardless of isActive (D2: hidden can be default)', () => {
      const wrapper = mountCard({ isActive: false, isDefault: true })
      const box = wrapper.find('[data-testid="product-card-default"]')
      expect(box.exists()).toBe(true)
      expect(box.element.checked).toBe(true)
    })
  })

  // FE-9571: card layout system -- regression guards for the structural fix.
  // These assert the presence of the specific classes the fix's scoped SCSS
  // targets, so reverting the template markup (even if the SCSS block is left
  // in place) makes these fail. Pixel-level verification (no mid-word breaks,
  // no clipped controls, footers aligned) was done against a live build --
  // jsdom does not run a real layout/CSS engine, so it cannot assert wrapped
  // line counts or clipping directly; see the PR screenshot for that evidence.
  describe('layout system (FE-9571)', () => {
    it('top-aligns the title/chip row instead of vertically centering it', () => {
      // A vertically-centered row put the "Shown" chip mid-title for a name
      // that wraps to multiple lines. Top-aligning keeps the chip level with
      // the title's first line regardless of how many lines the title takes.
      const wrapper = mountCard({ isActive: true })
      const row = wrapper.find('.product-title-row')
      expect(row.exists()).toBe(true)
      expect(row.classes()).toContain('align-start')
      expect(row.classes()).not.toContain('align-center')
    })

    it('clamps a long product name instead of letting it collide with the chip unbounded', () => {
      const longName = 'ZZ TEST CARD - DELETE ME (Giljo HQ audit dry-run) with an even longer trailing qualifier'
      const product = { ...baseProduct, name: longName }
      const wrapper = mountCard({ product, isActive: true })
      const title = wrapper.find('.product-title-clamp')
      expect(title.exists()).toBe(true)
      // Full name stays available (a11y / hover tooltip) even though the
      // visual line-clamp CSS truncates what's shown.
      expect(title.attributes('title')).toBe(longName)
      expect(title.text()).toBe(longName)
    })

    it('marks every stat column label to resist Vuetify\'s inherited mid-word break-word', () => {
      // Vuetify's base .v-card rule sets overflow-wrap: break-word, which let
      // "Completed" split into "Complet"/"ed" inside its narrow 1-of-3 column.
      // The fix scopes overflow-wrap: normal / word-break: keep-all to these
      // labels specifically -- guard that the marker class survives on all
      // three (Tasks / Projects / Completed), not just the one that visibly
      // broke in the reported screenshot.
      const wrapper = mountCard()
      const labels = wrapper.findAll('.product-stat-label')
      expect(labels).toHaveLength(3)
      expect(labels.map(l => l.text())).toEqual(['Tasks', 'Projects', 'Completed'])
    })

    it('marks the actions row as the pinned footer', () => {
      // The scoped SCSS pins this element to the card's bottom edge via
      // `margin-top: auto` inside the card's flex-column, regardless of how
      // little content (no vision chips, no updated_at) sits above it in
      // v-card-text -- keeping footers aligned across cards of different
      // content volumes (confirmed live: 0px gap below the actions row on
      // 4 test cards with different content, vs. up to 76px before the fix).
      const minimalProduct = { ...baseProduct, updated_at: null, vision_summary: { doc_count: 0 } }
      const wrapper = mountCard({ product: minimalProduct })
      const actions = wrapper.find('.v-card-actions')
      expect(actions.exists()).toBe(true)
      expect(actions.classes()).toContain('product-actions-footer')
    })
  })
})
