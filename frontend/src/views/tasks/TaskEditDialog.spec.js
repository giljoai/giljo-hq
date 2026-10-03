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

  it('shows "Create new Task" title when editingTask is null', () => {
    const wrapper = mountDialog({ editingTask: null })
    expect(wrapper.find('.dlg-title').text()).toBe('Create new Task')
  })

  it('shows no icon in the header, create or edit', () => {
    expect(mountDialog({ editingTask: null }).find('.dlg-icon').exists()).toBe(false)
    expect(mountDialog({ editingTask: { id: 'task-1', title: 'T' } }).find('.dlg-icon').exists()).toBe(false)
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
    const saveBtn = wrapper.findAll('.v-btn').find(b => b.text() === 'Save')
    await saveBtn.trigger('click')
    expect(wrapper.emitted('save')).toBeTruthy()
  })

  it('primary button says Save when editing', () => {
    const wrapper = mountDialog({ editingTask: { id: 'task-1', title: 'Edit me' } })
    expect(wrapper.findAll('.v-btn').some((b) => b.text() === 'Save')).toBe(true)
  })

  it('primary button says Save when creating', () => {
    const wrapper = mountDialog({ editingTask: null })
    expect(wrapper.findAll('.v-btn').some((b) => b.text() === 'Save')).toBe(true)
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
    const FIELDS = [
      ['prior-work', 'Prior work', 'What was done, and where it stopped.', '## Where I left off'],
      ['next-steps', 'Next steps', 'What the next agent should do first.', '## Next steps'],
      [
        'please-validate',
        'Please validate',
        'Things the next agent should re-check before relying on them, like "tests pass on branch X".',
        '## Verify before trusting',
      ],
      [
        'human-approvals',
        'Human approvals',
        'Decisions, approvals or access only a person can give. Leave empty if none.',
        '## Waiting on the operator',
      ],
      ['unknowns', 'Unknowns', 'What you did not check, or what is still unclear.', '## Cannot testify'],
      ['links', 'Links', 'Files, reports or URLs, one per line.', '## References'],
    ]

    const OLD_THREE_SECTIONS = [
      '## Verify before trusting',
      '- checked with `pytest -x`, 12 passed',
      '',
      '## Waiting on the operator',
      '- nothing',
      '',
      '## Cannot testify',
      '- the concurrency path',
    ].join('\n')

    function mountHandover(description = '', extra = {}) {
      return mountDialog({
        currentTask: { title: '', description, status: 'pending', priority: 'medium', task_type: 'HND', series_number: null },
        ...extra,
      })
    }
    const field = (wrapper, key) => wrapper.find(`[data-test="handover-field-${key}"]`)
    const lastDescription = (wrapper) => {
      const emitted = wrapper.emitted('update:currentTask')
      return emitted[emitted.length - 1][0].description
    }

    it('shows "Create new Handover" with no icon and no pill', () => {
      const wrapper = mountHandover()
      expect(wrapper.find('.dlg-title').text()).toBe('Create new Handover')
      expect(wrapper.find('.dlg-icon').exists()).toBe(false)
      expect(wrapper.find('[data-test="handover-pill"]').exists()).toBe(false)
    })

    it('shows "Edit Agent Handover" when editing', () => {
      const wrapper = mountHandover(OLD_THREE_SECTIONS, { editingTask: { id: 'hnd-1', title: 'A', task_type: 'HND' } })
      expect(wrapper.html()).toContain('Edit Agent Handover')
    })

    it.each(FIELDS)('renders the %s field with its label and hint, not required', (key, label, hint) => {
      const el = field(mountHandover(), key)
      expect(el.exists()).toBe(true)
      expect(el.attributes('label')).toBe(label)
      expect(el.attributes('hint')).toBe(hint)
      expect(el.attributes('required')).toBeUndefined()
    })

    it('replaces the single description box, checklist, gap line and subtitle', () => {
      const wrapper = mountHandover()
      expect(wrapper.find('[data-test="edit-task-description"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="handover-checklist"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="handover-gap-message"]').exists()).toBe(false)
      expect(wrapper.find('[data-test="handover-subtitle"]').exists()).toBe(false)
    })

    it('puts the copy-as-path tip under Links', () => {
      const tip = mountHandover().find('[data-test="handover-tip"]')
      expect(tip.text()).toBe(
        'Tip: to copy a file path, Windows: Shift + right-click, then Copy as path. Mac: Option + right-click, then Copy as pathname.',
      )
    })

    it('Save is enabled with every field empty', () => {
      const saveBtn = mountHandover().findAll('.v-btn').find((b) => b.text() === 'Save')
      expect(saveBtn.attributes('disabled')).toBeUndefined()
    })

    it('typing in one field emits only that section under its agent heading', async () => {
      const wrapper = mountHandover()
      await field(wrapper, 'prior-work').setValue('Stopped at the rebase.')
      expect(lastDescription(wrapper)).toBe('## Where I left off\nStopped at the rebase.')
    })

    it('joins filled fields under the agent headings in the card order and omits empty ones', async () => {
      const wrapper = mountHandover()
      await field(wrapper, 'links').setValue('docs/a.md')
      await field(wrapper, 'unknowns').setValue('the retry path')
      await field(wrapper, 'prior-work').setValue('done X')
      await field(wrapper, 'please-validate').setValue('tests pass on branch X')
      expect(lastDescription(wrapper)).toBe(
        [
          '## Where I left off\ndone X',
          '## Verify before trusting\ntests pass on branch X',
          '## Cannot testify\nthe retry path',
          '## References\ndocs/a.md',
        ].join('\n\n'),
      )
    })

    it('clearing the last filled field emits an empty description', async () => {
      const wrapper = mountHandover()
      await field(wrapper, 'next-steps').setValue('run it')
      await field(wrapper, 'next-steps').setValue('')
      expect(lastDescription(wrapper)).toBe('')
    })

    it('keeps a typed trailing newline in the field', async () => {
      const wrapper = mountHandover()
      await field(wrapper, 'prior-work').setValue('line one\n')
      expect(field(wrapper, 'prior-work').attributes('data-model-value')).toBe('line one\n')
      expect(lastDescription(wrapper)).toBe('## Where I left off\nline one')
    })

    it('edit splits an old three-section handover into the matching fields, nothing lost', () => {
      const wrapper = mountHandover(OLD_THREE_SECTIONS, { editingTask: { id: 'hnd-1', title: 'A', task_type: 'HND' } })
      expect(field(wrapper, 'please-validate').attributes('data-model-value')).toBe('- checked with `pytest -x`, 12 passed')
      expect(field(wrapper, 'human-approvals').attributes('data-model-value')).toBe('- nothing')
      expect(field(wrapper, 'unknowns').attributes('data-model-value')).toBe('- the concurrency path')
      expect(field(wrapper, 'prior-work').attributes('data-model-value')).toBe('')
    })

    it('edit round-trips all six fields by heading', async () => {
      const six = FIELDS.map(([, , , heading], i) => `${heading}\ntext ${i}`).join('\n\n')
      const wrapper = mountHandover(six, { editingTask: { id: 'hnd-1', title: 'A', task_type: 'HND' } })
      FIELDS.forEach(([key], i) => expect(field(wrapper, key).attributes('data-model-value')).toBe(`text ${i}`))
      await field(wrapper, 'next-steps').setValue('text 1')
      expect(lastDescription(wrapper)).toBe(six)
    })

    it('text before any heading and under an unknown heading lands in Prior work', () => {
      const description = ['Session covered the rebase.', '', '## Verify before trusting', '- x', '', '## Misc notes', 'keep me'].join('\n')
      const wrapper = mountHandover(description, { editingTask: { id: 'hnd-1', title: 'A', task_type: 'HND' } })
      const prior = field(wrapper, 'prior-work').attributes('data-model-value')
      expect(prior).toContain('Session covered the rebase.')
      expect(prior).toContain('## Misc notes')
      expect(prior).toContain('keep me')
      expect(field(wrapper, 'please-validate').attributes('data-model-value')).toBe('- x')
    })

    it('a heading with trailing text on its own line keeps that text', () => {
      const wrapper = mountHandover('## Cannot testify: nothing', { editingTask: { id: 'hnd-1', title: 'A', task_type: 'HND' } })
      expect(field(wrapper, 'unknowns').attributes('data-model-value')).toBe('nothing')
    })

    it('the Type field is read-only and shows HND', () => {
      const wrapper = mountHandover(OLD_THREE_SECTIONS, { editingTask: { id: 'hnd-1', title: 'A', task_type: 'HND' } })
      expect(wrapper.find('[data-test="edit-task-type"]').attributes('data-model-value')).toBe('HND')
    })

    it('renders a saveError prop verbatim inside the dialog', () => {
      const wrapper = mountHandover('', { saveError: 'server said no' })
      expect(wrapper.find('[data-test="dialog-save-error"]').text()).toBe('server said no')
    })

    it('an ordinary task keeps the single description box and no handover fields', () => {
      const wrapper = mountDialog()
      expect(wrapper.find('[data-test="edit-task-description"]').exists()).toBe(true)
      expect(wrapper.find('[data-test="handover-field-prior-work"]').exists()).toBe(false)
    })
  })
})
