import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentsViewSwitcher from '@/components/templates/AgentsViewSwitcher.vue'

const tooltipStub = {
  props: ['text'],
  template: '<div><slot name="activator" :props="{}" /><slot />{{ text }}</div>',
}

function mountSwitcher(props = {}) {
  return mount(AgentsViewSwitcher, {
    props: { modelValue: 'roster', ...props },
    global: { stubs: { 'v-tooltip': tooltipStub } },
  })
}

describe('FE-9643b — the four square view buttons', () => {
  it('renders one icon-only button per view, in order, no text labels', () => {
    const wrapper = mountSwitcher()

    const ids = ['agents-view-roster', 'agents-view-behaviour', 'agents-view-handover', 'agents-view-prompt']
    ids.forEach((id) => {
      const btn = wrapper.find(`[data-testid="${id}"]`)
      expect(btn.exists()).toBe(true)
      expect(btn.attributes('icon')).toBeTruthy()
      expect(btn.text()).toBe('')
    })
  })

  it.each([
    ['agents-view-roster', 'mdi-view-list'],
    ['agents-view-behaviour', 'mdi-cog-outline'],
    ['agents-view-handover', 'mdi-swap-horizontal'],
    ['agents-view-prompt', 'mdi-text-box-edit-outline'],
  ])('%s uses %s', (testid, icon) => {
    const wrapper = mountSwitcher()
    expect(wrapper.find(`[data-testid="${testid}"]`).attributes('icon')).toBe(icon)
  })

  it('carries the view name as a tooltip and an aria-label', () => {
    const wrapper = mountSwitcher()

    expect(wrapper.find('[data-testid="agents-view-handover"]').attributes('aria-label')).toBe(
      'Handover template',
    )
    expect(wrapper.text()).toContain('Handover template')
  })

  it('lights the active button the same yellow as the toolbar +: color=primary, variant=flat', () => {
    const wrapper = mountSwitcher({ modelValue: 'handover' })

    const active = wrapper.find('[data-testid="agents-view-handover"]')
    expect(active.attributes('color')).toBe('primary')
    expect(active.attributes('variant')).toBe('flat')
    expect(active.attributes('data-active')).toBe('true')

    const inactive = wrapper.find('[data-testid="agents-view-roster"]')
    expect(inactive.attributes('color')).not.toBe('primary')
    expect(inactive.attributes('data-active')).toBe('false')
  })

  it('emits update:modelValue with the clicked view', async () => {
    const wrapper = mountSwitcher()

    await wrapper.find('[data-testid="agents-view-behaviour"]').trigger('click')

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['behaviour'])
  })

  it('omits the Orchestrator prompt button when showPrompt is false', () => {
    const wrapper = mountSwitcher({ showPrompt: false })

    expect(wrapper.find('[data-testid="agents-view-prompt"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="agents-view-roster"]').exists()).toBe(true)
  })
})
