import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ThreadDeletedDialog from '@/components/hub/ThreadDeletedDialog.vue'

const listItemWithAppend = {
  template: `<div class="v-list-item"><slot /><slot name="prepend" /><slot name="append" /></div>`,
}

const THREAD_A = {
  thread_id: 'thr-aaa-111',
  chat_id: 'CHT-0002',
  subject: 'Alpha coordination',
}

const THREAD_B = {
  thread_id: 'thr-bbb-222',
  chat_id: 'CHT-0005',
  subject: '',
}

function mountDialog(props = {}) {
  return mount(ThreadDeletedDialog, {
    props: {
      modelValue: true,
      deletedThreads: [THREAD_A],
      restoringId: null,
      ...props,
    },
    global: {
      stubs: {
        'v-list-item': listItemWithAppend,
      },
      directives: {
        draggable: {},
      },
    },
  })
}

describe('ThreadDeletedDialog', () => {
  it('renders each deleted thread with chat_id as title and subject as subtitle', () => {
    const wrapper = mountDialog({ deletedThreads: [THREAD_A, THREAD_B] })
    const text = wrapper.text()
    expect(text).toContain('CHT-0002')
    expect(text).toContain('Alpha coordination')
    expect(text).toContain('CHT-0005')
    expect(text).toContain('(no subject)')
  })

  it('emits restore with the thread when the restore button is clicked', async () => {
    const wrapper = mountDialog()
    const btn = wrapper.find('[data-testid="restore-thread"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('restore')).toBeTruthy()
    expect(wrapper.emitted('restore')[0][0]).toEqual(THREAD_A)
  })

  it('renders the empty state when deletedThreads is empty', () => {
    const wrapper = mountDialog({ deletedThreads: [] })
    expect(wrapper.text()).toContain('No deleted threads')
    expect(wrapper.find('[data-testid="restore-thread"]').exists()).toBe(false)
  })

  it('disables the restore button for the thread whose id matches restoringId', () => {
    const wrapper = mountDialog({ restoringId: THREAD_A.thread_id })
    const btn = wrapper.find('[data-testid="restore-thread"]')
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('does not disable the restore button when restoringId is null', () => {
    const wrapper = mountDialog({ restoringId: null })
    const btn = wrapper.find('[data-testid="restore-thread"]')
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it('renders the data-testid on the root card', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('[data-testid="thread-deleted-dialog"]').exists()).toBe(true)
  })
})
