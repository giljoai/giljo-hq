/**
 * AUTH-EMAIL Phase 4 frontend contract: the OAuth consent login identifier
 * field must indicate that either an email OR a username can be entered.
 * See the AUTH_EMAIL_USERNAME_DECISION record (Option A, Phase 4 copy
 * consolidation).
 *
 * Guard-rails:
 *   - Label reads "Email or username".
 *   - aria-label mirrors the label.
 *   - autocomplete stays "username" (browser hint accepts either value).
 *   - Exactly one identifier input, no new field.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRoute: () => ({
    query: {
      client_id: 'cid',
      redirect_uri: 'https://example.com/cb',
      response_type: 'code',
      scope: 'openid',
      state: 's',
      code_challenge: 'c',
      code_challenge_method: 'S256',
    },
  }),
}))

vi.mock('@/services/api', () => ({
  apiClient: { get: vi.fn(() => Promise.resolve({ data: {} })) },
  default: {},
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: null,
    isAuthenticated: false,
    login: vi.fn(() => Promise.resolve(true)),
    fetchCurrentUser: vi.fn(),
  }),
}))

import OAuthAuthorize from '@/views/OAuthAuthorize.vue'

describe('OAuthAuthorize.vue -- identifier field accepts email or username (AUTH-EMAIL Phase 4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  function mountOAuth() {
    return mount(OAuthAuthorize, {
      global: {
        stubs: {
          AppAlert: { template: '<div class="app-alert"><slot /></div>' },
        },
      },
    })
  }

  it('uses "Email or username" as the identifier field label', async () => {
    const wrapper = mountOAuth()
    await flushPromises()

    const html = wrapper.html()
    expect(html).toContain('Email or username')
    expect(html).not.toMatch(/label="Username"/)
    expect(html).not.toMatch(/aria-label="Username"/)
  })

  it('keeps autocomplete="username" on the identifier field', async () => {
    const wrapper = mountOAuth()
    await flushPromises()

    const el = wrapper.find('input[autocomplete="username"]')
    expect(el.exists()).toBe(true)
  })

  it('does not introduce a second identifier field', async () => {
    const wrapper = mountOAuth()
    await flushPromises()

    const inputs = wrapper.findAll('input[autocomplete="username"]')
    expect(inputs.length).toBe(1)
  })
})
