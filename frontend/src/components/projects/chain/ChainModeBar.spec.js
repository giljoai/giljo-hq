import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ChainModeBar from './ChainModeBar.vue'

const stubs = { 'v-icon': { template: '<i class="v-icon-stub"><slot /></i>' } }

function mountBar(props = {}) {
  return mount(ChainModeBar, {
    props: { counter: { n: 1, m: 5 }, ...props },
    global: { stubs },
  })
}

describe('ChainModeBar — existing chrome (unchanged by FE-9632)', () => {
  it('renders the N/M counter', () => {
    expect(mountBar().find('[data-testid="chain-counter"]').text()).toBe('1/5')
  })

  it('renders the Multi project mode indicator', () => {
    expect(mountBar().find('[data-testid="chain-mode-indicator"]').text()).toContain(
      'Multi project mode',
    )
  })
})

describe('ChainModeBar — read-only execution mode (FE-9632)', () => {
  it('renders nothing extra when no mode is passed (the pre-run screen)', () => {
    expect(mountBar().find('[data-testid="chain-mode-readonly"]').exists()).toBe(false)
  })

  it('renders nothing when the mode is an empty string (old runs carry none)', () => {
    expect(mountBar({ mode: '' }).find('[data-testid="chain-mode-readonly"]').exists()).toBe(false)
  })

  it('renders the mode once the chain is running', () => {
    const readout = mountBar({ mode: 'subagent' }).find('[data-testid="chain-mode-readonly"]')
    expect(readout.exists()).toBe(true)
    expect(readout.text()).toContain('subagent')
  })

  it('labels the readout so the value is not a bare word on screen', () => {
    expect(mountBar({ mode: 'subagent' }).find('[data-testid="chain-mode-readonly"]').text()).toContain(
      'Execution mode',
    )
  })

  it('renders whatever mode the run carries, not a fixed list', () => {
    expect(mountBar({ mode: 'multi_terminal' }).find('[data-testid="chain-mode-readonly"]').text()).toContain(
      'multi_terminal',
    )
  })

  it('leaves the counter and indicator in place alongside it', () => {
    const w = mountBar({ mode: 'subagent' })
    expect(w.find('[data-testid="chain-counter"]').exists()).toBe(true)
    expect(w.find('[data-testid="chain-mode-indicator"]').exists()).toBe(true)
  })
})
