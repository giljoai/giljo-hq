
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import SupersedeProjectModal from '@/components/projects/SupersedeProjectModal.vue'
import api from '@/services/api'

const vuetify = createVuetify()

const PROJECT_ID = 'proj-be9157'
const OTHER_PROJECT = { id: 'proj-other', name: 'Other Active Project', taxonomy_alias: 'FE-9501a' }

async function mountModal(props = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)

  const wrapper = mount(SupersedeProjectModal, {
    props: {
      show: false,
      projectId: PROJECT_ID,
      projectName: 'Old Project',
      ...props,
    },
    global: {
      plugins: [pinia, vuetify],
      directives: {
        draggable: {},
      },
    },
  })

  await wrapper.setProps({ show: true })
  await flushPromises()

  return { wrapper }
}

describe('SupersedeProjectModal.vue', () => {
  beforeEach(() => {
    api.projects.list = vi.fn().mockResolvedValue({
      data: [OTHER_PROJECT, { id: PROJECT_ID, name: 'Old Project' }],
    })
    api.projects.update = vi.fn().mockResolvedValue({
      data: { id: PROJECT_ID, status: 'superseded', successor_project_id: OTHER_PROJECT.id },
    })
  })

  it('requests successor candidates within the projects endpoint limit bound', async () => {
    await mountModal()

    const params = api.projects.list.mock.calls.at(-1)[0]
    expect(params.limit === undefined || params.limit <= 200).toBe(true)
  })

  it('excludes the project being superseded from the successor candidates', async () => {
    const { wrapper } = await mountModal()

    const select = wrapper.findComponent('[data-testid="successor-select"]')
    expect(select.exists()).toBe(true)
    expect(wrapper.vm.successorOptions).toHaveLength(1)
    expect(wrapper.vm.successorOptions[0].value).toBe(OTHER_PROJECT.id)
  })

  it('renders the taxonomy alias alongside the name for each successor option', async () => {
    const { wrapper } = await mountModal()

    expect(wrapper.vm.successorOptions[0].title).toContain(OTHER_PROJECT.taxonomy_alias)
    expect(wrapper.vm.successorOptions[0].title).toContain(OTHER_PROJECT.name)
  })

  it('falls back to the bare name when a candidate has no taxonomy alias', async () => {
    api.projects.list = vi.fn().mockResolvedValue({
      data: [{ id: 'proj-no-alias', name: 'Unaliased Project' }, { id: PROJECT_ID, name: 'Old Project' }],
    })
    const { wrapper } = await mountModal()

    expect(wrapper.vm.successorOptions).toEqual([{ title: 'Unaliased Project', value: 'proj-no-alias' }])
  })

  it('surfaces an inactive candidate as a selectable successor', async () => {
    const INACTIVE_PROJECT = { id: 'proj-inactive', name: 'Inactive Candidate', status: 'inactive', taxonomy_alias: 'BE-9499c' }
    api.projects.list = vi.fn().mockResolvedValue({
      data: [OTHER_PROJECT, INACTIVE_PROJECT, { id: PROJECT_ID, name: 'Old Project' }],
    })
    const { wrapper } = await mountModal()

    const values = wrapper.vm.successorOptions.map((o) => o.value)
    expect(values).toContain(INACTIVE_PROJECT.id)
  })

  it('disables the confirm button until a successor is chosen', async () => {
    const { wrapper } = await mountModal()

    const confirmBtn = wrapper.find('[data-testid="confirm-supersede-btn"]')
    expect(confirmBtn.attributes('disabled')).toBeDefined()

    wrapper.vm.successorProjectId = OTHER_PROJECT.id
    await flushPromises()

    expect(wrapper.find('[data-testid="confirm-supersede-btn"]').attributes('disabled')).toBeUndefined()
  })

  it('calls supersedeProject with the chosen successor and emits superseded on confirm', async () => {
    const { wrapper } = await mountModal()

    wrapper.vm.successorProjectId = OTHER_PROJECT.id
    await flushPromises()

    await wrapper.find('[data-testid="confirm-supersede-btn"]').trigger('click')
    await flushPromises()

    expect(api.projects.update).toHaveBeenCalledWith(PROJECT_ID, {
      status: 'superseded',
      successor_project_id: OTHER_PROJECT.id,
    })
    expect(wrapper.emitted('superseded')).toBeTruthy()
  })

  it('surfaces a backend validation error inline instead of crashing', async () => {
    api.projects.update = vi.fn().mockRejectedValue({
      response: {
        status: 400,
        data: {
          error_code: 'VALIDATIONERROR',
          message: 'Successor project must be different from the project itself.',
        },
      },
    })
    const { wrapper } = await mountModal()

    wrapper.vm.successorProjectId = OTHER_PROJECT.id
    await flushPromises()

    await wrapper.find('[data-testid="confirm-supersede-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('superseded')).toBeFalsy()
    expect(wrapper.text()).toContain('Successor project must be different from the project itself.')
  })
})
