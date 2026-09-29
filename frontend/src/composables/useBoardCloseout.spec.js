import { describe, it, expect, beforeEach, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const m = vi.hoisted(() => ({ getMemoryEntries: vi.fn() }))
vi.mock('@/services/api', () => {
  const api = { products: { getMemoryEntries: (...a) => m.getMemoryEntries(...a) } }
  return { api, default: api }
})
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

import { useBoardCloseout } from './useBoardCloseout'
import { useWebSocketStore } from '@/stores/websocket'

const PROJECT = { id: 'p-1', name: 'Done one', status: 'active', product_id: 'prod-1', implementation_launched_at: '2026-09-26T00:00:00Z' }
const orch = (status, waiting = 0) => ({ agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status, messages_waiting_count: waiting })
const worker = (status) => ({ agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status })

function setup(initialAgents) {
  const agents = ref(initialAgents)
  let board
  const Host = defineComponent({
    setup() {
      board = useBoardCloseout({ agentsFor: () => agents.value, refresh: vi.fn() })
      return () => h('div')
    },
  })
  const wrapper = mount(Host, { global: { plugins: [createPinia()] } })
  return { board, agents, wrapper }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  m.getMemoryEntries.mockResolvedValue({ data: { entries: [] } })
})

describe('useBoardCloseout live behaviours (FE-9681 D3, D4)', () => {
  it('D3: the memory entry landing over the socket flips memory-pending to Review for the focused project', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wsStore = useWebSocketStore()
    const onSpy = vi.spyOn(wsStore, 'on')
    const agents = ref([orch('complete'), worker('complete')])
    let board
    const Host = defineComponent({
      setup() {
        board = useBoardCloseout({ agentsFor: () => agents.value, refresh: vi.fn() })
        return () => h('div')
      },
    })
    mount(Host, { global: { plugins: [pinia] } })
    board.focus(PROJECT)
    await flushPromises()
    expect(board.allJobsTerminal).toBe(true)
    expect(board.showMemoryPending).toBe(true)
    expect(board.showCloseoutButton).toBe(false)

    const memoryHandler = onSpy.mock.calls.find(([type]) => type === 'product:memory:updated')?.[1]
    expect(typeof memoryHandler).toBe('function')
    memoryHandler({ entry: { project_id: 'someone-else' } })
    await nextTick()
    expect(board.showCloseoutButton).toBe(false)

    memoryHandler({ entry: { project_id: 'p-1' } })
    await nextTick()
    expect(board.memoryWritten).toBe(true)
    expect(board.showCloseoutButton).toBe(true)
    expect(board.showMemoryPending).toBe(false)
  })

  it('D4: the unlocked banner clears when every job goes terminal', async () => {
    const { board, agents } = setup([orch('working'), worker('working')])
    board.focus(PROJECT)
    board.onApprovalDecided()
    expect(board.showOrchUnlockedBanner).toBe(true)

    agents.value = [orch('complete'), worker('complete')]
    await nextTick()
    await flushPromises()
    expect(board.showOrchUnlockedBanner).toBe(false)
  })

  it('D4: the unlocked banner clears when the orchestrator drains its inbox', async () => {
    const { board, agents } = setup([orch('working', 2), worker('working')])
    board.focus(PROJECT)
    board.onApprovalDecided()
    expect(board.showOrchUnlockedBanner).toBe(true)

    agents.value = [orch('working', 1), worker('working')]
    await nextTick()
    expect(board.showOrchUnlockedBanner).toBe(true)

    agents.value = [orch('working', 0), worker('working')]
    await nextTick()
    expect(board.showOrchUnlockedBanner).toBe(false)
  })

  it('D4: the unlocked banner clears when the project closes', async () => {
    const { board } = setup([orch('working')])
    board.focus(PROJECT)
    board.onApprovalDecided()
    board.focus({ ...PROJECT, status: 'completed' })
    await nextTick()
    expect(board.showOrchUnlockedBanner).toBe(false)
  })
})
