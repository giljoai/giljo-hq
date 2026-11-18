import { describe, it, expect } from 'vitest'
import { readCsrfToken } from './csrfCookie'

describe('readCsrfToken', () => {
  it('reads the plain cookie when it is the only one (plain-HTTP install)', () => {
    expect(readCsrfToken('access_token=a; csrf_token=plain')).toBe('plain')
  })

  it('reads the __Host- cookie when it is the only one (HTTPS)', () => {
    expect(readCsrfToken('__Host-csrf_token=host')).toBe('host')
  })

  it('prefers __Host- when both are present with different values, in either order', () => {
    expect(readCsrfToken('csrf_token=stale; __Host-csrf_token=fresh')).toBe('fresh')
    expect(readCsrfToken('__Host-csrf_token=fresh; csrf_token=stale')).toBe('fresh')
  })

  it('takes __Host- when the plain cookie is empty', () => {
    expect(readCsrfToken('csrf_token=; __Host-csrf_token=fresh')).toBe('fresh')
  })

  it('returns null when neither cookie is present', () => {
    expect(readCsrfToken('access_token=a; other=b')).toBeNull()
    expect(readCsrfToken('')).toBeNull()
  })

  it('never matches a cookie whose name only ends in csrf_token', () => {
    expect(readCsrfToken('x_csrf_token=nope')).toBeNull()
  })
})
