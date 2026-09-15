import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

import ThreadTimeline from '@/components/hub/ThreadTimeline.vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { getAgentColor } from '@/config/agentColors'

const vuetify = createVuetify()
const THREAD_ID = 'thr-timeline'
const USER_UUID = '550e8400-e29b-41d4-a716-446655440000'

const USER_MSG = {
  thread_id: THREAD_ID,
  message_id: 'msg-user',
  from_agent_id: USER_UUID,
  from_kind: 'user',
  from_display_name: 'Sam Rivera',
  content: 'operator speaking',
  message_type: 'broadcast',
  created_at: '2026-06-18T10:00:00Z',
}

const AGENT_MSG = {
  thread_id: THREAD_ID,
  message_id: 'msg-agent',
  from_agent_id: 'implementer',
  from_kind: 'agent',
  from_display_name: 'implementer',
  content: 'building it',
  message_type: 'broadcast',
  created_at: '2026-06-18T10:01:00Z',
}

function mountTimeline(pinia) {
  return mount(ThreadTimeline, { global: { plugins: [pinia, vuetify] } })
}

describe('ThreadTimeline author rendering (FE-6122)', () => {
  let pinia
  let store

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
    store.selectedThreadId = THREAD_ID
    store.handleThreadMessage(USER_MSG)
    store.handleThreadMessage(AGENT_MSG)
  })

  it('renders both messages on the selected thread', () => {
    const wrapper = mountTimeline(pinia)
    expect(wrapper.findAll('.timeline-msg').length).toBe(2)
  })

  it('renders a USER post with the brand-yellow user avatar treatment + initials', () => {
    const wrapper = mountTimeline(pinia)
    const row = wrapper.find('[data-testid="timeline-message-msg-user"]')
    expect(row.classes()).toContain('timeline-msg--user')
    const avatar = row.find('.timeline-msg__avatar')
    expect(avatar.classes()).toContain('timeline-msg__avatar--user')
    expect(avatar.text()).toBe('SR')
    expect(avatar.attributes('style') || '').not.toContain('background-color')
  })

  it('renders an AGENT post with a tinted role color badge, NOT the user treatment', () => {
    const wrapper = mountTimeline(pinia)
    const row = wrapper.find('[data-testid="timeline-message-msg-agent"]')
    expect(row.classes()).toContain('timeline-msg--agent')
    const avatar = row.find('.timeline-msg__avatar')
    expect(avatar.classes()).not.toContain('timeline-msg__avatar--user')
    expect(avatar.attributes('style') || '').toContain('background-color')
  })
})


const RESOLVE_THREAD = 'thr-resolve'
const AGENT_UUID = '277e2ee9-e15d-4339-9730-4ffee559cdcb'

function seedResolveMessage(store, overrides = {}) {
  store.selectedThreadId = RESOLVE_THREAD
  store.handleThreadMessage({
    thread_id: RESOLVE_THREAD, message_id: 'msg-uuid-agent', from_agent_id: AGENT_UUID,
    from_kind: 'agent', from_display_name: AGENT_UUID, content: 'orchestrating',
    message_type: 'broadcast', created_at: '2026-06-18T10:00:00Z', ...overrides,
  })
}

