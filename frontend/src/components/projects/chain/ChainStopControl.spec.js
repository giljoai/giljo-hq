import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ChainStopControl from './ChainStopControl.vue'

const run = {
  id: 'run-1',
  resolved_order: ['p1', 'p2', 'p3', 'p4', 'p5'],
  project_statuses: {
    p1: 'completed',
    p2: 'implementing',
    p3: 'pending',
    p4: 'pending',
    p5: 'pending',
  },
}

const stubs = {
  BaseDialog: {
    props: ['modelValue', 'title', 'confirmLabel', 'type'],
    emits: ['confirm', 'cancel'],
    template: `<div class="base-dialog-stub" v-if="modelValue">
      <span class="stub-title">{{ title }}</span>
      <span class="stub-type">{{ type }}</span>
      <span class="stub-confirm-label">{{ confirmLabel }}</span>
      <div class="stub-body"><slot /></div>
      <button class="stub-confirm" @click="$emit('confirm')">go</button>
      <button class="stub-cancel" @click="$emit('cancel')">no</button>
    </div>`,
  },
  'v-btn': { template: '<button class="v-btn-stub" v-bind="$attrs"><slot /></button>' },
  'v-icon': { template: '<i class="v-icon-stub"><slot /></i>' },
}

function mountControl(props = {}) {
  return mount(ChainStopControl, {
    props: { run, modelValue: false, stopping: false, ...props },
    global: { stubs },
  })
}

describe('ChainStopControl — the button', () => {
  it('renders a Stop chain button', () => {
    const w = mountControl()
    expect(w.find('[data-testid="stop-chain-btn"]').exists()).toBe(true)
    expect(w.find('[data-testid="stop-chain-btn"]').text()).toContain('Stop chain')
  })

  it('asks to open the confirm modal on click rather than stopping directly', async () => {
    const w = mountControl()
    await w.find('[data-testid="stop-chain-btn"]').trigger('click')
    expect(w.emitted('open')).toBeTruthy()
    expect(w.emitted('confirm')).toBeFalsy()
  })

  it('shows no modal until it is opened', () => {
    expect(mountControl().find('.base-dialog-stub').exists()).toBe(false)
  })
})

describe('ChainStopControl — the confirm modal', () => {
  it('opens when the host says so', () => {
    expect(mountControl({ modelValue: true }).find('.base-dialog-stub').exists()).toBe(true)
  })

  it('is a danger dialog titled "Stop chain?" with a Stop chain confirm label', () => {
    const w = mountControl({ modelValue: true })
    expect(w.find('.stub-title').text()).toBe('Stop chain?')
    expect(w.find('.stub-type').text()).toBe('danger')
    expect(w.find('.stub-confirm-label').text()).toBe('Stop chain')
  })

  it('narrates the operator copy with the REAL member numbers', () => {
    const body = mountControl({ modelValue: true }).find('.stub-body').text()
    expect(body).toContain('1 completed stays.')
    expect(body).toContain('2 becomes terminated.')
    expect(body).toContain('3, 4, 5 return to inactive.')
  })

  it('separates the sentences with a space (adjacent spans rendered "stays.2 becomes")', () => {
    const body = mountControl({ modelValue: true }).find('.stub-body').text()
    expect(body).toContain('1 completed stays. 2 becomes terminated. 3, 4, 5 return to inactive.')
  })

  it('carries the operator hint about staging the terminated project again', () => {
    const body = mountControl({ modelValue: true }).find('.stub-body').text()
    expect(body).toContain(
      'You can set the terminated project back to inactive from the Projects list and stage it again.',
    )
  })

  it('renders the numbers from THIS run, not the operator example', () => {
    const w = mountControl({
      modelValue: true,
      run: {
        id: 'run-2',
        resolved_order: ['a', 'b', 'c'],
        project_statuses: { a: 'completed', b: 'completed', c: 'implementing' },
      },
    })
    const body = w.find('.stub-body').text()
    expect(body).toContain('1, 2 completed stay.')
    expect(body).toContain('3 becomes terminated.')
  })

  it('omits the completed sentence when nothing has finished yet', () => {
    const w = mountControl({
      modelValue: true,
      run: {
        id: 'run-3',
        resolved_order: ['a', 'b'],
        project_statuses: { a: 'implementing', b: 'pending' },
      },
    })
    expect(w.find('.stub-body').text()).not.toContain('completed stay')
  })

  it('omits the inactive sentence when every remaining member has started', () => {
    const w = mountControl({
      modelValue: true,
      run: {
        id: 'run-4',
        resolved_order: ['a', 'b'],
        project_statuses: { a: 'completed', b: 'implementing' },
      },
    })
    expect(w.find('.stub-body').text()).not.toContain('return to inactive')
  })

  it('emits confirm when the user confirms', async () => {
    const w = mountControl({ modelValue: true })
    await w.find('.stub-confirm').trigger('click')
    expect(w.emitted('confirm')).toBeTruthy()
  })

  it('emits cancel and never confirm when the user backs out', async () => {
    const w = mountControl({ modelValue: true })
    await w.find('.stub-cancel').trigger('click')
    expect(w.emitted('cancel')).toBeTruthy()
    expect(w.emitted('confirm')).toBeFalsy()
  })
})
