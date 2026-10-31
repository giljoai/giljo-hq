import { describe, it, expect, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import StagingControlArea from './StagingControlArea.vue'

const tooltipStub = { template: '<div><slot name="activator" :props="{}" /><slot /></div>' }

const VARIANTS = [
  { variant: 'project', stage: 'jbf-stage', implement: 'jbf-implement', tag: 'jbf-mode-tag', secondary: 'jb-btn-detail', copy: 'Copy prompt' },
  {
    variant: 'chain',
    stage: 'stage-chain-btn',
    implement: 'implement-chain-btn',
    tag: 'chain-group-mode-tag',
    secondary: 'chain-group-deactivate',
    copy: 'Copy chain prompt',
  },
]

function mountArea(props) {
  return mount(StagingControlArea, {
    props: { stageText: 'Stage', secondaryLabel: 'Secondary', ...props },
    global: { stubs: { 'v-tooltip': tooltipStub } },
  })
}

const byId = (w, id) => w.find(`[data-testid="${id}"]`)

afterEach(() => {
  vi.unstubAllGlobals()
})

describe.each(VARIANTS)('StagingControlArea ($variant)', (v) => {
  it('no mode: Stage is disabled with its reason announced, the frame has the attention border', () => {
    const w = mountArea({ variant: v.variant, phase: 'ready', mode: null, stageNeedsMode: true })
    const stage = byId(w, v.stage)
    expect(byId(w, 'sca-label').text()).toBe('Select execution mode')
    expect(stage.attributes('aria-disabled')).toBe('true')
    const reason = byId(w, 'sca-mode-reason')
    expect(reason.text()).toBe('Pick a mode first')
    expect(stage.attributes('aria-describedby')).toBe(reason.attributes('id'))
    expect(stage.attributes('title')).toBe('Pick a mode first')
    expect(stage.classes()).not.toContain('jb-btn-primary')
    expect(w.classes()).toContain('sca--attn')
    expect(byId(w, v.implement).classes()).toContain('jb-btn-muted')
    expect(byId(w, v.implement).attributes('disabled')).toBeDefined()
  })

  it('a press on the waiting Stage emits nothing and pulses the frame once', async () => {
    const w = mountArea({ variant: v.variant, phase: 'ready', mode: null, stageNeedsMode: true })
    await byId(w, v.stage).trigger('click')
    expect(w.emitted('stage')).toBeUndefined()
    expect(w.classes()).toContain('sca--pulse')
    expect(w.classes()).not.toContain('sca--highlight')
    await w.trigger('animationend')
    expect(w.classes()).not.toContain('sca--pulse')
  })

  it('reduced motion: the press gives a static highlight, no animation', async () => {
    vi.stubGlobal('matchMedia', (query) => ({ matches: query.includes('prefers-reduced-motion'), media: query }))
    const w = mountArea({ variant: v.variant, phase: 'ready', mode: null, stageNeedsMode: true })
    await byId(w, v.stage).trigger('click')
    expect(w.classes()).toContain('sca--highlight')
    expect(w.classes()).not.toContain('sca--pulse')
    await w.setProps({ mode: 'subagent', stageNeedsMode: false })
    expect(w.classes()).not.toContain('sca--highlight')
  })

  it('mode picked: Stage is the one filled button and emits stage; Implement stays grey', async () => {
    const w = mountArea({ variant: v.variant, phase: 'ready', mode: 'subagent' })
    const stage = byId(w, v.stage)
    expect(stage.classes()).toContain('jb-btn-primary')
    expect(stage.attributes('aria-disabled')).toBeUndefined()
    expect(byId(w, 'sca-mode-reason').exists()).toBe(false)
    expect(w.classes()).not.toContain('sca--attn')
    expect(w.findAll('.jb-btn-primary')).toHaveLength(1)
    expect(byId(w, 'radio-subagent').attributes('aria-pressed')).toBe('true')
    await stage.trigger('click')
    expect(w.emitted('stage')).toHaveLength(1)
  })

  it('the account default arrives as the picked mode: preselected, Stage ready', () => {
    const w = mountArea({ variant: v.variant, phase: 'ready', mode: 'multi_terminal' })
    expect(byId(w, 'radio-multi-terminal').attributes('aria-pressed')).toBe('true')
    expect(byId(w, v.stage).classes()).toContain('jb-btn-primary')
  })

  it('picking a mode emits pick-mode; the switch is labelled by the visible label', async () => {
    const w = mountArea({ variant: v.variant, phase: 'ready', mode: null, stageNeedsMode: true })
    expect(byId(w, v.variant === 'chain' ? 'chain-group-run-as' : 'jbf-run-as').attributes('aria-labelledby')).toBe(
      byId(w, 'sca-label').attributes('id'),
    )
    await byId(w, 'radio-multi-terminal').trigger('click')
    expect(w.emitted('pick-mode')?.[0]).toEqual(['multi_terminal'])
  })

  it('staged: Implement filled, Re-stage outlined, the mode a locked tag', async () => {
    const w = mountArea({
      variant: v.variant,
      phase: 'staged',
      mode: 'subagent',
      modeLocked: true,
      stageText: 'Re-Stage',
      implementReady: true,
    })
    expect(byId(w, 'sca-label').text()).toBe('Execution mode')
    expect(byId(w, v.tag).text()).toContain('Subagent')
    expect(byId(w, 'radio-subagent').exists()).toBe(false)
    expect(byId(w, v.implement).classes()).toContain('jb-btn-primary')
    expect(byId(w, v.stage).classes()).toContain('jb-btn-secondary')
    expect(w.findAll('.jb-btn-primary')).toHaveLength(1)
    await byId(w, v.implement).trigger('click')
    expect(w.emitted('implement')).toHaveLength(1)
  })

  it('waiting for pickup: one filled copy button and the hint; no Stage or Implement', async () => {
    const w = mountArea({ variant: v.variant, phase: 'pickup', mode: 'subagent', modeLocked: true })
    expect(byId(w, 'sca-pickup-hint').text()).toBe('No agent has picked this up yet')
    const copy = byId(w, 'sca-copy-prompt')
    expect(copy.text()).toContain(v.copy)
    expect(w.findAll('.jb-btn-primary')).toHaveLength(1)
    expect(byId(w, v.stage).exists()).toBe(false)
    expect(byId(w, v.implement).exists()).toBe(false)
    await copy.trigger('click')
    expect(w.emitted('copy-prompt')).toHaveLength(1)
  })

  it('the quiet secondary action is a text link far right', async () => {
    const w = mountArea({ variant: v.variant, phase: 'ready', mode: 'subagent' })
    const link = byId(w, v.secondary)
    expect(link.element.tagName).toBe('BUTTON')
    expect(link.classes()).toContain('sca-link')
    await link.trigger('click')
    expect(w.emitted('secondary')).toHaveLength(1)
  })
})

describe('StagingControlArea: hard disables', () => {
  it('a Stage blocked for another reason (staging in progress) is truly disabled, not a mode refusal', () => {
    const w = mountArea({ phase: 'ready', mode: 'subagent', stageBlocked: true, stageRole: 'quiet', stageText: 'Staging...' })
    const stage = byId(w, 'jbf-stage')
    expect(stage.attributes('disabled')).toBeDefined()
    expect(stage.attributes('aria-disabled')).not.toBe('true')
    expect(stage.classes()).toContain('jb-btn-ghost')
    expect(w.findAll('.jb-btn-primary')).toHaveLength(0)
  })

  it('uses design tokens only: no hex colour in the component styles', async () => {
    const source = (await import('./StagingControlArea.vue?raw')).default
    const style = source.slice(source.indexOf('<style'))
    expect(style).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })

  it('FE-9834b: the secondary link carries the tooltip it is given', () => {
    const w = mountArea({ secondaryTitle: 'Tip text' })
    expect(w.find('.sca-link').attributes('title')).toBe('Tip text')
  })
})
