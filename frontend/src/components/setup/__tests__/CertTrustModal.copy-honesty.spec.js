/**
 * CertTrustModal.copy-honesty.spec.js — FE-9320
 *
 * Regression: the two "copy command" controls in the SETUP wizard's cert-trust
 * step set copiedOs / copiedNode BEFORE checking whether the copy actually
 * succeeded, so a failed clipboard write still flipped the icon to a green
 * check. The user reads that check as "the command is on my clipboard", pastes
 * nothing, and the cert-trust step looks done when it is not.
 *
 * The affirmative UI must appear only inside the verified-success branch.
 *
 * Edition scope: Both (shared frontend/src).
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  // What useClipboard().copy() resolves to for the next click.
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
  Transition: { template: '<slot />' },
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

  // Positive control FIRST: without this, the two negative tests below would
  // pass just as happily against a modal that never renders a check at all.
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
