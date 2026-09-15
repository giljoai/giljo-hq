import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCommHubStore } from '@/stores/commHubStore'

const historyMock = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
      history: (...args) => historyMock(...args),
      participants: vi.fn(() => Promise.resolve({ data: { participants: [] } })),
    },
  },
}))

const THREAD_ID = 'thr-be9414'
const MESSAGE_ID = 'msg-be9414'
const EXCERPT = 'the first five kilobytes of a very long agent post'
const FULL_BODY = `${EXCERPT} ... and the eight kilobytes the broker could not carry`

function truncatedEvent(overrides = {}) {
  return {
    thread_id: THREAD_ID,
    message_id: MESSAGE_ID,
    from_agent_id: 'orchestrator',
    from_display_name: 'Coordinator',
    from_kind: 'agent',
    content: EXCERPT,
    message_type: 'broadcast',
    priority: 'normal',
    requires_action: false,
    update_type: 'new',
    content_truncated: true,
    content_length: FULL_BODY.length,
    ...overrides,
  }
}

function historyPayload(content = FULL_BODY) {
  return {
    data: {
      thread: { thread_id: THREAD_ID, chat_id: 'CHT-9414', status: 'open' },
      messages: [
        {
          message_id: MESSAGE_ID,
          thread_id: THREAD_ID,
          from_agent_id: 'orchestrator',
          from_display_name: 'Coordinator',
          from_kind: 'agent',
          content,
          created_at: '2026-08-13T06:30:00Z',
        },
      ],
    },
  }
}

describe('BE-9414 — a truncated thread_message is topped up to its full body', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useCommHubStore()
    historyMock.mockReset()
    historyMock.mockResolvedValue(historyPayload())
  })

  it('renders the FULL message after a truncated event lands on the open thread', async () => {
    store.selectedThreadId = THREAD_ID

    await store.handleThreadMessage(truncatedEvent())

    expect(historyMock).toHaveBeenCalledWith(THREAD_ID)
    const [message] = store.messagesFor(THREAD_ID)
    expect(message.message_id).toBe(MESSAGE_ID)
    expect(message.content).toBe(FULL_BODY)
  })

  it('tops up a thread that is NOT on screen too, so a late mention still reaches the bell', async () => {
    store.selectedThreadId = 'some-other-thread'

    await store.handleThreadMessage(truncatedEvent())

    expect(historyMock).toHaveBeenCalledWith(THREAD_ID)
    expect(store.messagesFor(THREAD_ID)[0].content).toBe(FULL_BODY)
  })

  it('fetches nothing for an ordinary, untruncated message on the open thread', async () => {
    store.selectedThreadId = THREAD_ID

    await store.handleThreadMessage(
      truncatedEvent({ content: 'a short post', content_truncated: false, content_length: 12 }),
    )

    expect(historyMock).not.toHaveBeenCalled()
    expect(store.messagesFor(THREAD_ID)[0].content).toBe('a short post')
  })

  it('still counts the message as unread on a thread that is not open', async () => {
    store.selectedThreadId = null

    await store.handleThreadMessage(truncatedEvent())

    expect(store.unreadFor(THREAD_ID)).toBe(1)
  })

  it('never flips the Hub into its loading state while topping up', async () => {
    store.selectedThreadId = THREAD_ID
    let loadingDuringFetch = null
    historyMock.mockImplementation(() => {
      loadingDuringFetch = store.loading
      return Promise.resolve(historyPayload())
    })

    await store.handleThreadMessage(truncatedEvent())

    expect(loadingDuringFetch).toBe(false)
  })

  it('leaves other threads unread counts alone', async () => {
    store.selectedThreadId = THREAD_ID
    store.unreadByThreadId = new Map([['another-thread', 3]])

    await store.handleThreadMessage(truncatedEvent())

    expect(store.unreadFor('another-thread')).toBe(3)
  })

  it('coalesces a burst of long posts into two reads, not one per post', async () => {
    store.selectedThreadId = THREAD_ID
    const pending = []
    historyMock.mockImplementation(
      () => new Promise((resolve) => pending.push(() => resolve(historyPayload()))),
    )

    const inFlight = [store.handleThreadMessage(truncatedEvent())]
    for (let i = 0; i < 4; i += 1) {
      inFlight.push(store.handleThreadMessage(truncatedEvent({ message_id: `msg-burst-${i}` })))
    }
    for (let i = 0; i < 5; i += 1) {
      pending.splice(0).forEach((release) => release())
      await Promise.resolve()
      await Promise.resolve()
    }
    await Promise.all(inFlight)

    expect(historyMock).toHaveBeenCalledTimes(2)
  })

  it('does not strand a message that arrived while a read was already in flight', async () => {
    store.selectedThreadId = THREAD_ID
    const LATE_ID = 'msg-arrived-during-the-read'
    const LATE_BODY = 'the late post, in full'
    let firstReadResolve
    historyMock
      .mockImplementationOnce(
        () => new Promise((resolve) => (firstReadResolve = () => resolve(historyPayload()))),
      )
      .mockImplementationOnce(() =>
        Promise.resolve({
          data: {
            thread: { thread_id: THREAD_ID },
            messages: [
              historyPayload().data.messages[0],
              {
                message_id: LATE_ID,
                thread_id: THREAD_ID,
                from_agent_id: 'orchestrator',
                content: LATE_BODY,
                created_at: '2026-08-13T06:31:00Z',
              },
            ],
          },
        }),
      )

    const first = store.handleThreadMessage(truncatedEvent())
    const late = store.handleThreadMessage(
      truncatedEvent({ message_id: LATE_ID, content: 'the late post' }),
    )
    firstReadResolve()
    await Promise.all([first, late])

    const stored = store.messagesFor(THREAD_ID).find((m) => m.message_id === LATE_ID)
    expect(stored.content).toBe(LATE_BODY)
  })

  it('leaves the excerpt readable when the top-up read fails', async () => {
    store.selectedThreadId = THREAD_ID
    historyMock.mockRejectedValue(new Error('network down'))

    await store.handleThreadMessage(truncatedEvent())

    expect(store.messagesFor(THREAD_ID)[0].content).toBe(EXCERPT)
    expect(store.error).toBeNull()
  })

  it('can top up again after a failure, rather than latching', async () => {
    store.selectedThreadId = THREAD_ID
    historyMock.mockRejectedValueOnce(new Error('network down'))

    await store.handleThreadMessage(truncatedEvent())
    await store.handleThreadMessage(truncatedEvent())

    expect(historyMock).toHaveBeenCalledTimes(2)
    expect(store.messagesFor(THREAD_ID)[0].content).toBe(FULL_BODY)
  })
})
