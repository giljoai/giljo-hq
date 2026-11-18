import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  login: vi.fn(),
  me: vi.fn(),
  push: vi.fn(),
  query: {},
  mode: 'saas',
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push }),
  useRoute: () => ({ query: h.query }),
}))

vi.mock('@/services/api', () => ({
  default: {
    auth: {
      login: (...a) => h.login(...a),
      me: (...a) => h.me(...a),
      checkFirstLogin: vi.fn().mockResolvedValue({ data: { must_change_password: true } }),
    },
  },
  apiClient: {},
}))
vi.mock('@/sentry', () => ({ setSentryTenantKey: vi.fn() }))
vi.mock('@/services/configService', () => ({
  default: { fetchConfig: vi.fn().mockResolvedValue({}), getGiljoMode: vi.fn(() => h.mode) },
}))
vi.mock('@/config/api', () => ({ getRuntimeConfig: () => ({}) }))

import Login from './Login.vue'

const formStub = {
  template: '<form @submit.prevent><slot /></form>',
  methods: { validate: () => Promise.resolve({ valid: true }) },
}

async function signIn() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(Login, { global: { plugins: [pinia], stubs: { 'v-form': formStub } } })
  await flushPromises()
  await wrapper.find('[data-testid="email-input"]').setValue('sam')
  await wrapper.find('[data-testid="password-input"]').setValue('hunter2')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  await flushPromises()
}

describe('Login.vue keeps the return place on the way to /first-login', () => {
  beforeEach(() => {
    h.push.mockReset()
    h.login.mockResolvedValue({ data: { user: { username: 'sam' } } })
    h.me.mockResolvedValue({ data: { id: 1, username: 'sam', role: 'admin' } })
    h.mode = 'saas'
    h.query = {}
  })

  it('SaaS: carries ?redirect to /first-login', async () => {
    h.query = { redirect: '/projects/42' }
    await signIn()
    expect(h.push).toHaveBeenCalledWith({ path: '/first-login', query: { redirect: '/projects/42' } })
  })

  it('SaaS without a return place: plain /first-login', async () => {
    await signIn()
    expect(h.push).toHaveBeenCalledWith('/first-login')
  })

  it('CE: plain /first-login even with a return place (unchanged)', async () => {
    h.mode = 'ce'
    h.query = { redirect: '/projects/42' }
    await signIn()
    expect(h.push).toHaveBeenCalledWith('/first-login')
  })
})
