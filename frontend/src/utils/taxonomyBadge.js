import {
  DEFAULT_PROJECT_TYPE_COLOR,
  HND_TYPE_COLOR,
  RESERVED_HANDOVER_TYPE_ABBR,
  RESERVED_TASK_TYPE_ABBR,
  TSK_TYPE_COLOR,
} from './constants'

export function taxonomyBadgeStyle(color) {
  const resolved = color || DEFAULT_PROJECT_TYPE_COLOR
  return {
    backgroundColor: `${resolved}26`,
    color: resolved,
  }
}

export function isReservedTaskAlias(alias) {
  return typeof alias === 'string' && /^TSK(?=[-\d])/.test(alias)
}

export function isReservedHandoverAlias(alias) {
  return typeof alias === 'string' && /^HND(?=[-\d])/.test(alias)
}

export function resolveTaxonomyColor({ abbreviation, alias, color } = {}) {
  if (abbreviation === RESERVED_TASK_TYPE_ABBR || isReservedTaskAlias(alias)) {
    return TSK_TYPE_COLOR
  }
  if (abbreviation === RESERVED_HANDOVER_TYPE_ABBR || isReservedHandoverAlias(alias)) {
    return HND_TYPE_COLOR
  }
  return color || DEFAULT_PROJECT_TYPE_COLOR
}

export function isHandoverRow(row) {
  if (!row) return false
  return row.task_type?.abbreviation === RESERVED_HANDOVER_TYPE_ABBR || isReservedHandoverAlias(row.taxonomy_alias)
}

export { DEFAULT_PROJECT_TYPE_COLOR }
