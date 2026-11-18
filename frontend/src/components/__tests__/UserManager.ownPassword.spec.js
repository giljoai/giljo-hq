import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const updateUserMock = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    auth: {
      listUsers: () => Promise.resolve({ data: [] }),
      updateUser: (...args) => updateUserMock(...args),
    },
  },
}))
vi.mock('@/services/configService', () => ({ default: { getEdition: () => 'community' } }))
vi.mock('@/services/setupService', () => ({
  default: { checkEnhancedStatus: () => Promise.resolve({ mode: 'ce' }) },
}))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

const SELF = { id: 'user-self', username: 'solo', email: 'solo@example.com', role: 'admin' }
const OTHER = {
  id: 'user-other',
  username: 'member',
  email: 'member@example.com',
  role: 'developer',
}
vi.mock('@/stores/user', () => ({ useUserStore: () => ({ currentUser: SELF }) }))

async function openDialogFor(user) {
  const { default: UserManager } = await import('@/components/UserManager.vue')
  const wrapper = mount(UserManager)
  await flushPromises()
  wrapper.vm.openPasswordDialog(user)
  await flushPromises()
  return wrapper
}

describe('UserManager credentials dialog (SEC-0050, SEC-0060)', () => {
  beforeEach(() => updateUserMock.mockReset().mockResolvedValue({ data: {} }))

  it('sends your own row to the Profile page instead of offering password or PIN fields', async () => {
    const wrapper = await openDialogFor(SELF)

    expect(wrapper.find('input[label="New Password"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Save Password')
    expect(wrapper.find('input[label="New PIN (4 digits)"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Save PIN')
    expect(wrapper.text()).toContain('Profile')
  })

  it("still lets an admin set another user's PIN", async () => {
    const wrapper = await openDialogFor(OTHER)

    expect(wrapper.find('input[label="New PIN (4 digits)"]').exists()).toBe(true)
    wrapper.vm.newPin = '1234'
    wrapper.vm.confirmPin = '1234'
    await wrapper.vm.changePin()

    expect(updateUserMock).toHaveBeenCalledWith(OTHER.id, { recovery_pin: '1234' })
  })

  it("still lets an admin set another user's password", async () => {
    const wrapper = await openDialogFor(OTHER)

    expect(wrapper.find('input[label="New Password"]').exists()).toBe(true)
    wrapper.vm.newPassword = 'NewPassword2@'
    wrapper.vm.confirmPassword = 'NewPassword2@'
    await wrapper.vm.changePassword()

    expect(updateUserMock).toHaveBeenCalledWith(OTHER.id, { password: 'NewPassword2@' })
  })
})
