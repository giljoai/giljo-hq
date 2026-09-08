/**
 * Login.errorStatus.spec.js (FE-9556)
 *
 * Every login failure showed the generic "Login failed. Please check your
 * credentials." because userStore.login() swallowed the axios error into a
 * bare boolean -- Login.vue's carefully status-branched catch block
 * (401 detail branching, 403, 429, network) was dead code for a real login
 * attempt. The store now rethrows after clearing local state, so the
 * already-written catch block owns failures. Each case below was proven RED
 * against the pre-fix code (generic copy rendered for every status).
 *
 * Mounting pattern: Login.rateLimit.spec.js (PR #1002), which this builds on.
 * Edition scope: Both -- Login.vue is CE+SaaS shared.
 */
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

describe('Login.vue — status-specific copy per failure (FE-9556)', () => {
  beforeEach(() => {
    h.login.mockReset()
    h.me.mockReset()
    h.push.mockReset()
  })

  it('401 with no detail shows "Invalid credentials", not the generic line', async () => {
    h.login.mockRejectedValue({ response: { status: 401, data: { detail: '' } } })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    expect(wrapper.text()).toContain('Invalid credentials')
    expect(wrapper.text()).not.toContain('Please check your credentials')
  })

  it('401 with an inactive-account detail shows the inactive copy', async () => {
    h.login.mockRejectedValue({
      response: { status: 401, data: { detail: 'Account is inactive' } },
    })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    expect(wrapper.text()).toContain('Account is inactive. Please contact your administrator.')
  })

  it('401 with a must_change_password detail redirects to /welcome', async () => {
    h.login.mockRejectedValue({
      response: { status: 401, data: { detail: 'must_change_password' } },
    })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    expect(h.push).toHaveBeenCalledWith('/welcome')
  })

  it('403 shows the forbidden copy', async () => {
    h.login.mockRejectedValue({ response: { status: 403, data: { detail: '' } } })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    expect(wrapper.text()).toContain('Access forbidden. Please contact your administrator.')
  })

  it('a network error shows the network copy', async () => {
    h.login.mockRejectedValue({ code: 'ERR_NETWORK', message: 'Network Error' })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    expect(wrapper.text()).toContain(
      'Network error - please check your connection and try again',
    )
    expect(wrapper.text()).not.toContain('Please check your credentials')
  })

  it('429 keeps the PR #1002 rate-limit copy (regression pin)', async () => {
    h.login.mockRejectedValue({ response: { status: 429, data: {} } })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    expect(wrapper.text()).toContain(
      'Too many sign-in attempts. Please wait a minute and try again.',
    )
    expect(wrapper.text()).not.toContain('Please check your credentials')
  })

  it('a successful login is unaffected', async () => {
    h.login.mockResolvedValue({ data: {} })
    h.me.mockResolvedValue({ data: { id: 'u1', tenant_key: 'tk1' } })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    expect(wrapper.text()).not.toContain('Login failed')
    expect(wrapper.text()).not.toContain('Invalid credentials')
  })
})
