
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

const lastActivityAt = (t) => new Date(t?.updated_at || t?.created_at || 0).getTime()

export const sortUpdatedState = (a, b) => lastActivityAt(a) - lastActivityAt(b)

export const templateRowActive = (template) =>
  template?._system === true || (template?.product_active ?? false) === true

export const sortRowActive = (a, b) => Number(templateRowActive(a)) - Number(templateRowActive(b))

export const templateOwningProductName = (template, productsById) =>
  (template?.product_id && productsById?.[template.product_id]?.name) || 'Unknown product'

export const sortByProductName = (productsById) => (a, b) =>
  templateOwningProductName(a, productsById).localeCompare(
    templateOwningProductName(b, productsById),
  )

export const TEMPLATE_TABLE_HEADERS = [
  { title: 'Agent Name', key: 'name', align: 'start' },
  { title: 'Role', key: 'role', align: 'start' },
  { title: 'Active here', key: 'is_active', align: 'center', sortRaw: sortRowActive },
  { title: 'Updated', key: 'updated_at', align: 'start', sortRaw: sortUpdatedState },
  { title: 'Actions', key: 'actions', sortable: false, width: '4%', align: 'center' },
]

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

export const TEMPLATE_STATUS_OPTIONS = [
  { title: 'Active', value: 'active' },
  { title: 'Inactive', value: 'inactive' },
]

export const templateTableHeaders = ({ showAllProducts = false, productsById = {} } = {}) => {
  if (!showAllProducts) return TEMPLATE_TABLE_HEADERS
  const [name, ...rest] = TEMPLATE_TABLE_HEADERS
  return [
    name,
    {
      title: 'Product',
      key: 'product_id',
      align: 'start',
      sortRaw: sortByProductName(productsById),
    },
    ...rest,
  ]
}
