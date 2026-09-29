/**
 * jobs_board_control_row.spec.ts — FE-9655c
 *
 * A project is run from its Jobs board card: pick a mode and Stage, let the
 * orchestrator finish staging (driven here over the real MCP endpoint, the way
 * an agent would), Implement from the card, then open an agent's assigned job
 * from the row's kebab.
 *
 * Needs the local CE stack (backend :7272, frontend :7274) and TEST_USER /
 * TEST_PASSWORD. Chromium only: the Stage button copies to the clipboard.
 *
 * Edition scope: Both.
 */
import { test, expect, Page } from '@playwright/test'
import { loginAsDefaultTestUser, openBoardCardsDetailed, createTestProject, deleteTestProject, reportRateLimiting, authHeaders, McpClient } from './helpers'

const API = 'http://localhost:7272'

/**
 * The worker agent this project may spawn: the first agent the project's own
 * product has switched on (the spawn allowlist is product-scoped, and template
 * names are unique per tenant, so a hardcoded name breaks on real tenants).
 */
async function resolveWorkerAgentName(page: Page, projectId: string): Promise<string | null> {
  const headers = await authHeaders(page)
  const project = await (await page.request.get(`${API}/api/v1/projects/${projectId}`, { headers })).json()
  const res = await page.request.get(`${API}/api/v1/products/${project.product_id}/agent-assignments`, { headers })
  if (!res.ok()) throw new Error(`agent-assignments read failed: ${res.status()}`)
  const { assignments } = await res.json()
  const usable = (assignments || []).filter(
    (a: { is_active: boolean; template_is_active?: boolean | null; template_name?: string | null }) =>
      a.is_active && a.template_is_active !== false && a.template_name && a.template_name !== 'orchestrator',
  )
  return usable.length ? usable[0].template_name : null
}

test.describe('Jobs board control row', () => {
  let projectId = ''
  let projectName = ''

  test.beforeEach(async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'Stage copies to the clipboard; chromium grants that permission')
    reportRateLimiting(page)
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await openBoardCardsDetailed(page)
    await loginAsDefaultTestUser(page)
    projectName = `E2E board row ${Date.now()}`
    projectId = await createTestProject(page, { name: projectName })
    const activate = await page.request.post(`${API}/api/v1/projects/${projectId}/activate`, {
      headers: await authHeaders(page),
      data: { force: false },
    })
    expect(activate.ok()).toBeTruthy()
  })

  test.afterEach(async ({ page }) => {
    if (!projectId) return
    try {
      await deleteTestProject(page, projectId)
    } catch {
      // Session gone or already removed.
    }
  })

  test('stage, implement, and open an agent job from the board', async ({ page }) => {
    await page.goto('/jobs-overview')
    // FE-9679: the board has two sides and lands on Implementation when anything
    // runs on this tenant; a freshly activated project waits on Staging.
    await page.locator('[data-testid="jobs-side-staging"]').click()
    const card = page.locator('[data-testid="jobs-board-card-wrap"]').filter({ hasText: projectName })
    await expect(card).toBeVisible()

    // Ready: pick a mode on the card, then Stage.
    const footer = card.locator('[data-testid="jb-footer"]')
    await expect(footer).toHaveAttribute('data-footer-state', 'ready')
    await card.locator('[data-testid="radio-multi-terminal"]').click()
    await expect(card.locator('[data-testid="jbf-stage"]')).toBeEnabled()
    await card.locator('[data-testid="jbf-stage"]').click()
    await expect(card.locator('[data-testid="jbf-stage"]')).toHaveText('Unstage')

    // The orchestrator stages the project (what a pasted prompt would do).
    const workerName = await resolveWorkerAgentName(page, projectId)
    test.skip(!workerName, "The test user's product has no agents switched on; enable one under Tools > Agents.")
    const headers = await authHeaders(page)
    const keyRes = await page.request.post(`${API}/api/auth/api-keys`, { headers, data: { name: `e2e-board-${Date.now()}` } })
    expect(keyRes.ok()).toBeTruthy()
    const { api_key: apiKey, id: keyId } = await keyRes.json()
    const orchRes = await page.request.get(`${API}/api/v1/projects/${projectId}/orchestrator`, { headers })
    const orchJobId = (await orchRes.json()).orchestrator.job_id

    const mcp = new McpClient(page.request, apiKey)
    await mcp.init()
    await mcp.tool('get_job_mission', { job_id: orchJobId })
    await mcp.tool('update_project_mission', { project_id: projectId, mission: 'E2E: implement the board row.' })
    await mcp.tool('spawn_job', {
      project_id: projectId,
      agent_name: workerName,
      agent_display_name: workerName,
      mission: 'E2E worker mission: open me from the board.',
    })
    await mcp.tool('complete_job', { job_id: orchJobId, result: { summary: 'staged by e2e', artifacts: [], commits: [] } })
    await page.request.delete(`${API}/api/auth/api-keys/${keyId}`, { headers })

    // Staged: the card carries its own Implement.
    await expect(footer).toHaveAttribute('data-footer-state', 'staged', { timeout: 15000 })
    await expect(card.locator('[data-testid="jbf-mode-tag"]')).toContainText('Multi-Terminal')
    await card.locator('[data-testid="jbf-implement"]').click()

    // Implementing: the card moved to the Implementation side; rows are live;
    // open the worker's job from its kebab.
    await page.locator('[data-testid="jobs-side-implementation"]').click()
    await expect(footer).toHaveAttribute('data-footer-state', 'implementing', { timeout: 15000 })
    const rows = card.locator('[data-testid="jb-agent-row"]')
    await expect(rows).toHaveCount(2)
    await card.getByRole('button', { name: `Actions for ${workerName}` }).click()
    await page.locator('[data-testid="jb-agent-menu-job"]').click()
    await expect(page.getByText('E2E worker mission: open me from the board.')).toBeVisible()
  })
})
