import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SequenceBulkBar from '@/components/sequence/SequenceBulkBar.vue'

function mountBar(count) {
  return mount(SequenceBulkBar, { props: { count } })
}

describe('SequenceBulkBar', () => {
  it('renders nothing when no projects are selected', () => {
    const wrapper = mountBar(0)
    expect(wrapper.find('[data-testid="seq-bulk-bar"]').exists()).toBe(false)
  })

  it('shows the selected count and the N/5 run label within the cap', () => {
    const wrapper = mountBar(3)
    expect(wrapper.find('[data-testid="seq-bulk-bar"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="seq-bulk-count"]').text()).toContain('3 selected')
    expect(wrapper.find('[data-testid="seq-run-btn"]').text()).toContain('3/5')
    expect(wrapper.find('[data-testid="seq-bulk-warn"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="seq-run-btn"]').attributes('disabled')).toBeUndefined()
  })

  it('warns and DISABLES the run button when over the cap (cap=5 enforcement)', () => {
    const wrapper = mountBar(6)
    expect(wrapper.find('[data-testid="seq-bulk-warn"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="seq-run-btn"]').attributes('disabled')).toBeDefined()
  })

  it('allows exactly 5 (the cap boundary)', () => {
    const wrapper = mountBar(5)
    expect(wrapper.find('[data-testid="seq-bulk-warn"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="seq-run-btn"]').attributes('disabled')).toBeUndefined()
  })

  it('emits run and clear', async () => {
    const wrapper = mountBar(2)
    await wrapper.find('[data-testid="seq-run-btn"]').trigger('click')
    await wrapper.find('.seq-bulk-clear').trigger('click')
    expect(wrapper.emitted('run')).toBeTruthy()
    expect(wrapper.emitted('clear')).toBeTruthy()
  })
})
