import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  login: vi.fn(),
  me: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push, replace: h.replace }),
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

const formStub = {
  template: '<form @submit.prevent><slot /></form>',
  methods: { validate: () => Promise.resolve({ valid: true }) },
}

const textFieldStub = {
  props: ['modelValue'],
  emits: ['update:modelValue'],
  inheritAttrs: false,
  template:
    '<input v-bind="$attrs" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

async function mountLogin() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(Login, {
    global: {
      plugins: [pinia],
      stubs: { 'v-form': formStub, 'v-text-field': textFieldStub },
    },
  })
  await flushPromises()
  return wrapper
}

async function submitLogin(wrapper, { username = 'sam', password = 'hunter2' } = {}) {
  await wrapper.find('[data-testid="email-input"]').setValue(username)
  await wrapper.find('[data-testid="password-input"]').setValue(password)
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  await flushPromises()
}


const LOCKED_MESSAGE = 'Too many failed login attempts. Your account is temporarily locked.'

function throttled(seconds, message = 'Too many requests. Limit: 5 per 60 seconds. Try again later.') {
  const headers = seconds === null ? {} : { 'retry-after': String(seconds) }
  return { response: { status: 429, headers, data: { error_code: 'HTTP_ERROR', message } } }
}

function signInButton(wrapper) {
  return wrapper.find('[data-testid="login-button"]')
}

async function retypePassword(wrapper) {
  await wrapper.find('[data-testid="password-input"]').setValue('hunter2')
}

