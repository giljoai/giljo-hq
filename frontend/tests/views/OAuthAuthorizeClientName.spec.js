/**
 * FE-9850: the consent screen names the app by its registered name, not the client id.
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

async function mountView() {
  const wrapper = mount(OAuthAuthorize, {
    global: { stubs: { AppAlert: { template: '<div><slot /></div>' } } },
  })
  await flushPromises()
  return wrapper
}

function nameText(wrapper) {
  return wrapper.find('[data-testid="consent-client-name"]').text()
}

describe('OAuthAuthorize.vue -- registered app name (FE-9850)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    h.clientId = 'dcr-7f3a9c'
  })

  it('shows the registered name returned by the server, not the client id', async () => {
    h.get.mockResolvedValue({ data: { client_id: 'dcr-7f3a9c', client_name: 'Acme Notes' } })
    const wrapper = await mountView()
    expect(h.get).toHaveBeenCalledWith('/api/oauth/authorize/client', { params: { client_id: 'dcr-7f3a9c' } })
    expect(nameText(wrapper)).toBe('Acme Notes')
    expect(wrapper.text()).not.toContain('dcr-7f3a9c')
  })

  it('renders a name containing markup as plain text', async () => {
    h.get.mockResolvedValue({ data: { client_name: '<img src=x onerror=alert(1)>Evil' } })
    const wrapper = await mountView()
    expect(wrapper.find('[data-testid="consent-client-name"] img').exists()).toBe(false)
    expect(nameText(wrapper)).toContain('<img src=x')
  })

  it('caps a very long name at 80 characters with an ellipsis', async () => {
    h.get.mockResolvedValue({ data: { client_name: 'A'.repeat(300) } })
    const wrapper = await mountView()
    const text = nameText(wrapper)
    expect(text.length).toBe(80)
    expect(text.endsWith('…')).toBe(true)
  })

  it('falls back to the client id when the lookup fails', async () => {
    h.get.mockRejectedValue(new Error('404'))
    const wrapper = await mountView()
    expect(nameText(wrapper)).toBe('dcr-7f3a9c')
  })

  it('keeps the built-in client label without a lookup', async () => {
    h.clientId = 'giljo-mcp-default'
    const wrapper = await mountView()
    expect(nameText(wrapper)).toContain('Client')
    expect(h.get).not.toHaveBeenCalled()
  })
})
