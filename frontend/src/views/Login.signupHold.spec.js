import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useRoute: () => ({ query: {} }),
}))
vi.mock('@/services/api', () => ({
  default: { auth: { login: vi.fn(), me: vi.fn(), checkFirstLogin: vi.fn() } },
  apiClient: {},
}))
vi.mock('@/sentry', () => ({ setSentryTenantKey: vi.fn() }))
vi.mock('@/services/configService', () => ({
  default: { fetchConfig: vi.fn().mockResolvedValue({}), getGiljoMode: vi.fn(() => 'saas') },
}))
vi.mock('@/config/api', () => ({ getRuntimeConfig: () => ({}) }))
vi.mock('@/saas/components/auth/SocialLoginButtons.vue', () => ({
  default: defineComponent({
    emits: ['update:signup-active', 'update:link-active'],
    setup(_, { emit }) {
      return () =>
        h('div', [
          h('button', { 'data-testid': 'hold-on', onClick: () => emit('update:signup-active', true) }),
          h('button', { 'data-testid': 'hold-off', onClick: () => emit('update:signup-active', false) }),
        ])
    },
  }),
}))

import Login from './Login.vue'

const formStub = {
  template: '<form @submit.prevent><slot /></form>',
  methods: { validate: () => Promise.resolve({ valid: true }) },
}

describe('Login.vue sign-up hold clears a typed password', () => {
  let wrapper
  beforeEach(async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    wrapper = mount(Login, { global: { plugins: [pinia], stubs: { 'v-form': formStub } } })
    await flushPromises()
  })

  it('drops the password from component state while the hold is shown, and after Cancel', async () => {
    await vi.waitFor(() => expect(wrapper.find('[data-testid="hold-on"]').exists()).toBe(true))
    await wrapper.find('[data-testid="email-input"]').setValue('sam')
    wrapper.vm.password = 'hunter2'
    await flushPromises()
    expect(wrapper.vm.password).toBe('hunter2')

    await wrapper.find('[data-testid="hold-on"]').trigger('click')
    expect(wrapper.find('[data-testid="password-input"]').exists()).toBe(false)
    expect(wrapper.vm.password).toBe('')

    await wrapper.find('[data-testid="hold-off"]').trigger('click')
    expect(wrapper.vm.password).toBe('')
  })
})
