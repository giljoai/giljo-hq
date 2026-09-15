
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProjectDeletedDialog from '@/components/projects/ProjectDeletedDialog.vue'

const listItemWithAppend = {
  template: `<div class="v-list-item"><slot /><slot name="append" /></div>`,
}

const defaultProjects = [
  { id: 'proj-x1', name: 'Restore Test Project' },
]

function mountDialog(props = {}) {
  return mount(ProjectDeletedDialog, {
    props: {
      modelValue: true,
      deletedProjects: defaultProjects,
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

describe('ProjectDeletedDialog — restore button', () => {
  it('renders the restore button with mdi-restore icon', () => {
    const wrapper = mountDialog()
    const btn = wrapper.find('.restore-btn')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('icon')).toBe('mdi-restore')
  })

  it('does not use the deprecated mdi-delete-restore icon', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('[icon="mdi-delete-restore"]').exists()).toBe(false)
  })

  it('emits restore event with project when restore button is clicked', async () => {
    const wrapper = mountDialog()
    const btn = wrapper.find('.restore-btn')
    await btn.trigger('click')
    expect(wrapper.emitted('restore')).toBeTruthy()
    expect(wrapper.emitted('restore')[0][0]).toEqual(defaultProjects[0])
  })
})
