/**
 * fe9689_board_updates_live.spec.ts — FE-9689
 *
 * The Jobs board is alive: when an agent changes state from outside the page
 * (here over the real MCP endpoint, as an agent would), the card updates with
 * NO page reload. A marker set on window before the change must survive, which
 * proves the page was not reloaded.
 *
 * Needs the local CE stack (backend :7272, frontend :7274) and TEST_USER /
 * TEST_PASSWORD. Chromium only: the Stage button copies to the clipboard.
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

test.describe('Jobs board updates live (FE-9689)', () => {
  let projectId = ''
  let projectName = ''

  test.beforeEach(async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'Stage copies to the clipboard; chromium grants that permission')
    reportRateLimiting(page)
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await openBoardCardsDetailed(page)
    await loginAsDefaultTestUser(page)
    projectName = `E2E live board ${Date.now()}`
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

  test('an agent that starts working and then blocks shows on the card without a reload', async ({ page }) => {
    await page.goto('/jobs-overview')
    await page.locator('[data-testid="jobs-side-staging"]').click()
    const card = page.locator('[data-testid="jobs-board-card-wrap"]').filter({ hasText: projectName })
    await expect(card).toBeVisible()
    await card.locator('[data-testid="radio-multi-terminal"]').click()
    await card.locator('[data-testid="jbf-stage"]').click()
    await expect(card.locator('[data-testid="jbf-stage"]')).toHaveText('Unstage')

    const workerName = await resolveWorkerAgentName(page, projectId)
    test.skip(!workerName, "The test user's product has no agents switched on; enable one under Tools > Agents.")
    const headers = await authHeaders(page)
    const keyRes = await page.request.post(`${API}/api/auth/api-keys`, { headers, data: { name: `e2e-live-board-${Date.now()}` } })
    expect(keyRes.ok()).toBeTruthy()
    const { api_key: apiKey, id: keyId } = await keyRes.json()
    const orchJobId = (await (await page.request.get(`${API}/api/v1/projects/${projectId}/orchestrator`, { headers })).json())
      .orchestrator.job_id

    const mcp = new McpClient(page.request, apiKey)
    await mcp.init()
    await mcp.tool('get_job_mission', { job_id: orchJobId })
    await mcp.tool('update_project_mission', { project_id: projectId, mission: 'E2E: the board follows along.' })
    const spawned = await mcp.tool('spawn_job', {
      project_id: projectId,
      agent_name: workerName,
      agent_display_name: workerName,
      mission: 'E2E worker mission: change state while the board watches.',
    })
    await mcp.tool('complete_job', { job_id: orchJobId, result: { summary: 'staged by e2e', artifacts: [], commits: [] } })

    const footer = card.locator('[data-testid="jb-footer"]')
    await expect(footer).toHaveAttribute('data-footer-state', 'staged', { timeout: 15000 })
    await card.locator('[data-testid="jbf-implement"]').click()
    await page.locator('[data-testid="jobs-side-implementation"]').click()
    await expect(footer).toHaveAttribute('data-footer-state', 'implementing', { timeout: 15000 })
    const workerStatus = card.locator('[data-testid="jb-agent-row"]').nth(1).locator('[data-testid="jb-agent-status"]')
    await expect(workerStatus).toHaveText('Waiting.')

    // From here on, nothing on the page is touched. Mark the page so a reload would show.
    await page.evaluate(() => {
      ;(window as unknown as { __fe9689: string }).__fe9689 = 'same-page'
    })

    await mcp.tool('get_job_mission', { job_id: spawned.job_id })
    await expect(workerStatus).toHaveText('Working...', { timeout: 10000 })

    await mcp.tool('set_agent_status', { job_id: spawned.job_id, status: 'blocked', reason: 'Needs a deploy key' })
    await expect(workerStatus).toHaveText('Needs Input', { timeout: 10000 })
    await expect(card.locator('[data-testid="jb-lifecycle-pill"]')).toHaveText('Needs Input', { timeout: 10000 })
    await page.request.delete(`${API}/api/auth/api-keys/${keyId}`, { headers })

    const marker = await page.evaluate(() => (window as unknown as { __fe9689?: string }).__fe9689)
    expect(marker, 'the page was not reloaded').toBe('same-page')
  })
})
