/**
 * fe9670d_play_stamps_before_prompt.spec.ts — FE-9670d
 *
 * A solo project's one Play (the Implement control) must stamp the
 * implementation gate through its one writer, PATCH launch-implementation,
 * BEFORE the implementation prompt is fetched. The prompt route reads that
 * stamp, so the order is load-bearing; this watches it on the wire.
 *
 * Self-contained: beforeEach creates a throwaway solo multi_terminal project,
 * stages it (GET the staging prompt), and ends staging over MCP the way an
 * orchestrator does (complete_job on its own job), so Implement is enabled.
 * afterEach deletes the project.
 *
 * Edition scope: Both.
 */
import { test, expect } from '@playwright/test'
import {
  loginAsDefaultTestUser,
  createTestProject,
  deleteTestProject,
  reportRateLimiting,
  authHeaders,
  McpClient,
} from './helpers'

const API = 'http://localhost:7272'

test.describe('Play stamps the gate before the prompt (FE-9670d)', () => {
  let projectId = ''

  test.beforeEach(async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'Play copies to the clipboard; chromium grants that permission')
    reportRateLimiting(page)
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await loginAsDefaultTestUser(page)
    projectId = await createTestProject(page, { name: `E2E fe9670d play ${Date.now()}` })
    const headers = await authHeaders(page)

    const mode = await page.request.patch(`${API}/api/v1/projects/${projectId}`, {
      headers,
      data: { execution_mode: 'multi_terminal' },
    })
    expect(mode.ok(), `set execution_mode: ${mode.status()}`).toBeTruthy()

    const staging = await page.request.get(`${API}/api/v1/prompts/staging/${projectId}`, { headers })
    expect(staging.ok(), `staging prompt: ${staging.status()}`).toBeTruthy()

    // End staging the way the orchestrator does, so the project is staging_complete.
    const orch = await page.request.get(`${API}/api/v1/projects/${projectId}/orchestrator`, { headers })
    expect(orch.ok(), `orchestrator: ${orch.status()}`).toBeTruthy()
    const orchJobId = (await orch.json())?.orchestrator?.job_id
    expect(orchJobId, 'orchestrator job id').toBeTruthy()
    // Spawn from whatever implementer template this DB has, not one seed name.
    // spawn_job validates against the PROJECT's product crew, so list that product's templates.
    const projRes = await page.request.get(`${API}/api/v1/projects/${projectId}`, { headers })
    expect(projRes.ok(), `project: ${projRes.status()}`).toBeTruthy()
    const productId = (await projRes.json()).product_id
    expect(productId, 'project product_id').toBeTruthy()
    const tplRes = await page.request.get(`${API}/api/v1/templates/`, { headers, params: { product_id: productId } })
    expect(tplRes.ok(), `templates: ${tplRes.status()}`).toBeTruthy()
    const tplBody = await tplRes.json()
    const templates: Array<{ name?: string }> = Array.isArray(tplBody) ? tplBody : tplBody.templates ?? []
    const implementerName =
      templates.find((t) => t.name === 'implementer')?.name ??
      templates.find((t) => t.name?.startsWith('implementer'))?.name
    expect(implementerName, 'an implementer* agent template').toBeTruthy()
    const keyRes = await page.request.post(`${API}/api/auth/api-keys`, { headers, data: { name: `e2e-fe9670d-${Date.now()}` } })
    expect(keyRes.ok()).toBeTruthy()
    const { api_key: apiKey, id: keyId } = await keyRes.json()
    try {
      const mcp = new McpClient(page.request, apiKey)
      await mcp.init()
      // A real orchestrator writes the mission while staging; the page only
      // commits the execution mode (and so enables Implement) once one exists.
      await mcp.tool('update_project_mission', { project_id: projectId, mission: '# E2E fe9670d\n\nThrowaway mission.' })
      // Staging cannot end without at least one spawned specialist.
      const spawned = await mcp.tool('spawn_job', {
        project_id: projectId,
        agent_name: implementerName,
        agent_display_name: 'implementer',
        mission: 'e2e throwaway',
      })
      expect(spawned.job_id, JSON.stringify(spawned)).toBeTruthy()
      const done = await mcp.tool('complete_job', { job_id: orchJobId, result: { summary: 'E2E staging end' } })
      expect(done.status, JSON.stringify(done)).toBe('success')
    } finally {
      await page.request.delete(`${API}/api/auth/api-keys/${keyId}`, { headers })
    }
  })

  test.afterEach(async ({ page }) => {
    if (projectId) await deleteTestProject(page, projectId).catch(() => undefined)
    projectId = ''
  })

  test('PATCH launch-implementation goes on the wire before the prompt fetch', async ({ page }) => {
    const wire: string[] = []
    page.on('request', (req) => {
      const url = req.url()
      if (url.includes(`/api/agent-jobs/projects/${projectId}/launch-implementation`)) {
        wire.push(`${req.method()} launch-implementation`)
      } else if (url.includes(`/api/v1/prompts/implementation/${projectId}`)) {
        wire.push(`${req.method()} prompt`)
      }
    })

    await page.goto(`/projects/${projectId}`)
    await page.waitForLoadState('networkidle')

    const play = page.locator('[data-testid="launch-jobs-btn"]')
    await expect(play).toBeEnabled()
    const promptResponse = page.waitForResponse((r) => r.url().includes(`/api/v1/prompts/implementation/${projectId}`))
    await play.click()
    await promptResponse

    expect(wire.slice(0, 2)).toEqual(['PATCH launch-implementation', 'GET prompt'])
  })
})
