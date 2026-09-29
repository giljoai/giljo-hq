/**
 * chain_finished_notice.spec.ts — FE-9665
 *
 * FE-9655d moved the chain layer from the project page to one group on the
 * Jobs board and, in doing so, silently killed the "Chain finished" bell
 * notice: it used to fire from a watch on the retired `?run=` cockpit view,
 * which no longer opens (useChainContext derives the run from the board's
 * own pools instead). This drives a chain to a GENUINE purge -- the SAME
 * condition the retired cockpit watched for -- and asserts the restored
 * notice lands in the bell.
 *
 * A genuine purge (the sequence_runs row actually DELETED, not merely
 * flipped to a terminal status) only happens at the conductor's own
 * finish-line complete_job, once every member project is truly terminal
 * (project_helpers.complete_chain_run_if_finished). Deactivate/Stop do NOT
 * purge -- they cancel (the row survives), which correctly does NOT raise
 * this notice (pinned by sequenceRunStore.fe9665.spec.js's second case). So
 * this spec drives the REAL headless finish line over MCP: link two
 * projects, close each one out with no_code_changes (the real per-member
 * closeout writer, BE-6198, which flips project_statuses on the run and
 * broadcasts sequence:updated), then complete the conductor's own job twice
 * -- once to clear staging (BE-6177's gateless self-stamp), once for the
 * real finale, which is what triggers the purge.
 *
 * Needs the local CE stack (backend :7272) and TEST_USER / TEST_PASSWORD.
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

test.describe('Chain finished bell notice (FE-9665)', () => {
  let projectIds: string[] = []
  let runId = ''

  test.beforeEach(async ({ page }) => {
    reportRateLimiting(page)
    await openBoardCardsDetailed(page)
    await loginAsDefaultTestUser(page)
    const stamp = Date.now()
    projectIds = [
      await createTestProject(page, { name: `E2E chain finished first ${stamp}` }),
      await createTestProject(page, { name: `E2E chain finished second ${stamp}` }),
    ]
  })

  test.afterEach(async ({ page }) => {
    const headers = await authHeaders(page).catch(() => null)
    if (headers && runId) {
      // Best-effort: if the run wasn't purged (test failed mid-way), deactivate
      // it so it doesn't linger. A genuinely purged run 404s here -- fine.
      await page.request.post(`${API}/api/v1/sequence-runs/${runId}/deactivate`, { headers }).catch(() => undefined)
    }
    for (const id of projectIds) {
      await deleteTestProject(page, id).catch(() => undefined)
    }
    runId = ''
  })

  test('the conductor finish-line purge raises the Chain finished bell row', async ({ page }) => {
    const headers = await authHeaders(page)

    const keyRes = await page.request.post(`${API}/api/auth/api-keys`, {
      headers,
      data: { name: `e2e-chain-finished-${Date.now()}` },
    })
    expect(keyRes.ok()).toBeTruthy()
    const { api_key: apiKey, id: keyId } = await keyRes.json()
    const mcp = new McpClient(page.request, apiKey)
    await mcp.init()

    // Link a two-project chain, subagent mode (no clipboard flow needed --
    // this spec never touches Stage/Implement, only the finish line).
    const linked = await mcp.tool('link_projects', { project_ids: projectIds, execution_mode: 'subagent' })
    expect(linked.success, JSON.stringify(linked)).toBe(true)
    runId = linked.run_id
    const conductorJobId: string = linked.conductor_job_id
    expect(conductorJobId, JSON.stringify(linked)).toBeTruthy()

    // Open the board so it hydrates and the store actually tracks this run
    // (runsById) BEFORE the purge -- handleSequenceUpdated's board-purge
    // branch only fires a notice for a run the board already knew about.
    await page.goto('/jobs-overview')
    // A fresh pending run sits on Staging, but the board's own landing rule
    // (FE-9679: Implementation when anything runs tenant-wide, else Staging)
    // lands on Implementation whenever the shared dev tenant has unrelated
    // in-flight work -- pick the side explicitly rather than assume the
    // landing default matches where this test's own run is.
    await page.locator('[data-testid="jobs-side-staging"]').click()
    const group = page.locator(`[data-testid="chain-group"][data-run-id="${runId}"]`)
    await expect(group).toBeVisible()

    // The bell starts with no "Chain finished" row.
    const bell = page.getByRole('button', { name: 'View notifications' })
    await bell.click()
    const dropdown = page.locator('.notification-dropdown')
    await expect(dropdown).toBeVisible()
    await expect(dropdown.getByText('Chain finished')).toHaveCount(0)
    await bell.click() // close

    // Conductor staging-end: the gateless self-stamp (BE-6177) that marks the
    // conductor no longer "staging" so its NEXT complete_job is read as the
    // real finish line, not a premature mid-drive call.
    const stagingEnd = await mcp.tool('complete_job', {
      job_id: conductorJobId,
      result: { summary: 'e2e: conductor staging complete' },
    })
    expect(stagingEnd.success !== false, JSON.stringify(stagingEnd)).toBeTruthy()

    // Close out each member for real (BE-6198's per-member writer): flips
    // this member's status to completed on both the project row and the
    // run's project_statuses map, and broadcasts sequence:updated as it goes.
    for (const projectId of projectIds) {
      const closeout = await mcp.tool('write_project_closeout', {
        project_id: projectId,
        summary: 'e2e: closed for the chain-finished-notice spec',
        key_outcomes: ['e2e closeout'],
        decisions_made: ['e2e: no real code change, closed to drive the chain to its finish line'],
        no_code_changes: 'e2e chain-finished-notice spec -- no product code touched by this member',
      })
      expect(closeout.success !== false, JSON.stringify(closeout)).toBeTruthy()
    }

    // The conductor's OWN finish-line complete_job: every member is now
    // terminal, so the C1 guard passes and complete_chain_run_if_finished
    // PURGES the run (project_helpers.py) -- the genuine "gone", not merely
    // cancelled, condition this whole notice exists to catch.
    const finale = await mcp.tool('complete_job', {
      job_id: conductorJobId,
      result: { summary: 'e2e: chain finished, all members terminal' },
    })
    expect(finale.success !== false, JSON.stringify(finale)).toBeTruthy()
    await page.request.delete(`${API}/api/auth/api-keys/${keyId}`, { headers })
    runId = '' // purged; afterEach's own deactivate call would 404

    await expect(group).toHaveCount(0, { timeout: 15000 })
    await bell.click()
    await expect(dropdown.getByText('Chain finished')).toBeVisible({ timeout: 15000 })
    await expect(dropdown.getByText('This chain has finished; its record was retired.')).toBeVisible()
  })
})
