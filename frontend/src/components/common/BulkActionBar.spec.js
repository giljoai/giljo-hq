import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import BulkActionBar from '@/components/common/BulkActionBar.vue'

const BaseDialogStub = {
  name: 'BaseDialog',
  props: ['modelValue', 'title', 'confirmLabel'],
  emits: ['confirm', 'cancel', 'update:modelValue'],
  template: `<div v-if="modelValue" data-testid="bulk-delete-dialog">
      <span class="dlg-title">{{ title }}</span><slot />
      <button data-testid="dlg-confirm" @click="$emit('confirm')">{{ confirmLabel }}</button>
    </div>`,
}

function mountBar(props = {}) {
  return mount(BulkActionBar, {
    props: { count: 2, pageCount: 10, matchingTotal: 10, canArchive: true, ...props },
    global: { stubs: { BaseDialog: BaseDialogStub } },
  })
}

describe('BulkActionBar', () => {
  it('renders nothing when no row is ticked', () => {
    const wrapper = mountBar({ count: 0 })
    expect(wrapper.find('[data-testid="bulk-action-bar"]').exists()).toBe(false)
  })

  it('shows the count and only the actions that apply', () => {
    const wrapper = mountBar({ count: 3, canArchive: true, canUnarchive: false })
    expect(wrapper.find('[data-testid="bulk-count"]').text()).toBe('3 selected')
    expect(wrapper.find('[data-testid="bulk-archive"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="bulk-unarchive"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="bulk-chain"]').exists()).toBe(false)
  })

  it('offers Unarchive when archived rows are ticked', () => {
    const wrapper = mountBar({ canArchive: false, canUnarchive: true })
    expect(wrapper.find('[data-testid="bulk-unarchive"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="bulk-archive"]').exists()).toBe(false)
  })

  it('emits archive, unarchive and clear', async () => {
    const wrapper = mountBar({ canUnarchive: true })
    await wrapper.find('[data-testid="bulk-archive"]').trigger('click')
    await wrapper.find('[data-testid="bulk-unarchive"]').trigger('click')
    await wrapper.find('[data-testid="bulk-clear"]').trigger('click')
    expect(wrapper.emitted('archive')).toHaveLength(1)
    expect(wrapper.emitted('unarchive')).toHaveLength(1)
    expect(wrapper.emitted('clear')).toHaveLength(1)
  })

  it('asks before deleting, naming the count, and only then emits delete', async () => {
    const wrapper = mountBar({ count: 3, noun: ['task', 'tasks'] })
    await wrapper.find('[data-testid="bulk-delete"]').trigger('click')
    expect(wrapper.emitted('delete')).toBeUndefined()
    const dialog = wrapper.find('[data-testid="bulk-delete-dialog"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.find('.dlg-title').text()).toBe('Delete 3 tasks?')

    await wrapper.find('[data-testid="dlg-confirm"]').trigger('click')
    expect(wrapper.emitted('delete')).toHaveLength(1)
  })

  describe('select all across pages', () => {
    it('offers "Select all N matching" once the whole page is ticked and more rows match', async () => {
      const wrapper = mountBar({ count: 25, pageCount: 25, matchingTotal: 240 })
      const offer = wrapper.find('[data-testid="bulk-select-all-offer"]')
      expect(offer.exists()).toBe(true)
      expect(offer.text()).toContain('25 selected on this page.')
      expect(offer.text()).toContain('Select all 240 matching')
      await wrapper.find('[data-testid="bulk-select-all-matching"]').trigger('click')
      expect(wrapper.emitted('select-all-matching')).toHaveLength(1)
    })

    it('does not offer it while only part of the page is ticked, or when nothing more matches', () => {
      expect(mountBar({ count: 3, pageCount: 25, matchingTotal: 240 }).find('[data-testid="bulk-select-all-offer"]').exists()).toBe(false)
      expect(mountBar({ count: 10, pageCount: 10, matchingTotal: 10 }).find('[data-testid="bulk-select-all-offer"]').exists()).toBe(false)
    })

    it('says so when every matching row, including other pages, is selected', () => {
      const wrapper = mountBar({ count: 240, pageCount: 25, matchingTotal: 240, allMatching: true })
      expect(wrapper.find('[data-testid="bulk-select-all-offer"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="bulk-all-matching-note"]').text()).toContain('All 240 matching rows are selected')
    })
  })

  describe('Chain (Projects)', () => {
    it('is disabled when the ticked rows do not make a chain, and explains why', () => {
      const wrapper = mountBar({ showChain: true, chainReady: false, chainNote: 'Chain uses 0 of 2: 2 not inactive.' })
      expect(wrapper.find('[data-testid="bulk-chain"]').attributes('disabled')).toBeDefined()
      expect(wrapper.find('[data-testid="bulk-chain-note"]').text()).toBe('Chain uses 0 of 2: 2 not inactive.')
    })

    it('emits chain when the ticked rows make a chain', async () => {
      const wrapper = mountBar({ showChain: true, chainReady: true })
      await wrapper.find('[data-testid="bulk-chain"]').trigger('click')
      expect(wrapper.emitted('chain')).toHaveLength(1)
    })
  })
})
