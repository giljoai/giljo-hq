import { DEFAULT_PROJECT_TYPE_COLOR, RESERVED_TASK_TYPE_ABBR, TSK_TYPE_COLOR } from './constants'

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

export function resolveTaxonomyColor({ abbreviation, alias, color } = {}) {
  if (abbreviation === RESERVED_TASK_TYPE_ABBR || isReservedTaskAlias(alias)) {
    return TSK_TYPE_COLOR
  }
  return color || DEFAULT_PROJECT_TYPE_COLOR
}

export { DEFAULT_PROJECT_TYPE_COLOR }
