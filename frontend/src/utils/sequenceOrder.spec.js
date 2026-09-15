import { describe, it, expect } from 'vitest'
import {
  MAX_SEQUENCE_PROJECTS,
  SEQUENCE_EXECUTION_MODES,
  parseChainKey,
  computeChains,
  isChainLocked,
  orderByRoadmap,
  normalizeChainOrder,
} from '@/utils/sequenceOrder'

describe('sequenceOrder — constants', () => {
  it('caps a sequence at 5 projects', () => {
    expect(MAX_SEQUENCE_PROJECTS).toBe(5)
  })

  it('exposes multi_terminal as a valid execution mode (the default)', () => {
    expect(SEQUENCE_EXECUTION_MODES.map((m) => m.value)).toContain('multi_terminal')
  })
})

describe('sequenceOrder — parseChainKey', () => {
  it('splits a series alias into base + subseries letter', () => {
    expect(parseChainKey('FE-6131e')).toEqual({ base: 'FE-6131', suffix: 'e' })
    expect(parseChainKey('BE-0001a')).toEqual({ base: 'BE-0001', suffix: 'a' })
  })

  it('returns null for a suffix-less alias or empty input', () => {
    expect(parseChainKey('FE-6131')).toBeNull()
    expect(parseChainKey('')).toBeNull()
    expect(parseChainKey(null)).toBeNull()
    expect(parseChainKey('FOO')).toBeNull()
  })
})

describe('sequenceOrder — computeChains / isChainLocked', () => {
  const rows = [
    { project_id: 'a', taxonomy_alias: 'BE-0001a' },
    { project_id: 'b', taxonomy_alias: 'BE-0001b' },
    { project_id: 'c', taxonomy_alias: 'BE-0001c' },
    { project_id: 'solo', taxonomy_alias: 'FE-0009' },
    { project_id: 'lonely', taxonomy_alias: 'API-0002a' },
  ]

  it('groups multi-member series into chains, ordered by suffix', () => {
    const chains = computeChains(rows)
    expect(chains.has('BE-0001')).toBe(true)
    expect(chains.get('BE-0001')).toEqual(['a', 'b', 'c'])
    expect(chains.has('API-0002')).toBe(false)
    expect(chains.has('FE-0009')).toBe(false)
  })

  it('marks chain members as locked, free rows as unlocked', () => {
    const chains = computeChains(rows)
    expect(isChainLocked({ taxonomy_alias: 'BE-0001b' }, chains)).toBe(true)
    expect(isChainLocked({ taxonomy_alias: 'FE-0009' }, chains)).toBe(false)
    expect(isChainLocked({ taxonomy_alias: 'API-0002a' }, chains)).toBe(false)
  })
})

describe('sequenceOrder — orderByRoadmap', () => {
  it('orders rows by roadmap sort_order, roadmap-absent rows last (stable)', () => {
    const rows = [
      { project_id: 'x' },
      { project_id: 'y' },
      { project_id: 'z' },
      { project_id: 'w' },
    ]
    const orderMap = new Map([
      ['w', 0],
      ['x', 1],
      ['y', 2],
    ])
    const ordered = orderByRoadmap(rows, orderMap).map((r) => r.project_id)
    expect(ordered).toEqual(['w', 'x', 'y', 'z'])
  })
})

describe('sequenceOrder — normalizeChainOrder (dependency-locked ordering)', () => {
  const rows = [
    { project_id: 'a', taxonomy_alias: 'BE-0001a' },
    { project_id: 'b', taxonomy_alias: 'BE-0001b' },
    { project_id: 'free', taxonomy_alias: 'FE-0009' },
  ]

  it('keeps a chain contiguous and in suffix order even when scrambled', () => {
    const chains = computeChains(rows)
    const scrambled = [
      { project_id: 'b', taxonomy_alias: 'BE-0001b' },
      { project_id: 'free', taxonomy_alias: 'FE-0009' },
      { project_id: 'a', taxonomy_alias: 'BE-0001a' },
    ]
    const normalized = normalizeChainOrder(scrambled, chains).map((r) => r.project_id)
    expect(normalized).toEqual(['a', 'b', 'free'])
  })

  it('lets free items reorder while the chain stays put', () => {
    const chains = computeChains(rows)
    const moved = [
      { project_id: 'free', taxonomy_alias: 'FE-0009' },
      { project_id: 'a', taxonomy_alias: 'BE-0001a' },
      { project_id: 'b', taxonomy_alias: 'BE-0001b' },
    ]
    const normalized = normalizeChainOrder(moved, chains).map((r) => r.project_id)
    expect(normalized).toEqual(['free', 'a', 'b'])
  })

  it('is a no-op when there are no chains', () => {
    const noChainRows = [
      { project_id: '1', taxonomy_alias: 'FE-0001' },
      { project_id: '2', taxonomy_alias: 'BE-0002' },
    ]
    const chains = computeChains(noChainRows)
    expect(normalizeChainOrder(noChainRows, chains).map((r) => r.project_id)).toEqual(['1', '2'])
  })
})
