import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobsBoardCard from './JobsBoardCard.vue'
import { useProjectStore } from '@/stores/projects'
import { useProjectStateStore } from '@/stores/projectStateStore'

const vuetify = createVuetify()
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
  ],
})
const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

let pinia
let projectStore
let mounted = []

function mountCard(project, agents = [], props = {}) {
  const wrapper = mount(JobsBoardCard, {
    props: { project, agents, now: Date.parse('2026-11-15T06:00:00Z'), ...props },
    attachTo: document.body,
    global: { plugins: [pinia, vuetify, router], stubs: { 'v-tooltip': tooltipStub } },
  })
  mounted.push(wrapper)
  return wrapper
}

const DESCRIPTION = 'Patrik GO 2026-11-15 first line.\nSecond line of the description.'
const MISSION = 'Phase 1 frontend: copy.\nPhase 2 tester: specs.'

const staged = {
  id: 'p-1',
  taxonomy_alias: 'FE-0076',
  name: 'Card edit',
  status: 'active',
  description: DESCRIPTION,
  mission: MISSION,
  staging_status: 'staging_complete',
  execution_mode: 'multi_terminal',
  implementation_launched_at: null,
}
const noMission = { ...staged, id: 'p-2', mission: '', staging_status: null }
const writing = { ...staged, id: 'p-3', mission: '', staging_status: 'staging' }
const orch = { agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'complete' }
const orchWorking = { ...orch, status: 'working' }

const q = (wrapper, id) => wrapper.find(`[data-testid="${id}"]`)

async function openPanel(wrapper) {
  await q(wrapper, 'jb-details-btn').trigger('click')
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  projectStore = useProjectStore()
  projectStore.updateProject = vi.fn().mockResolvedValue({})
})

afterEach(() => {
  mounted.forEach((w) => w.unmount())
  mounted = []
})

describe('the one line (FE-0076 items 1 and 2)', () => {
  it('replaces the Description and Mission rows and the old Details toggle with ONE button', () => {
    const wrapper = mountCard(staged, [orch])
    expect(q(wrapper, 'jb-summary-rows').exists()).toBe(false)
    expect(q(wrapper, 'jb-row-description').exists()).toBe(false)
    expect(q(wrapper, 'jb-row-mission').exists()).toBe(false)
    const buttons = wrapper.findAll('[data-testid="jb-details-btn"]')
    expect(buttons).toHaveLength(1)
    expect(buttons[0].text()).toContain('Description and mission')
    expect(buttons[0].text()).not.toMatch(/^Details$/)
    expect(buttons[0].attributes('aria-expanded')).toBe('false')
  })

  it('pill: no mission yet', () => {
    const pill = q(mountCard(noMission, [orch]), 'jb-mission-state')
    expect(pill.attributes('data-state')).toBe('none')
    expect(pill.text()).toBe('No mission yet')
  })

  it('pill: writing mission, with the moving dots', () => {
    const pill = q(mountCard(writing, [orchWorking]), 'jb-mission-state')
    expect(pill.attributes('data-state')).toBe('writing')
    expect(pill.text()).toContain('Writing mission')
    expect(pill.find('[data-testid="live-dots"]').exists()).toBe(true)
  })

  it('pill: mission written', () => {
    const pill = q(mountCard(staged, [orch]), 'jb-mission-state')
    expect(pill.attributes('data-state')).toBe('written')
    expect(pill.text()).toBe('Mission written')
  })

  it('a finished project with no mission never tells the person to press Stage (FE-9763)', async () => {
    const done = { ...noMission, id: 'p-4', status: 'completed', closeout_summary: 'Shipped it.' }
    const wrapper = mountCard(done)
    expect(q(wrapper, 'jb-mission-state').text()).toBe('No mission yet')
    await openPanel(wrapper)
    expect(q(wrapper, 'jb-drawer-mission').text()).toContain('Closeout: Shipped it.')
    expect(wrapper.text()).not.toMatch(/Press Stage/)
  })
})

describe('read inside the panel (item 4)', () => {
  it('opening the line shows the full description and the full mission', async () => {
    const wrapper = mountCard(staged, [orch])
    expect(q(wrapper, 'jb-drawer').exists()).toBe(false)
    await openPanel(wrapper)
    expect(q(wrapper, 'jb-details-btn').attributes('aria-expanded')).toBe('true')
    expect(q(wrapper, 'jb-drawer-description').text()).toContain('Second line of the description.')
    expect(q(wrapper, 'jb-drawer-mission').text()).toContain('Phase 2 tester: specs.')
  })
})

