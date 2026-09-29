import { describe, it, expect } from 'vitest'
import { groupBoardByProduct, OTHER_PRODUCT_ID, OTHER_PRODUCT_NAME } from './jobsBoardProductGroups'

const productsById = {
  'prod-a': { id: 'prod-a', name: 'Alpha' },
  'prod-b': { id: 'prod-b', name: 'Beta' },
}
const pA1 = { id: 'a1', product_id: 'prod-a', updated_at: '2026-09-26T10:00:00Z' }
const pA2 = { id: 'a2', product_id: 'prod-a', updated_at: '2026-09-26T08:00:00Z' }
const pB1 = { id: 'b1', product_id: 'prod-b', updated_at: '2026-09-26T12:00:00Z' }
const pX1 = { id: 'x1', product_id: 'prod-gone', updated_at: '2026-09-25T00:00:00Z' }
const runB = { id: 'run-b', status: 'running', project_ids: ['b2'], resolved_order: ['b2'] }
const pB2 = { id: 'b2', product_id: 'prod-b', updated_at: '2026-09-26T11:00:00Z' }

const sideOf = (p) => (p.id === 'a2' ? 'staging' : 'implementation')
const sideOfRun = (run) => (run.status === 'running' ? 'implementation' : 'staging')
const membersOf = (run) => run.resolved_order

function group(side, overrides = {}) {
  return groupBoardByProduct({
    projects: [pA1, pA2, pB1, pX1],
    chainMembers: [pB2],
    runs: [runB],
    membersOf,
    productsById,
    sideOf,
    sideOfRun,
    side,
    ...overrides,
  })
}

describe('groupBoardByProduct', () => {
  it('makes one group per product, most recent activity first, named from the product list', () => {
    const groups = group('implementation')
    expect(groups.map((g) => g.id)).toEqual(['prod-b', 'prod-a', OTHER_PRODUCT_ID])
    expect(groups.map((g) => g.name)).toEqual(['Beta', 'Alpha', OTHER_PRODUCT_NAME])
  })

  it('puts only this side\'s loose projects and runs inside the group, and counts both sides', () => {
    const [beta, alpha] = group('implementation')
    expect(beta.projects.map((p) => p.id)).toEqual(['b1'])
    expect(beta.runIds).toEqual(['run-b'])
    expect(beta.counts).toEqual({ staging: 0, implementation: 2 })
    expect(alpha.projects.map((p) => p.id)).toEqual(['a1'])
    expect(alpha.runIds).toEqual([])
    expect(alpha.counts).toEqual({ staging: 1, implementation: 1 })
  })

  it('a product with cards on the other side only is a quiet group, never an empty grid', () => {
    const groups = group('staging')
    const beta = groups.find((g) => g.id === 'prod-b')
    expect(beta.projects).toEqual([])
    expect(beta.runIds).toEqual([])
    expect(beta.quiet).toBe(true)
    const alpha = groups.find((g) => g.id === 'prod-a')
    expect(alpha.projects.map((p) => p.id)).toEqual(['a2'])
    expect(alpha.quiet).toBe(false)
  })

  it('a chain member never appears twice: it is inside its run, not a loose card', () => {
    const beta = group('implementation').find((g) => g.id === 'prod-b')
    expect(beta.projects.map((p) => p.id)).not.toContain('b2')
  })

  it('a run whose members carry no known product lands in the Other group', () => {
    const orphanRun = { id: 'run-x', status: 'pending', project_ids: ['nope'], resolved_order: ['nope'] }
    const groups = group('staging', { runs: [runB, orphanRun] })
    const other = groups.find((g) => g.name === OTHER_PRODUCT_NAME)
    expect(other.runIds).toEqual(['run-x'])
  })

  it('is empty when nothing is in flight anywhere', () => {
    expect(groupBoardByProduct({ projects: [], chainMembers: [], runs: [], membersOf, productsById, sideOf, sideOfRun, side: 'staging' })).toEqual([])
  })
})
