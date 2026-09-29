
export const OTHER_PRODUCT_ID = '__other__'
export const OTHER_PRODUCT_NAME = 'Other product'

function activityOf(project) {
  const stamps = [project?.implementation_launched_at, project?.updated_at, project?.completed_at, project?.created_at]
  let latest = 0
  for (const stamp of stamps) {
    const t = stamp ? Date.parse(stamp) : NaN
    if (Number.isFinite(t) && t > latest) latest = t
  }
  return latest
}

export function groupBoardByProduct({ projects = [], chainMembers = [], runs = [], membersOf, productsById = {}, sideOf, sideOfRun, side }) {
  const groups = new Map()
  const memberProduct = new Map(chainMembers.map((project) => [project.id, project.product_id]))

  function groupFor(productId) {
    const id = productId && productsById[productId] ? productId : OTHER_PRODUCT_ID
    if (!groups.has(id)) {
      groups.set(id, {
        id,
        name: id === OTHER_PRODUCT_ID ? OTHER_PRODUCT_NAME : productsById[id].name || OTHER_PRODUCT_NAME,
        projects: [],
        runIds: [],
        counts: { staging: 0, implementation: 0 },
        quiet: false,
        lastActivity: 0,
      })
    }
    return groups.get(id)
  }

  for (const project of projects) {
    const group = groupFor(project.product_id)
    const projectSide = sideOf(project)
    group.counts[projectSide]++
    group.lastActivity = Math.max(group.lastActivity, activityOf(project))
    if (projectSide === side) group.projects.push(project)
  }

  for (const run of runs) {
    const members = membersOf(run) || []
    const productId = members.map((id) => memberProduct.get(id)).find(Boolean) || null
    const group = groupFor(productId)
    const runSide = sideOfRun(run)
    group.counts[runSide]++
    for (const id of members) {
      const member = chainMembers.find((project) => project.id === id)
      if (member) group.lastActivity = Math.max(group.lastActivity, activityOf(member))
    }
    if (runSide === side) group.runIds.push(run.id)
  }

  return [...groups.values()]
    .map((group) => ({ ...group, quiet: group.projects.length === 0 && group.runIds.length === 0 }))
    .sort((a, b) => b.lastActivity - a.lastActivity || a.name.localeCompare(b.name))
}
