/**
 * A failed PIN check or PIN reset must not write the typed PIN or password to the console:
 * the axios error carries the request body in config.data.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const SECRET_PIN = '4821'
const SECRET_PASSWORD = 'Unrelated-Passphrase-77'

function axiosError(body) {
  const err = new Error('Request failed with status code 400')
  err.config = { data: JSON.stringify(body) }
  err.response = { status: 400, data: { detail: 'Invalid username or PIN.' } }
  return err
}

vi.mock('@/services/api', () => ({
  default: {
    auth: {
      verifyPin: vi.fn((body) => Promise.reject(axiosError(body))),
      verifyPinAndResetPassword: vi.fn((body) => Promise.reject(axiosError(body))),
    },
  },
}))

import ForgotPasswordPin from '@/components/ForgotPasswordPin.vue'

function logged(spy) {
  return spy.mock.calls
    .flat()
    .map((arg) => {
      if (arg instanceof Error) return `${arg.message} ${JSON.stringify(arg.config ?? {})}`
      return typeof arg === 'string' ? arg : JSON.stringify(arg)
    })
    .join('\n')
}

describe('ForgotPasswordPin.vue -- failures never log the PIN or password', () => {
  let errorSpy
  let wrapper

  beforeEach(() => {
    setActivePinia(createPinia())
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    wrapper = mount(ForgotPasswordPin, {
      props: { show: true },
      global: { stubs: { AppAlert: { template: '<div><slot /></div>' } } },
      attachTo: document.body,
    })
    const state = wrapper.vm.$.setupState
    state.username = 'someone'
    state.pin = SECRET_PIN
    state.newPassword = SECRET_PASSWORD
    state.confirmPassword = SECRET_PASSWORD
    state.pinForm = { validate: async () => ({ valid: true }) }
    state.resetPasswordForm = { validate: async () => ({ valid: true }) }
  })

  afterEach(() => {
    wrapper.unmount()
    errorSpy.mockRestore()
  })

  it('a failed PIN check logs no PIN', async () => {
    await wrapper.vm.$.setupState.handleVerifyPin()
    await flushPromises()

    expect(errorSpy).toHaveBeenCalled()
    expect(logged(errorSpy)).not.toContain(SECRET_PIN)
  })

  it('a failed reset logs neither the PIN nor the new password', async () => {
    await wrapper.vm.$.setupState.handleResetPassword()
    await flushPromises()

    expect(errorSpy).toHaveBeenCalled()
    const text = logged(errorSpy)
    expect(text).not.toContain(SECRET_PIN)
    expect(text).not.toContain(SECRET_PASSWORD)
  })
})
