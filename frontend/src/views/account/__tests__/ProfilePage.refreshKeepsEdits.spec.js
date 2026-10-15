import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const updateUserMock = vi.fn()
vi.mock('@/services/api', () => ({
  default: { auth: { updateUser: (...args) => updateUserMock(...args) } },
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/services/setupService', () => ({
  default: { checkEnhancedStatus: () => Promise.resolve({ mode: 'ce' }) },
}))

const storeState = reactive({ currentUser: null })
function serverUser(overrides = {}) {
  return {
    id: 'user-1',
    username: 'solo',
    first_name: 'Solo',
    last_name: 'Admin',
    full_name: 'Solo Admin',
    email: 'solo@example.com',
    role: 'admin',
    ...overrides,
  }
}
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    get currentUser() {
      return storeState.currentUser
    },
    currentOrg: null,
    orgRole: null,
    logout: vi.fn(),
  }),
}))

async function mountPage() {
  setActivePinia(createPinia())
  const { default: ProfilePage } = await import('@/views/account/ProfilePage.vue')
  const wrapper = mount(ProfilePage, {
    global: {
      stubs: {
        RoleBadge: true,
        'v-card': { template: '<div><slot /></div>' },
        'v-card-text': { template: '<div><slot /></div>' },
        'v-form': { template: '<form><slot /></form>' },
        'v-text-field': { template: '<div><slot /></div>' },
        'v-btn': { template: '<button><slot /></button>' },
        'v-alert': true,
        'v-divider': true,
        'v-icon': true,
        'v-spacer': true,
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('ProfilePage keeps typed edits across a current-user refresh', () => {
  beforeEach(() => {
    storeState.currentUser = serverUser()
    updateUserMock.mockReset()
    updateUserMock.mockImplementation((_id, payload) =>
      Promise.resolve({ data: { ...payload, full_name: `${payload.first_name} ${payload.last_name}` } }),
    )
  })

  it('a refetch of the same user does not overwrite the typed name, and Save sends it', async () => {
    const wrapper = await mountPage()

    wrapper.vm.form.first_name = 'Typed'
    wrapper.vm.form.last_name = 'Name'

    storeState.currentUser = serverUser()
    await flushPromises()

    await wrapper.vm.save()
    await flushPromises()

    expect(updateUserMock).toHaveBeenCalledWith('user-1', { first_name: 'Typed', last_name: 'Name' })
  })

  it('a different signed-in user still reloads the form', async () => {
    const wrapper = await mountPage()
    wrapper.vm.form.first_name = 'Typed'

    storeState.currentUser = serverUser({ id: 'user-2', first_name: 'Other', last_name: 'Person' })
    await flushPromises()

    expect(wrapper.vm.form.first_name).toBe('Other')
    expect(wrapper.vm.form.last_name).toBe('Person')
  })

  it('Reset still restores the stored values', async () => {
    const wrapper = await mountPage()
    wrapper.vm.form.first_name = 'Typed'

    wrapper.vm.reset()

    expect(wrapper.vm.form.first_name).toBe('Solo')
  })
})