describe('Login.vue: wait on a 429, never re-send the password by itself (FE-0068)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
    h.login.mockReset()
    h.me.mockReset()
    h.push.mockReset()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('429 with Retry-After shows the countdown and disables the button until it ends', async () => {
    h.login.mockRejectedValue(throttled(30))
    const wrapper = await mountLogin()
    await submitLogin(wrapper)
    await retypePassword(wrapper)

    expect(wrapper.find('[data-testid="signin-wait"]').text()).toMatch(/30 seconds/)
    expect(signInButton(wrapper).attributes('disabled')).toBeDefined()

    await vi.advanceTimersByTimeAsync(10000)
    expect(wrapper.find('[data-testid="signin-wait"]').text()).toMatch(/20 seconds/)
    expect(signInButton(wrapper).attributes('disabled')).toBeDefined()

    await vi.advanceTimersByTimeAsync(20000)
    expect(wrapper.find('[data-testid="signin-wait"]').exists()).toBe(false)
    expect(signInButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('announces the wait politely to assistive technology', async () => {
    h.login.mockRejectedValue(throttled(30))
    const wrapper = await mountLogin()
    await submitLogin(wrapper)

    const live = wrapper.find('[aria-live="polite"]')
    expect(live.exists()).toBe(true)
    expect(live.text()).toMatch(/30 seconds/)
  })

  it('sends the sign-in POST exactly once across the whole countdown', async () => {
    h.login.mockRejectedValue(throttled(5))
    const wrapper = await mountLogin()
    await submitLogin(wrapper)

    await vi.advanceTimersByTimeAsync(120000)

    expect(h.login).toHaveBeenCalledTimes(1)
  })

  it('a second press after the countdown sends the POST again (the person acts)', async () => {
    h.login.mockRejectedValueOnce(throttled(3)).mockResolvedValue({ data: {} })
    h.me.mockResolvedValue({ data: { id: 'u1', tenant_key: 'tk1' } })
    const wrapper = await mountLogin()
    await submitLogin(wrapper)
    await vi.advanceTimersByTimeAsync(3000)
    await retypePassword(wrapper)
    await wrapper.find('form').trigger('submit')
    await vi.advanceTimersByTimeAsync(1000)

    expect(h.login).toHaveBeenCalledTimes(2)
  })

  it('a 429 without Retry-After falls back to a fixed wait', async () => {
    h.login.mockRejectedValue(throttled(null))
    const wrapper = await mountLogin()
    await submitLogin(wrapper)
    await retypePassword(wrapper)

    expect(wrapper.find('[data-testid="signin-wait"]').text()).toMatch(/a minute/)
    expect(signInButton(wrapper).attributes('disabled')).toBeDefined()
    await vi.advanceTimersByTimeAsync(60000)
    expect(signInButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('Enter during the wait does not send the sign-in', async () => {
    h.login.mockRejectedValue(throttled(30))
    const wrapper = await mountLogin()
    await submitLogin(wrapper)
    await retypePassword(wrapper)
    await wrapper.find('[data-testid="password-input"]').trigger('keyup.enter')
    await wrapper.find('form').trigger('submit')
    await vi.advanceTimersByTimeAsync(1000)

    expect(h.login).toHaveBeenCalledTimes(1)
  })

  it('a locked account keeps its existing message: no countdown, button not held', async () => {
    h.login.mockRejectedValue(throttled(900, LOCKED_MESSAGE))
    const wrapper = await mountLogin()
    await submitLogin(wrapper)
    expect(wrapper.text()).toContain('Too many sign-in attempts. Please wait a minute and try again.')
    await retypePassword(wrapper)

    expect(wrapper.find('[data-testid="signin-wait"]').exists()).toBe(false)
    expect(signInButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('the generic ACCOUNT_LOCKED answer is a locked account: field emptied, no countdown', async () => {
    h.login.mockRejectedValue({
      response: {
        status: 429,
        headers: { 'retry-after': '900' },
        data: {
          error_code: 'ACCOUNT_LOCKED',
          message: 'Account locked out due to too many failed attempts. Try again in 15 minutes.',
        },
      },
    })
    const wrapper = await mountLogin()
    await submitLogin(wrapper)

    expect(wrapper.find('[data-testid="signin-wait"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Too many sign-in attempts. Please wait a minute and try again.')
    expect(wrapper.find('[data-testid="password-input"]').element.value).toBe('')
  })

  it('a wrong password keeps its existing message: no countdown, button not held', async () => {
    h.login.mockRejectedValue({ response: { status: 401, headers: {}, data: {} } })
    const wrapper = await mountLogin()
    await submitLogin(wrapper)
    expect(wrapper.text()).toContain('Invalid credentials')
    await retypePassword(wrapper)

    expect(signInButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('a normal sign-in is unchanged: one POST, no wait', async () => {
    h.login.mockResolvedValue({ data: {} })
    h.me.mockResolvedValue({ data: { id: 'u1', tenant_key: 'tk1' } })
    const wrapper = await mountLogin()
    await submitLogin(wrapper)
    await vi.advanceTimersByTimeAsync(1000)

    expect(h.login).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="signin-wait"]').exists()).toBe(false)
  })
})

describe('Login.vue: the typed password is kept during a 429 wait, inside three limits (FE-0068)', () => {
  const passwordValue = (wrapper) => wrapper.find('[data-testid="password-input"]').element.value

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
    h.login.mockReset()
    h.me.mockReset()
    h.push.mockReset()
    h.replace.mockReset()
    sessionStorage.clear()
    localStorage.setItem.mockClear()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('limit 1: the 429 wait keeps the password; a wrong password and a locked account still empty it', async () => {
    h.login.mockRejectedValue(throttled(30))
    const waiting = await mountLogin()
    await submitLogin(waiting)
    expect(waiting.find('[data-testid="signin-wait"]').exists()).toBe(true)
    expect(passwordValue(waiting)).toBe('hunter2')

    h.login.mockRejectedValue({ response: { status: 401, headers: {}, data: {} } })
    const wrong = await mountLogin()
    await submitLogin(wrong)
    expect(passwordValue(wrong)).toBe('')

    h.login.mockRejectedValue(throttled(900, LOCKED_MESSAGE))
    const locked = await mountLogin()
    await submitLogin(locked)
    expect(passwordValue(locked)).toBe('')
  })

  it('limit 2: the value lives only in the input: no storage, no log line, no extra holder', async () => {
    const logs = ['log', 'info', 'warn', 'error', 'debug'].map((m) => vi.spyOn(console, m))
    h.login.mockRejectedValue(throttled(30))
    const wrapper = await mountLogin()
    await submitLogin(wrapper)
    await vi.advanceTimersByTimeAsync(5000)

    expect(passwordValue(wrapper)).toBe('hunter2')
    expect(JSON.stringify(localStorage.setItem.mock.calls)).not.toContain('hunter2')
    expect(JSON.stringify({ ...sessionStorage })).not.toContain('hunter2')
    expect(JSON.stringify([h.push.mock.calls, h.replace.mock.calls])).not.toContain('hunter2')
    for (const spy of logs) {
      expect(JSON.stringify(spy.mock.calls)).not.toContain('hunter2')
    }
    const holders = Object.entries(wrapper.vm.$.setupState).filter(
      ([key, value]) => key !== 'password' && value === 'hunter2',
    )
    expect(holders).toEqual([])
  })

  it('limit 3: leaving the page clears the value', async () => {
    h.login.mockRejectedValue(throttled(30))
    const wrapper = await mountLogin()
    await submitLogin(wrapper)
    const state = wrapper.vm.$.setupState
    expect(state.password).toBe('hunter2')

    wrapper.unmount()

    expect(state.password).toBe('')
  })

  it('limit 3: a later answer saying the account is locked clears the value', async () => {
    h.login.mockRejectedValueOnce(throttled(3)).mockRejectedValueOnce(throttled(900, LOCKED_MESSAGE))
    const wrapper = await mountLogin()
    await submitLogin(wrapper)
    await vi.advanceTimersByTimeAsync(3000)
    expect(passwordValue(wrapper)).toBe('hunter2')
    await wrapper.find('form').trigger('submit')
    await vi.advanceTimersByTimeAsync(100)

    expect(passwordValue(wrapper)).toBe('')
  })

  it('after the wait one press sends the kept password exactly once; Enter during the wait sends nothing', async () => {
    h.login.mockRejectedValueOnce(throttled(30)).mockResolvedValue({ data: {} })
    h.me.mockResolvedValue({ data: { id: 'u1', tenant_key: 'tk1' } })
    const wrapper = await mountLogin()
    await submitLogin(wrapper)
    await wrapper.find('[data-testid="password-input"]').trigger('keyup.enter')
    await wrapper.find('form').trigger('submit')
    await vi.advanceTimersByTimeAsync(29000)
    expect(h.login).toHaveBeenCalledTimes(1)
    expect(signInButton(wrapper).attributes('disabled')).toBeDefined()

    await vi.advanceTimersByTimeAsync(1000)
    expect(signInButton(wrapper).attributes('disabled')).toBeUndefined()
    await wrapper.find('form').trigger('submit')
    await vi.advanceTimersByTimeAsync(1000)

    expect(h.login).toHaveBeenCalledTimes(2)
    expect(h.login).toHaveBeenLastCalledWith('sam', 'hunter2')
  })

  it('during the wait the password rule has nothing to flag', async () => {
    h.login.mockRejectedValue(throttled(30))
    const wrapper = await mountLogin()
    await submitLogin(wrapper)

    expect(wrapper.vm.$.setupState.rules.password(wrapper.vm.$.setupState.password)).toBe(true)
  })
})
