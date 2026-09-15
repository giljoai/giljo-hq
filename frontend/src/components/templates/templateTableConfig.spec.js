
import { describe, it, expect } from 'vitest'
import {
  templateUpdatedState,
  sortUpdatedState,
  templateRowActive,
  sortRowActive,
  templateOwningProductName,
  sortByProductName,
  templateTableHeaders,
  TEMPLATE_TABLE_HEADERS,
  TEMPLATE_TABLE_DEFAULT_SORT,
} from './templateTableConfig'

const HOUR = 60 * 60 * 1000
const NOW = new Date('2026-08-11T14:00:00Z')

const EARLIER_TODAY = new Date(NOW.getTime() - HOUR).toISOString()
const YESTERDAY = new Date(NOW.getTime() - 30 * HOUR).toISOString()

describe('templateUpdatedState — the three states', () => {
  it('reports the real date once the agent has actually been edited', () => {
    const state = templateUpdatedState(
      { updated_at: '2026-08-05T10:00:00Z', created_at: '2026-08-01T10:00:00Z' },
      { now: NOW },
    )

    expect(state.kind).toBe('edited')
    expect(state.label).toBeNull()
    expect(state.exact).toBe('2026-08-05T10:00:00Z')
  })

  it('reports "Never edited" when updated_at is NULL', () => {
    const state = templateUpdatedState(
      { updated_at: null, created_at: '2026-07-01T10:00:00Z' },
      { now: NOW },
    )

    expect(state.kind).toBe('never-edited')
    expect(state.label).toBe('Never edited')
    expect(state.exact).toBe('2026-07-01T10:00:00Z')
  })

  it('reports "Added today" for an agent created today and never edited', () => {
    const state = templateUpdatedState(
      { updated_at: null, created_at: EARLIER_TODAY },
      { now: NOW },
    )

    expect(state.kind).toBe('added-today')
    expect(state.label).toBe('Added today')
  })

  it('does NOT say "Added today" for an agent created before today', () => {
    const state = templateUpdatedState(
      { updated_at: null, created_at: YESTERDAY },
      { now: NOW },
    )

    expect(state.kind).toBe('never-edited')
  })

  it('prefers "edited" over "Added today" for an agent created AND edited today', () => {
    const state = templateUpdatedState(
      { updated_at: EARLIER_TODAY, created_at: EARLIER_TODAY },
      { now: NOW },
    )

    expect(state.kind).toBe('edited')
  })

  it('renders system-managed rows as a dash, unchanged', () => {
    expect(templateUpdatedState({ _system: true }, { now: NOW }).label).toBe('—')
  })

  it('does not treat an unparseable created_at as today', () => {
    const state = templateUpdatedState(
      { updated_at: null, created_at: 'not-a-date' },
      { now: NOW },
    )

    expect(state.kind).toBe('never-edited')
  })
})

describe('templateUpdatedState — FE-9386 regression: updated_at must mean a real edit', () => {
  it('a duplicated agent must not mark the ORIGINAL as edited', () => {
    const untouchedOriginal = { updated_at: null, created_at: '2026-07-01T10:00:00Z' }

    expect(templateUpdatedState(untouchedOriginal, { now: NOW }).kind).toBe('never-edited')

    const theCopy = { updated_at: null, created_at: EARLIER_TODAY }
    expect(templateUpdatedState(theCopy, { now: NOW }).kind).toBe(
      'added-today',
    )
  })
})

describe('sortUpdatedState — new agents rise without a special-case rule', () => {
  it('sorts on last activity, so a never-edited new agent outranks an old edit', () => {
    const newAgent = { updated_at: null, created_at: EARLIER_TODAY }
    const oldEdited = { updated_at: '2026-08-05T10:00:00Z', created_at: '2026-01-01T10:00:00Z' }

    expect(sortUpdatedState(newAgent, oldEdited)).toBeGreaterThan(0)
  })

  it('falls back to created_at on both sides rather than treating NULL as epoch-zero for one', () => {
    const older = { updated_at: null, created_at: '2026-01-01T10:00:00Z' }
    const newer = { updated_at: null, created_at: EARLIER_TODAY }

    expect(sortUpdatedState(older, newer)).toBeLessThan(0)
  })
})

