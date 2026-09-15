import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'


vi.mock('@/config/api', () => ({
  getApiBaseURL: vi.fn().mockReturnValue('http://localhost:8000'),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn().mockResolvedValue(true) }),
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
    template: '<div><slot name="label" /><input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" /></div>',
    props: ['modelValue', 'color', 'hideDetails'],
    emits: ['update:modelValue'],
  },
}

async function mountModal(open = true) {
  const CertTrustModal = (await import('@/components/setup/CertTrustModal.vue')).default
  return mount(CertTrustModal, {
    props: { modelValue: open },
    global: { stubs: globalStubs },
  })
}


describe('CertTrustModal — honest copy (INF-6241)', () => {
  it('does not contain mkcert / rootCA framing in the displayed copy', async () => {
    const wrapper = await mountModal()
    const text = wrapper.text()
    expect(text).not.toContain('rootCA')
    expect(text).not.toContain('our root certificate')
    expect(text).not.toContain('Install HTTPS Certificate')
  })

  it('renders the both-cases intro (public-cert done + self-signed trust steps)', async () => {
    const wrapper = await mountModal()
    const text = wrapper.text()
    expect(text).toContain('not one issued by GiljoAI')
    expect(text).toContain('If your browser showed no certificate warning')
    expect(text).toContain('If your browser warned you')
    expect(text).toContain('Skip these if your browser shows a padlock')
  })

  it('uses the canonical downloaded filename giljo-server-cert.pem', async () => {
    const wrapper = await mountModal()
    const text = wrapper.text()
    expect(text).toContain('giljo-server-cert.pem')
  })
})

describe('CertTrustModal — "Don\'t show again" checkbox (INF-6040)', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('renders a "Don\'t show this again" checkbox in the footer', async () => {
    const wrapper = await mountModal()
    expect(wrapper.text()).toContain("Don't show this again on this device")
  })

  it('emits continue with false when Continue is clicked without checking the box', async () => {
    const wrapper = await mountModal()
    const buttons = wrapper.findAll('button')
    const continueBtn = buttons.find(b => b.text().includes('Continue'))
    await continueBtn.trigger('click')

    const emitted = wrapper.emitted('continue')
    expect(emitted).toHaveLength(1)
    expect(emitted[0]).toEqual([false])
  })

  it('emits continue with true when the checkbox is checked and Continue is clicked', async () => {
    const wrapper = await mountModal()

    const checkbox = wrapper.find('input[type="checkbox"]')
    await checkbox.setValue(true)

    const buttons = wrapper.findAll('button')
    const continueBtn = buttons.find(b => b.text().includes('Continue'))
    await continueBtn.trigger('click')

    const emitted = wrapper.emitted('continue')
    expect(emitted).toHaveLength(1)
    expect(emitted[0]).toEqual([true])
  })

  it('emits continue with false when Skip is clicked (checkbox unchecked)', async () => {
    const wrapper = await mountModal()
    const buttons = wrapper.findAll('button')
    const skipBtn = buttons.find(b => b.text().includes('Skip'))
    await skipBtn.trigger('click')

    const emitted = wrapper.emitted('continue')
    expect(emitted).toHaveLength(1)
    expect(emitted[0]).toEqual([false])
  })

  it('emits continue with the checkbox value when Skip is clicked (checkbox checked)', async () => {
    const wrapper = await mountModal()

    const checkbox = wrapper.find('input[type="checkbox"]')
    await checkbox.setValue(true)

    const buttons = wrapper.findAll('button')
    const skipBtn = buttons.find(b => b.text().includes('Skip'))
    await skipBtn.trigger('click')

    const emitted = wrapper.emitted('continue')
    expect(emitted).toHaveLength(1)
    expect(emitted[0]).toEqual([true])
  })
})
