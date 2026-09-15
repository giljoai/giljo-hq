
export function buildRoadmapPrompt(mode, product, host = '') {
  const name = product?.name || 'the viewed product'
  const productId = product?.id || ''
  const scope = productId ? `product_id="${productId}"` : ''
  const scoped = scope ? `(${scope})` : ''
  const target = `the GiljoAI product "${name}"${host ? ` (host: ${host})` : ''}`
  if (mode === 'create') {
    return [
      `Build a product roadmap for ${target}.`,
      '',
      `1. Call get_roadmap${scoped} first to confirm you are connected to the account/product shown above`,
      "   (it will be empty for a first build). Then read this product's INACTIVE projects",
      '   (list_projects) and PENDING tasks (list_tasks).',
      '2. Rank them by ENGINEERING BUILD-LOGIC: foundations / database / shared infrastructure first,',
      '   then dependents in the order they must be built. Break ties by lower risk / faster unblock.',
      '3. For each item assign a risk (low|med|high) and complexity (light|med|heavy).',
      '4. Flag any item that cannot start until something else lands — a dependency or gate, often',
      '   noted in its description. Set blocked: true and put the dependency in blocked_reason',
      '   (e.g. "needs the auth gate from BE-6077 first"). Leave blocked false for ready items.',
      `5. Save the roadmap by calling the save_roadmap MCP tool with${scope ? ` ${scope} and` : ''}`,
      '   items: [{item_type: "project"|"task", project_id OR task_id, sort_order, risk, complexity,',
      '   blocked, blocked_reason}] plus an optional one-line summary.',
      '',
      'Make sure you are connected to the account/product shown above before saving.',
    ].join('\n')
  }
  return [
    `Re-rank the roadmap for ${target}.`,
    '',
    `1. Read the current roadmap (get_roadmap${scoped}) plus this product's INACTIVE projects (list_projects)`,
    '   and PENDING tasks (list_tasks) to catch anything newly added or finished.',
    '2. Re-rank by ENGINEERING BUILD-LOGIC: foundations / database / shared infrastructure first, then',
    '   dependents in build order. Break ties by lower risk / faster unblock.',
    '3. Refresh each item\'s risk (low|med|high) and complexity (light|med|heavy).',
    '4. Re-check what is blocked: set blocked: true with a blocked_reason for any item still waiting',
    '   on a dependency or gate (often noted in its description); clear blocked once it is unblocked.',
    `5. Save by calling save_roadmap with${scope ? ` ${scope} and` : ''}`,
    '   items: [{item_type: "project"|"task", project_id OR task_id, sort_order, risk, complexity,',
    '   blocked, blocked_reason}] plus an optional one-line summary.',
    '',
    'Make sure you are connected to the account/product shown above before saving.',
  ].join('\n')
}
