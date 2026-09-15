import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createVuetify } from 'vuetify'

const copyMock = vi.fn(() => Promise.resolve(true))
const showToastMock = vi.fn()

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: copyMock, copied: { value: false } }),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

import ThreadCreatedDialog, {
  isThreadCreatedHintHidden,
} from '@/components/hub/ThreadCreatedDialog.vue'

const HIDE_HINT_KEY = 'giljo.hub.threadCreatedHintHidden'

const vuetify = createVuetify()

const THREAD = {
  thread_id: '972cd252-dd0f-42e0-9ddc-0dc71356b6c6',
  chat_id: 'CHT-0001',
}

function mountDialog(props = {}) {
  return mount(ThreadCreatedDialog, {
    props: { modelValue: true, thread: THREAD, ...props },
    global: { plugins: [vuetify] },
    attachTo: document.body,
  })
}

describe('ThreadCreatedDialog', () => {
  beforeEach(() => {
    copyMock.mockClear()
    showToastMock.mockClear()
    window.localStorage.getItem.mockReset()
    window.localStorage.setItem.mockReset()
    window.localStorage.getItem.mockReturnValue(null)
  })

  afterEach(() => {
    copyMock.mockClear()
    showToastMock.mockClear()
  })

  it('renders the thread_id as the copyable value and CHT-#### as the label', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('[data-testid="thread-created-thread-id"]').text()).toBe(THREAD.thread_id)
    expect(wrapper.find('[data-testid="thread-created-chat-id"]').text()).toBe('CHT-0001')
  })

  it('shows the operator-facing lead copy', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('[data-testid="thread-created-lead"]').text()).toContain(
      'Copy this and tell agents to message you in this thread.',
    )
  })

  it('copy button copies the thread_id (not the chat id)', async () => {
    const wrapper = mountDialog()
    await wrapper.find('[data-testid="thread-created-copy"]').trigger('click')
    await flushPromises()
    expect(copyMock).toHaveBeenCalledTimes(1)
    expect(copyMock).toHaveBeenCalledWith(THREAD.thread_id)
  })

  it('persists never-show-again to localStorage when checkbox is ticked then closed', async () => {
    const wrapper = mountDialog()

    wrapper.vm.dontShowAgain = true
    await wrapper.vm.$nextTick()
    await wrapper.find('[data-testid="thread-created-done"]').trigger('click')

    expect(window.localStorage.setItem).toHaveBeenCalledWith(HIDE_HINT_KEY, '1')
  })

  it('does NOT persist the opt-out when closed without ticking the checkbox', async () => {
    const wrapper = mountDialog()
    await wrapper.find('[data-testid="thread-created-done"]').trigger('click')
    expect(window.localStorage.setItem).not.toHaveBeenCalled()
  })

  it('isThreadCreatedHintHidden reflects the persisted localStorage flag', () => {
    window.localStorage.getItem.mockReturnValue('1')
    expect(isThreadCreatedHintHidden()).toBe(true)
    window.localStorage.getItem.mockReturnValue(null)
    expect(isThreadCreatedHintHidden()).toBe(false)
  })

  it('emits update:modelValue false on close', async () => {
    const wrapper = mountDialog()
    await wrapper.find('[data-testid="thread-created-done"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([false])
  })
})
