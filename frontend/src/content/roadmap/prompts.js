/**
 * Roadmap copy-prompts — the text the Roadmap page's copy buttons hand a user
 * to paste into their own agent (ruling 19: the UI prepares prompts, it never
 * executes). Frontend-authored on purpose: unlike the staging/implementation
 * prompts there is no server-side generator for this one, so this file is the
 * ONLY copy and BE-9504a's no-duplication rule is satisfied by that fact.
 *
 * Extracted from RoadmapView.vue (FE-9564) when the view hit its shrink-only
 * size budget. Sibling of content/onboarding/prompts.js, which does the same
 * job for the tutorial.
 *
 * Every tool name here must be one the server actually registers — the guard
 * is tests/unit/test_fe9564_frontend_prompt_tool_names.py.
 *
 * Edition Scope: CE
 */

// FE-9564: the prompt names the product's UUID wherever the page knows it.
// Both roadmap tools take an optional product_id and BOTH misbehave without it
// on a tenant that owns more than one product: get_roadmap silently falls back
// to whatever product is currently DEFAULT (roadmap_service resolves it with
// write=false), and save_roadmap hard-refuses with PRODUCT_AMBIGUOUS
// (write=true). The page is looking at one specific product, so telling the
// agent which one is the difference between the prompt working and the user
// pasting a five-step instruction that fails on the last step. Falls back to
// the name-only wording when no product is given.
export function buildRoadmapPrompt(mode, product, host = '') {
  const name = product?.name || 'the viewed product'
  const productId = product?.id || ''
  // Written inline rather than through a helper so every tool NAME stays a
  // bare literal in the sentence -- that is what the FE-9564 guard reads.
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
