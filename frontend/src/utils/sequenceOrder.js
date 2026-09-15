
export const MAX_SEQUENCE_PROJECTS = 5

export const SEQUENCE_EXECUTION_MODES = [
  { value: 'multi_terminal', label: 'Multi-terminal (interactive)' },
  { value: 'subagent', label: 'Subagent (orchestrator-managed)' },
]

export const DEFAULT_EXECUTION_MODE = 'multi_terminal'

export function parseChainKey(alias) {
  if (!alias || typeof alias !== 'string') return null
  const m = alias.trim().match(/^(.*[0-9])([a-z])$/)
  if (!m) return null
  return { base: m[1], suffix: m[2] }
}

export function computeChains(rows) {
  const groups = new Map()
  for (const r of rows || []) {
    const key = parseChainKey(r.taxonomy_alias)
    if (!key) continue
    if (!groups.has(key.base)) groups.set(key.base, [])
    groups.get(key.base).push({ id: r.project_id, suffix: key.suffix })
  }
  const chains = new Map()
  for (const [base, members] of groups) {
    if (members.length < 2) continue
    members.sort((a, b) => (a.suffix < b.suffix ? -1 : a.suffix > b.suffix ? 1 : 0))
    chains.set(
      base,
      members.map((m) => m.id),
    )
  }
  return chains
}

export function isChainLocked(row, chains) {
  const key = parseChainKey(row?.taxonomy_alias)
  return !!(key && chains && chains.has(key.base))
}

export function orderByRoadmap(rows, orderMap) {
  const map = orderMap || new Map()
  return (rows || [])
    .map((row, i) => ({
      row,
      rank: map.has(row.project_id) ? map.get(row.project_id) : Number.MAX_SAFE_INTEGER,
      i,
    }))
    .sort((a, b) => a.rank - b.rank || a.i - b.i)
    .map((w) => w.row)
}

export function normalizeChainOrder(rows, chains) {
  if (!chains || chains.size === 0) return [...(rows || [])]
  const byId = new Map((rows || []).map((r) => [r.project_id, r]))
  const emitted = new Set()
  const result = []
  for (const r of rows || []) {
    const key = parseChainKey(r.taxonomy_alias)
    if (key && chains.has(key.base)) {
      if (emitted.has(key.base)) continue
      for (const id of chains.get(key.base)) {
        if (byId.has(id)) result.push(byId.get(id))
      }
      emitted.add(key.base)
    } else {
      result.push(r)
    }
  }
  return result
}
