import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  login: vi.fn(),
  me: vi.fn(),
  push: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push }),
  useRoute: () => ({ query: {} }),
}))

vi.mock('@/services/api', () => ({
  default: {
    auth: {
      login: (...a) => h.login(...a),
      me: (...a) => h.me(...a),
      checkFirstLogin: vi.fn().mockResolvedValue({ data: {} }),
    },
  },
  apiClient: {},
  setTenantKey: vi.fn(),
}))

vi.mock('@/sentry', () => ({
  setSentryTenantKey: vi.fn(),
}))

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getGiljoMode: vi.fn(() => 'ce'),
  },
}))

vi.mock('@/config/api', () => ({
  getRuntimeConfig: () => ({}),
}))

import Login from './Login.vue'

const formStub = {
  template: '<form @submit.prevent><slot /></form>',
  methods: { validate: () => Promise.resolve({ valid: true }) },
}

async function mountLogin() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(Login, {
    global: {
      plugins: [pinia],
      stubs: { 'v-form': formStub },
    },
  })
  await flushPromises()
  return wrapper
}

async function submitLogin(wrapper, { username = 'sam', password = 'hunter2' } = {}) {
  await wrapper.find('[data-testid="email-input"]').setValue(username)
  await wrapper.find('[data-testid="password-input"]').setValue(password)
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  await flushPromises()
}

describe('Login.vue — rate-limit copy on a 429', () => {
  beforeEach(() => {
    h.login.mockReset()
    h.me.mockReset()
    h.push.mockReset()
  })

  it('shows rate-limit copy, NOT the credentials message, when the server returns 429', async () => {
    h.login.mockRejectedValue({ response: { status: 429, data: {} } })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    const text = wrapper.text()
    expect(text).not.toContain('Please check your credentials')
    expect(text).toMatch(/too many (sign-in|login) attempts/i)
  })

  it('gives a 401 its own copy, never the rate-limit line (FE-9556 re-baseline)', async () => {
    h.login.mockRejectedValue({ response: { status: 401, data: {} } })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    expect(wrapper.text()).toContain('Invalid credentials')
    expect(wrapper.text()).not.toMatch(/too many (sign-in|login) attempts/i)
  })

  it('logs in successfully on a real 200, unaffected by the new branch', async () => {
    h.login.mockResolvedValue({ data: {} })
    h.me.mockResolvedValue({ data: { id: 'u1', tenant_key: 'tk1' } })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    expect(wrapper.text()).not.toContain('Login failed')
    expect(wrapper.text()).not.toContain('too many')
  })
})