describe('ThreadTimeline server-resolved author kind (BE-9289a)', () => {
  let pinia
  let store

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
  })

  it('REGRESSION: a UUID-authored AGENT post renders as an agent with NO directory loaded', () => {
    seedResolveMessage(store)
    const wrapper = mountTimeline(pinia)
    const row = wrapper.find('[data-testid="timeline-message-msg-uuid-agent"]')
    expect(row.classes()).toContain('timeline-msg--agent')
    expect(row.classes()).not.toContain('timeline-msg--user')
    const avatar = row.find('.timeline-msg__avatar')
    expect(avatar.classes()).not.toContain('timeline-msg__avatar--user')
    expect(avatar.attributes('style') || '').toContain('background-color')
  })

  it('uses the participant directory for the NAME, not for the kind', () => {
    seedResolveMessage(store)
    store.participantsByThreadId = new Map([
      [RESOLVE_THREAD, [{ participant_id: AGENT_UUID, participant_type: 'agent', display_name: 'orchestrator' }]],
    ])
    const wrapper = mountTimeline(pinia)
    const row = wrapper.find('[data-testid="timeline-message-msg-uuid-agent"]')
    expect(row.classes()).toContain('timeline-msg--agent')
    expect(row.find('.timeline-msg__sender').text()).toBe('orchestrator')
  })

  it('renders a genuine USER post with the user treatment', () => {
    seedResolveMessage(store, { from_kind: 'user', from_display_name: 'Sam' })
    const wrapper = mountTimeline(pinia)
    const row = wrapper.find('[data-testid="timeline-message-msg-uuid-agent"]')
    expect(row.classes()).toContain('timeline-msg--user')
    expect(row.find('.timeline-msg__sender').text()).toBe('Sam')
  })

  it('a stale directory entry cannot override the server on the author kind', () => {
    seedResolveMessage(store)
    store.participantsByThreadId = new Map([
      [RESOLVE_THREAD, [{ participant_id: AGENT_UUID, participant_type: 'user', display_name: 'Sam' }]],
    ])
    const wrapper = mountTimeline(pinia)
    const row = wrapper.find('[data-testid="timeline-message-msg-uuid-agent"]')
    expect(row.classes()).toContain('timeline-msg--agent')
    expect(row.classes()).not.toContain('timeline-msg--user')
  })
})


const PUNCT_THREAD = 'thr-fe9490'
const REVIEWER_ID = 'reviewer-phase5-agent'

describe('ThreadTimeline agent badge consistency (FE-9490)', () => {
  let pinia
  let store

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
    store.selectedThreadId = PUNCT_THREAD
    store.handleThreadMessage({
      thread_id: PUNCT_THREAD, message_id: 'msg-reviewer-phase5', from_agent_id: REVIEWER_ID,
      from_kind: 'agent', from_display_name: 'Reviewer (Phase 5)', content: 'reviewing',
      message_type: 'broadcast', created_at: '2026-06-18T10:02:00Z',
    })
    store.participantsByThreadId = new Map([
      [PUNCT_THREAD, [{ participant_id: REVIEWER_ID, role: 'reviewer', display_name: 'Reviewer (Phase 5)' }]],
    ])
  })

  it('does not leak a bracket into the avatar initials for a parenthetical name', () => {
    const wrapper = mountTimeline(pinia)
    const row = wrapper.find('[data-testid="timeline-message-msg-reviewer-phase5"]')
    const avatar = row.find('.timeline-msg__avatar')
    expect(avatar.text()).toBe('RP')
    expect(avatar.text()).not.toContain('(')
  })

  it('colours the avatar by the participant ROLE, matching the reviewer badge everywhere else', () => {
    const wrapper = mountTimeline(pinia)
    const row = wrapper.find('[data-testid="timeline-message-msg-reviewer-phase5"]')
    const avatar = row.find('.timeline-msg__avatar')
    const reviewerHex = getAgentColor('reviewer').hex
    const [r, g, b] = [1, 3, 5].map((i) => Number.parseInt(reviewerHex.slice(i, i + 2), 16))
    expect(avatar.attributes('style') || '').toContain(`color: rgb(${r}, ${g}, ${b})`)
  })
})


const READ_THREAD = 'thr-read'

function seedRead(store, msgs) {
  store.selectedThreadId = READ_THREAD
  msgs.forEach((m) =>
    store.handleThreadMessage({
      thread_id: READ_THREAD, from_kind: 'agent', message_type: 'broadcast',
      created_at: '2026-06-18T10:00:00Z', ...m,
    }),
  )
}

