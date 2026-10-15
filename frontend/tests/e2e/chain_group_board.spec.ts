/**
 * chain_group_board.spec.ts — FE-9655d
 *
 * A chain is one group on the Jobs board. Link two projects over MCP (the way
 * an agent would), open the board, Stage the chain from its control area, let the
 * conductor write the chain goal, Implement from its control area, and watch the group
 * advance to step 2 when the first member finishes. The run-record writes that
 * stand in for the conductor go through the same REST writer the dashboard uses.
 *
 * No agents are spawned here, so no agent name is involved.
 *
 * Needs the local CE stack (backend :7272, frontend :7274) and TEST_USER /
 * TEST_PASSWORD. Chromium only: Stage chain copies to the clipboard.
 *
 * Edition scope: Both.
 */
import { test, expect } from '@playwright/test'
import {
  loginAsDefaultTestUser, openBoardCardsDetailed,
  createTestProject,
  deleteTestProject,
  reportRateLimiting,
  authHeaders,
  McpClient,
} from './helpers'

const API = 'http://localhost:7272'

test.describe('Jobs board chain group', () => {
  let projectIds: string[] = []
  let runId = ''

  test.beforeEach(async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'Stage chain copies to the clipboard; chromium grants that permission')
    reportRateLimiting(page)
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await openBoardCardsDetailed(page)
    await loginAsDefaultTestUser(page)
    const stamp = Date.now()
    projectIds = [
      await createTestProject(page, { name: `E2E chain first ${stamp}` }),
      await createTestProject(page, { name: `E2E chain second ${stamp}` }),
    ]
  })

  test.afterEach(async ({ page }) => {
    const headers = await authHeaders(page).catch(() => null)
    if (headers && runId) {
      await page.request.post(`${API}/api/v1/sequence-runs/${runId}/stop`, { headers }).catch(() => undefined)
    }
    for (const id of projectIds) {
      await deleteTestProject(page, id).catch(() => undefined)
    }
    runId = ''
  })

  test('link, stage, implement, and see the group advance', async ({ page }) => {
    const headers = await authHeaders(page)

    // Link the two projects over MCP, the headless door.
    const keyRes = await page.request.post(`${API}/api/auth/api-keys`, { headers, data: { name: `e2e-chain-${Date.now()}` } })
    expect(keyRes.ok()).toBeTruthy()
    const { api_key: apiKey, id: keyId } = await keyRes.json()
    const mcp = new McpClient(page.request, apiKey)
    await mcp.init()
    const linked = await mcp.tool('link_projects', { project_ids: projectIds, execution_mode: 'multi_terminal' })
    await page.request.delete(`${API}/api/auth/api-keys/${keyId}`, { headers })
    expect(linked.success, JSON.stringify(linked)).toBe(true)
    runId = linked.run_id

    // An old chain link lands on the board with this chain's group highlighted,
    // on the side that holds it (Staging, before the chain runs).
    await page.goto(`/projects/${projectIds[0]}?run=${runId}`)
    await expect(page).toHaveURL(new RegExp(`/jobs-overview\\?run=${runId}`))
    await expect(page.locator('[data-testid="jobs-side-staging"]')).toHaveAttribute('aria-pressed', 'true')
    const group = page.locator(`[data-testid="chain-group"][data-run-id="${runId}"]`)
    await expect(group).toBeVisible()
    await expect(group).toHaveClass(/cg--highlight/)
    await expect(group.locator('[data-testid="chain-group-counter"]')).toHaveText('Step 1 of 2')
    const members = group.locator('[data-testid="chain-group-member"]')
    await expect(members).toHaveCount(2)
    await expect(members.nth(0)).toHaveAttribute('data-project-id', projectIds[0])
    await expect(members.nth(0)).toHaveAttribute('data-member-state', 'current')
    await expect(members.nth(1)).toHaveAttribute('data-member-state', 'waiting')
    // The member cards carry no staging buttons of their own.
    await expect(group.locator('[data-testid="jbf-stage"]')).toHaveCount(0)

    // FE-9749: the chain's controls sit in the shared control area at the bottom;
    // the header carries information only.
    const runAs = group.locator('[data-testid="chain-group-run-as"]')
    await expect(group.locator('[data-testid="sca-label"]')).toHaveText('Select execution mode')
    await expect(runAs.locator('[data-testid="radio-multi-terminal"]')).toHaveAttribute('aria-pressed', 'true')
    await expect(group.locator('[data-testid="chain-group-header"] [data-testid="stage-chain-btn"]')).toHaveCount(0)

    // Stage the chain from its control area.
    await group.locator('[data-testid="stage-chain-btn"]').click()
    await expect(group.locator('[data-testid="stage-chain-btn"]')).toHaveText('Unstage chain')
    await expect(group.locator('[data-testid="chain-group-mode-tag"]')).toContainText('Multi-terminal')

    // The conductor writes the chain goal while staging.
    const goal = await page.request.patch(`${API}/api/v1/sequence-runs/${runId}`, {
      headers,
      data: { chain_mission: '# Chain mission: E2E two steps\n\nBuild first, then second.' },
    })
    expect(goal.ok()).toBeTruthy()
    await expect(group.locator('[data-testid="chain-group-name"]')).toHaveText('E2E two steps')
    await expect(group.locator('[data-testid="chain-mission-window"]')).toContainText('Build first, then second.')

    // Implement: the single start for the whole chain. The board stays put; the
    // running chain now sits on the Implementation side (FE-9679).
    await expect(group.locator('[data-testid="implement-chain-btn"]')).toBeEnabled()
    await group.locator('[data-testid="implement-chain-btn"]').click()
    await page.locator('[data-testid="jobs-side-implementation"]').click()
    await expect(group.locator('[data-testid="stop-chain-btn"]')).toBeVisible({ timeout: 15000 })
    await expect(page).toHaveURL(/\/jobs-overview/)

    // The first member finishes; its closeout advances the run on the server
    // (written directly here).
    const advance = await page.request.patch(`${API}/api/v1/sequence-runs/${runId}`, {
      headers,
      data: {
        current_index: 1,
        project_statuses: { [projectIds[0]]: 'completed', [projectIds[1]]: 'implementing' },
      },
    })
    expect(advance.ok()).toBeTruthy()
    await expect(group.locator('[data-testid="chain-group-counter"]')).toHaveText('Step 2 of 2', { timeout: 15000 })
    await expect(members.nth(0)).toHaveAttribute('data-member-state', 'done')
    await expect(members.nth(1)).toHaveAttribute('data-member-state', 'current')
    await expect(group.locator(`[data-testid="chain-member-review-${projectIds[0]}"]`)).toBeVisible()
  })
})
