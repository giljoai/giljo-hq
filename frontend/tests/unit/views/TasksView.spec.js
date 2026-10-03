/**
 * TasksView.spec.js
 *
 * Tests for TasksView component - task management interface.
 *
 * Post-refactor notes:
 * - TasksView uses search, statusFilter, priorityFilter, categoryFilter for filtering
 * - No taskFilter ref or data-test chip selectors (my-tasks-chip, all-tasks-chip)
 * - Uses taskStore, productStore, userStore
 * - Task creation via showTaskDialog ref
 * - Inline v-select dropdowns for status/priority editing
 * - Tasks filtered by productStore.effectiveProductId
 * - Component uses <script setup> - no setData(), access refs via wrapper.vm
 */

import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import TasksView from '@/views/TasksView.vue'
import TaskEditDialog from '@/views/tasks/TaskEditDialog.vue'
import api from '@/services/api'
import { useTaskStore } from '@/stores/tasks'
import { useNotificationStore } from '@/stores/notifications'
import { useProductStore } from '@/stores/products'

// Mock API
vi.mock('@/services/api', () => ({
  default: {
    tasks: {
      list: vi.fn().mockResolvedValue({ data: [] }),
      create: vi.fn().mockResolvedValue({ data: {} }),
      update: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn().mockResolvedValue({}),
    },
    users: {
      list: vi.fn().mockResolvedValue({ data: [] }),
    },
    agents: {
      list: vi.fn().mockResolvedValue({ data: [] }),
    },
    settings: {
      getHandoverTemplate: vi.fn().mockResolvedValue({
        data: { handover_template: '## Verify before trusting\n- <fill this in>', is_default: true },
      }),
    },
  },
}))

// api is used via vi.mock only (the mock reference is consumed by module resolution)

describe('TasksView - Component Rendering', () => {
  let vuetify

  beforeEach(() => {
    setActivePinia(createPinia())
    vuetify = createVuetify({ components, directives })
    vi.clearAllMocks()
  })

  it('renders the component without errors', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('displays page title "Tasks"', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    expect(wrapper.text()).toContain('Tasks')
  })

  it('renders a v-data-table for tasks', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    // Global test setup stubs v-data-table as <div class="v-data-table">
    const dataTable = wrapper.find('.v-data-table')
    expect(dataTable.exists()).toBe(true)
  })

  it('has search field for tasks', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    expect(wrapper.vm.search).toBe('')
  })

  it('has status and priority filter refs', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    expect(wrapper.vm.statusFilter).toBeNull()
    expect(wrapper.vm.priorityFilter).toBeNull()
  })
})

describe('TasksView - Task Statistics', () => {
  let vuetify

  beforeEach(() => {
    setActivePinia(createPinia())
    vuetify = createVuetify({ components, directives })
    vi.clearAllMocks()
  })

  it('displays task page with new task button', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    expect(wrapper.text()).toContain('Tasks')
    // The toolbar is icon-only: the New task entry is identified by its aria-label.
    expect(wrapper.find('[aria-label="Create new task"]').exists()).toBe(true)
  })
})

describe('TasksView - Task Dialog', () => {
  let vuetify

  beforeEach(() => {
    setActivePinia(createPinia())
    vuetify = createVuetify({ components, directives })
    vi.clearAllMocks()
  })

  it('has showTaskDialog ref initialized to false', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    expect(wrapper.vm.showTaskDialog).toBe(false)
  })

  it('has saveTask method', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    expect(typeof wrapper.vm.saveTask).toBe('function')
  })

  it('has currentTask ref with default values', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    expect(wrapper.vm.currentTask).toBeDefined()
    expect(wrapper.vm.currentTask.status).toBe('pending')
    expect(wrapper.vm.currentTask.priority).toBe('medium')
  })
})

