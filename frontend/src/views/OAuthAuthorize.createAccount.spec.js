import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ mode: 'saas', me: vi.fn() }))

const QUERY = {
  client_id: 'cid',
  redirect_uri: 'https://example.com/cb',
  response_type: 'code',
  scope: 'mcp:read',
  state: 's t',
  code_challenge: 'c',
  code_challenge_method: 'S256',
}

vi.mock('vue-router', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useRoute: () => ({
    query: QUERY,
    fullPath:
      '/oauth/authorize?client_id=cid&redirect_uri=https%3A%2F%2Fexample.com%2Fcb&response_type=code&scope=mcp%3Aread&state=s%20t&code_challenge=c&code_challenge_method=S256',
  }),
}))

vi.mock('@/services/api', () => ({
  default: { auth: { login: vi.fn(), me: (...a) => h.me(...a) } },
  apiClient: { get: vi.fn(() => Promise.resolve({ data: {} })), post: vi.fn() },
}))
vi.mock('@/sentry', () => ({ setSentryTenantKey: vi.fn() }))
vi.mock('@/config/api', () => ({ getRuntimeConfig: () => ({}) }))
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getGiljoMode: () => h.mode,
  },
}))

import OAuthAuthorize from './OAuthAuthorize.vue'

async function mountView({ expectSocial = false } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  h.me.mockRejectedValue({ response: { status: 401 } })
  const wrapper = mount(OAuthAuthorize, {
    global: {
      plugins: [pinia],
      stubs: {
        'v-form': { template: '<form @submit.prevent><slot /></form>' },
        AppAlert: { template: '<div class="app-alert"><slot /></div>' },
        RouterLink: {
          props: ['to'],
          template: '<a class="router-link" :href="to"><slot /></a>',
        },
      },
    },
  })
  await flushPromises()
  if (expectSocial) {
    await vi.waitFor(() => expect(wrapper.find('[data-testid="social-login-google"]').exists()).toBe(true))
  }
  return wrapper
}

describe('OAuthAuthorize signed-out Create account door', () => {
  beforeEach(() => {
    h.mode = 'saas'
  })

  it('SaaS: links to /register carrying the full OAuth URL in redirect', async () => {
    const wrapper = await mountView({ expectSocial: true })
    const link = wrapper.find('[data-testid="oauth-create-account"]')
    expect(link.exists()).toBe(true)
    const href = link.attributes('href')
    expect(href.startsWith('/register?redirect=')).toBe(true)
    const redirect = decodeURIComponent(href.slice('/register?redirect='.length))
    expect(redirect.startsWith('/oauth/authorize?client_id=cid')).toBe(true)
    expect(redirect).toContain('state=s%20t')
    expect(redirect).toContain('code_challenge_method=S256')
  })

  it('SaaS: renders the social sign-in component', async () => {
    const wrapper = await mountView({ expectSocial: true })
    expect(wrapper.find('[data-testid="social-login-google"]').exists()).toBe(true)
  })

  it('CE: no create-account link and no social component', async () => {
    h.mode = 'ce'
    const wrapper = await mountView()
    expect(wrapper.find('[data-testid="oauth-create-account"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="social-login-google"]').exists()).toBe(false)
  })
})
