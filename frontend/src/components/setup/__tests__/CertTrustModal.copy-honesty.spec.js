import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  copyResult: true,
}))

vi.mock('@/config/api', () => ({
  getApiBaseURL: vi.fn().mockReturnValue('http://localhost:8000'),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn(async () => h.copyResult) }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

const globalStubs = {
  Teleport: true,
  Transition: true,
  'v-btn': { template: '<button @click="$emit(\'click\', $event)"><slot /></button>', emits: ['click'] },
  'v-icon': { template: '<i><slot /></i>' },
  'v-spacer': { template: '<div />' },
  'v-checkbox': {
    template: '<div><slot name="label" /><input type="checkbox" :checked="modelValue" /></div>',
    props: ['modelValue', 'color', 'hideDetails'],
  },
}

async function mountModal() {
  const CertTrustModal = (await import('@/components/setup/CertTrustModal.vue')).default
  return mount(CertTrustModal, { props: { modelValue: true }, global: { stubs: globalStubs } })
}

async function clickCopy(wrapper, ariaLabel) {
  await wrapper.find(`button[aria-label="${ariaLabel}"]`).trigger('click')
  await flushPromises()
}

const OS_BTN = 'Copy command'
const NODE_BTN = 'Copy NODE_EXTRA_CA_CERTS command'

describe('CertTrustModal — the check mark must mean the copy happened (FE-9320)', () => {
  beforeEach(() => {
    h.copyResult = true
  })

  it('POSITIVE CONTROL: a SUCCESSFUL copy does show the check on both controls', async () => {
    const wrapper = await mountModal()
    expect(wrapper.html()).not.toContain('mdi-check')

    await clickCopy(wrapper, OS_BTN)
    expect(wrapper.html()).toContain('mdi-check')

    await clickCopy(wrapper, NODE_BTN)
    expect(wrapper.html()).toContain('mdi-check')
  })

  it('a FAILED os-command copy does NOT show the check', async () => {
    h.copyResult = false
    const wrapper = await mountModal()

    await clickCopy(wrapper, OS_BTN)

    expect(wrapper.html()).not.toContain('mdi-check')
    expect(wrapper.html()).toContain('mdi-content-copy')
  })

  it('a FAILED node-command copy does NOT show the check', async () => {
    h.copyResult = false
    const wrapper = await mountModal()

    await clickCopy(wrapper, NODE_BTN)

    expect(wrapper.html()).not.toContain('mdi-check')
    expect(wrapper.html()).toContain('mdi-content-copy')
  })
})