describe('TasksView - Table Headers', () => {
  let vuetify

  beforeEach(() => {
    setActivePinia(createPinia())
    vuetify = createVuetify({ components, directives })
    vi.clearAllMocks()
  })

  it('has correct table headers', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    // Access headers directly from the component instance since
    // the global test setup stubs VDataTable as a simple div
    const headers = wrapper.vm.headers

    const headerKeys = headers.map((h) => h.key)
    expect(headerKeys).toContain('status')
    expect(headerKeys).toContain('priority')
    expect(headerKeys).toContain('title')
    expect(headerKeys).toContain('actions')
  })

  // FE-5046: Type+Serial parity with ProjectsView
  it('exposes a taxonomy_alias (Serial) column and no standalone task_type column', async () => {
    const wrapper = mount(TasksView, {
      global: { plugins: [vuetify] },
    })
    await flushPromises()
    const headerKeys = wrapper.vm.headers.map((h) => h.key)
    expect(headerKeys).toContain('taxonomy_alias')
    expect(headerKeys).not.toContain('task_type')
  })

  it('renders Serial column BEFORE Title column', async () => {
    const wrapper = mount(TasksView, {
      global: { plugins: [vuetify] },
    })
    await flushPromises()
    const keys = wrapper.vm.headers.map((h) => h.key)
    expect(keys.indexOf('taxonomy_alias')).toBeLessThan(keys.indexOf('title'))
  })
})

// Contract guard for the dialog → save → POST wiring (task-create silent-fail
// finding, 2026-06-11). The TaskEditDialog `update:current-task` event MUST
// flow back into the composable's `currentTask` ref, and the save path MUST
// POST that title — otherwise task creation no-ops with no error toast. These
// tests lock that wiring so it cannot silently break again, regardless of how
// the template binding is compiled.
describe('TasksView - currentTask binding (silent-save regression)', () => {
  let vuetify

  beforeEach(() => {
    setActivePinia(createPinia())
    vuetify = createVuetify({ components, directives })
    vi.clearAllMocks()
  })

  it('propagates dialog update:current-task back to the currentTask ref', async () => {
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()

    const dialog = wrapper.findComponent(TaskEditDialog)
    expect(dialog.exists()).toBe(true)

    // Simulate the user typing a Title in the dialog (the dialog emits the
    // whole patched object via updateField → emit('update:currentTask', ...)).
    dialog.vm.$emit('update:currentTask', {
      ...wrapper.vm.currentTask,
      title: 'Wire the new endpoint',
    })
    await flushPromises()

    expect(wrapper.vm.currentTask.title).toBe('Wire the new endpoint')
  })

  it('saveTask POSTs the typed title (end-to-end create path)', async () => {
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()

    // Type a title via the same event the dialog fires.
    wrapper.findComponent(TaskEditDialog).vm.$emit('update:currentTask', {
      ...wrapper.vm.currentTask,
      title: 'Created via save path',
    })
    await flushPromises()

    // Drive the save with a form ref that validates clean (create mode:
    // editingTask is null by default).
    const formRef = { value: { validate: async () => ({ valid: true }) } }
    await wrapper.vm.saveTask(formRef)
    await flushPromises()

    expect(api.tasks.create).toHaveBeenCalledTimes(1)
    expect(api.tasks.create.mock.calls[0][0]).toMatchObject({
      title: 'Created via save path',
    })
  })

  // The REAL prod/staging shape (caught only in a real browser on test.giljo.ai):
  // the dialog's `@click="$emit('save', taskFormRef)"` runs in the TEMPLATE, which
  // AUTO-UNWRAPS the ref, so the parent receives the v-form INSTANCE, not a ref.
  // The old `taskForm.value.validate()` then threw `undefined.validate()` →
  // swallowed → silent no-op (no POST). This test drives the instance shape and
  // would FAIL on the old code, PASS on the normalized saveTask.
  it('saveTask handles the unwrapped v-form INSTANCE shape (real dialog emit)', async () => {
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()

    wrapper.findComponent(TaskEditDialog).vm.$emit('update:currentTask', {
      ...wrapper.vm.currentTask,
      title: 'Instance shape works',
    })
    await flushPromises()

    // Instance shape: validate() is on the object directly, NOT under `.value`.
    const formInstance = { validate: async () => ({ valid: true }) }
    wrapper.findComponent(TaskEditDialog).vm.$emit('save', formInstance)
    await flushPromises()

    expect(api.tasks.create).toHaveBeenCalledTimes(1)
    expect(api.tasks.create.mock.calls[0][0]).toMatchObject({ title: 'Instance shape works' })
  })

  it('saveTask surfaces an error (no silent no-op) when the form ref is unusable', async () => {
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()

    wrapper.findComponent(TaskEditDialog).vm.$emit('update:currentTask', {
      ...wrapper.vm.currentTask,
      title: 'Should not POST',
    })
    await flushPromises()

    // No usable form (neither instance nor ref) → must NOT POST, must not throw.
    await wrapper.vm.saveTask(undefined)
    await flushPromises()

    expect(api.tasks.create).not.toHaveBeenCalled()
  })

  // FE-9643c decision 4: the server's VALIDATION_ERROR message must be
  // readable IN the dialog itself, not only as a toast (EM_114 ruling,
  // 2026-09-24) -- proven end to end through the real save path and the
  // real (unstubbed) TaskEditDialog child, not just at the composable layer.
  it('a VALIDATION_ERROR on save renders the server message verbatim inside the dialog', async () => {
    const serverMessage =
      "A handover task (task_type='HND') must carry these headings in its description, " +
      "and is missing '## Cannot testify'."
    api.tasks.create.mockRejectedValueOnce(
      Object.assign(new Error('Request failed with status code 422'), {
        response: {
          status: 422,
          data: { error_code: 'VALIDATION_ERROR', message: serverMessage, context: {} },
        },
      }),
    )
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()

    wrapper.findComponent(TaskEditDialog).vm.$emit('update:currentTask', {
      ...wrapper.vm.currentTask,
      title: 'A handover missing a section',
    })
    await flushPromises()

    const formRef = { value: { validate: async () => ({ valid: true }) } }
    await wrapper.vm.saveTask(formRef)
    await flushPromises()

    // Not just "the composable knows the message" -- the actual rendered
    // dialog HTML contains the server's own words, verbatim.
    const dialog = wrapper.findComponent(TaskEditDialog)
    expect(dialog.props('saveError')).toBe(serverMessage)
    expect(dialog.text()).toContain(serverMessage)
    expect(dialog.find('[data-test="dialog-save-error"]').text()).toBe(serverMessage)
  })
})

