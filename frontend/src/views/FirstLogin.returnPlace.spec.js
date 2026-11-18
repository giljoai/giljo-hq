import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  push: vi.fn(),
  query: {},
  mode: 'saas',
  needsSetup: true,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push }),
  useRoute: () => ({ query: h.query }),
}))

vi.mock('@/services/configService', () => ({
  default: { fetchConfig: vi.fn(), getGiljoMode: () => h.mode, config: null },
}))

vi.mock('@/services/api', () => ({
  apiClient: { get: vi.fn(() => Promise.resolve({ data: { needs_setup: h.needsSetup } })) },
  default: { auth: { completeFirstLogin: vi.fn(() => Promise.resolve({ data: {} })) } },
}))

import FirstLogin from '@/views/FirstLogin.vue'

async function submit() {
  const wrapper = mount(FirstLogin, {
    global: { stubs: { AppAlert: { template: '<div><slot /></div>' } } },
  })
  await flushPromises()
  wrapper.vm.currentPassword = 'old-password'
  wrapper.vm.newPassword = 'NewPassword123!'
  wrapper.vm.confirmPassword = 'NewPassword123!'
  wrapper.vm.recoveryPin = '1234'
  wrapper.vm.confirmPin = '1234'
  wrapper.vm.firstLoginForm = { validate: () => Promise.resolve({ valid: true }) }
  await wrapper.vm.handleSubmit()
  await flushPromises()
}

describe('FirstLogin.vue carries the page the person first asked for to org setup', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.push.mockReset()
    h.query = {}
    h.mode = 'saas'
    h.needsSetup = true
  })

  it('passes ?redirect on to /org-setup', async () => {
    h.query = { redirect: '/projects/42' }
    await submit()
    expect(h.push).toHaveBeenCalledWith({ path: '/org-setup', query: { redirect: '/projects/42' } })
  })

  it('goes to plain /org-setup when there is no return place', async () => {
    await submit()
    expect(h.push).toHaveBeenCalledWith('/org-setup')
  })

  it('CE: never calls org setup and still lands on /', async () => {
    h.mode = 'ce'
    h.query = { redirect: '/projects/42' }
    await submit()
    expect(h.push).toHaveBeenCalledTimes(1)
    expect(h.push).toHaveBeenCalledWith('/')
  })
})
