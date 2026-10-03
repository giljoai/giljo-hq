import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import {
  useJobsBoardLiveRefresh,
  AGENT_REFRESH_EVENTS,
  BOARD_REFRESH_EVENTS,
} from './useJobsBoardLiveRefresh'

function fakeWs() {
  const handlers = {}
  return {
    handlers,
    on: vi.fn((type, fn) => {
      ;(handlers[type] ||= new Set()).add(fn)
      return () => handlers[type].delete(fn)
    }),
    fire(type, payload) {
      for (const fn of handlers[type] || []) fn(payload)
    },
  }
}

function harness(opts) {
  const Comp = defineComponent({
    setup() {
      useJobsBoardLiveRefresh(opts)
      return () => h('div')
    },
  })
  return mount(Comp)
}

let ws
let refreshAgents
let refreshBoard
const onBoard = new Set(['p1', 'p2'])

beforeEach(() => {
  vi.useFakeTimers()
  ws = fakeWs()
  refreshAgents = vi.fn()
  refreshBoard = vi.fn()
})
afterEach(() => {
  vi.useRealTimers()
})

function mountDefault() {
  return harness({ wsStore: ws, isOnBoard: (pid) => onBoard.has(pid), refreshAgents, refreshBoard, delay: 300 })
}

describe('useJobsBoardLiveRefresh (FE-9689)', () => {
  it('listens to agent, job, message, project and chain events', () => {
    for (const ev of ['agent:status_changed', 'agent:created', 'agent:silent', 'job:progress_update', 'thread_message']) {
      expect(AGENT_REFRESH_EVENTS).toContain(ev)
    }
    for (const ev of ['project:staging_complete', 'project:implementation_launched', 'project:mission_updated', 'project_update', 'sequence:updated']) {
      expect(BOARD_REFRESH_EVENTS).toContain(ev)
    }
  })

  it('an agent status change reloads only that card, once per burst', () => {
    mountDefault()
    ws.fire('agent:status_changed', { project_id: 'p1', status: 'working' })
    ws.fire('job:progress_update', { project_id: 'p1' })
    ws.fire('agent:status_changed', { project_id: 'p1', status: 'complete' })
    expect(refreshAgents).not.toHaveBeenCalled()
    vi.advanceTimersByTime(300)
    expect(refreshAgents).toHaveBeenCalledTimes(1)
    expect(refreshAgents).toHaveBeenCalledWith('p1')
    expect(refreshBoard).not.toHaveBeenCalled()
  })

  it('two cards changing reload both cards', () => {
    mountDefault()
    ws.fire('agent:status_changed', { project_id: 'p1' })
    ws.fire('agent:status_changed', { project_id: 'p2' })
    vi.advanceTimersByTime(300)
    expect(refreshAgents.mock.calls.map((c) => c[0]).sort()).toEqual(['p1', 'p2'])
  })

  it('an agent event for a project not on the board reloads the board (it may have just arrived)', () => {
    mountDefault()
    ws.fire('agent:created', { project_id: 'p-new' })
    vi.advanceTimersByTime(300)
    expect(refreshAgents).not.toHaveBeenCalled()
    expect(refreshBoard).toHaveBeenCalledTimes(1)
  })

  it('project and chain events reload the board once per burst, naming the projects that moved', () => {
    mountDefault()
    ws.fire('project_update', { project_id: 'p1' })
    ws.fire('sequence:updated', { run_id: 'r1' })
    ws.fire('project:implementation_launched', { project_id: 'p2' })
    vi.advanceTimersByTime(300)
    expect(refreshBoard).toHaveBeenCalledTimes(1)
    expect(refreshBoard.mock.calls[0][0].sort()).toEqual(['p1', 'p2'])
  })

  it('other activity in a project this board does not show is ignored', () => {
    mountDefault()
    ws.fire('agent:status_changed', { project_id: 'p-elsewhere' })
    ws.fire('job:progress_update', { project_id: 'p-elsewhere' })
    vi.advanceTimersByTime(1000)
    expect(refreshAgents).not.toHaveBeenCalled()
    expect(refreshBoard).not.toHaveBeenCalled()
  })

  it('coming back to the tab catches up', () => {
    mountDefault()
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    vi.advanceTimersByTime(300)
    expect(refreshBoard).toHaveBeenCalledTimes(1)
  })

  it('stops listening when the board unmounts', () => {
    const wrapper = mountDefault()
    wrapper.unmount()
    ws.fire('agent:status_changed', { project_id: 'p1' })
    ws.fire('project_update', {})
    document.dispatchEvent(new Event('visibilitychange'))
    vi.advanceTimersByTime(1000)
    expect(refreshAgents).not.toHaveBeenCalled()
    expect(refreshBoard).not.toHaveBeenCalled()
  })
})
