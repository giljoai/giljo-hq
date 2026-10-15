import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import ThreadCard from '@/components/hub/ThreadCard.vue'

const vuetify = createVuetify()
const mountCard = (thread) => mount(ThreadCard, { props: { thread }, global: { plugins: [vuetify] } })
const BASE = { thread_id: 't1', chat_id: 'CHT-0001', subject: 'Laptop interop', status: 'open', project_id: null, participants: [], last_message: null }

describe('ThreadCard resolve / reopen control (FE-9746)', () => {
  it.each(['open', 'active'])('shows "Mark resolved" with a check-circle icon on a %s card', (status) => {
    const w = mountCard({ ...BASE, status })
    const btn = w.get('[data-testid="thread-card-resolve"]')
    expect(btn.attributes('aria-label')).toBe('Mark resolved')
    expect(btn.attributes('title')).toBe('Mark resolved')
    expect(btn.html()).toContain('mdi-check-circle-outline')
  })

  it.each(['resolved', 'closed'])('shows "Reopen" with an undo icon on a %s card', (status) => {
    const w = mountCard({ ...BASE, status })
    const btn = w.get('[data-testid="thread-card-resolve"]')
    expect(btn.attributes('aria-label')).toBe('Reopen')
    expect(btn.attributes('title')).toBe('Reopen')
    expect(btn.html()).toContain('mdi-undo')
  })

  it('sits left of edit, copy and delete in the icon row', () => {
    const w = mountCard(BASE)
    const html = w.get('[data-testid="thread-card-actions"]').html()
    const at = (id) => html.indexOf(`data-testid="${id}"`)
    expect(at('thread-card-resolve')).toBeGreaterThan(-1)
    expect(at('thread-card-resolve')).toBeLessThan(at('thread-card-rename'))
    expect(at('thread-card-rename')).toBeLessThan(at('thread-card-copy'))
    expect(at('thread-card-copy')).toBeLessThan(at('thread-card-delete'))
  })

  it('is still offered on a project-bound (locked) card', () => {
    const w = mountCard({ ...BASE, project_id: 'p1' })
    expect(w.find('[data-testid="thread-card-rename"]').exists()).toBe(false)
    expect(w.find('[data-testid="thread-card-resolve"]').exists()).toBe(true)
  })

  it('emits toggle-resolved with the thread on click and does not open the card', async () => {
    const thread = { ...BASE, status: 'resolved' }
    const w = mountCard(thread)
    await w.get('[data-testid="thread-card-resolve"]').trigger('click')
    expect(w.emitted('toggle-resolved')).toHaveLength(1)
    expect(w.emitted('toggle-resolved')[0][0].thread_id).toBe('t1')
    expect(w.emitted('open')).toBeUndefined()
  })
})
