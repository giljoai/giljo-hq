
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import TaskDeletedDialog from '@/components/tasks/TaskDeletedDialog.vue'

const listItemWithAppend = {
  template: `<div class="v-list-item"><slot /><slot name="append" /></div>`,
}

const defaultTasks = [
  { id: 'task-001', title: 'Fix login bug', taxonomy_alias: 'BE-42' },
  { id: 'task-002', title: 'Update dashboard', taxonomy_alias: 'FE-7' },
]

function mountDialog(props = {}) {
  return mount(TaskDeletedDialog, {
    props: {
      modelValue: true,
      deletedTasks: defaultTasks,
      ...props,
    },
    global: {
      stubs: {
        'v-list-item': listItemWithAppend,
      },
      directives: {
        draggable: {},
      },
    },
  })
}

describe('TaskDeletedDialog', () => {
  it('renders soft-deleted tasks from the deletedTasks prop', () => {
    const wrapper = mountDialog()
    expect(wrapper.text()).toContain('Fix login bug')
    expect(wrapper.text()).toContain('BE-42')
    expect(wrapper.text()).toContain('Update dashboard')
    expect(wrapper.text()).toContain('FE-7')
  })

  it('emits restore event with the task when restore button is clicked', async () => {
    const wrapper = mountDialog()
    const btn = wrapper.find('[data-testid="restore-task"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('restore')).toBeTruthy()
    expect(wrapper.emitted('restore')[0][0]).toEqual(defaultTasks[0])
  })

  it('shows the empty state when deletedTasks is empty', () => {
    const wrapper = mountDialog({ deletedTasks: [] })
    expect(wrapper.text()).toContain('No deleted tasks')
    expect(wrapper.find('[data-testid="restore-task"]').exists()).toBe(false)
  })

  it('disables the restore button for the task being restored', () => {
    const wrapper = mountDialog({ restoringId: 'task-001' })
    const btns = wrapper.findAll('[data-testid="restore-task"]')
    expect(btns.length).toBe(2)
    expect(btns[0].attributes('disabled')).toBeDefined()
    expect(btns[1].attributes('disabled')).toBeUndefined()
  })

  it('carries the brand-yellow restore-btn class on restore buttons', () => {
    const wrapper = mountDialog()
    const btn = wrapper.find('.restore-btn')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('icon')).toBe('mdi-restore')
  })
})