describe('table configuration', () => {
  it('keeps the Updated column sortable by last activity and defaults to newest first', () => {
    const updated = TEMPLATE_TABLE_HEADERS.find((h) => h.key === 'updated_at')

    expect(updated.sortRaw).toBe(sortUpdatedState)
    expect(TEMPLATE_TABLE_DEFAULT_SORT).toEqual([{ key: 'updated_at', order: 'desc' }])
  })

  it('still exposes "Active here" as the per-product column', () => {
    const activeHere = TEMPLATE_TABLE_HEADERS.find((h) => h.key === 'is_active')

    expect(activeHere.title).toBe('Active here')
    expect(JSON.stringify(TEMPLATE_TABLE_HEADERS)).not.toMatch(/retire/i)
  })
})

describe('templateRowActive', () => {
  it('an agent with an active assignment is on', () => {
    expect(templateRowActive({ product_active: true })).toBe(true)
  })

  it('an agent with an inactive assignment is off', () => {
    expect(templateRowActive({ product_active: false })).toBe(false)
  })

  it('an agent with no assignment is off', () => {
    expect(templateRowActive({ is_active: true })).toBe(false)
    expect(templateRowActive({ is_active: false })).toBe(false)
  })

  it('an agent with an active assignment is on regardless of other row fields', () => {
    expect(templateRowActive({ is_active: false, product_active: true })).toBe(true)
  })

  it('the system orchestrator row is always on', () => {
    expect(templateRowActive({ _system: true })).toBe(true)
  })

  it('a missing or malformed row is off', () => {
    expect(templateRowActive(null)).toBe(false)
    expect(templateRowActive({})).toBe(false)
    expect(templateRowActive(undefined)).toBe(false)
  })
})

describe('sortRowActive — the status column orders by what the row SHOWS', () => {
  it('orders off-before-on using the displayed state', () => {
    const on = { id: 'on', product_active: true }
    const off = { id: 'off', product_active: false }

    expect([on, off].sort(sortRowActive).map((t) => t.id)).toEqual(['off', 'on'])
  })

  it('an agent with an active assignment sorts as on', () => {
    const retired = { id: 'retired', is_active: false, product_active: true }
    const off = { id: 'off', product_active: false }

    expect([off, retired].sort(sortRowActive).map((t) => t.id)).toEqual(['off', 'retired'])
  })

  it('is wired onto the "Active here" header', () => {
    const activeHere = TEMPLATE_TABLE_HEADERS.find((h) => h.key === 'is_active')

    expect(activeHere.sortRaw).toBe(sortRowActive)
  })
})

describe('the product column (show all products)', () => {
  const productsById = { 'p-1': { id: 'p-1', name: 'Atlas' }, 'p-2': { id: 'p-2', name: 'Beacon' } }

  it('names the owning product', () => {
    expect(templateOwningProductName({ product_id: 'p-2' }, productsById)).toBe('Beacon')
  })

  it('does not guess when the owner is unknown or absent', () => {
    expect(templateOwningProductName({ product_id: 'gone' }, productsById)).toBe('Unknown product')
    expect(templateOwningProductName({}, productsById)).toBe('Unknown product')
  })

  it('sorts by the NAME the chip shows, not the raw uuid', () => {
    const rows = [{ id: 'a', product_id: 'p-2' }, { id: 'b', product_id: 'p-1' }]

    expect(rows.sort(sortByProductName(productsById)).map((r) => r.id)).toEqual(['b', 'a'])
  })

  it('adds the product column only in show-all mode', () => {
    expect(templateTableHeaders().map((h) => h.key)).not.toContain('product_id')
    const shown = templateTableHeaders({ showAllProducts: true, productsById })
    expect(shown.map((h) => h.key)).toContain('product_id')
    expect(shown[1].key).toBe('product_id')
  })
})
