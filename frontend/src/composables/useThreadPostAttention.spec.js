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
