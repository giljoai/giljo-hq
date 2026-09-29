/**
 * fe9684_live_activity_board.spec.ts — FE-9684
 *
 * On a running Jobs board card, a working agent moves: its badge breathes,
 * its status word ends in blinking dots, and the Implementing pill glows.
 * An agent that is not working stays still. The animation is read from the
 * browser's computed style, so a class that exists but whose CSS never
 * loaded fails here.
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

function animationName(page: Page, selector: string) {
  return page.locator(selector).first().evaluate((el) => getComputedStyle(el).animationName)
}

test.describe('Jobs board live activity (FE-9684)', () => {
  let projectId = ''
  let projectName = ''

  test.beforeEach(async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'Stage copies to the clipboard; chromium grants that permission')
    reportRateLimiting(page)
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await openBoardCardsDetailed(page)
    await loginAsDefaultTestUser(page)
    projectName = `E2E live activity ${Date.now()}`
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

  test('a working agent breathes and ends in dots; the others stay still', async ({ page }) => {
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
    const keyRes = await page.request.post(`${API}/api/auth/api-keys`, { headers, data: { name: `e2e-live-${Date.now()}` } })
    expect(keyRes.ok()).toBeTruthy()
    const { api_key: apiKey, id: keyId } = await keyRes.json()
    const orchJobId = (await (await page.request.get(`${API}/api/v1/projects/${projectId}/orchestrator`, { headers })).json())
      .orchestrator.job_id

    const mcp = new McpClient(page.request, apiKey)
    await mcp.init()
    await mcp.tool('get_job_mission', { job_id: orchJobId })
    await mcp.tool('update_project_mission', { project_id: projectId, mission: 'E2E: watch the worker move.' })
    const spawned = await mcp.tool('spawn_job', {
      project_id: projectId,
      agent_name: workerName,
      agent_display_name: workerName,
      mission: 'E2E worker mission: be seen working.',
    })
    await mcp.tool('complete_job', { job_id: orchJobId, result: { summary: 'staged by e2e', artifacts: [], commits: [] } })

    const footer = card.locator('[data-testid="jb-footer"]')
    await expect(footer).toHaveAttribute('data-footer-state', 'staged', { timeout: 15000 })
    await card.locator('[data-testid="jbf-implement"]').click()
    await page.locator('[data-testid="jobs-side-implementation"]').click()
    await expect(footer).toHaveAttribute('data-footer-state', 'implementing', { timeout: 15000 })

    // The worker picks up its job: the server moves it to working.
    await mcp.tool('get_job_mission', { job_id: spawned.job_id })
    await page.request.delete(`${API}/api/auth/api-keys/${keyId}`, { headers })

    const workerRow = card.locator('[data-testid="jb-agent-row"]').filter({ has: page.locator('.live-badge') })
    await expect(workerRow).toHaveCount(1, { timeout: 15000 })
    await expect(workerRow.locator('[data-testid="jb-agent-status"]')).toHaveText('Working...')
    await expect(card.locator('[data-testid="jb-agent-row"] .live-badge')).toHaveCount(1)

    const pill = card.locator('[data-testid="jb-status-pill"]')
    await expect(pill).toHaveText('Implementing...')
    await expect(pill).toHaveClass(/live-pill/)

    // The global stylesheet really animates them.
    const scope = `[data-testid="jobs-board-card-wrap"]:has-text("${projectName}")`
    expect(await animationName(page, `${scope} .live-badge`)).toBe('live-badge-breathe')
    expect(await animationName(page, `${scope} .live-pill`)).toBe('live-pill-glow')
    expect(await animationName(page, `${scope} .live-dot`)).toBe('live-dot-blink')

    if (process.env.FE9684_SHOT) await card.screenshot({ path: process.env.FE9684_SHOT })
  })
})
