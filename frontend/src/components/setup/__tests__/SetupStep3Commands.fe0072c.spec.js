import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ copy: vi.fn(async () => true) }))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: (...a) => h.copy(...a) }) }))

import SetupStep3Commands from '../SetupStep3Commands.vue'
import { useStartListStore } from '@/stores/startList'
import { SETUP_REQUEST } from '@/content/onboarding/guide'
import { startListPayload } from '../../../../tests/helpers/startListRows'

const stubs = { 'v-icon': { template: '<i><slot /></i>' } }

function mountStep(tools, skillsDone = false) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const list = useStartListStore()
  list.rows = startListPayload({ skills_installed: { done: skillsDone } }).rows
  return mount(SetupStep3Commands, { props: { tools }, global: { plugins: [pinia], stubs } })
}
const line = (w) => w.get('[data-testid="setup-ask-line"]').text()

describe('Setup instructions: the tool name in the line', () => {
  beforeEach(() => h.copy.mockClear())

  it('one pick: names that tool', () => {
    expect(line(mountStep(['codex_cli']))).toBe('Ask your Codex CLI to run giljo_setup.')
  })

  it('several picks: a tab per pick, the first pick shown, and the line follows the tab', async () => {
    const w = mountStep(['opencode', 'claude_code'])
    expect(w.findAll('[role="tab"]')).toHaveLength(2)
    expect(line(w)).toBe('Ask your OpenCode to run giljo_setup.')
    await w.findAll('[role="tab"]')[1].trigger('click')
    expect(line(w)).toBe('Ask your Claude Code to run giljo_setup.')
  })

  it('no pick: a neutral line, never a made-up tool', () => {
    const w = mountStep([])
    expect(line(w)).toBe('Ask your AI tool to run giljo_setup.')
    expect(w.text()).not.toContain('Claude Code')
    expect(w.findAll('[role="tab"]')).toHaveLength(0)
  })

  it('an unknown pick id is not shown as a name', () => {
    expect(line(mountStep(['nonsense']))).toBe('Ask your AI tool to run giljo_setup.')
  })

  it('says nothing about installing agents', () => {
    expect(mountStep(['claude_code']).text().toLowerCase()).not.toContain('agent')
  })
})

describe('Setup instructions: copy the request', () => {
  beforeEach(() => h.copy.mockClear())

  it('copies the same request text the side pane copies and answers Copied', async () => {
    const w = mountStep(['claude_code'])
    const btn = w.get('[data-testid="setup-copy-request"]')
    expect(btn.text()).toBe('Copy the request')
    await btn.trigger('click')
    await flushPromises()
    expect(h.copy).toHaveBeenCalledWith(SETUP_REQUEST)
    expect(w.get('[data-testid="setup-copy-request"]').text()).toBe('Copied')
  })

  it('a failed copy does not say Copied', async () => {
    h.copy.mockResolvedValueOnce(false)
    const w = mountStep(['claude_code'])
    await w.get('[data-testid="setup-copy-request"]').trigger('click')
    await flushPromises()
    expect(w.get('[data-testid="setup-copy-request"]').text()).toBe('Copy the request')
  })
})

describe('Setup instructions: the done dot is the server fact', () => {
  it('open while the start list says setup is not done', () => {
    expect(mountStep(['claude_code'], false).get('[data-testid="setup-skills-dot"]').attributes('data-done')).toBe('false')
  })

  it('done when the start list says so', () => {
    expect(mountStep(['claude_code'], true).get('[data-testid="setup-skills-dot"]').attributes('data-done')).toBe('true')
  })

  it('follows the store when the fact changes while the step is open', async () => {
    const w = mountStep(['claude_code'], false)
    useStartListStore().rows = startListPayload({ skills_installed: { done: true } }).rows
    await w.vm.$nextTick()
    expect(w.get('[data-testid="setup-skills-dot"]').attributes('data-done')).toBe('true')
  })

  it('an unread start list is open, not done', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const w = mount(SetupStep3Commands, { props: { tools: ['claude_code'] }, global: { plugins: [pinia], stubs } })
    expect(w.get('[data-testid="setup-skills-dot"]').attributes('data-done')).toBe('false')
  })
})
