/**
 * templateTableConfig.js — FE-9385c
 *
 * Column, role and status configuration for the agent-template table.
 * Extracted from TemplateManager.vue so the table's shape is editable without
 * opening the container — this is the file the per-product Agents redesign
 * edits when it adds a column.
 *
 * Pure data + pure sort comparators. No Vue, no API, no state.
 *
 * Edition scope: CE
 */

// FE-9203: Export Status column sort — needs-export first (stale or never
// exported), then exported (oldest export first), then user-managed dismissals,
// system-managed rows last. Uses the real export signals on the API payload
// (may_be_stale, last_exported_at, user_managed_export).
const exportStatusRank = (t) => {
  if (t._system) return 3
  if (t.user_managed_export) return 2
  if (t.may_be_stale || !t.last_exported_at) return 0
  return 1
}

const sortExportStatus = (a, b) =>
  exportStatusRank(a) - exportStatusRank(b) ||
  new Date(a.last_exported_at || 0) - new Date(b.last_exported_at || 0)

// FE-9385c: the Updated column is a STATE column, not a date field.
//
// The signal was already in the data and being thrown away. `updated_at` has an
// onupdate and NO default, so it is NULL until the agent is genuinely edited --
// but the UI fell back to `created_at`, which is why every stock agent showed the
// same seed timestamp and nothing distinguished one you had tuned from one you
// had never touched.
//
// Three states, and the exact timestamp is always available on hover:
//   updated_at set        -> the real date        ("you tuned this")
//   never edited, brand new -> "Added today"      ("this is waiting for you")
//   never edited          -> "Never edited"       ("stock, untouched")
//
// Each state is a SINGLE fact about the row. "Added today" was briefly specified
// as a composite -- created today AND switched on nowhere -- but the second half
// needed cross-product membership that is not in scope, and a single fact is the
// better rule regardless: it cannot disagree with itself, and it is true of an
// agent you added today whether or not you have switched it on yet.
export const templateUpdatedState = (template, { now = new Date() } = {}) => {
  if (template?._system) return { kind: 'system', label: '—', exact: null }

  if (template?.updated_at) {
    return { kind: 'edited', label: null, exact: template.updated_at }
  }

  if (isSameCalendarDay(template?.created_at, now)) {
    return { kind: 'added-today', label: 'Added today', exact: template.created_at }
  }

  return { kind: 'never-edited', label: 'Never edited', exact: template?.created_at || null }
}

const isSameCalendarDay = (value, now) => {
  if (!value) return false
  const then = new Date(value)
  if (Number.isNaN(then.getTime())) return false
  return (
    then.getFullYear() === now.getFullYear() &&
    then.getMonth() === now.getMonth() &&
    then.getDate() === now.getDate()
  )
}

// Newest-first on this column must float a brand-new agent to the top, and a new
// agent has no `updated_at` at all. Sorting the raw column would bury exactly the
// rows the column exists to surface, so the comparator sorts on last activity --
// the edit if there was one, the creation otherwise. That is what makes "new
// agents rise on their own" true without a badge or a special-case rule.
const lastActivityAt = (t) => new Date(t?.updated_at || t?.created_at || 0).getTime()

export const sortUpdatedState = (a, b) => lastActivityAt(a) - lastActivityAt(b)

// Table configuration
export const TEMPLATE_TABLE_HEADERS = [
  { title: 'Agent Name', key: 'name', align: 'start' },
  { title: 'Role', key: 'role', align: 'start' },
  { title: 'Active here', key: 'is_active', align: 'center' }, // BE-9394: per-PRODUCT, not tenant-wide
  { title: 'Export Status', key: 'export_status', align: 'center', sortRaw: sortExportStatus },
  { title: 'Updated', key: 'updated_at', align: 'start', sortRaw: sortUpdatedState },
  { title: 'Actions', key: 'actions', sortable: false, width: '4%', align: 'center' },
]

// Default ordering for the table: last activity, newest first.
export const TEMPLATE_TABLE_DEFAULT_SORT = [{ key: 'updated_at', order: 'desc' }]

export const TEMPLATE_ROLE_OPTIONS = [
  'analyzer',
  'designer',
  'frontend',
  'backend',
  'implementer',
  'tester',
  'reviewer',
  'documenter',
]

// FE-9203: agent templates have exactly two lifecycle states — is_active
// true/false. There is no archived/draft state on the model; do not add
// options here that the API cannot satisfy.
export const TEMPLATE_STATUS_OPTIONS = [
  { title: 'Active', value: 'active' },
  { title: 'Inactive', value: 'inactive' },
]
