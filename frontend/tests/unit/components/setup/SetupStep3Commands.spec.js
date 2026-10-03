/**
 * Unit tests for SetupStep3Commands component (Handover 0855e)
 * Covers: rendering, giljo_setup command display, mini-checklist, WebSocket events,
 * post-install agent command, can-proceed logic, skip behavior, tab switching.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import SetupStep3Commands from '@/components/setup/SetupStep3Commands.vue'

// --- Mock stores ---

const mockUnsub = vi.fn()
const mockWsOn = vi.fn(() => mockUnsub)

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on: mockWsOn,
    off: vi.fn(),
    isConnected: true,
  }),
}))

// --- Mount helper ---

function mountStep3(props = {}) {
  return mount(SetupStep3Commands, {
    props: {
      connectedTools: ['claude_code'],
      ...props,
    },
    global: {
      plugins: [createPinia()],
      stubs: {
        Transition: { template: '<div><slot /></div>' },
      },
    },
  })
}

// --- Tests ---

describe('SetupStep3Commands', () => {
  // Fire the event a real giljo_setup run produces for one tool: the skills
  // install (BE-9605c dropped the separate agent-template download signal).
  function fireInstalled(toolName) {
    mockWsOn.mock.calls.find((call) => call[0] === 'setup:commands_installed')[1]({
      tool_name: toolName,
    })
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  // -------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------
  describe('Rendering', () => {
    it('renders heading text', async () => {
      const wrapper = mountStep3()
      await flushPromises()
      // BE-9605c retired the agent-template install path; the heading now
      // covers skills only.
      expect(wrapper.text()).toContain('Install skills')
    })

    it('renders giljo_setup command', async () => {
      const wrapper = mountStep3()
      await flushPromises()
      expect(wrapper.text()).toContain('giljo_setup')
    })

    it('renders instruction text with tool name (harmonized registry name)', async () => {
      const wrapper = mountStep3()
      await flushPromises()
      // TOOL_META now comes from the shared setupTools.js registry (FE-9204), so
      // the display name harmonizes to "Claude Code" (was "Claude Code CLI").
      expect(wrapper.text()).toContain('Ask your Claude Code to run:')
    })

    it('does not show tab bar with single connected tool', async () => {
      const wrapper = mountStep3({ connectedTools: ['claude_code'] })
      await flushPromises()
      expect(wrapper.find('.tool-tabs').exists()).toBe(false)
    })

    it('shows tab bar with multiple connected tools', async () => {
      const wrapper = mountStep3({
        connectedTools: ['claude_code', 'codex_cli'],
      })
      await flushPromises()
      expect(wrapper.find('.tool-tabs').exists()).toBe(true)
      expect(wrapper.findAll('.tool-tab')).toHaveLength(2)
    })

    // FE-9204: the Install step must resolve the two tools added to the choose grid
    // (OpenCode has an mdi icon, Generic MCP client a logo) — it kept a stale 4-tool
    // TOOL_META fork that rendered a broken image + empty name for them.
    it('renders OpenCode (mdi icon, no broken image) when connected', async () => {
      const wrapper = mountStep3({ connectedTools: ['opencode'] })
      await flushPromises()
      expect(wrapper.text()).toContain('Ask your OpenCode to run:')
    })

    it('renders the generic MCP client with a resolvable name + logo when connected', async () => {
      const wrapper = mountStep3({
        connectedTools: ['claude_code', 'generic'],
      })
      await flushPromises()
      const tabs = wrapper.findAll('.tool-tab')
      expect(tabs).toHaveLength(2)
      // The generic tab renders its name (not empty) and a logo image (not broken).
      expect(tabs[1].text()).toContain('Generic MCP client')
      expect(tabs[1].find('img').attributes('src')).toBe('/logo-mcp.svg')
    })
  })

  // -------------------------------------------------------------------
  // Mini-checklist
  // -------------------------------------------------------------------
  describe('Mini-checklist', () => {
    it('starts with checklist unchecked', async () => {
      const wrapper = mountStep3()
      await flushPromises()
      const items = wrapper.findAll('.checklist-item')
      expect(items).toHaveLength(1)
      expect(wrapper.findAll('.checklist-text--done')).toHaveLength(0)
    })

    it('flips checkmark on setup:bootstrap_complete WebSocket event', async () => {
      const wrapper = mountStep3()
      await flushPromises()

      const onCall = mockWsOn.mock.calls.find(
        (call) => call[0] === 'setup:bootstrap_complete',
      )
      expect(onCall).toBeTruthy()

      onCall[1]({})
      await flushPromises()

      expect(wrapper.findAll('.checklist-text--done')).toHaveLength(1)
    })
  })

  // -------------------------------------------------------------------
  // can-proceed logic
  // -------------------------------------------------------------------
  describe('can-proceed', () => {
    it('emits can-proceed false initially', async () => {
      const wrapper = mountStep3()
      await flushPromises()

      const events = wrapper.emitted('can-proceed')
      expect(events).toBeTruthy()
      expect(events[0]).toEqual([false])
    })

    it('emits can-proceed true once the skills land for at least 1 tool', async () => {
      const wrapper = mountStep3()
      await flushPromises()

      fireInstalled('claude_code')
      await flushPromises()

      const events = wrapper.emitted('can-proceed')
      const lastEmit = events[events.length - 1]
      expect(lastEmit).toEqual([true])
    })

    it('does not emit can-proceed true with no commands installed', async () => {
      const wrapper = mountStep3()
      await flushPromises()

      const events = wrapper.emitted('can-proceed')
      const lastEmit = events[events.length - 1]
      expect(lastEmit).toEqual([false])
    })

    it('emits can-proceed true via bootstrap_complete event', async () => {
      const wrapper = mountStep3()
      await flushPromises()

      const bootstrapCall = mockWsOn.mock.calls.find(
        (call) => call[0] === 'setup:bootstrap_complete',
      )
      bootstrapCall[1]({})
      await flushPromises()

      const events = wrapper.emitted('can-proceed')
      const lastEmit = events[events.length - 1]
      expect(lastEmit).toEqual([true])
    })
  })

  // -------------------------------------------------------------------
  // step-data emit
  // -------------------------------------------------------------------
  describe('step-data', () => {
    it('emits step-data with installed tools after commands installed', async () => {
      const wrapper = mountStep3()
      await flushPromises()

      fireInstalled('claude_code')
      await flushPromises()

      const events = wrapper.emitted('step-data')
      expect(events).toBeTruthy()
      const lastEmit = events[events.length - 1][0]
      expect(lastEmit.installedTools).toContain('claude_code')
    })
  })

  // -------------------------------------------------------------------
  // No pre-fill (FE-9497). The step used to take a previouslyCompleted prop
  // and tick both boxes for anyone who had finished setup before, which let a
  // repeat user past Next without installing anything. A past run tells us
  // nothing about the current machine, so only observed events tick a box.
  // -------------------------------------------------------------------
  describe('No pre-fill from a previous run', () => {
    it('ignores a legacy previouslyCompleted prop and stays unticked', async () => {
      const wrapper = mountStep3({ previouslyCompleted: true })
      await flushPromises()

      expect(wrapper.findAll('.checklist-text--done')).toHaveLength(0)
    })

    it('keeps can-proceed false for a repeat user until something installs', async () => {
      const wrapper = mountStep3({ previouslyCompleted: true })
      await flushPromises()

      const events = wrapper.emitted('can-proceed')
      expect(events).toBeTruthy()
      const lastEmit = events[events.length - 1]
      expect(lastEmit).toEqual([false])
    })
  })

  // -------------------------------------------------------------------
  // FE-9569 detector 2. `toolStatus` used to be built ONCE at component setup
  // from the initial `connectedTools` prop (Object.fromEntries(...)) and never
  // re-keyed. Detector 1 (the connect step's credential-status seeding) is
  // async, so a connectedTools prop that starts empty and populates a beat
  // later (or any other timing where this step mounts before the parent's
  // connectedTools settles) left toolStatus permanently `{}` — every
  // WS-driven tick handler guards on `if (toolStatus[id])`, which is false
  // forever for a key that was never added, and the checklist looks
  // permanently stuck even though a real setup:bootstrap_complete arrives.
  // Confirmed at runtime (FE-9569 thread): setup:bootstrap_complete ALREADY
  // fires unconditionally on every giljo_setup call (see
  // api/endpoints/mcp_tools/_setup_tools.py:198-214) — re-running installs
  // that were already present still ticks both boxes once toolStatus has the
  // key. This is the one thing that needed a genuine fix on this component.
  // -------------------------------------------------------------------
  describe('Recovers when connectedTools populates AFTER mount (FE-9569 detector 2 cascade)', () => {
    it('mounting with an empty connectedTools then receiving the real list still ticks on bootstrap_complete', async () => {
      const wrapper = mountStep3({ connectedTools: [] })
      await flushPromises()

      await wrapper.setProps({ connectedTools: ['claude_code'] })
      await flushPromises()

      const bootstrapCall = mockWsOn.mock.calls.find((call) => call[0] === 'setup:bootstrap_complete')
      bootstrapCall[1]({})
      await flushPromises()

      expect(wrapper.findAll('.checklist-text--done')).toHaveLength(1)
      const events = wrapper.emitted('can-proceed')
      expect(events[events.length - 1]).toEqual([true])
    })

    it('re-keys the active tool too, so the panel is not stuck showing the wrong/empty tool', async () => {
      const wrapper = mountStep3({ connectedTools: [] })
      await flushPromises()

      await wrapper.setProps({ connectedTools: ['codex_cli'] })
      await flushPromises()

      const bootstrapCall = mockWsOn.mock.calls.find((call) => call[0] === 'setup:bootstrap_complete')
      bootstrapCall[1]({})
      await flushPromises()

      expect(wrapper.text()).toContain('Ask your Codex CLI to run:')
      expect(wrapper.findAll('.checklist-text--done')).toHaveLength(1)
    })

    it('a later-arriving second tool gets its own key too (no stomping the first)', async () => {
      const wrapper = mountStep3({ connectedTools: ['claude_code'] })
      await flushPromises()
      const bootstrapCall = mockWsOn.mock.calls.find((call) => call[0] === 'setup:bootstrap_complete')
      bootstrapCall[1]({})
      await flushPromises()
      expect(wrapper.findAll('.checklist-text--done')).toHaveLength(1)

      // A second tool connects later (multi-tool walk) -- its own status must
      // start fresh, not reuse or clobber the first tool's completed state.
      await wrapper.setProps({ connectedTools: ['claude_code', 'codex_cli'] })
      await flushPromises()
      await wrapper.find('.tool-tab:last-child').trigger('click')
      await flushPromises()
      expect(wrapper.findAll('.checklist-text--done')).toHaveLength(0)
    })
  })

  // -------------------------------------------------------------------
  // Skip control — moved to the shared wizard footer (FE-6259b: the
  // Gradient Rail redesign centralizes the step-1/step-2 skip control in
  // SetupWizardOverlay's footer instead of each step owning its own
  // skip link — see SetupWizardOverlay.vue footerSkipLabel/handleFooterSkip
  // and the passing coverage in
  // src/components/setup/__tests__/SetupWizardOverlay.spec.js). This
  // component no longer renders a skip link or emits 'skip' on its own;
  // verify that delegation held and that the remaining escape hatch at
  // this level (the manual-setup pointer) still renders.
  // -------------------------------------------------------------------
  describe('Skip control (delegated to wizard footer, FE-6259b)', () => {
    it('does not render its own skip link (control now lives in the wizard footer)', async () => {
      const wrapper = mountStep3()
      await flushPromises()
      expect(wrapper.find('.skip-link').exists()).toBe(false)
    })

    it('does not emit a "skip" event on its own — SetupWizardOverlay owns skip now', async () => {
      const wrapper = mountStep3()
      await flushPromises()
      expect(wrapper.emitted('skip')).toBeUndefined()
    })

    it('still points users to manual setup as a fallback', async () => {
      const wrapper = mountStep3()
      await flushPromises()
      expect(wrapper.text()).toContain('For manual setup, go to')
      expect(wrapper.text()).toContain('Tools')
      expect(wrapper.text()).toContain('Connect')
    })
  })

  // -------------------------------------------------------------------
  // Tab switching (multi-tool)
  // -------------------------------------------------------------------
  describe('Tab switching', () => {
    it('switches active tool on tab click', async () => {
      const wrapper = mountStep3({
        connectedTools: ['claude_code', 'codex_cli'],
      })
      await flushPromises()

      const tabs = wrapper.findAll('.tool-tab')
      expect(tabs).toHaveLength(2)

      await tabs[1].trigger('click')
      await flushPromises()

      expect(tabs[1].classes()).toContain('tool-tab--active')
    })

    it('emits can-proceed when one tool is fully installed in multi-tool setup', async () => {
      const wrapper = mountStep3({
        connectedTools: ['claude_code', 'codex_cli'],
      })
      await flushPromises()

      fireInstalled('claude_code')
      await flushPromises()

      const events = wrapper.emitted('can-proceed')
      const lastEmit = events[events.length - 1]
      expect(lastEmit).toEqual([true])
    })
  })

  // -------------------------------------------------------------------
  // WebSocket cleanup
  // -------------------------------------------------------------------
  describe('Cleanup', () => {
    it('subscribes to WebSocket events on mount', async () => {
      mountStep3()
      await flushPromises()

      const eventTypes = mockWsOn.mock.calls.map((c) => c[0])
      expect(eventTypes).toContain('setup:commands_installed')
      expect(eventTypes).toContain('setup:bootstrap_complete')
    })

    it('unsubscribes from WebSocket events on unmount', async () => {
      const wrapper = mountStep3()
      await flushPromises()

      wrapper.unmount()
      expect(mockUnsub).toHaveBeenCalledTimes(2)
    })
  })
})
