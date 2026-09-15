import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const handlers = {}
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on(event, fn) {
      handlers[event] = fn
      return () => { delete handlers[event] }
    },
  }),
}))

async function mountOverlay(props = {}) {
  const SetupWizardOverlay = (await import('@/components/setup/SetupWizardOverlay.vue')).default
  return mount(SetupWizardOverlay, {
    props: { modelValue: true, mode: 'setup', currentStep: 2, ...props },
    global: {
      stubs: {
        teleport: true,
        SetupStep2Connect: {
          emits: ['can-proceed', 'step-data'],
          template: '<div />',
          mounted() {
            this.$emit('step-data', { connectedTools: ['claude_code'] })
            this.$emit('can-proceed', true)
          },
        },
        SetupStep4Complete: { template: '<div />' },
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

async function mountOnInstallStep(props = {}) {
  const wrapper = await mountOverlay({ currentStep: 1, ...props })
  await wrapper.vm.$nextTick()
  await wrapper.setProps({ currentStep: 2 })
  await wrapper.vm.$nextTick()
  return wrapper
}

function nextBtn(wrapper) {
  return wrapper.find('[data-testid="setup-next-btn"]')
}

describe('FE-9497 — install step gates Next on real installs', () => {
  beforeEach(() => {
    for (const key of Object.keys(handlers)) delete handlers[key]
  })

  it('connects a tool but installs nothing: Next is disabled', async () => {
    const wrapper = await mountOnInstallStep()
    expect(nextBtn(wrapper).attributes('disabled')).not.toBeUndefined()
  })

  it('skills installed: Next becomes enabled (BE-9605c: no agents step)', async () => {
    const wrapper = await mountOnInstallStep()
    handlers['setup:commands_installed']({ tool_name: 'claude_code' })
    await wrapper.vm.$nextTick()
    expect(nextBtn(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('the retired agents_downloaded event is not subscribed', async () => {
    await mountOnInstallStep()
    expect(handlers['setup:agents_downloaded']).toBeUndefined()
  })

  it('giljo_setup bootstrap event alone enables Next', async () => {
    const wrapper = await mountOnInstallStep()
    handlers['setup:bootstrap_complete']({})
    await wrapper.vm.$nextTick()
    expect(nextBtn(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('the checklist starts unticked even for a user who finished setup before', async () => {
    const wrapper = await mountOnInstallStep({ isRerun: true, setupStepCompleted: 4 })
    expect(wrapper.findAll('.checklist-text--done')).toHaveLength(0)
    expect(nextBtn(wrapper).attributes('disabled')).not.toBeUndefined()
  })

  it('offers the skip link so a gated user is never trapped', async () => {
    const wrapper = await mountOnInstallStep()
    const skip = wrapper.find('[data-testid="install-skip"]')
    expect(skip.exists()).toBe(true)

    await skip.trigger('click')
    const stepChange = wrapper.emitted('update:currentStep')
    expect(stepChange[stepChange.length - 1]).toEqual([3])
  })
})
