/**
 * FE-0027: browser page translation rewrites text nodes Vue owns and crashes the consent page;
 * the page opts out of translation.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ clientId: 'dcr-7f3a9c', get: vi.fn() }))

vi.mock('vue-router', () => ({
  useRoute: () => ({
    query: {
      client_id: h.clientId,
      redirect_uri: 'https://example.com/cb',
      response_type: 'code',
      scope: 'mcp:read',
      state: 's',
      code_challenge: 'c',
      code_challenge_method: 'S256',
    },
  }),
}))

vi.mock('@/services/api', () => ({
  apiClient: { get: (...a) => h.get(...a), post: vi.fn() },
  default: {},
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: { username: 'pat' },
    isAuthenticated: true,
    fetchCurrentUser: vi.fn(),
  }),
}))

vi.mock('@/services/configService', () => ({
  default: { fetchConfig: vi.fn().mockResolvedValue({}), getGiljoMode: vi.fn(() => 'ce') },
}))

import OAuthAuthorize from '@/views/OAuthAuthorize.vue'


describe('OAuthAuthorize.vue -- browser translation opt-out (FE-0027)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  it('marks the whole page as not translatable', async () => {
    h.get.mockResolvedValue({ data: { client_name: 'Acme Notes' } })
    const wrapper = mount(OAuthAuthorize, {
      global: { stubs: { AppAlert: { template: '<div><slot /></div>' } } },
    })
    await flushPromises()
    const root = wrapper.find('.oauth-container')
    expect(root.attributes('translate')).toBe('no')
    expect(root.classes()).toContain('notranslate')
    expect(wrapper.find('[data-testid="consent-client-name"]').element.closest('[translate="no"]')).not.toBeNull()
  })
})
