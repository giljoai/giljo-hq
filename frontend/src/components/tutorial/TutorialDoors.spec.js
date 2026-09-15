import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import TutorialRouter from './TutorialRouter.vue'
import TutorialDoneScreen from './TutorialDoneScreen.vue'

const stubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': {
    template: '<button v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
    emits: ['click'],
  },
}

const DOORS = [
  { name: 'Existing codebase', testid: 'door-expect-existing', pick: 'D' },
  { name: 'I have an idea', testid: 'door-expect-idea', pick: 'B' },
  { name: 'I have a document', testid: 'door-expect-document', pick: 'A' },
  { name: "I'll enter it myself", testid: 'door-expect-manual', pick: 'C' },
]

describe('TutorialRouter — every door states its expectations up front (FE-9320)', () => {
  it.each(DOORS)('the "$name" door carries an expectations line', ({ testid }) => {
    const wrapper = mount(TutorialRouter, { global: { stubs } })
    const line = wrapper.find(`[data-testid="${testid}"]`)
    expect(line.exists()).toBe(true)
    expect(line.text().length).toBeGreaterThan(40)
  })

  it('"Existing codebase" warns the run takes a while', () => {
    const wrapper = mount(TutorialRouter, { global: { stubs } })
    expect(wrapper.find('[data-testid="door-expect-existing"]').text()).toMatch(
      /minutes, not seconds|run for a while/i,
    )
  })

  it('"I have an idea" says plainly that the exchange is the user and their own agent', () => {
    const wrapper = mount(TutorialRouter, { global: { stubs } })
    const text = wrapper.find('[data-testid="door-expect-idea"]').text()
    expect(text).toMatch(/conversation between you and your own agent/i)
    expect(text).toMatch(/only\s+hands you the opening prompt/i)
    expect(text).toMatch(/does not take part/i)
  })

  it('"I have a document" promises an explicit copy control, not an automatic one', () => {
    const wrapper = mount(TutorialRouter, { global: { stubs } })
    const text = wrapper.find('[data-testid="door-expect-document"]').text()
    expect(text).toMatch(/copy the discovery prompt yourself/i)
    expect(text).toMatch(/nothing is copied for you/i)
  })

  it('"I\'ll enter it myself" says it leaves the tour for the product form', () => {
    const wrapper = mount(TutorialRouter, { global: { stubs } })
    expect(wrapper.find('[data-testid="door-expect-manual"]').text()).toMatch(
      /leaves the tour and opens the product form/i,
    )
  })

  it('still emits the stored letter for each door (no data migration)', async () => {
    const wrapper = mount(TutorialRouter, { global: { stubs } })
    for (const { pick } of DOORS) {
      await wrapper.find(`[data-testid="tutorial-door-${pick}"]`).trigger('click')
    }
    expect(wrapper.emitted('pick').flat()).toEqual(DOORS.map((d) => d.pick))
  })
})

describe('TutorialDoneScreen — the finish state has a way out (FE-9320)', () => {
  it('offers a close/proceed control that is not "skip"', () => {
    const wrapper = mount(TutorialDoneScreen, {
      props: { routerChoice: 'A' },
      global: { stubs },
    })
    const btn = wrapper.find('[data-testid="tutorial-done-close"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).not.toMatch(/skip/i)
  })

  it('emits close when it is used', async () => {
    const wrapper = mount(TutorialDoneScreen, {
      props: { routerChoice: 'D' },
      global: { stubs },
    })
    await wrapper.find('[data-testid="tutorial-done-close"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('ships the operator\'s literal copy, not the old lookalike-card promise', () => {
    const wrapper = mount(TutorialDoneScreen, {
      props: { routerChoice: 'D' },
      global: { stubs },
    })
    const text = wrapper.text()
    expect(text).toContain('Great work, you just added a product. Time to put your agents to work.')
    expect(text).toContain('Your Home screen will now show three cards')
    expect(text).toContain('create your first project')
    expect(text).toContain('bootstrap a new product')
    expect(text).toContain('import an existing product')
    expect(text).toContain('We suggest Import an existing product')
    expect(text).toContain('writes your first 360 memories')
    expect(text).not.toContain('four read-only audits that seed your 360 Memory')
    expect(text).not.toContain('Product active. Time for a mission.')
  })

  it('no longer renders a lookalike card that could mismatch the real one', () => {
    const wrapper = mount(TutorialDoneScreen, {
      props: { routerChoice: 'D' },
      global: { stubs },
    })
    expect(wrapper.find('[data-testid="tutorial-spotlight-card"]').exists()).toBe(false)
  })

  it('the copy is identical regardless of which door the user took (no per-door lookalike)', () => {
    const wrapperD = mount(TutorialDoneScreen, { props: { routerChoice: 'D' }, global: { stubs } })
    const wrapperB = mount(TutorialDoneScreen, { props: { routerChoice: 'B' }, global: { stubs } })
    expect(wrapperD.text()).toBe(wrapperB.text())
  })
})
