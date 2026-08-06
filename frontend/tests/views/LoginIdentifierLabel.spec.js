/**
 * AUTH-EMAIL frontend contract: the login identifier field must indicate that
 * either a username OR an email can be entered. See the
 * AUTH_EMAIL_USERNAME_DECISION record (Option A, decision commit
 * af53e62b). The backend performs dual-lookup; the frontend only updates copy.
 *
 * Guard-rails:
 *   - Label reads "Email or username" (not just "Username").
 *   - Placeholder gives the same hint.
 *   - autocomplete stays "username" (browser hint accepts either value).
 *   - No extra field, no new endpoint, no validation change.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

let mockGiljoMode = 'ce'
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn(() => Promise.resolve()),
    getGiljoMode: vi.fn(() => mockGiljoMode),
    config: null,
  },
}))

const mockPush = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
  useRoute: () => ({ query: {} }),
}))

vi.mock('@/config/api', () => ({
  getRuntimeConfig: vi.fn(() => null),
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: null,
    login: vi.fn(() => Promise.resolve(true)),
    fetchCurrentUser: vi.fn(),
  }),
}))

import Login from '@/views/Login.vue'

describe('Login.vue -- identifier field accepts username or email (AUTH-EMAIL)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    mockGiljoMode = 'ce'
  })

  function mountLogin() {
    return mount(Login, {
      global: {
        stubs: {
          'router-link': {
            props: ['to'],
            template: '<a :href="to"><slot /></a>',
          },
          ForgotPasswordPin: { template: '<div class="forgot-pin-stub" />' },
          AppAlert: { template: '<div class="app-alert"><slot /></div>' },
        },
      },
    })
  }

  it('uses "Email or username" as the identifier field label', async () => {
    const wrapper = mountLogin()
    await flushPromises()

    const identifierField = wrapper.find('[data-testid="email-input"]')
    expect(identifierField.exists()).toBe(true)
    // Vuetify renders the label attribute onto the input wrapper
    const html = wrapper.html()
    expect(html).toContain('Email or username')
    // Old label must be gone as a standalone string
    expect(html).not.toMatch(/label="Username"/)
    expect(html).not.toContain('Username or email')
  })

  it('keeps autocomplete="username" on the identifier field', async () => {
    const wrapper = mountLogin()
    await flushPromises()

    const input = wrapper.find('input[data-testid="email-input"], [data-testid="email-input"] input')
    // Vuetify wraps the native input; grab whichever exists
    const el = input.exists() ? input : wrapper.find('input[autocomplete="username"]')
    expect(el.exists()).toBe(true)
    expect(el.attributes('autocomplete')).toBe('username')
  })

  it('does not introduce a second identifier field', async () => {
    const wrapper = mountLogin()
    await flushPromises()

    // Still exactly one username-autocomplete input
    const inputs = wrapper.findAll('input[autocomplete="username"]')
    expect(inputs.length).toBe(1)
  })
})
