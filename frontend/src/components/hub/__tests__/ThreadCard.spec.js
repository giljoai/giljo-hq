/**
 * ThreadCard.spec.js — FE-9289c
 *
 * One Quiet Card's rendering + the packet corrections that override the design spec:
 *  - NO host on the pill (role badge + agent name + harness + live dot only)
 *  - the harness token `generic` renders "Generic Harness"
 *  - an empty participant list shows the check-in prompt
 *  - a project thread shows a lock (not a missing button) and no rename affordance
 *  - the status chip renders only for terminal threads (no "open" chip noise)
 *  - inline rename emits { thread, subject } and is not offered on project threads
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import { createVuetify } from 'vuetify'
import ThreadCard from '@/components/hub/ThreadCard.vue'

const vuetify = createVuetify()

function mountCard(thread, props = {}) {
  return mount(ThreadCard, { props: { thread, ...props }, global: { plugins: [vuetify] } })
}

const BASE = {
  thread_id: 't1',
  chat_id: 'CHT-0001',
  subject: 'Laptop interop',
  status: 'open',
  project_id: null,
  participants: [],
  last_message: null,
  unread: false,
}

describe('ThreadCard', () => {
  it('shows the title', () => {
    const w = mountCard(BASE)
    expect(w.find('[data-testid="thread-card-title"]').text()).toBe('Laptop interop')
  })

  it('renders an agent pill as badge + harness + dot, with NO name and NO host', () => {
    // FE-9365c: the NAME left the pill. Real names are `LANE_A — installer + harness
    // fixes`; with no max-width they wrapped to three lines each, so a five-agent card
    // became taller than everything else on screen. The badge is the identity; the full
    // name lives in the pill's title and in the two places it is actually read — the
    // composer's To dropdown and every message author line.
    const w = mountCard({
      ...BASE,
      participants: [{ participant_id: 'a', display_name: 'Alpha', role: 'implementer', harness: 'claude-code', host: 'laptop-a' }],
    })
    const pill = w.find('[data-testid="thread-card-pill"]')
    expect(pill.exists()).toBe(true)
    expect(pill.text()).toContain('claude-code')
    expect(pill.text()).not.toContain('Alpha')
    // Still recoverable — hovering the pill names the agent, its harness and its status.
    expect(pill.attributes('title')).toContain('Alpha')
    // The correction that predates this: host is never rendered, even if the payload
    // still carries it.
    expect(pill.text()).not.toContain('laptop-a')
    expect(pill.attributes('title')).not.toContain('laptop-a')
  })

  it('normalises the model suffix out of the harness label', () => {
    // `OpenCode · Qwen` renders as `OpenCode`. At 11.5px the family is the useful fact,
    // and the model changes per session — the same agent would look different between
    // two polls.
    const w = mountCard({
      ...BASE,
      participants: [{ participant_id: 'a', display_name: 'Alpha', harness: 'OpenCode · Qwen' }],
    })
    const pill = w.find('[data-testid="thread-card-pill"]')
    expect(pill.text()).toContain('OpenCode')
    expect(pill.text()).not.toContain('Qwen')
  })

  it('renders the generic harness token as "Generic Harness"', () => {
    const w = mountCard({
      ...BASE,
      participants: [{ participant_id: 'a', display_name: 'Alpha', role: 'implementer', harness: 'generic' }],
    })
    expect(w.find('[data-testid="thread-card-pill"]').text()).toContain('Generic Harness')
  })

  it('shows the check-in prompt when no agents have registered', () => {
    const w = mountCard(BASE)
    expect(w.find('[data-testid="thread-card-empty-pills"]').text()).toContain('No one has checked in yet')
  })

  it('excludes the user from the registered-agent pills', () => {
    const w = mountCard({
      ...BASE,
      participants: [
        { participant_id: 'u', participant_type: 'user', display_name: 'Sam Rivera' },
        { participant_id: 'a', participant_type: 'agent', display_name: 'Alpha', harness: 'codex' },
      ],
    })
    const pills = w.findAll('[data-testid="thread-card-pill"]')
    expect(pills.length).toBe(1)
    expect(pills[0].attributes('title')).toContain('Alpha')
  })

  it('shows the last message with its author', () => {
    const w = mountCard({ ...BASE, last_message: { author: 'Alpha', excerpt: 'shipping it', created_at: '2026-07-25T10:00:00Z' } })
    const last = w.find('[data-testid="thread-card-last"]')
    expect(last.text()).toContain('Alpha')
    expect(last.text()).toContain('shipping it')
  })

  it('renders the status chip ONLY for terminal threads', () => {
    expect(mountCard({ ...BASE, status: 'open' }).find('[data-testid="thread-card-status"]').exists()).toBe(false)
    expect(mountCard({ ...BASE, status: 'resolved' }).find('[data-testid="thread-card-status"]').exists()).toBe(true)
  })

  it('a general thread offers rename + delete', () => {
    const w = mountCard({ ...BASE, project_id: null })
    expect(w.find('[data-testid="thread-card-rename"]').exists()).toBe(true)
    const del = w.find('[data-testid="thread-card-delete"]')
    expect(del.attributes('aria-label')).toContain('Delete')
  })

  it('a project thread shows a lock and no rename', () => {
    const w = mountCard({ ...BASE, project_id: 'proj-1' })
    expect(w.find('[data-testid="thread-card-rename"]').exists()).toBe(false)
    expect(w.find('[data-testid="thread-card-delete"]').attributes('aria-label')).toContain('Locked')
  })

  it('project card footer says it is kept with the project 360 memory', () => {
    const w = mountCard({ ...BASE, project_id: 'proj-1' })
    // FE-9365c: the note left the serial (which moved to the FRONT of the title) and
    // now sits beside the join block, where the rest of the footer's context lives.
    expect(w.find('[data-testid="thread-card"]').text()).toContain('360 memory')
  })

  it('reserves room for the hover actions so they never draw over the title', () => {
    // FAIL-FIRST for a live defect (reported with screenshots, 2026-08-04): on hover the
    // copy and trash icons were drawn directly ON TOP of the title's last words.
    //
    // Cause: `__actions` is absolutely positioned at `right: 20px`, so it is out of flow
    // and `__title` (flex: 1) truncated at the FULL card width — the title never
    // shortened to make room. Worst in a narrow column, which is why it survived review.
    //
    // jsdom does no layout, so the assertion is against the RULE rather than rendered
    // geometry: the head must reserve a right-hand strip at least as wide as the action
    // block (3 x 26px + 2 x 4px gap + 20px offset = 106px). Deleting the padding — the
    // obvious "cleanup" — fails here instead of silently restoring the overlap.
    const style = readFileSync(resolve(__dirname, '../ThreadCard.vue'), 'utf8')
    const head = style.match(/&__head\s*\{([^}]*)\}/)
    expect(head, 'the __head rule went missing').not.toBeNull()

    const padding = head[1].match(/padding-right:\s*(\d+)px/)
    expect(padding, '__head no longer reserves room for the hover actions').not.toBeNull()
    expect(Number(padding[1])).toBeGreaterThanOrEqual(106)

    // And the actions must still be OUT of flow, or the fix trades overlap for the
    // layout shift the absolute positioning exists to prevent.
    expect(style).toMatch(/&__actions\s*\{[^}]*position:\s*absolute/)
  })

  it('raises the hand ONLY from the baton — the same source as the gold frame', () => {
    // FE-9365g. The hand and the frame must agree, and both must ignore unread:
    // an operator who was away has unread everywhere, and a signal that is always
    // on signals nothing (the all-gold board was a live report, 2026-08-05).
    const up = mountCard({ ...BASE, unread: true, _yourTurn: true })
    expect(up.find('[data-testid="thread-card-hand"]').exists()).toBe(true)
    expect(up.classes()).toContain('thread-card--attention')

    const unreadOnly = mountCard({ ...BASE, unread: true, _yourTurn: false })
    expect(unreadOnly.find('[data-testid="thread-card-hand"]').exists()).toBe(false)
    expect(unreadOnly.classes()).not.toContain('thread-card--attention')
  })

  it('leads the title with the serial, loud, because it is what the operator quotes', () => {
    const w = mountCard({ ...BASE, chat_id: 'CHT-0477' })
    expect(w.find('[data-testid="thread-card-serial"]').text()).toBe('CHT-0477')
  })

  it('the footer carries the FULL thread uuid as a copyable join command', () => {
    // A partial id is useless to paste, so the card shows all of it — this is the
    // most-used action after opening the thread.
    const w = mountCard({ ...BASE, thread_id: '906637cb-d8fa-4b71-9c2e-4f1ab0d77e31' })
    const join = w.find('[data-testid="thread-card-join"]')
    expect(join.text()).toContain('join_thread')
    expect(join.text()).toContain('906637cb-d8fa-4b71-9c2e-4f1ab0d77e31')
  })

  it('caps the pills at five and collapses the rest into ONE +N more chip', () => {
    const participants = Array.from({ length: 7 }, (_, i) => ({
      participant_id: `a${i}`,
      display_name: `LANE_${i} — installer + harness fixes`,
      harness: 'claude-code',
    }))
    const w = mountCard({ ...BASE, participants })

    expect(w.findAll('[data-testid="thread-card-pill"]').length).toBe(5)
    const more = w.find('[data-testid="thread-card-pill-more"]')
    expect(more.text()).toBe('+2 more')
    // The dropped names stay recoverable rather than lost.
    expect(more.attributes('title')).toContain('LANE_5')
    expect(more.attributes('title')).toContain('LANE_6')
  })

  it('never leaves a +0 more or +-1 more string in the DOM', () => {
    // The naive `agents.length - MAX` computes a label for every card, including the
    // ones with nothing to overflow.
    for (const count of [0, 1, 4, 5]) {
      const participants = Array.from({ length: count }, (_, i) => ({ participant_id: `a${i}`, harness: 'generic' }))
      const html = mountCard({ ...BASE, participants }).html()
      expect(html).not.toContain('+0 more')
      expect(html).not.toContain('+-1 more')
    }
  })

  it('inline rename emits { thread, subject } and does not select', async () => {
    const w = mountCard({ ...BASE, subject: 'Old' })
    await w.find('[data-testid="thread-card-rename"]').trigger('click')
    const input = w.find('[data-testid="thread-card-rename-input"]')
    expect(input.exists()).toBe(true)
    await input.setValue('New name')
    await input.trigger('keydown.enter')
    expect(w.emitted('rename')[0][0]).toEqual({ thread: expect.objectContaining({ thread_id: 't1' }), subject: 'New name' })
    // Clicking inside the card while editing must not bubble to open.
    expect(w.emitted('open')).toBeFalsy()
  })

  it('emits copy with the whole thread (list resolves the id)', async () => {
    const w = mountCard(BASE)
    await w.find('[data-testid="thread-card-copy"]').trigger('click')
    expect(w.emitted('copy')[0][0].thread_id).toBe('t1')
    expect(w.emitted('open')).toBeFalsy()
  })
})
