import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const { createMock, roadmapGetMock, pushMock } = vi.hoisted(() => ({
  createMock: vi.fn(),
  roadmapGetMock: vi.fn(),
  pushMock: vi.fn(),
}))

vi.mock('@/services/api', () => {
  const apiObj = {
    sequenceRuns: { create: createMock },
    roadmap: { get: roadmapGetMock },
  }
  return { api: apiObj, default: apiObj }
})

vi.mock('vue-router', () => ({ useRouter: () => ({ push: pushMock }) }))

vi.mock('@/components/sequence/SequenceBulkBar.vue', () => ({
  default: {
    name: 'SequenceBulkBar',
    props: ['count'],
    emits: ['run', 'clear'],
    template: '<div data-testid="bulk-bar" @click="$emit(\'run\')" />',
  },
}))

import SequenceLauncher from '@/components/sequence/SequenceLauncher.vue'

beforeEach(() => {
  vi.clearAllMocks()
  createMock.mockResolvedValue({ data: { id: 'run-99' } })
  roadmapGetMock.mockResolvedValue({ data: { items: [] } })
})

describe('SequenceLauncher — slot contract', () => {
  it('exposes selectedIds, selectedCount, electionActive, toggle, clear — not showModal or resolved', () => {
    const wrapper = mount(SequenceLauncher, { slots: { default: '<span />' } })
    const exposed = wrapper.vm
    expect(typeof exposed.toggle).toBe('function')
    expect(typeof exposed.clear).toBe('function')
    expect(Array.isArray(exposed.selectedIds)).toBe(true)
    expect(typeof exposed.selectedCount).toBe('number')
    expect(typeof exposed.electionActive).toBe('boolean')
    expect(exposed.showModal).toBeUndefined()
    expect(exposed.resolved).toBeUndefined()
  })

  it('passes selectedIds + toggle + clear + electionActive to the default slot', () => {
    let slotProps = null
    mount(SequenceLauncher, {
      slots: {
        default: (props) => {
          slotProps = props
          return '<span />'
        },
      },
    })
    expect(slotProps).not.toBeNull()
    expect('selectedIds' in slotProps).toBe(true)
    expect('toggle' in slotProps).toBe(true)
    expect('clear' in slotProps).toBe(true)
    expect('electionActive' in slotProps).toBe(true)
  })
})

describe('SequenceLauncher — onRunClicked via @run', () => {
  it('does nothing when selection is empty', async () => {
    const wrapper = mount(SequenceLauncher, { slots: { default: '<span />' } })
    await wrapper.find('[data-testid="bulk-bar"]').trigger('click')
    expect(createMock).not.toHaveBeenCalled()
  })

  it('calls api.sequenceRuns.create and router.push to the /jobs multi head project after @run', async () => {
    const wrapper = mount(SequenceLauncher, { slots: { default: '<span />' } })
    wrapper.vm.toggle({ id: 'p-1', name: 'Alpha', taxonomy_alias: 'BE-0001' })
    await wrapper.find('[data-testid="bulk-bar"]').trigger('click')
    await new Promise((r) => setTimeout(r, 0))
    expect(createMock).toHaveBeenCalledTimes(1)
    const body = createMock.mock.calls[0][0]
    expect(body.review_policy).toBe('per_card')
    expect(body.execution_mode).toBe('multi_terminal')
    expect(pushMock).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'ProjectLaunch',
        params: expect.objectContaining({ projectId: 'p-1' }),
        query: expect.objectContaining({ run: 'run-99' }),
      }),
    )
  })

  it('does not render the confirm modal (removed in FE-6165f)', () => {
    const wrapper = mount(SequenceLauncher, { slots: { default: '<span />' } })
    expect(wrapper.find('[data-testid="seq-confirm-modal"]').exists()).toBe(false)
  })
})
