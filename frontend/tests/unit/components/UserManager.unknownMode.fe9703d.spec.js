/**
 * When the edition cannot be read, the CE-only password and PIN action must
 * not appear: unknown is not CE.
 *
 * Edition scope: Both
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'

vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('@/services/api', () => ({
  default: { auth: { listUsers: vi.fn().mockResolvedValue({ data: [] }), register: vi.fn(), updateUser: vi.fn() } },
}))
vi.mock('@/services/configService', () => ({
  default: { getEdition: () => 'community', fetchConfig: vi.fn().mockResolvedValue({}) },
}))
vi.mock('@/services/setupService', () => ({
  default: {
    checkEnhancedStatus: vi.fn(() =>
      Promise.resolve({ is_fresh_install: false, requires_admin_creation: false, transient_failure: true }),
    ),
  },
}))
vi.mock('@/composables/useApiUrl', () => ({ getApiBaseUrl: vi.fn(() => '') }))

import UserManager from '@/components/UserManager.vue'

describe('UserManager: a status reply with no mode', () => {
  it('hides the CE-only password and PIN action', async () => {
    const wrapper = mount(UserManager, {
      global: {
        plugins: [
          createTestingPinia({
            initialState: { user: { currentUser: { id: 1, username: 'admin', role: 'admin', tenant_key: 'tk' } } },
          }),
        ],
      },
    })
    await flushPromises()

    expect(wrapper.vm.isCe).toBe(false)
    expect(wrapper.vm.showPasswordPinAction).toBe(false)
  })
})
