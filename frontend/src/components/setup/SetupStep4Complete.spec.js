import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SetupStep4Complete from './SetupStep4Complete.vue'

const stubs = {
  'v-icon': { template: '<i><slot /></i>' },
}

describe('SetupStep4Complete — teaches the terminal/harness path (FE-9503b)', () => {
  it('keeps all three original informational cards', () => {
    const wrapper = mount(SetupStep4Complete, { global: { stubs } })
    expect(wrapper.find('[data-testid="launch-cta-product"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="launch-cta-dashboard"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="launch-cta-guide"]').exists()).toBe(true)
  })

  it('adds a fourth "drive from your terminal" informational card', () => {
    const wrapper = mount(SetupStep4Complete, { global: { stubs } })
    const card = wrapper.find('[data-testid="launch-cta-terminal"]')
    expect(card.exists()).toBe(true)
    expect(card.text().toLowerCase()).toMatch(/terminal|agent/)
  })

  it('the terminal card is informational only — no input, no toggle, no button', () => {
    const wrapper = mount(SetupStep4Complete, { global: { stubs } })
    const card = wrapper.find('[data-testid="launch-cta-terminal"]')
    expect(card.findAll('input, button, select').length).toBe(0)
  })
})
