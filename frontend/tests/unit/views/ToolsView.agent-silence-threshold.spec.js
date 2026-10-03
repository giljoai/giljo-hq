/**
 * ToolsView.agent-silence-threshold.spec.js — PLACEMENT ONLY as of FE-9553,
 * and one level further down as of FE-9616.
 *
 * This file used to mount the whole view and assert that the agent silence
 * threshold and check-in cadence loaded and saved. That worked only because
 * those inputs happened to sit on the Notifications tab, which the view renders
 * eagerly. FE-9553 relocated them to Tools -> Agents, into the Agent Behaviour
 * Settings group, on the record's instruction that each tab should mean one
 * thing -- they tune how agents behave, not how notifications display.
 *
 * The BEHAVIOUR (load, save, the value each API call receives, the CE/hosted
 * question) moved with them and is asserted at the component that now owns it:
 * src/components/settings/AgentTimingSettings.spec.js. That spec also covers
 * two things this one could not reach -- an invalid keystroke, and one load
 * failing without taking the other down.
 *
 * What is left here is the claim only the VIEW can make: that the controls are
 * actually reachable from the page, on the tab they were moved to. FE-9616 moved
 * them again, from a block on that tab into a dialog the roster's toolbar opens,
 * so the claim is now that the tab renders the roster and holds no settings block
 * of its own. Kept as its
 * own file rather than folded away, because "the component exists and works"
 * and "the component is wired into the page" are different failures and the
 * second one is the sort that ships.
 *
 * Edition Scope: Both
 */
import { readFileSync } from 'fs'
import { resolve } from 'path'

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import configService from '@/services/configService'

const modeState = vi.hoisted(() => ({ value: 'ce' }))
const apiMock = vi.hoisted(() => ({
  settings: {
    get: vi.fn(() => Promise.resolve({ data: { notifications: {} } })),
    getAgentSilenceThreshold: vi.fn(() =>
      Promise.resolve({ data: { agent_silence_threshold_minutes: 22 } }),
    ),
    updateAgentSilenceThreshold: vi.fn(() => Promise.resolve({ data: {} })),
    getAgentCheckinCadence: vi.fn(() =>
      Promise.resolve({ data: { agent_checkin_cadence_minutes: 15 } }),
    ),
    updateAgentCheckinCadence: vi.fn(() => Promise.resolve({ data: {} })),
    getNotificationPrefs: vi.fn(() =>
      Promise.resolve({ data: { notification_preferences: {} } }),
    ),
    updateNotificationPrefs: vi.fn(() =>
      Promise.resolve({ data: { notification_preferences: {} } }),
    ),
  },
  notifications: { list: vi.fn(() => Promise.resolve({ data: [] })) },
}))

vi.mock('@/services/api', () => ({ default: apiMock, api: apiMock }))

vi.mock('@/services/setupService', () => ({
  default: {
    checkEnhancedStatus: vi.fn(() => Promise.resolve({ mode: modeState.value })),
    getGitSettings: vi.fn(() => Promise.resolve({ enabled: false })),
    toggleGit: vi.fn(() => Promise.resolve({ success: true, enabled: true })),
  },
}))

const childStubs = {
  TemplateManager: { template: '<div data-test="template-manager" />' },
  ApiKeyManager: { template: '<div data-test="api-key-manager" />' },
  AgentExport: { template: '<div data-test="agent-export" />' },
  ContextPriorityConfig: { template: '<div data-test="context-priority" />' },
  McpIntegrationCard: { template: '<div data-test="mcp-card" />' },
  GitIntegrationCard: { template: '<div data-test="git-card" />' },
}

