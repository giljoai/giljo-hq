import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/services/api', () => ({
  default: { connect: { credentialStatus: vi.fn(() => Promise.resolve({ data: {} })) } },
}))

async function mountOverlay(pinia, step2 = { template: '<div />' }) {
  const SetupWizardOverlay = (await import('@/components/setup/SetupWizardOverlay.vue')).default
  const w = mount(SetupWizardOverlay, {
    props: { modelValue: true, currentStep: 1, selectedTools: ['claude_code'] },
    global: {
      plugins: [pinia],
      stubs: {
        teleport: true,
        SetupStep2Connect: step2,
        SetupStep3Commands: { template: '<div />' },
        'v-btn': { template: '<button><slot /></button>' },
        'v-icon': { template: '<i><slot /></i>' },
      },
    },
  })
  await flushPromises()
  return w
}
const overlay = (w) => w.find('[data-testid="setup-wizard-overlay"]')

describe('setup pop-up beside the getting-started pane', () => {
  let guide
  let pinia
  beforeEach(async () => {
    pinia = createPinia()
    setActivePinia(pinia)
    const { useGuideStore } = await import('@/stores/guide')
    guide = useGuideStore()
  })

  it('no pane: the dark layer covers the whole screen', async () => {
    const w = await mountOverlay(pinia)
    expect(overlay(w).attributes('style')).toContain('right: 0px')
  })

  it('open pane: the whole pop-up, scrim included, ends where the pane starts', async () => {
    guide.setReservedWidth(320)
    const w = await mountOverlay(pinia)
    expect(overlay(w).attributes('style')).toContain('right: 320px')
    expect(overlay(w).find('.setup-wizard-backdrop').exists()).toBe(true)
  })

  it('folded pane: it leaves the rail alone too', async () => {
    guide.setReservedWidth(56)
    const w = await mountOverlay(pinia)
    expect(overlay(w).attributes('style')).toContain('right: 56px')
  })

  it('the pane drawer is not inside the pop-up element at all', async () => {
    const w = await mountOverlay(pinia)
    expect(overlay(w).find('[data-testid="guide-pane"]').exists()).toBe(false)
  })

  it('the rail row of a connected_before tool says so and is not the green or waiting look', async () => {
    const step2 = {
      emits: ['walk-state'],
      mounted() {
        this.$emit('walk-state', { order: ['claude_code'], activeId: 'claude_code', conn: { claude_code: 'connected_before' } })
      },
      template: '<div />',
    }
    const w = await mountOverlay(pinia, step2)
    const row = w.find('[data-testid="rail-sub-claude_code"]')
    expect(row.text()).toContain('CONNECTED BEFORE')
    expect(row.find('.rail-sub-dot--done').exists()).toBe(false)
    expect(row.find('.rail-sub-dot--current').exists()).toBe(false)
  })
})
