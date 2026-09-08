/**
 * Login.rateLimit.spec.js
 *
 * A throttled sign-in (HTTP 429 from the login rate limiter) rendered as
 * "Login failed. Please check your credentials." -- telling a user their
 * PASSWORD was wrong when the server was actually rate-limiting them, which
 * misleads anyone who reaches the limit through a shared NAT or a few
 * mistyped attempts.
 *
 * Root cause: userStore.login() swallows the axios error internally and returns a
 * bare boolean, discarding the response status. Login.vue's `if (!loginSuccess)`
 * branch therefore always shows the generic credentials message -- the carefully
 * status-branched `catch (err)` block below it (401/403/429/network) is DEAD CODE
 * for a login attempt, because login() never rethrows.
 *
 * Fix: userStore exposes the failed attempt's status via `lastLoginErrorStatus`;
 * Login.vue's `if (!loginSuccess)` branch reads it and shows the same 429 copy the
 * (already-correct) catch block uses for other failure paths, rather than a second
 * copy of the message living in two places.
 *
 * Edition scope: Both -- Login.vue is CE+SaaS shared.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  login: vi.fn(),
  me: vi.fn(),
  push: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push }),
  useRoute: () => ({ query: {} }),
}))

vi.mock('@/services/api', () => ({
  default: {
    auth: {
      login: (...a) => h.login(...a),
      me: (...a) => h.me(...a),
      checkFirstLogin: vi.fn().mockResolvedValue({ data: {} }),
    },
  },
  apiClient: {},
  setTenantKey: vi.fn(),
}))

vi.mock('@/sentry', () => ({
  setSentryTenantKey: vi.fn(),
}))

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getGiljoMode: vi.fn(() => 'ce'),
  },
}))

vi.mock('@/config/api', () => ({
  getRuntimeConfig: () => ({}),
}))

import Login from './Login.vue'

// The global `v-form` stub (tests/setup.js) is a bare `<form>` with no exposed
// `validate()` -- Login.vue's submit handler calls `loginForm.value.validate()`
// before doing anything else, so a local override supplying it is required (the
// same pattern tests/unit/views/CreateAdminAccount.spec.js already uses).
const formStub = {
  template: '<form @submit.prevent><slot /></form>',
  methods: { validate: () => Promise.resolve({ valid: true }) },
}

async function mountLogin() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(Login, {
    global: {
      plugins: [pinia],
      stubs: { 'v-form': formStub },
    },
  })
  await flushPromises()
  return wrapper
}

// The global `v-text-field` stub binds $attrs (including data-testid) straight
// onto the rendered `<input>` -- there is no wrapper element to look inside.
async function submitLogin(wrapper, { username = 'sam', password = 'hunter2' } = {}) {
  await wrapper.find('[data-testid="email-input"]').setValue(username)
  await wrapper.find('[data-testid="password-input"]').setValue(password)
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  await flushPromises()
}

describe('Login.vue — rate-limit copy on a 429', () => {
  beforeEach(() => {
    h.login.mockReset()
    h.me.mockReset()
    h.push.mockReset()
  })

  it('shows rate-limit copy, NOT the credentials message, when the server returns 429', async () => {
    h.login.mockRejectedValue({ response: { status: 429, data: {} } })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    const text = wrapper.text()
    expect(text).not.toContain('Please check your credentials')
    expect(text).toMatch(/too many (sign-in|login) attempts/i)
  })

  it('gives a 401 its own copy, never the rate-limit line (FE-9556 re-baseline)', async () => {
    // This test originally pinned that a 401 stayed on the generic
    // "check your credentials" copy -- deliberately scoping PR #1002 to 429
    // only and flagging the wider swallowed-error defect. FE-9556 is that
    // flag actioned: the store now rethrows and the catch block's 401 branch
    // is live, so the 401 assertion moves to its own copy. The invariant this
    // file exists for is unchanged: a 401 must never render rate-limit copy.
    h.login.mockRejectedValue({ response: { status: 401, data: {} } })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    expect(wrapper.text()).toContain('Invalid credentials')
    expect(wrapper.text()).not.toMatch(/too many (sign-in|login) attempts/i)
  })

  it('logs in successfully on a real 200, unaffected by the new branch', async () => {
    h.login.mockResolvedValue({ data: {} })
    h.me.mockResolvedValue({ data: { id: 'u1', tenant_key: 'tk1' } })
    const wrapper = await mountLogin()

    await submitLogin(wrapper)

    expect(wrapper.text()).not.toContain('Login failed')
    expect(wrapper.text()).not.toContain('too many')
  })
})