describe('ToolsView — FE-9553 relocation and the four notification cards', () => {
  let router

  beforeEach(async () => {
    vi.clearAllMocks()
    localStorage.clear()
    modeState.value = 'ce'
    configService.config = { giljo_mode: 'ce', mode: 'server', api: {} }
    setActivePinia(createPinia())
    router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', name: 'Tools', component: { template: '<div />' } }],
    })
    await router.push('/')
    await router.isReady()
  })

  async function mountView(tab) {
    const { default: ToolsView } = await import('@/views/ToolsView.vue')
    const wrapper = mount(ToolsView, {
      global: { plugins: [router], stubs: childStubs },
    })
    if (tab) {
      wrapper.vm.activeTab = tab
      await flushPromises()
    }
    await flushPromises()
    return wrapper
  }

  // load-sensitive: the dynamic import + mount can exceed vitest's 5s default
  // when this spec runs alongside the two -n6 pytest jobs on a busy CI runner.
  //
  // FE-9616: the agents tab renders the roster and nothing else. The timing
  // controls did not leave the product -- they moved one level down, into the
  // behaviour dialog the roster's own toolbar opens -- so the reachability claim
  // this file makes is now "the agents tab renders the manager that owns them",
  // and the dialog's own contents are asserted in
  // src/components/settings/AgentBehaviourDialog.spec.js.
  it('mounts the agent roster on the agents tab', async () => {
    const wrapper = await mountView('agents')

    expect(wrapper.find('[data-test="template-manager"]').exists()).toBe(true)
  }, 15000)

  // WHICH TAB a control sits on is asserted from the SOURCE, not by mounting,
  // and the reason matters: tests/setup.js stubs v-window-item as a plain div
  // that renders its default slot, so EVERY tab renders simultaneously under
  // test regardless of activeTab. My first draft of this suite mounted with
  // activeTab='notifications' and asserted the agent controls were absent --
  // it failed, and it would have been just as meaningless had it passed, since
  // the mount cannot see tabs at all. (That is also why the pre-FE-9553 spec
  // could find these inputs without ever activating a tab.)
  //
  // So the placement claim is made against the template text, with a
  // known-positive first so an empty read cannot masquerade as a clean one.
  describe('placement, asserted structurally', () => {
    const source = readFileSync(resolve(__dirname, '../../../src/views/ToolsView.vue'), 'utf8')

    /** The markup between one v-window-item's value="..." and the next. */
    function tabBlock(value) {
      const start = source.indexOf(`<v-window-item value="${value}">`)
      expect(start).toBeGreaterThan(-1) // known-positive: the tab exists
      const end = source.indexOf('<v-window-item', start + 1)
      return source.slice(start, end === -1 ? source.length : end)
    }

    it('leaves the agents tab to the roster alone', () => {
      // FE-9616: the five behaviour settings open from the roster's toolbar, so
      // the tab holds ONE child. A settings component reappearing here means the
      // block grew back and the same 250px is being paid for twice.
      const block = tabBlock('agents')
      expect(block).toContain('<TemplateManager')
      expect(block).not.toContain('<AgentTimingSettings')
      expect(block).not.toContain('<ExecutionModeDefaultSelect')
      expect(block).not.toContain('<OrchestrationToggles')
    })

    it('does NOT leave the agent controls in the notifications tab', () => {
      // The point of the relocation. If this regresses they are in two places
      // and one of them is stale.
      const block = tabBlock('notifications')
      expect(block).not.toContain('AgentTimingSettings')
      expect(block).not.toContain('silence-threshold-input')
      expect(block).not.toContain('agent-monitoring-settings')
    })

    it('puts the four notification cards in the notifications tab, in the ruled order', () => {
      const block = tabBlock('notifications')
      const order = ['BannerPreferencesCard', 'PopoutPreferencesCard', 'ToastPreferencesCard', 'BellPreferencesCard']
      const positions = order.map((name) => block.indexOf(`<${name}`))
      expect(positions.every((p) => p > -1)).toBe(true)
      // The record's order: what asks you for something, then the medium that
      // delivers it, then feedback, then the archive.
      expect([...positions].sort((a, b) => a - b)).toEqual(positions)
    })
  })

  it('renders all four notification cards on the notifications tab', async () => {
    // The four-card structure is the record's spec for this tab, and a card
    // silently failing to mount is exactly the defect a component-only spec
    // cannot see.
    const wrapper = await mountView('notifications')

    for (const card of [
      'banner-preferences',
      'popout-preferences',
      'notification-settings', // the toast card keeps this hook, and its specs with it
      'bell-preferences',
    ]) {
      expect(wrapper.find(`[data-test="${card}"]`).exists()).toBe(true)
    }
  }, 15000)

})
