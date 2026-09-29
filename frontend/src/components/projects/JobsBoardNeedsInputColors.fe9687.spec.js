import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import JobsBoardCard from './JobsBoardCard.vue'
import { needsInputColor } from '@/utils/jobsBoardLifecycle'
import { getStatusColor } from '@/utils/statusConfig'

const ORANGE = '#ff9800'
const BLUE = '#2196f3'
const MAGENTA = '#e060b0'
const RED = '#f44336'
const GREY = '#999'

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

function rgb(hex) {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const n = parseInt(full, 16)
  return `rgb(${n >> 16}, ${(n >> 8) & 255}, ${n & 255})`
}

const project = { id: 'p', taxonomy_alias: 'INF-1', name: 'x', status: 'active', implementation_launched_at: '2026-09-26T13:00:00Z' }
const orch = (extra = {}) => ({ agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'working', ...extra })
const impl = (extra = {}) => ({ agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'working', ...extra })

const CASES = [
  { kind: 'decision', color: ORANGE, agents: [orch({ status: 'awaiting_user' }), impl()] },
  { kind: 'unread', color: BLUE, agents: [orch({ action_required_unread: 1 }), impl()] },
  { kind: 'silent', color: MAGENTA, agents: [orch(), impl({ status: 'silent' })] },
  { kind: 'blocked', color: RED, agents: [orch(), impl({ status: 'blocked', block_reason: 'Needs a key' })] },
]

function mountCard(agents) {
  return mount(JobsBoardCard, {
    props: { project, agents, now: Date.parse('2026-09-26T14:00:00Z') },
    global: { plugins: [vuetify, router], stubs: { 'v-tooltip': tooltipStub } },
  })
}

describe('needsInputColor (FE-9687)', () => {
  it.each(CASES)('$kind is $color', ({ kind, color }) => {
    expect(needsInputColor(kind).toLowerCase()).toBe(color)
  })

  it('agent status words follow: blocked is red, silent is magenta', () => {
    expect(getStatusColor('blocked').toLowerCase()).toBe(RED)
    expect(getStatusColor('silent').toLowerCase()).toBe(MAGENTA)
  })
})

describe('Needs Input card colours (FE-9687)', () => {
  it.each(CASES)('a $kind card takes its reason colour on the edge; the lifecycle pill is grey', ({ kind, color, agents }) => {
    const wrapper = mountCard(agents)
    const card = wrapper.find('[data-testid="jobs-board-card"]')
    expect(card.attributes('style')).toContain(`--jb-edge: ${color}`)

    const lifecycle = wrapper.find('[data-testid="jb-lifecycle-pill"]')
    expect(lifecycle.text()).toBe('Needs Input')
    expect(lifecycle.element.style.color).toBe(rgb(GREY))

    const reason = wrapper.find('[data-testid="jb-status-pill"]')
    if (kind === 'decision') {
      expect(reason.classes()).toContain('jb-status-pill--decision')
    } else {
      expect(reason.element.style.color).toBe(rgb(color))
    }
  })
})

describe('Needs Input stylesheet colours (FE-9687)', () => {
  const read = (p) => readFileSync(resolve(__dirname, p), 'utf8')
  const tokens = read('../../styles/design-tokens.scss')
  const main = read('../../styles/main.scss')
  const agentRow = read('./JobsBoardAgentRow.vue')
  const card = read('./JobsBoardCard.vue')

  it('the blocked token is red, and silent and unread have their own tokens', () => {
    expect(tokens).toMatch(/\$color-status-blocked:\s*#f44336/i)
    expect(tokens).toMatch(/\$color-status-silent:\s*#e060b0/i)
    expect(tokens).toMatch(/\$color-status-unread:\s*#2196f3/i)
  })

  it('an agent with unread messages shows a blue count, not orange', () => {
    const hasMsgs = main.match(/&\.has-msgs\s*\{([^}]*)\}/)
    expect(hasMsgs[1]).toMatch(/\$color-status-unread/)
    expect(hasMsgs[1]).not.toMatch(/\$color-status-blocked/)
  })

  it('"Not picked up" is a stall, so it reads in the silent magenta', () => {
    const rule = agentRow.match(/\.jb-state--not-picked-up\s*\{([^}]*)\}/)
    expect(rule[1]).toMatch(/\$color-status-silent/)
  })

  it("a folded card's attention outline follows the card's own edge colour", () => {
    const rule = card.match(/\.jb-card--attn\s*\{([^}]*)\}/)
    expect(rule[1]).not.toMatch(/\$color-status-blocked/)
    expect(rule[1]).toMatch(/var\(--jb-edge/)
  })
})
