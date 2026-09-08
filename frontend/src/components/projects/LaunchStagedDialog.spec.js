/**
 * LaunchStagedDialog.spec.js — FE-9555
 *
 * The board-level "Launch staged..." confirm dialog. Three jobs, in order:
 * (a) list the missions being approved, (b) ask the execution-mode question,
 * (c) hand over ONE copyable master prompt.
 *
 * Ruling 3: this dialog is UI ERGONOMICS, not a server gate. The only real gate
 * is server-side (the staging pause and launch_implementation admission), and a
 * headless agent never sees this dialog at all. So nothing here may be written as
 * though it were protecting anything — its whole job is to put the missions in
 * front of a human before they commit, and to ask the one question.
 *
 * Ruling 4: the UI door NEVER executes. The dialog prepares a prompt. It does not
 * create the sequence_run, does not launch, does not stage. The pasted session
 * writes the record itself via link_projects. A test below pins that, because
 * "while we're here, just create the run too" is the obvious wrong turn and it
 * would put a second writer on the record.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const mockBuild = vi.fn()
const mockCopy = vi.fn().mockResolvedValue(true)

vi.mock('@/services/api', () => {
  const apiMock = { prompts: { buildMasterPrompt: (...a) => mockBuild(...a) } }
  return { api: apiMock, default: apiMock }
})

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copied: { value: false }, copy: mockCopy }),
}))

import LaunchStagedDialog from './LaunchStagedDialog.vue'

const PROJECTS = [
  { id: 'p-1', name: 'First thing', taxonomy_alias: 'FE-0001' },
  { id: 'p-2', name: 'Second thing', taxonomy_alias: 'BE-0002' },
]

const SERVER_RESPONSE = {
  data: {
    prompt: 'MASTER PROMPT BODY',
    execution_mode: 'subagent',
    projects: [
      { project_id: 'p-1', taxonomy_alias: 'FE-0001', name: 'First thing', mission: 'Do the first thing.' },
      { project_id: 'p-2', taxonomy_alias: 'BE-0002', name: 'Second thing', mission: 'Then the second.' },
    ],
  },
}

const stubs = {
  'v-btn': { template: '<button class="v-btn" :disabled="disabled" v-bind="$attrs"><slot /></button>', props: ['disabled'] },
  'v-icon': { template: '<i><slot /></i>' },
  'v-radio-group': {
    template: '<div class="v-radio-group"><slot /></div>',
    props: ['modelValue'],
  },
  'v-radio': { template: '<label class="v-radio" v-bind="$attrs"><slot /></label>' },
  'v-progress-circular': { template: '<div class="v-progress-circular" />' },
  'v-alert': { template: '<div class="v-alert"><slot /></div>' },
  BaseDialog: {
    template: '<div class="base-dialog" v-if="modelValue"><slot /><slot name="actions" /></div>',
    props: ['modelValue', 'title', 'type', 'size', 'persistent'],
  },
}

function mountDialog(props = {}) {
  return mount(LaunchStagedDialog, {
    props: { modelValue: true, projects: PROJECTS, ...props },
    global: { stubs },
  })
}

describe('LaunchStagedDialog (FE-9555)', () => {
  beforeEach(() => {
    mockBuild.mockReset()
    mockBuild.mockResolvedValue(SERVER_RESPONSE)
    mockCopy.mockClear()
  })

  it('names every selected project so the user can see what they are approving', async () => {
    const wrapper = mountDialog()
    await flushPromises()

    expect(wrapper.text()).toContain('First thing')
    expect(wrapper.text()).toContain('Second thing')
  })

  it('shows each mission once the server has answered, not just the project names', async () => {
    // The missions arrive WITH the prompt, so they cannot appear before the mode
    // question is answered -- that is the no-fetch-until-answered rule two tests
    // below, not a gap. Until then the dialog lists what the board already knew.
    const wrapper = mountDialog()
    wrapper.vm.executionMode = 'subagent'
    await flushPromises()

    expect(wrapper.text()).toContain('Do the first thing.')
    expect(wrapper.text()).toContain('Then the second.')
  })

  it('asks the execution-mode question and starts on neither answer', () => {
    const wrapper = mountDialog()

    // NULL-state, matching ExecutionModeSelector: unchosen until chosen. A
    // pre-selected radio is a silent pick wearing a question's clothes.
    expect(wrapper.vm.executionMode).toBe(null)
    expect(wrapper.find('[data-testid="launch-staged-mode"]').exists()).toBe(true)
  })

  it('does not fetch a prompt until the mode question is answered', async () => {
    mountDialog()
    await flushPromises()

    expect(mockBuild).not.toHaveBeenCalled()
  })

  it('fetches the prompt from the server once a mode is chosen', async () => {
    const wrapper = mountDialog()
    wrapper.vm.executionMode = 'subagent'
    await flushPromises()

    expect(mockBuild).toHaveBeenCalledWith({
      project_ids: ['p-1', 'p-2'],
      execution_mode: 'subagent',
    })
    expect(wrapper.text()).toContain('MASTER PROMPT BODY')
  })

  it('re-fetches when the user changes their mind about the mode', async () => {
    const wrapper = mountDialog()
    wrapper.vm.executionMode = 'subagent'
    await flushPromises()
    wrapper.vm.executionMode = 'multi_terminal'
    await flushPromises()

    expect(mockBuild).toHaveBeenLastCalledWith({
      project_ids: ['p-1', 'p-2'],
      execution_mode: 'multi_terminal',
    })
  })

  it('never builds the prompt in the browser -- the server is the only author', async () => {
    /**
     * BE-9504a drift guard. If the dialog ever assembled prose itself, the UI copy
     * and the MCP payload would drift apart a sentence at a time, which is the
     * exact failure the shared-generator rule exists to prevent.
     */
    const wrapper = mountDialog()
    wrapper.vm.executionMode = 'subagent'
    await flushPromises()

    expect(wrapper.vm.prompt).toBe('MASTER PROMPT BODY')
  })

  it('copies the server prompt verbatim', async () => {
    const wrapper = mountDialog()
    wrapper.vm.executionMode = 'subagent'
    await flushPromises()

    await wrapper.find('[data-testid="launch-staged-copy"]').trigger('click')

    expect(mockCopy).toHaveBeenCalledWith('MASTER PROMPT BODY')
  })

  it('executes nothing: no launch, no staging, no sequence-run creation', async () => {
    /**
     * Ruling 4 -- the UI door prepares prompts and crosses gates; it never runs
     * anything. The pasted session writes the run record itself via link_projects,
     * so a helpful "create the run while we're here" would put a SECOND writer on
     * that record. The only call this dialog may make is the prompt build.
     */
    const { api } = await import('@/services/api')
    const wrapper = mountDialog()
    wrapper.vm.executionMode = 'subagent'
    await flushPromises()
    await wrapper.find('[data-testid="launch-staged-copy"]').trigger('click')

    expect(Object.keys(api)).toEqual(['prompts'])
    expect(mockBuild).toHaveBeenCalledTimes(1)
  })

  it('surfaces a failed build instead of offering an empty prompt to copy', async () => {
    mockBuild.mockRejectedValue(new Error('boom'))
    const wrapper = mountDialog()
    wrapper.vm.executionMode = 'subagent'
    await flushPromises()

    expect(wrapper.find('[data-testid="launch-staged-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="launch-staged-copy"]').exists()).toBe(false)
  })
})
