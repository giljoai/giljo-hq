import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}))

vi.mock('@/services/api', () => ({
  default: {
    auth: { login: vi.fn(), me: vi.fn(), checkFirstLogin: vi.fn().mockResolvedValue({ data: {} }) },
  },
  apiClient: {},
  setTenantKey: vi.fn(),
}))

vi.mock('@/sentry', () => ({ setSentryTenantKey: vi.fn() }))

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getGiljoMode: vi.fn(() => 'ce'),
  },
}))

vi.mock('@/config/api', () => ({ getRuntimeConfig: () => ({}) }))

import Login from './Login.vue'

async function mountLogin() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(Login, {
    global: {
      plugins: [pinia],
      stubs: { 'v-form': { template: '<form @submit.prevent><slot /></form>' } },
    },
  })
  await flushPromises()
  return wrapper
}

const NOTICE =
  'You were signed out because your account signed in on another browser. Each person can use two browsers at a time.'

describe('Login.vue -- signed out because the account signed in elsewhere (SEC-9758)', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('shows the notice when the interceptor parked a "displaced" reason, and only once', async () => {
    sessionStorage.setItem('giljo_sign_out_reason', 'displaced')

    const first = await mountLogin()
    expect(first.text()).toContain(NOTICE)

    const second = await mountLogin()
    expect(second.text()).not.toContain('signed in on another browser')
  })

  it('shows no notice on an ordinary visit to the login screen', async () => {
    const wrapper = await mountLogin()

    expect(wrapper.text()).not.toContain('signed in on another browser')
  })

  it('ignores a parked reason it does not know', async () => {
    sessionStorage.setItem('giljo_sign_out_reason', 'something-else')

    const wrapper = await mountLogin()

    expect(wrapper.text()).not.toContain('signed in on another browser')
  })
})
