/**
 * HubComposer.spec.js — FE-6054e, reshaped by FE-9289c
 *
 * The composer collapsed to one row: To [everyone here ▾] + input + send. The two
 * outcomes it has always had are unchanged — a broadcast carries no `to_participant`,
 * a direct post carries one — but they now come from ONE selector instead of a pair of
 * toggle buttons plus a separate dropdown, so these tests drive `recipient` rather
 * than `isBroadcast` + `selectedParticipant`.
 *
 * Everything the old suite pinned is still pinned here:
 *  - broadcast sends without to_participant / direct sends with it
 *  - the auto check-in slider sets loop_directive AND round-trips its interval
 *  - the human user never appears as a recipient
 *  - a freshly-joined agent appears after the refetch the selector triggers
 *  - send guards (empty content, no thread)
 * Plus what the new shape introduces: the slider MOVED behind the To row rather than
 * being removed, Enter sends, and a recipient cannot leak across a thread switch.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { withRealVuetify } from '../../../../tests/helpers/realVuetify'

// ---- mocks ----
const postMessageMock = vi.fn()
const showToastMock = vi.fn()
const participantsMock = vi.fn(() => Promise.resolve({ data: { participants: [] } }))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
      post: (...args) => postMessageMock(...args),
      participants: (...args) => participantsMock(...args),
    },
  },
}))

import HubComposer from '@/components/hub/HubComposer.vue'
import AutoCheckinControls from '@/components/projects/AutoCheckinControls.vue'
import { useCommHubStore } from '@/stores/commHubStore'

const vuetify = createVuetify()
const EVERYONE = '__everyone__'

function mountComposer(activePinia, opts = {}) {
  const { stubs, ...rest } = opts
  return mount(HubComposer, {
    global: {
      plugins: [activePinia, vuetify],
      ...(stubs ? { stubs } : {}),
    },
    ...rest,
  })
}

// FE-9366 — the names below are the verified-working set for rendering the To
// selector's #item / #selection slots for real: VSelect composes VTextField
// (its field/input wrapper, NOT VField directly — a real component detail
// only discoverable by mounting it), which composes VField/VFieldLabel/VInput
// in turn, and the open menu is a real VMenu-over-VOverlay teleported list of
// real VListItem rows. Leaving any one of these on the flat stub either blanks
// the control (VTextField) or leaves the menu unable to open (VMenu/VOverlay).
const REAL_TO_SELECTOR_COMPONENTS = [
  'VSelect', 'VTextField', 'VField', 'VFieldLabel', 'VInput',
  'VMenu', 'VOverlay', 'VList', 'VListItem', 'VIcon',
]

async function mountComposerReal(activePinia) {
  const { plugin, restore } = await withRealVuetify(REAL_TO_SELECTOR_COMPONENTS)
  const wrapper = mount(HubComposer, {
    attachTo: document.body,
    global: {
      plugins: [activePinia, plugin],
    },
  })
  return { wrapper, restore }
}

// Real VMenu opens on a mousedown+click of the field, not the outer control —
// clicking `[data-testid="composer-to"]` alone (the v-input root) never
// dispatches VSelect's own open handler, which is bound to `.v-field`.
async function openRecipientMenu(wrapper) {
  const field = wrapper.get('[data-testid="composer-to"] .v-field')
  await field.trigger('mousedown')
  await field.trigger('click')
  await flushPromises()
  await wrapper.vm.$nextTick()
}


describe('HubComposer', () => {
  let pinia
  let store

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
    postMessageMock.mockReset()
    showToastMock.mockClear()
    participantsMock.mockReset()
    participantsMock.mockResolvedValue({ data: { participants: [] } })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // ---------------------------------------------------------------------------
  // broadcast is the DEFAULT, and it is a visible choice rather than an empty field
  // ---------------------------------------------------------------------------
  it('defaults to "everyone here" and sends without to_participant', async () => {
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockResolvedValue({ data: { message_id: 'msg-new' } })

    const wrapper = mountComposer(pinia)
    expect(wrapper.vm.recipient).toBe(EVERYONE)
    expect(wrapper.vm.recipientItems[0].display_name).toBe('Everyone here')

    wrapper.vm.content = 'Hello agents'
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="send-btn"]').trigger('click')
    await flushPromises()

    expect(postMessageMock).toHaveBeenCalledTimes(1)
    const [threadId, body] = postMessageMock.mock.calls[0]
    expect(threadId).toBe('thr-001')
    expect(body.content).toBe('Hello agents')
    expect(body.to_participant).toBeUndefined()
  })

  // ---------------------------------------------------------------------------
  // direct
  // ---------------------------------------------------------------------------
  it('picking a participant makes the post direct', async () => {
    store.selectedThreadId = 'thr-001'
    store.participantsByThreadId.set('thr-001', [
      {
        participant_id: 'p-impl',
        display_name: 'implementer',
        participant_type: 'agent',
        role: 'implementer',
      },
    ])

    postMessageMock.mockResolvedValue({ data: { message_id: 'msg-direct' } })

    const wrapper = mountComposer(pinia)
    wrapper.vm.recipient = 'p-impl'
    wrapper.vm.content = 'Direct message'
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="send-btn"]').trigger('click')
    await flushPromises()

    expect(postMessageMock).toHaveBeenCalledTimes(1)
    const [, body] = postMessageMock.mock.calls[0]
    expect(body.to_participant).toBe('p-impl')
    expect(body.content).toBe('Direct message')
  })

  it('the caption tells the operator who will actually see it', async () => {
    store.selectedThreadId = 'thr-001'
    store.participantsByThreadId.set('thr-001', [
      { participant_id: 'p-impl', display_name: 'implementer', participant_type: 'agent' },
    ])
    const wrapper = mountComposer(pinia)
    expect(wrapper.get('[data-testid="composer-caption"]').text()).toContain('registered on this thread')

    wrapper.vm.recipient = 'p-impl'
    await wrapper.vm.$nextTick()
    // FE-9365d: the caption NAMES the recipient. "Only that agent" made the operator
    // re-read the field to find out which one; the point of the caption is that they
    // do not have to.
    expect(wrapper.get('[data-testid="composer-caption"]').text()).toContain('Direct — only')
  })

  // ---------------------------------------------------------------------------
  // FE-9365d — the `??` defect, now pinned by RENDERING the real component
  // rather than reading its source (FE-9366).
  //
  // Reported live with a screenshot: every option in the To dropdown rendered as a bare
  // `??` chip with no name, and the collapsed control showed `??` too.
  //
  // Cause — a Vuetify 3 -> 4 migration miss. VSelect.js now passes `item: item.raw`
  // into the #item and #selection slots (the InternalItem arrives separately as
  // `internalItem`). The slots read `item.title` / `item.value`, which are undefined on
  // the raw object, so agentAbbr(undefined) returned the literal '??', the name rendered
  // empty, and `undefined !== EVERYONE` was true — which is why even the broadcast row
  // wore an agent badge.
  //
  // The old suite drove `wrapper.vm.recipient` directly and asserted on the emitted
  // body, so every one of those tests passed against a dropdown the operator could not
  // read. FE-9365d's interim fix was a source-text guard — grepping HubComposer.vue's
  // template for `item.title` / `item.value` — because tests/setup.js's flat VSelect
  // stub renders only the default slot, so #item / #selection never executed here and
  // the bug's own layer was unreachable at runtime. `withRealVuetify()` (FE-9366) closes
  // that gap: these two tests mount the REAL VSelect/VMenu/VListItem chain and read the
  // actual rendered DOM, which is where the defect actually lived and where a
  // regression will actually be caught again.
  // ---------------------------------------------------------------------------
  it('the closed To control renders the real selection slot — mascot, name, never `??`', async () => {
    store.selectedThreadId = 'thr-001'
    store.participantsByThreadId.set('thr-001', [
      { participant_id: 'p-lane-a', display_name: 'LANE_A', participant_type: 'agent', role: 'implementer', harness: 'claude-code' },
    ])

    const { wrapper, restore } = await mountComposerReal(pinia)
    try {
      const control = wrapper.get('[data-testid="composer-to"]')
      expect(control.html()).not.toContain('??')
      expect(control.find('img.hub-composer__mascot').exists()).toBe(true)
      expect(control.find('.hub-composer__agent-name').text()).toBe('Everyone here')
      // The default recipient is the broadcast row, so the closed control must not
      // wear an agent badge — that was the other half of the `??` defect (FE-9365d):
      // `undefined !== EVERYONE` was true, so even the broadcast selection got one.
      expect(control.find('.hub-composer__agent-badge').exists()).toBe(false)
    } finally {
      wrapper.unmount()
      restore()
    }
  })

  it('opening the To menu renders real item rows — mascot/no-badge for Everyone, real initials and harness for an agent', async () => {
    store.selectedThreadId = 'thr-001'
    store.participantsByThreadId.set('thr-001', [
      { participant_id: 'p-lane-a', display_name: 'LANE_A', participant_type: 'agent', role: 'implementer', harness: 'claude-code' },
    ])
    // The menu open handler (onRecipientMenu) refetches participants (FE-6121 DoD-3) —
    // the refetch REPLACES participantsByThreadId, so the mock has to answer with the
    // same row or the list set above ends up looking correct except a fetch we can't see.
    participantsMock.mockResolvedValue({
      data: {
        participants: [
          { participant_id: 'p-lane-a', display_name: 'LANE_A', participant_type: 'agent', role: 'implementer', harness: 'claude-code' },
        ],
      },
    })

    const { wrapper, restore } = await mountComposerReal(pinia)
    try {
      await openRecipientMenu(wrapper)

      const menu = document.querySelector('.hub-composer__menu')
      expect(menu).not.toBeNull()
      expect(menu.innerHTML).not.toContain('??')

      const rows = document.querySelectorAll('[data-testid="composer-to-item"]')
      expect(rows).toHaveLength(2)

      const [everyoneRow, agentRow] = rows
      expect(everyoneRow.querySelector('img.hub-composer__mascot')).not.toBeNull()
      expect(everyoneRow.querySelector('.agent-badge-sq')).toBeNull()
      expect(everyoneRow.querySelector('.hub-composer__option-name').textContent).toBe('Everyone here')
      expect(everyoneRow.querySelector('.hub-composer__option-sub').textContent).toBe('broadcast · 1 registered')

      // agentAbbr('LANE_A') splits on [-_\s]+ -> ['LANE', 'A'] -> 'L' + 'A'
      expect(agentRow.querySelector('.agent-badge-sq').textContent).toBe('LA')
      expect(agentRow.querySelector('img.hub-composer__mascot')).toBeNull()
      expect(agentRow.querySelector('.hub-composer__option-name').textContent).toBe('LANE_A')
      expect(agentRow.querySelector('.hub-composer__option-sub').textContent).toBe('direct · claude-code')
    } finally {
      wrapper.unmount()
      restore()
    }
  })

  it('builds recipient items from the raw participant, so the slots have real fields', () => {
    // The slot templates read display_name / participant_id / harness / role straight off
    // the item, because Vuetify 4 hands them the RAW object. If the items were ever
    // reduced back to a {title, value} pair the slots would render blanks and `??` again.
    store.selectedThreadId = 'thr-001'
    store.participantsByThreadId.set('thr-001', [
      { participant_id: 'p-lane-a', display_name: 'LANE_A', participant_type: 'agent', role: 'implementer', harness: 'claude-code' },
    ])
    const wrapper = mountComposer(pinia)

    const [broadcast, agent] = wrapper.vm.recipientItems
    expect(broadcast.participant_id).toBe(EVERYONE)
    expect(broadcast.display_name).toBe('Everyone here')
    expect(agent).toMatchObject({
      participant_id: 'p-lane-a',
      display_name: 'LANE_A',
      role: 'implementer',
      harness: 'claude-code',
    })
  })

  it('labels the broadcast row with a live registered count and agents with their harness', () => {
    store.selectedThreadId = 'thr-001'
    store.participantsByThreadId.set('thr-001', [
      { participant_id: 'a', display_name: 'LANE_A', participant_type: 'agent', harness: 'claude-code' },
      { participant_id: 'b', display_name: 'LANE_B', participant_type: 'agent', harness: 'generic' },
    ])
    const wrapper = mountComposer(pinia)

    expect(wrapper.vm.optionSubLabel({ participant_id: EVERYONE })).toBe('broadcast · 2 registered')
    expect(wrapper.vm.optionSubLabel({ participant_id: 'a', harness: 'claude-code' })).toBe('direct · claude-code')
    // The `generic` token is the resolver's fail-safe floor, not a harness name.
    expect(wrapper.vm.optionSubLabel({ participant_id: 'b', harness: 'generic' })).toBe('direct · Generic Harness')
  })

  it('Mark handled clears the baton without posting anything', async () => {
    // FE-9365g: the release valve. Until this existed the only way to clear
    // "waiting on you" was to post a message, so a thread needing nothing stayed
    // gold forever. 'none' is the reserved no-owner target.
    store.selectedThreadId = 'thr-001'
    store.currentUserId = undefined
    const passBatonSpy = vi.spyOn(store, 'passBaton').mockResolvedValue({ thread_id: 'thr-001', next_action_owner: null })

    const wrapper = mountComposer(pinia)
    // Force the your-turn surface visible regardless of user-store wiring.
    wrapper.vm.$.setupState // touch
    // Drive the handler directly — the badge row is v-if'd on isYourTurn, which
    // depends on the user store; the CONTRACT under test is what the button does.
    await wrapper.vm.onMarkHandled()

    expect(passBatonSpy).toHaveBeenCalledWith('thr-001', 'none')
    expect(postMessageMock).not.toHaveBeenCalled()
  })

  it('a recipient picked on one thread does not leak onto the next', async () => {
    store.selectedThreadId = 'thr-001'
    store.participantsByThreadId.set('thr-001', [
      { participant_id: 'p-impl', display_name: 'implementer', participant_type: 'agent' },
    ])
    const wrapper = mountComposer(pinia)
    wrapper.vm.recipient = 'p-impl'
    await wrapper.vm.$nextTick()

    // Switching threads: p-impl does not exist over there, so a post aimed at it
    // would go to nobody. The selector resets to the broadcast default.
    store.selectedThreadId = 'thr-002'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.recipient).toBe(EVERYONE)
  })

  // ---------------------------------------------------------------------------
  // Enter sends (the composer is one line; ceremony was the thing being removed)
  // ---------------------------------------------------------------------------
  it('Enter sends the message', async () => {
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockResolvedValue({ data: { message_id: 'msg-enter' } })

    const wrapper = mountComposer(pinia)
    wrapper.vm.content = 'sent with the keyboard'
    await wrapper.vm.$nextTick()

    await wrapper.get('textarea[data-testid="message-input"]').trigger('keydown.enter')
    await flushPromises()

    expect(postMessageMock).toHaveBeenCalledTimes(1)
    expect(postMessageMock.mock.calls[0][1].content).toBe('sent with the keyboard')
  })

  // ---------------------------------------------------------------------------
  // TSK-9295 — Enter must not send while an IME is composing.
  //
  // A user typing Japanese, Chinese or Korean presses Enter to CONFIRM a candidate
  // word, not to send. That keydown reaches this handler anyway: `.exact` filters
  // ctrl/alt/shift/meta, not composition. The half-written message posted mid-sentence
  // instead of the candidate committing to the input.
  //
  // Both signals are pinned because they cover different browsers. `isComposing` is the
  // standard one; `keyCode === 229` is the fallback for browsers that dispatch
  // compositionend BEFORE the keydown, leaving isComposing false on an Enter that is
  // still confirming a candidate.
  // ---------------------------------------------------------------------------
  it('Enter during an IME composition does NOT send (isComposing)', async () => {
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockResolvedValue({ data: { message_id: 'msg-ime' } })

    const wrapper = mountComposer(pinia)
    wrapper.vm.content = 'にほん'
    await wrapper.vm.$nextTick()

    await wrapper
      .get('textarea[data-testid="message-input"]')
      .trigger('keydown.enter', { isComposing: true, keyCode: 229 })
    await flushPromises()

    expect(postMessageMock).not.toHaveBeenCalled()
    // the operator's half-written text is still there to keep composing
    expect(wrapper.vm.content).toBe('にほん')
  })

  it('Enter during an IME composition does NOT send (legacy keyCode 229 only)', async () => {
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockResolvedValue({ data: { message_id: 'msg-ime-legacy' } })

    const wrapper = mountComposer(pinia)
    wrapper.vm.content = '中文'
    await wrapper.vm.$nextTick()

    // compositionend fired before keydown, so isComposing is already false — keyCode is
    // the only remaining evidence that this Enter is a candidate commit. Built as a real
    // KeyboardEvent rather than via trigger('keydown.enter', ...), because that shorthand
    // stamps keyCode 13 over the value under test and the case would never be exercised.
    const textarea = wrapper.get('textarea[data-testid="message-input"]').element
    const legacy = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    Object.defineProperty(legacy, 'isComposing', { value: false })
    Object.defineProperty(legacy, 'keyCode', { value: 229 })
    textarea.dispatchEvent(legacy)
    await flushPromises()

    expect(postMessageMock).not.toHaveBeenCalled()
    expect(wrapper.vm.content).toBe('中文')
  })

  it('does NOT preventDefault on a composing Enter — the IME must still commit', async () => {
    store.selectedThreadId = 'thr-001'
    const wrapper = mountComposer(pinia)
    wrapper.vm.content = 'にほん'
    await wrapper.vm.$nextTick()

    // The load-bearing half. `.prevent` as a TEMPLATE modifier runs before the handler
    // and fired on the composing keydown too, so suppressing the send alone would still
    // have stopped the IME from committing the candidate — the message would not post
    // AND the word would not commit. preventDefault belongs on the send path only.
    const textarea = wrapper.get('textarea[data-testid="message-input"]').element
    const composing = new KeyboardEvent('keydown', {
      key: 'Enter',
      bubbles: true,
      cancelable: true,
    })
    Object.defineProperty(composing, 'isComposing', { value: true })
    Object.defineProperty(composing, 'keyCode', { value: 229 })
    textarea.dispatchEvent(composing)
    await flushPromises()

    expect(composing.defaultPrevented).toBe(false)
    expect(postMessageMock).not.toHaveBeenCalled()
  })

  it('a normal Enter still sends AND still suppresses the newline', async () => {
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockResolvedValue({ data: { message_id: 'msg-plain' } })

    const wrapper = mountComposer(pinia)
    wrapper.vm.content = 'plain enter'
    await wrapper.vm.$nextTick()

    const textarea = wrapper.get('textarea[data-testid="message-input"]').element
    const plain = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    Object.defineProperty(plain, 'isComposing', { value: false })
    Object.defineProperty(plain, 'keyCode', { value: 13 })
    textarea.dispatchEvent(plain)
    await flushPromises()

    expect(postMessageMock).toHaveBeenCalledTimes(1)
    expect(postMessageMock.mock.calls[0][1].content).toBe('plain enter')
    // Enter is the send key here, so it must not also insert a newline.
    expect(plain.defaultPrevented).toBe(true)
  })
  // ---------------------------------------------------------------------------
  // loop directive — REMOVED from the composer (FE-9365d, absorbing FE-9296b)
  // ---------------------------------------------------------------------------
  it('has no auto check-in control at all — not on the face, not behind a toggle', async () => {
    // The four tests that used to live here pinned the slider IN the composer, first on
    // its face and then one click away. Operator decision (2026-08-04): it leaves
    // entirely. Asking "how often should they poll?" on the send path made a cadence
    // decision out of every message; the framing belongs in the protocol prompts, where
    // a durable default lives, and the loop_directive plumbing stays reachable over MCP.
    store.selectedThreadId = 'thr-001'
    const wrapper = mountComposer(pinia)

    expect(wrapper.findComponent(AutoCheckinControls).exists()).toBe(false)
    expect(wrapper.find('[data-testid="composer-cadence-toggle"]').exists()).toBe(false)
  })

  it('sends no loop fields in the body', async () => {
    // The composer can no longer arm a directive, so the body must carry neither field —
    // not `false`, not `null`, absent. A stray `loop_directive: false` would still be a
    // cadence decision the operator never made.
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockResolvedValue({ data: { message_id: 'msg-noloop' } })

    const wrapper = mountComposer(pinia)
    wrapper.vm.content = 'No loop'
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="send-btn"]').trigger('click')
    await flushPromises()

    const [, body] = postMessageMock.mock.calls[0]
    expect(body.loop_directive).toBeUndefined()
    expect(body.loop_interval_minutes).toBeUndefined()
  })

  // ---------------------------------------------------------------------------
  // selector reactivity (FE-6121 DoD-3) — newly-joined agents appear w/o refresh
  // ---------------------------------------------------------------------------
  it('opening the To selector refetches participants', async () => {
    store.selectedThreadId = 'thr-001'
    const wrapper = mountComposer(pinia)
    participantsMock.mockClear()

    wrapper.vm.onRecipientMenu(true)
    await flushPromises()

    expect(participantsMock).toHaveBeenCalledWith('thr-001')
  })

  it('a freshly-joined agent appears in the To items after a participants refetch', async () => {
    store.selectedThreadId = 'thr-001'
    store.participantsByThreadId.set('thr-001', [
      { participant_id: 'p-old', display_name: 'agent-legacy', participant_type: 'agent' },
    ])

    const wrapper = mountComposer(pinia)
    expect(wrapper.vm.recipientItems.map((p) => p.participant_id)).toEqual([EVERYONE, 'p-old'])

    // Simulate the refetch (triggered by opening the selector) returning a NEW join.
    participantsMock.mockResolvedValueOnce({
      data: {
        participants: [
          { participant_id: 'p-old', display_name: 'agent-legacy', participant_type: 'agent' },
          { participant_id: 'p-new', display_name: 'CI2_lane', participant_type: 'agent' },
        ],
      },
    })
    wrapper.vm.onRecipientMenu(true)
    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.recipientItems.map((p) => p.participant_id)).toEqual([EVERYONE, 'p-old', 'p-new'])
  })

  it('the human user is never offered as a recipient', async () => {
    store.selectedThreadId = 'thr-001'
    store.participantsByThreadId.set('thr-001', [
      { participant_id: 'p-user', display_name: 'Patrik', participant_type: 'user' },
      { participant_id: 'p-agent', display_name: 'CI2_lane', participant_type: 'agent' },
    ])
    const wrapper = mountComposer(pinia)
    expect(wrapper.vm.recipientItems.map((p) => p.participant_id)).toEqual([EVERYONE, 'p-agent'])
  })

  // ---------------------------------------------------------------------------
  // TSK-9300 — a DECLINED post must not look like a sent one.
  //
  // BE-9292a made the post route able to refuse at HTTP 200. Before the store learned
  // to treat that as a failure, this composer cleared the box and toasted "Message
  // sent." on a message the server never wrote — the operator's text gone, with no
  // signal. Driven through the REAL store here, not a stubbed action, because the
  // defect lived in the seam between them.
  // ---------------------------------------------------------------------------
  const POST_REFUSAL = {
    success: false,
    error: 'TARGET_IS_A_DISPLAY_NAME',
    thread_id: 'thr-001',
    requested: 'implementer',
    registered_id: 'agent-7',
    hint: 'implementer is a display name held by agent-7 — address agent-7 instead.',
  }

  it('KEEPS the operator text when the server declines the post', async () => {
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockResolvedValue({ data: POST_REFUSAL })

    const wrapper = mountComposer(pinia)
    wrapper.vm.content = 'a message worth not losing'
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="send-btn"]').trigger('click')
    await flushPromises()

    // the irreversible step must not have happened
    expect(wrapper.vm.content).toBe('a message worth not losing')
  })

  it('tells the operator WHY it was declined, using the server hint', async () => {
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockResolvedValue({ data: POST_REFUSAL })

    const wrapper = mountComposer(pinia)
    wrapper.vm.content = 'hello'
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="send-btn"]').trigger('click')
    await flushPromises()

    expect(showToastMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('agent-7') }),
    )
    // and emphatically NOT a success toast
    expect(showToastMock).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'success', message: 'Message sent.' }),
    )
  })

  it('a real send still clears the box and reports success', async () => {
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockResolvedValue({ data: { message_id: 'm-ok', thread_id: 'thr-001' } })

    const wrapper = mountComposer(pinia)
    wrapper.vm.content = 'this one lands'
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="send-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.vm.content).toBe('')
    expect(showToastMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: 'success', message: 'Message sent.' }),
    )
  })

  // ---------------------------------------------------------------------------
  // send disabled guards
  // ---------------------------------------------------------------------------
  it('send button is disabled when content is empty', async () => {
    store.selectedThreadId = 'thr-001'
    const wrapper = mountComposer(pinia)
    wrapper.vm.content = ''
    await wrapper.vm.$nextTick()
    const btn = wrapper.find('[data-testid="send-btn"]')
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('send button is disabled when no thread is selected', async () => {
    const wrapper = mountComposer(pinia)
    wrapper.vm.content = 'Some content'
    await wrapper.vm.$nextTick()
    const btn = wrapper.find('[data-testid="send-btn"]')
    expect(btn.attributes('disabled')).toBeDefined()
  })
})
