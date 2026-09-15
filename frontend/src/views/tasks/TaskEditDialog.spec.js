import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: vi.fn() }),
}))

import TaskEditDialog from './TaskEditDialog.vue'

const stubs = {
  'v-dialog': { template: '<div v-if="modelValue" class="v-dialog"><slot /></div>', props: ['modelValue'] },
  'v-card': { template: '<div class="v-card"><slot /></div>' },
  'v-form': { template: '<form class="v-form"><slot /></form>', props: ['modelRef'] },
  'v-row': { template: '<div class="v-row"><slot /></div>' },
  'v-col': { template: '<div class="v-col"><slot /></div>' },
  'v-select': { template: '<div class="v-select" :data-test="$attrs[\'data-test\']"><slot /></div>' },
  'v-text-field': { template: '<input class="v-text-field" :data-test="$attrs[\'data-test\']" :data-model-value="modelValue" />', props: ['modelValue'] },
  'v-textarea': { template: '<textarea class="v-textarea" />' },
  'v-btn': { template: '<button class="v-btn" @click="$emit(\'click\')"><slot /></button>' },
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-spacer': { template: '<div />' },
  'v-draggable': { template: '<div><slot /></div>' },
}

function mountDialog(props = {}) {
  return mount(TaskEditDialog, {
    props: {
      modelValue: true,
      editingTask: null,
      currentTask: { title: '', description: '', status: 'pending', priority: 'medium', task_type: null, series_number: null, due_date: null },
      saving: false,
      statusSelectOptions: ['pending', 'in_progress', 'completed', 'blocked', 'cancelled'],
      ...props,
    },
    global: { stubs, directives: { draggable: {} } },
  })
}

describe('TaskEditDialog', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders when modelValue is true', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('.v-dialog').exists()).toBe(true)
  })

  it('does not render when modelValue is false', () => {
    const wrapper = mountDialog({ modelValue: false })
    expect(wrapper.find('.v-dialog').exists()).toBe(false)
  })

  it('shows "Create Task" title when editingTask is null', () => {
    const wrapper = mountDialog({ editingTask: null })
    expect(wrapper.html()).toContain('Create Task')
  })

  it('shows "Edit Task" title when editingTask is provided', () => {
    const wrapper = mountDialog({ editingTask: { id: 'task-1', title: 'My Task' } })
    expect(wrapper.html()).toContain('Edit Task')
  })

  it('emits cancel when close button clicked', async () => {
    const wrapper = mountDialog()
    const closeBtn = wrapper.findAll('.v-btn').find(b => b.attributes('aria-label') === 'Close dialog')
    await closeBtn.trigger('click')
    expect(wrapper.emitted('cancel')).toBeTruthy()
  })

  it('emits save when save button clicked', async () => {
    const wrapper = mountDialog()
    const saveBtn = wrapper.findAll('.v-btn').find(b => b.text().includes('Create') || b.text().includes('Update'))
    await saveBtn.trigger('click')
    expect(wrapper.emitted('save')).toBeTruthy()
  })

  it('shows Update label when editingTask is set', () => {
    const wrapper = mountDialog({ editingTask: { id: 'task-1', title: 'Edit me' } })
    expect(wrapper.html()).toContain('Update')
  })

  it('shows Create label when editingTask is null', () => {
    const wrapper = mountDialog({ editingTask: null })
    expect(wrapper.html()).toContain('Create')
  })

  it('renders Type and Serial as read-only fields (no type picker)', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('[data-test="edit-task-type"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="edit-task-serial"]').exists()).toBe(true)
    expect(wrapper.find('.v-select[data-test="edit-task-type"]').exists()).toBe(false)
  })

  function serialFieldValue(wrapper) {
    return wrapper.find('[data-test="edit-task-serial"]').attributes('data-model-value')
  }

  describe('serial field zero-padding', () => {
    it('displays "0007" when series_number is 7 (edit mode)', () => {
      const wrapper = mountDialog({
        editingTask: { id: 'task-7', title: 'My Task' },
        currentTask: { title: 'My Task', description: '', status: 'pending', priority: 'medium', task_type: null, series_number: 7, due_date: null },
      })
      expect(serialFieldValue(wrapper)).toBe('0007')
    })

    it('displays "0042" when series_number is 42 (edit mode)', () => {
      const wrapper = mountDialog({
        editingTask: { id: 'task-42', title: 'Another Task' },
        currentTask: { title: 'Another Task', description: '', status: 'pending', priority: 'medium', task_type: null, series_number: 42, due_date: null },
      })
      expect(serialFieldValue(wrapper)).toBe('0042')
    })

    it('displays "—" when series_number is null in edit mode', () => {
      const wrapper = mountDialog({
        editingTask: { id: 'task-x', title: 'No Serial' },
        currentTask: { title: 'No Serial', description: '', status: 'pending', priority: 'medium', task_type: null, series_number: null, due_date: null },
      })
      expect(serialFieldValue(wrapper)).toBe('—')
    })

    it('displays "auto" in create mode (editingTask null)', () => {
      const wrapper = mountDialog({
        editingTask: null,
        currentTask: { title: '', description: '', status: 'pending', priority: 'medium', task_type: null, series_number: null, due_date: null },
      })
      expect(serialFieldValue(wrapper)).toBe('auto')
    })
  })
})
