/**
 * AgentTipsDialog — INF-9605a
 *
 * The dialog's "AI coding agent" chip group offers spawn tips for the CLIs that
 * still have a per-CLI spawn command (Claude Code CLI, Codex); the retired
 * Gemini/Antigravity chips and their agy/gemini commands are gone.
 * Edition scope: Both
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import AgentTipsDialog from '@/components/common/AgentTipsDialog.vue'

describe('AgentTipsDialog — tool chips after the preset retirement (INF-9605a)', () => {
  let vuetify

  beforeEach(() => {
    vuetify = createVuetify({ components, directives })
  })

  const passthrough = (cls) => ({ template: `<div class="${cls}"><slot /></div>` })

  const createWrapper = () =>
    mount(AgentTipsDialog, {
      global: {
        plugins: [vuetify],
        directives: { draggable: {} },
        stubs: {
          'v-dialog': passthrough('v-dialog'),
          'v-tooltip': passthrough('v-tooltip'),
          'v-expansion-panels': passthrough('v-expansion-panels'),
          'v-expansion-panel': passthrough('v-expansion-panel'),
          'v-expansion-panel-title': passthrough('v-expansion-panel-title'),
          'v-expansion-panel-text': passthrough('v-expansion-panel-text'),
        },
      },
    })

  it('renders and offers exactly the Claude Code CLI and Codex spawn chips', () => {
    const wrapper = createWrapper()
    const chipLabels = wrapper.findAll('.tool-selector .v-chip').map((c) => c.text().trim())
    expect(chipLabels).toEqual(['Claude Code CLI', 'Codex'])
  })

  it('shows the claude spawn command by default and the codex one when Codex is selected', async () => {
    const wrapper = createWrapper()
    expect(wrapper.text()).toContain('cmd /k claude')
    expect(wrapper.text()).not.toContain('cmd /k codex')

    wrapper.vm.selectedTool = 'codex'
    await nextTick()
    expect(wrapper.text()).toContain('cmd /k codex')
    expect(wrapper.text()).not.toContain('cmd /k claude')
  })

  it('never mentions the retired presets or their launchers', () => {
    const text = createWrapper().text()
    expect(text).not.toMatch(/gemini|antigravity|cmd \/k agy/i)
  })
})
