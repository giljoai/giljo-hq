import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import HarnessChip from './HarnessChip.vue'

describe('HarnessChip', () => {
  it('renders "detected: Claude Code" for a concrete recognized harness', () => {
    const wrapper = mount(HarnessChip, { props: { harness: 'claude-code' } })
    expect(wrapper.find('[data-testid="harness-chip"]').exists()).toBe(true)
    expect(wrapper.text()).toBe('detected: Claude Code')
  })

  it('renders nothing for the generic fail-safe token', () => {
    const wrapper = mount(HarnessChip, { props: { harness: 'generic' } })
    expect(wrapper.find('[data-testid="harness-chip"]').exists()).toBe(false)
  })

  it('renders nothing when no harness has been detected (null)', () => {
    const wrapper = mount(HarnessChip, { props: { harness: null } })
    expect(wrapper.find('[data-testid="harness-chip"]').exists()).toBe(false)
  })
})

describe('HarnessChip — retired presets (INF-9605a)', () => {
  it('shows a stored gemini stamp as Generic (was Gemini)', () => {
    const wrapper = mount(HarnessChip, { props: { harness: 'gemini' } })
    expect(wrapper.text()).toBe('detected: Generic (was Gemini)')
  })

  it('shows a stored antigravity stamp as Generic (was Antigravity)', () => {
    const wrapper = mount(HarnessChip, { props: { harness: 'antigravity' } })
    expect(wrapper.text()).toBe('detected: Generic (was Antigravity)')
  })
})
