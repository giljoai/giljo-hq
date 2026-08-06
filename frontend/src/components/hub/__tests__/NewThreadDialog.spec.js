/**
 * NewThreadDialog.spec.js — FE-6121, reshaped by FE-9289c
 *
 * The dialog is a name and one hint. FE-6121's DoD-6 (no severity field) still holds;
 * FE-9289c drops the raw project_id / product_id inputs on top of it — a general thread
 * does not need them and a project thread is created BY the project — and puts the new
 * thread id on the clipboard, since handing it to an agent is why the dialog exists.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

// ---- mocks ----
const createThreadMock = vi.fn()
const showToastMock = vi.fn()
const copyMock = vi.fn()

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: copyMock }),
}))

vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
      create: (...args) => createThreadMock(...args),
    },
  },
}))

import NewThreadDialog from '@/components/hub/NewThreadDialog.vue'

const vuetify = createVuetify()
const NEW_ID = '33333333-3333-4333-8333-333333333333'

function mountDialog() {
  return mount(NewThreadDialog, {
    props: { modelValue: true },
    global: { plugins: [createPinia(), vuetify] },
    attachTo: document.body,
  })
}

async function createWith(wrapper, name) {
  wrapper.vm.subject = name
  await wrapper.vm.$nextTick()
  await wrapper.find('[data-testid="new-thread-submit"]').trigger('click')
  await flushPromises()
}

describe('NewThreadDialog', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    createThreadMock.mockReset()
    createThreadMock.mockResolvedValue({ data: { thread_id: NEW_ID, chat_id: 'CHT-0009' } })
    showToastMock.mockClear()
    copyMock.mockReset()
    copyMock.mockResolvedValue(true)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not render the severity selector (FE-6121 DoD-6)', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('[data-testid="new-thread-severity"]').exists()).toBe(false)
  })

  it('offers a name and one hint — no raw project_id / product_id inputs', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('[data-testid="new-thread-subject"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="new-thread-hint"]').text()).toContain('paste into any harness')
    expect(wrapper.find('[data-testid="new-thread-project"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="new-thread-product"]').exists()).toBe(false)
  })

  it('sends only the subject — no severity, no ids', async () => {
    const wrapper = mountDialog()
    await createWith(wrapper, 'Coordination thread')

    expect(createThreadMock).toHaveBeenCalledTimes(1)
    const [body] = createThreadMock.mock.calls[0]
    expect(body.subject).toBe('Coordination thread')
    expect(Object.keys(body)).toEqual(['subject'])
  })

  it('copies the new thread id automatically and says so', async () => {
    const wrapper = mountDialog()
    await createWith(wrapper, 'Laptop interop')

    expect(copyMock).toHaveBeenCalledWith(NEW_ID)
    expect(showToastMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: 'success', message: expect.stringContaining('id copied') }),
    )
    expect(wrapper.emitted('created')).toBeTruthy()
  })

  it('a blocked clipboard is not a failed create — the thread still lands', async () => {
    copyMock.mockResolvedValue(false)
    const wrapper = mountDialog()
    await createWith(wrapper, 'Laptop interop')

    expect(wrapper.emitted('created')).toBeTruthy()
    expect(showToastMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: 'success', message: 'Thread created.' }),
    )
  })

  it('surfaces a create failure and does not emit created', async () => {
    createThreadMock.mockRejectedValue({ response: { data: { detail: 'nope' } } })
    const wrapper = mountDialog()
    await createWith(wrapper, 'Doomed')

    expect(wrapper.get('[data-testid="new-thread-error"]').text()).toContain('nope')
    expect(wrapper.emitted('created')).toBeFalsy()
    expect(copyMock).not.toHaveBeenCalled()
  })
})
