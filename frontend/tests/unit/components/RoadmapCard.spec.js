/**
 * RoadmapCard.vue — FE-6022b, updated FE-9568 (2026-09-02, operator ruling)
 *
 * Covers the load-bearing, type-dependent behavior + the design-system /
 * accessibility contract:
 *   - Convert renders for a TASK; a PROJECT renders NO primary action at all
 *     (Activate/Deactivate were REMOVED by FE-9568 — /roadmap is
 *     ordering-only now, see RoadmapCard.spec.js in src/components for the
 *     dedicated removal-coverage file).
 *   - Convert emits the right intent; the .rm-grip drag handle exists (drag
 *     itself is owned by vuedraggable in RoadmapView).
 *   - taxonomy_alias chip hides when the alias is empty.
 *   - meta badges use the tinted-badge anatomy (rgba 0.15 tint; radius owned
 *     by the .rm-badge class, not an inline style).
 *   - WCAG AA: every new badge text color clears 4.5:1 on the #12202e panel bg.
 *
 * Edition Scope: CE
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import RoadmapCard from '@/components/RoadmapCard.vue'

// ── WCAG luminance helpers (per StatusBadge.spec convention) ──────────────────
function hexToRgb(hex) {
  const c = hex.replace('#', '')
  return {
    r: parseInt(c.slice(0, 2), 16) / 255,
    g: parseInt(c.slice(2, 4), 16) / 255,
    b: parseInt(c.slice(4, 6), 16) / 255,
  }
}
function relativeLuminance({ r, g, b }) {
  const ch = (v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4))
  return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)
}
function contrastRatio(a, b) {
  const La = relativeLuminance(hexToRgb(a))
  const Lb = relativeLuminance(hexToRgb(b))
  return (Math.max(La, Lb) + 0.05) / (Math.min(La, Lb) + 0.05)
}

// ── stubs ─────────────────────────────────────────────────────────────────────
// Tooltip stub renders the activator slot (so the badge/button exists) and
// exposes the tooltip `text` as data-text so the copy can be asserted.
const stubs = {
  'v-btn': {
    template: '<button class="v-btn" v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
  },
  'v-icon': { template: '<i class="v-icon"><slot /></i>' },
  'v-tooltip': {
    props: ['text'],
    template: '<div class="v-tooltip" :data-text="text"><slot name="activator" :props="{}" /></div>',
  },
}

const PROJECT_ITEM = {
  id: 'rmi-1',
  item_type: 'project',
  project_id: 'p-1',
  task_id: null,
  title: 'Core database schema',
  taxonomy_alias: 'BE-0001',
  status: 'inactive',
  priority: 0,
  risk: 'low',
  complexity: 'heavy',
}
const TASK_ITEM = {
  id: 'rmi-2',
  item_type: 'task',
  project_id: null,
  task_id: 't-1',
  title: 'Fix login redirect loop',
  taxonomy_alias: 'TASK-0027',
  status: 'pending',
  priority: 1,
  risk: 'high',
  complexity: 'light',
}

// FE-6022c terminal-state fixtures
const COMPLETED_PROJECT = { ...PROJECT_ITEM, status: 'completed' }
const ACTIVE_PROJECT = { ...PROJECT_ITEM, status: 'active' }
const DELETED_PROJECT = { ...PROJECT_ITEM, status: 'deleted' }
const CANCELLED_PROJECT = { ...PROJECT_ITEM, status: 'cancelled' }
const COMPLETED_TASK = { ...TASK_ITEM, status: 'completed' }

function mountCard(item, rank = 1) {
  return mount(RoadmapCard, { props: { item, rank }, global: { stubs } })
}

describe('RoadmapCard.vue — type-dependent action rail (FE-9568: Activate/Deactivate REMOVED)', () => {
  it('renders Convert to Project for a TASK', () => {
    const w = mountCard(TASK_ITEM)
    expect(w.text()).toContain('Convert to Project')
  })

  it('renders no primary action at all for an inactive, non-chain PROJECT', () => {
    const w = mountCard(PROJECT_ITEM)
    expect(w.text()).not.toContain('Activate')
    expect(w.text()).not.toContain('Convert to Project')
    expect(w.find('.rm-primary-btn').exists()).toBe(false)
  })

  it('primary button emits "convert" with the item for a TASK', async () => {
    const w = mountCard(TASK_ITEM)
    await w.find('.rm-primary-btn').trigger('click')
    expect(w.emitted('convert')).toBeTruthy()
    expect(w.emitted('convert')[0][0]).toEqual(TASK_ITEM)
  })

  it('renders no Deactivate/Activate button for an ACTIVATED project — only the ACTIVATED status badge', () => {
    const w = mountCard(ACTIVE_PROJECT)
    expect(w.text()).not.toContain('Deactivate')
    expect(w.text()).not.toContain('Activate')
    expect(w.find('.rm-primary-btn').exists()).toBe(false)
    expect(w.text()).toContain('ACTIVATED') // the passive status badge stays
  })

  it('exposes the .rm-grip drag handle (drag is owned by vuedraggable)', () => {
    // vuedraggable/SortableJS scopes the drag to this handle via handle:'.rm-grip'
    // in RoadmapView, so the card no longer emits native drag events itself.
    const w = mountCard(PROJECT_ITEM)
    expect(w.find('.rm-grip').exists()).toBe(true)
  })
})

describe('RoadmapCard.vue — terminal-state badges + lock (FE-6022c)', () => {
  it('inactive project / pending task are NOT terminal (no status badge)', () => {
    expect(mountCard(PROJECT_ITEM).vm.isTerminal).toBe(false)
    expect(mountCard(PROJECT_ITEM).vm.statusBadge).toBeNull()
    expect(mountCard(TASK_ITEM).vm.isTerminal).toBe(false)
  })

  it('badges an activated project ACTIVATED and marks it terminal', () => {
    const w = mountCard(ACTIVE_PROJECT)
    expect(w.vm.isTerminal).toBe(true)
    expect(w.vm.statusBadge.label).toBe('ACTIVATED')
    expect(w.text()).toContain('ACTIVATED')
  })

  it('badges a completed project COMPLETED', () => {
    expect(mountCard(COMPLETED_PROJECT).vm.statusBadge.label).toBe('COMPLETED')
  })

  it('badges a cancelled project CANCELLED', () => {
    expect(mountCard(CANCELLED_PROJECT).vm.statusBadge.label).toBe('CANCELLED')
  })

  it('badges a soft-deleted project DELETED', () => {
    expect(mountCard(DELETED_PROJECT).vm.statusBadge.label).toBe('DELETED')
  })

  it('badges a completed task COMPLETED and marks it terminal', () => {
    const w = mountCard(COMPLETED_TASK)
    expect(w.vm.isTerminal).toBe(true)
    expect(w.vm.statusBadge.label).toBe('COMPLETED')
  })

  it('replaces the drag grip with a non-draggable locked handle on terminal items', () => {
    const w = mountCard(COMPLETED_PROJECT)
    expect(w.find('.rm-grip').exists()).toBe(false) // SortableJS handle gone -> not reorderable
    expect(w.find('.rm-grip-locked').exists()).toBe(true)
  })

  it('keeps the draggable .rm-grip on a non-terminal item', () => {
    const w = mountCard(PROJECT_ITEM)
    expect(w.find('.rm-grip').exists()).toBe(true)
    expect(w.find('.rm-grip-locked').exists()).toBe(false)
  })

  it('renders no primary action for a terminal project (Activate/Deactivate were removed, FE-9568)', () => {
    const w = mountCard(COMPLETED_PROJECT)
    expect(w.find('.rm-primary-btn').exists()).toBe(false)
  })

  it('disables Convert on a terminal task', () => {
    const w = mountCard(COMPLETED_TASK)
    expect(w.find('.rm-primary-btn').attributes('disabled')).toBeDefined()
  })

  it('leaves the primary action (Convert) enabled on a non-terminal task', () => {
    const w = mountCard(TASK_ITEM)
    expect(w.find('.rm-primary-btn').attributes('disabled')).toBeUndefined()
  })
})

describe('RoadmapCard.vue — polish: badge tooltips, no 3-dot menu, (x) remove (FE-6022c-polish)', () => {
  function tooltipTexts(w) {
    return w.findAll('.v-tooltip').map((t) => t.attributes('data-text'))
  }

  it('renders a tooltip on the risk badge with the WO copy', () => {
    const texts = tooltipTexts(mountCard(PROJECT_ITEM))
    expect(texts).toContain('Chance this work causes problems or breaks things — low / med / high.')
  })

  it('renders a tooltip on the complexity badge with the WO copy', () => {
    const texts = tooltipTexts(mountCard(PROJECT_ITEM))
    expect(texts).toContain('Roughly how much effort to build — light / med / heavy.')
  })

  it('omits the risk/complexity tooltips when those badges are absent', () => {
    const texts = tooltipTexts(mountCard({ ...PROJECT_ITEM, risk: null, complexity: null }))
    expect(texts).not.toContain('Chance this work causes problems or breaks things — low / med / high.')
    expect(texts).not.toContain('Roughly how much effort to build — light / med / heavy.')
  })

  it('no longer renders the 3-dot "More" menu', () => {
    const w = mountCard(PROJECT_ITEM)
    expect(w.find('[aria-label="More actions"]').exists()).toBe(false)
    expect(w.html()).not.toContain('mdi-dots-vertical')
  })

  it('renders an (x) remove button that emits "remove" with the item', async () => {
    const w = mountCard(PROJECT_ITEM)
    const btn = w.find('.rm-remove-btn')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(w.emitted('remove')).toBeTruthy()
    expect(w.emitted('remove')[0][0]).toEqual(PROJECT_ITEM)
  })

  it('exposes the remove button via a "Remove from roadmap" tooltip', () => {
    expect(tooltipTexts(mountCard(PROJECT_ITEM))).toContain('Remove from roadmap')
  })
})

describe('RoadmapCard.vue — content', () => {
  it('shows the taxonomy alias chip when present', () => {
    const w = mountCard(PROJECT_ITEM)
    expect(w.find('.rm-alias').exists()).toBe(true)
    expect(w.find('.rm-alias').text()).toBe('BE-0001')
  })

  it('hides the alias chip when taxonomy_alias is empty', () => {
    const w = mountCard({ ...PROJECT_ITEM, taxonomy_alias: '' })
    expect(w.find('.rm-alias').exists()).toBe(false)
  })

  it('tints the alias chip with the per-taxonomy color (15% bg + full-color text)', () => {
    // jsdom normalizes the #6DB3E4 / #6DB3E426 hex to rgb()/rgba().
    const w = mountCard({ ...PROJECT_ITEM, taxonomy_color: '#6DB3E4' })
    const style = w.find('.rm-alias').attributes('style')
    expect(style).toContain('rgba(109, 179, 228, 0.15)') // 15% tinted background
    expect(style).toContain('rgb(109, 179, 228)') // full-color text
  })

  it('falls back to the default type color when taxonomy_color is absent', () => {
    const w = mountCard({ ...PROJECT_ITEM, taxonomy_color: null })
    const style = w.find('.rm-alias').attributes('style')
    expect(style).toContain('rgb(96, 125, 139)') // DEFAULT_PROJECT_TYPE_COLOR #607D8B
  })

  it('renders the display rank (1-based position, not raw priority)', () => {
    const w = mountCard({ ...PROJECT_ITEM, priority: 99 }, 3)
    expect(w.find('.rm-num').text()).toBe('3')
  })

  it('labels the type badge PROJECT / TASK', () => {
    expect(mountCard(PROJECT_ITEM).vm.typeLabel).toBe('PROJECT')
    expect(mountCard(TASK_ITEM).vm.typeLabel).toBe('TASK')
  })
})

describe('RoadmapCard.vue — blocked dependency row (FE-6022d)', () => {
  it('shows no blocked row when the item is not blocked', () => {
    expect(mountCard(PROJECT_ITEM).find('.rm-blocked-row').exists()).toBe(false)
    expect(mountCard({ ...PROJECT_ITEM, blocked: false }).find('.rm-blocked-row').exists()).toBe(false)
  })

  it('renders a red Blocked label + reason on its own row when blocked', () => {
    const w = mountCard({
      ...PROJECT_ITEM,
      blocked: true,
      blocked_reason: 'needs the auth gate from BE-6077 first',
    })
    expect(w.find('.rm-blocked-row').exists()).toBe(true)
    expect(w.find('.rm-blocked-label').text()).toBe('Blocked')
    expect(w.find('.rm-blocked-reason').text()).toBe('reason: needs the auth gate from BE-6077 first')
    // No icon in the blocked row — red text only, by design.
    expect(w.find('.rm-blocked-row').findAll('.v-icon').length).toBe(0)
  })

  it('renders the Blocked label even when no reason is supplied', () => {
    const w = mountCard({ ...PROJECT_ITEM, blocked: true, blocked_reason: null })
    expect(w.find('.rm-blocked-label').exists()).toBe(true)
    expect(w.find('.rm-blocked-reason').exists()).toBe(false)
  })
})

describe('RoadmapCard.vue — tinted-badge anatomy', () => {
  it('type badge uses an rgba(…, 0.15) tint from an inline style, with no inline radius', () => {
    const w = mountCard(PROJECT_ITEM)
    const badge = w.findAll('.rm-badge')[0]
    const style = badge.attributes('style')
    expect(style).toContain('rgba(')
    expect(style).toContain('0.15')
    expect(style).not.toContain('border-radius')
  })

  it('the .rm-badge class, not an inline style, owns the radius', async () => {
    const { readFileSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const src = readFileSync(resolve(__dirname, '../../../src/components/RoadmapCard.vue'), 'utf8')
    const rmBadgeBlock = src.match(/\.rm-badge\s*\{([^}]*)\}/)?.[1] || ''
    expect(rmBadgeBlock).toMatch(/border-radius:\s*\$border-radius-default/)
  })

  it('renders risk + complexity badges when set, omits them when null', () => {
    const full = mountCard(PROJECT_ITEM)
    // PROJECT + risk:low + complexity:heavy -> 3 badges
    expect(full.findAll('.rm-badge').length).toBe(3)

    const bare = mountCard({ ...PROJECT_ITEM, risk: null, complexity: null })
    // type badge only
    expect(bare.findAll('.rm-badge').length).toBe(1)
  })
})

describe('RoadmapCard.vue — WCAG AA on new color usage', () => {
  // Every badge foreground color must clear 4.5:1 on the #12202e panel bg
  // (a 0.15-alpha tint blends almost entirely into the page background).
  const NEW_COLORS = {
    'project yellow': '#ffc300',
    'task blue': '#6db3e4',
    'risk low (success)': '#67bd6d',
    'risk med (tester amber)': '#edba4a',
    'risk high (analyzer red)': '#e07872',
    'complexity muted': '#8895a8',
  }
  Object.entries(NEW_COLORS).forEach(([name, hex]) => {
    it(`${name} (${hex}) clears 4.5:1 on #12202e`, () => {
      expect(contrastRatio(hex, '#12202e')).toBeGreaterThanOrEqual(4.5)
    })
  })
})
