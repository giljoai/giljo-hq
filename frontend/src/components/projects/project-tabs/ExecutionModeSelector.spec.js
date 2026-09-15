import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ExecutionModeSelector from './ExecutionModeSelector.vue'

const globalStubs = {
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
}

describe('ExecutionModeSelector', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  function mountSelector(props = {}) {
    return mount(ExecutionModeSelector, {
      props: {
        executionPlatform: null,
        isExecutionModeLocked: false,
        ...props,
      },
      global: { stubs: globalStubs },
    })
  }

  it('renders 2 mode pills (BE-9035c collapse)', () => {
    const wrapper = mountSelector()
    expect(wrapper.findAll('[data-testid^="radio-"]')).toHaveLength(2)
  })

  it('emits subagent when the Subagent pill is clicked', async () => {
    const wrapper = mountSelector({ executionPlatform: null })
    await wrapper.find('[data-testid="radio-subagent"]').trigger('click')
    expect(wrapper.emitted('change')).toBeTruthy()
    expect(wrapper.emitted('change')[0]).toEqual(['subagent'])
  })

  it('marks the active platform pill with class "active"', () => {
    const wrapper = mountSelector({ executionPlatform: 'subagent' })
    const subagentBtn = wrapper.find('[data-testid="radio-subagent"]')
    expect(subagentBtn.classes()).toContain('active')
  })

  it('emits change event when unlocked pill is clicked', async () => {
    const wrapper = mountSelector({ executionPlatform: null })
    await wrapper.find('[data-testid="radio-multi-terminal"]').trigger('click')
    expect(wrapper.emitted('change')).toBeTruthy()
    expect(wrapper.emitted('change')[0]).toEqual(['multi_terminal'])
  })

  it('does NOT emit when locked pill is clicked', async () => {
    const wrapper = mountSelector({ isExecutionModeLocked: true })
    await wrapper.find('[data-testid="radio-multi-terminal"]').trigger('click')
    expect(wrapper.emitted('change')).toBeFalsy()
  })

  it('disabled prop on pill buttons when locked', () => {
    const wrapper = mountSelector({ isExecutionModeLocked: true })
    const btn = wrapper.find('[data-testid="radio-multi-terminal"]')
    expect(btn.attributes('disabled')).toBeDefined()
  })
})