describe('TasksView - Filter Controls', () => {
  let vuetify

  beforeEach(() => {
    setActivePinia(createPinia())
    vuetify = createVuetify({ components, directives })
    vi.clearAllMocks()
  })

  it('has clearFilters method', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    expect(typeof wrapper.vm.clearFilters).toBe('function')
  })

  it('has New Task button', async () => {
    const wrapper = mount(TasksView, {
      global: {
        plugins: [vuetify],
      },
    })

    await flushPromises()
    // FE-9365f: icon-only button; the accessible name is what a user (and a screen
    // reader) actually gets, so that is what the test pins.
    const btn = wrapper.find('[aria-label="Create new task"]')
    expect(btn.exists()).toBe(true)
  })
})

// FE-9643c: the "+" control is now a menu offering "New task" (unchanged
// behavior) and "New Agent Handover" (the six-field handover form).
describe('TasksView - New Agent Handover menu entry', () => {
  let vuetify

  beforeEach(() => {
    setActivePinia(createPinia())
    vuetify = createVuetify({ components, directives })
    vi.clearAllMocks()
  })

  it('offers a "New Agent Handover" menu entry alongside New task', async () => {
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()
    expect(wrapper.find('[data-testid="new-task-menu-item"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="new-handover-menu-item"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('New Agent Handover')
  })

  it('New task menu entry still opens an ordinary (non-HND) dialog', async () => {
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()
    useProductStore().currentProductId = 'product-1'

    await wrapper.find('[data-testid="new-task-menu-item"]').trigger('click')
    await flushPromises()

    expect(wrapper.vm.showTaskDialog).toBe(true)
    expect(wrapper.vm.currentTask.task_type).toBeNull()
    expect(api.settings.getHandoverTemplate).not.toHaveBeenCalled()
  })

  it('New Agent Handover opens the dialog empty, without fetching the template', async () => {
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()
    useProductStore().currentProductId = 'product-1'

    await wrapper.find('[data-testid="new-handover-menu-item"]').trigger('click')
    await flushPromises()

    expect(api.settings.getHandoverTemplate).not.toHaveBeenCalled()
    expect(wrapper.vm.showTaskDialog).toBe(true)
    expect(wrapper.vm.currentTask.task_type).toBe('HND')
    expect(wrapper.vm.currentTask.description).toBe('')
  })

  it('New Agent Handover shows the No Product dialog instead of fetching when no product is open', async () => {
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()
    // The shared test-setup pinia instance (tests/setup.js) outlives any single
    // test, so a prior test's product selection can still be sitting there --
    // force the "no product open" precondition explicitly rather than assume it.
    useProductStore().currentProductId = null
    useProductStore().activeProduct = null

    await wrapper.find('[data-testid="new-handover-menu-item"]').trigger('click')
    await flushPromises()

    expect(wrapper.vm.showNoProductDialog).toBe(true)
    expect(wrapper.vm.showTaskDialog).toBe(false)
    expect(api.settings.getHandoverTemplate).not.toHaveBeenCalled()
  })
})

// FE-5046: Task UI parity with ProjectsView — Type+Serial badge, edit
// modal field order, hide/show action, default hidden:false filter.
describe('TasksView - FE-5046 task parity', () => {
  let vuetify

  beforeEach(() => {
    setActivePinia(createPinia())
    vuetify = createVuetify({ components, directives })
    vi.clearAllMocks()
  })

  // The v-data-table is globally stubbed as <div><slot/></div> in
  // tests/setup.js, so item.* scoped slots don't render their own
  // markup. We assert taxonomy parity at the data layer (store +
  // headers) and verify the badge-style helper independently.
  it('exposes taxonomy_alias on hydrated task records (typed task)', async () => {
    api.tasks.list.mockResolvedValueOnce({
      data: [
        {
          id: 't1',
          title: 'Wire BE serializer',
          description: '',
          status: 'pending',
          priority: 'medium',
          product_id: 'p1',
          taxonomy_alias: 'BE-0017',
          series_number: 17,
          subseries: null,
          task_type: { abbreviation: 'BE', color: '#6DB3E4' },
          hidden: false,
        },
      ],
    })
    mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()
    const store = useTaskStore()
    expect(store.tasks).toHaveLength(1)
    expect(store.tasks[0].taxonomy_alias).toBe('BE-0017')
    expect(store.tasks[0].task_type?.color).toBe('#6DB3E4')
  })

  it('keeps taxonomy_alias null for untyped (legacy) tasks', async () => {
    api.tasks.list.mockResolvedValueOnce({
      data: [
        {
          id: 't2',
          title: 'Legacy untyped',
          description: '',
          status: 'pending',
          priority: 'low',
          product_id: 'p1',
          taxonomy_alias: null,
          task_type: null,
          hidden: false,
        },
      ],
    })
    mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()
    const store = useTaskStore()
    expect(store.tasks[0].taxonomy_alias).toBeNull()
    expect(store.tasks[0].task_type).toBeNull()
  })

  it('Edit modal renders fields in order: Type → Serial → Title', async () => {
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()
    // The edit-task data-test attributes mark the three fields. We
    // assert DOM order via outerHTML index lookup since the global
    // setup stubs v-text-field/v-select as flat inputs.
    const html = wrapper.html()
    const typeIdx = html.indexOf('data-test="edit-task-type"')
    const serialIdx = html.indexOf('data-test="edit-task-serial"')
    const titleIdx = html.indexOf('data-test="edit-task-title"')
    expect(typeIdx).toBeGreaterThan(-1)
    expect(serialIdx).toBeGreaterThan(-1)
    expect(titleIdx).toBeGreaterThan(-1)
    expect(typeIdx).toBeLessThan(serialIdx)
    expect(serialIdx).toBeLessThan(titleIdx)
  })

  it('default fetchTasks call passes no hidden param to api.tasks.list', async () => {
    api.tasks.list.mockClear()
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    // BE-2002: the prior { hidden: false } param was a silent no-op (the list
    // endpoint has no server-side hidden filter). The fetch now pulls the full
    // set; default-view archived exclusion is client-side and locked in
    // useTaskFilters.spec.js.
    expect(api.tasks.list).toHaveBeenCalled()
    const lastCallArg = api.tasks.list.mock.calls.at(-1)?.[0]
    expect(lastCallArg).toBeDefined()
    expect(lastCallArg.hidden).toBeUndefined()
  })

  it('toggleHidden calls taskStore.updateTask with flipped hidden flag', async () => {
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()
    const store = useTaskStore()
    const spy = vi.spyOn(store, 'updateTask').mockResolvedValue({})
    await wrapper.vm.toggleHidden({ id: 'task-99', title: 'X', hidden: false })
    expect(spy).toHaveBeenCalledWith('task-99', { hidden: true })
    await wrapper.vm.toggleHidden({ id: 'task-99', title: 'X', hidden: true })
    expect(spy).toHaveBeenLastCalledWith('task-99', { hidden: false })
  })
})

// FE-9466: save/mutation failures become persistent notifications instead of a
// swallowed string. These three bare catch{} wrappers previously only set a
// hardcoded generic errorMessage + showErrorDialog=true -- the server's own
// reason (when structured) never reached the user anywhere durable.
function structuredServerError(message, errorCode = 'TASK_STATE_ERROR', status = 409) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: { error_code: errorCode, message, context: {} } },
  })
}

