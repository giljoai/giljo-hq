/**
 * Community Edition recovery copy: CE sends no email, so the forgot-password
 * dialog and the Create Admin PIN step must say the Recovery PIN is the way back in.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/services/api', () => ({
  default: {
    post: vi.fn(() => Promise.resolve({ data: {} })),
    auth: { createFirstAdmin: vi.fn() },
  },
  setTenantKey: vi.fn(),
}))

vi.mock('@/services/setupService', () => ({
  default: { invalidateStatusCache: vi.fn() },
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return { ...actual, useRouter: () => ({ push: vi.fn() }) }
})

import ForgotPasswordPin from '@/components/ForgotPasswordPin.vue'
import CreateAdminAccount from '@/views/CreateAdminAccount.vue'

const LEAD =
  'Community Edition does not send email. Enter your username and the 4-digit Recovery PIN you set when you created your account.'
const ADMIN_RESET =
  'Forgot the PIN too? Another admin on this install can reset it from your user row under Users.'
const PIN_HELPER =
  'This PIN is the only way to reset a forgotten password on Community Edition. Keep it safe.'

describe('ForgotPasswordPin.vue -- CE recovery copy', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
    setActivePinia(createPinia())
  })

  function mountDialog() {
    return mount(ForgotPasswordPin, {
      props: { show: true },
      global: {
        stubs: { AppAlert: { template: '<div class="app-alert"><slot /></div>' } },
      },
      attachTo: document.body,
    })
  }

  it('states that CE sends no email and asks for the Recovery PIN', async () => {
    mountDialog()
    await flushPromises()
    expect(document.body.textContent.replace(/\s+/g, ' ')).toContain(LEAD)
  })

  it('points a user who lost the PIN to another admin', async () => {
    mountDialog()
    await flushPromises()
    const text = document.body.textContent.replace(/\s+/g, ' ')
    expect(text).toContain(ADMIN_RESET)
    expect(text).not.toContain('please contact your administrator')
  })

  it('keeps the "Email or username" field label', async () => {
    mountDialog()
    await flushPromises()
    expect(document.body.innerHTML).toContain('Email or username')
  })
})

describe('CreateAdminAccount.vue -- Recovery PIN step helper', () => {
  it('tells the user the PIN is the only way to reset a password on CE', async () => {
    const wrapper = mount(CreateAdminAccount, {
      global: {
        plugins: [
          createVuetify(),
          createPinia(),
          createRouter({
            history: createMemoryHistory(),
            routes: [{ path: '/', name: 'Dashboard' }],
          }),
        ],
        stubs: {
          'v-container': { template: '<div><slot /></div>' },
          'v-row': { template: '<div><slot /></div>' },
          'v-col': { template: '<div><slot /></div>' },
          'v-card': { template: '<div><slot /></div>' },
          'v-card-text': { template: '<div><slot /></div>' },
          'v-form': { template: '<form><slot /></form>' },
          'v-text-field': { template: '<div />' },
          'v-btn': true,
          'v-icon': true,
          'v-alert': true,
        },
      },
    })
    wrapper.vm.step = 2
    await flushPromises()
    expect(wrapper.text().replace(/\s+/g, ' ')).toContain(PIN_HELPER)
  })
})
