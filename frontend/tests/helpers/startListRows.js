/**
 * The six-row answer of GET /api/onboarding/start-list (the FE-0072c contract),
 * built from the facts a test cares about. Everything else is "not yet".
 */
export function startListPayload(over = {}) {
  const rows = {
    tool_connected: { done: false, live: false, tool_name: null },
    skills_installed: { done: false },
    product_exists: { done: false, product_name: null },
    project_created: { done: false, project_id: null, project_name: null },
    project_staged: { done: false, has_project: false, mode: null },
    project_built: { done: false, in_progress: false },
  }
  for (const [key, value] of Object.entries(over)) rows[key] = { ...rows[key], ...value }
  const done_count = Object.values(rows).filter((r) => r.done).length
  return { rows, done_count, step_count: 6 }
}

export const ALL_DONE = startListPayload({
  tool_connected: { done: true, live: true, tool_name: 'Claude Code' },
  skills_installed: { done: true },
  product_exists: { done: true, product_name: 'Recipe Box' },
  project_created: { done: true, project_id: 'p-1', project_name: 'Add a search box' },
  project_staged: { done: true, has_project: true, mode: 'subagent' },
  project_built: { done: true, in_progress: false },
})
