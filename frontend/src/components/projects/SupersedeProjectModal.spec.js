/**
 * SupersedeProjectModal.spec.js — BE-9157
 *
 * Regression coverage for the "Mark Superseded" successor-picker modal:
 * the successor v-select must populate from candidate projects, the confirm
 * button must stay disabled until a successor is chosen, and confirming must
 * call the store's supersedeProject action with the right payload.
 *
 * Edition scope: Both
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import SupersedeProjectModal from '@/components/projects/SupersedeProjectModal.vue'
import api from '@/services/api'

const vuetify = createVuetify()

const PROJECT_ID = 'proj-be9157'
const OTHER_PROJECT = { id: 'proj-other', name: 'Other Active Project' }

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

  // FE-9485: GET /api/v1/projects/ 422s if `limit` exceeds the REST bound
  // (le=200, BE-6076's deliberate page-size cap). The mocked api.projects.list
  // above accepts any params, so this asserts the store's OUTGOING request
  // actually respects the real endpoint's bound rather than just proving the
  // mock is permissive.
  it('requests successor candidates within the projects endpoint limit bound', async () => {
    await mountModal()

    const params = api.projects.list.mock.calls.at(-1)[0]
    expect(params.limit === undefined || params.limit <= 200).toBe(true)
  })

  it('excludes the project being superseded from the successor candidates', async () => {
    const { wrapper } = await mountModal()

    const select = wrapper.findComponent('[data-testid="successor-select"]')
    expect(select.exists()).toBe(true)
    expect(wrapper.vm.successorOptions).toEqual([{ title: OTHER_PROJECT.name, value: OTHER_PROJECT.id }])
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
      response: { data: { detail: 'Successor project must be different from the project itself.' } },
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
