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
  'v-textarea': { template: '<textarea class="v-textarea" :data-model-value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />', props: ['modelValue'] },
  'v-btn': { template: '<button class="v-btn" v-bind="$attrs" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>', props: ['disabled'] },
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-spacer': { template: '<div />' },
  'v-draggable': { template: '<div><slot /></div>' },
}

function mountDialog(props = {}) {
  return mount(TaskEditDialog, {
    props: {
      modelValue: true,
      editingTask: null,
      currentTask: { title: '', description: '', status: 'pending', priority: 'medium', task_type: null, series_number: null },
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
        currentTask: { title: 'My Task', description: '', status: 'pending', priority: 'medium', task_type: null, series_number: 7 },
      })
      expect(serialFieldValue(wrapper)).toBe('0007')
    })

    it('displays "0042" when series_number is 42 (edit mode)', () => {
      const wrapper = mountDialog({
        editingTask: { id: 'task-42', title: 'Another Task' },
        currentTask: { title: 'Another Task', description: '', status: 'pending', priority: 'medium', task_type: null, series_number: 42 },
      })
      expect(serialFieldValue(wrapper)).toBe('0042')
    })

    it('displays "—" when series_number is null in edit mode', () => {
      const wrapper = mountDialog({
        editingTask: { id: 'task-x', title: 'No Serial' },
        currentTask: { title: 'No Serial', description: '', status: 'pending', priority: 'medium', task_type: null, series_number: null },
      })
      expect(serialFieldValue(wrapper)).toBe('—')
    })

    it('displays "auto" in create mode (editingTask null)', () => {
      const wrapper = mountDialog({
        editingTask: null,
        currentTask: { title: '', description: '', status: 'pending', priority: 'medium', task_type: null, series_number: null },
      })
      expect(serialFieldValue(wrapper)).toBe('auto')
    })
  })

  describe('handover mode (task_type HND)', () => {
    const UNTOUCHED_TEMPLATE = [
      '## Verify before trusting',
      '- <claim> -- check with: <command>',
      '',
      '## Waiting on the operator',
      '- <fill this in>',
      '',
      '## Cannot testify',
      '- <fill this in>',
    ].join('\n')

    const COMPLETE_HANDOVER = [
      '## Verify before trusting',
      '- checked with `pytest -x`, 12 passed',
      '',
      '## Waiting on the operator',
      '- nothing',
      '',
      '## Cannot testify',
      '- nothing',
    ].join('\n')

    function mountHandover(description, extra = {}) {
      return mountDialog({
        currentTask: {
          title: '',
          description,
          status: 'pending',
          priority: 'medium',
          task_type: 'HND',
          series_number: null,
        },
        ...extra,
      })
    }

    it('shows "New Agent Handover" as the title, not "Create Task"', () => {
      const wrapper = mountHandover(UNTOUCHED_TEMPLATE)
      expect(wrapper.html()).toContain('New Agent Handover')
      expect(wrapper.html()).not.toContain('Create Task')
    })

    it('shows "Edit Agent Handover" when editing an existing handover', () => {
      const wrapper = mountHandover(COMPLETE_HANDOVER, {
        editingTask: { id: 'hnd-1', title: 'A handover', task_type: 'HND' },
      })
      expect(wrapper.html()).toContain('Edit Agent Handover')
    })

    it('renders the HND pill', () => {
      const wrapper = mountHandover(UNTOUCHED_TEMPLATE)
      expect(wrapper.find('[data-test="handover-pill"]').exists()).toBe(true)
    })

    it('does not render the HND pill for an ordinary task', () => {
      const wrapper = mountDialog()
      expect(wrapper.find('[data-test="handover-pill"]').exists()).toBe(false)
    })

    it('the subtitle is exactly the operator-specified text', () => {
      const wrapper = mountHandover(UNTOUCHED_TEMPLATE)
      expect(wrapper.find('[data-test="handover-subtitle"]').text()).toBe(
        'Starts from your handover template. Shape it once in Tools › Agents › Handover template.',
      )
    })

    it('the tip line is exactly the operator-specified copy-as-path text', () => {
      const wrapper = mountHandover(UNTOUCHED_TEMPLATE)
      expect(wrapper.find('[data-test="handover-tip"]').text()).toBe(
        'Windows: Shift + right-click, then Copy as path. Mac: Option + right-click, then Copy as pathname.',
      )
    })

    it('the Type field is read-only and shows HND (no type-change control)', () => {
      const wrapper = mountHandover(COMPLETE_HANDOVER, {
        editingTask: { id: 'hnd-1', title: 'A handover', task_type: 'HND' },
      })
      const typeField = wrapper.find('[data-test="edit-task-type"]')
      expect(typeField.attributes('data-model-value')).toBe('HND')
      expect(wrapper.find('.v-select[data-test="edit-task-type"]').exists()).toBe(false)
    })

    it('save is disabled while the untouched template placeholders remain', () => {
      const wrapper = mountHandover(UNTOUCHED_TEMPLATE)
      const saveBtn = wrapper.findAll('.v-btn').find((b) => b.text().includes('Create'))
      expect(saveBtn.attributes('disabled')).not.toBeUndefined()
    })

    it('names the still-missing sections in the gap message', () => {
      const wrapper = mountHandover(UNTOUCHED_TEMPLATE)
      const gap = wrapper.find('[data-test="handover-gap-message"]')
      expect(gap.exists()).toBe(true)
      expect(gap.text()).toContain('Verify before trusting')
      expect(gap.text()).toContain('Waiting on the operator')
      expect(gap.text()).toContain('Cannot testify')
    })

    it('save is enabled once every section carries real content', () => {
      const wrapper = mountHandover(COMPLETE_HANDOVER)
      const saveBtn = wrapper.findAll('.v-btn').find((b) => b.text().includes('Create'))
      expect(saveBtn.attributes('disabled')).toBeUndefined()
      expect(wrapper.find('[data-test="handover-gap-message"]').exists()).toBe(false)
    })

    it('does not gate Save for an ordinary (non-handover) task', () => {
      const wrapper = mountDialog({
        currentTask: { title: '', description: '', status: 'pending', priority: 'medium', task_type: null, series_number: null },
      })
      const saveBtn = wrapper.findAll('.v-btn').find((b) => b.text().includes('Create'))
      expect(saveBtn.attributes('disabled')).toBeUndefined()
    })

    it('renders a saveError prop verbatim inside the dialog', () => {
      const serverMessage = "A handover task (task_type='HND') must carry these headings..."
      const wrapper = mountHandover(COMPLETE_HANDOVER, { saveError: serverMessage })
      expect(wrapper.find('[data-test="dialog-save-error"]').text()).toBe(serverMessage)
    })

    it('shows no save-error banner when saveError is empty', () => {
      const wrapper = mountHandover(COMPLETE_HANDOVER)
      expect(wrapper.find('[data-test="dialog-save-error"]').exists()).toBe(false)
    })

    it('strips the placeholder line once typing adds real content under its heading', async () => {
      const wrapper = mountHandover(UNTOUCHED_TEMPLATE)
      const textarea = wrapper.find('.v-textarea')
      const grown =
        UNTOUCHED_TEMPLATE.split('\n## Waiting on the operator\n- <fill this in>').join(
          '\n## Waiting on the operator\n- <fill this in>\n- ops needs to rotate the key',
        )
      await textarea.setValue(grown)

      const emitted = wrapper.emitted('update:currentTask')
      const lastPayload = emitted[emitted.length - 1][0]
      expect(lastPayload.description).not.toContain('- <fill this in>\n- ops needs to rotate the key')
      expect(lastPayload.description).toContain('## Waiting on the operator\n- ops needs to rotate the key')
    })
  })
})
