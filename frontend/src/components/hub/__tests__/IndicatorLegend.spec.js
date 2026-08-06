/**
 * IndicatorLegend.spec.js — FE-9365e
 *
 * The legend's whole value is that it agrees with the screen. A hand-copied hex table
 * starts correct and drifts silently: the dot changes, the legend keeps explaining the
 * old colour, and the operator is now worse off than with no legend at all.
 *
 * So these tests pin DERIVATION, not content. They fail if someone inlines the colours,
 * and they fail if a status the dot can render stops being explained.
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import { createVuetify } from 'vuetify'
import IndicatorLegend from '@/components/hub/IndicatorLegend.vue'
import { agentStatusDot } from '@/composables/useAgentStatusDot'

const vuetify = createVuetify()
const mountLegend = () => mount(IndicatorLegend, { global: { plugins: [vuetify] } })

describe('IndicatorLegend', () => {
  it('explains every status the dot can actually render', () => {
    // The reachable set, from the composable rather than from a list kept in step with
    // it by hand. Adding a status to the dot without documenting it fails here.
    const reachable = [
      'waiting',
      'working',
      'blocked',
      'awaiting_user',
      'complete',
      'idle',
      'sleeping',
      'handed_over',
      'closed',
      'decommissioned',
    ]
    const text = mountLegend().text()

    for (const status of reachable) {
      const { label } = agentStatusDot({ status, last_seen_at: 'seen' })
      expect(text, `no legend row explains "${status}" (${label})`).toContain(label)
    }
  })

  it('explains the never-registered hollow ring, which is not a status', () => {
    // Easy to forget precisely because it has no status value — it is the ABSENCE of
    // one, and it is the state most likely to confuse someone who just shared an id.
    const text = mountLegend().text()
    expect(text).toContain(agentStatusDot({ status: null, last_seen_at: null }).label)
  })

  it('derives its swatches from the composable instead of inlining hexes', () => {
    // The guard that keeps the two from drifting. Every swatch colour rendered must be
    // one the composable produces — and the source must not carry a hex table.
    const wrapper = mountLegend()
    const rendered = wrapper.findAll('[data-testid="legend-status-row"]')
    expect(rendered.length).toBeGreaterThanOrEqual(11)

    const src = readFileSync(resolve(__dirname, '../IndicatorLegend.vue'), 'utf8')
    const script = src.slice(src.indexOf('<script'), src.indexOf('</script>'))
    expect(script, 'a hex literal in the script means the legend can drift from the dot').not.toMatch(/#[0-9a-fA-F]{6}/)
    expect(script).toContain('agentStatusDot')
  })

  it('says out loud that open is never rendered', () => {
    // The prototype gives `open` its own chip row precisely so its absence on cards
    // reads as a decision rather than a bug.
    const text = mountLegend().text()
    expect(text).toContain('open')
    expect(text).toMatch(/never rendered/i)
  })

  it('closes from its own ✕ — the panel floats, so it must be dismissible in place', async () => {
    const wrapper = mountLegend()
    await wrapper.get('[data-testid="legend-close"]').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('states both honesty rules, because they are promises not features', () => {
    const text = mountLegend().text()
    expect(text).toContain('verbatim')
    expect(text).toMatch(/baton pointing at you/i)
  })
})
