/**
 * useThreadPostAttention.spec.js — FE-9586
 *
 * The projection behind the thread-post banner family, and the contract that
 * matters most is NULL MEANS NOT LOADED.
 *
 * FE-9553's reconcile closes every popout absent from the live set. If this
 * composable handed out [] before its first read landed, a cold page load would
 * be indistinguishable from "nothing is waiting" and every popout would close on
 * mount — silently, and only on a real OS where popouts exist. That is the
 * near-miss the sibling lane caught by reading the store instead of trusting its
 * own green, so it is pinned here rather than left to a comment.
 *
 * Edition Scope: Both
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'

const attentionMock = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    threads: {
      attention: (...args) => attentionMock(...args),
    },
  },
}))

import { useThreadPostAttention, __resetThreadPostAttention } from './useThreadPostAttention'

const ONE_MENTION = {
  data: { mentions: [{ thread_id: 't-1', chat_id: 'CHT-0001', message_ids: ['m-1'] }], directed_action: [] },
}

describe('useThreadPostAttention (FE-9586)', () => {
  beforeEach(() => {
    __resetThreadPostAttention()
    attentionMock.mockReset()
    attentionMock.mockResolvedValue({ data: { mentions: [], directed_action: [] } })
  })

  it('THE CONTRACT: a FRESH module starts null, never as an empty array', async () => {
    // Imported fresh on purpose. The first version of this test read the state after
    // __resetThreadPostAttention() had set it to null, so it asserted what the RESET
    // HELPER does and passed happily with the module declaring ref([]) instead — a
    // mutation run proved it: changing the declaration killed zero tests. A test of
    // the fixture wearing the module's name is exactly the shape this lane has been
    // deleting elsewhere, so it is fixed here rather than trusted.
    vi.resetModules()
    const fresh = await import('./useThreadPostAttention')
    const { mentions, directedAsks, loaded } = fresh.useThreadPostAttention()

    expect(mentions.value).toBeNull()
    expect(directedAsks.value).toBeNull()
    expect(loaded.value).toBe(false)
  })

  it('becomes loaded, with a real empty list, once the read lands', async () => {
    const { mentions, loaded, refresh } = useThreadPostAttention()

    await refresh()

    expect(mentions.value).toEqual([])
    expect(loaded.value).toBe(true)
  })

  it('reports what the server said', async () => {
    attentionMock.mockResolvedValue(ONE_MENTION)
    const { mentions, refresh } = useThreadPostAttention()

    await refresh()

    expect(mentions.value).toEqual([
      { thread_id: 't-1', chat_id: 'CHT-0001', message_ids: ['m-1'] },
    ])
  })

  it('KEEPS the last known state when a read fails -- a failed poll is not evidence of quiet', async () => {
    // The dangerous alternative is clearing to []: the banner would vanish and the
    // reconcile would close popouts for signals still owed an answer, because the
    // network blipped.
    attentionMock.mockResolvedValue(ONE_MENTION)
    const { mentions, refresh } = useThreadPostAttention()
    await refresh()

    attentionMock.mockRejectedValue(new Error('offline'))
    await refresh()

    expect(mentions.value).toHaveLength(1)
  })

  it('stays unloaded if the FIRST read fails, rather than claiming an empty world', async () => {
    attentionMock.mockRejectedValue(new Error('offline'))
    const { loaded, refresh } = useThreadPostAttention()

    await refresh()

    expect(loaded.value).toBe(false)
  })

  it('collapses concurrent callers onto one request', async () => {
    // A burst of thread events is the normal case when an orchestrator fans out
    // directives, and one read answers all of them.
    const { refresh } = useThreadPostAttention()

    await Promise.all([refresh(), refresh(), refresh()])

    expect(attentionMock).toHaveBeenCalledTimes(1)
  })

  it('reads once per page load however many consumers ask', async () => {
    const a = useThreadPostAttention()
    const b = useThreadPostAttention()

    await a.ensureLoaded()
    await b.ensureLoaded()

    expect(attentionMock).toHaveBeenCalledTimes(1)
  })

  it('re-reads when the Hub says something happened', async () => {
    useThreadPostAttention()
    await Promise.resolve()
    attentionMock.mockClear()

    window.dispatchEvent(new CustomEvent('hub:thread_message', { detail: {} }))
    await nextTick()

    expect(attentionMock).toHaveBeenCalled()
  })

  it('shares ONE answer across callers -- a per-caller copy would leave the reconcile blind', async () => {
    // The lifecycle, the banner and the announcer all have to see the same verdict.
    // Per-caller refs would give the reconcile its own permanently-unloaded copy.
    attentionMock.mockResolvedValue(ONE_MENTION)
    const first = useThreadPostAttention()
    const second = useThreadPostAttention()

    await first.refresh()

    expect(second.mentions.value).toHaveLength(1)
    expect(second.loaded.value).toBe(true)
  })

  it('counts both classes together, and counts nothing while unloaded', async () => {
    attentionMock.mockResolvedValue({
      data: {
        mentions: [{ thread_id: 't-1', message_ids: ['m-1'] }],
        directed_action: [{ thread_id: 't-2' }],
      },
    })
    const { attentionCount, refresh } = useThreadPostAttention()

    expect(attentionCount.value).toBe(0)

    await refresh()

    expect(attentionCount.value).toBe(2)
  })
})
