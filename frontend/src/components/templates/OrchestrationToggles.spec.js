import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import OrchestrationToggles from '@/components/templates/OrchestrationToggles.vue'

let mockShowToast = vi.fn()

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: (...a) => mockShowToast(...a) }),
}))

vi.mock('@/services/api', () => {
  const api = {
    settings: {
      getGeneral: vi.fn().mockResolvedValue({ data: { settings: {} } }),
      updateGeneral: vi.fn().mockResolvedValue({ data: {} }),
      getHeadlessLaunch: vi.fn().mockResolvedValue({ data: { allow_headless_launch: false } }),
      updateHeadlessLaunch: vi.fn().mockResolvedValue({ data: {} }),
    },
  }
  return { api, default: api }
})

const switchStub = {
  props: ['modelValue', 'disabled', 'color', 'hideDetails', 'density', 'ariaLabel'],
  emits: ['update:modelValue'],
  template: `
    <input
      type="checkbox"
      class="v-switch"
      v-bind="$attrs"
      :checked="modelValue"
      :disabled="disabled"
      @change="$emit('update:modelValue', $event.target.checked)"
    />
  `,
}

function mountToggles() {
  return mount(OrchestrationToggles, {
    global: {
      plugins: [createTestingPinia({ createSpy: vi.fn })],
      stubs: {
        'v-switch': switchStub,
        'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
      },
    },
  })
}


describe('OrchestrationToggles — HITL closeout toggle', () => {
  it('renders the closeout-mode-toggle testid', async () => {
    mockShowToast = vi.fn()
    const wrapper = mountToggles()
    await flushPromises()
    expect(wrapper.find('[data-testid="closeout-mode-toggle"]').exists()).toBe(true)
  })

  it('calls api.settings.updateGeneral when toggle changes', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    const wrapper = mountToggles()
    await flushPromises()

    const toggle = wrapper.find('[data-testid="closeout-mode-toggle"]')
    toggle.element.checked = false
    await toggle.trigger('change')
    await flushPromises()

    expect(api.settings.updateGeneral).toHaveBeenCalledWith(
      expect.objectContaining({ closeout_mode: 'autonomous' })
    )
  })

  it('calls api.settings.updateGeneral with hitl when toggle turns ON', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.settings.getGeneral.mockResolvedValue({
      data: { settings: { closeout_mode: 'autonomous' } },
    })
    const wrapper = mountToggles()
    await flushPromises()

    const toggle = wrapper.find('[data-testid="closeout-mode-toggle"]')
    toggle.element.checked = true
    await toggle.trigger('change')
    await flushPromises()

    expect(api.settings.updateGeneral).toHaveBeenCalledWith(
      expect.objectContaining({ closeout_mode: 'hitl' })
    )
  })
})

describe('OrchestrationToggles — BE-9084 Headless-vs-HITL launch toggle', () => {
  it('renders the headless-launch-toggle testid', async () => {
    mockShowToast = vi.fn()
    const wrapper = mountToggles()
    await flushPromises()
    expect(wrapper.find('[data-testid="headless-launch-toggle"]').exists()).toBe(true)
  })

  it('loads the current headless setting on mount (default HITL / off)', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    mountToggles()
    await flushPromises()
    expect(api.settings.getHeadlessLaunch).toHaveBeenCalled()
  })

  it('calls updateHeadlessLaunch(true) when the toggle turns ON', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    const wrapper = mountToggles()
    await flushPromises()

    const toggle = wrapper.find('[data-testid="headless-launch-toggle"]')
    toggle.element.checked = true
    await toggle.trigger('change')
    await flushPromises()

    expect(api.settings.updateHeadlessLaunch).toHaveBeenCalledWith(true)
  })

  it('shows an error toast (revert path) when the save fails', async () => {
    mockShowToast = vi.fn()
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.settings.updateHeadlessLaunch.mockRejectedValueOnce(new Error('boom'))
    const wrapper = mountToggles()
    await flushPromises()

    const toggle = wrapper.find('[data-testid="headless-launch-toggle"]')
    toggle.element.checked = true
    await toggle.trigger('change')
    await flushPromises()

    expect(api.settings.updateHeadlessLaunch).toHaveBeenCalledWith(true)
    expect(mockShowToast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error' })
    )
  })
})


describe('OrchestrationToggles — the closeout toggle preserves sibling general settings', () => {
  it('sends the merged category, not just closeout_mode', async () => {
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.settings.getGeneral.mockResolvedValue({
      data: { settings: { closeout_mode: 'hitl', execution_mode_default: 'subagent' } },
    })

    const wrapper = mountToggles()
    await flushPromises()

    const toggle = wrapper.find('[data-testid="closeout-mode-toggle"]')
    toggle.element.checked = false
    await toggle.trigger('change')
    await flushPromises()

    expect(api.settings.updateGeneral).toHaveBeenCalledWith({
      closeout_mode: 'autonomous',
      execution_mode_default: 'subagent',
    })
  })

  it('still writes closeout_mode when there are no siblings to preserve', async () => {
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.settings.getGeneral.mockResolvedValue({ data: { settings: {} } })

    const wrapper = mountToggles()
    await flushPromises()

    const toggle = wrapper.find('[data-testid="closeout-mode-toggle"]')
    toggle.element.checked = true
    await toggle.trigger('change')
    await flushPromises()

    expect(api.settings.updateGeneral).toHaveBeenCalledWith({ closeout_mode: 'hitl' })
  })

  it('does not lose the toggle write when the sibling read fails', async () => {
    const api = (await import('@/services/api')).default
    vi.clearAllMocks()
    mockShowToast = vi.fn()
    api.settings.getGeneral.mockRejectedValue(new Error('offline'))

    const wrapper = mountToggles()
    await flushPromises()

    const toggle = wrapper.find('[data-testid="closeout-mode-toggle"]')
    toggle.element.checked = false
    await toggle.trigger('change')
    await flushPromises()

    expect(api.settings.updateGeneral).toHaveBeenCalledWith(
      expect.objectContaining({ closeout_mode: 'autonomous' })
    )
  })
})
