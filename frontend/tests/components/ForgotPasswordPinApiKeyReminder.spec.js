/**
 * A completed PIN reset keeps API keys working, so the success message tells the
 * user to replace them if someone else may have had access.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/services/api', () => ({
  default: {
    auth: {
      verifyPinAndResetPassword: vi.fn(() => Promise.resolve({ data: { message: 'Password reset successful' } })),
    },
  },
}))

import ForgotPasswordPin from '@/components/ForgotPasswordPin.vue'

const REMINDER = 'If you think someone else had access to your account, also replace your API keys in Tools.'

describe('ForgotPasswordPin.vue -- reset success reminds the user about API keys', () => {
  let wrapper

  beforeEach(async () => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    wrapper = mount(ForgotPasswordPin, {
      props: { show: true },
      global: { stubs: { AppAlert: { template: '<div class="app-alert"><slot /></div>' } } },
      attachTo: document.body,
    })
    const state = wrapper.vm.$.setupState
    state.stage = 'reset'
    state.username = 'someone'
    state.pin = '1234'
    state.newPassword = 'Unrelated-Passphrase-77'
    state.confirmPassword = 'Unrelated-Passphrase-77'
    // The reset stage renders its own v-form, which binds the ref; replace it after that render.
    await flushPromises()
    state.resetPasswordForm = { validate: async () => ({ valid: true }) }
  })

  afterEach(() => {
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('shows the reminder with a link to the API keys page in the dialog', async () => {
    const pending = wrapper.vm.$.setupState.handleResetPassword()
    await flushPromises()

    expect(document.body.textContent).toContain(REMINDER)
    const link = document.body.querySelector('[data-testid="reset-api-keys-link"]')
    expect(link).not.toBeNull()
    expect(link.getAttribute('href')).toBe('/tools?tab=connect')

    await vi.runAllTimersAsync()
    await pending
  })

  it('carries the reminder into the message the login screen shows', async () => {
    const pending = wrapper.vm.$.setupState.handleResetPassword()
    await vi.runAllTimersAsync()
    await pending

    const [message] = wrapper.emitted('success').at(-1)
    expect(message).toContain(REMINDER)
  })
})
