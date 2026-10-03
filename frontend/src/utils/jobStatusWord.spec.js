import { describe, it, expect } from 'vitest'
import { jobStatusWord, needsInputOwner } from './jobStatusWord'

describe('jobStatusWord', () => {
  it('prefers the server-computed activity word', () => {
    expect(jobStatusWord({ status: 'silent', activity: 'holding' })).toBe('holding')
    expect(jobStatusWord({ status: 'working', activity: 'working' })).toBe('working')
  })

  it('falls back to the stored status for a row without the word (older server, live update)', () => {
    expect(jobStatusWord({ status: 'silent' })).toBe('silent')
    expect(jobStatusWord({ status: 'complete' })).toBe('complete')
    expect(jobStatusWord(null)).toBe('')
  })

  it('lets a later stored status win over a stale word (the socket patches status only)', () => {
    expect(jobStatusWord({ status: 'complete', activity: 'holding' })).toBe('complete')
    expect(jobStatusWord({ status: 'working', activity: 'silent' })).toBe('working')
  })
})

describe('needsInputOwner', () => {
  const orch = { agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'working' }

  it('is null when nobody has to act (holding is not an alarm)', () => {
    expect(needsInputOwner([orch, { agent_display_name: 'implementer', status: 'silent', activity: 'holding' }])).toBeNull()
    expect(needsInputOwner([])).toBeNull()
  })

  it('names the orchestrator and counts its unread action-required posts', () => {
    expect(needsInputOwner([{ ...orch, action_required_unread: 2 }])).toMatchObject({
      owner: 'orchestrator', count: 2, text: 'Orchestrator: answer 2',
    })
    expect(needsInputOwner([{ ...orch, action_required_unread: 2 }]).hint).toMatch(/Hub/)
  })

  it('reads "answer N of M": posts to answer, out of posts waiting', () => {
    const text = (row) => needsInputOwner([{ ...orch, ...row }]).text
    expect(text({ action_required_unread: 1, messages_waiting_count: 4 })).toBe('Orchestrator: answer 1 of 4')
    expect(text({ action_required_unread: 1, messages_waiting_count: 1 })).toBe('Orchestrator: answer 1')
    expect(text({ action_required_unread: 2 })).toBe('Orchestrator: answer 2')
    expect(text({ action_required_unread: 2, messages_waiting_count: 1 })).toBe('Orchestrator: answer 2')
    expect(
      needsInputOwner([orch, { agent_display_name: 'implementer', status: 'working', action_required_unread: 1, messages_waiting_count: 2 }]).text,
    ).toBe('Implementer: answer 1 of 2')
  })

  it('names the operator for an awaiting-decision agent, ahead of a blocked one and of unread posts', () => {
    const agents = [
      { ...orch, action_required_unread: 1 },
      { agent_display_name: 'implementer', status: 'blocked' },
      { agent_display_name: 'tester', status: 'awaiting_user' },
    ]
    expect(needsInputOwner(agents)).toMatchObject({ owner: 'operator', kind: 'decision', count: 1, text: 'Your decision needed' })
    expect(needsInputOwner([{ agent_display_name: 'tester', status: 'awaiting_user' }])).toMatchObject({
      owner: 'operator', kind: 'decision', count: 1, text: 'Your decision needed',
    })
    expect(
      needsInputOwner([{ agent_display_name: 'tester', status: 'awaiting_user' }, { agent_display_name: 'reviewer', status: 'awaiting_user' }]),
    ).toMatchObject({ owner: 'operator', kind: 'decision', count: 2, text: '2 decisions need you' })
  })

  it('FE-9683 incident: a blocked agent with no pending approval is "<Role> blocked", never "Your decision needed"', () => {
    const result = needsInputOwner([orch, { agent_display_name: 'implementer', status: 'blocked' }])
    expect(result).toMatchObject({ owner: 'operator', kind: 'blocked', count: 1, text: 'Implementer blocked' })
    expect(result.text).not.toMatch(/decision/)
    expect(result.hint).toMatch(/reason/)
    expect(result.hint).toMatch(/Jobs detail|Hub thread/)
    expect(
      needsInputOwner([{ agent_display_name: 'implementer', status: 'blocked' }, { agent_display_name: 'tester', status: 'blocked' }]),
    ).toMatchObject({ kind: 'blocked', count: 2, text: '2 agents blocked' })
    expect(needsInputOwner([{ ...orch, status: 'blocked' }])).toMatchObject({ kind: 'blocked', text: 'Orchestrator blocked' })
  })

  it('a blocked agent outranks unread posts and silence', () => {
    expect(
      needsInputOwner([{ ...orch, action_required_unread: 2 }, { agent_display_name: 'implementer', status: 'blocked' }]),
    ).toMatchObject({ kind: 'blocked', text: 'Implementer blocked' })
    expect(
      needsInputOwner([{ ...orch, status: 'silent' }, { agent_display_name: 'implementer', status: 'blocked' }]),
    ).toMatchObject({ kind: 'blocked' })
  })

  it('every result names its kind', () => {
    expect(needsInputOwner([{ ...orch, action_required_unread: 1 }]).kind).toBe('unread')
    expect(needsInputOwner([orch, { agent_display_name: 'implementer', status: 'silent' }]).kind).toBe('silent')
    expect(needsInputOwner([{ ...orch, status: 'silent' }]).kind).toBe('silent')
  })

  it('names a worker by its role when the unread post is for it', () => {
    expect(
      needsInputOwner([orch, { agent_display_name: 'implementer', status: 'working', action_required_unread: 1 }]),
    ).toMatchObject({ owner: 'implementer', count: 1, text: 'Implementer: answer 1' })
  })

  it('hands a silent worker to the orchestrator, by the role that went quiet', () => {
    expect(needsInputOwner([orch, { agent_display_name: 'implementer', status: 'silent', activity: 'silent' }])).toMatchObject({
      owner: 'orchestrator', count: 1, text: 'Implementer silent',
    })
    expect(
      needsInputOwner([orch, { agent_display_name: 'implementer', status: 'silent' }, { agent_display_name: 'tester', status: 'silent' }]),
    ).toMatchObject({ owner: 'orchestrator', count: 2, text: '2 agents silent' })
  })

  it('the incident: a silent orchestrator is on the operator, and the hint says why and what to do', () => {
    const result = needsInputOwner([{ ...orch, status: 'silent' }])
    expect(result).toMatchObject({ owner: 'operator', count: 1, text: 'Orchestrator silent' })
    expect(result.hint).toMatch(/Nobody else can nudge the orchestrator/)
    expect(result.hint).toMatch(/Hub thread|replay/)
  })

  it('every non-null result carries a hint the pill can show', () => {
    const cases = [
      [{ ...orch, action_required_unread: 1 }],
      [{ agent_display_name: 'tester', status: 'blocked' }],
      [orch, { agent_display_name: 'implementer', status: 'silent' }],
      [{ ...orch, status: 'silent' }],
    ]
    for (const agents of cases) {
      expect(typeof needsInputOwner(agents).hint).toBe('string')
      expect(needsInputOwner(agents).hint.length).toBeGreaterThan(10)
    }
  })
})
