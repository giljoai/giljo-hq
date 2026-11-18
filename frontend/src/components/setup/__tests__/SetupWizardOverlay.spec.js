import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

async function mountOverlay(props = {}) {
  const SetupWizardOverlay = (await import('@/components/setup/SetupWizardOverlay.vue')).default
  return mount(SetupWizardOverlay, {
    props: { modelValue: true, currentStep: 1, ...props },
    global: {
      stubs: {
        teleport: true,
        SetupStep2Connect: { template: '<div class="step2-stub" />' },
        'v-btn': { template: '<button v-bind="$attrs"><slot /></button>' },
        'v-icon': { template: '<i><slot /></i>' },
        'v-dialog': { template: '<div><slot /></div>' },
        'v-card': { template: '<div><slot /></div>' },
        'v-card-text': { template: '<div><slot /></div>' },
        'v-spacer': { template: '<span />' },
      },
    },
  })
}

describe('SetupWizardOverlay — footer skip control (Connect step only)', () => {
  it('renders the "Skip for now" footer link on the Connect step', async () => {
    const wrapper = await mountOverlay({ currentStep: 1 })
    const skip = wrapper.find('[data-testid="connect-skip"]')
    expect(skip.exists()).toBe(true)
    expect(skip.text()).toBe('Skip for now')
  })

  it('does NOT render a footer skip link on Choose Tools', async () => {
    const stepTools = await mountOverlay({ currentStep: 0 })
    expect(stepTools.find('[data-testid="connect-skip"]').exists()).toBe(false)
  })

  it('clicking the Connect skip reports skipped and closes the pop-up', async () => {
    const wrapper = await mountOverlay({ currentStep: 1 })
    await wrapper.find('[data-testid="connect-skip"]').trigger('click')

    expect(wrapper.emitted('update:currentStep')).toBeFalsy()
    const closed = wrapper.emitted('update:modelValue')
    expect(closed[closed.length - 1]).toEqual([false])

    const completed = wrapper.emitted('step-complete')
    expect(completed).toBeTruthy()
    const last = completed[completed.length - 1][0]
    expect(last.step).toBe(1)
    expect(last.data.skipped).toBe(true)
    expect(last.data.connectedTools).toEqual([])
  })
})

describe('SetupWizardOverlay — Gradient Rail stepper node state', () => {
  it('marks the earlier step done, the current step active', async () => {
    const wrapper = await mountOverlay({ currentStep: 1 })
    const tools = wrapper.find('[data-testid="rail-node-tools"]')
    const connect = wrapper.find('[data-testid="rail-node-connect"]')

    expect(tools.classes()).toContain('rail-node--done')
    expect(connect.classes()).toContain('rail-node--active')
    expect(connect.classes()).not.toContain('rail-node--done')
  })

  it('on the first step nothing is done and Choose Tools is active', async () => {
    const wrapper = await mountOverlay({ currentStep: 0 })
    expect(wrapper.find('[data-testid="rail-node-tools"]').classes()).toContain('rail-node--active')
    expect(wrapper.find('[data-testid="rail-node-connect"]').classes()).not.toContain('rail-node--done')
    expect(wrapper.find('[data-testid="rail-node-connect"]').classes()).not.toContain('rail-node--clickable')
  })

  it('only the done (earlier) rail node is clickable', async () => {
    const wrapper = await mountOverlay({ currentStep: 1 })
    expect(wrapper.find('[data-testid="rail-node-tools"]').classes()).toContain('rail-node--clickable')
    expect(wrapper.find('[data-testid="rail-node-connect"]').classes()).not.toContain('rail-node--clickable')
  })

  it('clicking the done rail node navigates back to Choose Tools', async () => {
    const wrapper = await mountOverlay({ currentStep: 1 })
    await wrapper.find('[data-testid="rail-node-tools"]').trigger('click')
    const stepChange = wrapper.emitted('update:currentStep')
    expect(stepChange[stepChange.length - 1]).toEqual([0])
  })

  it('clicking a future rail node does nothing', async () => {
    const wrapper = await mountOverlay({ currentStep: 0 })
    await wrapper.find('[data-testid="rail-node-connect"]').trigger('click')
    expect(wrapper.emitted('update:currentStep')).toBeFalsy()
  })

  it('shows the current step count out of 3', async () => {
    const wrapper = await mountOverlay({ currentStep: 1 })
    expect(wrapper.find('.rail-count').text()).toBe('Step 2 of 3')
  })
})

describe('SetupWizardOverlay — Next button gating (canProceed)', () => {
  it('disables Next on Choose Tools until a tool is selected', async () => {
    const wrapper = await mountOverlay({ currentStep: 0, selectedTools: [] })
    const next = wrapper.find('[data-testid="setup-next-btn"]')
    expect(next.attributes('disabled')).not.toBeUndefined()
  })

  it('enables Next on Choose Tools once a tool card is selected', async () => {
    const wrapper = await mountOverlay({ currentStep: 0, selectedTools: [] })
    await wrapper.find('[data-testid="tool-select-claude_code"]').trigger('click')
    const next = wrapper.find('[data-testid="setup-next-btn"]')
    expect(next.attributes('disabled')).toBeUndefined()
  })
})

describe('SetupWizardOverlay — Choose-tools grid (FE-9204 / INF-9605a: four tools)', () => {
  it('renders all four tool cards, including OpenCode and the generic client', async () => {
    const wrapper = await mountOverlay({ currentStep: 0, selectedTools: [] })
    for (const id of ['claude_code', 'codex_cli', 'opencode', 'generic']) {
      expect(wrapper.find(`[data-testid="tool-select-${id}"]`).exists()).toBe(true)
    }
  })

  it('shows a method tag per card (SaaS default: sign-in tools + manual)', async () => {
    const wrapper = await mountOverlay({ currentStep: 0, selectedTools: [] })
    expect(wrapper.find('[data-testid="tool-method-claude_code"]').text()).toBe('SIGN-IN OR KEY')
    expect(wrapper.find('[data-testid="tool-method-codex_cli"]').text()).toBe('SIGN-IN OR KEY')
    expect(wrapper.find('[data-testid="tool-method-generic"]').text()).toBe('MANUAL CONFIG')
  })

  it('toggling a card selects and deselects it (check ring)', async () => {
    const wrapper = await mountOverlay({ currentStep: 0, selectedTools: [] })
    const card = wrapper.find('[data-testid="tool-select-opencode"]')
    expect(card.classes()).not.toContain('tool-card--sel')
    await card.trigger('click')
    expect(card.classes()).toContain('tool-card--sel')
    await card.trigger('click')
    expect(card.classes()).not.toContain('tool-card--sel')
  })
})

describe('SetupWizardOverlay — learning mode removed (FE-9200)', () => {
  it('renders the Gradient Rail regardless of the legacy mode prop', async () => {
    const wrapper = await mountOverlay({ mode: 'learning', currentStep: 0 })
    expect(wrapper.text()).not.toContain('How to Use GiljoAI MCP')
    expect(wrapper.find('[aria-label="Setup Giljo HQ"]').exists()).toBe(true)
    expect(wrapper.find('.setup-wizard-panel').exists()).toBe(false)
    expect(wrapper.find('.wizard-rail').exists()).toBe(true)
  })
})
