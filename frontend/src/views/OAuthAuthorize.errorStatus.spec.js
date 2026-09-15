import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  login: vi.fn(),
  me: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({
    query: {
      client_id: 'cid',
      redirect_uri: 'https://example.com/cb',
      response_type: 'code',
      scope: 'read',
      state: 's',
      code_challenge: 'c',
      code_challenge_method: 'S256',
    },
  }),
}))

vi.mock('@/services/api', () => ({
  default: {
    auth: {
      login: (...a) => h.login(...a),
      me: (...a) => h.me(...a),
    },
  },
  apiClient: { get: vi.fn(() => Promise.resolve({ data: {} })), post: vi.fn() },
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

import OAuthAuthorize from './OAuthAuthorize.vue'

const formStub = {
  template: '<form @submit.prevent><slot /></form>',
  methods: { validate: () => Promise.resolve({ valid: true }) },
}

async function mountView() {
  const pinia = createPinia()
  setActivePinia(pinia)
  h.me.mockRejectedValue({ response: { status: 401 } })
  const wrapper = mount(OAuthAuthorize, {
    global: {
      plugins: [pinia],
      stubs: {
        'v-form': formStub,
        AppAlert: { template: '<div class="app-alert"><slot /></div>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

async function submitLogin(wrapper) {
  const inputs = wrapper.findAll('input')
  await inputs[0].setValue('sam')
  await inputs[1].setValue('hunter2')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  await flushPromises()
}

describe('OAuthAuthorize.vue — status-specific login copy (FE-9556)', () => {
  beforeEach(() => {
    h.login.mockReset()
    h.me.mockReset()
  })

  it('429 shows the rate-limit copy, not "Invalid credentials."', async () => {
    const wrapper = await mountView()
    h.login.mockRejectedValue({ response: { status: 429, data: {} } })

    await submitLogin(wrapper)

    expect(wrapper.text()).toContain(
      'Too many sign-in attempts. Please wait a minute and try again.',
    )
    expect(wrapper.text()).not.toContain('Invalid credentials')
  })

  it('a network error shows the network copy', async () => {
    const wrapper = await mountView()
    h.login.mockRejectedValue({ code: 'ERR_NETWORK', message: 'Network Error' })

    await submitLogin(wrapper)

    expect(wrapper.text()).toContain(
      'Network error. Please check your connection and try again.',
    )
    expect(wrapper.text()).not.toContain('Invalid credentials')
  })

  it('401 keeps "Invalid credentials." (equivalence pin)', async () => {
    const wrapper = await mountView()
    h.login.mockRejectedValue({ response: { status: 401, data: { detail: '' } } })

    await submitLogin(wrapper)

    expect(wrapper.text()).toContain('Invalid credentials.')
  })
})
