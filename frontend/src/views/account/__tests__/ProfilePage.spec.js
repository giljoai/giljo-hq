import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'


const changePasswordMock = vi.fn()
const updateUserMock = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    auth: {
      changePassword: (...args) => changePasswordMock(...args),
      updateUser: (...args) => updateUserMock(...args),
    },
  },
}))

const showToastMock = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

const routerPushMock = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPushMock }),
}))

const modeRef = { value: 'ce' }
vi.mock('@/services/setupService', () => ({
  default: {
    checkEnhancedStatus: () => Promise.resolve({ mode: modeRef.value }),
  },
}))

const logoutMock = vi.fn()
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: {
      id: 'user-1',
      username: 'solo',
      first_name: 'Solo',
      last_name: 'Admin',
      email: 'solo@example.com',
      role: 'admin',
    },
    currentOrg: { name: 'My Workspace' },
    orgRole: 'owner',
    logout: logoutMock,
  }),
}))


async function mountPage() {
  setActivePinia(createPinia())
  const { default: ProfilePage } = await import('@/views/account/ProfilePage.vue')
  const wrapper = mount(ProfilePage, {
    global: {
      stubs: {
        RoleBadge: { template: '<span class="role-badge-stub" />' },
        'v-card': { template: '<div><slot /></div>' },
        'v-card-text': { template: '<div><slot /></div>' },
        'v-form': { template: '<form @submit="$emit(\'submit\', $event)"><slot /></form>' },
        'v-text-field': { template: '<div><slot /></div>' },
        'v-btn': {
          template:
            '<button class="v-btn-stub" :disabled="disabled || loading" @click="$emit(\'click\', $event)"><slot /></button>',
          props: ['disabled', 'loading', 'color', 'variant', 'type'],
          emits: ['click'],
        },
        'v-alert': { template: '<div class="v-alert-stub"><slot /></div>' },
        'v-divider': { template: '<hr />' },
        'v-icon': { template: '<i><slot /></i>' },
        'v-spacer': { template: '<span />' },
      },
    },
  })
  await flushPromises()
  return wrapper
}


describe('ProfilePage — self-service password & PIN (IMP-5042)', () => {
  beforeEach(() => {
    modeRef.value = 'ce'
    changePasswordMock.mockReset()
    updateUserMock.mockReset()
    showToastMock.mockClear()
    routerPushMock.mockClear()
    logoutMock.mockClear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the password-change form in every edition', async () => {
    const wrapper = await mountPage()
    expect(wrapper.find('[data-test="security-card"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="current-password"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="new-password"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="change-password-btn"]').exists()).toBe(true)
  })

  it('renders the recovery-PIN form in CE', async () => {
    modeRef.value = 'ce'
    const wrapper = await mountPage()
    expect(wrapper.find('[data-test="new-pin"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="change-pin-btn"]').exists()).toBe(true)
  })

  it('hides the recovery-PIN form in SaaS', async () => {
    modeRef.value = 'saas'
    const wrapper = await mountPage()
    expect(wrapper.find('[data-test="security-card"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="new-pin"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="change-pin-btn"]').exists()).toBe(false)
  })

  it('changes password then signs out and redirects to /login', async () => {
    changePasswordMock.mockResolvedValue({ data: { message: 'ok' } })
    const wrapper = await mountPage()

    wrapper.vm.pwForm.current = 'OldPass123'
    wrapper.vm.pwForm.next = 'NewPass456'
    wrapper.vm.pwForm.confirm = 'NewPass456'
    await wrapper.vm.changePassword()
    await flushPromises()

    expect(changePasswordMock).toHaveBeenCalledTimes(1)
    expect(changePasswordMock).toHaveBeenCalledWith('user-1', {
      old_password: 'OldPass123',
      new_password: 'NewPass456',
    })
    expect(logoutMock).toHaveBeenCalledTimes(1)
    expect(routerPushMock).toHaveBeenCalledWith('/login')
  })

  it('surfaces a friendly error when the current password is wrong (401)', async () => {
    changePasswordMock.mockRejectedValue({ response: { status: 401 } })
    const wrapper = await mountPage()

    wrapper.vm.pwForm.current = 'WrongPass1'
    wrapper.vm.pwForm.next = 'NewPass456'
    wrapper.vm.pwForm.confirm = 'NewPass456'
    await wrapper.vm.changePassword()
    await flushPromises()

    expect(wrapper.vm.pwError).toMatch(/incorrect/i)
    expect(logoutMock).not.toHaveBeenCalled()
    expect(routerPushMock).not.toHaveBeenCalled()
  })

  it('sets the recovery PIN via updateUser({ recovery_pin })', async () => {
    updateUserMock.mockResolvedValue({ data: {} })
    const wrapper = await mountPage()

    wrapper.vm.pinForm.next = '1234'
    wrapper.vm.pinForm.confirm = '1234'
    await wrapper.vm.changePin()
    await flushPromises()

    expect(updateUserMock).toHaveBeenCalledTimes(1)
    expect(updateUserMock).toHaveBeenCalledWith('user-1', { recovery_pin: '1234' })
  })
})