describe('edit the description in place (items 5 and 9)', () => {
  it('the pencil opens a text box in the same spot, with Save and Cancel; the pop-up is not asked for', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-description').trigger('click')
    const box = q(wrapper, 'jb-drawer-description').find('textarea')
    expect(box.exists()).toBe(true)
    expect(box.element.value).toBe(DESCRIPTION)
    expect(q(wrapper, 'jb-edit-save').text()).toBe('Save')
    expect(q(wrapper, 'jb-edit-cancel').text()).toBe('Cancel')
    expect(wrapper.emitted('edit-description')).toBeUndefined()
  })

  it('Save makes the dialog\'s own call, updateProject(id, ...), and then closes the box', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-description').trigger('click')
    await q(wrapper, 'jb-drawer-description').find('textarea').setValue('A new description')
    expect(projectStore.updateProject).not.toHaveBeenCalled()
    await q(wrapper, 'jb-edit-save').trigger('click')
    await flushPromises()
    expect(projectStore.updateProject).toHaveBeenCalledTimes(1)
    expect(projectStore.updateProject).toHaveBeenCalledWith('p-1', { description: 'A new description' })
    expect(q(wrapper, 'jb-drawer-description').find('textarea').exists()).toBe(false)
    expect(q(wrapper, 'jb-drawer-description').text()).toContain('A new description')
    expect(wrapper.emitted('changed')).toBeTruthy()
  })

  it('Cancel drops the typed text and saves nothing', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-description').trigger('click')
    await q(wrapper, 'jb-drawer-description').find('textarea').setValue('typed then dropped')
    await q(wrapper, 'jb-edit-cancel').trigger('click')
    expect(projectStore.updateProject).not.toHaveBeenCalled()
    expect(q(wrapper, 'jb-drawer-description').find('textarea').exists()).toBe(false)
    expect(q(wrapper, 'jb-drawer-description').text()).toContain('Second line of the description.')
    expect(q(wrapper, 'jb-drawer-description').text()).not.toContain('typed then dropped')
  })

  it('an empty description is refused under the box, as the dialog refuses it, and nothing is sent', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-description').trigger('click')
    await q(wrapper, 'jb-drawer-description').find('textarea').setValue('')
    await q(wrapper, 'jb-edit-save').trigger('click')
    await flushPromises()
    expect(projectStore.updateProject).not.toHaveBeenCalled()
    expect(q(wrapper, 'jb-edit-error').text()).toBe('Description is required')
    expect(q(wrapper, 'jb-drawer-description').find('textarea').exists()).toBe(true)
  })

  it('a refusal from the server shows under the box and keeps the typed text', async () => {
    projectStore.updateProject.mockRejectedValueOnce({ response: { data: { error: 'Cannot modify project in a locked status.' } } })
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-description').trigger('click')
    await q(wrapper, 'jb-drawer-description').find('textarea').setValue('kept text')
    await q(wrapper, 'jb-edit-save').trigger('click')
    await flushPromises()
    expect(q(wrapper, 'jb-edit-error').text()).toContain('Cannot modify project in a locked status.')
    expect(q(wrapper, 'jb-drawer-description').find('textarea').element.value).toBe('kept text')
  })
})

describe('edit the mission in place (item 5)', () => {
  it('Save sends only the mission, with the dialog\'s own regenerate note under the box', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-mission').trigger('click')
    const box = q(wrapper, 'jb-drawer-mission').find('textarea')
    expect(box.element.value).toBe(MISSION)
    expect(q(wrapper, 'jb-drawer-mission').text()).toContain(
      'Written by the orchestrator during staging; you can edit it. Clear it to regenerate on the next staging.',
    )
    await box.setValue('Rewritten mission')
    await q(wrapper, 'jb-edit-save').trigger('click')
    await flushPromises()
    expect(projectStore.updateProject).toHaveBeenCalledTimes(1)
    expect(projectStore.updateProject).toHaveBeenCalledWith('p-1', { mission: 'Rewritten mission' })
  })

  it('an empty mission is allowed (clear it to regenerate), as in the dialog', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-mission').trigger('click')
    await q(wrapper, 'jb-drawer-mission').find('textarea').setValue('')
    await q(wrapper, 'jb-edit-save').trigger('click')
    await flushPromises()
    expect(projectStore.updateProject).toHaveBeenCalledWith('p-1', { mission: '' })
  })
})

