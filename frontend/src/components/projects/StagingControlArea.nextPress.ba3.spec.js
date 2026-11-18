import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StagingControlArea from './StagingControlArea.vue'

const tooltipStub = { template: '<div><slot name="activator" :props="{}" /><slot /></div>' }

function mountArea(props) {
  return mount(StagingControlArea, {
    props: { stageText: 'Stage', secondaryLabel: 'Secondary', variant: 'project', ...props },
    global: { stubs: { 'v-tooltip': tooltipStub } },
  })
}

const pulsing = (w) => w.findAll('.next-press-pulse')
const byId = (w, id) => w.find(`[data-testid="${id}"]`)

describe('StagingControlArea next-press pulse', () => {
  it('no mode picked: only the mode box pulses', () => {
    const w = mountArea({ phase: 'ready', mode: null, stageNeedsMode: true, pulseNext: true })
    expect(pulsing(w)).toHaveLength(1)
    expect(byId(w, 'jbf-run-as').classes()).toContain('next-press-pulse')
  })

  it('mode picked: the box stops and only Stage pulses', () => {
    const w = mountArea({ phase: 'ready', mode: 'subagent', stageNeedsMode: false, pulseNext: true })
    expect(pulsing(w)).toHaveLength(1)
    expect(byId(w, 'jbf-stage').classes()).toContain('next-press-pulse')
    expect(byId(w, 'jbf-run-as').classes()).not.toContain('next-press-pulse')
  })

  it('staged and waiting for the go: only Implement pulses', () => {
    const w = mountArea({
      phase: 'staged', mode: 'subagent', modeLocked: true, stageRole: 'secondary', stageText: 'Re-Stage',
      implementReady: true, pulseNext: true,
    })
    expect(pulsing(w)).toHaveLength(1)
    expect(byId(w, 'jbf-implement').classes()).toContain('next-press-pulse')
  })

  it('Stage prompt handed out (Unstage showing, no plan): nothing pulses', () => {
    const w = mountArea({
      phase: 'ready', mode: 'multi_terminal', stageRole: 'quiet', stageText: 'Unstage', pulseNext: true,
    })
    expect(pulsing(w)).toHaveLength(0)
  })

  it('a card that is not in focus never pulses', () => {
    const w = mountArea({ phase: 'ready', mode: null, stageNeedsMode: true, pulseNext: false })
    expect(pulsing(w)).toHaveLength(0)
    const staged = mountArea({ phase: 'staged', mode: 'subagent', modeLocked: true, implementReady: true })
    expect(pulsing(staged)).toHaveLength(0)
  })

  it('a chain card never pulses (the chain owns one gate)', () => {
    const w = mountArea({ variant: 'chain', phase: 'ready', mode: null, stageNeedsMode: true, pulseNext: true })
    expect(pulsing(w)).toHaveLength(0)
  })

  it('the title is centred, larger and brand yellow while a mode is being chosen', () => {
    const w = mountArea({ phase: 'ready', mode: null, stageNeedsMode: true })
    expect(byId(w, 'sca-label').classes()).toContain('sca-label--title')
    const locked = mountArea({ phase: 'staged', mode: 'subagent', modeLocked: true })
    expect(byId(locked, 'sca-label').classes()).not.toContain('sca-label--title')
  })
})
