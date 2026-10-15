import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import ThreadCard from '@/components/hub/ThreadCard.vue'

const vuetify = createVuetify()
const mountCard = (thread) => mount(ThreadCard, { props: { thread }, global: { plugins: [vuetify] } })

const BASE = {
  thread_id: 't1',
  chat_id: 'CHT-0001',
  subject: 'Laptop interop',
  status: 'open',
  project_id: null,
  participants: [],
  last_message: null,
}

describe('ThreadCard kind marker (FE-9741)', () => {
  it('labels a standalone thread "General" and renders no project badge', () => {
    const w = mountCard(BASE)
    expect(w.find('[data-testid="thread-card-general"]').text()).toBe('General')
    expect(w.find('[data-testid="thread-card-project-badge"]').exists()).toBe(false)
  })

  it('shows the project taxonomy badge and the project title on a project thread', () => {
    const w = mountCard({
      ...BASE,
      project_id: 'p1',
      subject: '(project comms)',
      title: 'Hub thread list: one list',
      project_name: 'Hub thread list: one list',
      _projectAlias: 'FE-9741',
      _projectColor: '#6DB3E4',
    })
    const badge = w.find('[data-testid="thread-card-project-badge"]')
    expect(badge.text()).toBe('FE-9741')
    expect(badge.attributes('style')).toContain('background-color')
    expect(w.find('[data-testid="thread-card-title"]').text()).toBe('Hub thread list: one list')
    expect(w.find('[data-testid="thread-card-general"]').exists()).toBe(false)
  })

  it('falls back to a muted "Project" label while the alias is not known yet', () => {
    const w = mountCard({ ...BASE, project_id: 'p1', title: 'Some project', project_name: 'Some project' })
    expect(w.find('[data-testid="thread-card-project-badge"]').exists()).toBe(false)
    expect(w.find('[data-testid="thread-card-project-label"]').text()).toBe('Project')
    expect(w.find('[data-testid="thread-card-general"]').exists()).toBe(false)
  })
})