describe('the panel allows exactly what the dialog allows (item 6, rule map)', () => {
  const WRITABLE = ['inactive', 'active', 'parked', 'terminated', 'deleted']
  const REFUSED = ['completed', 'cancelled', 'superseded']

  it.each(WRITABLE)('status %s: both pencils', async (status) => {
    const wrapper = mountCard({ ...staged, status }, [orch])
    await openPanel(wrapper)
    expect(q(wrapper, 'jb-edit-description').exists()).toBe(true)
    expect(q(wrapper, 'jb-edit-mission').exists()).toBe(true)
  })

  it.each(REFUSED)('status %s: no pencil, the text still reads', async (status) => {
    const wrapper = mountCard({ ...staged, status }, [orch])
    await openPanel(wrapper)
    expect(q(wrapper, 'jb-edit-description').exists()).toBe(false)
    expect(q(wrapper, 'jb-edit-mission').exists()).toBe(false)
    expect(q(wrapper, 'jb-drawer-description').text()).toContain('Second line of the description.')
  })

  it('a launched project keeps both pencils (the dialog saves them after launch)', async () => {
    const wrapper = mountCard({ ...staged, implementation_launched_at: '2026-11-15T05:00:00Z' }, [orchWorking])
    await openPanel(wrapper)
    expect(q(wrapper, 'jb-edit-description').exists()).toBe(true)
    expect(q(wrapper, 'jb-edit-mission').exists()).toBe(true)
  })

  it('a chain member keeps both pencils, as the dialog opened for it', async () => {
    const wrapper = mountCard(staged, [orch], { chainCtx: { runId: 'run-1' }, showStaging: false })
    await openPanel(wrapper)
    expect(q(wrapper, 'jb-edit-description').exists()).toBe(true)
    expect(q(wrapper, 'jb-edit-mission').exists()).toBe(true)
  })

  it('no pencil while the orchestrator is writing the mission; the description pencil stays', async () => {
    const wrapper = mountCard(writing, [orchWorking])
    await openPanel(wrapper)
    expect(q(wrapper, 'jb-edit-mission').exists()).toBe(false)
    expect(q(wrapper, 'jb-edit-description').exists()).toBe(true)
  })
})

describe('a live event never replaces typed text (item 7)', () => {
  it('a store mission event while the mission box is open leaves the box alone', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-mission').trigger('click')
    const box = q(wrapper, 'jb-drawer-mission').find('textarea')
    await box.setValue('my half-typed mission')
    const state = useProjectStateStore()
    state.setMission('p-1', 'The orchestrator rewrote it elsewhere')
    await flushPromises()
    expect(q(wrapper, 'jb-drawer-mission').find('textarea').element.value).toBe('my half-typed mission')
  })

  it('a changed description row while the description box is open leaves the box alone, and Cancel then shows the new text', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-description').trigger('click')
    await q(wrapper, 'jb-drawer-description').find('textarea').setValue('typing here')
    await wrapper.setProps({ project: { ...staged, description: 'Saved in another tab' } })
    await flushPromises()
    expect(q(wrapper, 'jb-drawer-description').find('textarea').element.value).toBe('typing here')
    await q(wrapper, 'jb-edit-cancel').trigger('click')
    expect(q(wrapper, 'jb-drawer-description').text()).toContain('Saved in another tab')
  })

  it('the mission turning to "writing" while typing keeps the typed text', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-mission').trigger('click')
    await q(wrapper, 'jb-drawer-mission').find('textarea').setValue('still mine')
    await wrapper.setProps({ project: { ...staged, staging_status: 'staging' }, agents: [orchWorking] })
    await flushPromises()
    expect(q(wrapper, 'jb-drawer-mission').find('textarea').element.value).toBe('still mine')
  })
})

