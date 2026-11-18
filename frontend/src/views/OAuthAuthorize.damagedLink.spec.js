import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ me: vi.fn(), post: vi.fn(), query: {} }))

vi.mock('vue-router', () => ({ useRoute: () => ({ query: h.query, fullPath: '/oauth/authorize' }) }))
vi.mock('@/services/api', () => ({
  default: { auth: { me: (...a) => h.me(...a) } },
  apiClient: { get: vi.fn(() => Promise.resolve({ data: {} })), post: (...a) => h.post(...a) },
}))
vi.mock('@/sentry', () => ({ setSentryTenantKey: vi.fn() }))
vi.mock('@/services/configService', () => ({
  default: { fetchConfig: vi.fn().mockResolvedValue({}), getGiljoMode: vi.fn(() => 'ce') },
}))
vi.mock('@/config/api', () => ({ getRuntimeConfig: () => ({}) }))

import OAuthAuthorize from './OAuthAuthorize.vue'

const LINE_ONE = 'This sign-in link is damaged. Go back to your AI tool and copy the link again.'
const LINE_TWO =
  'Tip: let your tool copy it for you. A link copied by hand from a terminal can break at the line end.'

const GOOD_QUERY = {
  client_id: 'cid',
  redirect_uri: 'http://localhost:3000/cb',
  response_type: 'code',
  scope: 'mcp:read',
  state: 's',
  code_challenge: 'abc',
  code_challenge_method: 'S256',
}

async function mountView(query, { authed = true } = {}) {
  h.query = query
  const pinia = createPinia()
  setActivePinia(pinia)
  if (authed) h.me.mockResolvedValue({ data: { id: 'u1', username: 'sam' } })
  else h.me.mockRejectedValue({ response: { status: 401 } })
  const wrapper = mount(OAuthAuthorize, {
    global: {
      plugins: [pinia],
      stubs: { AppAlert: { template: '<div class="app-alert"><slot /></div>' } },
    },
  })
  await flushPromises()
  return wrapper
}

const authorizeBtn = (w) => w.findAll('button').find((b) => b.text().includes('Authorize'))

describe('OAuthAuthorize.vue: damaged sign-in link', () => {
  beforeEach(() => {
    h.me.mockReset()
    h.post.mockReset()
  })

  it('a known-good query shows the consent screen and no damaged-link message', async () => {
    const w = await mountView({ ...GOOD_QUERY })
    expect(w.text()).not.toContain(LINE_ONE)
    expect(authorizeBtn(w)).toBeDefined()
  })

  it.each([
    ['method name cut (absent)', (q) => { delete q.code_challenge_method }],
    ['method value cut', (q) => { q.code_challenge_method = 'S25  6' }],
    ['method not S256', (q) => { q.code_challenge_method = 'plain' }],
    ['parameter name contains whitespace', (q) => { q['code_challenge_  method'] = 'S256' }],
    ['challenge missing', (q) => { delete q.code_challenge }],
  ])('on load: %s shows both lines and offers no Authorize', async (_n, damage) => {
    const q = { ...GOOD_QUERY }
    damage(q)
    const w = await mountView(q)
    expect(w.text()).toContain(LINE_ONE)
    expect(w.text()).toContain(LINE_TWO)
    expect(authorizeBtn(w)).toBeUndefined()
    expect(h.post).not.toHaveBeenCalled()
  })

  it('on load: a damaged link is also flagged before sign-in', async () => {
    const w = await mountView({ ...GOOD_QUERY, code_challenge_method: '' }, { authed: false })
    expect(w.text()).toContain(LINE_ONE)
    expect(w.find('input[type="password"]').exists()).toBe(false)
  })

  it('the request is never repaired: the damaged value is not sent trimmed', async () => {
    const w = await mountView({ ...GOOD_QUERY, code_challenge_method: ' S256' })
    expect(w.text()).toContain(LINE_ONE)
    expect(h.post).not.toHaveBeenCalled()
  })

  it('server refusal with the stable code shows both lines (decided by the code, not the text)', async () => {
    h.post.mockRejectedValue({
      response: { status: 400, data: { error_code: 'AUTHORIZE_REQUEST_MALFORMED', message: 'zzz anything' } },
    })
    const w = await mountView({ ...GOOD_QUERY })
    await authorizeBtn(w).trigger('click')
    await flushPromises()
    expect(w.text()).toContain(LINE_ONE)
    expect(w.text()).toContain(LINE_TWO)
    expect(w.text()).not.toContain('Authorization failed. Please try again.')
    expect(authorizeBtn(w)).toBeUndefined()
  })

  it('the English refusal text without the code is NOT treated as damaged', async () => {
    h.post.mockRejectedValue({
      response: { status: 400, data: { error_code: 'HTTP_ERROR', message: 'Invalid authorization request parameters.' } },
    })
    const w = await mountView({ ...GOOD_QUERY })
    await authorizeBtn(w).trigger('click')
    await flushPromises()
    expect(w.text()).not.toContain(LINE_ONE)
    expect(w.text()).toContain('Authorization failed. Please try again.')
  })
})
