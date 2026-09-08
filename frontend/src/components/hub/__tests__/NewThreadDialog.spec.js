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
import { useProductStore } from '@/stores/products'

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

  it('sends no severity and no raw project id', async () => {
    // WAS `expect(Object.keys(body)).toEqual(['subject'])`, and that assertion is
    // why this defect shipped. FE-9289c's intent was "no raw id INPUTS in the
    // dialog" -- a UI claim. Frozen as an exact payload shape, it became a
    // guarantee that the create could never carry product context, so the day the
    // server started requiring it (Headless-S4) the suite defended the break
    // instead of catching it. The intent is asserted here as what it always was:
    // no severity, no project id, and (below) the product the operator is looking
    // at. A test that pins a payload's exact keys pins every future field out too.
    const wrapper = mountDialog()
    await createWith(wrapper, 'Coordination thread')

    expect(createThreadMock).toHaveBeenCalledTimes(1)
    const [body] = createThreadMock.mock.calls[0]
    expect(body.subject).toBe('Coordination thread')
    expect(body.severity).toBeUndefined()
    expect(body.project_id).toBeUndefined()
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

  // ---- FE-9588: the create must carry the product the operator is looking at ----
  //
  // THE DEFECT, reproduced on a live install: the create POSTed subject alone. On a
  // tenant owning more than one product -- every real user -- the server's
  // `_resolve_create_product_id` reaches `resolve_binding_product(None)` and raises
  // ProductAmbiguousError, so the dialog 400s and no thread can be made from the UI
  // at all.
  //
  // That rejection is CORRECT and is not what is being changed here. It is a BE-6081
  // Tier-2 domain refusal built for AGENTS, whose whole remedy is "retry naming a
  // product" -- an agent reads the list in the error and calls again. A dialog cannot
  // retry; it can only show the text. So the fix belongs on the caller that already
  // knows the answer: the Hub is product-tabbed, and the viewed tab is the
  // unambiguous default. Nothing server-side moves.
  //
  // Asserted at the payload, not through a mocked 400, because the payload is the
  // defect. A test that stubbed the server's rejection would pass against a dialog
  // that swallowed the error just as well as against one that prevented it.
  describe('product binding (FE-9588)', () => {
    const VIEWED = '77777777-7777-4777-8777-777777777777'

    async function createWithViewedProduct(productId, name = 'Night orders') {
      const wrapper = mountDialog()
      // Set AFTER mount: the component resolves the store during setup against the
      // pinia this mount installed, and reads `.value` only when the button is
      // pressed -- so this is the same store instance the dialog will consult.
      useProductStore().currentProductId = productId
      await createWith(wrapper, name)
      return createThreadMock.mock.calls[0]?.[0]
    }

    it('sends the viewed product as product_id', async () => {
      const body = await createWithViewedProduct(VIEWED)
      expect(body.product_id).toBe(VIEWED)
    })

    it('still sends the subject alongside it (control)', async () => {
      // Guards the obvious wrong fix of replacing the payload rather than adding to
      // it -- a create carrying a product and no name is not an improvement.
      const body = await createWithViewedProduct(VIEWED, 'Night orders')
      expect(body.subject).toBe('Night orders')
    })

    it('omits product_id entirely when no product is being viewed', async () => {
      // A fresh install owning zero products is ruling 1's stated exception: the
      // server returns None and the thread is genuinely standalone. Sending an
      // explicit null would be equivalent today, but omitting says what we mean --
      // "we have nothing to offer", not "bind this to nothing".
      const body = await createWithViewedProduct(null)
      expect('product_id' in body).toBe(false)
    })
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