describe('an open mission box while the mission is being written (item 7)', () => {
  const goWriting = (wrapper) => wrapper.setProps({ project: { ...staged, staging_status: 'staging' }, agents: [orchWorking] })
  const goWritten = (wrapper) => wrapper.setProps({ project: { ...staged, staging_status: 'staging_complete' }, agents: [orch] })

  it('keeps the typed text, cannot save, still cancels; the description box is unaffected; Save works again once written', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-mission').trigger('click')
    await q(wrapper, 'jb-drawer-mission').find('textarea').setValue('my mission text')

    await goWriting(wrapper)
    await flushPromises()
    expect(q(wrapper, 'jb-mission-state').attributes('data-state')).toBe('writing')
    const mission = q(wrapper, 'jb-drawer-mission')
    expect(mission.find('textarea').element.value).toBe('my mission text')
    const save = mission.find('[data-testid="jb-edit-save"]')
    save.element.click()
    await flushPromises()
    expect(projectStore.updateProject).not.toHaveBeenCalled()
    expect(save.attributes('disabled')).toBeDefined()

    await q(wrapper, 'jb-edit-description').trigger('click')
    await q(wrapper, 'jb-drawer-description').find('textarea').setValue('desc while writing')
    await q(wrapper, 'jb-drawer-description').find('[data-testid="jb-edit-save"]').trigger('click')
    await flushPromises()
    expect(projectStore.updateProject).toHaveBeenCalledTimes(1)
    expect(projectStore.updateProject).toHaveBeenLastCalledWith('p-1', { description: 'desc while writing' })

    await goWritten(wrapper)
    await flushPromises()
    const again = q(wrapper, 'jb-drawer-mission').find('[data-testid="jb-edit-save"]')
    expect(again.attributes('disabled')).toBeUndefined()
    expect(q(wrapper, 'jb-drawer-mission').find('textarea').element.value).toBe('my mission text')
    await again.trigger('click')
    await flushPromises()
    expect(projectStore.updateProject).toHaveBeenCalledTimes(2)
    expect(projectStore.updateProject).toHaveBeenLastCalledWith('p-1', { mission: 'my mission text' })
  })

  it('Cancel and Escape still work while it is being written', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-mission').trigger('click')
    await q(wrapper, 'jb-drawer-mission').find('textarea').setValue('x')
    await goWriting(wrapper)
    await flushPromises()
    await q(wrapper, 'jb-drawer-mission').find('textarea').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(q(wrapper, 'jb-drawer-mission').find('textarea').exists()).toBe(false)
    expect(projectStore.updateProject).not.toHaveBeenCalled()
  })
})

describe('keyboard and screen reader (item 8)', () => {
  it('Escape cancels the edit, not the panel, and focus returns to the pencil', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-description').trigger('click')
    const box = q(wrapper, 'jb-drawer-description').find('textarea')
    await box.setValue('abandon me')
    await box.trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(q(wrapper, 'jb-drawer-description').find('textarea').exists()).toBe(false)
    expect(q(wrapper, 'jb-drawer').exists()).toBe(true)
    expect(projectStore.updateProject).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(q(wrapper, 'jb-edit-description').element)
  })

  it('focus returns to the pencil after Save too', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    await q(wrapper, 'jb-edit-mission').trigger('click')
    await q(wrapper, 'jb-edit-save').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(q(wrapper, 'jb-edit-mission').element)
  })

  it('the pencils, Save and Cancel are real buttons with names', async () => {
    const wrapper = mountCard(staged, [orch])
    await openPanel(wrapper)
    expect(q(wrapper, 'jb-edit-description').element.tagName).toBe('BUTTON')
    expect(q(wrapper, 'jb-edit-description').attributes('aria-label')).toBe('Edit description')
    expect(q(wrapper, 'jb-edit-mission').attributes('aria-label')).toBe('Edit mission')
    await q(wrapper, 'jb-edit-description').trigger('click')
    expect(q(wrapper, 'jb-edit-save').element.tagName).toBe('BUTTON')
    expect(q(wrapper, 'jb-edit-cancel').element.tagName).toBe('BUTTON')
  })
})

describe('type size and tokens of the line (item 3, item 10)', () => {
  it('0.8rem, weight 600, the secondary text token, a 16px chevron, brand yellow on hover and focus', () => {
    const line = readFileSync(resolve(__dirname, 'JobsBoardDetailsLine.vue'), 'utf8')
    const block = (sel) => line.match(new RegExp(`${sel.replace('.', '\\.')}\\s*\\{([^}]*)\\}`))?.[1] || ''
    const btn = block('.jb-details-btn')
    expect(btn).toMatch(/font-size:\s*0\.8rem/)
    expect(btn).toMatch(/font-weight:\s*600/)
    expect(btn).toMatch(/color:\s*\$color-text-secondary/)
    expect(line).toMatch(/<v-icon[^>]*size="16"/)
    expect(line).toMatch(/&:hover,\s*&:focus-visible\s*\{[^}]*\$color-brand-yellow/)
    expect(line).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})

describe('the pop-up keeps name, type and number and reads the description better (item 9)', () => {
  it('the description box grows with its text up to a cap; name, type and number stay in the pop-up', async () => {
    const { default: ProjectCreateEditDialog } = await import('./ProjectCreateEditDialog.vue')
    const wrapper = mount(ProjectCreateEditDialog, {
      props: { modelValue: true, editingProject: { id: 'p-1', name: 'N', description: 'D', mission: 'M', status: 'active' } },
      global: { plugins: [pinia, vuetify] },
    })
    const box = wrapper.find('[aria-label="Project description"]')
    expect(box.exists()).toBe(true)
    expect(box.attributes()).toHaveProperty('auto-grow')
    expect(Number(box.attributes('max-rows'))).toBeGreaterThanOrEqual(8)
    expect(wrapper.find('[aria-label="Project name"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="Project type"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="Series number"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