describe('TasksView - save/mutation failures become notifications (FE-9466)', () => {
  let vuetify

  beforeEach(() => {
    // restoreAllMocks (not just clearAllMocks): the preceding 'toggleHidden'
    // test spies on a REAL pinia store instance via vi.spyOn(store,
    // 'updateTask') and never restores it. clearAllMocks resets call
    // history but leaves a vi.spyOn replacement installed -- and it turns
    // out to survive into a later test's freshly-mounted TasksView (traced
    // by execution: the "fresh" store a later test reads back off a new
    // pinia still carries `_isMockFunction: true` unless this runs first),
    // silently swallowing the real api.tasks.update path this suite drives.
    vi.restoreAllMocks()
    setActivePinia(createPinia())
    vuetify = createVuetify({ components, directives })
    vi.clearAllMocks()
  })

  // The composable's own completeTask() catch ALSO pushes a notification
  // (useTaskCrud.spec.js covers that in isolation). Both layers catch the
  // SAME rethrown error for the SAME task -- proving here that only one
  // notification survives is what makes the dedup-by-id ruling correct
  // rather than merely convenient.
  it('completeTask: stacked composable + view catches collapse to ONE notification', async () => {
    const serverMessage = 'Cannot complete a task with unresolved subtasks.'
    api.tasks.update.mockRejectedValueOnce(
      structuredServerError(serverMessage, 'TASK_HAS_OPEN_SUBTASKS'),
    )
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()

    await wrapper.vm.completeTask({ id: 'task-77', title: 'x' })
    await flushPromises()

    const notificationStore = useNotificationStore()
    const matches = notificationStore.notifications.filter((n) => n.message === serverMessage)
    expect(matches).toHaveLength(1)
  })

  it('updateTaskField: surfaces the server reason as a persistent notification', async () => {
    const serverMessage = 'Status transition not allowed from completed.'
    api.tasks.update.mockRejectedValueOnce(
      structuredServerError(serverMessage, 'INVALID_STATUS_TRANSITION'),
    )
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()

    await wrapper.vm.updateTaskField({ id: 'task-88', title: 'x' }, 'status', 'pending')
    await flushPromises()

    const notificationStore = useNotificationStore()
    expect(notificationStore.notifications.some((n) => n.message === serverMessage)).toBe(true)
  })

  it('never surfaces a raw exception/stack trace on an unstructured failure', async () => {
    api.tasks.update.mockRejectedValueOnce(new Error('ECONNRESET at TCP.onread (net.js:123)'))
    const wrapper = mount(TasksView, { global: { plugins: [vuetify] } })
    await flushPromises()

    await wrapper.vm.updateTaskField({ id: 'task-100', title: 'x' }, 'status', 'pending')
    await flushPromises()

    const notificationStore = useNotificationStore()
    for (const n of notificationStore.notifications) {
      expect(n.message ?? '').not.toMatch(/ECONNRESET|net\.js/)
    }
  })
})
