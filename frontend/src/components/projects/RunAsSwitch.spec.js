import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import RunAsSwitch from './RunAsSwitch.vue'

const tooltipStub = { template: '<div><slot name="activator" :props="{}" /><slot /></div>' }
const mountSwitch = (props = {}) => mount(RunAsSwitch, { props, global: { stubs: { 'v-tooltip': tooltipStub } } })

describe('RunAsSwitch (TSK-9692)', () => {
  it('reads "Run as" and offers the two modes, nothing picked by default', () => {
    const w = mountSwitch({ modelValue: null })
    expect(w.find('[data-testid="run-as-label"]').text()).toBe('Run as')
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

  it('a locked switch cannot change', async () => {
    const w = mountSwitch({ modelValue: 'subagent', locked: true })
    const multi = w.find('[data-testid="radio-multi-terminal"]')
    expect(multi.attributes('disabled')).toBeDefined()
    await multi.trigger('click')
    expect(w.emitted('change')).toBeUndefined()
  })

  it('a refused switch is marked for the refusal outline', () => {
    expect(mountSwitch({ modelValue: null, refused: true }).classes()).toContain('run-as--refused')
  })

  it('the card and the chain header both use it; the old selector is gone', () => {
    const footer = readFileSync(resolve(__dirname, 'JobsBoardCardFooter.vue'), 'utf8')
    const header = readFileSync(resolve(__dirname, 'chain/ChainGroupHeader.vue'), 'utf8')
    expect(footer).toMatch(/<RunAsSwitch\b/)
    expect(header).toMatch(/<RunAsSwitch\b/)
    expect(header).not.toMatch(/ExecutionModeSelector/)
  })
})
