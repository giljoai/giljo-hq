import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import MemoryEntryRow from '@/components/memory/MemoryEntryRow.vue'
import ThreadCard from '@/components/hub/ThreadCard.vue'
import ApprovalCard from '@/components/orchestration/ApprovalCard.vue'
import AgentDetailsModal from '@/components/projects/AgentDetailsModal.vue'

vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn() }) }))

const TINT = /^background-color: rgba\((\d+, \d+, \d+), 0\.15\); color: rgb\(\1\);(.*)$/

function tint(el) {
  const m = (el.attributes('style') || '').match(TINT)
  return m ? { rgb: m[1], rest: m[2].trim() } : el.attributes('style')
}

describe('tinted badges', () => {
  it('memory tag chip', () => {
    const w = mount(MemoryEntryRow, {
      props: { entry: { id: 'm1', summary: 'x', tags: ['alpha'] }, expanded: false, renderedSummary: '' },
    })
    expect(tint(w.find('[data-test="memory-tag-alpha"]'))).toEqual({ rgb: expect.any(String), rest: '' })
  })

  it('thread card terminal status chip uses the reviewer colour', () => {
    setActivePinia(createPinia())
    const w = mount(ThreadCard, {
      props: { thread: { thread_id: 't1', chat_id: 'CHT-1', subject: 's', status: 'resolved', project_id: null } },
    })
    expect(tint(w.find('[data-testid="thread-card-status"]'))).toEqual({ rgb: '172, 128, 204', rest: '' })
  })

  it('approval card agent badge keeps its radius', () => {
    setActivePinia(createPinia())
    const w = mount(ApprovalCard, {
      props: { approval: { id: 'a1', agent_display_name: 'orchestrator', job_id: 'j', reason: 'r', options: [] } },
    })
    expect(tint(w.find('.approval-card__agent-badge'))).toEqual({ rgb: '212, 176, 138', rest: 'border-radius: 8px;' })
  })

  it('agent details badge for a non-orchestrator agent', () => {
    const w = mount(AgentDetailsModal, {
      props: { modelValue: true, agent: { id: 'j1', agent_id: 'j1', agent_display_name: 'implementer', agent_name: 'impl' } },
      global: { stubs: { 'v-dialog': { template: '<div><slot /></div>', props: ['modelValue'] } } },
    })
    expect(tint(w.find('.agent-tinted-badge'))).toEqual({ rgb: '212, 176, 138', rest: '' })
  })
})