describe('ThreadTimeline reading surface (FE-9289c)', () => {
  let pinia
  let store

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
  })

  it('the waiting/read/sent filter row is gone', () => {
    seedRead(store, [
      {
        message_id: 'f1', content: 'act please', from_agent_id: 'orchestrator',
        requires_action: true, recipients: ['beta'], acked_by: [], completed_by: [], pending_for: ['beta'],
      },
    ])
    const wrapper = mountTimeline(pinia)
    expect(wrapper.find('[data-testid="thread-filter"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="thread-filter-waiting"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="timeline-message-f1"]').exists()).toBe(true)
  })

  it('renders markdown through the sanctioned sanitizer, not as raw text', () => {
    seedRead(store, [{ message_id: 'md1', content: '**bold** and `code`', from_agent_id: 'implementer' }])
    const wrapper = mountTimeline(pinia)
    const body = wrapper.get('[data-testid="timeline-message-md1"] .timeline-msg__md')
    expect(body.find('strong').exists()).toBe(true)
    expect(body.find('code').exists()).toBe(true)
    expect(body.text()).not.toContain('**')
  })

  it('strips a script tag out of a message body (SEC-0003 path)', () => {
    seedRead(store, [
      { message_id: 'md2', content: 'hello <script>window.__pwned = 1</script> there', from_agent_id: 'implementer' },
    ])
    const wrapper = mountTimeline(pinia)
    const body = wrapper.get('[data-testid="timeline-message-md2"] .timeline-msg__md')
    expect(body.html()).not.toContain('<script')
    expect(body.text()).toContain('hello')
  })

  it('badges a DIRECT post and says nothing on a broadcast', () => {
    seedRead(store, [
      { message_id: 'b1', content: 'to everyone', from_agent_id: 'implementer', message_type: 'broadcast' },
      { message_id: 'd1', content: 'to you', from_agent_id: 'reviewer', message_type: 'direct' },
    ])
    const wrapper = mountTimeline(pinia)
    expect(
      wrapper.find('[data-testid="timeline-message-b1"] [data-testid="message-type-chip"]').exists(),
    ).toBe(false)
    const chip = wrapper.get('[data-testid="timeline-message-d1"] [data-testid="message-type-chip"]')
    expect(chip.text()).toBe('direct')
  })

  it('groups a run of posts by the same author — one badge, one header', () => {
    seedRead(store, [
      { message_id: 'g1', content: 'first', from_agent_id: 'implementer', created_at: '2026-06-18T10:00:00Z' },
      { message_id: 'g2', content: 'second', from_agent_id: 'implementer', created_at: '2026-06-18T10:01:00Z' },
      { message_id: 'g3', content: 'other', from_agent_id: 'reviewer', created_at: '2026-06-18T10:02:00Z' },
    ])
    const wrapper = mountTimeline(pinia)
    const g2 = wrapper.get('[data-testid="timeline-message-g2"]')
    expect(g2.classes()).toContain('timeline-msg--grouped')
    expect(g2.find('.timeline-msg__avatar').exists()).toBe(false)
    expect(g2.find('.timeline-msg__header').exists()).toBe(false)
    const g3 = wrapper.get('[data-testid="timeline-message-g3"]')
    expect(g3.classes()).not.toContain('timeline-msg--grouped')
    expect(g3.find('.timeline-msg__avatar').exists()).toBe(true)
  })

  it('never groups an action-required post — it must keep its own header', () => {
    seedRead(store, [
      { message_id: 'a1', content: 'first', from_agent_id: 'orchestrator', created_at: '2026-06-18T10:00:00Z' },
      {
        message_id: 'a2', content: 'decide this', from_agent_id: 'orchestrator',
        requires_action: true, created_at: '2026-06-18T10:01:00Z',
      },
    ])
    const wrapper = mountTimeline(pinia)
    const a2 = wrapper.get('[data-testid="timeline-message-a2"]')
    expect(a2.classes()).not.toContain('timeline-msg--grouped')
    expect(a2.find('[data-testid="message-action-flag"]').exists()).toBe(true)
  })

  it('folds a long post to its first sentence and unfolds on request', async () => {
    const long = `The short version is here. ${'x'.repeat(500)}`
    seedRead(store, [{ message_id: 'l1', content: long, from_agent_id: 'implementer' }])
    const wrapper = mountTimeline(pinia)
    const body = wrapper.get('[data-testid="timeline-message-l1"] .timeline-msg__md')
    expect(body.text()).toContain('The short version is here.')
    expect(body.text()).not.toContain('xxxxx')
    await wrapper.get('[data-testid="message-unfold-l1"]').trigger('click')
    expect(wrapper.get('[data-testid="timeline-message-l1"] .timeline-msg__md').text()).toContain('xxxxx')
  })

  it('leaves a short post unfolded — no expander at all', () => {
    seedRead(store, [{ message_id: 's1', content: 'brief.', from_agent_id: 'implementer' }])
    const wrapper = mountTimeline(pinia)
    expect(wrapper.find('[data-testid="message-unfold-s1"]').exists()).toBe(false)
  })

  it('shows the harness on the meta line and NEVER a host (packet correction 1)', () => {
    seedRead(store, [{ message_id: 'h1', content: 'hi', from_agent_id: 'implementer' }])
    store.participantsByThreadId = new Map([
      [READ_THREAD, [{
        participant_id: 'implementer', participant_type: 'agent', display_name: 'implementer',
        harness: 'claude-code', host: 'laptop-a',
      }]],
    ])
    const wrapper = mountTimeline(pinia)
    const row = wrapper.get('[data-testid="timeline-message-h1"]')
    expect(row.get('[data-testid="message-harness"]').text()).toBe('claude-code')
    expect(row.text()).not.toContain('laptop-a')
  })

  it('labels the `generic` harness floor and shows nothing when the author is unknown', () => {
    seedRead(store, [
      { message_id: 'k1', content: 'a', from_agent_id: 'implementer' },
      { message_id: 'k2', content: 'b', from_agent_id: 'stranger' },
    ])
    store.participantsByThreadId = new Map([
      [READ_THREAD, [{ participant_id: 'implementer', participant_type: 'agent', harness: 'generic' }]],
    ])
    const wrapper = mountTimeline(pinia)
    expect(
      wrapper.get('[data-testid="timeline-message-k1"] [data-testid="message-harness"]').text(),
    ).toBe('Generic Harness')
    expect(
      wrapper.find('[data-testid="timeline-message-k2"] [data-testid="message-harness"]').exists(),
    ).toBe(false)
  })
})


describe('ThreadTimeline explicit threadId (Phase 5 / D1(a))', () => {
  let pinia
  let store
  const EXPLICIT = 'thr-explicit'

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
    store.selectedThreadId = 'thr-other-empty'
    store.handleThreadMessage({
      thread_id: EXPLICIT, message_id: 'e1', content: 'hello', from_agent_id: 'implementer',
      created_at: '2026-06-18T10:00:00Z',
    })
    store.handleThreadMessage({
      thread_id: EXPLICIT, message_id: 'e2', content: 'world', from_agent_id: 'orchestrator',
      created_at: '2026-06-18T10:01:00Z',
    })
  })

  function mountExplicit(props) {
    return mount(ThreadTimeline, { props, global: { plugins: [pinia, vuetify] } })
  }

  it("renders the explicit thread's messages, ignoring selectedThreadId", () => {
    const wrapper = mountExplicit({ threadId: EXPLICIT })
    expect(wrapper.findAll('[data-testid^="timeline-message-"]')).toHaveLength(2)
    expect(wrapper.find('[data-testid="timeline-message-e1"]').exists()).toBe(true)
  })
})
