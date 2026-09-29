/**
 * fe9679_staging_on_board.spec.ts — FE-9679
 *
 * A project is staged from the Jobs board's Staging side: the card shows
 * description, mission and crew; Stage with no mode refuses visibly; pick a
 * mode and Stage; the orchestrator stages it over the real MCP endpoint (what
 * a pasted prompt would do); the card reaches Staged with the mission and a
 * crew tile; Play moves it to the Implementation side.
 *
 * Needs the local CE stack (backend :7272, frontend :7274) and TEST_USER /
 * TEST_PASSWORD. Chromium only: Stage copies to the clipboard.
 *
 * Written in a cloud session without the stack; the EM runs it live before
 * merge.
 *
 * Edition scope: Both.
 */
import { test, expect, Page } from '@playwright/test'
import { loginAsDefaultTestUser, openBoardCardsDetailed, createTestProject, deleteTestProject, reportRateLimiting, authHeaders, McpClient } from './helpers'

const API = 'http://localhost:7272'

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

test.describe('Staging on the Jobs board', () => {
  let projectId = ''
  let projectName = ''

  test.beforeEach(async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'Stage copies to the clipboard; chromium grants that permission')
    reportRateLimiting(page)
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await openBoardCardsDetailed(page)
    await loginAsDefaultTestUser(page)
    projectName = `E2E staging side ${Date.now()}`
    projectId = await createTestProject(page, {
      name: projectName,
      description: 'Staging on the board: description, mission and crew before Play.',
    })
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

  test('stage from the Staging side, with the mode gate, then Play to Implementation', async ({ page }) => {
    await page.goto('/jobs-overview')

    // The activated project waits on the Staging side.
    const stagingSide = page.locator('[data-testid="jobs-side-staging"]')
    await expect(stagingSide).toBeVisible()
    if ((await stagingSide.getAttribute('aria-pressed')) !== 'true') await stagingSide.click()
    const card = page.locator('[data-testid="jobs-board-card-wrap"]').filter({ hasText: projectName })
    await expect(card).toBeVisible()
    // FE-9682: one-line rows under the stat strip.
    await expect(card.locator('[data-testid="jb-row-description"]')).toContainText('description, mission and crew')
    await expect(card.locator('[data-testid="jb-row-mission"]')).toContainText('No mission yet')
    await expect(card.locator('[data-testid="jb-stat-mode"]')).toContainText('not picked')

    // The mode gate: Stage with nothing picked refuses, visibly, and sends nothing.
    const footer = card.locator('[data-testid="jb-footer"]')
    await expect(footer).toHaveAttribute('data-footer-state', 'ready')
    await expect(card.locator('[data-testid="jbf-stage"]')).toBeEnabled()
    await card.locator('[data-testid="jbf-stage"]').click()
    await expect(card.locator('[data-testid="jbf-mode-refusal"]')).toContainText('Pick a mode before staging')
    await expect(footer).toHaveAttribute('data-footer-state', 'ready')

    // Pick a mode: the refusal clears; Stage copies the staging prompt.
    await card.locator('[data-testid="radio-subagent"]').click()
    await expect(card.locator('[data-testid="jbf-mode-refusal"]')).toHaveCount(0)
    await card.locator('[data-testid="jbf-stage"]').click()
    await expect(card.locator('[data-testid="jbf-stage"]')).toHaveText('Unstage')

    // The orchestrator stages the project (what a pasted prompt would do).
    const workerName = await resolveWorkerAgentName(page, projectId)
    test.skip(!workerName, "The test user's product has no agents switched on; enable one under Tools > Agents.")
    const headers = await authHeaders(page)
    const keyRes = await page.request.post(`${API}/api/auth/api-keys`, { headers, data: { name: `e2e-staging-${Date.now()}` } })
    expect(keyRes.ok()).toBeTruthy()
    const { api_key: apiKey, id: keyId } = await keyRes.json()
    const orchRes = await page.request.get(`${API}/api/v1/projects/${projectId}/orchestrator`, { headers })
    const orchJobId = (await orchRes.json()).orchestrator.job_id

    const mcp = new McpClient(page.request, apiKey)
    await mcp.init()
    await mcp.tool('get_job_mission', { job_id: orchJobId })
    await mcp.tool('update_project_mission', { project_id: projectId, mission: 'E2E: the mission the board shows on its card.' })
    await mcp.tool('spawn_job', {
      project_id: projectId,
      agent_name: workerName,
      agent_display_name: workerName,
      mission: 'E2E worker mission on the staging side.',
    })
    await mcp.tool('complete_job', { job_id: orchJobId, result: { summary: 'staged by e2e', artifacts: [], commits: [] } })
    await page.request.delete(`${API}/api/auth/api-keys/${keyId}`, { headers })

    // Staged: mission written, crew chosen, mode is now a fact, one Play.
    await expect(footer).toHaveAttribute('data-footer-state', 'staged', { timeout: 15000 })
    await expect(card.locator('[data-testid="jb-row-mission"]')).toContainText('Written')
    await expect(card.locator('[data-testid="jb-row-mission"]')).toContainText('the mission the board shows')
    await expect(card.locator('[data-testid="jb-crew-chip"]')).toHaveCount(2)
    // FE-9682: the one Details drawer holds the full mission with its tag and the crew rows.
    await card.locator('[data-testid="jb-details-btn"]').click()
    await expect(card.locator('[data-testid="jb-mission-tag"]')).toContainText('Orchestrator generated')
    await expect(card.locator('[data-testid="jb-crew-row"]')).toHaveCount(2)
    await expect(card.locator('[data-testid="jb-crew-edit"]')).toHaveCount(1)
    await card.locator('[data-testid="jb-details-btn"]').click()
    await expect(card.locator('[data-testid="jb-stat-mode"]')).toContainText('Subagent')
    await card.locator('[data-testid="jbf-implement"]').click()

    // Play stamped the gate: the project is now on the Implementation side.
    await expect(card).toHaveCount(0, { timeout: 15000 })
    await page.locator('[data-testid="jobs-side-implementation"]').click()
    const running = page.locator('[data-testid="jobs-board-card-wrap"]').filter({ hasText: projectName })
    await expect(running).toBeVisible()
    await expect(running.locator('[data-testid="jb-footer"]')).toHaveAttribute('data-footer-state', 'implementing', { timeout: 15000 })
    await expect(running.locator('[data-testid="jb-agent-row"]')).toHaveCount(2)
  })
})
