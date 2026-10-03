/**
 * The frontend ships in the same build as the backend. Code written for an
 * older server is a second contract nobody serves: the legacy string form of
 * buildServerUrl and the bare File[] form of the upload event are refused.
 *
 * Edition scope: Both
 */
import { describe, it, expect } from 'vitest'
import { buildServerUrl } from '@/composables/useMcpConfig'

describe('buildServerUrl', () => {
  it('takes only the backend config object', () => {
    expect(() => buildServerUrl('myhost.local', '8372')).toThrow()
    expect(() => buildServerUrl()).toThrow()
  })
})
