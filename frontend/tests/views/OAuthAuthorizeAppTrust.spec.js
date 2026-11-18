/**
 * SEC-0058: the consent screen says where the access goes, marks apps the server does not
 * vouch for, and describes every grantable permission in plain words.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  query: {},
  get: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: h.query, fullPath: '/oauth/authorize' }),
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

function setQuery(overrides = {}) {
  h.query = {
    client_id: '7c1f0d3e-2b51-4f7e-9a51-1f2d3c4b5a69',
    redirect_uri: 'https://attacker.example/cb',
    response_type: 'code',
    scope: 'mcp:read mcp:write mcp:agent',
    state: 's',
    code_challenge: 'c',
    code_challenge_method: 'S256',
    ...overrides,
  }
}

async function mountView() {
  const wrapper = mount(OAuthAuthorize, {
    global: { stubs: { AppAlert: { template: '<div><slot /></div>' } } },
  })
  await flushPromises()
  return wrapper
}

describe('OAuthAuthorize.vue -- where the access goes (SEC-0058)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    setQuery()
  })

  it('asks the server about this redirect and shows the host it vouches for', async () => {
    h.get.mockResolvedValue({
      data: { client_name: 'Claude', verified: false, redirect_host: 'attacker.example', redirect_is_local: false },
    })
    const wrapper = await mountView()
    expect(h.get).toHaveBeenCalledWith('/api/oauth/authorize/client', {
      params: { client_id: h.query.client_id, redirect_uri: 'https://attacker.example/cb' },
    })
    expect(wrapper.find('[data-testid="consent-redirect-host"]').text()).toContain('attacker.example')
  })

  it('marks a self-registered app as unverified, with a caution line', async () => {
    h.get.mockResolvedValue({
      data: { client_name: 'Claude', verified: false, redirect_host: 'attacker.example', redirect_is_local: false },
    })
    const wrapper = await mountView()
    const mark = wrapper.find('[data-testid="consent-unverified-mark"]')
    expect(mark.exists()).toBe(true)
    expect(mark.text()).toMatch(/unverified/i)
    expect(wrapper.find('[data-testid="consent-unverified-caution"]').text()).toContain('attacker.example')
  })

  it('shows a known app as known and without the unverified mark', async () => {
    h.get.mockResolvedValue({
      data: { client_name: 'Claude', verified: true, redirect_host: 'claude.ai', redirect_is_local: false },
    })
    const wrapper = await mountView()
    expect(wrapper.find('[data-testid="consent-unverified-mark"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="consent-known-mark"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="consent-redirect-host"]').text()).toContain('claude.ai')
  })

  it('says "an app on this computer" for a loopback redirect', async () => {
    setQuery({ client_id: 'giljo-mcp-default', redirect_uri: 'http://127.0.0.1:5173/callback' })
    h.get.mockResolvedValue({
      data: { client_name: 'Giljo HQ (built-in)', verified: true, redirect_host: '127.0.0.1', redirect_is_local: true },
    })
    const wrapper = await mountView()
    expect(wrapper.find('[data-testid="consent-redirect-host"]').text()).toContain('an app on this computer')
  })

  it('treats a failed lookup as unverified and still shows the host from the request', async () => {
    h.get.mockRejectedValue(new Error('404'))
    const wrapper = await mountView()
    expect(wrapper.find('[data-testid="consent-unverified-mark"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="consent-redirect-host"]').text()).toContain('attacker.example')
  })

  it('when the server will not name the host, shows where the browser would really go', async () => {
    h.get.mockRejectedValue(new Error('400'))
    setQuery({ redirect_uri: 'https://attacker.example\\@claude.ai/cb' })
    let wrapper = await mountView()
    expect(wrapper.find('[data-testid="consent-redirect-host"]').text()).toContain('attacker.example')
    expect(wrapper.find('[data-testid="consent-redirect-host"]').text()).not.toContain('claude.ai')

    setQuery({ redirect_uri: 'https://\u0441laude.ai/cb' })
    wrapper = await mountView()
    expect(wrapper.find('[data-testid="consent-redirect-host"]').text()).toContain('xn--laude-0ye.ai')
    expect(wrapper.find('[data-testid="consent-unverified-mark"]').exists()).toBe(true)
  })

  it('shows the address the app was published from when it differs from the redirect host', async () => {
    setQuery({ client_id: 'https://lookalike.example/client.json' })
    h.get.mockResolvedValue({
      data: {
        client_name: 'Claude',
        verified: false,
        redirect_host: 'attacker.example',
        redirect_is_local: false,
        client_id_host: 'lookalike.example',
      },
    })
    const wrapper = await mountView()
    expect(wrapper.find('[data-testid="consent-client-host"]').text()).toContain('lookalike.example')
  })
})

describe('OAuthAuthorize.vue -- link-forwarding warning and known-site wording (SEC-0058)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    setQuery()
  })

  const STARTED = 'Only allow this if you just started connecting this app yourself. If someone sent you this link, close this page.'

  it.each([
    ['a known app site', { verified: true, redirect_host: 'chatgpt.com' }],
    ['an unverified app', { verified: false, redirect_host: 'attacker.example' }],
    ['an app on this computer', { verified: false, redirect_host: '127.0.0.1', redirect_is_local: true }],
  ])('shows the started-it-yourself line for %s', async (_label, record) => {
    h.get.mockResolvedValue({ data: { client_name: 'ChatGPT', redirect_is_local: false, ...record } })
    const wrapper = await mountView()
    expect(wrapper.find('[data-testid="consent-started-yourself"]').text().replace(/\s+/g, ' ')).toBe(STARTED)
  })

  it('labels a known app as a known app site, not as an app Giljo HQ vouches for', async () => {
    h.get.mockResolvedValue({ data: { client_name: 'ChatGPT', verified: true, redirect_host: 'chatgpt.com' } })
    const wrapper = await mountView()
    expect(wrapper.find('[data-testid="consent-known-mark"]').text()).toMatch(/Known app site$/)
  })
})

// Operator ruling 2026-11-10: a redirect to the user's own computer gets a neutral tag and no
// caution box; every other unknown destination keeps the orange tag and the box.
describe('OAuthAuthorize.vue -- one tag per destination kind (SEC-0058)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  function marks(wrapper) {
    return {
      local: wrapper.find('[data-testid="consent-local-mark"]'),
      known: wrapper.find('[data-testid="consent-known-mark"]'),
      unverified: wrapper.find('[data-testid="consent-unverified-mark"]'),
      caution: wrapper.find('[data-testid="consent-unverified-caution"]'),
      started: wrapper.find('[data-testid="consent-started-yourself"]'),
    }
  }

  it.each([
    ['a self-registered local app', 'dcr-local', { client_name: 'Claude Code', verified: false }],
    ['the built-in client on a local install', 'giljo-mcp-default', { client_name: 'Giljo HQ (built-in)', verified: true }],
    ['a local app published on a known site', 'https://claude.ai/oauth/claude-code-client-metadata', { client_name: 'Claude Code', verified: true }],
  ])('shows only the neutral "App on this computer" tag for %s', async (_label, clientId, record) => {
    setQuery({ client_id: clientId, redirect_uri: 'http://127.0.0.1:33418/callback' })
    h.get.mockResolvedValue({ data: { ...record, redirect_host: '127.0.0.1', redirect_is_local: true } })
    const m = marks(await mountView())
    expect(m.local.exists()).toBe(true)
    expect(m.local.text()).toMatch(/App on this computer$/)
    expect(m.unverified.exists()).toBe(false)
    expect(m.known.exists()).toBe(false)
    expect(m.caution.exists()).toBe(false)
    expect(m.started.exists()).toBe(true)
  })

  it('a failed lookup for a loopback redirect is still the neutral local tag', async () => {
    setQuery({ client_id: 'dcr-local', redirect_uri: 'http://localhost:5173/callback' })
    h.get.mockRejectedValue(new Error('404'))
    const m = marks(await mountView())
    expect(m.local.exists()).toBe(true)
    expect(m.caution.exists()).toBe(false)
  })

  it('a look-alike website still shows the orange tag and the caution box', async () => {
    setQuery()
    h.get.mockResolvedValue({
      data: { client_name: 'Claude', verified: false, redirect_host: 'claude-connect.app', redirect_is_local: false },
    })
    const m = marks(await mountView())
    expect(m.unverified.exists()).toBe(true)
    expect(m.caution.exists()).toBe(true)
    expect(m.local.exists()).toBe(false)
    expect(m.known.exists()).toBe(false)
  })

  it('a known site still shows the green tag only', async () => {
    setQuery()
    h.get.mockResolvedValue({
      data: { client_name: 'ChatGPT', verified: true, redirect_host: 'chatgpt.com', redirect_is_local: false },
    })
    const m = marks(await mountView())
    expect(m.known.exists()).toBe(true)
    expect(m.unverified.exists()).toBe(false)
    expect(m.caution.exists()).toBe(false)
    expect(m.local.exists()).toBe(false)
  })
})

describe('OAuthAuthorize.vue -- every grantable permission in plain words (SEC-0058)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    setQuery()
    h.get.mockResolvedValue({ data: { client_name: 'Claude', verified: true, redirect_host: 'claude.ai' } })
  })

  it('describes mcp:agent instead of falling back to the raw scope string', async () => {
    const wrapper = await mountView()
    const text = wrapper.text()
    expect(text).not.toContain('Access: mcp:agent')
    expect(text).not.toMatch(/^\s*mcp:agent\s*$/m)
    expect(text).toMatch(/agents/i)
  })
})
