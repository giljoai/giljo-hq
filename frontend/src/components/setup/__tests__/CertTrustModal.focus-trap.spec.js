/**
 * CertTrustModal.focus-trap.spec.js — IMP-9342 item 2
 *
 * The dialog is `role="dialog" aria-modal="true"`, which is a promise to the
 * user agent that focus is contained. It was not: the component carried no
 * focus-management code at all, so Tab walked straight out of the open overlay
 * into the page behind it. From the Connect tab that let a keyboard user tab
 * out, reach the inline cert-trust link, press Enter, and end up with two
 * identical overlays stacked at the same z-index — closing the top one revealed
 * another, which reads as "the close button didn't work".
 *
 * Pinned here: focus enters the dialog on open, Tab and Shift+Tab wrap inside
 * it, Escape closes it, and focus returns whence it came on close.
 *
 * Museum rule: the backdrop deliberately does NOT close this dialog (it matches
 * SetupWizardOverlay). The last test pins that so a later "improvement" to
 * dismiss-on-backdrop has to argue with a failing test first.
 *
 * Edition scope: CE.
 */
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

// Same stub set as CertTrustModal.spec.js, but the buttons must be real focusable
// <button> elements — the whole point of the test is where focus lands.
const globalStubs = {
  Teleport: true,
  Transition: { template: '<slot />' },
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
    attachTo: document.body, // real focus needs the nodes in the document
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
    // Same payload contract as Skip/close: the "don't show again" choice rides along.
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
    await flushPromises() // the watcher awaits nextTick before focusing the panel
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
