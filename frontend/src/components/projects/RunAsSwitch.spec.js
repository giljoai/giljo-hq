import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import RunAsSwitch from './RunAsSwitch.vue'

const tooltipStub = { template: '<div><slot name="activator" :props="{}" /><slot /></div>' }
const mountSwitch = (props = {}) => mount(RunAsSwitch, { props, global: { stubs: { 'v-tooltip': tooltipStub } } })

describe('RunAsSwitch (TSK-9692, FE-9749)', () => {
  it('offers the two modes as one group, nothing picked by default', () => {
    const w = mountSwitch({ modelValue: null, labelledBy: 'lbl-1' })
    expect(w.attributes('role')).toBe('group')
    expect(w.attributes('aria-labelledby')).toBe('lbl-1')
    const multi = w.find('[data-testid="radio-multi-terminal"]')
    const sub = w.find('[data-testid="radio-subagent"]')
    expect(multi.text()).toBe('Multi-terminal')
    expect(sub.text()).toBe('Subagent')
    expect(multi.attributes('aria-pressed')).toBe('false')
    expect(sub.attributes('aria-pressed')).toBe('false')
  })

  it('shows the picked mode as pressed and emits a change', async () => {
    const w = mountSwitch({ modelValue: 'subagent' })
    expect(w.find('[data-testid="radio-subagent"]').attributes('aria-pressed')).toBe('true')
    await w.find('[data-testid="radio-multi-terminal"]').trigger('click')
    expect(w.emitted('change')?.[0]).toEqual(['multi_terminal'])
  })

  it('the shared control area is its one host; the card and chain header no longer embed it', () => {
    const area = readFileSync(resolve(__dirname, 'StagingControlArea.vue'), 'utf8')
    const footer = readFileSync(resolve(__dirname, 'JobsBoardCardFooter.vue'), 'utf8')
    const header = readFileSync(resolve(__dirname, 'chain/ChainGroupHeader.vue'), 'utf8')
    const chainActions = readFileSync(resolve(__dirname, 'chain/ChainStagingActions.vue'), 'utf8')
    expect(area).toMatch(/<RunAsSwitch\b/)
    expect(footer).toMatch(/<StagingControlArea\b/)
    expect(chainActions).toMatch(/<StagingControlArea\b/)
    expect(header).not.toMatch(/<RunAsSwitch\b/)
    expect(header).not.toMatch(/ExecutionModeSelector/)
  })
})
