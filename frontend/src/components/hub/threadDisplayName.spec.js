/**
 * threadDisplayName.spec.js — FE-9436
 *
 * The operator's names-never-UUIDs rule, pinned at its single implementation.
 *
 * The test that carries the weight is the last one: an id must never come out, from any
 * field, at any position. Every surface that names a thread reached for one when it ran
 * out of better options, so "never" is the property to assert rather than "prefers".
 *
 * Edition scope: Both
 */
import { describe, it, expect } from 'vitest'
import { threadDisplayName } from './threadDisplayName'

const UUID = '9f8e7d6c-5b4a-4321-9876-0abcdef12345'

describe('threadDisplayName (FE-9436)', () => {
  it('says the thread name first — what a person would call it', () => {
    expect(threadDisplayName({ subject: 'Laptop interop', chat_id: 'CHT-0009' })).toBe(
      'Laptop interop',
    )
    expect(threadDisplayName({ title: 'Legacy title' })).toBe('Legacy title')
  })

  it('falls back to the live event when the store has not hydrated the thread', () => {
    // The cold-page case: the browser notification fires for a thread this session has
    // never loaded, which is precisely when the old fallbacks printed an id.
    expect(threadDisplayName(undefined, { subject: 'Renamed thread' })).toBe('Renamed thread')
    expect(threadDisplayName(null, { chat_id: 'CHT-0493' })).toBe('CHT-0493')
  })

  it('falls back to the serial a person would actually quote', () => {
    expect(threadDisplayName({ chat_id: 'CHT-0493' })).toBe('CHT-0493')
  })

  it('says plain words rather than nothing, and never "undefined"', () => {
    for (const name of [threadDisplayName(), threadDisplayName({}, {}), threadDisplayName(null)]) {
      expect(name).toBe('a thread')
      expect(name).not.toContain('undefined')
    }
  })

  it('NEVER returns an id, from any field or any position', () => {
    // Each case gives the function an id and nothing else it prefers. A future edit that
    // adds `thread_id` to the fallback chain — the shape all three surfaces had — fails
    // here rather than in front of an operator.
    const cases = [
      { thread_id: UUID },
      { thread_id: UUID, subject: '', title: '', chat_id: '' },
      { thread_id: UUID, subject: null },
    ]
    for (const thread of cases) {
      expect(threadDisplayName(thread)).toBe('a thread')
    }
    expect(threadDisplayName({ thread_id: UUID }, { thread_id: UUID })).not.toContain(UUID)
  })
})
