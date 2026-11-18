import { describe, it, expect } from 'vitest'
import { isAccountLocked429 } from './signInWait'

const answer = (data) => ({ response: { status: 429, headers: { 'retry-after': '900' }, data } })

describe('isAccountLocked429', () => {
  it('is true for the generic handler body with error_code ACCOUNT_LOCKED', () => {
    expect(
      isAccountLocked429(
        answer({
          error_code: 'ACCOUNT_LOCKED',
          message: 'Account locked out due to too many failed attempts. Try again in 15 minutes.',
        }),
      ),
    ).toBe(true)
  })

  it('is true for the sign-in lockout message', () => {
    expect(
      isAccountLocked429(
        answer({ error_code: 'HTTP_ERROR', message: 'Too many failed login attempts. Try again later.' }),
      ),
    ).toBe(true)
  })

  it('is false for an ordinary rate-limit 429', () => {
    expect(
      isAccountLocked429(answer({ error_code: 'HTTP_ERROR', message: 'Too many requests. Limit: 5 per 60 seconds.' })),
    ).toBe(false)
  })
})
