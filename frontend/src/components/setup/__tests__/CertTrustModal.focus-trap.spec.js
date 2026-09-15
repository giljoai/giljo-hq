import { describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

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
    attachTo: document.body,
  })
}

function focusablesIn(wrapper) {
  const panel = wrapper.find('.setup-wizard-panel').element
  return Array.from(
    panel.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  )
}

describe('CertTrustModal — focus containment (IMP-9342)', () => {
  it('moves focus into the dialog when it opens', async () => {
    const wrapper = await mountModal()
    const panel = wrapper.find('.setup-wizard-panel').element
    expect(panel.contains(document.activeElement) || document.activeElement === panel).toBe(true)
    wrapper.unmount()
  })

  it('Tab on the last focusable element wraps back to the first, not out of the dialog', async () => {
    const wrapper = await mountModal()
    const items = focusablesIn(wrapper)
    expect(items.length).toBeGreaterThan(1)

    const first = items[0]
    const last = items[items.length - 1]
    last.focus()
    expect(document.activeElement).toBe(last)

    await wrapper.find('.setup-wizard-overlay').trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(first)
    wrapper.unmount()
  })

  it('Shift+Tab on the first focusable element wraps to the last, not out of the dialog', async () => {
    const wrapper = await mountModal()
    const items = focusablesIn(wrapper)
    const first = items[0]
    const last = items[items.length - 1]
    first.focus()
    expect(document.activeElement).toBe(first)

    await wrapper.find('.setup-wizard-overlay').trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(last)
    wrapper.unmount()
  })

  it('Escape closes the dialog the same way the close button does', async () => {
    const wrapper = await mountModal()

    await wrapper.find('.setup-wizard-overlay').trigger('keydown', { key: 'Escape' })

    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')[0]).toEqual([false])
    expect(wrapper.emitted('continue')[0]).toEqual([false])
    wrapper.unmount()
  })

  it('returns focus to the element that opened it when it closes', async () => {
    const opener = document.createElement('button')
    opener.textContent = 'Trust the certificate'
    document.body.appendChild(opener)
    opener.focus()
    expect(document.activeElement).toBe(opener)

    const wrapper = await mountModal(false)
    await wrapper.setProps({ modelValue: true })
    await flushPromises()
    expect(document.activeElement).not.toBe(opener)

    await wrapper.setProps({ modelValue: false })
    await flushPromises()
    expect(document.activeElement).toBe(opener)

    wrapper.unmount()
    opener.remove()
  })

  it('backdrop click still does NOT close the dialog (deliberate, matches SetupWizardOverlay)', async () => {
    const wrapper = await mountModal()

    await wrapper.find('.setup-wizard-backdrop').trigger('click')

    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
    wrapper.unmount()
  })
})
