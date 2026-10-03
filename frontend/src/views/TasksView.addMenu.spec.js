import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { withRealVuetify } from '../../tests/helpers/realVuetify'
import TasksView from './TasksView.vue'

vi.mock('@/services/api', () => ({
  default: {
    tasks: { list: vi.fn().mockResolvedValue({ data: [] }) },
    users: { list: vi.fn().mockResolvedValue({ data: [] }) },
    agents: { list: vi.fn().mockResolvedValue({ data: [] }) },
    settings: { getHandoverTemplate: vi.fn().mockResolvedValue({ data: {} }) },
  },
}))

const REAL = ['VMenu', 'VOverlay', 'VList', 'VListItem', 'VListItemTitle', 'VBtn', 'VIcon']

describe('TasksView add menu', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    document.body.innerHTML = ''
  })

  it('lists New task and New Agent Handover once each', async () => {
    const { plugin, restore } = await withRealVuetify(REAL)
    const wrapper = mount(TasksView, { attachTo: document.body, global: { plugins: [plugin] } })
    try {
      await flushPromises()
      await wrapper.get('[data-testid="add-task-menu-btn"]').trigger('click')
      await flushPromises()

      const items = document.querySelectorAll(
        '[data-testid="new-task-menu-item"], [data-testid="new-handover-menu-item"]',
      )
      expect(items).toHaveLength(2)
      const labels = Array.from(items).map((el) => el.textContent.trim())
      expect(labels).toEqual(['New task', 'New Agent Handover'])
    } finally {
      wrapper.unmount()
      restore()
    }
  })
})
