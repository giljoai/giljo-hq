import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { withRealVuetify } from '../../../../tests/helpers/realVuetify'

const postMessageMock = vi.fn()
const showToastMock = vi.fn()
const participantsMock = vi.fn(() => Promise.resolve({ data: { participants: [] } }))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  route: { path: '/hub', query: {} },
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerMock.push, replace: routerMock.replace }),
  useRoute: () => routerMock.route,
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
    routerMock.push.mockClear()
    routerMock.replace.mockClear()
    routerMock.route.query = {}
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

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
    expect(wrapper.get('[data-testid="composer-caption"]').text()).toContain('Direct — only')
  })

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
    expect(wrapper.vm.optionSubLabel({ participant_id: 'b', harness: 'generic' })).toBe('direct · Generic Harness')
  })

  it('Mark handled clears the baton without posting anything', async () => {
    store.selectedThreadId = 'thr-001'
    store.currentUserId = undefined
    const passBatonSpy = vi.spyOn(store, 'passBaton').mockResolvedValue({ thread_id: 'thr-001', next_action_owner: null })

    const wrapper = mountComposer(pinia)
    wrapper.vm.$.setupState
    await wrapper.vm.markHandled()

    expect(passBatonSpy).toHaveBeenCalledWith('thr-001', 'none')
    expect(postMessageMock).not.toHaveBeenCalled()
  })

  it('Mark handled drops the stale focus params from the route', async () => {
    store.selectedThreadId = 'thr-001'
    vi.spyOn(store, 'passBaton').mockResolvedValue({ thread_id: 'thr-001', next_action_owner: null })
    routerMock.route.query = { thread: 'thr-001', focus: 'baton', message: 'msg-1' }

    const wrapper = mountComposer(pinia)
    await wrapper.vm.markHandled()

    expect(routerMock.replace).toHaveBeenCalledTimes(1)
    expect(routerMock.replace).toHaveBeenCalledWith({ path: '/hub', query: { thread: 'thr-001' } })
    expect(routerMock.push).not.toHaveBeenCalled()
  })

  it('Mark handled leaves an ordinary arrival route untouched', async () => {
    store.selectedThreadId = 'thr-001'
    vi.spyOn(store, 'passBaton').mockResolvedValue({ thread_id: 'thr-001', next_action_owner: null })
    routerMock.route.query = { thread: 'thr-001' }

    const wrapper = mountComposer(pinia)
    await wrapper.vm.markHandled()

    expect(routerMock.replace).not.toHaveBeenCalled()
  })

  it('a recipient picked on one thread does not leak onto the next', async () => {
    store.selectedThreadId = 'thr-001'
    store.participantsByThreadId.set('thr-001', [
      { participant_id: 'p-impl', display_name: 'implementer', participant_type: 'agent' },
    ])
    const wrapper = mountComposer(pinia)
    wrapper.vm.recipient = 'p-impl'
    await wrapper.vm.$nextTick()

    store.selectedThreadId = 'thr-002'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.recipient).toBe(EVERYONE)
  })

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
    expect(wrapper.vm.content).toBe('にほん')
  })

  it('Enter during an IME composition does NOT send (legacy keyCode 229 only)', async () => {
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockResolvedValue({ data: { message_id: 'msg-ime-legacy' } })

    const wrapper = mountComposer(pinia)
    wrapper.vm.content = '中文'
    await wrapper.vm.$nextTick()

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
    expect(plain.defaultPrevented).toBe(true)
  })
  it('has no auto check-in control at all — not on the face, not behind a toggle', async () => {
    store.selectedThreadId = 'thr-001'
    const wrapper = mountComposer(pinia)

    expect(wrapper.find('[data-testid="auto-checkin"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="composer-cadence-toggle"]').exists()).toBe(false)
  })

  it('sends no loop fields in the body', async () => {
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
      { participant_id: 'p-user', display_name: 'Sam Rivera', participant_type: 'user' },
      { participant_id: 'p-agent', display_name: 'CI2_lane', participant_type: 'agent' },
    ])
    const wrapper = mountComposer(pinia)
    expect(wrapper.vm.recipientItems.map((p) => p.participant_id)).toEqual([EVERYONE, 'p-agent'])
  })

  function postRefusal() {
    const err = new Error('Request failed with status code 409')
    err.response = {
      status: 409,
      data: {
        error_code: 'TARGET_IS_A_DISPLAY_NAME',
        message: 'implementer is a display name held by agent-7 — address agent-7 instead.',
        context: { thread_id: 'thr-001', requested: 'implementer', registered_id: 'agent-7' },
      },
    }
    return err
  }

  it('KEEPS the operator text when the server declines the post', async () => {
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockRejectedValue(postRefusal())

    const wrapper = mountComposer(pinia)
    wrapper.vm.content = 'a message worth not losing'
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="send-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.vm.content).toBe('a message worth not losing')
  })

  it('tells the operator WHY it was declined, using the server hint', async () => {
    store.selectedThreadId = 'thr-001'
    postMessageMock.mockRejectedValue(postRefusal())

    const wrapper = mountComposer(pinia)
    wrapper.vm.content = 'hello'
    await wrapper.vm.$nextTick()

    await wrapper.find('[data-testid="send-btn"]').trigger('click')
    await flushPromises()

    expect(showToastMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('agent-7') }),
    )
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
